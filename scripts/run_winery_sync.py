#!/usr/bin/env python3
"""
Safer winery event sync.
- reviews only allowlisted winery senders/domains
- deduplicates by message id
- reads full messages for headers/body
- rejects promo-only noise
- records richer skip reasons
- falls back to OCR/vision hints for image-heavy emails
- refuses to create events without real title/date
- checks calendar for duplicates before create

Usage:
  python3 scripts/run_winery_sync.py --account user@gmail.com --calendar-id CAL --days 5 [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")

DEFAULT_DATA_DIR = Path(
    os.environ.get("WINERY_DATA_DIR")
    or (Path.home() / ".openclaw" / "workspace" / "data")
)
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = SCRIPT_DIR.parent / "data" / "multi-event-catalog.json"

STATE_PATH = Path(os.environ.get("WINERY_STATE_PATH") or (DEFAULT_DATA_DIR / "winery-sync-seen.json"))
ALLOWLIST_PATH = Path(os.environ.get("WINERY_ALLOWLIST_PATH") or (DEFAULT_DATA_DIR / "winery-allowlist.json"))
STATUS_PATH = Path(os.environ.get("WINERY_STATUS_PATH") or (DEFAULT_DATA_DIR / "winery-allowlist-status.json"))
CATALOG_PATH = Path(os.environ.get("WINERY_CATALOG_PATH") or DEFAULT_CATALOG_PATH)
NOISE_SUBJECT_TERMS = [
    "receipt",
    "invoice",
    "order confirmed",
    "thank you for your wine order",
    "shipping",
    "save up to",
    "final hours",
    "use code",
    "% off",
    "offer ends",
    "flash sale",
    "mystery packs",
    "allocation",
    "library wines release",
    "new releases",
    "introducing the",
    "pinot noir",
    "chardonnay",
    "pinot gris",
    "experience the reimagined",
    "vineyard experiences reimagined",
    "what's happening in downtown camas",
    "the new releases are here",
    "this is how we rhône",
    "pinot blanc oregon",
    "save more when you take more",
    "limited access",
    "2025 pinot",
    "2023 ambar estate",
    "aurora allocation",
]
NOISE_BODY_TERMS = [
    "discount",
    "coupon",
    "sale",
    "savings",
    "% off",
    "shipping included",
    "now in stock",
]
EVENT_TERMS = [
    "tasting",
    "dinner",
    "pickup",
    "pick-up",
    "release party",
    "release weekend",
    "member event",
    "club event",
    "harvest",
    "open house",
    "winemaker dinner",
    "barrel tasting",
    "picnic day",
    "reserve your spot",
    "invitation:",
    "spring events",
    "what's happening",
]
MONTH_MAP = {m: i for i, m in enumerate([
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
], 1)}
MONTH_ABBR = {m[:3]: i for m, i in MONTH_MAP.items()}


@dataclass
class Candidate:
    message_id: str
    subject: str
    sender: str
    start: str
    end: str
    description: str
    location: str = ""
    rsvp_url: str = ""
    extraction_mode: str = "text"


def build_candidate(message_id: str, subject: str, sender: str, dt: datetime, end_dt: datetime, body: str, extraction_mode: str, location: str = "", rsvp_url: str = "") -> Candidate:
    description_parts = [
        f"Source: {sender or 'Unknown sender'}",
        f"Email subject: {subject}",
        f"Message ID: {message_id}",
        f"Extraction mode: {extraction_mode}",
    ]
    if location:
        description_parts.append(f"Location: {location}")
    if rsvp_url:
        description_parts.append(f"RSVP: {rsvp_url}")
    return Candidate(
        message_id=message_id,
        subject=subject,
        sender=sender or "Unknown sender",
        start=dt.isoformat(),
        end=end_dt.isoformat(),
        description="\n".join(description_parts),
        location=location,
        rsvp_url=rsvp_url,
        extraction_mode=extraction_mode,
    )


SUBPROCESS_TIMEOUT_SECONDS = 120


def run(cmd: list[str], timeout: float = SUBPROCESS_TIMEOUT_SECONDS) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        sys.stderr.write(
            f"[winery-sync] subprocess timeout after {timeout}s: {' '.join(cmd[:3])}...\n"
        )
        if exc.stderr:
            sys.stderr.write(exc.stderr.decode("utf-8", "replace"))
        raise SystemExit(124) from exc
    if p.returncode != 0:
        sys.stderr.write(
            f"[winery-sync] subprocess failed rc={p.returncode}: {' '.join(cmd[:3])}...\n"
        )
        sys.stderr.write(p.stderr.decode("utf-8", "replace"))
        raise SystemExit(p.returncode)
    return p.stdout.decode("utf-8", "replace")


def log_progress(message: str) -> None:
    print(f"[winery-sync] {message}", file=sys.stderr, flush=True)


def collect_search_results(account: str, query: str, max_results: int, found: dict[str, dict]) -> None:
    log_progress(f"search {query}")
    out = run(["gog", "gmail", "messages", "search", query, "--max", str(max_results), "--account", account, "--json"])
    data = json.loads(out)
    if isinstance(data, dict):
        items = data.get("messages") or data.get("items") or data.get("results") or []
    else:
        items = data
    for item in items:
        mid = item.get("id") or item.get("messageId") or item.get("message_id")
        if mid:
            found[mid] = item


def search_messages(account: str, days: int, max_results: int, allow_senders: set[str], allow_domains: set[str]) -> list[dict]:
    found: dict[str, dict] = {}

    sender_domains = {s.split('@', 1)[1] for s in allow_senders if '@' in s}
    domain_queries = sorted(set(allow_domains) | sender_domains)

    for domain in domain_queries:
        query = f"from:{domain} newer_than:{days}d"
        collect_search_results(account, query, max_results, found)

    return list(found.values())


def get_message(account: str, message_id: str) -> str:
    return run(["gog", "gmail", "get", message_id, "--account", account])


def extract_header(raw: str, name: str) -> str:
    m = re.search(rf"(?:^|\n){re.escape(name)}:\s*(.+)", raw, re.I)
    if m:
        return unescape(m.group(1).strip())
    m = re.search(rf"\b{name.lower()}\s+(.+?)(?=\s+(?:date|to|cc|bcc|subject|unsubscribe|label_ids|thread_id)\b|$)", raw, re.I | re.S)
    return unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


def parse_sender_email(sender: str) -> str:
    m = re.search(r"<([^>]+)>", sender or "")
    email = (m.group(1) if m else (sender or "")).strip().lower()
    return email if "@" in email else ""


def parse_sender_domain(sender: str) -> str:
    email = parse_sender_email(sender)
    return email.split("@", 1)[1] if "@" in email else ""


class AllowlistError(RuntimeError):
    pass


def load_allowlist() -> tuple[set[str], set[str], dict]:
    if not ALLOWLIST_PATH.exists():
        raise AllowlistError(f"allowlist file not found: {ALLOWLIST_PATH}")
    try:
        data = json.loads(ALLOWLIST_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise AllowlistError(f"failed to read/parse allowlist {ALLOWLIST_PATH}: {exc}") from exc
    senders = {str(v).strip().lower() for v in data.get("senders", []) if str(v).strip()}
    domains = {str(v).strip().lower() for v in data.get("domains", []) if str(v).strip()}
    if not senders and not domains:
        raise AllowlistError(
            f"allowlist {ALLOWLIST_PATH} has no senders or domains; refusing to run empty scan"
        )
    return senders, domains, data


def sender_is_allowlisted(sender: str, allow_senders: set[str], allow_domains: set[str]) -> bool:
    email = parse_sender_email(sender)
    domain = parse_sender_domain(sender)
    return (email in allow_senders) or (domain in allow_domains)


def looks_like_noise(subject: str, body: str) -> bool:
    subject_l = subject.lower()
    text = f"{subject}\n{body}".lower()
    if any(term in subject_l for term in NOISE_SUBJECT_TERMS):
        return True
    if any(term in text for term in NOISE_BODY_TERMS):
        return True
    return False


def looks_like_event(subject: str, body: str) -> bool:
    subject_l = subject.lower()
    body_l = body.lower()
    text = f"{subject_l}\n{body_l}"

    strong_subject_signals = [
        "invitation:",
        "pick-up party",
        "pickup party",
        "reserve your spot",
        "release & picnic day",
        "release party",
        "summer bbq",
        "spring events",
        "open house",
    ]
    if any(term in subject_l for term in strong_subject_signals):
        return True

    strong_body_signals = [
        "reserve your spot",
        "join us",
        "rsvp",
        "tickets",
        "ticket link",
        "save the date",
        "club pick-up party",
        "pickup party",
        "tasting room event",
        "member event",
        "at our winery",
        "event details",
        "hosted at",
    ]
    return any(term in text for term in EVENT_TERMS) and any(term in text for term in strong_body_signals)


def strip_html_to_text(raw: str) -> str:
    text = raw
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_image_alt_text(raw: str) -> str:
    bits = []
    for alt in re.findall(r'alt=["\']([^"\']{4,300})["\']', raw, re.I):
        bits.append(unescape(alt))
    for title in re.findall(r'title=["\']([^"\']{4,300})["\']', raw, re.I):
        bits.append(unescape(title))
    return "\n".join(bits)


def maybe_extract_visual_fallback(subject: str, raw: str, sender_email: str = "", sender_domain: str = "") -> tuple[str | None, str | None]:
    html_title_match = re.search(r"<title>(.*?)</title>", raw, re.I | re.S)
    html_title = re.sub(r"\s+", " ", unescape(html_title_match.group(1))).strip() if html_title_match else ""
    alt_text = extract_image_alt_text(raw)

    fallback_parts = [part for part in [html_title, alt_text] if part]
    fallback = "\n".join(fallback_parts).strip()
    if not fallback:
        return None, None
    image_heavy = len(strip_html_to_text(raw)) < 1200 or bool(re.search(r"<img\b", raw, re.I))
    if not image_heavy:
        return None, None
    return fallback, "html-title-alt"


_CATALOG_CACHE: dict | None = None


def load_multi_event_catalog() -> dict:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    if not CATALOG_PATH.exists():
        _CATALOG_CACHE = {"entries": []}
        return _CATALOG_CACHE
    try:
        data = json.loads(CATALOG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log_progress(f"WARN: could not load catalog {CATALOG_PATH}: {exc}")
        _CATALOG_CACHE = {"entries": []}
        return _CATALOG_CACHE
    _CATALOG_CACHE = data
    return _CATALOG_CACHE


def _parse_catalog_datetime(value: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


def parse_catalog_multi_events(subject: str, raw: str, sender_email: str, sender_domain: str, sender: str, message_id: str) -> list[Candidate]:
    catalog = load_multi_event_catalog()
    entries = catalog.get("entries", [])
    if not entries:
        return []
    title_match = re.search(r"<title>(.*?)</title>", raw, re.I | re.S)
    html_title = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip().lower() if title_match else ""
    tz_name = catalog.get("timezone") or "America/Los_Angeles"
    tz = ZoneInfo(tz_name)

    sender_email_l = (sender_email or "").lower()
    sender_domain_l = (sender_domain or "").lower()

    for entry in entries:
        entry_domain = (entry.get("sender_domain") or "").lower()
        entry_email = (entry.get("sender_email") or "").lower()
        if entry_domain and entry_domain != sender_domain_l and not sender_email_l.endswith(f"@{entry_domain}"):
            continue
        if entry_email and entry_email != sender_email_l:
            continue
        title_needle = (entry.get("html_title_match") or "").lower()
        if title_needle and title_needle not in html_title:
            continue
        mode = entry.get("extraction_mode") or "catalog-image-fallback"
        candidates = []
        for item in entry.get("events", []):
            try:
                start_dt = _parse_catalog_datetime(item["start"], tz)
                end_dt = _parse_catalog_datetime(item["end"], tz)
            except (KeyError, ValueError) as exc:
                log_progress(f"WARN: bad catalog entry for {entry_domain}: {exc}")
                continue
            candidates.append(
                build_candidate(
                    message_id,
                    item["subject"],
                    sender,
                    start_dt,
                    end_dt,
                    raw,
                    mode,
                    item.get("location", ""),
                    item.get("rsvp_url", ""),
                )
            )
        if candidates:
            return candidates
    return []


PAST_DATE_GRACE_DAYS = 7


def parse_date(body: str) -> datetime | None:
    pat = re.compile(r"\b(" + "|".join(list(MONTH_MAP.keys()) + list(MONTH_ABBR.keys())) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?", re.I)
    now = datetime.now(TZ)
    stale_cutoff = now - timedelta(days=PAST_DATE_GRACE_DAYS)
    for m in pat.finditer(body.lower()):
        mon = m.group(1).lower()
        month = MONTH_MAP.get(mon, MONTH_ABBR.get(mon[:3]))
        day = int(m.group(2))
        year_explicit = m.group(3) is not None
        year = int(m.group(3)) if year_explicit else now.year
        try:
            base = datetime(year, month, day, 18, 0, tzinfo=TZ)
        except ValueError:
            continue
        if not year_explicit and base < stale_cutoff:
            try:
                base = base.replace(year=year + 1)
            except ValueError:
                continue

        time_patterns = [
            r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\s*(?:-|to|–|—)\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b",
            r"@\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)\s*(?:-|to|–|—)\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)",
        ]
        for tp in time_patterns:
            tm = re.search(tp, body, re.I)
            if tm:
                sh = int(tm.group(1)); sm = int(tm.group(2) or 0); sap = tm.group(3).lower()
                if sap == "pm" and sh != 12: sh += 12
                if sap == "am" and sh == 12: sh = 0
                return base.replace(hour=sh, minute=sm)

        tm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b", body, re.I)
        if tm:
            hour = int(tm.group(1))
            minute = int(tm.group(2) or 0)
            ap = tm.group(3).lower()
            if ap == "pm" and hour != 12:
                hour += 12
            if ap == "am" and hour == 12:
                hour = 0
            base = base.replace(hour=hour, minute=minute)
        return base
    return None


def parse_end(body: str, start: datetime) -> datetime:
    time_patterns = [
        r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\s*(?:-|to|–|—)\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b",
        r"@\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)\s*(?:-|to|–|—)\s*(\d{1,2})(?::(\d{2}))?\s?(am|pm)",
    ]
    for tp in time_patterns:
        tm = re.search(tp, body, re.I)
        if tm:
            eh = int(tm.group(4)); em = int(tm.group(5) or 0); eap = tm.group(6).lower()
            if eap == "pm" and eh != 12: eh += 12
            if eap == "am" and eh == 12: eh = 0
            return start.replace(hour=eh, minute=em)
    return start + timedelta(hours=3)


def extract_location(body: str) -> str:
    patterns = [
        r"(?:location|where)[:\s]+(.+)",
        r"hosted at\s+(.+)",
        r"at\s+([A-Z][A-Za-z0-9&'’ .-]+(?:Winery|Vineyard|Estate|Cellars|Farm|Spirits|Butchery|Hotel))",
    ]
    for pat in patterns:
        m = re.search(pat, body, re.I)
        if m:
            line = m.group(1).split("\n")[0].strip()
            line = re.sub(r"\s+", " ", line)
            if len(line) <= 140:
                return line
    return ""


def extract_rsvp_url(body: str) -> str:
    urls = [u.rstrip(').,\"\'') for u in re.findall(r"https?://\S+", body)]
    blocked = [
        "unsubscribe",
        "list-manage",
        "w3.org",
        "mailto:",
        "constantcontact",
        "subscription_center",
        "utm_",
    ]
    preferred = ["event", "events", "tickets", "rsvp", "reserve", "tock", "exploretock", "calendar"]

    cleaned = []
    for url in urls:
        low = url.lower()
        if any(term in low for term in blocked):
            continue
        cleaned.append(url)

    for url in cleaned:
        low = url.lower()
        if any(term in low for term in preferred):
            return url
    return cleaned[0] if cleaned else ""


def get_existing_events(account: str, calendar_id: str, days: int) -> list[dict]:
    start = (datetime.now(TZ) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = (datetime.now(TZ) + timedelta(days=45)).replace(hour=23, minute=59, second=0, microsecond=0).isoformat()
    log_progress(f"calendar fetch {start} to {end}")
    out = run(["gog", "calendar", "events", calendar_id, "--from", start, "--to", end, "--account", account, "--json"])
    data = json.loads(out)
    return data.get("events") or data.get("items") or data if isinstance(data, list) else []


def normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


FUZZY_DUP_RATIO = 0.82


def title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def duplicate_reason(existing: list[dict], candidate: Candidate) -> str | None:
    day = candidate.start[:10]
    subject_norm = normalized_text(candidate.subject)
    message_marker = f"Message ID: {candidate.message_id}"
    for ev in existing:
        summary = (ev.get("summary") or ev.get("title") or "")
        description = ev.get("description") or ""
        evstart = ev.get("start") or ev.get("startTime") or ev.get("from") or {}
        if isinstance(evstart, dict):
            evstart = evstart.get("dateTime") or evstart.get("date") or ""
        summary_norm = normalized_text(summary)
        if message_marker in description:
            return "message-id"
        if not evstart.startswith(day):
            continue
        if summary_norm and summary_norm == subject_norm:
            return "same-day-title"
        if title_similarity(subject_norm, summary_norm) >= FUZZY_DUP_RATIO:
            return "same-day-fuzzy-title"
    return None


def load_seen() -> dict:
    if not STATE_PATH.exists():
        return {"message_ids": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"message_ids": []}


def save_seen(seen: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(seen, indent=2))


def save_allowlist_status(status: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2))


def create_event(account: str, calendar_id: str, candidate: Candidate) -> None:
    run([
        "gog", "calendar", "create", calendar_id,
        "--summary", candidate.subject,
        "--from", candidate.start,
        "--to", candidate.end,
        "--description", candidate.description,
        "--account", account,
        "--force",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--calendar-id", required=True)
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        allow_senders, allow_domains, allowlist_meta = load_allowlist()
    except AllowlistError as exc:
        log_progress(f"ERROR: {exc}")
        raise SystemExit(2) from exc
    start_ts = time.time()
    log_progress(f"loaded allowlist senders={len(allow_senders)} domains={len(allow_domains)}")
    messages = search_messages(args.account, args.days, args.max, allow_senders, allow_domains)
    log_progress(f"discovered messages={len(messages)} elapsed={time.time()-start_ts:.1f}s")
    existing = get_existing_events(args.account, args.calendar_id, args.days)
    log_progress(f"existing calendar events={len(existing)} elapsed={time.time()-start_ts:.1f}s")
    seen = load_seen()
    seen_ids = set(seen.get("message_ids", []))

    created, duplicates, skipped = [], [], []

    for index, msg in enumerate(messages, start=1):
        message_id = msg.get("id") or msg.get("messageId") or msg.get("message_id")
        if index == 1 or index % 10 == 0:
            log_progress(f"message {index}/{len(messages)} id={message_id} elapsed={time.time()-start_ts:.1f}s")
        raw = get_message(args.account, message_id)
        subject = extract_header(raw, "subject")
        sender = extract_header(raw, "from")
        sender_email = parse_sender_email(sender)
        sender_domain = parse_sender_domain(sender)
        text_body = strip_html_to_text(raw)
        body = raw
        extraction_mode = "text"

        if message_id in seen_ids:
            duplicates.append({"message_id": message_id, "subject": subject or "", "reason": "seen-message-id"})
            continue
        if not sender_is_allowlisted(sender, allow_senders, allow_domains):
            skipped.append({
                "message_id": message_id,
                "subject": subject or "",
                "sender": sender or "",
                "sender_email": sender_email,
                "sender_domain": sender_domain,
                "reason": "sender-not-allowlisted",
            })
            continue
        if not subject or subject.lower() == "unknown subject":
            skipped.append({"message_id": message_id, "sender_email": sender_email, "reason": "missing-subject"})
            continue

        catalog_candidates = parse_catalog_multi_events(
            subject, raw, sender_email, sender_domain, sender, message_id
        )
        if catalog_candidates:
            log_progress(f"catalog-match message_id={message_id} candidates={len(catalog_candidates)}")
            for candidate in catalog_candidates:
                log_progress(f"catalog-candidate message_id={message_id} subject={candidate.subject} start={candidate.start}")
                dup_reason = duplicate_reason(existing, candidate)
                if dup_reason or candidate.message_id in seen_ids:
                    log_progress(f"catalog-duplicate message_id={message_id} subject={candidate.subject} reason={dup_reason or 'seen-message-id'}")
                    duplicates.append({**candidate.__dict__, "reason": dup_reason or "seen-message-id"})
                    continue
                if not args.dry_run:
                    create_event(args.account, args.calendar_id, candidate)
                    existing.append({
                        "summary": candidate.subject,
                        "description": candidate.description,
                        "start": {"dateTime": candidate.start},
                    })
                    seen_ids.add(candidate.message_id)
                log_progress(f"catalog-created message_id={message_id} subject={candidate.subject}")
                created.append(candidate.__dict__)
            continue

        if looks_like_noise(subject, text_body):
            skipped.append({"message_id": message_id, "subject": subject, "sender_email": sender_email, "reason": "promo-noise"})
            continue
        if not looks_like_event(subject, text_body):
            fallback_body, fallback_mode = maybe_extract_visual_fallback(subject, raw, sender_email, sender_domain)
            if fallback_body and looks_like_event(subject, fallback_body):
                body = fallback_body
                extraction_mode = fallback_mode or "ocr-fallback"
            else:
                skipped.append({
                    "message_id": message_id,
                    "subject": subject,
                    "sender_email": sender_email,
                    "reason": "no-event-signal",
                })
                continue
        else:
            body = text_body

        dt = parse_date(body)
        if not dt:
            fallback_body, fallback_mode = maybe_extract_visual_fallback(subject, raw, sender_email, sender_domain)
            if fallback_body and fallback_body != body:
                dt = parse_date(fallback_body)
                if dt:
                    body = fallback_body
                    extraction_mode = fallback_mode or "ocr-fallback"
            if not dt:
                skipped.append({
                    "message_id": message_id,
                    "subject": subject,
                    "sender_email": sender_email,
                    "reason": "missing-date",
                    "extraction_mode": extraction_mode,
                    "ocr_needed": True,
                })
                continue

        end_dt = parse_end(body, dt)
        start = dt.isoformat()
        end = end_dt.isoformat()
        location = extract_location(body)
        rsvp_url = extract_rsvp_url(body)
        candidate = build_candidate(
            message_id,
            subject,
            sender,
            dt,
            end_dt,
            body,
            extraction_mode,
            location,
            rsvp_url,
        )

        dup_reason = duplicate_reason(existing, candidate)
        if dup_reason:
            duplicates.append({**candidate.__dict__, "reason": dup_reason})
            continue

        if not args.dry_run:
            create_event(args.account, args.calendar_id, candidate)
            existing.append({
                "summary": candidate.subject,
                "description": candidate.description,
                "start": {"dateTime": candidate.start},
            })
            seen_ids.add(candidate.message_id)
        created.append(candidate.__dict__)

    result = {
        "emails_scanned": len(messages),
        "allowlisted_senders": len(allow_senders),
        "allowlisted_domains": len(allow_domains),
        "policy": allowlist_meta.get("policy", {}),
        "created": created,
        "duplicates": duplicates,
        "skipped": skipped,
        "dry_run": args.dry_run,
    }

    if not args.dry_run:
        save_seen({"message_ids": sorted(seen_ids)})

    save_allowlist_status({
        "updatedAt": datetime.now(TZ).isoformat(),
        "policy": allowlist_meta.get("policy", {}),
        "allowlistedSenders": len(allow_senders),
        "allowlistedDomains": len(allow_domains),
        "lastRunDays": args.days,
        "lastRunDryRun": args.dry_run,
        "emailsScanned": len(messages),
        "createdCount": len(created),
        "duplicateCount": len(duplicates),
        "skippedCount": len(skipped),
        "skipReasons": {
            reason: sum(1 for item in skipped if item.get("reason") == reason)
            for reason in sorted({item.get("reason") for item in skipped if item.get("reason")})
        }
    })

    log_progress(f"complete created={len(created)} duplicates={len(duplicates)} skipped={len(skipped)} elapsed={time.time()-start_ts:.1f}s")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

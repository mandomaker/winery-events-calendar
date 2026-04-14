#!/usr/bin/env python3
"""
Safer winery event sync.
- runs multiple simple Gmail searches
- deduplicates by message id
- reads full messages for headers/body
- rejects promo-only noise
- refuses to create events without real title/date
- checks calendar for duplicates before create

Usage:
  python3 scripts/run_winery_sync.py --account user@gmail.com --calendar-id CAL --days 5 [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
STATE_PATH = Path("/Users/mando/.openclaw/workspace/data/winery-sync-seen.json")
SEARCHES = [
    "winery",
    "vineyard",
    '"wine tasting"',
    '"wine dinner"',
    '"wine club"',
    '"release party"',
    '"club pickup"',
    '"member pickup"',
]
NEGATIVE_SUBJECT_TERMS = [
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


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "replace"))
        raise SystemExit(p.returncode)
    return p.stdout.decode("utf-8", "replace")


def search_messages(account: str, days: int, max_results: int) -> list[dict]:
    found: dict[str, dict] = {}
    for term in SEARCHES:
        query = f"{term} newer_than:{days}d"
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
    return list(found.values())


def get_message(account: str, message_id: str) -> str:
    return run(["gog", "gmail", "get", message_id, "--account", account])


def extract_header(raw: str, name: str) -> str:
    m = re.search(rf"(?:^|\n){re.escape(name)}:\s*(.+)", raw, re.I)
    if m:
        return m.group(1).strip()
    # fallback for gog one-line output blobs
    m = re.search(rf"\b{name.lower()}\s+(.+?)(?=\s+(?:date|to|cc|bcc|subject|unsubscribe|label_ids|thread_id)\b|$)", raw, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def looks_like_noise(subject: str, body: str) -> bool:
    subject_l = subject.lower()
    text = f"{subject}\n{body}".lower()
    if any(term in subject_l for term in NEGATIVE_SUBJECT_TERMS):
        return True
    if any(term in text for term in ["discount", "coupon", "sale", "savings", "% off", "shipping included", "now in stock"]):
        return True
    weak_marketing_subjects = [
        "experience the reimagined",
        "vineyard experiences reimagined",
        "what's happening in downtown camas",
        "the new releases are here",
        "this is how we rhône",
        "pinot blanc oregon",
        "save more when you take more",
    ]
    if any(term in subject_l for term in weak_marketing_subjects):
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


def parse_date(body: str) -> datetime | None:
    pat = re.compile(r"\b(" + "|".join(list(MONTH_MAP.keys()) + list(MONTH_ABBR.keys())) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?", re.I)
    for m in pat.finditer(body.lower()):
        mon = m.group(1).lower()
        month = MONTH_MAP.get(mon, MONTH_ABBR.get(mon[:3]))
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.now(TZ).year
        try:
            base = datetime(year, month, day, 18, 0, tzinfo=TZ)
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
                eh = int(tm.group(4)); em = int(tm.group(5) or 0); eap = tm.group(6).lower()
                if sap == "pm" and sh != 12: sh += 12
                if sap == "am" and sh == 12: sh = 0
                if eap == "pm" and eh != 12: eh += 12
                if eap == "am" and eh == 12: eh = 0
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
        r"at\s+([A-Z][A-Za-z0-9&'’ .-]+(?:Winery|Vineyard|Estate|Cellars|Farm|Spirits|Butchery))",
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
    out = run(["gog", "calendar", "events", calendar_id, "--from", start, "--to", end, "--account", account, "--json"])
    data = json.loads(out)
    return data.get("events") or data.get("items") or data if isinstance(data, list) else []


def normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


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
        if evstart.startswith(day) and summary_norm == subject_norm:
            return "same-day-title"
        if evstart.startswith(day) and subject_norm and summary_norm and (subject_norm in summary_norm or summary_norm in subject_norm):
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

    messages = search_messages(args.account, args.days, args.max)
    existing = get_existing_events(args.account, args.calendar_id, args.days)
    seen = load_seen()
    seen_ids = set(seen.get("message_ids", []))

    created, duplicates, skipped = [], [], []

    for msg in messages:
        message_id = msg.get("id") or msg.get("messageId") or msg.get("message_id")
        raw = get_message(args.account, message_id)
        subject = extract_header(raw, "subject")
        sender = extract_header(raw, "from")
        body = raw

        if message_id in seen_ids:
            duplicates.append({"message_id": message_id, "subject": subject or "", "reason": "seen-message-id"})
            continue
        if not subject or subject.lower() == "unknown subject":
            skipped.append({"message_id": message_id, "reason": "missing-subject"})
            continue
        if looks_like_noise(subject, body):
            skipped.append({"message_id": message_id, "subject": subject, "reason": "promo-noise"})
            continue
        if not looks_like_event(subject, body):
            skipped.append({"message_id": message_id, "subject": subject, "reason": "no-event-signal"})
            continue

        dt = parse_date(body)
        if not dt:
            skipped.append({"message_id": message_id, "subject": subject, "reason": "missing-date"})
            continue

        end_dt = parse_end(body, dt)
        start = dt.isoformat()
        end = end_dt.isoformat()
        location = extract_location(body)
        rsvp_url = extract_rsvp_url(body)
        description_parts = [
            f"Source: {sender or 'Unknown sender'}",
            f"Email subject: {subject}",
            f"Message ID: {message_id}",
        ]
        if location:
            description_parts.append(f"Location: {location}")
        if rsvp_url:
            description_parts.append(f"RSVP: {rsvp_url}")
        description = "\n".join(description_parts)
        candidate = Candidate(message_id=message_id, subject=subject, sender=sender or "Unknown sender", start=start, end=end, description=description, location=location, rsvp_url=rsvp_url)

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

    if not args.dry_run:
        save_seen({"message_ids": sorted(seen_ids)})

    print(json.dumps({
        "emails_scanned": len(messages),
        "created": created,
        "duplicates": duplicates,
        "skipped": skipped,
        "dry_run": args.dry_run,
    }, indent=2))


if __name__ == "__main__":
    main()

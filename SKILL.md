---
name: winery-events-calendar
description: Scan Gmail for winery and vineyard event emails (tastings, wine club pickups, release parties, dinners, harvest events, newsletters, etc.) and add them to a dedicated Google Calendar called "Winery Events". Use when the user asks to check for winery events in email, sync winery events to calendar, find upcoming winery events, or set up automated winery event detection. Requires gog CLI with Gmail and Calendar access. NOT for general email-to-calendar tasks.
---

# Winery Events Calendar

Scans Gmail for winery/vineyard event emails and adds them to a dedicated "Winery Events" Google Calendar using the `gog` CLI.

## Setup

1. Ensure `gog` is authenticated with Gmail + Calendar: `gog auth list`
2. The "Winery Events" calendar must already exist in Google Calendar. Note: `gog` cannot create calendars — only events. If the calendar doesn't exist, create it via the Google Calendar UI or API.
3. Get the calendar ID: `gog calendar calendars --account USER@gmail.com` and look for "Winery Events"
4. Save config:

```
# skills/winery-events-calendar/config.env
WINERY_CAL_ID=<calendar-id>@group.calendar.google.com
WINERY_ACCOUNT=user@gmail.com
```

## Workflow

### Step 1 — Read config

Read `config.env` from this skill directory for `WINERY_CAL_ID` and `WINERY_ACCOUNT`.

### Step 2 — Search Gmail for winery event emails

Run multiple focused searches via `gog` and deduplicate by message ID. Gmail's search doesn't handle complex nested quoted phrases well through `gog`, so use simple terms:

```bash
# Search 1: Winery/vineyard keyword search
gog gmail messages search "winery newer_than:30d" --max 30 --account USER --json

# Search 2: Vineyard keyword search
gog gmail messages search "vineyard newer_than:30d" --max 30 --account USER --json

# Search 3: Wine event terms
gog gmail messages search "wine tasting OR wine dinner OR wine club OR release party newer_than:30d" --max 30 --account USER --json
```

**Important lessons from production use:**
- Simple single-keyword searches work better than complex quoted compound queries
- Run multiple focused searches and deduplicate by message ID
- Don't rely solely on keywords — the best events come from **newsletters** (winery associations, individual wineries) and **forwards from family/friends**
- Filter out obvious non-events: receipts, shipping confirmations, sale/discount-only emails
- `gog gmail messages search` returns individual messages; `gog gmail search` returns threads

### Step 3 — Read and parse each candidate email

For each unique candidate:

```bash
gog gmail get MESSAGE_ID --account USER
```

Read the full body and extract event details:
- **Event name** (e.g. "Spring Release Tasting", "Wine Club Pickup Day")
- **Date and time** (convert to ISO 8601 with timezone, default PDT/-07:00)
- **End time** (estimate 2-3h for tastings, 3-4h for dinners if not specified)
- **Location** (winery name + full address if present)
- **Description** (brief summary + RSVP/ticket info + any special notes)

**Key parsing guidance:**
- **Newsletters are the richest source.** A single newsletter (e.g. from a winery association) may list 5-10 separate events. Create a calendar event for each one.
- **Forwarded emails** from family members often contain event info from winery mailing lists — parse the forwarded content, not just the forward wrapper.
- **Skip emails that are purely promotional** (sales, discounts, order confirmations) with no actual event dates.
- If an email mentions an event but has no parseable date, skip it and note it in the report.

### Step 4 — Check for duplicates

Before creating each event, check if something similar already exists:

```bash
gog calendar events CALENDAR_ID --from ISO_DATE_START --to ISO_DATE_END --account USER
```

Match on approximate name + same date. Skip if a match is found. Be generous with matching — "Spring Release Party" and "Arabils Spring Release Party" for the same date are the same event.

### Step 5 — Create calendar events

```bash
gog calendar create CALENDAR_ID \
  --summary "EVENT_NAME" \
  --from "ISO_START" \
  --to "ISO_END" \
  --description "DESCRIPTION" \
  --account USER \
  --force
```

Notes on `gog calendar create`:
- Use `--force` to skip confirmation prompts (required for automated runs)
- Times should include timezone offset (e.g. `2026-04-25T18:00:00-07:00`)
- Keep descriptions concise but include location, ticket/RSVP links, and source

### Step 6 — Report results

Summarize:
- Number of emails scanned
- Number of new events added (list each with name, date, and source)
- Number of duplicates skipped
- Any emails that looked promising but couldn't be parsed

## Scheduling

For daily automated runs:

```
openclaw cron add \
  --name "Winery Events Calendar Sync" \
  --cron "0 6 * * *" \
  --tz "America/Los_Angeles" \
  --session isolated \
  --message "Run winery events calendar sync. Read skill at skills/winery-events-calendar/SKILL.md and config at skills/winery-events-calendar/config.env. Search Gmail for winery/vineyard event emails from the last 30 days, check for duplicates, create new calendar events. Summarize findings." \
  --announce
```

**Use 30 days as the default lookback** — newsletters announce events weeks in advance, and 14 days misses too much. The duplicate check prevents re-adding events found in previous runs.

## Known Winery Senders (update over time)

Keep a list of known senders in `config.env` or a separate file to prioritize:

```
# Known senders (add as discovered)
# Dundee Hills Winegrowers Association <info@dundeehills.org>
# Adelsheim Vineyard <cheers@adelsheim.com>
# Walter Scott Wines (via Constant Contact)
```

## Notes

- No Python required — all searches use `gog` CLI directly
- `gog` cannot create Google Calendars, only events. Calendar must exist first.
- Always use `--force` flag when creating events in automated/cron context
- Winery newsletters often contain multiple events — parse each one separately
- Wine club pickup reminders should be treated as events
- Forwards from family/friends are valuable sources — don't skip them
- If no date is found in an email, skip it and mention it in the report

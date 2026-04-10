---
name: winery-events-calendar
description: Scan Gmail for winery and vineyard event emails (tastings, wine club pickups, release parties, dinners, harvest events, etc.) and add them to a dedicated Google Calendar called "Winery Events". Use when the user asks to check for winery events in email, sync winery events to calendar, find upcoming winery events, or set up automated winery event detection. Requires gog CLI with Gmail and Calendar access. NOT for general email-to-calendar tasks.
---

# Winery Events Calendar

Scans Gmail for winery/vineyard event emails and adds them to a dedicated "Winery Events" Google Calendar using the `gog` CLI.

## Setup (first run only)

1. Ensure `gog` is authenticated: `gog auth list`
2. Create the calendar if it doesn't exist (see references/setup.md)
3. Note the "Winery Events" calendar ID — store it for future runs

## Workflow

### Step 1 — Find the Winery Events calendar ID

```bash
gog calendar list --account USER@gmail.com
```

Look for "Winery Events" in the output. If missing, create it:

```bash
gog calendar create --summary "Winery Events" --account USER@gmail.com
```

Save the returned calendar ID for all subsequent event creation calls.

### Step 2 — Search Gmail for winery event emails

Run the search script to find relevant emails:

```bash
python3 ~/.openclaw/workspace/skills/winery-events-calendar/scripts/search_winery_emails.py --account USER@gmail.com --days 30
```

The script returns a JSON array of candidate emails with id, subject, date, snippet.

### Step 3 — Parse each email for event details

For each candidate email, read the full body and extract:
- **Event name** (e.g. "Spring Release Tasting", "Wine Club Pickup Day")
- **Date and time** (convert to ISO 8601)
- **End time** (estimate 2h if not specified)
- **Location** (winery name + address if present)
- **Description** (brief summary + RSVP info + any special notes)
- **URL** (RSVP or event link if present)

Use your judgment to identify the key event details. If a single email contains multiple events (e.g. a monthly newsletter), create a separate calendar event for each.

### Step 4 — Check for duplicates

Before creating, check if an event with the same name and date already exists:

```bash
gog calendar events CALENDAR_ID --from ISO_DATE --to ISO_DATE_PLUS_1 --account USER@gmail.com
```

Skip creation if a match is found.

### Step 5 — Create the calendar event

```bash
gog calendar create CALENDAR_ID \
  --summary "EVENT_NAME" \
  --from "ISO_START" \
  --to "ISO_END" \
  --description "DESCRIPTION" \
  --account USER@gmail.com
```

### Step 6 — Report results

After processing all emails, summarize:
- Number of emails scanned
- Number of new events added (list each with name + date)
- Number of duplicates skipped
- Any emails that looked like events but couldn't be parsed

## Gmail Search Queries

Use these queries (combine with OR) to find winery event emails:

See `references/gmail-queries.md` for the full list of search terms.

## Scheduling (optional)

To run automatically, set up a cron job:
```
openclaw cron add --schedule "0 8 * * *" --message "Run winery events calendar sync for USER@gmail.com"
```

## Notes

- Always confirm before creating events if running interactively
- Winery newsletters often contain multiple events — parse each one separately
- Wine club pickup reminders should be treated as events with the pickup window as the time range
- If no date is found in an email, skip it and mention it in the report

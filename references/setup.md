# Setup Reference

## Prerequisites

- `gog` CLI installed and authenticated with Gmail + Calendar scopes
- Verify: `gog auth list` should show `gmail,calendar` in services

## Creating the "Winery Events" Calendar

**Important:** `gog` cannot create calendars — only events. You must create the calendar via:

1. **Google Calendar UI** — go to calendar.google.com, click "+" next to "Other calendars", choose "Create new calendar", name it "Winery Events"
2. **Google Calendar API** — POST to `/calendar/v3/calendars` with an OAuth access token

### Getting the Calendar ID

```bash
gog calendar calendars --account USER@gmail.com
```

Look for "Winery Events" in the output. The ID will look like:
`abc123xyz@group.calendar.google.com`

## Storing Configuration

Save to `skills/winery-events-calendar/config.env`:

```
WINERY_CAL_ID=abc123xyz@group.calendar.google.com
WINERY_ACCOUNT=user@gmail.com
```

## Calendar Settings (recommended)

After creation, in Google Calendar UI:
- Set color to green (winery/nature theme)
- Make visible on main calendar view
- Enable notifications for new events

## Python NOT Required

The original skill included a Python search script. This has been removed — all Gmail searches use `gog` CLI directly, which is simpler and has no dependency requirements.

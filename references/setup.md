# Setup Reference

## Prerequisites

- `gog` CLI installed and authenticated with Gmail + Calendar scopes
- Verify: `gog auth list` should show `gmail,calendar` in services

## Creating the "Winery Events" Calendar

```bash
# List existing calendars to check if it already exists
gog calendar list --account USER@gmail.com

# Create if missing
gog calendar create --summary "Winery Events" --account USER@gmail.com
```

The calendar ID will be returned in the output — it looks like:
`abc123xyz@group.calendar.google.com`

Save this ID. It's needed for all event creation and lookup calls.

## Storing the Calendar ID

Save the calendar ID to the workspace for future runs:

```bash
echo "WINERY_CAL_ID=abc123xyz@group.calendar.google.com" >> ~/.openclaw/workspace/skills/winery-events-calendar/config.env
```

Then read it in future runs:
```bash
source ~/.openclaw/workspace/skills/winery-events-calendar/config.env
```

## Calendar Settings (recommended)

After creation, in Google Calendar UI:
- Set color: Green (fits a winery/nature theme)
- Make it visible on main calendar view
- Enable notifications for new events

## Verifying gog Calendar Permissions

```bash
# Test by listing events on primary calendar
gog calendar events primary --from $(date -u +%Y-%m-%dT%H:%M:%SZ) --to $(date -u -d "+7 days" +%Y-%m-%dT%H:%M:%SZ) --account USER@gmail.com
```

If this returns without error, Calendar write access is working.

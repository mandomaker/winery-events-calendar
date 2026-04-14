#!/bin/zsh
set -euo pipefail

ACCOUNT="michael.r.mcdonald@gmail.com"
CAL_ID="061748266060940d1b879cf6da8a5d42ff2f0b707627d2c623eb3aff8f3589d8@group.calendar.google.com"
DISCORD_CHANNEL="channel:1491893090703769681"
WORKDIR="/Users/mando/winery-events-calendar"
LOOKBACK_DAYS="${1:-2}"
STATUS_FILE="/Users/mando/.openclaw/workspace/data/winery-sync-status.json"
mkdir -p "$(dirname "$STATUS_FILE")"

write_status() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
path = "/Users/mando/.openclaw/workspace/data/winery-sync-status.json"
status, created, error, detail = sys.argv[1:5]
now = datetime.now(ZoneInfo('America/Los_Angeles')).isoformat()
payload = {
    "lastRun": now,
    "status": status,
    "createdCount": int(created),
    "error": error,
    "detail": detail,
}
with open(path, 'w') as f:
    json.dump(payload, f, indent=2)
PY
}

cd "$WORKDIR"
if ! RESULT=$(python3 scripts/run_winery_sync.py --account "$ACCOUNT" --calendar-id "$CAL_ID" --days "$LOOKBACK_DAYS" 2>&1); then
  write_status "error" "0" "sync-failed" "$RESULT"
  openclaw message send --channel discord --target "$DISCORD_CHANNEL" --message "⚠️ Winery sync failed. Check /tmp/winery-events-sync.err.log or Mission Control for details."
  echo "$RESULT" >&2
  exit 1
fi

echo "$RESULT"
CREATED_COUNT=$(printf '%s' "$RESULT" | python3 -c 'import sys, json; d=json.load(sys.stdin); print(len(d.get("created", [])))')
if [ "$CREATED_COUNT" -gt 0 ]; then
  SUMMARY=$(printf '%s' "$RESULT" | python3 -c 'import sys, json; d=json.load(sys.stdin); items=d.get("created", []); print("\n".join(["- {} ({})".format(i["subject"], i["start"][:10]) for i in items]))')
  MSG=$(printf '🍷 Winery Events Update\n\nAdded events:\n%s' "$SUMMARY")
  openclaw message send --channel discord --target "$DISCORD_CHANNEL" --message "$MSG"
  write_status "ok" "$CREATED_COUNT" "" "$SUMMARY"
else
  write_status "ok" "0" "" "No new winery events found."
fi

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
RESULT_FILE=$(mktemp)
trap 'rm -f "$RESULT_FILE"' EXIT

ERR_FILE=$(mktemp)
trap 'rm -f "$RESULT_FILE" "$ERR_FILE"' EXIT

if ! python3 scripts/run_winery_sync.py --account "$ACCOUNT" --calendar-id "$CAL_ID" --days "$LOOKBACK_DAYS" > "$RESULT_FILE" 2> "$ERR_FILE"; then
  RESULT=$(cat "$ERR_FILE")
  write_status "error" "0" "sync-failed" "$RESULT"
  openclaw message send --channel discord --target "$DISCORD_CHANNEL" --message "Winery sync failed. Check /tmp/winery-events-sync.err.log or Mission Control for details."
  cat "$ERR_FILE" >&2
  exit 1
fi

cat "$ERR_FILE" >&2
cat "$RESULT_FILE"
CREATED_COUNT=$(python3 - "$RESULT_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    result = json.load(f)
print(len(result.get('created', [])))
PY
)

if [ "$CREATED_COUNT" -gt 0 ]; then
  SUMMARY=$(python3 - "$RESULT_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    result = json.load(f)
print("\n".join(f"- {item['subject']} ({item['start'][:10]})" for item in result.get('created', [])))
PY
)
  MSG=$(python3 - "$RESULT_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    result = json.load(f)
summary = "\n".join(f"- {item['subject']} ({item['start'][:10]})" for item in result.get('created', []))
print("Winery Events Update\n\nAdded events:\n" + summary)
PY
)
  openclaw message send --channel discord --target "$DISCORD_CHANNEL" --message "$MSG"
  write_status "ok" "$CREATED_COUNT" "" "$SUMMARY"
else
  write_status "ok" "0" "" "No new winery events found."
fi

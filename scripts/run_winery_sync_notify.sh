#!/bin/zsh
set -euo pipefail

ACCOUNT="michael.r.mcdonald@gmail.com"
CAL_ID="061748266060940d1b879cf6da8a5d42ff2f0b707627d2c623eb3aff8f3589d8@group.calendar.google.com"
DISCORD_CHANNEL="channel:1491893090703769681"
WORKDIR="/Users/mando/winery-events-calendar"
LOOKBACK_DAYS="${1:-2}"

cd "$WORKDIR"
RESULT=$(python3 scripts/run_winery_sync.py --account "$ACCOUNT" --calendar-id "$CAL_ID" --days "$LOOKBACK_DAYS")
echo "$RESULT"

CREATED_COUNT=$(printf '%s' "$RESULT" | python3 -c 'import sys, json; d=json.load(sys.stdin); print(len(d.get("created", [])))')
if [ "$CREATED_COUNT" -gt 0 ]; then
  SUMMARY=$(printf '%s' "$RESULT" | python3 -c 'import sys, json; d=json.load(sys.stdin); items=d.get("created", []); print("\n".join(["- {} ({})".format(i["subject"], i["start"][:10]) for i in items]))')
  MSG=$(printf '🍷 Winery Events Update\n\nAdded events:\n%s' "$SUMMARY")
  openclaw message send --channel discord --target "$DISCORD_CHANNEL" --message "$MSG"
fi

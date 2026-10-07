#!/usr/bin/env bash
# Smoke test for the handover plugin: on its first session start in a new data
# folder, it carries over the metrics and YOLO audit logs it recorded under its
# old name (handoff, events renamed) and in its old marketplace (fundriven).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n      wanted: %s\n      got:    %s\n' "$1" "$2" "$3"; failures=$((failures + 1)); }
same() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1" "$2" "$3"; fi; }

echo "handover: carry-over of the old data folders"
data="$WORK/data"
mkdir -p "$data/handoff-fundrivendev" "$data/handover-fundriven/audit" "$data/handover-fundrivendev"
echo '{"event": "armed", "at": 1, "session": "a"}' >"$data/handoff-fundrivendev/metrics.jsonl"
printf '%s\n' '{"event": "handover_loaded", "at": 2, "session": "b", "model": "kept"}' 'not json' \
  >"$data/handover-fundriven/metrics.jsonl"
echo '{"line": 1}' >"$data/handover-fundriven/audit/run1.jsonl"
echo '{"event": "session_ended", "at": 3, "session": "c"}' >"$data/handover-fundrivendev/metrics.jsonl"

start() {
  echo '{"hook_event_name": "SessionStart", "source": "startup"}' |
    HOME=$WORK CLAUDE_PLUGIN_DATA="$data/handover-fundrivendev" python3 "$ROOT/plugins/handover/scripts/handover.py" hook >/dev/null 2>&1 || true
}
events() { jq -r .event "$data/handover-fundrivendev/metrics.jsonl" | tr '\n' ' '; }

start
same "old events first, renamed only from handoff" "wind_down_started handover_loaded session_ended" \
  "$(events | grep -oE '^(\S+ ){3}' | sed 's/ $//')"
same "events from the old marketplace keep their fields" '"kept"' \
  "$(jq -c 'select(.session == "b") | .model' "$data/handover-fundrivendev/metrics.jsonl")"
same "audit logs copied" '{"line": 1}' "$(cat "$data/handover-fundrivendev/audit/run1.jsonl" 2>/dev/null)"
same "the marker counts what was imported" "2 1" \
  "$(jq -r '"\(.metrics) \(.audit)"' "$data/handover-fundrivendev/imported.json" 2>/dev/null)"

start
same "a second start imports nothing again" 2 \
  "$(jq -c 'select(.session == "a" or .session == "b")' "$data/handover-fundrivendev/metrics.jsonl" | wc -l | tr -d ' ')"

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)"; exit 1
fi
echo "all passed"

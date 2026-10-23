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

echo "handover: a subagent stopped without SubagentStop"
mkdir -p "$WORK/.claude/projects/p"
echo '{"type": "user", "message": {"role": "user", "content": "hi"}}' >"$WORK/.claude/projects/p/s1.jsonl"
handover() { HOME=$WORK CLAUDE_PLUGIN_DATA="$data/handover-fundrivendev" python3 "$ROOT/plugins/handover/scripts/handover.py" "$@"; }
echo '{"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "general-purpose"}' |
  handover hook >/dev/null 2>&1 || true
out=$(handover request --cause user --session s1 2>&1) && code=0 || code=$?
same "the request is accepted" 0 "$code"
same "the session is told subagents may still run" 1 "$(grep -c 'may still run (1 counted)' <<<"$out")"
same "the wind-down starts" true "$(jq -r '.wind_down != null' "$data/handover-fundrivendev/sessions/s1.json" 2>/dev/null)"

echo "handover: the running subagents are kept up to date outside a handover"
sessions="$data/handover-fundrivendev/sessions"
tp="$WORK/.claude/projects/p/s2.jsonl"
echo '{"type": "user", "message": {"role": "user", "content": "hi"}}' >"$tp"
hook() { jq -nc --arg tp "$tp" "{session_id: \"s2\", transcript_path: \$tp} + $1" | handover hook >/dev/null 2>&1 || true; }
agents() { jq -r 'keys | join(" ")' "$sessions/s2.agents.json" 2>/dev/null; }
for a in a1 a2 a3 a4; do hook "{hook_event_name: \"SubagentStart\", agent_id: \"$a\"}"; done
hook '{hook_event_name: "PostToolUse", tool_name: "TaskStop", tool_response: {task_id: "a1", task_type: "local_agent"}}'
same "TaskStop of a subagent drops it" "a2 a3 a4" "$(agents)"
mkdir -p "$WORK/wf"
touch "$WORK/wf/agent-a2.jsonl" "$WORK/wf/agent-a2.meta.json" "$WORK/wf/agent-a3.jsonl" "$WORK/wf/journal.jsonl"
hook "{hook_event_name: \"PostToolUse\", tool_name: \"Workflow\", tool_response: {taskId: \"w1\", transcriptDir: \"$WORK/wf\"}}"
hook '{hook_event_name: "PostToolUse", tool_name: "TaskStop", tool_response: {task_id: "w1", task_type: "local_workflow"}}'
same "TaskStop of a workflow drops its agents" "a4" "$(agents)"
hook '{hook_event_name: "Stop", background_tasks: [{id: "x", type: "subagent", status: "running"}]}'
same "a Stop with a subagent running keeps the count" "a4" "$(agents)"
hook '{hook_event_name: "Stop", background_tasks: [{id: "b", type: "shell", status: "running"}]}'
same "a Stop with no subagent running clears it, below the suggestion" "" "$(agents)"
same "no handover state was started" false "$([ -e "$sessions/s2.json" ] && echo true || echo false)"

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)"; exit 1
fi
echo "all passed"

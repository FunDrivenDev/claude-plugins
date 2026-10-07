---
name: afk
description: Turn AFK mode on in this session - work toward a goal while the user is away, relaying to fresh sessions with no relay_limit, until the goal is met, nothing can move without the user, or an optional deadline passes. Needs tmux. Argument, the goal, optionally followed by a deadline; `off` turns it off.
argument-hint: "<goal> [until <when>] | off"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# AFK

Argument: `$ARGUMENTS`

When the argument is `off`, run this, show its output, and stop:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" afk --off --session "${CLAUDE_SESSION_ID}"
```

Otherwise the argument is the goal. When it is empty, ask the user for the goal and stop. When it ends on a deadline (`until 8`, `until tomorrow 8:00`, `until mon 9`, `for 10h`), take the deadline out of the goal and pass it as `--until`: a time or a day and a time as is (`8`, `tomorrow 8:00`, `mon 9`), a duration as `+10h`. Run, with the goal and the deadline shell-quoted:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" afk --session "${CLAUDE_SESSION_ID}" --goal '<goal>' [--until '<when>']
```

This skill never turns YOLO on: a running session keeps its permission mode. A run without permission prompts starts with `claude-relay --afk '<goal>' --yolo`.

- Exit code 0: stdout holds the AFK rules. Tell the user in one line that AFK mode is on, with the deadline if there is one, then start on the goal right away and follow those rules until the run ends.
- Otherwise: show the error from stderr, as is.

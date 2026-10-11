---
name: trigger
description: Hand this session over now, before the automatic trigger - the same wind-down and handover the trigger starts, then /clear loads it into a fresh session. Optional argument, what the next session will focus on.
argument-hint: "[focus of the next session, e.g. \"address the review comments on PR #12\"]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# Trigger a handover

Focus of the next session: `$ARGUMENTS`

Run this command. When the focus above is not empty, append `--focus '<focus>'`, shell-quoted.

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" request --cause user --session "${CLAUDE_SESSION_ID}" --reason 'asked by the user'
```

As your turn ends, a separate model writes the handover from this session's complete transcript; do not write one yourself, and do not read the file it produces.

- Exit code 0: do not start a new task. Close the step in progress, then end your turn on one short line on where the work stands, without `Ready to hand over` nor the resume message: the user must not run /clear before the handover exists. The hook then writes the handover and tells you once it is written; only then write your closing reply, as that message says: one line on where the work stands, then the handover's full path, then `Ready to hand over: run /clear.`, then, in a code block, the message the user should send after /clear to resume, naming the very next step.
- Exit code 3: subagents of this session still run. Start no new work and no new subagent; wait for their results, then run the command again.
- Otherwise: show the error from stderr, as is.

---
name: handover
description: Hand this session over to a fresh one while its context is still sharp. Use at a boundary between scopes (a task done, a PR pushed, before an unrelated task or a long new investigation) once the handover hook has said the context is past its suggestion point, rather than waiting for the automatic trigger. A separate model writes the handover as the turn ends, then the session writes its closing reply; the user runs /clear and the next session starts from it at once.
argument-hint: "[focus of the next session]"
user-invocable: false
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# Handover

Focus of the next session: `$ARGUMENTS`

A fresh session reasons better than one deep into its context window. Hand over at a clean boundary: the step in progress finished, its subagents and the background commands you need back, the files and the git state coherent. The handover is written from the transcript as your turn ends, so whatever is still running then is missing from it.

Run this command. Replace `<reason>` with one line on why now (the boundary reached, the size of what comes next), shell-quoted. When the focus above is not empty, append `--focus '<focus>'`, shell-quoted.

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" request --cause model --session "${CLAUDE_SESSION_ID}" --reason '<reason>'
```

As your turn ends, a separate model writes the handover from this session's complete transcript; do not write one yourself, and do not read the file it produces.

- Exit code 0: do not start a new task. End your turn on one short line on where the work stands, without `Ready to hand over` nor the resume message: the user must not run /clear before the handover exists. The hook then writes the handover and tells you once it is written; only then write your closing reply, as that message says: one line on where the work stands, then `Ready to hand over: run /clear.`, then, in a code block, the message the user should send after /clear to resume, naming the very next step.
- Exit code 3: subagents of this session still run. Start no new work and no new subagent; wait for their results, then run the command again.
- Otherwise: show the error from stderr, as is, and carry on.

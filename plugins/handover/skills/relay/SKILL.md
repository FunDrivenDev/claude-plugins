---
name: relay
description: Hand this session over now and relay it - a fresh session resumes from the handover without the user, and keeps handing over by itself, up to relay_limit handovers. Needs the session to run in tmux. Optional argument, what the next session will focus on.
argument-hint: "[focus of the next session]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# Relay

Focus of the next session: `$ARGUMENTS`

Run this command. When the focus above is not empty, append `--focus '<focus>'`, shell-quoted.

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" request --relay --cause user --session "${CLAUDE_SESSION_ID}"
```

As your turn ends, a separate model writes the handover from this session's complete transcript; do not write one yourself, and do not read the file it produces.

- Exit code 0: do not start a new task. End your turn on one short line on where the work stands, without `Ready to hand over` nor the resume message. The hook then writes the handover and tells you once it is written; only then write your closing reply, as that message says: one line on where the work stands, then the handover's full path, then `Ready to hand over: run /clear.`, then, in a code block, the message to send after /clear to resume, naming the very next step. Once that reply ends, the relay clears the session and sends the message for the user.
- Exit code 3: subagents of this session still run. Start no new work and no new subagent; wait for their results, then run the command again.
- Otherwise: show the error from stderr, as is.

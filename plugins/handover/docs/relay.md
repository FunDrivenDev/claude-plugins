# Relay

Hand over without typing `/clear` yourself, under tmux. [Back to the README](../README.md)

Two ways to turn the relay on:

- **For a whole session:** start it with `toolbox session create` or `toolbox session run` (below), which set `HANDOVER_RELAY=1` and run `claude` inside a tmux session of their own when not already in tmux. Arguments go to `claude`. Every handover of that session relays: the one the session asks for, and the automatic one at `trigger_tokens`.
- **From a running session:** type `/handover:relay [focus]`. The session hands over at the end of its turn, and the handover is relayed; the session must already run in tmux.

Either way, every session the relay starts relays in turn, until the chain reaches `relay_limit`. The handover is written first, as for any handover; once the session has then written its closing reply (`Ready to hand over: run /clear.` and the resume message), the `Stop` hook hands over without you:

1. A detached helper types `/clear` into the session's tmux pane.
2. The new session loads the handover, already written, like any `/clear`, and is told the relay started it.
3. The helper then types the resume message the old session wrote in its code block, and the new session starts right away.

Handovers go into one folder per day, `YYYY/MM/DD/`, named after the time they were written and their topic: `2026/10/07/09h32-<topic>.md`; a name already taken gets `-b`, `-c`. A relay chain follows the same rule, each handover in the folder of the day it was written: `2026/10/04/21h10-relay-after-handover.md`, `2026/10/04/21h55-relay-after-handover.md`, `2026/10/05/00h40-relay-after-handover.md`. Under its title, each handover of a chain says its rank and where the chain started: ``Relay 3/5 · chain started with `2026/10/04/21h10-relay-after-handover.md` ``. Handovers written before 0.10.0 stay where they are, as `YY-MM-DD-<topic>.md`.

At `relay_limit` handovers (5) the chain halts: the last handover is written, but the session waits for your `/clear`, with a macOS notification and a terminal bell. A `/clear` of yours starts a new chain. The same alert fires when the new session fails to load the handover, or when a relay session runs neither in tmux nor under the loop below.

Without tmux, `toolbox session run` falls back to a loop: the relay leaves the resume message in `$HANDOVER_RELAY_FILE` and ends `claude` with SIGTERM, and the loop starts `claude` again with the same arguments plus that message. There, give flags only and type the first prompt in the session.

The launcher is the [toolbox](https://github.com/FunDrivenDev/toolbox) CLI (`brew install fundrivendev/tap/toolbox`), which finds `handover.py` through the plugin's install path on every call, so it keeps working across plugin versions. `/handover:relay` and `/handover:afk` need a session already in tmux, which these commands give every Claude Code they start:

```zsh
toolbox session create                      # Claude Code with the relay; outside tmux, in a session that closes with the tab; inside tmux, in the current pane
toolbox session create --name <name>        # a named session that outlives the tab; inside tmux, renames the current one
toolbox session create --afk --yolo '<goal>' [--until <when>] [-- <claude options>]   # an AFK run
toolbox session list                        # the sessions
toolbox session attach <name>               # rejoins one
toolbox session run [claude args]           # the relay itself, arguments passed to claude untouched
```

`scripts/claude-relay` remains as a shim for older callers: it runs `toolbox session run` with its arguments, and fails with an install hint when toolbox is missing. The contract between toolbox and `handover.py` (the `HANDOVER_*` variables, `handover.py until` and `yolo-settings`) is documented in toolbox's [`docs/handover-relay.md`](https://github.com/FunDrivenDev/toolbox/blob/main/docs/handover-relay.md).

Inside tmux, Claude Code wants `extended-keys` on (Shift+Enter) and `mouse` on (the wheel scrolls tmux's history rather than Claude Code's prompt history).

# Relay

Hand over without typing `/clear` yourself, under tmux, in Rex, or in any terminal a command can type into. [Back to the README](../README.md)

Two ways to turn the relay on:

- **For a whole session:** start it with `toolbox session create` or `toolbox session run` (below), which set `HANDOVER_RELAY=1` and run `claude` inside a tmux session of their own when outside tmux; in a Rex pane, with `toolbox rex-session run`, which keeps `claude` in the pane. Arguments go to `claude`. Every handover of that session relays: the one the session asks for, and the automatic one at `trigger_tokens`.
- **From a running session:** type `/handover:relay [focus]`. The session hands over at the end of its turn, and the handover is relayed; the session must already run in a terminal the plugin can type into.

Either way, every session the relay starts relays in turn, until the chain reaches `relay_limit`. The handover is written first, as for any handover; once the session has then written its closing reply (`Ready to hand over: run /clear.` and the resume message), the `Stop` hook hands over without you:

1. A detached helper empties the session's prompt, so a draft does not merge with what it types (a draft stays in Claude Code's kill ring: `Ctrl+Y`), and types `/clear`.
2. The new session loads the handover, already written, like any `/clear`, and is told the relay started it. It takes only the handover offered in its own pane: two chains in one project (Guest-Suite sessions all start from guest-environment) that hand over in the same minute each resume their own handover and AFK goal. Under the `command` adapter the plugin cannot tell its panes apart: two of them in one project still share the offer, so hand over from one at a time. When it starts outside the directory the handover's `Working directory` section names (the old session's worktree, say), it is told to begin with one plain `cd` there. Claude Code resets a `cd` to a directory outside the one the session started in (a sibling `<repo>.worktrees/<task>`), so for such a directory the helper first types `/add-dir <path>` and confirms it, then the resume message; under the loop, which cannot type, the session is told to work there with absolute paths and `git -C`. When that directory is gone, it stays where it started if the directory sat inside it (a Guest-Suite session starts from the guest-environment root, its `apps/worktree-*` inside), else it is told to `cd` to the repo's main checkout.
3. The helper then types the resume message the old session wrote in its code block, and the new session starts right away.

Handovers go into one folder per day, `YYYY/MM/DD/`, named after the time they were written and their topic: `2026/10/07/09h32-<topic>.md`; a name already taken gets `-b`, `-c`. A relay chain follows the same rule, each handover in the folder of the day it was written: `2026/10/04/21h10-relay-after-handover.md`, `2026/10/04/21h55-relay-after-handover.md`, `2026/10/05/00h40-relay-after-handover.md`. Under its title, each handover of a chain says its rank and where the chain started: ``Relay 3/5 · chain started with `2026/10/04/21h10-relay-after-handover.md` ``. Handovers written before 0.10.0 stay where they are, as `YY-MM-DD-<topic>.md`.

At `relay_limit` handovers (10) the chain halts: the last handover is written, but the session waits for your `/clear`, with a notification ([notifier](notifications.md)) and a terminal bell. A `/clear` of yours starts a new chain. The same alert fires when the new session fails to load the handover, or when a relay session runs neither in tmux nor under the loop below.

Without tmux, `toolbox session run` falls back to a loop: the relay leaves the resume message in `$HANDOVER_RELAY_FILE` and ends `claude` with SIGTERM, and the loop starts `claude` again with the same arguments plus that message. There, give flags only and type the first prompt in the session.

The launcher is the [toolbox](https://github.com/FunDrivenDev/toolbox) CLI (`brew install fundrivendev/tap/toolbox`), 0.16.0 or later: a bypass-permissions AFK run that Rex brings back from a server restart is relaunched with `--bypass-permissions`, which older versions hand to `claude` as an unknown option. It finds `handover.py` through the plugin's install path on every call, so it keeps working across plugin versions. `/handover:relay` and `/handover:afk` need a session the plugin can type into: in Rex or a `command` terminal any session, otherwise one in tmux, which these commands give every Claude Code they start:

```zsh
toolbox session create                      # Claude Code with the relay; outside tmux, in a session that closes with the tab; inside tmux, in the current pane
toolbox session create --name <name>        # a named session that outlives the tab; inside tmux, renames the current one
toolbox session create --afk --bypass-permissions --prompt='<goal>' [--until <when>] [-- <claude options>]   # an AFK run
toolbox session list                        # the sessions
toolbox session attach <name>               # rejoins one
toolbox session run [claude args]           # the relay itself, arguments passed to claude untouched
toolbox rex-session run [claude args]       # the same in a Rex pane, without tmux
```

`scripts/claude-relay` remains as a shim for older callers: it runs `toolbox session run` with its arguments, and fails with an install hint when toolbox is missing. The contract between toolbox and `handover.py` (the `HANDOVER_*` variables, `handover.py until` and `yolo-settings`) is documented in toolbox's [`docs/handover-relay.md`](https://github.com/FunDrivenDev/toolbox/blob/main/docs/handover-relay.md).

## Terminals

Everything the plugin does to a terminal goes through one port, `scripts/terminal.py`. The `terminal` option picks the adapter; `auto` takes the innermost host it finds:

| Adapter | Found by | Relay | Tab title | Bell | Status on the tab |
| --- | --- | --- | --- | --- | --- |
| `tmux` | `TMUX_PANE` | types | window name | yes | no |
| `rex` | `REX_SESSION`, `REX_BLOCK` | types | tab label | yes | OSC 7501, record `handover` |
| `command` | `terminal` set to `command` | through `terminal_command` | what your command does | what your command does | what your command does |
| loop | `HANDOVER_RELAY_FILE` | restarts `claude` | no | no | no |

`handover.py terminal describe` prints what was found here. A relayed session names its tab `<chain> #<n>`, with `AFK` in front on a run; an AFK run's first session, before any chain, takes the start of its goal. A Rex tab that someone labelled keeps its label instead: a dispatcher's `rex window new <label>` or `rex new --window <label>`, or a `rex window rename` by hand mid-chain, gives `<label>` on the chain's first session and `<label> #<n>` from the second on. Callers pass nothing: at each title change the plugin reads the tab's name, and takes it as the label unless it is the title the plugin itself set there last (kept per pane in `tabs/` of its data folder for 90 days), in which case it reuses the label that title came from. A tab without that record, titled before 0.25.0 or idle longer, counts as unlabelled when its name has the shape of an unlabelled title (`AFK <name> #<n>`, or `<chain> #<n>`). Rex's own `Window <id>` names count as no label. A label is kept as given, `PR #123` or `AFK watcher` included. Under tmux the window still takes the chain's titles: `toolbox session create --name` names the tmux session, which they leave alone. The bell rings when a run ends, when it needs you, when a relay stalls and when a run is lost, never on an ordinary handover.

### Rex

Rex's own status on the tab needs `claude` directly in the pane, as it does not cross tmux. So in Rex, start the relay with `toolbox rex-session run`, which starts no tmux (`toolbox session run` there would start one).

A pane program dies with its tab and with the Rex server, and a Rex update restarts the server. An AFK run comes back from a restart: Rex restores the pane with a shell, and the plugin types `toolbox rex-session run --afk <goal> [--bypass-permissions] --resume <session>` there, within 5 minutes of the server's return. A closed tab ends the run, with an alert giving the resume command. A reboot sends Claude Code no `SessionEnd`, so it is not covered. A relay outside AFK mode is not resumed.

### Any other terminal

Set `terminal` to `command` and `terminal_command` to a command. `sh` runs it for each verb, with `HANDOVER_VERB` (`type_text`, `press_enter`, `clear_input`, `set_title`, `ring`, `report_status`), `HANDOVER_TEXT` and `HANDOVER_STATE` in its environment. It exits non-zero on a verb it cannot do; the relay needs `type_text` and `press_enter`. Keep it in a script, and set `terminal_command` to its path.

[AImux](https://github.com/rdavaillaud/aimux), whose tiles export `AIMUX_CLI` and `AIMUX_TASK_ID`:

```sh
#!/bin/sh
aimux=${AIMUX_CLI:-aimux}
case $HANDOVER_VERB in
  type_text) "$aimux" task send "$AIMUX_TASK_ID" "$HANDOVER_TEXT" --no-enter ;;
  press_enter) "$aimux" task send "$AIMUX_TASK_ID" "" ;;
  *) exit 1 ;;
esac
```

`aimux task send` holds the text until the agent is idle. This script has not been run on AImux yet.

## tmux

Inside tmux, Claude Code wants `extended-keys` on (Shift+Enter) and `mouse` on (the wheel scrolls tmux's history rather than Claude Code's prompt history).

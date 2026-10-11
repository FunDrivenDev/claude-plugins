# Relay

Hand over without typing `/clear` yourself, under tmux. [Back to the README](../README.md)

Two ways to turn the relay on:

- **For a whole session:** start it with `gmux` (below), or `scripts/claude-relay` itself, which sets `HANDOVER_RELAY=1` and runs `claude` inside a tmux session of its own when it is not already in tmux. Arguments go to `claude`. Every handover of that session relays: the one the session asks for, and the automatic one at `trigger_tokens`.
- **From a running session:** type `/handover:relay [focus]`. The session hands over at the end of its turn, and the handover is relayed; the session must already run in tmux.

Either way, every session the relay starts relays in turn, until the chain reaches `relay_limit`. The handover is written first, as for any handover; once the session has then written its closing reply (`Ready to hand over: run /clear.` and the resume message), the `Stop` hook hands over without you:

1. A detached helper types `/clear` into the session's tmux pane.
2. The new session loads the handover, already written, like any `/clear`, and is told the relay started it.
3. The helper then types the resume message the old session wrote in its code block, and the new session starts right away.

Handovers go into one folder per day, `YYYY/MM/DD/`, named after the time they were written and their topic: `2026/10/07/09h32-<topic>.md`; a name already taken gets `-b`, `-c`. A relay chain follows the same rule, each handover in the folder of the day it was written: `2026/10/04/21h10-relay-after-handover.md`, `2026/10/04/21h55-relay-after-handover.md`, `2026/10/05/00h40-relay-after-handover.md`. Under its title, each handover of a chain says its rank and where the chain started: ``Relay 3/5 · chain started with `2026/10/04/21h10-relay-after-handover.md` ``. Handovers written before 0.10.0 stay where they are, as `YY-MM-DD-<topic>.md`.

At `relay_limit` handovers (5) the chain halts: the last handover is written, but the session waits for your `/clear`, with a macOS notification and a terminal bell. A `/clear` of yours starts a new chain. The same alert fires when the new session fails to load the handover, or when a relay session runs neither in tmux nor under the loop below.

Without tmux, `claude-relay` falls back to a loop: the relay leaves the resume message in `$HANDOVER_RELAY_FILE` and ends `claude` with SIGTERM, and the loop starts `claude` again with the same arguments plus that message. There, give flags only and type the first prompt in the session.

`scripts/claude-relay` stays the plugin's entry point; since the plugin's install path changes with each version, call it from one shell function, `gmux`, which also names tmux sessions to find them again and launches AFK runs (`/handover:relay` and `/handover:afk` need a session already in tmux, which `gmux` gives every Claude Code it starts):

```zsh
# gmux [claude flags]: Claude Code with the relay; outside tmux, in a session that closes
#   with the tab; inside tmux, in the current pane
# gmux <name> [claude flags]: rejoins session <name> if it exists (flags ignored); otherwise
#   creates it, outliving the tab; inside tmux, names the current session so and runs
#   Claude Code in the pane
# gmux ls: the tmux sessions
# gmux --afk '<goal>' [--until <when>] [--yolo] [claude flags]: an AFK run
# A first argument is a name when it does not start with - and is not ls.
gmux() {
  if [[ $1 == ls ]]; then tmux list-sessions; return; fi
  if [[ $# -gt 0 && $1 != -* ]] && tmux has-session -t "=$1" 2>/dev/null; then
    if [[ -n $TMUX ]]; then tmux switch-client -t "=$1"; else tmux attach-session -t "=$1"; fi
    return
  fi
  local hp
  hp=$(jq -r '.plugins["handover@fundrivendev"][0].installPath // empty' ~/.claude/plugins/installed_plugins.json)
  [[ -x $hp/scripts/claude-relay ]] || { print -u2 "gmux: handover@fundrivendev is not installed"; return 1; }
  if [[ $# -eq 0 || $1 == -* ]]; then "$hp/scripts/claude-relay" "$@"; return; fi
  local name=$1; shift
  if [[ -n $TMUX ]]; then
    # claude-relay keeps a session bound to its tab while HANDOVER_RELAY_OWN is set:
    # a named session must outlive the tab.
    tmux rename-session -- "$name" \; set-option destroy-unattached off \; set-environment -u HANDOVER_RELAY_OWN || return
    HANDOVER_RELAY_OWN= "$hp/scripts/claude-relay" "$@"
  else
    tmux new-session -s "$name" -c "$PWD" "$hp/scripts/claude-relay" "$@" \; set-option destroy-unattached off
  fi
}
```

Inside tmux, Claude Code wants `extended-keys` on (Shift+Enter) and `mouse` on (the wheel scrolls tmux's history rather than Claude Code's prompt history).

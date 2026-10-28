# Status line

The one-line handover state a status line can print. [Back to the README](../README.md)

`handover.py statusline` reads the status-line payload on stdin and prints the session's handover state as one short line. The context size is left to the first line, which already shows it:

| Line | Colour | When |
|---|---|---|
| `✋ Handover will trigger at 185k` | gray, yellow within `warn_tokens` | Before the trigger |
| `✋ Handover suggested · will trigger at 185k` | gray, yellow within `warn_tokens` | Past `suggest_tokens` |
| `✋ Wind-down on the next tool call` | orange | Past the trigger, the wind-down not started yet |
| `✋ Winding down · finishing tasks` | orange | The session finishes its tasks in progress, then hands over |
| `✋ Handover writing · 3.2k/8.0k chars ▓▓▓▓░░░░░░ · 41s` | orange | The writer at work, the `Stop` hook holding the session: starting, reading, thinking, then drafting against `handover_chars` |
| `✋ Handover written · closing reply` | orange | Handover written; the session writes its closing reply. Not yet the time for `/clear` |
| `✋ Handover ready · run /clear` | green | Handover and closing reply written |
| `✋ Handover ready · relaying` | green | The relay is clearing the session |
| `✋ Compacting · handover written, loads after it` | gray | A compaction runs; its handover is loaded next to the summary, no `/clear` to run |
| `✋ Relay limit · 10 handovers · run /clear` | red | The chain reached `relay_limit` |
| `✋ AFK deadline · 3 handovers · run /clear` | red | An AFK run's deadline passed at a handover |
| `✋ AFK done · <why>` | green | The AFK run ended on `AFK done`; red for `blocked`, `deadline`, `idle`, `exit` |
| `✋ Handover failed · <error>` | red | The writer failed |
| `✋ Handover trigger off` | gray | `trigger_tokens` is 0 |

The line is empty in a session where the plugin is disabled: the plugin's hooks mark each session they run in, from its start to its end, and the status line prints only for those. A status-line script can therefore call it whenever the plugin is installed.

`· loaded` is appended when the session started from a handover (`· relay 3/10` when the relay started it, `· relay 3 · AFK until 08:00` in an AFK run), and `refreshing` replaces `writing` when an existing handover is rewritten.

With the [`statusline`](../../statusline/README.md) plugin, the line shows up by itself: the plugin ships an executable `statusline-segment`, which that status line runs for each installed plugin. Otherwise, print it as a second line from your own status-line script:

```bash
payload=$(cat)
# … first line from "$payload" …
hp=$(jq -r '.plugins["handover@fundrivendev"][0].installPath // empty' ~/.claude/plugins/installed_plugins.json)
[ -n "$hp" ] && printf '\n%s' "$(python3 "$hp/scripts/handover.py" statusline <<<"$payload")"
```

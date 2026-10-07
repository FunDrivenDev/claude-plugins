# handover

Takes over from auto-compaction before the context fills up: a separate model writes a handover of the session from its transcript, and `/clear` starts a fresh session from it.

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install handover@fundrivendev
```

**Moved in 0.13.0** from the `fundriven` marketplace (FunDrivenDev/skills). Install `handover@fundrivendev`, uninstall the old one with `claude plugin uninstall handover@fundriven --keep-data` (without `--keep-data`, Claude Code deletes its data folder, history included), and move its `pluginConfigs` entry to the new key: an uninstall removes the old entry. On its first session start the plugin imports `metrics.jsonl` and the YOLO audit logs from the old data folder, `handover-fundriven`.

**Renamed in 0.8.0**, from `handoff` (it collided with Matt Pocock's `handoff` skill). Uninstall `handoff@fundriven`, install `handover`, and move its `pluginConfigs` entry and options: `handoff_dir` → `handover_dir`, `model` → `writer_model`, `budget_chars` → `handover_chars`, `approach_tokens` → `warn_tokens`, `stale_tokens` → `refresh_tokens`, `relay_max` → `relay_limit`. The `HANDOFF_*` environment variables are now `HANDOVER_*`, the commands `/handover:relay|afk|stats`. On its first session start the plugin imports `metrics.jsonl` (its events renamed) and the YOLO audit logs from the old data folder, `handoff-<marketplace>`.

Words used below: the *handover* is the document the separate model writes, and a session *hands over* when a fresh one takes over from it; the *wind-down* is the session's last stretch before that: no new task, the tasks in progress finished, background commands waited for or stopped; then the handover is written, and only then does the session write its *closing reply* (`Ready to hand over: run /clear.` and the message to resume).

## How it works

- **Suggestion.** Once the context passes `suggest_tokens`, the session is told, once, to hand over by itself at the next boundary between scopes: a task done, a PR pushed, before an unrelated task or a long new investigation. It calls the `handover` skill, which is for the model only and hidden from the `/` menu, with a one-line reason. Nothing is forced: the session picks the moment.
- **On demand.** `/handover:trigger [focus]` starts the same wind-down at once, without waiting for `trigger_tokens`. The optional focus is what the next session should work on; the writer opens the handover's next steps with it and keeps what that work needs. Without it, the next steps follow from where the session stopped. For example:
  - `/handover:trigger` — carry on where this session stops;
  - `/handover:trigger address the review comments on PR #12` — the PR is open, its review comes next;
  - `/handover:trigger debug the flaky login test, leave the refactor aside` — narrow the next session to one thread;
  - `/handover:trigger write the migration plan before any code` — change the kind of work.
- **Trigger.** Once the context passes `trigger_tokens`, the session is told not to start a new task, to finish every task in progress (the current step, its subagents, its `[await]` background commands), to stop its `[endless]` ones, and then to end its turn on one line saying where the work stands, without the closing reply yet.
- **Writing.** At that stop, with nothing left running, the `Stop` hook has a separate `claude -p` write the handover from the complete transcript, on `writer_model`, for about $0.15, and holds the session until it is written: 15 to 25 s in the measured runs, the status line showing the writer's progress. The handover goes to `handover_dir`. Written while the work went on, it would miss its end. Esc during that hold interrupts the session, not the writer: the handover still lands, and the next stop asks for the closing reply.
- **Closing reply.** The hook then blocks that stop and tells the session the handover is written: it now writes its closing reply, `Ready to hand over: run /clear.` and, in a code block, the message to send after `/clear`. So that reply only appears once the handover exists, and the status line turns to `Handover ready` only after it. A session that ends its turn without it is asked once more.
- **Background commands.** Tagged at launch, they tell the wind-down what to wait for and what to stop: see [Background commands](#background-commands).
- **`/clear`.** The handover, already written, is loaded into the new session at once. The new session still waits, up to 150 s, where a handover can legitimately be in flight: a session that went on past `refresh_tokens` after its closing reply gets it refreshed at `/clear`; a writer that outlasts the `Stop` hook's 240 s hold leaves the session to close while it finishes. Claude Code gives hooks no way to run `/clear` itself, so that keystroke stays yours.
- **Writer failure.** The session is told, writes its closing reply all the same with a resume message complete enough to go on without the handover, and ends; the stop after that reply tries the writer once more. The status line shows the error, and a relay halts with an alert rather than start a session without a handover.
- **Auto-compaction.** A handover is written in parallel and loaded next to the built-in summary, the compacted session waiting for it up to 150 s. The suggestion and the trigger are then reset, for the session starts over from a small context.
- **Exit.** The handover is refreshed in the background if the session went on, and the next session in the same project is pointed to it once written.
- **Relay.** Under `claude-relay`, the `/clear` is no longer yours: see [Relay](#relay).
- **AFK.** A relay that works through a goal while you are away, past `relay_limit`: see [AFK mode](#afk-mode).

## Relay

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

## AFK mode

For a run that should go on while you are away, overnight for instance, on a sequence of tasks rather than one: implement every open issue of the tracker until nothing is left that can move without you. One task still stops at `relay_limit`; an AFK run does not.

Two ways to start one:

- **A new run:** `gmux --afk '<goal>' [--until <when>] [--yolo] [claude flags]`, which calls `claude-relay --afk`. The goal is also the first prompt. Outside tmux, the run gets a tmux session of its own, `afk-<folder>`, which outlives its terminal tab: `tmux ls` lists it, `tmux attach -t afk-<folder>` rejoins it.
- **From a running session:** `/handover:afk <goal> [until <when>]`, in a session that already runs in tmux. The session starts on the goal right away; its tmux session stops closing with its tab.

Then:

- **It keeps going.** When a session stops between two tasks, the `Stop` hook sends it back to work with the goal. It hands over at boundaries between tasks, as suggested past `suggest_tokens`, or at `trigger_tokens`, and the relay carries the goal into the next session. No `relay_limit`.
- **It ends when the model says so.** A reply that ends on `AFK done: <why>` (goal met) or `AFK blocked: <why>` (nothing left can move without you) ends the run, with a macOS notification and a terminal bell; a closing reply that carries that line ends it too, and its handover starts no new session. A session sent back three times in a row without doing anything ends it too (`idle`; denied tool calls are not work, and the reason counts them), and so does a session that ends other than by a relayed handover: an exit, a `/clear` of yours, a crash (`exit`).
- **Deadline, optional.** `--until` takes a time (`8`, `8:30`, `8h30`, `8am`: the next one to come, so `8` launched at 23:00 is tomorrow 8:00), a day and a time (`tomorrow 8`, `mon 9:00`), a duration (`+10h`, `in 2h30m`) or a date (`2026-10-06 08:00`). `claude-relay` prints the deadline it understood. Past it, the session is told to finish its step and end its turn, and no new handover starts.
- **Taking over.** Interrupt with Esc as usual; `/handover:afk off` stops sending the session back, and the relay goes back to `relay_limit`.

AFK runs are unattended: start them with the permissions they need (an auto or accept-edits mode, an allow list), since a permission prompt would wait for you until morning. A run that stands still on a prompt, an idle session or an API error alerts you (notification and bell), and `/handover:stats` counts these waits.

### Subagents

Every session that starts on a fresh context (`startup`, `/clear`, compaction) is told to keep its own context for steering and give each self-contained task to a subagent (an investigation across many files, a well-specified change, a test-and-fix loop, a review), with a full brief and a short report back; an AFK run hands each item to one. The main context then fills more slowly, and a session gets more done before it hands over. The `delegate` option turns this off.

A session never hands over, nor is it killed, while its subagents work. Past `suggest_tokens` (or once winding down, or past an AFK deadline) the `PreToolUse` hook refuses new subagents and workflows: the session finishes with the ones already running. A stop while they run is neither the end of the wind-down nor idleness: their results wake the session, and the handover is written after them. A subagent's report can come in before the notice of its end: the handover then waits for the turn that notice starts (20 seconds at most), so that no turn follows `Handover ready`. `request` (the `handover` and `relay` skills) exits 3 while subagents run.

### Background commands

Every Bash command the session runs in the background starts its description with a tag, which the session is told at startup:

- `[await]`: it ends by itself and its result is waited for (a test run, a build, a CI watch). During the wind-down it counts like a subagent: the session ends its turn, and the command's end wakes it. One still running after `await_minutes` (10) is stopped by the plugin, which wakes the session, and treated as endless.
- `[endless]`: it runs until stopped (a dev server, a watcher, `tail -f`). During the wind-down the session is told to stop it with `TaskStop`, not to restart it, and to name it in its reply with how to restart it. One still running at the next stop is killed by the plugin (its process group, a child of the session's `claude` process).

The writer gets the list of the commands stopped, and the handover names each. Stopping a command through `TaskStop` is silent; one killed by the plugin makes Claude Code report its failure and wake the session for one short extra turn, which is why the session is asked first. The handover is written at the stop of that extra turn, once, so that it includes it, and the closing reply follows as usual. With no such turn within 20 s, a watchdog writes the handover and hands over without a closing reply: the status line turns to ready, and a relay resumes with a generic message.

An untagged background command is refused once, with the format. Launched the same way again, it runs, tagged by a guess from its command line (`dev`, `serve`, `watch`, `tail -f` are endless; `test`, `build`, `lint`, `gh run watch` are awaited); a command matching both or neither is taken for endless, so that it is stopped rather than waited for. Each refusal and guess goes to the metrics with the command, its description, whether it came from a subagent and whether the session had been told the tags; `/handover:stats` lists them.

### YOLO

`gmux --afk '<goal>' --yolo` (or `claude-relay --afk … --yolo`) runs without any permission prompt: `--dangerously-skip-permissions`, for a run that must not wait on you at all. Use it on a machine or a project where the worst a wrong command does is acceptable.

What it still holds back:

- **Deny rules.** The run starts with `--settings` from `handover.py yolo-settings`: `Edit` deny rules on the plugin, its data folder (the audit log and the metrics), `~/.claude/plugins`, `~/.claude/hooks` and the user and project `settings.json`/`settings.local.json`. Deny rules apply even when permissions are bypassed, and your own deny rules keep applying. The `yolo_guard_paths` option adds files or folders of yours to the list, a gate the run must not edit to get through for instance; the command guard below covers them too. A `--settings` of yours, a JSON string or a file, gets these rules added and is passed as the run's only `--settings`.
- **A command guard.** A `PreToolUse` hook refuses any write or Bash command naming those paths (`~/…`, `$HOME/…` and real paths alike), or unloading the plugin (`claude plugin disable|uninstall|update`, `disableAllHooks`, `chflags`). The refusal goes to the audit log as `guarded`.
- **An audit log.** Every tool call of the run, subagents included, goes to `audit/<run>.jsonl` in the plugin's data folder: time, session, agent, tool, and its command, path or URL, never file contents. Each line is tagged with whether it would have run without YOLO in your usual mode: `read-only`, `free`, `rule` (the allow rule that covers it), `mode` (acceptEdits or auto allows it), or `prompt`, `classifier`, `protected` for the calls only YOLO let through. The tag mimics Claude Code's permission checks, which a hook cannot see: an estimate.
- **Tamper evidence.** Each audit line chains the hash of the one before; the run's end records the log's length and last hash in `metrics.jsonl`, and its start records a hash of the plugin's hooks and scripts. `/handover:stats` counts the YOLO-only calls per run; `handover.py stats --audit <run>` checks the chain, the length and head at the end, and the plugin hash, and exits 1 on any mismatch.

The limits: this is evidence, not proof. A command can spell a path the guard does not recognise (built from variables, base64, a script it writes first), and a process with your user's rights can rewrite both the log and the metrics consistently. Real isolation needs a container, a VM or a separate user account.

Inside tmux, Claude Code wants `extended-keys` on (Shift+Enter) and `mouse` on (the wheel scrolls tmux's history rather than Claude Code's prompt history).

## The thresholds and how they relate

With the defaults and a 250K `autoCompactWindow`:

```
0 ──────── 150K ──── 165K ──── 185K ──────────────── ~217K ──── 250K
           suggest   status    trigger:              auto-      window
           (nudge)   turns     finish tasks,         compaction
                     yellow    hand over
```

Each step escalates the one before:

| Context reaches | Option | What happens |
|---|---|---|
| 150K | `suggest_tokens` | The session is told, once, to hand over at its next scope boundary. |
| 165K | `trigger_tokens` − `warn_tokens` | The status line turns yellow. |
| 185K | `trigger_tokens` | The session is told to start no new task, finish those in progress and hand over; the handover is written once it has. |
| ~217K | `autoCompactWindow` − `compact_reserve_tokens` | Claude Code compacts; the plugin loads a handover next to the summary. |

The rules that tie them:

- **Suggestion below the trigger.** The suggestion is only given between `suggest_tokens` and `trigger_tokens`; past the trigger, the automatic handover takes over. A `suggest_tokens` at or above `trigger_tokens` is never given.
- **Trigger below compaction.** Auto-compaction fires about `compact_reserve_tokens` (33K) under Claude Code's `autoCompactWindow`, a Claude Code setting, not a plugin one. The default trigger, 185K, suits a 250K window, which compacts near 217K. With the default 200K window, compaction comes near 167K and a 185K trigger never fires: lower it to about 140K, and the suggestion to about 110K.
- **Room to finish the tasks.** Between the trigger and compaction the session finishes its step, the handover is written, and the session writes its reply; the writer reads the transcript from outside, so it takes none of the session's tokens, and the closing reply after it costs a few hundred. A session that runs into compaction anyway gets its handover written from the full transcript just before.
- **What each threshold is for.** `suggest_tokens` is about quality: a fresh session reasons better, so a lower value hands over earlier. `trigger_tokens` is the safety net before compaction.

## Settings

| Option | Default | Meaning | 0 means |
|---|---|---|---|
| `suggest_tokens` | 150000 | Context size at which the session is told to hand over by itself | Never suggest |
| `trigger_tokens` | 185000 | Context size at which the wind-down starts: no new task, those in progress finished, then the handover | No trigger: handovers only when the session asks, and before compaction |
| `await_minutes` | 10 | During the wind-down, how long each `[await]` background command is waited for before the plugin stops it | — |
| `yolo_guard_paths` | (none) | Extra files or folders a YOLO run must not write (spaces or commas between them, `~` allowed) | — |
| `delegate` | true | Tell each session to give self-contained tasks to subagents, so its context fills more slowly | — |
| `writer_model` | `sonnet` | Model that writes the handover (`claude --model` value). `claude -p` runs its default model on a name it does not know: the plugin tells you once, and `metrics.jsonl` records the model used | — |
| `handover_dir` | `~/Notes/claude/agent-handovers` | Base folder of the handovers, written as `YYYY/MM/DD/HHhMM-<topic>.md` | — |
| `handover_chars` | 8000 | Length the writer aims for, 2,000 to 9,500 characters | — |
| `warn_tokens` | 20000 | How far below the trigger the status line turns yellow | No yellow warning |
| `refresh_tokens` | 2000 | A handover this far behind the session is rewritten before it is used | Rewrite on any change |
| `relay_limit` | 5 | Handovers in a chain before it halts for you | — |
| `compact_reserve_tokens` | 33000 | How far below `autoCompactWindow` compaction fires, for `/handover:stats` until real compactions are measured | — |

Change them with `/handover:config`, which asks about each option in turn with its default and current value, in `/config`, which lists one row per option, or in `settings.json`:

```json
{
  "pluginConfigs": {
    "handover@fundrivendev": {
      "options": {
        "suggest_tokens": 120000,
        "trigger_tokens": 140000
      }
    }
  }
}
```

The hooks read the options each time they run. The status line and `/handover:stats` run outside hooks, so they use the values the last hook run saw, kept in `options.json` in the plugin's data folder.

Fixed, not options: the `Stop` hook holds the session up to 240 s for the writer (its timeout in `hooks.json` is 300 s), a new session waits up to 150 s for a handover still in flight, a loaded handover is cut at 9,500 characters (Claude Code moves injected context over 10,000 characters to a file Claude only sees a preview of), the transcript render sent to the writer is capped at 800,000 characters (about 200K tokens), and the writer runs at `medium` effort.

## Status line

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
| `✋ Relay limit · 5 handovers · run /clear` | red | The chain reached `relay_limit` |
| `✋ AFK deadline · 3 handovers · run /clear` | red | An AFK run's deadline passed at a handover |
| `✋ AFK done · <why>` | green | The AFK run ended on `AFK done`; red for `blocked`, `deadline`, `idle`, `exit` |
| `✋ Handover failed · <error>` | red | The writer failed |
| `✋ Handover trigger off` | gray | `trigger_tokens` is 0 |

The line is empty in a session where the plugin is disabled: the plugin's hooks mark each session they run in, from its start to its end, and the status line prints only for those. A status-line script can therefore call it whenever the plugin is installed.

`· loaded` is appended when the session started from a handover (`· relay 3/5` when the relay started it, `· relay 3 · AFK until 08:00` in an AFK run), and `refreshing` replaces `writing` when an existing handover is rewritten.

With the [`statusline`](../statusline/README.md) plugin, the line shows up by itself: the plugin ships an executable `statusline-segment`, which that status line runs for each installed plugin. Otherwise, print it as a second line from your own status-line script:

```bash
payload=$(cat)
# … first line from "$payload" …
hp=$(jq -r '.plugins["handover@fundrivendev"][0].installPath // empty' ~/.claude/plugins/installed_plugins.json)
[ -n "$hp" ] && printf '\n%s' "$(python3 "$hp/scripts/handover.py" statusline <<<"$payload")"
```

## Metrics and tuning

Each step is appended to `metrics.jsonl` in the plugin's data folder: token counts, durations and costs, and the one-line reasons sessions give when they ask for a handover; no transcript content. Auto-compactions are recorded too, whether a handover was under way or not, so the real compaction point is measured rather than estimated.

`/handover:stats` shows, per session, where the suggestion was given, where the trigger fired or the session asked, what the session used closing its work and until `/clear`, the margin left before auto-compaction, the writer's duration, tokens and cost, how long the `Stop` hook held the session for it, and how long the next session waited for a handover still being written; then one row per relay chain: how it was started, its handovers against `relay_limit`, its relays and their duration, stalls, and how it ended; then one row per AFK run: its goal and deadline, sessions, handovers, how often it was sent back, its YOLO-only and guarded calls, its waits (prompts, idle, API errors), denials and stops held for subagents, how it ended and why. `stats --audit <run>` checks a YOLO run's audit log and plugin hash. Read it to tune:

- Trigger cycles ending in `compact-auto`, or a median margin under 15K: lower `trigger_tokens`, or raise `autoCompactWindow`.
- A median margin over 50K with few compactions: room to raise `trigger_tokens`.
- Few handovers asked for by sessions: they wait for the trigger; lower `suggest_tokens` if that is too late.
- Background commands refused or guessed often: read the listed commands; `no tag guidance` means the session started before the tags were announced, `subagent` that a subagent launched it.
- A `load wait s` above 0: the handover was still being written at `/clear` (a session that went on after its closing reply, a writer slower than the `Stop` hook's hold, a compaction).
- `command_timed_out` events: a command tagged `[await]` that did not end in time; mis-tagged, or `await_minutes` too short.
- Relay chains often ending at `limit`: work outlasts `relay_limit`; any `stalled` or `failed` chain is a relay bug or a missing tmux.
- AFK runs ending `idle`, or sent back many times per handover: the goal lacks a clear next item or a definition of done.
- AFK runs with `waits`: something stood still for you; YOLO runs with many YOLO-only calls: read the audit log, and widen the allow list for the ones you would have approved.
- Fewer than 10 cycles: too small a sample to tune anything yet.

[`bench/handover/`](../../bench/handover/README.md) holds the benchmark behind this design. The writer reads the transcript with tool results clipped and messages kept whole.

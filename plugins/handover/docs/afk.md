# AFK mode

A relay that works through a goal while you are away, and its YOLO variant. [Back to the README](../README.md)

For a run that should go on while you are away, overnight for instance, on a sequence of tasks rather than one: implement every open issue of the tracker until nothing is left that can move without you. One task still stops at `relay_limit`; an AFK run does not.

Two ways to start one:

- **A new run:** `toolbox session create --afk '<goal>' [--until <when>] [--yolo] [-- <claude options>]`, which calls `toolbox session run --afk` (see [Relay](relay.md)). The goal is also the first prompt. Outside tmux, the run gets a tmux session of its own, `afk-<folder>`, which outlives its terminal tab: `tmux ls` lists it, `tmux attach -t afk-<folder>` rejoins it.
- **From a running session:** `/handover:afk <goal> [until <when>]`, in a session that already runs in tmux. The session starts on the goal right away; its tmux session stops closing with its tab.

Then:

- **It keeps going.** When a session stops between two tasks, the `Stop` hook sends it back to work with the goal. It hands over at boundaries between tasks, as suggested past `suggest_tokens`, or at `trigger_tokens`, and the relay carries the goal into the next session. No `relay_limit`.
- **It ends when the model says so.** A reply that ends on `AFK done: <why>` (goal met) or `AFK blocked: <why>` (nothing left can move without you) ends the run, with a notification and a terminal bell ([notifier](notifications.md)); a closing reply that carries that line ends it too, and its handover starts no new session. A session sent back three times in a row without doing anything ends it too (`idle`; denied tool calls are not work, and the reason counts them), and so does a session that ends other than by a relayed handover: an exit, a `/clear` of yours, a crash (`exit`).
- **Deadline, optional.** `--until` takes a time (`8`, `8:30`, `8h30`, `8am`: the next one to come, so `8` launched at 23:00 is tomorrow 8:00), a day and a time (`tomorrow 8`, `mon 9:00`), a duration (`+10h`, `in 2h30m`) or a date (`2026-10-06 08:00`). `toolbox session run` prints the deadline it understood. Past it, the session is told to finish its step and end its turn, and no new handover starts.
- **Taking over.** Interrupt with Esc as usual; `/handover:afk off` stops sending the session back, and the relay goes back to `relay_limit`.

AFK runs are unattended: start them with the permissions they need (an auto or accept-edits mode, an allow list), since a permission prompt would wait for you until morning. A run that stands still on a prompt, an idle session or an API error alerts you (notification and bell), and `/handover:stats` counts these waits.

## YOLO

`toolbox session create --afk --yolo '<goal>'` (or `toolbox session run --afk '<goal>' --yolo`) runs without any permission prompt: `--dangerously-skip-permissions`, for a run that must not wait on you at all. Use it on a machine or a project where the worst a wrong command does is acceptable.

What it still holds back:

- **Deny rules.** The run starts with `--settings` from `handover.py yolo-settings`: `Edit` deny rules on the plugin, its data folder (the audit log and the metrics), `~/.claude/plugins`, `~/.claude/hooks` and the user and project `settings.json`/`settings.local.json`. Deny rules apply even when permissions are bypassed, and your own deny rules keep applying. The `yolo_guard_paths` option adds files or folders of yours to the list, a gate the run must not edit to get through for instance; the command guard below covers them too. A `--settings` of yours, a JSON string or a file, gets these rules added and is passed as the run's only `--settings`.
- **A command guard.** A `PreToolUse` hook refuses any write or Bash command naming those paths (`~/…`, `$HOME/…` and real paths alike), or unloading the plugin (`claude plugin disable|uninstall|update`, `disableAllHooks`, `chflags`). The plugin's own `request`, `status` and `stats` commands pass when called alone (no expansion, redirection or chained command), so the run can still hand over. The refusal goes to the audit log as `guarded`.
- **An audit log.** Every tool call of the run, subagents included, goes to `audit/<run>.jsonl` in the plugin's data folder: time, session, agent, tool, and its command, path or URL, never file contents. Each line is tagged with whether it would have run without YOLO in your usual mode: `read-only`, `free`, `rule` (the allow rule that covers it), `mode` (acceptEdits or auto allows it), or `prompt`, `classifier`, `protected` for the calls only YOLO let through. The tag mimics Claude Code's permission checks, which a hook cannot see: an estimate.
- **Tamper evidence.** Each audit line chains the hash of the one before; the run's end records the log's length and last hash in `metrics.jsonl`, and its start records a hash of the plugin's hooks and scripts. `/handover:stats` counts the YOLO-only calls per run; `handover.py stats --audit <run>` checks the chain, the length and head at the end, and the plugin hash, and exits 1 on any mismatch.

The limits: this is evidence, not proof. A command can spell a path the guard does not recognise (built from variables, base64, a script it writes first), and a process with your user's rights can rewrite both the log and the metrics consistently. Real isolation needs a container, a VM or a separate user account.

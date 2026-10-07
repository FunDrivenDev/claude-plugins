---
name: stats
description: Show the token metrics of past handovers (where the trigger fired, what the session used while the handover was written, margin left before auto-compaction) and of relay chains (how far each went, how each relay went, how it ended), to tune trigger_tokens and the relay.
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# Handover stats

Run:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" stats
```

Show the tables as they are. In the first, one row is one cycle of a session, from the trigger to `/clear`, exit or compaction. Token columns are context sizes of the main session:

- `suggested`: where the session was told to hand over by itself (`suggest_tokens`); `wind-down`: where its wind-down started, at the trigger or at its own request (`cause` `model` or `user`); `notified`: where the user was told.
- `reply`: where the session, its work closed, wrote its closing reply; `+wind-down`: what the session used between `wind-down` and that point, closing its step and waiting for its subagents; `ready`: where the handover was written, from then.
- `end at`: where the cycle ended, and how (`clear`, `prompt_input_exit`, `compact-auto`…); `+total`: what the session used after its wind-down started.
- `margin`: room left before auto-compaction when the cycle ended by hand.
- `write s`: seconds the writer took for the first handover; `hold s`: seconds the `Stop` hook held the session while that handover was written, before its closing reply; `load wait s`: seconds the next session waited for a handover still being written (0 when it was ready); `writer in/out`: tokens of the separate writer model, over all its runs in the cycle.

The `Relay chains` table, when there is one, has one row per chain of sessions the relay handed over without the user, named after its first handover file (`YYYY/MM/DD/HHhMM-<topic>`):

- `start`: how the chain was started, `claude-relay` (the whole session) or `skill` (`/handover:relay` or `/handover:afk`); a `claude-relay --afk` run counts as `claude-relay`.
- `handovers`: handovers written in the chain, over `relay_limit`; `relays`: sessions relayed; `mode`: `tmux` (keys typed into the pane) or `loop` (claude-relay restarted claude); `resumed`: new sessions that got their resume message.
- `relay s`: median seconds from the relay starting to the new session resuming; `handover at`: median context size where the chain's handovers were written.
- `stalls`: new sessions that did not load the handover in time.
- `end`: `limit` (halted at `relay_limit`, waiting for `/clear`), `stalled`, `failed` (a session neither in tmux nor under claude-relay), how its last session ended (`clear`, `prompt_input_exit`, `compact-auto`…), or `open` while it runs; `min`: minutes from its first to its last event; `$`: writer cost over the chain.

The `AFK runs` table, when there is one, has one row per AFK run (`claude-relay --afk` or `/handover:afk`), with its goal and how it ended under the table:

- `how`: `claude-relay` or `skill`; `until`: the deadline, if any; `sessions` and `handovers` over the whole run.
- `sent back`: stops the `Stop` hook sent back to work.
- `yolo`: in a `--yolo` run, calls only YOLO let through (`prompt`, `classifier`, `protected` in the audit log) over all audited calls; `guarded`: calls the command guard refused (a write to the plugin, its data or the settings).
- `waits`: times the run stood still for the user (a permission prompt, an idle prompt, an API error); `denied`: calls auto mode denied; `agent waits`: turn ends held while subagents ran.
- `end`: `done` or `blocked` (declared by the model, reason below), `deadline`, `idle` (sent back three times in a row without working), `off`, `exit` (its session ended other than by a relayed handover), or `open`; `hours`: from its start to its last event.

Then read it in two or three sentences:

- Cycles whose wind-down the trigger started that end in `compact-auto`, or a median margin under 15K: the trigger is too close to compaction; suggest lowering `trigger_tokens` or raising `autoCompactWindow`.
- A median margin over 50K with few compactions: there is room to raise `trigger_tokens`.
- Background commands refused, guessed (`unsure` above all) or given up on (`command_timed_out`): quote the commands listed, and say whether the tags were missing from sessions told about them, from subagents, or from sessions that started without the guidance.
- A `load wait s` above 0: the handover was still being written at `/clear` (a session that went on after its closing reply, a writer slower than the `Stop` hook's hold, a compaction); name the cycles.
- Median `write s` under twice the status line's `refreshInterval`: the status row shows only one or two writer updates; suggest a shorter `refreshInterval` if the user wants to follow it.
- Handovers a session asked for: compare their median point with `suggest_tokens` and with the trigger; few or none means agents wait for the trigger.
- Relay chains: chains that end at `limit` mean work regularly outlasts `relay_limit`; check whether their last handovers still name concrete next steps before suggesting to raise it. Any `stalled` or `failed` chain is a relay bug or a setup gap (no tmux, no claude-relay): name it. A median relay over 30s, or `resumed` short of `relays`, points at the relay's waits. A low share of resume messages taken from the reply means sessions skip the closing reply.
- AFK runs: `blocked` runs list what needs the user, so quote their reasons. Runs ending `idle`, or with many `sent back` per handover, mean the goal gives no clear next item or definition of done; suggest wording it as a list to work through and a condition to stop on. Runs ending `deadline` with work left are fine.
- AFK runs with `waits`: name what stood still. A YOLO run with `guarded` calls tried to touch the plugin or the settings: say so. For a YOLO run, offer to check it with `handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" stats --audit <run>` (hash chain, length at the end, plugin hash; exit 1 on a mismatch), and suggest allow rules for the YOLO-only calls the user would have approved.
- Fewer than 10 cycles: say the sample is too small to tune anything yet.

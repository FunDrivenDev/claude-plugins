# Metrics and tuning

What the plugin records, `/handover:stats`, and how to tune the thresholds from it. [Back to the README](../README.md)

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

[`bench/handover/`](../../../bench/handover/README.md) holds the benchmark behind this design. The writer reads the transcript with tool results clipped and messages kept whole.

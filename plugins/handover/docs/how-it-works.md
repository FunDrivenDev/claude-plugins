# How it works

From the suggestion to the next session, and what the wind-down waits for. [Back to the README](../README.md)

Words used below: the *handover* is the document the separate model writes, and a session *hands over* when a fresh one takes over from it; the *wind-down* is the session's last stretch before that: no new task, the tasks in progress finished, background commands waited for or stopped; then the handover is written, and only then does the session write its *closing reply* (`Ready to hand over: run /clear.` and the message to resume).


- **Suggestion.** Once the context passes `suggest_tokens`, the session is told, once, to hand over by itself at the next boundary between scopes: a task done, a PR pushed, before an unrelated task or a long new investigation. It calls the `handover` skill, which is for the model only and hidden from the `/` menu, with a one-line reason. Nothing is forced: the session picks the moment.
- **On demand.** `/handover:trigger [focus]` starts the same wind-down at once, without waiting for `trigger_tokens`. The optional focus is what the next session should work on; the writer opens the handover's next steps with it and keeps what that work needs. Without it, the next steps follow from where the session stopped. For example:
  - `/handover:trigger` — carry on where this session stops;
  - `/handover:trigger address the review comments on PR #12` — the PR is open, its review comes next;
  - `/handover:trigger debug the flaky login test, leave the refactor aside` — narrow the next session to one thread;
  - `/handover:trigger write the migration plan before any code` — change the kind of work.
- **Trigger.** Once the context passes `trigger_tokens`, the session is told not to start a new task, to finish every task in progress (the current step, its subagents, its `[await]` background commands), to stop its `[endless]` ones, and then to end its turn on one line saying where the work stands, without the closing reply yet.
- **Writing.** At that stop, with nothing left running, the `Stop` hook has a separate `claude -p` write the handover from the complete transcript, on `writer_model`, for about $0.15, and holds the session until it is written: 15 to 25 s in the measured runs, the status line showing the writer's progress. The handover goes to `handover_dir`. Written while the work went on, it would miss its end. Esc during that hold interrupts the session, not the writer: the handover still lands, and the next stop asks for the closing reply.
- **Closing reply.** The hook then blocks that stop and tells the session the handover is written: it now writes its closing reply, the handover's full path, `Ready to hand over: run /clear.` and, in a code block, the message to send after `/clear`. So that reply only appears once the handover exists, and the status line turns to `Handover ready` only after it. A session that ends its turn without it is asked once more.
- **Background commands.** Tagged at launch, they tell the wind-down what to wait for and what to stop: see [Background commands](#background-commands).
- **`/clear`.** The handover, already written, is loaded into the new session at once. The new session still waits, up to 150 s, where a handover can legitimately be in flight: a session that went on past `refresh_tokens` after its closing reply gets it refreshed at `/clear`; a writer that outlasts the `Stop` hook's 240 s hold leaves the session to close while it finishes. Claude Code gives hooks no way to run `/clear` itself, so that keystroke stays yours.
- **Writer failure.** The session is told, writes its closing reply all the same with a resume message complete enough to go on without the handover, and ends; the stop after that reply tries the writer once more. The status line shows the error, and a relay halts with an alert rather than start a session without a handover.
- **Auto-compaction.** A handover is written in parallel and loaded next to the built-in summary, the compacted session waiting for it up to 150 s. The suggestion and the trigger are then reset, for the session starts over from a small context.
- **Exit.** The handover is refreshed in the background if the session went on, and the next session in the same project is pointed to it once written.
- **Relay.** Under `toolbox session run` (the toolbox CLI), the `/clear` is no longer yours: see [Relay](relay.md).
- **AFK.** A relay that works through a goal while you are away, past `relay_limit`: see [AFK mode](afk.md).

## Subagents

Every session that starts on a fresh context (`startup`, `/clear`, compaction) is told to keep its own context for steering and give each self-contained task to a subagent (an investigation across many files, a well-specified change, a test-and-fix loop, a review), with a full brief and a short report back; an AFK run hands each item to one. The main context then fills more slowly, and a session gets more done before it hands over. The `delegate` option turns this off.

A session never hands over, nor is it killed, while its subagents work. Past `suggest_tokens` (or once winding down, or past an AFK deadline) the `PreToolUse` hook refuses new subagents and workflows: the session finishes with the ones already running. A stop while they run is neither the end of the wind-down nor idleness: their results wake the session, and the handover is written after them. A subagent's report can come in before the notice of its end: the handover then waits for the turn that notice starts (20 seconds at most), so that no turn follows `Handover ready`. `request` (the `handover`, `trigger` and `relay` skills) never refuses for subagents: the count it keeps from `SubagentStart` and `SubagentStop` can still hold one stopped with `TaskStop`, which may get no `SubagentStop`. It starts the wind-down, tells the session that subagents may still run, and the `Stop` hook, which reads the running ones from Claude Code, waits for those.

## Background commands

Every Bash command the session runs in the background starts its description with a tag, which the session is told at startup:

- `[await]`: it ends by itself and its result is waited for (a test run, a build, a CI watch). During the wind-down it counts like a subagent: the session ends its turn, and the command's end wakes it. One still running after `await_minutes` (10) is stopped by the plugin, which wakes the session, and treated as endless.
- `[endless]`: it runs until stopped (a dev server, a watcher, `tail -f`). During the wind-down the session is told to stop it with `TaskStop`, not to restart it, and to name it in its reply with how to restart it. One still running at the next stop is killed by the plugin (its process group, a child of the session's `claude` process).

The writer gets the list of the commands stopped, and the handover names each. Stopping a command through `TaskStop` is silent; one killed by the plugin makes Claude Code report its failure and wake the session for one short extra turn, which is why the session is asked first. The handover is written at the stop of that extra turn, once, so that it includes it, and the closing reply follows as usual. With no such turn within 20 s, a watchdog writes the handover and hands over without a closing reply: the status line turns to ready, and a relay resumes with a generic message.

An untagged background command is refused once, with the format. Launched the same way again, it runs, tagged by a guess from its command line (`dev`, `serve`, `watch`, `tail -f` are endless; `test`, `build`, `lint`, `gh run watch` are awaited); a command matching both or neither is taken for endless, so that it is stopped rather than waited for. Each refusal and guess goes to the metrics with the command, its description, whether it came from a subagent and whether the session had been told the tags; `/handover:stats` lists them.

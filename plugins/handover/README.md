# handover

Takes over from auto-compaction before the context fills up: a separate model writes a handover of the session from its transcript, and `/clear` starts a fresh session from it. The session winds down first (no new task, the work in progress and its sub-agents finished), so the handover catches where the work really stands.

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install handover@fundrivendev
```

Coming from `handover@fundriven` or `handoff`: see [Migrating from older versions](docs/migration.md).

## Features

- **Suggestion**: past 150k tokens, the session is told once to hand over by itself at its next boundary between tasks.
- **Trigger**: past 185k, the session starts no new task, finishes the ones in progress, then hands over.
- **On demand**: `/handover:trigger [focus]` hands over at once, optionally naming what the next session should work on.
- **Separate writer**: a `claude -p` on Sonnet writes the handover from the full transcript in about 20 s, for about $0.15, outside the session's context.
- **Closing reply**: once the handover exists, the session ends on the handover's full path, `Ready to hand over: run /clear.` and the message to resume with.
- **Load on `/clear`**: the next session starts with the handover already in its context.
- **Background commands**: `[await]` and `[endless]` tags tell the wind-down which commands to wait for and which to stop.
- **Compaction safety net**: an auto-compaction still gets a handover loaded next to its summary.
- **Relay**: under tmux, the plugin types `/clear` and the resume message itself, up to 5 handovers in a chain.
- **AFK mode**: a relay that works through a goal while you are away, until done, blocked or a deadline, optionally in YOLO with guards and an audit log.
- **Status line**: a one-line handover state for your status line, from the threshold to `Handover ready`.
- **Notifications**: a desktop notification on macOS and Linux, or your own command (Slack, ntfy) when away or headless; `handover.py notifier --test` checks it.
- **Metrics**: `/handover:stats` reports margins, writer cost and duration, relay chains and AFK runs, to tune the thresholds.

## Documentation

- [How it works](docs/how-it-works.md): the wind-down, the writer, `/clear`, sub-agents and background commands
- [Relay](docs/relay.md): automatic `/clear` under tmux, started with the `toolbox session` commands
- [AFK mode](docs/afk.md): unattended runs on a goal, deadlines, YOLO
- [Settings](docs/settings.md): the thresholds, how they relate, and every option
- [Notifications](docs/notifications.md): how alerts reach you on macOS, a Linux desktop, a headless server or Slack
- [Status line](docs/status-line.md): the handover state line and how to print it
- [Metrics and tuning](docs/metrics.md): `/handover:stats` and what to change from it
- [Migrating from older versions](docs/migration.md): from the `fundriven` marketplace or the `handoff` name

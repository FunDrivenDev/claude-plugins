# Settings

The token thresholds, how they relate, and every option. [Back to the README](../README.md)

## The thresholds and how they relate

With the defaults and a 500K `autoCompactWindow`:

```
0 ──────── 200K ──── 230K ──── 250K ──────────────── ~467K ──── 500K
           suggest   status    trigger:              auto-      window
           (nudge)   turns     finish tasks,         compaction
                     yellow    hand over
```

Each step escalates the one before:

| Context reaches | Option | What happens |
|---|---|---|
| 200K | `suggest_tokens` | The session is told, once, to hand over at its next scope boundary. |
| 230K | `trigger_tokens` − `warn_tokens` | The status line turns yellow. |
| 250K | `trigger_tokens` | The session is told to start no new task, finish those in progress and hand over; the handover is written once it has. |
| ~467K | `autoCompactWindow` − `compact_reserve_tokens` | Claude Code compacts; the plugin loads a handover next to the summary. |

The rules that tie them:

- **Suggestion below the trigger.** The suggestion is only given between `suggest_tokens` and `trigger_tokens`; past the trigger, the automatic handover takes over. A `suggest_tokens` at or above `trigger_tokens` is never given.
- **Trigger below compaction.** Auto-compaction fires about `compact_reserve_tokens` (33K) under Claude Code's `autoCompactWindow`, a Claude Code setting, not a plugin one. The default trigger, 250K, needs a window above 283K; it suits a 500K window, which compacts near 467K. With a 250K window, compaction comes near 217K and a 250K trigger never fires: lower it to about 185K, and the suggestion to about 150K. With the default 200K window, lower them to about 140K and 110K. Each session start checks it: when auto-compaction is on (`autoCompactEnabled` in `~/.claude.json` or the user, project and local settings) and fires at or before `trigger_tokens`, the user and the session get a warning naming the window to set.
- **Room to finish the tasks.** Between the trigger and compaction the session finishes its step, the handover is written, and the session writes its reply; the writer reads the transcript from outside, so it takes none of the session's tokens, and the closing reply after it costs 2K to 4K, its reasoning included. A session that runs into compaction anyway gets its handover written from the full transcript just before.
- **What each threshold is for.** `suggest_tokens` is about quality: a fresh session reasons better, so a lower value hands over earlier. `trigger_tokens` is the safety net before compaction.

## Options

| Option | Default | Meaning | 0 means |
|---|---|---|---|
| `suggest_tokens` | 200000 | Context size at which the session is told to hand over by itself | Never suggest |
| `trigger_tokens` | 250000 | Context size at which the wind-down starts: no new task, those in progress finished, then the handover | No trigger: handovers only when the session asks, and before compaction |
| `await_minutes` | 10 | During the wind-down, how long each `[await]` background command is waited for before the plugin stops it | — |
| `yolo_guard_paths` | (none) | Extra files or folders a YOLO run must not write (spaces or commas between them, `~` allowed) | — |
| `delegate` | true | Tell each session to give self-contained tasks to subagents, so its context fills more slowly | — |
| `writer_model` | `sonnet` | Model that writes the handover (`claude --model` value). `claude -p` runs its default model on a name it does not know: the plugin tells you once, and `metrics.jsonl` records the model used | — |
| `handover_dir` | `~/Notes/claude/agent-handovers` | Base folder of the handovers, written as `YYYY/MM/DD/HHhMM-<topic>.md` | — |
| `handover_chars` | 8000 | Length the writer aims for, 2,000 to 9,500 characters | — |
| `warn_tokens` | 20000 | How far below the trigger the status line turns yellow | No yellow warning |
| `refresh_tokens` | 2000 | A handover this far behind the session is rewritten before it is used; the closing reply alone never counts | Rewrite on any change |
| `relay_limit` | 10 | Handovers in a chain before it halts for you | — |
| `compact_reserve_tokens` | 33000 | How far below `autoCompactWindow` compaction fires, for `/handover:stats` until real compactions are measured | — |
| `notifier` | `auto` | How an alert calls you back, on top of the terminal bell: `auto` (the desktop notification of the environment, plus `notify_command` when set), `macos`, `linux`, `command` or `bell` ([Notifications](notifications.md)) | — |
| `notify_command` | (none) | A command `sh` runs for each alert, `HANDOVER_TITLE` and `HANDOVER_MESSAGE` in its environment | — |

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


# session-panel

A calm side pane for a Claude Code session: what runs, since when, how warm the prompt cache still is, and what every sub-agent was asked and did.

```
Opus 5.5 · effort high
running 1h 12m   cache 54m 03s left (1h)
sub-agent session no, they run inside this session

Prompt
Build a mod that is a side panel…

Steps
▸ 37 earlier steps
✓ Bash: just validate
○ Thinking…

Running · 1                     Done · 2
▸ Find hooks                    ▸ Review diff
Explore · Sonnet 5.5 · 42s      general-purpose · 3m 10s
Find the hooks that…            Review the changes…
› Grep: turn.step               “ No issue found.
```

- **Header**: the main loop's model and effort, the session's age, the time left before the prompt cache expires (yellow under a minute, then how long ago it expired), and whether sub-agents run in sessions of their own (teammates) or inside this one.
- **Prompt**: the session's first prompt.
- **Steps**: one line per model request of the main loop, named by what it ran (`Bash: just validate`, `Read: src/main.rs`), or else the first sentence of its thinking or text; ✓ once answered. Only the two latest show, the earlier ones folded into one line you press to unfold, so the list never pushes the sub-agents down.
- **Running / Done**: each sub-agent with its type, model, age, the task it was given and its last entries (thinking `∴`, text `“`, tool calls `›`, results `⎿`, errors `✗`). Press its name to expand the full task and history. A finished one moves to the greyed Done column.

It is a mod: a plugin of function hooks, drawn by the engine (no shell script, no status line).

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install session-panel@fundrivendev
```

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `cacheTtl` | `1h` | The prompt-cache lifetime the countdown starts from (`1h` or `5m`), until a model switch reports the real one. In `/config`. |

## Limits

- Steps and sub-agents are recorded from the moment the plugin loads; the first prompt is read back from the transcript.
- The TTL is not reported per request: the countdown uses the setting until a model switch tells the real one.

## Developing

`claude plugin test plugins/session-panel` runs `tests/`; `just validate` runs it with the validator. Once Claude Code has loaded the plugin, `tsc -p plugins/session-panel` type-checks it against the types the engine lays in `.claude-plugin/types/` (ignored by git).

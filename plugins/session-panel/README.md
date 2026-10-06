# session-panel

A calm side pane for a Claude Code session: what runs, since when, how warm the prompt cache still is, and what every sub-agent was asked and did.

```
╭────────────╮ ╭────────────╮
│ ○ Opus 5.5 │ │ ○ high 3/5 │
╰────────────╯ ╰────────────╯
running 1h 12m   cache 54m 03s left (1h)
sub-agent session no, they run inside this session

Last prompt (7)
Strip the XML tags and show only the last prompt…

Steps
▸ 37 earlier steps · 2 refused · 1 repeated
✓ Sync, validate, commit, push, update PR
    cp … && just validate && git commit …
✗ Add file-tree tests and run them
    failed: AssertionError: expect(received).toEqual()

Running · 1                     Done · 2
▸ Find hooks                    ▸ Review diff
Explore · Sonnet 5.5 · 42s      general-purpose · 3m 10s
Find the hooks that…            Review the changes…
› Grep: turn.step               “ No issue found.

Files
claude-plugins +412 −3
├ plugins/session-panel/
│ ├ + README.md +58
│ └ hooks/
│   └ ~ register.tsx +40 −6
└ ~ README.md +1 −1
```

- **Selectors**: the main loop's model and effort as two rounded pills, the model in its colour (Catppuccin Frappé: Opus peach, Fable mauve, Sonnet blue, Haiku green), the effort in the colour `/effort` gives its level. Press one to open its choices, press a choice to switch (it runs `/model` or `/effort`).
- **Header**: the session's age, the time left before the prompt cache expires (yellow under a minute, then how long ago it expired), and whether sub-agents run in sessions of their own (teammates) or inside this one.
- **Last prompt**: the last prompt you typed, without the tags the engine wraps around it; slash commands are left out. Press the count beside it to see every prompt of the session, then `← Overview` to come back.
- **Steps**: an audit trail of the main loop, one entry per model request: what it did in the agent's own words (a Bash call's description, `Edit register.tsx`), and beneath it how (the command or path), or why it was refused or failed. `↻ ×N` marks the same action taken again within a few steps, a sign of a loop; `✗` a refused or failed call. Only the two latest show; the earlier ones fold into one line that counts their refusals, failures and repeats, and unfolds with the reasoning (`∴`) of each.
- **Files**, at the bottom: the changes against `HEAD` of the session's repository and of every repository a tool edited in (worktrees included), as a tree following the hierarchy; `+` added, `~` modified, `−` deleted, with the lines added in green and removed in red. Refreshed after each edit or Bash command.
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

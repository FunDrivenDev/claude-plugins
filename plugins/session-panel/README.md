# session-panel

A calm side pane for a Claude Code session: what runs, since when, how warm the prompt cache still is, and what every sub-agent was asked and did.

```
╭────────────╮ ╭────────────╮        ◉ Publish the session-panel mod
│ ○ Opus 5.5 │ │ ○ high 3/5 │        ⎇ claude-plugins #7 draft
╰────────────╯ ╰────────────╯
running 1h 12m   cache 54m 03s left (1h)

Last prompt (7)
Strip the XML tags and show only the last prompt…

Handover
✋ triggers at 185k · now 92k
loaded session-panel tracker/PR corner

Steps
▸ 37 earlier steps · 2 refused · 1 repeated
✓ Sync, validate, commit, push, update PR

✗ Add file-tree tests and run them
    failed: AssertionError: expect(received).toEqual()

● Searching engine types for link support

Sub-agents · 1 running · 1 done
▸ Find hooks
  sub-agent · 42s · Grep: turn.step
▸ Review diff
  background · 3m 10s · done

Files and history
claude-plugins ⎇ feat/session-panel +412 −3
├ plugins/session-panel/          ○ session-panel: tracker corner
│ ├ + README.md +58                 3f2a1bc · 2m 10s ago · local
│ └ hooks/                        ● session-panel: steps as an audit…
│   └ ~ register.tsx +40 −6         2ad70a1 · 1h 05m ago · pushed
└ ~ README.md +1 −1
```

- **Selectors**: the main loop's model and effort as two rounded pills, the model in its colour (Catppuccin Frappé: Opus peach, Fable mauve, Sonnet blue, Haiku green), the effort in the colour `/effort` gives its level. Press one to open its choices, press a choice to switch (it runs `/model` or `/effort`).
- **Header**: the session's age and the time left before the prompt cache expires (yellow under a minute, then how long ago it expired).
- **Issue and pull request**, top right: the tracker issue the session is about, with its platform's icon (GitHub `◉`, Linear `◐`) and its title, and its pull request as `repo #N` in GitHub's colours (grey draft, green open, red closed, purple merged), both clickable. The issue is the one your prompt names, else the one the session opened (`gh issue create`, a Linear tool's `create`), else one it worked on; the same for the pull request. GitHub items are read with `gh api`, the pull request's state again every minute. A Linear issue opens in the desktop app (`linear://`) where it is installed, else on linear.app; a bare `KEY-N` in a prompt counts once a Linear tool shows it, so an It's a Plan key is never taken for a Linear one.
- **Handover**: what the `handover` plugin's status line says (when the handover triggers, or that it is ready or writing), and the handover this session loaded and the one it wrote, each by its title (front matter `summary`, else its `# Handover:` heading) and linked to its file.
- **Last prompt**: the last prompt you typed, without the tags the engine wraps around it; slash commands are left out. Press the count beside it to see every prompt of the session, then `← Overview` to come back.
- **Steps**: an audit trail of the main loop, one entry per model request: what it did in the agent's own words (a Bash call's description, `Edit register.tsx`), printed in full with a blank line between steps, and beneath it why it was refused or failed when it was. `↻ ×N` marks the same action taken again within a few steps, a sign of a loop; `✗` a refused or failed call. The current step shows live, its latest whole sentence while the model thinks, then the call it runs until it returns, under the four latest finished steps, all in full; the earlier ones fold into one line that counts their refusals, failures and repeats, and unfolds with the reasoning (`∴`) of each.
- **Sub-agents**: how many run and are done, then one line per sub-agent, background agent or teammate: its mission, its kind, its age and what it is doing now (its last call or thought). Press one to expand its full task and history.
- **Files and history**, at the bottom: for the session's repository and every repository a tool edited in (worktrees included), the changes against `HEAD` as a tree (`+` added, `~` modified, `−` deleted, lines added in green and removed in red), and beside them the branch's latest commits by subject, `○` local or `●` pushed; press a commit to read its body. Refreshed after each edit or Bash command.

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
- The handover thresholds come from the handover plugin's `options.json` or its defaults (150k suggested, 185k trigger), not from `CLAUDE_PLUGIN_OPTION_*` overrides.
- The TTL is not reported per request: the countdown uses the setting until a model switch tells the real one.

## Developing

`claude plugin test plugins/session-panel` runs `tests/`; `just validate` runs it with the validator. Once Claude Code has loaded the plugin, `tsc -p plugins/session-panel` type-checks it against the types the engine lays in `.claude-plugin/types/` (ignored by git).

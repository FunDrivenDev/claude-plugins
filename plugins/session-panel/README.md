# session-panel

A calm side pane for a Claude Code session: what runs, since when, how warm the prompt cache still is, and what every sub-agent was asked and did.

```
Session panel tabs and topic title
╭──────╮ ╭──────╮ ╭────────╮ ╭──────╮  ╭────────────╮ ╭────────────╮ ╭─────╮
│ Main │ │ Misc │ │ Config │ │ Help │  │ ○ Opus 5.5 │ │ ○ high │ │  ✕  │
╰──────╯ ╰──────╯ ╰────────╯ ╰──────╯  ╰────────────╯ ╰────────────╯ ╰─────╯
⌛ running 1h12m   ⏳ cache 54m          ◉ Publish the session-panel mod
context 78.2k/217k (250k − 33k) 36%       ⎇ claude-plugins #7 draft
                                            ▣ session-panel-fixes

5h 30% →60%       🔄 2h30m   7d 71% out in 1d21h  🔄 2d07h
━━━━━━━┃────────────────────   ━━━━━━━━━━━━━━━━━━┃━━╸──────

Documents
Agent handovers
  21h57-session-panel-0-8-0
Reports
  26-10-06-claude-plugins-ci-ok-merge-wrap-up

Handover

loaded session-panel tracker/PR corner (142 lines · 2026-10-07 09:32)

✋ triggers at 185k · now 92k

Last prompt 14:32 (6 previous prompts)
Strip the XML tags and show only the last prompt…

── Misc ──
Steps ▸ 37 earlier · 2 refused · 1 repeated
✓ Sync, validate, commit, push, update PR
✗ Add file-tree tests and run them
    failed: AssertionError: expect(received).toEqual()
● Searching engine types for link support

Sub-agents · 1 running · 1 done
▸ Find hooks
  sub-agent · 42s · Grep: turn.step
▸ Review diff
  background · 3m 10s · done

Git diff
claude-plugins ⎇ feat/session-panel +412 −3
├ plugins/session-panel/
│ ├ + README.md +58
│ └ hooks/
│   └ ~ register.tsx +40 −6
└ ~ README.md +1 −1

Git History
○ session-panel: tracker corner
  3f2a1bc · 2 min ago · local
● session-panel: steps as an audit trail, last prompt with its history
  2ad70a1 · 1 hour ago · pushed
```

- **Top lines**: the session's title, its overall topic in a few words, on a line of its own; beneath, the tabs on the left, then the model and effort selectors beside the quota pill, and a close mark. The main agent names the topic with the plugin's `session_title` tool, once the first task is clear and again only when what the session is about changes significantly; once its turn ends, the title also goes to `/rename`, which names the session in `/resume` and the terminal tab. A session started from a handover takes the handover's title (its front matter `summary`, else its `# Handover:` heading) as soon as it has loaded, renamed at once, until the agent names it. A session that has no title of its own yet (Claude Code carries the previous name through `/clear` and a plugin reload) has its first typed prompt carry a one-line reminder to set one. `Session` until it has a title. **Main** shows the session at a glance (everything down to Documents, Handover and Last prompt, in that order); **Misc** shows the steps, the sub-agents and the git diff; **Config** lists each value the pane reads (its own `cacheTtl` option, Claude Code's `autoCompactWindow` and `plansDirectory`, `CC_TOKEN_LIMIT` and `CC_TOKEN_RESERVE`, the handover plugin's `handover_dir` and token thresholds), as in effect, with what it does and its default; **Help** explains each item of the pane, its colours and states, one per line: an example as the pane draws it, then greyed what it shows or does (the title, the model and effort selectors and the tabs, self-evident, are left out). `✕`, framed so it is easy to hit, closes the pane; `/session-panel` reopens it on Main.
- **Colours**: Catppuccin Frappé and the status line's bright tones on a dark macOS appearance; on a light one, every colour turns to its twin that reads on white (Catppuccin Latte, darker tones for the status line's yellow and orange), following the system setting within five seconds. Off macOS, the dark palette.
- **Selectors**: the main loop's model and effort as two rounded pills beside the tabs, selected from the session's start (the model `/model` shows, the effort `/effort` saved), the model in its colour (Catppuccin Frappé: Opus peach, Fable mauve, Sonnet blue, Haiku green), the effort in the colour `/effort` gives its level. Press one to open its choices, press a choice to switch (it runs `/model` or `/effort`).
- **Header**: the session's age (`⌛`) and the whole minutes left before the prompt cache expires (`⏳`), graded as in the status line (green down to half the TTL, yellow down to a fifth, then orange; red once expired). Beneath, the context counter: the tokens in the window against the auto-compact trigger the engine sets from your `autoCompactWindow` (the figures `/context` uses), followed in brackets by how it is reckoned, the window less Claude Code's margin (`217k (250k − 33k)`); where the engine gives none, the status line's reckoning (`CC_TOKEN_LIMIT`, else `autoCompactWindow`, else 200k, less `CC_TOKEN_RESERVE`, 33k by default). The grading follows that trigger, whatever its size: green up to half of it, yellow to three quarters, orange to nine tenths, then red, and `⚠ compacting` once reached.
- **Quotas**: one pill beside the close mark, `● 5h 30% │ ● 7d 71%`, each window's use with a dot in its verdict's colour, then `🔽`; press it (anywhere but its dots) to unfold, beneath the top lines, the 5-hour and 7-day windows as bars that fill with use, read as the status line reads them: the `┃` tick marks where even spending would be by now, fill up to it is green and fill past it takes the verdict's colour and breathes once a second; the verdict extrapolates the average burn to the reset (`→N%` green under 90%, yellow from 90%, `out in D` red when the limit comes first), judged once a tenth of the window has passed; `🔄` is the time to the reset. The two bars sit side by side, half the width each; press the pill again (its arrow now `🔼`) to fold them. Absent off a subscription.
- **Issue and pull request**, top right: the tracker issue the session is about, with its platform's icon (GitHub `◉`, Linear `◐`) and its title, and its pull request as `repo #N` in GitHub's colours (lavender draft, a lighter tone than GitHub's grey so it reads, green open, red closed, purple merged), both clickable, and beneath them the linked worktree the session last edited in (`▣ name`), or `main checkout`. The issue is the one your prompt names, else the one the session opened (`gh issue create`, a Linear tool's `create`), else one it worked on; the same for the pull request. A bare `#N` in a prompt (a numbered list's `#1, #2`) counts below any reference the session worked on, and the pane reads the whole transcript again when it loads, so a plugin loaded mid-session finds the references made before it. Both underline on hover, linked. GitHub items are read with `gh api`, the pull request's state again every minute. A Linear issue opens in the desktop app (`linear://`) where it is installed, else on linear.app; a bare `KEY-N` in a prompt counts once a Linear tool shows it, so an It's a Plan key is never taken for a Linear one.
- **Documents**: what the session wrote that lasts, grouped by kind: the artifacts it published (linked to claude.ai), then the handovers (in the handover plugin's `handover_dir`, `~/Notes/claude/agent-handovers` by default), then the plans (in Claude Code's `plansDirectory`, `~/.claude/plans` by default), then any other Markdown file the agent wrote outside the project's repository, temporary and hidden folders, under its folder's name. A file counts once an editing tool wrote it, a shell command named it by an absolute or `~` path and it changed since the session began, or the handover plugin wrote it; sub-agents' included. Each shows its name without `.md`, linked in the terminal; on desktop, press it to open it. `None written yet.` until then.
- **Handover**: what the `handover` plugin's status line says (when the handover triggers, or that it is ready or writing), the handover this session loaded on a line of its own beneath the section's title (`loaded none` until one loads), a blank line on either side, and the one it wrote beneath the status, each by its title (front matter `summary`, else its `# Handover:` heading), linked to its file and followed, greyed, by its line count and last change (`(142 lines · 2026-10-07 09:32)`). Once the handover is written and the session has stopped, two buttons start the next session from it, the resume message the closing reply ended on shown beneath them: both copy it, run `/clear`, which has the handover plugin load the handover into the new session, wait until the plugin records the handover as loaded, then enter the message in the prompt box. `🚀 Start with this prompt` (focused, so Enter alone starts it) then sends it; `✏️ Edit the prompt first` leaves it there to edit and send yourself. When the handover does not load within its 3-minute wait, the message stays in the prompt box, with a toast. Without a resume message, only `✏️ Edit the prompt first` shows, and it runs `/clear` alone. While no handover is under way, wherever the context stands, `⚡ Hand over now` starts the wind-down at once (`/handover:trigger`): the work in progress and its sub-agents finish, then the handover is written. While a handover is under way the status line animates its phase: `◐ Winding down` (the tasks in progress finish), `✎··· Writing the handover`, then `● Ready for the next session`.
- **Last prompt**: the last prompt you typed, without the tags the engine wraps around it; slash commands are left out. Greyed beside its title, the time you sent it (`14:32`, 24-hour) and the count of earlier prompts (`(6 previous prompts)`); press the count to see every prompt of the session, each numbered with its time (`#2 · 14:32`; no time for one read back after a resume), then `← Overview` to come back.
- **Steps**: an audit trail of the main loop, one entry per model request: what it did in the agent's own words (a Bash call's description, `Edit register.tsx`), printed in full, one after the other, and beneath it why it was refused or failed when it was. `↻ ×N` marks the same action taken again within a few steps, a sign of a loop; `✗` a refused or failed call. The current step shows live, its latest whole sentence while the model thinks, then the call it runs until it returns, under the four latest finished steps, all in full; the earlier ones fold into the heading's line, which counts their refusals, failures and repeats, and unfolds with the reasoning (`∴`) of each.
- **Sub-agents**: how many run and are done, then one line per sub-agent, background agent or teammate: its mission, its kind, its age and what it is doing now (its last call or thought). Press one to expand it, brought to the top of the pane: its task (the first 4,000 characters) and its 40 latest entries, the earlier ones counted; `▴ Collapse` at its foot closes it. Reopening the pane (`/session-panel`, a reload) starts on the overview, every sub-agent closed.
- **Git diff**, at the bottom: for the session's repository and every repository a tool edited in (worktrees included), the changes against `HEAD` as a tree (`+` added, `~` modified, `−` deleted, lines added in green and removed in red), and below them, under **Git History**, full width, the commits made since the session began, by subject, `○` local or `●` pushed; press a commit to read its body. Refreshed after each edit or Bash command.

It is a mod: a plugin of function hooks, drawn by the engine (no shell script, no status line).

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install session-panel@fundrivendev
```

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width. Docked beside a fullscreen transcript it opens 116 columns wide, unless a width was dragged or keyed since.

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

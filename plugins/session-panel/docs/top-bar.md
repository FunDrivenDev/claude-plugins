# Top bar

What the pane draws above its tabs' content: the title, the tabs, the selectors, the quotas, the close mark and the header. [Back to the README](../README.md)

## Title

The session's title, its overall topic in a few words, sits on a line of its own; `Session` until it has one.

- The main agent names the topic with the plugin's `session_title` tool, once the first task is clear and again only when what the session is about changes significantly. Once its turn ends, the title also goes to `/rename`, which names the session in `/resume` and the terminal tab.
- A session started from a handover takes the handover's title (its front matter `summary`, else its `# Handover:` heading) as soon as it has loaded, renamed at once, until the agent names it.
- A session that has no title of its own yet (Claude Code carries the previous name through `/clear` and a plugin reload) has its first typed prompt carry a one-line reminder to set one.

## Tabs

Beneath the title, the tabs on the left, then the model and effort selectors beside the quota pill, and a close mark.

- **Main** shows the session at a glance: Issue, Git, Documents, Handover and Last prompt, in that order. See [Main tab](main-tab.md).
- **Misc** shows the steps, the sub-agents and the git diff. See [Misc tab](misc-tab.md).
- **Config** lists each value the pane reads (its own `cacheTtl` option, Claude Code's `autoCompactWindow` and `plansDirectory`, `CC_TOKEN_LIMIT` and `CC_TOKEN_RESERVE`, the handover plugin's `handover_dir` and token thresholds), as in effect, with what it does and its default.
- **Help** explains each item of the pane, its colours and states, one per line: an example as the pane draws it, then greyed what it shows or does (the title, the model and effort selectors and the tabs, self-evident, are left out).

`✕`, framed so it is easy to hit, closes the pane; `/session-panel` reopens it on Main.

## Selectors

The main loop's model and effort as two rounded pills beside the tabs, selected from the session's start (the model `/model` shows, the effort `/effort` saved). The model shows in its colour (Catppuccin Frappé: Opus peach, Fable mauve, Sonnet blue, Haiku green), the effort in the colour `/effort` gives its level. Press one to open its choices, press a choice to switch (it runs `/model` or `/effort`).

## Quotas

One pill beside the close mark, `● 5h 30% │ ● 7d 71%`: each window's use with a dot in its verdict's colour, then `🔽`. Absent off a subscription.

Press it (anywhere but its dots) to unfold, beneath the top lines, the 5-hour and 7-day windows as bars that fill with use, read as the status line reads them:

- The `┃` tick marks where even spending would be by now. Fill up to it is green; fill past it takes the verdict's colour and breathes once a second.
- The verdict extrapolates the average burn to the reset: `→N%` green under 90%, yellow from 90%, `out in D` red when the limit comes first. It is judged once a tenth of the window has passed.
- `🔄` is the time to the reset.

The two bars sit side by side, half the width each; press the pill again (its arrow now `🔼`) to fold them.

## Header

The session's age (`⌛`) and the whole minutes left before the prompt cache expires (`⏳`), graded as in the status line: green down to half the TTL, yellow down to a fifth, then orange; red once expired.

Beneath, the context counter: the tokens in the window against the auto-compact trigger the engine sets from your `autoCompactWindow` (the figures `/context` uses), followed in brackets by how it is reckoned, the window less Claude Code's margin (`217k (250k − 33k)`). Where the engine gives none, the status line's reckoning applies: `CC_TOKEN_LIMIT`, else `autoCompactWindow`, else 200k, less `CC_TOKEN_RESERVE` (33k by default).

The grading follows that trigger, whatever its size: green up to half of it, yellow to three quarters, orange to nine tenths, then red, and `⚠ compacting` once reached.

## Colours

Catppuccin Frappé and the status line's bright tones on a dark macOS appearance. On a light one, every colour turns to its twin that reads on white (Catppuccin Latte, darker tones for the status line's yellow and orange), following the system setting within five seconds. Off macOS, the dark palette.

Under the pointer, every action (a tab, a pill, a fold, a sub-agent or a commit) lights in its colour, blue when it has none, and every link (a document, a handover, the issue and the pull request) underlines.

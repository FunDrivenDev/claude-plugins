# Top bar

What the pane draws above its tabs' content: the title, the tabs and the close mark. [Back to the README](../README.md)

The running time, the prompt-cache countdown, the context counter, the quotas and the model and effort selectors moved to the `session-bar` mod.

## Title

The session's title, its overall topic in a few words, sits on a line of its own; `Session` until it has one.

- The main agent names the topic with the plugin's `session_title` tool, once the first task is clear and again only when what the session is about changes significantly. Once its turn ends, the title also goes to `/rename`, which names the session in `/resume` and the terminal tab.
- A session started from a handover takes the handover's title (its front matter `summary`, else its `# Handover:` heading) as soon as it has loaded, renamed at once, until the agent names it.
- A session that has no title of its own yet (Claude Code carries the previous name through `/clear` and a plugin reload) has its first typed prompt carry a one-line reminder to set one.

## Tabs

Beneath the title, the tabs on the left, and a close mark on the right.

- **Main** shows the session at a glance: Issue, Git, Documents, Handover and Last prompt, in that order. See [Main tab](main-tab.md).
- **Misc** shows the steps, the sub-agents and the git diff. See [Misc tab](misc-tab.md).
- **Config** lists each value the pane reads (Claude Code's `plansDirectory`, the handover plugin's `handover_dir` and token thresholds), as in effect, with what it does and its default.
- **Help** explains each item of the pane, its colours and states, one per line: an example as the pane draws it, then greyed what it shows or does (the title and the tabs, self-evident, are left out).

`✕`, framed so it is easy to hit, closes the pane; `/session-panel` reopens it on Main.

## Colours

Catppuccin Frappé on a dark macOS appearance. On a light one, every colour turns to its twin that reads on white (Catppuccin Latte, darker tones for GitHub's colours), following the system setting within five seconds. Off macOS, the dark palette.

Under the pointer, every action (a tab, a pill, a fold, a sub-agent or a commit) lights in its colour, blue when it has none, and every link (a document, a handover, the issue and the pull request) underlines.

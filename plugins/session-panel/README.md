# session-panel

A calm side pane for a Claude Code session: what runs, since when, how warm the prompt cache still is, and what every sub-agent was asked and did. It also gathers the session's issue, pull requests, documents, handover and git changes in one place, drawn by the engine as a mod.

![The session panel docked beside a Claude Code transcript](docs/screenshot.png)

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install session-panel@fundrivendev
```

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width.

## Features

- **Title and tabs**: the session's topic as a title (also sent to `/rename`), and four tabs: Main, Misc, Config and Help.
- **Model and effort selectors**: two pills that show the main loop's model and effort and switch them with a click.
- **Quotas**: the 5-hour and 7-day windows in one pill, unfolding into pace bars that forecast when the limit comes.
- **Header**: the session's age, the minutes left on the prompt cache, and the context against the auto-compact trigger, colour-graded.
- **Issue and Git**: the tracker issue the session is about, then each repository it touched with its pull request and worktree.
- **Documents**: the artifacts, handovers, plans and notes the session wrote, linked.
- **Handover**: the `handover` plugin's status, the handover loaded and written, and buttons to hand over now or start the next session.
- **Last prompt**: your last prompt, with the whole session's prompt history one click away.
- **Steps**: an audit trail of the main loop, with refusals, failures and repeated actions flagged.
- **Sub-agents**: every sub-agent, background agent and teammate, with its task and history on demand.
- **Git diff and history**: the uncommitted changes as a tree and the commits made since the session began.
- **Colours**: Catppuccin Frappé, switching to light twins with the macOS appearance.

## Documentation

- [Top bar](docs/top-bar.md): title, tabs, selectors, quotas, header and colours
- [Main tab](docs/main-tab.md): Issue, Git, Documents, Handover and Last prompt
- [Misc tab](docs/misc-tab.md): Steps, Sub-agents, Git diff and Git History
- [Configuration](docs/configuration.md): opening the pane, settings and limits
- [Development](docs/development.md): tests, validation and type-checking

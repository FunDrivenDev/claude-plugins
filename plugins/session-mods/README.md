# session-mods

Two mods for a Claude Code session, drawn by the engine: a calm side pane with what every sub-agent was asked and did, and a one-row bar beneath the prompt with the session's live figures.

![The session pane docked beside a Claude Code transcript](docs/screenshot.png)

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install session-mods@fundrivendev
```

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width. The bar shows beneath the prompt from the start.

## The pane

It gathers the session's issue, pull requests, documents, handover and git changes in one place.

- **Title and tabs**: the session's topic as a title (also sent to `/rename`), and four tabs: Main, Misc, Config and Help.
- **Issue and Git**: the tracker issue the session is about, then each repository it touched with its pull request and worktree.
- **Documents**: the artifacts, handovers, plans and notes the session wrote, linked.
- **Handover**: the `handover` plugin's status, the handover loaded and written, and buttons to hand over now or start the next session.
- **Last prompt**: your last prompt, with the whole session's prompt history one click away.
- **Steps**: an audit trail of the main loop, with refusals, failures and repeated actions flagged.
- **Sub-agents**: every sub-agent, background agent and teammate, with its task and history on demand.
- **Git diff and history**: the uncommitted changes as a tree and the commits made since the session began.
- **Colours**: Catppuccin Frappé, switching to light twins with the macOS appearance.

## The bar

How long the session has run, when the prompt cache expires, how full the context is, the 5-hour and 7-day quotas, and the model and effort, each switchable with a click. It sits beneath the engine's own hint line, which stays in place. See [Bar](docs/bar.md).

## Configuration

| Option | Values | Default | What it sets |
|---|---|---|---|
| `cacheTtl` | `1h`, `5m` | `1h` | The prompt-cache lifetime the bar's countdown starts from; a model switch reports the real one. |

The pane has no option of its own: it reads Claude Code's `plansDirectory` and the handover plugin's settings. See [Configuration](docs/configuration.md).

## Documentation

- [Top bar](docs/top-bar.md): the pane's title, tabs and colours
- [Main tab](docs/main-tab.md): Issue, Git, Documents, Handover and Last prompt
- [Misc tab](docs/misc-tab.md): Steps, Sub-agents, Git diff and Git History
- [Bar](docs/bar.md): the bar beneath the prompt, item by item
- [Configuration](docs/configuration.md): opening the pane, settings and limits
- [Development](docs/development.md): tests, validation and type-checking

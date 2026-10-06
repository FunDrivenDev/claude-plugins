# claude-plugins

Public Claude Code plugins by FunDrivenDev.

```
/plugin marketplace add FunDrivenDev/claude-plugins
```

| Plugin | What it does |
|---|---|
| [`statusline`](plugins/statusline/README.md) | A status line built around the context budget: tokens against the auto-compact trigger, prompt-cache countdown, 5-hour and 7-day quota pace, git branch and PR, and a segment for each plugin that ships one. |
| [`session-panel`](plugins/session-panel/README.md) | A side pane: model and effort, first prompt, uptime, prompt-cache countdown, each sub-agent's task and full history (finished ones greyed beside the running ones), and a checklist of the session's steps. |

## Working on this repo

Tools are pinned in `mise.toml` and run through `just`:

| Recipe | What it does |
|---|---|
| `just init` | Installs the pinned tools and turns on the git hooks (`.githooks`); safe to re-run |
| `just lint` | `shellcheck` on every shell script and hook, `actionlint` on CI, `biome lint` on the mods' TypeScript (`biome.json`) |
| `just test` | The plugins' smoke tests, under the default `bash` and macOS's `/bin/bash` 3.2 |
| `just validate` | `claude plugin validate` on the marketplace and each plugin, and `claude plugin test` on each plugin with tests (needs the `claude` CLI) |
| `just check` | All of the above: `lint`, `test`, `validate` |

The pre-commit hook runs `just lint`, the pre-push hook `just check`; CI runs `just lint` and `just test`, the tests on Linux and macOS. Renovate keeps the tools and the actions current.

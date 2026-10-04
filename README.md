# claude-plugins

Public Claude Code plugins by FunDrivenDev.

```
/plugin marketplace add FunDrivenDev/claude-plugins
```

| Plugin | What it does |
|---|---|
| [`statusline`](plugins/statusline/README.md) | A status line built around the context budget: tokens against the auto-compact trigger, prompt-cache countdown, 5-hour and 7-day quota pace, git branch and PR, and a line for each plugin that ships a segment. |

## Working on this repo

Tools are pinned in `mise.toml` and run through `just`:

| Recipe | What it does |
|---|---|
| `just init` | Installs the pinned tools and turns on the git hooks (`.githooks`); safe to re-run |
| `just lint` | `shellcheck` on every shell script and hook, `actionlint` on CI |
| `just test` | The plugins' smoke tests, under the default `bash` and macOS's `/bin/bash` 3.2 |
| `just validate` | `claude plugin validate` on the marketplace and each plugin (needs the `claude` CLI) |

The pre-commit hook runs `just lint` and `just test`; CI runs the same, the tests on Linux and macOS. Renovate keeps the tools and the actions current.

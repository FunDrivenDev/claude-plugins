# claude-plugins

Public Claude Code plugins by FunDrivenDev.

```
/plugin marketplace add FunDrivenDev/claude-plugins
```

## Working on this repo

Tools are pinned in `mise.toml` and run through `just`:

| Recipe | What it does |
|---|---|
| `just init` | Installs the pinned tools and turns on the git hooks (`.githooks`); safe to re-run |
| `just lint` | `shellcheck` on every shell script and hook, `actionlint` on CI |
| `just validate` | `claude plugin validate` on the marketplace and each plugin (needs the `claude` CLI) |

The pre-commit hook runs `just lint`; CI runs the same. Renovate keeps the tools and the actions current.

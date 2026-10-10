# claude-plugins

Public Claude Code plugins by FunDrivenDev.

```
/plugin marketplace add FunDrivenDev/claude-plugins
```

| Plugin | What it does |
|---|---|
| [`statusline`](plugins/statusline/README.md) | **Deprecated**, no longer maintained. A status line built around the context budget: tokens against the auto-compact trigger, prompt-cache countdown, 5-hour and 7-day quota pace, git branch and PR, and a segment for each plugin that ships one. |
| [`session-panel`](plugins/session-panel/README.md) | A side pane: model and effort, first prompt, uptime, prompt-cache countdown, each sub-agent's task and full history (finished ones greyed beside the running ones), and a checklist of the session's steps. |
| [`handover`](plugins/handover/README.md) | Takes over from auto-compaction: before the context fills up, a separate model writes a handover from the transcript and `/clear` starts a fresh session from it; plus a relay that clears and resumes sessions on its own, and an AFK mode. [`bench/handover/`](bench/handover/README.md) holds the benchmark behind it. |
| [`tools`](plugins/tools/skills) | Workflow tooling: `wrap-up-doc` (session report as an artifact, Bear note or Slack message), `mcp-audit-and-fix`, `claude-config-audit-and-fix` (uses `writing-for-agents` from `mattpocock-skills@claude-plugins-official`) and `local-llm-advisor`. |

## Working on this repo

Tools are pinned in `mise.toml` and run through `just`:

| Recipe | What it does |
|---|---|
| `just init` | Installs the pinned tools and turns on the git hooks (`.githooks`); safe to re-run |
| `just lint` | `shellcheck` on every shell script and hook, `actionlint` on CI, `biome lint` on the mods' TypeScript (`biome.json`), `ruff` on the Python scripts (`ruff.toml`, Python 3.9 syntax: the handover hooks run the system `python3`) |
| `just test` | The plugins' smoke tests: the status line under the default `bash` and macOS's `/bin/bash` 3.2, the handover plugin's carry-over of its old data |
| `just validate` | `claude plugin validate` on the marketplace and each plugin, and `claude plugin test` on each plugin with tests (needs the `claude` CLI) |
| `just versions` | Fails when a plugin changed since `origin/main` (outside its `tests/`) without a version bump |
| `just bump <plugin> patch\|minor\|major` | Raises the plugin's version in its `plugin.json` |
| `just check` | All of the above: `lint`, `test`, `versions`, `validate` |
| `just ci-verdict <results>` | CI's verdict: green when each job result is `success` or `skipped` |

The pre-commit hook runs `just lint`, the pre-push hook `just check`; CI runs `just lint` and `just test`, the tests on Linux and macOS, then a `ci-ok` job that passes only when every other job succeeded or was skipped: the one check FunDrivenDev's organisation ruleset requires on `main`. Renovate keeps the tools and the actions current, automerging once `ci-ok` is green.

Merging a PR is the release: the marketplace serves `main`, and Claude Code updates an installed plugin only when its version changes. So a PR that changes a plugin bumps it (`just bump`: patch for a fix, minor for a feature, major for a breaking change), and the pre-push `just versions` refuses one that doesn't.

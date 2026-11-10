# claude-plugins

Public Claude Code plugins by FunDrivenDev.

```
/plugin marketplace add FunDrivenDev/claude-plugins
```

| Plugin | What it does |
|---|---|
| [`statusline`](plugins/statusline/README.md) | **Deprecated**, no longer maintained. A status line built around the context budget: tokens against the auto-compact trigger, prompt-cache countdown, 5-hour and 7-day quota pace, git branch and PR, and a segment for each plugin that ships one. |
| [`session-mods`](plugins/session-mods/README.md) | Two session mods: a side pane (first prompt, each sub-agent's task and full history, finished ones greyed beside the running ones, and a checklist of the session's steps) and a one-row bar beneath the prompt (running time, prompt-cache countdown, context usage, 5-hour and 7-day quotas, and the model and effort, switchable with a click). |
| [`handover`](plugins/handover/README.md) | Takes over from auto-compaction: before the context fills up, a separate model writes a handover from the transcript and `/clear` starts a fresh session from it; plus a relay that clears and resumes sessions on its own, and an AFK mode. [`bench/handover/`](bench/handover/README.md) holds the benchmark behind it. |
| [`tools`](plugins/tools/skills) | Workflow tooling: `wrap-up-doc` (session report as an artifact, Bear note or Slack message), `mental-model` (a whole system explained on one HTML page), `mcp-audit-and-fix`, `claude-config-audit-and-fix` (uses `writing-for-agents` from `mattpocock-skills@claude-plugins-official`) and `local-llm-advisor`; and a `cache-keepalive` hook ([`scripts/cache_keepalive.py`](plugins/tools/scripts/cache_keepalive.py)) that, while a session waits on a background task or a scheduled wakeup, wakes it 55 minutes after its last turn for a one-line reply that keeps the 1-hour prompt cache warm (on by default: `CACHE_KEEPALIVE=off` disables it, `always` arms it after every turn; `CACHE_KEEPALIVE_AFTER` seconds, `CACHE_KEEPALIVE_MAX` in a row, default 12). |
| [`delegation`](plugins/delegation/README.md) | Four typed read-only subagents the main session delegates to (`investigator`, `researcher`, `reviewer`, `skeptic`), a `guard-agent-type` hook that catches catch-all subagent calls and these agents' Bash writes (`off` by default, `log` or `block` when [set](plugins/delegation/README.md#guard)), and a measure of how sessions delegate to subagents and where the main session's context goes (typed share of agent calls, delegated writes, subagent starting context, peak context, large results, MCP volume): a snapshot of a date window, and a before/after compare. |

## Working on this repo

Tools are pinned in `mise.toml` and run through `just`:

| Recipe | What it does |
|---|---|
| `just init` | Installs the pinned tools; the git hooks are in `hk.pkl` (`mise exec -- hk install` installs them where no global hook runs hk); safe to re-run |
| `just lint` | `shellcheck` on every shell script, `actionlint` on CI, `biome lint` on the mods' TypeScript (`biome.json`), `ruff` on the Python scripts (`ruff.toml`, Python 3.9 syntax: the handover hooks run the system `python3`) |
| `just test` | The plugins' smoke tests, every `tests/*.sh` then every `tests/*.py` (a name starting with `_` is a helper): the status line under the default `bash` and macOS's `/bin/bash` 3.2, the handover plugin's carry-over of its old data and its notifier adapters, the delegation plugin's `measure` script, its eval cases, its four agents (exact tool allow-list, model, effort, no CLAUDE.md, report shape), its guard hook and its neutrality check, and the tools plugin's cache-keepalive hook |
| `just validate` | `claude plugin validate` on the marketplace and each plugin, and `claude plugin test` on each plugin with tests (needs the `claude` CLI) |
| `just versions` | Fails when a plugin changed since `origin/main` (outside its `tests/`) without a version bump |
| `just bump <plugin> patch\|minor\|major` | Raises the plugin's version in its `plugin.json` |
| `just check` | All of the above: `lint`, `test`, `versions`, `validate` |
| `just ci-verdict <results>` | CI's verdict: green when each job result is `success` or `skipped` |

The git hooks (`hk.pkl`) are the CI: the pre-commit hook runs `just lint`, the pre-push hook `just check`. When the hooks run through `toolbox check run` (the hk dispatcher of the dotfiles), it records the pass that `toolbox pr gate` reads before a PR is marked ready or merged. GitHub Actions runs no check on a push or a human's pull request: `.github/workflows/ci.yml` runs `just lint` and `just test`, the tests on Linux and macOS, then a `ci-ok` job that passes only when every other job succeeded or was skipped, by hand and on Renovate's pull requests, which no laptop checks. Renovate keeps the tools and the actions current: it merges a minor or patch update itself once that run passes, and `toolbox pr gate` reads the run's checks before a major one merges.

Merging a PR is the release: the marketplace serves `main`, and Claude Code updates an installed plugin only when its version changes. So a PR that changes a plugin bumps it (`just bump`: patch for a fix, minor for a feature, major for a breaking change), and the pre-push `just versions` refuses one that doesn't.

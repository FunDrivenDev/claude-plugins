# delegation

Measures how Claude Code sessions delegate to subagents, and where the main session's context goes, so a change to agents, rules or hooks is judged on data: a baseline window, the change, the same window length after it.

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install delegation@fundrivendev
```

Installing it changes no behaviour: the plugin only reads transcripts when asked.

## Use

`/delegation:measure` with a date range, or with two snapshot files to compare. The script runs alone too:

```
python3 plugins/delegation/scripts/measure.py snapshot take --since=2026-10-23 --until=2026-11-05 --out=baseline
python3 plugins/delegation/scripts/measure.py snapshot compare --before=baseline.json --after=after.json
```

It reads `<config>/projects` (`CLAUDE_CONFIG_DIR`, else `~/.claude`), or `--projects=<dir>`. A session belongs to the window of the day its transcript starts. `--json` prints JSON; `--json=<object>` (or `--json=-`) gives the whole input as JSON; `--help --json` prints its spec. Exit 0 on success, 1 on failure, 2 on a usage error.

## Metrics

| # | Metric | From |
|---|---|---|
| M1 | Share of agent calls naming a role (not `general-purpose`, `claude`, `fork`, untyped) | the Agent calls |
| M2 | Delegated calls that wrote (Edit, Write, a commit, a push) | the subagent transcripts |
| M3 | Subagent starting context, by type | a subagent's first request |
| M4 | Main peak context: median, p90, sessions above 150k | the main transcripts |
| M5 | Share of tool output in results above 20k characters; re-reads | the tool results |
| M6 | Delegated results the main session re-checked | files a subagent read, opened again afterwards |
| M7 | MCP result volume, by server and tool | the tool results |
| M9 | Would-block events of the `guard-agent-type` hook in `log` mode | its event log, when there is one |

A snapshot holds aggregates only: counts, sizes, shares, and the names of tools, agent types and skills. No prompt, description, session title, path or result text, so a snapshot taken on one machine can be shared from it.

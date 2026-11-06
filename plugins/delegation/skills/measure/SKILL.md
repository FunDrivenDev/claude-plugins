---
name: measure
description: Measure how sessions delegate to subagents and where the main session's context goes, as a snapshot of a date window (Markdown and JSON, aggregates only) or a before/after compare of two snapshots.
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/measure.py *)
---

# Measure delegation

Arguments: `$ARGUMENTS` (empty: the last 14 days; a date range; or two snapshot files to compare).

A snapshot of a window, printed as Markdown:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/measure.py snapshot take --since=YYYY-MM-DD --until=YYYY-MM-DD
```

To keep it, add `--out=<folder>/<YY-MM-DD>-delegation-<label>`: the script writes `.json` and `.md` there and prints both paths. Two snapshots side by side:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/measure.py snapshot compare --before=<a>.json --after=<b>.json
```

Compare windows of the same length (the two weeks before a change against the two weeks after), never all history against a week: the task mix and the models drift.

Show the tables as they are, then read them in a few sentences:

- **M1, typed share**: agent calls naming a role, against `general-purpose`, `claude`, `fork` or no type. Low means delegation goes to catch-all agents.
- **M2, delegated writes**: subagents that edited or wrote, through the file tools or Bash (a redirection, `tee`, `mv`, `rm`, `sed -i`, a commit, a push). Writes belong in the main session, which holds the decisions.
- **M3, starting context**: a subagent's first request, by type. A custom agent above `Explore` loads more than it needs (CLAUDE.md, rules, tools).
- **M4, main peak context**: median, p90 and sessions above 150k tokens.
- **M5, large results**: share of tool output in results above 20k characters, and re-reads of a file unchanged since its last read.
- **M6, re-checked**: delegated calls whose files the main session opened again afterwards. Stable or up for review roles; very high for a scout means its reports are not trusted.
- **M7, MCP volume**: result characters by server and tool.
- **M9, hook events**: catch-all calls the `guard-agent-type` hook caught, would-block (`log` mode, let through) and blocked (`block` mode, refused), by caller skill, when its log exists. Blocked at 0 under `block` means no caller still asks for a catch-all agent.

A snapshot holds no prompt, description, title, path or result text, so one taken on a work machine can be shared; the Markdown names only tools, agent types and skills.

# delegation

Typed read-only subagents for Claude Code, and a measure of how sessions delegate to them. The main session plans, writes and decides; a subagent reads, runs read-only commands and brings back a conclusion, so the tokens it spends stay out of the main context. The measure judges a change to agents, rules or hooks on data: a baseline window, the change, the same window length after it.

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install delegation@fundrivendev
```

Installing it adds four agents the main session can delegate to and a guard hook that is off until you set its mode; the measure only reads transcripts when asked.

## Agents

Each is called as `delegation:<role>`, beside the built-in `Explore`, which stays the scout (locating code). Each has a tool allow-list with no edit, write or delegation tool, a model and effort fit for its job, and `omitClaudeMd: true`: it starts on its own instructions and the brief, not on your CLAUDE.md, so its starting context stays small. Whatever it needs goes in the brief.

| Role | Job | Tools | Model, effort |
|---|---|---|---|
| `investigator` | diagnose a bug, a red test, a failed run; survey a system's state | Read, Grep, Glob, Bash | opus, high |
| `researcher` | answer from docs and the web, primary sources first | Read, Grep, Glob, Bash, WebSearch, WebFetch | sonnet, medium |
| `reviewer` | review a diff without the briefing session's reasoning; verified findings at `file:line` | Read, Grep, Glob, Bash | opus, high |
| `skeptic` | try to break a plan or a design; the objections that hold, or none | Read, Grep, Glob, Bash, WebSearch, WebFetch | fable, high |

Every report opens with `Status` (`done`, `partial`, `blocked`) and closes with `Unverified` and `Verify` (the one check that lets the briefing session trust it); the fields between depend on the role and are written in full in each agent file. Their Bash stays read-only by instruction, and the guard hook below catches what breaks it: a `permissions.deny` rule on the write commands would bind the main session too, the one meant to write, commit and push, while the hook reads the calling agent's type. The allow-list bounds the built-in tools, not a tool another plugin injects: on Claude Code 2.1.318, each agent also listed the handover plugin's `SubagentHandback`. Read-only then rests on each such tool being read-only too. A plugin agent ignores `permissionMode`, `hooks` and `mcpServers` in its frontmatter.

## Guard

The `guard-agent-type` hook watches two kinds of call:

- an Agent call of no type, `general-purpose`, `claude` or `fork`: a catch-all subagent starts on a large context with every tool;
- a Bash command of one of this plugin's agents (`agent_type` `delegation:*`) that writes, by the definition M2 uses (a redirection, a file command, an in-place edit, a git or gh write, a script's write). Writes that all land in a temporary folder (a `mktemp -d` one, `$TMPDIR`, `/tmp`) go through: the agents' throwaway reproductions. A push or a gh write is caught even there. The main session's commands and other agents' are never touched.

Its `guard_mode` option sets what it does with both:

- `off` (the default): nothing; installing the plugin changes no call.
- `log`: the call goes through, and a would-block event (time, tool, agent type, and for an Agent call the skill running in the turn) is appended to `guard-agent-type.jsonl` in the plugin's data folder. `measure` counts the Agent ones as M9 would-block, by skill and type, and the Bash ones as M9b, by agent type, so a caller that still spawns catch-all agents, or an agent that still writes, shows up before `block` is turned on.
- `block`: the call is refused, its reason naming the typed roles (Agent) or the `mktemp -d` way and the report (Bash); the refusal is logged, and `measure` counts it as M9 or M9b blocked.

Set it in `settings.json`:

```json
"pluginConfigs": { "delegation@fundrivendev": { "options": { "guard_mode": "log" } } }
```

`DELEGATION_GUARD_MODE=off|log|block` in a session's environment overrides it for that session. An invalid override (a typo such as `blok`) is ignored with a one-line warning on stderr, and the option applies: a typo never turns `block` off. An invalid option is `off`. A `settings.json` that cannot be read, or whose `pluginConfigs` level on the way to the option is not an object, sets no option, with a one-line warning. Any error in the hook lets the call through.

## Measure

`/delegation:measure` with a date range, or with two snapshot files to compare. The script runs alone too:

```
python3 plugins/delegation/scripts/measure.py snapshot take --since=2026-10-23 --until=2026-11-05 --out=baseline
python3 plugins/delegation/scripts/measure.py snapshot compare --before=baseline.json --after=after.json
```

It reads `<config>/projects` (`CLAUDE_CONFIG_DIR`, else `~/.claude`), or `--projects=<dir>`. A session belongs to the window of the day its transcript starts. `--json` prints JSON; `--json=<object>` (or `--json=-`) gives the whole input as JSON; `--help --json` prints its spec. Exit 0 on success, 1 on failure, 2 on a usage error.

## Metrics

| # | Metric | From |
|---|---|---|
| M1 | Share of the agents that ran naming a role (not `general-purpose`, `claude`, `fork`, untyped); a refused or failed Agent call stays out | the Agent calls and their results |
| M2 | Delegated calls that wrote (Edit, Write, or a Bash write: a redirection to a file, `tee`, `mv`, `rm`, an in-place edit, a git or gh write) | the subagent transcripts |
| M3 | Subagent starting context, by type | a subagent's first request |
| M4 | Main peak context: median, p90, sessions above 150k | the main transcripts |
| M5 | Share of tool output in results above 20k characters; re-reads | the tool results |
| M6 | Delegated results the main session re-checked | files a subagent read, opened again afterwards |
| M7 | MCP result volume, by server and tool | the tool results |
| M9 | Catch-all calls the `guard-agent-type` hook caught: would-block (`log` mode) and blocked (`block` mode), by caller skill and type | its event log, when there is one |
| M9b | The plugin's agents' Bash writes the same hook caught, would-block and blocked, by agent type | the same log |

A token count reads a message's usage once, though the transcript repeats it on each record the message is split into (one per content block, same `message.id`). A percentile (p75, p90) is the nearest rank, the value at rank ⌈p × n / 100⌉ of the sorted values; a median is the middle value, or the mean of the two middle values of an even count.

A snapshot holds aggregates only: counts, sizes, shares, and the names of tools, agent types and skills. No prompt, description, session title, path or result text, so a snapshot taken on one machine can be shared from it.

## Evals (M8)

`evals/` holds eight `claude plugin eval` cases on a small fixture repo (`evals/fixture.sh`, copied into each case): four read tasks that should go to a role (`Explore` as scout, `investigator`, `reviewer`, `skeptic`) and write nothing (no Edit, no Write, no Bash write), and four write tasks the main session should write itself (an Edit or a Write call, tools no role has; the rename, which the main session may do in one Bash `sed`, makes no agent call at all), with no `general-purpose`, `claude`, `fork` or untyped agent. M8 is the share of cases that pass. The runs spend tokens, and the fixture runs as you (`--scaffold`):

```
claude plugin eval plugins/delegation --ablation none --runs 2 --scaffold --trust-plugin \
  --model claude-opus-5-5 --threshold 0 --max-cost-usd 15 --json eval.json --allow-tools Bash Edit Write
```

An eval run starts from a clean configuration (its own `CLAUDE_CONFIG_DIR` and `HOME`): it measures the plugin alone, not your own rules or agents.

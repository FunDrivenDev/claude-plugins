---
name: mcp-audit-and-fix
description: Audit which MCP servers each project actually uses, then move, deny, or uninstall each one with your approval.
disable-model-invocation: true
---

# MCP audit and fix

`S` below is `scripts/mcp_audit.py` in this skill's directory, run with `python3`. Prefix every call with `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"` so the saved report choice survives plugin updates; outside a plugin it expands to empty and the script falls back to this skill's directory.

## Steps

0. **Report location.** If the invocation arguments contain `report=<default|none|path>`, run `python3 S set-report <value>`. Then run `python3 S report-dir --project <cwd>`. When `choice` is `null` (first run), ask one `AskUserQuestion` question, header "Report", with these options:
   - "Reports folder next to Claude Code's plans (Recommended)": show the `default` path, a `reports` folder beside Claude Code's `plansDirectory`, and say it moves with that setting.
   - "Another folder": the user types the path via "Other", or you ask for it next. The folder is created if it doesn't exist.
   - "No report": the results stay in the chat.

   Save the answer with `python3 S set-report default|<path>|none`. Done when `report-dir` returns a non-null `choice`. Tell the user they can change it later with `/mcp-audit-and-fix report=<default|none|path>`.
1. **Inventory.** Run `python3 S inventory > <scratchpad>/mcp-inventory.json` (takes a minute: it scans every transcript and starts two one-turn headless sessions). Done when every entry in `servers` carries a `usage` block.
2. **Findings.** Apply the finding rules to every entry in `servers`. Done when each server is either a finding or on a "fine" list with its one-line reason. Evidence for each finding: source, status, projects with recent calls, call counts, last use date.
3. **Ask.** One `AskUserQuestion` question per finding, in batches of at most 4, following the question format. Done when every finding has an answer.
4. **Apply** each answer from the action catalog, in this order: copies, then probe the targets, then removals, then denies, then plugin changes and manual steps. Never remove a server's old scope before a probe shows the new one loading.
5. **Verify.** Run `python3 S probe <project>` in every project a change touched, and `python3 S probe` (empty dir) after any global change. Done when every applied action shows the expected loaded/absent state; a mismatch is reported with the probe output, never retried silently.
6. **Report.** Write the report if `report-dir` gave a `path`, as `<path>/YY-MM-DD-mcp-audit-fix-results.md`. Create the folder if it's missing, and add a new section if the file already exists. The report contains:
   - one row per finding: evidence, choice, result;
   - the "fine" list;
   - the `/mcp` toggles found in `blocked.per_project`;
   - undo notes for each change.

   End the chat with a short summary, plus the report path when there is one. With `choice: "none"`, the chat summary carries the undo notes instead.

## Finding rules

A server is **used** in a project when `usage.real_projects[<project>].recent_calls > 0`; N is the count of such projects. Calls under `ephemeral_or_gone` are evidence only; they never justify keeping a server. Skip servers already in `blocked.global_denied`.

| Source | Situation | Options, recommended first |
|---|---|---|
| `user` | N = 0 | Uninstall · Deny globally · Keep |
| `user` | N = 1–2 | Move to local scope in those projects · Keep global · Uninstall |
| `local` | not used in its project | Uninstall from that project · Keep |
| `local` | same name configured locally in 3+ projects, all used | Promote to user scope · Keep |
| `project` (.mcp.json) | not used in its project | Deny in this project · Remove from .mcp.json · Keep |
| `claudeai` | N = 0 | Deny globally · Disconnect on claude.ai · Keep |
| `claudeai` | N = 1–2 | Keep · Deny in the other known projects |
| `plugin` | N = 0 | Deny globally · Disable the whole plugin · Keep |
| any | status `failed`/`needs-auth` and N ≥ 1 | Re-authenticate · Keep |

Everything else is fine: `user`/`claudeai`/`plugin` servers with N ≥ 3, and `plugin` servers with N ≥ 1. `plugin_servers_not_loaded` and `usage_of_unlisted_servers` are report-only (desktop-app servers, servers injected by tools).

## Question format

- `header`: the server name, cut to 12 characters.
- `question`: the server, its evidence, then "What should I do?". Example: "tracker (user scope, loaded everywhere) was only called in ~/Code/api: 108 calls, last on 2026-09-20. What should I do?"
- `options`: the row's options in order, the first labelled with a "(Recommended)" suffix, "Keep as is" last. Each `description` names the exact effect: which file or command, which projects, and how to undo it.
- A free-text "Other" answer is followed when it maps onto the action catalog; otherwise ask again.

## Action catalog

| Action | Commands |
|---|---|
| Move to local scope | `python3 S copy NAME --from user --to P1 P2…`, probe each P, then `claude mcp remove NAME -s user` |
| Promote to user scope | `python3 S copy NAME --from P1 --to user`, probe, then `claude mcp remove NAME -s local` with cwd = each P |
| Uninstall | `claude mcp remove NAME -s user`, or `claude mcp remove NAME -s local` with cwd = P |
| Remove from .mcp.json | `claude mcp remove NAME -s project` with cwd = P; this edits a committed file, so leave it uncommitted and say so |
| Deny globally / in projects | `python3 S deny NAME --where global` or `--where P1 P2…` (writes `deniedMcpServers` in `~/.claude/settings.json` or `P/.claude/settings.local.json`; undo by deleting the entry) |
| Disable the whole plugin | `claude plugin details <plugin id>` to list what else it removes (put that in the option description), then `claude plugin disable <plugin id>` |
| Disconnect on claude.ai | Manual: the user disconnects it at https://claude.ai/settings/connectors; this also removes it from web and desktop |
| Re-authenticate | The user runs `! claude mcp login NAME` |

## Gotchas

- Only `deniedMcpServers` blocks a server from a settings file. `disabledMcpServers` in a settings file has no effect, and `claude mcp list` ignores settings-file denies: verify with `S probe`, never with `claude mcp list`.
- Local scope and project denies are keyed to the exact path. For a project with sessions under `.claude/worktrees/`, also probe one worktree path and report whether the change reached it.
- Moved OAuth servers may ask to authenticate again on first use in the new scope; say so in the option description.
- Changes take effect in new sessions; the current session keeps the servers it started with.

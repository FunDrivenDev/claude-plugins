# Misc tab

What the session touched and does under the hood: Issue, Git, Documents and Last prompt, then Steps, Sub-agents, Git diff and Git History. [Back to the README](../README.md)

## Issue

Names on its line the tracker issue the session is about, with its platform's icon (GitHub `◉`, Linear `◐`) and its title, linked, or `no issue`.

The issue is the one your prompt names, else the one the session opened (`gh issue create`, a Linear tool's `create`), else one it worked on. A Linear issue opens in the desktop app (`linear://`) where it is installed, else on linear.app; a bare `KEY-N` in a prompt counts once a Linear tool shows it, so an It's a Plan key is never taken for a Linear one.

## Git

Lists, a blank line apart, each repository the session worked on (its starting folder, and any it edited in) in the order it first touched them, or `no repository yet` outside any:

- `⎇ name`, then its pull request as `#N title`, linked, in GitHub's colours (lavender draft, a lighter tone than GitHub's grey so it reads, green open, red closed, purple merged) with its state, or `no pull request yet`.
- Beneath, the linked worktree the session last edited in (`▣ name`), or `main checkout`.

A pull request worked on in a repository not checked out here gets a block of its own, without the worktree line. Each repository's pull request is chosen as the issue is: the one your prompt names, else the one the session opened, else one it worked on.

A bare `#N` in a prompt (a numbered list's `#1, #2`) counts below any reference the session worked on. The pane reads the whole transcript again when it loads, so a plugin loaded mid-session finds the references made before it. GitHub items are read with `gh api`, the pull request's state again every minute.

## Documents

What the session wrote that lasts, grouped by kind:

1. the artifacts it published (linked to claude.ai);
2. the handovers (in the handover plugin's `handover_dir`, `~/Notes/claude/agent-handovers` by default);
3. the plans (in Claude Code's `plansDirectory`, `~/.claude/plans` by default);
4. any other Markdown file the agent wrote outside the project's repository, temporary and hidden folders, under its folder's name.

A file counts once an editing tool wrote it, a shell command named it by an absolute or `~` path and it changed since the session began, or the handover plugin wrote it; sub-agents' included. Each shows its name without `.md`, linked in the terminal; on desktop, press it to open it. `None written yet.` until then.

## Last prompt

The last prompt you typed, without the tags the engine wraps around it; slash commands are left out. Greyed beside its title, the time you sent it (`14:32`, 24-hour) and the count of earlier prompts (`(6 previous prompts)`).

Press the count to see every prompt of the session, each numbered with its time (`#2 · 14:32`; no time for one read back after a resume), then `← Overview` to come back.

```
Steps ▸ 37 earlier · 2 refused · 1 repeated
✓ Sync, validate, commit, push, update PR
✗ Add file-tree tests and run them
    failed: AssertionError: expect(received).toEqual()
● Searching engine types for link support

Sub-agents · 1 running · 1 done
▸ Find hooks
  sub-agent · 42s · Grep: turn.step
▸ Review diff
  background · 3m 10s · done

Git diff
claude-plugins ⎇ feat/session-panel +412 −3
├ plugins/session-panel/
│ ├ + README.md +58
│ └ hooks/
│   └ ~ register.tsx +40 −6
└ ~ README.md +1 −1

Git History
○ session-panel: tracker corner
  3f2a1bc · 2 min ago · local
● session-panel: steps as an audit trail, last prompt with its history
  2ad70a1 · 1 hour ago · pushed
```

## Steps

An audit trail of the main loop, one entry per model request: what it did in the agent's own words (a Bash call's description, `Edit register.tsx`), printed in full, one after the other, and beneath it why it was refused or failed when it was.

- `↻ ×N` marks the same action taken again within a few steps, a sign of a loop.
- `✗` marks a refused or failed call.
- The current step shows live: its latest whole sentence while the model thinks, then the call it runs until it returns.

The four latest finished steps show in full above the current one; the earlier ones fold into the heading's line, which counts their refusals, failures and repeats, and unfolds with the reasoning (`∴`) of each.

## Sub-agents

How many run and are done, then one line per sub-agent, background agent or teammate: its mission, its kind, its age and what it is doing now (its last call or thought).

Press one to expand it, brought to the top of the pane: its task (the first 4,000 characters) and its 40 latest entries, the earlier ones counted; `▴ Collapse` at its foot closes it. Reopening the pane (`/session-panel`, a reload) starts on the overview, every sub-agent closed.

## Git diff and Git History

At the bottom, for the session's repository and every repository a tool edited in (worktrees included), the changes against `HEAD` as a tree: `+` added, `~` modified, `−` deleted, lines added in green and removed in red.

Below them, under **Git History**, full width, the commits made since the session began, by subject, `○` local or `●` pushed; press a commit to read its body.

Both refresh after each edit or Bash command.

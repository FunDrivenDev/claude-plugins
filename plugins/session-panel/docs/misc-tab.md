# Misc tab

What the session does under the hood: Steps, Sub-agents, Git diff and Git History. [Back to the README](../README.md)

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

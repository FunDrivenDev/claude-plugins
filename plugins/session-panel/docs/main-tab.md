# Main tab

The session at a glance: Issue, Git, Documents, Handover and Last prompt, in that order. [Back to the README](../README.md)

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

## Handover

What the `handover` plugin's status line says (when the handover triggers, or that it is ready or writing), the handover this session loaded on a line of its own beneath the section's title (`loaded none` until one loads), a blank line on either side, and the one it wrote beneath the status. Each shows by its title (front matter `summary`, else its `# Handover:` heading), linked to its file and followed, greyed, by its line count and last change (`(142 lines · 2026-10-07 09:32)`).

While a handover is under way the status line animates its phase: `◐ Winding down` (the tasks in progress finish), `✎··· Writing the handover`, then `● Ready for the next session`.

While no handover is under way, wherever the context stands, `⚡ Hand over now` starts the wind-down at once (`/handover:trigger`): the work in progress and its sub-agents finish, then the handover is written.

Once the handover is written and the session has stopped, two buttons start the next session from it, the resume message the closing reply ended on shown beneath them. Both copy it, run `/clear` (which has the handover plugin load the handover into the new session), wait until the plugin records the handover as loaded, then enter the message in the prompt box:

- `🚀 Start with this prompt` (focused, so Enter alone starts it) then sends it;
- `✏️ Edit the prompt first` leaves it there to edit and send yourself.

When the handover does not load within its 3-minute wait, the message stays in the prompt box, with a toast. Without a resume message, only `✏️ Edit the prompt first` shows, and it runs `/clear` alone.

## Last prompt

The last prompt you typed, without the tags the engine wraps around it; slash commands are left out. Greyed beside its title, the time you sent it (`14:32`, 24-hour) and the count of earlier prompts (`(6 previous prompts)`).

Press the count to see every prompt of the session, each numbered with its time (`#2 · 14:32`; no time for one read back after a resume), then `← Overview` to come back.

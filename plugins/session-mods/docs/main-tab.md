# Main tab

The topic at a glance: Handover, then Situation. [Back to the README](../README.md)

## Handover

What the `handover` plugin's status line says (when the handover triggers, or that it is ready or writing), the handover this session loaded on a line of its own beneath the section's title (`loaded none` until one loads), a blank line on either side, and the one it wrote beneath the status. Each shows by its title (front matter `summary`, else its `# Handover:` heading), linked to its file and followed, greyed, by its line count and last change (`(142 lines · 2026-10-07 09:32)`).

The pane renders what the handover plugin answers: it runs the installed plugin's `handover.py state --session <id> --json` (handover 0.29.0 and later) and reads none of its files. Without that answer (the plugin not installed, or older), the section reads `Handover state unknown` and why.

While a handover is under way the status line animates its phase: `◐ Winding down` (the tasks in progress finish), `✎··· Writing the handover`, then `● Ready for the next session`.

While no handover is under way, wherever the context stands, `⚡ Hand over now` starts the wind-down at once (`/handover:trigger`): the work in progress and its sub-agents finish, then the handover is written.

Once the handover is written and the session has stopped, two buttons start the next session from it, the resume message the closing reply ended on shown beneath them. Both copy it, run `/clear` (which has the handover plugin load the handover into the new session), wait until the plugin records the handover as loaded, then enter the message in the prompt box:

- `🚀 Start with this prompt` (focused, so Enter alone starts it) then sends it;
- `✏️ Edit the prompt first` leaves it there to edit and send yourself.

When the handover does not load within its 3-minute wait, the message stays in the prompt box, with a toast. Without a resume message, only `✏️ Edit the prompt first` shows, and it runs `/clear` alone.

## Situation

The live state of the session's topic, the same in every session of it and after a handover, read again every 30 seconds without a prompt. Its title line names the topic and where it came from (`· session-panel-journal · Rex session`).

```
Situation · session-panel-journal · Rex session

Merge plan · file · changed 12 min ago
1  ✅ claude-plugins#89 base merged
2  🔧 claude-plugins#90! worker running

Workers
● review · running · Reading the diff
✓ fix · done · AFK done: claude-plugins#90

Open questions
Q1 Lock mode in mise.toml?

Awaiting you register
D02 Pin the lock in CI
```

The topic is a notes `topic:` slug (the front matter of the plans and registers in `~/Notes/claude`):

1. the Rex session's label, when a plan or a register names it as its topic (a dispatched or watched session is labelled by its topic);
2. else the `topic:` of the last notes document the session read or wrote (a brief, a plan, a register, a handover), read again as soon as it changes.

A handover chain keeps it: the next session runs in the same Rex tab, or reads the handover and the brief. Without a topic, the section says so in one dim line.

Four blocks follow, each with one dim line when it has nothing to show:

- **Merge plan**: the topic's latest `*-merge-plan.md` in `~/Notes/claude/plans`, one row per line of its `| Wave | PR | Status | Note |` table: wave, status, each pull request linked in its live state's colour (as in [Git](misc-tab.md#git)) with `!` on a red check, then the note. The heading links the file and gives its age, yellow past an hour. Pull requests are read with `gh` every minute; `gh unreachable` replaces their colours when none answers.
- **Workers**: the other tabs of the Rex session labelled by the topic (this one, or another found with `rex ls`), each with its state read from its screen (`rex capture`): `●` running, `◆` waiting for you, `○` idle, `✓` done or `✗` blocked on its `AFK` line, `›` a shell; then the last thing it said. Without Rex it reads `not in a Rex session` or `rex unreachable`.
- **Open questions**: the `## Qn — title` headings of the topic's `*-open-questions.md` plans still `todo` or `doing`, without those a `**Decided**` line answers.
- **Awaiting you**: the entries of the topic's decision register (`~/Notes/claude/decisions-register`) still `proposed`, linked to the register.

The panel computes it all live from the notes, `gh` and `rex`: no skill or worker writes a state file for it.

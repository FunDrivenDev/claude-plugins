# Main tab

The topic at a glance: Handover (AFK mode included), then Situation when the `situation` option is on. [Back to the README](../README.md)

## Handover

What the `handover` plugin's status line says (its thresholds, or that it is ready or writing), the handover this session loaded on a line of its own beneath the section's title (`loaded none` until one loads), a blank line on either side, and the one it wrote beneath the status. Each shows by its title (front matter `summary`, else its `# Handover:` heading), linked to its file and followed, greyed, by its line count and last change (`(142 lines · 2026-10-07 09:32)`).

The pane renders what the handover plugin answers: it runs the installed plugin's `handover.py state --session <id> --json` (handover 0.29.0 and later) and reads none of its files. Without that answer (the plugin not installed, or older), the section reads `Handover state unknown` and why.

Before a handover starts, the line lists every threshold the handover state gives, as the handover plugin names them ([Settings](../../handover/docs/settings.md)): `✋ suggest 170k · warn 185k · trigger 200k`, `suggest` from `suggest_tokens`, `warn` its `warn_at_tokens` (where the line turns yellow: halfway from the suggestion to the trigger, else 20k before the trigger), `trigger` from `trigger_tokens`. A threshold the context has passed is dimmed, with a ✓ (`✓ suggest 170k`), so the next one stands out; one set to 0 reads `off` (`trigger off`, and then no `warn`). Past the trigger, the wind-down's phase takes the line's place. The context's size is the status line's, not the pane's.

While a handover is under way the status line animates its phase: `◐ Winding down` (the tasks in progress finish), `✎··· Writing the handover`, then `● Ready for the next session`.

The section's buttons sit side by side on one row of pills, beneath the status and the handover written, and wrap onto a second row where the pane is too narrow: `⚡ Hand over now` while a handover can start; `🚀 Start with this prompt` (with a resume message) and `✏️ Edit the prompt first` once one is written and the session has stopped; then `🌙 Go AFK` whenever AFK mode can be turned on.

While no handover is under way, wherever the context stands, `⚡ Hand over now` starts the wind-down at once (`/handover:trigger`): the work in progress and its sub-agents finish, then the handover is written.

Once the handover is written and the session has stopped, two buttons start the next session from it, the resume message the closing reply ended on shown beneath their row. Both copy it, run `/clear` (which has the handover plugin load the handover into the new session), wait until the plugin records the handover as loaded, then enter the message in the prompt box:

- `🚀 Start with this prompt` (focused, so Enter alone starts it) then sends it;
- `✏️ Edit the prompt first` leaves it there to edit and send yourself.

When the handover does not load within its 3-minute wait, the message stays in the prompt box, with a toast. Without a resume message, only `✏️ Edit the prompt first` shows, and it runs `/clear` alone.

### AFK mode

Last in Handover, the `handover` plugin's AFK mode: a run toward a goal while you are away, handing over to fresh sessions until the goal is met or blocked ([AFK mode](../../handover/docs/afk.md)).

- Off, `🌙 Go AFK` opens a field for the goal and, when the prompt is empty, moves the keyboard into it (with a draft in the prompt, click the field first); the goal may end on a deadline as `/handover:afk` takes it (`until 8`, `until tomorrow 9:00`, `for 10h`). Enter runs `/handover:afk <goal>`: the session gets the AFK rules from the plugin and starts on the goal. `cancel`, beside the field, closes it.
- On, the line reads `🌙 AFK on · until Tue 17 Nov 08:00` (`AFK on` without a deadline), the goal beneath it, and `☀️ Turn AFK off`, on the AFK line's row, runs `/handover:afk off`.
- Until the state follows a press, `Turning AFK on…` or `Turning AFK off…` stands in its place, two minutes at most.

The pane reads AFK mode from the handover plugin's `state` answer (its `afk` and `relays`, handover 0.35.0 and later) and writes none of its files. Where the session cannot relay (no terminal the plugin types into, such as tmux, and no `toolbox session run`), a dim line says so in place of the button; with an older handover plugin, it names the version needed.

## Situation

An opt-in section, off by default: set the `situation` option to turn it on ([Configuration](configuration.md#situation)). Off, Main shows Handover alone, and the Help tab leaves Situation out.

The live state of the session's topic, the same in every session of it and after a handover, read again every 30 seconds without a prompt. Its title line names the topic and where it came from (`· session-panel-journal · terminal session`).

```
Situation · session-panel-journal · terminal session

Merge plan · file · changed 12 min ago
1  ✅ claude-plugins#89 base merged
2  🔧 claude-plugins#90! worker running
3  ⏳ stale: merged claude-plugins#91 merges after #90

Workers
● review · running · Reading the diff
✓ fix · done · AFK done: claude-plugins#90

Open questions
▸ Q1 Lock mode in mise.toml?

Awaiting you register
▸ D02 Pin the lock in CI
```

The topic is a notes `topic:` slug (the front matter of the plans and registers in `~/Notes/claude`, and of the registers in factory's log):

1. the terminal session's label, when a plan or a register names it as its topic (a dispatched or watched session is labelled by its topic);
2. else the `topic:` of the last notes document the session read or wrote (a brief, a plan, a register, a handover), read again as soon as it changes.

A handover chain keeps it: the next session runs in the same terminal tab, or reads the handover and the brief. Without a topic, the section says so in one dim line.

Four blocks follow, each with one dim line when it has nothing to show:

- **Merge plan**: the topic's latest open merge plan: factory's plan titled `Merge plan: <topic>` (the `merge-plan` skill), else an older `*-merge-plan.md` in `~/Notes/claude/plans`; one row per line of its `| Wave | PR | Status | Note |` table: wave, status, each pull request linked in its live state's colour (as in [Git](misc-tab.md#git)) with `!` on a red check, then the note. The heading links the file and gives its age, yellow past an hour. Pull requests are read with `gh` every minute; `gh unreachable` replaces their colours when none answers. A row whose status `gh` contradicts shows, in yellow after its status, `stale:` and the live state that contradicts it, the sign the file needs a refresh: `stale: open` or `stale: closed` on a ✅ row with a pull request open (a draft too) or closed unmerged; `stale: merged` or `stale: closed` on a 🔧, ⏳, 👤 or ⚠️ row once all its pull requests are merged or closed, and on a 🗑️ row once its pull request is. A ❓ row, and a row with a pull request `gh` could not read, is never stale; nor is a ⚠️ row whose checks are green, since `gh`'s answer does not say whether it conflicts.
- **Workers**: the other tabs of the terminal session labelled by the topic (this one, or another the terminal lists), each with its state read from its screen: `●` running, `◆` waiting for you, `○` idle, `✓` done or `✗` blocked on its `AFK` line, `›` a shell; then the last thing it said. Outside a terminal whose sessions the pane can read, it reads `not in a terminal session`, and `terminal sessions unreachable` when the terminal does not answer.
- **Open questions**: the `## Qn — title` headings of the topic's `*-open-questions.md` plans still `todo` or `doing`, without those a `**Decided**` line answers. Each shows as `▸ Qn` and its title cut to one line; a press on it shows the whole title, wrapped, and `▾ Qn` closes it.
- **Awaiting you**: the entries of the topic's decision register (factory's `documents/registers`, or an older one in `~/Notes/claude/decisions-register`) still `proposed`, linked to the register. Each shows as `▸ Dnn` and the decision cut to one line; a press on it shows the whole decision, wrapped, and beneath it, dimmed, its `Why:` clause, so it can be judged from the pane. `▾ Dnn` closes it; one row is open at a time across the pane, a sub-agent or a commit of Misc included.

The panel computes it all live from the notes, `gh` and the terminal: no skill or worker writes a state file for it.

# Configuration

Opening the pane, the settings it reads, and what it cannot know. [Back to the README](../README.md)

## Opening the pane

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width. Docked beside a fullscreen transcript it opens as wide as Claude Code allows, 45% of the terminal, unless a width was dragged or keyed since.

It is a mod: a plugin of function hooks, drawn by the engine (no shell script, no status line).

## Settings

The pane has no option of its own. It reads Claude Code's `plansDirectory` and the handover plugin's `handover_dir` and token thresholds. The **Config** tab lists each one as in effect, with what it does and its default.

## Limits

- Steps and sub-agents are recorded from the moment the plugin loads; the first prompt is read back from the transcript.
- The handover thresholds come from the handover plugin's `options.json` or its defaults (150k suggested, 185k trigger), not from `CLAUDE_PLUGIN_OPTION_*` overrides.

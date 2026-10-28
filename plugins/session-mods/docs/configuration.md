# Configuration

Opening the pane, the settings it reads, and what it cannot know. [Back to the README](../README.md)

## Opening the pane

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width. Docked beside a fullscreen transcript it opens as wide as Claude Code allows, 45% of the terminal, unless a width was dragged or keyed since.

It is a mod: a plugin of function hooks, drawn by the engine (no shell script, no status line).

## Settings

The bar's one option, `cacheTtl`, is described in [Bar](bar.md#configuration). The pane has no option of its own. It reads Claude Code's `plansDirectory` and the handover plugin's `handover_dir` and token thresholds. The **Config** tab lists each one as in effect, with what it does, and its default for the first two.

## Limits

- Steps and sub-agents are recorded from the moment the plugin loads; the first prompt is read back from the transcript.
- The handover thresholds are those this session runs with: the `thresholds` the handover plugin records in the session's state, `sessions/<session_id>.json` in its data folder, at session start (handover 0.20.0 and later), the point where its line turns yellow included. The pane has no default of its own: when it cannot read them, the Handover row and the Config tab say why. A `suggest_tokens` or `trigger_tokens` set in `settings.json` since then shows beneath it in the Config tab, as applying from the next session.
- `handover_dir` comes from the handover plugin's options in `settings.json`, `pluginConfigs["handover@fundrivendev"].options`.

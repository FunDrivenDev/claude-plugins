# Configuration

Opening the pane, its one setting, and what it cannot know. [Back to the README](../README.md)

## Opening the pane

The pane opens at session start when the terminal is at least 144 columns wide; `/session-panel` opens it at any width. Docked beside a fullscreen transcript it opens 116 columns wide, unless a width was dragged or keyed since.

It is a mod: a plugin of function hooks, drawn by the engine (no shell script, no status line).

## Settings

| Setting | Default | What it does |
|---|---|---|
| `cacheTtl` | `1h` | The prompt-cache lifetime the countdown starts from (`1h` or `5m`), until a model switch reports the real one. In `/config`. |

The pane also reads Claude Code's `autoCompactWindow` and `plansDirectory`, the `CC_TOKEN_LIMIT` and `CC_TOKEN_RESERVE` variables, and the handover plugin's `handover_dir` and token thresholds. The **Config** tab lists each one as in effect, with what it does and its default.

## Limits

- Steps and sub-agents are recorded from the moment the plugin loads; the first prompt is read back from the transcript.
- The handover thresholds come from the handover plugin's `options.json` or its defaults (150k suggested, 185k trigger), not from `CLAUDE_PLUGIN_OPTION_*` overrides.
- The TTL is not reported per request: the countdown uses the setting until a model switch tells the real one.

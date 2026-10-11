# Development

[Back to the README](../README.md)

- `claude plugin test plugins/session-panel` runs `tests/`.
- `just validate` runs it with the validator.
- Once Claude Code has loaded the plugin, `tsc -p plugins/session-panel` type-checks it against the types the engine lays in `.claude-plugin/types/` (ignored by git).
- `docs/screenshot.png` is a capture of the pane docked in Ghostty (`screencapture -l <window id>`); retake it when the pane's look changes.

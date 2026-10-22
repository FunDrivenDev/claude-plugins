# Development

[Back to the README](../README.md)

- `hooks/register.tsx` is the plugin's one hooks module: it calls `registerPanel` (`hooks/panel.tsx`) and `registerBar` (`hooks/bar.tsx`), and hooks once the events both mods need, `session.start` and `turn.step`, running each mod's exported work there (the validator refuses a second unmatched hook on one event). Both mods' state shares the `session-mods` namespace, so a new atom key must not reuse one of the other mod's.
- `claude plugin test plugins/session-mods` runs `tests/`, the pane's and the bar's.
- `just validate` runs it with the validator.
- Once Claude Code has loaded the plugin, `tsc -p plugins/session-mods` type-checks it against the types the engine lays in `.claude-plugin/types/` (ignored by git).
- `docs/screenshot.png` is a capture of the pane docked in Ghostty (`screencapture -l <window id>`); retake it when the pane's look changes.

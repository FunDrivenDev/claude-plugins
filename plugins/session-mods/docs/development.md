# Development

[Back to the README](../README.md)

- `hooks/register.tsx` is the plugin's one hooks module, and holds every hook and every function handed `$`: Claude Code follows `$` and `on` only into functions of that same file and refuses the module otherwise (`claude plugin validate` says so). The bar's hooks and the pane's each sit in a block of their own inside `register`, which hooks once the events both need, `session.start` and `turn.step` (the validator refuses a second unmatched hook on one event). Both mods' state shares the `session-mods` namespace, so a new atom key must not reuse one of the other mod's.
- `hooks/bar.tsx` and `hooks/panel.tsx` hold each mod's pure helpers (formatting, colours, parsing), which `register.tsx` imports and `tests/` checks; `files.ts`, `documents.ts`, `handover.ts` and `tracker.ts` hold the shared ones.
- `hooks/appearance.ts` holds what both mods draw with: the light twin of each colour (`LIGHT`, one map for both), `recolor`, `prettyModel` and `duration`. `register.tsx` reads the OS appearance at `session.start`, then every 5 s, and each mod's render reads it with `currentScheme()`. A colour either mod draws gets its light twin in `appearance.ts`.
- `claude plugin test plugins/session-mods` runs `tests/`, the pane's and the bar's.
- `just validate` runs it with the validator.
- Once Claude Code has loaded the plugin, `tsc -p plugins/session-mods` type-checks it against the types the engine lays in `.claude-plugin/types/` (ignored by git).
- `docs/screenshot.png` is a capture of the pane docked in Ghostty (`screencapture -l <window id>`); retake it when the pane's look changes.

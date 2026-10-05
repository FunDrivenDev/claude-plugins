# statusline

A Claude Code status line built around what ends a session's memory (auto-compaction) and what makes it expensive (an expired prompt cache, the quotas).

```
⌛1h06m TTL 42m │ Opus 3/5 │ 90.0k/167k 53% │ <plugin segments>
5h ███│░░░░░░░  30% ok →60% 🔄2h30m │ 7d █████│░░░░  50% ok →75% 🔄2d07h │ ⎇ feat/my-branch* #412✓
```

A dim `·` line sits under each line, as spacing (`CC_STATUS_SPACING=0` drops it).

The first line, left to right:

- session duration, then the time left before the prompt cache expires (`EXP 🔄N` once it has: the tokens the next message pays for in full);
- model, effort out of 5 (in `/effort`'s colours), `⚡` in fast mode, `¬think` without thinking;
- context tokens against the **auto-compact trigger** (`autoCompactWindow` minus a reserve), not the model's window; green → yellow → orange → red, then `⚠ COMPACTING`;
- one segment per plugin that ships one (see [Plugin segments](#plugin-segments)).

The second line:

- 5-hour and 7-day quotas: a usage bar, `│` where even spending would put you by now, the verdict projected to the reset (`ok →N%`, `tight →N%`, `out <duration>`, `max`), and the time to the reset;
- branch (`*` when tracked files changed), worktree, PR number with `✓` approved / `✗` changes requested.

## Install

```
/plugin marketplace add FunDrivenDev/claude-plugins
/plugin install statusline@fundrivendev
/statusline:install
```

`/statusline:install` copies the script into the plugin's data directory (`~/.claude/plugins/data/statusline-fundrivendev/`) and points `statusLine` in `~/.claude/settings.json` at it, after saving the status line in place. A plugin update reaches the copy at the next session start.

To go back: `/statusline:uninstall` restores the saved status line, then `/plugin uninstall statusline@fundrivendev`.

Needs `bash` (macOS's 3.2 is fine), `jq` 1.6 or later, and `git`.

## Settings (environment variables)

| Variable | Default | Role |
|---|---|---|
| `CC_TOKEN_LIMIT` | the settings' `autoCompactWindow`, else 200000 | the auto-compact window |
| `CC_TOKEN_RESERVE` | 33000 | gap between the window and where compaction really fires |
| `CC_TOKEN_WARN` / `CC_TOKEN_DANGER` / `CC_TOKEN_ALERT` | 50 / 75 / 90 | colour thresholds, in % of the limit |
| `CC_STATUS_GIT_DIRTY` | 1 | `0` skips the `*` check on a huge repo |
| `CC_QUOTA_BAR` | 10 | cells per quota bar, `0` hides the bars |
| `CC_PACE_MIN` | 10 | % of a window that must elapse before a projection shows |
| `CC_STATUS_SEGMENTS` | 1 | `0` skips the plugin segments |
| `CC_STATUS_SPACING` | 1 | `0` drops the dim `·` spacer line under each line |
| `CC_STATUS_LAZY` | 1 | `0` computes git and the plugin segments before printing (see [Lazy segments](#lazy-segments)) |

An unusable setting never blanks the line; it is reported instead:

- a value that is not an integer, or `WARN` / `DANGER` / `ALERT` out of order: the default applies, and a leading `⚠ ignored: …` segment names the variables (likewise for a non-numeric `autoCompactWindow`);
- a window no larger than the reserve (`CC_TOKEN_LIMIT=20000` with the default 33000 reserve): the context segment shows `⚠ CC_TOKEN_LIMIT 20000 ≤ CC_TOKEN_RESERVE 33000` rather than a meaningless percentage;
- `jq` missing or too old: only `⚠ jq not found` / `⚠ jq failed (1.6+ needed)` shows.

## Plugin segments

Any installed plugin can add a segment at the end of the first line by shipping an executable `statusline-segment` at its root. It gets the same JSON payload on stdin (compacted) and prints one line, or nothing; a non-zero exit shows nothing. It must print nothing where its plugin is disabled: the status line cannot tell.

## Lazy segments

Git and the plugin segments are the slow part of a refresh (a `git status`, a plugin's own interpreter starting). They never delay the line: each refresh prints the value the previous refresh computed, a dim `…` before the first one, and recomputes it in the background. They therefore lag one refresh behind; set `statusLine.refreshInterval` (seconds) in `settings.json` to bound that lag while idle. A run still going when the next refresh comes is not started again, so a slow or hung segment never piles up.

The values are kept in `$TMPDIR/claude-statusline-$UID/`, per directory for git and per session and plugin for the segments. `CC_STATUS_LAZY=0` goes back to computing them before printing.

# Settings

Every setting is an environment variable. [Back to the README](../README.md)

| Variable | Default | Role |
|---|---|---|
| `CC_TOKEN_LIMIT` | the settings' `autoCompactWindow`, else 200000 | the auto-compact window |
| `CC_TOKEN_RESERVE` | 33000 | gap between the window and where compaction really fires |
| `CC_TOKEN_WARN` / `CC_TOKEN_DANGER` / `CC_TOKEN_ALERT` | 50 / 75 / 90 | colour thresholds, in % of the limit |
| `CC_STATUS_GIT_DIRTY` | 1 | `0` skips the `*` check on a huge repo |
| `CC_QUOTA_BAR` | 10 | cells per quota bar, `0` hides the bars |
| `CC_PACE_MIN` | 10 | % of a window that must elapse before a projection shows |
| `CC_STATUS_SEGMENTS` | 1 | `0` skips the plugin segments |
| `CC_STATUS_SPACING` | 1 | `0` drops the dim `·` spacer line between the two lines |
| `CC_STATUS_LAZY` | 1 | `0` computes git and the plugin segments before printing (see [Lazy segments](segments.md#lazy-segments)) |

An unusable setting never blanks the line; it is reported instead:

- a value that is not an integer, or `WARN` / `DANGER` / `ALERT` out of order: the default applies, and a leading `⚠ ignored: …` segment names the variables (likewise for a non-numeric `autoCompactWindow`);
- a window no larger than the reserve (`CC_TOKEN_LIMIT=20000` with the default 33000 reserve): the context segment shows `⚠ CC_TOKEN_LIMIT 20000 ≤ CC_TOKEN_RESERVE 33000` rather than a meaningless percentage;
- `jq` missing or too old: only `⚠ jq not found` / `⚠ jq failed (1.6+ needed)` shows.

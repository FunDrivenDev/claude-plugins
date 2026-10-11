# Layout

What each segment of the two lines shows. [Back to the README](../README.md)

```
⌛1h06m TTL 42m │ Opus 3/5 │ 90.0k/167k 53% │ <plugin segments>
5h ███│░░░░░░░  30% ok →60% 🔄2h30m │ 7d █████│░░░░  50% ok →75% 🔄2d07h │ ⎇ feat/my-branch* #412✓
```

A dim `·` line sits between the two lines, as spacing (`CC_STATUS_SPACING=0` drops it).

The first line, left to right:

- session duration, then the time left before the prompt cache expires (`EXP 🔄N` once it has: the tokens the next message pays for in full);
- model, effort out of 5 (in `/effort`'s colours), `⚡` in fast mode, `¬think` without thinking;
- context tokens against the **auto-compact trigger** (`autoCompactWindow` minus a reserve), not the model's window; green → yellow → orange → red, then `⚠ COMPACTING`;
- one segment per plugin that ships one (see [Plugin segments](segments.md#plugin-segments)).

The second line:

- 5-hour and 7-day quotas: a usage bar, `│` where even spending would put you by now, the verdict projected to the reset (`ok →N%`, `tight →N%`, `out <duration>`, `max`), and the time to the reset;
- branch (`*` when tracked files changed), worktree, PR number with `✓` approved / `✗` changes requested.

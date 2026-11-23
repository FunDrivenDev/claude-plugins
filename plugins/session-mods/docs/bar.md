# Bar

A one-row bar beneath Claude Code's prompt: how long the session has run, when the prompt cache expires, how full the context is, the 5-hour and 7-day quotas, and the model and effort, each switchable with a click. [Back to the README](../README.md)

## Items

- **Running time**: since the session started.
- **Cache countdown**: the time left before the prompt cache expires, counted from the last request.
- **Context**: the tokens in use against factory's handover trigger, its suggested handover point in brackets (`123.4k/400k (300k) 30%`): green below the suggested point, yellow to halfway from it to the trigger, then orange, and red with `⚠ handing over` once the trigger is reached. Without factory, against the auto-compact trigger, green to half of it, then yellow, orange and red, and `⚠ compacting` once reached.
- **Quotas**: the 5-hour and 7-day usage, coloured by where the current pace lands at the reset; a click unfolds the details.
- **Model and effort**: the current ones as chips; a click opens a picker that switches them.
- **Colours**: Catppuccin Frappé.

The bar sits beneath the engine's own hint line, which stays in place.

## Configuration

The `cacheTtl` option (`1h` or `5m`, `1h` by default) sets the prompt-cache lifetime the countdown starts from; a model switch reports the real one.

The context counter reads its thresholds from `factory relay show --json`, run in the session's folder when the session starts (never holding its start) and every 30 seconds after, each run given 3 seconds: its `trigger` and its `suggest` (`handover_tokens` and `handover_suggest_tokens` in factory's configuration; no brackets while `suggest` is unset). Factory is looked up on the `PATH` once, when the session starts (`command -v factory`): where it is missing, the bar never runs it during that session. Where factory is missing, fails or answers no trigger, the counter takes the auto-compact trigger from the engine; where the engine gives none, it reckons it from the `CC_TOKEN_LIMIT` environment variable, else the `autoCompactWindow` setting, else 200k, less `CC_TOKEN_RESERVE` (33k by default).

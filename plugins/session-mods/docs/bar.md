# Bar

A one-row bar beneath Claude Code's prompt: how long the session has run, when the prompt cache expires, how full the context is, the 5-hour and 7-day quotas, and the model and effort, each switchable with a click. [Back to the README](../README.md)

## Items

- **Running time**: since the session started.
- **Cache countdown**: the time left before the prompt cache expires, counted from the last request.
- **Context**: the tokens in use against the auto-compact trigger, how the trigger is reckoned in brackets, green to half of it, then yellow, orange and red, and `⚠ compacting` once reached.
- **Quotas**: the 5-hour and 7-day usage, coloured by where the current pace lands at the reset; a click unfolds the details.
- **Model and effort**: the current ones as chips; a click opens a picker that switches them.
- **Colours**: Catppuccin Frappé.

The bar sits beneath the engine's own hint line, which stays in place.

## Configuration

The `cacheTtl` option (`1h` or `5m`, `1h` by default) sets the prompt-cache lifetime the countdown starts from; a model switch reports the real one.

The context counter takes the auto-compact trigger from the engine. Where the engine gives none, it reckons it from the `CC_TOKEN_LIMIT` environment variable, else the `autoCompactWindow` setting, else 200k, less `CC_TOKEN_RESERVE` (33k by default).

---
name: config
description: Set the handover plugin's options one by one - each question explains the option, its default and its current value, then the answers are saved as the plugin's configuration.
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py *)
---

# Handover config

Run:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" config
```

On a non-zero exit code, show the error from stderr, as is, and stop. Otherwise stdout is JSON: `plugin`, the `settings` file the values go to, its `chezmoi_source` (null unless chezmoi manages it), and `options`, each with its `key`, `title`, `description`, `default`, `min`/`max` when it has bounds, `choices` when it has a fixed set, `configured`, `current` (null while unset: the default applies) and `seen_by_hooks` (the value the last hook run used).

Ask about every option with AskUserQuestion, in the order of `options` (`handover_dir`, the base folder, comes first), up to four questions per call, one option per question:

- Question: the option's `title` and `key`, its `description` in one or two plain sentences, then `Default: <default>. Current: <current, or "not set, the default applies">.` Mention `seen_by_hooks` only when it differs from what applies.
- Header: a short form of the title (12 characters at most).
- Choices: first `Keep <current or default> (Recommended)`; then `Default (<default>)` when an option is set to another value; then one or two values worth weighing, each with its effect (for a token threshold, one lower and one higher, within `min`/`max`, saying what moves earlier or later; for a boolean, the other value; for `writer_model`, another model alias). The user can always type another value.

Collect only the answers that change what applies. Check each against the option: a number within `min`/`max`, a folder as an absolute or `~` path, one of the `choices`. Ask again about any answer that fails, saying why. With no change, say so in one line and stop.

Save the changes, as one shell-quoted JSON object of strings:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/handover.py --data-dir "${CLAUDE_PLUGIN_DATA}" config --set '{"<key>": "<value>", ...}'
```

- Exit code 0: list the changed options, old value → new value, in a short table. The hooks read the new values on their next run; the status line, once a hook has run.
- When the output's `chezmoi_source` is not null, the settings file is generated from that source, and the next `chezmoi apply` would undo the change: write the same values into its `pluginConfigs` entry for the plugin, following the source repo's own instructions (its `AGENTS.md`), and say so.
- Otherwise: show the error, as is.

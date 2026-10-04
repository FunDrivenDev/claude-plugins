---
name: uninstall
description: Put back the status line that /statusline:install replaced, or none. Use when the user asks to remove, uninstall or revert the FunDrivenDev status line, before uninstalling the plugin.
allowed-tools: Bash(bash *scripts/uninstall.sh*)
---

# Uninstall the status line

Run the uninstaller; never edit `settings.json` by hand:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" bash "${CLAUDE_PLUGIN_ROOT}/scripts/uninstall.sh"
```

It acts only when this plugin's status line is the one in place: it restores the `statusLine` saved at install, or removes the key when there was none.

Report its output. To remove the plugin as well, the user runs `/plugin uninstall statusline@fundrivendev` afterwards: uninstalling first deletes the data directory the status line runs from, and leaves the status line blank.

On a `✗` line, report it verbatim and stop: do not retry, and do not edit the files it names.

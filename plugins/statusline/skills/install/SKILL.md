---
name: install
description: Make this plugin's context-budget status line Claude Code's status line, keeping the current one to restore later. Use when the user asks to install, set up, switch to or update the FunDrivenDev status line.
allowed-tools: Bash(bash *scripts/install.sh*)
---

# Install the status line

Run the installer; never edit `settings.json` by hand, the installer keeps every other key:

```bash
CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" bash "${CLAUDE_PLUGIN_ROOT}/scripts/install.sh"
```

It copies `statusline.sh` into the plugin's data directory, saves the `statusLine` in place (when it is not already this one), and points `statusLine` in `~/.claude/settings.json` at the copy.

Report from its output: the installed path, the previous status line it saved, that `/statusline:uninstall` puts that one back, and that the copy refreshes itself at each session start after a plugin update. The new status line shows within ten seconds; restart Claude Code if it does not.

On a `✗` line, report it verbatim and stop: do not retry, and do not edit the files it names.

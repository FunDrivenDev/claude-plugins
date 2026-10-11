# Install and uninstall

What `/statusline:install` changes, and how to go back. [Back to the README](../README.md)

`/statusline:install` copies the script into the plugin's data directory (`~/.claude/plugins/data/statusline-fundrivendev/`) and points `statusLine` in `~/.claude/settings.json` at it, after saving the status line in place. A plugin update reaches the copy at the next session start.

To go back: `/statusline:uninstall` restores the saved status line, then `/plugin uninstall statusline@fundrivendev`.

Needs `bash` (macOS's 3.2 is fine), `jq` 1.6 or later, and `git`.

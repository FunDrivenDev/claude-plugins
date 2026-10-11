# Segments

How plugins add a segment, and why git and the segments lag one refresh. [Back to the README](../README.md)

## Plugin segments

Any installed plugin can add a segment at the end of the first line by shipping an executable `statusline-segment` at its root. It gets the same JSON payload on stdin (compacted) and prints one line, or nothing; a non-zero exit shows nothing. It must print nothing where its plugin is disabled: the status line cannot tell.

## Lazy segments

Git and the plugin segments are the slow part of a refresh (a `git status`, a plugin's own interpreter starting). They never delay the line: each refresh prints the value the previous refresh computed, a dim `…` before the first one, and recomputes it in the background. They therefore lag one refresh behind; set `statusLine.refreshInterval` (seconds) in `settings.json` to bound that lag while idle. A run still going when the next refresh comes is not started again, so a slow or hung segment never piles up.

The values are kept in `$TMPDIR/claude-statusline-$UID/`, per directory for git and per session and plugin for the segments. `CC_STATUS_LAZY=0` goes back to computing them before printing.

#!/usr/bin/env bash
# Put back the status line that install.sh replaced (or none), when ours is the
# one in place. Safe to re-run.
set -euo pipefail
# shellcheck source=common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

check_settings
real=$(resolve "$SETTINGS")
current=""
[ -e "$real" ] && current=$(jq -r '.statusLine.command? // empty' "$real")

if [ "$current" != "$INSTALLED" ]; then
  echo "✓ nothing to undo: the status line in place is not this plugin's (${current:-none})"
  exit 0
fi

previous=null
[ -r "$SAVED" ] && previous=$(jq -c . "$SAVED" 2>/dev/null || echo null)
if [ "$previous" = null ]; then
  write_settings 'del(.statusLine)'
  echo "✓ $SETTINGS: statusLine removed (there was none before)"
else
  write_settings --argjson prev "$previous" '.statusLine = $prev'
  echo "✓ $SETTINGS: statusLine restored to $previous"
fi
rm -f "$SAVED"
echo "✓ to remove the plugin too: /plugin uninstall statusline@fundrivendev"

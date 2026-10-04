#!/usr/bin/env bash
# Point Claude Code's status line at this plugin's, keeping the previous one
# for uninstall.sh. Safe to re-run: it only refreshes the copy then.
set -euo pipefail
# shellcheck source=common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

check_settings
sync_copy
echo "✓ status line copied to $INSTALLED"

real=$(resolve "$SETTINGS")
mkdir -p "$(dirname "$real")"
[ -e "$real" ] || echo '{}' >"$real"

current=$(jq -r '.statusLine.command? // empty' "$real")
if [ "$current" != "$INSTALLED" ]; then
  # Saved only when the status line in place is not ours, so a rerun never
  # loses the one to go back to.
  jq '.statusLine // null' "$real" >"$SAVED"
  [ -n "$current" ] && echo "✓ previous status line saved: $current"
fi

# refreshInterval: without it, the cache countdown and the quotas freeze
# between two messages.
write_settings --arg cmd "$INSTALLED" \
  '.statusLine = {type: "command", command: $cmd, padding: 0, refreshInterval: 10}'
echo "✓ $SETTINGS: statusLine runs $INSTALLED"

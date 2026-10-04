# Sourced by the plugin's scripts: where things live.
# shellcheck shell=bash disable=SC2034  # the variables are read by the scripts sourcing this one

PLUGIN_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CLAUDE_HOME=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
# Claude Code's persistent directory for this plugin. Hooks and skills pass it
# in; the fallback is where Claude Code puts it for statusline@fundrivendev.
DATA_DIR=${CLAUDE_PLUGIN_DATA:-$CLAUDE_HOME/plugins/data/statusline-fundrivendev}
# The status line runs from a copy in DATA_DIR: the plugin's own path changes
# with every version, and the data directory survives updates.
INSTALLED="$DATA_DIR/statusline.sh"
SETTINGS="$CLAUDE_HOME/settings.json"
# The statusLine that was in place before ours, restored by uninstall.sh.
SAVED="$DATA_DIR/previous-statusline.json"

# Copy the status line into DATA_DIR when it differs, atomically: Claude Code
# may run it mid-copy.
sync_copy() {
  cmp -s "$PLUGIN_ROOT/statusline.sh" "$INSTALLED" && return 0
  mkdir -p "$DATA_DIR"
  local tmp
  tmp=$(mktemp "$INSTALLED.XXXXXX")
  cp "$PLUGIN_ROOT/statusline.sh" "$tmp"
  chmod +x "$tmp"
  mv "$tmp" "$INSTALLED"
}

# The real file at the end of a symlink chain (no readlink -f on old macOS), so
# a settings.json linked from elsewhere is written in place, link kept.
resolve() {
  local p=$1 l n=0
  while [ -L "$p" ]; do
    n=$((n + 1)); [ "$n" -le 40 ] || { echo "✗ symlink loop: $1" >&2; exit 1; }
    l=$(readlink "$p")
    case $l in /*) p=$l ;; *) p="$(dirname "$p")/$l" ;; esac
  done
  printf '%s' "$p"
}

# write_settings FILTER [jq args...]: rewrite settings.json through FILTER,
# atomically, keeping every other key and the file's permissions.
write_settings() {
  local real tmp
  real=$(resolve "$SETTINGS")
  tmp=$(mktemp "$real.XXXXXX")
  cp -p "$real" "$tmp"
  if ! jq "$@" "$real" >"$tmp"; then
    rm -f "$tmp"
    echo "✗ could not write $SETTINGS; it was left unchanged" >&2
    exit 1
  fi
  mv "$tmp" "$real"
}

# Stop unless settings.json is absent or valid JSON, before any write.
check_settings() {
  command -v jq >/dev/null || { echo "✗ jq is required (brew install jq, or apt install jq)" >&2; exit 1; }
  local real
  real=$(resolve "$SETTINGS")
  if [ -L "$SETTINGS" ] && [ ! -e "$real" ]; then
    echo "✗ $SETTINGS is a broken symlink (to $real); nothing was changed" >&2; exit 1
  fi
  if [ -e "$real" ] && ! jq -e 'type == "object"' "$real" >/dev/null 2>&1; then
    echo "✗ $SETTINGS is not a JSON object; nothing was changed" >&2; exit 1
  fi
}

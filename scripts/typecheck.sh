#!/usr/bin/env bash
# Type-check each mod (a plugin with a tsconfig.json) against the types of the
# Claude Code version mise.toml pins (ci.yml: the latest release). Claude Code lays
# them in .claude-plugin/types/ only when it loads the mod, so a headless start
# loads it first: a throwaway config dir and an invalid API key, so the call is
# refused before any token is spent. A -p run watches (and so types) a
# --plugin-dir mod only under CLAUDE_CODE_PLUGIN_DIR_WATCH
# (Claude Code 2.1.322; 2.1.289 typed it regardless).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Claude Code pinned in mise.toml (local-first-ci D70); ci.yml sets CLAUDE to the latest release.
claude=${CLAUDE:-$(mise which claude)} || { echo "typecheck: no claude from mise.toml; run just init" >&2; exit 1; }
root=$PWD
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for config in plugins/*/tsconfig.json; do
  [[ -f "$config" ]] || continue
  dir=$root/$(dirname "$config")
  rm -rf "$dir/.claude-plugin/types"
  # Out of the repo and of any hook's git env, so the load reads nothing else of ours.
  (
    # shellcheck disable=SC2046 # one name per variable
    unset $(git rev-parse --local-env-vars) CLAUDE_CODE_OAUTH_TOKEN
    cd "$tmp"
    CLAUDE_CODE_PLUGIN_DIR_WATCH=1 CLAUDE_CONFIG_DIR=$tmp/config ANTHROPIC_API_KEY=sk-ant-typecheck-no-key \
      "$claude" --plugin-dir "$dir" -p --max-turns 1 hi >/dev/null 2>&1 || true
  )
  [[ -f "$dir/.claude-plugin/types/claude-code/index.d.ts" ]] \
    || { echo "typecheck: claude $("$claude" --version) laid no types in $dir/.claude-plugin/types" >&2; exit 1; }
  echo "== tsc -p $(dirname "$config")"
  mise exec -- tsc -p "$dir"
done

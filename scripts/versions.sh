#!/usr/bin/env bash
# Fail when a plugin changed since the base (origin/main by default) without a
# version bump: installs only update when plugin.json's version changes, so the
# bump is what turns a merged PR into a release. Changes under tests/ alone
# don't count, and a plugin new since the base passes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

base=$(git merge-base "${VERSION_BASE:-origin/main}" HEAD)
version() { git show "$1:$2/.claude-plugin/plugin.json" 2>/dev/null | jq -r .version; }

stale=0
for dir in plugins/*/; do
  dir=${dir%/}
  git cat-file -e "$base:$dir/.claude-plugin/plugin.json" 2>/dev/null || continue
  git diff --quiet "$base" -- "$dir" ":(exclude)$dir/tests" && continue
  old=$(version "$base" "$dir")
  new=$(jq -r .version "$dir/.claude-plugin/plugin.json")
  if [ "$old" = "$new" ]; then
    echo "versions: ${dir#plugins/} changed but is still $new; run just bump ${dir#plugins/} patch|minor|major" >&2
    stale=1
  fi
done
exit "$stale"

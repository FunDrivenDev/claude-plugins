#!/usr/bin/env bash
# Usage: files.sh <scope> <pattern>. Prints the files in scope whose path matches
# `pattern` (an extended regex), one per line. Scopes: all, changed (since the
# merge-base with origin/main, or CI_BASE), staged (the index).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

scope=$1
pattern=$2
case "$scope" in
  all) files=$(git ls-files --cached --others --exclude-standard) ;;
  changed)
    ref=${CI_BASE:-origin/main}
    git rev-parse --verify --quiet "$ref^{commit}" >/dev/null || ref=main
    base=$(git merge-base "$ref" HEAD 2>/dev/null || true)
    if [[ -z "$base" ]]; then
      files=$(git ls-files --cached --others --exclude-standard)
    else
      files=$( { git diff --name-only --diff-filter=d "$base"; git ls-files --others --exclude-standard; } | sort -u)
      # A change to the toolchain can change any result: check everything then.
      if printf '%s\n' "$files" | grep -qE '^(mise\.(toml|lock)|[Jj]ustfile|hk\.pkl|biome\.json|ruff\.toml|scripts/.*\.sh|\.github/workflows/.*)$'; then
        files=$(git ls-files --cached --others --exclude-standard)
      fi
    fi ;;
  staged) files=$(git diff --cached --name-only --diff-filter=d) ;;
  *) echo "unknown scope $scope: all, changed or staged" >&2; exit 2 ;;
esac
printf '%s\n' "$files" | grep -E "$pattern" | while read -r f; do [[ -f "$f" ]] && echo "$f"; done || true

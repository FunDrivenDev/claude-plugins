#!/usr/bin/env bash
# Usage: lint.sh [scope]. Lint the files in scope (all, changed, staged), each kind
# with its linter: shellcheck, actionlint, biome on the mods' TypeScript, ruff on
# the Python scripts. A kind with no file in scope is skipped.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

scope=${1:-all}
files() { scripts/files.sh "$scope" "$1"; }
run() { # run <pattern> <command…>: the command on the files in scope, if any
  local pattern=$1; shift
  local list; list=$(files "$pattern")
  [[ -z "$list" ]] && return 0
  printf '%s\n' "$list" | tr '\n' '\0' | xargs -0 mise exec -- "$@"
}

run '\.sh$' shellcheck
run '^\.github/workflows/.*\.ya?ml$' actionlint
run '^plugins/.*\.tsx?$' biome lint --error-on-warnings --no-errors-on-unmatched
run '\.py$' ruff format --check --quiet
run '\.py$' ruff check --quiet

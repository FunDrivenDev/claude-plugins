#!/usr/bin/env bash
# Validate the marketplace and each plugin with `claude plugin validate`, and
# run the tests of each plugin that has some (`claude plugin test`).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v claude >/dev/null || { echo "validate: the claude CLI is not on PATH" >&2; exit 1; }
claude plugin validate .
for dir in plugins/*/; do
  claude plugin validate "$dir"
  if [ -n "$(find "$dir" -name '*.test.ts' -o -name '*.test.tsx' | head -1)" ]; then
    claude plugin test "$dir"
  fi
done

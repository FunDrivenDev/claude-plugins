#!/usr/bin/env bash
# Validate the marketplace and each plugin with `claude plugin validate`, and
# run the tests of each plugin that has some (`claude plugin test`), with the
# Claude Code version mise.toml pins (ci.yml: the latest release).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Claude Code pinned in mise.toml (local-first-ci D70); ci.yml sets CLAUDE to the latest release.
claude=${CLAUDE:-$(mise which claude)} || { echo "validate: no claude from mise.toml; run just init" >&2; exit 1; }
"$claude" plugin validate .
for dir in plugins/*/; do
  "$claude" plugin validate "$dir"
  if [ -n "$(find "$dir" -name '*.test.ts' -o -name '*.test.tsx' | head -1)" ]; then
    "$claude" plugin test "$dir"
  fi
done

#!/usr/bin/env bash
# One-time setup on a new clone; each step checks first, so a rerun is a check.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

mise trust --quiet .
mise install --quiet
echo "✓ tools from mise.toml installed"

# The git hooks live in hk.pkl; a clone set up before them still points git at .githooks.
if [ "$(git config --get core.hooksPath || true)" = .githooks ]; then
  git config --unset core.hooksPath
fi
echo "✓ git hooks: hk.pkl (\`mise exec -- hk install\` where no global hook runs it)"

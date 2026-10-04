#!/usr/bin/env bash
# One-time setup on a new clone; each step checks first, so a rerun is a check.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

mise trust --quiet .
mise install --quiet
echo "✓ tools from mise.toml installed"

if [ "$(git config --get core.hooksPath || true)" != .githooks ]; then
  git config core.hooksPath .githooks
fi
echo "✓ git hooks: .githooks"

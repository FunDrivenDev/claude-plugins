#!/usr/bin/env bash
# Usage: fmt.sh [scope]. Format the files in scope (all, changed, staged): ruff on
# the Python scripts, the one kind with a formatter here (biome.json keeps biome's off).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

list=$(scripts/files.sh "${1:-all}" '\.py$')
[[ -z "$list" ]] && exit 0
printf '%s\n' "$list" | tr '\n' '\0' | xargs -0 mise exec -- ruff format --quiet

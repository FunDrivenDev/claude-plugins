#!/usr/bin/env bash
# Usage: audit.sh [scope]. `all`: gitleaks over the whole history, then zizmor on
# the workflows. `staged`: gitleaks on the index alone, the pre-commit hook's.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "${1:-all}" in
  all)
    mise exec -- gitleaks git --config .gitleaks.toml --redact --no-banner --log-level warn .
    mise exec -- zizmor --quiet .github/workflows ;;
  staged)
    mise exec -- gitleaks git --config .gitleaks.toml --staged --redact --no-banner --log-level warn . ;;
  *) echo "unknown scope $1: all or staged" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# Usage: test.sh. The plugins' smoke tests: every tests/*.sh, then every
# tests/*.py, in name order, stopping at the first failure; a name starting
# with _ is a helper, not a test. Run through `just test`, under mise.
set -euo pipefail
shopt -s nullglob
export LC_ALL=C
for t in tests/[!_]*.sh; do
    echo "== $t"
    "$t"
done
for t in tests/[!_]*.py; do
    echo "== $t"
    python3 "$t"
done

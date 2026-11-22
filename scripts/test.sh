#!/usr/bin/env bash
# Usage: test.sh. The plugins' smoke tests: every tests/*.sh, then every
# tests/*.py, in name order, stopping at the first failure; a name starting
# with _ is a helper, not a test. Run through `just test`, under mise.
set -euo pipefail
shopt -s nullglob
export LC_ALL=C
# A test that runs a script under a throwaway HOME still reaches the mise shims
# on PATH (jq among them, when the global mise config pins it): mise keeps its
# trust records and installs under the real home, so the shim would refuse the
# untrusted configs and fail every jq call.
export MISE_STATE_DIR="${MISE_STATE_DIR:-$HOME/.local/state/mise}"
export MISE_DATA_DIR="${MISE_DATA_DIR:-$HOME/.local/share/mise}"
for t in tests/[!_]*.sh; do
    echo "== $t"
    "$t"
done
for t in tests/[!_]*.py; do
    echo "== $t"
    python3 "$t"
done

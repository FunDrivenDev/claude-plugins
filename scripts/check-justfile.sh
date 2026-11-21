#!/usr/bin/env bash
# Usage: check-justfile.sh [justfile]. Refuses a justfile whose recipes would
# not all run the tools mise.toml pins, whatever the caller's shell (fundrivenOS
# rules/ci/just.md): its shell must be mise exec, and no recipe may have a
# shebang or [script] body, which just runs outside that shell.
set -euo pipefail

jf=${1:-}
if [[ -z $jf ]]; then
    for f in Justfile justfile .justfile; do
        if [[ -f $f ]]; then
            jf=$f
            break
        fi
    done
fi
want='set shell := ["mise", "exec", "--", "bash", "-euo", "pipefail", "-c"]'
grep -qxF "$want" "$jf" || {
    echo "$jf: every recipe runs through mise: $want" >&2
    exit 1
}
if grep -nE '^[[:space:]]+#!|^[[:space:]]*\[script' "$jf" >&2; then
    echo "$jf: a shebang or [script] recipe skips the mise shell: move its body to scripts/" >&2
    exit 1
fi

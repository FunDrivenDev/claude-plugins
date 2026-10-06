#!/usr/bin/env bash
# Smoke tests for scripts/versions.sh and scripts/bump.sh against a throwaway repo.
set -euo pipefail
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars)

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1"; failures=$((failures + 1)); }
passes() { if VERSION_BASE=main scripts/versions.sh 2>/dev/null; then pass "$1"; else fail "$1"; fi; }
# version NAME WANTED: the demo plugin's version is WANTED.
version() { if [ "$(jq -r .version plugins/demo/.claude-plugin/plugin.json)" = "$2" ]; then pass "$1"; else fail "$1"; fi; }
fails() { if VERSION_BASE=main scripts/versions.sh 2>/dev/null; then fail "$1"; else pass "$1"; fi; }

cd "$WORK"
git init -q -b main
mkdir -p scripts plugins/demo/.claude-plugin plugins/demo/tests plugins/demo/hooks
cp "$ROOT/scripts/versions.sh" "$ROOT/scripts/bump.sh" scripts/
printf '{\n  "name": "demo",\n  "version": "1.2.3"\n}\n' >plugins/demo/.claude-plugin/plugin.json
echo a >plugins/demo/hooks/h.ts
echo a >plugins/demo/tests/t.ts
git add -A && git -c user.name=t -c user.email=t@t commit -qm init
git checkout -qb feat

passes "no change passes"
echo b >plugins/demo/tests/t.ts
passes "a change under tests/ alone passes"
echo b >plugins/demo/hooks/h.ts
fails "a change without a bump fails"
scripts/bump.sh demo patch >/dev/null
passes "the same change with a bump passes"
version "patch bumps 1.2.3 to 1.2.4" 1.2.4
scripts/bump.sh demo minor >/dev/null
version "minor resets the patch" 1.3.0
scripts/bump.sh demo major >/dev/null
version "major resets minor and patch" 2.0.0
mkdir -p plugins/fresh/.claude-plugin
printf '{\n  "name": "fresh",\n  "version": "0.1.0"\n}\n' >plugins/fresh/.claude-plugin/plugin.json
passes "a new plugin passes"
if scripts/bump.sh demo huge >/dev/null 2>&1; then fail "bump refuses an unknown level"; else pass "bump refuses an unknown level"; fi

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)"; exit 1
fi
echo "all passed"

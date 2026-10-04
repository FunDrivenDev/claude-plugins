#!/usr/bin/env bash
# Smoke tests for the statusline plugin: the status line under each bash at
# hand (the default one and macOS's /bin/bash 3.2), and the install, uninstall
# and sync scripts against a throwaway home.
set -euo pipefail

# A git hook runs this with GIT_DIR, GIT_INDEX_FILE and the like pointing at
# this repository: left set, the test repo's `git init` and `git commit` would
# land here, and the status line would read this repository's branch.
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars)

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PLUGIN="$ROOT/plugins/statusline"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n%s\n' "$1" "${2:-}" | sed '3,$s/^/      /'; failures=$((failures + 1)); }
# expect NAME HAYSTACK NEEDLE: HAYSTACK contains NEEDLE.
expect() { case $2 in *"$3"*) pass "$1" ;; *) fail "$1" "wanted: $3"$'\n'"got:    $2" ;; esac; }
reject() { case $2 in *"$3"*) fail "$1" "unwanted: $3"$'\n'"got:      $2" ;; *) pass "$1" ;; esac; }
plain() { sed $'s/\033\\[[0-9;]*m//g'; }

# A home with settings, a plugin shipping a segment, and a git repo on a branch.
home="$WORK/home"
mkdir -p "$home/.claude/plugins" "$WORK/seg-plugin" "$WORK/repo"
echo '{"autoCompactWindow": 200000}' >"$home/.claude/settings.json"
printf '#!/bin/sh\ncat >/dev/null; echo "segment line"\n' >"$WORK/seg-plugin/statusline-segment"
chmod +x "$WORK/seg-plugin/statusline-segment"
jq -n --arg p "$WORK/seg-plugin" '{version: 2, plugins: {"seg@test": [{scope: "user", installPath: $p}]}}' \
  >"$home/.claude/plugins/installed_plugins.json"
git -C "$WORK/repo" init -q -b feat/smoke
git -C "$WORK/repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init

now=$(date +%s)
payload=$(jq -n --arg cwd "$WORK/repo" --argjson now "$now" '{
  model: {display_name: "Opus"}, effort: {level: "high"}, cwd: $cwd,
  cost: {total_duration_ms: 3960000},
  context_window: {total_input_tokens: 90000, current_usage: {}},
  rate_limits: {
    five_hour: {used_percentage: 30, resets_at: ($now + 9030)},
    seven_day: {used_percentage: 40, resets_at: ($now + 302400)}},
  prompt_cache: {caching_observed: true, warm: true, expires_at: ($now + 2550), ttl: "1h"}}')

shells=("$(command -v bash)")
[ -x /bin/bash ] && ! [ /bin/bash -ef "${shells[0]}" ] && shells+=(/bin/bash)

for sh in "${shells[@]}"; do
  echo "status line under $sh ($("$sh" -c 'echo $BASH_VERSION'))"
  run() { HOME=$home "$@" "$sh" "$PLUGIN/statusline.sh" | plain; }

  out=$(run env <<<"$payload")
  first=${out%%$'\n'*}
  expect "duration and cache countdown" "$first" "⌛1h06m TTL 42m"
  expect "model and effort" "$first" "Opus 3/5"
  expect "context against the auto-compact trigger" "$first" "90.0k/167k 53%"
  expect "5-hour quota" "$first" "30% ok →60%"
  expect "7-day quota" "$first" "40% ok →80%"
  expect "git branch" "$first" "⎇ feat/smoke"
  expect "plugin segment on its own line" "$out" $'\nsegment line'

  out=$(run env CC_STATUS_SEGMENTS=0 <<<"$payload")
  reject "CC_STATUS_SEGMENTS=0 drops the segments" "$out" "segment line"

  out=$(run env CC_TOKEN_WARN=abc <<<"$payload")
  expect "a non-integer setting is reported" "$out" "⚠ ignored: CC_TOKEN_WARN"
  expect "and its default applies" "$out" "90.0k/167k 53%"

  out=$(run env CC_TOKEN_LIMIT=20000 <<<"$payload")
  expect "a window under the reserve is reported" "$out" "⚠ CC_TOKEN_LIMIT 20000 ≤ CC_TOKEN_RESERVE 33000"

  if out=$(run env <<<'{not json'); then
    expect "malformed JSON falls back to defaults" "$out" "0/167k"
  else
    fail "malformed JSON exits non-zero"
  fi

  mkdir -p "$WORK/nojq"; ln -sf "$(command -v cat)" "$WORK/nojq/cat"
  out=$(run env PATH="$WORK/nojq" <<<"$payload")
  expect "missing jq is reported" "$out" "⚠ jq not found"
done

echo "install, uninstall and sync"
ihome="$WORK/ihome"
data="$ihome/.claude/plugins/data/statusline-fundrivendev"
mkdir -p "$ihome/.claude"
echo '{"theme": "dark", "statusLine": {"type": "command", "command": "/old.sh"}}' >"$ihome/.claude/settings.json"
script() { HOME=$ihome CLAUDE_PLUGIN_DATA="" bash "$PLUGIN/scripts/$1.sh" >/dev/null; }
settings() { jq -c "$1" "$ihome/.claude/settings.json"; }

script install
expect "install points statusLine at the copy" "$(settings .statusLine.command)" "\"$data/statusline.sh\""
expect "install keeps the other keys" "$(settings .theme)" '"dark"'
if [ -x "$data/statusline.sh" ] && cmp -s "$data/statusline.sh" "$PLUGIN/statusline.sh"; then
  pass "install copies the script, executable"
else
  fail "install copies the script, executable"
fi

script install
expect "a rerun keeps the saved status line" "$(jq -c . "$data/previous-statusline.json")" '"/old.sh"'

echo '# stale' >"$data/statusline.sh"
HOME=$ihome CLAUDE_PLUGIN_DATA=$data bash "$PLUGIN/scripts/sync.sh"
if cmp -s "$data/statusline.sh" "$PLUGIN/statusline.sh"; then
  pass "sync refreshes a stale copy"
else
  fail "sync refreshes a stale copy"
fi

script uninstall
expect "uninstall restores the previous status line" "$(settings .statusLine)" '{"type":"command","command":"/old.sh"}'
expect "uninstall keeps the other keys" "$(settings .theme)" '"dark"'
script uninstall
expect "a second uninstall changes nothing" "$(settings .statusLine.command)" '"/old.sh"'

rm "$ihome/.claude/settings.json"
script install
script uninstall
expect "without a previous status line, uninstall removes the key" "$(settings 'has("statusLine")')" false

echo '{broken' >"$ihome/.claude/settings.json"
if HOME=$ihome bash "$PLUGIN/scripts/install.sh" >/dev/null 2>&1; then
  fail "install refuses an unparseable settings.json"
else
  expect "install refuses an unparseable settings.json, untouched" "$(cat "$ihome/.claude/settings.json")" '{broken'
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)"; exit 1
fi
echo "all passed"

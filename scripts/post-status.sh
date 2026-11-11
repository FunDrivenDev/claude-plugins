#!/usr/bin/env bash
# Prototype (local-first-ci D53): once the pre-push checks passed, post a `checks`
# commit status on the pushed commit, so the PR shows the laptop's verdict. GitHub
# has the commit only after the push, which waits on this hook, so a detached job
# waits for it, then posts; the push never waits. Its log:
# ~/.local/state/post-status/<repo>-<sha>.log. Limit of the prototype: it posts on
# HEAD, the commit a push of the current branch sends.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

sha=$(git rev-parse HEAD)
# A prototype never refuses a push: without gh, or logged out, it posts nothing.
if ! command -v gh >/dev/null || ! repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null); then
  echo "post-status: skipped, gh is missing or cannot read the repo"
  exit 0
fi
log=${XDG_STATE_HOME:-$HOME/.local/state}/post-status/${repo//\//-}-$sha.log
mkdir -p "$(dirname "$log")"

nohup bash -c '
  repo=$1 sha=$2
  for _ in $(seq 90); do
    gh api "repos/$repo/commits/$sha" --silent 2>/dev/null && break
    sleep 2
  done
  gh api -X POST "repos/$repo/statuses/$sha" -f state=success -f context=checks \
    -f description="just check and just audit passed on the laptop" --jq ".state + \" \" + .context"
' post-status "$repo" "$sha" </dev/null >"$log" 2>&1 &
disown
echo "post-status: the checks status goes on ${sha:0:7} once GitHub has it ($log)"

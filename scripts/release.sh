#!/usr/bin/env bash
# Release every plugin changed since its last release, once CI is green on main:
# release.sh <sha>, the commit CI checked. For each plugin whose files (its tests/
# aside) changed since its last tag <plugin>-vX.Y.Z, it bumps plugin.json by the
# highest level its commits' subjects give (the squash-merged PRs' titles:
# `type!:` or a BREAKING CHANGE footer a major, `feat:` a minor, any other a
# patch), commits `release: <plugin> X.Y.Z`, tags it, pushes main and the tags in
# one atomic push, then publishes a GitHub release with those titles as notes. A
# plugin with no tag yet gets its current version as its first release.
#
# Installs update only when a version changes, so this turns a merge into a
# release; a run whose commit is no longer main's head (a newer merge landed)
# releases nothing, and the newer commit's run releases both once its checks pass.
# Env: RELEASE_REMOTE (origin), RELEASE_PUBLISH=0 stops before the push (a dry
# run), RELEASE_GH (gh) the command that publishes the releases.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

[ $# -eq 1 ] || { echo "usage: just release <sha>" >&2; exit 2; }
remote=${RELEASE_REMOTE:-origin}
gh=${RELEASE_GH:-gh}

git fetch -q --tags "$remote" main
head=$(git rev-parse "$remote/main")
checked=$(git rev-parse "$1^{commit}")

if ! git merge-base --is-ancestor "$checked" "$head"; then
  echo "release: $checked is not on $remote/main; nothing to release"
  exit 0
fi
if [ -n "$(git log --format=%H --invert-grep --grep='^release: ' "$checked..$head")" ]; then
  echo "release: $remote/main moved past $checked; the run on its head releases it"
  exit 0
fi
git checkout -q --detach "$head"

notes=$(mktemp -d)
trap 'rm -rf "$notes"' EXIT

# level <commit>: 3 major, 2 minor, 1 patch, from its subject and body.
breaking='^[[:alnum:]_-]+(\([^)]*\))?!:'
feature='^feat(\([^)]*\))?:'
level() {
  local subject body
  subject=$(git log -1 --format=%s "$1")
  body=$(git log -1 --format=%b "$1")
  if [[ $subject =~ $breaking ]] || grep -q '^BREAKING[ -]CHANGE:' <<<"$body"; then
    echo 3
  elif [[ $subject =~ $feature ]]; then
    echo 2
  else
    echo 1
  fi
}

tags=()
for dir in plugins/*/; do
  dir=${dir%/}
  name=${dir#plugins/}
  manifest=$dir/.claude-plugin/plugin.json
  [ -f "$manifest" ] || continue
  last=$(git tag --list "$name-v*" --sort=-v:refname | head -n1)
  if [ -z "$last" ]; then
    new=$(jq -r .version "$manifest")
    echo "First release." >"$notes/$name-v$new.md"
    git tag -a "$name-v$new" -m "$name $new"
    tags+=("$name-v$new")
    echo "release: $name $new, its first release"
    continue
  fi
  commits=$(git log --format=%H --invert-grep --grep='^release: ' "$last..HEAD" -- "$dir" ":(exclude)$dir/tests")
  [ -n "$commits" ] || continue
  top=1
  for c in $commits; do
    l=$(level "$c")
    [ "$l" -gt "$top" ] && top=$l
  done
  case $top in 3) kind="major" ;; 2) kind="minor" ;; *) kind="patch" ;; esac
  old=$(jq -r .version "$manifest")
  scripts/bump.sh "$name" "$kind" >/dev/null
  new=$(jq -r .version "$manifest")
  # Every subject, oldest first: GitHub links each (#N) to its PR.
  git log --reverse --format='- %s' --invert-grep --grep='^release: ' "$last..HEAD" -- "$dir" ":(exclude)$dir/tests" >"$notes/$name-v$new.md"
  git commit -q -m "release: $name $new" -- "$manifest"
  git tag -a "$name-v$new" -m "$name $new"
  tags+=("$name-v$new")
  echo "release: $name $old → $new ($kind)"
done

if [ ${#tags[@]} -eq 0 ]; then
  echo "release: no plugin changed since its last release"
  exit 0
fi
if [ "${RELEASE_PUBLISH:-1}" = 0 ]; then
  echo "release: dry run, nothing pushed: ${tags[*]}"
  exit 0
fi

refs=()
for t in "${tags[@]}"; do refs+=("refs/tags/$t"); done
git push -q --atomic "$remote" HEAD:refs/heads/main "${refs[@]}"
for t in "${tags[@]}"; do
  name=${t%-v*}
  "$gh" release create "$t" --verify-tag --title "$name ${t##*-v}" --notes-file "$notes/$t.md"
done

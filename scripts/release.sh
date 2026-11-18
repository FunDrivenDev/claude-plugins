#!/usr/bin/env bash
# Release every plugin changed since its last release, once CI is green on main:
# release.sh <sha>, the commit CI checked. For each plugin whose files (its tests/
# aside) changed since its last tag <plugin>-vX.Y.Z, it bumps plugin.json by the
# highest level its commits' subjects give (the squash-merged PRs' titles:
# `type!:` or a BREAKING CHANGE footer a major, `feat:` a minor, any other a
# patch), commits `release: <plugin> X.Y.Z`, tags it, and pushes main and the tags
# in one atomic push. Then each plugin's newest tag without a GitHub release gets
# one, the titles since its previous tag as notes: a release that failed to
# publish is published by the next run. A plugin with no tag yet gets its
# current version as its first release.
#
# Installs update only when a version changes, so this turns a merge into a
# release. Only a commit whose checks are green is released: when main's head is
# past <sha>, the run releases the head only if its required-checks is green
# already, else it leaves the head to its own run.
# Env: RELEASE_REMOTE (origin), RELEASE_PUBLISH=0 stops before the push (a dry
# run), RELEASE_GH (gh) the command that reads the checks and publishes,
# GITHUB_REPOSITORY (owner/repo).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

[ $# -eq 1 ] || { echo "usage: just release <sha>" >&2; exit 2; }
remote=${RELEASE_REMOTE:-origin}
gh=${RELEASE_GH:-gh}

# A release commit is one this script made: its subject alone says so.
release_subject='^release: [a-z0-9-]+ [0-9]+\.[0-9]+\.[0-9]+$'
# changes <range> [path…]: the commits in range, release commits aside, newest first.
changes() {
  local range=$1; shift
  # Through ENVIRON, not -v, which reads escapes and turns the regex's \. into any character.
  git log --format='%H%x09%s' "$range" -- "$@" | r=$release_subject awk -F '\t' '$2 !~ ENVIRON["r"] { print $1 }'
}

git fetch -q --tags "$remote" main
head=$(git rev-parse "$remote/main")
checked=$(git rev-parse "$1^{commit}")

if ! git merge-base --is-ancestor "$checked" "$head"; then
  echo "release: $checked is not on $remote/main; nothing to release"
  exit 0
fi
newest=$(changes "$checked..$head" | head -n1)
if [ -n "$newest" ]; then
  green=$("$gh" api "repos/${GITHUB_REPOSITORY:-FunDrivenDev/claude-plugins}/commits/$newest/check-runs?check_name=required-checks" \
    --jq '[.check_runs[].conclusion] | any(. == "success")') \
    || { echo "release: cannot read the checks of $newest" >&2; exit 1; }
  if [ "$green" != true ]; then
    echo "release: $remote/main moved past $checked to $newest, whose checks are not green yet; its run releases both"
    exit 0
  fi
  echo "release: $remote/main moved past $checked to $newest, green already: releasing up to it"
fi
git checkout -q --detach "$head"

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
# newest_tag <plugin> [n]: its n-th newest release tag (1 by default), or nothing.
newest_tag() { git tag --list "$1-v*" --sort=-v:refname | sed -n "${2:-1}p"; }

tags=()
for dir in plugins/*/; do
  dir=${dir%/}
  name=${dir#plugins/}
  manifest=$dir/.claude-plugin/plugin.json
  [ -f "$manifest" ] || continue
  last=$(newest_tag "$name")
  if [ -z "$last" ]; then
    new=$(jq -r .version "$manifest")
    git tag -a "$name-v$new" -m "$name $new"
    tags+=("$name-v$new")
    echo "release: $name $new, its first release"
    continue
  fi
  commits=$(changes "$last..HEAD" "$dir" ":(exclude)$dir/tests")
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
  git commit -q -m "release: $name $new" -- "$manifest"
  git tag -a "$name-v$new" -m "$name $new"
  tags+=("$name-v$new")
  echo "release: $name $old → $new ($kind)"
done

if [ "${RELEASE_PUBLISH:-1}" = 0 ]; then
  echo "release: dry run, nothing pushed: ${tags[*]:-no new tag}"
  exit 0
fi
if [ ${#tags[@]} -gt 0 ]; then
  refs=()
  for t in "${tags[@]}"; do refs+=("refs/tags/$t"); done
  git push -q --atomic "$remote" HEAD:refs/heads/main "${refs[@]}"
fi

# Each plugin's tags since its newest GitHub release get theirs, oldest first, so
# a publish that failed is retried even after a newer tag; the notes list every
# subject between the previous tag and it, oldest first (GitHub links each (#N)
# to its PR).
notes=$(mktemp)
trap 'rm -f "$notes"' EXIT
failed=0
pending=()
for dir in plugins/*/; do
  name=${dir#plugins/}
  name=${name%/}
  missing=()
  n=1
  while tag=$(newest_tag "$name" "$n") && [ -n "$tag" ]; do
    "$gh" release view "$tag" >/dev/null 2>&1 && break
    missing=("$n" "${missing[@]}")
    n=$((n + 1))
  done
  for n in "${missing[@]}"; do pending+=("$name:$n"); done
done
for item in "${pending[@]}"; do
  name=${item%:*}
  n=${item#*:}
  dir=plugins/$name
  tag=$(newest_tag "$name" "$n")
  previous=$(newest_tag "$name" $((n + 1)))
  if [ -z "$previous" ]; then
    echo "The first tagged version." >"$notes"
  else
    mapfile -t listed < <(changes "$previous..$tag" "$dir" ":(exclude)$dir/tests")
    : >"$notes"
    for ((i = ${#listed[@]} - 1; i >= 0; i--)); do
      git log -1 --format='- %s' "${listed[i]}" >>"$notes"
    done
  fi
  if "$gh" release create "$tag" --verify-tag --title "$name ${tag##*-v}" --notes-file "$notes"; then
    echo "release: published $tag"
  else
    echo "release: publishing $tag failed; the next run retries it" >&2
    failed=1
  fi
done
exit "$failed"

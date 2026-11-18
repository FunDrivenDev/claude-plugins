#!/usr/bin/env bash
# Smoke tests for scripts/release.sh and scripts/bump.sh against a throwaway repo
# and its bare remote; a stub stands in for gh and records the releases.
set -euo pipefail
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars)

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

failures=0
pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1"; failures=$((failures + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got '$2', want '$3')"; fi; }

# The gh stub: `api` answers true for a commit listed in green (its required-checks
# passed); `release view` finds a tag listed in published; `release create` fails
# while the file failing exists, else appends `== <tag>` and the notes to
# releases.log and lists the tag in published.
mkdir "$WORK/bin"
touch "$WORK/green" "$WORK/published"
cat >"$WORK/bin/gh" <<EOF
#!/usr/bin/env bash
case "\$1 \$2" in
  "api "*) if grep -q "\$(cut -d/ -f5 <<<"\$2")" "$WORK/green"; then echo true; else echo false; fi; exit 0 ;;
  "release view") grep -qx "\$3" "$WORK/published"; exit ;;
esac
[ -e "$WORK/failing" ] && exit 1
tag=\$3; while [ \$# -gt 0 ]; do [ "\$1" = --notes-file ] && notes=\$2; shift; done
{ echo "== \$tag"; cat "\$notes"; } >>"$WORK/releases.log"
echo "\$tag" >>"$WORK/published"
EOF
chmod +x "$WORK/bin/gh"
export RELEASE_GH="$WORK/bin/gh"

git init -q --bare -b main "$WORK/origin.git"
git init -q -b main "$WORK/repo"
cd "$WORK/repo"
git remote add origin "$WORK/origin.git"
mkdir -p scripts
cp "$ROOT/scripts/release.sh" "$ROOT/scripts/bump.sh" scripts/
for p in demo other; do
  mkdir -p "plugins/$p/.claude-plugin" "plugins/$p/tests" "plugins/$p/hooks"
  echo a >"plugins/$p/hooks/h.ts"
  echo a >"plugins/$p/tests/t.ts"
done
printf '{\n  "name": "demo",\n  "version": "1.2.3"\n}\n' >plugins/demo/.claude-plugin/plugin.json
printf '{\n  "name": "other",\n  "version": "0.1.0"\n}\n' >plugins/other/.claude-plugin/plugin.json
git add -A && git commit -qm init
git tag -a demo-v1.2.3 -m "demo 1.2.3"
git tag -a other-v0.1.0 -m "other 0.1.0"
git push -q origin main --tags

# land "<subject>" <file>…: a squash merge on origin's main changing each file.
land() {
  local subject=$1; shift
  git checkout -q --detach origin/main
  for f in "$@"; do echo "$RANDOM" >>"$f"; done
  git add -A && git commit -qm "$subject"
  git push -q origin HEAD:main
}
release() { scripts/release.sh "${1:-HEAD}" >/dev/null; git fetch -q --tags origin; }
version() { git show "origin/main:plugins/$1/.claude-plugin/plugin.json" | jq -r .version; }
tagged() { if git rev-parse -q --verify "refs/tags/$1" >/dev/null; then echo yes; else echo no; fi; }

release
check "nothing changed releases nothing" "$(git rev-list --count origin/main)" 1

land "fix: a (#1)" plugins/demo/hooks/h.ts
release
check "fix: is a patch" "$(version demo)" 1.2.4
check "the release is tagged" "$(tagged demo-v1.2.4)" yes
check "the release commit is on main" "$(git log -1 --format=%s origin/main)" "release: demo 1.2.4"
check "the tag points at the release commit" "$(git rev-parse "demo-v1.2.4^{commit}")" "$(git rev-parse origin/main)"
check "an unchanged plugin is not released" "$(version other)" 0.1.0
check "the notes list the PR title" "$(sed -n '/== demo-v1.2.4/{n;p;}' "$WORK/releases.log")" "- fix: a (#1)"

land "docs: tests only (#2)" plugins/demo/tests/t.ts
release
check "a change under tests/ alone is not released" "$(version demo)" 1.2.4

land "feat: b (#3)" plugins/demo/hooks/h.ts
land "fix: c (#4)" plugins/demo/hooks/h.ts
release
check "the highest level wins: feat: is a minor" "$(version demo)" 1.3.0
check "the notes list every title since the last release" "$(sed -n '/== demo-v1.3.0/,$p' "$WORK/releases.log" | tail -n +2 | tr '\n' '|')" "- feat: b (#3)|- fix: c (#4)|"

land "feat(other)!: d (#5)" plugins/other/hooks/h.ts
release
check "type!: is a major" "$(version other)" 1.0.0
land "fix: e (#6)" plugins/other/hooks/h.ts
git checkout -q --detach origin/main
echo x >>plugins/other/hooks/h.ts
git add -A && git commit -qm "fix: f (#7)" -m "BREAKING CHANGE: gone"
git push -q origin HEAD:main
release
check "a BREAKING CHANGE footer is a major" "$(version other)" 2.0.0

land "chore: g (#8)" plugins/demo/hooks/h.ts
release
check "any other title is a patch" "$(version demo)" 1.3.1

land "fix: h (#9)" plugins/demo/hooks/h.ts
checked=$(git rev-parse origin/main)
land "fix: i (#10)" plugins/demo/hooks/h.ts
release "$checked"
check "a run behind a head whose checks are not green releases nothing" "$(version demo)" 1.3.1
release
check "the run on the head releases both" "$(version demo)" 1.3.2
land "fix: j (#13)" plugins/demo/hooks/h.ts
checked=$(git rev-parse origin/main)
land "fix: k (#14)" plugins/demo/hooks/h.ts
git rev-parse origin/main >>"$WORK/green"
release "$checked"
check "a run behind a green head releases it (its own run was cancelled)" "$(version demo)" 1.3.3

land "fix: l (#15)" plugins/demo/hooks/h.ts
git checkout -q --detach origin/main
echo x >>plugins/demo/hooks/h.ts
git add -A && git commit -qm "fix: m (#16)" -m "release: a body line like a release subject"
git push -q origin HEAD:main
release
check "a body line starting with release: is still a change" "$(version demo)" 1.3.4

land "fix: n (#17)" plugins/demo/hooks/h.ts
touch "$WORK/failing"
if scripts/release.sh HEAD >/dev/null 2>&1; then fail "a failed publish fails the run"; else pass "a failed publish fails the run"; fi
rm "$WORK/failing"
git fetch -q --tags origin
release
check "the next run publishes the release that failed" "$(grep -cx 'demo-v1.3.5' "$WORK/published")" 1
check "its notes list the titles since the previous tag" "$(sed -n '/== demo-v1.3.5/{n;p;}' "$WORK/releases.log")" "- fix: n (#17)"
touch "$WORK/failing"
land "fix: o (#18)" plugins/demo/hooks/h.ts
scripts/release.sh HEAD >/dev/null 2>&1 || true
rm "$WORK/failing"
git fetch -q --tags origin
land "fix: p (#19)" plugins/demo/hooks/h.ts
release
check "a failed publish is retried after a newer tag, oldest first" "$(grep -x 'demo-v1.3.[67]' "$WORK/published" | tr '\n' ' ')" "demo-v1.3.6 demo-v1.3.7 "
check "the retried release keeps its own notes" "$(sed -n '/== demo-v1.3.6/{n;p;}' "$WORK/releases.log")" "- fix: o (#18)"

mkdir -p plugins/fresh/.claude-plugin
printf '{\n  "name": "fresh",\n  "version": "0.1.0"\n}\n' >plugins/fresh/.claude-plugin/plugin.json
land "feat: fresh (#11)" plugins/fresh/README.md
release
check "a plugin with no tag gets its version as its first release" "$(tagged fresh-v0.1.0)" yes

land "fix: dry (#12)" plugins/demo/hooks/h.ts
RELEASE_PUBLISH=0 scripts/release.sh HEAD >/dev/null
git fetch -q --tags origin
check "a dry run pushes nothing" "$(version demo)" 1.3.7

for level in patch minor major; do scripts/bump.sh demo "$level" >/dev/null; done
check "bump: patch, then minor resets the patch, then major resets both" "$(jq -r .version plugins/demo/.claude-plugin/plugin.json)" 2.0.0
if scripts/bump.sh demo huge >/dev/null 2>&1; then fail "bump refuses an unknown level"; else pass "bump refuses an unknown level"; fi

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)"; exit 1
fi
echo "all passed"

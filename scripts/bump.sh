#!/usr/bin/env bash
# Raise a plugin's version: bump.sh <plugin> patch|minor|major.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

usage() { echo "usage: just bump <plugin> patch|minor|major" >&2; exit 2; }
[ $# -eq 2 ] || usage
manifest="plugins/$1/.claude-plugin/plugin.json"
[ -f "$manifest" ] || { echo "bump: no plugin $1" >&2; exit 1; }

old=$(jq -r .version "$manifest")
IFS=. read -r major minor patch <<<"$old"
case $2 in
  patch) patch=$((patch + 1)) ;;
  minor) minor=$((minor + 1)) patch=0 ;;
  major) major=$((major + 1)) minor=0 patch=0 ;;
  *) usage ;;
esac
new="$major.$minor.$patch"
# sed rather than jq, so the rest of the file keeps its formatting.
sed -i.bak "s/\"version\": \"$old\"/\"version\": \"$new\"/" "$manifest" && rm "$manifest.bak"
echo "$1: $old → $new"

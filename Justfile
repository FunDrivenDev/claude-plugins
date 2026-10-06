# The entry point to this repo's checks. Tools come from mise.toml.

_default:
    @just --list --unsorted

# One-time setup on a new clone: the pinned tools and the git hooks; safe to re-run.
init:
    scripts/init.sh

# Lint every shell script and git hook (shellcheck), the CI workflow (actionlint) and the mods' TypeScript (biome); the pre-commit hook.
lint:
    git ls-files -z --cached --others --exclude-standard '*.sh' '.githooks/*' | xargs -0 mise exec -- shellcheck
    mise exec -- actionlint
    mise exec -- biome lint --error-on-warnings

# Run the plugins' smoke tests.
test:
    mise exec -- tests/run.sh
    mise exec -- tests/versions.sh

# Fail when a plugin changed since origin/main without a version bump (needs origin/main, so not in CI).
versions:
    mise exec -- scripts/versions.sh

# Raise a plugin's version: `just bump session-panel minor`.
bump plugin level:
    mise exec -- scripts/bump.sh {{plugin}} {{level}}

# Check the marketplace and every plugin with Claude Code's own validator, and run the mods' tests (needs the claude CLI, so not in CI).
validate:
    scripts/validate.sh

# Every check: lint, the smoke tests, the version bumps, then the validator and the mods' tests; the pre-push hook.
check: lint test versions validate

# The entry point to this repo's checks. Tools come from mise.toml.

_default:
    @just --list --unsorted

# One-time setup on a new clone: the pinned tools and the git hooks; safe to re-run.
init:
    scripts/init.sh

# Lint every shell script and git hook (shellcheck) and the CI workflow (actionlint).
lint:
    git ls-files -z --cached --others --exclude-standard '*.sh' '.githooks/*' | xargs -0 mise exec -- shellcheck
    mise exec -- actionlint

# Run the plugins' smoke tests.
test:
    mise exec -- tests/run.sh

# Check the marketplace and every plugin with Claude Code's own validator (needs the claude CLI, so not in CI).
validate:
    scripts/validate.sh

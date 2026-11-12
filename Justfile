# The entry point to this repo's checks. Tools come from mise.toml.

_default:
    @just --list --unsorted

# One-time setup on a new clone: the pinned tools and the git hooks; safe to re-run.
init:
    scripts/init.sh

# Format the files in scope (all, changed, staged): ruff on the Python scripts.
fmt scope="all":
    scripts/fmt.sh {{ quote(scope) }}

# Lint the files in scope (all, changed, staged): shellcheck, actionlint, biome on the mods' TypeScript, ruff on the Python scripts; the pre-commit hook runs `staged`.
lint scope="all":
    scripts/lint.sh {{ quote(scope) }}

# Run the plugins' smoke tests: every tests/*.sh, then every tests/*.py, in name order, stopping at the first failure; a name starting with _ is a helper, not a test.
test:
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    export LC_ALL=C
    for t in tests/[!_]*.sh; do echo "== $t"; mise exec -- "$t"; done
    for t in tests/[!_]*.py; do echo "== $t"; mise exec -- python3 "$t"; done

# Fail when a plugin changed since origin/main without a version bump (needs origin/main, so not in ci.yml).
versions:
    mise exec -- scripts/versions.sh

# Raise a plugin's version: `just bump session-mods minor`.
bump plugin level:
    mise exec -- scripts/bump.sh {{plugin}} {{level}}

# CI's verdict from the results of the jobs required-checks needs: green when each one succeeded or was skipped.
ci-verdict *results:
    scripts/ci-verdict.sh {{ results }}

# Check the marketplace and every plugin with Claude Code's own validator, and run the mods' tests, with the Claude Code version mise.toml pins.
validate:
    scripts/validate.sh

# Type-check each mod's TypeScript (tsc) against the types of the Claude Code version mise.toml pins, which it lays first.
typecheck:
    scripts/typecheck.sh

# Every check: lint, the smoke tests, the version bumps, the type-check, then the validator and the mods' tests; the pre-push hook.
check: lint test versions typecheck validate

# Look for secrets (gitleaks: the whole history, or `staged` for the pre-commit hook) and audit the workflows (zizmor).
audit scope="all":
    scripts/audit.sh {{ quote(scope) }}

# Post the `checks` status on HEAD once GitHub has it, in the background; the pre-push hook's last step.
post-status:
    scripts/post-status.sh

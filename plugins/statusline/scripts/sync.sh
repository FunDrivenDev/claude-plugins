#!/usr/bin/env bash
# SessionStart hook: refresh the installed copy after a plugin update. Never
# touches settings.json, and never fails the session.
set -uo pipefail
# shellcheck source=common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
sync_copy 2>/dev/null
exit 0

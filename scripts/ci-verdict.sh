#!/usr/bin/env bash
# CI's one verdict, from the results of the jobs the ci-ok job needs (success,
# skipped, failure, cancelled). A skipped job is fine: the change did not need
# it. A failed or cancelled one fails the whole run.
set -euo pipefail

failed=0
for result in "$@"; do
  case "$result" in
    success | skipped) ;;
    *)
      echo "a needed check ended in: $result"
      failed=1
      ;;
  esac
done

if [ "$failed" -eq 0 ]; then
  echo "every needed check passed ($*)"
fi
exit "$failed"

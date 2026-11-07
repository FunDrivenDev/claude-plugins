#!/usr/bin/env bash
# Fixture of every delegation eval case (each case's fixture.sh is a copy; EvalCases in tests/delegation.py keeps
# them identical): "ledger", a small Python package in a git repo. One test fails (a rounding bug in rates.py), the
# working tree holds an uncommitted change with an off-by-one bug (cache.py), and PLAN.md proposes a design.
set -euo pipefail
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars 2>/dev/null) 2>/dev/null || true
mkdir -p ledger tests

cat >ledger/__init__.py <<'EOF'
"""Ledger: convert amounts between currencies and build monthly reports."""
EOF

cat >ledger/config.py <<'EOF'
import os


def load_cfg():
    """Settings from the environment."""
    return {
        "db_url": os.environ.get("LEDGER_DB_URL", "sqlite:///ledger.db"),
        "rate_limit": int(os.environ.get("LEDGER_RATE_LIMIT", "10")),
    }
EOF

cat >ledger/rates.py <<'EOF'
import os

DIGITS = int(os.environ.get("LEDGER_DIGITS", "2"))


def convert(amount, rate):
    """amount in the target currency, rounded to DIGITS decimals."""
    return round(amount * rate)


def inverse(rate):
    return 1 / rate
EOF

cat >ledger/cache.py <<'EOF'
_store = {}
_order = []
LIMIT = 3


def get(key):
    return _store.get(key)


def put(key, value):
    if key not in _store:
        _order.append(key)
    _store[key] = value
EOF

cat >ledger/report.py <<'EOF'
import os

from ledger import cache
from ledger.config import load_cfg
from ledger.rates import convert

REPORT_DIR = os.environ.get("LEDGER_REPORT_DIR", "reports")


def monthly(entries, rate):
    cfg = load_cfg()
    total = sum(convert(e["amount"], rate) for e in entries)
    cache.put(("monthly", len(entries)), total)
    return {"total": total, "db": cfg["db_url"], "dir": REPORT_DIR}
EOF

cat >ledger/cli.py <<'EOF'
import sys

from ledger.config import load_cfg
from ledger.report import monthly


def main(argv=None):
    cfg = load_cfg()
    args = sys.argv[1:] if argv is None else argv
    print(monthly([{"amount": float(a)} for a in args], 1.0), cfg["rate_limit"])


if __name__ == "__main__":
    main()
EOF

cat >tests/__init__.py <<'EOF'
EOF

cat >tests/test_rates.py <<'EOF'
import unittest

from ledger.rates import convert, inverse


class Rates(unittest.TestCase):
    def test_convert_rounds_to_two_decimals(self):
        self.assertEqual(convert(10, 1.2345), 12.35)

    def test_inverse(self):
        self.assertEqual(inverse(4), 0.25)
EOF

cat >tests/test_config.py <<'EOF'
import os
import unittest

from ledger.config import load_cfg


class Config(unittest.TestCase):
    def test_defaults(self):
        os.environ.pop("LEDGER_RATE_LIMIT", None)
        self.assertEqual(load_cfg()["rate_limit"], 10)
EOF

cat >README-dev.md <<'EOF'
Run the tests with `python3 -m unittest`.
EOF

cat >PLAN.md <<'EOF'
# Plan: one global cache

Replace `ledger/cache.py`'s module dict with a process-wide singleton shared by every worker thread and
every request, with no eviction, so monthly reports are computed once per process lifetime. Report totals
are keyed by the number of entries only, which is unique enough.
EOF

printf "__pycache__/\n" >.gitignore
git init -q -b main
git add -A
git -c user.name=eval -c user.email=eval@example.invalid commit -qm "ledger: initial"

# The uncommitted change under review: eviction once the cache passes LIMIT entries.
cat >>ledger/cache.py <<'EOF'


def evict():
    """Drop the oldest entries until LIMIT remain."""
    while len(_order) >= LIMIT:
        _store.pop(_order.pop(0))
EOF

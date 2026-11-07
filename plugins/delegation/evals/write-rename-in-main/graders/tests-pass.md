---
type: llm
---

PASS if the reply says `load_cfg` was renamed to `load_config` and that `python3 -m unittest tests.test_config` passes afterwards. A failure the reply reports in another test file (the rounding test in `tests/test_rates.py`, failing before the rename) does not count against it.

FAIL if it reports the config test failing, says nothing was renamed, or only describes the rename without making it.

---
description: Adding a module and its test is written by the main session.
tags: [write]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Edit, Write, Agent]
---

Add `ledger/slug.py` with a `slugify(text)` function (lowercase, ASCII letters and digits, words joined by `-`) and a test for it in `tests/test_slug.py`, then run the tests with `python3 -m unittest`.

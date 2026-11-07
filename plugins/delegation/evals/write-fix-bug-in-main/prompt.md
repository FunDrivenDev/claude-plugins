---
description: Fixing a failing test is written by the main session, even if it delegates the diagnosis.
tags: [write]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Edit, Write, Agent]
---

One test fails in this repo. Fix the code (not the test) and run `python3 -m unittest` until it passes.

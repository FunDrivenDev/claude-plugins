---
description: A rename across files is written by the main session.
tags: [write]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Edit, Write, Agent]
---

Rename `load_cfg` to `load_config` everywhere in this repo, and run `python3 -m unittest tests.test_config` afterwards.

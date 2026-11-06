---
description: Diagnosing a failing test without fixing it goes to the investigator.
tags: [read, investigator]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Agent]
---

A test fails in this repo. Find the cause and tie it to the line responsible, but do not fix anything: I will decide what to change.

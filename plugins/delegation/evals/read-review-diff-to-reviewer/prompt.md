---
description: Reviewing the uncommitted diff goes to the reviewer, which reads it without the main session's reasoning.
tags: [read, reviewer]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Agent]
---

Before I commit: review the uncommitted change in this repo for bugs. Report the findings, do not edit anything.

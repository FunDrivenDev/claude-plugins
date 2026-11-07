---
description: A wide read with a narrow answer goes to the scout (Explore), not a catch-all agent.
tags: [read, scout]
runs: 1
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Bash, Agent]
---

Map this repository for me: every place that reads an environment variable, as `file:line: variable`. I only need the list; change nothing.

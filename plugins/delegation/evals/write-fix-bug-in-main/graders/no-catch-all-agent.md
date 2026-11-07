---
type: tool_used
tool: Agent
input_match: '"subagent_type"\s*:\s*"(?:general-purpose|claude|fork)"|^(?![\s\S]*"subagent_type")'
min: 0
max: 0
arm: both
---

No agent call names `general-purpose`, `claude` or `fork`, or leaves the type out.

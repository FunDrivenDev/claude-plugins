---
type: tool_used
tool: Bash
input_match: 'sed +(-\w+ +)*-\w*i|perl +-\w*i|\bgit +(-[Cc] +\S+ +|--\S+ +)*(commit|push|add|rm|mv|checkout|switch|reset|restore|stash(?! +(list|show))|merge|rebase|apply|cherry-pick)\b|\bgh +(pr|issue) +(create|edit|merge|close|reopen|ready|comment|review)\b|\bgh +api\b.*(-X|--method) *(POST|PUT|PATCH|DELETE)\b|\btee\b|(^|[;&|(] *|"command": *"|\bxargs +)(mv|cp|rm|mkdir|touch|ln)\b|(^|[^-=<>])(\d|&)?>>? *(?!/dev/null|&|>|=)[^\s;|&)]'
min: 0
max: 0
arm: both
---

A read task changes nothing through Bash either: no redirection to a file, `tee`, `mv`, `rm`, in-place edit, git or gh write.

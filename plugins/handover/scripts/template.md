# Handover: <topic in 3 to 5 words>

## Goal
The user's objective and what "done" means. Quote the user's latest formulation verbatim; if the goal shifted during the session, say from what to what.

## Working directory
The absolute path the next session works from, alone on one line in backticks: the worktree or checkout the task's work is in, whether the session `cd`'d there or reached it with `git -C` and absolute paths; the `cwd` of `<session>` only when it is that directory. When the session removed that worktree, the directory the session was started from if the worktree sat inside it (the guest-environment root for an `apps/worktree-*`), else the repo's main checkout, with a line saying the worktree is gone.

## User instructions
Every standing instruction, preference, prohibition and approval the user gave that still applies, quoted verbatim or near-verbatim, newest last. Drop ones the user later revoked, and say so if the revocation matters.

## State
- Done: what is finished, each with how it was verified (test run, command output, user confirmation).
- In progress: what was being done at the moment of the handover, precisely enough to resume mid-step.
- Not started: remaining scope.

Tag any claim not backed by an observed result `[unverified]`.

## Decisions
One line per decision: the choice, why, and the alternatives rejected.

## Dead ends and pitfalls
Approaches tried that failed and why; traps discovered (tool quirks, flaky tests, wrong assumptions corrected).

## References
Pointers, not copies: files (`path:line` and their role), branch, commits, PRs, issues, URLs, the commands that build/test/run, background jobs or workflows still running with their IDs.

## Next steps
Ordered and concrete; the very next action first.

## Open questions
What only the user can answer, if anything.

## Suggested skills
Skills the next session should load, and why.

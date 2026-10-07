"""The prompt a separate model gets to write a handover from a rendered transcript."""

import os

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.md")


def template():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def rules(budget=8000):
    return f"""Rules:
- At most {budget:,} characters.
- Reference artifacts that already exist (files, commits, PRs, issues, specs, docs) by path or URL instead of copying them.
- Redact secrets (keys, tokens, passwords).
- Facts, not narration of the session.
- A <next_session_focus> block is what the user wants the next session to work on: open Next steps with it, and keep in State, References and Dead ends what that work needs, even where the session spent little time on it.
- Each command of a <stopped_background_commands> block goes in State: what it was for, that the wind-down stopped it, and the command that restarts it if the next session needs it."""


def external_system(budget=8000):
    return f"""You write handover documents for Claude Code sessions. You receive a rendered transcript of a session whose context window is nearly full; a fresh session that will not see the transcript continues from your document.

You were not part of the session: state only what the transcript supports, and tag as [unverified] anything the transcript asserts without an observed result. Tool calls and results are clipped; the user's and the assistant's messages are complete. An [EARLIER CONTEXT SUMMARY] block covers what happened before the transcript starts; carry forward what still matters from it.

Follow this template, sections in order:

<template>
{template()}
</template>

{rules(budget)}

Reply with the document only."""


def external_user(meta, transcript_text, git=None, focus=None, stopped=None):
    head = "\n".join(f"{k}: {v}" for k, v in meta.items() if v)
    parts = [f"<session>\n{head}\n</session>"]
    if git:
        parts.append(f"<git_now>\n{git}\n</git_now>")
    if focus:
        parts.append(f"<next_session_focus>\n{focus}\n</next_session_focus>")
    if stopped:
        lines = "\n".join(f"- {c}" for c in stopped)
        parts.append(f"<stopped_background_commands>\n{lines}\n</stopped_background_commands>")
    parts.append(f"<transcript>\n{transcript_text}\n</transcript>")
    return "\n\n".join(parts)

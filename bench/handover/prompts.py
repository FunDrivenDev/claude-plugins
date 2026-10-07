"""Prompts of the handoff benchmark: generation variants and the evaluation chain."""

from writer_prompt import external_system, external_user, rules, template  # noqa: F401

RULES = rules()

# Matt Pocock's `handoff` skill (mattpocock-skills 1.2.3), with "save to a file"
# replaced by "reply with it": the benchmark reads the document from the reply.
POCOCK = """Write a handoff document summarising the current conversation so a fresh agent can continue the work.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

Reply with the document only. Do not call tools or write files."""


def inline_template():
    return f"""The context window of this session is nearly full. Write a handoff document so that a fresh session, which will not see this conversation, can continue the work without asking the user to re-explain anything.

Follow this template, sections in order:

<template>
{template()}
</template>

{RULES}

Reply with the document only. Do not call tools or write files."""


def hybrid(draft):
    return f"""The context window of this session is nearly full. Another model, which only saw a clipped transcript of this session, drafted the handoff document below for the fresh session that will continue the work.

You hold context it lacks. Return the final document: correct anything wrong, add what is missing (the user's intent and standing instructions, the exact step in progress, decisions and their reasons, pitfalls), and cut what does not help the next session. Keep its template and section order.

{RULES}

Reply with the document only. Do not call tools or write files.

<draft>
{draft}
</draft>"""


QGEN_SYSTEM = """You build an evaluation set for session handoff documents.

You receive (A) the transcript of a Claude Code session up to the moment its context was handed off, and (B) what the session did after the handoff. Write 14 questions that a successor agent must be able to answer from a good handoff to continue the work the way the original agent would have.

- The answer to every question is established in part A. Part B only tells you which facts mattered: prefer facts that B shows were used, relied on, or corrected.
- Cover these categories: goal (1-2), user_instruction (3: standing instructions, preferences, prohibitions the user stated), decision (2-3: a choice made and why), state (2-3: what is done, what is in progress), reference (2: an exact path, branch, PR, ticket, command or ID), pitfall (2: something tried that failed, or a trap discovered), next_step (1-2).
- Gold answers are short and checkable: one or two sentences, with the exact identifier when one exists.
- No trivia (timestamps, token counts, harness plumbing), nothing only knowable from part B, and no question that gives away its answer.
- Set needed_after to true when part B shows the fact was needed."""

QGEN_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["goal", "user_instruction", "decision", "state", "reference", "pitfall", "next_step"],
                    },
                    "question": {"type": "string"},
                    "gold": {"type": "string"},
                    "needed_after": {"type": "boolean"},
                },
                "required": ["id", "category", "question", "gold", "needed_after"],
            },
        }
    },
    "required": ["questions"],
}

QGEN_SYSTEM_A = """You build an evaluation set for session handoff documents.

You receive the transcript of a Claude Code session up to the moment its context is handed off to a fresh session. Write 14 questions that the successor agent must be able to answer from a good handoff to continue the work the way the original agent would have.

- Ask about what the successor needs to carry on: the facts it would otherwise have to rediscover, ask the user again, or would get wrong.
- Cover these categories: goal (1-2), user_instruction (3: standing instructions, preferences, prohibitions the user stated), decision (2-3: a choice made and why), state (2-3: what is done, what is in progress), reference (2: an exact path, branch, PR, ticket, command or ID), pitfall (2: something tried that failed, or a trap discovered), next_step (1-2).
- Gold answers are short and checkable: one or two sentences, with the exact identifier when one exists.
- No trivia (timestamps, token counts, harness plumbing), and no question that gives away its answer.
- Set needed_after to true for the questions whose answer the very next steps of the work depend on."""

ANSWER_SYSTEM = """You are a fresh agent taking over a piece of work. All you know about it is the handoff document you are given. Answer each question from the document only. When the document does not settle a question, answer exactly UNKNOWN; do not guess."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["id", "answer"],
            },
        }
    },
    "required": ["answers"],
}

GRADE_SYSTEM = """You grade answers against gold answers. For each item give a grade:
- correct: the answer states what the gold states (wording may differ; extra correct detail is fine).
- partial: part of the gold is present, or it is right but too vague to act on.
- unknown: the answer is UNKNOWN or does not address the question.
- wrong: the answer asserts something that contradicts the gold.
Judge meaning, not wording."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "grade": {"type": "string", "enum": ["correct", "partial", "unknown", "wrong"]},
                },
                "required": ["id", "grade"],
            },
        }
    },
    "required": ["grades"],
}

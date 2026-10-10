---
name: explain-codebase
description: Use when the user invokes /explain-codebase or asks for a systematic explanation of an unfamiliar codebase. Triggers deep exploration and produces a structured written report.
---

# Explain Codebase

## Overview

Systematically explore the current working directory, understand what it does and how it's built, then write a structured report to `.ai/explain/`.

## Steps

### 1. Determine the report path

Derive the project name from the current working directory name: lowercase, hyphens for spaces.

Report path: `.ai/explain/<project-name>.md`

Create the `.ai/explain/` directory if it doesn't exist.

### 2. Explore the codebase thoroughly

Use the **Explore subagent** (`subagent_type: Explore`, thoroughness: `very thorough`) with this mission:

> Explore this codebase and return a comprehensive briefing covering:
> - What the project does and its domain
> - Tech stack (languages, frameworks, databases, key libraries with versions where visible)
> - Directory structure (top 2–3 levels) with purpose of each significant folder
> - Entry points: main files, CLI commands, server startup, build pipeline
> - Key abstractions: core types, interfaces, models, services — what they represent
> - Data flow: what comes in, how it's processed, what goes out
> - Configuration: env vars, config files, feature flags
> - Testing approach and coverage
> - Non-obvious design decisions or patterns worth highlighting
> - Anything that would confuse a developer new to this codebase
>
> Cite file paths for all significant claims. Return everything — this briefing drives a full written report.

### 3. Write the report

Using the Explore subagent's briefing, write the report in Markdown at `.ai/explain/<project-name>.md`.

---

## Report Structure

### Section 1 — What Is This? (3–4 paragraphs)

Write 3–4 paragraphs that give a new developer immediate orientation:

1. **Purpose and domain** — What problem does this solve? For whom? What does it do in plain language?
2. **Technology choices** — Languages, frameworks, databases, notable libraries. Why these (if apparent from the code or docs)?
3. **Core concepts** — The key domain terms, abstractions, or mental models a developer must grasp to work here. Not a glossary — explain relationships and why they matter.
4. **How it works end-to-end** — The main execution path or loop: request → processing → response, or job → transform → output. Enough to picture the runtime.

Keep this section accessible to someone new to both the domain and the tech.

---

### Section 2 — Architecture Overview

Describe the high-level structure:

- How the system is decomposed (layers, services, modules)
- How the pieces connect (calls, events, queues, shared state)
- Where the boundaries are (what's internal vs. external)
- Any non-obvious constraints that shape the design (e.g., "must run serverless", "single-process by design")

Include a text diagram or ASCII art if it helps. Reference real files that anchor each component.

---

### Section 3 — Directory Tour

Walk through the top-level directories and key subdirectories. For each significant one:

- What lives here
- What it's responsible for
- Anything surprising about how it's organized

Format as a commented tree or a list of `path/` — description pairs. Example:

```
src/
  api/        — HTTP handlers, request validation, route definitions
  services/   — Business logic layer; each file maps to a domain concept
  models/     — Database schemas and ORM models
  workers/    — Background job processors (Bull queue consumers)
```

---

### Section 4 — Deep Dives

Choose **3–5 topics** that would most benefit a new developer. Pick based on:

- Where the real complexity lives
- Non-obvious design decisions that aren't explained in docs
- Patterns or conventions that repeat across the codebase
- Areas where a developer would likely get confused or make mistakes

For each deep dive:
- **Title** that names the topic clearly
- **Why it matters** — 1–2 sentences on why a developer working here needs to understand this
- **How it works** — concrete explanation with file:line references where useful
- **Gotchas** — anything that trips people up

Example topics (pick what's actually relevant):

- Authentication / authorization flow
- How database migrations are managed
- The testing strategy and what's mocked vs. real
- A core abstraction that everything depends on
- How configuration and environment variables work
- Error handling philosophy
- A clever or unusual pattern in the codebase

---

### Section 5 — Getting Started (if applicable)

If there's a dev setup, include:

- How to run it locally (commands)
- Required environment variables (names, not secrets)
- How to run tests
- Common dev tasks (build, lint, seed data, etc.)

Skip this section if the repo has an up-to-date README that covers it.

---

## Quality Bar

- **Cite files.** Every significant claim should reference a real file (and line number where helpful).
- **Concrete over abstract.** "Uses Express 4 with Zod for request validation" beats "uses a web framework with validation."
- **Deep dives must teach something a README wouldn't.** If it's already in the docs, summarize and move on.
- **Write for the developer who will touch this code**, not a manager reading a summary.
- **Don't pad.** If a section doesn't apply (e.g., no interesting architecture, trivial directory structure), keep it short or skip it.

## After Writing

Tell the user:
- The report path
- A one-sentence summary of what the codebase is
- The 3–5 deep dive topics you chose and why

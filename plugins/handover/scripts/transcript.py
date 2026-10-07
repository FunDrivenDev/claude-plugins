"""Read a Claude Code transcript (JSONL) and render its live segment as plain text.

The live segment is what the model currently holds: the main-chain entries from
the latest compact boundary to the leaf, walked through `parentUuid` so that
rewound branches are left out. Standard library only: hooks run it on every
tool call.
"""

import json
import os
import re

TAIL_BYTES = 1 << 20

# (tool input chars, tool result chars) kept per call, by render level.
LEVELS = {
    "full": (2000, 2000),
    "condensed": (500, 300),
    "tight": (200, 120),
}

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def load(path, upto_line=None):
    """Entries of the file, in file order, skipping a torn last line."""
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if upto_line is not None and i >= upto_line:
                break
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def context_tokens(path):
    """(tokens, model) of the latest main-chain API call, read from the file tail.

    Tokens are what that call sent as input plus what it produced: the size the
    next request starts from. (0, None) when no call is found in the tail.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0, None
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        u = (e.get("message") or {}).get("usage") or {}
        tokens = sum(
            u.get(k) or 0
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
        )
        if tokens:
            return tokens, e["message"].get("model")
    return 0, None


def last_assistant_text(path):
    """Text of the main chain's latest assistant reply in the current turn, read from the file tail."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain"):
            continue
        if e.get("type") == "user" and isinstance((e.get("message") or {}).get("content"), str):
            return ""
        if e.get("type") == "assistant":
            text = _user_text(e)
            if text.strip():
                return text
    return ""


AGENT_MESSAGE_RE = re.compile(r'<agent-message from="([\w-]+)"')
TASK_ID_RE = re.compile(r"<task-notification>\s*<task-id>([\w-]+)</task-id>")


def notifications_due(path):
    """Subagents whose message reached the session after their last task notification, read from the file tail.

    A subagent's report can come in before the notice of its end, which then starts one more turn."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    due = {}
    for line in lines:
        if "<agent-message" not in line and "<task-notification>" not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain"):
            continue
        a = e.get("attachment") or {}
        if e.get("type") == "user":
            text = _user_text(e)
        elif e.get("type") == "attachment" and a.get("type") == "queued_command" and isinstance(a.get("prompt"), str):
            text = a["prompt"]
        else:
            continue
        for m in AGENT_MESSAGE_RE.finditer(text):
            due[m.group(1)] = True
        for m in TASK_ID_RE.finditer(text):
            due[m.group(1)] = False
    return [aid for aid, d in due.items() if d]


def live_chain(entries):
    """Main-chain entries from the latest compact boundary to the leaf, oldest first."""
    by_uuid = {}
    leaf = None
    for e in entries:
        if e.get("isSidechain") or not e.get("uuid"):
            continue
        by_uuid[e["uuid"]] = e
        if e.get("type") in ("user", "assistant", "attachment", "system"):
            leaf = e
    chain = []
    seen = set()
    while leaf is not None and leaf["uuid"] not in seen:
        seen.add(leaf["uuid"])
        chain.append(leaf)
        if leaf.get("type") == "system" and leaf.get("subtype") == "compact_boundary":
            break
        leaf = by_uuid.get(leaf.get("parentUuid"))
    chain.reverse()
    return chain


def _clip(text, limit):
    text = text.strip()
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return f"{text[:head]} […{len(text) - limit} chars cut…] {text[-(limit - head) :]}"


def _result_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif b.get("type") == "image":
                parts.append("[image]")
    return "\n".join(parts)


def _tool_input(name, inp, limit):
    if name == "Bash":
        return _clip(inp.get("command", ""), limit)
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if name == "Read":
            return path
        body = inp.get("content") or inp.get("new_string") or ""
        return f"{path}\n{_clip(body, limit)}" if body else path
    return _clip(json.dumps(inp, ensure_ascii=False), limit)


def _user_text(e):
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")


def render(chain, level="condensed"):
    """Plain-text rendition of a chain; thinking and harness plumbing are left out."""
    in_limit, out_limit = LEVELS[level]
    out = []
    for e in chain:
        t = e.get("type")
        if t == "user":
            if e.get("isCompactSummary"):
                out.append(f"[EARLIER CONTEXT SUMMARY]\n{_user_text(e)}")
                continue
            c = (e.get("message") or {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tag = "RESULT (error)" if b.get("is_error") else "RESULT"
                        out.append(f"[{tag}] {_clip(_result_text(b.get('content')), out_limit)}")
            text = _user_text(e).strip()
            if not text:
                continue
            if e.get("isMeta"):
                if text.startswith("Base directory for this skill"):
                    out.append(f"[SKILL LOADED] {text.splitlines()[0][30:]}")
                else:
                    out.append(f"[HARNESS] {_clip(text, in_limit)}")
            else:
                out.append(f"[USER] {text}")
        elif t == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    out.append(f"[ASSISTANT] {b['text'].strip()}")
                elif b.get("type") == "tool_use":
                    name = b.get("name", "?")
                    out.append(f"[TOOL {name}] {_tool_input(name, b.get('input') or {}, in_limit)}")
        elif t == "attachment":
            a = e.get("attachment") or {}
            at = a.get("type")
            if at == "queued_command" and isinstance(a.get("prompt"), str):
                p = a["prompt"]
                tag = "HARNESS" if p.lstrip().startswith("<task-notification>") else "USER"
                out.append(f"[{tag}] {_clip(p, in_limit) if tag == 'HARNESS' else p}")
            elif at in ("goal_status", "task_status"):
                out.append(f"[{at.upper()}] {_clip(json.dumps(a, ensure_ascii=False), in_limit)}")
    return "\n\n".join(out)


def user_messages(chain):
    """Every message the user typed in the chain, oldest first."""
    msgs = []
    for e in chain:
        if e.get("type") == "user" and not e.get("isMeta") and not e.get("isCompactSummary"):
            text = _user_text(e).strip()
            if text and not text.startswith("<local-command"):
                msgs.append(text)
        elif e.get("type") == "attachment":
            a = e.get("attachment") or {}
            p = a.get("prompt")
            if (
                a.get("type") == "queued_command"
                and isinstance(p, str)
                and not p.lstrip().startswith("<task-notification>")
            ):
                msgs.append(p.strip())
    return msgs


def files_written(chain):
    """Paths the chain created or edited, most recent last, without repeats."""
    paths = []
    for e in chain:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in WRITE_TOOLS:
                p = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                if p:
                    if p in paths:
                        paths.remove(p)
                    paths.append(p)
    return paths


def session_meta(chain):
    """cwd, branch, session id and model of the chain's latest entry that carries them."""
    meta = {}
    for e in reversed(chain):
        for k_src, k_dst in (("cwd", "cwd"), ("gitBranch", "branch"), ("sessionId", "session_id")):
            if k_dst not in meta and e.get(k_src):
                meta[k_dst] = e[k_src]
        if "model" not in meta and e.get("type") == "assistant":
            m = (e.get("message") or {}).get("model")
            if m and not m.startswith("<"):
                meta["model"] = m
    return meta

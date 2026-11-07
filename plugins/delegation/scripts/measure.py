#!/usr/bin/env python3
"""Measure how Claude Code sessions delegate to subagents and where the main session's context goes.

Reads the transcripts under <config>/projects (CLAUDE_CONFIG_DIR, else ~/.claude); writes nothing there.
A snapshot holds aggregates only (counts, sizes, shares, tool, agent and skill names): no prompt,
description, title, path or result text, so one taken on a work machine can be shared.

  measure.py snapshot take [--since=D] [--until=D] [--out=PREFIX] [--projects=DIR] [--guard-log=FILE] [--json]
  measure.py snapshot compare --before=FILE --after=FILE [--json]

`snapshot take` prints Markdown, or JSON with --json; --out=PREFIX writes PREFIX.json and PREFIX.md instead.
`snapshot compare` prints the headline metrics of two snapshots side by side with their delta.
--json=<object> (or --json=- for stdin) gives the whole input as JSON; `--help --json` prints its spec.
"""

import datetime as dt
import json
import os
import pathlib
import re
import sys
from collections import Counter, defaultdict

SCHEMA = 1
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "LSP"}
AGENT_TOOLS = {"Agent", "Task"}
# Calls that name no role: they start a catch-all agent or a copy of the session.
UNTYPED = {"(untyped)", "general-purpose", "claude", "fork"}
LARGE_RESULT = 20000
HEAVY_READ = 100000
# Bash writes, read on the command with its quoted strings and heredoc bodies taken out: a redirection to a
# file (not /dev/null nor another descriptor), a file command at a command's start, an in-place edit, a git
# or gh verb that changes the repo or the remote.
CMD_START = r"(?:^|[;&|(`]|\b(?:xargs|sudo|then|do|else)\b)\s*"
BASH_WRITE = re.compile(
    r"(?:^|[^-=<>!\d&])(?:\d|&)?>>?(?![&>=])\s*(?!/dev/(?:null|stdout|stderr)\b)[^\s;&|)]"
    r"|\|\s*tee\b(?!\s+/dev/null\b)"
    + rf"|{CMD_START}(?:mv|cp|rm|rmdir|mkdir|touch|ln|chmod|chown|truncate|install|dd)(?:\s|$)"
    + r"|\b(?:g?sed|perl)\s+(?:-[^\si]*\s+|'[^']*'\s+)*-[a-zA-Z]*i"
    r"|\bgit\b(?:\s+(?:-[Cc]\s+\S+|--\S+))*\s+(?:commit|push|pull|merge|rebase|reset|revert|cherry-pick|am|apply"
    r"|add|rm|mv|restore|clean|checkout|switch|tag\s+(?!-l\b)\S|stash(?!\s+(?:list|show)\b))\b"
    r"|\bgh\s+(?:pr|issue)\s+(?:create|edit|merge|close|reopen|ready|comment|review)\b"
    r"|\bgh\s+release\s+create\b|\bgh\s+api\b.*(?:-X|--method)\s*(?:POST|PUT|PATCH|DELETE)\b"
)
# A script's own writes, read on the raw command since they sit inside its quoted code.
SCRIPT_WRITE = re.compile(r"\.write_(?:text|bytes)\(|\bopen\([^)]*,\s*['\"][wax]")
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?(?:\n\2\s*(?:\n|$)|$)", re.DOTALL)


def bash_writes(command):
    """Whether a Bash command changes a file, the repo or a remote, as far as its text shows."""
    if SCRIPT_WRITE.search(command):
        return True
    bare = HEREDOC.sub(lambda m: m.group(3) + "\n", command)
    return bool(BASH_WRITE.search(QUOTED.sub("''", bare)))


# The patterns also match French words, so that briefs written in French (older sessions) get the same classes:
# removing them would move those briefs to "other" and shift the baseline.
CLASSES = [
    ("review", r"review|revue|relecture|audit|verif|vérif|check\b|critique|adversar|judge|disprove|prove"),
    ("research", r"research|recherch|prior art|compare|compar|best practice|web\b|survey|état de l'art|docs?\b"),
    ("diagnose", r"diagnos|debug|investigat|enquête|why\b|pourquoi|root cause|cause|failing|échec|bug|probe|sonde"),
    ("explore", r"explor|find|trouv|locate|map\b|cartograph|inventor|search|cherch|list|scan|understand|compren"),
    ("plan", r"plan\b|planif|design|concevoir|conception|architect|propos"),
    (
        "write",
        (
            r"implement|implément|fix|corrig|create|crée|créer|write|écri|add\b|ajout|build|refactor|migrat|"
            r"update|mettre à jour|mise à jour|rename|renomm|port\b|set ?up|scaffold|commit|apply|prep\b|prépar"
        ),
    ),
]

BASH_KINDS = [
    ("git push (hooks)", r"git( -C \S+)? push"),
    ("git commit (hooks)", r"git( -C \S+)? commit"),
    ("git diff/show/log", r"git( -C \S+)? (diff|show|log)"),
    (
        "tests",
        r"(just|cargo|pnpm|npm|go|pytest|deno|bun|composer|phpunit|make)\b.*\btest|scripts/test|phpunit|pest",
    ),
    ("build/lint", r"(just|cargo|pnpm|npm|go|deno|bun|composer|make)\b.*(build|lint|check|clippy|stan|cs)"),
    ("gh", r"^gh "),
    ("curl/http", r"curl|wget|http "),
    ("file read (cat/sed/head)", r"^(cat|sed|head|tail|less|bat) "),
    ("search (grep/find/ls)", r"^(grep|rg|find|fd|ls|eza|tree) "),
    ("jq", r"jq "),
    ("remote (ssh/docker/kubectl)", r"^ssh |docker|kubectl"),
    ("db (psql/mysql)", r"psql|mysql|pg_"),
    ("script (python/node/bash)", r"^(python3?|node|uv|bash|sh|php) "),
]


def config_dir():
    return pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")


def records(path):
    with open(path, errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def blocks(rec, kind):
    c = (rec.get("message") or {}).get("content")
    return [x for x in c if isinstance(x, dict) and x.get("type") == kind] if isinstance(c, list) else []


def text_len(c):
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(x.get("text", "")) for x in c if isinstance(x, dict))
    return 0


def classify(desc):
    d = desc.lower()
    return next((name for name, pat in CLASSES if re.search(pat, d)), "other")


def bash_kind(cmd):
    c = re.sub(r"^(cd \S+ (&&|;) )+", "", cmd.strip())
    return next((k for k, p in BASH_KINDS if re.search(p, c)), "other")


def context_of(usage):
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def first_usage(rec, seen):
    """The usage of an assistant record, or None when an earlier record of the same message carried it.

    A transcript writes one record per content block of a message, each with the message's id and its whole
    usage: summing usage per record counts a message once per block. A record without an id counts alone.
    """
    msg = rec.get("message") or {}
    usage, mid = msg.get("usage"), msg.get("id")
    if not usage or mid in seen:
        return None
    if mid:
        seen.add(mid)
    return usage


def local_date(stamp):
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date()
    except (AttributeError, ValueError):
        return None


def started(path):
    """The local date of a transcript's first timestamped record."""
    for r in records(path):
        if r.get("timestamp"):
            return local_date(r["timestamp"])
    return None


def mcp_parts(name):
    """('server', 'tool') for an MCP tool name, else None."""
    if not name.startswith("mcp__"):
        return None
    server, _, tool = name[5:].partition("__")
    return server, tool


def median(xs):
    """The middle value, or the mean of the two middle values of an even count; 0 for none."""
    xs, n = sorted(xs), len(xs)
    if not n:
        return 0
    mid = (xs[(n - 1) // 2] + xs[n // 2]) / 2
    return int(mid) if mid == int(mid) else mid


def nearest_rank(xs, pct):
    """The pct-th percentile of sorted XS by nearest rank: the value at rank ceil(pct * n / 100)."""
    return xs[-(-pct * len(xs) // 100) - 1]


def quantiles(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return {"n": 0, "median": 0, "p75": 0, "p90": 0, "max": 0}
    return {"n": n, "median": median(xs), "p75": nearest_rank(xs, 75), "p90": nearest_rank(xs, 90), "max": xs[-1]}


def avg(xs):
    return int(sum(xs) / len(xs)) if xs else 0


def share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def subagent(meta):
    """What one subagent did, from its transcript next to META."""
    try:
        m = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return None, None
    tools, files, bash_wrote, out_tok, peak, start, model, report = Counter(), set(), 0, 0, 0, 0, None, 0
    seen = set()
    tr = meta.with_name(meta.name.replace(".meta.json", ".jsonl"))
    if tr.exists():
        for r in records(tr):
            if r.get("type") != "assistant":
                continue
            usage = first_usage(r, seen)
            if usage:
                out_tok += usage.get("output_tokens", 0)
                ctx = context_of(usage)
                peak = max(peak, ctx)
                start = start or ctx
                model = model or r["message"].get("model")
            texts = blocks(r, "text")
            if texts:
                report = sum(len(t.get("text", "")) for t in texts)  # the last assistant text wins
            for t in blocks(r, "tool_use"):
                tools[t["name"]] += 1
                inp = t.get("input") or {}
                if t["name"] == "SubagentHandback":
                    report = len(json.dumps(inp))
                if t["name"] == "Read" and inp.get("file_path"):
                    files.add(inp["file_path"])
                if t["name"] == "Bash" and bash_writes(inp.get("command", "")):
                    bash_wrote += 1
    writes = sum(tools[t] for t in WRITE_TOOLS) + bash_wrote
    return m.get("toolUseId"), {
        "type": m.get("agentType"),
        "files": files,
        "out_tok": out_tok,
        "peak": peak,
        "start": start,
        "model": model,
        "report": report,
        "writes": writes,
    }


def in_window(day, since, until):
    return day is not None and (since is None or day >= since) and (until is None or day <= until)


def session(path):
    """Agent calls and context figures of one main transcript."""
    pending, chars, calls, after = {}, Counter(), [], defaultdict(list)
    mcp_chars, mcp_calls, bash_chars, bash_calls = Counter(), Counter(), Counter(), Counter()
    skills, workflows, read_before_edit, edited, peak = Counter(), 0, 0, False, 0
    large, large_chars, total = 0, 0, 0
    reads, reread, reread_chars = {}, 0, 0  # (path, offset, limit) -> read since the file's last edit
    for r in records(path):
        if r.get("type") == "assistant":
            usage = (r.get("message") or {}).get("usage")
            if usage:  # a peak: a message split over several records counts the same
                peak = max(peak, context_of(usage))
            for t in blocks(r, "tool_use"):
                pending[t["id"]] = t
                inp = t.get("input") or {}
                if t["name"] in WRITE_TOOLS:
                    edited = True
                    for key in [k for k in reads if k[0] == inp.get("file_path")]:
                        del reads[key]
                if t["name"] == "Skill":
                    skills[inp.get("skill", "?")] += 1
                if t["name"] == "Workflow":
                    workflows += 1
                trace = inp.get("file_path") or inp.get("command") or ""
                for c in calls:
                    after[c["id"]].append(trace)
        if r.get("type") != "user":
            continue
        for res in blocks(r, "tool_result"):
            t = pending.get(res.get("tool_use_id"))
            if not t:
                continue
            name, inp, n = t["name"], t.get("input") or {}, text_len(res.get("content"))
            chars[name] += n
            total += n
            if n > LARGE_RESULT:
                large += 1
                large_chars += n
            if name == "Read" and inp.get("file_path"):
                key = (inp["file_path"], inp.get("offset"), inp.get("limit"))
                if key in reads:
                    reread += 1
                    reread_chars += n
                reads[key] = True
            parts = mcp_parts(name)
            if parts:
                mcp_chars[parts] += n
                mcp_calls[parts] += 1
            if name == "Bash":
                k = bash_kind(inp.get("command", ""))
                bash_chars[k] += n
                bash_calls[k] += 1
            if not edited and (name in READ_TOOLS or name == "Bash"):
                read_before_edit += n
            if name in AGENT_TOOLS and not res.get("is_error"):  # a refused or failed call ran no agent
                calls.append(
                    {
                        "id": t["id"],
                        "type": inp.get("subagent_type") or "(untyped)",
                        "task": classify(inp.get("description", "")),
                        "brief": len(inp.get("prompt", "")),
                        "model": bool(inp.get("model")),
                        "effort": bool(inp.get("effort")),
                    }
                )
    for c in calls:
        c["after"] = after.get(c["id"], [])
    return {
        "calls": calls,
        "chars": chars,
        "total": total,
        "large": large,
        "large_chars": large_chars,
        "reread": reread,
        "reread_chars": reread_chars,
        "mcp_chars": mcp_chars,
        "mcp_calls": mcp_calls,
        "bash_chars": bash_chars,
        "bash_calls": bash_calls,
        "skills": skills,
        "workflows": workflows,
        "read_before_edit": read_before_edit,
        "peak": peak,
    }


def guard_events(path, since, until):
    """Would-block events of the guard-agent-type hook in log mode, by caller skill and agent type."""
    by_skill, by_type, n = Counter(), Counter(), 0
    if not path or not pathlib.Path(path).exists():
        return None
    for r in records(path):
        if r.get("decision") != "would-block" or not in_window(local_date(r.get("ts", "")), since, until):
            continue
        n += 1
        by_skill[r.get("skill") or "(none)"] += 1
        by_type[r.get("agent_type") or "(untyped)"] += 1
    return {"would_block": n, "by_skill": dict(by_skill.most_common()), "by_type": dict(by_type.most_common())}


def snapshot(projects, since=None, until=None, guard_log=None):
    subs, sessions = {}, []
    for tr in sorted(projects.glob("*/*.jsonl")):
        if not in_window(started(tr), since, until):
            continue
        sessions.append(session(tr))
        for meta in (tr.parent / tr.stem / "subagents").glob("*.meta.json"):
            key, sub = subagent(meta)
            if key:
                subs[key] = sub

    calls = [c for s in sessions for c in s["calls"]]
    for c in calls:
        c["sub"] = subs.get(c["id"])
    by_type = {}
    for t in sorted({c["type"] for c in calls}):
        cs = [c for c in calls if c["type"] == t]
        ss = [c["sub"] for c in cs if c["sub"]]
        by_type[t] = {
            "calls": len(cs),
            "typed": t not in UNTYPED,
            "with_transcript": len(ss),
            "wrote": sum(1 for s in ss if s["writes"]),
            "brief_chars_avg": avg([c["brief"] for c in cs]),
            "report_chars_avg": avg([s["report"] for s in ss]),
            "start_context": quantiles([s["start"] for s in ss if s["start"]]),
            "peak_context_avg": avg([s["peak"] for s in ss]),
            "output_tokens_avg": avg([s["out_tok"] for s in ss]),
            "read_files": sum(1 for c in cs if c["sub"] and c["sub"]["files"]),
            "rechecked": sum(1 for c in cs if rechecked(c)),
        }
    with_tr = [c for c in calls if c["sub"]]
    tasks = defaultdict(lambda: {"calls": 0, "wrote": 0})
    for c in calls:
        tasks[c["task"]]["calls"] += 1
        tasks[c["task"]]["wrote"] += bool(c["sub"] and c["sub"]["writes"])

    ratios = sorted(seen_share(c) for c in calls if c["sub"] and c["sub"]["files"])
    total = sum(s["total"] for s in sessions)
    tools = sum((s["chars"] for s in sessions), Counter())
    bash_chars = sum((s["bash_chars"] for s in sessions), Counter())
    bash_calls = sum((s["bash_calls"] for s in sessions), Counter())
    mcp_chars = sum((s["mcp_chars"] for s in sessions), Counter())
    mcp_calls = sum((s["mcp_calls"] for s in sessions), Counter())
    servers_chars, servers_calls = Counter(), Counter()
    for (server, _), n in mcp_chars.items():
        servers_chars[server] += n
    for (server, _), n in mcp_calls.items():
        servers_calls[server] += n
    large_chars = sum(s["large_chars"] for s in sessions)
    reread_chars = sum(s["reread_chars"] for s in sessions)
    mcp_total = sum(mcp_chars.values())
    typed = sum(1 for c in calls if c["type"] not in UNTYPED)
    days = (until - since).days + 1 if since and until else None

    return {
        "schema": SCHEMA,
        "generated": dt.datetime.now().date().isoformat(),
        "window": {"since": since and since.isoformat(), "until": until and until.isoformat(), "days": days},
        "sessions": {"main": len(sessions), "with_agent_calls": sum(1 for s in sessions if s["calls"])},
        "agents": {
            "calls": len(calls),
            "typed": typed,
            "typed_share": share(typed, len(calls)),
            "with_transcript": len(with_tr),
            "wrote": sum(1 for c in with_tr if c["sub"]["writes"]),
            "wrote_share": share(sum(1 for c in with_tr if c["sub"]["writes"]), len(with_tr)),
            "per_call_model": sum(1 for c in calls if c["model"]),
            "per_call_effort": sum(1 for c in calls if c["effort"]),
            "models": dict(Counter(c["sub"]["model"] or "?" for c in with_tr).most_common()),
            "by_type": by_type,
            "tasks": dict(sorted(tasks.items(), key=lambda kv: -kv[1]["calls"])),
        },
        "verification": {
            "calls_with_files": len(ratios),
            "rechecked": sum(1 for r in ratios if r > 0),
            "rechecked_share": share(sum(1 for r in ratios if r > 0), len(ratios)),
            "median_seen_share": round(median(ratios), 2) if ratios else 0.0,
        },
        "main_context": dict(
            quantiles([s["peak"] for s in sessions if s["peak"]]),
            above_150k=sum(1 for s in sessions if s["peak"] > 150000),
        ),
        "tool_output": {
            "total_chars": total,
            "by_tool": {k: v for k, v in tools.most_common()},
            "bash_by_kind": {k: {"chars": v, "calls": bash_calls[k]} for k, v in bash_chars.most_common()},
        },
        "read_waste": {
            "threshold_chars": LARGE_RESULT,
            "large_results": sum(s["large"] for s in sessions),
            "large_chars": large_chars,
            "large_share": share(large_chars, total),
            "sessions_with_large": sum(1 for s in sessions if s["large"]),
            "rereads": sum(s["reread"] for s in sessions),
            "reread_chars": reread_chars,
            "reread_share": share(reread_chars, total),
            "heavy_read_before_edit_no_agent": sum(
                1 for s in sessions if not s["calls"] and s["read_before_edit"] > HEAVY_READ
            ),
        },
        "mcp": {
            "total_chars": mcp_total,
            "share": share(mcp_total, total),
            "calls": sum(mcp_calls.values()),
            "by_server": {k: {"chars": v, "calls": servers_calls[k]} for k, v in servers_chars.most_common()},
            "by_tool": {f"{s}/{t}": {"chars": v, "calls": mcp_calls[(s, t)]} for (s, t), v in mcp_chars.most_common()},
        },
        "skills": dict(sum((s["skills"] for s in sessions), Counter()).most_common()),
        "workflows": sum(s["workflows"] for s in sessions),
        "guard": guard_events(guard_log, since, until),
    }


def seen_share(c):
    files = c["sub"]["files"]
    seen = {f for f in files if any(f in a for a in c["after"])}
    return len(seen) / len(files)


def rechecked(c):
    return bool(c["sub"] and c["sub"]["files"] and seen_share(c) > 0)


def k(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def pct(x):
    return f"{100 * x:.0f}%"


def markdown(s):
    w = s["window"]
    span = f"{w['since'] or 'start'} to {w['until'] or 'now'}"
    a, v, mc, rw, m = s["agents"], s["verification"], s["main_context"], s["read_waste"], s["mcp"]
    out = [
        f"# Delegation snapshot, {span}",
        "",
        (
            f"Generated {s['generated']}: {s['sessions']['main']} main sessions, "
            f"{s['sessions']['with_agent_calls']} with an agent call; {a['calls']} agent calls, "
            f"{s['workflows']} Workflow calls."
        ),
        "",
        "## Headline metrics",
        "",
        "| # | Metric | Value |",
        "|---|---|---|",
        f"| M1 | Agents that ran of a typed role | {a['typed']} of {a['calls']} ({pct(a['typed_share'])}) |",
        f"| M2 | Delegated calls that wrote | {a['wrote']} of {a['with_transcript']} with a transcript |",
        "| M3 | Subagent starting context, median by type | "
        + ", ".join(
            f"{t} {k(x['start_context']['median'])}" for t, x in a["by_type"].items() if x["start_context"]["n"]
        )
        + " |",
        (
            f"| M4 | Main peak context: median, p90, sessions > 150k | {k(mc['median'])}, {k(mc['p90'])}, "
            f"{mc['above_150k']} of {mc['n']} |"
        ),
        (
            f"| M5 | Tool output in results > {k(rw['threshold_chars'])} chars | {pct(rw['large_share'])} "
            f"({rw['large_results']} results in {rw['sessions_with_large']} sessions); re-reads {pct(rw['reread_share'])} |"
        ),
        f"| M6 | Delegated results re-checked | {v['rechecked']} of {v['calls_with_files']} |",
        (
            f"| M7 | MCP result volume | {k(m['total_chars'])} chars, {pct(m['share'])} of tool output, "
            f"{m['calls']} calls |"
        ),
    ]
    if s.get("guard") is not None:
        out.append(f"| M9 | Hook would-block events | {s['guard']['would_block']} |")
    out += [
        "",
        "## Agent calls by type",
        "",
        "| type | typed | calls | wrote | brief | report | start ctx median | peak ctx avg | output tok | re-checked |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t, x in sorted(a["by_type"].items(), key=lambda kv: -kv[1]["calls"]):
        out.append(
            f"| {t} | {'yes' if x['typed'] else 'no'} | {x['calls']} | {x['wrote']}/{x['with_transcript']} | "
            f"{k(x['brief_chars_avg'])} | {k(x['report_chars_avg'])} | {k(x['start_context']['median'])} | "
            f"{k(x['peak_context_avg'])} | {k(x['output_tokens_avg'])} | {x['rechecked']}/{x['read_files']} |"
        )
    out += [
        "",
        f"Per-call model: {a['per_call_model']}, effort: {a['per_call_effort']}. Subagent models: "
        + ", ".join(f"{n} {c}" for n, c in a["models"].items()),
        "",
        "Task classes (description keywords): "
        + ", ".join(f"{t} {x['calls']} ({x['wrote']} wrote)" for t, x in a["tasks"].items()),
        "",
        "## Main-session context",
        "",
        (
            f"Peak context: median {k(mc['median'])}, p75 {k(mc['p75'])}, p90 {k(mc['p90'])}, max {k(mc['max'])}; "
            f"above 150k: {mc['above_150k']} of {mc['n']}."
        ),
        "",
        f"Tool output {k(s['tool_output']['total_chars'])} chars: "
        + ", ".join(f"{t} {k(n)}" for t, n in list(s["tool_output"]["by_tool"].items())[:10]),
        "",
        "| Bash kind | share | calls | avg chars |",
        "|---|---|---|---|",
    ]
    bash_total = sum(x["chars"] for x in s["tool_output"]["bash_by_kind"].values()) or 1
    for kind, x in s["tool_output"]["bash_by_kind"].items():
        out.append(
            f"| {kind} | {pct(x['chars'] / bash_total)} | {x['calls']} | {k(x['chars'] // max(x['calls'], 1))} |"
        )
    out += [
        "",
        (
            f"Sessions without an agent call that read over {k(HEAVY_READ)} chars before their first edit: "
            f"{rw['heavy_read_before_edit_no_agent']}."
        ),
        "",
        "## MCP results",
        "",
    ]
    if m["by_tool"]:
        out += ["| server/tool | chars | calls |", "|---|---|---|"]
        out += [f"| {t} | {k(x['chars'])} | {x['calls']} |" for t, x in list(m["by_tool"].items())[:20]]
    else:
        out.append("No MCP call.")
    if s.get("guard") is not None:
        g = s["guard"]
        out += [
            "",
            "## Hook would-block events",
            "",
            "By caller skill: " + (", ".join(f"{n} {c}" for n, c in g["by_skill"].items()) or "none"),
            "",
            "By agent type: " + (", ".join(f"{n} {c}" for n, c in g["by_type"].items()) or "none"),
        ]
    out += ["", "## Skills invoked", "", ", ".join(f"{n} {c}" for n, c in s["skills"].items()) or "None."]
    return "\n".join(out) + "\n"


HEADLINES = [
    ("M1 typed share", ("agents", "typed_share")),
    ("M1 agent calls", ("agents", "calls")),
    ("M2 wrote", ("agents", "wrote")),
    ("M2 wrote share", ("agents", "wrote_share")),
    ("M4 peak median", ("main_context", "median")),
    ("M4 peak p90", ("main_context", "p90")),
    ("M4 sessions > 150k", ("main_context", "above_150k")),
    ("M5 large-result share", ("read_waste", "large_share")),
    ("M5 re-read share", ("read_waste", "reread_share")),
    ("M6 re-checked", ("verification", "rechecked")),
    ("M6 re-checked share", ("verification", "rechecked_share")),
    ("M7 MCP chars", ("mcp", "total_chars")),
    ("M7 MCP share", ("mcp", "share")),
    ("M9 would-block", ("guard", "would_block")),
    ("main sessions", ("sessions", "main")),
]


def dig(doc, path):
    for key in path:
        doc = doc.get(key) if isinstance(doc, dict) else None
    return doc


def compare(before, after):
    rows = [(name, dig(before, path), dig(after, path)) for name, path in HEADLINES]
    for t in sorted(set(before["agents"]["by_type"]) | set(after["agents"]["by_type"])):
        path = ("agents", "by_type", t, "start_context", "median")
        rows.append((f"M3 start ctx {t}", dig(before, path), dig(after, path)))
    out = []
    for name, b, a in rows:
        if b is None and a is None:
            continue
        delta = round((a or 0) - (b or 0), 4)
        out.append({"metric": name, "before": b, "after": a, "delta": delta})
    return out


def compare_markdown(before, after, rows):
    span = lambda s: f"{s['window']['since'] or 'start'} to {s['window']['until'] or 'now'}"
    out = [f"# Delegation compare: {span(before)} against {span(after)}", ""]
    if not any(r["delta"] for r in rows):
        out.append("No delta.")
    out += ["", "| metric | before | after | delta |", "|---|---|---|---|"]
    out += [f"| {r['metric']} | {r['before']} | {r['after']} | {r['delta']:+g} |" for r in rows]
    return "\n".join(out) + "\n"


class Usage(Exception):
    pass


class Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def to_date(value):
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise Usage(f"not a YYYY-MM-DD date: {value}") from None


# Each command's flags: name -> (type, help). The --json=<object> input uses the same names in snake_case.
COMMANDS = {
    ("snapshot", "take"): {
        "since": (to_date, "sessions started on or after this date (YYYY-MM-DD)"),
        "until": (to_date, "sessions started on or before this date (YYYY-MM-DD)"),
        "out": (str, "write PREFIX.json and PREFIX.md, print their paths"),
        "projects": (pathlib.Path, "transcript folder (default: <config>/projects)"),
        "guard-log": (str, "guard-agent-type event log (default: the plugin's data folder)"),
    },
    ("snapshot", "compare"): {
        "before": (pathlib.Path, "snapshot JSON of the baseline window (required)"),
        "after": (pathlib.Path, "snapshot JSON of the window to compare (required)"),
    },
}
REQUIRED = {("snapshot", "compare"): ("before", "after")}
USAGE = """usage: measure.py snapshot take [--since=D] [--until=D] [--out=PREFIX] [--projects=DIR] [--guard-log=FILE] [--json]
       measure.py snapshot compare --before=FILE --after=FILE [--json]
       measure.py <noun> <verb> --help [--json]

snapshot take     aggregate the transcripts of a window (Markdown, or JSON with --json)
snapshot compare  headline metrics of two snapshots side by side with their delta
--json=<object>   or --json=- (stdin): the whole input as JSON, keys in snake_case
"""


def parse(argv):
    """(command, params, json_out, help) under the CLI contract: flags only, --opt=value or --opt value."""
    if len(argv) < 2 or (argv[0], argv[1]) not in COMMANDS:
        raise Usage("expected a command: snapshot take, snapshot compare")
    cmd, spec = (argv[0], argv[1]), COMMANDS[(argv[0], argv[1])]
    params, seen, json_out, json_in, want_help, rest = {}, set(), False, None, False, list(argv[2:])
    while rest:
        arg = rest.pop(0)
        if not arg.startswith("--"):
            raise Usage(f"unexpected argument: {arg} (this command takes flags only)")
        name, eq, value = arg[2:].partition("=")
        if name in seen:
            raise Usage(f"--{name} given twice")
        seen.add(name)
        if name == "help":
            if eq:
                raise Usage("--help takes no value")
            want_help = True
        elif name == "json":
            if eq:
                json_in = value
            json_out = True
        elif name in spec:
            if not eq:
                if not rest or rest[0].startswith("-"):
                    raise Usage(f"--{name} needs a value (write --{name}=<value> for one starting with -)")
                value = rest.pop(0)
            params[name] = spec[name][0](value)
        else:
            raise Usage(f"unknown flag --{name}")
    if json_in is not None:
        if params:
            raise Usage("--json=<object> gives the whole input: give no other flag with it")
        params = json_params(cmd, sys.stdin.read() if json_in == "-" else json_in)
    if not want_help:
        missing = [f"--{n}" for n in REQUIRED.get(cmd, ()) if n not in params]
        if missing:
            raise Usage(f"missing {', '.join(missing)}")
    return cmd, params, json_out, want_help


def json_params(cmd, text):
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise Usage(f"--json input is not JSON: {e}") from None
    if not isinstance(doc, dict):
        raise Usage("--json input must be an object")
    spec, params = COMMANDS[cmd], {}
    for key, value in doc.items():
        name = key.replace("_", "-")
        if name not in spec:
            raise Usage(f"unknown key {key}")
        if not isinstance(value, str):
            raise Usage(f"{key} must be a string")
        params[name] = spec[name][0](value)
    return params


def input_spec(cmd):
    return {
        "command": " ".join(cmd),
        "input": {n.replace("-", "_"): {"type": "string", "help": h} for n, (_, h) in COMMANDS[cmd].items()},
        "required": [n.replace("-", "_") for n in REQUIRED.get(cmd, ())],
    }


def read_snapshot(path):
    try:
        doc = json.loads(path.read_text())
    except OSError as e:
        raise Failure("not_found", f"cannot read a snapshot: {e}") from None
    except json.JSONDecodeError as e:
        raise Failure("invalid", f"a snapshot is not JSON: {path}: {e}") from None
    if not isinstance(doc, dict) or "schema" not in doc:
        raise Failure("invalid", f"not a snapshot (no schema field): {path}")
    return doc


def run(cmd, params, json_out):
    if cmd == ("snapshot", "compare"):
        before, after = (read_snapshot(params[n]) for n in ("before", "after"))
        rows = compare(before, after)
        return json.dumps(rows, indent=2) if json_out else compare_markdown(before, after, rows)

    projects = params.get("projects") or config_dir() / "projects"
    if not projects.is_dir():
        raise Failure("not_found", f"no transcript folder at {projects}")
    s = snapshot(projects, params.get("since"), params.get("until"), params.get("guard-log") or default_guard_log())
    out = params.get("out")
    if out:
        try:
            pathlib.Path(out + ".json").write_text(json.dumps(s, indent=2) + "\n")
            pathlib.Path(out + ".md").write_text(markdown(s))
        except OSError as e:
            raise Failure("not_found", f"cannot write --out={out}: {e}") from None
        paths = [out + ".json", out + ".md"]
        return json.dumps({"files": paths}) if json_out else "\n".join(paths)
    return json.dumps(s, indent=2) if json_out else markdown(s)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    json_out = "--json" in argv or any(a.startswith("--json=") for a in argv)
    try:
        cmd, params, json_out, want_help = parse(argv)
        if want_help:
            print(json.dumps(input_spec(cmd), indent=2) if json_out else USAGE, end="\n")
            return 0
        print(run(cmd, params, json_out).rstrip("\n"))
        return 0
    except Usage as e:
        report("usage", f"{e}" + ("" if json_out else "\n\n" + USAGE), json_out)
        return 2
    except Failure as e:
        report(e.code, str(e), json_out)
        return 1


def report(code, message, json_out):
    if json_out:
        print(json.dumps({"error": {"code": code, "message": message.strip()}}), file=sys.stderr)
    else:
        print(f"measure: {message}", file=sys.stderr)


def default_guard_log():
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return str(pathlib.Path(data) / "guard-agent-type.jsonl")
    return str(config_dir() / "plugins" / "data" / "delegation-fundrivendev" / "guard-agent-type.jsonl")


if __name__ == "__main__":
    sys.exit(main())

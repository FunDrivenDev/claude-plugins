#!/usr/bin/env python3
"""Benchmark of handoff strategies on real auto-compaction points.

Each sample is a point where Claude Code auto-compacted a real session. Every
method writes a handoff from what the session held at that point; the
built-in compaction summary recorded in the transcript is the baseline. A
question set per sample, written by Opus from the transcript before the point
and what the session did after it, is answered from each handoff alone by a
fresh model and graded against the gold answers.

Transcripts and every intermediate file stay in the work directory
($HANDOFF_BENCH_DIR, default ~/.cache/handoff-bench); only aggregate numbers
leave it.

    bench.py select               pick samples -> samples.json
    bench.py prep                 render transcripts, extract the baseline
    bench.py qgen                 write question sets
    bench.py gen METHOD...        write handoffs
    bench.py eval METHOD...       answer and grade
    bench.py report               aggregate -> results.json + table on stdout
"""

import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "plugins", "handover", "scripts"))

import prompts as P
import transcript as T

WORK = os.path.expanduser(os.environ.get("HANDOFF_BENCH_DIR", "~/.cache/handoff-bench"))
EXTERNAL_MODEL = {
    "external": "claude-sonnet-5-5",
    "external-opus": "claude-opus-5-5",
    "external-haiku": "claude-haiku-4-5-20251001",
    "external-long": "claude-sonnet-5-5",
    "external-full": "claude-sonnet-5-5",
}
BUDGET = {"external-long": 16000}
QGEN_MODEL = "claude-opus-5-5"
JUDGE_MODEL = "claude-sonnet-5-5"
POST_CHARS = 120_000
# Question set: "ab" sees the session after the cut, "a" does not. The session
# after the cut only knew what the built-in summary kept, so "ab" leans toward it.
QSET = os.environ.get("HANDOFF_BENCH_QSET", "ab")
WORKERS = int(os.environ.get("HANDOFF_BENCH_WORKERS", "4"))

BASE_FLAGS = ["-p", "--safe-mode", "--tools", "", "--no-session-persistence", "--output-format", "json"]


def sdir(sample_id, *parts):
    return os.path.join(WORK, "samples", sample_id, *parts)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def load_samples():
    return json.loads(read(os.path.join(WORK, "samples.json")))


def claude(prompt, model, system=None, schema=None, cwd=None, extra=(), timeout=1200):
    """One `claude -p` call. Returns (parsed json output, wall seconds)."""
    cmd = ["claude", *BASE_FLAGS, "--model", model, *extra]
    if system:
        cmd += ["--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd or WORK, timeout=timeout, check=False)
    wall = time.time() - t0
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude failed ({p.returncode}): {p.stderr[-2000:]} {p.stdout[-2000:]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude error: {str(out)[:2000]}")
    return out, wall


def structured(out):
    s = out.get("structured_output")
    if s is None:
        s = json.loads(out["result"])
    return s


def cmd_select(args):
    """Pick samples from events.json: auto compactions with a live cwd and user activity on both sides."""
    ids = args
    cands = json.loads(read(os.path.join(WORK, "candidates.json")))
    chosen = [c for c in cands if f"{os.path.basename(c['f'])[:8]}-{c['line']}" in ids] if ids else cands
    samples = [
        {
            "id": f"{os.path.basename(c['f'])[:8]}-{c['line']}",
            "file": c["f"],
            "line": c["line"],
            "pre_tokens": c["pre"],
            "model": c["model"],
        }
        for c in chosen
    ]
    write(os.path.join(WORK, "samples.json"), json.dumps(samples, indent=1))
    print(f"{len(samples)} samples")


def cmd_prep(_):
    for s in load_samples():
        with open(s["file"], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        pre = T.load(s["file"], upto_line=s["line"])
        chain = T.live_chain(pre)
        meta = T.session_meta(chain)
        boundary = json.loads(lines[s["line"]])
        write(sdir(s["id"], "pre_full.txt"), T.render(chain, "full"))
        write(sdir(s["id"], "pre_condensed.txt"), T.render(chain, "condensed"))
        post = []
        for line in lines[s["line"] + 1 :]:
            try:
                post.append(json.loads(line))
            except ValueError:
                continue
        post_main = [e for e in post if not e.get("isSidechain")]
        end = next((i for i, e in enumerate(post_main) if e.get("subtype") == "compact_boundary"), len(post_main))
        post_main = post_main[:end]
        summary = next((e for e in post_main if e.get("isCompactSummary")), None)
        post_rest = [e for e in post_main if e is not summary]
        write(sdir(s["id"], "post.txt"), T.render(post_rest, "full")[:POST_CHARS])
        baseline = T._user_text(summary) if summary else ""
        preserved = ((boundary.get("compactMetadata") or {}).get("preservedMessages") or {}).get("uuids") or []
        if preserved:
            keep = [e for e in pre if e.get("uuid") in set(preserved)]
            baseline += "\n\n[Recent messages kept verbatim]\n\n" + T.render(keep, "full")
        write(sdir(s["id"], "handoffs", "autocompact.md"), baseline)
        write(
            sdir(s["id"], "handoffs", "autocompact.meta.json"),
            json.dumps(
                {"wall_s": (boundary.get("compactMetadata") or {}).get("durationMs", 0) / 1000, "cost_usd": None}
            ),
        )
        meta.update({"user_messages": len(T.user_messages(chain)), "files_written": T.files_written(chain)})
        write(sdir(s["id"], "meta.json"), json.dumps(meta, indent=1))
        print(
            s["id"],
            "pre",
            len(read(sdir(s["id"], "pre_full.txt"))),
            "post",
            len(read(sdir(s["id"], "post.txt"))),
            "baseline",
            len(baseline),
        )


def qfile(sample_id):
    return sdir(sample_id, "questions.json" if QSET == "ab" else f"questions_{QSET}.json")


def qgen_one(s):
    path = qfile(s["id"])
    if os.path.exists(path):
        return
    prompt = f"<part_a_before_handoff>\n{read(sdir(s['id'], 'pre_full.txt'))}\n</part_a_before_handoff>"
    if QSET == "ab":
        prompt += f"\n\n<part_b_after_handoff>\n{read(sdir(s['id'], 'post.txt'))}\n</part_b_after_handoff>"
    system = P.QGEN_SYSTEM if QSET == "ab" else P.QGEN_SYSTEM_A
    out, wall = claude(prompt, QGEN_MODEL, system=system, schema=P.QGEN_SCHEMA, extra=["--effort", "high"])
    qs = structured(out)["questions"]
    for i, q in enumerate(qs):
        q["id"] = f"q{i + 1}"
    write(
        path,
        json.dumps(
            {"questions": qs, "cost_usd": out.get("total_cost_usd"), "wall_s": wall}, indent=1, ensure_ascii=False
        ),
    )
    print(s["id"], len(qs), "questions")


def cmd_qgen(_):
    run_all(qgen_one, load_samples())


class Fork:
    """A copy of the transcript cut at the sample point, resumable with `claude --resume`."""

    def __init__(self, s):
        self.s = s
        self.src = s["file"]
        self.old = os.path.basename(self.src)[: -len(".jsonl")]
        self.sid = str(uuid.uuid4())
        self.dst = os.path.join(os.path.dirname(self.src), self.sid + ".jsonl")
        with open(self.src, encoding="utf-8") as f:
            self.cwd = next(json.loads(line)["cwd"] for line in f if '"cwd"' in line)

    def __enter__(self):
        with open(self.src, encoding="utf-8") as src, open(self.dst, "w", encoding="utf-8") as out:
            for i, line in enumerate(src):
                if i >= self.s["line"]:
                    break
                out.write(line.replace(self.old, self.sid))
        return self

    def __exit__(self, *exc):
        os.remove(self.dst)

    def ask(self, prompt):
        return claude(
            prompt,
            self.s["model"],
            cwd=self.cwd,
            extra=["--resume", self.sid, "--fork-session", "--autocompact", "1000000"],
        )


def save_handoff(s, method, text, out, wall, **extra):
    write(sdir(s["id"], "handoffs", f"{method}.md"), text)
    u = out.get("usage") or {} if out else {}
    write(
        sdir(s["id"], "handoffs", f"{method}.meta.json"),
        json.dumps(
            {
                "wall_s": round(wall, 1),
                "cost_usd": out.get("total_cost_usd") if out else 0,
                "input_tokens": sum(
                    u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                ),
                "output_tokens": u.get("output_tokens"),
                **extra,
            }
        ),
    )


def exists(s, method):
    return os.path.exists(sdir(s["id"], "handoffs", f"{method}.md"))


def gen_inline(s, methods):
    todo = [m for m in methods if not exists(s, m)]
    if not todo:
        return
    with Fork(s) as fork:
        # Warm the prompt cache so every measured call starts from a cached
        # context, as a live session does.
        fork.ask("Reply with: ok")
        for m in todo:
            if m == "inline-pocock":
                prompt = P.POCOCK
            elif m == "inline":
                prompt = P.inline_template()
            elif m == "hybrid":
                if not exists(s, "external"):
                    gen_external(s, "external")
                prompt = P.hybrid(read(sdir(s["id"], "handoffs", "external.md")))
            else:
                continue
            out, wall = fork.ask(prompt)
            extra = {}
            if m == "hybrid":
                ext = json.loads(read(sdir(s["id"], "handoffs", "external.meta.json")))
                extra = {"session_wall_s": round(wall, 1), "session_cost_usd": out.get("total_cost_usd")}
                wall += ext["wall_s"]
                out = dict(out, total_cost_usd=(out.get("total_cost_usd") or 0) + (ext["cost_usd"] or 0))
            save_handoff(s, m, out["result"], out, wall, **extra)
            print(s["id"], m, len(out["result"]), f"{wall:.0f}s")


def gen_external(s, method):
    if exists(s, method):
        return
    meta = json.loads(read(sdir(s["id"], "meta.json")))
    head = {k: meta.get(k) for k in ("cwd", "branch", "model")}
    head["files_written"] = ", ".join(meta.get("files_written", [])[-30:])
    level = "full" if method == "external-full" else "condensed"
    prompt = P.external_user(head, read(sdir(s["id"], f"pre_{level}.txt")))
    out, wall = claude(
        prompt, EXTERNAL_MODEL[method], system=P.external_system(BUDGET.get(method, 8000)), extra=["--effort", "medium"]
    )
    save_handoff(s, method, out["result"], out, wall)
    print(s["id"], method, len(out["result"]), f"{wall:.0f}s")


def gen_deterministic(s):
    pre = T.load(s["file"], upto_line=s["line"])
    chain = T.live_chain(pre)
    meta = T.session_meta(chain)
    t0 = time.time()
    text = deterministic_doc(chain, meta)
    save_handoff(s, "deterministic", text, None, time.time() - t0)


def deterministic_doc(chain, meta):
    msgs = T.user_messages(chain)[-20:]
    last = next(
        (
            b["text"]
            for e in reversed(chain)
            if e.get("type") == "assistant"
            for b in (e.get("message") or {}).get("content") or []
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
        ),
        "",
    )
    parts = [
        f"# Handoff\n\ncwd: {meta.get('cwd')}\nbranch: {meta.get('branch')}",
        "## User messages, oldest first\n\n" + "\n\n".join(f"> {T._clip(m, 1500)}" for m in msgs),
        "## Files written\n\n" + "\n".join(f"- {p}" for p in T.files_written(chain)[-30:]),
        "## Last assistant message\n\n" + T._clip(last, 2000),
    ]
    return "\n\n".join(parts)


def gen_external_plus(s):
    """external + the user's messages appended verbatim, no extra model call."""
    if exists(s, "external+"):
        return
    ext = read(sdir(s["id"], "handoffs", "external.md"))
    chain = T.live_chain(T.load(s["file"], upto_line=s["line"]))
    msgs = T.user_messages(chain)[-20:]
    appendix = "\n\n## Appendix: the user's messages, verbatim, oldest first\n\n" + "\n\n".join(
        f"> {T._clip(m, 1500)}" for m in msgs
    )
    meta = json.loads(read(sdir(s["id"], "handoffs", "external.meta.json")))
    write(sdir(s["id"], "handoffs", "external+.md"), ext + appendix)
    write(sdir(s["id"], "handoffs", "external+.meta.json"), json.dumps(meta))


def cmd_gen(methods):
    samples = load_samples()
    ext = [m for m in methods if m in EXTERNAL_MODEL]
    inline = [m for m in methods if m in ("inline-pocock", "inline", "hybrid")]
    if ext or "hybrid" in inline or "external+" in methods:
        run_all(lambda s: [gen_external(s, m) for m in (ext or ["external"])], samples)
    if "external+" in methods:
        for s in samples:
            gen_external_plus(s)
    if "deterministic" in methods:
        for s in samples:
            gen_deterministic(s)
    if inline:
        run_all(lambda s: gen_inline(s, inline), samples)


def eval_one(s, method, run):
    path = sdir(s["id"], "eval" if QSET == "ab" else f"eval_{QSET}", f"{method}.{run}.json")
    if os.path.exists(path) or not exists(s, method):
        return
    qs = json.loads(read(qfile(s["id"])))["questions"]
    doc = read(sdir(s["id"], "handoffs", f"{method}.md"))
    ask = "\n".join(f"{q['id']}. {q['question']}" for q in qs)
    out, _ = claude(
        f"<handoff>\n{doc}\n</handoff>\n\n<questions>\n{ask}\n</questions>",
        JUDGE_MODEL,
        system=P.ANSWER_SYSTEM,
        schema=P.ANSWER_SCHEMA,
        extra=["--effort", "low"],
    )
    answers = {a["id"]: a["answer"] for a in structured(out)["answers"]}
    items = [
        {"id": q["id"], "question": q["question"], "gold": q["gold"], "answer": answers.get(q["id"], "UNKNOWN")}
        for q in qs
    ]
    out2, _ = claude(
        json.dumps(items, ensure_ascii=False, indent=1),
        JUDGE_MODEL,
        system=P.GRADE_SYSTEM,
        schema=P.GRADE_SCHEMA,
        extra=["--effort", "medium"],
    )
    grades = {g["id"]: g["grade"] for g in structured(out2)["grades"]}
    for it, q in zip(items, qs):
        it["grade"] = grades.get(it["id"], "unknown")
        it["category"] = q["category"]
        it["needed_after"] = q["needed_after"]
    write(path, json.dumps(items, indent=1, ensure_ascii=False))
    print(s["id"], method, run, sum(it["grade"] == "correct" for it in items), "/", len(items))


def cmd_eval(args):
    runs = int(os.environ.get("HANDOFF_BENCH_RUNS", "2"))
    jobs = [(s, m, r) for s in load_samples() for m in args for r in range(runs)]
    run_all(lambda j: eval_one(*j), jobs)


POINTS = {"correct": 1.0, "partial": 0.5, "unknown": 0.0, "wrong": -0.5}


def cmd_report(_):
    samples = load_samples()
    methods = sorted({f[:-3] for s in samples for f in os.listdir(sdir(s["id"], "handoffs")) if f.endswith(".md")})
    res = {}
    for m in methods:
        items, walls, costs, chars = [], [], [], []
        per_sample = {}
        edir = "eval" if QSET == "ab" else f"eval_{QSET}"
        for s in samples:
            ev = (
                [f for f in os.listdir(sdir(s["id"], edir)) if f.startswith(m + ".") and f[len(m) + 1 : -5].isdigit()]
                if os.path.isdir(sdir(s["id"], edir))
                else []
            )
            sample_items = []
            for f in ev:
                sample_items += json.loads(read(sdir(s["id"], edir, f)))
            if sample_items:
                per_sample[s["id"]] = sum(POINTS[i["grade"]] for i in sample_items) / len(sample_items)
            items += sample_items
            if exists(s, m):
                meta = json.loads(read(sdir(s["id"], "handoffs", f"{m}.meta.json")))
                walls.append(meta.get("wall_s") or 0)
                costs.append(meta.get("cost_usd") or 0)
                chars.append(len(read(sdir(s["id"], "handoffs", f"{m}.md"))))
        if not items:
            continue
        n = len(items)
        cats = {}
        for i in items:
            cats.setdefault(i["category"], []).append(POINTS[i["grade"]])
        needed = [POINTS[i["grade"]] for i in items if i["needed_after"]]
        res[m] = {
            "score": round(sum(POINTS[i["grade"]] for i in items) / n, 3),
            "correct": round(sum(i["grade"] == "correct" for i in items) / n, 3),
            "partial": round(sum(i["grade"] == "partial" for i in items) / n, 3),
            "unknown": round(sum(i["grade"] == "unknown" for i in items) / n, 3),
            "wrong": round(sum(i["grade"] == "wrong" for i in items) / n, 3),
            "needed_score": round(sum(needed) / len(needed), 3) if needed else None,
            "by_category": {k: round(sum(v) / len(v), 3) for k, v in sorted(cats.items())},
            "per_sample": {k: round(v, 3) for k, v in per_sample.items()},
            "median_chars": sorted(chars)[len(chars) // 2] if chars else None,
            "median_wall_s": sorted(walls)[len(walls) // 2] if walls else None,
            "mean_cost_usd": round(sum(costs) / len(costs), 3) if costs else None,
            "n_items": n,
        }
    write(os.path.join(WORK, f"results_{QSET}.json"), json.dumps(res, indent=1))
    cols = [
        "score",
        "needed_score",
        "correct",
        "partial",
        "unknown",
        "wrong",
        "median_chars",
        "median_wall_s",
        "mean_cost_usd",
    ]
    print("| method | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for m, r in sorted(res.items(), key=lambda kv: -kv[1]["score"]):
        print(f"| {m} | " + " | ".join(str(r[c]) for c in cols) + " |")
    cats = sorted({c for r in res.values() for c in r["by_category"]})
    print("\n| method | " + " | ".join(cats) + " |")
    print("|---" * (len(cats) + 1) + "|")
    for m, r in sorted(res.items(), key=lambda kv: -kv[1]["score"]):
        print(f"| {m} | " + " | ".join(str(r["by_category"].get(c, "")) for c in cats) + " |")


def run_all(fn, jobs):
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001 keep the other jobs running; the failure is printed
                print("FAILED", str(futs[f])[:120], e, file=sys.stderr)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["-h"]
    fn = globals().get("cmd_" + cmd)
    if not fn:
        print(__doc__)
        sys.exit(1)
    fn(rest)

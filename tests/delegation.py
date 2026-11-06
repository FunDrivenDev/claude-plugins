"""Tests of the delegation plugin's measure script (plugins/delegation/scripts/measure.py) against fixture
transcripts in a temp dir: the metrics, the window, compare, the CLI contract, and that a snapshot carries no
transcript content."""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "delegation" / "scripts" / "measure.py"
sys.path.insert(0, str(SCRIPT.parent))

import measure as M

SECRET = "SECRET-CONTENT-7f3a"


def usage(ctx):
    return {"input_tokens": 1, "cache_read_input_tokens": ctx - 1, "output_tokens": 10}


def assistant(ts, tools=(), ctx=1000, text=None):
    content = [{"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in tools]
    if text:
        content.append({"type": "text", "text": text})
    return {"type": "assistant", "timestamp": ts, "message": {"model": "m-1", "usage": usage(ctx), "content": content}}


def result(ts, tool_id, chars):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "x" * chars}]},
    }


def write(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs))


def build(projects):
    """Two sessions in one project: 2026-10-01 (in the window), 2026-12-01 (outside it)."""
    proj = projects / "-tmp-proj"
    ts = "2026-10-01T10:00:00Z"
    agent = {"subagent_type": "Explore", "description": f"find {SECRET}", "prompt": SECRET * 10}
    gp = {"description": f"fix {SECRET}", "prompt": "do it"}
    write(
        proj / "s1.jsonl",
        [
            {"type": "user", "timestamp": ts, "message": {"content": SECRET}},
            assistant(ts, [("r1", "Read", {"file_path": f"/{SECRET}/a.py"})], ctx=50000),
            result(ts, "r1", 25000),
            assistant(ts, [("r2", "Read", {"file_path": f"/{SECRET}/a.py"})], ctx=160000),
            result(ts, "r2", 100),
            assistant(ts, [("a1", "Agent", agent), ("a2", "Agent", gp)]),
            result(ts, "a1", 500),
            result(ts, "a2", 500),
            assistant(ts, [("m1", "mcp__tracker__get_issue", {"id": SECRET})]),
            result(ts, "m1", 300),
            assistant(ts, [("b1", "Bash", {"command": f"cat /{SECRET}/b.py"})]),
            result(ts, "b1", 400),
            assistant(ts, [("s", "Skill", {"skill": "wrap-up"})]),
        ],
    )
    sub = proj / "s1" / "subagents"
    write(sub / "agent-1.meta.json", [])
    (sub / "agent-1.meta.json").write_text(json.dumps({"agentType": "Explore", "toolUseId": "a1"}))
    write(
        sub / "agent-1.jsonl",
        [
            assistant(ts, [("x1", "Read", {"file_path": f"/{SECRET}/b.py"})], ctx=9000),
            assistant(ts, ctx=12000, text=SECRET),
        ],
    )
    (sub / "agent-2.meta.json").write_text(json.dumps({"agentType": "general-purpose", "toolUseId": "a2"}))
    write(sub / "agent-2.jsonl", [assistant(ts, [("w1", "Edit", {"file_path": "/x"})], ctx=24000)])
    write(
        proj / "s2.jsonl",
        [
            assistant("2026-12-01T10:00:00Z", [("a9", "Agent", {"description": "late", "prompt": "p"})]),
            result("2026-12-01T10:00:00Z", "a9", 10),
        ],
    )


class Snapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.projects = cls.tmp / "projects"
        build(cls.projects)
        cls.snap = M.snapshot(cls.projects, M.to_date("2026-09-01"), M.to_date("2026-10-31"))

    def test_the_window_keeps_sessions_started_inside_it(self):
        self.assertEqual(self.snap["sessions"]["main"], 1)
        self.assertEqual(self.snap["window"]["days"], 61)
        everything = M.snapshot(self.projects)
        self.assertEqual(everything["sessions"]["main"], 2)

    def test_typed_share_and_writes_by_type(self):
        a = self.snap["agents"]
        self.assertEqual((a["calls"], a["typed"], a["typed_share"]), (2, 1, 0.5))
        self.assertEqual(a["wrote"], 1)
        self.assertEqual(a["by_type"]["(untyped)"]["wrote"], 1)
        self.assertFalse(a["by_type"]["(untyped)"]["typed"])
        self.assertEqual(a["by_type"]["Explore"]["start_context"]["median"], 9000)

    def test_a_file_the_main_session_opens_after_the_report_counts_as_rechecked(self):
        self.assertEqual(self.snap["verification"]["rechecked"], 1)
        self.assertEqual(self.snap["agents"]["by_type"]["Explore"]["rechecked"], 1)

    def test_large_results_rereads_and_mcp_volume(self):
        rw, mcp = self.snap["read_waste"], self.snap["mcp"]
        self.assertEqual((rw["large_results"], rw["large_chars"]), (1, 25000))
        self.assertEqual((rw["rereads"], rw["reread_chars"]), (1, 100))
        self.assertEqual(mcp["by_server"], {"tracker": {"chars": 300, "calls": 1}})
        self.assertIn("tracker/get_issue", mcp["by_tool"])

    def test_main_context_peaks(self):
        self.assertEqual(self.snap["main_context"]["max"], 160000)
        self.assertEqual(self.snap["main_context"]["above_150k"], 1)

    def test_a_snapshot_carries_no_transcript_content(self):
        text = json.dumps(self.snap) + M.markdown(self.snap)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("-tmp-proj", text)

    def test_compare_with_itself_shows_no_delta(self):
        rows = M.compare(self.snap, self.snap)
        self.assertTrue(rows)
        self.assertFalse(any(r["delta"] for r in rows))
        self.assertIn("No delta.", M.compare_markdown(self.snap, self.snap, rows))

    def test_compare_shows_the_change(self):
        after = M.snapshot(self.projects)
        delta = {r["metric"]: r["delta"] for r in M.compare(self.snap, after)}
        self.assertEqual(delta["M1 agent calls"], 1)

    def test_guard_events_count_would_blocks_in_the_window(self):
        log = self.tmp / "guard.jsonl"
        write(
            log,
            [
                {
                    "ts": "2026-10-02T09:00:00Z",
                    "decision": "would-block",
                    "agent_type": "general-purpose",
                    "skill": "s",
                },
                {"ts": "2026-10-02T09:00:00Z", "decision": "allow", "agent_type": "Explore"},
                {"ts": "2026-11-20T09:00:00Z", "decision": "would-block", "agent_type": "claude"},
            ],
        )
        g = M.snapshot(self.projects, M.to_date("2026-09-01"), M.to_date("2026-10-31"), str(log))["guard"]
        self.assertEqual(g, {"would_block": 1, "by_skill": {"s": 1}, "by_type": {"general-purpose": 1}})


class BashWrites(unittest.TestCase):
    """M2 counts a Bash call that changes a file, the repo or a remote; Bash is the only write path of a
    read-only agent, so each common form is caught, and each common read stays a read."""

    WRITES = (
        "cat > a.py <<'EOF'\nprint(1)\nEOF",
        "echo x > f",
        "echo x >> notes.txt",
        "printf '%s' x>f",
        "ls 2> err.log",
        "cmd &> out.log",
        "printf x | tee f",
        "make | tee -a build.log",
        "mv a b",
        "cd src && cp a b",
        "rm -rf build",
        "find . -name '*.tmp' | xargs rm",
        "mkdir -p out; touch out/x",
        "sed -i '' 's/a/b/' f",
        "sed -E -i 's/a/b/' f",
        "perl -pi -e 's/a/b/' f",
        "git commit -m x",
        "git -C repo push origin main",
        "git -c user.name=x commit -m m",
        "git --no-pager -C r add -A",
        "git checkout -b fix",
        "git stash",
        "git reset --hard HEAD~1",
        "gh pr create --draft",
        "gh issue comment 3 --body x",
        "gh api repos/o/r/labels -X POST -f name=x",
        "python3 -c \"open('f', 'w').write('x')\"",
        'python3 -c \'import pathlib; pathlib.Path("f").write_text("x")\'',
    )
    READS = (
        "cat f",
        "ls 2>/dev/null",
        "cmd 2>&1 | head -5",
        "cmd >/dev/null 2>&1",
        "grep -c '=>' f",
        "grep 'a > b' f",
        'echo "x > y"',
        "git -C repo log --oneline -3",
        "git diff main...HEAD",
        "git stash list",
        "sed -n 1,20p f",
        "jq '.a' f",
        "python3 -c 'print(1 if 2 > 1 else 0)'",
        "python3 - <<'EOF'\nprint(2 > 1)\nEOF",
        "gh pr view 3 --json title",
        "gh api repos/o/r/pulls",
        "[[ $a -gt 3 ]] && echo big",
        "find . -name '*.py' -exec grep -l x {} +",
    )

    def test_each_write_form_counts_as_a_write(self):
        missed = [c for c in self.WRITES if not M.bash_writes(c)]
        self.assertEqual(missed, [])

    def test_reads_do_not_count_as_writes(self):
        flagged = [c for c in self.READS if M.bash_writes(c)]
        self.assertEqual(flagged, [])


class EvalCases(unittest.TestCase):
    EVALS = SCRIPT.parent.parent / "evals"

    def cases(self):
        return sorted(d for d in self.EVALS.iterdir() if d.is_dir() and d.name != "results")

    def test_every_case_has_a_prompt_graders_and_the_shared_fixture(self):
        fixture = (self.EVALS / "fixture.sh").read_text()
        for d in self.cases():
            self.assertTrue((d / "prompt.md").exists(), d.name)
            self.assertIn("scaffold_script: fixture.sh", (d / "case.yaml").read_text(), d.name)
            self.assertEqual((d / "fixture.sh").read_text(), fixture, f"{d.name}/fixture.sh differs from evals/")
            self.assertTrue(list((d / "graders").glob("*.md")), d.name)

    def grader(self, path):
        meta = {}
        for line in path.read_text().split("---")[1].strip().splitlines():
            key, _, value = line.partition(":")
            value = value.strip()
            meta[key.strip()] = value[1:-1].replace("''", "'") if value.startswith("'") else value
        return meta

    def graders(self, case):
        return [self.grader(p) for p in sorted((case / "graders").glob("*.md"))]

    def test_a_read_case_refuses_every_write_path(self):
        # Bash is allowed in the read cases, so a write through it fails the case like an Edit or a Write.
        bash = (self.EVALS / "read-map-config-to-scout" / "graders" / "no-bash-write.md").read_text()
        for d in self.cases():
            if d.name.startswith("read-"):
                refused = {g["tool"] for g in self.graders(d) if g.get("type") == "tool_used" and g.get("max") == "0"}
                self.assertLessEqual({"Edit", "Write", "Bash"}, refused, d.name)
                self.assertEqual((d / "graders" / "no-bash-write.md").read_text(), bash, d.name)
        pattern = re.compile(
            self.grader(self.EVALS / "read-map-config-to-scout" / "graders" / "no-bash-write.md")["input_match"]
        )
        # The grader matches the JSON input with one regex: a script's own writes and a quoted `>` are out of its
        # reach, which the measure's own check (BashWrites) covers.
        writes = [c for c in BashWrites.WRITES if not c.startswith("python3")]
        reads = [c for c in BashWrites.READS if c.startswith(("cat", "ls", "cmd", "git", "sed", "jq", "gh", "find"))]
        as_input = lambda c: json.dumps({"command": c, "description": "d"})
        self.assertEqual([c for c in writes if not pattern.search(as_input(c))], [])
        self.assertEqual([c for c in reads if pattern.search(as_input(c))], [])

    def test_a_write_case_needs_a_write_by_the_main_session(self):
        # Edit and Write belong to no role, so a call to either is the main session writing, not a delegated agent.
        for d in self.cases():
            if d.name.startswith("write-"):
                wrote = [
                    g for g in self.graders(d) if g.get("type") == "tool_used" and g.get("tool") in ("Edit", "Write")
                ]
                self.assertTrue([g for g in wrote if int(g.get("min", "1")) >= 1], d.name)

    def test_read_and_write_cases_are_balanced(self):
        kinds = [d.name.split("-")[0] for d in self.cases()]
        self.assertEqual(kinds.count("read"), kinds.count("write"))
        self.assertGreaterEqual(len(kinds), 6)


class Cli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        build(cls.tmp / "projects")
        cls.env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cls.tmp), HOME=str(cls.tmp))
        cls.env.pop("CLAUDE_PLUGIN_DATA", None)

    def run_cli(self, *args, stdin=""):
        p = subprocess.run(
            [sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=self.env, check=False
        )
        return p.returncode, p.stdout, p.stderr

    def test_flag_form_and_json_form_give_the_same_snapshot(self):
        _, flags, _ = self.run_cli("snapshot", "take", "--since", "2026-09-01", "--until=2026-10-31", "--json")
        _, inline, _ = self.run_cli("snapshot", "take", '--json={"since": "2026-09-01", "until": "2026-10-31"}')
        _, piped, _ = self.run_cli(
            "snapshot", "take", "--json=-", stdin='{"since": "2026-09-01", "until": "2026-10-31"}'
        )
        self.assertEqual(json.loads(flags)["agents"], json.loads(inline)["agents"])
        self.assertEqual(json.loads(flags), json.loads(piped))

    def test_out_writes_both_views_and_compare_of_one_with_itself_has_no_delta(self):
        prefix = str(self.tmp / "snap")
        code, out, _ = self.run_cli("snapshot", "take", f"--out={prefix}")
        self.assertEqual((code, out.split()), (0, [prefix + ".json", prefix + ".md"]))
        code, out, _ = self.run_cli("snapshot", "compare", f"--before={prefix}.json", f"--after={prefix}.json")
        self.assertEqual(code, 0)
        self.assertIn("No delta.", out)
        _, out, _ = self.run_cli("snapshot", "compare", "--json", f"--before={prefix}.json", f"--after={prefix}.json")
        self.assertFalse(any(r["delta"] for r in json.loads(out)))

    def test_usage_errors_exit_2_with_a_json_error_under_json(self):
        cases = [
            ("snapshot",),
            ("snapshot", "take", "free text"),
            ("snapshot", "take", "--since=2026-01-01", "--since=2026-01-02"),
            ("snapshot", "take", "--bogus"),
            ("snapshot", "take", "--since", "--json"),
            ("snapshot", "take", "--since=nope"),
            ("snapshot", "take", "--help=x"),
            ("snapshot", "compare", "--before=a"),
            ("snapshot", "take", '--json={"since": "2026-01-01"}', "--until=2026-02-01"),
        ]
        for args in cases:
            code, out, err = self.run_cli(*args, "--json")
            self.assertEqual(code, 2, args)
            self.assertEqual(out, "", args)
            self.assertEqual(json.loads(err)["error"]["code"], "usage", args)

    def test_a_missing_folder_or_snapshot_fails_with_not_found(self):
        code, _, err = self.run_cli("snapshot", "take", f"--projects={self.tmp}/none", "--json")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (1, "not_found"))
        code, _, err = self.run_cli("snapshot", "compare", "--before=/no/a", "--after=/no/b", "--json")
        self.assertEqual((code, json.loads(err)["error"]["code"]), (1, "not_found"))

    def test_help_json_prints_the_input_spec(self):
        code, out, _ = self.run_cli("snapshot", "take", "--help", "--json")
        spec = json.loads(out)
        self.assertEqual(code, 0)
        self.assertIn("guard_log", spec["input"])
        code, out, _ = self.run_cli("snapshot", "compare", "--help")
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()

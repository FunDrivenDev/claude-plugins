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
from typing import ClassVar

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
                {"ts": "2026-10-03T09:00:00Z", "decision": "block", "agent_type": "", "skill": "s"},
                {"ts": "2026-11-20T09:00:00Z", "decision": "would-block", "agent_type": "claude"},
                {"ts": "2026-11-20T09:00:00Z", "decision": "block", "agent_type": "fork"},
            ],
        )
        g = M.snapshot(self.projects, M.to_date("2026-09-01"), M.to_date("2026-10-31"), str(log))["guard"]
        self.assertEqual(
            g,
            {
                "would_block": 1,
                "blocked": 1,
                "by_skill": {"s": 2},
                "by_type": {"general-purpose": 1, "(untyped)": 1},
            },
        )

    def test_blocked_events_show_in_the_markdown_and_the_compare(self):
        log = self.tmp / "guard.jsonl"
        write(log, [{"ts": "2026-10-03T09:00:00Z", "decision": "block", "agent_type": "claude"}])
        s = M.snapshot(self.projects, M.to_date("2026-09-01"), M.to_date("2026-10-31"), str(log))
        self.assertIn("| M9 | Hook events: would-block 0, blocked 1 |", M.markdown(s))
        self.assertIn("M9 blocked", [name for name, _ in M.HEADLINES])


class RefusedAgentCalls(unittest.TestCase):
    """M1 counts the agents that ran: an Agent call whose result is an error (refused by the guard hook or by
    permissions, or failed) stays out of it."""

    def test_a_refused_catch_all_call_and_its_typed_retry_count_one_typed_agent(self):
        projects = pathlib.Path(tempfile.mkdtemp()) / "projects"
        ts = "2026-10-01T10:00:00Z"
        refused = result(ts, "g1", 50)
        refused["message"]["content"][0]["is_error"] = True
        write(
            projects / "-tmp-proj" / "s1.jsonl",
            [
                assistant(
                    ts, [("g1", "Agent", {"subagent_type": "general-purpose", "description": "d", "prompt": "p"})]
                ),
                refused,
                assistant(ts, [("e1", "Agent", {"subagent_type": "Explore", "description": "d", "prompt": "p"})]),
                result(ts, "e1", 500),
            ],
        )
        a = M.snapshot(projects)["agents"]
        self.assertEqual((a["calls"], a["typed"], a["typed_share"]), (1, 1, 1.0))


class SplitMessages(unittest.TestCase):
    """A transcript writes one record per content block of an assistant message, each with the message's id and
    its whole usage: the usage counts once per message.id, and a record without an id counts alone."""

    def test_a_message_split_over_two_records_counts_its_output_tokens_once(self):
        projects = pathlib.Path(tempfile.mkdtemp()) / "projects"
        ts = "2026-10-01T10:00:00Z"
        proj = projects / "-tmp-proj"
        write(
            proj / "s1.jsonl",
            [
                assistant(ts, [("e1", "Agent", {"subagent_type": "Explore", "description": "d", "prompt": "p"})]),
                result(ts, "e1", 500),
            ],
        )
        sub = proj / "s1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.meta.json").write_text(json.dumps({"agentType": "Explore", "toolUseId": "e1"}))
        split = [assistant(ts, [("x1", "Read", {"file_path": "/a"})], ctx=9000), assistant(ts, ctx=9000, text="r")]
        for r in split:
            r["message"]["id"] = "msg_1"
        write(sub / "agent-1.jsonl", [*split, assistant(ts, ctx=12000), assistant(ts, ctx=13000)])
        explore = M.snapshot(projects)["agents"]["by_type"]["Explore"]
        self.assertEqual(explore["output_tokens_avg"], 30)  # msg_1 once, then two records without an id
        self.assertEqual((explore["start_context"]["median"], explore["peak_context_avg"]), (9000, 13000))


class Quantiles(unittest.TestCase):
    """Percentiles by nearest rank (the value at rank ceil(q*n)); the median of an even count is the mean of
    the two middle values."""

    def test_small_lists(self):
        cases = {
            1: (1, 1, 1),
            2: (1.5, 2, 2),
            4: (2.5, 3, 4),
            10: (5.5, 8, 9),
            11: (6, 9, 10),
        }
        for n, (median, p75, p90) in cases.items():
            q = M.quantiles(list(range(n, 0, -1)))
            self.assertEqual((q["n"], q["median"], q["p75"], q["p90"], q["max"]), (n, median, p75, p90, n), n)
        self.assertEqual(M.quantiles([])["median"], 0)

    def test_the_median_seen_share_is_the_mean_of_the_middles(self):
        self.assertEqual(M.median([0.0, 0.5]), 0.25)


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

    def test_a_subagent_that_writes_through_bash_counts_as_wrote(self):
        projects = pathlib.Path(tempfile.mkdtemp()) / "projects"
        ts = "2026-10-01T10:00:00Z"
        proj = projects / "-tmp-proj"
        explore = {"subagent_type": "Explore", "description": "d", "prompt": "p"}
        write(proj / "s1.jsonl", [assistant(ts, [("e1", "Agent", explore)]), result(ts, "e1", 500)])
        sub = proj / "s1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.meta.json").write_text(json.dumps({"agentType": "Explore", "toolUseId": "e1"}))
        bash = [("b1", "Bash", {"command": "cat f"}), ("b2", "Bash", {"command": "echo x > f"})]
        write(sub / "agent-1.jsonl", [assistant(ts, bash)])
        self.assertEqual(M.snapshot(projects)["agents"]["wrote"], 1)


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
        # A case the main session may write through Bash (the rename's one `sed`) forbids every agent call instead.
        for d in self.cases():
            if d.name.startswith("write-"):
                tools = [g for g in self.graders(d) if g.get("type") == "tool_used"]
                wrote = [g for g in tools if g.get("tool") in ("Edit", "Write") and int(g.get("min", "1")) >= 1]
                alone = [
                    g for g in tools if g.get("tool") == "Agent" and g.get("max") == "0" and "input_match" not in g
                ]
                self.assertTrue(wrote or alone, d.name)
        rename = self.graders(self.EVALS / "write-rename-in-main")
        self.assertIn({"type": "tool_used", "tool": "Agent", "min": "0", "max": "0", "arm": "both"}, rename)

    def test_read_and_write_cases_are_balanced(self):
        kinds = [d.name.split("-")[0] for d in self.cases()]
        self.assertEqual(kinds.count("read"), kinds.count("write"))
        self.assertGreaterEqual(len(kinds), 6)


class Agents(unittest.TestCase):
    """The plugin's agents are read-only roles with an exact, pinned allow-list, a set model and effort, no CLAUDE.md, and a report
    that opens on Status and closes on Unverified then Verify."""

    AGENTS = SCRIPT.parent.parent / "agents"
    ROLES = (("investigator", "opus"), ("researcher", "sonnet"), ("reviewer", "opus"), ("skeptic", "fable"))
    WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "Agent", "Task", "Workflow"})
    # Each role's exact allow-list: a tool added, removed or renamed in an agent file needs this table changed on purpose.
    TOOLS: ClassVar[dict[str, set[str]]] = {
        "investigator": {"Read", "Grep", "Glob", "Bash"},
        "researcher": {"Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"},
        "reviewer": {"Read", "Grep", "Glob", "Bash"},
        "skeptic": {"Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"},
    }

    def parse(self, name):
        text = (self.AGENTS / f"{name}.md").read_text()
        head, body = text.split("\n---\n", 1)
        meta = dict(line.split(": ", 1) for line in head.removeprefix("---\n").splitlines())
        return meta, body

    def test_the_four_roles_and_no_other(self):
        self.assertEqual(sorted(p.stem for p in self.AGENTS.glob("*.md")), [n for n, _ in self.ROLES])
        self.assertEqual(sorted(self.TOOLS), [n for n, _ in self.ROLES], "TOOLS must pin every role and no other")

    def test_each_role_is_read_only_with_its_model_effort_and_no_claude_md(self):
        for name, model in self.ROLES:
            meta, _ = self.parse(name)
            self.assertEqual(meta["name"], name)
            tools = {t.strip() for t in meta["tools"].split(",")}
            self.assertFalse(tools & self.WRITE_TOOLS, f"{name} can write or delegate: {tools & self.WRITE_TOOLS}")
            self.assertEqual(
                tools, self.TOOLS[name], f"{name}'s tools changed: change Agents.TOOLS on purpose if this is meant"
            )
            self.assertEqual(meta["model"], model, name)
            self.assertEqual(meta["effort"], "high", name)
            self.assertEqual(meta["omitClaudeMd"], "true", name)

    def test_the_investigator_reruns_only_a_failing_command_without_side_effects(self):
        # A failed deploy, migration or POST is itself a write: it is reported as the repro, never rerun.
        _, body = self.parse("investigator")
        rules = " ".join(body.split("Stop when", 1)[0].split())
        self.assertNotIn("the failing command itself:", rules)
        self.assertIn("no side effect", rules)
        self.assertIn("goes under `Repro`", rules)

    def test_the_readme_does_not_send_bash_rules_to_the_session_wide_deny_list(self):
        # permissions.deny binds the main session too, which is the one meant to commit and push.
        readme = " ".join((SCRIPT.parent.parent / "README.md").read_text().split())
        self.assertNotIn("deny the write commands in your `permissions.deny`", readme)
        self.assertIn("would bind the main session too", readme)

    def test_the_reviewer_reports_a_review_without_agents_md(self):
        # AGENTS.md alone holds the standards: a repo without one is reviewed anyway, and the report names the gap.
        _, body = self.parse("reviewer")
        report = body.split("Report in this format", 1)[1]
        self.assertIn("- **Standards**: each `AGENTS.md` read, or `none: the repo has no AGENTS.md`.", report)
        self.assertNotIn("CLAUDE.md", body)

    def test_each_report_opens_on_status_and_closes_on_unverified_then_verify(self):
        for name, _ in self.ROLES:
            _, body = self.parse(name)
            fields = re.findall(r"^- \*\*(\w+)\*\*", body.split("Report in this format", 1)[1], re.MULTILINE)
            self.assertEqual(fields[0], "Status", name)
            self.assertEqual(fields[-2:], ["Unverified", "Verify"], name)


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

    def test_compare_of_json_that_is_not_a_snapshot_fails_with_invalid(self):
        prefix = str(self.tmp / "valid")
        self.run_cli("snapshot", "take", f"--out={prefix}")
        for i, text in enumerate(("[]", '{"a": 1}')):
            other = self.tmp / f"not-a-snapshot-{i}.json"
            other.write_text(text)
            code, out, err = self.run_cli(
                "snapshot", "compare", f"--before={prefix}.json", f"--after={other}", "--json"
            )
            self.assertEqual((code, out), (1, ""), text)
            self.assertEqual(json.loads(err)["error"]["code"], "invalid", text)
            self.assertIn(str(other), json.loads(err)["error"]["message"], text)

    def test_out_into_a_missing_folder_fails_with_not_found(self):
        prefix = self.tmp / "no-such-folder" / "snap"
        code, out, err = self.run_cli("snapshot", "take", f"--out={prefix}", "--json")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["error"]["code"], "not_found")
        self.assertIn(str(prefix), json.loads(err)["error"]["message"])
        self.assertFalse(prefix.parent.exists())

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

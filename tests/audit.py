"""Unit tests of the handover plugin's YOLO audit (scripts/handover.py): the tag `classify` gives each call of a
YOLO run, the hash chain `audit_check` verifies, and a run under bypassPermissions counted as a YOLO run."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
PROJECT = os.path.join(HOME, "project")
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.makedirs(PROJECT)
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
os.environ.pop("CLAUDE_PROJECT_DIR", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H


def bash(command, mode=None):
    inp = {"session_id": "s-audit", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": PROJECT}
    if mode:
        inp["permission_mode"] = mode
    return inp


def tag(command):
    return H.classify(bash(command), "default")[0]


def sessions():
    out = {}
    with open(H.metrics_path(), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            out.setdefault(e["session"], []).append(e)
    return out


def check(run):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
        code = H.audit_check(run, sessions())
    return code, out.getvalue()


class Classify(unittest.TestCase):
    def test_listing_and_reading_commands_are_read_only(self):
        for command in (
            "ls -la",
            "find . -name '*.py'",
            "date +%s",
            "date -u -r 1700000000 +%F",
            "git status",
            "git branch",
            "git branch -a -v",
            "git branch --list 'feat/*'",
            "git remote -v",
            "git remote get-url origin",
            "git worktree list",
            "git reflog",
            "git reflog show main",
            "grep x f 2>/dev/null",
            "ls missing 2>&1 | head",
            "echo x >&2",
        ):
            self.assertEqual(tag(command), "read-only", command)

    def test_commands_that_write_need_a_prompt_without_yolo(self):
        for command in (
            "find . -delete",
            "find . -name x -exec rm {} +",
            "git branch -D main",
            "git branch -m old new",
            "git branch new-branch",
            "git remote add up https://example.com/x.git",
            "git remote remove origin",
            "git worktree remove ../x",
            "git worktree add ../x",
            "git reflog expire --all",
            "date -s 12:00",
            "date 0613162785",
            "ls 2>f",
            "echo x &>f",
            "echo x >> f",
            "echo x > f",
        ):
            self.assertEqual(tag(command), "prompt", command)

    def test_auto_mode_leaves_the_rest_to_its_classifier(self):
        self.assertEqual(H.classify(bash("git branch -D main"), "auto")[0], "classifier")

    def test_an_allow_rule_covers_its_subcommand_only(self):
        settings = os.path.join(PROJECT, ".claude", "settings.json")
        os.makedirs(os.path.dirname(settings), exist_ok=True)
        with open(settings, "w") as f:
            json.dump({"permissions": {"allow": ["Bash(git branch -D:*)"]}}, f)
        try:
            self.assertEqual(H.classify(bash("git branch -D x"), "default"), ("rule", "Bash(git branch -D:*)"))
            self.assertEqual(tag("git branch -D x && git remote add a b"), "prompt")
            self.assertEqual(
                H.allowed_by("Bash", {}, ["Bash(git branch -D:*)"], PROJECT, "git branch -D x"), "Bash(git branch -D:*)"
            )
        finally:
            os.remove(settings)


class AuditChain(unittest.TestCase):
    def start(self, run, **fields):
        afk = {"run": run, "yolo": True, "since": 0}
        H.record(
            "afk_started",
            "s-audit",
            run=run,
            how="test",
            yolo=True,
            plugin_root=H.plugin_root(),
            plugin_sha=H.plugin_sha(),
            **fields,
        )
        for command in ("ls", "git branch -D x", "cat f"):
            H.audit_write(afk, bash(command), H.classify(bash(command), "default")[0])
        lines, head = H.audit_head(run)
        H.record("afk_ended", "s-audit", run=run, kind="done", reason="", audit_lines=lines, audit_head=head)
        return H.audit_path(run)

    def test_a_whole_log_passes(self):
        self.start("r-whole")
        code, out = check("r-whole")
        self.assertEqual(code, 0, out)
        self.assertIn("3 audited calls", out)

    def test_an_edited_line_breaks_the_chain(self):
        path = self.start("r-edit")
        with open(path) as f:
            lines = f.read().splitlines()
        entry = json.loads(lines[1])
        entry["verdict"] = "read-only"
        lines[1] = json.dumps(entry)
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        code, out = check("r-edit")
        self.assertEqual(code, 1)
        self.assertIn("line 2 breaks the hash chain", out)

    def test_a_cut_log_fails(self):
        path = self.start("r-cut")
        with open(path) as f:
            lines = f.read().splitlines()
        with open(path, "w") as f:
            f.write("\n".join(lines[:2]) + "\n")
        code, out = check("r-cut")
        self.assertEqual(code, 1)
        self.assertIn("the log was cut", out)

    def test_an_inserted_line_breaks_the_chain(self):
        path = self.start("r-insert")
        with open(path) as f:
            lines = f.read().splitlines()
        lines.insert(1, lines[0])
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        self.assertEqual(check("r-insert")[0], 1)


class BypassPermissions(unittest.TestCase):
    def test_a_run_under_bypass_permissions_counts_as_a_yolo_run(self):
        run = "r-bypass"
        H.write_json(H.state_path("s-audit"), {"project": PROJECT, "afk": {"run": run, "yolo": False, "since": 0}})
        H.record("afk_started", "s-audit", run=run, how="test", yolo=False)
        afk = H.read_json(H.state_path("s-audit"))["afk"]
        self.assertFalse(H.yolo_on(afk, bash("ls")))
        self.assertTrue(H.yolo_on(afk, bash("ls", mode="bypassPermissions")))
        self.assertTrue(H.yolo_on(afk, bash("ls", mode="bypassPermissions")))
        H.audit_write(afk, bash("ls"), "read-only")
        lines, head = H.audit_head(run)
        H.record("afk_ended", "s-audit", run=run, kind="done", reason="", audit_lines=lines, audit_head=head)

        promoted = [e for e in sessions()["s-audit"] if e["event"] == "afk_yolo" and e["run"] == run]
        self.assertEqual(len(promoted), 1, "recorded once")
        self.assertEqual(H.read_json(H.state_path("s-audit"))["afk"]["baseline"], "default")
        [row] = [r for r in H.afk_runs(sessions()) if r["run"] == run]
        self.assertTrue(row["yolo"])
        self.assertEqual(row["calls"], 1)
        code, out = check(run)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()

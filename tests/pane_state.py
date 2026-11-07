"""Unit tests of the handover state the session-mods pane renders (D18): session.py `view`, and
`handover.py state --session <sid> --json`, the command the pane runs instead of reading the plugin's files."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, "data")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
# Run from a relayed session, a closing reply here would relay into that session's own terminal.
for key in [k for k in os.environ if k.startswith(("HANDOVER_", "REX_", "TMUX"))]:
    os.environ.pop(key)
SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts")
sys.path.insert(0, SCRIPTS)

import session as S

NOW = time.time()
RECORDED = {"suggest_tokens": 150_000, "warn_at_tokens": 180_000, "trigger_tokens": 200_000}
THRESHOLDS = {"suggest": 150_000, "warn_at": 180_000, "trigger": 200_000}


def handover_doc(text):
    fd, path = tempfile.mkstemp(suffix=".md", dir=HOME)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class View(unittest.TestCase):
    def view(self, st, on=True, resolved=RECORDED):
        return S.view(st, on, resolved)

    def test_fresh_session(self):
        v = self.view({"thresholds": RECORDED})
        self.assertEqual(
            v,
            {
                "on": True,
                "phase": S.WORKING,
                "wound_down": False,
                "writing": False,
                "error": None,
                "written": None,
                "loaded": None,
                "thresholds": THRESHOLDS,
                "thresholds_error": None,
                "pending": None,
                "resume": None,
            },
        )

    def test_off(self):
        self.assertFalse(self.view({}, on=False)["on"])

    def test_phase_and_wind_down(self):
        cases = [
            ({"phase": S.WINDING_DOWN}, S.WINDING_DOWN, True),
            ({"phase": S.HANDED_OVER}, S.HANDED_OVER, True),
            ({"phase": S.COMPACTING}, S.COMPACTING, False),
            ({"phase": S.COMPACTING, "phase_before": S.WINDING_DOWN}, S.COMPACTING, True),
            # An older plugin version's flag, converted on read.
            ({"wind_down": True}, S.WINDING_DOWN, True),
        ]
        for st, phase, wound in cases:
            with self.subTest(st):
                v = self.view(S.converted(dict(st)))
                self.assertEqual((v["phase"], v["wound_down"]), (phase, wound))

    def test_writing_is_pid_checked(self):
        # The pane's old `since < 660` showed a dead writer as writing for 11 minutes.
        self.assertTrue(self.view({"writer": {"pid": os.getpid(), "since": NOW}})["writing"])
        self.assertFalse(self.view({"writer": {"pid": dead_pid(), "since": NOW}})["writing"])
        self.assertFalse(self.view({"writer": {"pid": os.getpid(), "since": NOW - S.WRITER_TIMEOUT - 61}})["writing"])
        self.assertFalse(self.view({"writer": {"since": NOW}})["writing"])

    def test_error_as_the_status_line_cuts_it(self):
        self.assertEqual(self.view({"error": {"at": NOW, "message": "x" * 100}})["error"], "x" * 60)
        self.assertIsNone(self.view({"error": "a bare string"})["error"])
        self.assertIsNone(self.view({"error": {"at": NOW, "message": ""}})["error"])

    def test_written_and_loaded_handovers(self):
        written = handover_doc('---\nstatus: done\nsummary: "panel corner"\n---\n# Handover: x\nbody\n')
        loaded = handover_doc("# Handover: session-panel tracker\n\nnext\n")
        v = self.view({"written": {"ok": True}, "path": written, "loaded_from": loaded})
        self.assertEqual(v["written"]["title"], "panel corner")
        self.assertEqual(v["written"]["lines"], 6)
        self.assertEqual(v["written"]["modified_at"], int(os.path.getmtime(written)))
        self.assertEqual(
            v["loaded"],
            {
                "path": loaded,
                "title": "session-panel tracker",
                "lines": 3,
                "modified_at": int(os.path.getmtime(loaded)),
            },
        )
        # A path recorded without a successful write is no written handover.
        self.assertIsNone(self.view({"written": {"ok": False}, "path": written})["written"])
        # As `wc -l` and `head` read it: a lone "\r" ends no line, a byte that is not UTF-8 hides nothing else.
        crlf = handover_doc("# Handover: hello world\r\nline2\rline3\n")
        front = handover_doc('---\r\nsummary: "Ship it"\r\n---\r\n# Handover: heading\r\n')
        self.assertEqual(self.view({"loaded_from": front})["loaded"]["title"], "Ship it")
        v = self.view({"loaded_from": crlf})["loaded"]
        self.assertEqual((v["title"], v["lines"]), ("hello world", 2))
        latin = handover_doc("")
        with open(latin, "wb") as f:
            f.write(b"# Handover: caf\xe9\nnext\n")
        v = self.view({"loaded_from": latin})["loaded"]
        self.assertEqual((v["title"], v["lines"], v["modified_at"]), ("caf\ufffd", 2, int(os.path.getmtime(latin))))
        gone = os.path.join(HOME, "gone.md")
        self.assertEqual(
            self.view({"loaded_from": gone})["loaded"],
            {"path": gone, "title": None, "lines": None, "modified_at": None},
        )

    def test_thresholds(self):
        self.assertEqual(
            self.view({"thresholds": RECORDED}, resolved={**RECORDED, "trigger_tokens": 120_000})["pending"],
            {"trigger": 120_000},
        )
        self.assertIsNone(self.view({"thresholds": RECORDED}, resolved=None)["pending"])
        old = self.view({})
        self.assertIsNone(old["thresholds"])
        self.assertIn("older than 0.20.0", old["thresholds_error"])
        bad = self.view({"plugin_version": "0.20.0", "thresholds": {**RECORDED, "trigger_tokens": "3"}})
        self.assertEqual(
            bad["thresholds_error"],
            "in this session's handover state (handover 0.20.0), not a number: thresholds.trigger_tokens",
        )

    def test_resume_message_is_the_closing_reply_s(self):
        st = {"phase": S.WINDING_DOWN, "reply_due": True}
        S.reply_written(st, "Resume the pane work: open the PR.")
        self.assertEqual(self.view(st)["resume"], "Resume the pane work: open the PR.")
        # Asked again, the next closing reply gives the next one.
        S.requested(st)
        self.assertIsNone(self.view(st)["resume"])
        S.reply_written(st, "Again.")
        S.compacted(st)
        self.assertIsNone(self.view(st)["resume"])

    def test_a_session_that_went_on_after_its_closing_reply_gives_no_resume_message(self):
        st = {"phase": S.WINDING_DOWN, "reply_due": True}
        S.reply_written(st, "Resume the pane work.")
        self.assertIsNone(S.view(st, True, RECORDED, went_on=True)["resume"])


class ClosingReply(unittest.TestCase):
    def test_the_stop_after_the_closing_reply_records_its_resume_message(self):
        import handover as H

        sid, transcript = "pane-reply", handover_doc("")
        doc = handover_doc("# Handover: pane\n")
        with S.locked(sid) as st:
            S.started(st, RECORDED, "0.29.0")
            S.wind_down(st, "trigger", 200_000)
            S.reply_asked(st, False)
            st.update(written={"ok": True, "at": NOW, "tokens": 0}, path=doc, transcript=transcript)
        reply = f"The handover is written: {doc}.\n\nReady to hand over: run /clear.\n\n```\nResume the pane:\n open the PR.\n```"
        inp = {"session_id": sid, "transcript_path": transcript, "last_assistant_message": reply, "cwd": HOME}
        H.on_activity(inp, H.session_config(sid), "Stop")
        v = S.view(S.read(sid), True, RECORDED)
        self.assertEqual((v["phase"], v["resume"]), (S.HANDED_OVER, "Resume the pane: open the PR."))
        self.assertEqual(v["written"]["title"], "pane")

    def stop(self, sid, reply, **state):
        import handover as H

        transcript, doc = handover_doc(""), handover_doc("# Handover: pane\n")
        with S.locked(sid) as st:
            S.started(st, RECORDED, "0.29.0")
            S.wind_down(st, "trigger", 200_000)
            S.reply_asked(st, False)
            st.update(written={"ok": True, "at": NOW, "tokens": 0}, path=doc, transcript=transcript, **state)
        inp = {"session_id": sid, "transcript_path": transcript, "last_assistant_message": reply, "cwd": HOME}
        H.on_activity(inp, H.session_config(sid), "Stop")
        return S.view(S.read(sid), True, RECORDED)

    def test_after_the_reminder_a_reply_without_its_message_hands_over_without_one(self):
        v = self.stop("pane-reminded", "Done for today.", reply_reminded=True)
        self.assertEqual((v["phase"], v["resume"]), (S.HANDED_OVER, None))

    def test_the_reminder_s_closing_reply_gives_its_resume_message(self):
        v = self.stop("pane-reminded-2", "Run /clear, then send:\n\n```\nResume the pane.\n```", reply_reminded=True)
        self.assertEqual((v["phase"], v["resume"]), (S.HANDED_OVER, "Resume the pane."))


class Command(unittest.TestCase):
    def run_state(self, sid, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "handover.py"), *extra, "state", "--session", sid, "--json"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_answers_json_on_one_line(self):
        sid = "pane-cmd"
        with S.locked(sid) as st:
            S.started(st, RECORDED, "0.29.0")
            S.wind_down(st, "trigger", 200_000)
        os.makedirs(os.path.join(DATA, "live"), exist_ok=True)
        open(os.path.join(DATA, "live", sid), "a").close()
        out = self.run_state(sid)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(out.stdout.strip().splitlines()), 1)
        v = json.loads(out.stdout)
        self.assertTrue(v["on"])
        self.assertEqual((v["phase"], v["wound_down"], v["thresholds"]), (S.WINDING_DOWN, True, THRESHOLDS))

    def test_a_session_that_went_on_after_its_closing_reply_gives_no_resume_message(self):
        sid, transcript = "pane-went-on", handover_doc('{"type": "assistant"}\n')
        with S.locked(sid) as st:
            S.started(st, RECORDED, "0.29.0")
            S.wind_down(st, "trigger", 200_000)
            S.reply_written(st, "Resume the pane.")
            st.update(transcript=transcript, reply_offset=os.path.getsize(transcript))
        self.assertEqual(json.loads(self.run_state(sid).stdout)["resume"], "Resume the pane.")
        with open(transcript, "a") as f:
            f.write('{"type": "assistant"}\n{"type": "user", "isSidechain": true}\n')
        self.assertEqual(json.loads(self.run_state(sid).stdout)["resume"], "Resume the pane.")
        # A local command before /clear writes user entries that no turn answers.
        with open(transcript, "a") as f:
            f.write('{"type": "user", "isMeta": true, "message": {"content": "<local-command-caveat>x"}}\n')
            f.write('{"type": "user", "message": {"content": "<command-name>/usage</command-name>"}}\n')
            f.write('{"type": "user", "isMeta": true, "message": {"content": "The user named this session"}}\n')
            f.write('{"type": "system", "subtype": "local_command"}\n')
        self.assertEqual(json.loads(self.run_state(sid).stdout)["resume"], "Resume the pane.")
        # A prompt alone is not answered yet; its answer is.
        with open(transcript, "a") as f:
            f.write('{"type": "user", "message": {"content": "one more thing"}}\n')
        self.assertEqual(json.loads(self.run_state(sid).stdout)["resume"], "Resume the pane.")
        with open(transcript, "a") as f:
            f.write('{"type": "assistant"}\n')
        self.assertIsNone(json.loads(self.run_state(sid).stdout)["resume"])

    def test_options_that_do_not_resolve_leave_the_rest_of_the_state(self):
        sid = "pane-bad-options"
        with S.locked(sid) as st:
            S.started(st, RECORDED, "0.29.0")
        for value in ("inf", "nan", "many"):
            with self.subTest(value):
                out = subprocess.run(
                    [sys.executable, os.path.join(SCRIPTS, "handover.py"), "state", "--session", sid, "--json"],
                    capture_output=True,
                    text=True,
                    check=False,
                    env={**os.environ, "CLAUDE_PLUGIN_OPTION_TRIGGER_TOKENS": value},
                )
                self.assertEqual(out.returncode, 0, out.stderr)
                v = json.loads(out.stdout)
                self.assertEqual((v["thresholds"], v["pending"]), (THRESHOLDS, None))

    def test_the_pane_s_snippet_runs_the_installed_plugin_with_its_own_data(self):
        """HANDOVER_STATE, the shell snippet session-mods/hooks/handover.ts runs, against a fake install."""
        with open(os.path.join(SCRIPTS, "..", "..", "session-mods", "hooks", "handover.ts")) as f:
            ts = f.read()
        snippet = ts.split("export const HANDOVER_STATE = `", 1)[1].split("`\n", 1)[0]
        snippet = snippet.replace("\\${", "${").replace("${NOT_INSTALLED}", "3")
        config = tempfile.mkdtemp(dir=HOME)
        os.makedirs(os.path.join(config, "plugins"))

        def run(plugins):
            with open(os.path.join(config, "plugins", "installed_plugins.json"), "w") as f:
                json.dump({"version": 2, "plugins": plugins}, f)
            env = {**os.environ, "CLAUDE_CONFIG_DIR": config, "CLAUDE_PLUGIN_DATA": "/nonexistent/another-plugin"}
            return subprocess.run(
                ["sh", "-c", snippet, "sh", "pane-snippet"], capture_output=True, text=True, check=False, env=env
            )

        self.assertEqual(run({}).returncode, 3)
        self.assertEqual(run({"other@fundrivendev": [{"installPath": "/x"}]}).returncode, 3)
        install = os.path.join(SCRIPTS, "..")
        for key in ("handover@fundrivendev", "handover@fundriven"):
            with self.subTest(key):
                out = run({key: [{"installPath": install}]})
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(json.loads(out.stdout)["phase"], S.WORKING)
        self.assertFalse(os.path.exists("/nonexistent/another-plugin"))
        gone = run({"handover@fundrivendev": [{"installPath": os.path.join(HOME, "gone")}]})
        self.assertEqual(gone.returncode, 2)
        self.assertIn("can't open file", gone.stderr)

    def test_an_unknown_session_is_off(self):
        out = self.run_state("never-seen", "--data-dir", tempfile.mkdtemp())
        self.assertEqual(out.returncode, 0, out.stderr)
        v = json.loads(out.stdout)
        self.assertEqual((v["on"], v["phase"], v["thresholds"]), (False, S.WORKING, None))


if __name__ == "__main__":
    unittest.main()

"""Tests of the tools plugin's cache-keepalive hook (plugins/tools/scripts/cache_keepalive.py), run as Claude Code
runs it: the hook input on stdin, the options in the environment, a temp data folder, the delay cut to a fraction of
a second. Arming only while waiting, the wake (exit 2 and its message), a prompt, a newer turn, a busy transcript or
the session's end cancelling a pending timer, the cap on keep-alives in a row, and bad options."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugins" / "tools" / "scripts" / "cache_keepalive.py"
HOOKS_JSON = ROOT / "plugins" / "tools" / "hooks" / "hooks.json"

# The hook runs as `python3`, which on macOS can be the system one (3.9): run it there when it exists.
SYSTEM_PYTHON = pathlib.Path("/usr/bin/python3")
HOOK_PYTHON = str(SYSTEM_PYTHON) if SYSTEM_PYTHON.exists() else sys.executable

TASK = [{"id": "t1", "type": "monitor", "status": "running", "description": "watch"}]
CRON = [{"id": "c1", "schedule": "*/5 * * * *", "recurring": True, "prompt": "check"}]


class Hook(unittest.TestCase):
    def setUp(self):
        self.data = pathlib.Path(tempfile.mkdtemp())
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CACHE_KEEPALIVE"))}
        self.env.update(CLAUDE_PLUGIN_DATA=str(self.data), CACHE_KEEPALIVE_AFTER="0.3", CACHE_KEEPALIVE_POLL="0.05")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
            p.stderr.close()

    def payload(self, event, **extra):
        return json.dumps({"hook_event_name": event, "session_id": "s-1", **extra})

    def start(self, event, env=None, **extra):
        p = subprocess.Popen(
            [HOOK_PYTHON, "-B", str(HOOK)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**self.env, **(env or {})},
        )
        self.procs.append(p)
        p.stdin.write(self.payload(event, **extra))
        p.stdin.close()
        return p

    def armed(self, token=None):
        """Waits until a Stop has saved its token (a different one than `token`), so the next event comes after it."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                current = self.state().get("token")
            except (OSError, ValueError):
                current = None
            if current and current != token:
                return current
            time.sleep(0.01)
        self.fail("the Stop hook never saved its token")

    def run_hook(self, event, env=None, **extra):
        p = self.start(event, env, **extra)
        p.wait(timeout=10)
        return p.returncode, p.stderr.read()

    def stop(self, env=None, **extra):
        extra.setdefault("background_tasks", TASK)
        extra.setdefault("session_crons", [])
        return self.run_hook("Stop", env, **extra)

    def state(self):
        return json.loads((self.data / "cache-keepalive" / "s-1.json").read_text())

    def test_wakes_while_a_background_task_runs(self):
        code, err = self.stop()
        self.assertEqual(code, 2)
        self.assertIn("Cache keep-alive", err)
        self.assertLess(len(err), 400)
        self.assertEqual(self.state()["count"], 1)

    def test_wakes_while_a_cron_is_scheduled(self):
        code, _ = self.stop(background_tasks=[], session_crons=CRON)
        self.assertEqual(code, 2)

    def test_idle_with_nothing_pending_stays_cold(self):
        code, err = self.stop({"CACHE_KEEPALIVE_AFTER": "5"}, background_tasks=[], session_crons=[])
        self.assertEqual((code, err), (0, ""))

    def test_always_arms_without_waiting(self):
        code, _ = self.stop({"CACHE_KEEPALIVE": "always"}, background_tasks=[])
        self.assertEqual(code, 2)

    def test_off_never_arms(self):
        self.assertEqual(self.stop({"CACHE_KEEPALIVE": "off"}), (0, ""))

    def test_a_prompt_cancels_the_pending_timer(self):
        p = self.start("Stop", {"CACHE_KEEPALIVE_AFTER": "5"}, background_tasks=TASK)
        self.armed()
        self.assertEqual(self.run_hook("UserPromptSubmit", prompt="back"), (0, ""))
        p.wait(timeout=2)
        self.assertEqual(p.returncode, 0)

    def test_a_newer_turn_supersedes_the_older_timer(self):
        old = self.start("Stop", {"CACHE_KEEPALIVE_AFTER": "5"}, background_tasks=TASK)
        self.armed()
        code, _ = self.stop()
        old.wait(timeout=2)
        self.assertEqual((old.returncode, code), (0, 2))

    def test_session_end_cancels_and_cleans_up(self):
        p = self.start("Stop", {"CACHE_KEEPALIVE_AFTER": "5"}, background_tasks=TASK)
        self.armed()
        self.assertEqual(self.run_hook("SessionEnd", reason="exit"), (0, ""))
        p.wait(timeout=2)
        self.assertEqual(p.returncode, 0)
        self.assertFalse((self.data / "cache-keepalive" / "s-1.json").exists())

    def test_cap_on_keepalives_in_a_row_until_the_user_is_back(self):
        cap = {"CACHE_KEEPALIVE_MAX": "2"}
        self.assertEqual(self.stop(cap)[0], 2)  # an ordinary turn ends: first keep-alive
        self.assertEqual(self.stop(cap)[0], 2)  # the keep-alive's turn ends: second
        self.assertEqual(self.stop(cap)[0], 0)  # cap reached: left to go cold
        self.run_hook("UserPromptSubmit", prompt="back")
        self.assertEqual(self.stop(cap)[0], 2)

    def test_the_keepalive_wake_is_not_the_user_coming_back(self):
        cap = {"CACHE_KEEPALIVE_MAX": "1"}
        code, message = self.stop(cap)
        self.assertEqual(code, 2)
        # Claude Code delivers the wake as a task notification, which UserPromptSubmit sees with the message
        wake = "<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n" + message
        self.assertEqual(self.run_hook("UserPromptSubmit", prompt=wake), (0, ""))
        self.assertEqual(self.stop(cap)[0], 0)

    def test_a_prompt_quoting_the_marker_still_cancels(self):
        p = self.start("Stop", {"CACHE_KEEPALIVE_AFTER": "5"}, background_tasks=TASK)
        self.armed()
        quoted = "What does 'Cache keep-alive (tools plugin, cache-keepalive hook)' mean?"
        self.assertEqual(self.run_hook("UserPromptSubmit", prompt=quoted), (0, ""))
        p.wait(timeout=2)
        self.assertEqual(p.returncode, 0)

    def test_a_busy_transcript_cancels_the_timer(self):
        # A turn a Stop hook continues, or one a task notification starts, writes to the transcript with no new Stop
        transcript = self.data / "t.jsonl"
        transcript.write_text("{}\n")
        p = self.start("Stop", {"CACHE_KEEPALIVE_AFTER": "4"}, background_tasks=TASK, transcript_path=str(transcript))
        self.armed()  # the grace counts from the hook's start, which a cold interpreter delays
        # The transcript keeps growing until the hook exits: some growth lands after its baseline, however late the
        # runner takes it. Past AFTER, a hook that does not cancel fails on its exit code, not a timeout.
        deadline = time.monotonic() + 10
        while p.poll() is None and time.monotonic() < deadline:
            with transcript.open("a") as f:
                f.write('{"type": "assistant"}\n')
            time.sleep(0.1)
        p.wait(timeout=1)
        self.assertEqual((p.returncode, p.stderr.read()), (0, ""))

    def test_a_quiet_transcript_still_wakes(self):
        transcript = self.data / "t.jsonl"
        transcript.write_text("{}\n")
        code, _ = self.stop(transcript_path=str(transcript))
        self.assertEqual(code, 2)

    def test_non_finite_options_fall_back_to_the_defaults(self):
        bad = {"CACHE_KEEPALIVE_MAX": "nan", "CACHE_KEEPALIVE_AFTER": "inf"}
        p = self.start("Stop", bad, background_tasks=TASK)
        self.armed()
        self.run_hook("UserPromptSubmit", prompt="back")
        p.wait(timeout=2)
        nan_max = {"CACHE_KEEPALIVE_MAX": "nan"}
        for _ in range(12):
            self.assertEqual(self.stop(nan_max)[0], 2)
        self.assertEqual(self.stop(nan_max)[0], 0)  # the default cap of 12, not none

    def test_another_turn_between_keepalives_restarts_the_count(self):
        cap = {"CACHE_KEEPALIVE_MAX": "1"}
        self.assertEqual(self.stop(cap)[0], 2)
        # A background task's notification starts a turn that ends with nothing pending: not a keep-alive turn
        self.assertEqual(self.stop(cap, background_tasks=[])[0], 0)
        self.assertEqual(self.stop(cap)[0], 2)

    def test_bad_input_is_ignored(self):
        p = subprocess.run(
            [HOOK_PYTHON, "-B", str(HOOK)], input="not json", capture_output=True, text=True, env=self.env, check=False
        )
        self.assertEqual((p.returncode, p.stderr), (0, ""))

    def test_hooks_json_wires_the_three_events(self):
        hooks = json.loads(HOOKS_JSON.read_text())["hooks"]
        stop = hooks["Stop"][0]["hooks"][0]
        self.assertTrue(stop["asyncRewake"])
        self.assertGreaterEqual(stop["timeout"], 3600)
        for event in ("Stop", "UserPromptSubmit", "SessionEnd"):
            self.assertIn("cache_keepalive.py", hooks[event][0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()

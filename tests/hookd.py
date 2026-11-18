"""Tests of the handover plugin's hook daemon (plugins/handover/scripts/hookd.py) and its client (hookd-client),
run as Claude Code runs the hot hooks: `sh hookd-client`, the hook input on stdin, the session in the environment.

A probe plugin (a stand-in handover.py that echoes what its hook saw) checks the contract: the environment, cwd,
parent pid and input reach the hook, and with no daemon to connect to the client runs the cold hook. The real
handover.py checks that the daemon answers as the cold hook does."""

import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "handover" / "scripts"
CLIENT = SCRIPTS / "hookd-client"
# The hooks run as `python3`, which on macOS can be the system one (3.9): run the daemon there when it exists.
PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable

PROBE = f"""import json, os, sys
sys.path.insert(0, {str(SCRIPTS)!r})
import hookd

HOOK_PID = None


def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detach(args):
    return None


def cmd_hook(_args):
    inp = json.load(sys.stdin)
    if inp.get("raise"):
        raise RuntimeError("probe failure")
    print(json.dumps({{"via": "daemon" if HOOK_PID else "cold", "probe": os.environ.get("PROBE"), "cwd": os.getcwd(),
                      "pid": HOOK_PID, "input": inp, "start": os.environ.get("HANDOVER_HOOKD_START")}}))
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "hookd":
        sys.exit(hookd.serve(sys.modules[__name__], idle=float(os.environ.get("IDLE", "3600")), poll=0.2))
    sys.exit(cmd_hook(None))
"""


def short_tmp():
    # A Unix socket path has a limit of about 104 bytes: macOS's own temp folder is too deep.
    return pathlib.Path(tempfile.mkdtemp(dir="/tmp")).resolve()


def answers(sock):
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(str(sock))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_for(cond, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class Daemon:
    def __init__(self, script, env):
        self.p = subprocess.Popen([PYTHON, str(script), "hookd"], env=env, stdout=subprocess.DEVNULL)

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
            self.p.wait(10)


class Contract(unittest.TestCase):
    """The client and the daemon, with the probe plugin."""

    def setUp(self):
        self.tmp = short_tmp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.scripts = self.tmp / "probe" / "scripts"
        self.scripts.mkdir(parents=True)
        shutil.copy(CLIENT, self.scripts / "hookd-client")
        self.script = self.scripts / "handover.py"
        self.script.write_text(PROBE)
        self.data = self.tmp / "data"
        self.sock = self.data / "hookd-probe.sock"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp),
            "CLAUDE_PLUGIN_DATA": str(self.data),
            "PROBE": "a value with spaces, = and é",
        }

    def start(self, **env):
        d = Daemon(self.script, {**self.env, **env})
        self.addCleanup(d.stop)
        self.assertTrue(wait_for(lambda: answers(self.sock)), "the daemon never answered")
        return d

    def hook(self, inp, cwd=None, **env):
        return subprocess.run(
            ["/bin/sh", str(self.scripts / "hookd-client")],
            input=json.dumps(inp),
            capture_output=True,
            text=True,
            env={**self.env, **env},
            cwd=cwd or self.tmp,
            check=False,
        )

    def test_the_daemon_runs_the_hook_in_the_session_environment(self):
        self.start()
        cwd = self.tmp / "a dir"
        cwd.mkdir()
        p = self.hook({"hook_event_name": "PreToolUse", "text": "line\nbreak"}, cwd=cwd)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["via"], "daemon")
        self.assertEqual(out["probe"], self.env["PROBE"])
        self.assertEqual(out["cwd"], str(cwd))
        self.assertEqual(out["input"], {"hook_event_name": "PreToolUse", "text": "line\nbreak"})
        self.assertIsNone(out["start"])
        # The client's parent: the hook's own command runs under claude, the daemon's child does not.
        self.assertEqual(out["pid"], os.getpid())

    def test_with_no_socket_the_cold_hook_runs_and_starts_the_daemon(self):
        out = json.loads(self.hook({"n": 1}).stdout)
        self.assertEqual((out["via"], out["start"], out["input"]), ("cold", "1", {"n": 1}))

    def test_a_socket_nobody_listens_on_falls_back_to_the_cold_hook(self):
        self.data.mkdir()
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.sock))
        s.close()
        p = self.hook({"n": 2})
        self.assertEqual(json.loads(p.stdout)["via"], "cold", p.stderr)

    def test_turned_off_the_client_runs_the_cold_hook_without_starting_the_daemon(self):
        self.start()
        out = json.loads(self.hook({"n": 3}, HANDOVER_HOOKD="off").stdout)
        self.assertEqual((out["via"], out["start"]), ("cold", "1"))

    def test_without_a_usable_curl_the_cold_hook_runs(self):
        self.start()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for tool in ("env", "python3", "cat"):
            os.symlink(shutil.which(tool), bin_dir / tool)
        for curl in (None, "#!/bin/sh\nexit 2\n"):  # none, then one too old for --fail-with-body
            with self.subTest(curl=curl):
                if curl:
                    (bin_dir / "curl").write_text(curl)
                    (bin_dir / "curl").chmod(0o755)
                p = self.hook({"n": 10}, PATH=str(bin_dir))
                self.assertEqual(json.loads(p.stdout)["via"], "cold", p.stderr)

    def test_bytecode_written_by_another_python_keeps_the_daemon(self):
        d = self.start()
        (self.scripts / "__pycache__").mkdir()
        (self.scripts / "__pycache__" / "x.pyc").write_text("")
        self.assertEqual(json.loads(self.hook({"n": 11}).stdout)["via"], "daemon")
        self.assertEqual(json.loads(self.hook({"n": 12}).stdout)["via"], "daemon")
        self.assertIsNone(d.p.poll())

    def test_a_socket_path_past_the_limit_starts_no_daemon(self):
        sys.path.insert(0, str(SCRIPTS))
        import hookd

        started = []
        fake = type("H", (), {"plugin_root": staticmethod(lambda: "/p/" + "v" * 120), "detach": started.append})
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.data)
        self.addCleanup(os.environ.pop, "CLAUDE_PLUGIN_DATA")
        self.assertIsNone(hookd.ensure(fake))
        self.assertEqual(started, [])

    def test_a_failing_hook_is_reported_and_not_run_again(self):
        self.start()
        p = self.hook({"raise": True})
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertIn("RuntimeError: probe failure", p.stderr)

    def test_a_hook_of_the_plugin_own_child_does_nothing(self):
        p = self.hook({"n": 4}, HANDOVER_CHILD="1")
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_one_daemon_per_version(self):
        self.start()
        second = subprocess.run([PYTHON, str(self.script), "hookd"], env=self.env, timeout=10, check=False)
        self.assertEqual(second.returncode, 0)
        self.assertTrue(answers(self.sock))

    def test_a_stale_socket_is_replaced(self):
        self.data.mkdir()
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.sock))
        s.close()
        self.start()
        self.assertEqual(json.loads(self.hook({"n": 5}).stdout)["via"], "daemon")

    def test_the_daemon_exits_once_idle(self):
        d = self.start(IDLE="0.5")
        self.assertEqual(json.loads(self.hook({"n": 6}).stdout)["via"], "daemon")
        d.p.wait(10)
        self.assertFalse(self.sock.exists())

    def test_the_daemon_exits_once_its_scripts_change(self):
        d = self.start()
        time.sleep(0.01)
        self.script.write_text(PROBE + "\n")
        self.hook({"n": 7})  # served by the old code, then the daemon stops
        d.p.wait(10)
        self.assertFalse(self.sock.exists())
        self.assertEqual(json.loads(self.hook({"n": 8}).stdout)["via"], "cold")

    def test_the_daemon_exits_once_its_socket_is_gone(self):
        d = self.start()
        self.sock.unlink()
        self.hook({"n": 9})
        self.assertEqual(d.p.wait(10), 0)


class RealHook(unittest.TestCase):
    """handover.py through the daemon answers as the cold hook does."""

    def setUp(self):
        self.tmp = short_tmp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = self.tmp / "d"
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp), "CLAUDE_PLUGIN_DATA": str(self.data)}
        d = Daemon(SCRIPTS / "handover.py", self.env)
        self.addCleanup(d.stop)
        self.assertTrue(wait_for(lambda: answers(self.data / "hookd-handover.sock")), "the daemon never answered")

    def run_hook(self, inp, hot):
        cmd = ["sh", str(CLIENT)] if hot else [PYTHON, str(SCRIPTS / "handover.py"), "hook"]
        env = self.env if hot else {**self.env, "HANDOVER_HOOKD": "off"}
        p = subprocess.run(
            cmd, input=json.dumps(inp), capture_output=True, text=True, env=env, cwd=self.tmp, check=False
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_an_untagged_background_command_gets_the_same_answer(self):
        for session in ("s1", "s2"):
            with self.subTest(session=session):
                outs = []
                for hot in (False, True):
                    inp = {
                        "hook_event_name": "PreToolUse",
                        "session_id": f"{session}-{hot}",
                        "tool_name": "Bash",
                        "tool_input": {"command": "sleep 100", "run_in_background": True, "description": "wait"},
                        "cwd": str(self.tmp),
                    }
                    outs.append(self.run_hook(inp, hot))
                self.assertEqual(outs[0], outs[1])
                self.assertIn('"permissionDecision": "deny"', outs[1])

    def test_the_hot_events_leave_the_same_state(self):
        for hot in (False, True):
            sid = f"agents-{hot}"
            self.run_hook({"hook_event_name": "SubagentStart", "session_id": sid, "agent_id": "a1"}, hot)
        cold = json.loads((self.data / "sessions" / "agents-False.agents.json").read_text())
        hot = json.loads((self.data / "sessions" / "agents-True.agents.json").read_text())
        self.assertEqual(cold.keys(), hot.keys())


if __name__ == "__main__":
    unittest.main(verbosity=2)

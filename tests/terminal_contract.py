"""The contract of the handover plugin's terminal port (scripts/terminal.py), black box.

The same cases run against every adapter, on a real host: a pane of a private tmux server, a pane of a
throwaway Rex server. A host whose tool is missing is skipped. The subject in the pane is a fake `claude`, this file run with --fake: a raw-mode prompt with the editing rules measured on
the real one (2026-11-05), which logs what it is sent. The cases go through `handover.py terminal <verb>` and
`handover.py relay-drive`, run with the environment the pane really has, as a hook would be.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import tty
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts")
HANDOVER = os.path.join(SCRIPTS, "handover.py")
sys.path.insert(0, SCRIPTS)

import terminal as T

ALL_VERBS = ("type_text", "press_enter", "clear_input", "set_title", "ring", "report_status")
# Left by the host, or by the session running these tests: a case must see only what its pane sets.
LEAKS = ("TMUX", "REX_", "HANDOVER_", "CLAUDE_", "GIT_")
TRICKY = (
    "plain words",
    "/clear",
    "--starts-with-a-dash",
    "ends with a semicolon;",
    "quotes ' \" ` and $HOME \\ # *",
    "accents é ü 日本語",
)


def wait_until(check, seconds=8):
    deadline = time.time() + seconds
    while True:
        value = check()
        if value or time.time() > deadline:
            return value
        time.sleep(0.05)


class Prompt:
    """Claude's prompt: Enter submits, ctrl+j adds a line, ctrl+u and ctrl+k stop at the line's edge and then
    take the newline. So a draft takes one key per line, and text after the cursor survives ctrl+u."""

    def __init__(self, draft="", cursor=0):
        self.text, self.cursor = draft, cursor

    def press(self, ch):
        """The line submitted by this key, or None."""
        t, c = self.text, self.cursor
        if ch == "\r":
            self.text, self.cursor = "", 0
            return t
        if ch == "\x15":
            start = t.rfind("\n", 0, c) + 1
            cut = c - 1 if start == c and c else start
            self.text, self.cursor = t[:cut] + t[c:], cut
        elif ch == "\x0b":
            end = t.find("\n", c)
            end = len(t) if end < 0 else end
            cut = end + 1 if end == c and c < len(t) else end
            self.text = t[:c] + t[cut:]
        else:
            self.text, self.cursor = t[:c] + ("\n" if ch == "\n" else ch) + t[c:], c + 1
        return None


def fake(directory):
    """The subject: reports its environment, then serves the prompt on its terminal."""
    with open(os.path.join(directory, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
    prompt = Prompt(config.get("draft", ""), config.get("cursor", 0))
    tty.setraw(0, termios.TCSANOW)
    with open(os.path.join(directory, "env.tmp"), "w", encoding="utf-8") as f:
        json.dump(dict(os.environ), f)
    os.rename(os.path.join(directory, "env.tmp"), os.path.join(directory, "env.json"))
    log = open(os.path.join(directory, "submitted"), "a", encoding="utf-8")  # noqa: SIM115

    def show():
        with open(os.path.join(directory, "buffer.tmp"), "w", encoding="utf-8") as f:
            f.write(prompt.text)
        os.rename(os.path.join(directory, "buffer.tmp"), os.path.join(directory, "buffer"))

    show()
    stdin = open(0, encoding="utf-8", errors="replace", newline="\n", buffering=1)  # noqa: SIM115
    while ch := stdin.read(1):
        line = prompt.press(ch)
        if line is not None:
            log.write(json.dumps(line) + "\n")
            log.flush()
            if line == "/clear" and config.get("marker"):
                with open(config["marker"], "w", encoding="utf-8") as f:
                    json.dump({"ok": config.get("loads", True)}, f)
        show()


class TmuxHost:
    """A private tmux server, on its own socket and without the user's config."""

    def __init__(self):
        self.socket = f"handover-contract-{os.getpid()}"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(LEAKS)}

    def tmux(self, *args):
        return subprocess.run(
            ["tmux", "-L", self.socket, "-f", os.devnull, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            env=self.env,
        ).stdout.strip()

    def start(self):
        # The window that keeps the server up and stays current: a subject's window can then ring.
        self.tmux("new-session", "-d", "-s", "host", "-x", "100", "-y", "30", "sleep 600")

    def stop(self):
        self.tmux("kill-server")

    def spawn(self, command):
        return self.tmux("new-window", "-d", "-t", "host", "-P", "-F", "#{pane_id}", command)

    def close(self, pane):
        self.tmux("kill-pane", "-t", pane)

    def title(self, pane):
        return self.tmux("display-message", "-p", "-t", pane, "#{window_name}")

    def belled(self, pane):
        return self.tmux("display-message", "-p", "-t", pane, "#{window_bell_flag}") == "1"


class RexHost:
    """A throwaway Rex server, on its own socket and state, never the user's: its pid is checked, and it is stopped
    by signal because `rex server stop` could reach another one. A pane is a (session, block) pair."""

    def __init__(self):
        # The socket's path has to fit in sockaddr_un, so not in the long temporary directory of macOS.
        self.lab = os.path.expanduser(f"~/.cache/hc{os.getpid()}")
        self.endpoint = f"unix://{self.lab}/s.sock"
        # A pane's rex finds this server by REX_SERVER, and a pane inherits the server's environment.
        self.env = {**{k: v for k, v in os.environ.items() if not k.startswith(LEAKS)}, "REX_SERVER": self.endpoint}
        self.watchers = {}

    def rex(self, *args):
        return subprocess.run(
            ["rex", "-S", self.endpoint, "--autostart=false", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            env=self.env,
        ).stdout

    def start(self):
        os.makedirs(os.path.join(self.lab, "state"))
        config = os.path.join(self.lab, "empty.lua")
        open(config, "w").close()
        self.server = subprocess.Popen(
            ["rex", "server", "run", "--listen", self.endpoint, "--state-dir", f"{self.lab}/state", "--config", config],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self.env,
        )

        def serving():
            try:
                return json.loads(self.rex("whoami", "--json"))["pid"] == self.server.pid
            except (subprocess.SubprocessError, ValueError):
                return False

        if not wait_until(serving):
            self.stop()
            raise AssertionError("the throwaway Rex server did not start, or is not the one answering")

    def stop(self):
        for watcher in self.watchers.values():
            watcher.kill()
            watcher.wait()
        self.server.kill()
        self.server.wait()
        shutil.rmtree(self.lab, True)

    def spawn(self, command):
        session = json.loads(self.rex("new", f"s{len(self.watchers)}", "--json", "--", "sh", "-c", command))
        session, block = session["session_id"], session["initial_windows"][0]["block_ids"][0]
        log = os.path.join(self.lab, f"events{len(self.watchers)}")
        with open(log, "w") as f:
            self.watchers[session, block] = subprocess.Popen(
                ["rex", "-S", self.endpoint, "--autostart=false", "events", "-s", session, "--json"],
                stdout=f,
                stderr=subprocess.DEVNULL,
                env=self.env,
            )
        self.logs = {**getattr(self, "logs", {}), (session, block): log}
        # The stream announces itself: a bell before that would be missed.
        wait_until(lambda: os.path.getsize(log))
        return session, block

    def close(self, pane):
        self.rex("kill", pane[0])

    def title(self, pane):
        windows = json.loads(self.rex("window", "ls", "-s", pane[0], "--json"))["windows"]
        return windows[0]["label"]

    def belled(self, pane):
        with open(self.logs[pane], encoding="utf-8") as f:
            return any('"name":"bell"' in line and pane[1] in line for line in f)

    def status(self, pane):
        records = json.loads(self.rex("block", "call", "-s", pane[0], "-b", pane[1], "program_status"))["records"]
        return (records[0].get("id"), records[0].get("state")) if records else None


class Contract:
    """The cases every adapter passes; a subclass per host names the adapter it expects."""

    Host = None
    adapter = None

    @classmethod
    def setUpClass(cls):
        cls.host = cls.Host()
        cls.host.start()
        cls.addClassCleanup(cls.host.stop)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hc")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = os.path.join(self.root, "data")
        os.makedirs(os.path.join(self.data, "relay"))

    def subject(self, **config):
        """Starts the fake claude in a new pane; the pane, and the environment a hook would have in it."""
        self.dir = tempfile.mkdtemp(dir=self.root)
        with open(os.path.join(self.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
        python = shutil.which("python3") or sys.executable
        self.pane = self.host.spawn(f"'{python}' '{os.path.abspath(__file__)}' --fake '{self.dir}'")
        path = os.path.join(self.dir, "env.json")
        self.assertTrue(wait_until(lambda: os.path.exists(path)), "the fake claude did not start")
        with open(path, encoding="utf-8") as f:
            self.env = {**json.load(f), "CLAUDE_PLUGIN_DATA": self.data, "CLAUDE_PLUGIN_OPTION_NOTIFIER": "bell"}

    def handover(self, *args):
        return subprocess.run(
            [sys.executable, HANDOVER, *args], capture_output=True, text=True, timeout=30, env=self.env, check=False
        )

    def verb(self, *args):
        p = self.handover("terminal", *args)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return json.loads(p.stdout)

    def buffer(self):
        with open(os.path.join(self.dir, "buffer"), encoding="utf-8") as f:
            return f.read()

    def submitted(self):
        try:
            with open(os.path.join(self.dir, "submitted"), encoding="utf-8") as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def assertBuffer(self, text):
        wait_until(lambda: self.buffer() == text)
        self.assertEqual(self.buffer(), text)

    def assertSubmitted(self, lines):
        wait_until(lambda: self.submitted() == lines)
        self.assertEqual(self.submitted(), lines)

    def test_describe_names_the_adapter_and_what_it_can_do(self):
        self.subject()
        d = self.verb("describe")
        self.assertEqual(d["adapter"], self.adapter)
        self.assertTrue(d["address"])
        self.assertTrue(d["relays"])
        self.assertLessEqual({"type_text", "press_enter"}, set(d["verbs"]))
        self.assertLessEqual(set(d["verbs"]), set(ALL_VERBS))

    def test_a_verb_the_adapter_lacks_does_nothing_and_says_so(self):
        self.subject(draft="kept")
        lacking = set(ALL_VERBS) - set(self.verb("describe")["verbs"])
        for verb in lacking:
            p = self.handover("terminal", verb, "--text=x")
            self.assertEqual((p.returncode, json.loads(p.stdout)["done"]), (1, False), verb)
        self.assertBuffer("kept")

    def test_typed_text_arrives_as_is_and_is_not_submitted(self):
        self.subject()
        for text in TRICKY:
            with self.subTest(text):
                self.assertTrue(self.verb("type_text", f"--text={text}")["done"])
                self.assertBuffer(text)
                self.verb("clear_input")
                self.assertBuffer("")
        self.assertEqual(self.submitted(), [])

    def test_enter_submits_what_was_typed(self):
        self.subject()
        self.verb("type_text", "--text=/clear")
        self.assertBuffer("/clear")
        self.assertTrue(self.verb("press_enter")["done"])
        self.assertSubmitted(["/clear"])
        self.assertBuffer("")

    def test_clear_input_empties_a_draft_wherever_the_cursor_is(self):
        drafts = {
            "one line": ("a draft", 7),
            "several lines": ("first\nsecond\nthird", 17),
            "cursor inside": ("first\nsecond\nthird", 2),
            "at the very start": ("first\nsecond", 0),
        }
        for name, (draft, cursor) in drafts.items():
            with self.subTest(name):
                self.subject(draft=draft, cursor=cursor)
                self.assertBuffer(draft)
                self.assertTrue(self.verb("clear_input")["done"])
                self.assertBuffer("")
                self.assertEqual(self.submitted(), [])

    def test_clear_input_on_an_empty_prompt_changes_nothing(self):
        self.subject()
        self.assertTrue(self.verb("clear_input")["done"])
        self.assertBuffer("")

    def test_ring_reaches_the_pane(self):
        self.subject()
        if "ring" not in self.verb("describe")["verbs"]:
            self.skipTest("no bell on this adapter")
        self.assertTrue(self.verb("ring")["done"])
        self.assertTrue(wait_until(lambda: self.host.belled(self.pane)))

    def test_set_title_names_the_tab(self):
        self.subject()
        if "set_title" not in self.verb("describe")["verbs"]:
            self.skipTest("no title on this adapter")
        self.assertTrue(self.verb("set_title", "--text=port the relay #3")["done"])
        self.assertTrue(wait_until(lambda: self.host.title(self.pane) == "port the relay #3"))

    def test_report_status_reaches_the_tab(self):
        self.subject()
        if "report_status" not in self.verb("describe")["verbs"]:
            self.skipTest("no status on this adapter")
        self.assertTrue(self.verb("report_status", "--state=blocked", "--message=needs you, é")["done"])
        self.assertTrue(wait_until(lambda: self.host.status(self.pane) == ("handover", "blocked")))
        self.assertTrue(self.verb("report_status", "--state=clear")["done"])
        self.assertTrue(wait_until(lambda: self.host.status(self.pane) is None))

    def relay_drive(self, message="Continue the work"):
        d = self.verb("describe")
        return self.handover(
            "relay-drive",
            "--session",
            "s1",
            f"--terminal={d['adapter']}",
            f"--address={d['address']}",
            f"--message={message}",
        )

    def marker(self):
        return os.path.join(self.data, "relay", "s1.loaded.json")

    def test_the_relay_clears_the_draft_then_sends_clear_then_the_message(self):
        self.subject(draft="half a thought\nand more", cursor=4, marker=self.marker())
        p = self.relay_drive("--Continue; the work;")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertSubmitted(["/clear", "--Continue; the work;"])
        self.assertBuffer("")
        self.assertFalse(os.path.exists(self.marker()))
        with open(os.path.join(self.data, "metrics.jsonl"), encoding="utf-8") as f:
            events = [json.loads(line) for line in f]
        self.assertEqual(events[-1]["event"], "relay_resumed")
        self.assertEqual(events[-1]["mode"], self.adapter)

    def test_a_new_session_that_loads_nothing_stalls_the_relay(self):
        self.subject(marker=self.marker(), loads=False)
        p = self.relay_drive()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertSubmitted(["/clear"])
        self.assertTrue(wait_until(lambda: self.host.belled(self.pane)), "the stall rings the pane")

    def test_a_lost_pane_stalls_the_relay(self):
        self.subject(marker=self.marker())
        d = self.verb("describe")
        self.host.close(self.pane)
        p = self.handover(
            "relay-drive", "--session", "s1", f"--terminal={d['adapter']}", f"--address={d['address']}", "--message=x"
        )
        self.assertEqual(p.returncode, 1, p.stderr)


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class Tmux(Contract, unittest.TestCase):
    Host = TmuxHost
    adapter = "tmux"


@unittest.skipUnless(shutil.which("rex"), "rex is not installed")
class Rex(Contract, unittest.TestCase):
    Host = RexHost
    adapter = "rex"


class Selection(unittest.TestCase):
    """Which adapter a session gets, by the environment it runs in."""

    def test_the_innermost_host_wins(self):
        env = {"TMUX_PANE": "%1", "REX_SESSION": "s", "REX_BLOCK": "b", "HANDOVER_RELAY_FILE": "/f"}
        self.assertEqual(T.detect(env).name, "tmux")
        del env["TMUX_PANE"]
        self.assertEqual(T.detect(env).name, "rex")

    def test_the_restart_loop_relays_without_typing(self):
        loop = T.detect({"HANDOVER_RELAY_FILE": "/f"})
        self.assertEqual((loop.name, loop.address, loop.relays, loop.types), ("loop", "/f", True, False))

    def test_elsewhere_there_is_no_relay(self):
        none = T.detect({})
        self.assertEqual((none.name, none.relays, none.types), ("none", False, False))

    def test_the_detached_relay_rebuilds_the_adapter_from_its_description(self):
        d = T.detect({"TMUX_PANE": "%7"}).describe()
        self.assertEqual(T.adapter(d["adapter"], d["address"]).describe(), d)


class Prompts(unittest.TestCase):
    """The fake's prompt keeps to what the real one does: see the class's docstring."""

    def keys(self, prompt, text):
        for ch in text:
            prompt.press(ch)
        return prompt.text

    def test_ctrl_u_takes_the_line_then_the_newline(self):
        self.assertEqual(self.keys(Prompt("one\ntwo", 7), "\x15"), "one\n")
        self.assertEqual(self.keys(Prompt("one\ntwo", 7), "\x15\x15"), "one")

    def test_text_after_the_cursor_survives_ctrl_u(self):
        self.assertEqual(self.keys(Prompt("abcmid def", 3), "\x15"), "mid def")

    def test_ctrl_k_takes_the_rest_of_the_line_then_the_newline(self):
        self.assertEqual(self.keys(Prompt("abc\nmid", 3), "\x0b"), "abcmid")
        self.assertEqual(self.keys(Prompt("a def\nmid", 1), "\x0b"), "a\nmid")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fake"]:
        fake(sys.argv[2])
    else:
        unittest.main()

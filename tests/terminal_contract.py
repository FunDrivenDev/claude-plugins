"""The contract of the handover plugin's terminal port (scripts/terminal.py), black box.

The same cases run against every adapter, on a real host: a pane of a private tmux server. The subject in
the pane is a fake `claude`, this file run with --fake: a raw-mode prompt with the editing rules measured on
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
        self.dir = tempfile.mkdtemp(prefix="hc")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.data = os.path.join(self.dir, "data")
        os.makedirs(os.path.join(self.data, "relay"))

    def subject(self, **config):
        """Starts the fake claude in a new pane; the pane, and the environment a hook would have in it."""
        with open(os.path.join(self.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
        python = shutil.which("python3") or sys.executable
        self.pane = self.host.spawn(f"'{python}' '{os.path.abspath(__file__)}' --fake '{self.dir}'")
        path = os.path.join(self.dir, "env.json")
        self.assertTrue(wait_until(lambda: os.path.exists(path)), "the fake claude did not start")
        with open(path, encoding="utf-8") as f:
            self.env = {**json.load(f), "CLAUDE_PLUGIN_DATA": self.data}

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
            p = self.handover("terminal", verb, "x")
            self.assertEqual((p.returncode, json.loads(p.stdout)["done"]), (1, False), verb)
        self.assertBuffer("kept")

    def test_typed_text_arrives_as_is_and_is_not_submitted(self):
        self.subject()
        for text in TRICKY:
            with self.subTest(text):
                self.assertTrue(self.verb("type_text", "--", text)["done"])
                self.assertBuffer(text)
                self.verb("clear_input")
                self.assertBuffer("")
        self.assertEqual(self.submitted(), [])

    def test_enter_submits_what_was_typed(self):
        self.subject()
        self.verb("type_text", "--", "/clear")
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
        self.assertTrue(self.verb("set_title", "--", "port the relay #3")["done"])
        self.assertTrue(wait_until(lambda: self.host.title(self.pane) == "port the relay #3"))

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


class Selection(unittest.TestCase):
    """Which adapter a session gets, by the environment it runs in."""

    def test_the_innermost_host_wins(self):
        env = {"TMUX_PANE": "%1", "HANDOVER_RELAY_FILE": "/f"}
        self.assertEqual(T.detect(env).describe()["adapter"], "tmux")

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

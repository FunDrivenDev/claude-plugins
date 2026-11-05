"""How the handover plugin acts on the terminal its session runs in: a port and its adapters.

The plugin depends on the port alone: `Terminal`, whose verbs are

    type_text(text)      type into the session's prompt, without submitting
    press_enter()        submit what the prompt holds
    clear_input()        empty the prompt, so that what is typed next does not merge with a draft
    set_title(title)     name the session's tab
    ring()               ring the terminal's bell
    report_status(state, message)  show a status on the session's tab: a state of STATES, and one line

An adapter whose host can end a session and restore its pane sets `recovers`, and answers `instance()`, what
identifies its server now, and `survey(instance)`: "gone", the server does not answer; "restarted", another
server than `instance` holds the pane; "ended", anything else.

`detect()` picks the adapter from the `terminal` option and the environment, innermost host first, and
`adapter()` rebuilds one from its name and address, for the detached half of the relay:

    tmux  TMUX_PANE, the session's pane
    rex   REX_SESSION and REX_BLOCK, the session's pane in Rex; REX_SERVER tells the rex CLI which server
    command  the terminal_command option, only when `terminal` is command: sh runs it for each verb, with
          HANDOVER_VERB, HANDOVER_TEXT and HANDOVER_STATE in its environment (docs/relay.md)
    loop  HANDOVER_RELAY_FILE, the `toolbox session run` loop: nothing to type into, the relay restarts claude
    none  neither: no relay

A verb an adapter lacks does nothing and returns False, and `verbs` lists those it has; only typing is
required for the relay to type. A verb never raises: it returns False when it could not be done. The contract
is tests/terminal_contract.py, which every adapter passes.
"""

import base64
import contextlib
import json
import os
import subprocess

TIMEOUT = 5
# Keys sent to empty Claude's prompt. ctrl+u and ctrl+k stop at the edge of the line, then take the newline, and
# text after the cursor survives ctrl+u: both, once per line, and a draft longer than this keeps its head.
CLEAR_LINES = 64
VERBS = ("type_text", "press_enter", "clear_input", "set_title", "ring", "report_status")
STATES = ("idle", "working", "done", "blocked", "error", "clear")


def _write(tty, text):
    with contextlib.suppress(OSError), open(tty, "w") as f:
        f.write(text)
        return True
    return False


def _ring(tty="/dev/tty"):
    return _write(tty, "\a")


class Terminal:
    """The port, and an adapter that has none of it: the bell of the controlling terminal aside."""

    name = "none"
    verbs = ("ring",)
    recovers = False

    def __init__(self, address=""):
        self.address = address

    @property
    def types(self):
        """Whether the relay can type into this session."""
        return "type_text" in self.verbs

    @property
    def relays(self):
        return self.types

    def type_text(self, text):
        return False

    def press_enter(self):
        return False

    def clear_input(self):
        return False

    def set_title(self, title):
        return False

    def ring(self):
        return _ring()

    def report_status(self, state, message=""):
        return False

    def instance(self):
        return ""

    def survey(self, instance):
        return "ended"

    def describe(self):
        return {"adapter": self.name, "address": self.address, "relays": self.relays, "verbs": list(self.verbs)}


class Loop(Terminal):
    """Under the `toolbox session run` loop, the address its relay file: the relay ends claude, which the loop
    restarts with the message."""

    name = "loop"

    @property
    def relays(self):
        return True


class Tmux(Terminal):
    """A tmux pane, the address its id. tmux finds its server through $TMUX, as for the session itself."""

    name = "tmux"
    verbs = ("type_text", "press_enter", "clear_input", "set_title", "ring")

    def _tmux(self, *args):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=TIMEOUT, check=True).stdout
        return None

    def _keys(self, *keys):
        return self._tmux("send-keys", "-t", self.address, *keys) is not None

    def type_text(self, text):
        # tmux reads an argument's trailing ; as the end of the command.
        return self._keys("-l", "--", text[:-1] + r"\;" if text.endswith(";") else text)

    def press_enter(self):
        return self._keys("Enter")

    def clear_input(self):
        return self._keys(*["C-k"] * CLEAR_LINES, *["C-u"] * CLEAR_LINES)

    def set_title(self, title):
        return self._tmux("rename-window", "-t", self.address, "--", title) is not None

    def ring(self):
        tty = self._tmux("display-message", "-p", "-t", self.address, "#{pane_tty}")
        return _ring((tty or "").strip() or "/dev/tty")


class Rex(Terminal):
    """A pane of Rex, the address its session and block ids. --autostart=false: a server gone stays gone, a new one
    would hold none of these ids."""

    name = "rex"
    verbs = VERBS
    recovers = True

    def __init__(self, address=""):
        super().__init__(address)
        self.session, _, self.block = address.partition(" ")

    def _rex(self, *args, stdin=None):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            return subprocess.run(
                ["rex", "--autostart=false", *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                check=True,
            ).stdout
        return None

    def _keys(self, *keys):
        return self._rex("send-key", "-s", self.session, "-b", self.block, *keys) is not None

    def _json(self, *args):
        with contextlib.suppress(TypeError, ValueError):
            return json.loads(self._rex(*args))
        return {}

    def _tty(self):
        """The pane's tty, for what only a program in the pane can send. Rex does not name it: the foreground
        process does."""
        process = self._json("block", "call", "-s", self.session, "-b", self.block, "process")
        pid = (process.get("foreground") or {}).get("pid")
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            tty = subprocess.run(
                ["ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True, timeout=TIMEOUT, check=True
            ).stdout.strip()
            return f"/dev/{tty}" if tty else None
        return None

    def instance(self):
        return self._json("whoami", "--json").get("instance_id", "")

    def survey(self, instance):
        now = self.instance()
        if not now:
            return "gone"
        blocks = self._json("block", "ls", "-s", self.session, "--json").get("blocks") or []
        held = any(b.get("block_id") == self.block for b in blocks)
        return "restarted" if held and now != instance else "ended"

    def type_text(self, text):
        # By stdin: as an argument, a leading dash would read as a flag.
        return self._rex("send", "-s", self.session, "-b", self.block, stdin=text) is not None

    def press_enter(self):
        return self._keys("enter")

    def clear_input(self):
        return self._keys(*["ctrl+k"] * CLEAR_LINES, *["ctrl+u"] * CLEAR_LINES)

    def set_title(self, title):
        block = self._json("block", "inspect", "-s", self.session, self.block, "--json").get("block") or {}
        window = block.get("window_id")
        return bool(window) and self._rex("window", "rename", "-s", self.session, window, title) is not None

    def ring(self):
        tty = self._tty()
        return _ring(tty) if tty else False

    def report_status(self, state, message=""):
        tty = self._tty()
        if not tty or state not in STATES:
            return False
        msg = base64.b64encode(message.encode()).decode()
        return _write(tty, f"\x1b]7501;state={state}:id=handover:app=handover:msg={msg}\x1b\\")


class Command(Terminal):
    """The user's own command, the address: it gets every verb, and fails on those it has no way to do."""

    name = "command"
    verbs = VERBS

    def _run(self, verb, text="", state=""):
        env = dict(os.environ, HANDOVER_VERB=verb, HANDOVER_TEXT=text, HANDOVER_STATE=state)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            p = subprocess.run(["sh", "-c", self.address], capture_output=True, timeout=TIMEOUT, check=False, env=env)
            return p.returncode == 0
        return False

    def type_text(self, text):
        return self._run("type_text", text)

    def press_enter(self):
        return self._run("press_enter")

    def clear_input(self):
        return self._run("clear_input")

    def set_title(self, title):
        return self._run("set_title", title)

    def ring(self):
        return self._run("ring") or _ring()

    def report_status(self, state, message=""):
        return self._run("report_status", message, state)


ADAPTERS = {a.name: a for a in (Terminal, Loop, Tmux, Rex, Command)}
CHOICES = ("auto", "tmux", "rex", "command", "none")


def adapter(name, address=""):
    """The adapter `name` at `address`, as `Terminal.describe()` gave them."""
    return ADAPTERS.get(name, Terminal)(address)


def detect(environ, choice="auto", command=""):
    """The adapter for the host this session runs in: `choice`, or under auto the innermost one, so that tmux
    inside another terminal is tmux. A choice the environment cannot serve gives no terminal to type into."""
    choice = (choice or "auto").strip().lower()
    command = (command or "").strip()
    if choice == "command" and command:
        return Command(command)
    if choice in ("auto", "tmux") and environ.get("TMUX_PANE"):
        return Tmux(environ["TMUX_PANE"])
    if choice in ("auto", "rex") and environ.get("REX_SESSION") and environ.get("REX_BLOCK"):
        return Rex(f"{environ['REX_SESSION']} {environ['REX_BLOCK']}")
    if environ.get("HANDOVER_RELAY_FILE"):
        return Loop(environ["HANDOVER_RELAY_FILE"])
    return Terminal()

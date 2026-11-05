"""How the handover plugin acts on the terminal its session runs in: a port and its adapters.

The plugin depends on the port alone: `Terminal`, whose verbs are

    type_text(text)      type into the session's prompt, without submitting
    press_enter()        submit what the prompt holds
    clear_input()        empty the prompt, so that what is typed next does not merge with a draft
    set_title(title)     name the session's tab
    ring()               ring the terminal's bell
    report_status(text)  show a status on the session's tab

`detect()` picks the adapter from the environment, innermost host first, and `adapter()` rebuilds one from
its name and address, for the detached half of the relay:

    tmux  TMUX_PANE, the session's pane
    loop  HANDOVER_RELAY_FILE, the `toolbox session run` loop: nothing to type into, the relay restarts claude
    none  neither: no relay

A verb an adapter lacks does nothing and returns False, and `verbs` lists those it has; only typing is
required for the relay to type. A verb never raises: it returns False when it could not be done. The contract
is tests/terminal_contract.py, which every adapter passes.
"""

import contextlib
import subprocess

TIMEOUT = 5
# Keys sent to empty Claude's prompt. ctrl+u and ctrl+k stop at the edge of the line, then take the newline, and
# text after the cursor survives ctrl+u: both, once per line, and a draft longer than this keeps its head.
CLEAR_LINES = 64
VERBS = ("type_text", "press_enter", "clear_input", "set_title", "ring", "report_status")


def _ring(tty="/dev/tty"):
    with contextlib.suppress(OSError), open(tty, "w") as f:
        f.write("\a")
        return True
    return False


class Terminal:
    """The port, and an adapter that has none of it: the bell of the controlling terminal aside."""

    name = "none"
    verbs = ("ring",)

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

    def report_status(self, status):
        return False

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


ADAPTERS = {a.name: a for a in (Terminal, Loop, Tmux)}


def adapter(name, address=""):
    """The adapter `name` at `address`, as `Terminal.describe()` gave them."""
    return ADAPTERS.get(name, Terminal)(address)


def detect(environ):
    """The adapter for the host this session runs in: the innermost one, so tmux inside another terminal is tmux."""
    if environ.get("TMUX_PANE"):
        return Tmux(environ["TMUX_PANE"])
    if environ.get("HANDOVER_RELAY_FILE"):
        return Loop(environ["HANDOVER_RELAY_FILE"])
    return Terminal()

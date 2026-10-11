"""How the handover plugin calls the user back to the keyboard: a port and its adapters.

The plugin depends on the port alone, `Notifier.notify(title, message)`; `notifier()` picks
the adapters from the `notifier` option and the platform:

    auto     the desktop notifier of the platform (macOS: osascript, Linux: notify-send),
             else the command when notify_command is set
    macos    osascript
    linux    notify-send (Ubuntu: libnotify-bin)
    command  notify_command, run by sh with HANDOVER_TITLE and HANDOVER_MESSAGE in its
             environment: `curl -d "$HANDOVER_MESSAGE" ntfy.sh/<topic>` reaches a phone
    bell     the terminal bell only

The terminal bell rings in every case. An adapter never raises: a notification that cannot be
shown is lost, the plugin goes on.
"""

import contextlib
import os
import shutil
import subprocess
import sys
from typing import Protocol

TIMEOUT = 5


class Notifier(Protocol):
    def notify(self, title, message):
        """Show the notification; True when it was handed to the system."""


def _run(argv, env=None):
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        return subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False, env=env).returncode == 0
    return False


class MacOS:
    """A macOS notification, through osascript."""

    def notify(self, title, message):
        script = ["on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run"]
        return _run(["osascript", *[a for line in script for a in ("-e", line)], message, title])


class Linux:
    """A freedesktop notification (GNOME, KDE…), through notify-send."""

    def notify(self, title, message):
        return _run(["notify-send", "--app-name=Claude Code", title, message])


class Command:
    """The user's own command, run by sh: the title and the message come in its environment."""

    def __init__(self, command):
        self.command = command

    def notify(self, title, message):
        env = dict(os.environ, HANDOVER_TITLE=title, HANDOVER_MESSAGE=message)
        return _run(["sh", "-c", self.command], env=env)


class Bell:
    """The terminal bell, on the terminal `tty` names (the session's tmux pane, or /dev/tty)."""

    def __init__(self, tty="/dev/tty"):
        self.tty = tty

    def notify(self, title, message):
        with contextlib.suppress(OSError), open(self.tty, "w") as f:
            f.write("\a")
            return True
        return False


class Fanout:
    """Every notifier in turn; True when one of them got through."""

    def __init__(self, *notifiers):
        self.notifiers = notifiers

    def notify(self, title, message):
        # Every adapter runs, even after one got through: no short-circuit.
        results = [n.notify(title, message) for n in self.notifiers]
        return any(results)


def desktop(platform=None, which=shutil.which):
    """The desktop notifier of the platform, or None when it has none at hand."""
    platform = platform or sys.platform
    if platform == "darwin" and which("osascript"):
        return MacOS()
    if platform.startswith("linux") and which("notify-send"):
        return Linux()
    return None


def notifier(choice="auto", command="", tty="/dev/tty", platform=None, which=shutil.which):
    """The notifier for the `notifier` and `notify_command` options; an unknown choice is auto."""
    choice = (choice or "auto").strip().lower()
    command = (command or "").strip()
    picked = None
    if choice == "macos":
        picked = MacOS()
    elif choice == "linux":
        picked = Linux()
    elif choice == "command":
        picked = Command(command) if command else None
    elif choice != "bell":
        picked = desktop(platform, which) or (Command(command) if command else None)
    return Fanout(*([picked] if picked else []), Bell(tty))

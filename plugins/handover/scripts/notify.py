"""How the handover plugin calls the user back to the keyboard: a port and its adapters.

The plugin depends on the port alone, `Notifier.notify(title, message)`; `notifier()` picks
the adapters from the `notifier` option and the environment it runs in (`environment()`):

    auto     the desktop notifier when this is a desktop session with its tool installed
             (macOS: osascript; Linux: notify-send), and the command too when notify_command
             is set
    macos    osascript
    linux    notify-send (Ubuntu: libnotify-bin)
    command  notify_command, run by sh with HANDOVER_TITLE and HANDOVER_MESSAGE in its
             environment: a Slack webhook, ntfy… (docs/notifications.md)
    bell     the terminal bell only

The terminal bell rings in every case. An adapter never raises: a notification that cannot be
shown is lost, the plugin goes on. `describe()` reports what was detected and chosen, with a
hint when the setup cannot reach the user (`handover.py notifier`).
"""

import contextlib
import os
import shutil
import subprocess
import sys
from typing import Protocol

TIMEOUT = 5
CHOICES = ("auto", "macos", "linux", "command", "bell")
DOC = "https://github.com/FunDrivenDev/claude-plugins/blob/main/plugins/handover/docs/notifications.md"
CONFIGURE = "/handover:config, or: claude plugin configure handover@fundrivendev"


class Notifier(Protocol):
    def notify(self, title, message):
        """Show the notification; True when it was handed to the system."""


def _run(argv, env=None):
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        return subprocess.run(argv, capture_output=True, timeout=TIMEOUT, check=False, env=env).returncode == 0
    return False


class MacOS:
    """A macOS notification, through osascript."""

    name = "macos"

    def notify(self, title, message):
        script = ["on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run"]
        return _run(["osascript", *[a for line in script for a in ("-e", line)], message, title])


class Linux:
    """A freedesktop notification (GNOME, KDE…), through notify-send."""

    name = "linux"

    def notify(self, title, message):
        return _run(["notify-send", "--app-name=Claude Code", title, message])


class Command:
    """The user's own command, run by sh: the title and the message come in its environment."""

    name = "command"

    def __init__(self, command):
        self.command = command

    def notify(self, title, message):
        env = dict(os.environ, HANDOVER_TITLE=title, HANDOVER_MESSAGE=message)
        return _run(["sh", "-c", self.command], env=env)


class Bell:
    """The terminal bell, on the terminal `tty` names (the session's tmux pane, or /dev/tty)."""

    name = "bell"

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


def _read(path):
    with contextlib.suppress(OSError), open(path, encoding="utf-8", errors="replace") as f:
        return f.read()
    return ""


def environment(platform=None, environ=None, which=shutil.which, proc_version="/proc/version"):
    """Where the plugin runs, as far as notifications go.

    os is macos, linux, wsl (Linux under Windows, whose notify-send reaches no desktop) or other;
    desktop says whether a desktop notification can reach a screen: always on macOS, and on Linux
    with a display (DISPLAY or WAYLAND_DISPLAY) and a session bus (DBUS_SESSION_BUS_ADDRESS, or
    $XDG_RUNTIME_DIR/bus) to talk to its notification daemon.
    """
    platform = platform or sys.platform
    env = os.environ if environ is None else environ
    ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_TTY"))
    tools = {t: which(t) for t in ("osascript", "notify-send")}
    if platform == "darwin":
        return {"os": "macos", "desktop": True, "ssh": ssh, "why": "macOS", "tools": tools}
    if not platform.startswith("linux"):
        return {
            "os": "other",
            "desktop": False,
            "ssh": ssh,
            "why": f"no desktop notifier on {platform}",
            "tools": tools,
        }
    if "microsoft" in _read(proc_version).lower() or env.get("WSL_DISTRO_NAME"):
        return {
            "os": "wsl",
            "desktop": False,
            "ssh": ssh,
            "why": "WSL: notify-send reaches no Windows desktop",
            "tools": tools,
        }
    display = env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")
    runtime = env.get("XDG_RUNTIME_DIR")
    bus = env.get("DBUS_SESSION_BUS_ADDRESS") or (runtime and os.path.exists(os.path.join(runtime, "bus")))
    if not display:
        why = "over SSH, without a display" if ssh else "no display (DISPLAY, WAYLAND_DISPLAY)"
        return {"os": "linux", "desktop": False, "ssh": ssh, "why": why, "tools": tools}
    if not bus:
        return {
            "os": "linux",
            "desktop": False,
            "ssh": ssh,
            "why": "no session bus (DBUS_SESSION_BUS_ADDRESS)",
            "tools": tools,
        }
    return {"os": "linux", "desktop": True, "ssh": ssh, "why": "a Linux desktop session", "tools": tools}


def desktop(env):
    """The desktop notifier `env` (environment()) can use, or None."""
    if not env["desktop"]:
        return None
    if env["os"] == "macos" and env["tools"]["osascript"]:
        return MacOS()
    if env["os"] == "linux" and env["tools"]["notify-send"]:
        return Linux()
    return None


def _pick(choice, command, env):
    """The adapters for a choice, the bell aside: auto adds the command to the desktop notifier."""
    cmd = [Command(command)] if command else []
    if choice == "macos":
        return [MacOS()]
    if choice == "linux":
        return [Linux()]
    if choice == "command":
        return cmd
    if choice == "bell":
        return []
    found = desktop(env)
    return [*([found] if found else []), *cmd]


def notifier(choice="auto", command="", tty="/dev/tty", env=None):
    """The notifier for the `notifier` and `notify_command` options; an unknown choice is auto."""
    env = env or environment()
    return Fanout(*_pick(_choice(choice), (command or "").strip(), env), Bell(tty))


def _choice(choice):
    choice = (choice or "auto").strip().lower()
    return choice if choice in CHOICES else "auto"


def describe(choice="auto", command="", env=None):
    """What notifier() picks here and why, with a hint when the user may not be reached."""
    env = env or environment()
    asked = (choice or "auto").strip().lower()
    command = (command or "").strip()
    picked = _pick(_choice(asked), command, env)
    hints = []
    if asked not in CHOICES:
        hints.append(f"unknown notifier {asked!r}, auto used: pick one of {', '.join(CHOICES)}")
    if _choice(asked) == "command" and not command:
        hints.append("notifier is command but notify_command is empty: set notify_command")
    if asked == "macos" and env["os"] != "macos":
        hints.append(f"notifier is macos on {env['os']}: osascript is macOS only, set notifier to auto")
    if asked == "linux" and env["os"] != "linux":
        hints.append(f"notifier is linux on {env['os']}: set notifier to auto")
    if asked == "linux" and not env["tools"]["notify-send"]:
        hints.append("notify-send is missing: sudo apt-get install libnotify-bin")
    if _choice(asked) == "auto" and not desktop(env):
        if env["os"] == "linux" and env["desktop"]:
            hints.append("notify-send is missing: sudo apt-get install libnotify-bin")
        elif not command:
            hints.append(f"{env['why']}: only the bell rings; set notify_command (Slack, ntfy…) to be reached")
    if hints:
        hints.append(f"options: {CONFIGURE}; guide: {DOC}")
    return {
        "environment": env,
        "notifier": asked,
        "notify_command_set": bool(command),
        "adapters": [*[n.name for n in picked], "bell"],
        "reaches_you": bool(picked),
        "hints": hints,
    }

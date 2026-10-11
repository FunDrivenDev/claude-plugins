"""Unit tests of the handover plugin's notifier port, its adapters and its environment detection
(scripts/notify.py)."""

import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import notify as N

DESKTOP = {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}


def which(*tools):
    return lambda t: f"/usr/bin/{t}" if t in tools else None


def env(platform="linux", environ=None, tools=("notify-send",), proc=""):
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(proc)
    try:
        return N.environment(platform, DESKTOP if environ is None else environ, which(*tools), f.name)
    finally:
        os.unlink(f.name)


def names(notifier):
    return [n.name for n in notifier.notifiers]


class Environment(unittest.TestCase):
    def test_macos_is_a_desktop(self):
        e = env("darwin", {}, ("osascript",))
        self.assertEqual((e["os"], e["desktop"]), ("macos", True))

    def test_linux_desktop_needs_a_display_and_a_bus(self):
        self.assertTrue(env()["desktop"])
        self.assertTrue(env(environ={"WAYLAND_DISPLAY": "wayland-0", "DBUS_SESSION_BUS_ADDRESS": "x"})["desktop"])
        no_display = env(environ={"DBUS_SESSION_BUS_ADDRESS": "x"})
        self.assertEqual((no_display["desktop"], no_display["why"]), (False, "no display (DISPLAY, WAYLAND_DISPLAY)"))
        self.assertFalse(env(environ={"DISPLAY": ":0"})["desktop"])

    def test_the_bus_is_found_in_the_runtime_dir(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "bus"), "w").close()
            self.assertTrue(env(environ={"DISPLAY": ":0", "XDG_RUNTIME_DIR": d})["desktop"])

    def test_ssh_without_display_is_headless(self):
        e = env(environ={"SSH_CONNECTION": "1 2 3 4"})
        self.assertEqual((e["desktop"], e["ssh"], e["why"]), (False, True, "over SSH, without a display"))

    def test_wsl_is_not_a_desktop(self):
        self.assertEqual(env(proc="Linux version 5.15 microsoft-standard-WSL2")["os"], "wsl")
        self.assertEqual(env(environ={**DESKTOP, "WSL_DISTRO_NAME": "Ubuntu"})["os"], "wsl")
        self.assertFalse(env(proc="microsoft")["desktop"])

    def test_other_platforms(self):
        self.assertEqual(env("win32")["os"], "other")


class Choice(unittest.TestCase):
    def test_auto_picks_the_desktop_of_the_environment(self):
        self.assertEqual(names(N.notifier(env=env("darwin", {}, ("osascript",)))), ["macos", "bell"])
        self.assertEqual(names(N.notifier(env=env())), ["linux", "bell"])

    def test_auto_falls_back_to_the_command_then_the_bell(self):
        headless = env(environ={"SSH_CONNECTION": "x"})
        self.assertEqual(names(N.notifier(command="true", env=headless)), ["command", "bell"])
        self.assertEqual(names(N.notifier(env=headless)), ["bell"])
        self.assertEqual(names(N.notifier(command="true", env=env(tools=()))), ["command", "bell"])
        self.assertEqual(names(N.notifier(command="true", env=env())), ["linux", "command", "bell"])
        self.assertEqual(names(N.notifier(env=env("win32"))), ["bell"])

    def test_explicit_choices(self):
        e = env()
        self.assertEqual(names(N.notifier("macos", env=e)), ["macos", "bell"])
        self.assertEqual(names(N.notifier("Linux ", env=e)), ["linux", "bell"])
        self.assertEqual(names(N.notifier("command", "true", env=e)), ["command", "bell"])
        self.assertEqual(names(N.notifier("command", "", env=e)), ["bell"])
        self.assertEqual(names(N.notifier("bell", "true", env=e)), ["bell"])
        self.assertEqual(names(N.notifier("nope", env=e)), ["linux", "bell"])


class Describe(unittest.TestCase):
    def test_a_desktop_reaches_you_without_hints(self):
        d = N.describe(env=env())
        self.assertEqual((d["adapters"], d["reaches_you"], d["hints"]), (["linux", "bell"], True, []))

    def test_headless_hints_at_notify_command(self):
        d = N.describe(env=env(environ={"SSH_CONNECTION": "x"}))
        self.assertFalse(d["reaches_you"])
        self.assertIn("set notify_command", d["hints"][0])
        self.assertIn("notifications.md", d["hints"][-1])

    def test_headless_with_a_command_reaches_you(self):
        d = N.describe(command="true", env=env(environ={"SSH_CONNECTION": "x"}))
        self.assertEqual((d["adapters"], d["reaches_you"], d["hints"]), (["command", "bell"], True, []))

    def test_a_desktop_without_notify_send_hints_at_the_package(self):
        self.assertIn("libnotify-bin", N.describe(env=env(tools=()))["hints"][0])

    def test_misconfigurations(self):
        self.assertIn("unknown notifier", N.describe("slack", env=env())["hints"][0])
        self.assertIn("notify_command is empty", N.describe("command", env=env())["hints"][0])
        self.assertIn("macOS only", N.describe("macos", env=env())["hints"][0])
        self.assertIn("set notifier to auto", N.describe("linux", env=env("darwin", {}, ("osascript",)))["hints"][0])

    def test_the_command_itself_is_never_reported(self):
        d = N.describe("command", "curl https://hooks.slack.com/services/SECRET", env=env())
        self.assertNotIn("SECRET", repr(d))
        self.assertTrue(d["notify_command_set"])


class Adapters(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = os.path.join(self.dir.name, "out")

    def stub(self, tool):
        """A fake tool on PATH that writes its arguments, one per line, to self.out."""
        path = os.path.join(self.dir.name, tool)
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.out}"\n')
        os.chmod(path, stat.S_IRWXU)
        old = os.environ["PATH"]
        os.environ["PATH"] = self.dir.name + os.pathsep + old
        self.addCleanup(os.environ.__setitem__, "PATH", old)

    def read(self):
        with open(self.out) as f:
            return f.read().splitlines()

    def test_linux_calls_notify_send(self):
        self.stub("notify-send")
        self.assertTrue(N.Linux().notify("T", "it's done; $(x)"))
        self.assertEqual(self.read(), ["--app-name=Claude Code", "T", "it's done; $(x)"])

    def test_macos_passes_title_and_message_as_arguments(self):
        self.stub("osascript")
        self.assertTrue(N.MacOS().notify("T", "M"))
        self.assertEqual(self.read()[-2:], ["M", "T"])

    def test_command_gets_title_and_message_in_its_environment(self):
        cmd = f'printf "%s|%s" "$HANDOVER_TITLE" "$HANDOVER_MESSAGE" > "{self.out}"'
        self.assertTrue(N.Command(cmd).notify("T", "a `b` $(c)"))
        self.assertEqual(self.read(), ["T|a `b` $(c)"])

    def test_bell_writes_to_the_tty(self):
        self.assertTrue(N.Bell(self.out).notify("T", "M"))
        with open(self.out) as f:
            self.assertEqual(f.read(), "\a")

    def test_failures_are_swallowed_and_fanout_tries_every_adapter(self):
        missing = os.path.join(self.dir.name, "no", "tty")
        self.assertTrue(N.Fanout(N.Command("exit 3"), N.Bell(self.out), N.Bell(missing)).notify("T", "M"))
        self.assertFalse(N.Fanout(N.Command("exit 3"), N.Bell(missing)).notify("T", "M"))


if __name__ == "__main__":
    unittest.main()

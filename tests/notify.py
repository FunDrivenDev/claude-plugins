"""Unit tests of the handover plugin's notifier port and adapters (scripts/notify.py)."""

import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import notify as N


def names(notifier):
    return [type(n).__name__ for n in notifier.notifiers]


def which(*tools):
    return lambda t: f"/usr/bin/{t}" if t in tools else None


class Choice(unittest.TestCase):
    def test_auto_picks_the_platform_desktop(self):
        self.assertEqual(names(N.notifier(platform="darwin", which=which("osascript"))), ["MacOS", "Bell"])
        self.assertEqual(names(N.notifier(platform="linux", which=which("notify-send"))), ["Linux", "Bell"])

    def test_auto_falls_back_to_the_command_then_the_bell(self):
        self.assertEqual(names(N.notifier(command="true", platform="linux", which=which())), ["Command", "Bell"])
        self.assertEqual(names(N.notifier(platform="linux", which=which())), ["Bell"])
        self.assertEqual(names(N.notifier(platform="win32", which=which("notify-send"))), ["Bell"])

    def test_explicit_choices(self):
        self.assertEqual(names(N.notifier("macos", which=which())), ["MacOS", "Bell"])
        self.assertEqual(names(N.notifier("Linux ", which=which())), ["Linux", "Bell"])
        self.assertEqual(names(N.notifier("command", "true")), ["Command", "Bell"])
        self.assertEqual(names(N.notifier("command", "")), ["Bell"])
        self.assertEqual(names(N.notifier("bell", "true", platform="darwin", which=which("osascript"))), ["Bell"])

    def test_unknown_choice_is_auto(self):
        self.assertEqual(names(N.notifier("nope", platform="linux", which=which("notify-send"))), ["Linux", "Bell"])


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
        fan = N.Fanout(N.Command("exit 3"), N.Bell(self.out), N.Bell(missing))
        self.assertTrue(fan.notify("T", "M"))
        self.assertFalse(N.Fanout(N.Command("exit 3"), N.Bell(missing)).notify("T", "M"))


if __name__ == "__main__":
    unittest.main()

"""Unit tests of the handover plugin's per-session thresholds (scripts/handover.py): resolved from settings.json and
plugin.json at SessionStart, recorded in the session's state, and kept by that session whatever the settings or
another session do afterwards."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "plugins", "handover", "scripts", "handover.py")
HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, "data")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
for k in [k for k in os.environ if k.startswith("CLAUDE_PLUGIN_OPTION_") or k == "CLAUDE_CONFIG_DIR"]:
    del os.environ[k]
sys.path.insert(0, os.path.dirname(SCRIPT))

import handover as H

PLUGIN = H.plugin_json()
DEFAULTS = {k: v["default"] for k, v in PLUGIN["userConfig"].items()}


def configure(**options):
    """The options as /handover:config saves them in settings.json."""
    path = os.path.join(HOME, ".claude", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"pluginConfigs": {H.plugin_id(): {"options": options}}} if options else {}, f)


def start(sid, **env):
    """A SessionStart hook run, as Claude Code starts it: options in the environment when it passes them."""
    subprocess.run(
        [sys.executable, SCRIPT, "hook"],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": sid, "cwd": HOME}),
        env={**os.environ, **{f"CLAUDE_PLUGIN_OPTION_{k.upper()}": str(v) for k, v in env.items()}},
        capture_output=True,
        text=True,
        check=True,
    )
    return H.read_json(H.state_path(sid), {})


def statusline(sid, tokens):
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = (
        io.StringIO(json.dumps({"session_id": sid, "context_window": {"total_input_tokens": tokens}})),
        io.StringIO(),
    )
    try:
        H.cmd_statusline(None)
        return sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = stdin, stdout


class Resolution(unittest.TestCase):
    def setUp(self):
        configure()

    def test_without_settings_the_plugin_json_defaults_apply(self):
        cfg = H.config()
        self.assertEqual(cfg["suggest"], DEFAULTS["suggest_tokens"])
        self.assertEqual(cfg["trigger"], DEFAULTS["trigger_tokens"])
        self.assertEqual(cfg["writer_model"], DEFAULTS["writer_model"])
        self.assertIs(cfg["delegate"], DEFAULTS["delegate"])

    def test_settings_override_the_defaults_typed_or_not(self):
        configure(suggest_tokens=150000, trigger_tokens="180000", delegate=False)
        cfg = H.config()
        self.assertEqual((cfg["suggest"], cfg["trigger"], cfg["delegate"]), (150_000, 180_000, False))

    def test_the_hook_environment_comes_first(self):
        configure(trigger_tokens=180000)
        os.environ["CLAUDE_PLUGIN_OPTION_TRIGGER_TOKENS"] = "300000"
        try:
            self.assertEqual(H.config()["trigger"], 300_000)
        finally:
            del os.environ["CLAUDE_PLUGIN_OPTION_TRIGGER_TOKENS"]


class PerSession(unittest.TestCase):
    def setUp(self):
        configure()

    def test_session_start_records_the_thresholds_and_the_plugin_version(self):
        st = start("a")
        self.assertEqual(
            st["thresholds"],
            {"suggest_tokens": 200_000, "trigger_tokens": 250_000, "warn_at_tokens": 225_000},
        )
        self.assertEqual(st["plugin_version"], PLUGIN["version"])

    def test_a_settings_change_waits_for_the_next_session(self):
        start("old")
        configure(suggest_tokens=100000, trigger_tokens=120000)
        cfg = H.session_config("old")
        self.assertEqual((cfg["suggest"], cfg["trigger"]), (200_000, 250_000))
        self.assertEqual(start("new")["thresholds"]["trigger_tokens"], 120_000)
        self.assertEqual(H.read_json(H.state_path("old"))["thresholds"]["trigger_tokens"], 250_000)

    def test_two_sessions_never_move_each_others_thresholds(self):
        start("x", suggest_tokens=100000, trigger_tokens=120000)
        start("y", suggest_tokens=300000, trigger_tokens=400000)
        self.assertEqual(H.session_config("x")["trigger"], 120_000)
        self.assertEqual(H.session_config("y")["trigger"], 400_000)
        self.assertIn("will trigger at 120k", statusline("x", 50_000))
        self.assertIn("will trigger at 400k", statusline("y", 50_000))

    def test_a_session_that_recorded_none_resolves_them_now(self):
        configure(trigger_tokens=180000)
        self.assertEqual(H.session_config("unknown")["trigger"], 180_000)

    def test_the_start_record_alone_does_not_wake_the_activity_hooks(self):
        start("idle")
        self.assertFalse(H.tracked("idle"))
        with H.locked_state("idle") as st:
            st["transcript"] = "/t"
        self.assertTrue(H.tracked("idle"))

    def test_no_shared_options_file_is_written(self):
        start("z")
        self.assertFalse(os.path.exists(os.path.join(DATA, "options.json")))


if __name__ == "__main__":
    unittest.main()

"""Unit tests of the handover plugin's YOLO guard (guard_hit in scripts/handover.py): a YOLO run may run the
plugin's own handover commands, and nothing else that names the plugin, its data or the settings that load it."""

import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

SCRIPT = os.path.join(H.plugin_root(), "scripts", "handover.py")
CALL = f'python3 {SCRIPT} --data-dir "{DATA}"'


def hit(command, tool="Bash"):
    key = "command" if tool == "Bash" else "file_path"
    return H.guard_hit({"tool_name": tool, "tool_input": {key: command}, "cwd": HOME})


class OwnCommands(unittest.TestCase):
    def test_the_handover_skill_may_request_a_handover(self):
        self.assertIsNone(hit(f"{CALL} request --cause model --session abc --reason 'context past 150K'"))

    def test_the_trigger_and_relay_requests_and_the_read_only_commands_pass(self):
        for args in ("request --cause user --session abc", "request --relay --cause user --session abc", "status"):
            self.assertIsNone(hit(f"{CALL} {args}"), args)
        self.assertIsNone(hit(f"{CALL} stats --json"))

    def test_commands_that_change_the_run_or_the_options_stay_denied(self):
        for args in ('config --set \'{"yolo_guard_paths": ""}\'', "afk --off --session abc", "hook", "write"):
            self.assertIsNotNone(hit(f"{CALL} {args}"), args)

    def test_anything_chained_to_an_own_command_stays_denied(self):
        for tail in (f"; rm -rf {DATA}", f"&& rm -rf {DATA}", f"> {SCRIPT}", f"| tee {SCRIPT}", "$(touch x)", "`x`"):
            self.assertIsNotNone(hit(f"{CALL} status {tail}"), tail)

    def test_a_dollar_or_a_line_break_is_denied_even_in_quotes(self):
        for reason in ("'costs $5'", "'a\nb'", '"$(touch x)"', "'`x`'"):
            self.assertIsNotNone(hit(f"{CALL} request --cause model --session abc --reason {reason}"), reason)

    def test_a_denied_own_command_is_named_for_the_refusal(self):
        # As an AFK run once sent it: the appended `echo rc=$?` made the guard deny the handover request.
        command = f"{CALL} request --cause model --session abc --reason 'done'; echo rc=$?"
        self.assertIsNotNone(hit(command))
        self.assertEqual(H.own_call_attempt(command), "request")
        self.assertIsNone(H.own_call_attempt(f"rm -rf {DATA}"))

    def test_another_script_under_the_plugin_stays_denied(self):
        other = os.path.join(H.plugin_root(), "scripts", "notify.py")
        self.assertIsNotNone(hit(f"python3 {other} request --session abc"))


class Guard(unittest.TestCase):
    def test_writing_the_plugin_or_its_data_is_denied(self):
        self.assertIsNotNone(hit(f"rm -rf {DATA}"))
        self.assertIsNotNone(hit("echo x >> ~/.claude/settings.json"))
        self.assertIsNotNone(hit(SCRIPT, tool="Edit"))
        self.assertIsNotNone(hit("claude plugin disable handover"))

    def test_reading_stays_free(self):
        self.assertIsNone(hit(SCRIPT, tool="Read"))


if __name__ == "__main__":
    unittest.main()

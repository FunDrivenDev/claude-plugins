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


def installed(*parts):
    path = os.path.join(HOME, ".claude", "plugins", *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n")
    return path


TOOLKIT = os.path.join("cache", "guest-suite", "gs-dev-toolkit", "4.49.1", "scripts")
PROOF = installed(TOOLKIT, "gs-review-proof.sh")
QGATE = installed(TOOLKIT, "qgate.sh")
CLONED = installed("marketplaces", "guest-suite", "plugins", "gs-dev-toolkit", "scripts", "qgate.sh")
OWN_INSTALLED = installed("cache", "fundrivendev", "handover", "0.20.0", "scripts", "handover.py")
IN_DATA = installed("data", "gs-dev-toolkit-guest-suite", "tool.sh")


class InstalledScripts(unittest.TestCase):
    def test_a_review_record_with_dollars_and_line_breaks_in_single_quotes_passes(self):
        record = '\'{"verdict": "validé",\n "note": "costs $5, `x` and $(y) stay text"}\''
        self.assertIsNone(hit(f"bash {PROOF} write --record {record} --head 55e9b8f"))

    def test_an_installed_script_runs_directly_or_through_an_interpreter(self):
        tilde = "~" + QGATE[len(HOME) :]
        for command in (f"{QGATE} --json", f"sh {QGATE}", f"bash {tilde} run", f"bash {CLONED}", f'"{QGATE}" -q'):
            self.assertIsNone(hit(command), command)

    def test_anything_chained_redirected_or_expanded_stays_denied(self):
        for tail in (
            "; rm -rf ~/.claude/plugins",
            "&& touch x",
            "| tee x",
            "> x",
            "--out $HOME/x",
            '--out "$HOME"',
            "`x`",
            "\nrm x",
            "~/.claude/plug*",
            "{a,b}",
        ):
            self.assertIsNotNone(hit(f"bash {QGATE} {tail}"), tail)

    def test_a_guarded_path_among_the_arguments_stays_denied(self):
        for arg in (DATA, "~/.claude/settings.json", "'~/.claude/'plugins", QGATE):
            self.assertIsNotNone(hit(f"bash {QGATE} --out {arg}"), arg)

    def test_a_shell_wrapper_or_an_interpreter_flag_stays_denied(self):
        for command in (f"bash -c {QGATE}", f"bash -c '{QGATE}'", f"eval {QGATE}", f"env {QGATE}", f"X=1 {QGATE}"):
            self.assertIsNotNone(hit(command), command)

    def test_a_copy_or_a_move_into_the_plugins_stays_denied(self):
        self.assertIsNotNone(hit(f"cp x {QGATE}"))
        self.assertIsNotNone(hit(f"mv {QGATE} x"))

    def test_this_plugins_own_scripts_and_scripts_outside_cache_and_marketplaces_stay_denied(self):
        for script in (OWN_INSTALLED, IN_DATA, os.path.join(H.plugin_root(), "scripts", "notify.py")):
            self.assertIsNotNone(hit(f"python3 {script} config --set x"), script)


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

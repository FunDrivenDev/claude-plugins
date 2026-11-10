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

    def test_a_plain_perl_call_of_an_installed_script_passes(self):
        # As gs-dev-toolkit's review workflow sent it 278 times on 2026-11-09 and 10, refused for want of perl.
        select = installed(TOOLKIT, "doc-select.pl")
        self.assertIsNone(hit(f"perl '{select}' --stack php --diff-files 'src/a.php,src/b.php'"))
        self.assertIsNotNone(hit(f"perl -e 'unlink q({select})'"))

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
        for tool in ("Read", "Glob", "Grep"):
            self.assertIsNone(hit(INDEX, tool=tool), tool)

    def test_a_structured_result_naming_a_plugin_script_passes(self):
        # A workflow agent's result once quoted the qgate launch it ran, and was refused 57 times.
        out = {"tool_name": "StructuredOutput", "tool_input": {"command": f"bash {QGATE} launch --slug s"}}
        self.assertIsNone(H.guard_hit({**out, "cwd": HOME}))


KNOWLEDGE = os.path.join(HOME, ".claude", "plugins", "cache", "guest-suite", "gs-dev-toolkit", "4.61.0", "knowledge")


class ReadOnlyBash(unittest.TestCase):
    def test_a_bash_command_that_only_reads_other_plugins_files_passes(self):
        # The review workflow's knowledge listing, refused 502 times (agent-a711db52bd4bf16b6, 2026-11-09).
        listing = (
            f'W=/r/bim-4375; K={KNOWLEDGE}; echo "== knowledge"; '
            f'find "$K" -name \'*.md\' 2>/dev/null | sed "s|^$K/||"; '
            'echo "== composer"; jq -r \'(.require // {}) | keys[]\' "$W/composer.json" 2>/dev/null || echo ABSENT'
        )
        for command in (
            listing,
            f"ls -la {KNOWLEDGE} && head -40 {KNOWLEDGE}/php.md",
            f'for f in {KNOWLEDGE}/*.md; do\n  wc -l "$f"\ndone',
            f"sed -n '1,60p' {INDEX}",
            "grep -rn 'qgate' $HOME/.claude/plugins/cache 2>&1 | head -5",
        ):
            self.assertIsNone(hit(command), command)

    def test_a_command_that_writes_runs_or_hides_what_it_runs_stays_denied(self):
        for command in (
            f"find {KNOWLEDGE} -name '*.md' -delete",
            f"X=-delete; find {KNOWLEDGE} $X",
            f"find {KNOWLEDGE} $X",
            f"sed -i '' 's/a/b/' {INDEX}",
            f"sed -n 's/a/b/w {INDEX}' /tmp/x",
            f"cat /tmp/x > {INDEX}",
            f"cat {INDEX} | tee {INDEX}.bak",
            f"ls {KNOWLEDGE}; rm -rf {KNOWLEDGE}",
            f"cat $(ls {KNOWLEDGE})",
            f"cat {INDEX} &",
            f"tail -f {INDEX}",
            f"sort -o {INDEX} {INDEX}",
            f"$CMD {INDEX}",
            f"cat <<EOF > {INDEX}\nx\nEOF",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_what_bash_reads_otherwise_than_the_parse_stays_denied(self):
        # The bypasses a review of claude-plugins#80 ran: each one wrote or ran something under bash.
        for command in (
            f"ls {KNOWLEDGE}#; touch ~/PWN1",
            f"X='-name n -delete'; find {KNOWLEDGE} $X",
            f"X=-delete; X=a true; find {KNOWLEDGE} $X",
            f"X=a; for X in -delete; do find {KNOWLEDGE} $X; done",
            f"X=a; printf -v X %s -delete; find {KNOWLEDGE} $X",
            f"echo -delete; find {KNOWLEDGE} $_",
            f"find {KNOWLEDGE} ${{X:=-delete}}",
            f"find {KNOWLEDGE} $'-delete'",
            f'sed -n "1w {INDEX}" /dev/null',
            f"sed -n '$w {INDEX}' /dev/null",
            f"sed -n '/x/w {INDEX}' /dev/null",
            f"sed -n --expression='1w {INDEX}' /dev/null",
            f"sed -n -f /tmp/script {INDEX}",
            f"sed --in {INDEX}",
            f"git -C /r log -1 --output={INDEX}",
            f"git -C /r log -1 --out={INDEX}",
            f"find {KNOWLEDGE} -de\\\nlete",
            f"sort --o={INDEX} {INDEX}",
            f"sort --compress-program=sh {INDEX}",
            f"file -C -m {INDEX}",
            f"tail --fo {INDEX}",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_reading_this_plugin_its_data_or_the_settings_by_bash_stays_denied(self):
        for command in (
            f"cat {SCRIPT}",
            f"ls {DATA}",
            "cat ~/.claude/settings.json",
            f"cat {INDEX} {DATA}/audit.jsonl",
        ):
            self.assertIsNotNone(hit(command), command)


INDEX = os.path.join(HOME, ".claude", "plugins", "cache", "x", "y", "index.json")


def reason(command, tool="Bash"):
    key = "command" if tool == "Bash" else "file_path"
    inp = {"tool_name": tool, "tool_input": {key: command}, "cwd": HOME}
    found = H.guard_hit(inp)
    return found and H.guard_reason(inp, found)


class Refusal(unittest.TestCase):
    def test_a_bash_read_of_another_plugins_file_is_pointed_to_the_reading_tools(self):
        # As a gs-knowledge-loading run once sent it: refused with "do the work another way", the agent gave up.
        for command in (
            "jq '.routes' ~/.claude/plugins/cache/x/y/index.json | python3 -m json.tool",
            f"ls {os.path.dirname(INDEX)} > /tmp/listing",
        ):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertIn("use the Read, Glob or Grep tool", got, command)
            self.assertIn("Writes stay refused", got, command)

    def test_a_call_of_an_installed_script_that_is_not_plain_is_told_how_to_run_it(self):
        # As a review launcher once sent it: the refusal named only the reading tools, so the script looked off limits.
        script = "~/.claude/plugins/cache/x/y/scripts/qgate.sh"
        for command in (f"bash {script} state-check --repo /r; echo done", f'bash {script} state-check --repo "$PWD"'):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertIn("one plain call", got, command)
            self.assertIn("use the Read, Glob or Grep tool", got, command)

    def test_the_plugins_own_files_its_audit_log_and_the_settings_keep_the_plain_refusal(self):
        audit = os.path.join(DATA, "audit.jsonl")
        for command in (
            f"cat {audit}",
            "jq . ~/.claude/settings.json",
            f"grep x {SCRIPT}",
            "ls ~/.claude/hooks",
            f"jq . {INDEX} {audit}",
            f"cat {INDEX}; claude plugin disable handover",
        ):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertNotIn("Read, Glob or Grep", got, command)
            self.assertIn("must leave", got, command)

    def test_an_edit_of_another_plugins_file_keeps_the_plain_refusal(self):
        got = reason(INDEX, tool="Edit")
        self.assertIsNotNone(got)
        self.assertNotIn("Read, Glob or Grep", got)

    def test_a_denied_own_command_keeps_its_own_refusal(self):
        got = reason(f"{CALL} request --cause model --session abc --reason 'done'; echo rc=$?")
        self.assertTrue(got.startswith("Denied: in this YOLO run, the plugin's own `request`"), got)


if __name__ == "__main__":
    unittest.main()

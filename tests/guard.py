"""Unit tests of the handover plugin's YOLO guard (guard_hit in scripts/handover.py): a YOLO run may run the
plugin's own handover commands, and nothing else that names the plugin (any installed copy), its data or the
settings that load it; other plugins' files are not guarded."""

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

    def test_the_hook_daemon_and_its_client_stay_denied(self):
        client = os.path.join(H.plugin_root(), "scripts", "hookd-client")
        self.assertIsNotNone(hit(f"{CALL} hookd"))
        self.assertIsNotNone(hit(f"sh {client}"))
        self.assertIsNotNone(hit(f"curl --unix-socket {DATA}/hookd-0.36.0.sock http://hookd/hook"))


def installed(*parts, body="#!/bin/sh\n"):
    path = os.path.join(HOME, ".claude", "plugins", *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    return path


TOOLKIT = os.path.join("cache", "guest-suite", "gs-dev-toolkit", "4.73.1", "scripts")
PROOF = installed(TOOLKIT, "gs-review-proof.sh")
QGATE = installed(TOOLKIT, "qgate.sh")
CLONED = installed("marketplaces", "guest-suite", "plugins", "gs-dev-toolkit", "scripts", "qgate.sh")
OWN_INSTALLED = installed("cache", "fundrivendev", "handover", "0.20.0", "scripts", "handover.py")
OWN_CLONED = installed("marketplaces", "fundrivendev", "plugins", "handover", "scripts", "handover.py")
NEIGHBOUR = installed("marketplaces", "fundrivendev", "plugins", "delegation", "scripts", "measure.py")
CATALOG = installed(
    "marketplaces",
    "fundrivendev",
    ".claude-plugin",
    "marketplace.json",
    body='{"plugins": [{"name": "delegation", "source": "./plugins/delegation"}, '
    '{"name": "handover", "source": "./plugins/handover"}]}',
)
IN_DATA = installed("data", "gs-dev-toolkit-guest-suite", "tool.sh")
INSTALLED_JSON = installed("installed_plugins.json", body="{}")
INDEX = os.path.join(HOME, ".claude", "plugins", "cache", "x", "y", "index.json")


class OtherPlugins(unittest.TestCase):
    """The guard protects the handover plugin alone: another plugin's files are free, chained or not."""

    def test_a_chained_call_of_another_plugins_script_passes(self):
        # As gs-dev-toolkit's review skills send it: 511 refusals in 83 sessions on the work laptop (D-W3Z1).
        command = (
            "Q=~/.claude/plugins/cache/guest-suite/gs-dev-toolkit/4.73.1/scripts/qgate.sh; "
            "ls $Q && $Q launch --slug x --repo /tmp/r -- just check"
        )
        self.assertIsNone(hit(command))

    def test_another_plugins_scripts_pass_however_they_are_called(self):
        record = '\'{"verdict": "validé",\n "note": "costs $5, `x` and $(y) stay text"}\''
        tilde = "~" + QGATE[len(HOME) :]
        for command in (
            f"bash {PROOF} write --record {record} --head 55e9b8f",
            f"{QGATE} --json",
            f"bash {tilde} run; echo rc=$?",
            f'bash {QGATE} state-check --repo "$PWD" | tail -5',
            f"bash -c '{CLONED}'",
            f"python3 {NEIGHBOUR} snapshot",
            f"python3 {IN_DATA}",
        ):
            self.assertIsNone(hit(command), command)

    def test_reading_or_writing_another_plugins_files_passes(self):
        for command in (
            "jq '.routes' ~/.claude/plugins/cache/x/y/index.json",
            f"ls {os.path.dirname(INDEX)}",
            f"cp x {QGATE}",
            f"rm -rf {os.path.dirname(QGATE)}",
            "ls $HOME/.claude/plugins/marketplaces/fundrivendev/plugins/delegation",
        ):
            self.assertIsNone(hit(command), command)
        self.assertIsNone(hit(INDEX, tool="Edit"))
        self.assertIsNone(hit(NEIGHBOUR, tool="Write"))

    def test_another_plugins_script_naming_a_guarded_path_stays_denied(self):
        for arg in (DATA, "~/.claude/settings.json", OWN_INSTALLED, "'~/.claude/'plugins"):
            self.assertIsNotNone(hit(f"bash {QGATE} --out {arg}"), arg)


class HandoverCopies(unittest.TestCase):
    """Every copy of the handover plugin Claude Code may load stays guarded: cache, marketplace, catalog."""

    def test_writing_an_installed_copy_of_the_plugin_is_denied(self):
        for command in (
            f"python3 {OWN_INSTALLED} config --set x",
            f"echo x >> {OWN_CLONED}",
            "rm -rf ~/.claude/plugins/cache/fundrivendev/handover",
            "sed -i '' s/a/b/ $HOME/.claude/plugins/marketplaces/fundrivendev/plugins/handover/hooks/hooks.json",
        ):
            self.assertIsNotNone(hit(command), command)
        for path in (OWN_INSTALLED, OWN_CLONED, CATALOG, INSTALLED_JSON):
            self.assertIsNotNone(hit(path, tool="Edit"), path)

    def test_the_settings_that_load_the_plugin_are_denied(self):
        for command in (
            f"jq . {CATALOG}",
            "echo {} > ~/.claude/plugins/installed_plugins.json",
            "rm ~/.claude/plugins/known_marketplaces.json",
            "echo x >> ~/.claude/settings.json",
            "ls ~/.claude/hooks",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_a_folder_that_holds_the_plugin_named_whole_or_through_a_glob_is_denied(self):
        for command in (
            "rm -rf ~/.claude",
            "rm -rf ~/.claude/plugins",
            "rm -rf ~/.claude/plugins/",
            "mv ~/.claude/plugins/cache/fundrivendev /tmp/x",
            "rm -rf ~/.claude/plugins/cache/*/handover",
            "rm -rf ~/.claude/plugins/cache/fundrivendev/hand*",
            "rm -rf ~/.claude/plugins/cache/guest-suite/../fundrivendev/handover",
            "rm -rf '~/.claude/'plugins",
            'rm -rf "$HOME/.claude/plugins"',
            "cd ~/.claude/plugins/data && rm -rf handover-fundrivendev",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_a_relative_path_from_another_plugins_folder_is_denied(self):
        # Review finding: a cd by a literal path into a sibling, then a relative path to the plugin.
        for command in (
            "cd ~/.claude/plugins/cache/guest-suite && rm -rf ../fundrivendev",
            "cd ~/.claude/plugins/marketplaces/fundrivendev/plugins/delegation && rm -rf ../handover",
            "cd ~/.claude/plugins/cache/guest-suite/gs-dev-toolkit; cd ../../fundrivendev; rm -rf handover",
            "cd ~/.claude/plugins && rm -rf cache/fundrivendev",
        ):
            self.assertIsNotNone(hit(command), command)
        inp = {"tool_name": "Bash", "tool_input": {"command": "rm -rf ../fundrivendev"}}
        inp["cwd"] = os.path.join(HOME, ".claude", "plugins", "cache", "guest-suite")
        self.assertIsNotNone(H.guard_hit(inp))

    def test_an_expansion_or_a_cut_path_after_a_cd_there_is_denied(self):
        for command in (
            'cd ~/.claude/plugins/cache/guest-suite && rm -rf "$(dirname $PWD)/fundrivendev"',
            "D=~/.claude/plugins/ca; rm -rf ${D}che/fundrivendev",
            "echo x > ~/.claude/plugins/marketplaces/fundrivendev/.git/config",
            "git -C ~/.claude/plugins/marketplaces/fundrivendev/.git config remote.origin.url https://x",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_other_ways_to_work_from_another_plugins_folder_are_denied(self):
        # Third review: a cd with options or inside a block, git -C, find -execdir, and folded case.
        for command in (
            "cd -P ~/.claude/plugins/cache/guest-suite && rm -rf ../fundrivendev",
            "cd -- ~/.claude/plugins/cache/guest-suite && rm -rf ../fundrivendev",
            "true\ncd ~/.claude/plugins/cache/guest-suite\nrm -rf ../fundrivendev",
            "{ cd ~/.claude/plugins/cache/guest-suite; rm -rf ../fundrivendev; }",
            "if true; then cd ~/.claude/plugins/cache/guest-suite; rm -rf ../fundrivendev; fi",
            "git -C ~/.claude/plugins/cache/guest-suite rm -rf ../fundrivendev",
            "find ~/.claude/plugins/cache/guest-suite -maxdepth 0 -execdir rm -rf fundrivendev ;",
            "rm -rf ~/.claude/plugins/cache/FundrivenDev",
            "rm -rf ~/.claude/plugins/cache/fundrivendev/Handover",
            "rm -rf ~/.CLAUDE/plugins",
            f"find {QGATE} -execdir rm -rf ../../../../fundrivendev/handover +",
            f"find {QGATE} -execdir rm -rf ../../../.. ;",
            f"find {QGATE} -exec sh -c 'cd .. && rm -rf x' ;",
            f'find {QGATE} -execdir rm -rf ..""/..""/..""/..""/fundrivendev/handover ;',
            'cd ~/.claude/plugins/cache/guest-suite && rm -rf ..""/fundrivendev/handover',
            "cd ~/.claude/plugins/cache/guest-suite && rm -rf .\\./fundrivendev/handover",
            "cd ~/.claude/plugins/marketplaces/guest-suite && rm -rf ..''/fundrivendev/.git",
            f"find -L {QGATE} -execdir rm -rf ../../../../fundriven* ;",
            f"find -L {QGATE} -execdir rm -rf ../../../../fundriven[d]ev ;",
            f"{QGATE} x; rm -rf ../../../fundriven{{dev,}}",
            f"find -L {QGATE} -execdir sh -c 'cd ../../../.. && rm -rf fundrivendev' ;",
            f"cd $(/usr/bin/dirname {QGATE}) && rm -rf ../../../../fundriven*",
            "cd $(dirname $(dirname $(dirname $(dirname ~/.claude/plugins/cache/guest-suite/gs-dev-toolkit/4.73.1/scripts/qgate.sh)))) && rm -rf fundrivendev",
        ):
            self.assertIsNotNone(hit(command), command)

    def test_relative_words_beside_another_plugins_script_pass(self):
        # Second review: words such as `..`, `handover` or `data` are a script's arguments, not a path from there.
        q = "~/.claude/plugins/cache/guest-suite/gs-dev-toolkit/4.73.1/scripts/qgate.sh"
        for command in (
            f"{q} launch --slug x --repo ../r -- just check",
            f"{q} launch --slug handover --repo /tmp/r",
            f"{q} launch --repo . && git diff -- plugins/handover/scripts/handover.py",
            f"{q} launch -- just check && ls data",
            f"bash {PROOF} write --head abc --repo ..",
            f'cd "$REPO" && {q} launch --slug x --repo .',
            f'Q={q}; cd $WT && $Q launch --slug x --repo "$WT"',
            f"{q} launch --slug x --repo /tmp/r; printf 'rc=%s\\n' \"$?\"",
            f"Q={q}; $Q launch --slug x --repo /tmp/r && date +%H:%M",
            f'{q} launch --slug "run-$(date +%s)" --repo /tmp/r',
            f"{q} launch --slug dirname-check --repo /tmp/r",
            f"Q={q}; $Q launch --slug x --repo /tmp/r -- just check && git -C /tmp/r status",
            f"Q={q}; $Q launch --repo /tmp/r | grep -C 3 FAIL; ls -C /tmp/r; make -C /tmp/r test",
            f"Q={q}; $Q launch --repo /tmp/r; find /tmp/r -name '*.log' -exec cat {{}} ;; s=${{name%-dev}}",
            f"{q} launch --repo ../data && {q} launch --repo ../cache --base /tmp/data/../r",
            f"{q} launch --repo /tmp/r -- git diff HEAD~1 -- '../src/*.ts'",
            f"cd /tmp/r && ls ../*/x; cp ../*.md /tmp/out && {q} launch --repo /tmp/r -- rg -g '../*.ts' foo",
            f"find /tmp/r -name '*.tmp' -exec rm {{}} +; echo rc=$?; {q} launch --slug x --repo /tmp/r -- just check",
            f"find /tmp/r -exec sh -c 'echo $1' _ {{}} \\; ; Q={q}; $Q launch --repo /tmp/r",
        ):
            inp = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp/proj"}
            self.assertIsNone(H.guard_hit(inp), command)

    def test_a_marketplace_plugin_root_is_followed(self):
        root = installed("marketplaces", "pr", "plugins", "handover", "hooks", "hooks.json", body="{}")
        installed(
            "marketplaces",
            "pr",
            ".claude-plugin",
            "marketplace.json",
            body='{"metadata": {"pluginRoot": "./plugins"}, "plugins": [{"name": "handover", "source": "handover"}]}',
        )
        self.assertIsNotNone(hit(root, tool="Edit"))
        self.assertIsNotNone(hit("rm -rf ~/.claude/plugins/marketplaces/pr/plugins/handover"))

    def test_the_other_plugins_of_the_same_marketplace_are_free(self):
        self.assertIsNone(hit(f"rm -rf {os.path.dirname(os.path.dirname(NEIGHBOUR))}"))
        self.assertIsNone(hit("ls ~/.claude/plugins/cache/fundrivendev/delegation"))

    def test_the_yolo_settings_deny_edits_of_the_plugin_alone(self):
        rules = " ".join(f"//{p.lstrip('/')}" for p in H.guarded_paths(HOME))
        for path in (OWN_CLONED, CATALOG, INSTALLED_JSON, DATA):
            self.assertTrue(any(path.startswith("/" + r.lstrip("/")) for r in rules.split()), path)
        self.assertNotIn("gs-dev-toolkit", rules)
        self.assertNotIn(os.path.join(HOME, ".claude", "plugins") + " ", rules + " ")


class Guard(unittest.TestCase):
    def test_writing_the_plugin_or_its_data_is_denied(self):
        self.assertIsNotNone(hit(f"rm -rf {DATA}"))
        self.assertIsNotNone(hit(SCRIPT, tool="Edit"))
        self.assertIsNotNone(hit("claude plugin disable handover"))

    def test_reading_stays_free(self):
        self.assertIsNone(hit(SCRIPT, tool="Read"))
        for tool in ("Read", "Glob", "Grep"):
            self.assertIsNone(hit(OWN_INSTALLED, tool=tool), tool)

    def test_structured_output_is_never_matched(self):
        # 11 refusals (D-W3Z1): the tool returns a subagent's answer and acts on nothing.
        inp = {
            "tool_name": "StructuredOutput",
            "tool_input": {"command": f"rm -rf {DATA}", "path": OWN_INSTALLED, "summary": "claude plugin disable"},
            "cwd": HOME,
        }
        self.assertIsNone(H.guard_hit(inp))


def reason(command, tool="Bash"):
    key = "command" if tool == "Bash" else "file_path"
    inp = {"tool_name": tool, "tool_input": {key: command}, "cwd": HOME}
    found = H.guard_hit(inp)
    return found and H.guard_reason(inp, found)


class Refusal(unittest.TestCase):
    def test_a_bash_read_of_the_plugins_installed_copy_is_pointed_to_the_reading_tools(self):
        # As a gs-knowledge-loading run once sent it: refused with "do the work another way", the agent gave up.
        for command in (f"cat {OWN_INSTALLED}", "ls ~/.claude/plugins/cache", "ls ~/.claude/plugins/cache/*/"):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertIn("use the Read, Glob or Grep tool", got, command)
            self.assertIn("another plugin's files", got, command)
            self.assertIn("Writes stay refused", got, command)

    def test_the_plugins_data_its_audit_log_and_the_settings_keep_the_plain_refusal(self):
        audit = os.path.join(DATA, "audit.jsonl")
        for command in (
            f"cat {audit}",
            "jq . ~/.claude/settings.json",
            "ls ~/.claude/hooks",
            f"jq . {INDEX} {audit}",
            f"cat {OWN_INSTALLED}; claude plugin disable handover",
            "rm -rf ~/.claude",
        ):
            got = reason(command)
            self.assertIsNotNone(got, command)
            self.assertNotIn("Read, Glob or Grep", got, command)
            self.assertIn("must leave", got, command)
            self.assertIn("other plugins' files are not guarded", got, command)

    def test_an_edit_of_the_plugin_keeps_the_plain_refusal(self):
        got = reason(OWN_INSTALLED, tool="Edit")
        self.assertIsNotNone(got)
        self.assertNotIn("Read, Glob or Grep", got)

    def test_a_denied_own_command_keeps_its_own_refusal(self):
        got = reason(f"{CALL} request --cause model --session abc --reason 'done'; echo rc=$?")
        self.assertTrue(got.startswith("Denied: in this YOLO run, the plugin's own `request`"), got)


if __name__ == "__main__":
    unittest.main()

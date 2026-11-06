"""Tests of the delegation plugin's guard-agent-type hook (plugins/delegation/scripts/guard_agent_type.py), run as
Claude Code runs it: the hook input on stdin, the options in the environment or settings.json, a temp config and data
folder. Modes off, log and block; the override variable; the would-block events measure reads (M9)."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "delegation"
HOOK = PLUGIN / "scripts" / "guard_agent_type.py"
sys.path.insert(0, str(HOOK.parent))

import measure as M

# The hook runs as `python3`, which on macOS can be the system one (3.9): run it there when it exists.
SYSTEM_PYTHON = pathlib.Path("/usr/bin/python3")
HOOK_PYTHON = str(SYSTEM_PYTHON) if SYSTEM_PYTHON.exists() else sys.executable


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.data = self.tmp / "data" / "delegation-market"
        self.config = self.tmp / "config"
        self.config.mkdir()
        self.transcript = self.tmp / "t.jsonl"
        self.transcript.write_text("")
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CLAUDE_", "HANDOVER_", "DELEGATION_")) and k != "HOME"
        }
        self.env.update(HOME=str(self.tmp), CLAUDE_CONFIG_DIR=str(self.config), CLAUDE_PLUGIN_DATA=str(self.data))

    def run_hook(self, agent_type=None, tool="Agent", **env):
        tool_input = {"prompt": "p", "description": "d"}
        if agent_type is not None:
            tool_input["subagent_type"] = agent_type
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "transcript_path": str(self.transcript),
            "session_id": "s-1",
        }
        r = subprocess.run(
            [HOOK_PYTHON, "-B", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**self.env, **env},
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def events(self):
        log = self.data / "guard-agent-type.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def denied(self, out):
        return out is not None and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_off_by_default_lets_everything_through_and_logs_nothing(self):
        for t in (None, "general-purpose", "claude", "fork", "Explore"):
            self.assertIsNone(self.run_hook(t))
        self.assertEqual(self.events(), [])

    def test_block_refuses_each_catch_all_type_and_names_the_roles(self):
        for t in (None, "", "general-purpose", "claude", "fork"):
            out = self.run_hook(t, CLAUDE_PLUGIN_OPTION_GUARD_MODE="block")
            self.assertTrue(self.denied(out), t)
            self.assertIn("delegation:investigator", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertTrue(self.denied(self.run_hook(None, tool="Task", CLAUDE_PLUGIN_OPTION_GUARD_MODE="block")))

    def test_block_lets_a_typed_agent_through(self):
        for t in ("Explore", "delegation:reviewer", "investigator", "claude-code-guide", "other:agent"):
            self.assertIsNone(self.run_hook(t, CLAUDE_PLUGIN_OPTION_GUARD_MODE="block"), t)

    def test_another_tool_is_never_touched(self):
        self.assertIsNone(self.run_hook(None, tool="Bash", CLAUDE_PLUGIN_OPTION_GUARD_MODE="block"))

    def test_log_lets_the_call_through_and_records_a_would_block_event(self):
        self.assertIsNone(self.run_hook("general-purpose", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log"))
        self.assertIsNone(self.run_hook("Explore", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log"))
        [e] = self.events()
        self.assertEqual((e["decision"], e["agent_type"], e["skill"]), ("would-block", "general-purpose", None))
        self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_block_records_its_refusals(self):
        self.run_hook(None, CLAUDE_PLUGIN_OPTION_GUARD_MODE="block")
        self.assertEqual([(e["decision"], e["agent_type"]) for e in self.events()], [("block", "")])

    def test_the_override_variable_wins_over_the_option(self):
        self.assertIsNone(self.run_hook("claude", CLAUDE_PLUGIN_OPTION_GUARD_MODE="block", DELEGATION_GUARD_MODE="off"))
        self.assertTrue(self.denied(self.run_hook("claude", DELEGATION_GUARD_MODE="block")))

    def test_settings_json_sets_the_mode_when_the_environment_does_not(self):
        settings = {"pluginConfigs": {"delegation@market": {"options": {"guard_mode": "block"}}}}
        (self.config / "settings.json").write_text(json.dumps(settings))
        self.assertTrue(self.denied(self.run_hook("fork")))

    def test_an_unknown_mode_falls_back_to_off(self):
        self.assertIsNone(self.run_hook("claude", CLAUDE_PLUGIN_OPTION_GUARD_MODE="strict"))

    def test_the_event_names_the_skill_running_in_the_current_turn(self):
        records = [
            {"type": "user", "message": {"role": "user", "content": "first task"}},
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "old-skill"}}]},
            },
            {"type": "user", "message": {"role": "user", "content": "<command-name>/sweep</command-name>"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "the skill's body"}},
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
            },
        ]
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        self.run_hook("general-purpose", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        records.append({"type": "user", "message": {"role": "user", "content": "plain prompt"}})
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        self.run_hook("claude", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        records.append(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "x:y"}}]},
            }
        )
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        self.run_hook("fork", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        self.assertEqual([e["skill"] for e in self.events()], ["sweep", None, "x:y"])

    def test_a_notice_or_a_shell_echo_is_no_new_prompt_and_keeps_the_skill(self):
        # A background agent's notice, a `!` command's echo or another session's message arrive as user records:
        # the skill that started the turn still runs.
        records = [
            {"type": "user", "message": {"role": "user", "content": "<command-name>/sweep</command-name>"}},
            {"type": "user", "message": {"role": "user", "content": "<task-notification>\n<task-id>a1</task-id>"}},
            {
                "type": "user",
                "origin": {"kind": "task-notification", "producer": "session-task"},
                "message": {"role": "user", "content": "A background task finished."},
            },
            {"type": "user", "message": {"role": "user", "content": "<bash-stdout>ok</bash-stdout>"}},
            {"type": "user", "message": {"role": "user", "content": "<local-command-stdout>x</local-command-stdout>"}},
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": 'Another Claude session sent a message:\n<agent-message from="p">',
                },
            },
        ]
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
        self.run_hook("general-purpose", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        self.assertEqual([e["skill"] for e in self.events()], ["sweep"])

    def test_a_broken_input_or_transcript_never_blocks_a_call_by_mistake(self):
        self.transcript.write_text("not json\n")
        self.assertIsNone(self.run_hook("Explore", CLAUDE_PLUGIN_OPTION_GUARD_MODE="block"))
        r = subprocess.run(
            [HOOK_PYTHON, "-B", str(HOOK)],
            input="{",
            capture_output=True,
            text=True,
            env={**self.env, "CLAUDE_PLUGIN_OPTION_GUARD_MODE": "block"},
            check=False,
        )
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_measure_counts_the_events_the_hook_writes(self):
        self.run_hook("general-purpose", CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        self.run_hook(None, CLAUDE_PLUGIN_OPTION_GUARD_MODE="log")
        self.run_hook("fork", CLAUDE_PLUGIN_OPTION_GUARD_MODE="block")
        g = M.guard_events(str(self.data / "guard-agent-type.jsonl"), None, None)
        self.assertEqual((g["would_block"], g["blocked"]), (2, 1))
        self.assertEqual(g["by_type"], {"general-purpose": 1, "(untyped)": 1, "fork": 1})


class Registration(unittest.TestCase):
    def test_the_plugin_registers_the_hook_on_the_agent_tool(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        [entry] = [h for h in hooks if any("guard_agent_type.py" in c["command"] for c in h["hooks"])]
        self.assertEqual(entry["matcher"], "Agent|Task")

    def test_the_mode_option_defaults_to_off(self):
        option = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["userConfig"]["guard_mode"]
        self.assertEqual(option["default"], "off")


if __name__ == "__main__":
    unittest.main()

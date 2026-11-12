"""Unit tests of the background-command tags (untagged_background in scripts/handover.py): the main session's
untagged command is refused once, then guessed; a subagent's is guessed at once."""

import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

# A subagent's call refused on 2026-11-07 (competitive-analysis data-fetcher session, agent-a0f39508205e88dd1).
CHECK = "cd /tmp/data-fetcher && just check > /tmp/check.log 2>&1; echo exit $? >> /tmp/check.log"


def call(sid, command, description="Run the checks", agent_id=None):
    inp = {
        "session_id": sid,
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": description, "run_in_background": True},
    }
    if agent_id:
        inp.update(agent_id=agent_id, agent_type="Explore")
    return H.untagged_background(inp)


def guessed(sid, command):
    return H.task_tag({"command": command}, H.read_json(H.tasks_path(sid), {}))


class Tags(unittest.TestCase):
    def test_a_tagged_command_runs(self):
        self.assertIsNone(call("s-tagged", CHECK, description="[await] Run the checks"))

    def test_the_sessions_untagged_command_is_refused_once_then_guessed(self):
        self.assertEqual(call("s-main", CHECK), H.UNTAGGED)
        self.assertIsNone(call("s-main", CHECK))
        self.assertEqual(guessed("s-main", CHECK), "await")

    def test_a_subagents_untagged_command_runs_at_once_with_a_guessed_tag(self):
        self.assertIsNone(call("s-sub", CHECK, agent_id="a0f39508205e88dd1"))
        self.assertEqual(guessed("s-sub", CHECK), "await")


if __name__ == "__main__":
    unittest.main()

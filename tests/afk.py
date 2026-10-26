"""Unit tests of the handover plugin's AFK relay past the suggestion (scripts/handover.py): a subagent refused
in an AFK run hands the session over, with the refused call as the next session's focus, and an
`AFK blocked:` that only the refusal caused does not end the run."""

import json
import os
import sys
import tempfile
import time
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

H.alert = lambda message: None
TRANSCRIPT = os.path.join(HOME, "transcript.jsonl")
with open(TRANSCRIPT, "w") as f:
    f.write('{"type": "user", "message": {"role": "user", "content": "hi"}}\n')
REVIEW = {"name": "gs-dev-toolkit:review", "args": {"repo": "/tmp/wt", "fix": True}}


def session(sid, afk=True, **st):
    os.makedirs(os.path.join(DATA, "sessions"), exist_ok=True)
    st = {"suggested": True, "transcript": TRANSCRIPT, **st}
    if afk:
        st["afk"] = {"goal": "ship it", "until": None, "run": f"run-{sid}", "since": time.time(), "yolo": True}
        st["relay_on"] = True
    H.write_json(H.state_path(sid), st)


def state(sid):
    return H.read_json(H.state_path(sid), {})


def refuse(sid, tool="Workflow", ti=REVIEW):
    out = H.on_pre_tool_use(
        {"session_id": sid, "tool_name": tool, "tool_input": ti, "transcript_path": TRANSCRIPT, "cwd": HOME}
    )
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def stop(sid, reply):
    with H.locked_state(sid) as st:
        return H.afk_on_activity(st, sid, {"last_assistant_message": reply, "transcript_path": TRANSCRIPT}, "Stop")


def requested(sid):
    with open(H.metrics_path()) as f:
        return [e["cause"] for e in map(json.loads, f) if e["session"] == sid and e["event"] == "handover_requested"]


class RefusedSubagent(unittest.TestCase):
    def test_an_afk_run_hands_over_with_the_refused_call_as_focus(self):
        session("a1")
        self.assertEqual(refuse("a1"), H.AFK_AGENT_HANDOVER)
        st = state("a1")
        self.assertTrue(st["wind_down"])
        self.assertIn("Workflow gs-dev-toolkit:review", st["focus"])
        self.assertIn("/tmp/wt", st["focus"])
        self.assertEqual(requested("a1"), ["agent_refused"])

    def test_a_second_refusal_requests_no_second_handover(self):
        session("a2")
        refuse("a2")
        self.assertEqual(refuse("a2", "Agent", {"subagent_type": "Explore", "description": "find x"}), H.NO_NEW_AGENT)
        self.assertEqual(requested("a2"), ["agent_refused"])
        self.assertEqual(state("a2")["agents_refused"], 2)

    def test_outside_afk_the_refusal_only_tells_the_session(self):
        session("a3", afk=False)
        self.assertEqual(refuse("a3"), H.NO_NEW_AGENT)
        self.assertFalse(state("a3").get("wind_down"))

    def test_past_the_afk_deadline_no_handover_starts(self):
        session("a4")
        with H.locked_state("a4") as st:
            st["afk"]["deadline_told"] = True
        self.assertEqual(refuse("a4"), H.NO_NEW_AGENT)
        self.assertFalse(state("a4").get("wind_down"))


class BlockedByRefusal(unittest.TestCase):
    def test_a_block_the_refusal_caused_hands_over_instead_of_ending_the_run(self):
        session("b1", agents_refused=1, refused_call={"call": "Workflow gs-dev-toolkit:review", "input": "{}"})
        out = stop("b1", "Review cannot start.\nAFK blocked: a hook blocks new subagents")
        self.assertEqual(out["decision"], "block")
        self.assertIn("Workflow gs-dev-toolkit:review", out["reason"])
        st = state("b1")
        self.assertFalse(st["afk"].get("ended"))
        self.assertTrue(st["wind_down"])
        self.assertEqual(requested("b1"), ["afk_blocked"])

    def test_a_closing_reply_blocked_by_the_refusal_still_relays(self):
        session("b2", agents_refused=1)
        with H.locked_state("b2") as st:
            self.assertIsNone(H.afk_declared_end(st, "b2", "AFK blocked: subagents refused"))
        self.assertFalse(state("b2")["afk"].get("ended"))

    def test_a_block_without_a_refusal_ends_the_run(self):
        session("b3")
        out = stop("b3", "AFK blocked: the user must pick a design")
        self.assertNotIn("decision", out)
        self.assertEqual(state("b3")["afk"]["ended"], "blocked")

    def test_done_ends_the_run_even_after_a_refusal(self):
        session("b4", agents_refused=1)
        stop("b4", "AFK done: every issue shipped")
        self.assertEqual(state("b4")["afk"]["ended"], "done")


if __name__ == "__main__":
    unittest.main()

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
# An AFK run names its tab: not the tab these tests run in.
for key in ("TMUX", "TMUX_PANE", "REX_SESSION", "REX_BLOCK", "REX_SERVER"):
    os.environ.pop(key, None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H
import session as S

H.alert = lambda message, *a, **k: None
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
    H.write_json(S.path(sid), st)


def state(sid):
    return S.read(sid)


def refuse(sid, tool="Workflow", ti=REVIEW):
    out = H.on_pre_tool_use(
        {"session_id": sid, "tool_name": tool, "tool_input": ti, "transcript_path": TRANSCRIPT, "cwd": HOME}
    )
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def stop(sid, reply):
    with S.locked(sid) as st:
        return H.afk_on_activity(st, sid, {"last_assistant_message": reply, "transcript_path": TRANSCRIPT}, "Stop")


def requested(sid):
    with open(H.metrics_path()) as f:
        return [e["cause"] for e in map(json.loads, f) if e["session"] == sid and e["event"] == "handover_requested"]


class RefusedSubagent(unittest.TestCase):
    def test_an_afk_run_hands_over_with_the_refused_call_as_focus(self):
        session("a1")
        self.assertEqual(refuse("a1"), H.AFK_AGENT_HANDOVER)
        st = state("a1")
        self.assertTrue(S.wound_down(st))
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
        self.assertFalse(S.wound_down(state("a3")))

    def test_past_the_afk_deadline_no_handover_starts(self):
        session("a4")
        with S.locked("a4") as st:
            st["afk"]["deadline_told"] = True
        self.assertEqual(refuse("a4"), H.NO_NEW_AGENT)
        self.assertFalse(S.wound_down(state("a4")))


class BlockedByRefusal(unittest.TestCase):
    def test_a_block_the_refusal_caused_hands_over_instead_of_ending_the_run(self):
        session("b1", agents_refused=1, refused_call={"call": "Workflow gs-dev-toolkit:review", "input": "{}"})
        out = stop("b1", "Review cannot start.\nAFK blocked: a hook blocks new subagents")
        self.assertEqual(out["decision"], "block")
        self.assertIn("Workflow gs-dev-toolkit:review", out["reason"])
        st = state("b1")
        self.assertFalse(st["afk"].get("ended"))
        self.assertTrue(S.wound_down(st))
        self.assertEqual(requested("b1"), ["afk_blocked"])

    def test_a_closing_reply_blocked_by_the_refusal_still_relays(self):
        session("b2", agents_refused=1)
        with S.locked("b2") as st:
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


class Recovery(unittest.TestCase):
    def test_only_a_rex_pane_is_recovered(self):
        # The resume typed after a restart is a Rex launcher: another host that set `recovers` ends the run.
        real = H.terminal
        H.terminal = lambda: type("Host", (), {"name": "tmux", "recovers": True, "address": "%1"})()
        try:
            session("r1")
            H.on_session_end({"session_id": "r1", "reason": "other", "transcript_path": TRANSCRIPT, "cwd": HOME})
        finally:
            H.terminal = real
        self.assertNotIn("recovering", state("r1"))
        self.assertIn("ended", state("r1")["afk"])


class FailedRelay(unittest.TestCase):
    def test_a_failed_relay_never_resumes_the_run(self):
        # The relay outcome stays a fact past the phase: a session asked again, or compacted, is not kept going.
        for after in ("request", "compaction"):
            with self.subTest(after):
                st = {"transcript": TRANSCRIPT}
                session("f1")
                st = state("f1")
                S.wind_down(st, "trigger", 1)
                S.reply_written(st)
                S.halted(st, "failed", 1)
                if after == "request":
                    S.requested(st)
                    S.reply_written(st)
                else:
                    S.compaction_starts(st)
                    S.compacted(st)
                inp = {"last_assistant_message": "done", "transcript_path": TRANSCRIPT}
                self.assertIsNone(H.afk_on_activity(st, "f1", inp, "Stop"))


if __name__ == "__main__":
    unittest.main()

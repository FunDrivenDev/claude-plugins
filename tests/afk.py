"""Unit tests of the handover plugin's subagent refusal (scripts/handover.py, D51): past the suggestion alone a
subagent still starts; once the session winds down it is refused, and in an AFK run the refused call becomes
the next session's focus; an `AFK blocked:` that only the refusal caused does not end the run."""

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


def call(sid, tool="Workflow", ti=REVIEW):
    return H.on_pre_tool_use(
        {"session_id": sid, "tool_name": tool, "tool_input": ti, "transcript_path": TRANSCRIPT, "cwd": HOME}
    )


def refuse(sid, tool="Workflow", ti=REVIEW):
    return call(sid, tool, ti)["hookSpecificOutput"]["permissionDecisionReason"]


def wind_down(sid):
    with S.locked(sid) as st:
        S.wind_down(st, "trigger", 260_000)


def stop(sid, reply):
    with S.locked(sid) as st:
        return H.afk_on_activity(st, sid, {"last_assistant_message": reply, "transcript_path": TRANSCRIPT}, "Stop")


def requested(sid):
    with open(H.metrics_path()) as f:
        return [e["cause"] for e in map(json.loads, f) if e["session"] == sid and e["event"] == "handover_requested"]


class RefusedSubagent(unittest.TestCase):
    def test_past_the_suggestion_alone_the_review_before_a_push_still_starts(self):
        for afk in (True, False):
            with self.subTest(afk=afk):
                sid = f"a0-{afk}"
                session(sid, afk=afk)
                self.assertIsNone(call(sid))
                self.assertIsNone(call(sid, "Agent", {"subagent_type": "delegation:reviewer", "description": "r"}))
                st = state(sid)
                self.assertNotIn("agents_refused", st)
                self.assertFalse(S.wound_down(st))
                self.assertEqual(requested(sid), [])

    def test_an_afk_run_winding_down_gives_the_refused_call_to_the_next_session(self):
        session("a1")
        wind_down("a1")
        self.assertEqual(refuse("a1"), H.AFK_AGENT_HANDOVER)
        st = state("a1")
        self.assertIn("Workflow gs-dev-toolkit:review", st["focus"])
        self.assertIn("/tmp/wt", st["focus"])
        self.assertEqual(st["agents_refused"], 1)

    def test_a_second_refusal_keeps_the_first_focus(self):
        session("a2")
        wind_down("a2")
        refuse("a2")
        self.assertEqual(refuse("a2", "Agent", {"subagent_type": "Explore", "description": "find x"}), H.NO_NEW_AGENT)
        self.assertIn("Workflow gs-dev-toolkit:review", state("a2")["focus"])
        self.assertEqual(state("a2")["agents_refused"], 2)

    def test_a_focus_the_session_set_is_kept(self):
        session("a5", focus="Push the branch first.")
        wind_down("a5")
        self.assertEqual(refuse("a5"), H.NO_NEW_AGENT)
        self.assertEqual(state("a5")["focus"], "Push the branch first.")

    def test_outside_afk_the_refusal_only_tells_the_session(self):
        session("a3", afk=False)
        wind_down("a3")
        self.assertEqual(refuse("a3"), H.NO_NEW_AGENT)
        self.assertNotIn("focus", state("a3"))

    def test_past_the_afk_deadline_no_handover_starts(self):
        session("a4")
        with S.locked("a4") as st:
            st["afk"]["deadline_told"] = True
        self.assertEqual(refuse("a4"), H.NO_NEW_AGENT)
        self.assertFalse(S.wound_down(state("a4")))

    def test_past_the_afk_deadline_before_the_hook_tells_it_no_subagent_starts(self):
        session("a6")
        with S.locked("a6") as st:
            st["afk"]["until"] = time.time() - 60
        self.assertEqual(refuse("a6", "Agent", {"subagent_type": "Explore", "description": "find x"}), H.NO_NEW_AGENT)

    def test_once_the_handover_is_written_the_refused_call_is_left_to_the_closing_reply(self):
        for key in ("reply_due", "held_since"):
            with self.subTest(key=key):
                sid = f"a7-{key}"
                session(sid)
                wind_down(sid)
                with S.locked(sid) as st:
                    st[key] = time.time()
                self.assertEqual(refuse(sid), H.NO_NEW_AGENT)
                self.assertNotIn("focus", state(sid))

    def test_a_focus_set_after_the_handover_was_written_has_it_written_again(self):
        session("a9")
        wind_down("a9")
        with S.locked("a9") as st:
            st["written"] = {"ok": True, "at": time.time() - 10, "tokens": 260_000}
            self.assertFalse(H.needs_refresh(st, 260_000))
        refuse("a9")
        self.assertTrue(H.needs_refresh(state("a9"), 260_000))

    def test_a_compaction_drops_the_focus_of_the_handover_it_loaded(self):
        session("a8", focus="Old step.")
        with S.locked("a8") as st:
            S.compacted(st)
        wind_down("a8")
        self.assertEqual(refuse("a8"), H.AFK_AGENT_HANDOVER)
        self.assertIn("Workflow gs-dev-toolkit:review", state("a8")["focus"])


class BlockedByRefusal(unittest.TestCase):
    def test_a_closing_reply_blocked_by_the_refusal_still_relays(self):
        session("b2")
        wind_down("b2")
        self.assertEqual(refuse("b2"), H.AFK_AGENT_HANDOVER)
        with S.locked("b2") as st:
            self.assertIsNone(H.afk_declared_end(st, "b2", "AFK blocked: subagents refused"))
        self.assertFalse(state("b2")["afk"].get("ended"))

    def test_a_refusal_after_the_handover_was_written_does_not_overrule_a_block(self):
        session("b1")
        wind_down("b1")
        with S.locked("b1") as st:
            st["held_since"] = time.time()
        self.assertEqual(refuse("b1"), H.NO_NEW_AGENT)
        with S.locked("b1") as st:
            self.assertIsNotNone(H.afk_declared_end(st, "b1", "AFK blocked: needs Raphael's 2FA code"))
        self.assertEqual(state("b1")["afk"]["ended"], "blocked")

    def test_a_block_after_a_refusal_still_relays_when_the_session_set_the_focus(self):
        session("b6", focus="Push the branch first.")
        wind_down("b6")
        self.assertEqual(refuse("b6"), H.NO_NEW_AGENT)
        with S.locked("b6") as st:
            self.assertIsNone(H.afk_declared_end(st, "b6", "AFK blocked: the review workflow is refused"))
        self.assertFalse(state("b6")["afk"].get("ended"))

    def test_a_refusal_before_an_earlier_closing_reply_does_not_overrule_a_later_block(self):
        session("b7")
        wind_down("b7")
        refuse("b7")
        with S.locked("b7") as st:
            S.enter(st, S.HALTED)
            S.requested(st)
            self.assertIsNotNone(H.afk_declared_end(st, "b7", "AFK blocked: needs Raphael's 2FA code"))
        self.assertEqual(state("b7")["afk"]["ended"], "blocked")

    def test_a_block_without_a_refusal_ends_the_run(self):

        session("b3")
        out = stop("b3", "AFK blocked: the user must pick a design")
        self.assertNotIn("decision", out)
        self.assertEqual(state("b3")["afk"]["ended"], "blocked")

    def test_a_refusal_before_a_compaction_does_not_overrule_a_later_block(self):
        session("b5")
        wind_down("b5")
        self.assertEqual(refuse("b5"), H.AFK_AGENT_HANDOVER)
        with S.locked("b5") as st:
            S.compacted(st)
        out = stop("b5", "AFK blocked: needs Raphael's 2FA code")
        self.assertNotIn("decision", out)
        self.assertEqual(state("b5")["afk"]["ended"], "blocked")

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

"""Unit tests of the handover plugin's session phase (scripts/session.py), its transitions, and the status line
it drives (handover.py `status_line`): one case per phase and per flag combination the transitions leave, the
contradictions the state survey found among them."""

import os
import sys
import tempfile
import time
import unittest

HOME = tempfile.mkdtemp()
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=os.path.join(HOME, "data"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H
import session as S

CFG = {"trigger": 200_000, "suggest": 150_000, "chars": 12_000, "relay_limit": 5}
NOW = time.time()
WRITTEN = {"ok": True, "at": NOW}
ERROR = {"at": NOW, "message": "the writer timed out", "reported": True}

# (name, state an older plugin version wrote, phase, closing reply owed, halt reason): the conversion of its flags.
PHASES = [
    ("fresh session", {}, S.WORKING, False, None),
    ("suggested", {"suggested": True}, S.WORKING, False, None),
    ("handover kept fresh", {"keep_fresh": True, "written": WRITTEN}, S.WORKING, False, None),
    ("compaction", {"keep_fresh": True, "compacting": True}, S.COMPACTING, False, None),
    ("compaction while winding down", {"wind_down": True, "compacting": True}, S.COMPACTING, False, None),
    ("wind-down", {"wind_down": True}, S.WINDING_DOWN, False, None),
    ("held, writing", {"wind_down": True, "held_since": NOW}, S.WINDING_DOWN, False, None),
    (
        "held, an older handover",
        {"wind_down": True, "held_since": NOW, "written": {"ok": True, "at": NOW - 60}},
        S.WINDING_DOWN,
        False,
        None,
    ),
    ("held, written", {"wind_down": True, "held_since": NOW, "written": WRITTEN}, S.WINDING_DOWN, True, None),
    ("reply due", {"wind_down": True, "reply_due": True}, S.WINDING_DOWN, True, None),
    (
        "reply due, write failed",
        {"wind_down": True, "reply_due": True, "write_failed": True},
        S.WINDING_DOWN,
        True,
        None,
    ),
    ("closing reply", {"wind_down": True, "reply_due": True, "closing_reply": True}, S.HANDED_OVER, False, None),
    (
        "relay launched",
        {"wind_down": True, "closing_reply": True, "relay_outcome": {"at": NOW, "n": 1}},
        S.RELAYING,
        False,
        None,
    ),
    ("relay limit", {"closing_reply": True, "relay_outcome": {"limit": True, "n": 5}}, S.HALTED, False, "limit"),
    ("AFK deadline", {"relay_outcome": {"limit": True, "n": 2, "deadline": True}}, S.HALTED, False, "deadline"),
    ("relay failed", {"relay_outcome": {"failed": True, "n": 1}}, S.HALTED, False, "failed"),
    ("AFK run ended", {"relay_outcome": {"afk": "done", "n": 3}}, S.HALTED, False, "afk"),
]


class Phase(unittest.TestCase):
    def test_table(self):
        for name, old, phase, owed, reason in PHASES:
            with self.subTest(name):
                st = S.converted(dict(old))
                self.assertFalse(set(S.LEGACY) & set(st))
                self.assertEqual(S.phase(st), phase)
                self.assertEqual(S.reply_owed(st), owed)
                self.assertEqual(S.halt_reason(st), reason)

    def test_every_phase_is_reached(self):
        self.assertEqual({row[2] for row in PHASES}, set(S.PHASES))


class Transitions(unittest.TestCase):
    def test_lifecycle(self):
        st = {}
        self.assertTrue(S.wind_down(st, "trigger", 200_000))
        self.assertEqual(S.phase(st), S.WINDING_DOWN)
        self.assertFalse(S.wind_down(st, "request", 210_000))
        self.assertEqual(st["cause"], "trigger")
        S.held(st, NOW)
        self.assertFalse(S.reply_owed(st))
        S.reply_asked(st, False)
        self.assertTrue(S.reply_owed(st))
        S.reply_written(st)
        self.assertEqual(S.phase(st), S.HANDED_OVER)
        S.relayed(st, 1, "rex")
        self.assertEqual(S.phase(st), S.RELAYING)

    def test_halts_carry_their_reason(self):
        for reason in ("limit", "deadline", "failed", "afk"):
            with self.subTest(reason):
                st = {}
                S.halted(st, reason, 2, afk="done")
                self.assertEqual((S.phase(st), S.halt_reason(st)), (S.HALTED, reason))

    def test_a_cancelled_compaction_returns_to_the_phase_before_it(self):
        # The survey's contradiction: keep_fresh outlived a cancelled compaction, and kept the wind-down off.
        st = S.converted({"keep_fresh": True})
        S.compaction_starts(st)
        self.assertEqual(S.phase(st), S.COMPACTING)
        S.active(st)
        self.assertEqual(st, {})
        self.assertTrue(S.wind_down(st, "cli", 1))
        S.compaction_starts(st)
        S.active(st)
        self.assertEqual(S.phase(st), S.WINDING_DOWN)

    def test_a_handover_asked_during_a_compaction_outlives_a_cancelled_one(self):
        st = {}
        S.compaction_starts(st)
        self.assertTrue(S.wind_down(st, "request", 1))
        S.requested(st)
        S.active(st)
        self.assertEqual(S.phase(st), S.WINDING_DOWN)

    def test_a_compaction_starts_the_session_over(self):
        st = {"phase": S.COMPACTING, "phase_before": S.WINDING_DOWN, "reply_due": True, "written": WRITTEN}
        st["afk"] = {"goal": "g"}
        S.compacted(st)
        self.assertEqual(st, {"afk": {"goal": "g"}})

    def test_a_handover_asked_again_owes_a_new_reply(self):
        st = {"phase": S.HANDED_OVER, "reply_due": True, "held_since": NOW}
        S.requested(st)
        self.assertEqual(S.phase(st), S.WINDING_DOWN)
        self.assertFalse(S.reply_owed(st))
        self.assertTrue(st["user_notified"] and st["wind_down_sent"])

    def test_a_compaction_while_winding_down_comes_back_to_it(self):
        st = S.converted({"wind_down": True, "compacting": True})
        self.assertEqual(st, {"phase": S.COMPACTING, "phase_before": S.WINDING_DOWN})
        self.assertTrue(S.wound_down(st))
        S.reply_written(st)
        self.assertEqual(S.phase(st), S.COMPACTING)
        S.active(st)
        self.assertEqual(st, {"phase": S.HANDED_OVER})

    def test_an_old_file_is_converted_once_read(self):
        H.write_json(S.path("old"), {"wind_down": True, "closing_reply": True, "keep_fresh": True})
        self.assertEqual(S.read("old"), {"phase": S.HANDED_OVER})
        with S.locked("old") as st:
            self.assertEqual(st, {"phase": S.HANDED_OVER})
        self.assertEqual(H.read_json(S.path("old")), {"phase": S.HANDED_OVER})

    def test_a_restart_keeps_the_thresholds(self):
        # The survey's contradiction: each SessionStart, a compaction's or a resume's, recomputed them.
        st = {}
        S.started(st, {"trigger_tokens": 1}, "1.0.0")
        S.started(st, {"trigger_tokens": 2}, "1.1.0")
        self.assertEqual(st, {"thresholds": {"trigger_tokens": 1}, "plugin_version": "1.0.0"})


def line(st, tokens=0, prog=None):
    """The status line of a state written with an older plugin version's flags, read as cmd_statusline reads it."""
    return H.status_line(S.converted(dict(st)), prog, tokens, CFG)


class StatusLine(unittest.TestCase):
    def test_working(self):
        self.assertEqual(line({}, 10_000), ("gray", "Handover will trigger at 200k"))
        self.assertEqual(line({}, 199_000), ("yellow", "Handover suggested · will trigger at 200k"))
        self.assertEqual(line({}, 210_000), ("orange", "Wind-down on the next tool call"))
        self.assertEqual(line({"written": WRITTEN}), ("green", "Handover ready · run /clear"))

    def test_writer_shows_over_any_phase(self):
        writer = {"writer": {"pid": os.getpid(), "since": NOW}}
        prog = {"phase": "thinking", "since": NOW}
        for st in ({}, {"wind_down": True, "held_since": NOW}, {"compacting": True}):
            with self.subTest(st):
                colour, text = line({**st, **writer}, prog=prog)
                self.assertEqual(colour, "orange")
                self.assertTrue(text.startswith("Handover writing · thinking"), text)

    def test_compacting(self):
        self.assertEqual(line({"compacting": True}), ("gray", "Compacting · handover not written"))
        self.assertEqual(
            line({"compacting": True, "written": WRITTEN}), ("gray", "Compacting · handover written, loads after it")
        )

    def test_winding_down_and_closing(self):
        self.assertEqual(line({"wind_down": True}), ("orange", "Winding down · finishing tasks"))
        self.assertEqual(
            line({"wind_down": True, "held_since": NOW, "written": WRITTEN}),
            ("orange", "Handover written · closing reply"),
        )

    def test_handed_over(self):
        st = {"wind_down": True, "closing_reply": True, "written": WRITTEN}
        self.assertEqual(line(st), ("green", "Handover ready · run /clear"))
        self.assertEqual(line({**st, "relay_outcome": {"at": NOW, "n": 1}}), ("green", "Handover ready · relaying"))

    def test_failed_write_over_an_older_handover(self):
        # The survey's contradiction: an older handover on disk hid the failed write.
        st = {"wind_down": True, "reply_due": True, "write_failed": True, "error": ERROR, "written": WRITTEN}
        self.assertEqual(line(st), ("red", "Handover failed · closing reply"))
        self.assertEqual(line({**st, "closing_reply": True}), ("red", "Handover failed · the writer timed out"))
        halted = {**st, "closing_reply": True, "relay_outcome": {"failed": True, "n": 1}}
        self.assertEqual(line(halted), ("red", "Handover failed · the writer timed out"))

    def test_failed_write_without_a_handover(self):
        self.assertEqual(line({"error": ERROR}), ("red", "Handover failed · the writer timed out"))

    def test_halted(self):
        cases = [
            ({"limit": True, "n": 5}, "Relay limit · 5 handovers · run /clear"),
            ({"limit": True, "n": 2, "deadline": True}, "AFK deadline · 2 handovers · run /clear"),
            # The survey's contradiction: a failed relay showed as a ready handover.
            ({"failed": True, "n": 1}, "Relay failed · run /clear"),
        ]
        for outcome, text in cases:
            with self.subTest(outcome):
                st = {"closing_reply": True, "written": WRITTEN, "relay_outcome": outcome}
                self.assertEqual(line(st), ("red", text))

    def test_afk_end(self):
        st = {"closing_reply": True, "written": WRITTEN, "relay_outcome": {"afk": "done", "n": 3}}
        st["afk"] = {"ended": "done", "reason": "shipped"}
        self.assertEqual(line(st), ("green", "AFK done · shipped"))


if __name__ == "__main__":
    unittest.main()

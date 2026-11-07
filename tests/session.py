"""Unit tests of the handover plugin's session phase (scripts/session.py) and of the status line it drives
(handover.py `status_line`): one case per phase and per flag combination today's transitions leave, the
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

# (name, state, phase, closing reply owed, halt reason)
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
        for name, st, phase, owed, reason in PHASES:
            with self.subTest(name):
                self.assertEqual(S.phase(st), phase)
                self.assertEqual(S.reply_owed(st), owed)
                self.assertEqual(S.halt_reason(st), reason)

    def test_every_phase_is_reached(self):
        self.assertEqual({row[2] for row in PHASES}, set(S.PHASES))


def line(st, tokens=0, prog=None):
    return H.status_line(st, prog, tokens, CFG)


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

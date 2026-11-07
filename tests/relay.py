"""Unit tests of the relay handshake (D19), relay.py: offer, claim, confirm and await, each step and each failure,
in a throwaway data folder with a fake clock: no session, no terminal, no wait."""

import os
import shutil
import sys
import tempfile
import unittest

DATA = tempfile.mkdtemp()
os.environ["CLAUDE_PLUGIN_DATA"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import relay as R
from store import read_json, write_json

NOW = 1_000_000.0


def tearDownModule():
    shutil.rmtree(DATA, ignore_errors=True)


class Clock:
    """A clock that a sleep moves on, and that runs `at` once it reaches each of its times."""

    def __init__(self, at=None):
        self.now, self.at, self.slept = NOW, dict(at or {}), 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.slept += seconds
        for t in sorted(self.at):
            if self.now >= NOW + t:
                self.at.pop(t)()


def leftovers():
    return sorted(os.listdir(os.path.join(DATA, "relay")))


class Handshake(unittest.TestCase):
    def setUp(self):
        for name in os.listdir(os.path.join(DATA, "relay")) if os.path.isdir(os.path.join(DATA, "relay")) else ():
            os.remove(os.path.join(DATA, "relay", name))

    def test_offer_claim_confirm_await(self):
        R.offer("proj", "old", "rex", now=NOW)
        self.assertEqual(read_json(R.offer_path("proj")), {"session": "old", "at": NOW, "mode": "rex"})
        self.assertEqual(R.claim("proj", "new", now=NOW + 5), {"session": "old", "at": NOW, "mode": "rex"})
        # Taken: the offer is gone, nothing else is left behind.
        self.assertEqual(leftovers(), [])
        R.confirm("old", True)
        self.assertEqual(leftovers(), ["old.loaded.json"])
        clock = Clock()
        self.assertTrue(R.await_confirmation("old", clock=clock, sleep=clock.sleep))
        self.assertEqual(clock.slept, 0)
        # The answer is consumed.
        self.assertEqual(leftovers(), [])

    def test_the_files_keep_their_names(self):
        # The contract tests and an older plugin version's sessions read them by these names.
        self.assertEqual(R.offer_path("p"), os.path.join(DATA, "relay", "p.json"))
        self.assertEqual(R.confirmation_path("s1"), os.path.join(DATA, "relay", "s1.loaded.json"))

    def test_no_offer(self):
        self.assertIsNone(R.claim("proj", "new", now=NOW))

    def test_a_stale_offer_is_not_taken(self):
        R.offer("proj", "old", "rex", now=NOW)
        self.assertEqual(R.claim("proj", "new", now=NOW + R.OFFER_SECONDS)["session"], "old")
        R.offer("proj", "old", "rex", now=NOW)
        self.assertIsNone(R.claim("proj", "new", now=NOW + R.OFFER_SECONDS + 1))
        # Nobody may take it any more: it is dropped.
        self.assertEqual(leftovers(), [])

    def test_a_session_does_not_take_its_own_offer(self):
        R.offer("proj", "old", "rex", now=NOW)
        self.assertIsNone(R.claim("proj", "old", now=NOW))
        self.assertEqual(leftovers(), ["proj.json"])
        self.assertEqual(R.claim("proj", "new", now=NOW)["session"], "old")

    def test_an_offer_of_another_project_is_not_taken(self):
        R.offer("other", "old", "rex", now=NOW)
        self.assertIsNone(R.claim("proj", "new", now=NOW))

    def test_a_malformed_offer_is_not_taken(self):
        for bad in ({}, {"session": "old"}, {"session": "old", "at": "now"}, [1], {"session": 3, "at": NOW}):
            with self.subTest(bad):
                write_json(R.offer_path("proj"), bad)
                self.assertIsNone(R.claim("proj", "new", now=NOW))

    def test_a_double_claim_gives_the_offer_once(self):
        R.offer("proj", "old", "rex", now=NOW)
        self.assertEqual(R.claim("proj", "new", now=NOW)["session"], "old")
        self.assertIsNone(R.claim("proj", "other", now=NOW))

    def test_of_two_claims_made_together_one_wins(self):
        # Session a starts its claim; before it takes the offer, session b takes it: a's rename finds nothing.
        R.offer("proj", "old", "rex", now=NOW)
        real, won = R.sweep, {}

        def racing(key, now):
            R.sweep = real
            won["b"] = R.claim("proj", "b", now=NOW)
            return real(key, now)

        R.sweep = racing
        try:
            a = R.claim("proj", "a", now=NOW)
        finally:
            R.sweep = real
        self.assertIsNone(a)
        self.assertEqual(won["b"]["session"], "old")
        self.assertEqual(leftovers(), [])

    def test_a_claim_judges_the_offer_it_took_not_one_read_before(self):
        # Session a lists the folder; meanwhile b takes X's offer and Y offers: a takes Y's, which is valid.
        R.offer("proj", "X", "rex", now=NOW)
        real = R.sweep

        def racing(key, now):
            R.sweep = real
            self.assertEqual(R.claim("proj", "b", now=NOW)["session"], "X")
            R.offer("proj", "Y", "rex", now=NOW + 1)
            return real(key, now)

        R.sweep = racing
        try:
            self.assertEqual(R.claim("proj", "a", now=NOW + 1)["session"], "Y")
        finally:
            R.sweep = real
        self.assertEqual(leftovers(), [])

    def test_a_crashed_claim_s_leftover_is_swept(self):
        R.offer("proj", "old", "rex", now=NOW)
        left = R.offer_path("proj") + ".a.123.claimed"
        os.rename(R.offer_path("proj"), left)
        R.offer("proj", "old2", "rex", now=NOW)
        R.claim("proj", "new", now=os.path.getmtime(left) + R.OFFER_SECONDS - 1)
        self.assertEqual(leftovers(), [os.path.basename(left)])
        R.claim("proj", "new", now=os.path.getmtime(left) + R.OFFER_SECONDS + 1)
        self.assertEqual(leftovers(), [])

    def test_the_claim_answers_that_the_handover_did_not_load(self):
        R.confirm("old", False)
        clock = Clock()
        self.assertFalse(R.await_confirmation("old", clock=clock, sleep=clock.sleep))
        self.assertEqual(leftovers(), [])

    def test_an_answer_that_comes_while_waiting(self):
        clock = Clock({30: lambda: R.confirm("old", True)})
        self.assertTrue(R.await_confirmation("old", clock=clock, sleep=clock.sleep))
        self.assertEqual(clock.slept, 30)

    def test_no_claim_before_the_deadline(self):
        clock = Clock({R.CONFIRM_SECONDS + 5: lambda: R.confirm("old", True)})
        self.assertFalse(R.await_confirmation("old", clock=clock, sleep=clock.sleep))
        self.assertEqual(clock.slept, R.CONFIRM_SECONDS)
        # The driver waits longer than the claiming session waits for the writer.
        self.assertGreater(R.CONFIRM_SECONDS, R.LOAD_SECONDS)

    def test_a_malformed_answer_is_no_load(self):
        for bad in ({}, {"ok": "yes"}, [True]):
            with self.subTest(bad):
                write_json(R.confirmation_path("old"), bad)
                clock = Clock()
                self.assertFalse(R.await_confirmation("old", clock=clock, sleep=clock.sleep))


if __name__ == "__main__":
    unittest.main()

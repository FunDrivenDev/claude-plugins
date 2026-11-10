"""Two relay chains in one project (scripts/handover.py): each new session resumes the handover and the AFK goal of
its own chain, never the other's.

A Guest-Suite session starts from the guest-environment root whatever repo it changes, so two AFK chains there
share their project. Both hand over within the same minute, each in its own pane; the relay of each must start its
new session from its own handover. A session whose /clear did not end it (Claude Code ran another command) and
that hands over again is relayed again, its first driver silent. The relay is driven through its hooks' functions,
its terminal faked per pane: no session, no terminal, no wait."""

import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
PROJECT = os.path.join(HOME, "guest-environment")
os.makedirs(PROJECT)
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
# Not the session these tests run in: its pane, its project, its relay or AFK run.
for key in list(os.environ):
    if key.startswith(("TMUX", "REX_", "HANDOVER_")) or key == "CLAUDE_PROJECT_DIR":
        os.environ.pop(key)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H
import session as S
import terminal as TERM

TRANSCRIPT = os.path.join(HOME, "transcript.jsonl")
with open(TRANSCRIPT, "w") as f:
    f.write('{"type": "user", "message": {"role": "user", "content": "hi"}}\n')


class Pane(TERM.Terminal):
    """A Rex pane that types into nothing: the relay's driver is not started here."""

    name = "rex"
    verbs = TERM.VERBS

    def report_status(self, state, message=""):
        return True

    def set_title(self, title):
        return True


HERE = {"pane": None}
H.terminal = lambda: HERE["pane"]
H.alert = lambda *a, **k: None
DRIVEN = []
H.detach = lambda args, **k: DRIVEN.append(args)


def chain(sid, pane, topic, goal):
    """Session `sid`, in `pane`, has written its handover and asks the relay to hand over, in an AFK run."""
    path = os.path.join(HOME, f"{topic}.md")
    with open(path, "w") as f:
        f.write(f"# {topic}\n")
    H.write_json(
        S.path(sid),
        {
            "transcript": TRANSCRIPT,
            "project": PROJECT,
            "path": path,
            "written": {"ok": True},
            "chain": {"base": f"{topic}.md", "n": 2},
            "relay_on": True,
            "afk": {"goal": goal, "until": None, "run": f"run-{topic}", "since": time.time(), "yolo": False},
        },
    )
    HERE["pane"] = pane
    with S.locked(sid) as st:
        return H.relay(st, sid, 0, H.config(), "Carry on.")


def start(sid, pane):
    """The session the relay starts in `pane`, after /clear."""
    HERE["pane"] = pane
    return H.on_session_start({"session_id": sid, "source": "clear", "cwd": PROJECT, "transcript_path": TRANSCRIPT})


A = Pane("session:1 block:a")
B = Pane("session:2 block:b")


class TwoChainsInOneProject(unittest.TestCase):
    def test_each_new_session_resumes_its_own_chain(self):
        self.assertIn("relaying", chain("a1", A, "bim-3169", "ship BIM-3169"))
        self.assertIn("relaying", chain("b1", B, "ge-v2", "resume the ge v2 run"))
        # Pane A's session starts first: it must not take the offer pane B made last.
        a2, b2 = start("a2", A), start("b2", B)
        self.assertIsNotNone(a2)
        self.assertIsNotNone(b2)
        self.assertIn("bim-3169.md", a2["systemMessage"])
        self.assertIn("ge-v2.md", b2["systemMessage"])
        self.assertEqual(S.read("a2")["afk"]["goal"], "ship BIM-3169")
        self.assertEqual(S.read("b2")["afk"]["goal"], "resume the ge v2 run")
        self.assertEqual(S.read("a2")["afk"]["run"], "run-bim-3169")
        self.assertEqual(S.read("b2")["afk"]["run"], "run-ge-v2")

    def test_a_pane_with_no_offer_of_its_own_resumes_nothing(self):
        chain("c1", A, "only-a", "goal a")
        # A session starting in pane B, the same project, takes nothing from pane A.
        self.assertIsNone(start("c2", B))
        self.assertIn("only-a.md", start("c3", A)["systemMessage"])

    def test_a_claim_keeps_the_clear_pointer_another_session_left(self):
        chain("d1", A, "pointer-a", "goal a")
        # A session of another pane in the same project ended on a /clear of the user's own.
        latest = os.path.join(DATA, "latest", f"{H.project_key(PROJECT)}.json")
        H.write_json(latest, {"session": "other", "at": time.time(), "reason": "clear"})
        start("d2", A)
        self.assertEqual(H.read_json(latest)["session"], "other")


class Typed(Pane):
    """A pane that records what the driver types, and runs `on_enter` at each Enter."""

    def __init__(self, address, on_enter=lambda: None):
        super().__init__(address)
        self.typed, self.on_enter = [], on_enter

    def clear_input(self):
        return True

    def type_text(self, text):
        self.typed.append(text)
        return True

    def press_enter(self):
        self.on_enter()
        return True


def again(sid):
    """The session `sid`, still there after its relay's /clear, wrote its handover again: its Stop relays."""
    with S.locked(sid) as st:
        return H.relay(st, sid, 0, H.config(), "Carry on.")


class Clock:
    """The driver's wait for the new session, on a fake clock: a sleep moves it on and runs `at` once past each time."""

    def __init__(self, at=None):
        self.now, self.at = 0.0, dict(at or {})

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        for t in sorted(self.at):
            if self.now >= t:
                self.at.pop(t)()


def drive(sid, attempt, pane, clock=None):
    """The relay's driver of `attempt`, typing into `pane`: what it returns, and the events it records."""
    events = []
    clock = clock or Clock()
    wait = H.R.await_confirmation
    args = SimpleNamespace(
        session=sid, attempt=attempt, kill=None, terminal="rex", address=pane.address, message="Carry on.", add_dir=None
    )
    with (
        mock.patch.object(H.time, "sleep"),
        mock.patch.object(TERM, "adapter", lambda *a: pane),
        mock.patch.object(H, "record", lambda event, *a, **k: events.append(event)),
        mock.patch.object(H.R, "await_confirmation", lambda *a, **k: wait(*a, clock=clock, sleep=clock.sleep, **k)),
    ):
        return H.cmd_relay_drive(args), events


class AClearThatDidNotEndTheSession(unittest.TestCase):
    def test_a_second_handover_relays_again(self):
        chain("e1", A, "bim-4440", "ship BIM-4440")
        self.assertEqual(S.read("e1")["relay_outcome"]["attempt"], 1)
        DRIVEN.clear()
        self.assertIn("relaying", again("e1"))
        self.assertIn("--attempt=2", DRIVEN[-1])
        self.assertEqual(S.read("e1")["relay_outcome"]["attempt"], 2)
        self.assertIn("bim-4440.md", start("e2", A)["systemMessage"])

    def test_the_relay_stops_after_its_last_attempt(self):
        chain("f1", A, "stuck", "goal")
        for _ in range(H.RELAY_ATTEMPTS - 1):
            self.assertIn("relaying", again("f1"))
        DRIVEN.clear()
        self.assertIn("halted", again("f1"))
        self.assertEqual(DRIVEN, [])
        self.assertEqual(S.halt_reason(S.read("f1")), "failed")
        # Halted, it never relays again.
        self.assertIsNone(again("f1"))

    def test_a_halted_relay_does_not_relay_again(self):
        chain("g1", A, "limit", "goal")
        with S.locked("g1") as st:
            S.halted(st, "limit", 2)
        DRIVEN.clear()
        self.assertIsNone(again("g1"))
        self.assertEqual(DRIVEN, [])

    def test_a_superseded_driver_exits_without_a_word(self):
        chain("h1", A, "drivers", "goal")
        # Its /clear runs another command, whose handover the relay launches again while this driver waits.
        pane = Typed(A.address, on_enter=lambda: again("h1"))
        code, events = drive("h1", 1, pane)
        # Only the relay launched again records: this driver records no stall and no resume.
        self.assertEqual((code, events), (0, ["relay_retried"]))
        self.assertEqual(pane.typed, ["/clear"])
        # Superseded before it starts, it types nothing.
        late = Typed(A.address)
        self.assertEqual(drive("h1", 1, late), (0, []))
        self.assertEqual(late.typed, [])

    def test_the_halt_ends_the_last_driver_and_its_offer(self):
        chain("j1", A, "capped", "goal")
        for _ in range(H.RELAY_ATTEMPTS - 1):
            again("j1")
        # The last attempt's /clear runs another command too: that handover halts the chain.
        pane = Typed(A.address, on_enter=lambda: again("j1"))
        self.assertEqual(drive("j1", H.RELAY_ATTEMPTS, pane), (0, ["relay_failed"]))
        # The /clear the halt asks the user for starts a chain of its own.
        self.assertIsNone(start("j2", A))

    def test_a_writer_slower_than_the_wait_raises_no_stall(self):
        chain("k1", A, "slow", "goal")

        def handing_over():
            with S.locked("k1") as st:
                S.requested(st)

        # Its /clear runs /handover:trigger, whose writer outlasts the driver's wait before the next attempt.
        pane = Typed(A.address, on_enter=handing_over)
        clock = Clock({H.R.CONFIRM_SECONDS + 60: lambda: again("k1")})
        self.assertEqual(drive("k1", 1, pane, clock), (0, ["relay_retried"]))

    def test_a_relay_whose_new_session_never_answers_stalls(self):
        chain("l1", A, "stalled", "goal")
        clock = Clock()
        self.assertEqual(drive("l1", 1, Typed(A.address), clock), (1, ["relay_stalled"]))
        self.assertEqual(clock.now, H.R.CONFIRM_SECONDS)

    def test_the_current_driver_resumes(self):
        chain("i1", A, "current", "goal")
        again("i1")
        pane = Typed(A.address, on_enter=lambda: H.R.confirm("i1", True))
        code, events = drive("i1", 2, pane)
        self.assertEqual((code, events), (0, ["relay_resumed"]))
        self.assertEqual(pane.typed, ["/clear", "Carry on."])


if __name__ == "__main__":
    unittest.main()

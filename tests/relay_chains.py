"""Two relay chains in one project (scripts/handover.py): each new session resumes the handover and the AFK goal of
its own chain, never the other's.

A Guest-Suite session starts from the guest-environment root whatever repo it changes, so two AFK chains there
share their project. Both hand over within the same minute, each in its own pane; the relay of each must start its
new session from its own handover. The relay is driven through its hooks' functions, its terminal faked per pane:
no session, no terminal, no wait."""

import os
import sys
import tempfile
import time
import unittest

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


if __name__ == "__main__":
    unittest.main()

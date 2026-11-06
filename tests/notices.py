"""Unit tests of the handover plugin's wait for subagent notices (notifications_due in scripts/transcript.py): a
report that came in before the notice of its agent's end waits for that notice, a hand-back report announced by
its notice does not."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import transcript as T

AID = "a9550954fb31329d7"


def notice(aid, handback=False):
    result = (
        f'This agent\'s report was delivered to you as a message from "{aid}" (its SubagentHandback call). '
        "Read it there; it is not repeated here."
        if handback
        else "The report."
    )
    return (
        f"<task-notification>\n<task-id>{aid}</task-id>\n<status>completed</status>\n"
        f"<result>{result}\n</result>\n</task-notification>"
    )


def message(aid, handback=False):
    head = "[Subagent hand-back] The text below is the final report of a subagent." if handback else "Partial."
    return f'Another Claude session sent a message:\n<agent-message from="{aid}">\n{head}\n  1. Yes.\n</agent-message>'


def transcript(*texts):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for t in texts:
            f.write(
                json.dumps({"type": "user", "isSidechain": False, "message": {"role": "user", "content": t}}) + "\n"
            )
    return path


class NoticesDue(unittest.TestCase):
    def test_a_report_before_its_notice_waits_for_the_notice(self):
        self.assertEqual(T.notifications_due(transcript(message(AID))), [AID])

    def test_the_notice_after_the_report_clears_the_wait(self):
        self.assertEqual(T.notifications_due(transcript(message(AID), notice(AID))), [])

    def test_a_hand_back_announced_by_its_notice_is_not_awaited(self):
        self.assertEqual(T.notifications_due(transcript(notice(AID, handback=True), message(AID, handback=True))), [])

    def test_a_message_after_a_plain_notice_still_waits(self):
        # A resumed agent writes again after its first notice: its next notice is still to come.
        self.assertEqual(T.notifications_due(transcript(notice(AID), message(AID))), [AID])

    def test_an_announcement_covers_one_message_only(self):
        texts = (notice(AID, handback=True), message(AID, handback=True), message(AID))
        self.assertEqual(T.notifications_due(transcript(*texts)), [AID])


if __name__ == "__main__":
    unittest.main()

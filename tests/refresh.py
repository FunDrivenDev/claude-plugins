"""Unit tests of the handover plugin's refresh at the session's end (scripts/handover.py): a session that ends on its
closing reply keeps the handover written before it, so the next session loads it at once; one that went on gets it
rewritten."""

import json
import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
DATA = os.path.join(HOME, ".claude", "plugins", "data", "handover-fundrivendev")
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=DATA)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

started = []
H.start_writer = lambda st, sid, cause: started.append((sid, cause))


def assistant(tokens):
    usage = {"input_tokens": tokens, "output_tokens": 0}
    return {"type": "assistant", "message": {"role": "assistant", "content": "ok", "usage": usage}}


def append(path, *entries):
    with open(path, "a") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)


def closed_session(sid, written_at=185_000):
    """A wound-down session whose handover was written at `written_at` and whose closing reply's stop just ran."""
    transcript = os.path.join(HOME, f"{sid}.jsonl")
    append(transcript, {"type": "user", "message": {"role": "user", "content": "go"}}, assistant(written_at))
    os.makedirs(os.path.join(DATA, "sessions"), exist_ok=True)
    st = {
        "transcript": transcript,
        "wind_down": True,
        "closing_reply": True,
        "written": {"ok": True, "tokens": written_at},
        "reply_offset": os.path.getsize(transcript),
    }
    H.write_json(H.state_path(sid), st)
    return transcript


def end(sid, transcript):
    started.clear()
    H.on_session_end({"session_id": sid, "transcript_path": transcript, "reason": "clear", "cwd": HOME})
    return [cause for s, cause in started if s == sid]


class RefreshAtTheEnd(unittest.TestCase):
    def test_the_closing_reply_alone_rewrites_nothing(self):
        transcript = closed_session("reply")
        # The reply reaches the transcript after its Stop hook: 2.3K tokens, past refresh_tokens.
        append(transcript, assistant(187_300), {"type": "system", "subtype": "stop_hook_summary"})
        self.assertEqual(end("reply", transcript), [])

    def test_a_prompt_after_the_reply_rewrites_the_handover(self):
        transcript = closed_session("prompt")
        append(transcript, assistant(187_300), {"type": "user", "message": {"role": "user", "content": "one more"}})
        append(transcript, assistant(198_000))
        self.assertEqual(end("prompt", transcript), ["session_end"])

    def test_a_failed_handover_is_written_at_the_end(self):
        transcript = closed_session("failed")
        with H.locked_state("failed") as st:
            st["written"] = {"ok": False}
        append(transcript, assistant(187_300))
        self.assertEqual(end("failed", transcript), ["session_end"])

    def test_without_a_closing_reply_the_rule_is_unchanged(self):
        transcript = closed_session("no-reply")
        with H.locked_state("no-reply") as st:
            st.pop("reply_offset")
        append(transcript, assistant(187_300))
        self.assertEqual(end("no-reply", transcript), ["session_end"])


if __name__ == "__main__":
    unittest.main()

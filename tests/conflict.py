"""Unit tests of the handover plugin's check of auto-compaction against its thresholds (scripts/handover.py): a
compaction window that fires before the trigger gets a warning, one that leaves room or is turned off does not."""

import json
import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=os.path.join(HOME, "data"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H

CFG = {"suggest": 200_000, "trigger": 250_000, "reserve": 33_000}
PROJECT = os.path.join(HOME, "project")


def settings(path, **values):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(values, f)


def user(**values):
    settings(os.path.join(HOME, ".claude", "settings.json"), **values)


class CompactionConflict(unittest.TestCase):
    def setUp(self):
        for path in (
            os.path.join(HOME, ".claude.json"),
            os.path.join(PROJECT, ".claude", "settings.json"),
            os.path.join(PROJECT, ".claude", "settings.local.json"),
        ):
            if os.path.exists(path):
                os.remove(path)

    def test_a_window_compacting_before_the_trigger_warns(self):
        user(autoCompactWindow=250_000)
        warning = H.compaction_conflict(CFG, PROJECT)
        self.assertIn("fires near 217K (autoCompactWindow 250K), before trigger_tokens at 250K", warning)
        self.assertIn("Set autoCompactWindow above 283K", warning)

    def test_an_unset_window_is_claude_codes_default(self):
        user()
        self.assertIn("near 167K (autoCompactWindow unset)", H.compaction_conflict(CFG, PROJECT))

    def test_a_window_with_room_says_nothing(self):
        user(autoCompactWindow=500_000)
        self.assertIsNone(H.compaction_conflict(CFG, PROJECT))

    def test_the_local_settings_win(self):
        user(autoCompactWindow=500_000)
        settings(os.path.join(PROJECT, ".claude", "settings.local.json"), autoCompactWindow=250_000)
        self.assertIsNotNone(H.compaction_conflict(CFG, PROJECT))

    def test_auto_compaction_off_says_nothing(self):
        user(autoCompactWindow=250_000)
        settings(os.path.join(HOME, ".claude.json"), autoCompactEnabled=False)
        self.assertIsNone(H.compaction_conflict(CFG, PROJECT))

    def test_without_a_trigger_the_suggestion_is_checked(self):
        user(autoCompactWindow=200_000)
        warning = H.compaction_conflict({**CFG, "trigger": 0}, PROJECT)
        self.assertIn("before suggest_tokens at 200K", warning)


if __name__ == "__main__":
    unittest.main()

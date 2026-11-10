"""Unit tests of the working directory a relayed session is told to work from (handover_workdir and
workdir_notice in scripts/handover.py): the handover's Working directory section names it, the session is told
to `cd` there when it starts elsewhere, and to go to the main checkout when the directory is gone; a session started
at a stay root stays there and reaches the directory by absolute path."""

import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
for key in ("CLAUDE_CONFIG_DIR", "CLAUDE_PLUGIN_OPTION_STAY_ROOTS"):
    os.environ.pop(key, None)
os.environ.update(HOME=HOME, CLAUDE_PLUGIN_DATA=os.path.join(HOME, "data"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "handover", "scripts"))

import handover as H
import writer_prompt as P

WORKTREE = os.path.join(HOME, "repo.worktrees", "task")
os.makedirs(WORKTREE)
GONE = os.path.join(HOME, "repo.worktrees", "removed")


def handover(section):
    return (
        f"# Handover: x\n\n## Goal\nShip `/not/this`.\n\n## Working directory\n{section}\n\n## State\n- `/nor/this`\n"
    )


class Workdir(unittest.TestCase):
    def test_the_template_asks_for_the_section(self):
        self.assertIn("## Working directory", P.template())

    def test_the_section_s_backticked_path(self):
        self.assertEqual(H.handover_workdir(handover(f"`{WORKTREE}/`")), WORKTREE)

    def test_a_bare_path_in_a_sentence(self):
        self.assertEqual(H.handover_workdir(handover(f"The main checkout, {WORKTREE}.")), WORKTREE)

    def test_no_section_no_path(self):
        self.assertIsNone(H.handover_workdir("# Handover: x\n\n## Goal\nShip `/not/this`.\n"))
        self.assertIsNone(H.handover_workdir(handover("Unknown.")))

    def test_a_session_elsewhere_is_told_to_cd(self):
        notice = H.workdir_notice(handover(f"`{WORKTREE}`"), HOME)
        self.assertIn(f"`cd {WORKTREE}`", notice)
        self.assertIn(HOME, notice)

    def test_a_directory_outside_the_start_one_is_added_by_the_relay(self):
        start = os.path.join(HOME, "repo")
        os.makedirs(start, exist_ok=True)
        notice = H.workdir_notice(handover(f"`{WORKTREE}`"), start, added=True)
        self.assertIn("`/add-dir`", notice)
        self.assertIn(f"`cd {WORKTREE}`", notice)

    def test_a_directory_outside_the_start_one_without_the_relay_s_add_dir(self):
        start = os.path.join(HOME, "repo")
        os.makedirs(start, exist_ok=True)
        notice = H.workdir_notice(handover(f"`{WORKTREE}`"), start)
        self.assertIn("does not hold", notice)
        self.assertIn(f"`git -C {WORKTREE}`", notice)
        self.assertNotIn(f"`cd {WORKTREE}`", notice)

    def test_outside(self):
        self.assertFalse(H.outside(WORKTREE, HOME))
        self.assertFalse(H.outside(HOME, HOME + "/"))
        self.assertTrue(H.outside(WORKTREE, os.path.join(HOME, "repo")))
        self.assertTrue(H.outside(HOME + "x", HOME))

    def test_a_session_already_there_is_told_nothing(self):
        self.assertEqual(H.workdir_notice(handover(f"`{WORKTREE}`"), WORKTREE + "/"), "")

    def test_a_removed_directory_elsewhere_sends_to_the_main_checkout(self):
        notice = H.workdir_notice(handover(f"`{GONE}`"), WORKTREE)
        self.assertIn("no longer exists", notice)
        self.assertIn("main checkout", notice)
        self.assertNotIn(f"`cd {GONE}`", notice)

    def test_a_removed_worktree_inside_the_start_directory_keeps_the_session_there(self):
        notice = H.workdir_notice(handover(f"`{GONE}`"), HOME)
        self.assertIn(f"It sat inside {HOME}, where this session started: work from there.", notice)
        self.assertNotIn("main checkout", notice)

    def test_a_session_at_a_stay_root_stays_and_reaches_the_worktree_by_path(self):
        app = os.path.join(HOME, "apps", "worktree-api-x")
        os.makedirs(app, exist_ok=True)
        notice = H.workdir_notice(handover(f"`{app}`"), HOME, added=True, roots=[HOME])
        self.assertIn("where it stays", notice)
        self.assertIn(f"`git -C {app}`", notice)
        self.assertIn("`ge -s <service> -w <branch>`", notice)
        self.assertNotIn(f"`cd {app}`", notice)
        self.assertNotIn("/add-dir", notice)

    def test_a_stay_root_session_reaches_a_sibling_repo_by_path_after_the_relay_s_add_dir(self):
        start = os.path.join(HOME, "repo")
        os.makedirs(start, exist_ok=True)
        notice = H.workdir_notice(handover(f"`{WORKTREE}`"), start, added=True, roots=[start])
        self.assertIn(f"`git -C {WORKTREE}`", notice)
        self.assertIn("`/add-dir`", notice)
        self.assertNotIn(f"`cd {WORKTREE}`", notice)
        self.assertNotIn("`ge -s", notice)
        loop = H.workdir_notice(handover(f"`{WORKTREE}`"), start, roots=[start])
        self.assertIn(f"`/add-dir {WORKTREE}`", loop)
        self.assertNotIn(f"`cd {WORKTREE}`", loop)

    def test_a_stay_root_session_stays_when_the_worktree_is_gone(self):
        start = os.path.join(HOME, "repo")
        os.makedirs(start, exist_ok=True)
        for cwd in (HOME, start):
            notice = H.workdir_notice(handover(f"`{GONE}`"), cwd, roots=[cwd])
            self.assertIn("no longer exists", notice)
            self.assertIn("where it stays", notice)
            self.assertNotIn("`cd", notice)

    def test_a_stay_root_session_already_there_is_told_nothing(self):
        self.assertEqual(H.workdir_notice(handover(f"`{HOME}`"), HOME, roots=[HOME]), "")

    def test_the_stay_roots_option_defaults_to_guest_environment(self):
        self.assertEqual(
            H.stay_roots(lambda key: "~/Code/Guest-Suite/guest-environment, /x"),
            [os.path.realpath(os.path.join(HOME, "Code/Guest-Suite/guest-environment")), "/x"],
        )
        self.assertEqual(H.stay_roots(), [os.path.realpath(os.path.join(HOME, "Code/Guest-Suite/guest-environment"))])
        self.assertEqual(H.stay_roots(lambda key: ","), [])

    def test_the_ge_hint_only_for_an_app_under_the_root_s_apps(self):
        pkg = os.path.join(HOME, "pkg")
        os.makedirs(pkg, exist_ok=True)
        notice = H.workdir_notice(handover(f"`{pkg}`"), HOME + "/", roots=[HOME])
        self.assertIn(f"`git -C {pkg}`", notice)
        self.assertNotIn("`ge -s", notice)

    def test_an_old_handover_without_the_section_is_told_nothing(self):
        self.assertEqual(H.workdir_notice("# Handover: x\n", HOME), "")


if __name__ == "__main__":
    unittest.main()

"""Runs session-mods' TOPIC_NOTES script (plugins/session-mods/hooks/situation.ts) with a real shell on a notes tree:
the mod tests cannot spawn a process, so the script's own behaviour is checked here."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

SOURCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "session-mods", "hooks", "situation.ts"
)


def script():
    """The template literal's text, as JavaScript reads it: no `${`, so unescaping `\\` and `` \\` `` is enough."""
    with open(SOURCE) as f:
        body = re.search(r"export const TOPIC_NOTES = `(.*?)(?<!\\)`", f.read(), re.DOTALL).group(1)
    assert "${" not in body
    return re.sub(r"\\(.)", r"\1", body)


class TopicNotes(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)

    def put(self, path, text):
        full = os.path.join(self.home, "Notes", "claude", path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def run_for(self, topic):
        env = dict(os.environ, HOME=self.home)
        return subprocess.run(["sh", "-c", script(), "sh", topic], env=env, capture_output=True, text=True, check=False)

    def paths(self, out):
        return sorted(chunk.split("\t", 1)[0][len(self.home) :] for chunk in out.split("\x1e")[1:])

    def test_front_matter_names_the_topic(self):
        self.put("plans/a brief.md", '---\nkind: plan\ntopic: "spj"\n---\n# A\n')
        self.put("decisions-register/r.md", "---\nkind: decision-register\ntopic: spj\n---\n- **D01**\n")
        self.put("plans/other.md", "---\ntopic: spj-2\n---\n")
        self.put("plans/late.md", "---\ntopic: x\n---\n" + "line\n" * 30 + "topic: spj\n")
        out = self.run_for("spj")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(
            self.paths(out.stdout), ["/Notes/claude/decisions-register/r.md", "/Notes/claude/plans/a brief.md"]
        )
        self.assertIn("- **D01**", out.stdout)

    def test_a_dot_in_the_topic_is_literal(self):
        self.put("plans/a.md", "---\ntopic: v1x2\n---\n")
        self.assertEqual(self.run_for("v1.2").returncode, 1)

    def test_none_exits_1(self):
        self.put("plans/a.md", "---\ntopic: spj\n---\n")
        self.assertEqual(self.run_for("none").returncode, 1)
        shutil.rmtree(os.path.join(self.home, "Notes"))
        self.assertEqual(self.run_for("spj").returncode, 1)


if __name__ == "__main__":
    unittest.main()

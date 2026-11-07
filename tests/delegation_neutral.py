"""The delegation plugin ships to anyone who installs it: it must name no person, company, tracker or
internal tool. Fails on any such term in a file, a file name or a folder name under plugins/delegation/."""

import pathlib
import re
import sys
import tempfile
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "plugins" / "delegation"
# Names, case-insensitive; prefixes of internal skills and tickets, case-sensitive at a word start.
TERMS = re.compile(
    r"(?i:rlvdx|rapha[eë]l|louvradoux|itsaplan|fundrivenos|1password|guest|bibim)|\bBIM-|\bgs-",
)


def scan(root):
    """Each term under root, in a file's text, its name or the name of a folder on its path."""
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        text = path.read_text(errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for m in TERMS.finditer(line):
                hits.append(f"{path.relative_to(root)}:{n}: {m.group(0)}")
        rel = path.relative_to(root)
        if TERMS.search(path.name):
            hits.append(f"{rel}: in the file name")
        hits.extend(f"{rel}: in the folder name {part}" for part in rel.parts[:-1] if TERMS.search(part))
    return hits


class Neutral(unittest.TestCase):
    def test_no_personal_or_work_term_in_the_plugin(self):
        self.assertEqual(scan(PLUGIN), [], "personal or work terms in plugins/delegation")

    def test_a_folder_name_with_a_term_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "gs-review").mkdir()
            (root / "gs-review" / "notes.txt").write_text("neutral\n")
            self.assertEqual(scan(root), ["gs-review/notes.txt: in the folder name gs-review"])

    def test_the_pattern_catches_each_term(self):
        for word in ("rlvdx", "Raphaël", "Itsaplan", "fundrivenOS", "1Password", "Guest Suite", "bibim", "BIM-12"):
            self.assertRegex(word, TERMS)
        self.assertRegex("run gs-review-and-fix", TERMS)
        for word in ("args-file", "FunDrivenDev", "bim-"):
            self.assertNotRegex(word, TERMS)


if __name__ == "__main__":
    sys.exit(unittest.main())

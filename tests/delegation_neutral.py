"""The delegation plugin ships to anyone who installs it: it must name no person, company, tracker or
internal tool. Fails on any such term in a file under plugins/delegation/."""

import pathlib
import re
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parent.parent / "plugins" / "delegation"
# Names, case-insensitive; prefixes of internal skills and tickets, case-sensitive at a word start.
TERMS = re.compile(
    r"(?i:rlvdx|rapha[eë]l|louvradoux|itsaplan|fundrivenos|1password|guest|bibim)|\bBIM-|\bgs-",
)


class Neutral(unittest.TestCase):
    def test_no_personal_or_work_term_in_the_plugin(self):
        hits = []
        for path in sorted(p for p in PLUGIN.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            text = path.read_text(errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                for m in TERMS.finditer(line):
                    hits.append(f"{path.relative_to(PLUGIN)}:{n}: {m.group(0)}")
            if TERMS.search(path.name):
                hits.append(f"{path.relative_to(PLUGIN)}: in the file name")
        self.assertEqual(hits, [], "personal or work terms in plugins/delegation")

    def test_the_pattern_catches_each_term(self):
        for word in ("rlvdx", "Raphaël", "Itsaplan", "fundrivenOS", "1Password", "Guest Suite", "bibim", "BIM-12"):
            self.assertRegex(word, TERMS)
        self.assertRegex("run gs-review-and-fix", TERMS)
        for word in ("args-file", "FunDrivenDev", "bim-"):
            self.assertNotRegex(word, TERMS)


if __name__ == "__main__":
    sys.exit(unittest.main())

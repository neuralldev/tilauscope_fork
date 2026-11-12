# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""What is left of Artisan's code in the shared core and the tablet (android/LICENSING-SPEC.md).

DERIVED lists the files that still carry Artisan's copyright. Each lot of the spec
removes entries; none is ever added. Once it is empty, no Artisan line remains.
"""
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[2]
SCANNED = (("src/tilaucore", ("*.py",)), ("android/python", ("*.py",)),
           ("android/app/src/main", ("*.kt", "*.js", "*.html")))
ARTISAN = re.compile(r"Artisan team|Marko Luther|derived from Artisan", re.IGNORECASE)
DERIVED: set[str] = set()


def carrying_artisan() -> set[str]:
    found = set()
    for folder, patterns in SCANNED:
        for pattern in patterns:
            for path in (REPO / folder).rglob(pattern):
                if "graphify-out" in path.parts or "__pycache__" in path.parts:
                    continue
                if ARTISAN.search(path.read_text(encoding="utf-8", errors="replace")):
                    found.add(path.relative_to(REPO).as_posix())
    return found


class LicenceBoundaryTests(unittest.TestCase):
    def test_artisan_code_only_where_listed(self):
        self.assertEqual(carrying_artisan() - DERIVED, set(), "Artisan's copyright outside DERIVED")

    def test_a_cleaned_file_leaves_the_list(self):
        self.assertEqual(DERIVED - carrying_artisan(), set(), "no Artisan line left: remove it from DERIVED")


if __name__ == "__main__":
    unittest.main()

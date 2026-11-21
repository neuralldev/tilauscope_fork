# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The tablet reads the files of the desktop version in use (audit 2026-11-21, P2-01).

The tablet stayed at 4.3 when the desktop went to 4.4: every .tilaucoffee a 4.4 desktop wrote,
shared, moved or published to the library, read as "needs a newer TilauScope".
"""
from pathlib import Path
import re
import tempfile
import unittest

from tilaucore import coffee_share as core
from tilauscope_mobile import alog, coffee_share
from test_coffee_share import write

DESKTOP_INIT = Path(__file__).resolve().parents[2] / "src" / "artisanlib" / "__init__.py"


def desktop_version() -> str:
    """Read as text: the tablet core never imports Artisan."""
    return re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", DESKTOP_INIT.read_text(encoding="utf-8")).group(1)


class VersionTests(unittest.TestCase):
    def test_the_tablet_reads_and_writes_the_desktop_s_version(self):
        self.assertEqual(coffee_share.VERSION, desktop_version())
        self.assertEqual(alog.TILAUSCOPE_VERSION, desktop_version())

    def test_a_package_from_the_current_desktop_opens_on_the_tablet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(Path(folder) / "catuai.tilaucoffee", version=desktop_version(), build=4)
            package = core.read_package(path, version=coffee_share.VERSION, build=coffee_share.READS_BUILD)
            self.assertEqual(package.bean.name, "Catuai")


if __name__ == "__main__":
    unittest.main()

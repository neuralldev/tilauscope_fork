# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""An alarm list is saved whole or not at all (audit 2026-11-21, P2-07).

Every edit rewrote the active list in place: the app killed or the battery flat during the write left
it empty or cut, and every roast after ran it so, or failed to read it.
"""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tilaucore.alarms import read_alrm
from tilauscope_mobile.alarms import AlarmLists
from test_alarms import MINIMAL


class AlarmListSaveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lists = AlarmLists(directory.name)

    def _a_list(self) -> tuple[str, str]:
        return self.lists.add("Mine", MINIMAL), MINIMAL

    def test_a_save_cut_short_keeps_the_previous_list(self):
        name, text = self._a_list()
        with mock.patch("os.fsync", side_effect=OSError("the battery went flat")):
            with self.assertRaises(OSError):
                self.lists.save(name, read_alrm(text)[:1])
        self.assertEqual(len(self.lists.rows(name)), len(read_alrm(text)))
        self.assertEqual([p.name for p in Path(self.lists.folder).iterdir()], [f"{name}.alrm"]) # no leftover

    def test_an_added_list_cut_short_leaves_nothing_half_written(self):
        _, text = self._a_list()
        with mock.patch("os.fsync", side_effect=OSError("the app was killed")):
            with self.assertRaises(OSError):
                self.lists.add("Other", text)
        self.assertFalse((Path(self.lists.folder) / "Other.alrm").exists())


if __name__ == "__main__":
    unittest.main()

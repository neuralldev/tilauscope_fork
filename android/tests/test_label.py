# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roast label: the lines of the desktop's 30 mm label for the roast just over."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile.demo import Demo

UUID = "2d1a0dd8-2f15-4cb5-a8c9-41cfb583bb49"


class LabelTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "beancave"))
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "Barazilie", "uuid": UUID, "country": "Brazil",
                                                            "farm": "Eloir", "process": "Anaerobic Fermentation",
                                                            "altitude": 800, "flavour_notes": "peach"}]}), "beancave.json")
        self.demo.choose_coffee(UUID)

    def roast(self, milestones):
        self.demo.start()
        self.demo.mark("charge")
        for milestone in milestones:
            self.demo.advance(120)
            self.demo.mark(milestone)
        self.demo.stop()

    def test_the_label_says_what_the_desktops_30_mm_label_says(self):
        self.roast(("dry_end", "first_crack", "drop"))
        self.assertEqual(json.loads(self.demo.snapshot())["label_coffee"], "Barazilie")
        lines = json.loads(self.demo.roast_label())
        self.assertEqual((lines["origin_farm"], lines["bean"]), ("Brazil Eloir", "Beans: Barazilie"))
        self.assertEqual(lines["details"], [["Process", "Anaerobic Fermentation"], ["Altitude", "800 m"]]) # no density, no score
        self.assertEqual(lines["notes"], "F: peach")

    def test_a_listed_roast_has_the_same_label(self):
        self.roast(("dry_end", "first_crack", "drop"))
        just_over = json.loads(self.demo.roast_label())
        name = Path(self.demo.export_alog(str(self.dir / "roasts"))).name
        self.assertEqual(json.loads(self.demo.roast_label(json.dumps({"origin": "tablet", "name": name}))), just_over)

    def test_no_label_without_the_milestones(self):
        self.roast(("dry_end",))
        with self.assertRaises(ValueError):
            self.demo.roast_label()


if __name__ == "__main__":
    unittest.main()

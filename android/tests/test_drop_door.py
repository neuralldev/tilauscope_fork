# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The drop door's contact on TilauAmbient marks DROP on the tablet as on the desktop (wiki/Drop-Door-Contact-Spec.md)."""
import json
from pathlib import Path
import tempfile
import unittest

from tilaucore.drop_door import DoorFrame, build_frame
from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from test_automation import PROFILE


def frame(opened: bool, count: int, since_ms: int | None = None) -> str:
    return build_frame(DoorFrame(opened, count, since_ms)).hex()


class DropDoorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        # automatic DROP off: the door marks it all the same
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"},
                                    "auto_marks": ["charge"]})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "auto.alog").write_text(repr(PROFILE), encoding="utf-8")
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.demo._roast_plan = lambda: {"End of Dry Temp": 160.0, "First Crack Temp": 185.0}
        self.demo.simulate(json.dumps({"origin": "computer", "name": "auto.alog"}))
        self.seq = 0

    def read(self, data: str, age_ms: int = 0):
        self.seq += 1
        self.demo.door_frame(data, self.seq, age_ms)

    def run_to(self, seconds):
        while self.demo.now < seconds:
            self.demo.advance(1)

    def test_the_door_marks_drop_on_the_sample_it_opened_with_automatic_drop_off(self):
        self.read(frame(False, 0)) # the probe connected, door shut: armed
        self.demo.start("plan")
        self.run_to(300)
        self.assertEqual(self.demo.session.milestones, {"charge": 30})
        self.read(frame(True, 1, 2000), age_ms=500) # opened 2 s before the probe was read, read 0.5 s ago
        self.run_to(302)
        self.assertIn(self.demo.session.milestones["drop"], (297, 298))

    def test_the_previous_roast_s_opening_does_not_drop_this_one(self):
        self.read(frame(False, 0))
        self.read(frame(True, 1, 0)) # the last roast's drop
        self.read(frame(False, 1, 30_000)) # door shut again before CHARGE
        self.demo.start("plan")
        self.run_to(400)
        self.assertNotIn("drop", self.demo.session.milestones)
        self.read(frame(True, 2, 0))
        self.run_to(402)
        self.assertIn(self.demo.session.milestones["drop"], (400, 401))

    def test_a_contact_never_seen_closed_marks_nothing(self):
        self.read(frame(True, 0)) # nothing wired: the pull-up reads open
        self.demo.start("plan")
        self.run_to(300)
        self.read(frame(True, 1, 0))
        self.run_to(305)
        self.assertNotIn("drop", self.demo.session.milestones)

    def test_drop_touched_first_leaves_the_door_nothing_to_mark(self):
        self.read(frame(False, 0))
        self.demo.start("plan")
        self.run_to(300)
        self.demo.mark("drop")
        drop = self.demo.session.milestones["drop"]
        self.read(frame(True, 1, 0))
        self.run_to(305)
        self.assertEqual(self.demo.session.milestones["drop"], drop)

    def test_the_header_pill_says_closed_open_or_nothing(self):
        door = lambda: json.loads(self.demo.snapshot())["door"]
        self.assertIsNone(door()) # no probe heard
        self.read(frame(True, 0))
        self.assertIsNone(door()) # never seen closed: no contact
        self.read(frame(False, 0))
        self.assertEqual(door(), "closed")
        self.read(frame(True, 1, 0))
        self.demo.advance(1)
        self.assertEqual(door(), "open")
        self.demo.clock = lambda: 1e9 # the probe silent for longer than a reading lasts
        self.assertIsNone(door())

    def test_a_damaged_frame_is_refused(self):
        with self.assertRaises(ValueError):
            self.demo.door_frame("5555", 1, 0)


if __name__ == "__main__":
    unittest.main()

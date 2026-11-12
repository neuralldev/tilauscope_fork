# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A simulated roaster that reacts (SIM-SPEC S3): the replayed BT answers the burner after CHARGE."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo

from test_automation import PROFILE


class ReactingRoasterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "live.alog").write_text(repr(PROFILE), encoding="utf-8")
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.demo.simulate(json.dumps({"origin": "computer", "name": "live.alog"}))

    def run_to(self, seconds):
        while self.demo.now < seconds:
            self.demo.advance(1)

    def bt_gap(self):
        """The simulated BT minus the recorded one, now."""
        return self.demo.session.samples[-1].bt_c - PROFILE["temp2"][int(self.demo.now)]

    def test_twenty_burner_points_less_bring_the_curve_down_from_the_recorded_one(self):
        self.demo.start()
        self.run_to(31)
        self.demo.mark("charge")
        self.run_to(100)
        self.assertEqual(self.bt_gap(), 0.0) # the levers as recorded: the recorded curve
        self.demo.set_lever("burner", self.demo.levers["burner"] - 20)
        self.run_to(250)
        self.assertLess(self.bt_gap(), -10.0) # 8 °C/min less once felt, over two minutes

    def test_the_turning_point_is_on_the_curve(self):
        self.demo.start()
        self.run_to(31)
        self.demo.mark("charge")
        self.assertIsNone(json.loads(self.demo.snapshot())["tp"]) # not before BT has turned up
        self.run_to(140)
        tp = json.loads(self.demo.snapshot())["tp"]
        self.assertEqual((tp["s"], tp["c"]), (91.0, 90.2)) # the middle of the profile's flat bottom (90 °C at 90 s)
        self.demo.unmark() # CHARGE undone: no turning point any more
        self.assertIsNone(json.loads(self.demo.snapshot())["tp"])

    def test_nothing_reacts_before_charge(self):
        self.demo.start()
        self.demo.set_lever("burner", 0)
        self.run_to(25)
        self.assertEqual(self.bt_gap(), 0.0)


if __name__ == "__main__":
    unittest.main()

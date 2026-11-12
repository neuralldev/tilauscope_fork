# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""TilauPID on the tablet (PREHEAT-SPEC P2): the desktop's controller on the roaster's readings."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo


class PreheatTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2", "preheat_on": True,
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        self.demo = Demo(str(self.dir / "session.journal"), config, str(self.dir / "beancave"))
        self.demo.setup = {"preheat_target": 176.0}
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]
        self.drum, self.burner, self.lag = 45.0, 0, [0, 0, 0, 0]

    def commands(self):
        return json.loads(self.demo.take_commands())

    def run_seconds(self, seconds, *, readings=True):
        """The roaster: its burner follows the OT1 commands, the drum follows the burner."""
        for _ in range(seconds):
            for command in self.commands():
                if command.startswith("OT1,"):
                    self.burner = int(command[4:])
            self.lag = self.lag[1:] + [self.burner]
            # About 30 °C/min at 80 % from cold; 176 °C held near 37 % (the default hold power).
            self.drum += 0.81 * (self.lag[0] / 100) ** 2 - 0.00071 * (self.drum - 20)
            self.clock[0] += 1
            if readings:
                self.demo.link_reading(json.dumps({"bt": round(self.drum, 1), "et": round(self.drum - 12, 1),
                                                   "burner": self.burner, "air": self.demo.levers["air"]}))
            self.demo.advance(1)
        for command in self.commands(): # what the last second sent
            if command.startswith("OT1,"):
                self.burner = int(command[4:])

    def start(self):
        self.demo.start()
        self.demo.link_state(json.dumps({"state": "connected"}))

    def preheat(self):
        return json.loads(self.demo.snapshot())["preheat"]

    def test_the_preheat_climbs_to_its_target_and_is_learned_from_at_charge(self):
        self.start()
        self.run_seconds(30)
        self.assertEqual((self.preheat()["state"], self.burner), ("climb", 80)) # the 80 % ceiling
        self.run_seconds(1200)
        self.assertEqual(self.preheat()["state"], "arrived")
        self.assertLessEqual(abs(self.drum - 176.0), 2.0)
        self.demo.mark("charge")
        self.assertFalse(self.demo.preheat.active)
        learned = json.loads((self.dir / "preheat_learning.json").read_text())
        self.assertTrue(any(key.endswith("/p_ss") for key in learned)) # the hold power of this target
        self.run_seconds(2)
        self.demo.stop()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertEqual((data["tilau_preheat_sv_c"], data["pidSource"]), (176.0, 1))
        self.assertTrue(any(s.startswith("S3:") for s in data["specialeventsStrings"])) # read as TilauPID's

    def test_the_link_still_connecting_at_start_never_trips_the_preheat(self):
        self.demo.start()
        self.run_seconds(10, readings=False) # connecting, then verifying the burner at 0
        self.assertIsNone(self.preheat()["fault"])
        self.assertNotIn("OFF", self.commands())
        self.demo.link_state(json.dumps({"state": "connected"}))
        self.run_seconds(4, readings=False) # the roaster's first readings come 2 to 3 s after
        self.assertIsNone(self.preheat()["fault"])
        self.run_seconds(30)
        self.assertEqual((self.preheat()["state"], self.burner), ("climb", 80))

    def test_touching_the_burner_pauses_until_resumed(self):
        self.start()
        self.run_seconds(20)
        self.demo.set_lever("burner", 50)
        self.assertEqual(self.preheat()["state"], "paused")
        self.run_seconds(10)
        self.assertEqual(self.burner, 50) # the operator's value holds
        self.demo.resume_preheat()
        self.run_seconds(5)
        self.assertEqual(self.preheat()["state"], "climb")
        self.assertGreater(self.burner, 50) # TilauPID has it again

    def test_lost_readings_stop_the_preheat_safely(self):
        self.start()
        self.run_seconds(40)
        self.run_seconds(6, readings=False)
        self.assertEqual(self.preheat()["state"], "fault")
        self.assertEqual(self.burner, 0)
        self.assertEqual(self.demo.machine_log[-6:], ["CLDN,ON", "OT2,75", "OT3,80", "UNTIL_BT_BELOW,50", "EVT,9", "OFF"]) # cooled first
        self.assertIsNone(self.demo.session.preheat_sv_c) # not a guided preheat for the learning


if __name__ == "__main__":
    unittest.main()

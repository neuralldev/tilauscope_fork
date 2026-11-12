# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Whole roasts on the virtual Skywalker (virtual_roaster.py): what the operator would try on the machine."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo

from virtual_roaster import Bench

TARGET_C = 200.0
HEATER_MAX = 80 # the operator's hardware-preservation ceiling


class VirtualRoasterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2", "preheat_on": True,
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.bench = Bench(self.demo)
        self.roaster = self.bench.roaster

    def start(self, target=TARGET_C):
        self.demo.setup = {**(self.demo.setup or {}), "preheat_target": target}
        return self.bench.do("start", "hand")

    def preheated(self):
        self.start()
        snap = self.bench.run(900, until=lambda s: (s.get("preheat") or {}).get("state") == "arrived")
        self.assertEqual(snap["preheat"]["state"], "arrived", "the preheat never reached its target")
        return snap

    def roasted_and_ended(self):
        self.preheated()
        self.bench.do("mark", "charge")
        self.bench.do("set_lever", "burner", 70)
        self.bench.run(240)
        self.bench.do("mark", "drop")
        self.bench.do("stop")

    def test_the_preheat_brings_the_roaster_to_its_target_under_the_ceiling(self):
        self.preheated()
        self.assertGreater(max(self.bench.burners), 0)
        self.assertLessEqual(max(self.bench.burners), HEATER_MAX)
        self.assertLess(abs(self.roaster.bt - TARGET_C), 10.0)

    def test_end_roast_cools_the_beans_then_stops_the_roaster(self):
        self.roasted_and_ended()
        self.assertEqual(self.roaster.state, "cooling")
        self.assertFalse(self.roaster.stopped) # never stopped hot
        self.assertEqual(self.roaster.burner, 0)
        self.bench.run(900, until=lambda s: self.roaster.state == "idle")
        self.assertEqual(self.roaster.state, "idle")
        self.assertTrue(self.roaster.stopped)
        self.assertLess(self.roaster.bt, 50.0)

    def test_back_to_back_the_next_preheat_heats_the_cooling_roaster(self):
        self.roasted_and_ended()
        self.bench.run(20) # cooling
        self.bench.do("reset")
        cooled = self.roaster.bt
        received = len(self.roaster.received)
        self.start()
        self.bench.run(30)
        orders = self.roaster.received[received:]
        self.assertIn("CLDN,OF", orders)
        self.assertNotIn("OFF", orders) # the cooling roaster is taken, never stopped
        self.assertTrue(any(o.startswith("OT1,") and int(o.split(",")[1]) > 0 for o in orders), orders)
        self.assertGreater(self.roaster.bt, cooled) # heating again

    def test_a_dropped_link_never_brings_the_heat_back_by_itself(self):
        self.preheated()
        self.bench.do("mark", "charge")
        self.bench.do("set_lever", "burner", 70)
        self.bench.do("set_lever", "air", 50)
        self.bench.run(30)
        self.roaster.drop(away_s=5)
        snap = self.bench.run(40)
        self.assertEqual(snap["link"]["state"], "connected")
        self.assertTrue(snap["link"]["recovered"])
        self.assertEqual(self.roaster.burner, 0) # held at 0 until the operator raises it
        self.assertEqual(self.roaster.air, 50) # the mechanical state again
        self.bench.do("set_lever", "burner", 60)
        self.bench.run(2)
        self.assertEqual(self.roaster.burner, 60)

    def test_a_preheat_cut_by_a_dropped_link_waits_then_resumes(self):
        self.start()
        self.bench.run(20)
        self.roaster.drop(away_s=5)
        snap = self.bench.run(15)
        self.assertEqual(snap["preheat"]["state"], "paused")
        self.assertEqual(self.roaster.burner, 0)
        self.bench.do("resume_preheat")
        self.bench.run(5)
        self.assertGreater(self.roaster.burner, 0)



GR2 = {"name": "74110 GR2", "uuid": "a82364a8-e9ad-447c-a3d8-5f49111dc3ee", "process": "Natural / Dry Process",
       "country": "Ethiopia", "varieties": "74110", "weight_left": 2000.0, "density": 700.0, "last_humidity": 10.5}


class AutoOnTheVirtualRoasterTests(VirtualRoasterTests):
    """AUTO (GUIDED-SPEC G4) from START to the cooling, on the machine's own link."""

    def auto_roast(self, touch_at=None):
        self.demo.cave.replace(json.dumps({"green_beans": [GR2]}), "beancave.json")
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        self.demo.set_plan_choice(json.dumps({"plan_level": "Medium", "roast_destination": "espresso"}))
        self.demo.setup = {**self.demo.setup, "preheat_target": 120.0}
        self.bench.do("start", "auto")
        self.bench.run(900, until=lambda s: (s.get("preheat") or {}).get("state") == "arrived")
        self.bench.do("mark", "charge")
        if touch_at is not None:
            self.bench.run(touch_at)
            self.bench.do("set_lever", "burner", 40)
            self.bench.run(2)
            return
        for _ in range(1500): # a crash pauses AUTO: the operator follows its message, then resumes with the chip
            snap = self.bench.run(1)
            if self.demo.pilot.engine.state == "paused":
                self.bench.do("resume_auto")
            if "first_crack" in snap["milestones"]:
                break
        self.bench.run(60)
        # This drum's qualitative law never reaches the drop temperature on development's burner:
        # the operator drops (the auto-drop is checked on replayed roasts, tests/test_guided.py).
        self.bench.do("mark", "drop")
        self.bench.run(3)

    def test_auto_marks_the_roast_drives_the_machine_and_cools_it_at_the_drop(self):
        self.auto_roast()
        self.assertEqual(list(self.demo.session.milestones), ["charge", "dry_end", "first_crack", "drop"])
        burners = [int(c.split(",")[1]) for c in self.roaster.received if c.startswith("OT1,")]
        self.assertGreater(len(set(burners)), 3, "the burner follows the plan's ramp")
        self.assertLessEqual(max(burners), HEATER_MAX)
        self.assertEqual((self.roaster.burner, self.roaster.air, self.roaster.drum), (0, 75, 80)) # roasters.json
        self.assertEqual(self.demo.pilot.engine.state, "off")

    def test_a_hand_on_the_burner_pauses_auto_and_the_machine_keeps_it(self):
        self.auto_roast(touch_at=150)
        self.assertEqual(self.demo.pilot.engine.state, "paused")
        self.assertEqual(self.roaster.burner, 40)


if __name__ == "__main__":
    unittest.main()

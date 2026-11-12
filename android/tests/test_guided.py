# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The guided mode and AUTO on the tablet (GUIDED-SPEC G4), on a replayed roast of the corpus."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import shutil
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.guided import Guide

CORPUS = Path(__file__).resolve().parents[2] / "src" / "test" / "fixtures" / "corpus"
GR2 = {"name": "74110 GR2", "uuid": "a82364a8-e9ad-447c-a3d8-5f49111dc3ee", "process": "Natural / Dry Process",
       "country": "Ethiopia", "varieties": "74110", "weight_left": 2000.0, "density": 700.0, "last_humidity": 10.5}


def _resume_after_a_crash(demo):
    """The operator follows the crash message, then gives the levers back to AUTO with its chip."""
    if demo.pilot.engine.state == "paused":
        demo.resume_auto()


def _follow_the_bubble(demo):
    """The operator makes the gesture the bubble asks for."""
    bubble = demo._bubble or {}
    lever = {"Burner": "burner", "Air": "air"}.get(str(bubble.get("title", "")).split(" ")[0])
    if lever is not None and bubble.get("tone") == "guide":
        demo.set_lever(lever, int(bubble["title"].split(" ")[1]))


class GuidedTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        (base / "roasts-computer").mkdir()
        roasts = sorted(CORPUS.glob("74110 GR2*.alog"))
        for path in roasts:
            shutil.copy(path, base / "roasts-computer" / path.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "auto_marks": ["charge", "dry_end", "first_crack", "drop"]})
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.demo.cave.replace(json.dumps({"green_beans": [GR2]}), "beancave.json")
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        self.demo.set_plan_choice(json.dumps({"plan_level": "Medium", "roast_destination": "espresso"}))
        self.demo.simulate(json.dumps({"origin": "computer", "name": roasts[-1].name}))

    def run_to_end(self, touch=None):
        """To the drop, on the recorded BT: the simulated roaster's answer to the levers is left out,
        these tests read the decisions, not the machine (SIM-SPEC S3)."""
        self.demo.response = None
        snaps = []
        while self.demo.now < self.demo.replay.length_s - 1 and "drop" not in self.demo.session.milestones:
            self.demo.advance(1)
            if touch is not None:
                touch(self.demo)
            snaps.append(json.loads(self.demo.snapshot()))
        return snaps

    def charge(self):
        """Until CHARGE marks itself, where the replayed roast charged."""
        while "charge" not in self.demo.session.milestones:
            self.demo.advance(1)
            self.assertLess(self.demo.now, self.demo.replay.length_s)

    def test_auto_marks_the_roast_and_drives_the_levers_to_the_drop(self):
        self.demo.start("auto")
        self.assertEqual(self.demo.pilot.engine.state, "armed")
        self.assertIsNone(self.demo.alarms) # alarms are a manual tool (AUTOMATION-SPEC decision 9)
        self.charge()
        snaps = self.run_to_end(touch=_resume_after_a_crash)
        self.assertEqual(set(self.demo.session.milestones), {"charge", "dry_end", "first_crack", "drop"})
        moved = [s for s in self.demo.session.settings if s[1] == "burner"]
        self.assertGreater(len(moved), 3) # the burner ramp
        self.assertTrue(any(s["pilot"]["text"] for s in snaps))
        self.assertIsNone(snaps[-2]["guide"]) # AUTO speaks through its toast, no bubble
        # the drop: the roaster's cooling (roasters.json), then AUTO hands back
        self.assertEqual((self.demo.levers["burner"], self.demo.levers["air"]), (0, 75))
        self.assertEqual(self.demo.pilot.engine.state, "off")

    def test_a_lever_touched_pauses_auto_and_the_chip_resumes_it(self):
        clock = [1000.0] # the milestone's grace window is real seconds: past it here
        patch = mock.patch("tilaucore.autopilot.time", SimpleNamespace(monotonic=lambda: clock[0]))
        patch.start()
        self.addCleanup(patch.stop)
        self.demo.start("auto")
        self.charge()
        clock[0] += 60.0
        for _ in range(60):
            self.demo.advance(1)
        self.demo.set_lever("burner", 40)
        self.demo.advance(1)
        self.assertEqual(self.demo.pilot.engine.state, "paused")
        self.assertEqual(self.demo.levers["burner"], 40) # left as the operator set it
        self.demo.resume_auto()
        self.assertEqual(self.demo.pilot.engine.state, "armed")
        self.assertEqual(self.demo.levers["burner"], 40) # resuming moves nothing

    def test_wait_cancels_the_auto_drop_for_the_roast(self):
        self.demo.start("auto")
        self.demo.pilot.engine.drop_deadline = 1.0
        self.demo.cancel_auto_drop()
        self.assertTrue(self.demo.pilot.engine.drop_cancelled)

    def test_the_plan_guides_through_the_bubble_and_the_drop_button_fills(self):
        self.demo.start("plan")
        self.assertIsNone(self.demo.pilot)
        self.charge()
        snaps = self.run_to_end(touch=_follow_the_bubble)
        bubbles = [s["guide"] for s in snaps if s["guide"]]
        self.assertTrue(any(b["title"].startswith(("Burner", "Air")) for b in bubbles))
        self.assertTrue(any(b["title"].startswith("Drop at") for b in bubbles))
        gauges = [s["drop_gauge"] for s in snaps if s["drop_gauge"] is not None]
        self.assertTrue(gauges and gauges[-1] > gauges[0])

    def test_by_hand_no_guided_bubble(self):
        self.demo.start()
        self.charge()
        self.assertFalse([s for s in self.run_to_end() if s["guide"] and s["guide"]["tone"] != "crash"])


    def test_a_plan_that_fails_at_start_leaves_no_roast_half_started(self):
        def fail():
            raise RuntimeError("no plan")
        self.demo._roast_plan = fail
        with self.assertRaises(ValueError):
            self.demo.start("auto")
        with self.assertRaises(ValueError):
            self.demo.start("plan")
        self.assertEqual(self.demo.session.state, "idle")

    def test_start_computes_the_plan_once(self):
        engine = self.demo._plan_engine()
        with mock.patch.object(engine, "generate_roast_plan", wraps=engine.generate_roast_plan) as generate:
            self.demo.start("auto")
        self.assertEqual(generate.call_count, 1)

    def test_auto_keeps_the_extractor_within_the_airwave_s_range(self):
        self.demo.start("auto")
        self.demo.pilot_extractor(20)
        self.assertEqual(self.demo.levers["extractor"], 30) # the AirWave would clamp it: its echo is AUTO's


class CrashTests(unittest.TestCase):
    def test_a_crash_asks_for_the_air_and_says_why(self):
        guide = Guide(None)
        said = None
        for ror in [9.0] * 20 + [9.0 - 0.3 * i for i in range(1, 15)]:
            said = guide.crash_check(ror, "DEV", 600.0, 90.0, False) or said
        self.assertEqual(said, ("The roast is losing speed", "Air up one step · leave the burner"))

    def test_the_charge_dip_is_not_a_crash(self):
        guide = Guide(None)
        said = [guide.crash_check(ror, "DRY", 30.0, 0.0, False) for ror in [20.0 - i for i in range(30)]]
        self.assertFalse(any(said))


if __name__ == "__main__":
    unittest.main()

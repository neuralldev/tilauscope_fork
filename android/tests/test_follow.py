# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Follow a roast (AUTOMATION-SPEC decision 13): its levers played back on a replayed roast."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo

from test_automation import PROFILE

COFFEE = {"name": "Barazilie", "uuid": "3f0c9e7a-1b2c-4d5e-8f90-123456789abc", "process": "Natural / Dry Process",
          "country": "Brazil", "varieties": "Bourbon", "weight_left": 2000.0, "density": 660.0, "last_humidity": 12.2}
# The roast followed: the same curve, burner to 80 % at 60 s (before the turning point), to 60 % at 300 s
FOLLOWED = {**PROFILE, "title": "Followed", "timeindex": [30, 0, 0, 0, 0, 0, 560, 0],
            "specialevents": [60, 300], "specialeventstype": [3, 3], "specialeventsvalue": [9.0, 7.0]}


class FollowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = self.base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"},
                                    "devices": {"extractor": {"name": "AirWave", "address": "11:22:33:44:55:66"}}})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "live.alog").write_text(repr(PROFILE), encoding="utf-8")
        (base / "roasts-computer" / "followed.alog").write_text(repr(FOLLOWED), encoding="utf-8")
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        plan = json.loads(self.demo.set_follow(json.dumps({"origin": "computer", "name": "followed.alog"})))
        self.view = plan["follow"]
        self.demo.simulate(json.dumps({"origin": "computer", "name": "followed.alog"})) # a simulation follows what it replays

    def start_and_charge(self):
        """Charge detection off: Charge is touched, when the beans go in."""
        self.demo.config = {**self.demo.config, "charge_detection": False}
        self.demo.start("roast")
        self.run_to(30)
        self.demo.mark("charge")
        self.assertIsNone(self.demo.auto)

    def run_to(self, seconds):
        while self.demo.now < seconds:
            self.demo.advance(1)
        return json.loads(self.demo.snapshot())

    def burner_settings(self):
        return [(round(t), v) for t, lever, v in self.demo.session.settings if lever == "burner"]

    def test_a_roast_picked_before_its_coffee_is_chosen_stays_the_one_followed(self):
        self.demo.exit_simulation()
        self.demo.cave.replace(json.dumps({"green_beans": [COFFEE]}), "beancave.json")
        self.demo.choose_coffee(COFFEE["uuid"]) # as the toast asks, after the pick
        self.assertEqual(self.demo._follow_source(), ("computer", "followed.alog"))

    def test_a_simulation_follows_the_roast_it_replays_and_gives_the_pick_back_on_exit(self):
        self.demo.exit_simulation()
        self.demo.set_follow(json.dumps({"origin": "computer", "name": "followed.alog"}))
        self.demo.simulate(json.dumps({"origin": "computer", "name": "live.alog"}))
        self.assertEqual(self.demo._follow_source(), ("computer", "live.alog"))
        self.demo.exit_simulation()
        self.assertEqual(self.demo._follow_source(), ("computer", "followed.alog"))

    def test_the_roast_followed_outlives_a_restart_of_the_app(self):
        self.demo.exit_simulation()
        self.demo.cave.replace(json.dumps({"green_beans": [COFFEE]}), "beancave.json")
        self.demo.choose_coffee(COFFEE["uuid"])
        self.demo.set_follow(json.dumps({"origin": "computer", "name": "followed.alog"}))
        again = Demo(str(self.base / "session.journal"), str(self.base / "config.json"), str(self.base / "beancave"))
        self.assertEqual(again._follow_source(), ("computer", "followed.alog")) # not the reference ★ again

    def test_an_unreadable_roast_followed_leaves_the_plan_tab_working(self):
        self.demo._follow_source() # picked in setUp
        (self.base / "roasts-computer" / "followed.alog").write_text("{'timex': [0.0, 1", encoding="utf-8")
        self.demo._followed = None
        plan = json.loads(self.demo.get_plan())
        self.assertIsNone(plan["follow"]["roast"]) # nothing to follow: START offers no roast

    def test_the_extractor_sent_by_the_playback_is_recorded_when_it_confirms(self):
        self.start_and_charge()
        self.demo._follow_extractor.append(62) # a move sent
        self.demo.device_lever("extractor", 62)
        self.assertEqual(self.demo.session.settings[-1][1:], ("extractor", 62)) # what the AirWave got
        self.assertIsNotNone(self.demo.playback)

    def test_the_extractor_moved_on_its_own_buttons_takes_the_roast_back(self):
        self.start_and_charge()
        self.demo._follow_extractor.append(62)
        self.demo.device_lever("extractor", 40) # the operator's hand on the AirWave
        self.assertIsNone(self.demo.playback)

    def test_the_lanes_of_the_roast_followed_stop_at_its_drop(self):
        roast = self.demo._followed_roast()
        roast.events, roast.etypes, roast.evalues = [60, 300, 580], [3, 3, 0], [9.0, 7.0, 7.0] # air opened in cooling
        self.assertEqual(sorted(roast.view()["lanes"]), ["burner"])

    def test_start_is_told_the_roast_it_can_follow(self):
        self.assertEqual(self.view["roast"]["title"], "Followed")
        self.assertEqual(self.view["roast"]["moves"], 2)
        self.assertEqual([r["key"] for r in self.view["roast"]["rows"]], ["charge", "drop"])

    def test_its_moves_are_played_back_as_recorded_without_alarms(self):
        self.start_and_charge()
        self.assertIsNone(self.demo.alarms) # following a roast is following a plan (decision 9)
        self.run_to(61)
        self.assertEqual(self.burner_settings()[-1], (60, 80)) # before the turning point, on time
        self.run_to(200)
        self.assertEqual(self.demo.levers["burner"], 80) # as by hand: held until the next move, no ramp
        self.assertEqual(self.burner_settings()[-1], (60, 80))
        self.run_to(420)
        self.assertEqual(self.burner_settings()[-1][1], 60) # past the turning point, on the bean temperature

    def test_charge_detection_marks_charge_and_engages_the_playback_nothing_else(self):
        self.demo.start("roast")
        self.run_to(61)
        self.assertEqual(set(self.demo.session.milestones), {"charge"})
        self.assertEqual(self.burner_settings()[-1], (60, 80)) # the playback runs from the Charge found
        self.run_to(599)
        self.assertNotIn("dry_end", self.demo.session.milestones) # the detections are the by-hand way's

    def test_a_touch_on_a_lever_takes_the_roast_back_for_good(self):
        self.start_and_charge()
        self.run_to(100)
        self.demo.set_lever("air", 50)
        snap = self.run_to(400)
        self.assertIsNone(self.demo.playback)
        self.assertEqual(snap["auto"]["kind"], "unfollowed")
        self.assertEqual(self.burner_settings()[-1], (60, 80))
        self.assertLessEqual(self.burner_settings()[-1][0], 100) # nothing after the hand took the levers back


if __name__ == "__main__":
    unittest.main()

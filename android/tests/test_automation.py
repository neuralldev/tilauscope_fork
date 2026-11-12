# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Milestones that mark themselves (AUTOMATION-SPEC D1), on a replayed roast."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo


def _bt(t: int) -> float:
    """A preheated drum at 200 °C, beans in after 30 s, TP near 90 °C, a steady climb, beans out after 560 s
    (BT, in the hot drum, still rises 6 s before it falls)."""
    if t < 30:
        return 200.0
    if t < 90:
        return 200.0 - 110.0 * (1 - (90 - t) / 60) ** 0.5
    if t <= 566:
        return 90.0 + 0.25 * (t - 90)
    return 209.0 - 8.0 * (t - 566)


TIMES = list(range(600))
PROFILE = {"title": "Auto marks", "mode": "C", "timex": [float(t) for t in TIMES],
           "temp1": [_bt(t) + 15 for t in TIMES], "temp2": [_bt(t) for t in TIMES],
           "extradevices": [193], "tilau_name_map": {0: "tilau56"}, "extratimex": [[float(t) for t in TIMES]],
           # the crack counter: silent, then a pop every second from 470 s
           "extratemp1": [[float(max(0, t - 469)) for t in TIMES]], "extratemp2": [[-1.0] * len(TIMES)],
           "timeindex": [-1, 0, 0, 0, 0, 0, 0, 0]}
MINIMAL = ('{"alarmflags":[1],"alarmguards":[-1],"alarmnegguards":[-1],"alarmtimes":[9],"alarmoffsets":[1],'
           '"alarmconds":[1],"alarmsources":[-3],"alarmtemperatures":[0.0],"alarmactions":[3],"alarmbeep":[0],'
           '"alarmstrings":["20"]}')


class AutoMarksTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        self.base = base
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"},
                                    "auto_marks": ["charge", "dry_end", "first_crack", "drop"]})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "auto.alog").write_text(repr(PROFILE), encoding="utf-8")
        (base / "minimal.alrm").write_text(MINIMAL, encoding="utf-8")
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.demo.import_alarms(str(base / "minimal.alrm"), "minimal") # the active list
        self.demo._roast_plan = lambda: {"End of Dry Temp": 160.0, "First Crack Temp": 185.0} # the plan Roast Setup shows
        self.demo.simulate(json.dumps({"origin": "computer", "name": "auto.alog"}))

    def run_to(self, seconds):
        while self.demo.now < seconds:
            self.demo.advance(1)
        return json.loads(self.demo.snapshot())

    def test_an_armed_roast_marks_itself_as_a_touch_would_and_runs_no_alarm(self):
        self.demo.start("plan")
        self.assertIsNone(self.demo.alarms) # alarms are a manual tool (decision 9)
        snap = self.run_to(40)
        self.assertEqual(self.demo.session.milestones, {"charge": 30}) # the last reading at 200 °C, before the plunge
        self.assertEqual((snap["auto"]["kind"], snap["auto"]["milestone"]), ("marked", "charge"))
        self.run_to(599)
        marks, samples = self.demo.session.milestones, self.demo.session.samples
        self.assertTrue(155 <= samples[marks["dry_end"]].bt_c <= 165)
        self.assertEqual(marks["first_crack"], 470) # four cracks by 473 s: back to the first one heard
        self.assertEqual(marks["drop"], 560)

    def _simulate(self, **changes):
        profile = {**PROFILE, **changes}
        (self.base / "roasts-computer" / "auto.alog").write_text(repr(profile), encoding="utf-8")
        self.demo.simulate(json.dumps({"origin": "computer", "name": "auto.alog"}))
        self.demo.start("plan")
        self.run_to(599)
        return self.demo.session.milestones

    def test_a_simulation_takes_the_replayed_roast_s_own_first_crack_and_drop(self):
        marks = self._simulate(timeindex=[30, 280, 300, 0, 0, 0, 500, 0])
        self.assertEqual((marks["first_crack"], marks["drop"]), (300, 500))

    def test_a_replayed_roast_without_cracks_takes_its_milestone(self):
        marks = self._simulate(timeindex=[30, 280, 450, 0, 0, 0, 500, 0], tilau_name_map={},
                               extradevices=[], extratimex=[], extratemp1=[], extratemp2=[])
        self.assertEqual((marks["first_crack"], marks["drop"]), (450, 500))

    def test_cracks_heard_before_the_original_mark_call_first_crack(self):
        marks = self._simulate(timeindex=[30, 280, 520, 0, 0, 0, 560, 0])
        self.assertEqual(marks["first_crack"], 470)

    def test_without_a_counter_first_crack_marks_once_past_its_window(self):
        marks = self._simulate(tilau_name_map={}, extradevices=[], extratimex=[], extratemp1=[], extratemp2=[])
        self.assertTrue(marks["first_crack"] > 470)

    def test_a_lever_touched_in_preheat_leaves_the_automation_to_charge(self):
        self.demo.start("plan")
        self.demo.set_lever("air", 50) # in preheat: the hand takes the PID only
        snap = self.run_to(120)
        self.assertTrue(snap["auto"]["active"])
        self.assertIn("charge", self.demo.session.milestones) # CHARGE marked itself

    def test_a_lever_touched_after_charge_leaves_the_plan_s_milestones_armed(self):
        """Following the plan, a lever is the gesture the guided bubble asks for (GUIDED-SPEC, 2026-11-08)."""
        self.demo.start("plan")
        self.run_to(120)
        self.demo.set_lever("air", 50)
        snap = self.run_to(599)
        self.assertTrue(snap["auto"]["active"])
        self.assertEqual(set(self.demo.session.milestones), {"charge", "dry_end", "first_crack", "drop"})

    def test_an_undo_after_charge_drops_the_automation_for_the_rest_of_the_roast(self):
        self.demo.start("plan")
        self.run_to(120)
        self.demo.unmark() # the operator takes CHARGE back
        snap = self.run_to(599)
        self.assertEqual((snap["auto"]["active"], snap["auto"]["kind"]), (False, "dropped"))

    def test_without_a_plan_the_roast_is_manual_with_its_alarms(self):
        self.demo.config = {**self.demo.config, "charge_detection": False}
        self.demo.start() # by hand
        self.assertIsNone(self.demo.auto)
        self.assertIsNotNone(self.demo.alarms)

    def test_by_hand_charge_detection_marks_charge_with_the_alarms_on(self):
        self.demo.start() # by hand, Charge detection on as the desktop's Auto CHARGE
        self.assertIsNotNone(self.demo.alarms)
        self.run_to(60)
        self.assertEqual(set(self.demo.session.milestones), {"charge"})
        self.run_to(599)
        self.assertEqual(set(self.demo.session.milestones), {"charge"}) # nothing else armed by hand

    def test_by_hand_the_detections_of_settings_mark_dry_end_and_first_crack_with_the_alarms_on(self):
        self.demo.config = {**self.demo.config, "charge_detection": False, "dry_end_detection": True, "crack_detection": True}
        self.demo.start() # by hand
        self.assertIsNotNone(self.demo.alarms) # roasting by hand, the alarm list runs
        self.run_to(31)
        self.assertEqual(self.demo.session.milestones, {}) # Charge is the operator's
        self.demo.mark("charge")
        self.demo.set_lever("air", 50) # a lever is part of roasting by hand: the detections stay
        self.run_to(599)
        marks = self.demo.session.milestones
        # no plan: the trade's 195 °C with the Skywalker V2's probe at FC (-10 °C), 185 ± 5 °C as Artisan's Phases
        self.assertEqual(marks["first_crack"], 470)
        self.assertIn("dry_end", marks)
        self.assertNotIn("drop", marks)

    def test_the_crack_counter_calibrates_then_counts_from_dry_end_to_drop(self):
        self.demo.start("plan")
        self.assertEqual(self.run_to(24)["crack_detection"], {"phase": "empty", "left_s": 26}) # CAL1 at Start + 20 s
        self.assertIsNone(self.run_to(50)["crack_detection"]) # nothing shown between the two listenings
        self.run_to(599)
        sent, dry_end = self.demo._crack_sent, self.demo._elapsed("dry_end")
        self.assertEqual(sent["cal1"], 20)
        self.assertEqual(sent["cal2"], dry_end + 90)
        self.assertEqual(sent["start"], sent["cal2"] + 40)
        self.assertEqual(sent["stop"], 568) # DROP found two readings into BT's fall, 8 s after the beans left, then marked at 560
        self.assertEqual(json.loads(self.demo.take_device_commands()), []) # a replay sends nothing to a probe


if __name__ == "__main__":
    unittest.main()

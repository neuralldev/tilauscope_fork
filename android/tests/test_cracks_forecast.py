# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The crack counter heard and kept with the roast, the ET's RoR, and the forecast of the next milestone
(Tilau, 2026-11-22: the cracks were neither shown nor in the .alog, the ΔET and the forecast were missing)."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration, cracks
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.session import Sample

import test_automation


def _samples(counts):
    """One sample a second, the counter's value at each (None: no reading)."""
    return [Sample(float(t), 150.0, 160.0, None if c is None else {"cracks": float(c)}) for t, c in enumerate(counts)]


class MeterTests(unittest.TestCase):
    def test_each_rise_of_the_counter_is_a_crack_heard_and_a_restart_counts_from_there(self):
        times = cracks.crack_times(_samples([0, 0, 2, None, 3, 1, 2]))
        self.assertEqual(times, [2.0, 2.0, 4.0, 6.0]) # 3 -> 1 is the probe restarting, 1 -> 2 one more

    def test_nothing_heard_yet_is_no_meter(self):
        self.assertIsNone(cracks.meter(_samples([None, None]), None))

    def test_before_first_crack_the_word_is_listening_then_first_cracks(self):
        self.assertEqual(cracks.meter(_samples([0, 0, 0]), None)["phase"], "listening")
        heard = cracks.meter(_samples([0, 0, 1]), None)
        self.assertEqual((heard["phase"], heard["count"]), ("first", 1))

    def test_after_first_crack_rolling_then_settling_after_twenty_seconds_under_the_threshold(self):
        counts = [0] * 10 + list(range(1, 21)) + [20] * 60 # a crack a second from 10 s to 29 s, then none
        rolling = cracks.meter(_samples(counts[:31]), 10.0)
        self.assertEqual((rolling["phase"], rolling["count"], rolling["bars"]), ("rolling", 20, 10))
        # 35 s after the last crack fewer than four are in the window; 20 s later the crack is settling
        self.assertEqual(cracks.meter(_samples(counts[:70]), 10.0)["phase"], "rolling")
        self.assertEqual(cracks.meter(_samples(counts[:90]), 10.0)["phase"], "settling")


class LiveCountTests(unittest.TestCase):
    """A roast by hand with TilauAmbient on: the count is kept from the probe's Start, and the file has it."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2", "crack_detection": True,
                                    "devices": {"ambient": {"name": "TilauAmbient", "address": "11:22:33:44:55:66"}}})
        self.demo = Demo(str(self.dir / "session.journal"), config, str(self.dir / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]

    def step(self, seconds, count=None):
        for _ in range(seconds):
            self.clock[0] += 1
            if count is not None:
                self.demo.crack_count(count)
            self.demo.advance(1)

    def test_the_count_is_recorded_from_the_probe_start_and_written_as_the_desktop_cracks_channel(self):
        demo = self.demo
        demo.start()
        self.step(25, count=7) # CAL1 at Start + 20 s: a count before the probe's Start is not the roast's
        demo.mark("charge")
        self.step(200)
        demo.mark("dry_end")
        self.step(90 + 40 + 1) # CAL2 at Dry end + 90 s, Start 40 s later
        self.assertIn("start", demo._crack_sent)
        snap = json.loads(demo.snapshot())
        self.assertEqual(snap["crack_detection"]["phase"], "listening")
        self.step(5, count=0)
        self.step(3, count=4)
        snap = json.loads(demo.snapshot())
        self.assertEqual((snap["crack_detection"]["phase"], snap["crack_detection"]["count"]), ("first", 4))
        self.assertEqual(len(snap["crack_times"]), 4)
        demo.mark("first_crack")
        self.step(30)
        demo.mark("drop")
        self.step(2)
        demo.stop()
        data = ast.literal_eval(Path(demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        slot = next(slot for slot, key in data["tilau_name_map"].items() if key == "tilau56")
        self.assertEqual(data["extradevices"][slot], 193)
        self.assertEqual((data["extraname1"][slot], data["extraname2"][slot]), ("cracks", "")) # the desktop finds it by name
        counted = [v for v in data["extratemp1"][slot] if v != -1.0]
        self.assertEqual(sorted(set(counted)), [0.0, 4.0]) # the 7 heard before the probe's Start is not there
        self.assertEqual(set(data["extratemp2"][slot]), {-1.0})

    def test_without_crack_detection_nothing_is_recorded(self):
        self.demo.config = {**self.demo.config, "crack_detection": False}
        self.demo.start()
        self.demo.mark("charge")
        self.step(10, count=3)
        snap = json.loads(self.demo.snapshot())
        self.assertIsNone(snap["crack_detection"])
        self.assertEqual(snap["crack_times"], [])


class ForecastTests(unittest.TestCase):
    """On the replayed roast of test_automation (BT climbs 15 °C/min from 90 s): Dry end 160, FC 185 by the plan."""
    setUp = test_automation.AutoMarksTests.setUp
    run_to = test_automation.AutoMarksTests.run_to

    def test_the_forecast_aims_at_dry_end_then_first_crack_and_ends_there(self):
        self.demo.start("plan")
        f = self.run_to(300)["forecast"] # BT 142.5 °C at 300 s: 17.5 °C to go at 15 °C/min
        self.assertEqual((f["milestone"], f["target_c"]), ("dry_end", 160.0))
        self.assertAlmostEqual(f["at_s"], 370.0, delta=3.0)
        f = self.run_to(400)["forecast"] # Dry end marked at 160 °C; 167.5 °C now
        self.assertEqual((f["milestone"], f["target_c"]), ("first_crack", 185.0))
        self.assertAlmostEqual(f["at_s"], 470.0, delta=3.0)
        self.assertIsNone(self.run_to(500)["forecast"]) # First crack heard: nothing left to forecast

    def test_the_forecast_holds_still_until_it_has_moved_three_seconds(self):
        self.demo.start("plan")
        self.run_to(300)
        before = self.demo._forecast["at_s"]
        self.demo._forecast_ema = before + 2.9 # the average has drifted less than the dead band
        self.demo._forecast_step()
        self.assertEqual(self.demo._forecast["at_s"], before)

    def test_the_et_ror_goes_with_each_sample_and_its_setting_with_the_snapshot(self):
        self.demo.start("plan")
        snap = self.run_to(200)
        self.assertAlmostEqual(snap["samples"][-1][4], 15.0, delta=0.5) # ET is BT + 15: the same climb
        self.assertFalse(snap["det_curve"])
        self.demo.config = {**self.demo.config, "det_curve": True}
        self.assertTrue(json.loads(self.demo.snapshot())["det_curve"])



if __name__ == "__main__":
    unittest.main()

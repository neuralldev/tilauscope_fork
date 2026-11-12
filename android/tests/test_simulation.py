# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Simulation (SIM-SPEC S2): a listed roast replayed in place of every device, then left without a trace."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo

# A recorded roast as the desktop writes it: no BT for the first two samples, one extra device (the AirWave).
PROFILE = {"title": "Caturra replay", "mode": "C", "timex": [float(t) for t in range(40)],
           "temp1": [-1.0, -1.0] + [150.0 + t for t in range(38)], "temp2": [-1.0, -1.0] + [100.0 + 2 * t for t in range(38)],
           "extradevices": [190], "tilau_name_map": {0: "difluid"}, "extratimex": [[float(t) for t in range(40)]],
           "extratemp1": [[60.0 + t for t in range(40)]], "extratemp2": [[-1.0] * 40], "timeindex": [-1, 0, 0, 0, 0, 0, 0, 0]}


class SimulationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        (self.dir / "roasts-computer").mkdir()
        (self.dir / "roasts-computer" / "caturra.alog").write_text(repr(PROFILE), encoding="utf-8")
        self.demo = Demo(str(self.dir / "session.journal"), config, str(self.dir / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())

    def test_a_roast_is_replayed_in_place_of_the_roaster_at_the_chosen_speed(self):
        self.assertEqual(json.loads(self.demo.simulate(json.dumps({"origin": "computer", "name": "caturra.alog"}))),
                         {"title": "Caturra replay"})
        self.assertTrue(json.loads(self.demo.get_setup())["simulation"]) # the page connects no device
        idle = json.loads(self.demo.snapshot())
        self.assertEqual((idle["bt_c"], idle["simulated"]), (100.0, True)) # the file's first BT, before Start
        snap = json.loads(self.demo.start())
        self.assertIsNone(snap["link"])
        self.demo.set_speed(8)
        snap = json.loads(self.demo.advance(1))
        self.assertEqual(snap["sample_count"], 9) # one sample per simulated second
        self.assertEqual(snap["samples"][-1][1:3], [116.0, 158.0])
        self.assertEqual(snap["simulation"], {"title": "Caturra replay", "position_s": 8.0, "length_s": 37.0, "speed": 8})
        self.assertEqual(self.demo.session.samples[-1].extras, {"inlet_c": 70.0}) # the file's AirWave inlet
        self.assertRaises(ValueError, self.demo.set_speed, 4)
        self.demo.set_speed(0) # paused: the replay and the roast clock stand still
        snap = json.loads(self.demo.advance(1))
        self.assertEqual((snap["sample_count"], snap["simulation"]["position_s"]), (9, 8.0))
        snap = json.loads(self.demo.set_speed(0)) # pause touched again: the speed before it
        self.assertEqual(snap["simulation"]["speed"], 8)

    def test_a_fast_replay_slows_to_1x_before_its_beans_go_in_once(self):
        late = {**PROFILE, "timex": [float(t) for t in range(200)], "temp1": [150.0] * 200, "temp2": [100.0] * 200,
                "extratimex": [[float(t) for t in range(200)]], "extratemp1": [[60.0] * 200], "extratemp2": [[-1.0] * 200],
                "timeindex": [100, 0, 0, 0, 0, 0, 0, 0]} # beans in at 100 s
        (self.dir / "roasts-computer" / "late.alog").write_text(repr(late), encoding="utf-8")
        self.demo.simulate(json.dumps({"origin": "computer", "name": "late.alog"}))
        self.demo.start()
        self.demo.set_speed(8)
        while self.demo.speed == 8:
            self.demo.advance(1)
        self.assertEqual(self.demo.now, 70.0) # 30 s before: time to touch Charge
        self.demo.set_speed(8) # chosen again: kept
        self.demo.advance(1)
        self.assertEqual((self.demo.speed, self.demo.now), (8, 78.0))

    def test_leaving_drops_the_simulated_roast_and_gives_the_roaster_back(self):
        self.demo.simulate(json.dumps({"origin": "computer", "name": "caturra.alog"}))
        before = dict(self.demo.levers)
        self.demo.start()
        self.demo.set_lever("burner", 0) # as the replay's alarms or the operator's touch would
        self.assertRaises(ValueError, self.demo.simulate, json.dumps({"origin": "computer", "name": "caturra.alog"}))
        snap = json.loads(self.demo.exit_simulation())
        self.assertEqual((snap["state"], snap["simulation"], snap["sample_count"]), ("idle", None, 0))
        self.assertFalse((self.dir / "session.journal").exists())
        self.assertFalse(json.loads(self.demo.get_setup())["simulation"])
        self.assertFalse(json.loads(self.demo.snapshot())["simulated"])
        self.assertEqual(self.demo.levers, before) # the real roaster's levels, as before the replay


if __name__ == "__main__":
    unittest.main()


class ReplayPreheatTests(unittest.TestCase):
    def test_the_preheat_runs_on_the_replayed_curve_in_simulated_seconds(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2", "preheat_on": True,
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "caturra.alog").write_text(repr(PROFILE), encoding="utf-8")
        demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: demo.journal and demo.journal.close())
        demo.setup = {"preheat_target": 176.0}
        built = demo._preheat_ready[1] # built between roasts: Start does not wait for its history
        demo.simulate(json.dumps({"origin": "computer", "name": "caturra.alog"}))
        demo.start()
        self.assertIs(demo.preheat, built) # the replay kept it, history and all
        demo.set_speed(8)
        snap = json.loads(demo.advance(1))
        self.assertIsNotNone(snap["preheat"]) # the screen draws the preheat's climb before Charge
        self.assertTrue(demo.preheat._sim) # never learns
        self.assertEqual(demo.preheat._clock(), 8.0) # the replay's seconds, not the tablet's

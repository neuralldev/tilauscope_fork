# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The real roaster (MACHINE-SPEC §7): its readings, echoes and commands, its link lost and back."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo


class LinkTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2",
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        self.demo = Demo(str(self.dir / "session.journal"), config)
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]

    def commands(self):
        return json.loads(self.demo.take_commands())

    def connected(self):
        self.demo.start()
        self.demo.link_state(json.dumps({"state": "connected"}))

    def tick(self, bt=150.0, burner=0, air=None):
        self.clock[0] += 1
        self.demo.link_reading(json.dumps({"bt": bt, "et": bt - 10, "burner": burner,
                                           "air": self.demo.levers["air"] if air is None else air}))
        self.demo.advance(1)

    def test_on_connection_the_burner_is_held_and_air_and_drum_follow_the_screen(self):
        self.connected()
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["link"]["name"], snap["simulated"]), ("Skywalker V2", False))
        self.assertEqual(self.commands(), ["OT2,40", "OT3,70"]) # never the burner
        self.assertEqual(snap["levers"]["burner"]["value"], 0)

    def test_a_lever_is_sent_and_confirmed_by_its_echo(self):
        self.connected()
        self.commands()
        self.demo.set_lever("burner", 55)
        self.demo.set_lever("drum", 40) # below the setup's range
        self.assertEqual(self.commands(), ["OT1,55", "OT3,60"])
        self.tick(burner=0)
        self.assertTrue(json.loads(self.demo.snapshot())["levers"]["burner"]["pending"]) # not confirmed yet
        self.tick(burner=55)
        lever = json.loads(self.demo.snapshot())["levers"]["burner"]
        self.assertEqual((lever["echo"], lever["pending"]), (55, False))

    def test_readings_are_the_samples_and_a_silent_link_leaves_a_gap(self):
        self.connected()
        for bt in (150.0, 151.0, 152.0):
            self.tick(bt=bt)
        self.clock[0] += 4 # no reading for 4 s
        self.demo.advance(1)
        self.assertEqual([s.bt_c for s in self.demo.session.samples], [150.0, 151.0, 152.0])

    def test_after_a_drop_the_burner_stays_at_zero_until_raised(self):
        self.connected()
        self.demo.set_lever("burner", 60)
        self.commands()
        self.demo.link_state(json.dumps({"state": "reconnecting"}))
        self.demo.link_state(json.dumps({"state": "connected", "recovered": True}))
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["levers"]["burner"]["value"], snap["link"]["recovered"]), (0, True))
        self.assertEqual(self.commands(), []) # heat is never re-applied by the tablet
        self.demo.set_lever("burner", 50)
        self.assertFalse(json.loads(self.demo.snapshot())["link"]["recovered"])

    def test_the_roaster_levers_are_locked_while_the_link_is_away(self):
        self.connected()
        self.commands()
        settings = len(self.demo.session.settings)
        levers = dict(self.demo.levers)
        self.demo.link_state(json.dumps({"state": "reconnecting"}))
        for lever, value in (("burner", 70), ("air", 60), ("drum", 80)): # nothing would reach the roaster
            self.demo.set_lever(lever, value)
        self.assertEqual(self.commands(), [])
        self.assertEqual({k: self.demo.levers[k] for k in ("burner", "air", "drum")},
                         {k: levers[k] for k in ("burner", "air", "drum")})
        self.assertEqual(self.demo.session.settings[settings:], []) # nothing on record

    def test_a_preheat_waits_for_the_operator_after_a_drop(self):
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "beancave"))
        self.demo.clock = lambda: self.clock[0]
        self.demo.config = {**self.demo.config, "preheat_on": True}
        self.demo.setup = {"preheat_target": 150.0}
        self.connected()
        self.tick(bt=60.0)
        self.demo.link_state(json.dumps({"state": "reconnecting"}))
        self.demo.link_state(json.dumps({"state": "connected", "recovered": True}))
        self.assertEqual(json.loads(self.demo.snapshot())["preheat"]["state"], "paused")

    def test_a_back_to_back_preheat_heats_once_the_roaster_is_connected(self):
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "beancave"))
        self.demo.clock = lambda: self.clock[0]
        self.demo.config = {**self.demo.config, "preheat_on": True}
        self.demo.setup = {"preheat_target": 200.0}
        self.connected()
        self.tick(bt=180.0)
        self.demo.mark("charge")
        self.tick(bt=185.0)
        self.demo.stop()
        self.demo.link_state(json.dumps({"state": "cooling"}))
        self.tick(bt=120.0)
        self.demo.reset()
        self.demo.setup = {**(self.demo.setup or {}), "preheat_target": 200.0}
        self.demo.start() # while the roaster cools: its last reading is still fresh
        self.demo.link_state(json.dumps({"state": "verifying"}))
        self.clock[0] += 1
        self.demo.advance(1) # a second while the link verifies the burner
        self.demo.link_state(json.dumps({"state": "connected"}))
        self.commands()
        for _ in range(3):
            self.tick(bt=121.0, burner=self.demo.levers["burner"])
        heat = [c for c in self.commands() if c.startswith("OT1,") and int(c.split(",")[1]) > 0]
        self.assertTrue(heat, "TilauPID never sent the burner")

    def test_the_roast_time_is_the_real_clock_and_a_late_tick_shows(self):
        self.demo.real_clock = lambda: self.clock[0]
        self.connected()
        for step in (1.0, 1.0, 4.4, 0.2, 1.0): # a tick 4.4 s late, then one run right after it
            self.clock[0] += step
            self.demo.link_reading(json.dumps({"bt": 150.0, "et": 140.0, "burner": 0, "air": self.demo.levers["air"]}))
            snap = json.loads(self.demo.tick())
        self.assertEqual([s.elapsed_s for s in self.demo.session.samples], [1.0, 2.0, 6.4, 7.6]) # a gap, nothing filled in
        self.assertEqual((snap["late_s"], snap["late_sampling"]), (4, [1, 4.4]))
        for _ in range(30):
            self.clock[0] += 1
            self.demo.link_reading(json.dumps({"bt": 150.0, "et": 140.0, "burner": 0, "air": self.demo.levers["air"]}))
            snap = json.loads(self.demo.tick())
        self.assertIsNone(snap["late_s"]) # the pill tells it 30 s
        self.demo.stop()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertEqual(data["tilau_late_sampling"], [1, 4.4])

    def test_end_roast_stops_the_roaster_and_the_file_is_not_simulated(self):
        self.connected()
        self.tick()
        self.demo.mark("charge")
        for _ in range(3):
            self.tick()
        self.commands()
        self.demo.stop()
        self.assertEqual(self.commands(), ["OT1,0", "CLDN,ON", "OT2,75", "OT3,80", "UNTIL_BT_BELOW,50", "EVT,9", "OFF"])
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertNotIn("tilau_simulated", data)

    def test_while_cooling_the_screen_reads_the_roaster_live(self):
        self.connected()
        self.tick(bt=180.0)
        self.demo.mark("charge")
        self.tick(bt=185.0)
        self.demo.stop()
        self.demo.link_state(json.dumps({"state": "cooling"}))
        self.tick(bt=120.0)
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["bt_c"], snap["et_c"]), (120.0, 110.0))
        self.assertEqual(self.demo.session.samples[-1].bt_c, 185.0) # not recorded

    def test_without_a_roaster_the_simulation_sends_nothing(self):
        demo = Demo(None)
        demo.start()
        demo.set_lever("burner", 70)
        self.assertEqual(json.loads(demo.take_commands()), [])
        self.assertTrue(json.loads(demo.snapshot())["simulated"])


class FollowedRoastLinkTests(unittest.TestCase):
    """A roast followed on the real roaster when its link drops (audit 2026-10-25 A02): the heat waits for the operator."""
    def setUp(self):
        from test_automation import _bt
        from test_follow import FOLLOWED
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2", "charge_detection": False,
                                    "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}})
        (base / "roasts-computer").mkdir()
        (base / "roasts-computer" / "followed.alog").write_text(repr(FOLLOWED), encoding="utf-8")
        self.demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        self.addCleanup(lambda: self.demo.journal and self.demo.journal.close())
        self.bt, self.clock = _bt, [100.0]
        self.demo.clock = self.demo.real_clock = lambda: self.clock[0]
        self.demo.set_follow(json.dumps({"origin": "computer", "name": "followed.alog"}))
        self.demo.start("roast")
        self.demo.link_state(json.dumps({"state": "connected"}))
        self.feed(1, 31)
        self.demo.mark("charge")
        self.feed(31, 200)
        self.demo.take_commands()
        self.demo.link_state(json.dumps({"state": "reconnecting"}))
        self.clock[0] += 5
        self.demo.link_state(json.dumps({"state": "connected", "recovered": True}))

    def feed(self, first, last):
        for t in range(first, last):
            self.clock[0] += 1
            self.demo.link_reading(json.dumps({"bt": self.bt(t), "et": self.bt(t) + 15,
                                               "burner": self.demo.levers["burner"], "air": self.demo.levers["air"]}))
            self.demo.tick()

    def heat(self):
        return [c for c in json.loads(self.demo.take_commands()) if c.startswith("OT1,") and c != "OT1,0"]

    def test_the_followed_roast_pauses_and_never_raises_the_burner_by_itself(self):
        self.feed(205, 215)
        self.assertEqual(self.heat(), [])
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["levers"]["burner"]["value"], snap["follow_paused"]), (0, True))

    def test_a_touch_on_any_lever_takes_the_roast_back_and_clears_the_banner(self):
        self.feed(205, 210)
        self.demo.set_lever("air", 50)
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["link"]["recovered"], snap["follow_paused"]), (False, False))
        self.assertIsNone(self.demo.playback) # the levers are the operator's now
        self.feed(210, 220)
        self.assertEqual(self.heat(), [])

    def test_resumed_the_followed_roast_takes_the_burner_again(self):
        self.feed(205, 210)
        self.demo.resume_follow()
        snap = json.loads(self.demo.snapshot())
        self.assertEqual((snap["follow_paused"], snap["link"]["recovered"]), (False, False))
        self.feed(210, 220)
        self.assertNotEqual(self.heat(), [])


if __name__ == "__main__":
    unittest.main()

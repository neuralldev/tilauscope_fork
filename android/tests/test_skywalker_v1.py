# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The Skywalker V1 on its SkyCommand Bluetooth box: its commands, its stop, and no ET or drum shown."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import catalogue, config as configuration, machine
from tilauscope_mobile.demo import Demo


class SetupTests(unittest.TestCase):
    def test_its_sliders_send_the_burner_and_the_air(self):
        levers = machine.setup("skywalker-v1").levers
        self.assertEqual((levers["burner"].command, levers["air"].command), ("OT1,{}", "OT2,{}"))
        self.assertEqual(levers["burner"].command_for(55), "OT1,55")

    def test_ending_the_roast_stops_the_box(self):
        self.assertEqual(machine.end_roast("skywalker-v1")[-1], "OFF")

    def test_only_the_v1_has_no_environment_probe(self):
        self.assertFalse(machine.has_et("skywalker-v1"))
        self.assertTrue(machine.has_et("skywalker-v2"))
        self.assertTrue(machine.has_et(None))

    def test_no_drum_lever_on_the_v1(self):
        self.assertNotIn("drum", catalogue.MACHINES["skywalker-v1"]["levers"])


class LinkTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        config = str(self.dir / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v1", "preheat_input": "ET",
                                    "roaster": {"name": "ESP32_Skycommand_BLE", "address": "AA:BB:CC:DD:EE:FF"}})
        self.demo = Demo(str(self.dir / "session.journal"), config)
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]

    def test_the_et_field_is_not_an_et(self):
        self.demo.start()
        self.demo.link_state(json.dumps({"state": "connected"}))
        for bt in (150.0, 151.0):
            self.clock[0] += 1
            self.demo.link_reading(json.dumps({"bt": bt, "et": bt, "burner": 0, "air": 40}))
            self.demo.advance(1)
        self.assertEqual([s.et_c for s in self.demo.session.samples], [None, None])
        self.assertEqual([s.bt_c for s in self.demo.session.samples], [150.0, 151.0])
        self.assertIsNone(json.loads(self.demo.snapshot())["et_c"])

    def test_the_roast_screen_is_told_there_is_no_et(self):
        self.assertFalse(json.loads(self.demo.snapshot())["has_et"])

    def test_no_drum_on_the_roast_screen(self):
        self.assertNotIn("drum", json.loads(self.demo.snapshot())["levers"])

    def test_the_preheat_reads_bt_and_et_is_not_offered(self):
        self.assertEqual(self.demo._preheat_key(), None) # preheat off: nothing built
        self.demo.config = {**self.demo.config, "preheat_on": True}
        self.demo._real = lambda: True
        self.assertEqual(self.demo._preheat_key(), ("skywalker-v1", "BT"))
        self.assertFalse(json.loads(self.demo.get_setup())["has_et"])


if __name__ == "__main__":
    unittest.main()

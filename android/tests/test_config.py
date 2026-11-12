# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import catalogue, config
from tilauscope_mobile.demo import Demo


class CatalogueTests(unittest.TestCase):
    def test_advertisements_are_classified_by_prefix_or_service(self):
        self.assertEqual(catalogue.classify("TD5325A-3F21"), ("machine", "skywalker-v2"))
        self.assertEqual(catalogue.classify("AirWave 0123"), ("device", "extractor"))
        self.assertEqual(catalogue.classify("pearls-12"), ("device", "scale")) # case-insensitive
        self.assertEqual(catalogue.classify(None, ["000000E0-0000-1000-8000-00805F9B34FB"]),
                         ("device", "colour"))
        self.assertEqual(catalogue.classify(None, ["000000e3-0000-1000-8000-00805f9b34fb"]),
                         ("device", "extractor")) # AirWave without a name
        self.assertEqual(catalogue.classify("BlueDOT"), ("other", "BlueDOT"))
        self.assertIsNone(catalogue.classify("Living room TV"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "config.json")

    def test_only_the_extractor_name_is_free_and_steps_are_bounded(self):
        clean = config.validate({"machine": "skywalker-v2", "levers": {
            "burner": {"name": "Flame", "step": 3}, "extractor": {"name": "  Hood  ", "step": 5}}})
        self.assertEqual(clean["levers"]["burner"], {"name": "Burner", "step": 3})
        self.assertEqual(clean["levers"]["extractor"]["name"], "Hood")
        for bad in ({"machine": "unknown"}, {"levers": {"air": {"step": 0}}},
                    {"devices": {"toaster": {"address": "x"}}}, {"roaster": {"name": "no address"}}):
            with self.assertRaises(ValueError):
                config.validate(bad)

    def test_levers_follow_the_machine_and_the_extractor_device(self):
        v1 = config.validate({"machine": "skywalker-v1"})
        self.assertEqual(list(config.levers(v1)), ["burner", "air"]) # fixed-speed drum
        v2 = config.validate({"machine": "skywalker-v2",
                              "devices": {"extractor": {"address": "AA", "name": "AirWave 1"}}})
        self.assertEqual(list(config.levers(v2)), ["burner", "air", "drum", "extractor"])

    def test_setup_is_saved_and_refused_during_a_roast(self):
        demo = Demo(config_path=self.path)
        self.assertFalse(json.loads(demo.get_setup())["configured"])
        demo.save_setup(json.dumps({"machine": "skywalker-v1", "levers": {"burner": {"step": 2}}}))
        self.assertEqual(config.load(self.path)["machine"], "skywalker-v1")
        snapshot = json.loads(Demo(config_path=self.path).snapshot())
        self.assertEqual(list(snapshot["levers"]), ["burner", "air"])
        self.assertEqual(snapshot["levers"]["burner"]["step"], 2)
        demo.start()
        with self.assertRaises(ValueError):
            demo.save_setup(json.dumps({"machine": "skywalker-v2"}))

    def test_an_unreadable_configuration_is_set_aside_and_the_app_starts_unconfigured(self):
        """A machine the catalogue no longer knows made every session operation fail, for good."""
        for text in ('{"machine": "gone-machine"}', "{not json"):
            Path(self.path).write_text(text, encoding="utf-8")
            demo = Demo(config_path=self.path)
            self.assertFalse(json.loads(demo.get_setup())["configured"])
            self.assertFalse(Path(self.path).exists())
            self.assertEqual(Path(self.path + ".unreadable").read_text(encoding="utf-8"), text)

    def test_scan_results_keep_only_recognised_devices(self):
        found = json.loads(Demo.classify_scan(json.dumps([
            {"address": "A", "name": "TD5325A-1", "rssi": -50},
            {"address": "B", "name": "Phone", "rssi": -60}])))
        self.assertEqual([(f["address"], f["kind"]) for f in found], [("A", "machine")])


if __name__ == "__main__":
    unittest.main()

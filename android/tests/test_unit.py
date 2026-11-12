# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The temperature unit (UNIT-SPEC): a roast recorded in °F is read in °C, the tablet's unit."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from tilaucore.alarms import NEW_ALARM, read_alrm, write_alrm
from tilaucore.ror import RoRSettings
from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.follow import FollowedRoast
from tilauscope_mobile.roasts import Roasts

from test_automation import PROFILE

# The same roast as the desktop writes it in °F
PROFILE_F = {**PROFILE, "mode": "F", "temp1": [v * 1.8 + 32 for v in PROFILE["temp1"]],
             "temp2": [v * 1.8 + 32 for v in PROFILE["temp2"]]}


class ImportedUnitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        (self.base / "roasts-computer").mkdir()
        for name, profile in (("c.alog", PROFILE), ("f.alog", PROFILE_F)):
            (self.base / "roasts-computer" / name).write_text(repr(profile), encoding="utf-8")

    def test_a_roast_in_fahrenheit_shows_its_curve_in_celsius(self):
        roasts = Roasts(str(self.base))
        self.assertEqual(roasts.detail("computer", "f.alog")["curve"], roasts.detail("computer", "c.alog")["curve"])

    def test_a_roast_in_fahrenheit_is_followed_in_celsius(self):
        folder = self.base / "roasts-computer"
        celsius, fahrenheit = FollowedRoast(folder / "c.alog", RoRSettings()), FollowedRoast(folder / "f.alog", RoRSettings())
        for a, b in zip(fahrenheit.bt + fahrenheit.et, celsius.bt + celsius.et):
            self.assertAlmostEqual(a, b, places=9)

    def test_a_roast_tiles_follow_the_unit_shown(self):
        roasts = Roasts(str(self.base))
        computed = {"DROP_BT": 210.0, "FCs_BT": 200.0, "DROP_time": 600.0, "FCs_time": 500.0}
        (self.base / "roasts-computer" / "t.alog").write_text(repr({**PROFILE, "computed": computed}), encoding="utf-8")
        tiles = {t["caption"]: t for t in roasts.detail("computer", "t.alog", "F")["tiles"]}
        self.assertIn("410 °F", [t["value"] for t in tiles.values()]) # 210 °C

    def test_each_milestone_carries_its_bean_temperature_and_the_saved_turning_point(self):
        computed = {"TP_time": 60.0, "TP_BT": 212.0} # °F, as a desktop in °F saves it: 100 °C
        (self.base / "roasts-computer" / "tp.alog").write_text(repr({**PROFILE_F, "computed": computed}), encoding="utf-8")
        points = Roasts(str(self.base)).detail("computer", "tp.alog")["points"]
        self.assertIn({"key": "tp", "t": 60.0, "bt": 100.0}, points)
        self.assertEqual([p["t"] for p in points], sorted(p["t"] for p in points))


class SettingTests(unittest.TestCase):
    def test_the_unit_is_celsius_or_fahrenheit_and_celsius_by_default(self):
        self.assertEqual(configuration.validate(configuration.default())["unit"], "C")
        self.assertEqual(configuration.validate({**configuration.default(), "unit": "F"})["unit"], "F")
        with self.assertRaises(ValueError):
            configuration.validate({**configuration.default(), "unit": "K"})


class AlarmUnitTests(unittest.TestCase):
    def test_an_alarm_list_in_fahrenheit_is_kept_in_celsius_and_shown_and_shared_in_fahrenheit(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "unit": "F"})
        demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))

        rows = [replace(NEW_ALARM, source=1, temperature=392.0), replace(NEW_ALARM, source=-1, temperature=18.0),
                replace(NEW_ALARM, temperature=500.0)] # BT above 392 °F, BT RoR 18 °F/min, no source
        (base / "f.alrm").write_text(write_alrm(rows), encoding="utf-8")
        demo.import_alarms(str(base / "f.alrm"), "f")
        kept = read_alrm((base / "alarms" / "f.alrm").read_text(encoding="utf-8"))
        self.assertEqual([a.temperature for a in kept], [200.0, 10.0, 500.0]) # °C, a rate × 5/9, 500 untouched
        shown = json.loads(demo.get_alarm_list("f"))["rows"]
        self.assertEqual([r["temperature"] for r in shown], [392.0, 18.0, 500.0])
        demo.edit_alarm(json.dumps({"name": "f", "row": 0, "fields": {"temperature": 401}}))
        self.assertAlmostEqual(read_alrm((base / "alarms" / "f.alrm").read_text(encoding="utf-8"))[0].temperature, 205.0)
        shared = read_alrm(Path(demo.alarm_list_file("f")).read_text(encoding="utf-8"))
        self.assertEqual([a.temperature for a in shared], [401.0, 18.0, 500.0])

    def _demo_f(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "unit": "F"})
        return base, Demo(str(base / "session.journal"), config, str(base / "beancave"))

    def test_a_typed_500_fahrenheit_is_a_threshold(self):
        base, demo = self._demo_f()
        (base / "f.alrm").write_text(write_alrm([replace(NEW_ALARM, source=1, temperature=392.0)]), encoding="utf-8")
        demo.import_alarms(str(base / "f.alrm"), "f")
        demo.edit_alarm(json.dumps({"name": "f", "row": 0, "fields": {"temperature": 500}}))
        self.assertAlmostEqual(read_alrm((base / "alarms" / "f.alrm").read_text(encoding="utf-8"))[0].temperature, 260.0)

    def test_changing_only_the_source_keeps_the_value_shown(self):
        base, demo = self._demo_f()
        (base / "f.alrm").write_text(write_alrm([replace(NEW_ALARM, source=1, temperature=392.0)]), encoding="utf-8")
        demo.import_alarms(str(base / "f.alrm"), "f")
        demo.edit_alarm(json.dumps({"name": "f", "row": 0, "fields": {"source": -1}})) # BT to BT RoR
        self.assertEqual(json.loads(demo.get_alarm_list("f"))["rows"][0]["temperature"], 392.0)

    def test_a_deleted_list_leaves_no_shared_copy(self):
        base, demo = self._demo_f()
        (base / "f.alrm").write_text(write_alrm([replace(NEW_ALARM, source=1, temperature=392.0)]), encoding="utf-8")
        demo.import_alarms(str(base / "f.alrm"), "f")
        shared = Path(demo.alarm_list_file("f"))
        demo.delete_alarm_list("f")
        self.assertFalse(shared.exists())


class PreheatUnitTests(unittest.TestCase):
    def test_the_preheat_range_is_said_in_the_unit_shown(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = str(base / "config.json")
        configuration.save(config, {**configuration.default(), "unit": "F"})
        demo = Demo(str(base / "session.journal"), config, str(base / "beancave"))
        demo.coffee, demo.setup = {"name": "x"}, {"title": "x"}
        with self.assertRaisesRegex(ValueError, "122 and 572 °F"):
            demo.set_roast_setup(json.dumps({"density": 700, "moisture": 10, "preheat": {"target": 320.0}}))


if __name__ == "__main__":
    unittest.main()

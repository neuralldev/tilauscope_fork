# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A roast made on the tablet is a desktop .alog: read back as the desktop reads it."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import alog
from tilauscope_mobile.demo import Demo

DESKTOP = Path(__file__).resolve().parents[2] / "src"


def typed_dict_keys(source: Path, name: str) -> set[str]:
    """Keys of a desktop TypedDict, read from its source without importing it."""
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign)}
    raise AssertionError(f"{name} not found in {source}")


class AlogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        demo, clock = Demo(str(self.dir / "session.journal")), [100.0]
        demo.clock = lambda: clock[0]
        demo.set_weight("green", 250)
        demo.ambient_reading(json.dumps({"temperature_c": 21.0, "humidity_pct": 55.0, "pressure_hpa": 1012.0}))
        demo.extra_readings(json.dumps({"inlet_c": 40.0, "catalyst_c": 150.0, "room_c": 21.0, "room_rh": 55.0}))
        demo.start()
        demo.mark("charge")
        for seconds, milestone in ((240, "dry_end"), (240, "first_crack"), (60, "drop")):
            for _ in range(seconds):
                clock[0] += 1
                demo.extra_readings(json.dumps({"inlet_c": 45.0, "catalyst_c": 160.0}))
                demo.advance(1)
            demo.mark(milestone)
        demo.set_lever("burner", 0)
        clock[0] += 5
        demo.advance(1) # the accessory values are now older than 3 s: no reading
        demo.stop()
        demo.set_weight("roasted", 213)
        demo.set_colour("whole", 58.4)
        self.path = demo.export_alog(str(self.dir / "roasts"))
        self.data = ast.literal_eval(Path(self.path).read_text(encoding="utf-8")) # as the desktop deserializes
        self.demo = demo

    def test_curve_milestones_and_measurements(self):
        d = self.data
        self.assertEqual(len(d["timex"]), len(d["temp1"]))
        self.assertEqual(len(d["timex"]), len(d["temp2"]))
        self.assertEqual(d["timeindex"][0], 0) # CHARGE at the first sample
        self.assertEqual([d["timeindex"][i] > 0 for i in range(1, 8)], [True, True, False, False, False, True, False])
        self.assertEqual(d["weight"], [250.0, 213.0, "g"])
        self.assertEqual((d["whole_color"], d["ground_color"]), (58.4, 0.0))
        self.assertEqual((d["ambientTemp"], d["ambient_humidity"], d["ambient_pressure"]), (21.0, 55.0, 1012.0))
        self.assertEqual(len(d["roastUUID"]), 32)
        self.assertEqual(d["mode"], "C")
        self.assertIs(d["tilau_simulated"], True) # kept out of the desktop's learning
        self.assertRegex(Path(self.path).name, r"^TilauScope roast_\d\d-\d\d-\d\d_\d{4}\.alog$")

    def test_settings_are_desktop_events(self):
        d = self.data
        lengths = {len(d[k]) for k in ("specialevents", "specialeventstype", "specialeventsvalue", "specialeventsStrings")}
        self.assertEqual(len(lengths), 1)
        last = list(zip(d["specialeventstype"], d["specialeventsvalue"], d["specialeventsStrings"]))[-1]
        self.assertEqual(last, (3, 0.0, "0%")) # burner, Artisan's value for 0 %
        self.assertIn((0, 5.0, "40%"), zip(d["specialeventstype"], d["specialeventsvalue"], d["specialeventsStrings"]))
        self.assertEqual(alog.event_value(79), 8.9)

    def test_accessories_are_extra_devices_named_for_the_desktop(self):
        d = self.data
        self.assertEqual(d["tilau_name_map"], {0: "difluid", 1: "tilau12"})
        n = len(d["extradevices"])
        for key in [k for k in d if k.startswith("extra")]:
            self.assertEqual(len(d[key]), n, key)
        inlet = d["extratemp1"][0]
        self.assertEqual(len(inlet), len(d["timex"]))
        self.assertEqual(inlet[-1], -1.0) # no fresh reading at the end
        self.assertIn(45.0, inlet)

    def test_computed_follows_the_desktop_rules(self):
        c = self.data["computed"]
        for key in ("CHARGE_BT", "TP_idx", "TP_BT", "DRY_time", "FCs_time", "DROP_time", "DROP_BT", "totaltime",
                    "dryphasetime", "midphasetime", "finishphasetime", "MET"):
            self.assertIn(key, c)
        self.assertEqual(c["totaltime"], c["DROP_time"])
        self.assertAlmostEqual(c["dryphasetime"] + c["midphasetime"] + c["finishphasetime"], c["totaltime"], places=2)
        self.assertEqual(c["weight_loss"], 14.8)
        self.assertEqual((c["weightin"], c["weightout"]), (250.0, 213.0))

    def test_keys_exist_in_the_desktop_profile(self):
        written = {k for k in self.data if not k.startswith("tilau_")}
        self.assertFalse(written - typed_dict_keys(DESKTOP / "artisanlib/atypes.py", "ProfileData"))
        computed = typed_dict_keys(DESKTOP / "artisanlib/atypes.py", "ComputedProfileInformation")
        self.assertFalse(set(self.data["computed"]) - computed)

    def test_accessory_keys_exist_in_the_desktop_registry(self):
        registry = (DESKTOP / "artisanlib/device_registry.py").read_text(encoding="utf-8")
        for key in alog.REGISTRY_ID:
            self.assertIn(f"'{key}':", registry)

    def test_a_failed_write_leaves_no_partial_roast_file(self):
        """The .alog was opened before its text was ready: a failure left an empty roast in the folder."""
        class Broken:
            def __repr__(self):
                raise RuntimeError("interrupted")
        folder = self.dir / "write-check"
        folder.mkdir()
        target = folder / "roast.alog"
        with self.assertRaises(RuntimeError):
            alog.write(str(target), {"title": Broken()})
        self.assertEqual(list(folder.iterdir()), [])
        target.write_text("{'title': 'kept'}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            alog.write(str(target), {"title": Broken()})
        self.assertEqual(target.read_text(encoding="utf-8"), "{'title': 'kept'}")

    def test_saved_again_a_roast_keeps_its_file_and_the_next_one_of_the_same_minute_its_own(self):
        self.assertEqual(self.demo.export_alog(str(self.dir / "roasts")), self.path) # saved twice: one file
        demo, clock = self.demo, [10_000.0]
        demo.reset()
        demo.clock = lambda: clock[0]
        demo.start()
        demo.mark("charge")
        for _ in range(10):
            clock[0] += 1
            demo.advance(1)
        demo.stop()
        demo.session.started_epoch = self.data["roastepoch"] # started in the same minute, with the same title
        second = demo.export_alog(str(self.dir / "roasts"))
        self.assertNotEqual(second, self.path)
        self.assertEqual(ast.literal_eval(Path(self.path).read_text(encoding="utf-8")), self.data) # the first one intact

    def test_export_refused_during_the_roast(self):
        with self.assertRaises(ValueError):
            Demo().export_alog(str(self.dir))


if __name__ == "__main__":
    unittest.main()

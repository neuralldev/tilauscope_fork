# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The tablet's roasts: its own and the computer's, indexed as the desktop does."""
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile.demo import Demo

UUID = "94ee0778-f239-4457-91d6-d33153c17e6f"


def alog(roast_uuid: str, epoch: int, simulated: bool = False, whole: float = 57.8) -> str:
    profile = {"roastUUID": roast_uuid, "roastepoch": epoch, "title": "Caturra - Natural - 2025", "mode": "C",
               "beans": f"Caturra\nuuid: {UUID}", "weight": [180.0, 157.0, "g"], "whole_color": whole, "ground_color": 0.0,
               "timex": [0.0, 60.0, 238.0, 417.0, 478.0], "temp2": [175.6, 109.0, 150.0, 182.0, 190.4],
               "temp1": [200.0, 160.0, 170.0, 195.0, 205.0], "timeindex": [0, 2, 3, 0, 0, 0, 4, 0],
               "specialevents": [0, 3], "specialeventstype": [3, 3], "specialeventsvalue": [8.0, 7.0],
               "computed": {"DROP_time": 478.0, "FCs_time": 417.0, "DROP_BT": 190.4, "FCs_BT": 182.0}}
    if simulated:
        profile["tilau_simulated"] = True
    return repr(profile)


class RoastsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "beancave"))
        self.demo.cave.replace(json.dumps({"green_beans": [{"name": "Caturra", "uuid": UUID, "process": "Natural / Dry Process"}]}), "beancave.json")
        self.stage = self.dir / "stage"
        self.stage.mkdir()

    def stage_files(self, **files):
        for name, text in files.items():
            (self.stage / name).write_text(text, encoding="utf-8")
        return json.dumps([str(self.stage / name) for name in files])

    def test_the_computers_roasts_come_in_once_into_their_own_folder(self):
        paths = self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "b.alog": alog("b" * 32, 1791702000),
                                    "notes.txt": "hello", "c.alog": "not a profile"})
        self.assertEqual(json.loads(self.demo.import_roasts(paths)), {"imported": 2, "already": 0, "invalid": 2})
        self.assertEqual(json.loads(self.demo.import_roasts(paths))["already"], 2) # the same roasts again change nothing
        rows = json.loads(self.demo.get_roasts())["roasts"]
        self.assertEqual({(r["origin"], r["coffee"]) for r in rows}, {("computer", "Caturra")})
        self.assertTrue((self.dir / "roasts-computer" / "a.alog").exists())
        self.assertFalse((self.dir / "roasts").exists()) # never mixed with the tablet's own

    def test_a_folder_is_previewed_before_anything_is_copied(self):
        paths = json.loads(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "a2.alog": alog("a" * 32, 1791709165),
                                               "c.alog": "not a profile"}))
        preview = json.loads(self.demo.roasts_preview(json.dumps({"folder": "TilauScope-roasts", "paths": paths})))
        self.assertEqual(preview, {"folder": "TilauScope-roasts", "new": 1, "already": 1, "invalid": 1})
        self.assertFalse((self.dir / "roasts-computer").exists())

    def test_a_roast_reads_with_the_desktop_summary(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165)}))
        detail = json.loads(self.demo.get_roast(json.dumps({"origin": "computer", "name": "a.alog"})))
        self.assertEqual([(t["caption"], t["value"], t["sub"]) for t in detail["tiles"]],
                         [("Roasted weight", "157 g", "−13 % from 180 g"), ("Roast time", "7:58", "Development 1:01"),
                          ("Drop temperature", "190 °C", "First crack at 182 °C"), ("Colour", "58", "Whole bean · Medium"),
                          ("Energy", "—", "Not recorded")])
        self.assertEqual(detail["marks"], {"charge": 0.0, "dry_end": 238.0, "first_crack": 417.0, "drop": 478.0})
        self.assertEqual(detail["lanes"], {"burner": [[0.0, 70], [417.0, 60]]})
        self.assertEqual(detail["bean_uuid"], UUID)
        with self.assertRaises(ValueError):
            self.demo.get_roast(json.dumps({"origin": "computer", "name": "../config.json"}))

    def test_a_deleted_roast_leaves_the_tablet_and_what_followed_it(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "b.alog": alog("b" * 32, 1791702000)}))
        self.demo._follow_pick = ("computer", "a.alog")
        self.demo.cave.set_reference(UUID, "a" * 32, True)
        rows = json.loads(self.demo.delete_roast(json.dumps({"origin": "computer", "name": "a.alog"})))["roasts"]
        self.assertEqual([r["name"] for r in rows], ["b.alog"])
        self.assertFalse((self.dir / "roasts-computer" / "a.alog").exists())
        self.assertIsNone(self.demo._follow_pick)
        self.assertEqual(self.demo.cave.beans()[0].reference_roast_uuid, "") # its star goes with it
        with self.assertRaises(ValueError):
            self.demo.delete_roast(json.dumps({"origin": "computer", "name": "../config.json"}))

    def test_a_roast_recalls_its_tasting_in_the_desktop_words(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "b.alog": alog("b" * 32, 1791702000)}))
        (self.dir / "beancave" / "tastings.json").write_text(json.dumps({"entries": {"a" * 32: {
            "bean_uuid": UUID, "iso_date": "2026-10-10", "verdict": "almost", "defects": ["sour"]}}}), encoding="utf-8")
        tasted = json.loads(self.demo.get_roast(json.dumps({"origin": "computer", "name": "a.alog"})))
        self.assertEqual((tasted["tasted"], tasted["defects"]), ("🤏  Almost · Sour, thin", ["sour"]))
        self.assertEqual(json.loads(self.demo.get_roast(json.dumps({"origin": "computer", "name": "b.alog"})))["tasted"], "")

    def test_a_tasting_is_written_as_the_desktop_writes_it(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165)}))
        reply = json.loads(self.demo.save_tasting(json.dumps({"origin": "computer", "name": "a.alog", "verdict": "almost",
                                                             "defects": ["sour", "flat"], "notes": " fruity "})))
        self.assertEqual(reply["tasting"], {"verdict": "almost", "defects": ["flat", "sour"], "notes": "fruity"})
        self.assertEqual(reply["tasted"], "🤏  Almost · Flat, papery · Sour, thin")
        entry = json.loads((self.dir / "beancave" / "tastings.json").read_text())["entries"]["a" * 32]
        self.assertEqual((entry["bean_uuid"], entry["verdict"]), (UUID, "almost"))
        self.assertEqual(reply["words"]["defects"][0][:2], ["burnt", "Burnt"]) # the order the next change is chosen in
        with self.assertRaises(ValueError):
            self.demo.save_tasting(json.dumps({"origin": "computer", "name": "a.alog", "verdict": "maybe"}))

    def test_the_star_makes_one_reference_per_coffee(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "b.alog": alog("b" * 32, 1791702000)}))
        yes = {"origin": "computer", "verdict": "yes", "defects": [], "notes": ""}
        self.assertTrue(json.loads(self.demo.save_tasting(json.dumps({**yes, "name": "a.alog", "reference": True})))["is_reference"])
        other = json.loads(self.demo.save_tasting(json.dumps({**yes, "name": "b.alog", "reference": True})))
        self.assertTrue(other["is_reference"])
        self.assertEqual(self.demo.cave.beans()[0].reference_roast_uuid, "b" * 32) # replaced, one per coffee
        cleared = json.loads(self.demo.save_tasting(json.dumps({**yes, "name": "b.alog", "reference": False})))
        self.assertFalse(cleared["is_reference"] or cleared["has_reference"])

    def test_the_roast_memory_skips_simulated_roasts(self):
        self.demo.import_roasts(self.stage_files(**{"a.alog": alog("a" * 32, 1791709165), "s.alog": alog("s" * 32, 1791800000, simulated=True)}))
        memory = json.loads(self.demo.get_coffees())["coffees"][0]["memory"]
        self.assertEqual((memory["count"], memory["epoch"], memory["colour_basis"]), (1, 1791709165, "whole"))
        rows = json.loads(self.demo.get_roasts())["roasts"]
        self.assertEqual(sorted(r["simulated"] for r in rows), [False, True]) # shown in the list, marked


if __name__ == "__main__":
    unittest.main()

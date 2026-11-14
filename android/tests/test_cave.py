# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The tablet keeps the desktop's beancave.json exactly as it came."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilaucore.bean_edit import ZONES
from tilaucore.beans import BeanCaveContainer, from_json, to_json
from tilauscope_mobile import config
from tilauscope_mobile.cave import EMPTY, Cave, parse
from tilauscope_mobile.demo import Demo

GUJI = {"name": "Guji Kurume", "country": "Ethiopia", "process": "Natural", "crop": 2025, "sca": 88.0,
        "varieties": "Kurume", "water_activity": 0.59, "weight_left": 2000.0, "uuid": "a82364a8-e9ad-447c-a3d8-5f49111dc3ee"}
DESKTOP_FILE = '﻿{"green_beans": [{"name": "Guji", "weight_left": 1200.0, "uuid": "x"}, ' \
               '{"name": "Huila", "weight_left": 0.0}], "reference_profiles": []}\r\n'


class CaveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def test_a_windows_file_comes_back_byte_for_byte(self):
        cave = Cave(str(self.dir))
        state = cave.replace(DESKTOP_FILE, "beancave.json")
        self.assertEqual((state["coffees"], state["in_stock"], state["stock_g"]), (2, 1, 1200))
        self.assertEqual(cave.path.read_bytes(), DESKTOP_FILE.encode("utf-8"))

    def test_other_files_are_refused_and_change_nothing(self):
        cave = Cave(str(self.dir))
        for text in ("", "[]", '{"beans": []}', '{"green_beans": [1]}', "not json"):
            with self.assertRaises(ValueError):
                cave.replace(text, "x.json")
        self.assertFalse(cave.state()["present"])

    def _folder(self, **files):
        folder = self.dir / "from-desktop"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name.replace("_", ".")).write_bytes(text.encode("utf-8"))
        return str(folder)

    def test_the_cave_comes_with_its_tastings_and_brews(self):
        tastings = '{"version": 1, "entries": {"r1": {"bean_uuid": "x", "verdict": "yes"}}}\r\n'
        folder = self._folder(beancave_json=DESKTOP_FILE, tastings_json=tastings, brewlog_json='{"version": 1, "entries": {}}')
        preview = json.loads(Demo.cave_preview(folder, "roasters"))
        self.assertEqual((preview["valid"], preview["coffees"], preview["tastings"]), (True, 2, 1))
        self.assertEqual(preview["files"], ["beancave.json", "tastings.json", "brewlog.json"])
        cave = Cave(str(self.dir / "tablet"))
        self.assertEqual(cave.replace_folder(folder, "roasters")["tastings"], 1)
        self.assertEqual((cave.directory / "tastings.json").read_bytes(), tastings.encode("utf-8"))
        self.assertTrue((cave.directory / "brewlog.json").is_file())

    def test_a_folder_is_refused_whole_when_a_file_cannot_be_read(self):
        cave = Cave(str(self.dir / "tablet"))
        cave.replace(DESKTOP_FILE, "beancave.json")
        for files, reason in (({"tastings_json": "{}"}, "No BeanCave in this folder"),
                              ({"beancave_json": "[]"}, "beancave.json cannot be read"),
                              ({"beancave_json": DESKTOP_FILE, "brewlog_json": '{"entries": []}'}, "brewlog.json cannot be read")):
            folder = self._folder(**files)
            self.assertEqual(json.loads(Demo.cave_preview(folder, "x"))["reason"], reason)
            with self.assertRaises(ValueError):
                cave.replace_folder(folder, "x")
            for name in ("beancave.json", "tastings.json", "brewlog.json"):
                (Path(folder) / name).unlink(missing_ok=True)
        self.assertEqual(cave.path.read_bytes(), DESKTOP_FILE.encode("utf-8"))

    def test_tastings_of_the_replaced_cave_do_not_stay(self):
        cave = Cave(str(self.dir / "tablet"))
        cave.replace_folder(self._folder(beancave_json=DESKTOP_FILE, tastings_json='{"entries": {"r1": {}}}'), "a")
        (self.dir / "from-desktop" / "tastings.json").unlink()
        self.assertEqual(cave.replace_folder(str(self.dir / "from-desktop"), "b")["tastings"], 0)
        self.assertFalse((cave.directory / "tastings.json").exists())

    def test_an_empty_cave_is_the_desktop_empty_container(self):
        cave = Cave(str(self.dir))
        cave.start_empty()
        self.assertEqual(cave.path.read_text(encoding="utf-8"),
                         '{"green_beans": [], "reference_profiles": [], "stock_taken_roasts": null, "stock_awaiting_link": []}')
        self.assertEqual(parse(EMPTY), [])
        with self.assertRaises(ValueError):
            cave.start_empty() # never over an existing cave

    def test_stock_owner_is_this_tablet_or_a_computer(self):
        self.assertEqual(config.default()["cave_owner"], "tablet")
        self.assertEqual(config.validate({"cave_owner": "computer"})["cave_owner"], "computer")
        with self.assertRaises(ValueError):
            config.validate({"cave_owner": "phone"})

    def test_prices_are_in_the_system_currency_until_one_is_chosen(self):
        self.assertEqual(config.default()["currency"], "")
        self.assertEqual(config.validate({"currency": "THB"})["currency"], "THB") # a system one outside the list
        with self.assertRaises(ValueError):
            config.validate({"currency": "euro"})


class ChosenCoffeeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.demo = Demo(str(self.dir / "session.journal"), cave_directory=str(self.dir / "cave"))
        self.demo.cave.replace(json.dumps({"green_beans": [GUJI]}), "beancave.json")

    def roast(self):
        self.demo.start()
        self.demo.mark("charge")
        self.demo.advance(5)
        self.demo.stop()

    def test_the_chosen_coffee_and_its_setup_survive_a_restart(self):
        config = str(self.dir / "config.json")
        demo = Demo(str(self.dir / "a.journal"), config, str(self.dir / "cave"))
        demo.choose_coffee(GUJI["uuid"])
        demo.set_weight("green", 244)
        again = Demo(str(self.dir / "b.journal"), config, str(self.dir / "cave"))
        self.assertEqual((again.coffee["uuid"], again.setup["green"]), (GUJI["uuid"], 244))
        self.assertEqual(json.loads(again.snapshot())["weights_g"]["green"], 244)
        again.cave.replace(json.dumps({"green_beans": []}), "beancave.json") # the coffee is gone
        self.assertIsNone(Demo(str(self.dir / "c.journal"), config, str(self.dir / "cave")).coffee)

    def test_the_roast_names_its_coffee_as_the_desktop_does(self):
        self.demo.choose_coffee(GUJI["uuid"])
        self.assertEqual(json.loads(self.demo.snapshot())["coffee"], {"name": "Guji Kurume", "stock_g": 2000.0, "decrease": True})
        self.roast()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertEqual(data["title"], "Guji Kurume - Natural - 2025")
        self.assertEqual(data["beans"].splitlines(), ["Guji Kurume", "Ethiopia", "Process Natural", "Variety Kurume",
                                                      "SCA: 88.0", "uuid: " + GUJI["uuid"]])

    def test_an_interrupted_roast_keeps_its_coffee(self):
        self.demo.choose_coffee(GUJI["uuid"])
        self.demo.start()
        self.demo.advance(3)
        restored = Demo(str(self.dir / "session.journal"))
        self.assertTrue(restored.interrupted)
        self.assertEqual(restored.session.title, "Guji Kurume - Natural - 2025")
        self.assertIn("uuid: " + GUJI["uuid"], restored.session.beans)

    def test_a_coffee_is_not_chosen_during_a_roast_nor_kept_when_its_file_goes(self):
        self.demo.start()
        with self.assertRaises(ValueError):
            self.demo.choose_coffee(GUJI["uuid"])
        self.demo.stop()
        self.demo.choose_coffee(GUJI["uuid"])
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        Path(other.name, "beancave.json").write_text(DESKTOP_FILE, encoding="utf-8")
        self.demo.cave_import(other.name, "other")
        self.assertIsNone(json.loads(self.demo.snapshot())["coffee"])

    def test_the_sheet_uses_the_desktop_words(self):
        coffee = json.loads(self.demo.get_coffees())["coffees"][0]
        self.assertEqual(coffee["aw"]["word"], "typical")
        self.assertEqual(coffee["family"], "Ethiopian — wants a faster roast")
        self.assertEqual(coffee["density"], {"value": None, "word": "", "level": None})


class EditTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "cave"))
        self.demo.cave.replace(json.dumps({"green_beans": [GUJI], "reference_profiles": [{"title": "kept"}]}), "beancave.json")

    def save(self, **request):
        return json.loads(self.demo.save_coffee(json.dumps(request)))

    def test_a_zone_is_written_as_the_desktop_writes_the_file(self):
        self.demo.choose_coffee(GUJI["uuid"])
        self.save(uuid=GUJI["uuid"], zone="essentials",
                  values={"name": " Guji Kurume ", "country": "Ethiopia", "crop": 2025, "weight_left": 1984.4})
        text = (self.dir / "cave" / "beancave.json").read_text(encoding="utf-8")
        container = from_json(BeanCaveContainer, text)
        self.assertEqual(text, to_json(container)) # the desktop's own serializer
        self.assertEqual((container.green_beans[0].name, container.green_beans[0].weight_left), ("Guji Kurume", 1984.0))
        self.assertEqual(container.reference_profiles[0].title, "kept")
        self.assertEqual(json.loads(self.demo.snapshot())["coffee"]["stock_g"], 1984.0) # the pill follows

    def test_a_new_coffee_needs_the_desktop_required_fields(self):
        values = {key: "" for zone in ZONES.values() for key in zone}
        values.update(name="Huila", country="Colombia", category="Traditional Wet", process="Washed / Wet Process",
                      species="Arabica", varieties="", is_blend=False, crop=2026, weight_left=2500)
        with self.assertRaises(ValueError):
            self.save(zone="all", values=values)
        values["varieties"] = "Caturra"
        reply = self.save(zone="all", values=values)
        new = next(c for c in reply["coffees"] if c["uuid"] == reply["saved"])
        self.assertEqual((new["name"], new["stock_g"], new["edit"]["bean1_ratio"]), ("Huila", 2500, 100.0))

    def test_a_computer_owner_keeps_the_coffees(self):
        self.demo.save_setup(json.dumps({**config.default(), "cave_owner": "computer"}))
        with self.assertRaises(ValueError):
            self.save(uuid=GUJI["uuid"], zone="sensory", values={"sca": 87, "flavour_notes": "", "tips": ""})
        self.assertFalse(json.loads(self.demo.get_coffees())["editable"])

    def test_limits_are_the_desktop_editor_limits(self):
        with self.assertRaises(ValueError):
            self.save(uuid=GUJI["uuid"], zone="provenance", values={"farm": "", "supplier": "", "altitude": 3001, "price_per_kg": 0})


class RoastSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.demo = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "cave"))
        self.demo.cave.replace(json.dumps({"green_beans": [{**GUJI, "density": 712.0, "last_humidity": 11.5, "screen_size": "large"}]}), "beancave.json")
        self.demo.choose_coffee(GUJI["uuid"])

    def setup(self, **values):
        return self.demo.set_roast_setup(json.dumps({"green": 250, "decrease": True, "density": 712, "moisture": 11.5,
                                                     "greens_temp": 18.5, "title": "", **values}))

    def drive_a_roaster(self, **extra):
        """A roaster declared in Settings: only a real roast takes beans from the stock."""
        self.demo.save_setup(json.dumps({**config.default(), "machine": "skywalker-v2",
                                         "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"}, **extra}))

    def stock(self):
        return from_json(BeanCaveContainer, (self.dir / "cave" / "beancave.json").read_text(encoding="utf-8")).green_beans[0].weight_left

    def test_the_plan_s_charge_offered_as_preheat_target_is_never_kept_as_the_operator_s(self):
        self.setup(preheat={"on": True, "input": "BT", "target": 200.0, "typed": False}) # the plan's charge, untouched
        kept = json.loads(self.demo.get_coffees())["setup"]
        self.assertEqual((kept["preheat_target"], kept["preheat_typed"]), (200.0, False)) # this roast preheats to it
        self.setup(preheat={"on": True, "input": "BT", "target": 205.0, "typed": True}) # the operator's own
        self.assertTrue(json.loads(self.demo.get_coffees())["setup"]["preheat_typed"])

    def test_choosing_the_same_coffee_again_keeps_its_weight_and_another_starts_afresh(self):
        self.demo.set_weight("green", 388) # weighed on the roast screen
        self.demo.choose_coffee(GUJI["uuid"]) # Roast this coffee again, from the BeanCave
        self.assertEqual(self.demo.setup["green"], 388)
        restarted = Demo(str(self.dir / "session.journal"), str(self.dir / "config.json"), str(self.dir / "cave"))
        self.assertEqual(json.loads(restarted.snapshot())["weights_g"]["green"], 388) # the app closed and opened again
        other = {**GUJI, "uuid": "another-coffee", "name": "Another"}
        self.demo.cave.replace(json.dumps({"green_beans": [GUJI, other]}), "beancave.json")
        self.demo.choose_coffee("another-coffee")
        self.assertIsNone(self.demo.setup["green"])

    def test_the_built_in_demo_never_takes_beans_from_the_stock(self):
        self.setup() # no roaster declared: the simulated machine
        self.demo.start()
        self.assertEqual(self.stock(), 2000.0)
        self.assertIsNone(json.loads(self.demo.snapshot())["stock_move"])

    def test_the_stock_goes_down_at_the_start_with_the_weight_held_then(self):
        self.drive_a_roaster()
        self.setup()
        self.demo.set_weight("green", 260) # changed on the roast screen after Roast Setup
        self.assertEqual(self.stock(), 2000.0)
        self.demo.start()
        self.assertEqual(self.stock(), 1740.0)
        self.assertEqual(json.loads(self.demo.snapshot())["stock_move"], {"owner": "tablet", "grams": 260, "done": True, "left": 1740.0})

    def test_the_stock_never_goes_below_zero_and_an_unticked_box_leaves_it(self):
        self.drive_a_roaster()
        self.setup(green=2500)
        self.demo.start()
        self.assertEqual(self.stock(), 0.0)
        self.demo.stop()
        self.demo.reset()
        self.demo.cave.replace(json.dumps({"green_beans": [GUJI]}), "beancave.json")
        self.demo.choose_coffee(GUJI["uuid"])
        self.setup(decrease=False)
        self.demo.start()
        self.assertEqual(self.stock(), 2000.0)

    def test_a_computer_owner_is_told_its_stock_was_not_decreased(self):
        self.drive_a_roaster(cave_owner="computer")
        self.setup()
        self.demo.start()
        self.assertEqual(self.stock(), 2000.0)
        self.assertFalse(json.loads(self.demo.snapshot())["stock_move"]["done"])

    def test_the_roast_file_carries_roast_setup_as_the_desktop_writes_it(self):
        self.setup(title="Guji test")
        self.demo.start()
        self.demo.mark("charge")
        self.demo.advance(5)
        self.demo.stop()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertEqual((data["title"], data["density"], data["moisture_greens"], data["greens_temp"]),
                         ("Guji test", [712.0, "g", 1.0, "l"], 11.5, 18.5))
        self.assertEqual((data["beansize_min"], data["beansize_max"]), ("17", "18"))
        self.assertEqual((data["computed"]["set_density"], data["computed"]["moisture_greens"]), (712.0, 11.5))

    def test_two_roasts_in_a_row_take_two_weights(self):
        self.drive_a_roaster()
        self.setup()
        for _ in range(2):
            self.demo.start()
            self.demo.stop()
            self.demo.reset() # New roast keeps the weight for the next one
        self.assertEqual(self.stock(), 1500.0)
        self.assertEqual(json.loads(self.demo.snapshot())["weights_g"]["green"], 250)

    def test_roast_setup_is_for_the_next_roast_only(self):
        self.demo.start()
        with self.assertRaises(ValueError):
            self.setup()


if __name__ == "__main__":
    unittest.main()

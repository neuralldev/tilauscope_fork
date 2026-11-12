# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The plan on the tablet is the desktop's, read over the tablet's roasts and the computer's."""
import ast
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tilaucore.roast_colour import AGTRON_SCALES, roast_agtron
from tilaucore.roast_plan import RoastPlanEngine
from tilaucore.roasters import RoasterManager
from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.machine import setup as machine_setup
from tilauscope_mobile.plan import apply_colour_gap

CORPUS = Path(__file__).resolve().parents[2] / "src" / "test" / "fixtures" / "corpus"
GR2 = {"name": "74110 GR2", "uuid": "a82364a8-e9ad-447c-a3d8-5f49111dc3ee", "process": "Natural / Dry Process",
       "country": "Ethiopia", "varieties": "74110", "weight_left": 2000.0, "density": 700.0, "last_humidity": 10.5}


class PlanTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        (self.dir / "roasts-computer").mkdir()
        for path in sorted(CORPUS.glob("74110 GR2*.alog")):
            shutil.copy(path, self.dir / "roasts-computer" / path.name)
        self.config = str(self.dir / "config.json")
        configuration.save(self.config, {**configuration.default(), "machine": "skywalker-v2"})
        self.demo = Demo(str(self.dir / "session.journal"), self.config, str(self.dir / "beancave"))
        self.demo.cave.replace(json.dumps({"green_beans": [GR2]}), "beancave.json")

    def plan(self) -> dict:
        return json.loads(self.demo.get_plan())

    def test_the_plan_says_what_it_still_needs(self):
        self.assertEqual(self.plan()["state"], "no_coffee")
        self.demo.choose_coffee(GR2["uuid"])
        self.assertEqual(self.plan()["state"], "no_level")
        self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"}))
        self.demo.setup["green"] = 0
        self.assertEqual(self.plan()["state"], "no_weight")
        configuration.save(self.config, {**configuration.default(), "plan_level": "Light"})
        self.demo.config = configuration.load(self.config)
        self.assertEqual(self.plan()["state"], "no_machine")

    def test_the_roadmap_reads_as_on_the_desktop(self):
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        plan = json.loads(self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"})))
        self.assertEqual(plan["state"], "ready")
        self.assertEqual([row["label"] for row in plan["rows"]], ["CHARGE", "DRY END", "FC START", "DROP"])
        self.assertTrue(plan["rows"][0]["levers"].startswith("Burner "))
        self.assertTrue(plan["rows"][3]["levers"].startswith("Development "))
        self.assertTrue(plan["notes"] and plan["cooled"]["grams"])
        self.assertEqual(json.loads(Path(self.config).read_text())["roast_destination"], "filter") # kept

    def test_the_plan_followed_is_the_one_of_the_batch_weighed_at_start(self):
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"}))
        self.assertIsNone(self.demo._plan_targets) # shown, not followed: START chooses
        self.demo.set_weight("green", 250) # back on Roast Setup, the batch weighed again
        shown = {row["key"]: float(row["temp"]) for row in json.loads(self.demo.get_plan())["rows"]}
        self.demo.start("plan")
        self.assertEqual(self.demo._plan_targets, {"dry_end": shown["dry_end"], "first_crack": shown["fc_start"]})

    def test_a_probe_pressure_reaches_the_plan(self):
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 250)
        self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"}))
        at_sea = self.plan()
        self.demo._room = (self.demo.clock(), {"temperature_c": 20.0, "humidity_pct": 50.0, "pressure_hpa": 700.0})
        up_high = self.plan()
        self.assertNotEqual(at_sea["rows"][0]["temp"], up_high["rows"][0]["temp"])

    def test_the_colour_gap_follows_the_machine(self):
        apply_colour_gap("skywalker-v2")
        self.assertEqual(roast_agtron(0.0, 60.0, "Agtron"), (70.0, "estimated"))
        apply_colour_gap(None)
        self.assertEqual(roast_agtron(0.0, 60.0, "Agtron"), (60.0, "whole"))

    def test_start_with_the_plan_is_refused_without_one(self):
        with self.assertRaises(ValueError):
            self.demo.start("plan")
        self.assertEqual(self.demo.session.state, "idle")

    def test_a_reference_roast_not_used_says_why(self):
        roast = ast.literal_eval(sorted((self.dir / "roasts-computer").glob("*.alog"))[0].read_text(encoding="utf-8"))
        self.demo.cave.replace(json.dumps({"green_beans": [{**GR2, "reference_roast_uuid": roast["roastUUID"]}]}), "beancave.json")
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        plan = json.loads(self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"})))
        line = plan["notes"][-1]
        self.assertEqual((line["kind"], line["used"]), ("reference", False)) # never tasted: not used
        self.assertTrue(line["text"].startswith("Your reference roast (") and "its tasting was not found." in line["text"])

    def test_both_folders_read_as_one_history(self):
        self.demo.choose_coffee(GR2["uuid"])
        self.demo.set_weight("green", 400)
        tablet = json.loads(self.demo.set_plan_choice(json.dumps({"plan_level": "Light", "roast_destination": "filter"})))
        engine = RoastPlanEngine(RoasterManager().get_roast_context("Skywalker V2"),
                                 alog_directory=str(self.dir / "roasts-computer"), beancave_directory=str(self.dir / "beancave"),
                                 roast_destination="filter", ror_settings=machine_setup("skywalker-v2").ror)
        scale = next(s for s in AGTRON_SCALES if s.name == "Light")
        desktop = engine.generate_roast_plan(self.demo.cave.beans()[0], scale, 20.0, 50.0, 400.0, 0.0, None, False, None)
        desktop = desktop[0] if isinstance(desktop, tuple) else desktop
        self.assertEqual([row["temp"] for row in tablet["rows"]],
                         [desktop[k] for k in ("Charge Temp", "End of Dry Temp", "First Crack Temp", "Drop Temp")])

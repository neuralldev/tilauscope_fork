# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roast's energy (MQTT-SPEC E2): START to STOP, written as the desktop's tilau_energy and read by its model."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilaucore.energy_model import ESTIMATED, MEASURED, NONE, ROASTER, phase_bounds, session_for_profile
from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.roasts import energy_tile

PLUG = {"name": "roaster", "topic": "zwave/154/49/0/Power", "feeds": "roaster_w"}


class EnergyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.config = str(self.dir / "config.json")

    def roast(self, sensors, machine="skywalker-v2", plug_w=None):
        """A roast of 30 s preheat, 60 s CHARGE to DROP at burner 50 %, 20 s after; the plug publishes every 10 s."""
        configuration.save(self.config, {**configuration.default(), "machine": machine,
                                         "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"} if machine else None,
                                         "mqtt": {"host": "192.168.1.20", "sensors": sensors}})
        demo = Demo(str(self.dir / "session.journal"), self.config, str(self.dir / "beancave"))
        real = [1000.0]
        demo.real_clock = lambda: real[0]
        demo.clock = lambda: real[0]
        demo.start()
        demo.link_state(json.dumps({"state": "connected"}))
        for second in range(1, 111):
            real[0] += 1
            demo.link_reading(json.dumps({"bt": 150.0, "et": 140.0, "burner": 50 if 30 < second <= 90 else 0, "air": 40}))
            if plug_w is not None and second % 10 == 0:
                demo.mqtt_message(json.dumps({"topic": PLUG["topic"], "payload": str(plug_w)}))
            demo.tick()
            if second == 30:
                demo.mark("charge")
            elif second == 90:
                demo.mark("drop")
        demo.stop()
        self.demo = demo
        return ast.literal_eval(Path(demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))

    def bill(self, profile):
        session = session_for_profile(profile)
        return session, session.summarize(phase_bounds(profile["timex"], profile["timeindex"]))

    def test_a_plug_measures_the_whole_roast_preheat_included_and_wins_over_the_burner(self):
        session, summary = self.bill(self.roast([PLUG], plug_w=1200))
        self.assertFalse(session.rebuilt) # the block written, not rebuilt from a curve
        before, roast = summary.before_charge.per_channel[ROASTER], summary.roast.per_channel[ROASTER]
        self.assertEqual((before.provenance, roast.provenance), (MEASURED, MEASURED))
        self.assertAlmostEqual(roast.wh, 1200 * 60 / 3600, delta=0.5)
        self.assertEqual(session.channels[ROASTER].topic, PLUG["topic"])

    def test_without_a_plug_the_burner_estimates_between_charge_and_drop_only(self):
        session, summary = self.bill(self.roast([]))
        self.assertEqual(summary.before_charge.per_channel[ROASTER].provenance, NONE) # the thermostat holds the preheat
        roast = summary.roast.per_channel[ROASTER]
        self.assertEqual(roast.provenance, ESTIMATED)
        self.assertAlmostEqual(roast.wh, 334 * 60 / 3600, delta=0.5) # the V2's measured curve at 50 %
        self.assertLessEqual(summary.after_drop.per_channel[ROASTER].estimated_s, 1.0) # up to the next tick, as on the desktop
        self.assertIn([31.0, 50.0, 40.0, -1.0], [row[:4] for row in session.context]) # burner, air, extraction

    def test_the_end_card_and_its_sheet_give_the_roast_and_the_three_periods(self):
        self.roast([PLUG], plug_w=1200)
        card = json.loads(self.demo.snapshot())["energy"]
        self.assertEqual((card["kwh"], card["roast"], card["provenance"]), (0.02, True, MEASURED)) # 1200 W for 60 s
        sheet = json.loads(self.demo.get_energy())
        self.assertEqual([p["name"] for p in sheet["periods"]], ["Preheat", "Roast", "Cooling"])
        self.assertEqual([p["s"] for p in sheet["periods"]], [30, 60, 20])
        self.assertEqual(sheet["sources"], [{"name": ROASTER, "kwh": sheet["kwh"], "provenance": MEASURED}])
        self.assertEqual(sheet["channels"][ROASTER]["measured"][0], [10.0, 1200.0])

    def test_the_roasts_tab_shows_the_roast_energy_as_the_desktop(self):
        tile = energy_tile(self.roast([PLUG], plug_w=1200))
        self.assertEqual((tile["value"], tile["sub"]), ("0.020 kWh", "Charge → Drop · ● Measured")) # 1200 W, CHARGE to DROP 60 s
        self.assertEqual(energy_tile({"timex": [0.0, 1.0]})["sub"], "Not recorded")

    def test_a_saved_roast_opens_the_same_sheet_from_beancave(self):
        self.roast([PLUG], plug_w=1200)
        name = self.demo.session.exported
        saved = json.loads(self.demo.get_roast_energy(json.dumps({"origin": "tablet", "name": name})))
        live = json.loads(self.demo.get_energy())
        self.assertEqual({k: saved[k] for k in ("kwh", "periods", "sources", "charge", "drop")},
                         {k: live[k] for k in ("kwh", "periods", "sources", "charge", "drop")})

    def test_a_simulated_roast_has_no_energy(self):
        self.assertNotIn("tilau_energy", self.roast([PLUG], machine=None, plug_w=1200))


if __name__ == "__main__":
    unittest.main()

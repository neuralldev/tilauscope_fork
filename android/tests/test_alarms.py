# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Alarms on the tablet (ALARM-SPEC C2): the operator's .alrm lists, run as the operator's hand."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo

# The operator's minimal.alrm (2026-10-16): levers at Start, Charge, TP, Dry end, FC, and at Drop
# air 0, burner 0, event button 5 (cooling on in the V2 setup), drum 80; PID on/off rows.
MINIMAL = ('{"alarmflags":[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],"alarmguards":[-1,0,0,-1,3,-1,-1,6,7,-1,-1,-1,-1,12,13,14],'
           '"alarmnegguards":[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],"alarmtimes":[9,10,10,-1,-1,0,0,10,10,8,1,2,6,10,10,6],'
           '"alarmoffsets":[1,1,1,1,1,1,2,2,3,1,1,2,1,1,1,1],"alarmconds":[2,2,2,2,2,2,2,2,2,2,2,2,2,2,2,2],'
           '"alarmsources":[-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3],'
           '"alarmtemperatures":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0],'
           '"alarmactions":[3,6,4,19,3,20,3,4,6,4,3,3,3,6,2,4],"alarmbeep":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],'
           '"alarmstrings":["20","0","80","","25","","30","85","75","80","35","45","0","0","5","80"]}\n')


def alrm(rows):
    """An .alrm text from (anchor, offset, source, cond, temperature, action, text) rows."""
    keys = ("alarmtimes", "alarmoffsets", "alarmsources", "alarmconds", "alarmtemperatures", "alarmactions", "alarmstrings")
    data = {key: [row[k] for row in rows] for k, key in enumerate(keys)}
    n = len(rows)
    data.update({"alarmflags": [1] * n, "alarmguards": [-1] * n, "alarmnegguards": [-1] * n, "alarmbeep": [0] * n})
    return json.dumps(data)


class AlarmTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.config = str(self.dir / "config.json")
        configuration.save(self.config, {**configuration.default(), "machine": "skywalker-v2",
                                         "roaster": {"name": "TD5325A", "address": "AA:BB:CC:DD:EE:FF"},
                                         "devices": {"extractor": {"name": "AirWave", "address": "11:22:33:44:55:66"},
                                                     "ambient": {"name": "TLSCAM", "address": "22:33:44:55:66:77"}}})
        self.demo = Demo(str(self.dir / "session.journal"), self.config, str(self.dir / "beancave"))
        self.clock = [100.0]
        self.demo.clock = lambda: self.clock[0]
        self.sent = []

    def use(self, name, text):
        source = self.dir / f"{name}.alrm"
        source.write_text(text, encoding="utf-8")
        return json.loads(self.demo.import_alarms(str(source), name))

    def roast(self, seconds, bt=180.0):
        for _ in range(seconds):
            self.clock[0] += 1
            self.demo.link_reading(json.dumps({"bt": bt, "et": bt - 12, "burner": self.demo.levers["burner"],
                                               "air": self.demo.levers["air"]}))
            self.demo.advance(1)
            self.sent += json.loads(self.demo.take_commands())

    def start(self):
        self.demo.start()
        self.demo.link_state(json.dumps({"state": "connected"}))
        self.sent += json.loads(self.demo.take_commands())

    def alarms(self):
        return json.loads(self.demo.snapshot())["alarms"]

    def test_an_imported_list_is_the_one_every_roast_runs_until_none_is_chosen(self):
        lists = self.use("minimal", MINIMAL)
        self.assertEqual(lists["active"], "minimal")
        self.assertEqual(lists["lists"], [{"name": "minimal", "count": 16, "not_run": 2}]) # PID on, PID off
        self.assertEqual(configuration.load(self.config)["alarm_list"], "minimal")
        self.assertIsNone(json.loads(self.demo.set_alarm_list(""))["active"])
        self.start()
        self.assertIsNone(self.alarms())
        with self.assertRaises(ValueError):
            self.demo.import_alarms(str(self.dir / "config.json"), "not a list")

    def test_the_operators_sequence_moves_the_levers_as_a_hand_would(self):
        self.use("minimal", MINIMAL)
        self.start()
        self.roast(3)
        self.assertEqual((self.demo.levers["air"], self.demo.levers["burner"], self.demo.levers["drum"]), (25, 0, 80))
        self.assertIn("OT2,25", self.sent)
        self.demo.mark("charge")
        self.roast(10, bt=150.0)
        self.assertEqual((self.demo.levers["air"], self.demo.levers["drum"], self.demo.levers["burner"]), (30, 85, 75))
        self.assertIn("OT1,75", self.sent) # sent and recorded as the operator's setting
        rows = {row["n"]: row for row in self.alarms()["rows"]}
        self.assertEqual((rows[4]["state"], rows[4]["why"]), ("skip", "The preheat is set in Roast Setup"))
        self.assertEqual((rows[7]["state"], rows[7]["at"]), ("done", "0:02"))
        self.demo.mark("drop")
        self.roast(4)
        self.assertIn("CLDN,ON", self.sent) # event button 5 of the V2 setup
        self.assertEqual((self.demo.levers["air"], self.demo.levers["burner"], self.demo.levers["drum"]), (0, 0, 80))
        self.demo.stop()
        data = ast.literal_eval(Path(self.demo.export_alog(str(self.dir / "roasts"))).read_text(encoding="utf-8"))
        self.assertIn("A9 (S3)", data["specialeventsStrings"]) # burner 75 by alarm 9, as the desktop writes it
        self.assertIn("A7 (S0)", data["specialeventsStrings"])

    def test_a_burner_alarm_pauses_the_preheat_as_a_touch_does(self):
        self.demo.setup = {"preheat_target": 176.0}
        self.demo.config = configuration.save(self.config, {**configuration.load(self.config), "preheat_on": True})
        self.use("burner", alrm([(-1, 5, -3, 2, 0.0, 6, "60")])) # START + 5 s: burner 60
        self.start()
        self.roast(8, bt=60.0)
        self.assertEqual((json.loads(self.demo.snapshot())["preheat"]["state"], self.demo.levers["burner"]), ("paused", 60))

    def test_a_message_and_the_extractor_follow_their_alarms(self):
        self.use("mixed", alrm([(-1, 2, -3, 2, 0.0, 0, "DE!"), (-1, 3, -3, 2, 0.0, 26, "MODE FAN,FAN 30"),
                                (-1, 4, -3, 2, 0.0, 27, "CAL")]))
        self.start()
        self.roast(5)
        view = self.alarms()
        self.assertEqual(view["message"]["text"], "DE!")
        self.assertEqual(json.loads(self.demo.take_device_commands()),
                         [{"device": "extractor", "op": "mode", "value": "FAN"},
                          {"device": "extractor", "op": "speed", "value": "30"},
                          {"device": "ambient", "op": "command", "value": 0}]) # CAL: the empty-drum calibration
        self.demo.device_lever("extractor", 30) # the AirWave confirms the speed
        self.assertIn(len(self.demo.session.settings) - 1, self.demo.session.alarm_settings)
        self.assertIsNone(view["rows"][2]["why"])

    def test_the_next_roast_s_alarms_are_new_to_the_screen(self):
        self.use("message", alrm([(-1, 2, -3, 2, 0.0, 0, "DE!")]))
        self.start()
        self.roast(4)
        first = self.alarms()
        self.demo.stop()
        self.demo.reset() # New roast: the page stays, it skips ids it has already shown
        self.start()
        self.roast(4)
        second = self.alarms()
        self.assertGreater(second["message"]["id"], first["message"]["id"])
        self.assertGreater(second["recent"][-1]["id"], first["recent"][-1]["id"])

    def test_a_bean_temperature_condition_fires_on_the_roaster_reading(self):
        self.use("hot", alrm([(0, 0, 1, 1, 160.0, 3, "50")])) # after CHARGE, BT above 160: air 50
        self.start()
        self.roast(2, bt=150.0)
        self.demo.mark("charge")
        self.roast(3, bt=150.0)
        self.assertNotEqual(self.demo.levers["air"], 50)
        self.roast(1, bt=161.0)
        self.assertEqual(self.demo.levers["air"], 50)

    def test_a_drum_temperature_rate_condition_fires_on_the_roaster_reading(self):
        self.use("et-ror", alrm([(0, 0, -2, 1, 5.0, 3, "50")])) # after CHARGE, ET RoR above 5 °C/min: air 50
        self.start()
        self.roast(2, bt=150.0)
        self.demo.mark("charge")
        self.roast(10, bt=150.0) # steady: no rate
        self.assertNotEqual(self.demo.levers["air"], 50)
        for step in range(10):
            self.roast(1, bt=150.0 + 0.2 * step) # rising 12 °C/min
        self.assertEqual(self.demo.levers["air"], 50)

    def test_an_extra_probe_of_the_computer_is_read_from_the_tablet_s_own_channel(self):
        folder = self.dir / "roasts-computer"
        folder.mkdir()
        (folder / "latest.alog").write_text(repr({"tilau_name_map": {0: "skywalker_pf", 1: "difluid"}}), encoding="utf-8")
        self.use("inlet", alrm([(0, 0, 4, 1, 100.0, 3, "50")])) # source 4: device 1 (difluid), first channel (Inlet)
        self.start()
        self.roast(2, bt=150.0)
        self.demo.mark("charge")
        self.demo.extra_readings(json.dumps({"inlet_c": 90.0}))
        self.roast(1)
        self.assertNotEqual(self.demo.levers["air"], 50)
        self.demo.extra_readings(json.dumps({"inlet_c": 101.0}))
        self.roast(1)
        self.assertEqual(self.demo.levers["air"], 50)
        self.assertEqual(self.alarms()["rows"][0]["when"], "Charge · Inlet above 100")

    def test_the_editor_writes_each_change_to_the_list(self):
        self.use("minimal", MINIMAL)
        view = json.loads(self.demo.edit_alarm(json.dumps({"name": "minimal", "row": 6, "fields": {"text": "35", "on": 0}})))
        self.assertEqual((view["rows"][6]["what"], view["rows"][6]["on"]), ("Air 35 %", 0))
        self.assertIn('"alarmstrings":["20","0","80","","25","","35"', (self.dir / "alarms" / "minimal.alrm").read_text())
        with self.assertRaises(ValueError):
            self.demo.edit_alarm(json.dumps({"name": "minimal", "row": 6, "fields": {"guard": 6}})) # itself
        with self.assertRaises(ValueError):
            self.demo.edit_alarm(json.dumps({"name": "minimal", "row": 6, "fields": {"offset": -1}}))

    def test_a_deleted_alarm_comes_back_with_undo_and_a_move_keeps_the_links(self):
        self.use("minimal", MINIMAL)
        view = json.loads(self.demo.delete_alarm(json.dumps({"name": "minimal", "row": 0})))
        self.assertEqual((len(view["rows"]), view["rows"][0]["guard"]), (15, -1))
        self.assertEqual(json.loads(self.demo.undo_alarm("minimal"))["rows"][1]["guard"], 0)
        self.assertEqual((self.dir / "alarms" / "minimal.alrm").read_text(), MINIMAL)
        view = json.loads(self.demo.move_alarm(json.dumps({"name": "minimal", "from": 15, "to": 12})))
        self.assertEqual((view["rows"][12]["what"], view["rows"][12]["guard"]), ("Drum 80 %", 15))

    def test_a_new_list_and_deleting_the_active_one(self):
        self.use("minimal", MINIMAL)
        view = json.loads(self.demo.new_alarm_list())
        self.assertEqual((view["name"], view["rows"]), ("New list", []))
        self.assertEqual(json.loads(self.demo.add_alarm("New list"))["rows"][0]["action"], -1)
        lists = json.loads(self.demo.delete_alarm_list("minimal"))
        self.assertEqual(([l["name"] for l in lists["lists"]], lists["active"]), (["New list"], None))


if __name__ == "__main__":
    unittest.main()

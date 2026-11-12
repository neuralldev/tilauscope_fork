# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

import json
from pathlib import Path
import tempfile
import unittest

from tilauscope_mobile import config as configuration
from tilauscope_mobile.demo import Demo
from tilauscope_mobile.journal import recover


class JournalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "session.journal")

    def recording(self, seconds):
        demo = Demo(self.path)
        demo.start()
        demo.mark("charge")
        demo.advance(seconds)
        return demo

    def test_stopped_session_round_trips(self):
        demo = Demo(self.path)
        demo.start()
        demo.mark("charge")
        demo.advance(45)
        expected = json.loads(demo.stop())
        session, interrupted = recover(self.path)
        self.assertFalse(interrupted)
        replayed = session.snapshot(45)
        self.assertEqual(replayed, {key: expected[key] for key in replayed})
        self.assertEqual(session.document(45)["samples"],
                         demo.session.document(45)["samples"])

    def test_undone_milestone_stays_undone_after_recovery(self):
        demo = self.recording(10)
        demo.mark("dry_end")
        demo.unmark()
        demo.advance(5)
        demo.mark("dry_end")
        session, _ = recover(self.path)
        self.assertEqual(session.milestones, {"charge": 0, "dry_end": 15})

    def test_settings_are_recorded_echoed_and_replayed(self):
        demo = self.recording(10)
        snapshot = json.loads(demo.set_lever("burner", 75))
        self.assertEqual(snapshot["levers"]["burner"],
                         {"value": 75, "echo": 65, "pending": True, "step": 5, "name": "Burner"})
        echoed = json.loads(demo.advance(1))["levers"]["burner"]
        self.assertEqual((echoed["value"], echoed["echo"], echoed["pending"]), (75, 75, False))
        for bad in (105, -5, 7.5):
            with self.assertRaises(ValueError):
                demo.set_lever("burner", bad)
        session, _ = recover(self.path)
        self.assertEqual(session.settings[-1], (10, "burner", 75))
        self.assertEqual({lever for _, lever, _ in session.settings},
                         {"burner", "air", "drum", "extractor"}) # starting levels

    def test_device_reported_value_is_confirmed_and_recorded_once(self):
        demo = self.recording(10)
        lever = json.loads(demo.device_lever("extractor", 45))["levers"]["extractor"]
        self.assertEqual((lever["value"], lever["echo"], lever["pending"]), (45, 45, False))
        demo.device_lever("extractor", 45) # the same value again is no new setting
        demo.device_lever("extractor", 0) # switched off
        session, _ = recover(self.path)
        self.assertEqual([s for s in session.settings if s[1] == "extractor"],
                         [(0, "extractor", 20), (10, "extractor", 45), (10, "extractor", 0)])

    def test_room_is_read_at_charge_and_replayed(self):
        demo, clock = Demo(self.path), [100.0]
        demo.clock = lambda: clock[0]
        room = {"temperature_c": 22.8, "humidity_pct": 54.0, "pressure_hpa": 1013.2}
        demo.ambient_reading(json.dumps(room))
        demo.start()
        clock[0] += 2 # still fresh
        self.assertEqual(json.loads(demo.mark("charge"))["ambient_at_charge"], room)
        demo.advance(5)
        session, _ = recover(self.path)
        self.assertEqual(session.document(5)["ambient_at_charge"], room)
        demo.unmark() # that reading belonged to the undone charge
        clock[0] += 5 # now older than the probe's freshness limit
        demo.mark("charge")
        self.assertIsNone(json.loads(demo.snapshot())["ambient_at_charge"])
        self.assertIsNone(recover(self.path)[0].ambient)
        with self.assertRaises(ValueError):
            demo.ambient_reading(json.dumps({"temperature_c": 22.8}))

    def test_weights_green_before_roasted_after_and_replayed(self):
        demo = Demo(self.path)
        demo.set_weight("green", 250)
        with self.assertRaises(ValueError):
            demo.set_weight("roasted", 212) # not before the roast is over
        demo.start()
        demo.mark("charge")
        demo.advance(5)
        demo.stop()
        with self.assertRaises(ValueError):
            demo.set_weight("roasted", 212.6) # whole grams only
        demo.set_weight("roasted", 213)
        demo.set_weight("roasted", 212) # weighed again: the last one counts
        session, interrupted = recover(self.path)
        self.assertFalse(interrupted)
        self.assertEqual(session.weights, {"green": 250, "roasted": 212})
        self.assertEqual(json.loads(Demo(self.path).snapshot())["weights_g"], {"green": 250, "roasted": 212})

    def test_whole_and_ground_colours_kept_apart_after_the_roast(self):
        demo = self.recording(5)
        with self.assertRaises(ValueError):
            demo.set_colour("whole", 78.3) # not during the roast
        demo.stop()
        demo.set_colour("whole", 78.34)
        demo.set_colour("ground", 85.1)
        with self.assertRaises(ValueError):
            demo.set_colour("mixed", 80)
        self.assertEqual(json.loads(demo.snapshot())["colours"], {"whole": 78.3, "ground": 85.1})
        self.assertEqual(recover(self.path)[0].colours, {"whole": 78.3, "ground": 85.1})

    def test_new_roast_forgets_the_finished_one(self):
        demo = self.recording(5)
        demo.stop()
        demo.reset()
        self.assertEqual(json.loads(Demo(self.path).snapshot())["state"], "idle")

    def test_saved_roast_stays_saved_after_a_restart(self):
        demo = self.recording(5)
        demo.stop()
        self.assertIsNone(json.loads(demo.snapshot())["exported"])
        name = Path(demo.export_alog(str(Path(self.path).parent / "roasts"))).name
        self.assertEqual(json.loads(Demo(self.path).snapshot())["exported"], name)

    def test_read_only_machine_exposes_only_the_extractor(self):
        demo = Demo(self.path)
        demo.set_readonly(True)
        with self.assertRaises(ValueError):
            demo.set_lever("burner", 50)
        demo.set_lever("extractor", 30)
        demo.start()
        self.assertEqual(json.loads(demo.snapshot())["levers"].keys(), {"extractor"})
        with self.assertRaises(ValueError):
            demo.set_readonly(False) # not during a roast

    def test_signal_loss_leaves_a_gap_and_blocks_marks(self):
        demo = self.recording(10)
        demo.toggle_signal()
        demo.advance(5)
        snapshot = json.loads(demo.snapshot())
        self.assertTrue(snapshot["stale"])
        self.assertIsNone(snapshot["ror_c_per_min"])
        with self.assertRaises(ValueError):
            demo.mark("dry_end")
        demo.toggle_signal()
        demo.advance(1)
        times = [sample[0] for sample in json.loads(demo.snapshot(10))["samples"]]
        self.assertEqual(times, [10, 16]) # nothing fabricated for 11..15

    def test_process_death_restores_read_only_interrupted_session(self):
        self.recording(30) # never stopped: the process dies here
        restored = Demo(self.path)
        snapshot = json.loads(restored.snapshot())
        self.assertTrue(snapshot["interrupted"])
        self.assertEqual(snapshot["state"], "stopped")
        self.assertEqual(snapshot["sample_count"], 31)
        self.assertEqual(snapshot["milestones"], {"charge": 0})
        self.assertEqual(json.loads(restored.advance(1))["sample_count"], 31)
        with self.assertRaises(ValueError):
            restored.mark("dry_end")
        # Restoring never rewrites the journal: a second start sees the same record.
        self.assertTrue(json.loads(Demo(self.path).snapshot())["interrupted"])

    def test_a_milestone_found_back_in_the_curve_is_restored_after_process_death(self):
        demo = Demo(self.path)
        demo.start()
        demo.advance(10)
        demo._mark("charge", 4) # as the automatic detection places it: on the sample before the plunge
        demo.advance(5) # the process dies here
        snapshot = json.loads(Demo(self.path).snapshot())
        self.assertTrue(snapshot["interrupted"])
        self.assertEqual((snapshot["sample_count"], snapshot["milestones"]), (16, {"charge": 4}))
        self.assertFalse(Path(self.path + ".unreadable").exists())

    def test_a_restored_roast_keeps_who_set_each_lever_and_the_preheat_it_had(self):
        config = str(Path(self.path).parent / "config.json")
        configuration.save(config, {**configuration.default(), "machine": "skywalker-v2"}) # the preheat drives a machine
        demo = Demo(self.path, config)
        demo.start()
        demo.mark("charge")
        demo.advance(5)
        demo.session.pid_source = 2 # the preheat read the drum probe
        demo._mark_preheat(200.0)
        demo._pid_burner(60) # TilauPID
        demo._lever("air", 50, alarm=3) # alarm 3
        demo._lever("drum", 70) # the operator
        demo.advance(2) # the process dies here
        live = demo.session
        session, interrupted = recover(self.path)
        self.assertTrue(interrupted)
        self.assertEqual((session.pid_settings, session.alarm_settings, session.preheat_sv_c, session.pid_source),
                         (live.pid_settings, live.alarm_settings, 200.0, 2))

    def test_truncated_last_line_is_ignored(self):
        self.recording(10)
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write('{"event": "sample", "t": 11, "b')
        session, interrupted = recover(self.path)
        self.assertTrue(interrupted)
        self.assertEqual(len(session.samples), 11)

    def test_corrupt_journal_is_set_aside_and_a_new_session_starts(self):
        self.recording(10)
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        lines[3] = "garbage"
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            recover(self.path)
        snapshot = json.loads(Demo(self.path).snapshot())
        self.assertFalse(snapshot["interrupted"])
        self.assertEqual(snapshot["state"], "idle")
        self.assertTrue(Path(self.path + ".unreadable").exists())

    def test_milestone_index_mismatch_is_rejected(self):
        self.recording(5)
        text = Path(self.path).read_text(encoding="utf-8")
        Path(self.path).write_text(text.replace('"index": 0', '"index": 3'), encoding="utf-8")
        with self.assertRaises(ValueError):
            recover(self.path)


if __name__ == "__main__":
    unittest.main()

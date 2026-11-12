# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tilauscope_mobile.demo import Demo
from tilauscope_mobile.session import Reading, Session
from tilauscope_mobile.tc4 import TC4Decoder, decode


class SessionTests(unittest.TestCase):
    def test_constant_temperature_is_fresh_and_has_zero_ror(self):
        session = Session()
        session.start(100)
        for second in range(10):
            session.ingest(Reading(180), 100 + second)
        self.assertFalse(session.stale(109))
        self.assertEqual(session.ror(109), 0)
        self.assertTrue(session.stale(112))
        self.assertIsNone(session.ror(112))

    def test_ror_uses_time_not_sample_count(self):
        session = Session()
        session.start(0)
        for time in (0, 0.5, 2, 3, 4.5, 6):
            session.ingest(Reading(150 + time * 0.2, 140), time)
        self.assertAlmostEqual(session.ror(6), 12)
        session.ingest(Reading(180), 20)
        self.assertIsNone(session.ror(20))

    def test_invalid_readings_do_not_refresh_telemetry(self):
        session = Session()
        session.start(0)
        session.ingest(Reading(100), 0)
        for invalid in (-1, 0, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                session.ingest(Reading(invalid), 2)
        self.assertTrue(session.stale(3))
        self.assertEqual(len(session.samples), 1)

    def test_session_lifecycle_and_chronology(self):
        session = Session()
        with self.assertRaises(ValueError):
            session.ingest(Reading(100), 0)
        session.start(50)
        session.ingest(Reading(100), 50)
        for timestamp in (49, 50, float("nan")):
            with self.assertRaises(ValueError):
                session.ingest(Reading(120), timestamp)
        session.stop(51)
        self.assertEqual(session.snapshot(100)["elapsed_s"], 1)
        with self.assertRaises(ValueError):
            session.ingest(Reading(120), 52)
        with self.assertRaises(ValueError):
            session.start(52)

    def test_milestones_accept_charge_at_zero_and_reject_stale_marks(self):
        session = Session()
        session.start(0)
        session.ingest(Reading(100), 0)
        with self.assertRaises(ValueError):
            session.mark("first_crack", 0)
        session.mark("charge", 0)
        self.assertEqual(session.milestones["charge"], 0)
        with self.assertRaises(ValueError):
            session.mark("charge", 0)
        with self.assertRaises(ValueError):
            session.mark("dry_end", 3)
        session.ingest(Reading(150), 4)
        session.mark("first_crack", 4)
        with self.assertRaises(ValueError):
            session.mark("dry_end", 4)

    def test_checkpoint_is_identified_as_simulation_and_not_alog(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "demo.json")
            demo = Demo()
            demo.start()
            demo.advance(600)
            demo.save(str(target))
            document = json.loads(target.read_text())
            self.assertTrue(document["simulated"])
            self.assertEqual(document["format"], "tilauscope-mobile-session")
            self.assertEqual(len(document["samples"]), 601)
            self.assertEqual(document["samples"][-1]["elapsed_s"], 600)
            with self.assertRaises(ValueError):
                demo.save(str(Path(directory, "demo.alog")))
            original = target.read_bytes()
            demo.advance(30)
            with patch("tilauscope_mobile.demo.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    demo.save(str(target))
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [target])
            demo.reset()
            self.assertEqual(json.loads(demo.snapshot())["state"], "idle")


class TC4Tests(unittest.TestCase):
    def test_mapping_and_missing_echo(self):
        frame = decode(b"25,140,180,0,30")
        self.assertEqual(frame.reading.bt_c, 180)
        self.assertEqual(frame.reading.et_c, 140) # ET below BT is valid
        self.assertEqual(frame.burner_echo, 0)
        self.assertIsNone(decode(b"25,-1,180").reading.et_c)
        self.assertIsNone(decode(b"25,140,180,nan").burner_echo)

    def test_fragmentation_coalescing_and_invalid_lines(self):
        decoder = TC4Decoder()
        self.assertEqual(decoder.feed(b"25,140,18", generation=0), [])
        frames = decoder.feed(b"0,0,30\r\nboot\r\n25,141,181\r\n", generation=0)
        self.assertEqual([frame.reading.bt_c for frame in frames], [180, 181])
        self.assertEqual(decoder.feed(b"25,140,nan\r\n", generation=0), [])

    def test_reconnect_rejects_old_callbacks_and_partial_frames(self):
        decoder = TC4Decoder()
        decoder.feed(b"25,140,", generation=0)
        current = decoder.reset()
        self.assertEqual(decoder.feed(b"180\r\n", generation=0), [])
        frames = decoder.feed(b"25,141,181\r\n", generation=current)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].reading.bt_c, 181)

    def test_oversized_frame_does_not_poison_next_frame(self):
        decoder = TC4Decoder()
        with self.assertRaises(ValueError):
            decoder.feed(b"x" * 4097, generation=0)
        self.assertEqual(len(decoder.feed(b"25,140,180\r\n", generation=0)), 1)


if __name__ == "__main__":
    unittest.main()

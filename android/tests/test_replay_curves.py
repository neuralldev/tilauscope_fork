# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A recorded roast read back faithfully (tilaucore.roast_replay, android/LICENSING-SPEC.md L2)."""
import unittest

from tilaucore.roast_replay import Replay

TIMES = [10.0, 11.0, 12.0, 13.5, 15.0, 16.0]
PROFILE = {"mode": "C", "title": "Kenya AA", "timex": TIMES,
           "temp1": [-1, 150.0, 148.0, 146.5, 147.0, 149.0], "temp2": [-1, -1, 120.0, 110.0, 104.0, 103.5],
           "extratimex": [TIMES], "extratemp1": [[21.0, 21.5, 22.0, 22.5, 23.0, 23.5]],
           "extratemp2": [[40.0, 41.0, 42.0, 43.0, 44.0, 45.0]], "extraDelta1": [False], "extraDelta2": [True]}


class ReplayTests(unittest.TestCase):
    def test_the_replay_starts_at_the_first_bean_temperature(self):
        replay = Replay(PROFILE)
        self.assertEqual(replay.read(0), (148.0, 120.0))
        self.assertEqual(replay.length_s, 4.0)
        self.assertEqual(replay.title, "Kenya AA")

    def test_straight_between_two_readings_and_held_past_the_end(self):
        replay = Replay(PROFILE)
        self.assertEqual(replay.read(0.75), (147.25, 115.0)) # 1.5 s between the two readings
        self.assertEqual(replay.read(10), (149.0, 103.5))
        self.assertEqual(replay.read(-2), replay.read(0))

    def test_a_probe_dropout_is_skipped_not_drawn_as_a_plunge(self):
        replay = Replay(dict(PROFILE, temp2=[-1, -1, 120.0, -1, 104.0, 103.5]))
        self.assertAlmostEqual(replay.read(1.5)[1], 112.0)

    def test_a_probe_that_starts_later_has_no_reading_before(self):
        replay = Replay(dict(PROFILE, temp1=[-1, -1, -1, 146.5, 147.0, 149.0]))
        self.assertEqual(replay.read(1.0)[0], -1)
        self.assertEqual(replay.read(1.5)[0], 146.5)

    def test_a_sample_whose_time_steps_back_is_left_out(self):
        times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 4.6, 7.0]
        replay = Replay({"timex": times, "temp1": [150.0] * 8, "temp2": [100.0 + 3 * i for i in range(8)]})
        self.assertAlmostEqual(replay.read(6.0)[1], (115.0 + 121.0) / 2)

    def test_a_fahrenheit_file_is_read_in_celsius(self):
        f = dict(PROFILE, mode="F", temp1=[-1, 302.0, 298.4, 295.7, 296.6, 300.2],
                 temp2=[-1, -1, 248.0, 230.0, 219.2, 218.3], extratemp1=[[69.8] * 6], extratemp2=[[18.0] * 6])
        replay = Replay(f, "C")
        et, bt = replay.read(0)
        self.assertAlmostEqual(et, 148.0)
        self.assertAlmostEqual(bt, 120.0)
        first, rate = replay.read_extra(0, 0)
        self.assertAlmostEqual(first, 21.0)
        self.assertAlmostEqual(rate, 10.0) # a rate: no offset

    def test_a_channel_marked_not_a_temperature_is_never_converted(self):
        replay = Replay(dict(PROFILE, mode="F", extraNoneTempHint1=[True], extraDelta2=[False]), "C")
        self.assertEqual(replay.read_extra(0, 0)[0], 22.0)

    def test_extra_channels_and_their_absence(self):
        self.assertEqual(Replay(PROFILE).read_extra(0, 1.5), (22.5, 43.0))
        self.assertEqual(Replay(PROFILE).read_extra(1, 1.0), (-1, -1))
        no_extra = Replay({k: v for k, v in PROFILE.items() if not k.startswith("extra")})
        self.assertEqual(no_extra.read_extra(0, 1.0), (-1, -1))

    def test_a_file_without_a_bean_curve_gives_nothing(self):
        replay = Replay(dict(PROFILE, temp2=[-1] * 6))
        self.assertTrue(replay.empty)
        self.assertEqual(replay.read(3), (-1, -1))
        self.assertEqual(replay.length_s, 0.0)


if __name__ == "__main__":
    unittest.main()

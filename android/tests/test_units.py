# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roast file's units and stored values (tilaucore.units), from the format's definitions."""
import math
import unittest

from tilaucore import units


class TemperatureTests(unittest.TestCase):
    def test_water_boils_at_100_c_and_212_f(self):
        self.assertAlmostEqual(units.c_from_f(212.0), 100.0)
        self.assertAlmostEqual(units.f_from_c(100.0), 212.0)
        self.assertAlmostEqual(units.c_from_f(32.0), 0.0)

    def test_no_reading_stays_no_reading_in_any_unit(self):
        for convert in (units.c_from_f, units.f_from_c, units.ror_c_from_f, units.ror_f_from_c):
            self.assertEqual(convert(-1), -1)

    def test_a_rate_has_no_offset(self):
        self.assertAlmostEqual(units.ror_f_from_c(10.0), 18.0)
        self.assertAlmostEqual(units.ror_c_from_f(18.0), 10.0)

    def test_an_unknown_or_same_unit_leaves_the_value(self):
        self.assertEqual(units.convert_temp(200.0, "", "F"), 200.0)
        self.assertEqual(units.convert_temp(200.0, "C", ""), 200.0)
        self.assertEqual(units.convert_temp(200.0, "C", "C"), 200.0)
        self.assertAlmostEqual(units.convert_temp(200.0, "C", "F"), 392.0)
        self.assertAlmostEqual(units.convert_temp(392.0, "F", "C"), 200.0)


class WeightTests(unittest.TestCase):
    def test_units_by_index(self):
        g, kg, lb, oz = range(4)
        self.assertEqual(units.WEIGHT_UNITS, ("g", "Kg", "lb", "oz"))
        self.assertAlmostEqual(units.convert_weight(1.0, kg, g), 1000.0)
        self.assertAlmostEqual(units.convert_weight(1.0, lb, g), 453.59237)
        self.assertAlmostEqual(units.convert_weight(16.0, oz, lb), 1.0)
        self.assertAlmostEqual(units.convert_weight(250.0, g, kg), 0.25)
        self.assertEqual(units.convert_weight(0.1, kg, kg), 0.1)

    def test_an_unknown_unit_is_an_error(self):
        for source, target in ((4, 0), (0, 4), (-1, 0)):
            with self.assertRaises(IndexError):
                units.convert_weight(1.0, source, target)


class EventValueTests(unittest.TestCase):
    def test_a_position_is_stored_as_a_tenth_plus_one(self):
        self.assertEqual(units.event_from_slider(0), 0.0)
        self.assertAlmostEqual(units.event_from_slider(75), 8.5)
        self.assertAlmostEqual(units.event_from_slider(-5), -1.5)

    def test_every_position_reads_back(self):
        for position in range(-100, 101):
            self.assertEqual(units.slider_from_event(units.event_from_slider(position)), position)

    def test_a_value_within_one_reads_zero(self):
        for value in (None, -1.0, 0.0, 0.5, 1.0):
            self.assertEqual(units.slider_from_event(value), 0)


class StoredNumberTests(unittest.TestCase):
    def test_rounding_and_non_finite(self):
        self.assertEqual(units.round_to(12.345), 12.3)
        self.assertEqual(units.round_to(12.3456, 3), 12.346)
        self.assertEqual(units.round_to(12.6, 0), 13.0)
        self.assertEqual(units.round_to(math.nan), 0.0)
        self.assertEqual(units.round_to(math.inf, 2), 0.0)

    def test_weight_loss(self):
        self.assertAlmostEqual(units.weight_loss_pct(250.0, 215.0), 14.0)
        self.assertEqual(units.weight_loss_pct(0.0, 0.0), 0.0)
        self.assertEqual(units.weight_loss_pct(200.0, 210.0), 0.0)

    def test_escaped_text(self):
        self.assertEqual(units.decode_escaped("caf\\u00e9"), "café")
        self.assertEqual(units.decode_escaped("Br\\xfbleur"), "Brûleur")
        self.assertEqual(units.decode_escaped(None, "g"), "g")
        self.assertEqual(units.decode_escaped("\\", "g"), "g")


if __name__ == "__main__":
    unittest.main()

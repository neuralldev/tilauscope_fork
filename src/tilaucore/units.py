# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Units and stored values of a roast file (.alog), as the file format defines them.

-1 is the format's "no reading": a temperature or a RoR of -1 stays -1 in any unit.
A slider position N (in %, or in steps) is stored as an event value N/10 + 1
(N/10 - 1 below zero); 0 is stored as 0, and any stored value within ±1 reads back as 0.
"""

from __future__ import annotations

import codecs
import math
from typing import Any, Final

NO_READING: Final[float] = -1

WEIGHT_UNITS: Final[tuple[str, str, str, str]] = ('g', 'Kg', 'lb', 'oz')  # the format's weight unit indices
_GRAMS_PER_UNIT: Final[tuple[float, float, float, float]] = (1.0, 1000.0, 453.59237, 453.59237 / 16)


def c_from_f(f: float) -> float:
    return f if f == NO_READING else (f - 32.0) * 5.0 / 9.0


def f_from_c(c: float) -> float:
    return c if c == NO_READING else c * 9.0 / 5.0 + 32.0


def ror_c_from_f(ror: float) -> float:
    """A rate (degrees per minute) has no offset: only the degree size changes."""
    return ror if ror == NO_READING else ror * 5.0 / 9.0


def ror_f_from_c(ror: float) -> float:
    return ror if ror == NO_READING else ror * 9.0 / 5.0


def convert_temp(t: float, source: str, target: str) -> float:
    """`t` from `source` to `target` ('C' or 'F'); an unknown unit ('') leaves it as it is."""
    if not source or not target or source == target:
        return t
    return f_from_c(t) if source == 'C' else c_from_f(t)


def convert_weight(value: float, source: int, target: int) -> float:
    """`value` from one WEIGHT_UNITS index to another."""
    if not (0 <= source < len(_GRAMS_PER_UNIT) and 0 <= target < len(_GRAMS_PER_UNIT)):
        raise IndexError(f'no weight unit {source} or {target}')
    if source == target:
        return value
    return value * _GRAMS_PER_UNIT[source] / _GRAMS_PER_UNIT[target]


def event_from_slider(position: float) -> float:
    """The event value stored for a slider position."""
    if position == 0:
        return 0.0
    return position / 10 + (1 if position > 0 else -1)


def slider_from_event(value: float | None) -> int:
    """The slider position a stored event value stands for."""
    if value is None or -1.0 <= value <= 1.0:
        return 0
    steps = round(abs(value) * 10) - 10
    return steps if value > 0 else -steps


def decode_escaped(text: Any | None, default: str = '') -> str:
    """A text the file stores with its non-ASCII characters escaped (\\xfb, \\u00e9)."""
    if text is None:
        return default
    try:
        return codecs.unicode_escape_decode(text)[0]
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return default


def round_to(value: float, digits: int = 1) -> float:
    """A number as the file stores it: rounded, and 0 when it is not finite."""
    if not math.isfinite(value):
        return 0.0
    return float(round(value)) if digits <= 0 else round(value, digits)


def weight_loss_pct(green: float, roasted: float) -> float:
    """Weight lost in roasting, % of the green weight; 0 when it cannot be told."""
    if green == 0 or roasted > green:
        return 0.0
    return (green - roasted) / green * 100.0

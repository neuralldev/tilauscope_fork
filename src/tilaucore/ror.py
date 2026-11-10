# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The rate of rise (RoR): how fast a temperature climbs, in degrees per minute (android/LICENSING-SPEC.md L6).

At each reading, the RoR is the slope of the straight line fitted (least squares) to the real
readings of the last `window_s` seconds. One step and one setting: a longer window is steadier and
trails the bean by about half of it. A reading the probe missed (-1, None, NaN) is left out of the
fit, never bridged. No value while the window holds fewer than three readings or spans less than
half of itself.

Measured on the reference hand (62 roasts): the 20 s window reads the plan's marks (peak, Dry End,
plateau before FC, FC, FC+1:20, DROP) within 0.1 °C/min of the rate the doctrine was measured with.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

RESPONSIVE_S: Final[float] = 15.0
STANDARD_S: Final[float] = 20.0
SMOOTH_S: Final[float] = 30.0
MIN_READINGS: Final[int] = 3

# The window of each smoothing level, by the (span, filter) the level sets in Artisan's RoR settings.
_LEVEL_WINDOWS: Final[dict[tuple[int, int], float]] = {(10, 5): RESPONSIVE_S, (15, 7): STANDARD_S, (25, 9): SMOOTH_S}


@dataclass(frozen=True)
class RoRSettings:
    """How a roast's RoR is computed and which values are kept."""
    window_s: float = STANDARD_S
    limit: bool = True          # values outside ]limit_min, limit_max[ are not kept
    limit_min: float = -10
    limit_max: float = 45
    delta_span_s: float = 0.0   # the span of the machine's setup, when it gives one (the preheat reads it)


def window_for(span_s: float, delta_filter: float) -> float:
    """The window of the smoothing level these two RoR settings stand for; Standard for any other pair."""
    try:
        return _LEVEL_WINDOWS.get((int(span_s), int(delta_filter)), STANDARD_S)
    except (TypeError, ValueError):
        return STANDARD_S


def _reads(value: float | None) -> bool:
    return value is not None and value != -1 and not math.isnan(value)


def rate_at(times: Sequence[float], temp: Sequence[float | None], i: int, window_s: float = STANDARD_S) -> float | None:
    """The RoR at reading `i`, per minute; None when the window is too thin."""
    now = times[i]
    xs: list[float] = []
    ys: list[float] = []
    j = i
    while j >= 0 and now - times[j] <= window_s:
        if _reads(temp[j]):
            xs.append(times[j])
            ys.append(temp[j])  # type: ignore[arg-type]
        j -= 1
    if len(xs) < MIN_READINGS or xs[0] - xs[-1] < window_s / 2:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread <= 0:
        return None
    return 60.0 * sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread


def rate_now(times: Sequence[float], temp: Sequence[float | None], settings: RoRSettings | None = None) -> float | None:
    """The RoR at the last reading, as `rate_of_rise` gives it."""
    s = settings or RoRSettings()
    rate = rate_at(times, temp, min(len(times), len(temp)) - 1, s.window_s) if times and temp else None
    return None if rate is None or (s.limit and not s.limit_min < rate < s.limit_max) else rate


def rate_of_rise(times: Sequence[float], temp: Sequence[float | None], settings: RoRSettings | None = None,
                 start: int = 0, end: int | None = None) -> list[float | None]:
    """The RoR of every reading, per minute; None outside readings `start`..`end` (to the last when None),
    where the window is too thin, and outside the settings' limits."""
    s = settings or RoRSettings()
    last = len(times) - 1 if end is None else end
    out: list[float | None] = []
    for i in range(min(len(times), len(temp))):
        rate = rate_at(times, temp, i, s.window_s) if start <= i <= last else None
        out.append(None if rate is None or (s.limit and not s.limit_min < rate < s.limit_max) else rate)
    return out

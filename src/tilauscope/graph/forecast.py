#
# ABOUT
# when the bean is due to reach the target of the phase it is in

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2026

"""The countdown to the next milestone — "DRY END in 1:20".

On the Artisan canvas this came out of a drawing: a projection line was plotted
forward from the bean, and the forecast was where that line crossed the target.
The crossing therefore depended on how far the line had been drawn, which is to
say on the width of the axes — a forecast that could vanish because a window
was narrow.

Here it is arithmetic, and the same arithmetic the projection was drawing: the
bean is climbing at a known rate, the target is a known distance above it. Both
figures are read in whatever unit the operator is in, so the countdown needs no
conversion — only the two of them agreeing, which they do by construction.

The reading is deliberately unsmoothed. It feeds the card, where the countdown
is expected to move; what is drawn on the chart goes through `Smoother`, because
a marker that jitters by a pixel every second reads as a fault in the chart.
"""

from __future__ import annotations

from typing import Any, Final

#: Weight of the newest reading in the drawn marker's position.
_EMA_ALPHA: Final[float] = 0.2
#: The marker does not move until the smoothed forecast has drifted this far.
_DEADBAND_S: Final[float] = 3.0


def milestone(qmc: Any, info: dict) -> float | None:
    """Absolute seconds at which the bean is due to reach `info['target']`.

    None whenever no honest answer exists: no rate, a bean already past the
    target, or a phase whose target has degenerated to the live reading — which
    is what happens after first crack, where there is nothing left to forecast.
    """
    try:
        target = float(info['target'])
        now = float(qmc.timex[-1])
        bt = float(qmc.temp2[-1])
        rate = qmc.rateofchange2
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        return None
    if rate is None:
        return None
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return None
    if rate <= 0 or target <= bt:
        return None
    return now + (target - bt) * 60.0 / rate


class Smoother:
    """Holds the drawn forecast still enough to be read.

    The raw forecast steps by several seconds from one sample to the next, all
    of it honest and none of it useful to look at. An exponential average takes
    the step out, and a dead band keeps the marker where it is until the average
    has actually moved somewhere.
    """

    def __init__(self) -> None:
        self._ema: float | None = None
        self._shown: float | None = None

    def reset(self) -> None:
        self._ema = self._shown = None

    def feed(self, raw: float | None) -> float | None:
        if raw is None:
            self.reset()
            return None
        if self._ema is None:
            self._ema = self._shown = raw
            return self._shown
        self._ema = _EMA_ALPHA * raw + (1.0 - _EMA_ALPHA) * self._ema
        if self._shown is None or abs(self._ema - self._shown) >= _DEADBAND_S:
            self._shown = self._ema
        return self._shown

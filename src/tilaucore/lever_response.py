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

"""A replayed roast that answers the burner and the air (android/SIM-SPEC.md §3b, S3).

The recorded curve stays the reference; from CHARGE the BT moves away from it by how far each lever is
from the recorded roast's at the same moment (a lever the recorded roast never moved: by its moves since
CHARGE), each gap felt through the probe's dead time and a first-order lag.
For checking that automations react, not for learning or steering: the values are the corpus's orders
of size on the Skywalker V2 (see the spec for how they were measured).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

DEAD_S = 5.5  # the bean probe's delay, measured on the Skywalker V2
TAU_S = {"burner": 30.0, "air": 15.0}
GAIN = {  # °C/min of the BT's RoR per lever point, by phase
    "burner": {"dry": 0.4, "mai": 0.4, "dev": 0.4},
    "air": {"dry": 0.0, "mai": 0.33, "dev": 0.0},  # in development the air chases the smoke
}


class LeverResponse:
    """One simulated roast's offset from the recorded BT."""

    def __init__(self, recorded: dict[str, Sequence[tuple[float, int]]]) -> None:
        """`recorded`: each lever's moves in the recorded roast, (replay time, %), in time order."""
        self.recorded = {lever: ([t for t, _ in moves], [v for _, v in moves])
                         for lever, moves in recorded.items() if lever in GAIN}
        self._charge: dict[str, float] | None = None  # at the live CHARGE, the levers the recorded roast never moved
        self._history: dict[str, list[tuple[float, float]]] = {lever: [] for lever in GAIN}
        self._felt = dict.fromkeys(GAIN, 0.0)
        self._last: float | None = None
        self.bt_offset = 0.0

    def _recorded_at(self, lever: str, t: float) -> float | None:
        """The recorded lever at t; before its first move, that move's level; never moved, None."""
        times, values = self.recorded.get(lever, ([], []))
        if not values:
            return None
        return float(values[max(0, bisect.bisect_right(times, t) - 1)])

    def _gap(self, lever: str, t: float, live: float) -> float:
        recorded = self._recorded_at(lever, t)
        return live - recorded if recorded is not None else live - self._charge[lever]

    def step(self, t: float, live: dict[str, float], phase: str) -> float:
        """At replay time t, the live levers and the live phase (dry, mai, dev): the BT offset, °C."""
        if self._charge is None:
            self._charge = {lever: live.get(lever, 0.0) for lever in GAIN}
            self._last = t
        dt = t - self._last if self._last is not None else 0.0
        self._last = t
        ror = 0.0
        for lever in GAIN:  # the RoR each gap asks for, felt late: a new phase's gain settles as a move would
            history = self._history[lever]
            history.append((t, GAIN[lever][phase] * self._gap(lever, t, live.get(lever, 0.0))))
            felt = next((g for when, g in reversed(history) if when <= t - DEAD_S), None)
            if felt is not None and dt > 0:
                self._felt[lever] += (felt - self._felt[lever]) * (1 - math.exp(-dt / TAU_S[lever]))
            ror += self._felt[lever]
        self.bt_offset += ror * dt / 60
        return self.bt_offset

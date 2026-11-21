# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A replayed roast that answers the burner and the air (android/SIM-SPEC.md §3b, S3).

The recorded curve stays the reference; from CHARGE the BT moves away from it by how far each lever is
from the recorded roast's at the same moment (a lever the recorded roast never moved: by its moves since
CHARGE), each gap felt through the probe's dead time and a first-order lag.
For checking that automations react, not for learning or steering: dead time, lags and gains are the
roaster's `lever_response` (roasters.json; the common default holds the corpus's orders of size on the
Skywalker V2, see the spec for how they were measured).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

from tilaucore.roasters import machine_value


def _merged(default: dict, own: dict) -> dict:
    """`own` over `default`, key by key at every depth: a roaster declares only what differs."""
    out = dict(default)
    for key, value in own.items():
        out[key] = _merged(default[key], value) if isinstance(value, dict) and isinstance(default.get(key), dict) else value
    return out


class LeverResponse:
    """One simulated roast's offset from the recorded BT."""

    def __init__(self, recorded: dict[str, Sequence[tuple[float, int]]], response: "dict | None" = None) -> None:
        """`recorded`: each lever's moves in the recorded roast, (replay time, %), in time order.
        `response`: the roaster's lever_response (dead_s, tau_s, gain in °C/min of RoR per lever point,
        by phase); roasters.json's common default without one."""
        response = _merged(machine_value(None, "lever_response"), response or {})
        self._dead_s = float(response["dead_s"])
        self._tau_s = {lever: float(v) for lever, v in response["tau_s"].items()}
        self._gain = {lever: {phase: float(g) for phase, g in by_phase.items()}
                      for lever, by_phase in response["gain"].items()}
        self.recorded = {lever: ([t for t, _ in moves], [v for _, v in moves])
                         for lever, moves in recorded.items() if lever in self._gain}
        self._charge: dict[str, float] | None = None  # at the live CHARGE, the levers the recorded roast never moved
        self._history: dict[str, list[tuple[float, float]]] = {lever: [] for lever in self._gain}
        self._felt = dict.fromkeys(self._gain, 0.0)
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
            self._charge = {lever: live.get(lever, 0.0) for lever in self._gain}
            self._last = t
        dt = t - self._last if self._last is not None else 0.0
        self._last = t
        ror = 0.0
        for lever in self._gain:  # the RoR each gap asks for, felt late: a new phase's gain settles as a move would
            history = self._history[lever]
            history.append((t, self._gain[lever][phase] * self._gap(lever, t, live.get(lever, 0.0))))
            felt = next((g for when, g in reversed(history) if when <= t - self._dead_s), None)
            if felt is not None and dt > 0:
                self._felt[lever] += (felt - self._felt[lever]) * (1 - math.exp(-dt / self._tau_s[lever]))
            ror += self._felt[lever]
        self.bt_offset += ror * dt / 60
        return self.bt_offset

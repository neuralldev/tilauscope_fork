# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.
#
# Portions derived from Artisan Roaster Scope (artisanlib/simulator.py),
# Copyright (C) 2010-2026 the Artisan team represented by Marko Luther
# and all contributors, distributed under the terms of their original licence.

"""A recorded roast replayed as the roaster's readings (android/SIM-SPEC.md S1).

Artisan's simulator (artisanlib/simulator.py) without numpy: the profile's curves
from its first valid BT, times shifted to start at 0, read at any time by linear
interpolation; before the first and past the last sample the end reading holds.
A reading that cannot be given is -1, as there.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from tilaucore.artisan_compat import RoRfromCtoFstrict, RoRfromFtoCstrict, fromCtoFstrict, fromFtoCstrict


_IN_CACHE = 8  # numpy's LIKELY_IN_CACHE_SIZE


def _search(key: float, arr: Sequence[float]) -> int:
    """numpy's binary_search_with_guess from its first guess (compiled_base.c): the same index even
    where a roast's times step back, which a plain bisection would not give."""
    n, imin, imax = len(arr), 0, len(arr)
    if key > arr[-1]:
        return n
    if key < arr[0]:
        return -1
    if n <= 4:
        i = 1
        while i < n and key >= arr[i]:
            i += 1
        return i - 1
    guess = max(1, min(0, n - 3))
    if key < arr[guess]:
        if key >= arr[guess - 1]:
            return guess - 1
        imax = guess - 1
        if guess > _IN_CACHE and key >= arr[guess - _IN_CACHE]:
            imin = guess - _IN_CACHE
    else:
        if key < arr[guess + 1]:
            return guess
        if key < arr[guess + 2]:
            return guess + 1
        imin = guess + 2
        if guess < n - _IN_CACHE - 1 and key < arr[guess + _IN_CACHE]:
            imax = guess + _IN_CACHE
    while imin < imax:
        mid = imin + ((imax - imin) >> 1)
        if key >= arr[mid]:
            imin = mid + 1
        else:
            imax = mid
    return imin - 1


def _interp(x: float, xp: Sequence[float], fp: Sequence[float]) -> float:
    """numpy.interp at one point; ValueError, as there, when the curve is empty or its lengths differ."""
    if not xp or len(xp) != len(fp):
        raise ValueError("no curve to read")
    if len(xp) == 1:
        return float(fp[0])
    j = _search(x, xp)
    if j == -1:
        return float(fp[0])
    if j >= len(xp) - 1:
        return float(fp[-1])
    if xp[j] == x:
        return float(fp[j])
    slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])
    return float(math.fma(slope, x - xp[j], fp[j])) # one rounding, as numpy's compiled loop on ARM


class Replay:
    """The curves of one roast file (an .alog already parsed), in `mode` ('C' or 'F')."""

    def __init__(self, profile: dict[str, Any], mode: str = "C") -> None:
        temp1, temp2, timex = list(profile.get("temp1", [])), list(profile.get("temp2", [])), list(profile.get("timex", []))
        has_extra = all(k in profile for k in ("extratemp1", "extratemp2", "extratimex"))
        extra1 = [list(c) for c in profile["extratemp1"]] if has_extra else []
        extra2 = [list(c) for c in profile["extratemp2"]] if has_extra else []
        extratimex = [list(c) for c in profile["extratimex"]] if has_extra else []
        n = min(len(extratimex), len(extra1), len(extra2))
        if "extraDelta1" in profile and "extraDelta2" in profile:
            delta1, delta2 = profile["extraDelta1"], profile["extraDelta2"]
        else:
            delta1, delta2 = [False] * n, [False] * n
        hint1, hint2 = profile.get("extraNoneTempHint1", []), profile.get("extraNoneTempHint2", [])

        source = profile.get("mode", mode)
        if source != mode and {source, mode} == {"C", "F"}:
            temp_of, ror_of = ((fromFtoCstrict, RoRfromFtoCstrict) if mode == "C" else (fromCtoFstrict, RoRfromCtoFstrict))
            temp1, temp2 = [temp_of(t) for t in temp1], [temp_of(t) for t in temp2]
            for e in range(n):
                for channel, delta, hint in ((extra1, delta1, hint1), (extra2, delta2, hint2)):
                    if e < len(delta) and delta[e]:
                        channel[e] = [ror_of(t) for t in channel[e]]
                    elif not (len(hint) > e and hint[e]):
                        channel[e] = [temp_of(t) for t in channel[e]]

        self.title = str(profile.get("title") or "")
        # from the first valid BT (Artisan's removeEmptyPrefix); none: nothing to replay
        start = next((i for i, v in enumerate(temp2) if v != -1), None)
        self.empty = start is None
        start = 0 if start is None else start
        self.et, self.bt = (temp1[start:], temp2[start:]) if not self.empty else ([], [])
        times = timex[start:] if not self.empty else []
        self.times = [t - times[0] for t in times] if times else []
        self.extra: list[tuple[list[float], list[float], list[float]]] = []
        if not self.empty:
            for e in range(n):
                t = extratimex[e][start:]
                self.extra.append(([v - t[0] for v in t] if t else [], extra1[e][start:], extra2[e][start:]))

    @property
    def length_s(self) -> float:
        return self.times[-1] if self.times else 0.0

    def read(self, t: float) -> tuple[float, float]:
        """ET and BT at `t` seconds of the replay."""
        return self._pair(t, self.times, self.et, self.bt)

    def read_extra(self, i: int, t: float) -> tuple[float, float]:
        """Extra device `i`'s two channels at `t` (first, second; Artisan's readextra returns them swapped)."""
        if i >= len(self.extra):
            return -1.0, -1.0
        return self._pair(t, *self.extra[i])

    @staticmethod
    def _pair(t: float, times: Sequence[float], first: Sequence[float], second: Sequence[float]) -> tuple[float, float]:
        """Both curves at `t`, read one after the other as Artisan does: a failure leaves the rest at -1."""
        values = [-1.0, -1.0]
        try:
            for k, curve in enumerate((first, second)):
                values[k] = float(curve[0]) if t == 0 else _interp(t, times, curve)
        except (IndexError, ValueError):
            pass
        return values[0], values[1]

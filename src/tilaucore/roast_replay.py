# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A recorded roast replayed as the roaster's readings (android/SIM-SPEC.md S1).

The replay starts at the first bean temperature the file holds (its 0 s). Each curve is
read faithfully at any time: straight between two real readings, a probe dropout (-1)
skipped rather than drawn as a plunge, a sample whose time steps back left out. Before a
probe's first reading there is none (-1); past its last one the last reading holds.
A file in the other unit is converted first: temperatures, rates (extra channels marked
as deltas), and nothing for channels marked as not temperatures.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from typing import Any

from tilaucore.units import NO_READING, c_from_f, f_from_c, ror_c_from_f, ror_f_from_c


def _valid(value: Any) -> bool:
    return isinstance(value, (int, float)) and value != NO_READING and math.isfinite(value)


class _Curve:
    """One probe's real readings, in time order."""

    def __init__(self, times: Sequence[float], values: Sequence[Any]) -> None:
        self.times: list[float] = []
        self.values: list[float] = []
        for t, v in zip(times, values, strict=False):
            if _valid(v) and (not self.times or t > self.times[-1]):
                self.times.append(float(t))
                self.values.append(float(v))

    def at(self, t: float) -> float:
        if not self.times or t < self.times[0]:
            return NO_READING
        i = bisect_right(self.times, t) - 1
        if i >= len(self.times) - 1:
            return self.values[-1]
        t0, t1, v0, v1 = self.times[i], self.times[i + 1], self.values[i], self.values[i + 1]
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def _converter(source: str, target: str, kind: str) -> Callable[[float], float] | None:
    if source == target or {source, target} != {"C", "F"} or kind == "none":
        return None
    if kind == "rate":
        return ror_c_from_f if target == "C" else ror_f_from_c
    return c_from_f if target == "C" else f_from_c


def _converted(values: Sequence[Any], convert: Callable[[float], float] | None) -> list[Any]:
    if convert is None:
        return list(values)
    return [convert(v) if _valid(v) else v for v in values]


class Replay:
    """The curves of one roast file (an .alog already parsed), in `mode` ('C' or 'F')."""

    def __init__(self, profile: dict[str, Any], mode: str = "C") -> None:
        source = str(profile.get("mode") or mode)
        timex = list(profile.get("timex") or [])
        temp_of = _converter(source, mode, "temperature")
        et = _converted(profile.get("temp1") or [], temp_of)
        bt = _converted(profile.get("temp2") or [], temp_of)
        self.title = str(profile.get("title") or "")

        start = next((i for i, v in enumerate(bt) if _valid(v) and i < len(timex)), None)
        self.empty = start is None
        zero = timex[start] if start is not None else 0.0
        times = [t - zero for t in timex[start:]] if start is not None else []
        self._et = _Curve(times, et[start:] if start is not None else [])
        self._bt = _Curve(times, bt[start:] if start is not None else [])

        self._extra: list[tuple[_Curve, _Curve]] = []
        extra_times = profile.get("extratimex") or []
        if start is not None and "extratemp1" in profile and "extratemp2" in profile:
            for e, channel_times in enumerate(extra_times):
                pair = []
                for channel in (1, 2):
                    values = (profile[f"extratemp{channel}"] or [])
                    values = values[e] if e < len(values) else []
                    is_rate = (profile.get(f"extraDelta{channel}") or [])
                    not_temp = (profile.get(f"extraNoneTempHint{channel}") or [])
                    kind = ("rate" if e < len(is_rate) and is_rate[e]
                            else "none" if e < len(not_temp) and not_temp[e] else "temperature")
                    values = _converted(values, _converter(source, mode, kind))
                    pair.append(_Curve([t - zero for t in channel_times[start:]], values[start:]))
                self._extra.append((pair[0], pair[1]))

    @property
    def length_s(self) -> float:
        return self._bt.times[-1] if self._bt.times else 0.0

    def read(self, t: float) -> tuple[float, float]:
        """ET and BT at `t` seconds of the replay."""
        t = max(0.0, t)
        return self._et.at(t), self._bt.at(t)

    def read_extra(self, i: int, t: float) -> tuple[float, float]:
        """Extra device `i`'s two channels at `t`."""
        if not 0 <= i < len(self._extra):
            return NO_READING, NO_READING
        t = max(0.0, t)
        first, second = self._extra[i]
        return first.at(t), second.at(t)

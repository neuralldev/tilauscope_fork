# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.
#
# Portions derived from Artisan Roaster Scope (artisanlib/canvas.py),
# Copyright (C) 2010-2026 the Artisan team represented by Marko Luther
# and all contributors, distributed under the terms of their original licence.

"""Roast Replay: a recorded roast's slider moves played back (android/AUTOMATION-SPEC.md D2).

Artisan's background event playback (canvas.playbackevent, timealign, updateReplayedBackgroundEvents)
for its four sliders, without numpy and without the screen: the playback aid, its beep and the Fuji
PID strings stay with the desktop. Times are the roast clock's seconds, temperatures the roast's unit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tilaucore.artisan_compat import events_internal_to_external_value as _external

BY_TIME, BY_BT, BY_ET, BY_TIME_BT, BY_TIME_ET = 0, 1, 2, 3, 4  # Artisan's replayType


def _line(x0: float, x1: float, y0: float, y1: float, x: float) -> float:
    """numpy.poly1d(numpy.polyfit([x0, x1], [y0, y1], 1))(x), to the last bits."""
    if x1 == x0: # polyfit's least-norm answer on its scaled columns, where numpy warns and goes on
        if x0 == 0:
            return (y0 + y1) / 2
        return (y0 + y1) / 4 * (x / x0 + 1)
    slope = (y1 - y0) / (x1 - x0)
    return slope * x + (y0 - slope * x0)


@dataclass
class Foreground:
    """The live roast as the playback reads it: its samples, its smoothed curves, its slider events."""
    timex: Sequence[float]
    temp1: Sequence[float]
    temp2: Sequence[float]
    ctemp1: Sequence[float | None]
    ctemp2: Sequence[float | None]
    tp_index: int | None = None
    events: Sequence[int] = field(default_factory=list)  # sample index of each event
    etypes: Sequence[int] = field(default_factory=list)
    evalues: Sequence[float] = field(default_factory=list)  # internal values, as recorded


class Playback:
    """The background roast and what of it was replayed already."""

    def __init__(self, times: Sequence[float], temp1: Sequence[float], temp2: Sequence[float],
                 stemp1: Sequence[float], stemp2: Sequence[float], events: Sequence[int],
                 etypes: Sequence[int], evalues: Sequence[float], timeindex: Sequence[int],
                 replay_type: int = BY_BT, playback: Sequence[bool] = (True,) * 4,
                 ramp: Sequence[bool] = (True,) * 4, lookahead_s: float = 0, moves: bool = True,
                 aid: Sequence[bool] = (False,) * 4, aid_window_s: float = 0) -> None:
        # read in place, never copied: the desktop builds one at every sample
        self.times = times
        self.temp1, self.temp2, self.stemp1, self.stemp2 = temp1, temp2, stemp1, stemp2
        self.events, self.etypes, self.evalues = events, etypes, evalues
        self.timeindex = timeindex
        self.replay_type, self.playback, self.ramp = replay_type, list(playback), list(ramp)
        self.lookahead_s = lookahead_s
        self.moves = moves  # off: the events still pass (the playback aid), no slider moves or ramps
        self.aid, self.aid_window_s = list(aid), aid_window_s
        self.replayed: set[int] = set()
        self.fired: list[int] = []  # the background events the last step passed, in order
        self.announced: tuple[int, float] | None = None  # the event the playback aid tells, s before it

    def align(self, charge_time: float) -> None:
        """timealign at CHARGE: the background moves by whole seconds onto the live roast's CHARGE."""
        if self.timeindex[0] == -1:
            return
        difference = charge_time - self.times[self.timeindex[0]]
        step = float(int(round(abs(difference))))
        if difference > 0:
            self.times = [t + step for t in self.times]
        elif difference < 0:
            self.times = [t - step for t in self.times]

    def engage(self, now: float, charge_time: float | None, sample_interval_s: float, auto_charge: bool = False) -> None:
        """turn_playback_event_ON: the background events already past are never played."""
        self.replayed = set()
        start = charge_time if charge_time is not None else 0
        short_after_charge = False
        additional = 3 if auto_charge else 2
        if charge_time is not None and now - start < additional * sample_interval_s:
            now -= additional * sample_interval_s
            short_after_charge = True
        for i, bge in enumerate(self.events):
            if len(self.times) <= bge:
                continue
            if self.times[bge] - now <= 0 and not (short_after_charge and self.times[bge] < 0):
                self.replayed.add(i)

    def step(self, now: float, live: Foreground) -> tuple[dict[int, int], list[float | None]]:
        """At a sample after CHARGE: the slider jumps (type: external value, each recorded as an event)
        and the ramps (type: value, sent but not recorded)."""
        end_reached = [not flag for flag in self.playback]
        ramps: list[float | None] = [None, None, None, None]
        jumps: dict[int, int] = {}
        next_by_temp_checked = [False, False, False, False]
        self.fired, self.announced = [], None
        drop = self.timeindex[6]

        last_foreground: dict[int, int] = {}  # the last live event of each type, found once per sample
        for k, live_type in enumerate(live.etypes):
            last_foreground[live_type] = k

        for i, bge in enumerate(self.events):
            if all(end_reached):
                break
            event_type = self.etypes[i]
            if not 0 <= event_type < 4:
                continue
            if i in self.replayed or end_reached[event_type] or not (drop == 0 or bge <= drop) or len(self.times) <= bge:
                continue
            last_fg = last_foreground.get(event_type)
            value_decreasing = (last_fg is not None and len(live.evalues) > last_fg
                                and live.evalues[last_fg] > self.evalues[i])
            timed = self.times[bge] - now
            delta: float = 99999
            rt = self.replay_type
            if rt == BY_TIME or (rt in {BY_TIME_BT, BY_TIME_ET} and not value_decreasing):
                delta = timed
            elif not next_by_temp_checked[event_type] and (rt == BY_BT or (rt == BY_TIME_BT and value_decreasing)):
                if live.tp_index is not None:
                    if live.ctemp2 and live.ctemp2[-1] is not None and len(self.stemp2) > bge:
                        delta = self.stemp2[bge] - live.ctemp2[-1]
                    next_by_temp_checked[event_type] = True
                else:
                    delta = timed
            elif not next_by_temp_checked[event_type] and (rt == BY_ET or (rt == BY_TIME_ET and value_decreasing)):
                if live.tp_index is not None:
                    if live.ctemp1 and live.ctemp1[-1] is not None and len(self.stemp1) > bge:
                        delta = self.stemp1[bge] - live.ctemp1[-1]
                    next_by_temp_checked[event_type] = True
                else:
                    delta = timed

            if self.announced is None and self.aid[event_type] and 0 < timed < self.aid_window_s:
                self.announced = (i, timed)
            if delta <= 0:
                if self.moves and self.playback[event_type] and len(self.evalues) > i:
                    jumps[event_type] = _external(self.evalues[i])  # a later jump of the type wins
                self.replayed.add(i)
                self.fired.append(i)
                continue
            if not self.moves:
                continue
            end_reached[event_type] = True
            if self.playback[event_type] and self.ramp[event_type]:
                ramp = self._ramp(i, bge, event_type, last_fg, value_decreasing, now, live)
                if ramp is not None:
                    ramps[event_type] = ramp
        return jumps, ramps

    def _ramp(self, i: int, bge: int, event_type: int, last_fg: int | None, value_decreasing: bool,
              now: float, live: Foreground) -> float | None:
        """Between the last event of the type (live or background, the later) and this one."""
        last_bg_idx = last_bg_time = last_fg_time = tp_time = None
        try:
            previous = self.etypes[:i]
            last_bg_idx = len(previous) - 1 - previous[::-1].index(event_type)
            last_bg_time = self.times[self.events[last_bg_idx]]
        except ValueError:
            pass
        if last_fg is not None:
            last_fg_time = live.timex[live.events[last_fg]]
        if live.tp_index is not None:
            tp_time = live.timex[live.tp_index]

        last_event_idx, last_event_time = last_bg_idx, last_bg_time
        last_event_value: int | None = None
        last_temp1 = last_temp2 = None
        if (last_fg is not None and last_bg_time is not None and last_fg_time is not None
                and last_fg_time > last_bg_time):
            last_event_idx, last_event_time = last_fg, last_fg_time
            last_event_value = _external(live.evalues[last_fg])
            if tp_time is not None and tp_time < last_event_time and len(live.events) > last_event_idx:
                last_temp1 = live.temp1[live.events[last_event_idx]]
                last_temp2 = live.temp2[live.events[last_event_idx]]
        elif last_bg_idx is not None and last_event_time is not None and last_event_idx is not None:
            last_event_value = _external(self.evalues[last_bg_idx])
            if tp_time is not None and tp_time < last_event_time and len(self.events) > last_event_idx:
                last_temp1 = self.temp1[self.events[last_event_idx]]
                last_temp2 = self.temp2[self.events[last_event_idx]]
        if last_event_idx is None:
            return None

        next_value = _external(self.evalues[i])
        last_temp = next_temp = current = None
        rt = self.replay_type
        t1, t2 = live.temp1, live.temp2
        if (last_temp2 is not None and (rt == BY_BT or (rt == BY_TIME_BT and value_decreasing)) and len(t2) > 1
                and t2[-1] != -1 and t2[-2] != -1 and t2[-1] >= t2[-2] and len(self.temp2) > bge):
            last_temp, next_temp, current = last_temp2, self.temp2[bge], t2[-1]
        elif (last_temp1 is not None and (rt == BY_ET or (rt == BY_TIME_ET and value_decreasing)) and len(t1) > 1
                and t1[-1] != -1 and t1[-2] != -1 and t1[-1] >= t1[-2] and len(self.temp1) > bge):
            last_temp, next_temp, current = last_temp1, self.temp1[bge], t1[-1]

        if ((rt in {BY_BT, BY_ET} or (rt in {BY_TIME_BT, BY_TIME_ET} and value_decreasing))
                and last_temp is not None and next_temp is not None and current is not None):
            if min(last_temp, next_temp) <= current <= max(last_temp, next_temp) and last_event_value is not None:
                return _line(last_temp, next_temp, last_event_value, next_value, current)
            return None
        # Artisan's condition, operator precedence included (the ET clause of type 2 stands alone)
        if (last_temp is None and next_temp is None and
                (rt == BY_TIME or (last_temp1 is None and last_temp2 is None)
                 or (last_temp2 is not None and (rt == BY_BT or (rt == BY_TIME_BT and not value_decreasing)))
                 or (last_temp1 is not None and (rt == BY_ET) or (rt == BY_TIME_ET and not value_decreasing)))
                and last_event_time is not None and len(self.times) > bge):
            next_time = self.times[bge]
            if not (last_event_time <= now <= next_time and last_event_value is not None):
                return None
            after_next = None
            if now + self.lookahead_s >= next_time:
                try:
                    later = self.etypes[i + 1:]
                    after_next = i + 1 + later.index(event_type)
                except ValueError:
                    pass
            if after_next is None:
                return _line(last_event_time, next_time, last_event_value, next_value, now + self.lookahead_s)
            try:
                after_next_bge = self.events[after_next]
                if self.timeindex[6] == 0 or after_next_bge < self.timeindex[6]:
                    return _line(next_time, self.times[after_next_bge], next_value,
                                 _external(self.evalues[after_next]), now + self.lookahead_s)
            except IndexError:
                pass
        return None

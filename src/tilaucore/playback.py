# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Roast Replay: a recorded roast's lever moves played back (android/AUTOMATION-SPEC.md D2, LICENSING-SPEC.md L8).

Engaged at CHARGE, the levers are set as the recorded roast had them at its CHARGE, then its moves
up to its DROP are played again, each as a jump to the recorded value, as the hand made it: no ramp
between two moves. A move is played at
the same time after CHARGE as in the recorded roast while the live turning point is not known; past
it, when the live BT reaches the BT the move was made at (moves of one lever in their recorded
order). A recorded roast without BT is played by time throughout. Nothing is played after the live
DROP. Times are the roast clock's seconds, temperatures the roast's unit; the sliders, the playback
aid, its beep and the Fuji PID strings stay with the apps.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from tilaucore.units import slider_from_event

BY_TIME, BY_BT = 0, 1
LEVERS = 4  # the four sliders


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
    evalues: Sequence[float] = field(default_factory=list)  # as recorded
    dropped: bool = False  # the live DROP is marked: nothing more is played


class Playback:
    """The recorded roast and which of its moves were played already."""

    def __init__(self, times: Sequence[float], temp1: Sequence[float], temp2: Sequence[float],  # noqa: ARG002
                 stemp1: Sequence[float], stemp2: Sequence[float], events: Sequence[int],  # noqa: ARG002
                 etypes: Sequence[int], evalues: Sequence[float], timeindex: Sequence[int],
                 replay_type: int = BY_BT, playback: Sequence[bool] = (True,) * LEVERS,
                 ramp: Sequence[bool] = (True,) * LEVERS, lookahead_s: float = 0, moves: bool = True,  # noqa: ARG002
                 aid: Sequence[bool] = (False,) * LEVERS, aid_window_s: float = 0) -> None:
        # read in place, never copied: the desktop builds one at every sample. `temp1`, `temp2`,
        # `stemp1`, `ramp` and `lookahead_s` are what the desktop passes; no move is played on ET nor ramped.
        self.times = times
        self.stemp2 = stemp2
        self.events, self.etypes, self.evalues = events, etypes, evalues
        self.timeindex = timeindex
        self.by_bt = replay_type != BY_TIME and any(_reads(v) for v in stemp2)
        self.playback = list(playback)
        self.moves = moves  # off: the moves still pass (the playback aid), no slider moves
        self.aid, self.aid_window_s = list(aid), aid_window_s
        self.replayed: set[int] = set()
        self.fired: list[int] = []  # the recorded moves the last step passed, in order
        self.announced: tuple[int, float] | None = None  # the move the playback aid tells, s before it

    def align(self, charge_time: float) -> None:
        """At CHARGE: the recorded roast's clock moved onto the live roast's CHARGE."""
        charge = self.timeindex[0]
        if 0 <= charge < len(self.times):
            shift = charge_time - self.times[charge]
            self.times = [t + shift for t in self.times]

    def engage(self, now: float, charge_time: float | None, sample_interval_s: float, auto_charge: bool = False) -> None:  # noqa: ARG002
        """Turned on. Engaged at CHARGE (within two samples): each lever is first set as the recorded
        roast had it at its CHARGE (its last preheat move), then everything from CHARGE on is to play.
        Engaged later: the moves already past are never played."""
        self.replayed = set()
        charge = self.timeindex[0]
        at_charge = charge_time is not None and now - charge_time <= 2 * sample_interval_s
        setup: dict[int, int] = {}  # each lever's last move before the recorded CHARGE
        for i, at in enumerate(self.events):
            if at >= len(self.times):
                self.replayed.add(i)
            elif charge >= 0 and at < charge:
                self.replayed.add(i)
                if i < len(self.etypes):
                    setup[self.etypes[i]] = i
            elif not at_charge and self.times[at] < now:
                self.replayed.add(i)
        if at_charge:
            self.replayed -= set(setup.values())  # due at once: played at the first step

    def step(self, now: float, live: Foreground) -> tuple[dict[int, int], list[float | None]]:
        """At a sample after CHARGE: the slider jumps (lever: value, each recorded as an event); the
        second list (ramps) stays empty."""
        jumps: dict[int, int] = {}
        self.fired, self.announced = [], None
        if live.dropped:
            return jumps, [None] * LEVERS
        drop = self.timeindex[6]
        live_bt = live.ctemp2[-1] if live.ctemp2 else None
        by_bt = self.by_bt and live.tp_index is not None and _reads(live_bt)
        waiting = [False] * LEVERS  # a lever's next move not reached yet holds its later ones
        for i, at in enumerate(self.events):
            lever = self.etypes[i] if i < len(self.etypes) else -1
            if not 0 <= lever < LEVERS or not self.playback[lever] or i in self.replayed or waiting[lever]:
                continue  # a lever not replayed is not followed at all
            if at >= len(self.times) or (drop > 0 and at > drop):
                continue
            until = self.times[at] - now
            if self.announced is None and self.aid[lever] and 0 < until < self.aid_window_s:
                self.announced = (i, until)
            if by_bt and at < len(self.stemp2) and _reads(self.stemp2[at]):
                reached = live_bt >= self.stemp2[at]  # type: ignore[operator]
            else:
                reached = until <= 0
            if not reached:
                waiting[lever] = True
                continue
            if self.moves and i < len(self.evalues):
                jumps[lever] = slider_from_event(self.evalues[i])  # a later move of the lever wins
            self.replayed.add(i)
            self.fired.append(i)
        return jumps, [None] * LEVERS

    def held(self) -> dict[int, int]:
        """Each lever's value as the replay holds it: its latest move played (to send again after a pause)."""
        latest: dict[int, int] = {}
        for i in sorted(k for k in self.replayed if k < len(self.events) and k < len(self.etypes) and k < len(self.evalues)):
            lever = self.etypes[i]
            if 0 <= lever < LEVERS and self.playback[lever] and self.events[i] < len(self.times):
                latest[lever] = i  # the recorded order: the last one stands, the CHARGE setup included
        return {lever: slider_from_event(self.evalues[i]) for lever, i in latest.items()}


def _reads(value: float | None) -> bool:
    return value is not None and value != -1 and not math.isnan(value)

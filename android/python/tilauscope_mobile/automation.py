# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The milestones that mark themselves during one roast (android/AUTOMATION-SPEC.md D1).

Following a plan, armed per milestone in Roast Setup, and the first hand of the operator (a
lever touched, a milestone undone) drops them all for the rest of the roast (decision 8). By
hand, Dry end and First crack come from Settings › General, and only an undo drops them. The detection is
the desktop's (tilaucore.milestones); placing the mark stays with the session.
"""

from tilaucore.milestones import (MILESTONE_HALF_C, DryEnd, FirstCrack, charge_index, drop_index, drop_looked_for,
                                  resolve_fc_window)

from .alarms import timeindex


class AutoMarks:
    def __init__(self, armed, dry_end_c: float | None, first_crack_c: float | None,
                 original: dict[str, float] | None = None,
                 drop: tuple[float | None, float | None] = (None, None)) -> None:
        self.armed = set(armed)
        self.drop = drop # the roaster's auto DROP values (fall °C, probe lag s); None: the shared default
        self.dropped = False
        self.first_crack_c = first_crack_c or 0.0 # 0: the trade band, as the desktop without a target
        self._first_crack_top = (self.first_crack_c + MILESTONE_HALF_C if first_crack_c
                                 else resolve_fc_window(0.0)[1]) # no cracks to hear: the bean has left the window
        self.original = original or {} # a simulation: the replayed roast's own milestones, in replay seconds
        self._dry_end = DryEnd()
        self._dry_end.set_context(dry_end_c or 0.0)
        self._first_crack = FirstCrack()

    @property
    def active(self) -> bool:
        return bool(self.armed) and not self.dropped

    def _reached(self, milestone: str, now: float) -> bool | None:
        """Whether a simulation is at the replayed roast's milestone; None if it has none to take."""
        at = self.original.get(milestone)
        return None if at is None else now >= at

    def step(self, session, cracks: int | None, tp: int | None) -> tuple[str, int] | None:
        """At each new sample: the milestone found and the sample it goes on, else None. `tp`: the roast's
        TP anchor (TurningPoint.index, kept by the caller), placed 2 min after CHARGE without one."""
        if not self.active or not session.samples:
            return None
        marks, samples = session.milestones, session.samples
        bt = [s.bt_c for s in samples]
        if "charge" not in marks:
            index = charge_index(bt) if "charge" in self.armed else None
            return None if index is None else ("charge", index)
        if "drop" in marks:
            return None
        times = [s.elapsed_s for s in samples]
        charge = marks["charge"]
        elapsed = times[-1] - times[charge]
        if "drop" in self.armed:
            reached = self._reached("drop", times[-1])
            if reached is None: # live: BT's fall once the beans have left, looked for as the desktop does (First Crack, 7 min, 160 °C)
                index = (drop_index(bt, fall_c=self.drop[0], probe_lag_s=self.drop[1])
                         if drop_looked_for(timeindex(marks), elapsed, bt[-1]) else None)
            else: # a replay: the recorded DROP
                index = len(samples) - 1 if reached else None
            if index is not None:
                return "drop", max(index, max(marks.values()))
        if "dry_end" not in marks and "first_crack" not in marks:
            if tp is not None:
                self._dry_end.set_tp(bt[tp])
            if "dry_end" in self.armed and (self._dry_end.check(bt[-1], elapsed, session.ror_series[-1]).fired
                                            or self._reached("dry_end", times[-1])):
                return "dry_end", len(samples) - 1
        elif "first_crack" not in marks and "first_crack" in self.armed:
            at = None if cracks is None else self._first_crack.check(bt[-1], self.first_crack_c, elapsed, cracks)
            reached = self._reached("first_crack", times[-1])
            if at is None and (reached if reached is not None else cracks is None and bt[-1] >= self._first_crack_top):
                at = elapsed
            if at is not None: # back to the first crack heard, never before Dry end
                index = next(i for i in range(charge, len(samples)) if times[i] - times[charge] >= at)
                return "first_crack", max(index, marks["dry_end"])
        return None

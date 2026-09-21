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

"""Several roasts on one frame, in the engine's vocabulary.

BeanCave compares roasts. It used to do it with a second charting library and a
second set of greys, so the screen that answers "is this roast like the last
one?" did not look like the screen the roast was watched on. The engine already
knows how to draw a roast it is not recording — that is what a loaded reference
is — so comparing is not a new kind of drawing: it is the same drawing, several
times, with one roast holding the frame.

This module is only the adapter. It turns a saved profile into the arrays the
engine paints, anchored on its own charge, and hands each roast the hue it will
be known by. Nothing here draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Final

from tilauscope.tilauscope_types import (THEME, is_reading, normalize_timeindex,
                                         profile_crack_times)

#: The hues a comparison is read by, in order. The roast holding the frame is
#: NOT given one: it keeps the bean colour every other screen draws it in, so
#: the reference reads as "the roast" and the others as what it is measured
#: against. Same order BeanCave has always used, so a comparison the operator
#: knows keeps its colours.
#: Blue and peach are absent on purpose: they are the bean and the air of the
#: roast holding the frame, and a compared roast wearing either would be read
#: as one of its probes.
COMPARISON_HUES: Final[tuple[str, ...]] = (
    THEME['MAUVE'], THEME['TEAL'], THEME['SUCCESS'], THEME['PINK'], THEME['YELLOW'],
)


@dataclass(frozen=True)
class ComparedRoast:
    """One roast, ready to paint: charge-relative, in the operator's unit."""

    title: str
    #: The trace colour. None for the roast holding the frame, which keeps the
    #: bean colour of the live chart.
    colour: str | None
    mode: str
    #: Seconds from CHARGE — negative before it, like the live chart's own axis.
    timex: list[float]
    temp1: list[Any]
    temp2: list[Any]
    delta2: list[Any]
    delta1: list[Any]
    timeindex: list[int] = field(default_factory=list)
    #: The gestures played on the machine: sample indices, channels, and values
    #: ALREADY in the operator's own scale. Only read when one roast is shown —
    #: several roasts' levers in one strip read as nobody's.
    events: list[Any] = field(default_factory=list)
    ev_types: list[Any] = field(default_factory=list)
    ev_pcts: list[Any] = field(default_factory=list)
    #: When each pop was counted, charge-relative — the roast's own, never the
    #: application's: the live channels belong to a different roast entirely.
    cracks: list[float] = field(default_factory=list)

    @property
    def total(self) -> float | None:
        """Seconds from charge to drop, or None for a roast never dropped."""
        if len(self.timeindex) < 7:
            return None
        drop = self.timeindex[6]
        return float(self.timex[drop]) if 0 < drop < len(self.timex) else None

    @property
    def shares(self) -> tuple[float, float, float] | None:
        """Drying / Maillard / development, as percentages of the roast.

        The three figures a comparison is actually made on. None when the roast
        is missing a milestone the split is measured from, because two thirds of
        a split invites reading the missing third as zero.
        """
        total = self.total
        if total is None or total <= 0 or len(self.timeindex) < 7:
            return None
        dry, crack = self.timeindex[1], self.timeindex[2]
        if not (0 < dry < len(self.timex) and 0 < crack < len(self.timex)):
            return None
        t_dry, t_crack = float(self.timex[dry]), float(self.timex[crack])
        return (100.0 * t_dry / total,
                100.0 * (t_crack - t_dry) / total,
                100.0 * (total - t_crack) / total)

    @property
    def traces(self) -> tuple[list[float], list[Any], list[Any], list[Any], list[Any], str]:
        """The six positional arrays the engine's reference painter takes."""
        return self.timex, self.temp1, self.temp2, self.delta2, self.delta1, self.mode


def from_profile(data: dict, *, colour: str | None, title: str,
                 deltabt: list[Any] | None = None,
                 deltaet: list[Any] | None = None,
                 ev_pcts: list[Any] | None = None) -> ComparedRoast | None:
    """A saved profile as a compared roast, or None when it has nothing to draw.

    The rate is taken as BeanCave computed it on load and never recomputed:
    no profile carries its own rate, and a second opinion about what the rate
    was would put two answers on one screen.
    """
    try:
        timex = [float(t) for t in (data.get('timex') or [])]
        # A roaster driven on the air probe alone records no bean channel: the
        # roast is drawn as it is, its bean read as Artisan's own "no reading".
        temp2 = list(data.get('temp2') or []) or [-1] * len(timex)
    except (TypeError, ValueError):
        return None
    if len(timex) < 2:
        return None
    timeindex = normalize_timeindex(data.get('timeindex') or [])
    charge = timeindex[0] if timeindex else -1
    # Anchored on its own charge, so two roasts are compared at the same instant
    # of their own story rather than at the same instant of the recording.
    origin = timex[charge] if 0 <= charge < len(timex) else timex[0]
    return ComparedRoast(
        title=title,
        colour=colour,
        mode=str(data.get('mode', 'C') or 'C'),
        timex=[t - origin for t in timex],
        temp1=list(data.get('temp1') or []),
        temp2=temp2,
        delta2=list(deltabt or []),
        delta1=list(deltaet or []),
        timeindex=timeindex,
        events=list(data.get('specialevents') or []),
        ev_types=list(data.get('specialeventstype') or []),
        # Artisan stores a lever's value in its own internal scale; the caller
        # converts, because only it holds the application that knows the rule.
        ev_pcts=list(ev_pcts or []),
        cracks=[t - origin for t in profile_crack_times(data)],
    )


def _bean_readings(roast: ComparedRoast) -> list[tuple[float, float]]:
    """(time, bean) up to the roast's OWN drop: after it the bean is in the cooling tray."""
    end = roast.total
    return [(float(t), float(v)) for t, v in zip(roast.timex, roast.temp2, strict=False)
            if is_reading(v) and (end is None or t <= end)]


def residual(roast: ComparedRoast, reference: ComparedRoast) -> list[float | None]:
    """`roast` minus `reference`, on the reference's own time grid.

    Read straight off the two curves the gap is a shape, not a number, and a
    shape a few degrees wide is invisible against a 200° scale. On its own
    strip it is the one thing the comparison is about: where the roasts parted,
    by how much, and whether they came back together.
    """
    # Two units cannot be subtracted from one another: a profile saved in °F
    # beside one saved in °C is not a comparison to be guessed at.
    if roast.mode != reference.mode:
        return []
    theirs = _bean_readings(roast)
    if len(theirs) < 2:
        return []
    # Charge to drop, and nothing else. Before the charge one roast is a cold
    # drum and the other is mid-preheat; after the drop one is in the cooling
    # tray. Those gaps are real and they are not the comparison — left in, they
    # set a scale on which the whole roast reads as a flat line.
    end = reference.total
    out: list[float | None] = []
    cursor = 0
    for t, mine in zip(reference.timex, reference.temp2, strict=False):
        if t < 0.0 or (end is not None and t > end):
            out.append(None)
            continue
        if not is_reading(mine) or t < theirs[0][0] or t > theirs[-1][0]:
            out.append(None)
            continue
        while cursor + 1 < len(theirs) and theirs[cursor + 1][0] < t:
            cursor += 1
        t0, v0 = theirs[cursor]
        t1, v1 = theirs[min(cursor + 1, len(theirs) - 1)]
        span = t1 - t0
        value = v0 if span <= 0 else v0 + (v1 - v0) * (t - t0) / span
        out.append(float(value) - float(mine))
    return out


#: The three ways a comparison is read. `overlay` puts the roasts on one clock,
#: `consistency` asks how far apart a batch of them ran, `align` puts them on
#: one another's milestones to compare shape rather than schedule.
MODES: Final[tuple[str, str, str]] = ('overlay', 'consistency', 'align')


def aligned(roast: ComparedRoast, reference: ComparedRoast) -> ComparedRoast:
    """`roast` on the reference's milestones — shape without schedule.

    Two roasts that dried a minute apart run side by side for the rest of the
    chart on a raw clock, and every later difference is read through that one
    minute. Stretching each stretch of the roast onto the reference's own
    milestones takes the schedule out and leaves the shape, which is the only
    thing the comparison is then about.
    """
    pairs = [(float(roast.timex[i]), float(reference.timex[j]))
             for i, j in _shared_marks(roast, reference)]
    if len(pairs) < 2:
        return roast
    return ComparedRoast(
        title=roast.title, colour=roast.colour, mode=roast.mode,
        timex=[_piecewise(t, pairs) for t in roast.timex],
        temp1=roast.temp1, temp2=roast.temp2,
        delta2=roast.delta2, delta1=roast.delta1, timeindex=roast.timeindex)


def _shared_marks(roast: ComparedRoast, reference: ComparedRoast) -> list[tuple[int, int]]:
    """Sample indices of the milestones BOTH roasts carry, in roast order."""
    out: list[tuple[int, int]] = []
    for milestone in range(7):
        if milestone >= len(roast.timeindex) or milestone >= len(reference.timeindex):
            break
        mine, theirs = roast.timeindex[milestone], reference.timeindex[milestone]
        ok_mine = mine >= 0 if milestone == 0 else mine > 0
        ok_theirs = theirs >= 0 if milestone == 0 else theirs > 0
        if (ok_mine and ok_theirs and mine < len(roast.timex)
                and theirs < len(reference.timex)):
            out.append((mine, theirs))
    return out


def _piecewise(t: float, pairs: list[tuple[float, float]]) -> float:
    """`t` mapped through the anchor pairs, extended linearly at both ends."""
    if t <= pairs[0][0]:
        return pairs[0][1] + (t - pairs[0][0])
    if t >= pairs[-1][0]:
        return pairs[-1][1] + (t - pairs[-1][0])
    for (t0, m0), (t1, m1) in zip(pairs, pairs[1:], strict=False):
        if t0 <= t <= t1:
            span = t1 - t0
            return m0 if span <= 0 else m0 + (m1 - m0) * (t - t0) / span
    return t


def envelope(roasts: Sequence[ComparedRoast]) -> list[tuple[float, float, float]]:
    """(time, coldest, hottest) across every roast, on the reference's grid.

    What a batch of roasts did, rather than what any one of them did: the band
    is the answer to "how repeatable am I", and a roast leaving it is the one
    worth opening.

    Walked once per roast with a cursor, never searched per sample: a roast is
    well over a thousand readings and this runs when the comparison is built.
    """
    if len(roasts) < 2:
        return []
    reference = roasts[0]
    end = reference.total
    grid = [(i, float(t)) for i, t in enumerate(reference.timex)
            if t >= 0.0 and (end is None or t <= end)]
    if not grid:
        return []
    lo: list[float | None] = []
    hi: list[float | None] = []
    for i, _t in grid:
        value = (float(reference.temp2[i])
                 if i < len(reference.temp2) and is_reading(reference.temp2[i]) else None)
        lo.append(value)
        hi.append(value)

    for other in roasts[1:]:
        if other.mode != reference.mode:
            continue
        samples = _bean_readings(other)
        if len(samples) < 2:
            continue
        cursor = 0
        for slot, (_i, t) in enumerate(grid):
            if t < samples[0][0] or t > samples[-1][0]:
                continue
            while cursor + 1 < len(samples) and samples[cursor + 1][0] < t:
                cursor += 1
            t0, v0 = samples[cursor]
            t1, v1 = samples[min(cursor + 1, len(samples) - 1)]
            span = t1 - t0
            value = v0 if span <= 0 else v0 + (v1 - v0) * (t - t0) / span
            lo[slot] = value if lo[slot] is None else min(lo[slot], value)
            hi[slot] = value if hi[slot] is None else max(hi[slot], value)

    return [(t, lo[slot], hi[slot]) for slot, (_i, t) in enumerate(grid)
            if lo[slot] is not None and hi[slot] is not None and hi[slot] > lo[slot]]

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""What the roast card shows (Roasts › Export › Roast card), the same on the desktop and the tablet.

Each app draws it (QPainter on the desktop, a canvas on the tablet) on the layout below; the milestones,
the phases, the settings played, the key moments, the scales and the header figures come from here.
The words are each app's own: a milestone carries its key, the painter names it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real

from tilaucore.roast_colour import roast_agtron
from tilaucore.units import decode_escaped, slider_from_event

DASH = '—'
# Drawn on a 2400 × 1350 layout, saved at 3200 × 1800.
WIDTH, HEIGHT, SCALE = 2400, 1350, 4 / 3
# Settings lanes by Artisan event type (0 air, 1 drum, 2 damper, 3 burner), burner first.
LANE_ORDER = (3, 0, 2, 1)
# Key moments column: first row's baseline, row step, last row's baseline.
ROW_Y0, ROW_STEP, ROW_LAST = 392, 39, 1270
CAPACITY = (ROW_LAST - ROW_Y0) // ROW_STEP + 1
# Changes on one setting closer than this collapse into the last one in the key moments.
SETTLE_S = 10.0


def number(value) -> float | None:
    if isinstance(value, Real) and math.isfinite(value):
        return float(value)
    return None


def mmss(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


@dataclass
class Lane:
    kind: int
    name: str
    color: str
    steps: list[tuple[float, int]]   # (seconds from CHARGE, value), in order


@dataclass
class Moment:
    t: float
    text: str
    color: str = ''   # a gesture's lane colour; a milestone's is the painter's, by its key
    milestone: bool = False
    kind: int = -1    # the setting a gesture moved
    key: str = ''     # a milestone's: charge, tp, dry, fc, drop


def milestones(profile: dict) -> dict[str, int]:
    """Sample index of CHARGE, Dry end, First crack and DROP, those marked and in order."""
    times = profile.get('timex') or []
    indices = profile.get('timeindex') or []
    marks = {}
    for key, slot in (('charge', 0), ('dry', 1), ('fc', 2), ('drop', 6)):
        if slot >= len(indices):
            continue
        index = indices[slot]
        if (isinstance(index, int) and (index >= 0 if slot == 0 else index > 0)
                and index < len(times) and number(times[index]) is not None):
            marks[key] = index
    # Never turn an absent CHARGE or DROP into a made-up milestone.
    if 'charge' in marks:
        for key in ('dry', 'fc', 'drop'):
            if key in marks and times[marks[key]] <= times[marks['charge']]:
                del marks[key]
    if 'drop' in marks:
        for key in ('dry', 'fc'):
            if key in marks and times[marks[key]] >= times[marks['drop']]:
                del marks[key]
    return marks


def has_frame(profile: dict, marks: dict[str, int]) -> bool:
    """A curve to draw: CHARGE and DROP marked, DROP after CHARGE."""
    times = profile.get('timex') or []
    return 'charge' in marks and 'drop' in marks and times[marks['drop']] > times[marks['charge']]


def phase_durations(profile: dict, marks: dict[str, int]) -> list[float | None]:
    times = profile.get('timex') or []
    result = []
    for start, end in (('charge', 'dry'), ('dry', 'fc'), ('fc', 'drop')):
        duration = times[marks[end]] - times[marks[start]] if start in marks and end in marks else 0
        result.append(duration if duration > 0 else None)
    return result


def turning_point(profile: dict, marks: dict[str, int]) -> int | None:
    tp = (profile.get('computed') or {}).get('TP_idx')
    if isinstance(tp, int) and marks['charge'] < tp < marks['drop']:
        return tp
    return None


def lanes(profile: dict, marks: dict[str, int], colours: Mapping[int, str]) -> list[Lane]:
    """Each setting played between CHARGE and DROP, with the value it had at CHARGE; `colours` by event type."""
    times = profile.get('timex') or []
    names = profile.get('etypes') or []
    charge, drop = marks['charge'], marks['drop']
    t0 = times[charge]
    steps: dict[int, list[tuple[float, int]]] = {}
    before: dict[int, int] = {}
    for idx, kind, value in zip(profile.get('specialevents') or [],
                                profile.get('specialeventstype') or [],
                                profile.get('specialeventsvalue') or [], strict=False):
        if kind not in LANE_ORDER or not isinstance(idx, int) or not 0 <= idx < len(times):
            continue
        pct = slider_from_event(number(value))
        if idx <= charge:
            before[kind] = pct
        elif idx <= drop:
            steps.setdefault(kind, []).append((times[idx] - t0, pct))
    result = []
    for kind in LANE_ORDER:
        played = ([(0.0, before[kind])] if kind in before else []) + steps.get(kind, [])
        name = decode_escaped(names[kind]).strip() if kind < len(names) else ''
        if played and name:
            result.append(Lane(kind, name, colours[kind], played))
    return result


def gestures(played: list[Lane]) -> list[Moment]:
    """Settings changes after CHARGE; a setting moved again within a few seconds keeps its last value."""
    moments = []
    for lane in played:
        changes = [s for s in lane.steps if s[0] > 0]
        # a value equal to the one held at CHARGE is no gesture
        previous = lane.steps[0][1] if lane.steps[0][0] == 0 else None
        kept: list[tuple[float, int]] = []
        for i, (t, value) in enumerate(changes):
            if i + 1 < len(changes) and changes[i + 1][0] - t < SETTLE_S:
                continue
            if t <= SETTLE_S:   # set with the charge: the opening value, not a gesture
                previous = value
            elif value != previous:
                kept.append((t, value))
                previous = value
        moments.extend(Moment(t, f'{lane.name} {value} %', lane.color, kind=lane.kind) for t, value in kept)
    return moments


def fit_moments(marked: list[Moment], moved: list[Moment], played: list[Lane], capacity: int) -> list[Moment]:
    """Every gesture when the column holds them; otherwise the least decisive settings go first."""
    room = capacity - len(marked)
    order = [lane.kind for lane in played]
    while len(moved) > room and len(order) > 1:
        dropped = order.pop()
        moved = [g for g in moved if g.kind != dropped]
    if len(moved) > room:
        moved = sorted(moved, key=lambda g: g.t)[:max(0, room)]
    return sorted(marked + moved, key=lambda m: (m.t, not m.milestone))


def key_moments(profile: dict, marks: dict[str, int], played: list[Lane],
                capacity: int = CAPACITY) -> list[Moment]:
    """The column's rows: the milestones (English names, the painter's to translate by key) and the gestures."""
    times = profile.get('timex') or []
    t0 = times[marks['charge']]
    marked = [Moment(0.0, 'Charge', milestone=True, key='charge')]
    tp = turning_point(profile, marks)
    if tp is not None:
        marked.append(Moment(times[tp] - t0, 'TP', milestone=True, key='tp'))
    for key, text in (('dry', 'Dry end'), ('fc', 'First crack'), ('drop', 'Drop')):
        if key in marks:
            marked.append(Moment(times[marks[key]] - t0, text, milestone=True, key=key))
    return fit_moments(marked, gestures(played), played, capacity)


def sample_at(profile: dict, marks: dict[str, int], t: float) -> int:
    """The sample nearest `t` seconds from CHARGE, between CHARGE and DROP."""
    times = profile.get('timex') or []
    t0 = times[marks['charge']]
    return min(range(marks['charge'], marks['drop'] + 1), key=lambda k: abs(times[k] - t0 - t))


def reading(series: Sequence, i: int) -> float | None:
    """A probe's value at sample `i`; None where it did not read (-1, missing, not a number)."""
    v = number(series[i]) if i < len(series) else None
    return v if v is not None and v != -1 else None


@dataclass
class Scales:
    low: int    # temperature axis, in the roast's unit
    high: int
    step: int
    rhigh: int  # rate of rise axis, from 0
    rstep: int


def scales(profile: dict, marks: dict[str, int], ror: Sequence[float | None]) -> Scales:
    """The temperature and rate-of-rise axes of the curve, CHARGE to DROP."""
    bt, et = profile.get('temp2') or [], profile.get('temp1') or []
    span = range(marks['charge'], marks['drop'] + 1)
    temps = [v for s in (bt, et) for i in span if (v := reading(s, i)) is not None]
    low = math.floor((min(temps) - 10) / 20) * 20 if temps else 0
    top = max(temps) if temps else 100
    step = 20 if top - low <= 180 else 40
    high = math.ceil((top + 0.2 * (top - low)) / step) * step
    rvalues = [r for r in ror[marks['charge']:marks['drop'] + 1] if r is not None]
    rstep = 4 if not rvalues or max(rvalues) <= 20 else 8
    rhigh = max(2 * rstep, math.ceil(max(rvalues, default=0) * 1.6 / rstep) * rstep)
    return Scales(low, high, step, rhigh, rstep)


def rise_start(profile: dict, marks: dict[str, int]) -> int:
    """The rate of rise is only meaningful from the turning point on."""
    tp = turning_point(profile, marks)
    return tp if tp is not None else marks['charge']


def peak_rise(profile: dict, marks: dict[str, int], ror: Sequence[float | None]) -> tuple[float, int] | None:
    """(rate, sample) of the highest rate of rise after the turning point."""
    after = [(r, i) for i in range(rise_start(profile, marks), marks['drop'] + 1) if (r := ror[i]) is not None]
    return max(after) if after else None


def colour(profile: dict) -> tuple[int, str]:
    """(Agtron, basis) of the roast, rounded; (0, '') without a reading. As roast_debrief.roast_colour reads it."""
    def positive(key):
        try:
            v = float(profile.get(key))
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0.0 else 0.0
    agtron, basis = roast_agtron(positive('ground_color'), positive('whole_color'),
                                 str(profile.get('color_system') or 'Agtron'))
    return (round(agtron), basis) if basis else (0, '')


def figures(profile: dict, marks: dict[str, int]) -> dict[str, str | list[str]]:
    """The header's values as shown: duration, development, development rise, weights, loss, ambient.
    A value not recorded is a dash; `ambient` lists the readings taken (none: empty)."""
    times = profile.get('timex') or []
    bt = profile.get('temp2') or []
    unit = '°F' if profile.get('mode') == 'F' else '°C'
    duration = times[marks['drop']] - times[marks['charge']] if has_frame(profile, marks) else None
    phases = phase_durations(profile, marks)
    development = DASH
    if phases[2] is not None and duration:
        development = f'{mmss(phases[2])} · {phases[2] / duration * 100:.1f} %'
    rise = DASH
    if 'fc' in marks and 'drop' in marks:
        fc_bt, drop_bt = number(bt[marks['fc']]), number(bt[marks['drop']])
        if fc_bt is not None and drop_bt is not None and fc_bt > 0 and drop_bt > 0:
            rise = f'{drop_bt - fc_bt:+.1f} {unit}'
    weight = profile.get('weight') or []
    incoming = number(weight[0]) if len(weight) >= 3 else None
    outgoing = number(weight[1]) if len(weight) >= 3 else None
    wunit = decode_escaped(weight[2], 'g') if len(weight) >= 3 else 'g'
    loss = DASH
    if incoming and outgoing and incoming > 0 and outgoing > 0:
        loss = f'{(incoming - outgoing) / incoming * 100:.1f} %'
    ambient = []
    for key, fmt in (('ambientTemp', '{:.0f} ' + unit), ('ambient_humidity', '{:.0f} %'),
                     ('ambient_pressure', '{:.0f} hPa')):
        value = number(profile.get(key))
        if value:
            ambient.append(fmt.format(value))
    return {'unit': unit, 'duration': mmss(duration) if duration else DASH, 'development': development,
            'rise': rise, 'green': f'{incoming:g} {wunit}' if incoming else DASH,
            'roasted': f'{outgoing:g} {wunit}' if outgoing else DASH, 'loss': loss, 'ambient': ambient}

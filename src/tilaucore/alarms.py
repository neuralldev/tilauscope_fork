# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.
#
# Portions derived from Artisan Roaster Scope (artisanlib/util.py, artisanlib/canvas.py),
# Copyright (C) 2010-2026 the Artisan team represented by Marko Luther
# and all contributors, distributed under the terms of their original licence.

"""Artisan alarm lists (.alrm), read, written back and fired (android/ALARM-SPEC.md C1).

An `.alrm` is Artisan's alarm table as parallel lists; each row becomes an `Alarm`
with named fields, and `write_alrm` gives the file Artisan's export writes, so a list
goes back to the desktop unchanged. `AlarmRun.step` is the desktop's firing rule
(canvas.py, the alarm loop of `sample()`), applied to one sample: pure, the caller
gives the readings, the marks and the clock. What an action does stays with the app;
here only its argument is read, as Artisan reads it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

# alarmtime codes (canvas.py: menuidx2alarmtime)
START: Final[int] = -1
CHARGE: Final[int] = 0
TP: Final[int] = 8
ON: Final[int] = 9
IF_ALARM: Final[int] = 10
ANCHORS: Final[dict[int, str]] = {
    ON: "on", START: "start", CHARGE: "charge", TP: "tp", 1: "dry_end", 2: "first_crack",
    3: "first_crack_end", 4: "second_crack", 5: "second_crack_end", 6: "drop", 7: "cool_end",
    IF_ALARM: "if_alarm"}
# alarmsource codes: -3 none, -2 ΔET, -1 ΔBT, 0 ET, 1 BT, 2+ extra device channels
NO_SOURCE: Final[int] = -3
# alarmaction codes the apps run by name (the others are Artisan's own)
POPUP: Final[int] = 0
EVENT_BUTTON: Final[int] = 2
SLIDERS: Final[dict[int, int]] = {3: 0, 4: 1, 5: 2, 6: 3}  # action -> slider position
AIRWAVE: Final[int] = 26
AMBIENT: Final[int] = 27

# The .alrm keys, in the order Artisan's export writes them, with the profile's (.alog) name.
_KEYS: Final[tuple[tuple[str, str, str], ...]] = (
    ("on", "alarmflags", "alarmflag"), ("guard", "alarmguards", "alarmguard"),
    ("negguard", "alarmnegguards", "alarmnegguard"), ("anchor", "alarmtimes", "alarmtime"),
    ("offset", "alarmoffsets", "alarmoffset"), ("cond", "alarmconds", "alarmcond"),
    ("source", "alarmsources", "alarmsource"), ("temperature", "alarmtemperatures", "alarmtemperature"),
    ("action", "alarmactions", "alarmaction"), ("beep", "alarmbeep", "alarmbeep"),
    ("text", "alarmstrings", "alarmstrings"))


@dataclass(frozen=True)
class Alarm:
    """One row of the table, as Artisan stores it (guards are row positions, -1 none)."""
    on: int = 1
    guard: int = -1
    negguard: int = -1
    anchor: int = CHARGE
    offset: int = 0
    cond: int = 1           # 0 below, 1 above, 2 equal, 3 not equal
    source: int = NO_SOURCE
    temperature: float = 0.0
    action: int = POPUP
    beep: int = 0
    text: str = ""


PROFILE_KEYS: Final[tuple[str, ...]] = tuple(keys[2] for keys in _KEYS)  # also Artisan's qmc attributes


def _rows(data: dict, names: int) -> list[Alarm]:
    """Rows from a dict of parallel lists; `names` 1 for the .alrm keys, 2 for the .alog ones."""
    flags = data[_KEYS[0][names]]
    count = len(flags)
    columns = {}
    for field, *keys in _KEYS:
        values = data.get(keys[names - 1])
        if values is None: # as Artisan's import: absent negative guards and beeps read as 0
            values = [0] * count
        columns[field] = values
    return [Alarm(**{field: columns[field][i] for field in columns}) for i in range(count)]


def read_alrm(text: str) -> list[Alarm]:
    """The rows of an .alrm file's text."""
    return _rows(json.loads(text), 1)


def read_profile_alarms(profile: dict) -> list[Alarm]:
    """The alarm table a roast file (.alog, already parsed) was recorded with; empty when none."""
    return _rows(profile, 2) if profile.get("alarmflag") else []


def write_alrm(rows: Sequence[Alarm]) -> str:
    """The .alrm text, as Artisan's export writes it."""
    data = {keys[0]: [getattr(row, field) for row in rows] for field, *keys in _KEYS}
    return json.dumps(data, indent=None, separators=(",", ":"), ensure_ascii=False) + "\n"


def slider_value(text: str) -> int:
    """A slider action's value, as Artisan reads it (before clamping to the slider's range)."""
    try:
        return int(round(float(text.split("#")[0].strip())))
    except ValueError:
        return 0


def event_buttons(text: str) -> list[tuple[int, int | None]]:
    """An event-button action's buttons: (number from 1, value that overrides the button's or None).

    Written `5`, `5>80` or `3,5`, with an optional `# comment`; a spec that is not a number is skipped.
    """
    buttons = []
    for spec in text.split("#")[0].split(","):
        parts = spec.strip().split(">")
        try:
            buttons.append((int(parts[0].strip()), int(parts[1].strip()) if len(parts) > 1 else None))
        except ValueError:
            continue
    return buttons


@dataclass(frozen=True)
class Readings:
    """What the firing rule reads at one sample (Artisan's sample_* lists and marks)."""
    clock_s: float                      # Artisan's timeclock: since ON, then since START
    recording: bool                     # flagstart
    times: Sequence[float]              # sample time of each sample
    et: Sequence[float]
    bt: Sequence[float]
    delta_et: Sequence[float | None]
    delta_bt: Sequence[float | None]
    marks: Sequence[int]                # Artisan's timeindex: [charge (-1 unset), dry_end … cool_end (0 unset)]
    tp: int | None = None               # sample index of the detected TP
    extra: Sequence[tuple[Sequence[float], Sequence[float]]] = ()  # each extra device: its two channels
    recorded: int | None = None         # len(Artisan's timex) when `times` is the ON buffer (before START)


class AlarmRun:
    """The rows of one roast: which have fired, at which sample (-1 not yet)."""

    def __init__(self, rows: Sequence[Alarm]) -> None:
        self.rows = list(rows)
        self.state = [-1] * len(self.rows)

    def step(self, r: Readings) -> list[int]:
        """The rows that fire at this sample, in table order (a row may unlock the next one)."""
        fired = []
        if not r.times:
            return fired
        state = self.state
        for i, a in enumerate(self.rows):
            if not a.on or state[i] != -1:
                continue
            if not (a.guard < 0 or (0 <= a.guard < len(state) and state[a.guard] != -1)):
                continue
            if not (a.negguard < 0 or (0 <= a.negguard < len(state) and state[a.negguard] == -1)):
                continue
            if not self._anchored(a, r):
                continue
            ready = False
            if a.offset > 0:
                ready = self._elapsed(a, r) >= a.offset
            reading, base = self._reading(a, r)
            if reading is not None and reading != -1:
                limit = a.temperature
                ready |= ((a.cond == 0 and reading < limit) or (a.cond == 1 and reading > limit)
                          or (a.cond == 2 and reading == limit) or (a.cond == 3 and reading != limit))
                if base is not None and reading == limit: # relative to the guard: equality fires too
                    ready = True
            if ready:
                state[i] = max(0, (len(r.times) if r.recorded is None else r.recorded) - 1)
                fired.append(i)
        return fired

    @staticmethod
    def _anchored(a: Alarm, r: Readings) -> bool:
        t, m = a.anchor, r.marks
        return (t == ON or (t < 0 and r.recording)
                or (r.recording and t == CHARGE and m[0] > -1)
                or (r.recording and 0 < t < TP and m[t] > 0)
                or (t == IF_ALARM and a.guard != -1)
                or (r.recording and t == TP and m[0] > -1 and bool(r.tp)))

    def _elapsed(self, a: Alarm, r: Readings) -> float:
        t, m, elapsed = a.anchor, r.marks, r.clock_s
        if t < 0:
            pass
        elif r.recording and t == CHARGE and m[0] > -1:
            elapsed -= r.times[m[0]]
        elif r.recording and t == TP and r.tp:
            elapsed -= r.times[r.tp]
        elif r.recording and t < TP and m[t] > 0:
            elapsed -= r.times[m[t]]
        elif r.recording and t == IF_ALARM:
            elapsed -= r.times[self.state[a.guard]]
        return elapsed

    def _reading(self, a: Alarm, r: Readings) -> tuple[float | None, int | None]:
        """The source's reading now, minus its reading at the guard's firing for an If Alarm."""
        base = None
        if a.anchor == IF_ALARM:
            fired_at = self.state[a.guard]
            if fired_at != -1:
                base = fired_at if fired_at < len(r.times) else -1
        s = a.source
        if s in (-2, -1):
            series = r.delta_et if s == -2 else r.delta_bt
            value = series[-1]
            if value is None:
                return None, base
            if base is not None and series[base] is not None:
                value -= series[base]
            return value, base
        if s in (0, 1):
            series = r.et if s == 0 else r.bt
            return (series[-1] - series[base] if base is not None else series[-1]), base
        if s > 1 and (s - 2) // 2 < len(r.extra):
            first, second = r.extra[(s - 2) // 2]
            # As Artisan: an even source with an empty first channel reads the second one
            series = first if s % 2 == 0 and first else second
            if not series:
                return None, base
            value = series[-1]
            if base is not None and base < len(series):
                value -= series[base]
            return value, base
        return None, base



TP_MAX_S: Final[float] = 120.0  # Artisan's TP_max_roasttime: past it, TP is placed at the current sample


class TurningPoint:
    """The TP the alarms anchor on, found live as Artisan finds it (canvas.sample, °C).

    Two minutes after CHARGE without one, TP is the current sample. Before that, once
    BT has turned up (20 s after CHARGE, the last five readings rising), TP is the
    lowest BT between CHARGE and now (Artisan's findTPint), kept if between 50 and 150 °C.
    """

    def __init__(self) -> None:
        self.index: int | None = None
        self._turned = False

    def update(self, times: Sequence[float], bt: Sequence[float], marks: Sequence[int]) -> int | None:
        charge = marks[0]
        if self.index is not None or charge < 0 or not times:
            return self.index
        if times[-1] - times[charge] > TP_MAX_S:
            self.index = len(times) - 1
        elif not marks[1] and charge + 8 < len(bt) and self._has_turned(times, bt, charge):
            tp = self._lowest(bt, marks)
            if 50 < bt[tp] < 150:
                self.index = tp
        return self.index

    def _has_turned(self, times: Sequence[float], bt: Sequence[float], charge: int) -> bool:
        if (not self._turned and int(times[-1] - times[charge]) > 20 and len(bt) > 3
                and bt[-5] <= bt[-4] and bt[-5] <= bt[-3] and bt[-5] <= bt[-2] and bt[-5] <= bt[-1] and bt[-5] < bt[-1]):
            self._turned = True
        return self._turned

    @staticmethod
    def _lowest(bt: Sequence[float], marks: Sequence[int]) -> int:
        start, end = 0, len(bt)
        for limit in (marks[6], marks[2]): # not beyond DROP, nor beyond FC
            if limit and start < limit < end:
                end = limit
        if start < marks[0] < end:
            start = marks[0]
        lowest, index = 1000.0, 0
        for i in range(end - 1, start - 1, -1):
            if 0 < bt[i] < lowest:
                lowest, index = bt[i], i
        return index


# ── Editing a list (the desktop editor's rules, android/ALARM-SPEC.md C3) ────
# Rows refer to each other by position in the file; the desktop edits them by identity,
# so a reference follows its alarm when rows move, and is dropped when its alarm goes.

NEW_ALARM: Final[Alarm] = Alarm(anchor=CHARGE, offset=0, action=-1)  # the desktop's new row: nothing to do yet


def _remap(rows: list[Alarm], new_index: dict[int, int]) -> list[Alarm]:
    """`rows` with each guard pointed at its alarm's new position (-1 when that alarm is gone)."""
    def ref(i: int) -> int:
        return i if i < 0 else new_index.get(i, -1)
    return [replace(r, guard=ref(r.guard), negguard=ref(r.negguard)) for r in rows]


def remove_row(rows: Sequence[Alarm], index: int) -> list[Alarm]:
    """The list without row `index`; alarms that waited on it no longer do."""
    kept = [i for i in range(len(rows)) if i != index]
    return _remap([rows[i] for i in kept], {old: new for new, old in enumerate(kept)})


def move_row(rows: Sequence[Alarm], source: int, target: int) -> list[Alarm]:
    """The list with row `source` moved to position `target`; references follow their alarms."""
    order = list(range(len(rows)))
    order.insert(target, order.pop(source))
    return _remap([rows[i] for i in order], {old: new for new, old in enumerate(order)})


def append_row(rows: Sequence[Alarm], row: Alarm = NEW_ALARM) -> list[Alarm]:
    return [*rows, row]

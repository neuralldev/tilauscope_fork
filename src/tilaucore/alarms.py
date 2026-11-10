# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Alarm lists (.alrm), read, written back and fired (android/ALARM-SPEC.md C1, LICENSING-SPEC.md L7).

An `.alrm` holds the alarm table as parallel lists (the file format the desktop shares);
each row becomes an `Alarm` with named fields, and `write_alrm` writes the file back,
so a list goes back to the desktop unchanged. `AlarmRun.step` is the firing rule of
both apps, applied to one sample: pure, the caller gives the readings, the marks and
the clock. What an action does stays with the app; here only its argument is read.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from tilaucore.milestones import turning_point

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
    """A slider action's value: the number before an optional `# comment`, rounded; 0 when none
    (the slider's own range clamps it)."""
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
    """What the rows read at one sample."""
    clock_s: float                      # the roast clock: since ON, then since START
    recording: bool                     # START pressed
    times: Sequence[float]              # each sample's time, on the roast clock
    et: Sequence[float]
    bt: Sequence[float]
    delta_et: Sequence[float | None]
    delta_bt: Sequence[float | None]
    marks: Sequence[int]                # the milestones' samples: [charge (-1 unset), dry_end … cool_end (0 unset)]
    tp: int | None = None               # the turning point's sample
    extra: Sequence[tuple[Sequence[float], Sequence[float]]] = ()  # each extra device: its two channels
    recorded: int | None = None         # samples recorded since START, when `times` is the ON buffer (before START)


class AlarmRun:
    """The rows of one roast: which have fired, at which sample (-1 not yet) (android/LICENSING-SPEC.md L7).

    A row fires once, at the first sample where all its conditions hold, checked again at each sample:
    switched on; its guard row fired (if any), its negative guard row not fired (if any); its anchor
    reached; its delay elapsed since the anchor's place (a milestone marked late counts from where it is
    placed, so a delay already past fires at once); and, when it reads a source, the reading on the
    right side of its limit (already past it when the anchor comes: it fires at once). A source with no
    reading (a lost probe, -1) holds the row until it reads again. An If Alarm row counts its delay from
    its guard's firing and reads its source as the change since then.
    """

    def __init__(self, rows: Sequence[Alarm]) -> None:
        self.rows = list(rows)
        self.state = [-1] * len(self.rows)

    def step(self, r: Readings) -> list[int]:
        """The rows that fire at this sample, in table order (a row may unlock the next one)."""
        fired: list[int] = []
        if not r.times:
            return fired
        now = max(0, (len(r.times) if r.recorded is None else r.recorded) - 1)
        for i, a in enumerate(self.rows):
            if a.on and self.state[i] == -1 and self._guards_allow(a) and self._ready(a, r):
                self.state[i] = now
                fired.append(i)
        return fired

    def _fired(self, row: int) -> bool:
        return 0 <= row < len(self.state) and self.state[row] != -1

    def _guards_allow(self, a: Alarm) -> bool:
        return ((a.guard < 0 or self._fired(a.guard))
                and (a.negguard < 0 or (a.negguard < len(self.state) and not self._fired(a.negguard))))

    def _ready(self, a: Alarm, r: Readings) -> bool:
        since = self._anchor_time(a, r)
        if since is None or r.clock_s - since < a.offset:
            return False
        if a.source == NO_SOURCE:
            return True
        reading = self._reading(a, r)
        if reading is None:
            return False
        limit = a.temperature
        return ((a.cond == 0 and reading < limit) or (a.cond == 1 and reading > limit)
                or (a.cond == 2 and reading == limit) or (a.cond == 3 and reading != limit))

    def _anchor_time(self, a: Alarm, r: Readings) -> float | None:
        """When the row's anchor was reached, on the roast clock; None when not yet."""
        t, m = a.anchor, r.marks
        if t == ON:
            return 0.0
        if t == IF_ALARM:
            if not self._fired(a.guard):
                return None
            if not r.recording: # before START the samples are a short rolling buffer: counted since ON
                return 0.0
            return r.times[self.state[a.guard]] if self.state[a.guard] < len(r.times) else None
        if not r.recording:
            return None
        if t < 0: # START
            return 0.0
        if t == CHARGE:
            return r.times[m[0]] if m[0] > -1 else None
        if t == TP:
            return r.times[r.tp] if m[0] > -1 and r.tp else None
        return r.times[m[t]] if 0 < t < len(m) and m[t] > 0 else None

    def _reading(self, a: Alarm, r: Readings) -> float | None:
        """The source's reading now (for an If Alarm: its change since the guard fired); None: no reading."""
        series = self._series(a.source, r)
        reads = _is_rate if a.source < 0 else _reads # a rate of -1 °C/min is a reading
        if not series or not reads(series[-1]):
            return None
        if a.anchor != IF_ALARM:
            return series[-1]
        base = self.state[a.guard]
        if base >= len(series) or not reads(series[base]):
            return None
        return series[-1] - series[base]

    @staticmethod
    def _series(source: int, r: Readings) -> Sequence[float | None]:
        if source == -2:
            return r.delta_et
        if source == -1:
            return r.delta_bt
        if source in (0, 1):
            return r.et if source == 0 else r.bt
        device = (source - 2) // 2
        if source > 1 and device < len(r.extra):
            return r.extra[device][source % 2]
        return ()


def _reads(value: float | None) -> bool:
    return value is not None and value != -1


def _is_rate(value: float | None) -> bool:
    return value is not None


class TurningPoint:
    """The TP the alarms anchor on, found live (tilaucore.milestones.turning_point, °C).

    Searched before the next milestone marked after CHARGE; once BT has turned it is kept.
    """

    def __init__(self) -> None:
        self.index: int | None = None

    def update(self, times: Sequence[float], bt: Sequence[float], marks: Sequence[int]) -> int | None:
        if self.index is None and marks[0] >= 0 and times:
            end = min((m for m in marks[1:] if m > marks[0]), default=None)
            self.index = turning_point(times, bt, marks[0], end)
        return self.index


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

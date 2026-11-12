# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Follow a roast (android/AUTOMATION-SPEC.md decision 13): a recorded roast's levers played back.

What the Plan tab shows of the roast followed, and the playback the roast runs from CHARGE: the desktop's
Roast Replay (tilaucore.playback), each move a jump as the hand made it, by BT once past the turning point,
up to the live DROP. The live BT is compared raw, the followed one smoothed.
"""

import ast
import bisect
import math
from pathlib import Path

from tilaucore.artisan_compat import events_internal_to_external_value
from tilaucore.ror import RoRSettings, rate_of_rise
from tilaucore.playback import BY_BT, BY_TIME, Foreground, Playback

from .alog import EVENT_TYPE, curves_c, event_value
from .session import Session

LEVER_OF = {kind: lever for lever, kind in EVENT_TYPE.items()} # Artisan's event type -> the tablet's lever
ROWS = (("charge", "CHARGE", 0), ("dry_end", "DRY END", 1), ("fc_start", "FC START", 2), ("drop", "DROP", 6))
WORDS = (("burner", "Burner"), ("air", "Air"), ("drum", "Drum"), ("extractor", "Extractor"))
CURVE_STEP_S = 5


def _clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class FollowedRoast:
    """A recorded roast, read once, as followed."""

    def __init__(self, path: Path, ror: RoRSettings) -> None:
        self.profile = ast.literal_eval(path.read_text(encoding="utf-8"))
        p = self.profile
        self.times = [float(t) for t in p.get("timex") or []]
        self.bt, self.et = curves_c(p)
        self.timeindex = list(p.get("timeindex") or [-1, 0, 0, 0, 0, 0, 0, 0]) + [0] * 8
        self.events = list(p.get("specialevents") or [])
        self.etypes = list(p.get("specialeventstype") or [])
        self.evalues = list(p.get("specialeventsvalue") or [])
        self.title = str(p.get("title") or path.stem)
        self.epoch = p.get("roastepoch") or 0
        self.ror = ror
        # the readings as recorded; a reading the probe missed (-1) is a gap
        self.sbt = [math.nan if v == -1 else v for v in self.bt]
        self.set = [math.nan if v == -1 else v for v in self.et]

    def _at(self, slot: int) -> int | None:
        index = self.timeindex[slot]
        marked = index >= 0 if slot == 0 else index > 0
        return index if marked and index < len(self.times) else None

    def targets(self) -> dict:
        """Its Dry end and First crack BT, as a plan's targets."""
        return {key: self.bt[i] for key, slot in (("dry_end", 1), ("first_crack", 2))
                if (i := self._at(slot)) is not None}

    def _levers_at(self, index: int) -> str:
        held: dict[str, int] = {}
        for at, kind, value in zip(self.events, self.etypes, self.evalues):
            if at <= index and kind in LEVER_OF:
                held[LEVER_OF[kind]] = events_internal_to_external_value(value)
        return " · ".join(f"{word} {held[key]} %" for key, word in WORDS if key in held)

    def view(self) -> dict:
        """The Plan tab's table and curve, as the plan's own."""
        charge = self._at(0)
        start = self.times[charge] if charge is not None else (self.times[0] if self.times else 0.0)
        rows = []
        for key, label, slot in ROWS:
            i = self._at(slot)
            if i is None:
                continue
            rows.append({"key": key, "label": label, "temp": f"{self.bt[i]:.0f}",
                         "time": "" if slot == 0 else "~" + _clock(self.times[i] - start), "levers": self._levers_at(i)})
        drop = self._at(6)
        ror = rate_of_rise(self.times, self.sbt, self.ror, charge or 0, drop)
        curve, last = {"t": [], "bt": [], "ror": []}, None
        for t, b, r in zip(self.times, self.sbt, ror):
            if t < start or (drop is not None and t > self.times[drop]) or (last is not None and t - last < CURVE_STEP_S):
                continue
            last = t
            curve["t"].append(round((t - start) / 60, 3))
            curve["bt"].append(None if math.isnan(b) else round(b, 1))
            curve["ror"].append(None if r is None else round(r, 2))
        marks = {key: round((self.times[i] - start) / 60, 3) for key, _, slot in ROWS[1:] if (i := self._at(slot)) is not None}
        lanes: dict[str, list] = {}
        for at, kind, value in zip(self.events, self.etypes, self.evalues):
            if kind in LEVER_OF and 0 <= at < len(self.times) and (drop is None or at <= drop): # not the cooling's
                lanes.setdefault(LEVER_OF[kind], []).append([round((self.times[at] - start) / 60, 3),
                                                             events_internal_to_external_value(value)])
        moves = sum(1 for kind in self.etypes if kind in LEVER_OF)
        return {"title": self.title, "epoch": self.epoch, "rows": rows, "curve": curve, "marks": marks, "lanes": lanes,
                "moves": moves}

    def playback(self) -> Playback:
        """The desktop's engagement: by BT when the roast has a BT trace, else by time."""
        usable = any(v not in (-1, 0) and math.isfinite(v) for v in self.sbt)
        return Playback(self.times, self.et, self.bt, self.set, self.sbt, self.events, self.etypes, self.evalues,
                        self.timeindex[:8], replay_type=BY_BT if usable else BY_TIME)


def live(session: Session, tp_index: int | None = None) -> Foreground:
    """The live roast as the playback reads it: each recorded setting is an event."""
    samples = session.samples
    times = [s.elapsed_s for s in samples]
    bt = [s.bt_c for s in samples]
    et = [s.et_c if s.et_c is not None else -1 for s in samples]
    events, etypes, evalues = [], [], []
    for elapsed, lever, value in session.settings:
        if lever in EVENT_TYPE and times:
            events.append(min(bisect.bisect_left(times, elapsed), len(times) - 1))
            etypes.append(EVENT_TYPE[lever])
            evalues.append(event_value(value))
    return Foreground(times, et, bt, et, bt, tp_index, events, etypes, evalues, dropped="drop" in session.milestones)

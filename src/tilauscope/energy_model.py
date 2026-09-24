#
# ABOUT
# Energy accounting of one monitoring session: power series in, Wh out.

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
# Tilau 2026

"""Pure energy model — no Qt, no application object.

A session holds one channel per source (`roaster`, `extractor`). A channel
keeps two series on the same time axis:

- measured points `(t, W)`, integrated by trapezes between two points no
  further apart than the channel's freshness limit;
- estimated command points `(t, W)`, a step function held until the next one.

A measurement always wins over an estimate. Time not covered by either is
unknown and is reported as such, never as zero. Spec:
wiki/Energy-Simplified-View-Spec.md.
"""

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any, Final

VERSION: Final[int] = 1

ROASTER: Final[str] = "roaster"
EXTRACTOR: Final[str] = "extractor"
CHANNELS: Final[tuple[str, str]] = (ROASTER, EXTRACTOR)

MEASURED: Final[str] = "measured"
ESTIMATED: Final[str] = "estimated"
MIXED: Final[str] = "mixed"
NONE: Final[str] = "none"

# Float noise tolerated before a period is called incomplete.
_EPS_S: Final[float] = 0.5
# Cadence assumed until the channel has shown its own.
DEFAULT_PERIOD_S: Final[float] = 10.0


def freshness_s(period_s: float) -> float:
    """Longest gap bridged between two measurements (spec §6)."""
    return max(3.0, 3.0 * period_s)


def heater_watts(pct: float, rated_w: float | None, exponent: float = 1.0,
                 curve: list[list[float]] | None = None) -> float | None:
    """Mean power for a heater command. A measured curve is interpolated and
    held flat past its ends; otherwise rated × (pct/100)^exponent."""
    pct = min(max(pct, 0.0), 100.0)
    if curve:
        pts = sorted((float(a), float(b)) for a, b in curve)
        if pct <= pts[0][0]:
            return pts[0][1]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
            if pct <= xb:
                return ya + (yb - ya) * (pct - xa) / (xb - xa) if xb > xa else yb
        return pts[-1][1]
    if rated_w:
        return rated_w * (pct / 100.0) ** exponent
    return None


def _valid_watts(w: Any) -> float | None:
    """A finite, non-negative number; anything else is not a reading."""
    try:
        v = float(w)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


@dataclass
class Totals:
    measured_wh: float = 0.0
    estimated_wh: float = 0.0
    measured_s: float = 0.0
    estimated_s: float = 0.0
    unknown_s: float = 0.0

    def __iadd__(self, o: Totals) -> Totals:
        self.measured_wh += o.measured_wh
        self.estimated_wh += o.estimated_wh
        self.measured_s += o.measured_s
        self.estimated_s += o.estimated_s
        self.unknown_s += o.unknown_s
        return self

    @property
    def wh(self) -> float:
        return self.measured_wh + self.estimated_wh

    @property
    def span_s(self) -> float:
        return self.measured_s + self.estimated_s + self.unknown_s

    @property
    def provenance(self) -> str:
        m, e = self.measured_s > _EPS_S, self.estimated_s > _EPS_S
        if m and e:
            return MIXED
        if m:
            return MEASURED
        if e:
            return ESTIMATED
        return NONE

    @property
    def incomplete(self) -> bool:
        return self.unknown_s > _EPS_S

    @property
    def coverage(self) -> float:
        """Share of the period with a measured or estimated power, 0..1."""
        span = self.span_s
        return 1.0 if span <= 0 else (self.measured_s + self.estimated_s) / span


@dataclass
class Channel:
    source: str = ""              # "mqtt" or "model"
    topic: str = ""               # MQTT topic, "" for a model
    period_s: float = DEFAULT_PERIOD_S
    mt: list[float] = field(default_factory=list)   # measured times
    mw: list[float] = field(default_factory=list)   # measured watts
    et: list[float] = field(default_factory=list)   # estimate change times
    ew: list[float] = field(default_factory=list)   # estimated watts

    @property
    def max_gap_s(self) -> float:
        return freshness_s(self.period_s)

    def add_measure(self, t: float, w: Any) -> bool:
        """Append a reading. Repeated or backward timestamps are dropped, so a
        callback firing twice on the same message counts it once."""
        v = _valid_watts(w)
        if v is None or (self.mt and t <= self.mt[-1]):
            return False
        self.mt.append(float(t))
        self.mw.append(v)
        return True

    def add_estimate(self, t: float, w: Any) -> bool:
        """Record a new commanded power; an unchanged value adds nothing."""
        v = _valid_watts(w)
        if v is None or (self.et and t <= self.et[-1]):
            return False
        if self.ew and self.ew[-1] == v:
            return False
        self.et.append(float(t))
        self.ew.append(v)
        return True

    def stop_estimate(self, t: float) -> None:
        """No estimate from `t` on (stored as -1) until the next add_estimate."""
        if self.ew and self.ew[-1] >= 0 and t > self.et[-1]:
            self.et.append(float(t))
            self.ew.append(-1.0)

    def _estimate_at(self, t: float) -> float | None:
        j = bisect_right(self.et, t) - 1
        return self.ew[j] if j >= 0 and self.ew[j] >= 0 else None

    def power_now(self, now: float) -> tuple[float | None, str]:
        """Last fresh reading, else the current estimate, else unknown."""
        if self.mt and 0 <= now - self.mt[-1] <= self.max_gap_s:
            return self.mw[-1], MEASURED
        est = self._estimate_at(now)
        if est is not None:
            return est, ESTIMATED
        return None, NONE

    def settled(self, now: float) -> float:
        """Up to where the power is final. While the last reading is fresh the
        interval after it waits for the next one: it may still be bridged."""
        if self.mt and now - self.mt[-1] <= self.max_gap_s:
            return self.mt[-1]
        return now

    def integrate(self, t0: float, t1: float) -> Totals:
        """Energy and coverage over [t0, t1]. Additive: integrating [a, b] and
        [b, c] gives the same totals as [a, c]."""
        out = Totals()
        if t1 <= t0:
            return out
        gap = self.max_gap_s
        # measured segments touching [t0, t1]
        segs: list[tuple[float, float, float, float]] = []
        k = max(bisect_right(self.mt, t0) - 1, 0)
        n = len(self.mt)
        while k < n - 1 and self.mt[k] < t1:
            ta, tb = self.mt[k], self.mt[k + 1]
            if tb > t0 and tb - ta <= gap:
                segs.append((ta, self.mw[k], tb, self.mw[k + 1]))
            k += 1
        cuts = {t0, t1}
        for ta, _, tb, _ in segs:
            cuts.add(min(max(ta, t0), t1))
            cuts.add(min(max(tb, t0), t1))
        lo, hi = bisect_right(self.et, t0), bisect_left(self.et, t1)
        cuts.update(self.et[lo:hi])
        edges = sorted(cuts)
        s = 0
        for x, y in zip(edges, edges[1:], strict=False):
            dt = y - x
            if dt <= 0:
                continue
            mid = (x + y) / 2
            while s < len(segs) and segs[s][2] <= mid:
                s += 1
            if s < len(segs) and segs[s][0] <= mid:
                ta, wa, tb, wb = segs[s]
                def lerp(t: float, ta: float = ta, wa: float = wa,
                         tb: float = tb, wb: float = wb) -> float:
                    return wa + (wb - wa) * (t - ta) / (tb - ta)
                out.measured_wh += (lerp(x) + lerp(y)) / 2 * dt / 3600.0
                out.measured_s += dt
                continue
            est = self._estimate_at(mid)
            if est is not None:
                out.estimated_wh += est * dt / 3600.0
                out.estimated_s += dt
            else:
                out.unknown_s += dt
        return out

    def shifted(self, dt: float) -> Channel:
        return Channel(self.source, self.topic, self.period_s,
                       [t - dt for t in self.mt], list(self.mw),
                       [t - dt for t in self.et], list(self.ew))

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "topic": self.topic, "unit": "W",
                "period_s": self.period_s, "max_gap_s": self.max_gap_s,
                "measured": [[round(t, 3), round(w, 1)] for t, w in zip(self.mt, self.mw, strict=False)],
                "estimated": [[round(t, 3), round(w, 1)] for t, w in zip(self.et, self.ew, strict=False)]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Channel:
        ch = cls(str(d.get("source", "")), str(d.get("topic", "")),
                 float(d.get("period_s", DEFAULT_PERIOD_S)))
        for t, w in d.get("measured", []):
            ch.add_measure(float(t), w)
        for t, w in d.get("estimated", []):
            if float(w) < 0:
                ch.stop_estimate(float(t))
            else:
                ch.add_estimate(float(t), w)
        return ch


@dataclass
class PhaseBounds:
    """Milestones on the session's time axis; None when not marked."""
    charge: float | None = None
    dry: float | None = None
    fcs: float | None = None
    drop: float | None = None


def phase_bounds(timex: Any, timeindex: Any) -> PhaseBounds:
    """Read the milestones with Artisan's per-index sentinels: CHARGE is
    marked when > -1 (0 is a valid sample), every other one when > 0."""
    def at(i: int, marked: bool) -> float | None:
        try:
            pos = int(timeindex[i])
            if marked and 0 <= pos < len(timex):
                return float(timex[pos])
        except (IndexError, TypeError, ValueError):
            pass
        return None
    try:
        ti = list(timeindex)
    except TypeError:
        return PhaseBounds()
    if len(ti) < 7:
        return PhaseBounds()
    return PhaseBounds(charge=at(0, ti[0] > -1), dry=at(1, ti[1] > 0),
                       fcs=at(2, ti[2] > 0), drop=at(6, ti[6] > 0))


@dataclass
class Period:
    start: float
    end: float
    per_channel: dict[str, Totals]
    open: bool = False            # still running (live, not closed by its milestone)


@dataclass
class Summary:
    since_start: dict[str, Totals]
    before_charge: Period | None
    roast: Period | None
    after_drop: Period | None
    roast_split: list[tuple[str, Period]]     # drying / maillard / development
    expected: list[str]
    extractor_included: bool                  # extractor sits behind the roaster meter
    wh_per_kg: float | None                # roast energy per kg green; None = not shown

    def total(self, per_channel: dict[str, Totals]) -> Totals:
        """Sum of the channels that count; the included extractor never does."""
        out = Totals()
        for name in self.expected:
            if name in per_channel:
                out += per_channel[name]
        return out

    def complete(self, per_channel: dict[str, Totals]) -> bool:
        """Every expected source present and covered over the whole period."""
        return all(name in per_channel and not per_channel[name].incomplete
                   and per_channel[name].provenance != NONE for name in self.expected)


@dataclass
class EnergySession:
    start: float                       # monitoring ON, session axis
    end: float                         # last settled instant
    channels: dict[str, Channel] = field(default_factory=dict)
    extractor_expected: bool = False
    extractor_on_roaster_meter: bool = False
    roaster: str = ""
    # [t, burner %, air %, extraction %] on change, -1 when unknown — the
    # context a later analysis needs, pre-START included (Artisan keeps none).
    context: list[list[float]] = field(default_factory=list)
    # Seconds to subtract to land on the profile's recording axis (timex);
    # 0 once saved. `recorded` is False when recording never started.
    offset: float = 0.0
    recorded: bool = False
    # Rebuilt from a saved extra-device curve, not recorded live.
    rebuilt: bool = False

    # ── live feed ────────────────────────────────────────────────────────

    def channel(self, name: str, source: str, topic: str = "",
                period_s: float = DEFAULT_PERIOD_S) -> Channel:
        ch = self.channels.get(name)
        if ch is None:
            ch = Channel(source, topic, period_s)
            self.channels[name] = ch
        return ch

    def add_context(self, t: float, burner: float, air: float, fan: float) -> None:
        row = [t, burner, air, fan]
        if self.context and self.context[-1][1:] == row[1:]:
            return
        self.context.append(row)

    def horizon(self, now: float) -> float:
        """Latest instant every channel has settled."""
        h = now
        for ch in self.channels.values():
            h = min(h, ch.settled(now))
        return max(h, self.start)

    # ── reading ──────────────────────────────────────────────────────────

    def expected(self) -> list[str]:
        out = [ROASTER]
        if self.extractor_expected and not self.extractor_on_roaster_meter:
            out.append(EXTRACTOR)
        return out

    def _period(self, t0: float, t1: float, open_: bool = False) -> Period:
        return Period(t0, t1, {n: ch.integrate(t0, t1) for n, ch in self.channels.items()},
                      open_)

    def summarize(self, bounds: PhaseBounds, green_kg: float = 0.0,
                  live: bool = False) -> Summary:
        """Totals by phase. `bounds` is on the recording axis (timex)."""
        def ax(t: float | None) -> float | None:
            return None if t is None or not self.recorded else t + self.offset

        start, end = self.start, self.end
        charge, drop = ax(bounds.charge), ax(bounds.drop)
        if charge is not None and not start <= charge <= end:
            charge = None
        if drop is not None and (charge is None or not charge < drop <= end):
            drop = None

        before = self._period(start, charge if charge is not None else end,
                              open_=charge is None and live)
        roast = after = None
        split: list[tuple[str, Period]] = []
        if charge is not None:
            if drop is not None:
                roast = self._period(charge, drop)
                after = self._period(drop, end, open_=live)
            elif live:
                roast = self._period(charge, end, open_=True)
            dry, fcs = ax(bounds.dry), ax(bounds.fcs)
            stop = drop if drop is not None else (end if live else None)
            if stop is not None and dry is not None and fcs is not None \
                    and charge < dry < fcs < stop:
                split = [("drying", self._period(charge, dry)),
                         ("maillard", self._period(dry, fcs)),
                         ("development", self._period(fcs, stop, open_=drop is None))]

        summary = Summary(since_start=self._period(start, end, open_=live).per_channel,
                          before_charge=before, roast=roast, after_drop=after,
                          roast_split=split, expected=self.expected(),
                          extractor_included=self.extractor_expected and self.extractor_on_roaster_meter,
                          wh_per_kg=None)
        if roast is not None and not roast.open and green_kg > 0 \
                and summary.complete(roast.per_channel):
            summary.wh_per_kg = summary.total(roast.per_channel).wh / green_kg
        return summary

    # ── persistence ──────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Versioned block saved in the .alog, times on the recording axis
        (or on the session start when recording never started)."""
        shift = self.offset if self.recorded else self.start
        return {
            "version": VERSION,
            "axis": "recording" if self.recorded else "session",
            "start": round(self.start - shift, 3),
            "end": round(self.end - shift, 3),
            "roaster": self.roaster,
            "extractor_expected": self.extractor_expected,
            "extractor_on_roaster_meter": self.extractor_on_roaster_meter,
            "rebuilt": self.rebuilt,
            "channels": {n: ch.shifted(shift).to_dict() for n, ch in self.channels.items()},
            "context": [[round(r[0] - shift, 3), *r[1:]] for r in self.context],
        }

    @classmethod
    def from_dict(cls, d: Any) -> EnergySession | None:
        """None for an absent, unreadable or newer block."""
        if not isinstance(d, dict):
            return None
        try:
            if int(d.get("version", 0)) != VERSION:
                return None
            s = cls(start=float(d["start"]), end=float(d["end"]),
                    extractor_expected=bool(d.get("extractor_expected", False)),
                    extractor_on_roaster_meter=bool(d.get("extractor_on_roaster_meter", False)),
                    roaster=str(d.get("roaster", "")),
                    recorded=d.get("axis") == "recording",
                    rebuilt=bool(d.get("rebuilt", False)))
            for name, cd in (d.get("channels") or {}).items():
                if name in CHANNELS and isinstance(cd, dict):
                    s.channels[name] = Channel.from_dict(cd)
            s.context = [list(map(float, r)) for r in d.get("context") or [] if len(r) == 4]
            return s
        except (KeyError, TypeError, ValueError):
            return None


def session_for_profile(profile: Any) -> EnergySession | None:
    """The energy bill a profile carries, else the one rebuilt from its curve."""
    if not isinstance(profile, dict):
        return None
    return EnergySession.from_dict(profile.get("tilau_energy")) or rebuild_from_profile(profile)


# A saved extra-device curve repeats the last cached value on every sample and
# hides a report identical to the previous one, so only its changes are
# readings, and a plateau between two of them is longer than any real silence.
REBUILT_PERIOD_S: Final[float] = 120.0


def rebuild_from_profile(profile: Any) -> EnergySession | None:
    """Energy session of a profile saved without one, from its extra-device
    channels named `roaster` / `extractor` (W). Covers START to the end of the
    recording only. None when the profile has no such channel."""
    try:
        if not isinstance(profile, dict) or profile.get("tilau_simulated"):
            return None
        timex = [float(t) for t in profile.get("timex") or []]
        if len(timex) < 2:
            return None
        s = EnergySession(start=timex[0], end=timex[-1], recorded=True, rebuilt=True,
                          roaster=str(profile.get("roastertype", "") or ""))
        xtimex = profile.get("extratimex") or []
        for k in (1, 2):
            for i, (name, series) in enumerate(zip(profile.get(f"extraname{k}") or [],
                                                   profile.get(f"extratemp{k}") or [], strict=False)):
                key = str(name).strip().lower()
                if key not in CHANNELS or key in s.channels:
                    continue
                # each extra device is sampled on its own axis
                axis = [float(t) for t in xtimex[i]] if i < len(xtimex) and xtimex[i] else timex
                ch = Channel("mqtt", "", REBUILT_PERIOD_S)
                prev: Any = None
                prev_t = axis[0]
                for t, w in zip(axis, series, strict=False):
                    if w != prev:
                        # the old value holds up to the last sample showing it: a step, not a ramp
                        if prev is not None:
                            ch.add_measure(prev_t, prev)
                        ch.add_measure(t, w)
                        prev = w
                    prev_t = t
                # the last sample closes the curve: its value is known up to there
                if len(series) >= len(axis) and prev is not None:
                    ch.add_measure(axis[-1], prev)
                if ch.mt:
                    s.channels[key] = ch
        if ROASTER not in s.channels and EXTRACTOR not in s.channels:
            return None
        s.extractor_expected = EXTRACTOR in s.channels
        return s
    except (TypeError, ValueError):
        return None

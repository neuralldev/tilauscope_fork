# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.
#
# Portions derived from Artisan Roaster Scope (artisanlib/main.py),
# Copyright (C) 2010-2026 the Artisan team represented by Marko Luther
# and all contributors, distributed under the terms of their original licence.

"""Milestones found during a roast (android/AUTOMATION-SPEC.md D1).

CHARGE and DROP from a break in BT, as Artisan finds them (main.BTbreak, checkTop and the
conditions of canvas.sample); First Crack and Dry End as TilauScope's detectors find them
(tilau_intelligence). Pure: the caller gives the readings, the target and the clock; reading
the devices and marking the milestone stay with the app.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Final, NamedTuple

# ── CHARGE and DROP: a break in BT (Artisan) ─────────────────────────────────
# Artisan's btbreak_params; index [mode][sample mode], mode 0 Standard, 1 Sensitive,
# sample mode 0 for a delay >= 1000 ms, 1 from 500 ms, 2 below.
BTBREAK: Final[dict] = {
    "delay": [[40000, 1000, 500], [40000, 1000, 500]],
    "d_charge": [[-0.67, -0.34, -0.20], [0.00, 0.00, 0.00]],
    "d_drop": [[-0.34, -0.20, 0.00], [0.00, 0.00, 0.00]],
    "offset_charge": [[0.5, 0.2, 0.0], [0.5, 0.1, 0.0]],
    "offset_drop": [[0.2, 0.1, 0.0], [0.2, 0.05, 0.0]],
    "dpre_dpost_diff": [[0.78, 0.78, 20.0], [20.0, 20.0, 20.0]],
    "tight": 3, "loose": 5, "f": 2.5, "maxdpre": 6.4, "f_dtwice": 1.5,
}
CHARGE_MIN_BT: Final[dict[str, float]] = {"C": 77.0, "F": 170.0}
DROP_MIN_BT: Final[dict[str, float]] = {"C": 160.0, "F": 320.0}
DROP_MIN_S: Final[float] = 7 * 60.0


def check_top(d: float, offset: float, dpre_dpost_diff: float, p0: float, p1: float, p2: float,
              p3: float, p4: float, p5: float, unit: str = "C", twice: bool = False) -> bool:
    """Artisan's checkTop: the two legs before p2–p3 against the two after."""
    d1, d2 = p0 - p1, p1 - p2
    d3, d4 = p4 - p3, p5 - p4
    dpre, dpost = (d1 + d2) / 2.0, (d3 + d4) / 2.0
    f, maxdpre, f_dtwice = BTBREAK["f"], BTBREAK["maxdpre"], BTBREAK["f_dtwice"]
    if unit == "F":
        f *= 1.8
        d *= 1.8
        maxdpre *= 1.8
        dpre_dpost_diff *= 1.8
    if twice:
        d = d * f_dtwice
    return bool(d3 < d and d4 < d and ((abs(dpost) > min(maxdpre, offset + (f * abs(dpre))))
                                       or (dpost < 0 and dpre < 0 and (-dpre - dpost) > dpre_dpost_diff)))


def bt_break(bt: Sequence[float], i: int, event: str, delay_ms: int = 1000, charge_mode: int = 0,
             drop_mode: int = 0, unit: str = "C") -> int:
    """Artisan's BTbreak: how many samples back from `i` the break is (3 or 5), 0 when none.

    As Artisan, the sample mode is chosen with the DROP mode for both events.
    """
    delays = BTBREAK["delay"][drop_mode]
    sample_mode = 2 if delay_ms < delays[2] else 1 if delay_ms < delays[1] else 0
    if event == "DROP":
        mode = drop_mode
        d, offset = BTBREAK["d_drop"][mode][sample_mode], BTBREAK["offset_drop"][mode][sample_mode]
    else:
        mode = charge_mode
        d, offset = BTBREAK["d_charge"][mode][sample_mode], BTBREAK["offset_charge"][mode][sample_mode]
    diff = BTBREAK["dpre_dpost_diff"][mode][sample_mode]
    if len(bt) > 5 and 4 < i < len(bt):
        if check_top(d, offset, diff, bt[i - 5], bt[i - 4], bt[i - 3], bt[i - 2], bt[i - 1], bt[i], unit):
            return BTBREAK["tight"]
        if len(bt) > 10 and i > 10 and check_top(d, offset, diff, bt[i - 10], bt[i - 8], bt[i - 6], bt[i - 4],
                                                 bt[i - 2], bt[i], unit, twice=True):
            return BTBREAK["loose"]
    return 0


def charge_index(bt: Sequence[float], unit: str = "C", delay_ms: int = 1000, charge_mode: int = 0,
                 drop_mode: int = 0) -> int | None:
    """The sample CHARGE is placed on, found at this sample (CHARGE not marked yet), else None."""
    n = len(bt)
    if n < 5 or not bt[-1] > CHARGE_MIN_BT[unit]:
        return None
    b = bt_break(bt, n - 1, "CHARGE", delay_ms, charge_mode, drop_mode, unit)
    return n - b if b > 0 else None


def drop_index(times: Sequence[float], bt: Sequence[float], charge: int, unit: str = "C",
               delay_ms: int = 1000, drop_mode: int = 0) -> int | None:
    """The sample DROP is placed on, found at this sample (after CHARGE, DROP not marked), else None."""
    n = len(bt)
    if n < 5 or not bt[-1] > DROP_MIN_BT[unit] or not times[-1] - times[charge] > DROP_MIN_S:
        return None
    b = bt_break(bt, n - 1, "DROP", delay_ms, 0, drop_mode, unit)
    return n - b if b > 0 else None


# ── Milestone windows (tilauscope_types) ─────────────────────────────────────
# Profession bands in the true bean frame, before the roaster's sensor offset.
PROFESSION_DE_TRUE_C: Final[tuple[float, float]] = (158.0, 163.0)
PROFESSION_FC_TRUE_C: Final[tuple[float, float]] = (195.0, 200.0)
MILESTONE_HALF_C: Final[float] = 5.0


def resolve_milestone_window(plan_target_c: float, true_band_c: tuple[float, float],
                             sensor_offset_c: float = 0.0,
                             half_c: float = MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    """(gate_lo, gate_hi, band_lo, band_hi) in the displayed BT frame: the plan's point, else the band."""
    if plan_target_c and plan_target_c > 0.0:
        band_lo = band_hi = float(plan_target_c)
    else:
        band_lo = float(true_band_c[0]) + float(sensor_offset_c)
        band_hi = float(true_band_c[1]) + float(sensor_offset_c)
    return band_lo - half_c, band_hi + half_c, band_lo, band_hi


def resolve_de_window(plan_target_c: float, bt_dry_offset_c: float = 0.0,
                      half_c: float = MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_DE_TRUE_C, bt_dry_offset_c, half_c)


def resolve_fc_window(plan_target_c: float, bt_fc_offset_c: float = 0.0,
                      half_c: float = MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_FC_TRUE_C, bt_fc_offset_c, half_c)


# ── First Crack (FirstCrackDetector) ─────────────────────────────────────────

class FirstCrack:
    """BT reaching the FC window is the base; a burst of cracks at or above the target calls
    it sooner. `cracks` is the crack counter's cumulative count (FC and SC channels fused)."""

    CONFIRM_S: Final[float] = 4.0

    def __init__(self, window_s: float = 35.0, threshold: int = 4, half_band_c: float = MILESTONE_HALF_C) -> None:
        self.window_s, self.threshold, self.half_band_c = window_s, threshold, half_band_c
        self.crack_times: deque[float] = deque()
        self.fired = False
        self._armed = False
        self._pos_since: float | None = None
        self._banked: int | None = None

    def check(self, bt: float, target: float, t: float, cracks: int | None, unit: str = "C") -> float | None:
        """The FC time when it fires at this sample (the first crack of a burst, else now), else None."""
        if self.fired:
            return None
        half = self.half_band_c * (1.8 if unit == "F" else 1.0)
        if target and target > 0.0:
            band_lo = band_hi = float(target)
            fc_lo, fc_hi = band_lo - half, band_hi + half
        else:
            fc_lo, fc_hi, band_lo, band_hi = resolve_fc_window(0.0, 0.0, self.half_band_c)
            if unit == "F":
                fc_lo, fc_hi, band_lo, band_hi = (v * 9.0 / 5.0 + 32.0 for v in (fc_lo, fc_hi, band_lo, band_hi))
        if bt < fc_lo: # below the window: armed from below, no pop banked (pre-FC noise)
            self._armed = True
            return None
        if not self._armed:
            return None
        if bt >= fc_hi: # FC cannot be later
            self.fired = True
            return t
        if cracks is not None:
            if self._banked is None:
                self._banked = cracks # pops before the window do not count
            elif cracks > self._banked:
                self.crack_times.extend([t] * (cracks - self._banked))
                self._banked = cracks
        while self.crack_times and t - self.crack_times[0] > self.window_s:
            self.crack_times.popleft()
        if len(self.crack_times) >= self.threshold and bt >= band_lo:
            self.fired = True
            return self.crack_times[0]
        if bt >= band_hi:
            if self._pos_since is None:
                self._pos_since = t
            if t - self._pos_since >= self.CONFIRM_S:
                self.fired = True
                return t
        else:
            self._pos_since = None
        return None


# ── Dry End (DryEndDetector) ─────────────────────────────────────────────────

class DryEndResult(NamedTuple):
    confidence: float
    fired: bool
    score_pos: float
    score_color: float
    score_morph: float
    reason: str


class DryEnd:
    """The physical window around the target, where BT's position, the knee of the post-TP RoR
    bell and, with a live colour meter, the turn of the colour decide; forced at the window's top."""

    BUFFER_SIZE: Final[int] = 240
    ROR_WINDOW_S: Final[float] = 30.0
    FIRE_THRESHOLD: Final[float] = 0.75
    CONFIRM_S: Final[float] = 4.0
    COLOR_SLOPE_WINDOW_S: Final[float] = 30.0
    COLOR_SLOPE_NEG: Final[float] = -0.8
    COLOR_ONSET_S: Final[float] = 6.0
    COLOR_MIN_SAMPLES: Final[int] = 5
    COLOR_VALID_MIN: Final[float] = 0.0
    AG_PEAK_DROP_MIN: Final[float] = 1.0
    MORPH_SLOPE_WINDOW_S: Final[float] = 30.0
    MORPH_DROP_FULL: Final[float] = 0.45
    MORPH_FLAT_SCALE: Final[float] = 4.0
    ROR_PEAK_MIN: Final[float] = 3.0
    POS_W: Final[float] = 0.75
    MORPH_W: Final[float] = 0.25
    COLOR_W: Final[float] = 0.90
    COLOR_POS_W: Final[float] = 0.10

    def __init__(self, colour_meter: bool = False) -> None:
        self.colour_meter = colour_meter # a colour channel among the devices
        self._bt: deque[float] = deque([0.0] * self.BUFFER_SIZE, maxlen=self.BUFFER_SIZE)
        self._t: deque[float] = deque([0.0] * self.BUFFER_SIZE, maxlen=self.BUFFER_SIZE)
        self._ror: deque[float] = deque(maxlen=self.BUFFER_SIZE)
        self._ror_t: deque[float] = deque(maxlen=self.BUFFER_SIZE)
        self._ag: deque[float] = deque(maxlen=self.BUFFER_SIZE)
        self._ag_t: deque[float] = deque(maxlen=self.BUFFER_SIZE)
        self.bt_tp = 0.0
        self.tp_confirmed = False
        self._de_lo = self._de_hi = self._band_lo = self._band_hi = 0.0
        self._unit_scale = 1.0
        self._ror_peak = 0.0
        self._ag_peak = -1.0
        self._color_neg_since: float | None = None
        self.fired = False
        self._armed = False
        self._confirm_since: float | None = None

    def set_context(self, target: float, dry_offset: float = 0.0, unit: str = "C") -> None:
        """The window: the plan's target (native unit) +/- half, else the profession band + offset."""
        self._unit_scale = 1.8 if unit == "F" else 1.0
        half = 9.0 if unit == "F" else 5.0
        if target and target > 0.0:
            de_lo, de_hi, band_lo, band_hi = resolve_de_window(target, dry_offset, half_c=half)
        else:
            de_lo, de_hi, band_lo, band_hi = resolve_de_window(0.0, dry_offset)
            if unit == "F":
                de_lo, de_hi, band_lo, band_hi = (v * 9.0 / 5.0 + 32.0 for v in (de_lo, de_hi, band_lo, band_hi))
        self._de_lo, self._de_hi, self._band_lo, self._band_hi = de_lo, de_hi, band_lo, band_hi

    def set_tp(self, bt_tp: float) -> None:
        """The turning point's BT, once found; nothing is detected before it."""
        if not self.tp_confirmed:
            self.bt_tp, self.tp_confirmed = float(bt_tp), True

    def check(self, bt: float, t: float, ror: float | None = None, colour: float | None = None) -> DryEndResult:
        """Each sample after CHARGE: `ror` the BT RoR (None: computed over 30 s), `colour` the meter's value."""
        self._bt.append(bt)
        self._t.append(t)
        if not self.fired and self.tp_confirmed:
            r = ror if ror is not None else self._computed_ror()
            self._ror.append(r)
            self._ror_t.append(t)
            self._ror_peak = max(self._ror_peak, r)
        if not self.fired and self.colour_meter and colour is not None and not colour < self.COLOR_VALID_MIN:
            self._ag.append(colour)
            self._ag_t.append(t)
        if not self.tp_confirmed or self._de_hi <= 0.0:
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, "")
        if self.fired:
            return DryEndResult(1.0, False, 0.0, 0.0, 0.0, "")
        if bt < self._de_lo:
            self._armed = True
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, "")
        if not self._armed:
            return DryEndResult(0.0, False, 0.0, 0.0, 0.0, "")
        if bt >= self._de_hi:
            self.fired = True
            return DryEndResult(1.0, True, 1.0, 0.0, 0.0, f"force@DE_hi (BT={bt:.1f}>={self._de_hi:.1f})")
        s_pos = self._score_pos(bt)
        s_morph = self._score_morph(ror)
        base = self.POS_W * s_pos + self.MORPH_W * s_morph
        color_live, s_color = self._score_color(t)
        confidence = max(base, self.COLOR_W * s_color + self.COLOR_POS_W * s_pos) if color_live and s_color > 0.0 else base
        confidence = max(0.0, min(1.0, confidence))
        if confidence >= self.FIRE_THRESHOLD:
            if self._confirm_since is None:
                self._confirm_since = t
        else:
            self._confirm_since = None
        if self._confirm_since is not None and t - self._confirm_since >= self.CONFIRM_S:
            self.fired = True
            return DryEndResult(confidence, True, s_pos, s_color, s_morph, self._reason(s_pos, s_color, s_morph, color_live))
        return DryEndResult(confidence, False, s_pos, s_color, s_morph, "")

    def _score_pos(self, bt: float) -> float:
        if bt <= self._de_lo:
            return 0.0
        if bt >= self._band_hi:
            return 1.0
        return (bt - self._de_lo) / (self._band_hi - self._de_lo)

    def _score_color(self, t: float) -> tuple[bool, float]:
        if not self.colour_meter or not self._ag:
            return False, 0.0
        ag_now = self._ag[-1]
        self._ag_peak = max(self._ag_peak, ag_now)
        slope = self._slope(self._ag, self._ag_t, self.COLOR_SLOPE_WINDOW_S, self.COLOR_MIN_SAMPLES)
        if slope is None:
            return False, 0.0
        if (self._ag_peak - ag_now) >= self.AG_PEAK_DROP_MIN and slope * 60.0 <= self.COLOR_SLOPE_NEG:
            if self._color_neg_since is None:
                self._color_neg_since = t
            return True, max(0.0, min(1.0, (t - self._color_neg_since) / self.COLOR_ONSET_S))
        self._color_neg_since = None
        return True, 0.0

    def _score_morph(self, ror: float | None) -> float:
        if self._ror_peak < self.ROR_PEAK_MIN * self._unit_scale:
            return 0.0
        r_now = ror if ror is not None else self._computed_ror()
        drop_score = max(0.0, min(1.0, (self._ror_peak - r_now) / self._ror_peak / self.MORPH_DROP_FULL))
        slope = self._slope(self._ror, self._ror_t, self.MORPH_SLOPE_WINDOW_S, 5)
        if slope is None:
            return 0.0
        slope_min2 = slope * 60.0
        flat_score = 1.0 if slope_min2 >= 0.0 else max(0.0, 1.0 - (-slope_min2) / (self.MORPH_FLAT_SCALE * self._unit_scale))
        return max(0.0, min(1.0, drop_score, flat_score))

    def _computed_ror(self) -> float:
        """BT RoR over the last 30 s, from this detector's own buffer (when the app gives none)."""
        n = len(self._t)
        if n < 2:
            return 0.0
        target = self._t[-1] - self.ROR_WINDOW_S
        for back in range(1, n):
            if self._t[-1 - back] <= target:
                idx = n - 1 - back
                dt = self._t[-1] - self._t[idx]
                return 0.0 if dt <= 0 else (self._bt[-1] - self._bt[idx]) / dt * 60.0
        return 0.0

    @staticmethod
    def _slope(vals: deque[float], ts: deque[float], window_s: float, min_n: int) -> float | None:
        """Least-squares slope (unit per second) over the last `window_s`; None under `min_n` points."""
        n = len(ts)
        if n < min_n:
            return None
        cutoff = ts[-1] - window_s
        xs: list[float] = []
        ys: list[float] = []
        for i in range(n - 1, -1, -1):
            if ts[i] < cutoff:
                break
            xs.append(ts[i])
            ys.append(vals[i])
        m = len(xs)
        if m < min_n:
            return None
        sx, sy = sum(xs), sum(ys)
        sxx, sxy = sum(x * x for x in xs), sum(x * y for x, y in zip(xs, ys, strict=True))
        den = m * sxx - sx * sx
        return None if den == 0 else (m * sxy - sx * sy) / den

    @staticmethod
    def _reason(pos: float, color: float, morph: float, color_live: bool) -> str:
        parts = []
        if color_live and color >= 0.5:
            parts.append(f"Agtron_peak_descent({color:.2f})")
        if morph >= 0.5:
            parts.append(f"RoR_knee({morph:.2f})")
        if pos >= 0.5:
            parts.append(f"BT_in_band({pos:.2f})")
        return " + ".join(parts) if parts else "composite"

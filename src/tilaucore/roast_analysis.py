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
# Tilau 2025-2026

"""Reading a recorded roast, shared by both apps: the RoR bands of each phase,
the sampling interval, the turning point, RoR crashes and flicks, the milestone
sentinels of `timeindex`, the probe offsets and the weight-loss target.

Standard library only: the numbers are those NumPy and SciPy gave, computed the
same way.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Final, NamedTuple

from tilaucore.numeric import moving_average
from tilaucore.roast_levels import ROASTING_BASIC_BASE, RoasterBasicPlanPerPhase


# ── RoR (Rate-of-Rise, bean temperature) phase classifier ───────────────────
# Distinct from get_roc_color() above (Rate-of-COLOUR, Agtron/min). RoR works on
# BT in degrees/min. Bands are dual-sided (both too-high and too-low matter) and
# phase-specific. Source: Rao / Cropster / Mill City / Anne Cooper.
_ROR_PHASE_BANDS_C = {
    # phase_key:  (warn_lo, warn_hi, crit_lo, crit_hi)   -- ideal band in comment
    "CHARGE_DRY": (6.0, 15.0, 3.0, 18.0),   # ideal 8-14
    "DRY_FC":     (4.0, 13.0, 2.0, 16.0),   # ideal 5-12
    "FC_DROP":    (1.5,  7.0, 0.5,  9.0),   # ideal 2-6
}
_ROR_IDEAL_C = {"CHARGE_DRY": (8.0, 14.0), "DRY_FC": (5.0, 12.0), "FC_DROP": (2.0, 6.0)}
_ROR_PHASE_ALIASES = {
    "drying": "CHARGE_DRY", "dry": "CHARGE_DRY", "charge_dry": "CHARGE_DRY",
    "maillard": "DRY_FC", "dry_fc": "DRY_FC",
    "development": "FC_DROP", "dev": "FC_DROP", "fc_drop": "FC_DROP",
}


def _ror_phase_key(phase: str) -> str:
    p = str(phase).strip()
    return _ROR_PHASE_ALIASES.get(p.lower(), p.upper())


def get_ror_color_by_phase(ror: float, phase: str, mode: str = "C") -> tuple[str, str, str]:
    """
    Classify a BT Rate-of-Rise (degrees/min) against dual-sided, phase-specific
    bands. Returns (level, direction, colour):

        level     : "ok" | "warn" | "crit"
        direction : "normal" | "high" | "low"
        colour    : hex string (green / gold / red)

    `phase` accepts a band key ("CHARGE_DRY"|"DRY_FC"|"FC_DROP") or an alias
    ("drying"|"maillard"|"development"). mode "F" scales the C bands by 1.8.

    This is the RoR (bean-temperature) classifier. For Rate-of-Colour
    (Agtron/min) use get_roc_color(): RoR and RoC are different signals.
    """
    band = _ROR_PHASE_BANDS_C.get(_ror_phase_key(phase))
    if band is None or ror is None:
        return "ok", "normal", "#32CD32"
    warn_lo, warn_hi, crit_lo, crit_hi = band
    if mode == "F":
        warn_lo, warn_hi, crit_lo, crit_hi = (v * 1.8 for v in (warn_lo, warn_hi, crit_lo, crit_hi))
    if ror > crit_hi:
        return "crit", "high", "#FF4500"
    if ror < crit_lo:
        return "crit", "low", "#FF4500"
    if ror > warn_hi:
        return "warn", "high", "#FFD700"
    if ror < warn_lo:
        return "warn", "low", "#FFD700"
    return "ok", "normal", "#32CD32"


def get_ror_ideal_band(phase: str, mode: str = "C") -> tuple[float, float]:
    """Ideal RoR target band (degrees/min) for a phase, for display/messaging."""
    lo, hi = _ROR_IDEAL_C.get(_ror_phase_key(phase), (0.0, 0.0))
    return (lo * 1.8, hi * 1.8) if mode == "F" else (lo, hi)


# ── Shared crash/flick detection (prominence-based, sample-rate invariant) ────
# Single source for both the plan generator (historical-log analysis) and the
# BeanCave coach (single-roast and multi-roast comparison) — same algorithm,
# same thresholds, everywhere a crash or a flick is flagged.

def clean_delta_bt(delta_bt: list) -> list:
    """Forward-fills None values in a delta_bt (RoR) array; 0.0 at the start."""
    cleaned_list = []
    last_valid_value = 0.0
    for value in delta_bt:
        if value is None:
            cleaned_list.append(last_valid_value)
        else:
            current_val = float(value)
            cleaned_list.append(current_val)
            last_valid_value = current_val
    return cleaned_list


def estimate_ror_dt(timex) -> float:
    """Median sampling interval (s) of a log, derived from its own recorded
    timestamps. Robust to the user's Artisan sampling setting, which varies
    per recording. Falls back to 1.0 s."""
    tx = [float(t) for t in timex]
    d = [b - a for a, b in zip(tx, tx[1:], strict=False) if b - a > 0]
    if not d:
        return 1.0
    return min(max(statistics.median(d), 0.25), 10.0)


def find_turning_point_index(bt_input: list, dt: float = 1.0) -> int:
    """Index of the Turning Point = the BT minimum, searched in the early
    window (~15 s .. 2 min 30 after charge). Uses BT, not the RoR minimum:
    the RoR minimum (steepest cooling) occurs BEFORE the turning point."""
    bt = [math.nan if b is None else float(b) for b in bt_input] if bt_input else []
    if not bt:
        return 0
    lo = min(int(round(15.0 / dt)), len(bt) - 1)
    hi = min(int(round(150.0 / dt)), len(bt))
    if hi <= lo:
        hi = len(bt)
    if hi <= lo:
        return 0
    lowest = None  # the first of the lowest readings, gaps ignored
    for i in range(lo, hi):
        if not math.isnan(bt[i]) and (lowest is None or bt[i] < bt[lowest]):
            lowest = i
    return lo if lowest is None else lowest


def which_roast_phase(current_time: float, phase_times: dict) -> int:
    """Roasting phase for a timestamp (seconds since charge): 1=DRY, 2=MAILLARD,
    3=DEVELOPMENT, 0=out of scope (including post-FC when FC itself is unmarked,
    since Maillard and development cannot then be told apart)."""
    dry_end  = phase_times.get("dry_end")
    fc_start = phase_times.get("fc_start")
    drop     = phase_times.get("drop")
    if drop is None:
        return 0
    if dry_end is not None and current_time <= dry_end:
        return 1
    if fc_start is not None and current_time <= fc_start:
        return 2
    if fc_start is None:
        return 0
    if current_time <= drop:
        return 3
    return 0


def _find_peaks(x: list, prominence: float, distance: int) -> tuple[list[int], list[float]]:
    """scipy.signal.find_peaks(x, prominence=, distance=): the peaks and their prominences.

    Same steps as SciPy: local maxima (a flat top counts once, at its middle),
    then the distance rule from the highest peak down, then the prominence.
    """
    peaks, i, last = [], 1, len(x) - 1
    while i < last:
        if x[i - 1] < x[i]:
            ahead = i + 1
            while ahead < last and x[ahead] == x[i]:
                ahead += 1
            if x[ahead] < x[i]:
                peaks.append((i + ahead - 1) // 2)
                i = ahead
        i += 1
    keep = [True] * len(peaks)
    # Highest first, a tie latest first, as SciPy (sorted(reverse=True) would turn ties round).
    for j in reversed(sorted(range(len(peaks)), key=lambda p: x[peaks[p]])):  # noqa: C413
        if not keep[j]:
            continue
        k = j - 1
        while k >= 0 and peaks[j] - peaks[k] < distance:
            keep[k] = False
            k -= 1
        k = j + 1
        while k < len(peaks) and peaks[k] - peaks[j] < distance:
            keep[k] = False
            k += 1
    kept, prominences = [], []
    for peak in (p for p, ok in zip(peaks, keep, strict=True) if ok):
        left = right = x[peak]
        i = peak
        while i >= 0 and x[i] <= x[peak]:
            left = min(left, x[i])
            i -= 1
        i = peak
        while i <= last and x[i] <= x[peak]:
            right = min(right, x[i])
            i += 1
        if x[peak] - max(left, right) >= prominence:
            kept.append(peak)
            prominences.append(x[peak] - max(left, right))
    return kept, prominences


def find_flicks_crashes(
        delta_bt: list,
        timex: list,
        phase_times: dict,
        tp_index: int,
        prominence: float = 1.0,        # degrees C/min: significance of the dip/bump
        debounce_sec: float = 20.0,
        recovery_margin_sec: float = 30.0,
):
    """
    Detect significant RoR dips (crashes) and bumps (flicks) as LOCAL EXTREMA
    ranked by PROMINENCE (degrees C/min).

    Why prominence: a healthy roast has a continuously declining RoR, which has
    no local extremum, so it is never flagged. A crash is a genuine local valley
    and a flick a genuine local peak; their prominence is the physical measure of
    how significant the event is, comparable across roasts.

    Sample-rate invariant: every time window/limit is converted to samples using
    the per-log sampling interval derived from timex, so detection does not
    assume 1 Hz.
    """
    flicks: list = []
    crashes: list = []

    ror = clean_delta_bt(delta_bt)
    tx  = [float(t) for t in timex]
    n = len(ror)
    if n < 10 or len(tx) != n:
        return flicks, crashes

    dt = estimate_ror_dt(tx)
    distance = max(1, int(round(debounce_sec / dt)))

    # Light denoise (~5 s). Prominence already rejects small wiggles, so keep
    # this light to avoid attenuating short real flicks near first crack.
    win = max(1, int(round(5.0 / dt)))
    ror_s = moving_average(ror, win) if win > 1 else ror

    # Exclude the post-TP recovery: locate the recovery RoR peak within ~180 s
    # after the (BT-based) turning point, then start detecting a margin later so
    # the recovery peak itself is never mistaken for a flick.
    peak_limit = min(n, tp_index + int(round(180.0 / dt)))
    if 0 <= tp_index < peak_limit:
        window = ror_s[tp_index:peak_limit]
        rec_idx = tp_index + window.index(max(window))
        detect_from_t = tx[rec_idx] + recovery_margin_sec
    else:
        detect_from_t = float(tx[0]) + 120.0

    flick_idx, flick_prominences = _find_peaks(ror_s, prominence, distance)
    crash_idx, crash_prominences = _find_peaks([-v for v in ror_s], prominence, distance)

    for k, i in enumerate(flick_idx):
        if tx[i] <= detect_from_t:
            continue
        flicks.append({
            "time":      float(tx[i]),
            "ror_value": round(float(ror_s[i]), 2),
            "severity":  round(float(flick_prominences[k]), 2),
            "phase":     which_roast_phase(float(tx[i]), phase_times),
        })
    for k, i in enumerate(crash_idx):
        if tx[i] <= detect_from_t:
            continue
        crashes.append({
            "time":      float(tx[i]),
            "ror_value": round(float(ror_s[i]), 2),
            "severity":  round(float(crash_prominences[k]), 2),
            "phase":     which_roast_phase(float(tx[i]), phase_times),
        })
    return flicks, crashes


# Below this prominence a dip or a bump is inside the smoothing noise of a stored
# log: it does not show on the plotted RoR curve, so the coach must not name it.
DEV_EVENT_PROMINENCE_C: float = 2.0


def dominant_dev_ror_event(delta_bt: list, timex: list, phase_times: dict,
                           tp_index: int, mode: str = "C") -> dict | None:
    """The one significant RoR accident between first crack and drop, or None.

    A crash and a flick announced together contradict each other: every dip sits
    between two bumps, so the same wiggle yields both. Only the most prominent
    event is kept, so the advice names a single gesture.
    """
    scale = 1.8 if mode == "F" else 1.0
    flicks, crashes = find_flicks_crashes(
        delta_bt, timex, phase_times, tp_index,
        prominence=DEV_EVENT_PROMINENCE_C * scale)
    events = ([dict(e, kind="crash") for e in crashes if e.get("phase") == 3]
              + [dict(e, kind="flick") for e in flicks if e.get("phase") == 3])
    if not events:
        return None
    return max(events, key=lambda e: float(e.get("severity", 0.0)))




# Artisan roasting phases from timeindex table
class RoastingPhase:
    CHARGE = 0
    DRYEND = 1
    FCSTART = 2
    FCEND = 3
    SCSTART = 4
    SCEND = 5
    DROP = 6
    COOLEND = 7


UNMARKED: Final[tuple[int, ...]] = (-1, 0, 0, 0, 0, 0, 0, 0)


def marked(timeindex: object, i: int) -> bool:
    """True if milestone `i` has been placed.

    The "unmarked" sentinel is PER INDEX, not per mode. `timeindex` resets to
    [-1,0,0,0,0,0,0,0] in every mode: CHARGE reads -1 because 0 is a valid
    sample index, while 1..7 read 0 when unmarked. Testing `> -1` on a milestone
    is therefore always true and silently disables whatever it was guarding.
    Lives here, beside RoastingPhase, so reading a timeindex never costs an
    import of the graph package.
    """
    try:
        if i == 0:
            return int(timeindex[0]) > -1  # type: ignore[index]
        return int(timeindex[i]) > 0  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return False


def is_reading(value: object) -> bool:
    """False for None and for Artisan's -1: the probe answered nothing at that sample.

    Lives beside `marked` for the same reason: reading a sample never costs an
    import of the graph package.
    """
    return value is not None and value != -1


def normalize_timeindex(raw: object) -> list[int]:
    """A short or absent `timeindex` padded to 8 slots, each with ITS sentinel.

    Padding every missing slot with -1 would leave one variable carrying two
    conventions at once — -1 for a slot the file never had, 0 for a milestone
    the operator never marked — and a reader testing either one alone silently
    misses the other half. Pad from Artisan's own reset row instead, so a
    truncated file is indistinguishable from an unmarked one and `marked()`
    is the only test any caller needs.
    """
    try:
        vals = [int(v) for v in raw]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        vals = []
    vals = vals[:8]
    return vals + list(UNMARKED[len(vals):])




# temperature offset from BT probe to actual bean temp
@dataclass
class ProbeDeviationInterval:
    start_min: float = 0.0
    end_min: float = 0.0

# roaster BT deviation settings
@dataclass
class ProbeDeviation:
    probe_id: str
    bt_at_charge : ProbeDeviationInterval
    bt_at_de : ProbeDeviationInterval
    bt_at_fc : ProbeDeviationInterval
    bt_at_drop : ProbeDeviationInterval
    use_roaster_offsets: bool = True



# Neutral green moisture (%). The reference a lot is read against when its own
# moisture was not measured. Shared with the plan model's charge modulation, so
# a single value moves both.
GREEN_MOISTURE_NEUTRAL_PCT: float = 10.5

# Weight loss decomposes: the WATER the lot carried, plus the DRY MATTER burnt
# off. The water is measured (green moisture), so only the dry matter is
# modelled here — and it depends on the DEVELOPMENT as much as on the colour.
# Corpus, n=92: at constant colour, dry-matter loss rises +2.2 points per minute
# of development; development alone explains R^2=0.24 of it against 0.08 for
# colour alone. Keying the band on colour only keys it on the weak variable.
# The chain is: destination (espresso/filter) -> development -> weight loss, so
# the destination never enters here, it enters through the development.
# Anchor: Hoos — light filter, 1:00 development, loss = moisture + 1 to 2 points.
DRY_MATTER_DEV_REF_MIN: float = 1.0
DRY_MATTER_PCT_PER_DEV_MIN: float = 2.2
# Set to the model's own measured residual spread (+/-1.7 points on the corpus):
# below that the flag reports weighing noise, not roasting — on a 300 g batch one
# point of loss is 3 g, the order of the chaff. The target is a bearing, not a
# fine verdict; nothing is flagged inside this tolerance.
WEIGHT_LOSS_TOLERANCE_PCT: float = 1.7

# Dry-matter loss (%) at the reference development, by Agtron category (names
# match AGTRON_SCALES).
DRY_MATTER_LOSS_PCT_BY_CATEGORY: dict[str, float] = {
    "Very Light":     0.6,
    "Light":          1.0,   # Hoos anchor
    "Medium Light":   1.1,
    "Medium":         1.3,
    # Below this line the values are CONVENTION, not measurement: the measured
    # range stops around 51 Agtron, and prolonging the observed colour slope to
    # Vienna/French would produce absurd numbers.
    "Medium Dark":    2.2,
    "Dark":           3.5,
    "Very Dark":      5.0,
    "Extremely Dark": 6.5,
}


class WeightLossTarget(NamedTuple):
    """Prescribed weight loss (%) and the band around it that reads as on-target."""

    target: float
    low:    float
    high:   float


_PLANS_BY_NAME: dict[str, RoasterBasicPlanPerPhase] = {}


def _plan_by_name(category: str) -> RoasterBasicPlanPerPhase | None:
    """Roast-level plan row by name, indexed on first use.

    Built lazily rather than at import time: `ROASTING_BASIC_BASE` is defined
    above but the module is imported from the 1 Hz refresh path, and a linear
    scan per lookup is the kind of cost that has no reason to be there.
    """
    if not _PLANS_BY_NAME:
        _PLANS_BY_NAME.update({p.name: p for p in ROASTING_BASIC_BASE.plans})
    return _PLANS_BY_NAME.get(category)


def weight_loss_target(category: str | None, *,
                       moisture_pct: float = 0.0,
                       dev_time_min: float = 0.0) -> WeightLossTarget | None:
    """Weight loss to aim for: the lot's water, plus the colour's dry matter,
    plus what the development adds to it.

    `moisture_pct` outside [5, 20] counts as not measured and falls back to
    GREEN_MOISTURE_NEUTRAL_PCT; `dev_time_min` <= 0 counts as not known and
    falls back to the roast level's conventional development. Returns None for
    an unknown category.
    """
    if not category:
        return None
    base = DRY_MATTER_LOSS_PCT_BY_CATEGORY.get(category)
    if base is None:
        return None
    water = (moisture_pct if 5.0 <= moisture_pct <= 20.0
             else GREEN_MOISTURE_NEUTRAL_PCT)
    if dev_time_min <= 0.0:
        # Not "no development", but "development not known": fall back to the
        # one this roast level conventionally gets, from the plan's own table.
        # Zeroing the term instead would silently target a 1:00 development for
        # every colour, and under-aim a medium roast by more than a point.
        _plan = _plan_by_name(category)
        dev_time_min = (sum(_plan.development_time) / 2.0 if _plan
                        else DRY_MATTER_DEV_REF_MIN)
    dev_extra = DRY_MATTER_PCT_PER_DEV_MIN * (dev_time_min - DRY_MATTER_DEV_REF_MIN)
    # A development short enough to drive the dry matter negative would mean the
    # bean lost less than its water, which cannot happen.
    target = water + max(0.0, base + dev_extra)
    return WeightLossTarget(target,
                            target - WEIGHT_LOSS_TOLERANCE_PCT,
                            target + WEIGHT_LOSS_TOLERANCE_PCT)


def weight_loss_target_from_plan(plan: dict | None) -> WeightLossTarget | None:
    """`weight_loss_target` read off a generated plan dict.

    Single place where the plan's three keys are named. The plan also publishes
    the rounded figure under "Target Weight Loss", but that string carries
    neither the tolerance band nor the decimals, so the panels recompute from
    the same inputs the printed plan used rather than parsing their own display.
    Returns None on a plan that predates these keys.
    """
    if not plan:
        return None
    def _num(key: str) -> float:
        try:
            return float(plan.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return weight_loss_target(plan.get("Target Agtron"),
                              moisture_pct=_num("Bean Humidity"),
                              dev_time_min=_num("Development Phase (min)"))

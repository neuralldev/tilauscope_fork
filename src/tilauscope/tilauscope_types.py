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
# TiLau 2025

import uuid
import math
import logging
import platform
from dataclasses import dataclass, field
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.dict import DataClassDictMixin
from mashumaro.config import BaseConfig
from PyQt6.QtWidgets import (QApplication, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
                             QFrame, QLabel, QWidget, QPushButton, QSizePolicy)
from PyQt6.QtCore import (Qt, QPropertyAnimation, QTimer, QElapsedTimer, QRectF, QSize,
                          QEvent, pyqtSignal)
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QIcon

_IS_MACOS   = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"

_log = logging.getLogger(__name__)
_IS_LINUX   = platform.system() == "Linux"

class AUCStartEvent:
    CHARGE = 0
    TP = 1
    DRYEND = 2
    FCSTART = 3

@dataclass(frozen=True)
class AgtronRange:
    min_value: float
    max_value: float

@dataclass
class AgtronScale:
    name: str
    agtron_range : AgtronRange
    description : str
    color_map: str

@dataclass
class BrewDialIn(DataClassJSONMixin):
    """One accepted brew dial-in for a bean, keyed by brew method.

    Stores the corrected recipe plus what produced it, so a later brew of the
    same bean reopens on the setting that actually tasted right instead of the
    generic recommendation. One entry per method (latest wins).
    """
    method_id: str = ''
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    # What the engine recommended before the correction. A dial-in is a relative
    # adjustment: storing the base lets the same ratio be re-applied to a different roast of the same bean.
    base_grind_um: int = 0
    base_temp_c: float = 0.0
    base_ratio: float = 0.0       # the N in 1:N before the correction
    dose_g: float = 0.0
    taste: list[str] = field(default_factory=list)   # TasteCode values reported
    diagnosis: str = ''                              # DiagnosisCode value
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    iso_date: str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True


# One measured extraction, kept for analysis — not for reopening. `dial_ins` above
# answers "what setting should I reopen on"; this append-only journal answers "did the last change do anything" (own file: brewlog.json).
@dataclass
class BrewSample(DataClassJSONMixin):
    method_id: str = ''
    iso_date: str = ''
    # ── the cause: what was actually brewed ──
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    dose_g: float = 0.0
    # ── what the engine had recommended before any correction ──
    base_grind_um: int = 0
    base_ratio: float = 0.0
    base_temp_c: float = 0.0
    # ── the target: needed to recompute the gap once the engine has moved on ──
    planned_time_s: int = 0
    planned_water_g: float = 0.0
    # ── the consequence ──
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    # The clean filter signal. Total time is mostly the operator's pour
    # schedule; only the final drain reflects the bed, hence the grind. False when
    # no scale was on the line — never estimated, the gap is left visible.
    drawdown_s: int = 0
    drawdown_valid: bool = False
    # Where the two measurements above came from: "scale" (Acaia) or "manual" (machines
    # with an integrated scale no cup fits over) — a later fit must tell the two populations apart.
    measured_source: str = 'scale'
    # ── the context, without which the two above cannot be compared ──
    agtron: float = 0.0
    days_off_roast: int = -1
    espresso_style: str = ''
    # ── the verdict that justified recording this at all ──
    taste: list[str] = field(default_factory=list)
    diagnosis: str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True


@dataclass
class BrewLog(DataClassJSONMixin):
    """Journal of measured extractions, keyed by GreenBean.uuid.

    Lives in brewlog.json beside beancave.json. Its absence is a normal state:
    nothing depends on it to brew.
    """
    version: int = 1
    entries: dict[str, list[BrewSample]] = field(default_factory=dict)
    class Config(BaseConfig):
        ignore_missing_keys = True


@dataclass
class GreenBean(DataClassJSONMixin):
    name: str = ''
    farm: str = ''
    country: str = ''
    supplier: str = ''
    category: str = ''
    process: str = ''
    crop: int = 0
    density: float = 0.0
    last_humidity: float = 0.0
    water_activity: float = 0.0
    altitude: int = 0
    species: str = ""
    varieties: str = ""
    weight_left: float = 0.0 # input green beans left in stock
    flavour_notes: str = ''
    sca: float = 0.0
    count: int = 0
    weight: float = 0.0 # calculation of total weight roasted from alogs
    # --- Blend Fields ---
    is_blend: bool = False
    bean1_ratio: float = 100.0
    bean2_name: str = ''
    bean2_ratio: float = 0.0
    bean3_name: str = ''
    bean3_ratio: float = 0.0
    blend_notes: str = ''
    tips: str = ''
    # Sack identifiers attached to this bean (labelled bags). Fully
    # optional: an empty list is a normal, permanent state — nothing depends
    # on a sack being registered. weight_left stays the single global stock.
    sacks: list[str] = field(default_factory=list)
    # Storage conditioning for the water-activity advisor (Stockage tab).
    # Language-neutral key: '' (unknown) | 'vacuum' | 'grainpro' | 'ecotact' | 'bocal' | 'toile'.
    # Sealed conditionings suspend the moisture-drift trend (no air exchange).
    conditioning: str = ''
    # Accepted brew dial-ins, one per brew method (latest wins). Optional and
    # additive: an empty list is the normal state for a bean never brewed with taste feedback.
    dial_ins: list[BrewDialIn] = field(default_factory=list)
    uuid:str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True

@dataclass
class ReferenceProfile(DataClassJSONMixin):
    title: str =''
    count: int = 0
    avg_drop_bt: float = 0.0
    avg_weight_loss : float = 0.0
    avg_roast_color : float = 0.0
    avg_total_time_min : float = 0.0
    avg_dtr_pct : float = 0.0

@dataclass
class BeanCaveContainer(DataClassJSONMixin):
    green_beans: list[GreenBean] = field(default_factory=list)
    reference_profiles: list[ReferenceProfile] = field(default_factory=list)
    class Config(BaseConfig):
        ignore_missing_keys = True

GREEN_BEAN_COLUMNS = [
    lambda b: b.name,
    lambda b: b.farm,
    lambda b: b.country,
    lambda b: b.supplier,
    lambda b: b.category,
    lambda b: b.process,
    lambda b: str(b.crop),
    lambda b: f"{b.density:.1f}",
    lambda b: f"{b.last_humidity:.1f}",
    lambda b: f"{b.water_activity:.2f}",
    lambda b: str(b.altitude),
    lambda b: b.species,
    lambda b: b.varieties,
    lambda b: f"{b.weight_left:.1f}",
    lambda b: b.flavour_notes,
    lambda b: f"{b.sca:.1f}",
    lambda b: str(b.count),
    lambda b: f"{b.weight:.1f}",
    lambda b: "Oui" if b.is_blend else "Non",
    lambda b: f"{b.bean1_ratio:.1f}%",
    lambda b: b.bean2_name,
    lambda b: f"{b.bean2_ratio:.1f}%",
    lambda b: b.bean3_name,
    lambda b: f"{b.bean3_ratio:.1f}%",
    lambda b: b.blend_notes,
    lambda b: b.tips,
    lambda b: b.uuid if b.uuid!='' else str(uuid.uuid4()),
]

AGTRON_SCALES: list[AgtronScale] = [
    AgtronScale(
        name="Extremely Dark",
        agtron_range=AgtronRange(0.0, 25.99),
        description="Italian",
        color_map="#2f1202",
    ),
    AgtronScale(
        name="Very Dark",
        agtron_range=AgtronRange(26.0, 34.99),
        description="French",
        color_map="#431902",
    ),
    AgtronScale(
        name="Dark",
        agtron_range=AgtronRange(35.0, 40.99),
        description="Vienna",
        color_map="#3c1601",
    ),
    AgtronScale(
        name="Medium Dark",
        agtron_range=AgtronRange(41.0, 50.99),
        description="Full City",
        color_map="#561f01",
    ),
    AgtronScale(
        name="Medium",
        agtron_range=AgtronRange(51.0, 60.99),
        description="City",
        color_map="#7b3916",
    ),
    AgtronScale(
        name="Medium Light",
        agtron_range=AgtronRange(61.0, 70.99),
        description="American",
        color_map="#863C14",
    ),
    AgtronScale(
        name="Light",
        agtron_range=AgtronRange(71.0, 100.99),
        description="New England",
        color_map="#9d4515",
    ),
    AgtronScale(
        name="Very Light",
        agtron_range=AgtronRange(101.0, 130.0),
        description="Cinnamon",
        color_map="#a14513",
    ),
]

# ── Colour helpers ────────────────────────────────────────────────────────────
# These functions are pure (no Qt dependency) so they can be imported at module
# level in any consumer without triggering Qt initialisation.

# Roast-colour systems whose readings are already on (or aligned to) the Agtron
# Gourmet scale (0-100, higher = lighter) and are used as-is.
# ColorTrack (Probat): SCAA cupping standard (coffeelabequipment.com/SCAA_COFFEE_COLOR.pdf)
# sets Agtron Gourmet=63.0 ↔ ColorTrack=62.0 (within the ±1 document tolerance),
# confirming the two scales are effectively 1:1 around the medium-light reference.
_AGTRON_NATIVE: frozenset[str] = frozenset({"agtron", "colortest", "colortrack", ""})


def to_agtron(value: float, system: str) -> float:
    """SINGLE SOURCE OF TRUTH for converting any roast-colour reading to the
    Agtron Gourmet scale (0-100, higher = lighter). Every TilauScope module that
    needs an Agtron value MUST go through this function so the whole app shares
    one definition.

    Agtron is the only *normalised* roast-level reference, so readings on other
    meters are APPROXIMATED rather than rejected — for roast-level purposes an
    approximation is more useful than no value at all.

    Sources:
      [S-SCAA] SCAA Standard "Roast Level for Cupping" (coffeelabequipment.com/
               SCAA_COFFEE_COLOR.pdf): single-point anchors at the cupping
               reference roast (Agtron Gourmet 63 ± 1).
      [S-TON]  Tonino-App official calibration files (github.com/myTonino/
               Tonino-App, src/scales/*.toni v1.0.24): 13 measured Agtron/
               Tonino pairs bridged through the shared raw-sensor axis.
               OLS linear fit: Tonino → Agtron  (σ ≈ 4 Ag).
      [S-PROB] Probat Colorette product page (probat.com): Colorette scale
               range 0–200.

    ColorTrack [S-SCAA]: CT=62.0 ↔ Ag=63.0 — within SCAA ±1 tolerance, so
    ColorTrack ≈ Agtron Gourmet (same scale, same direction). Listed in
    _AGTRON_NATIVE; value returned as-is.

    Tonino [S-TON]: T-values run lighter-is-higher, same direction as Agtron.
    OLS on 13 pairs from Agtron.toni + Tonino.toni:
      Agtron = 0.777 × T − 16.6   (±4 Ag at 1σ, unbiased)

    Probat Colorette 3b [S-SCAA + S-PROB]: scale 0–200, lighter-is-higher.
    SCAA anchor: Col3b=96.0 ↔ Ag=63.0.  Assuming proportional through origin
    (both read ≈ 0 for carbonised/unroasted green):
      Agtron = 0.656 × Colorette   (single-anchor estimate; ±8 Ag uncertainty)

    Returns 0.0 only when there is genuinely no reading (value <= 0), which
    callers treat as "unknown colour".
    """
    if value <= 0:
        return 0.0
    s = (system or "").strip().lower()
    if s in _AGTRON_NATIVE:
        return value
    if s == "tonino":
        # [S-TON] OLS on 13 Agtron.toni/Tonino.toni calibration pairs.
        return (value * 0.777) - 16.6
    if s == "colorette":
        # [S-SCAA + S-PROB] Colorette 3b, scale 0–200.  Single SCAA anchor
        # (Col3b=96 ↔ Ag=63) + proportional-through-origin assumption.
        return value * 0.656
    return value  # unknown meter → assume already Agtron-comparable


DEFAULT_COLOR_SYSTEM: str = "Agtron"


def resolve_color_system(current: str, ground: float, whole: float,
                         default: str = DEFAULT_COLOR_SYSTEM) -> str:
    """Name the colour scale of a roast that carries a reading but no scale.

    Artisan's colour-system index defaults to 0, and entry 0 is the empty
    string: a profile saved without an explicit choice reads back as
    `color_system: ''`. Every consumer that needs the scale to interpret the
    figure — the dial-in advice, the label — takes that for "no colour
    measured" and refuses a roast that was in fact measured. The TilauScope
    colour fields are Agtron, so the scale is named as soon as a reading
    exists.

    Returns *current* when it is already set, *default* when a reading exists
    without one, and "" when there is genuinely nothing measured.
    """
    cur = (current or "").strip()
    if cur:
        return cur
    if ground > 0 or whole > 0:
        return default
    return ""


def ensure_color_system(qmc: object, default: str = DEFAULT_COLOR_SYSTEM) -> str:
    """Apply :func:`resolve_color_system` to a live Artisan canvas.

    Called right after a colour reading is written to `qmc`, so the scale
    reaches the saved profile with the value it describes. Returns the
    resolved scale name.
    """
    def _num(name: str) -> float:
        try:
            return float(getattr(qmc, name, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    systems = list(getattr(qmc, "color_systems", None) or [])
    try:
        idx = int(getattr(qmc, "color_system_idx", 0) or 0)
    except (TypeError, ValueError):
        idx = 0
    current = systems[idx] if 0 <= idx < len(systems) else ""

    resolved = resolve_color_system(current, _num("ground_color"), _num("whole_color"), default)
    if resolved and resolved != current and resolved in systems:
        qmc.color_system_idx = systems.index(resolved)  # type: ignore[attr-defined]
    return resolved


def get_agtron_color(agtron: float) -> str:
    """Return the grain-colour hex that matches *agtron* on the SCA Gourmet scale.

    The colour is taken directly from AGTRON_SCALES.color_map so the
    annotation always reflects the actual visual colour of the bean.
    Falls back to a neutral grey when the value is out of range (e.g. -1
    sentinel or pre-stabilisation noise).
    """
    for scale in AGTRON_SCALES:
        if scale.agtron_range.min_value <= agtron <= scale.agtron_range.max_value:
            return scale.color_map
    return "#9E9E9E"  # grey — out of range / sensor not ready


def get_roc_color(roc: float) -> str:
    """Return a colour for the Omniflux Rate-of-Color value (Agtron/min).

    The RoC is negative during normal roasting (bean darkens → Agtron drops).
    We work on the magnitude so the palette is direction-independent:

        blue  → slow / stalled   (abs < 1.0)
        green → steady brunissement (1.0 – 3.0)
        gold  → active / fast    (3.0 – 6.0)
        red   → aggressive       (> 6.0)
    """
    abs_roc = abs(roc)
    if abs_roc > 6.0:  return "#FF4500"  # OrangeRed  — aggressive
    if abs_roc > 3.0:  return "#FFD700"  # Gold       — active
    if abs_roc >= 1.0: return "#32CD32"  # LimeGreen  — steady
    return "#00BFFF"                     # DeepSkyBlue — slow / stalled


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
    import numpy as np
    tx = np.asarray(timex, dtype=float)
    if tx.size < 2:
        return 1.0
    d = np.diff(tx)
    d = d[d > 0]
    if d.size == 0:
        return 1.0
    return float(np.clip(np.median(d), 0.25, 10.0))


def find_turning_point_index(bt_input: list, dt: float = 1.0) -> int:
    """Index of the Turning Point = the BT minimum, searched in the early
    window (~15 s .. 2 min 30 after charge). Uses BT, not the RoR minimum:
    the RoR minimum (steepest cooling) occurs BEFORE the turning point."""
    import numpy as np
    bt = np.array([np.nan if b is None else float(b) for b in bt_input], dtype=float) if bt_input else np.array([])
    if bt.size == 0:
        return 0
    lo = min(int(round(15.0 / dt)), bt.size - 1)
    hi = min(int(round(150.0 / dt)), bt.size)
    if hi <= lo:
        hi = bt.size
    if hi <= lo:
        return 0
    seg = bt[lo:hi]
    if np.all(np.isnan(seg)):
        return lo
    return lo + int(np.nanargmin(seg))


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
    import numpy as np
    from scipy.signal import find_peaks

    flicks: list = []
    crashes: list = []

    ror = np.asarray(clean_delta_bt(delta_bt), dtype=float)
    tx  = np.asarray(timex, dtype=float)
    n = ror.size
    if n < 10 or tx.size != n:
        return flicks, crashes

    dt = estimate_ror_dt(tx)
    distance = max(1, int(round(debounce_sec / dt)))

    # Light denoise (~5 s). Prominence already rejects small wiggles, so keep
    # this light to avoid attenuating short real flicks near first crack.
    win = max(1, int(round(5.0 / dt)))
    if win > 1:
        kernel = np.ones(win) / win
        ror_s = np.convolve(ror, kernel, mode='same')
    else:
        ror_s = ror

    # Exclude the post-TP recovery: locate the recovery RoR peak within ~180 s
    # after the (BT-based) turning point, then start detecting a margin later so
    # the recovery peak itself is never mistaken for a flick.
    peak_limit = min(n, tp_index + int(round(180.0 / dt)))
    if 0 <= tp_index < peak_limit:
        rec_idx = tp_index + int(np.argmax(ror_s[tp_index:peak_limit]))
        detect_from_t = tx[rec_idx] + recovery_margin_sec
    else:
        detect_from_t = float(tx[0]) + 120.0

    flick_idx, fprops = find_peaks(ror_s, prominence=prominence, distance=distance)
    crash_idx, cprops = find_peaks(-ror_s, prominence=prominence, distance=distance)

    for k, i in enumerate(flick_idx):
        if tx[i] <= detect_from_t:
            continue
        flicks.append({
            "time":      float(tx[i]),
            "ror_value": round(float(ror_s[i]), 2),
            "severity":  round(float(fprops["prominences"][k]), 2),
            "phase":     which_roast_phase(float(tx[i]), phase_times),
        })
    for k, i in enumerate(crash_idx):
        if tx[i] <= detect_from_t:
            continue
        crashes.append({
            "time":      float(tx[i]),
            "ror_value": round(float(ror_s[i]), 2),
            "severity":  round(float(cprops["prominences"][k]), 2),
            "phase":     which_roast_phase(float(tx[i]), phase_times),
        })
    return flicks, crashes


# dictionnaire de standardisation pour nettoyer les noms de processus courants
standardization_map = {
    # Cible les termes sans les séparateurs pour les rendre plus flexibles
    "Washed Wet": "Washed",
    "Natural - Dry": "Natural",
    "Natural - Wet": "Natural",
    "Washed Process": "Washed",
    "Natural Process": "Natural",
}

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


@dataclass
class MQTTSensor(DataClassDictMixin):
    id: str = ""
    topic: str =""
    command: str = ""
    multiplier: float | None = 1.0
    divider: float | None = 1.0
    # unit of the reading once multiplier/divider are applied: "C", "F", or ""
    # for a non-temperature sensor. Read at acquisition to convert into the
    # unit the application is currently working in. Defaults to "" so sensors
    # stored before this field existed keep their raw value.
    unit: str = ""

@dataclass
class MQTTSensorConfig(DataClassJSONMixin):
    sensors: list[MQTTSensor]

MQTT_SENSORS_KEY = "mqtt/sensors"

# temperature offset from BT probe to actual bean temp
@dataclass
class ProbeDeviationInterval:
    start_min: float = 0.0
    end_min: float = 0.0

# roaster BT deviation settings
@dataclass
class ProbeDeviation(DataClassDictMixin):
    probe_id: str
    bt_at_charge : ProbeDeviationInterval
    bt_at_de : ProbeDeviationInterval
    bt_at_fc : ProbeDeviationInterval
    bt_at_drop : ProbeDeviationInterval
    use_roaster_offsets: bool = True

@dataclass
class RoasterBasicPlanPerPhase:
   # No charge temperature here: charge is owned by _CHARGE_BAND_BY_PROCESS
   # in roast_plan_model (band by process, in measured BT).
   name: str
   heater_cmfc: tuple[float, float, float]
   total_time: tuple[float, float]
   drying_time: tuple[float, float]
   maillard_time: tuple[float, float]
   development_time: tuple[float, float]
   dtr_pct: tuple[float, float]
   drop_temp: tuple[int, int]
   fc_temp:int
   dry_temp:int

@dataclass
class RoasterBasicPlan(DataClassDictMixin):
    plans: list[RoasterBasicPlanPerPhase]

# Base roast-plan table by Agtron category (names match AGTRON_SCALES), before
# any per-roast correction (FIR/NIR light-roast tweak, BT-probe deviation).
# Single source shared by the plan generator (roast_plan_model.py, which
# deep-copies this before applying its corrections) and the BeanCave coach
# (beancave.py, which reads it as-is for post-roast reference ranges) so the
# two never judge a roast against different fundamentals.
ROASTING_BASIC_BASE: RoasterBasicPlan = RoasterBasicPlan(
    plans=[
        RoasterBasicPlanPerPhase(
            name="Very Light",
            heater_cmfc=(0.85, 0.70, 0.50),
            total_time=(7.5, 8.75),
            drying_time=(3.5, 4.0),
            maillard_time=(3.0, 3.5),
            development_time=(1.0, 1.25),
            dtr_pct=(0.13, 0.15),
            drop_temp=(197, 203),
            fc_temp=194,
            dry_temp=153,
        ),
        RoasterBasicPlanPerPhase(
            name="Light",
            heater_cmfc=(0.85, 0.70, 0.50),
            total_time=(8.25, 10.25),
            drying_time=(3.5, 4.5),
            maillard_time=(3.5, 4.0),
            development_time=(1.25, 1.75),
            dtr_pct=(0.15, 0.17),
            drop_temp=(203, 208),
            fc_temp=195,
            dry_temp=155,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium Light",
            heater_cmfc=(0.75, 0.65, 0.45),
            total_time=(9.75, 11.25),
            drying_time=(4.5, 5.0),
            maillard_time=(3.75, 4.25),
            development_time=(1.5, 2.0),
            dtr_pct=(0.16, 0.19),
            drop_temp=(208, 213),
            fc_temp=196,
            dry_temp=158,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium",
            heater_cmfc=(0.75, 0.60, 0.45),
            total_time=(11.0, 12.75),
            drying_time=(4.75, 5.25),
            maillard_time=(4.25, 4.75),
            development_time=(2.0, 2.75),
            dtr_pct=(0.18, 0.22),
            drop_temp=(212, 217),
            fc_temp=198,
            dry_temp=160,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium Dark",
            heater_cmfc=(0.70, 0.60, 0.40),
            total_time=(12.0, 13.5),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(2.5, 3.0),
            dtr_pct=(0.20, 0.23),
            drop_temp=(217, 222),
            fc_temp=200,
            dry_temp=162,
        ),
        RoasterBasicPlanPerPhase(
            name="Dark",
            heater_cmfc=(0.70, 0.60, 0.42),
            total_time=(12.25, 13.75),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(2.75, 3.25),
            dtr_pct=(0.22, 0.24),
            drop_temp=(221, 226),
            fc_temp=202,
            dry_temp=163,
        ),
        RoasterBasicPlanPerPhase(
            name="Very Dark",
            heater_cmfc=(0.72, 0.62, 0.44),
            total_time=(12.5, 14.0),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(3.0, 3.5),
            dtr_pct=(0.23, 0.26),
            drop_temp=(224, 229),
            fc_temp=203,
            dry_temp=164,
        ),
        RoasterBasicPlanPerPhase(
            name="Extremely Dark",
            heater_cmfc=(0.72, 0.62, 0.44),
            total_time=(13.0, 14.5),
            drying_time=(5.0, 5.5),
            maillard_time=(4.75, 5.25),
            development_time=(3.25, 3.75),
            dtr_pct=(0.24, 0.27),
            drop_temp=(228, 236),
            fc_temp=204,
            dry_temp=165,
        ),
    ]
)

# Weight-loss % target window by Agtron category (names match AGTRON_SCALES).
# Coach-only fundamental: the plan generator has no weight-loss table to share,
# so this progression is interpolated on ROASTING_BASIC_BASE's dtr_pct curve
# and validated against the specialty-coffee convention (~12-15% light,
# 18-20%+ dark).
WEIGHT_LOSS_PCT_BY_CATEGORY: dict[str, tuple[float, float]] = {
    "Very Light":     (10.5, 13.0),
    "Light":          (11.5, 14.5),
    "Medium Light":   (13.0, 16.0),
    "Medium":         (14.0, 17.5),
    "Medium Dark":    (15.5, 19.0),
    "Dark":           (16.5, 20.0),
    "Very Dark":      (18.0, 21.5),
    "Extremely Dark": (19.0, 22.5),
}
#
# category = Traditional Wet
# process = Washed / Wet Process
# species = Arabica
# varieties = Bourbon

# Catppuccin Mocha. Single source of colour for every TilauScope
# screen — read a token, never paste a hex literal into a new stylesheet.
# The base stylesheet built on top of these tokens lives in theme_qss.py;
# spec and migration plan in wiki/Theme-QSS-Spec.md.
THEME = {
    # --- surfaces, darkest to lightest ---
    "CRUST": "#11111B",   # deepest inset, behind a surface
    "SURFACE": "#181825", # Mantle — cards, headers, inset panels
    "BG": "#1E1E2E",      # Base — window / dialog background
    "BORDER": "#313244",  # Surface0 — separators, idle borders, button fill
    "SURFACE1": "#45475A",# raised surface, hover fill
    "SURFACE2": "#585B70",# disabled fill, strong border

    # --- text, faintest to brightest ---
    "OVERLAY0": "#6C7086", # disabled text, faint separator
    "OVERLAY1": "#7F849C", # muted glyphs
    "OVERLAY2": "#9399B2", # secondary caption
    "SUBTEXT": "#A6ADC8",  # Subtext0 — captions, units, secondary lines
    "SUBTEXT1": "#BAC2DE", # near-primary text
    "TEXT": "#CDD6F4",     # primary text

    # --- semantic accents ---
    "ACCENT": "#89B4FA",   # Blue — primary action, focus, selection
    "SUCCESS": "#A6E3A1",  # Green — on-target, connected, done
    "WARNING": "#FAB387",  # Peach — drifting, needs attention
    "CRITICAL": "#F38BA8", # Red — out of band, failed, destructive
    "TODAY": "#FAB387",    # Peach — "now" marker on a timeline

    # --- accent variants ---
    "LAVENDER": "#B4BEFE", # selection, focus ring
    "SAPPHIRE": "#74C7EC", # link
    "SKY": "#89DCEB",      # informational
    "TEAL": "#94E2D5",     # measured / sensor values
    "YELLOW": "#F9E2AF",   # attention, pending
    "MAUVE": "#CBA6F7",    # category / accent variant
    "PINK": "#F5C2E7",     # rare accent

    # --- roast-level swatches: the only place these belong ---
    "VERY_LIGHT_ROAST": "#BBE3A1",
    "LIGHT_ROAST": "#A6E3A1",
    "MED_ROAST": "#825E50",
    "DARK_ROAST": "#583121",
    "VERY_DARK_ROAST": "#35190E",
}

def format_batch_label(prefix: str, nr: int, pos: int | None = None) -> str:
    """Render an Artisan batch identity as a display string.

    Mirrors Artisan's convention: ``{prefix}{nr} (pos)``.
    Returns an empty string when ``nr <= 0`` (batch system inactive or
    not yet assigned — the number is assigned by Artisan at DROP).
    """
    if nr is None or nr <= 0:
        return ""
    label = f"{prefix or ''}{int(nr)}"
    if pos:
        label += f" ({int(pos)})"
    return label

import unicodedata
def replace_accents(texte):
    if not texte:
        return ""

    # Normalisation NFKD pour séparer les caractères de leurs accents
    charg_normalise = unicodedata.normalize('NFKD', texte)

    # On ne garde que les caractères qui ne sont pas des "combinaisons" (accents)
    # et on réencode en ASCII en ignorant les erreurs pour plus de sécurité
    return "".join([c for c in charg_normalise if not unicodedata.combining(c)])

# Single place where an exported file (label PDF, roast card, plan) is handed
# over to the OS's own viewer, ensuring it comes up in front: a WindowStaysOnTopHint
# window would otherwise keep the viewer underneath, and re-raising ourselves would push it behind again.

def drop_stay_on_top(window) -> None:
    """Let another application come in front of `window`.

    No-op when the window does not float. setWindowFlag() hides a visible
    window, hence the show(). The hint is not restored: once the export is on
    screen the window has no reason to fight it for the front.
    """
    try:
        if window is None or not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
            return
        was_visible = window.isVisible()
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        if was_visible:
            window.show()
    except Exception as exc:  # noqa: BLE001
        _log.warning("drop_stay_on_top failed: %s", exc)


def open_in_os_viewer(file_path: str, window=None, helpers=()) -> None:
    """Open `file_path` with the OS viewer, in front of `window`.

    `helpers` are floating companion windows (scale readout, colour card …)
    that would otherwise stay above the viewer on their own.
    """
    import os
    import subprocess
    import sys
    drop_stay_on_top(window)
    for helper in helpers:
        drop_stay_on_top(helper)
    try:
        if sys.platform.startswith("win"):
            os.startfile(file_path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", file_path])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", file_path])  # noqa: S603,S607
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to open file %s: %s", file_path, exc)


def show_styled_message(parent, title, text, icon=QMessageBox.Icon.Information, rich=False, width:int= 0, buttons:list[str]=None):
    m = TilauMessageBox(parent, title, text, icon, rich, width, buttons)
    return m.exec() # call message box

class TilauMessageBox(QMessageBox):
    def __init__(self, parent, title, text, icon, rich, width,buttons:list[str]=None):
        # Parent to the caller's window when it is a real visible window: ties
        # activation/modality to that window so TilauScope._safe_raise recognises it (avoids stealing focus).
        _p = parent if (parent is not None and parent.isVisible()) else None
        super().__init__(parent = _p)
        self.setModal(True)
        # No Qt.Tool flag: a Tool window never becomes key/active on macOS, requiring
        # two clicks. A plain frameless dialog takes activation on the first click.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)

        self.setWindowTitle(title)
        self.setText(text)

        if rich:
            self.setTextFormat(Qt.TextFormat.RichText)

        self.setIcon(QMessageBox.Icon.Information if icon is None else icon)


        if buttons is None:
            btn = self.addButton(QMessageBox.StandardButton.Ok)
            self._tilau_ok_button = btn
            btn.setDefault(True)
            btn.setAutoDefault(True)
        else:
            self._clicked_button_index = -1 # Valeur par défaut si fermé autrement
            for index, btn_text in enumerate(buttons):
                pb = self.addButton(btn_text, QMessageBox.ButtonRole.ActionRole)

                # On passe l'index actuel à la fonction qui gère le clic
                pb.clicked.connect(lambda checked, idx=index: self.on_button_clicked(idx))
        QTimer.singleShot(0, self._tilau_grab_focus)

        # 3. Use the stylesheet to force a solid background on the widget
        # We add a margin so the border-radius has "room" to exist inside the window
        self.setStyleSheet(f"""
            QMessageBox {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};

            }}
            QLabel {{
                color: {THEME['TEXT']};
                font-size: 14px;
                padding: 20px;
                background: transparent;
            }}
            QPushButton {{
                background-color: {THEME['ACCENT']};
                color: {THEME['BG']};
                border-radius: 5px;
                font-weight: bold;
                padding: 8px 20px;
                margin: 10px;
            }}
            QPushButton:hover {{
                background-color: {THEME['LAVENDER']};
            }}
        """)

        # Ensure it has a physical size
        self.setMinimumWidth(800 if width == 0 else width)
        self.setMinimumHeight(400)

    def on_button_clicked(self, index):
        # 1. On mémorise l'index du bouton qui a été cliqué
        self._clicked_button_index = index
        # 2. On lance votre animation de fade out
        self.start_fade_out()

    def _tilau_grab_focus(self):
        # Bring the message box to the front and give it activation +
        # button focus so the very first click on OK registers (see __init__).
        self.raise_()
        self.activateWindow()
        try:
            self._tilau_ok_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except (RuntimeError, AttributeError):
            pass

    def start_fade_out(self):
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.close)
        self.fade_anim.start()
        self.conclude_dialog()

    def conclude_dialog(self):
        # done() ferme la boîte de dialogue et fait sauter le verrou du exec()
        # en renvoyant la valeur passée en argument.
        if hasattr(self, '_clicked_button_index'):
            self.done(self._clicked_button_index)
        else:
            self.done(0) # Pour le bouton OK standard par exemple

# ══ TilauProgress — the one progress indicator ══════════════════════════════
# ONE component for every long operation, "the app is working" — painted with
# QPainter (not a styled QProgressBar) so it is identical on macOS and Windows.
# Never means "the roast is progressing" — that keeps its own domain widgets.

_reduce_motion_cache: "bool | None" = None


def _probe_reduce_motion() -> bool:
    """Ask the OS whether the operator has asked for less animation."""
    try:
        if _IS_MACOS:
            from AppKit import NSWorkspace  # noqa: PLC0415  # pylint: disable=import-error
            return bool(NSWorkspace.sharedWorkspace()
                        .accessibilityDisplayShouldReduceMotion())
        if _IS_WINDOWS:
            import ctypes  # noqa: PLC0415
            SPI_GETCLIENTAREAANIMATION = 0x1042
            enabled = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
            return not bool(enabled.value)
    except Exception:                                    # noqa: BLE001
        _log.debug("reduce-motion probe unavailable", exc_info=True)
    return False


def reduce_motion() -> bool:
    """True when the OS accessibility settings ask for reduced animation.

    Probed once and cached: it is a preference that needs a logout to change,
    and it must never be read from inside a paint or a sampling tick.
    """
    global _reduce_motion_cache                          # noqa: PLW0603
    if _reduce_motion_cache is None:
        _reduce_motion_cache = _probe_reduce_motion()
    return _reduce_motion_cache


class TilauProgress(QWidget):
    """Ring or bar progress indicator, in one of five states.

    Deliberately mirrors the part of the ``QProgressBar`` API the app already
    uses (``setRange`` / ``setValue`` / ``setMaximum`` / ``value``), so an
    existing bar is replaced by swapping the constructor.  As with
    ``QProgressBar``, ``setRange(0, 0)`` means indeterminate.
    """

    # shapes
    RING = "ring"
    BAR  = "bar"

    # states
    WAITING = "waiting"   # accepted, not started
    WORKING = "working"   # alive, duration unknown
    FILLING = "filling"   # alive, and it will end
    DONE    = "done"      # finished
    FAILED  = "failed"    # stopped — never auto-dismisses

    dismissed = pyqtSignal()   # DONE has been readable long enough to hide

    _TICK_MS    = 33     # 30 fps
    _SWEEP_MS   = 1400   # one ring revolution
    _SHUTTLE_MS = 1100   # one bar sweep
    _EASE_MS    = 180    # value changes never teleport
    _HOLD_MS    = 1200   # how long DONE stays before `dismissed` fires
    _PULSE_MS   = 1600   # reduced-motion breathing
    _ARC_SPAN   = 90.0   # degrees of the indeterminate arc — flat, no tail

    _GLYPH_MIN_PX = 40   # below this a glyph is a smudge: ring alone
    _MARK_MIN_PX  = 20   # below this the check/bang is a smudge: solid ring

    def __init__(self, shape: str = "ring", size: int = 24,
                 glyph: "str | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._shape = shape
        self._size  = int(size)
        self._glyph = glyph
        self._glyph_pm = None
        self._state = self.WORKING

        self._min = 0
        self._max = 0
        self._raw = 0            # last setValue(), for value()

        self._shown = 0.0        # eased 0..1 actually painted
        self._from  = 0.0
        self._to    = 0.0
        self._ease_at = -1       # ms on _clock when the ease started
        self._hold_token = 0

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self.update)

        if shape == self.BAR:
            self.setFixedHeight(6)
            self.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
            self.setMinimumWidth(80)
        else:
            self.setFixedSize(self._size, self._size)

    # ── Qt-compatible surface (drop-in for the bars being replaced) ─────────
    def setRange(self, lo: int, hi: int) -> None:
        self._min, self._max = int(lo), int(hi)
        if self._max <= self._min:
            self.set_state(self.WORKING)          # QProgressBar convention
        elif self._state in (self.WAITING, self.WORKING):
            self.set_state(self.FILLING)

    def setMaximum(self, hi: int) -> None:
        self.setRange(self._min, hi)

    def setMinimum(self, lo: int) -> None:
        self.setRange(lo, self._max)

    def setValue(self, v: int) -> None:
        """QProgressBar-compatible surface — jumps straight to the value, no
        ease.  This is what a blocking scan loop drives through manual
        ``QApplication.processEvents()`` calls: a step can arrive faster than
        the ease's own duration, so easing here only ever restarts the
        animation before it catches up, and the ring visibly stalls a
        quarter of the way round no matter how far the scan has actually
        gone. A caller fed by a real, separately-paced signal (a worker
        thread reporting one printed line at a time) wants the smoothing and
        should call ``set_value`` directly instead."""
        self._raw = int(v)
        span = self._max - self._min
        if span <= 0:
            return                                 # indeterminate: nothing to fill
        if self._state in (self.WAITING, self.WORKING):
            self._state = self.FILLING
        self.set_value((self._raw - self._min) / float(span), animate=False)

    def value(self) -> int:
        return self._raw

    def maximum(self) -> int:
        return self._max

    # ── native surface ──────────────────────────────────────────────────────
    def set_value(self, frac: float, animate: bool = True) -> None:
        """Set the filled fraction 0..1, eased by default so it never
        teleports when fed at a natural real-time pace. ``animate=False``
        jumps straight there — used by ``setValue()`` for blocking loops."""
        frac = max(0.0, min(1.0, float(frac)))
        if not animate:
            self._from = self._to = self._shown = frac
            self._ease_at = -1
            self._sync_timer()
            self.update()
            return
        if abs(frac - self._to) < 1e-4:
            return
        self._from = self._shown
        self._to   = frac
        self._ease_at = self._clock.elapsed()
        self._sync_timer()
        self.update()

    def set_count(self, done: int, total: int) -> None:
        self.setRange(0, int(total))
        self.setValue(int(done))

    def set_indeterminate(self) -> None:
        self.setRange(0, 0)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self._hold_token += 1
        if state == self.DONE:
            self.set_value(1.0)
            token = self._hold_token
            QTimer.singleShot(
                self._HOLD_MS,
                lambda: self.dismissed.emit() if token == self._hold_token else None)
        elif state == self.WAITING:
            self._from = self._to = self._shown = 0.0
        self._sync_timer()
        self.update()

    def state(self) -> str:
        return self._state

    def succeed(self) -> None:
        self.set_state(self.DONE)

    def fail(self) -> None:
        """Freeze at the last value. Never auto-dismisses — by design."""
        self.set_state(self.FAILED)

    # ── animation bookkeeping ───────────────────────────────────────────────
    def _easing(self) -> bool:
        return (self._ease_at >= 0
                and (self._clock.elapsed() - self._ease_at) < self._EASE_MS)

    def _needs_timer(self) -> bool:
        return self._state == self.WORKING or self._easing()

    def _sync_timer(self) -> None:
        want = self.isVisible() and self._needs_timer()
        if want and not self._timer.isActive():
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event) -> None:                  # noqa: N802
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:                  # noqa: N802
        # A spinner nobody can see must not repaint at 30 fps.
        self._timer.stop()
        super().hideEvent(event)

    # ── painting ────────────────────────────────────────────────────────────
    def _colour(self) -> QColor:
        if self._state == self.DONE:
            return QColor(THEME['SUCCESS'])
        if self._state == self.FAILED:
            return QColor(THEME['CRITICAL'])
        return QColor(THEME['ACCENT'])

    def _current_fraction(self) -> float:
        if self._ease_at < 0:
            self._shown = self._to
            return self._shown
        t = (self._clock.elapsed() - self._ease_at) / float(self._EASE_MS)
        if t >= 1.0:
            self._ease_at = -1
            self._shown = self._to
        else:
            e = 1.0 - pow(1.0 - t, 3)               # ease-out cubic
            self._shown = self._from + (self._to - self._from) * e
        return self._shown

    def paintEvent(self, event) -> None:                 # noqa: N802
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._shape == self.BAR:
                self._paint_bar(painter)
            else:
                self._paint_ring(painter)
            painter.end()
        except Exception:                                # noqa: BLE001
            _log.debug("TilauProgress paint failed", exc_info=True)

    def _paint_ring(self, painter: QPainter) -> None:
        side = min(self.width(), self.height())
        pen_w = max(2.0, side / 8.0)
        inset = pen_w / 2.0 + 1.0
        rect = QRectF(inset, inset, side - 2 * inset, side - 2 * inset)
        frac = self._current_fraction()

        # track
        track = QPen(QColor(THEME['BORDER']), pen_w)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self._state == self.WAITING:
            track.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)

        if self._state == self.WAITING:
            return

        pen = QPen(self._colour(), pen_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        if self._state == self.WORKING:
            if reduce_motion():
                # No rotation: the ring breathes instead.
                phase = (self._clock.elapsed() % self._PULSE_MS) / float(self._PULSE_MS)
                wave = 0.28 + 0.72 * (0.5 - 0.5 * math.cos(2.0 * math.pi * phase))
                col = self._colour()
                col.setAlphaF(wave)
                pen.setColor(col)
                painter.setPen(pen)
                painter.drawArc(rect, 0, 360 * 16)
            else:
                phase = (self._clock.elapsed() % self._SWEEP_MS) / float(self._SWEEP_MS)
                start = 90.0 - 360.0 * phase
                painter.setPen(pen)
                painter.drawArc(rect, int(start * 16), int(-self._ARC_SPAN * 16))
        else:
            painter.setPen(pen)
            span = 360.0 if self._state == self.DONE else 360.0 * frac
            if span > 0.0:
                painter.drawArc(rect, int(90 * 16), int(-span * 16))

        if self._state == self.DONE and side >= self._MARK_MIN_PX:
            self._paint_mark(painter, side, check=True)
        elif self._state == self.FAILED and side >= self._MARK_MIN_PX:
            self._paint_mark(painter, side, check=False)
        elif self._glyph and side >= self._GLYPH_MIN_PX:
            self._paint_glyph(painter, side)

    def _paint_mark(self, painter: QPainter, side: float, check: bool) -> None:
        pen = QPen(self._colour(), max(2.0, side / 9.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        if check:
            path.moveTo(side * 0.30, side * 0.51)
            path.lineTo(side * 0.44, side * 0.65)
            path.lineTo(side * 0.71, side * 0.36)
            painter.drawPath(path)
        else:
            path.moveTo(side * 0.50, side * 0.30)
            path.lineTo(side * 0.50, side * 0.56)
            painter.drawPath(path)
            painter.drawPoint(int(side * 0.50), int(side * 0.69))

    def _paint_glyph(self, painter: QPainter, side: float) -> None:
        px = int(side * 0.42)
        if px < 8:
            return
        if self._glyph_pm is None or self._glyph_pm.width() != px * self._dpr():
            self._glyph_pm = self._render_glyph(px)
        if self._glyph_pm is None:
            return
        x = (side - px) / 2.0
        painter.drawPixmap(QRectF(x, x, px, px), self._glyph_pm,
                           QRectF(self._glyph_pm.rect()))

    def _dpr(self) -> int:
        return max(1, int(round(self.devicePixelRatioF())))

    def _render_glyph(self, px: int):
        try:
            from tilauscope.header_icons import make_icon  # noqa: PLC0415
            hi = px * self._dpr()
            icon = make_icon(self._glyph, THEME['SUBTEXT'], QSize(hi, hi))
            return icon.pixmap(QSize(hi, hi))
        except Exception:                                # noqa: BLE001
            _log.debug("progress glyph unavailable", exc_info=True)
            return None

    def _paint_bar(self, painter: QPainter) -> None:
        w, h = float(self.width()), float(self.height())
        r = h / 2.0
        frac = self._current_fraction()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME['BORDER']))
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        if self._state == self.WAITING:
            return

        painter.setBrush(self._colour())
        if self._state == self.WORKING and not reduce_motion():
            shuttle = w * 0.30
            phase = (self._clock.elapsed() % self._SHUTTLE_MS) / float(self._SHUTTLE_MS)
            x = -shuttle + (w + shuttle) * phase
            painter.setClipPath(self._rounded(w, h, r))
            painter.drawRoundedRect(QRectF(x, 0, shuttle, h), r, r)
        elif self._state == self.WORKING:
            col = self._colour()
            pulse_phase = (self._clock.elapsed() % self._PULSE_MS) / float(self._PULSE_MS)
            col.setAlphaF(0.28 + 0.72 * (0.5 - 0.5 * math.cos(2.0 * math.pi * pulse_phase)))
            painter.setBrush(col)
            painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        else:
            fill = w if self._state == self.DONE else w * frac
            if fill > 0.0:
                painter.drawRoundedRect(QRectF(0, 0, max(fill, h), h), r, r)

    @staticmethod
    def _rounded(w: float, h: float, r: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        return path


class TilauProgressRow(QWidget):
    """Host C — a bar with its count, for a queue the operator can watch.

    Exposes the same ``setRange`` / ``setMaximum`` / ``setValue`` / ``hide`` /
    ``show`` surface as the QProgressBar it replaces, so existing call sites
    keep working, and writes the count as '3 of 5' rather than a bare
    percentage.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        self.progress = TilauProgress(TilauProgress.BAR, parent=self)
        lay.addWidget(self.progress, 1)

        self.count = QLabel("", self)
        self.count.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:10px; font-family:'JetBrains Mono';"
            f" background:transparent; border:none;")
        lay.addWidget(self.count)

    def _refresh(self) -> None:
        total = self.progress.maximum()
        if total > 0:
            self.count.setText(
                QApplication.translate("tilauscope", "{0} of {1}").format(
                    self.progress.value(), total))
        else:
            self.count.setText("")

    def setRange(self, lo: int, hi: int) -> None:         # noqa: N802
        self.progress.setRange(lo, hi)
        self._refresh()

    def setMaximum(self, hi: int) -> None:                # noqa: N802
        self.progress.setMaximum(hi)
        self._refresh()

    def setValue(self, v: int) -> None:                   # noqa: N802
        self.progress.setValue(v)
        self._refresh()

    def value(self) -> int:
        return self.progress.value()

    def maximum(self) -> int:
        return self.progress.maximum()

    def set_state(self, state: str) -> None:
        self.progress.set_state(state)


class TilauProgressPill(QWidget):
    """Host A — non-modal status pill, anchored bottom-right of its parent.

    For work the operator starts and then ignores.  The window stays usable,
    which makes this the ONLY progress form allowed while a roast is running:
    nothing may steal focus with 250 g and ten minutes on the line.
    """

    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget, text: str = "",
                 glyph: "str | None" = None, cancellable: bool = True) -> None:
        super().__init__(parent)
        self._margin_r = 16
        self._margin_b = 16
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:14px;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(8)

        # 20 px, not 16: below _MARK_MIN_PX the ✓ and ✕ are not painted. `glyph` is under
        # TilauProgress._GLYPH_MIN_PX (40) here, so it is never painted — only TilauProgressDialog (ring 64) is above threshold.
        self.progress = TilauProgress(TilauProgress.RING, 20, glyph, self)
        self.progress.dismissed.connect(self._fade_out)
        lay.addWidget(self.progress)

        self.label = QLabel(text, self)
        self.label.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:11px; "
            f" background:transparent; border:none;")
        lay.addWidget(self.label)

        self.count = QLabel("", self)
        self.count.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px; font-family:'JetBrains Mono';"
            f" background:transparent; border:none;")
        lay.addWidget(self.count)

        self.btn_cancel = QPushButton("✕", self)
        self.btn_cancel.setFixedSize(18, 18)
        self.btn_cancel.setProperty('variant', 'icon')   # fixed size: no base padding
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setToolTip(QApplication.translate("tilauscope", "Cancel"))
        self.btn_cancel.setStyleSheet(
            f"QPushButton {{ color:{THEME['SUBTEXT']}; background:transparent;"
            f" border:none; font-size:11px; }}"
            f"QPushButton:hover {{ color:{THEME['CRITICAL']}; }}")
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self.btn_cancel.setVisible(cancellable)
        lay.addWidget(self.btn_cancel)

        parent.installEventFilter(self)
        self.place()

    # ── placement ───────────────────────────────────────────────────────────
    def set_margin(self, right: int, bottom: int) -> None:
        """Lift the pill clear of the local furniture (a size grip, a button row)."""
        self._margin_r, self._margin_b = int(right), int(bottom)
        self.place()

    def place(self) -> None:
        self.adjustSize()
        p = self.parentWidget()
        if p is None:
            return
        self.move(max(0, p.width() - self.width() - self._margin_r),
                  max(0, p.height() - self.height() - self._margin_b))
        self.raise_()

    def eventFilter(self, obj, event) -> bool:           # noqa: N802
        if obj is self.parentWidget() and event.type() in (
                QEvent.Type.Resize, QEvent.Type.Show):
            self.place()
        return super().eventFilter(obj, event)

    # ── state, forwarded to the shared painter ──────────────────────────────
    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.place()

    def set_step(self, done: int, total: int) -> None:
        """Update the counter text only — for runs whose ring is driven finer
        than one step at a time (a printer reports line by line)."""
        self.count.setText(
            QApplication.translate("tilauscope", "{0} of {1}").format(done, total))
        self.place()

    def set_count(self, done: int, total: int) -> None:
        self.set_step(done, total)
        self.progress.set_count(done, total)

    def succeed(self, text: "str | None" = None) -> None:
        if text:
            self.label.setText(text)
        self.count.setText("")
        self.btn_cancel.setVisible(False)
        self.progress.succeed()
        self.place()

    def fail(self, text: str) -> None:
        """Never auto-dismisses: the operator has to read the gesture."""
        self.label.setText(text)
        self.label.setStyleSheet(
            f"color:{THEME['CRITICAL']}; font-size:11px; "
            f" background:transparent; border:none;")
        self.count.setText("")
        # The work is over: ✕ now means "I have read this", never "cancel".
        # Leaving it wired to `cancelled` would call back into a dead worker.
        try:
            self.btn_cancel.clicked.disconnect()
        except TypeError:
            pass
        self.btn_cancel.clicked.connect(self._fade_out)
        self.btn_cancel.setToolTip(QApplication.translate("tilauscope", "Dismiss"))
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setText("✕")
        self.progress.fail()
        self.place()

    def _fade_out(self) -> None:
        self.hide()
        self.deleteLater()


def print_progress_pill(parent: QWidget, total: int,
                        on_cancel=None) -> TilauProgressPill:
    """Host A wired for one Niimbot run — the single entry point for printing.

    ``total`` is the number of labels the run will put out.  A single label has
    nothing to count and nothing to interrupt: the ring just sweeps.  A batch
    counts, and offers ✕ when the caller can honour it — which on a printer
    means "stop after the label currently coming out", never "undo".
    """
    pill = TilauProgressPill(
        parent,
        "🖨  " + QApplication.translate("tilauscope", "Printing…"),
        cancellable=(total > 1 and on_cancel is not None))
    if total > 1:
        pill.progress.set_count(0, total)
        pill.set_step(0, total)
        if on_cancel is not None:
            pill.cancelled.connect(on_cancel)
            pill.btn_cancel.setToolTip(QApplication.translate(
                "tilauscope", "Stop after the label being printed"))
    else:
        # Nothing to count: sweep rather than show a ring frozen at zero.
        # A caller that does have finer progress may switch it to determinate.
        pill.progress.set_indeterminate()
    pill.show()
    return pill


def set_button_busy(button: QPushButton, busy: bool,
                    text: "str | None" = None,
                    glyph: "str | None" = None) -> None:
    """Host D — turn a button's own icon slot into a ring while it works.

    For actions between roughly 0.4 s and 2 s: Generate, Print, Connect.
    The button keeps its exact width, so nothing on the screen moves.

    `glyph` is accepted for signature symmetry with the other hosts and is
    never painted: the ring is 16 px, well under
    TilauProgress._GLYPH_MIN_PX (40). Do not pass one expecting it to show.
    """
    spinner = getattr(button, "_tilau_busy", None)
    if busy:
        if spinner is None:
            spinner = TilauProgress(TilauProgress.RING, 16, glyph, button)
            button._tilau_busy = spinner                 # noqa: SLF001
            button._tilau_text = button.text()           # noqa: SLF001
            button._tilau_icon = button.icon()           # noqa: SLF001
        button.setIcon(QIcon())
        if text:
            button.setText(text)
        spinner.set_indeterminate()
        spinner.move(max(6, (button.height() - 16) // 2),
                     max(0, (button.height() - 16) // 2))
        spinner.show()
        button.setEnabled(False)
    elif spinner is not None:
        spinner.hide()
        spinner.deleteLater()
        button._tilau_busy = None                        # noqa: SLF001
        button.setText(getattr(button, "_tilau_text", button.text()))
        button.setIcon(getattr(button, "_tilau_icon", QIcon()))
        button.setEnabled(True)


class TilauProgressDialog(QDialog):
    """Host B — modal progress, for work that must not be interrupted.

    ApplicationModal on purpose, NOT WindowModal: on macOS a WindowModal
    QDialog is rendered as a sheet, and closing one programmatically just
    before opening another dialog can leave the parent window unclickable —
    the failure already seen after Niimbot printing.
    """

    def __init__(self, message: str, parent=None, maxvalue: "int | None" = None,
                 glyph: "str | None" = None, hint: str = "") -> None:
        super().__init__(parent)
        # imported here, not at module level: theme_qss reads THEME
        # from this module, so a top-level import is a cycle that only happens
        # to work when tilauscope_types is imported first.
        from tilauscope.theme_qss import apply_tilau_theme  # noqa: PLC0415
        # frameless translucent window: ground=False. The grounded base emits
        # QDialog { background-color }, which paints the whole rectangle opaque
        # and squares off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setup_ui(message, maxvalue, glyph, hint)
        self.resize(400, 210)

    def setup_ui(self, message, maxvalue, glyph=None, hint="") -> None:
        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 20px;
            }}
        """)
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(30, 26, 30, 26)
        self.content_layout.setSpacing(14)
        self.main_layout.addWidget(self.container)

        # the ring carries the motion, so the message doesn't have to shout
        self.pbar = TilauProgress(TilauProgress.RING, 64, glyph, self)
        # maxvalue None -> indeterminate.
        self.pbar.setRange(0, 0 if maxvalue is None else int(maxvalue))

        self.msg_label = QLabel(message.upper())
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setStyleSheet(
            f"color:{THEME['TEXT']}; font-weight:bold; font-size:12px;"
            f" border:none; background:transparent;")

        self.hint_label = QLabel(hint)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setVisible(bool(hint))
        self.hint_label.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px;"
            f" border:none; background:transparent;")

        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        ring_row.addWidget(self.pbar)
        ring_row.addStretch(1)

        self.content_layout.addLayout(ring_row)
        self.content_layout.addWidget(self.msg_label)
        self.content_layout.addWidget(self.hint_label)

    def set_count(self, done: int, total: int) -> None:
        """Show '47 of 312' under the message — never a bare percentage."""
        self.hint_label.setText(
            QApplication.translate("tilauscope", "{0} of {1}").format(done, total))
        self.hint_label.setVisible(True)
        self.pbar.set_count(done, total)

    # ── QProgressDialog-compatible surface ──────────────────────────────────
    # Lets the raw QProgressDialog call sites migrate by swapping the
    # constructor alone, without rewriting the loops around them.
    def setValue(self, v: int) -> None:                  # noqa: N802
        self.pbar.setValue(v)
        total = self.pbar.maximum()
        if total > 0:
            self.hint_label.setText(
                QApplication.translate("tilauscope", "{0} of {1}").format(v, total))
            self.hint_label.setVisible(True)

    def wasCanceled(self) -> bool:                       # noqa: N802
        """Always False — as with the dialogs this replaces, which were built
        with no cancel button. Work that must not be interrupted has no
        cancel affordance; cancellable work belongs in a pill instead."""
        return False

# ── Milestone temperature windows (DE / FC) ─────────────────────────────────
# Profession-standard milestone bands in the *true* bean frame (before per-roaster
# sensor offset). Resolution: (1) plan target >0 -> point (offset already applied
# by the plan); (2) else profession band + roaster per-phase BT offset
# (displayed = true + offset); offset 0 -> raw profession default.
PROFESSION_DE_TRUE_C: tuple[float, float] = (158.0, 163.0)
PROFESSION_FC_TRUE_C: tuple[float, float] = (195.0, 200.0)
_MILESTONE_HALF_C: float = 5.0


def resolve_milestone_window(plan_target_c: float, true_band_c: tuple[float, float],
                             sensor_offset_c: float = 0.0,
                             half_c: float = _MILESTONE_HALF_C
                             ) -> tuple[float, float, float, float]:
    """Returns (gate_lo, gate_hi, band_lo, band_hi) in the displayed BT frame."""
    if plan_target_c and plan_target_c > 0.0:
        band_lo = band_hi = float(plan_target_c)
    else:
        band_lo = float(true_band_c[0]) + float(sensor_offset_c)
        band_hi = float(true_band_c[1]) + float(sensor_offset_c)
    return band_lo - half_c, band_hi + half_c, band_lo, band_hi


def resolve_de_window(plan_target_c: float, bt_dry_offset_c: float = 0.0,
                      half_c: float = _MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_DE_TRUE_C, bt_dry_offset_c, half_c)


def resolve_fc_window(plan_target_c: float, bt_fc_offset_c: float = 0.0,
                      half_c: float = _MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_FC_TRUE_C, bt_fc_offset_c, half_c)
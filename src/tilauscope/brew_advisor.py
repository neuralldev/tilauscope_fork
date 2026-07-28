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
# -*- coding: utf-8 -*-

# ── SCIENTIFIC SOURCES ────────────────────────────────────────────────────
# The recipe heuristics below are anchored on peer-reviewed work, not on
# common web/barista lore. Key references used while coding this module:
#
# [S1] Batali, Frost, Lebrilla, Guinard, Ristenpart (2020). "Brew temperature,
#      at fixed brew strength and extraction, has little impact on the sensory
#      profile of drip brew coffee." Scientific Reports 10, 16450.
#      https://www.nature.com/articles/s41598-020-73341-4
#      → Once TDS and extraction yield (EY) are fixed, brew temperature has
#        little sensory effect. Grind / time / ratio (which set TDS & EY) are
#        the real levers. Temperature is kept only as a COARSE anchor by roast
#        level; fine per-modifier °C tweaks are deliberately NOT applied.
#
# [S2] Cameron, Morisco, Hempel, ... Hendon (2020). "Systematically Improving
#      Espresso: Insights from Mathematical Modeling and Experiment."
#      Matter 2(3), 631-648. https://doi.org/10.1016/j.matt.2019.12.019
#      → EY-vs-grind is NON-monotonic in espresso: too fine causes channeling /
#        clogging, lowering EY and reproducibility. Even saturation (pre-
#        infusion) matters. Grind heuristics stay conservative.
#
# [S3] Hendon, Colonna-Dashwood & Colonna-Dashwood (2014). "The Role of
#      Dissolved Cations in Coffee Extraction." J. Agric. Food Chem. 62(21).
#      https://doi.org/10.1021/jf501687c
#      → It is the TYPE of hardness that matters: bicarbonate (KH / alkalinity)
#        buffers acids and mutes flavour; Ca/Mg hardness (GH) raises extraction.
#        GH and KH are therefore treated on SEPARATE axes (see _mod_water).
#
# [S4] Degassing & rest windows. Wang & Lim (2014), "Effect of roasting
#      conditions on CO2 degassing behavior in coffee", Food Res. Int.
#      https://doi.org/10.1016/j.foodres.2014.01.061 ; time-resolved gravimetric
#      method, J. Agric. Food Chem. (2017) https://doi.org/10.1021/acs.jafc.7b03310 ;
#      post-roast maturation (2025) https://doi.org/10.1007/s00217-025-04873-0 ;
#      post-roast rest sensory study (≥8 d peak for 73% of coffees).
#      → Residual CO2 is positively correlated with roast lightness; release
#        rate rises with roast degree — a light roast degasses ~3x SLOWER than a
#        dark one. So darker roasts are brew-ready sooner AND stale sooner
#        (shorter window); lighter roasts are ready later and hold longer. The
#        rest window is therefore roast-coupled on BOTH ends (see degassing_band)
#        and shifted later for pressure brewing, which is more CO2-sensitive.
#
# [S5] Luther / Artisan project — "Understanding Roast Color" (2023).
#      https://artisan-roasterscope.blogspot.com/2023/03/understanding-roast-color.html
#      → Roast-colour scales are device-dependent with no validated linear
#        conversion between them (e.g. a 10 pt Agtron step ≈ 16 pt Tonino).
#        Agtron is nonetheless the only *normalised* roast-level reference, so
#        other meters are APPROXIMATED (not rejected) by the single shared
#        converter tilauscope_types.to_agtron — flagged there as empirical.
#
# [S6] Guinard et al. (2023). "A new Coffee Brewing Control Chart..." J. Food
#      Sci. 88(4). https://doi.org/10.1111/1750-3841.16531
#      → The classic 18-22% "golden cup" window is a convention, not a law;
#        EY targets are presented as guidance only.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Single shared roast-colour → Agtron converter (re-exported for callers that
# already import it from here, e.g. roast_timeline).
from tilauscope.tilauscope_types import to_agtron  # noqa: F401
## TILAU ## Water activity is judged in ONE place. The Storage tab owns the aw
## doctrine (and lets the operator move its thresholds), so the brew advisor
## reads the same zones rather than keeping a second, hardcoded opinion — a bean
## must not be "optimal" in one tab and "high moisture" in another. Both modules
## are pure and Qt-free; the operator's thresholds are resolved at the extraction
## boundary and travel in on BrewInput.
from tilauscope.storage_advisor import (
    DEFAULT_THRESHOLDS, AwZone, StorageThresholds, classify_aw)


# ── Enumerations ──────────────────────────────────────────────────────────
class BrewFamily(Enum):
    PRESSURE = "pressure"
    PERCOLATION = "percolation"
    IMMERSION = "immersion"
    HYBRID = "hybrid"
    NO_BYPASS = "no_bypass"


class WaterProfile(Enum):
    AUTO = "auto"
    SCA = "sca"
    SOFT = "soft"
    HARD = "hard"


class Severity(Enum):
    INFO = "info"
    GOOD = "good"
    WARN = "warn"
    CRIT = "crit"


class PIType(Enum):
    NONE = "none"
    PASSIVE = "passive"
    LINE = "line"
    PROGRAMMABLE = "prog"
    LOW_FLOW = "low_flow"
    MANUAL = "manual"


class EspressoStyle(Enum):
    ## TILAU ## Two legitimate schools for pulling a roast-appropriate ratio.
    ## CLASSIC keeps the grind the roast asks for and lets the shot run as long
    ## as the ratio needs (a light roast reaches 1:3 in ~42 s). TURBO fixes the
    ## shot at ~25 s and opens the grind to get the flow, which by construction
    ## lands on nearly the same grind for every roast — in turbo the roast is
    ## expressed by the ratio alone. Neither is wrong; they are different drinks.
    CLASSIC = "classic"
    TURBO = "turbo"


ESPRESSO_STYLE_ORDER: tuple[EspressoStyle, ...] = (EspressoStyle.CLASSIC, EspressoStyle.TURBO)
_TURBO_TARGET_S: int = 25


class EspressoMachine(Enum):
    E61 = "e61"
    HX = "hx"
    DUAL_BOILER = "dual_boiler"
    LA_MARZOCCO = "la_marzocco"
    SLAYER = "slayer"
    LEVER_MANUAL = "lever_manual"
    FLOW_PROFILER = "flow_profiler"
    BASIC = "basic"
    OTHER = "other"


class AgitationCode(Enum):
    NONE_PUCK = "none_puck"
    PULSE = "pulse"
    CRUST = "crust"
    STIR = "stir"
    SPIN = "spin"
    VORTEX = "vortex"
    NONE_PREHEAT = "none_preheat"
    HIGH_DENSE = "high_dense"      # modifier override (dense high-altitude)
    REDUCED_UNEVEN = "reduced"     # modifier override (high spread)


class GrindCat(Enum):
    ULTRA_FINE = "ultra_fine"
    FINE = "fine"
    MEDIUM_FINE = "medium_fine"
    MEDIUM = "medium"
    MEDIUM_COARSE = "medium_coarse"
    COARSE = "coarse"
    EXTRA_COARSE = "extra_coarse"


class NoteCode(Enum):
    DENSITY_VERY_HIGH = "density_very_high"
    DENSITY_HIGH = "density_high"
    DENSITY_LOW = "density_low"
    WL_HIGH = "wl_high"
    WL_LOW = "wl_low"
    DEV_SHORT = "dev_short"
    DEV_LONG = "dev_long"
    ORIGIN_HIGH = "origin_high"
    ORIGIN_LOW = "origin_low"
    WATER_GH_HIGH = "water_gh_high"
    WATER_GH_LOW = "water_gh_low"
    WATER_KH_HIGH = "water_kh_high"
    WATER_KH_LOW = "water_kh_low"
    WATER_SCA = "water_sca"
    REST_FRESH = "rest_fresh"
    REST_OPTIMAL = "rest_optimal"
    REST_NEARPEAK = "rest_nearpeak"
    REST_STALE = "rest_stale"
    MOISTURE_AW_DRY = "moisture_aw_dry"
    MOISTURE_AW_WATCH = "moisture_aw_watch"
    MOISTURE_AW_RISK = "moisture_aw_risk"
    MOISTURE_GREEN_HIGH = "moisture_green_high"
    SPREAD_HIGH = "spread_high"
    SPREAD_EXCELLENT = "spread_excellent"
    RATIO_OFFSET = "ratio_offset"
    TURBO = "turbo"
    CAPACITY = "capacity"
    BASKET = "basket"
    AI_ADJUSTED = "ai_adjusted"


Note = tuple[Severity, NoteCode, dict]


# ── Machine specs ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EspressoMachineSpec:
    id: EspressoMachine
    pi_type: PIType
    supports_low_flow: bool       # independent low-flow "pre-brew" phase
    supports_pre_wet: bool        # explicit low-pressure puck soak
    needs_manual_preheat: bool    # group too cold without a manual warm-up
    needs_cooling_flush: bool     # HX: flush to drop brew temp before shot


ESPRESSO_MACHINES: dict[EspressoMachine, EspressoMachineSpec] = {
    EspressoMachine.E61:           EspressoMachineSpec(EspressoMachine.E61,           PIType.PASSIVE,      False, False, False, False),
    EspressoMachine.HX:            EspressoMachineSpec(EspressoMachine.HX,            PIType.PASSIVE,      False, False, False, True),
    EspressoMachine.DUAL_BOILER:   EspressoMachineSpec(EspressoMachine.DUAL_BOILER,   PIType.PROGRAMMABLE, True,  True,  False, False),
    EspressoMachine.LA_MARZOCCO:   EspressoMachineSpec(EspressoMachine.LA_MARZOCCO,   PIType.LINE,         False, True,  False, False),
    EspressoMachine.SLAYER:        EspressoMachineSpec(EspressoMachine.SLAYER,        PIType.LOW_FLOW,     True,  True,  False, False),
    EspressoMachine.LEVER_MANUAL:  EspressoMachineSpec(EspressoMachine.LEVER_MANUAL,  PIType.MANUAL,       True,  True,  True,  False),
    EspressoMachine.FLOW_PROFILER: EspressoMachineSpec(EspressoMachine.FLOW_PROFILER, PIType.MANUAL,       True,  True,  False, False),
    EspressoMachine.BASIC:         EspressoMachineSpec(EspressoMachine.BASIC,         PIType.NONE,         False, False, True,  False),
    EspressoMachine.OTHER:         EspressoMachineSpec(EspressoMachine.OTHER,         PIType.PROGRAMMABLE, False, False, False, False),
}

ESPRESSO_MACHINE_ORDER: tuple[EspressoMachine, ...] = (
    EspressoMachine.E61, EspressoMachine.HX, EspressoMachine.DUAL_BOILER,
    EspressoMachine.LA_MARZOCCO, EspressoMachine.SLAYER, EspressoMachine.LEVER_MANUAL,
    EspressoMachine.FLOW_PROFILER, EspressoMachine.BASIC, EspressoMachine.OTHER,
)


# ── I/O dataclasses ───────────────────────────────────────────────────────
@dataclass
class BrewInput:
    ground_color: float = 0.0
    whole_color: float = 0.0
    color_system: str = "Agtron"
    weight_loss: float = 0.0
    density: float = 0.0
    water_activity: float = 0.0
    green_moisture: float = 0.0
    dev_ratio: float = 0.0
    dev_time_s: int = 0
    process: str = ""
    country: str = ""
    altitude: int = 0
    variety: str = ""
    species: str = ""
    days_off_roast: int = -1
    water_profile: WaterProfile = WaterProfile.AUTO
    water_gh_ppm: float = 0.0
    water_kh_ppm: float = 0.0
    espresso_machine: EspressoMachine = EspressoMachine.OTHER
    espresso_style: EspressoStyle = EspressoStyle.CLASSIC
    ## TILAU ## The operator's own storage thresholds, resolved at the boundary.
    ## Defaults match the Storage tab's defaults, so an engine used without a UI
    ## still judges aw the same way.
    aw_thresholds: StorageThresholds = DEFAULT_THRESHOLDS


@dataclass
class PourStep:
    label_key: str            # i18n key resolved by the dialog
    at_s: int
    target_g: float
    params: dict = field(default_factory=dict)


@dataclass
class EspressoProfile:
    machine: EspressoMachine
    pi_type: PIType
    pi_seconds: int
    ## TILAU ## Pre-infusion is two physically distinct moments on any machine
    ## where the operator holds it: water flows in until the puck is saturated
    ## (WET), then flow stops and the puck sits while pressure equalises and CO2
    ## escapes (DWELL). They were reported as one number, which asked a La
    ## Marzocco or E61 owner to guess where the paddle or the lever should move.
    ## The two ALWAYS sum to pi_seconds, so the shot clock is unchanged.
    pi_wet_s: int
    pi_dwell_s: int
    pre_brew_seconds: int     # 0 => no independent low-flow pre-brew
    pre_wet: bool
    needs_manual_preheat: bool
    needs_cooling_flush: bool


@dataclass
class RecipeDelta:
    temp: float = 0.0
    grind_mult: float = 1.0
    ratio: float = 0.0
    agitation: Optional[AgitationCode] = None
    notes: list[Note] = field(default_factory=list)


@dataclass
class BrewRecipe:
    method_id: str
    family: BrewFamily
    roast_key: str            # RoastLevel.key (translated by dialog)
    agtron: float
    dose_g: float
    ratio_str: str
    water_g: float
    water_is_yield: bool
    temp_c: float
    grind_um: int
    grind_cat: GrindCat
    agitation: AgitationCode
    bloom_g: float = 0.0
    bloom_s: int = 0
    steps: list[PourStep] = field(default_factory=list)
    total_time_s: int = 0
    target_ey: str = ""
    tds_hint_key: str = ""
    espresso: Optional[EspressoProfile] = None
    notes: list[Note] = field(default_factory=list)
    ai_adjusted: bool = False
    dialed_in: bool = False       # this bean's own saved dial-in is folded in
    setup_adjusted: bool = False  # no bean dial-in; the learned setup offset is


# ── Roast levels (Agtron anchors, descending) ─────────────────────────────
@dataclass(frozen=True)
class RoastLevel:
    key: str
    min_agtron: float
    delta_t: float
    grind_mult: float
    ratio: float              # filter ratio DELTA off the method anchor
    pi_base_s: int            # espresso pre-infusion baseline seconds
    ## TILAU ## Espresso carries an ABSOLUTE ratio, not a delta off 1:2. A light
    ## roast is dense and poorly soluble and needs a long shot to reach a decent
    ## yield; a dark roast is highly soluble and releases its bitterness early,
    ## so it must be cut short. That is the whole distance between a Nordic long
    ## shot and an Italian ristretto — and the ratio was previously pinned at
    ## 1:2.0 for every roast, the only ratio lever in the module that never moved.
    esp_ratio: float = 2.0


ROAST_LEVELS: tuple[RoastLevel, ...] = (
    RoastLevel("EXTREMELY_LIGHT", 95, +4.0, 0.80, +1.5, 8, 3.0),
    RoastLevel("VERY_LIGHT",      85, +3.0, 0.86, +1.0, 7, 2.7),
    RoastLevel("LIGHT",           75, +1.5, 0.92, +0.5, 6, 2.4),
    RoastLevel("MEDIUM_LIGHT",    65,  0.0, 1.00,  0.0, 5, 2.0),   # anchor: 1:2.0 / 28 s
    RoastLevel("MEDIUM",          55, -1.5, 1.08, -0.5, 4, 1.9),
    RoastLevel("MEDIUM_DARK",     45, -3.0, 1.18, -1.0, 3, 1.7),
    RoastLevel("DARK",             0, -7.0, 1.35, -2.0, 2, 1.5),
)


# ── Method anchors (reference = MEDIUM_LIGHT) ─────────────────────────────
@dataclass(frozen=True)
class MethodAnchor:
    id: str
    family: BrewFamily
    ratio: float
    temp_c: float
    grind_um: int
    agitation: AgitationCode
    default_dose: int
    bloom_factor: float
    bloom_s: int
    total_time_s: int
    water_is_yield: bool
    target_ey: str
    tds_hint_key: str = ""


METHOD_ANCHORS: dict[str, MethodAnchor] = {
    "ESPRESSO":     MethodAnchor("ESPRESSO",     BrewFamily.PRESSURE,    2.0, 92.0, 285, AgitationCode.NONE_PUCK,    18, 0.0, 0,  28,  True,  "19-22%", "tds_espresso"),
    "V60":          MethodAnchor("V60",          BrewFamily.PERCOLATION, 16.0, 92.0, 650, AgitationCode.PULSE,        15, 2.5, 45, 180, False, "19-22%"),
    "FRENCH_PRESS": MethodAnchor("FRENCH_PRESS", BrewFamily.IMMERSION,   15.0, 94.0, 950, AgitationCode.CRUST,        30, 0.0, 0,  480, False, "18-21%"),
    "AEROPRESS":    MethodAnchor("AEROPRESS",    BrewFamily.HYBRID,      15.0, 88.0, 450, AgitationCode.STIR,         15, 0.0, 0,  120, False, "19-22%"),
    "PULSAR":       MethodAnchor("PULSAR",       BrewFamily.HYBRID,      17.0, 92.0, 800, AgitationCode.SPIN,         20, 3.0, 45, 255, False, "20-22%"),
    "WEBER_BIRD":   MethodAnchor("WEBER_BIRD",   BrewFamily.NO_BYPASS,   15.0, 92.0, 480, AgitationCode.VORTEX,       20, 0.0, 0,  240, False, "20-23%"),
    "MOKA":         MethodAnchor("MOKA",         BrewFamily.PRESSURE,    10.0, 95.0, 420, AgitationCode.NONE_PREHEAT, 18, 0.0, 0,  240, False, "—",      "tds_moka"),
}

METHOD_ORDER: tuple[str, ...] = (
    "ESPRESSO", "V60", "FRENCH_PRESS", "AEROPRESS", "PULSAR", "WEBER_BIRD", "MOKA",
)

# Pressurised extraction phase of a shot, AFTER any pre-brew / pre-infusion
# lead-in. Calibrated so the reference case reproduces the METHOD_ANCHORS
# espresso total exactly: MEDIUM_LIGHT has pi_base_s = 5, and 5 + 23 = 28 s.
# (The old hardcoded "full pressure at 8 s" matched no reference at all — 8 s is
# the EXTREMELY_LIGHT pre-infusion.) Machines with a real low-flow lead-in now
# get a shot long enough to contain it.
_ESPRESSO_PULL_S: int = 23


# ── Helpers ───────────────────────────────────────────────────────────────
# Neutral fallback when no reliable Agtron value is available: the reference
# level (MEDIUM_LIGHT, all deltas = 0), not the darkest one.
_REFERENCE_LEVEL_KEY = "MEDIUM_LIGHT"


def select_level(agtron: float) -> RoastLevel:
    # Unknown / untrusted colour → neutral reference recipe, not the darkest.
    if agtron <= 0:
        return next(l for l in ROAST_LEVELS if l.key == _REFERENCE_LEVEL_KEY)
    for lvl in ROAST_LEVELS:
        if agtron >= lvl.min_agtron:
            return lvl
    return ROAST_LEVELS[-1]


def grind_cat(um: int) -> GrindCat:
    if um < 200:
        return GrindCat.ULTRA_FINE
    if um < 320:
        return GrindCat.FINE
    if um < 520:
        return GrindCat.MEDIUM_FINE
    if um < 720:
        return GrindCat.MEDIUM
    if um < 900:
        return GrindCat.MEDIUM_COARSE
    if um < 1100:
        return GrindCat.COARSE
    return GrindCat.EXTRA_COARSE


# ── Degassing / rest window (single source of truth) ──────────────────────
# Shared by the Brew Advisor (_mod_rest, _espresso_profile) AND the Brew
# Planning timeline, so the two never disagree. [S4]: bands are roast-coupled
# on both ends (dark = ready sooner, stales sooner; light = ready later, holds
# longer). Day values are deliberately COARSE — the science gives ranges, and
# actual peak depends on bean and packaging.
@dataclass(frozen=True)
class DegassingBand:
    key: str            # identity + THEME colour key for the timeline
    min_agtron: float   # inclusive lower bound (bands listed lightest-first)
    ready_day: int      # first brew-ready day (degassing stabilised)
    peak_day: int       # best day to drink (centre of the sensory peak)
    peak_end_day: int   # last day of the peak window before oxidative staling


# peak_day is anchored on the sensory literature: most specialty coffees peak
# 7-10 days off roast and 73% of coffees peak at >=8 days (post-roast rest study
# [S4]); darker roasts degas faster and peak earlier, lighter/nordic later. The
# progression stays COARSE (5/8/11/14) — the science gives ranges, not a day.
DEGASSING_BANDS: tuple[DegassingBand, ...] = (
    DegassingBand("VERY_LIGHT_ROAST", 90, 7, 14, 30),   # Agtron >= 90
    DegassingBand("LIGHT_ROAST",      70, 5, 11, 25),   # 70-90
    DegassingBand("MED_ROAST",        45, 3,  8, 18),   # 45-70
    DegassingBand("DARK_ROAST",        0, 2,  5, 14),   # < 45
)
# Pressure brewing (espresso/moka) tolerates residual CO2 poorly → rest longer.
PRESSURE_REST_SHIFT_DAYS: int = 3
# Oxidative tail after the peak window: still drinkable ("near peak"), but no
# longer at its best. Staling here is gradual, not a cliff — the science gives a
# soft decline, so we keep a generous, COARSE grace band before "clearly stale".
NEAR_PEAK_TAIL_DAYS: int = 14


def degassing_band(agtron: float) -> DegassingBand:
    """Return the degassing band for an Agtron value. Unknown colour (<=0)
    falls back to the neutral medium band, never the darkest."""
    if agtron <= 0:
        return next(b for b in DEGASSING_BANDS if b.key == "MED_ROAST")
    for b in DEGASSING_BANDS:
        if agtron >= b.min_agtron:
            return b
    return DEGASSING_BANDS[-1]


# ── Rest status (single interpretation of the degassing bands) ─────────────
# The bands above give the NUMBERS; this gives their READING. Every surface that
# talks about freshness — the Brew Advisor recipe notes, the espresso pre-
# infusion, the startup "brew-ready" toast — must go through here so they can
# never disagree on whether a given day is fresh / optimal / near-peak / stale.
class RestStatus(Enum):
    FRESH = "fresh"          # still degassing, extraction unstable
    OPTIMAL = "optimal"      # inside the peak window
    NEAR_PEAK = "near_peak"  # past peak but still good (oxidative tail)
    STALE = "stale"          # clearly oxidised, irreversibly flat


@dataclass(frozen=True)
class RestWindow:
    status: RestStatus
    ready_day: int       # effective (family-shifted) first brew-ready day
    peak_day: int        # effective best day to drink
    peak_end_day: int    # effective last day of the peak window
    tail_end_day: int    # last near-peak day before "clearly stale"
    days_off: int


def rest_window(agtron: float, days_off: int,
                family: Optional["BrewFamily"] = None) -> RestWindow:
    """Classify how rested a roast is, from its colour and age. Optional brew
    family applies the pressure rest shift ([S4]); pass None for a method-
    agnostic reading (used by the timeline and the startup toast). days_off < 0
    (unknown) is treated as FRESH so callers can simply skip it."""
    band = degassing_band(agtron)
    shift = _rest_shift(family) if family is not None else 0
    ready = band.ready_day + shift
    peak = band.peak_day + shift
    peak_end = band.peak_end_day + shift
    tail_end = peak_end + NEAR_PEAK_TAIL_DAYS
    if days_off < 0 or days_off < ready:
        status = RestStatus.FRESH
    elif days_off <= peak_end:
        status = RestStatus.OPTIMAL
    elif days_off <= tail_end:
        status = RestStatus.NEAR_PEAK
    else:
        status = RestStatus.STALE
    return RestWindow(status, ready, peak, peak_end, tail_end, days_off)


# ── Taste feedback → diagnosis (pure) ─────────────────────────────────────
# Sour and bitter are NOT two ends of one axis: they are distinct failure modes
# that can co-occur, and the most common mistake is to treat them as a single
# slider. "Sour → grind finer" is exactly backwards when the brew also ran slow,
# because slow+sour means water channelled through the bed instead of extracting
# it. The measured time is therefore part of the diagnosis, not decoration — it
# is what separates a genuine under-extraction from uneven extraction.
class TasteCode(Enum):
    SOUR = "sour"
    BITTER = "bitter"
    HARSH = "harsh"        # astringent / drying
    THIN = "thin"          # weak body, watery
    BALANCED = "balanced"


class DiagnosisCode(Enum):
    UNDER_FAST = "under_fast"          # sour + fast  → grind finer
    UNDER_ON_TIME = "under_on_time"    # sour at time → hotter / more agitation
    UNDER_NO_TIME = "under_no_time"    # sour, timing unknown → primary lever
    OVER_SLOW = "over_slow"            # bitter + slow → grind coarser
    OVER_ON_TIME = "over_on_time"      # bitter at time → coarser
    OVER_NO_TIME = "over_no_time"      # bitter, timing unknown → primary lever
    CHANNELING = "channeling"          # sour + slow  → technique, NOT grind
    CHANNELING_FINES = "chan_fines"    # bitter + fast → technique / fines
    UNEVEN = "uneven"                  # sour AND bitter → uneven extraction
    ASTRINGENT = "astringent"          # harsh → over-extracted / too hot
    WEAK_BODY = "weak_body"            # thin → tighten the ratio
    STALE = "stale"                    # the bean explains it; do not chase it
    BALANCED = "balanced"              # lock it in
    NO_SIGNAL = "no_signal"            # nothing actionable reported


@dataclass(frozen=True)
class BrewCorrection:
    grind_mult: float = 1.0
    ratio_delta: float = 0.0
    temp_delta: float = 0.0

    @property
    def is_empty(self) -> bool:
        return (abs(self.grind_mult - 1.0) < 1e-6
                and abs(self.ratio_delta) < 1e-6 and abs(self.temp_delta) < 1e-6)


@dataclass(frozen=True)
class BrewDiagnosis:
    code: DiagnosisCode
    correction: BrewCorrection
    actionable: bool          # False → advice only, nothing to apply
    used_time: bool           # False → diagnosed on taste alone (no scale)


# One grinder "step" is ~6 %; corrections are capped so a bad cup can never
# swing the recipe wildly. Dial-in converges by iterating, not by jumping.
_GRIND_STEP: float = 0.06
_TIME_FAST: float = 0.85      # measured / planned below this = ran fast
_TIME_SLOW: float = 1.15      # above this = ran slow
## TILAU ## A ratio step has to match the scale of the ratio it acts on, not the
## family: filter lives around 1:16 where one useful step is a whole point,
## espresso around 1:2 where that would be a different drink, and moka is
## pressure-family yet brews at 1:10. Sizing the step proportionally makes "one
## notch less water" mean the same THING in the cup at every ratio — and at 6 %
## it lands on the traditional 1.0 filter step on its own.
_RATIO_STEP_PCT: float = 0.06


def ratio_step(current_ratio: float) -> float:
    """One dial-in notch of ratio, sized for the ratio in play."""
    if current_ratio <= 0:
        return _RATIO_STEP_PCT * 16.0   # filter-ish fallback when unknown
    return round(current_ratio * _RATIO_STEP_PCT, 2)


def ratio_floor(family: Optional[BrewFamily]) -> float:
    """Lowest ratio a correction may drive to. 1:4 is already extreme for
    filter; for espresso it would be a long black."""
    return 1.2 if family == BrewFamily.PRESSURE else 4.0


def diagnose(tastes: set[TasteCode], planned_time_s: int, measured_time_s: int,
             rest_status: Optional[RestStatus] = None,
             family: Optional[BrewFamily] = None,
             current_ratio: float = 0.0) -> BrewDiagnosis:
    """Turn reported taste + measured time into a diagnosis and a bounded fix.

    Order matters: staling and uneven extraction are checked BEFORE the
    under/over-extraction ladder, because both would otherwise be mis-read as a
    grind problem and "corrected" in a direction that makes the cup worse.
    """
    none_ = BrewCorrection()
    # A stale bean explains the cup on its own. Staling is oxidative and
    # irreversible ([S4]) — chasing it with grind is chasing a ghost.
    if rest_status == RestStatus.STALE:
        return BrewDiagnosis(DiagnosisCode.STALE, none_, False, measured_time_s > 0)
    if TasteCode.BALANCED in tastes:
        return BrewDiagnosis(DiagnosisCode.BALANCED, none_, False, measured_time_s > 0)

    sour = TasteCode.SOUR in tastes
    bitter = TasteCode.BITTER in tastes
    harsh = TasteCode.HARSH in tastes
    thin = TasteCode.THIN in tastes
    if not (sour or bitter or harsh or thin):
        return BrewDiagnosis(DiagnosisCode.NO_SIGNAL, none_, False, measured_time_s > 0)

    # Sour AND bitter together is the signature of uneven extraction: part of
    # the bed over-extracted while part under-extracted. No single grind size
    # fixes it — only distribution does.
    if sour and bitter:
        return BrewDiagnosis(DiagnosisCode.UNEVEN, none_, False, measured_time_s > 0)

    used_time = planned_time_s > 0 and measured_time_s > 0
    ratio = (measured_time_s / planned_time_s) if used_time else 1.0
    fast = used_time and ratio < _TIME_FAST
    slow = used_time and ratio > _TIME_SLOW

    if sour:
        if not used_time:
            # No measurement: "not fast and not slow" is absence of data, not
            # evidence of good timing. Fall back to the primary lever rather
            # than to the on-time branch, and say the timing is unknown.
            return BrewDiagnosis(DiagnosisCode.UNDER_NO_TIME,
                                 BrewCorrection(grind_mult=1.0 - _GRIND_STEP), True, False)
        if slow:
            # Slow AND sour: the water had time but did not extract — it found a
            # path. Finer would tighten the bed and worsen the channel.
            return BrewDiagnosis(DiagnosisCode.CHANNELING, none_, False, True)
        if fast:
            return BrewDiagnosis(DiagnosisCode.UNDER_FAST,
                                 BrewCorrection(grind_mult=1.0 - _GRIND_STEP), True, True)
        # On time but sour: grind is roughly right, push extraction another way.
        return BrewDiagnosis(DiagnosisCode.UNDER_ON_TIME,
                             BrewCorrection(temp_delta=+1.0), True, used_time)
    if bitter:
        if not used_time:
            return BrewDiagnosis(DiagnosisCode.OVER_NO_TIME,
                                 BrewCorrection(grind_mult=1.0 + _GRIND_STEP), True, False)
        if fast:
            # Fast AND bitter: fines/channelling over-extracting locally.
            return BrewDiagnosis(DiagnosisCode.CHANNELING_FINES, none_, False, True)
        return BrewDiagnosis(DiagnosisCode.OVER_SLOW if slow else DiagnosisCode.OVER_ON_TIME,
                             BrewCorrection(grind_mult=1.0 + _GRIND_STEP), True, used_time)
    if harsh:
        return BrewDiagnosis(DiagnosisCode.ASTRINGENT,
                             BrewCorrection(grind_mult=1.0 + _GRIND_STEP, temp_delta=-1.0),
                             True, used_time)
    # thin: body is the ratio's job, not the grind's.
    return BrewDiagnosis(DiagnosisCode.WEAK_BODY,
                         BrewCorrection(ratio_delta=-ratio_step(current_ratio)), True, used_time)


# ── Cross-bean setup offset (pure) ────────────────────────────────────────
# If every bean needs the same correction in the same direction, that is not a
# property of the beans — it is a property of the setup. Deliberately NOT called
# a "grinder offset": what is actually measured is the systematic gap between
# the engine's recommendation and what this particular kitchen produces, which
# also carries the palate, the water and the technique. Attributing it to the
# grinder alone would be an overclaim.
_OFFSET_MIN_SAMPLES: int = 4      # below this, a median is just noise
_OFFSET_MIN_AGREEMENT: float = 0.75   # share that must point the same way
_OFFSET_MIN_EFFECT: float = 0.03  # under 3 %, not worth acting on
_OFFSET_MAX: float = 0.15         # never shift a fresh recipe by more than this


def learn_setup_offset(ratios: list[float]) -> Optional[float]:
    """Median grind multiplier across per-bean dial-ins, or None if untrustworthy.

    Each ratio is one accepted correction expressed as corrected/recommended.
    Three guards keep this from learning noise: enough samples, agreement on the
    DIRECTION (a median alone would happily average two beans pulling opposite
    ways into a confident-looking number), and a large enough effect to matter.
    """
    vals = sorted(r for r in ratios if r > 0)
    if len(vals) < _OFFSET_MIN_SAMPLES:
        return None
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    if abs(median - 1.0) < _OFFSET_MIN_EFFECT:
        return None
    # Do the corrections agree on a direction, or do they merely average to one?
    same = sum(1 for r in vals if (r > 1.0) == (median > 1.0))
    if same / n < _OFFSET_MIN_AGREEMENT:
        return None
    return max(1.0 - _OFFSET_MAX, min(1.0 + _OFFSET_MAX, median))


# ── Modifiers (pure) ──────────────────────────────────────────────────────
def _mod_density(inp: BrewInput) -> RecipeDelta:
    d = inp.density
    if d <= 0:
        return RecipeDelta()
    if d > 780:
        return RecipeDelta(grind_mult=1.06, notes=[(Severity.INFO, NoteCode.DENSITY_VERY_HIGH, {})])
    if d > 750:
        return RecipeDelta(grind_mult=1.04, notes=[(Severity.INFO, NoteCode.DENSITY_HIGH, {})])
    if d < 650:
        return RecipeDelta(grind_mult=0.95, notes=[(Severity.INFO, NoteCode.DENSITY_LOW, {})])
    return RecipeDelta()


def _mod_weight_loss(inp: BrewInput) -> RecipeDelta:
    # Roast/organic loss correlates with development but is confounded with
    # bean moisture, and per [S1] brew temperature is a weak lever at fixed EY.
    # We therefore only FLAG weight-loss extremes; no °C tweak is applied.
    wl = inp.weight_loss
    if wl <= 0:
        return RecipeDelta()
    if wl > 16.0:
        return RecipeDelta(notes=[(Severity.WARN, NoteCode.WL_HIGH, {})])
    if wl < 12.0:
        return RecipeDelta(notes=[(Severity.WARN, NoteCode.WL_LOW, {})])
    return RecipeDelta()


# Plausibility band for a development ratio. A real drum roast lands well
# inside it; a value outside means the phase breakdown was partial rather than
# that the roast was extreme — BeanCave computes dev/(dry+mid+dev), so an alog
# with dry and Maillard missing yields a nonsensical DTR of 100 %. Outside the
# band we fall back to absolute development time instead of reading a data
# artifact as a roasting fact.
_DTR_MIN: float = 0.01
_DTR_MAX: float = 0.50


def _norm_dtr(v: float) -> float:
    """Development ratio as a 0-1 fraction, or 0 when it is not trustworthy.

    Both conventions exist in the codebase (BrewInput.dev_ratio is a fraction
    from BeanCave, canvas dev_pct is a percentage), so anything above 1 is read
    as a percentage.
    """
    if v <= 0:
        return 0.0
    dtr = min(v / 100.0, 1.0) if v > 1.0 else v
    return dtr if _DTR_MIN <= dtr <= _DTR_MAX else 0.0


def _mod_development(inp: BrewInput) -> RecipeDelta:
    # DTR is preferred over absolute development seconds: 60 s of development
    # means something very different on a 6-minute roast than on a 14-minute
    # one, and the ratio is what the roast side already reasons in. Typical
    # specialty DTR sits at 18-22%; outside 15-25% the cup skews and the ratio
    # is the lever that balances it. Absolute time remains the fallback when the
    # phase breakdown is unavailable.
    # Ratio/agitation are the real levers ([S1]); the prior +0.5 °C on short
    # development is dropped as below-perception false precision.
    dtr = _norm_dtr(inp.dev_ratio)
    if dtr > 0:
        if dtr < 0.15:
            return RecipeDelta(ratio=+1.0, notes=[(Severity.INFO, NoteCode.DEV_SHORT, {})])
        if dtr > 0.25:
            return RecipeDelta(ratio=-0.5, notes=[(Severity.INFO, NoteCode.DEV_LONG, {})])
        return RecipeDelta()
    t = inp.dev_time_s
    if t <= 0:
        return RecipeDelta()
    if t < 60:
        return RecipeDelta(ratio=+1.0, notes=[(Severity.INFO, NoteCode.DEV_SHORT, {})])
    if t > 150:
        return RecipeDelta(ratio=-0.5, notes=[(Severity.INFO, NoteCode.DEV_LONG, {})])
    return RecipeDelta()


def _mod_origin(inp: BrewInput) -> RecipeDelta:
    # Density is the real mechanism (high-altitude beans are denser/harder).
    # Altitude is already a measured input, so we drive off it directly and no
    # longer guess from a hard-coded country list (crude + stereotyping).
    if inp.altitude > 1800:
        return RecipeDelta(ratio=+0.5, agitation=AgitationCode.HIGH_DENSE,
                           notes=[(Severity.INFO, NoteCode.ORIGIN_HIGH, {})])
    if 0 < inp.altitude < 1100:
        return RecipeDelta(ratio=-1.0, notes=[(Severity.INFO, NoteCode.ORIGIN_LOW, {})])
    return RecipeDelta()


def _resolve_gh_kh(inp: BrewInput) -> tuple[float, float]:
    """Return (GH, KH) in ppm as CaCO3, deriving representative values from the
    coarse WaterProfile enum when explicit measurements are absent. SCA target
    is GH ~68 / KH ~40 mg/L CaCO3."""
    gh, kh = inp.water_gh_ppm, inp.water_kh_ppm
    if gh > 0 or kh > 0:
        return gh, kh
    wp = inp.water_profile
    if wp == WaterProfile.HARD:
        return 150.0, 100.0
    if wp == WaterProfile.SOFT:
        return 25.0, 15.0
    return 68.0, 40.0  # SCA / AUTO with no measurement


def _mod_water(inp: BrewInput) -> RecipeDelta:
    # [S3] Hendon et al.: it is the TYPE of hardness that matters, not a single
    # "hard/soft" axis. GH (Ca/Mg) raises extraction; KH (bicarbonate) buffers
    # acids and mutes flavour. They are handled independently, and — per [S1] —
    # without any °C tweak (the prior ±0.5 °C is dropped).
    # When the user gave no water info at all (AUTO + no measurement), make no
    # claim rather than asserting a balanced SCA profile we cannot know.
    if inp.water_profile == WaterProfile.AUTO and inp.water_gh_ppm <= 0 and inp.water_kh_ppm <= 0:
        return RecipeDelta()
    gh, kh = _resolve_gh_kh(inp)
    notes: list[Note] = []
    grind = 1.0
    balanced = True

    # GH → extraction: high GH over-extracts (coarsen), low GH under-extracts.
    if gh > 100.0:
        grind *= 1.02
        notes.append((Severity.WARN, NoteCode.WATER_GH_HIGH, {}))
        balanced = False
    elif 0 < gh < 40.0:
        grind *= 0.98
        notes.append((Severity.INFO, NoteCode.WATER_GH_LOW, {}))
        balanced = False

    # KH → buffering/flavour clarity (sensory, not an extraction lever).
    if kh > 70.0:
        notes.append((Severity.WARN, NoteCode.WATER_KH_HIGH, {}))
        balanced = False
    elif 0 < kh < 25.0:
        notes.append((Severity.INFO, NoteCode.WATER_KH_LOW, {}))
        balanced = False

    if balanced:
        notes.append((Severity.GOOD, NoteCode.WATER_SCA, {}))
    return RecipeDelta(grind_mult=grind, notes=notes)


def _rest_shift(family: BrewFamily) -> int:
    # [S4] Pressure brewing is more CO2-sensitive → the window opens & closes
    # a few days later for espresso/moka.
    return PRESSURE_REST_SHIFT_DAYS if family == BrewFamily.PRESSURE else 0


_REST_NOTE = {
    RestStatus.OPTIMAL:   (Severity.GOOD, NoteCode.REST_OPTIMAL),
    RestStatus.NEAR_PEAK: (Severity.INFO, NoteCode.REST_NEARPEAK),
    RestStatus.STALE:     (Severity.WARN, NoteCode.REST_STALE),
}


def _mod_rest(inp: BrewInput, family: BrewFamily, agtron: float) -> RecipeDelta:
    # [S4] Roast- and method-coupled degassing window, read from the shared
    # rest_window (single source of truth). Staling is oxidative and largely
    # IRREVERSIBLE — flagged only, never "recovered" by a finer/hotter brew.
    d = inp.days_off_roast
    if d < 0:
        return RecipeDelta()
    win = rest_window(agtron, d, family)
    if win.status == RestStatus.FRESH:
        gm = 1.03 if family == BrewFamily.PRESSURE else 1.0
        return RecipeDelta(grind_mult=gm, notes=[(Severity.WARN, NoteCode.REST_FRESH, {"d": d})])
    sev, code = _REST_NOTE[win.status]
    return RecipeDelta(notes=[(sev, code, {"d": d})])


def _mod_moisture(inp: BrewInput) -> RecipeDelta:
    ## TILAU ## Zones come from the Storage advisor, thresholds included, so the
    ## same bean cannot read "optimal" in the Storage tab and "high moisture"
    ## here. OPTIMAL and UNKNOWN say nothing worth a line in the recipe.
    notes: list[Note] = []
    aw = round(inp.water_activity, 2)
    zone = classify_aw(inp.water_activity, inp.aw_thresholds)
    if zone == AwZone.TOO_DRY:
        notes.append((Severity.INFO, NoteCode.MOISTURE_AW_DRY, {"aw": aw}))
    elif zone == AwZone.WATCH:
        notes.append((Severity.INFO, NoteCode.MOISTURE_AW_WATCH, {"aw": aw}))
    elif zone == AwZone.MOLD_RISK:
        notes.append((Severity.WARN, NoteCode.MOISTURE_AW_RISK, {"aw": aw}))
    if inp.green_moisture > 12.5:
        notes.append((Severity.INFO, NoteCode.MOISTURE_GREEN_HIGH, {"m": round(inp.green_moisture, 1)}))
    return RecipeDelta(notes=notes)


# ── Espresso machine profile ──────────────────────────────────────────────
## TILAU ## Seconds of low-pressure flow needed per gram of dry coffee to
## saturate the puck. Wetting is a FILL: a deeper basket holds more, so it takes
## proportionally longer. Calibrated on the common case (18 g → 3 s) because that
## is the only point anyone has a feel for; the slope itself is a convention
## awaiting data, like _POUR_FLOW_THRESHOLD (wiki/Brew-DialIn-Feedback-Spec.md §6).
_PI_WET_S_PER_G: float = 0.17


def _espresso_profile(level: RoastLevel, days_off: int, agtron: float,
                      spec: EspressoMachineSpec, dose_g: float = 18.0) -> EspressoProfile:
    pi_s = level.pi_base_s
    # Use the same roast/method-coupled freshness window as _mod_rest ([S4]) so a
    # still-degassing puck gets longer saturation. Espresso is pressure brewing,
    # hence the pressure rest shift.
    if days_off >= 0:
        win = rest_window(agtron, days_off, BrewFamily.PRESSURE)
        if win.status == RestStatus.FRESH:
            pi_s += 3        # heavy degassing → longer saturation
        elif win.status == RestStatus.STALE:
            pi_s = max(1, pi_s - 1)
    pi_s = max(1, min(30, pi_s))

    pre_brew = 0
    if spec.supports_low_flow:
        # Extended low-flow window (Slayer/profiler/lever/DB-flow).
        pre_brew = max(12, min(45, pi_s * 3))

    ## TILAU ## Wetting scales with the dose it has to soak; the dwell absorbs
    ## everything left over — including, deliberately, the whole freshness bonus
    ## added above. A puck that is still degassing needs to SIT longer, not to be
    ## filled longer: letting the +3 s inflate the wetting would push more water
    ## through a puck that has not yet stopped moving, which is what the bonus
    ## exists to avoid. Wetting is capped by the total so the dwell never goes
    ## negative; when nothing is left the dwell step is simply not shown.
    pi_wet = max(1, min(pi_s, int(round(_PI_WET_S_PER_G * max(0.0, dose_g)))))
    pi_dwell = max(0, pi_s - pi_wet)

    return EspressoProfile(
        machine=spec.id, pi_type=spec.pi_type, pi_seconds=pi_s,
        pi_wet_s=pi_wet, pi_dwell_s=pi_dwell,
        pre_brew_seconds=pre_brew, pre_wet=spec.supports_pre_wet,
        needs_manual_preheat=spec.needs_manual_preheat,
        needs_cooling_flush=spec.needs_cooling_flush,
    )


# ── Pour-plan builders (per family) ───────────────────────────────────────
## TILAU ## Roughly what the largest common model of each brewer holds, in g of
## water — and for espresso, of dose, since the basket is what limits a shot.
## The dose selector goes to 60 g, which asks an AeroPress for 930 g of water.
## These only WARN: someone may own a bigger brewer than the common one, so the
## recipe is still produced rather than clamped to a size nobody asked for.
_BREWER_CAPACITY_G: dict[str, float] = {
    "V60": 700.0,           # 02 holds ~500, 03 ~900
    "AEROPRESS": 250.0,     # chamber
    "FRENCH_PRESS": 1000.0,
    "PULSAR": 500.0,
    "WEBER_BIRD": 500.0,
    "MOKA": 300.0,          # a 6-cup pot
}
_MAX_BASKET_G: float = 25.0

## TILAU ## What a pour can actually deliver, in g/s. A gooseneck onto a cone
## bed pours ~3-4 g/s before it starts digging; a flat no-bypass bed (Pulsar)
## tolerates a much faster single add because there is no cone wall to erode.
_POUR_RATE_CONE: float = 3.5
_POUR_RATE_FLAT: float = 6.0
_POUR_RATE_VESSEL: float = 8.0   # kettle into a vessel: no bed to protect
_MIN_DRAWDOWN_S: int = 45     # a bed still has to drain after the last pour


def planned_pour_rate(rec: BrewRecipe) -> float:
    """The pour rate this recipe's schedule was built around, in g/s.

    Lives beside the constants that build the steps so the flow axis and the
    schedule can never drift apart. Pressure brewing is not poured at all — the
    machine sets the flow — so it reports its own typical range.
    """
    if rec.family == BrewFamily.PRESSURE:
        return 2.0
    if rec.method_id == "PULSAR":
        return _POUR_RATE_FLAT
    if rec.bloom_g > 0:
        return _POUR_RATE_CONE
    return _POUR_RATE_VESSEL


def _pour_seconds(grams: float, rate: float) -> int:
    """Seconds a pour of this size needs, rounded up, with a floor so a small
    pour still reads as a deliberate action rather than an instant."""
    if grams <= 0:
        return 0
    return max(10, -(-int(grams * 100) // int(rate * 100)))


def _build_steps(rec: BrewRecipe) -> list[PourStep]:
    fam = rec.family
    total = rec.water_g
    tt = rec.total_time_s

    if rec.method_id == "ESPRESSO":
        # The shot clock accumulates across the phases the machine profile
        # actually declares. Previously every lead-in step sat at 0:00 with full
        # pressure hardcoded at 0:08, which made a 24 s low-flow pre-brew claim
        # to finish inside an 8 s window.
        ep = rec.espresso
        steps: list[PourStep] = []
        # Prep, before the shot clock starts.
        if ep and ep.needs_cooling_flush:
            steps.append(PourStep("step_es_flush", 0, 0))
        if ep and ep.needs_manual_preheat:
            steps.append(PourStep("step_es_preheat", 0, 0))
        t = 0
        ## TILAU ## The generic "pre-wet" line is exactly the wetting phase the
        ## split below now describes properly — with a duration and a gesture.
        ## Kept only where that split does not happen, otherwise the plan showed
        ## two steps for one action, both stamped 0:00.
        _held = ep is not None and ep.pi_type in (PIType.LINE, PIType.PASSIVE,
                                                  PIType.MANUAL) and ep.pi_dwell_s > 0
        if ep and ep.pre_wet and not _held:
            steps.append(PourStep("step_es_prewet", t, 0))
        if ep and ep.pre_brew_seconds:
            steps.append(PourStep("step_es_prebrew", t, 0, {"s": ep.pre_brew_seconds}))
            t += ep.pre_brew_seconds
        if ep:
            ## TILAU ## Where the operator holds the pre-infusion himself, the two
            ## phases are two different gestures and are named as such. Where the
            ## machine runs it (programmable, low-flow needle, or none at all)
            ## there is no gesture to decompose: one line, one number to set.
            if _held:
                suffix = "_lever" if ep.pi_type in (PIType.PASSIVE, PIType.MANUAL) else "_line"
                steps.append(PourStep("step_es_pi_wet" + suffix, t, 0, {"s": ep.pi_wet_s}))
                t += ep.pi_wet_s
                steps.append(PourStep("step_es_pi_dwell" + suffix, t, 0, {"s": ep.pi_dwell_s}))
                t += ep.pi_dwell_s
            else:
                steps.append(PourStep("step_es_pi", t, 0, {"s": ep.pi_seconds}))
                t += ep.pi_seconds
        # Same logic: a machine the operator holds needs telling to let go.
        if _held:
            steps.append(PourStep(
                "step_es_full_lever" if ep.pi_type in (PIType.PASSIVE, PIType.MANUAL)
                else "step_es_full_line", t, 0))
        else:
            steps.append(PourStep("step_es_full", t, 0))
        steps.append(PourStep("step_es_stop", max(tt, t + 1), total, {"g": total}))
        return steps

    if rec.method_id == "MOKA":
        return [
            PourStep("step_moka_fill", 0, 0),
            PourStep("step_moka_grounds", 30, 0),
            PourStep("step_moka_heat", 60, 0),
            PourStep("step_moka_gurgle", tt, total, {"g": total}),
        ]
    ## TILAU ## Filling a vessel is still a pour. The step after the fill is what
    ## the live corridor treats as "all the water should be in by now", so
    ## hardcoding it (10 s on the AeroPress) demanded >20 g/s and flagged every
    ## normal fill as "behind" from the first second.
    fill_s = _pour_seconds(total, _POUR_RATE_VESSEL)
    if fam == BrewFamily.IMMERSION:
        steep = max(30, fill_s)
        crust = max(240, steep + 60)
        return [
            PourStep("step_fp_add", 0, total, {"g": total}),
            PourStep("step_fp_steep", steep, total),
            PourStep("step_fp_crust", crust, total),
            PourStep("step_fp_press", max(tt, crust + 60), total),
        ]
    if rec.method_id == "AEROPRESS":
        stir = max(10, fill_s)
        steep = stir + 20
        return [
            PourStep("step_ap_add", 0, total, {"g": total}),
            PourStep("step_ap_stir", stir, total),
            PourStep("step_ap_steep", steep, total),
            PourStep("step_ap_press", max(tt, steep + 30), total),
        ]
    if rec.method_id == "WEBER_BIRD":
        vortex = max(15, _pour_seconds(total, _POUR_RATE_VESSEL))
        return [
            PourStep("step_bird_add", 0, total, {"g": total}),
            PourStep("step_bird_vortex", vortex, total),
            PourStep("step_bird_steep", vortex + 15, total),
            PourStep("step_bird_pull", max(tt, vortex + 45), total),
        ]
    # Percolation / hybrid with bloom (V60, Pulsar)
    bloom = rec.bloom_g
    steps = [PourStep("step_bloom", 0, bloom, {"g": bloom})]
    ## TILAU ## Pour deadlines are derived from how long the water actually
    ## takes to pour, for two reasons the old fixed offsets got wrong. First,
    ## they were measured from the start of the BLOOM, so the pour window was
    ## whatever was left after it — 15 s, in which the first pour had to deliver
    ## ~100 g (6.5 g/s). Second, they were fixed while the water scales with
    ## dose, so the required rate grew with the batch. Both produced schedules a
    ## gooseneck cannot execute without dumping and channelling the bed.
    if rec.method_id == "PULSAR":
        spin_at = rec.bloom_s
        steps.append(PourStep("step_pulsar_spin", spin_at, bloom))
        steps.append(PourStep("step_pulsar_main",
                              spin_at + _pour_seconds(total - bloom, _POUR_RATE_FLAT),
                              total, {"g": total}))
        steps.append(PourStep("step_pulsar_draw", tt, total))
        return steps
    mid = bloom + (total - bloom) * 0.55
    p1_at = rec.bloom_s + _pour_seconds(mid - bloom, _POUR_RATE_CONE)
    p2_at = p1_at + _pour_seconds(total - mid, _POUR_RATE_CONE)
    steps.append(PourStep("step_v60_pour1", p1_at, mid, {"g": mid}))
    steps.append(PourStep("step_v60_pour2", p2_at, total, {"g": total}))
    steps.append(PourStep("step_v60_draw", max(tt, p2_at + _MIN_DRAWDOWN_S), total))
    return steps


# ── Engine ────────────────────────────────────────────────────────────────
class BrewAdvisor:
    @staticmethod
    def methods() -> tuple[str, ...]:
        return METHOD_ORDER

    @staticmethod
    def default_dose(method_id: str) -> int:
        return METHOD_ANCHORS[method_id].default_dose

    def advise(self, inp: BrewInput, method_id: str, dose_g: Optional[float] = None) -> BrewRecipe:
        anchor = METHOD_ANCHORS[method_id]
        dose = float(dose_g) if dose_g else float(anchor.default_dose)

        agt_g = round(to_agtron(inp.ground_color, inp.color_system), 1)
        agt_w = round(to_agtron(inp.whole_color, inp.color_system), 1)
        agtron = agt_g if agt_g > 0 else agt_w
        level = select_level(agtron)
        is_pressure = anchor.family == BrewFamily.PRESSURE

        temp = anchor.temp_c + level.delta_t
        grind = float(anchor.grind_um) * level.grind_mult
        ## TILAU ## Espresso reads its ratio straight from the roast level;
        ## moka stays on its anchor (the pot sets the ratio, not the bean).
        if method_id == "ESPRESSO":
            ratio = level.esp_ratio
        else:
            ratio = anchor.ratio + (0.0 if is_pressure else level.ratio)
        agitation = anchor.agitation

        notes: list[Note] = []
        agit_override: Optional[AgitationCode] = None
        ratio_up = ratio_down = 0.0
        for dlt in (
            _mod_density(inp), _mod_weight_loss(inp), _mod_development(inp),
            _mod_origin(inp), _mod_water(inp),
            _mod_rest(inp, anchor.family, agtron), _mod_moisture(inp),
        ):
            temp += dlt.temp
            grind *= dlt.grind_mult
            if not is_pressure:
                ratio += dlt.ratio
                if dlt.ratio > 0:
                    ratio_up += dlt.ratio
                elif dlt.ratio < 0:
                    ratio_down += dlt.ratio
            if dlt.agitation:
                agit_override = dlt.agitation
            notes.extend(dlt.notes)

        ## TILAU ## Two modifiers can legitimately pull the ratio opposite ways
        ## (a short development wants more water, a less dense bean wants less).
        ## The recipe already reconciles them, but the notes were printed as two
        ## independent instructions, so the panel told the operator to widen AND
        ## tighten the ratio with nothing saying which won. Say so explicitly.
        if ratio_up > 0 and ratio_down < 0 and abs(ratio_up + ratio_down) < 0.6:
            notes.append((Severity.INFO, NoteCode.RATIO_OFFSET, {}))

        # Agitation overrides only make sense where the brewer agitates a slurry;
        # for the pressure family (espresso/moka) the anchor is puck/pre-heat prep
        # and must not be replaced by a "stir/high agitation" instruction.
        if agit_override and not is_pressure:
            agitation = agit_override

        spread = abs(agt_g - agt_w) if (agt_g > 0 and agt_w > 0) else -1.0
        if spread > 15.0:
            temp -= 2.0
            if not is_pressure:
                agitation = AgitationCode.REDUCED_UNEVEN
            notes.append((Severity.CRIT, NoteCode.SPREAD_HIGH, {}))
        elif 0 <= spread < 6.0:
            notes.append((Severity.GOOD, NoteCode.SPREAD_EXCELLENT, {}))

        # [S1] Temperature is a coarse anchor by roast level only; rounded to
        # whole degrees to avoid below-perception false precision.
        temp = round(max(80.0, min(99.0, temp)))
        grind_um = int(round(max(150, min(1300, grind))))

        if is_pressure and method_id == "ESPRESSO":
            ratio_str = f"1:{ratio:.1f}"
            water_g = round(dose * ratio, 1)
        else:
            ratio = round(ratio, 1)
            ratio_str = f"1:{ratio:.0f}" if abs(ratio - round(ratio)) < 0.05 else f"1:{ratio:.1f}"
            water_g = round(dose * ratio, 0)

        ## TILAU ## The dose selector goes to 60 g, which asks an AeroPress for
        ## 930 g of water and an espresso basket for a 60 g dose. Warn rather
        ## than clamp: someone may own a larger brewer than the common one.
        cap = _BREWER_CAPACITY_G.get(method_id)
        if cap and water_g > cap:
            notes.append((Severity.WARN, NoteCode.CAPACITY,
                          {"w": f"{water_g:.0f}", "cap": f"{cap:.0f}"}))
        if method_id == "ESPRESSO" and dose > _MAX_BASKET_G:
            notes.append((Severity.WARN, NoteCode.BASKET,
                          {"d": f"{dose:.0f}", "cap": f"{_MAX_BASKET_G:.0f}"}))

        bloom_g = round(dose * anchor.bloom_factor, 0) if anchor.bloom_factor else 0.0

        espresso = None
        total_time_s = anchor.total_time_s
        if method_id == "ESPRESSO":
            spec = ESPRESSO_MACHINES.get(inp.espresso_machine, ESPRESSO_MACHINES[EspressoMachine.OTHER])
            espresso = _espresso_profile(level, inp.days_off_roast, agtron, spec, dose)
            # Shot length follows the machine profile instead of a fixed 28 s: a
            # Slayer-style low-flow lead-in genuinely makes the shot longer.
            ## TILAU ## The pull scales with the ratio, because at a fixed dose
            ## and grind the bed sets the flow: a longer ratio is not decreed,
            ## it is paid for in time. At the anchor (MEDIUM_LIGHT, 1:2.0) the
            ## factor is exactly 1.0, so the reference 28 s shot is preserved.
            lead_in = espresso.pre_brew_seconds + espresso.pi_seconds
            total_time_s = lead_in + round(_ESPRESSO_PULL_S * (ratio / 2.0))
            if inp.espresso_style == EspressoStyle.TURBO:
                ## TILAU ## Turbo fixes the shot short and opens the grind to
                ## get the flow. Flow rises with the SQUARE of particle size
                ## (Darcy / Kozeny-Carman), so the grind multiplier is the root
                ## of the flow ratio — and since the yield is identical in both
                ## styles, the flow ratio is simply classic time over turbo time.
                turbo_s = max(lead_in + 5, _TURBO_TARGET_S)
                grind_um = int(round(max(150, min(1300,
                    grind_um * math.sqrt(total_time_s / turbo_s)))))
                total_time_s = turbo_s
                notes.append((Severity.WARN, NoteCode.TURBO, {}))

        rec = BrewRecipe(
            method_id=method_id, family=anchor.family, roast_key=level.key, agtron=agtron,
            dose_g=round(dose, 1), ratio_str=ratio_str, water_g=water_g,
            water_is_yield=anchor.water_is_yield, temp_c=temp,
            grind_um=grind_um, grind_cat=grind_cat(grind_um), agitation=agitation,
            bloom_g=bloom_g, bloom_s=anchor.bloom_s, total_time_s=total_time_s,
            target_ey=anchor.target_ey, tds_hint_key=anchor.tds_hint_key,
            espresso=espresso, notes=notes,
        )
        rec.steps = _build_steps(rec)
        ## TILAU ## Safety net, not a substitute for getting each schedule right:
        ## several branches mix derived times with fixed anchors, and at extreme
        ## doses a derived time can overtake an anchor that follows it — which
        ## renders a checklist that counts backwards. Keep the order monotonic
        ## whatever the arithmetic produces.
        for i in range(1, len(rec.steps)):
            rec.steps[i].at_s = max(rec.steps[i].at_s, rec.steps[i - 1].at_s)
        ## TILAU ## A 13 g and a 30 g V60 cannot both take exactly 3:00: the
        ## bigger batch needs longer to pour and longer to drain. The anchor is
        ## a floor, not a fixed value — if the schedule that was just built runs
        ## past it, the headline time follows the schedule rather than
        ## contradicting it.
        if rec.steps:
            rec.total_time_s = max(rec.total_time_s, int(rec.steps[-1].at_s))
        return rec
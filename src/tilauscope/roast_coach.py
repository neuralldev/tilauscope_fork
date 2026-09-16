#
# ABOUT
# The coach's reading of a finished roast, shared by BeanCave and the roasting window.

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

"""What the coach says about a roast, worked out once for every screen.

The reading works from what the roast did — never from the plan for it, never
from the colour it came out. The roast level is read from the arrival pair
(development time and drop temperature, corrected for the machine's probe) and
every band is taken from that level. Nothing here builds a widget or HTML:
BeanCave renders the rows into its report, the roasting window into its own
dialog, and the roast review takes its bands from here, so no two screens can
judge the same roast differently.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from PyQt6.QtCore import QSettings, QT_TRANSLATE_NOOP
from PyQt6.QtWidgets import QApplication

from tilauscope.tilauscope_types import (
    ARRIVAL_UNCERTAINTY_DEFAULT_C, ROASTING_BASIC_BASE, RoastingPhase, dominant_dev_ror_event,
    estimate_ror_dt, find_turning_point_index, get_ror_ideal_band, normalize_timeindex,
    roast_level_from_arrival_detail, weight_loss_target)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# What the coach's inputs are actually worth. Nothing in a home roast is
# measured finely enough to judge a batch on a tenth of a point, so every
# band comparison is widened by the uncertainty of its own measurement
# rather than compared to a bare edge.
_MILESTONE_MARK_TOLERANCE_S: Final[float] = 5.0   # when first crack was called, by ear
_WEIGHT_READING_TOLERANCE_G: Final[float] = 1.0   # what a batch weight on file is worth

# Phase-duration ranges BeanCave keeps in the settings, before any are stored.
DEFAULT_DURATION_RULES: Final[dict[str, tuple[float, float]]] = {
    "drying": (4.0, 8.0),
    "maillard": (3.0, 5.0),
    "development": (1.5, 4.0),
}

_BEAN_UUID_RE: Final[re.Pattern[str]] = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')


@dataclass
class AdviceRow:
    """One line of advice: its icon, its sentence, and how much it matters."""
    icon: str
    text: str
    kind: str = "ok"   # ok | warn | bad | info


@dataclass
class CoachReading:
    """The level a roast ran at, the bands it implies, and what follows."""
    level: str | None = None
    neighbour: str | None = None
    # dtr/wl/wl_target/drop_c/dev_time, straight from the level's table.
    thresholds: dict[str, Any] = field(default_factory=dict)
    # The same bands widened by what their own measurement is worth. A screen
    # that judges a figure uses these, never the bare table edges.
    dtr_window: tuple[float, float] = (0.0, 0.0)
    wl_window: tuple[float, float] = (0.0, 0.0)
    rows: list[AdviceRow] = field(default_factory=list)


def _safe_moisture(value: Any) -> float:
    """Green moisture as a float; 0.0 when absent or unreadable (= not measured)."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def bean_uuid(beans_field: Any) -> str | None:
    """The BeanCave uuid a profile's ``beans`` block carries, or None."""
    match = _BEAN_UUID_RE.search(str(beans_field or ""))
    return match.group(1) if match else None


def stored_duration_rules() -> dict[str, Any]:
    """The phase-duration ranges BeanCave keeps in the settings."""
    return QSettings().value("duration_rules", dict(DEFAULT_DURATION_RULES)) or {}


def roast_inputs(profile: dict) -> tuple[Any, Any]:
    """(roaster record, linked green bean) of a roast, each None when unknown.

    Reads the roaster records and the bean file: call it on a user action or a
    review rebuild, never from the sampling path.
    """
    ctx = None
    try:
        from tilauscope.roasters import RoasterManager  # noqa: PLC0415
        ctx = RoasterManager().get_roast_context(str(profile.get('roastertype', '') or ''))
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        _log.debug("coach: roaster context unavailable: %s", e)
    bean = None
    uuid = bean_uuid(profile.get('beans'))
    if uuid:
        try:
            from tilauscope.cave.common import load_cave_beans  # noqa: PLC0415
            bean = next((b for b in load_cave_beans() if getattr(b, 'uuid', None) == uuid), None)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _log.debug("coach: green bean unavailable: %s", e)
    return ctx, bean


def probe_drop_offset_c(ctx: Any) -> float:
    """The bean probe's deviation at drop for the machine that ran the roast.

    Same value and same sign the plan generator applies to the reference drop
    window, so a level read here and a level prescribed there mean the same
    temperature on the operator's own display.
    """
    offsets = getattr(ctx, 'bt_offsets', None) if ctx is not None else None
    if offsets and len(offsets) >= 4:
        try:
            return float(offsets[3])
        except (TypeError, ValueError):
            pass
    return 0.0


def arrival_uncertainty_c(ctx: Any) -> float:
    """What a level read from this machine's arrival is worth, in °C."""
    try:
        return float(getattr(ctx, 'arrival_uncertainty_c', None)
                     or ARRIVAL_UNCERTAINTY_DEFAULT_C)
    except (TypeError, ValueError):
        return ARRIVAL_UNCERTAINTY_DEFAULT_C


def measured_level(computed: dict, mode: str, ctx: Any) -> tuple[str | None, str | None]:
    """(level, neighbour) for a roast, from its arrival pair.

    `neighbour` is the level the arrival could just as well be read as when it
    lands on a band edge — None when the reading is clear-cut.
    """
    try:
        drop_bt = float(computed.get('DROP_BT') or 0.0)
        fcs_t = float(computed.get('FCs_time') or 0.0)
        drop_t = float(computed.get('DROP_time') or 0.0)
    except (TypeError, ValueError):
        return None, None
    if drop_bt <= 0 or fcs_t <= 0 or drop_t <= fcs_t:
        return None, None
    # The reference table is in °C — convert at the boundary, once.
    drop_c = (drop_bt - 32.0) * 5.0 / 9.0 if mode == 'F' else drop_bt
    return roast_level_from_arrival_detail(drop_c, (drop_t - fcs_t) / 60.0,
                                           probe_drop_offset_c(ctx),
                                           arrival_uncertainty_c(ctx))


def level_thresholds(level: str | None, *, moisture_pct: float = 0.0,
                     dev_time_min: float = 0.0,
                     drop_offset_c: float = 0.0) -> tuple[str | None, dict[str, Any]]:
    """Return (level, thresholds) for a measured roast level.

    thresholds carries: dtr (min,max %), wl (min,max %), wl_target (%),
    drop_c (low,high bean-temp window in °C) and dev_time (low,high absolute
    minutes FCs→DROP). dtr/drop_c/dev_time come from ROASTING_BASIC_BASE
    (shared with the plan generator); wl comes from `weight_loss_target()`,
    which needs the lot's water and the development on top of the level —
    pass both when the roast has them, or the target falls back to a neutral
    moisture and drops the development term. When the level cannot be read we
    fall back to the Medium profile but keep level None so callers stay
    cautious.
    """
    plan = next((p for p in ROASTING_BASIC_BASE.plans if p.name == level), None)
    if plan is None:
        plan = next(p for p in ROASTING_BASIC_BASE.plans if p.name == "Medium")
    wl = weight_loss_target(plan.name, moisture_pct=moisture_pct,
                            dev_time_min=dev_time_min)
    thresholds = {
        'dtr': (plan.dtr_pct[0] * 100.0, plan.dtr_pct[1] * 100.0),
        'wl': (wl.low, wl.high),
        'wl_target': wl.target,
        # Shifted onto the machine's own display, like the plan generator
        # does, so the window can be compared with the recorded drop.
        'drop_c': (float(plan.drop_temp[0]) + drop_offset_c,
                   float(plan.drop_temp[1]) + drop_offset_c),
        'dev_time': plan.development_time,
    }
    return level, thresholds


def phase_rules_for_level(level: str | None, pooled: dict, by_band: dict) -> dict:
    """Phase-duration ranges for the roast's level, falling back per-phase to
    the pooled rules when the level has too few samples to be reliable."""
    band = by_band.get(level, {}) if level else {}
    out = {}
    for k in ('drying', 'maillard', 'development'):
        if k in band:
            out[k] = band[k]
        elif k in pooled:
            out[k] = pooled[k]
    return out


def average_rise(computed: dict, t_from: str, t_to: str) -> float | None:
    """Degrees gained between two milestones divided by the time it took, °/min.

    An average, not the rate of rise drawn on the curve, which moves within
    every phase. Recomputed from the milestones rather than read from the file:
    the stored block anchors each phase differently (the drying one starts from
    the green bean's own temperature, not the turning point) and comes out as a
    plain 0 on profiles whose milestones were edited after the roast.
    """
    try:
        bt0 = float(computed.get(f'{t_from}_BT') or 0.0)
        bt1 = float(computed.get(f'{t_to}_BT') or 0.0)
        s0 = float(computed.get(f'{t_from}_time') or 0.0)
        s1 = float(computed.get(f'{t_to}_time') or 0.0)
    except (TypeError, ValueError):
        return None
    if bt0 <= 0 or bt1 <= 0 or s1 <= s0:
        return None
    return (bt1 - bt0) / (s1 - s0) * 60.0


@dataclass
class _Basis:
    """Everything the checks share, resolved once."""
    computed: dict
    mode: str
    drying: float
    maillard: float
    development: float
    dtr_pct: float
    wl_val: float | None
    level: str | None
    neighbour: str | None
    thresholds: dict
    dtr_lo: float
    dtr_hi: float
    wl_lo: float
    wl_hi: float
    wl_hint: str
    level_label: str


def _basis(data: dict, ctx: Any, bean: Any) -> _Basis:
    computed = data.get("computed", {}) or {}
    mode = data.get("mode", "C")
    t_dry = computed.get("DRY_time", 0)
    t_fcs = computed.get("FCs_time", 0)
    t_drop = computed.get("DROP_time", 0)
    maillard = t_fcs - t_dry
    development = t_drop - t_fcs
    dtr_pct = 100 * development / t_drop if t_drop > 0 else 0

    weight_loss = computed.get("weight_loss", 0.0)
    try:
        wl_val = float(weight_loss) if weight_loss not in {0.0, "N/A"} else None
    except (ValueError, TypeError):
        wl_val = None

    # Single resolution of the roast-level thresholds, reused by every check.
    # The level is the one the roast ran, read from its arrival pair.
    read_level, neighbour = measured_level(computed, mode, ctx)
    level, th = level_thresholds(
        read_level,
        moisture_pct=_safe_moisture(data.get("moisture_greens")),
        dev_time_min=development / 60.0,
        drop_offset_c=probe_drop_offset_c(ctx))
    dtr_lo, dtr_hi = th['dtr']
    wl_lo, wl_hi = th['wl']

    # Widen both bands by what their own measurement is worth, once, so every
    # check and every badge inherits the same tolerant edges. A ratio built on
    # a first crack called by ear is worth about the seconds of that call; a
    # weight loss is worth what the two weights on file are worth.
    if t_drop > 0:
        dtr_tol = 100.0 * _MILESTONE_MARK_TOLERANCE_S / t_drop
        dtr_lo -= dtr_tol
        dtr_hi += dtr_tol
    try:
        w_in = float(computed.get('weightin') or 0.0)
        w_out = float(computed.get('weightout') or 0.0)
    except (TypeError, ValueError):
        w_in = w_out = 0.0
    if w_in > 0 and w_out > 0:
        wl_tol = 100.0 * _WEIGHT_READING_TOLERANCE_G * (1.0 / w_in + w_out / (w_in ** 2))
        wl_lo -= wl_tol
        wl_hi += wl_tol

    # The floor follows the roast level (lighter roasts lose less); a known
    # process only *widens the top* — it must not raise the floor above the
    # level, which would wrongly flag a light natural as low.
    wl_hint = ""
    if bean:
        proc = (getattr(bean, 'process', '') or '').lower()
        if any(p in proc for p in ['natural', 'honey', 'anaerobic']):
            # Surface sugars and looser chaff cost a little extra, but the
            # water and the development are already in the target itself.
            wl_hi += 1.0
            wl_hint = QApplication.translate("tilauscope_beancave", "(natural/honey)")
        elif 'washed' in proc:
            wl_hint = QApplication.translate("tilauscope_beancave", "(washed)")

    level_label = (
        QApplication.translate("tilauscope_beancave", "({0} roast)").format(level)
        if level else "")
    return _Basis(computed, mode, t_dry, maillard, development, dtr_pct, wl_val,
                  level, neighbour, th, dtr_lo, dtr_hi, wl_lo, wl_hi, wl_hint, level_label)


def roast_bands(data: dict, *, roast_context: Any = None, bean: Any = None) -> CoachReading:
    """The level and bands of a roast, without the advice built on them."""
    b = _basis(data, roast_context, bean)
    return CoachReading(level=b.level, neighbour=b.neighbour, thresholds=b.thresholds,
                        dtr_window=(b.dtr_lo, b.dtr_hi), wl_window=(b.wl_lo, b.wl_hi))


def read_roast(data: dict, *, roast_context: Any = None, bean: Any = None,
               duration_rules: dict | None = None,
               duration_rules_by_band: dict | None = None,
               evaluate_ror_bt: Callable[[], Any] | None = None,
               ror_mode: str = "C") -> CoachReading:
    """The coach's full reading of an .alog-shaped roast.

    roast_context     the roaster record of the machine that ran the roast
    bean              the green bean the roast is linked to, or None
    duration_rules    pooled phase-duration ranges (`stored_duration_rules()`)
    evaluate_ror_bt   returns the BT rate-of-rise series in `ror_mode`; called
                      only when the roast has a CHARGE and a DROP
    """
    b = _basis(data, roast_context, bean)
    computed, mode, development = b.computed, b.mode, b.development
    rows: list[AdviceRow] = []

    def add(icon: str, text: str, kind: str) -> None:
        rows.append(AdviceRow(icon, text, kind))

    # The level everything below is measured against, said out loud with the
    # pair it was read from — a verdict the operator cannot see the basis of
    # is a verdict they cannot argue with.
    if b.level:
        try:
            drop_num = float(computed.get('DROP_BT') or 0.0)
        except (TypeError, ValueError):
            drop_num = 0.0
        dev_txt = f"{int(development) // 60}:{int(development) % 60:02d}"
        drop_txt = f"{drop_num:.0f}°{mode}"
        if b.neighbour:
            add("\U0001F3AF",
                QApplication.translate("tilauscope_beancave",
                    "Read as a {0} roast — {1} development, dropped at {2} — but that is too "
                    "close to {3} for this machine to tell the two apart, so it could be read "
                    "either way. What follows is measured against {0}.").format(
                        b.level, dev_txt, drop_txt, b.neighbour),
                "info")
        else:
            add("\U0001F3AF",
                QApplication.translate("tilauscope_beancave",
                    "Read as a {0} roast — {1} development, dropped at {2}. What follows is "
                    "measured against that level.").format(b.level, dev_txt, drop_txt),
                "info")

    # ── 1. DTR% — with roast-level context ─────────────────────────────────
    if b.dtr_pct > 0:
        dtr_label = (
            QApplication.translate("tilauscope_beancave", "({0} roast range)").format(b.level)
            if b.level else "")
        # The ratio is only an under-development signal when the *absolute*
        # development time is also short. When the time is adequate, a low
        # ratio just means the front (drying/Maillard) is long — pointing at
        # "extend development" would be wrong, so it is reframed as info.
        dev_time_adequate = (development / 60.0) >= b.thresholds['dev_time'][0]
        if b.dtr_pct < b.dtr_lo:
            if dev_time_adequate:
                add("ℹ",
                    QApplication.translate("tilauscope_beancave", "DTR low but development time is adequate")
                    + f" ({b.dtr_pct:.1f}% < {b.dtr_lo:.1f}%, {development/60.0:.1f} min) {dtr_label} — "
                    + QApplication.translate("tilauscope_beancave",
                        "the ratio is low because the front (drying/Maillard) is long; shorten the front if you want a higher ratio, no need to extend development."),
                    "info")
            else:
                add("⚡",
                    QApplication.translate("tilauscope_beancave", "Short development")
                    + f" ({b.dtr_pct:.1f}% < {b.dtr_lo:.1f}%) {dtr_label} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Underdeveloped risk: baked/grassy notes. Extend dev phase or raise drop temp."),
                    "warn")
        elif b.dtr_pct > b.dtr_hi:
            add("⚡",
                QApplication.translate("tilauscope_beancave", "Long development")
                + f" ({b.dtr_pct:.1f}% > {b.dtr_hi:.1f}%) {dtr_label} — "
                + QApplication.translate("tilauscope_beancave",
                    "Over-development risk: flat, roasty notes dominate. Consider an earlier drop."),
                "warn")
        else:
            add("✓",
                QApplication.translate("tilauscope_beancave", "DTR in range")
                + f" ({b.dtr_pct:.1f}%) {dtr_label}", "ok")

    # ── 2. Weight loss — roast-level window, widened for high-retention process ─
    if b.wl_val is not None:
        if b.wl_val < b.wl_lo:
            add("⚠",
                QApplication.translate("tilauscope_beancave", "Low weight loss")
                + f" ({b.wl_val:.1f}% < {b.wl_lo:.1f}%) {b.wl_hint} — "
                + QApplication.translate("tilauscope_beancave",
                    "Bean may be under-roasted or the batch was unusually dense. Verify scale calibration."),
                "warn")
        elif b.wl_val > b.wl_hi:
            add("⚠",
                QApplication.translate("tilauscope_beancave", "High weight loss")
                + f" ({b.wl_val:.1f}% > {b.wl_hi:.1f}%) {b.wl_hint} — "
                + QApplication.translate("tilauscope_beancave",
                    "Roast may be over-developed or airflow too high. Watch for flat cup."),
                "bad")
        else:
            add("✓",
                QApplication.translate("tilauscope_beancave", "Weight loss in range")
                + f" ({b.wl_val:.1f}%) {b.wl_hint}", "ok")

    # ── 3. Phase durations ─────────────────────────────────────────────────
    # Development time is judged on the professional-convention window for the
    # level (absolute minutes), so a sound light development of 1:00–1:30 reads
    # on-target regardless of the learned average. Drying and Maillard keep the
    # learned, per-level ranges (with pooled fallback).
    rules = dict(phase_rules_for_level(b.level, duration_rules or {}, duration_rules_by_band or {}))
    rules['development'] = b.thresholds['dev_time']
    # QT_TRANSLATE_NOOP declares the label for the extractor and returns it
    # unchanged; the translate() below then finds it in the catalogue.
    for phase_name_key, phase_key, duration_s in [
        (QT_TRANSLATE_NOOP("tilauscope_beancave", "Dry Phase"),         "drying",      b.drying),
        (QT_TRANSLATE_NOOP("tilauscope_beancave", "Maillard Phase"),    "maillard",    b.maillard),
        (QT_TRANSLATE_NOOP("tilauscope_beancave", "Development Phase"), "development", development),
    ]:
        if phase_key in rules and duration_s > 0:
            mn, mx = rules[phase_key]
            actual_min = duration_s / 60.0
            phase_tr = QApplication.translate("tilauscope_beancave", phase_name_key)
            # Development cites the professional standard; the other phases
            # cite the user's own learned range.
            range_lbl = (QApplication.translate('tilauscope_beancave', 'standard for this level')
                         if phase_key == 'development'
                         else QApplication.translate('tilauscope_beancave', 'your usual range'))
            # Drying/Maillard are learned, soft references: a minor drift past
            # the band (< 30 s) is noise, not a fault — stay silent (on-target).
            # Development keeps the professional floor, but still cannot be
            # judged finer than the seconds its milestones were called with.
            grace = (0.5 if phase_key in ('drying', 'maillard')
                     else _MILESTONE_MARK_TOLERANCE_S / 60.0)
            if actual_min < mn - grace:
                # Observational, not a verdict: the range is learned from the
                # user's own roasts at this level, so a short phase may simply
                # be the intended style. Development gets the gentlest framing.
                context = {
                    "drying": QApplication.translate("tilauscope_beancave",
                        "If the cup tastes grassy or green, give the beans a little longer to dry before browning."),
                    "maillard": QApplication.translate("tilauscope_beancave",
                        "Less time for caramelization — body may be lighter and acidity sharper."),
                    "development": QApplication.translate("tilauscope_beancave",
                        "Below the professional minimum for this level — real under-development risk (grassy/baked). Carry more momentum into first crack or drop a little later."),
                }.get(phase_key, "")
                add("⏱",
                    f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'shorter than usual')}"
                    + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {b.level_label} — {context}",
                    "warn")
            elif actual_min > mx + grace:
                context = {
                    "drying": QApplication.translate("tilauscope_beancave",
                        "Long drying can reduce caramelization potential and flatten sweetness."),
                    "maillard": QApplication.translate("tilauscope_beancave",
                        "Excessive Maillard may push toward flat, bready notes."),
                    "development": QApplication.translate("tilauscope_beancave",
                        "Over-development: roasty, dark tones may dominate origin character."),
                }.get(phase_key, "")
                add("⏱",
                    f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'longer than usual')}"
                    + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {b.level_label} — {context}",
                    "warn")
            else:
                add("✓",
                    f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'on target')}"
                    + f" ({actual_min:.1f} min)", "ok")

    # ── 4. Cross-check: Drop BT vs DTR consistency ─────────────────────────
    # A low drop temperature is the *goal* on a light roast, so it is only a
    # concern when it lands below the window expected for the level AND the
    # development ratio is also short — two independent signals agreeing.
    # That concordance is what earns the red flag; either one alone does not.
    drop_bt_val = computed.get('DROP_BT', None)
    if drop_bt_val and b.dtr_pct > 0:
        try:
            drop_bt_f = float(drop_bt_val)
            drop_low_c, drop_high_c = b.thresholds['drop_c']
            if mode == 'F':
                drop_low = drop_low_c * 9.0 / 5.0 + 32.0
                drop_high = drop_high_c * 9.0 / 5.0 + 32.0
            else:
                drop_low, drop_high = drop_low_c, drop_high_c
            if drop_bt_f < drop_low and b.dtr_pct < b.dtr_lo:
                add("🔴",
                    QApplication.translate("tilauscope_beancave",
                        "Both the drop temperature and the development ratio land below the "
                        "window expected for this roast level — two signals agreeing on "
                        "under-development. Watch for grassy or baked notes; consider a hotter "
                        "charge or a slower Maillard.") + f" {b.level_label}",
                    "bad")
            elif drop_bt_f > drop_high and b.dtr_pct < b.dtr_lo:
                add("🔶",
                    QApplication.translate("tilauscope_beancave",
                        "Drop temperature is higher than expected for this level yet the "
                        "development ratio is short — the bean colour may be darker than "
                        "intended. Watch for scorching; reduce end-heat or drop earlier.") + f" {b.level_label}",
                    "warn")
        except (TypeError, ValueError):
            pass

    # ── 5. Rate of rise into and through development ───────────────────────
    # 5a. RoR at the onset of first crack — momentum entering development.
    #     Roaster-agnostic: a flat/negative RoR at FCs means the bean enters
    #     development with no thermal momentum (stall/crash risk), regardless
    #     of roaster type. No absolute "high" threshold is used here on purpose.
    # Ideal RoR band for the development phase (FC → DROP), the same shared
    # source used in-roast by the assistant and by the plan generator.
    dev_ror_lo, _ = get_ror_ideal_band("FC_DROP", mode)
    fcs_ror = computed.get('fcs_ror', None)
    if fcs_ror is not None:
        try:
            fcs_ror_v = float(fcs_ror)
            if fcs_ror_v <= 0:
                add("🧊",
                    QApplication.translate("tilauscope_beancave",
                        "Flat or negative RoR entering first crack: the roast lost momentum "
                        "right at FC, a strong stall/crash signal. Add a touch of heat just "
                        "before FC next time to carry momentum into development."),
                    "bad")
            elif fcs_ror_v < dev_ror_lo:
                add("🐌",
                    QApplication.translate("tilauscope_beancave",
                        "Low RoR entering first crack: little momentum into "
                        "development — watch for a stall and baked, flat character."),
                    "warn")
        except (TypeError, ValueError):
            pass

    # 5b. Crash/flick in development, via the same prominence-based local-extrema
    #     detector the plan generator uses on historical logs — one algorithm,
    #     not a separate ratio heuristic in the coach.
    try:
        ti = normalize_timeindex(data.get('timeindex', []))
        charge_idx, drop_idx = ti[RoastingPhase.CHARGE], ti[RoastingPhase.DROP]
        timex = data.get("timex", [])
        raw_delta_bt = (evaluate_ror_bt()
                        if evaluate_ror_bt is not None and charge_idx >= 0 < drop_idx else None)
        if (raw_delta_bt and timex and charge_idx >= 0 and drop_idx > charge_idx
                and len(timex) == len(raw_delta_bt) and drop_idx < len(timex)):
            charge_ts = timex[charge_idx]
            timex_shifted = [(t - charge_ts) for t in timex]
            dry_idx, fc_idx = ti[RoastingPhase.DRYEND], ti[RoastingPhase.FCSTART]
            phase_times = {
                "dry_end":  timex_shifted[dry_idx] if dry_idx > 0 else None,
                "fc_start": timex_shifted[fc_idx]  if fc_idx  > 0 else None,
                "drop":     timex_shifted[drop_idx],
            }
            bt_raw = data.get("temp2", [])
            seg_slice = slice(charge_idx, drop_idx + 1)
            seg_dt = estimate_ror_dt(timex_shifted[seg_slice])
            tp_idx_local = find_turning_point_index(bt_raw[seg_slice], seg_dt)
            # The RoR series is in the display unit, so the °C-based threshold
            # scales on that, not on the unit the profile was recorded in.
            event = dominant_dev_ror_event(
                raw_delta_bt[seg_slice], timex_shifted[seg_slice], phase_times,
                tp_idx_local, ror_mode)
            if event is not None:
                # The time is spelled out so the operator can go and look at
                # the spot on the curve instead of taking the claim on trust.
                at_t = f"{int(event['time']) // 60}:{int(event['time']) % 60:02d}"
                if event["kind"] == "crash":
                    add("📉",
                        QApplication.translate("tilauscope_beancave",
                            "RoR crash at {0} in development: the rate dropped sharply before "
                            "drop. This can cause baked character. Maintain at least {1:.0f}°/min "
                            "through drop.").format(at_t, dev_ror_lo),
                        "bad")
                else:
                    add("📈",
                        QApplication.translate("tilauscope_beancave",
                            "RoR flick at {0} in development: the rate bumped up significantly. "
                            "This may indicate a heat spike. Reduce burner earlier to avoid "
                            "scorching.").format(at_t),
                        "warn")
    except (TypeError, ValueError, IndexError):
        pass

    # ── 6. Density context ─────────────────────────────────────────────────
    # The bean this roast is linked to, never a catalogue selection. No link,
    # no density advice.
    if bean is not None:
        if bean.density > 780:
            add("💎",
                QApplication.translate("tilauscope_beancave",
                    "Very high density bean (>780 g/l): needs strong initial charge energy. "
                    "If DTR or weight loss is low, consider raising charge temp by 5–8°C next roast."),
                "info")
        elif 0 < bean.density < 650:
            add("🪶",
                QApplication.translate("tilauscope_beancave",
                    "Low density bean (<650 g/l): absorbs heat quickly — watch for early FC. "
                    "Reduce heat in Maillard to avoid rushing development."),
                "info")

    if not rows:
        add("✓",
            QApplication.translate("tilauscope_beancave",
                "All measured parameters are within the recommended ranges."), "ok")

    return CoachReading(level=b.level, neighbour=b.neighbour, thresholds=b.thresholds,
                        dtr_window=(b.dtr_lo, b.dtr_hi), wl_window=(b.wl_lo, b.wl_hi),
                        rows=rows)

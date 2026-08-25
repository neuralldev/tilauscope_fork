#
# ABOUT
# Post-roast debrief: compares a finished roast to the plan frozen before it.

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

"""Single source of the post-roast verdict.

`build_debrief()` is pure: it takes an .alog-shaped profile dict and the plan
snapshot frozen before CHARGE, and returns structured text plus per-milestone
deviations. It produces no HTML and touches no widget — every consumer (the
Roast Review panel, the roast card) formats the same result its own way, so the
two can never disagree about the same roast.

Band tables are never redefined here: roast levels come from
`tilauscope_types.ROASTING_BASIC_BASE` (the table the plan generator itself
builds from) and weight loss from `roast_insights.weight_loss_band()`.
"""

from dataclasses import dataclass, field
from typing import Final
import logging

try:
    from PyQt6.QtWidgets import QApplication  # @UnusedImport @Reimport  @UnresolvedImport
except ImportError:
    from PyQt5.QtWidgets import QApplication  # type: ignore # @UnusedImport @Reimport  @UnresolvedImport

from tilauscope.tilauscope_types import (AGTRON_SCALES, ROASTING_BASIC_BASE,
                                         WEIGHT_LOSS_PCT_BY_CATEGORY, to_agtron)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Translation context is written out literally at every call site: the string
# extractor ignores any translate() argument that is not a literal.

# Reporting thresholds: below these an écart is not worth a sentence, it stays
# in the milestone column. They say what deserves the operator's attention, not
# what is chemically significant.
_DROP_BT_TELL_C: Final[float] = 3.0
_DROP_TIME_TELL_S: Final[float] = 20.0
_MILESTONE_TIME_TELL_S: Final[float] = 30.0

# Fallback development band when no plan was recorded — the Medium roast level.
_DEFAULT_DTR_BAND: Final[tuple[float, float]] = (15.0, 22.0)


@dataclass
class MilestoneDelta:
    """Signed deviation of one milestone from the plan (actual − planned)."""
    time_s: "float | None" = None
    bt_c: "float | None" = None
    planned_time_s: "float | None" = None
    planned_bt_c: "float | None" = None


@dataclass
class Figure:
    """One headline number with the words that give it meaning."""
    value: str = "—"
    band: str = ""
    severity: str = "neutral"   # ok | attention | neutral


@dataclass
class Debrief:
    has_plan: bool = False
    severity: str = "none"      # ok | attention | none
    headline: str = ""
    detail: str = ""
    next_time: str = ""
    deltas: dict[str, MilestoneDelta] = field(default_factory=dict)
    figures: dict[str, Figure] = field(default_factory=dict)
    phases: dict[str, float] = field(default_factory=dict)
    milestones: list[tuple[str, float, float]] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _num(value) -> "float | None":
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos(value) -> "float | None":
    v = _num(value)
    return v if v is not None and v > 0.0 else None


def fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:d}:{s % 60:02d}"


def _ror_c_to_mode(value: float, mode: str) -> float:
    """Convert a °C/min interval to the requested display unit."""
    return value * 9.0 / 5.0 if str(mode).upper() == "F" else value


def _agtron_category(agtron: "float | None") -> "str | None":
    """Agtron value → one of AGTRON_SCALES' category names."""
    if agtron is None or agtron <= 0:
        return None
    for scale in AGTRON_SCALES:
        try:
            if scale.agtron_range.min_value <= agtron <= scale.agtron_range.max_value:
                return scale.name
        except (TypeError, ValueError):
            continue
    return None


def _dtr_band(category: "str | None") -> tuple[float, float]:
    """Development band (%) for a roast level, from the plan's own base table."""
    plan = next((p for p in ROASTING_BASIC_BASE.plans if p.name == category), None)
    if plan is None:
        return _DEFAULT_DTR_BAND
    return (plan.dtr_pct[0] * 100.0, plan.dtr_pct[1] * 100.0)


def _weight_loss_band(category: "str | None") -> "tuple[float, float] | None":
    if not category:
        return None
    return WEIGHT_LOSS_PCT_BY_CATEGORY.get(category)


def profile_from_qmc(aw) -> dict:
    """Build the .alog-shaped dict `build_debrief()` expects from live Artisan.

    Single conversion point between the running application and the debrief, so
    a displayed roast and a saved one are described by exactly the same keys.
    Calls `computedProfileInformation()` — never do this in the sampling path.
    """
    qmc = aw.qmc
    try:
        computed = dict(aw.computedProfileInformation() or {})
    except Exception as e:  # pylint: disable=broad-except
        _log.debug("computedProfileInformation: %s", e)
        computed = {}
    weight = list(getattr(qmc, "weight", (0, 0, "g")) or (0, 0, "g"))
    return {
        "title": getattr(qmc, "title", "") or "",
        "beans": getattr(qmc, "beans", "") or "",
        "mode": getattr(qmc, "mode", "C") or "C",
        # roastdate is a QDateTime live and a plain date string in a .alog:
        # normalised here so the panel and the roast card format one shape.
        **_roast_datetime(qmc),
        "roastbatchprefix": getattr(qmc, "roastbatchprefix", "") or "",
        "roastbatchnr": getattr(qmc, "roastbatchnr", 0) or 0,
        "weight": weight,
        "ground_color": getattr(qmc, "ground_color", 0) or 0,
        "whole_color": getattr(qmc, "whole_color", 0) or 0,
        "color_system": getattr(qmc, "color_system", "Agtron") or "Agtron",
        "ambientTemp": getattr(qmc, "ambientTemp", 0) or 0,
        "ambient_humidity": getattr(qmc, "ambient_humidity", 0) or 0,
        "ambient_pressure": getattr(qmc, "ambient_pressure", 0) or 0,
        "cuppingnotes": getattr(qmc, "cuppingnotes", "") or "",
        # By reference: the roast card reads these to draw its miniature, and a
        # copy of the whole curve would be pure waste.
        "timex": getattr(qmc, "timex", []),
        "temp1": getattr(qmc, "temp1", []),
        "temp2": getattr(qmc, "temp2", []),
        "timeindex": list(getattr(qmc, "timeindex", [])),
        "computed": computed,
    }


def display_name(profile: dict) -> str:
    """The name to put on the roast.

    `beans` is a description block carrying the BeanCave uuid, not a name, so
    the roast title comes first; only if there is none do we take the first
    readable line of the description.
    """
    title = str(profile.get("title") or "").strip()
    if title:
        return title
    for line in str(profile.get("beans") or "").splitlines():
        line = line.strip()
        if line and "uuid:" not in line.lower():
            return line
    return ""


def _roast_datetime(qmc) -> dict:
    """The roast date and time as the .alog stores them: two strings."""
    stamp = getattr(qmc, "roastdate", None)
    try:
        return {"roastdate": stamp.date().toString("yyyy-MM-dd"),
                "roasttime": stamp.time().toString("HH:mm")}
    except AttributeError:
        return {"roastdate": str(stamp or ""), "roasttime": ""}


def roast_colour_agtron(profile: dict) -> "float | None":
    """Ground colour when measured, else whole — never the lighter of the two."""
    system = str(profile.get("color_system") or "Agtron")
    for key in ("ground_color", "whole_color"):
        raw = _pos(profile.get(key))
        if raw is not None:
            try:
                return float(to_agtron(raw, system))
            except Exception:  # pylint: disable=broad-except
                return raw
    return None


# ─────────────────────────────────────────────────────────────────────────────
# public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_debrief(profile: dict, snapshot: "dict | None" = None,
                  mode: str = "C", peak_ror_reference_c: "float | None" = None,
                  peak_ror_c: "float | None" = None) -> Debrief:
    """Compare a finished roast to the plan frozen before it.

    profile              .alog-shaped dict (or `profile_from_qmc()` output)
    snapshot             qmc.tilau_roast_plan_snapshot, or None when the roast
                         ran without the assistant — the verdict then says so
                         instead of inventing a comparison
    peak_ror_c           peak BT RoR in °C/min, recomputed by the caller (the
                         RoR is never stored in the .alog)
    """
    out = Debrief()
    profile = profile or {}
    computed = profile.get("computed") or {}

    drop_t = _pos(computed.get("DROP_time"))
    fcs_t = _pos(computed.get("FCs_time"))
    dry_t = _pos(computed.get("DRY_time"))
    # An unmarked milestone reads 0, never None: a bean temperature of zero is
    # not a measurement, so every BT is taken as strictly positive or absent.
    drop_bt = _pos(computed.get("DROP_BT"))
    fcs_bt = _pos(computed.get("FCs_BT"))

    # ── milestones (time, BT), in roast order ──────────────────────────────
    for key, time_key, bt_key in (("CHARGE", "CHARGE_time", "CHARGE_BT"),
                                  ("TP", "TP_time", "TP_BT"),
                                  ("DRY END", "DRY_time", "DRY_BT"),
                                  ("FC START", "FCs_time", "FCs_BT"),
                                  ("DROP", "DROP_time", "DROP_BT")):
        bt = _pos(computed.get(bt_key))
        t = 0.0 if key == "CHARGE" else _pos(computed.get(time_key))
        if bt is not None and t is not None:
            out.milestones.append((key, t, bt))

    # ── phases ─────────────────────────────────────────────────────────────
    for key, computed_key in (("dry", "dryphasetime"), ("mai", "midphasetime"),
                              ("dev", "finishphasetime")):
        v = _pos(computed.get(computed_key))
        if v is not None:
            out.phases[key] = v

    # ── figures ────────────────────────────────────────────────────────────
    agtron = roast_colour_agtron(profile)
    category = _agtron_category(agtron)

    predicted = ((snapshot or {}).get("predicted") or {})
    planned_ms = predicted.get("milestones") or {}
    planned_drop_t = _pos((planned_ms.get("drop") or {}).get("time_s"))
    planned_drop_bt = _pos((planned_ms.get("drop") or {}).get("bt_c"))
    planned_fc_t = _pos((planned_ms.get("first_crack") or {}).get("time_s"))
    planned_dry_t = _pos((planned_ms.get("dry_end") or {}).get("time_s"))
    planned_colour = _pos(predicted.get("target_color_agtron"))
    # A snapshot that never saw a DROP describes an aborted roast: it cannot
    # carry a verdict, so it is treated as no plan at all.
    out.has_plan = bool(planned_drop_t or planned_drop_bt)

    planned_dtr = None
    if planned_drop_t and planned_fc_t and planned_fc_t < planned_drop_t:
        planned_dtr = (planned_drop_t - planned_fc_t) / planned_drop_t * 100.0

    # development
    dtr = None
    if drop_t and fcs_t and fcs_t < drop_t:
        dtr = (drop_t - fcs_t) / drop_t * 100.0
    if dtr is None:
        out.figures["dtr"] = Figure(
            band=QApplication.translate("tilauscope_review", "first crack was not marked"))
    elif planned_dtr is not None:
        sev = "ok" if abs(dtr - planned_dtr) <= 3.0 else "attention"
        word = (QApplication.translate("tilauscope_review", "on target") if sev == "ok"
                else (QApplication.translate("tilauscope_review", "short") if dtr < planned_dtr
                      else QApplication.translate("tilauscope_review", "long")))
        out.figures["dtr"] = Figure(
            f"{dtr:.1f} %",
            QApplication.translate("tilauscope_review", "planned {0} % · {1}").format(
                f"{planned_dtr:.0f}", word), sev)
    else:
        lo, hi = _dtr_band(category)
        out.figures["dtr"] = Figure(
            f"{dtr:.1f} %",
            QApplication.translate("tilauscope_review", "typical range {0}–{1} %").format(
                f"{lo:.0f}", f"{hi:.0f}"),
            "neutral")

    # development rise
    if drop_bt is not None and fcs_bt is not None:
        out.figures["dev_rise"] = Figure(
            f"{drop_bt - fcs_bt:.1f} °{mode}",
            QApplication.translate("tilauscope_review", "from first crack to drop"), "neutral")
    else:
        out.figures["dev_rise"] = Figure(
            band=QApplication.translate("tilauscope_review", "first crack was not marked"))

    # peak RoR — a reference for the roaster, never a ceiling to stay under:
    # values above it are common and are not a fault, so severity stays neutral.
    if peak_ror_c is not None:
        unit = "F" if str(mode).upper() == "F" else "C"
        peak = _ror_c_to_mode(peak_ror_c, unit)
        ref = (_ror_c_to_mode(peak_ror_reference_c, unit)
               if peak_ror_reference_c is not None else None)
        band = (QApplication.translate(
                    "tilauscope_review", "°{0}/min · typical peak here is {1}")
                .format(unit, f"{ref:.0f}") if ref is not None else
                QApplication.translate(
                    "tilauscope_review", "°{0}/min · peak after the turning point")
                .format(unit))
        out.figures["peak_ror"] = Figure(f"{peak:.1f}", band, "neutral")
    else:
        out.figures["peak_ror"] = Figure(
            band=QApplication.translate("tilauscope_review", "no rate of rise recorded"))

    # colour — stated, never turned into advice: no DROP↔Agtron slope is
    # validated, so an écart here cannot prescribe a temperature change.
    if agtron is not None and planned_colour is not None:
        out.figures["colour"] = Figure(
            f"{agtron:.0f}",
            QApplication.translate("tilauscope_review", "Agtron ground · planned {0}").format(
                f"{planned_colour:.0f}"), "neutral")
    elif agtron is not None:
        out.figures["colour"] = Figure(
            f"{agtron:.0f}", QApplication.translate("tilauscope_review", "Agtron ground"), "neutral")
    elif planned_colour is not None:
        out.figures["colour"] = Figure(
            band=QApplication.translate("tilauscope_review", "not measured · planned {0}").format(
                f"{planned_colour:.0f}"))
    else:
        out.figures["colour"] = Figure(
            band=QApplication.translate("tilauscope_review", "not measured"))

    # weight loss
    loss = _pos(computed.get("weight_loss"))
    if loss is None:
        w = profile.get("weight") or []
        if len(w) >= 2:
            w_in, w_out = _pos(w[0]), _pos(w[1])
            if w_in and w_out:
                loss = (w_in - w_out) / w_in * 100.0
    if loss is None:
        out.figures["weight_loss"] = Figure(
            band=QApplication.translate("tilauscope_review", "roasted weight missing"))
    else:
        band = _weight_loss_band(category)
        if band:
            sev = "ok" if band[0] <= loss <= band[1] else "attention"
            out.figures["weight_loss"] = Figure(
                f"{loss:.1f} %",
                QApplication.translate("tilauscope_review", "typical {0}–{1} % at this colour").format(
                    f"{band[0]:.0f}", f"{band[1]:.0f}"), sev)
        else:
            out.figures["weight_loss"] = Figure(
                f"{loss:.1f} %", QApplication.translate("tilauscope_review", "of the green weight"),
                "neutral")

    # ── deviations from the plan ───────────────────────────────────────────
    if not out.has_plan:
        out.severity = "none"
        out.headline = QApplication.translate("tilauscope_review", "No plan was recorded for this batch,")
        out.detail = QApplication.translate(
            "tilauscope_review", "so there is nothing to compare against — the figures below are "
                  "the roast as it happened.")
        out.next_time = QApplication.translate(
            "tilauscope_review", "Start the next one from the assistant to get a verdict.")
        return out

    for name, actual_t, actual_bt, plan_t, plan_bt in (
            ("dry_end", dry_t, _pos(computed.get("DRY_BT")), planned_dry_t,
             _pos((planned_ms.get("dry_end") or {}).get("bt_c"))),
            ("first_crack", fcs_t, fcs_bt, planned_fc_t,
             _pos((planned_ms.get("first_crack") or {}).get("bt_c"))),
            ("drop", drop_t, drop_bt, planned_drop_t, planned_drop_bt)):
        delta = MilestoneDelta(planned_time_s=plan_t, planned_bt_c=plan_bt)
        if actual_t is not None and plan_t is not None:
            delta.time_s = actual_t - plan_t
        if actual_bt is not None and plan_bt is not None:
            delta.bt_c = actual_bt - plan_bt
        if delta.time_s is not None or delta.bt_c is not None:
            out.deltas[name] = delta

    _verdict(out, mode)
    return out


def _verdict(out: Debrief, mode: str) -> None:
    """Name a single écart — the heaviest one — and the gesture that fixes it.

    Priority is drop, then first crack, then dry end: the drop is what the cup
    tastes, and the earlier milestones are already reported in their column.
    """
    drop = out.deltas.get("drop")
    fc = out.deltas.get("first_crack")
    dry = out.deltas.get("dry_end")

    def _sec(v: float) -> str:
        return f"{abs(v):.0f}"

    # is anything worth a sentence?
    drop_bt_off = drop is not None and drop.bt_c is not None and abs(drop.bt_c) >= _DROP_BT_TELL_C
    drop_t_off = drop is not None and drop.time_s is not None and abs(drop.time_s) >= _DROP_TIME_TELL_S
    fc_off = fc is not None and fc.time_s is not None and abs(fc.time_s) >= _MILESTONE_TIME_TELL_S
    dry_off = dry is not None and dry.time_s is not None and abs(dry.time_s) >= _MILESTONE_TIME_TELL_S

    # the detail sentence always reports first crack and drop when known
    bits: list[str] = []
    if fc is not None and fc.time_s is not None:
        bits.append((QApplication.translate("tilauscope_review", "first crack came {0} s late")
                     if fc.time_s > 0 else
                     QApplication.translate("tilauscope_review", "first crack came {0} s early"))
                    .format(_sec(fc.time_s)))
    if drop is not None and drop.bt_c is not None and drop.planned_bt_c is not None:
        bits.append((QApplication.translate("tilauscope_review", "you dropped {0} °{1} above the planned {2} °{1}")
                     if drop.bt_c > 0 else
                     QApplication.translate("tilauscope_review", "you dropped {0} °{1} below the planned {2} °{1}"))
                    .format(f"{abs(drop.bt_c):.0f}", mode, f"{drop.planned_bt_c:.0f}"))
    detail = QApplication.translate("tilauscope_review", " and ").join(bits)
    out.detail = (detail[0].upper() + detail[1:] + ".") if detail else ""

    if not (drop_bt_off or drop_t_off or fc_off or dry_off):
        out.severity = "ok"
        out.headline = QApplication.translate("tilauscope_review", "Ran to plan.")
        out.next_time = QApplication.translate("tilauscope_review", "Next time: nothing to change.")
        return

    out.severity = "attention"
    if drop_t_off and drop is not None and drop.time_s is not None:
        out.headline = (QApplication.translate("tilauscope_review", "Dropped {0} s late.")
                        if drop.time_s > 0 else
                        QApplication.translate("tilauscope_review", "Dropped {0} s early.")
                        ).format(_sec(drop.time_s))
    elif drop_bt_off and drop is not None and drop.bt_c is not None:
        out.headline = (QApplication.translate("tilauscope_review", "Dropped {0} °{1} above plan.")
                        if drop.bt_c > 0 else
                        QApplication.translate("tilauscope_review", "Dropped {0} °{1} below plan.")
                        ).format(f"{abs(drop.bt_c):.0f}", mode)
    elif fc_off and fc is not None and fc.time_s is not None:
        out.headline = (QApplication.translate("tilauscope_review", "First crack came {0} s late.")
                        if fc.time_s > 0 else
                        QApplication.translate("tilauscope_review", "First crack came {0} s early.")
                        ).format(_sec(fc.time_s))
    elif dry is not None and dry.time_s is not None:
        out.headline = (QApplication.translate("tilauscope_review", "Dry end came {0} s late.")
                        if dry.time_s > 0 else
                        QApplication.translate("tilauscope_review", "Dry end came {0} s early.")
                        ).format(_sec(dry.time_s))

    # the gesture, tied to the écart just named
    if (drop_t_off or drop_bt_off) and drop is not None and drop.planned_bt_c is not None:
        out.next_time = QApplication.translate(
            "tilauscope_review", "Next time: hold the drop to {0} °{1}, whatever the clock says."
        ).format(f"{drop.planned_bt_c:.0f}", mode)
    elif fc_off and fc is not None and fc.time_s is not None:
        out.next_time = (
            QApplication.translate("tilauscope_review", "Next time: more heat through drying to reach first crack on time.")
            if fc.time_s > 0 else
            QApplication.translate("tilauscope_review", "Next time: ease the burner through drying so first crack does not come early."))
    else:
        out.next_time = (
            QApplication.translate("tilauscope_review", "Next time: more heat at charge to dry on schedule.")
            if dry is not None and dry.time_s is not None and dry.time_s > 0 else
            QApplication.translate("tilauscope_review", "Next time: ease the charge heat so drying does not run short."))

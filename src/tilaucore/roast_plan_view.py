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

"""What a screen shows of a roast plan, shared by both apps: the levers at each
milestone, the weight expected after cooling, and the plan's notes.

Texts go through the caller's `translate` (a text pair -> str): the desktop's
QApplication.translate, or `english` on the tablet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tilaucore import tasting_log
from tilaucore.bean_qualifiers import QT_TRANSLATE_NOOP
from tilaucore.roast_summary import english_short_date, roast_name

Text = tuple[str, str]
Translate = Callable[[Text], str]


def english(text: Text) -> str:
    return text[1]


def phase_pct(raw: Any, col: int) -> "float | None":
    """One phase value out of a 'Dry | Mai | Dev' summary string."""
    try:
        return float(str(raw).split('|')[col].strip().rstrip('%'))
    except (ValueError, IndexError, AttributeError):
        return None

def entry_levels(plan_data: dict) -> "dict[str, list[float | None]]":
    """Heater, airflow and drum as each reads when CHARGE, DRY END and FIRST
    CRACK are crossed — the section 4 values, for any screen that shows them.

    A lever the plan does not drive maps to an empty list.
    """
    heater, airflow, ms = control_trajectories(plan_data)
    marks = [0.0, float(ms.get("dry_end") or 0.0), float(ms.get("fc_start") or 0.0)]

    def _held(points: list, t: float) -> "float | None":
        held = None
        for pt, pv in points:
            if pt <= t + 1e-9:
                held = pv
            else:
                break
        return held

    drum = [phase_pct(plan_data.get("Drum Speed (%) (Dry|Mai|Dev)", ""), c) for c in (0, 1, 2)]
    return {
        "heater": [_held(heater, t) for t in marks] if heater else [],
        "airflow": [_held(airflow, t) for t in marks] if airflow else [],
        "drum": drum if any(v is not None for v in drum) else [],
    }

def control_trajectories(plan_data: dict) -> "tuple[list, list, dict]":
    """Heater and airflow as (time_min, percent) points, plus milestones.

    Both are STAIRCASES: a setting is posted once and held until the next
    change. Drawing a slope between two settings would picture a continuous
    knob movement that never happens — the operator makes one step, then
    waits to read its effect.

    The sequence mirrors what the assistant actually applies (see
    ``roast_asssistant._ap_phase_targets``), not the phase summary table:
    the burner holds its charge value until the anticipated ramp takes over,
    then the Dev Ramp carries it through development; airflow is posted at
    each phase, refined by the Maillard Air Ramp, then also carried by the
    Dev Ramp. Reading the summary instead would draw three flat plateaus and
    hide every gesture the plan actually asks for.
    """
    curve = plan_data.get("bt_plan_curve") or {}
    times = list(curve.get("time_min") or [])
    bts = list(curve.get("bt_plan") or [])
    if len(times) < 2 or len(times) != len(bts):
        return [], [], {}

    # Milestones by stable key, never by translated label.
    wps = {w.get("key"): w for w in (curve.get("waypoints") or [])}

    def _wp_t(key: str) -> float:
        try:
            return float(wps.get(key, {}).get("time_min", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    t_end = float(times[-1])
    milestones = {"dry_end": _wp_t("dry_end"), "fc_start": _wp_t("fc_start"),
                  "tp": _wp_t("tp"), "t_end": t_end}

    # BT -> time, scanning forward from the TURNING POINT: bean temperature
    # falls to TP before it rises, so a scan from t=0 would resolve a
    # Maillard threshold against the charge descent and place the step at
    # the wrong end of the roast.
    i_tp = min(range(len(bts)), key=lambda i: bts[i])

    def t_at_bt(target: float) -> float:
        for i in range(i_tp + 1, len(bts)):
            if bts[i] >= target:
                b0, b1 = bts[i - 1], bts[i]
                if b1 > b0:
                    f = (target - b0) / (b1 - b0)
                    return times[i - 1] + f * (times[i] - times[i - 1])
                return times[i]
        return t_end

    def _collect(ramp_key: str, value_key: str, out: list) -> None:
        for e in (plan_data.get(ramp_key) or []):
            if not isinstance(e, dict) or value_key not in e:
                continue
            try:
                out.append((t_at_bt(float(e["bt"])), float(e[value_key])))
            except (KeyError, TypeError, ValueError):
                continue

    heater: list = []
    h_dry = phase_pct(plan_data.get("Heater (%) (Dry|Mai|Dev)", ""), 0)
    if h_dry is not None:
        heater.append((0.0, h_dry))
    _collect("Heater Ramp", "heater", heater)
    _collect("Dev Ramp", "heater", heater)

    airflow: list = []
    a_dry = phase_pct(plan_data.get("Airflow (%) (Dry|Mai|Dev)", ""), 0)
    if a_dry is not None:
        airflow.append((0.0, a_dry))
    a_mai = phase_pct(plan_data.get("Airflow (%) (Dry|Mai|Dev)", ""), 1)
    if a_mai is not None and milestones["dry_end"] > 0.0:
        airflow.append((milestones["dry_end"], a_mai))
    _collect("Air Ramp", "airflow", airflow)
    _collect("Dev Ramp", "airflow", airflow)

    def _tidy(points: list) -> list:
        """Chronological, and one value per instant — a later entry for the
        same time wins, so a ramp step overrides the phase feedforward it
        lands on rather than drawing a spike."""
        points.sort(key=lambda p: p[0])
        out: list = []
        for t, v in points:
            if out and abs(out[-1][0] - t) < 1e-6:
                out[-1] = (t, v)
            elif not out or out[-1][1] != v:
                out.append((t, v))
        return out

    return _tidy(heater), _tidy(airflow), milestones


def _plan_secs(text: Any) -> "int | None":
    """'MM:SS' → seconds; None when the text is not a time."""
    try:
        minutes, seconds = str(text).strip().split(':')
        return int(minutes) * 60 + int(seconds)
    except (ValueError, AttributeError):
        return None


def _plan_num(text: Any) -> "float | None":
    try:
        return float(str(text).strip().rstrip('%'))
    except (ValueError, AttributeError):
        return None


def plan_cooled_weight(plan: dict) -> "float | None":
    """Grams the plan expects on the scale after cooling: batch minus target loss."""
    weight, loss = _plan_num(plan.get("Weight")), _plan_num(plan.get("Target Weight Loss"))
    if weight is None or loss is None:
        return None
    return weight * (1.0 - loss / 100.0)


def tasting_change_text(change: dict, unit: str, translate: Translate) -> str:
    """'💡 Last time: <defect> — <change> (<before → after>)' for a plan's "Tasting Change"."""
    mode = 'F' if unit == 'F' else 'C'
    before, after = float(change["before"]), float(change["after"])
    lever = change["lever"]
    if lever.startswith("burner_"):
        values = f"{before:.0f} → {after:.0f} %"
    elif lever == "development_s":
        values = f"{int(before) // 60}:{int(before) % 60:02d} → {int(after) // 60}:{int(after) % 60:02d}"
    else:
        values = f"{before:.0f} → {after:.0f} °{mode}"
    defect = tasting_log.DEFECT_WORDS.get(change["defect"])
    return translate(QT_TRANSLATE_NOOP("tilauscope_roast_setup", "💡 Last taste: {0} — {1} ({2})")).format(
        translate(defect) if defect else "", tasting_log.change_text(change["defect"], mode, translate)[0], values)


def confidence(plan: dict, bean_roasts: int, translate: Translate) -> tuple[str, bool]:
    """What the plan rests on, in words — and whether it is guessing."""
    prev = plan.get("Previous Harvest") or {}
    if prev.get("crop"):
        return translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Built on the {0} harvest ({1} roasts)")).format(
                prev["crop"], prev.get("roasts", 0)), False
    try:
        n = int(plan.get("History Roasts") or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 1:   # a single roast is shown as reference only; the plan starts from the grid
        return translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Based on {0} roasts of this coffee")).format(n), False
    if n == 1 and (plan.get("Reference Roast") or {}).get("status") == "used":  # unless it is the reference
        return translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Based on your reference roast of this coffee")), False
    if bean_roasts == 0:
        return translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup",
            "First roast of this coffee — the plan starts from its characteristics; "
            "expect to adjust after tasting.")), True
    return translate(QT_TRANSLATE_NOOP(
        "tilauscope_roast_setup",
        "No earlier roast of this coffee could be used — the plan starts from its characteristics.")), True


def reference_line(plan: dict, level: str, translate: Callable[[Text], str],
                   short_date: Callable[[int], str] = english_short_date) -> "tuple[str, bool] | None":
    """The reference roast the plan stands on, or why it does not — (text, used); None without one.

    `level` is the roast level asked for (its name), `short_date` writes a day for the roast's name.
    """
    def _name(ref: dict) -> str:
        return roast_name(int(ref.get("epoch") or 0), str(ref.get("batch") or ""), in_sentence=True, short_date=short_date)

    ref = plan.get("Reference Roast") or {}
    status = ref.get("status")
    if not status:
        # Only the calendar is inherited: the burner follows the new lot.
        prev_ref = (plan.get("Previous Harvest") or {}).get("reference_roast") or {}
        if prev_ref.get("status") == "used":
            return translate(QT_TRANSLATE_NOOP(
                "tilauscope_roast_setup",
                "Timings and temperatures from the {0} crop's reference roast ({1}), "
                "until this crop has roasts of its own.")).format(
                    plan["Previous Harvest"].get("crop", ""), _name(prev_ref)), True
        return None
    name = _name(ref)
    if status == "used":
        if ref.get("tasting_change_skipped"):
            return (translate(QT_TRANSLATE_NOOP("tilauscope_roast_setup",
                                                "Based on your reference roast of {0}.")).format(name) + " "
                    + translate(QT_TRANSLATE_NOOP(
                        "tilauscope_roast_setup",
                        "The change asked by the last tasting is not applied: "
                        "going back to the reference is the correction."))), True
        if ref.get("tasting_change_applied"):
            return translate(QT_TRANSLATE_NOOP(
                "tilauscope_roast_setup",
                "Based on your reference roast of {0}, with the change asked by the last tasting.")).format(
                    name), True
        return translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Based on your reference roast of {0}.")).format(name), True
    reason = ref.get("reason")
    if reason == "missing":
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Your reference roast is not used: its roast file was not found."))
    elif status == "no_tasting":
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Your reference roast ({0}) is not used: its tasting was not found.")).format(name)
    elif reason == "excluded":
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Your reference roast ({0}) is not used: it is excluded from learning.")).format(
                name)
    elif status == "not_tasted_yes":
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Your reference roast ({0}) is not used: it was not tasted Yes.")).format(name)
    elif reason == "weight":
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup",
            "Your reference roast ({0}) is not used: it was {1} g and this batch is {2} g.")).format(
                name, f"{float(ref.get('weight_g') or 0):.0f}", f"{float(plan.get('Weight') or 0):.0f}")
    elif reason == "level" and ref.get("level") and level:
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup",
            "Your reference roast ({0}) is not used: it was roasted {1} and this roast is {2}.")).format(
                name, ref["level"], level)
    else:
        text = translate(QT_TRANSLATE_NOOP(
            "tilauscope_roast_setup", "Your reference roast ({0}) is not used for this batch.")).format(name)
    return text, False

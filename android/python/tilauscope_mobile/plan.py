# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roast plan on the tablet: the desktop's engine (tilaucore.roast_plan) over the
tablet's roasts and the computer's, and what the Plan tab of Roast Setup shows of it.

Past roasts are read with the RoR settings of the machine's Artisan setup (.aset), as
the desktop reads them with the settings that setup loaded.
"""

import math
from pathlib import Path

from tilaucore.artisan_compat import fromCtoFstrict
from tilaucore.roast_colour import AGTRON_SCALES, set_whole_to_ground_offset
from tilaucore.roast_plan import ROAST_DESTINATION_KEYS, RoastPlanEngine
from tilaucore.roast_plan_view import (confidence, control_trajectories, english, entry_levels, plan_cooled_weight,
                                      reference_line, tasting_change_text)
from tilaucore.roasters import RoasterManager

from .catalogue import MACHINES
from .machine import setup as machine_setup
from .roasts import Roasts

LEVELS = [scale.name for scale in reversed(AGTRON_SCALES)]  # lightest first, as the desktop lists them
ROOM_DEFAULT = (20.0, 50.0)  # the desktop's room when no probe answers
CURVE_STEP = 5  # seconds between two points sent to the screen
BAND_STEP = 10


class TabletPlan(RoastPlanEngine):
    """The engine reading the tablet's two roast folders as one history."""

    def __init__(self, roasts: Roasts, machine: str | None, beancave_directory: str, destination: str) -> None:
        context = None
        if machine in MACHINES:
            entry = MACHINES[machine]
            context = RoasterManager().get_roast_context(f"{entry['manufacturer']} {entry['model']}")
        super().__init__(context, alog_directory=str(roasts.folder("tablet")),
                         beancave_directory=beancave_directory, roast_destination=destination,
                         ror_settings=machine_setup(machine).ror if machine in MACHINES else None)
        self._roasts = roasts

    def _list_alogs(self):
        return [Path(path) for path in self._roasts.index()]

    def _load_index(self, directory: Path) -> dict:
        return self._roasts.index()


def _mmss(text) -> str:
    """'05:08' → '5:08', as the desktop's roadmap reads."""
    text = str(text or "")
    return text[1:] if len(text) == 5 and text.startswith("0") else text


def _levers(levels: dict, index: int, with_drum: bool) -> str:
    """'Burner 65 % · Air 30 % · Drum 65 %', the desktop roadmap's words."""
    parts = []
    for key, word in (("heater", "Burner"), ("airflow", "Air")):
        values = levels.get(key) or []
        if len(values) > index and values[index] is not None:
            parts.append(f"{word} {values[index]:.0f} %")
    drum = levels.get("drum") or []
    if with_drum and drum and drum[0] is not None:  # the drum is set once, at charge
        parts.append(f"Drum {drum[0]:.0f} %")
    return " · ".join(parts)


def _sampled(values: list, step: int) -> list:
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, 2) for v in values[::step]]


def apply_colour_gap(machine: str | None) -> None:
    """A roast measured whole reads at its estimated ground colour, the gap being the machine's."""
    context = None
    if machine in MACHINES:
        entry = MACHINES[machine]
        context = RoasterManager().get_roast_context(f"{entry['manufacturer']} {entry['model']}")
    set_whole_to_ground_offset(getattr(context, "whole_to_ground_agtron_offset", 0.0))


def generate(engine: TabletPlan, bean, level: str, green_g: float, room: tuple) -> dict:
    """The coffee's plan as the desktop's engine makes it: what the Plan tab shows and a roast follows."""
    scale = next(s for s in AGTRON_SCALES if s.name == level)
    temperature, humidity, altitude, pressure = room
    plan = engine.generate_roast_plan(bean, scale, temperature, humidity, green_g, altitude, None, False, None,
                                      station_pressure=pressure)
    return plan[0] if isinstance(plan, tuple) else plan


def view(engine: TabletPlan, bean, level: str, green_g: float, room: tuple, unit: str = "C") -> dict:
    """The Plan tab: the desktop's roadmap and notes, the planned curve and the band of past roasts."""
    scale = next(s for s in AGTRON_SCALES if s.name == level)
    plan = generate(engine, bean, level, green_g, room)
    levels = entry_levels(plan)
    dev_pct = f"{float(plan.get('Development Phase %')):.0f}"
    rows = [
        {"key": "charge", "label": "CHARGE", "temp": plan.get("Charge Temp"), "time": "",
         "levers": _levers(levels, 0, True)},
        {"key": "dry_end", "label": "DRY END", "temp": plan.get("End of Dry Temp"),
         "time": "~" + _mmss(plan.get("Dry Phase")), "levers": _levers(levels, 1, False)},
        {"key": "fc_start", "label": "FC START", "temp": plan.get("First Crack Temp"),
         "time": "~" + _mmss(plan.get("FC Time")), "levers": _levers(levels, 2, False)},
        {"key": "drop", "label": "DROP", "temp": plan.get("Drop Temp"), "time": "~" + _mmss(plan.get("Total Time")),
         "levers": f"Development {_mmss(plan.get('Development Phase'))} ({dev_pct} %)"},
    ]
    notes = []
    if plan.get("Tasting Change"):
        change = plan["Tasting Change"] # the plan works in °C: a temperature change is worded in the unit shown
        if unit == "F" and not (change["lever"].startswith("burner_") or change["lever"] == "development_s"):
            change = {**change, "before": fromCtoFstrict(float(change["before"])), "after": fromCtoFstrict(float(change["after"]))}
        notes.append({"kind": "tasting", "text": tasting_change_text(change, unit, english)})
    # As the desktop: the ★ line replaces what the plan rests on; a reference not used says why, then that.
    reference = reference_line(plan, level, english)
    if reference is not None and reference[1]:
        notes.append({"kind": "reference", "used": True, "text": reference[0]})
    else:
        text, guessing = confidence(plan, int(getattr(bean, "count", 0) or 0), english)
        if reference is not None:
            notes.append({"kind": "reference", "used": False, "text": reference[0] + " " + text})
        else:
            notes.append({"kind": "warn" if guessing else "info", "text": text})
    cooled = plan_cooled_weight(plan)
    heater, airflow, _ = control_trajectories(plan)
    drum = (levels.get("drum") or [None])[0]
    curve = plan.get("bt_plan_curve") or {}
    graph = (engine._analyze_historical_roasts(bean, scale, green_g) or {}).get("graph") or {}
    return {
        "rows": rows, "notes": notes,
        "cooled": {"loss": plan.get("Target Weight Loss"), "grams": round(cooled) if cooled else None},
        "curve": {"t": _sampled(curve.get("time_min") or [], CURVE_STEP), "bt": _sampled(curve.get("bt_plan") or [], CURVE_STEP),
                  "ror": _sampled(curve.get("ror_plan") or [], CURVE_STEP)},
        # The settings the plan asks for, as the lanes draw them: (minutes from Charge, percent) steps.
        "steps": {"burner": [[round(t, 3), v] for t, v in heater], "air": [[round(t, 3), v] for t, v in airflow],
                  "drum": [[0.0, drum]] if drum is not None else []},
        "marks": {w["key"]: round(w["time_min"], 3) for w in curve.get("waypoints") or []
                  if w.get("key") in ("dry_end", "fc_start", "drop")},
        "band": {key: _sampled(graph.get(key) or [], BAND_STEP)
                 for key in ("time_min", "bt_min", "bt_max", "bt_mean", "ror_min", "ror_max", "ror_mean")}
                if graph.get("time_min") else None,
    }


__all__ = ["LEVELS", "ROAST_DESTINATION_KEYS", "ROOM_DEFAULT", "TabletPlan", "generate", "view"]

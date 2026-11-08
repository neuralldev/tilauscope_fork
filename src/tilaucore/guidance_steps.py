# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The lever steps the plan asks for, and the one due now, for the guided mode.

A step is (BT, 'burner' | 'air', %). The screen reads the levers and gives them here as
plain values, so the desktop and the tablet ask for the same steps at the same BT.
"""

from __future__ import annotations

from typing import Final

DEV_STAGE: Final[int] = 5   # % moved at a time by hand in development

Step = tuple[float, str, int]


def plan_steps(plan: dict | None) -> list[Step]:
    """Every lever step the plan asks for, as (BT, 'burner' | 'air', %), in BT order. By hand
    the development levers move in whole stages, once the plan has drifted that far."""
    steps: list[Step] = []
    dev_steps: dict[str, list[tuple[float, int]]] = {"burner": [], "air": []}
    for key in ("Heater Ramp", "Air Ramp", "Dev Ramp"):
        for entry in (plan or {}).get(key) or []:
            try:
                threshold = float(entry["bt"])
                if entry.get("heater") is not None:
                    if key == "Dev Ramp":
                        dev_steps["burner"].append((threshold, int(entry["heater"])))
                    else:
                        steps.append((threshold, "burner", int(entry["heater"])))
                if entry.get("airflow") is not None:
                    if key == "Dev Ramp":
                        dev_steps["air"].append((threshold, int(entry["airflow"])))
                    else:
                        steps.append((threshold, "air", int(entry["airflow"])))
            except (TypeError, ValueError, KeyError):
                continue
    steps.sort(key=lambda step: step[0])
    for lever, ramp in dev_steps.items():
        held = next((step[2] for step in reversed(steps) if step[1] == lever), None)
        for threshold, pct in sorted(ramp):
            if held is None:
                held = pct
            elif abs(pct - held) >= DEV_STAGE:
                held += DEV_STAGE if pct > held else -DEV_STAGE
            else:
                continue
            steps.append((threshold, lever, held))
    return sorted(steps, key=lambda step: step[0])


def no_burner_step(due: Step | None, crashing: bool) -> Step | None:
    """A crash has its own message: no burner move is asked for against it."""
    return None if crashing and due is not None and due[1] == "burner" else due


class GestureTrack:
    """One roast's way up the plan. BT only counts going up, and a step is asked for once:
    a probe dip or a replan never brings back a step already behind the bean."""

    def __init__(self) -> None:
        self.peak: float | None = None
        self.pending: dict[str, Step] = {}


def ror_above(ror: float | None, target: float) -> bool:
    return ror is not None and target > 0 and ror > target


def gesture_steps(track: GestureTrack, steps: list[Step], bt: float, window: float,
                  held: dict[str, float | None], step_size: dict[str, float],
                  ror_high: bool = False) -> tuple[Step | None, Step | None]:
    """(step due now, next step that changes a lever), burner first.

    `window` is how near the bean must be to a step's BT (native units); `held` is each
    lever's value read back, None when the machine gives none: such a lever gets its step
    while the bean is on it. A step up on the burner waits while the RoR is already too high.
    """
    for step in steps:
        if step[0] <= bt + window and (track.peak is None or step[0] > track.peak):
            track.pending[step[1]] = step
    track.peak = max(bt + window, track.peak if track.peak is not None else bt + window)
    due = None
    current: dict[str, float | None] = {}
    for lever in ("air", "burner"):
        value = held.get(lever)
        current[lever] = value
        step = track.pending.get(lever)
        if step is None:
            continue
        size = step_size[lever]
        if (value is None and bt > step[0] + window * 2) or (
                value is not None and (abs(value - round(step[2] / size) * size) < 1
                                       or (lever == "air" and step[2] < value))):
            del track.pending[lever]
        elif not (ror_high and lever == "burner" and value is not None and step[2] > value):
            due = step
            current[lever] = step[2]
    return due, next((step for step in steps
                      if step[0] > track.peak and step[2] != current[step[1]]), None)

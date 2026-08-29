# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure, user-facing semantics for Artisan's software PID.

The module deliberately has no Qt dependency.  The UI observes engineering
values, but operators act on behaviours: react, catch up, brake and stabilise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal


SemanticState = Literal[
    "stopped",
    "unavailable",
    "power_limited",
    "coasting",
    "oscillating",
    "braking",
    "catching_up",
    "accelerating",
    "above_target",
    "holding",
]

Behaviour = Literal["reaction", "recovery", "braking", "stability"]


@dataclass(frozen=True, slots=True)
class PIDObservation:
    active: bool
    valid: bool
    error_c: float = 0.0
    ror_c_per_min: float = 0.0
    output_pct: float | None = None
    output_min_pct: float = 0.0
    output_max_pct: float = 100.0
    p_term: float = 0.0
    i_term: float = 0.0
    d_term: float = 0.0
    recent_errors_c: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class PIDNarrative:
    state: SemanticState
    confidence: Literal["low", "medium", "high"]


def _zero_crossings(values: tuple[float, ...], deadband: float = 0.35) -> int:
    signs: list[int] = []
    for value in values:
        if value > deadband:
            sign = 1
        elif value < -deadband:
            sign = -1
        else:
            continue
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return max(0, len(signs) - 1)


def narrate_pid(observation: PIDObservation) -> PIDNarrative:
    """Classify the controller's behaviour without exposing PID vocabulary."""
    o = observation
    if not o.active:
        return PIDNarrative("stopped", "high")
    if not o.valid:
        return PIDNarrative("unavailable", "high")

    output_span = max(1.0, o.output_max_pct - o.output_min_pct)
    saturation_margin = max(1.0, output_span * 0.02)
    if (
        o.output_pct is not None
        and o.output_pct >= o.output_max_pct - saturation_margin
        and o.error_c > 1.0
    ):
        return PIDNarrative("power_limited", "high")

    if o.output_pct is not None:  # noqa: SIM102 - keeps Optional narrowing clear
        at_minimum = o.output_pct <= o.output_min_pct + saturation_margin
        still_rising = o.ror_c_per_min > 1.0
        near_target = o.error_c <= 1.0
        if at_minimum and still_rising and near_target:
            return PIDNarrative("coasting", "high")

    if (
        len(o.recent_errors_c) >= 6
        and _zero_crossings(o.recent_errors_c) >= 3
        and max(o.recent_errors_c) - min(o.recent_errors_c) >= 1.5
    ):
        return PIDNarrative("oscillating", "medium")

    if o.error_c > 1.0:
        meaningful_brake = o.d_term < -max(0.5, abs(o.p_term) * 0.10)
        if o.ror_c_per_min > 1.0 and meaningful_brake:
            return PIDNarrative("braking", "high")
        meaningful_recovery = o.i_term > max(1.0, abs(o.p_term) * 0.20)
        if meaningful_recovery:
            return PIDNarrative("catching_up", "medium")
        return PIDNarrative("accelerating", "high")

    if o.error_c < -1.0:
        return PIDNarrative("above_target", "high")

    return PIDNarrative("holding", "medium")


_GAIN_KEYS: Final[dict[Behaviour, tuple[str, str, str]]] = {
    "reaction": ("pidKp", "pidKp1", "pidKp2"),
    "recovery": ("pidKi", "pidKi1", "pidKi2"),
    "braking": ("pidKd", "pidKd1", "pidKd2"),
    "stability": ("", "", ""),
}


def closest_schedule_anchor(
    schedule: tuple[float, float, float], value: float, quadratic: bool
) -> int:
    count = 3 if quadratic else 2
    return min(range(count), key=lambda idx: abs(schedule[idx] - value))


def adjust_pid_behaviour(
    config: Mapping[str, float | int | bool],
    behaviour: Behaviour,
    direction: int,
    *,
    all_zones: bool,
    schedule_value: float,
    mode: str,
) -> dict[str, float | int | bool]:
    """Return a bounded one-notch adjustment of a PID configuration.

    ``direction`` means more of reaction/recovery/braking.  For stability it
    means calmer (+1) versus more active (-1).  The caller applies the returned
    configuration atomically and owns undo/rollback.
    """
    if direction not in {-1, 1}:
        raise ValueError("direction must be -1 or +1")
    updated = dict(config)

    if behaviour == "stability":
        steps = int(updated.get("dutySteps", 1))
        duty_filter = bool(updated.get("duty_filter", False))
        if direction > 0:  # calmer
            if steps < 10:
                updated["dutySteps"] = steps + 1
            else:
                updated["duty_filter"] = True
        elif duty_filter:  # more active
            updated["duty_filter"] = False
        else:
            updated["dutySteps"] = max(1, steps - 1)
        return updated

    scheduling = bool(updated.get("pidGainScheduling", False))
    if scheduling and not all_zones:
        schedule = (
            float(updated.get("pidSchedule0", 0.0)),
            float(updated.get("pidSchedule1", 0.0)),
            float(updated.get("pidSchedule2", 0.0)),
        )
        indices = (
            closest_schedule_anchor(
                schedule,
                schedule_value,
                bool(updated.get("pidGainSchedulingQuadratic", False)),
            ),
        )
    else:
        indices = (0, 1, 2) if scheduling else (0,)

    keys = _GAIN_KEYS[behaviour]
    # Relative notches preserve the machine-specific scale.  A non-zero floor
    # lets the operator add recovery/braking to a configuration where it is off.
    factors = {
        "reaction": 1.10,
        "recovery": 1.20,
        "braking": 1.15,
    }
    factor = factors[behaviour]
    floor_c = {"reaction": 0.1, "recovery": 0.002, "braking": 1.0}[behaviour]
    floor = floor_c if mode == "C" else floor_c / 1.8

    for index in indices:
        key = keys[index]
        current = float(updated.get(key, 0.0))
        if direction > 0:
            value = floor if current == 0.0 else current * factor
        else:
            # A gain introduced from zero by one positive notch must return to
            # zero when the operator moves the same behaviour back one notch.
            value = 0.0 if current == floor else current / factor
        updated[key] = max(0.0, min(9999.0, value))
    return updated

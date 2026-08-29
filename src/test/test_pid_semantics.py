from __future__ import annotations

import pytest

from tilauscope.pid_semantics import (
    Behaviour,
    PIDObservation,
    adjust_pid_behaviour,
    narrate_pid,
)


def _observation(**overrides: object) -> PIDObservation:
    values: dict[str, object] = {
        "active": True,
        "valid": True,
        "error_c": 4.0,
        "ror_c_per_min": 0.5,
        "output_pct": 50.0,
        "output_min_pct": 0.0,
        "output_max_pct": 80.0,
        "p_term": 20.0,
        "i_term": 0.0,
        "d_term": 0.0,
    }
    values.update(overrides)
    return PIDObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "state"),
    [
        ({"active": False}, "stopped"),
        ({"valid": False}, "unavailable"),
        ({"output_pct": 80.0}, "power_limited"),
        ({"ror_c_per_min": 8.0, "d_term": -5.0}, "braking"),
        ({"i_term": 8.0}, "catching_up"),
        ({}, "accelerating"),
        ({"error_c": -3.0}, "above_target"),
        ({"error_c": 0.2}, "holding"),
    ],
)
def test_narrative_states(overrides: dict[str, object], state: str) -> None:
    assert narrate_pid(_observation(**overrides)).state == state


def test_narrative_detects_oscillation_before_normal_tracking() -> None:
    observation = _observation(
        error_c=0.8,
        recent_errors_c=(2.0, -1.8, 1.7, -1.6, 1.5, -1.4),
    )
    assert narrate_pid(observation).state == "oscillating"


def _config() -> dict[str, float | int | bool]:
    return {
        "pidKp": 10.0,
        "pidKi": 0.1,
        "pidKd": 20.0,
        "pidKp1": 8.0,
        "pidKi1": 0.08,
        "pidKd1": 30.0,
        "pidKp2": 6.0,
        "pidKi2": 0.06,
        "pidKd2": 40.0,
        "pidGainScheduling": False,
        "pidGainSchedulingQuadratic": False,
        "pidSchedule0": 95.0,
        "pidSchedule1": 150.0,
        "pidSchedule2": 185.0,
        "dutySteps": 1,
        "duty_filter": False,
    }


def test_reaction_notch_changes_only_base_gain_without_scheduling() -> None:
    changed = adjust_pid_behaviour(
        _config(), "reaction", 1, all_zones=False, schedule_value=120.0, mode="C"
    )
    assert changed["pidKp"] == pytest.approx(11.0)
    assert changed["pidKp1"] == 8.0
    assert changed["pidKp2"] == 6.0


def test_local_scheduled_notch_changes_closest_anchor_only() -> None:
    config = _config()
    config["pidGainScheduling"] = True
    changed = adjust_pid_behaviour(
        config, "braking", -1, all_zones=False, schedule_value=146.0, mode="C"
    )
    assert changed["pidKd"] == 20.0
    assert changed["pidKd1"] == pytest.approx(30.0 / 1.15)
    assert changed["pidKd2"] == 40.0


def test_all_zones_adjusts_each_scheduled_gain() -> None:
    config = _config()
    config["pidGainScheduling"] = True
    changed = adjust_pid_behaviour(
        config, "recovery", 1, all_zones=True, schedule_value=150.0, mode="C"
    )
    assert changed["pidKi"] == pytest.approx(0.12)
    assert changed["pidKi1"] == pytest.approx(0.096)
    assert changed["pidKi2"] == pytest.approx(0.072)


def test_braking_can_be_enabled_from_zero_and_respects_fahrenheit_scale() -> None:
    config = _config()
    config["pidKd"] = 0.0
    changed = adjust_pid_behaviour(
        config, "braking", 1, all_zones=False, schedule_value=150.0, mode="F"
    )
    assert changed["pidKd"] == pytest.approx(1.0 / 1.8)

    restored = adjust_pid_behaviour(
        changed, "braking", -1, all_zones=False, schedule_value=150.0, mode="F"
    )
    assert restored["pidKd"] == 0.0


@pytest.mark.parametrize("behaviour", ["reaction", "recovery", "braking"])
def test_opposite_notches_return_to_the_starting_gain(behaviour: Behaviour) -> None:
    config = _config()
    stronger = adjust_pid_behaviour(
        config, behaviour, 1, all_zones=False, schedule_value=120.0, mode="C"
    )
    restored = adjust_pid_behaviour(
        stronger, behaviour, -1, all_zones=False, schedule_value=120.0, mode="C"
    )
    key = {"reaction": "pidKp", "recovery": "pidKi", "braking": "pidKd"}[behaviour]
    assert restored[key] == pytest.approx(config[key])


def test_stability_uses_command_step_then_filter_and_is_reversible() -> None:
    config = _config()
    calmer = adjust_pid_behaviour(
        config, "stability", 1, all_zones=False, schedule_value=0.0, mode="C"
    )
    assert calmer["dutySteps"] == 2
    assert calmer["duty_filter"] is False

    calmer["dutySteps"] = 10
    filtered = adjust_pid_behaviour(
        calmer, "stability", 1, all_zones=False, schedule_value=0.0, mode="C"
    )
    assert filtered["duty_filter"] is True

    active = adjust_pid_behaviour(
        filtered, "stability", -1, all_zones=False, schedule_value=0.0, mode="C"
    )
    assert active["duty_filter"] is False
    assert active["dutySteps"] == 10

"""P0 acceptance tests for the Skywalker V2 roast-plan revision."""

from __future__ import annotations

import pytest

from tilauscope.roast_plan_model import (
    TilauScopeRoastPlan,
    _fit_fc_charge_regression,
    _heater_authority_notes,
    _learning_log_is_eligible,
    _selected_roast_color,
)


@pytest.mark.parametrize(("extra", "eligible"), [
    ({}, True),
    ({"tilau_exclude_learning": False}, True),
    ({"tilau_exclude_learning": True}, False),
    ({"tilau_simulated": True}, False),
    ({"tilau_simulated": True, "tilau_exclude_learning": False}, False),
])
def test_learning_flags_are_legacy_compatible(extra: dict, eligible: bool) -> None:
    data = {"computed": {"ambient_temperature": 20.0, "ambient_humidity": 50.0}, **extra}
    assert _learning_log_is_eligible(data) is eligible


@pytest.mark.parametrize(("temperature", "humidity"), [
    (555.0, 50.0), (-11.0, 50.0), (61.0, 50.0), (20.0, 0.0), (20.0, 101.0),
])
def test_aberrant_ambient_readings_are_rejected(temperature: float, humidity: float) -> None:
    data = {"computed": {"ambient_temperature": temperature, "ambient_humidity": humidity}}
    assert not _learning_log_is_eligible(data)


def test_ground_colour_has_priority_over_the_lighter_maximum() -> None:
    assert _selected_roast_color({"whole_color": 71.3, "ground_color": 73.1}) == (73.1, "ground")


def test_whole_colour_is_only_a_fallback() -> None:
    assert _selected_roast_color({"whole_color": 71.3, "ground_color": 0}) == (71.3, "whole")
    assert _selected_roast_color({}) == (None, None)


def test_fc_regression_refuses_three_points() -> None:
    assert _fit_fc_charge_regression([170, 180, 190], [195, 196, 197])["status"] == "refused"


def test_fc_regression_refuses_a_narrow_charge_range() -> None:
    result = _fit_fc_charge_regression([180, 181, 182, 183, 184], [195, 196, 197, 198, 199])
    assert result["status"] == "refused"
    assert result["charge_range_c"] == 4.0


def test_fc_regression_must_beat_leave_one_out_median() -> None:
    result = _fit_fc_charge_regression([170, 175, 180, 185, 190], [195, 197, 196, 197, 195])
    assert result["status"] == "refused"
    assert result["regression_mae_c"] is not None
    assert result["baseline_mae_c"] is not None


def test_pre_fc_low_authority_warns_without_clamping() -> None:
    values = [80.0, 60.0, 43.0]
    notes = _heater_authority_notes(values, 45.0, 50.0)
    assert values[-1] == 43.0
    assert notes and "low-authority" in notes[0]


def test_development_value_is_not_part_of_the_authority_check() -> None:
    assert _heater_authority_notes([80.0, 60.0, 50.0], 45.0, 50.0) == []


def test_valid_245_maillard_is_not_raised_to_three_minutes(plan_model: TilauScopeRoastPlan) -> None:
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=4.0, total_time_min=8.75, dev_time_min=2.0,
        drying_time_band=(3.5, 5.0), maillard_time_band=(2.5, 4.0),
        t_dry_raw=4.0, t_fc_raw=6.75, t_n=3,
        charge_weight_g=200.0, batch_optimal_g=400.0, thermal_inertia=0.45)
    assert result.maillard_time_min == pytest.approx(2.75)


def test_history_support_never_tightens_tolerance_below_one() -> None:
    result = TilauScopeRoastPlan._resolve_plan_confidence(
        fc_source="learned (n=5)", timing_source="learned (n=5)",
        drop_source="learned (n=5)", fc_bt_mad_c=0.2,
        soak_dcharge_c=0.0, soak_dheater_pct=0,
        minutes_since_last_drop=None, ror_scale=1.0)
    assert result.display == "consistent history"
    assert result.tol_factor == 1.0

"""P2 acceptance tests for pre-roast snapshots and predictive errors."""

from __future__ import annotations

import copy

from artisanlib.atypes import ProfileData
from tilauscope.roast_plan_snapshot import (
    ROAST_PLAN_MODEL_VERSION,
    build_prediction_snapshot,
    complete_prediction_snapshot,
    summarize_prediction_errors,
)


def test_snapshot_does_not_extend_artisan_profiledata_contract() -> None:
    assert "tilau_roast_plan_snapshot" not in ProfileData.__annotations__


def _plan(source: str = "grid") -> dict:
    return {
        "History Profile Source": source,
        "Phase Timing Source": source,
        "FC Temp Source": source,
        "Drop Temp Source": source,
        "Heater Source": source,
        "Dev Profile Source": source,
        "Dry Phase": "05:00",
        "FC Time": "09:00",
        "Total Time": "11:00",
        "End of Dry Temp": "150.0",
        "First Crack Temp": "190.0",
        "Drop Temp": "202.0",
        "Heater (%) (Dry|Mai|Dev)": "75% | 60% | 50%",
        "Airflow (%) (Dry|Mai|Dev)": "20% | 35% | 50%",
    }


def _snapshot(source: str = "grid") -> dict:
    return build_prediction_snapshot(
        _plan(source), plan_id="roast-123", target_color_agtron=55.0,
        expected_color_basis="ground", created_at_utc="2026-08-09T10:00:00+00:00")


def test_snapshot_freezes_version_sources_milestones_color_and_controls() -> None:
    snapshot = _snapshot("medoid (n=3)")
    assert snapshot["plan_id"] == "roast-123"
    assert snapshot["model_version"] == ROAST_PLAN_MODEL_VERSION
    assert snapshot["source_kinds"] == ["history", "medoid"]
    assert snapshot["predicted"]["milestones"] == {
        "dry_end": {"time_s": 300.0, "bt_c": 150.0},
        "first_crack": {"time_s": 540.0, "bt_c": 190.0},
        "drop": {"time_s": 660.0, "bt_c": 202.0},
    }
    assert snapshot["predicted"]["target_color_agtron"] == 55.0
    assert snapshot["predicted"]["expected_color_basis"] == "ground"
    assert snapshot["predicted"]["controls"]["dry_end"] == {
        "heater_pct": 75.0, "airflow_pct": 20.0}


def test_snapshot_uses_the_last_planned_ramp_values_at_fc_and_drop() -> None:
    plan = _plan()
    plan["Heater Ramp"] = [{"heater": 55}, {"heater": 52}]
    plan["Air Ramp"] = [{"airflow": 40}]
    plan["Dev Ramp"] = [{"heater": 48}, {"airflow": 55}, {"heater": 46}]
    snapshot = build_prediction_snapshot(
        plan, plan_id="ramp", target_color_agtron=55.0,
        created_at_utc="2026-08-09T10:00:00+00:00")
    assert snapshot["predicted"]["controls"]["first_crack"] == {
        "heater_pct": 52.0, "airflow_pct": 40.0}
    assert snapshot["predicted"]["controls"]["drop"] == {
        "heater_pct": 46.0, "airflow_pct": 55.0}


def test_two_roast_source_records_grid_history_and_blend() -> None:
    assert _snapshot("grid/profile blend (n=2)")["source_kinds"] == [
        "grid", "history", "blend"]


def test_completion_preserves_prediction_and_calculates_all_absolute_errors() -> None:
    snapshot = _snapshot()
    frozen_prediction = copy.deepcopy(snapshot["predicted"])
    completed = complete_prediction_snapshot(snapshot, {
        "mode": "C",
        "computed": {
            "DRY_time": 312.0, "DRY_BT": 151.5,
            "FCs_time": 550.0, "FCs_BT": 188.0,
            "DROP_time": 675.0, "DROP_BT": 205.0,
        },
        "whole_color": 52.0,
        "ground_color": 58.0,
        "color_system": "Agtron",
    })
    assert snapshot["actual"] == {}
    assert completed["predicted"] == frozen_prediction
    assert completed["status"] == "completed"
    assert completed["errors"]["milestones"]["dry_end"] == {
        "absolute_time_s": 12.0, "absolute_bt_c": 1.5}
    assert completed["errors"]["milestones"]["first_crack"] == {
        "absolute_time_s": 10.0, "absolute_bt_c": 2.0}
    assert completed["errors"]["milestones"]["drop"] == {
        "absolute_time_s": 15.0, "absolute_bt_c": 3.0}
    assert completed["errors"]["color_agtron"] == {"whole": 3.0, "ground": 3.0}


def test_completion_normalizes_fahrenheit_bt_errors_to_celsius() -> None:
    completed = complete_prediction_snapshot(_snapshot(), {
        "mode": "F",
        "computed": {"DROP_time": 660.0, "DROP_BT": 395.6},
        "whole_color": 0.0, "ground_color": 0.0,
    })
    assert completed["actual"]["milestones"]["drop"]["bt_c"] == 202.0
    assert completed["errors"]["milestones"]["drop"]["absolute_bt_c"] == 0.0
    assert completed["errors"]["color_agtron"] == {}


def test_summary_keeps_whole_and_ground_color_mae_separate() -> None:
    first = complete_prediction_snapshot(_snapshot(), {
        "mode": "C", "computed": {"DROP_time": 670.0, "DROP_BT": 204.0},
        "whole_color": 50.0, "ground_color": 58.0, "color_system": "Agtron"})
    second = complete_prediction_snapshot(_snapshot(), {
        "mode": "C", "computed": {"DROP_time": 680.0, "DROP_BT": 206.0},
        "whole_color": 54.0, "ground_color": 61.0, "color_system": "Agtron"})
    second["plan_id"] = "roast-456"
    legacy = copy.deepcopy(first)
    legacy["plan_id"] = "legacy"
    legacy["model_version"] = "old-model"
    summary = summarize_prediction_errors([first, second, legacy, {"errors": {}}])
    assert summary["model_version"] == ROAST_PLAN_MODEL_VERSION
    assert summary["snapshot_count"] == 2
    metrics = summary["metrics"]
    assert metrics["drop.absolute_time_s"] == {"n": 2, "mae": 15.0}
    assert metrics["drop.absolute_bt_c"] == {"n": 2, "mae": 3.0}
    assert metrics["color_agtron.whole"] == {"n": 2, "mae": 3.0}
    assert metrics["color_agtron.ground"] == {"n": 2, "mae": 4.5}

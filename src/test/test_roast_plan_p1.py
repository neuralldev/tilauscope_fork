"""P1 acceptance tests for coherent historical roast selection."""

from __future__ import annotations

import copy

from tilauscope.roast_plan_model import (
    _PlanSource,
    TilauScopeRoastPlan,
    _choose_coherent_history,
    _select_cohort_medoid,
)


def _profile(identifier: str, offset: float = 0.0, *, basis: str = "ground",
             mass: float = 400.0, agtron: float = 55.0) -> dict:
    return {
        "id": identifier, "color_basis": basis, "batch_g": mass, "agtron": agtron,
        "dry_time_min": 5.0 + offset,
        "maillard_time_min": 4.0 + offset,
        "dev_time_min": 2.0 + offset / 2.0,
        "heater_dry": 75.0 + offset,
        "heater_maillard": 65.0 + offset,
        "heater_dev": 48.0 + offset,
        "heater_fc": 52.0 + offset,
        "airflow_dry": 25.0 + offset,
        "airflow_maillard": 35.0 + offset,
        "airflow_dev": 50.0 + offset,
        "fc_bt_c": 190.0 + offset,
        "drop_bt_c": 202.0 + offset,
        "drop_ror_c": 5.0 + offset / 2.0,
        "dev_trajectory": {0: {0.25: 40.0 + offset, 0.75: 50.0 + offset},
                           3: {0.25: 50.0 + offset, 0.75: 45.0 + offset}},
    }


def test_medoid_is_one_real_roast_not_a_synthetic_coordinate_median() -> None:
    profiles = [_profile("cold", -2.0), _profile("central", 0.0), _profile("hot", 5.0)]
    selected = _select_cohort_medoid(profiles)
    assert selected is not None
    assert selected["id"] == "central"
    original = next(profile for profile in profiles if profile["id"] == selected["id"])
    for key in ("dry_time_min", "maillard_time_min", "heater_dry", "heater_dev",
                "airflow_dev", "drop_bt_c", "drop_ror_c", "dev_trajectory"):
        assert selected[key] == original[key]


def test_medoid_is_robust_to_the_different_units_of_time_temperature_and_percent() -> None:
    profiles = [_profile("a", -1.0), _profile("b", 0.0), _profile("c", 1.0)]
    profiles[0]["drop_bt_c"] -= 30.0
    profiles[2]["drop_bt_c"] += 30.0
    assert _select_cohort_medoid(profiles)["id"] == "b"


def test_medoid_does_not_mutate_the_candidate_roasts() -> None:
    profiles = [_profile("a", -1.0), _profile("b"), _profile("c", 1.0)]
    before = copy.deepcopy(profiles)
    _select_cohort_medoid(profiles)
    assert profiles == before


def test_zero_observations_use_the_grid() -> None:
    selected, count, source, basis = _choose_coherent_history([], 400.0, 55.0)
    assert (selected, count, basis) == (None, 0, None)
    assert source.key == "grid"


def test_one_observation_is_reference_only() -> None:
    selected, count, source, _ = _choose_coherent_history([_profile("only")], 400.0, 55.0)
    assert selected["id"] == "only"
    assert count == 1
    assert source.key == "reference"
    assert source.label == "reference only (n=1)"   # what the plan prints


def test_two_observations_choose_one_real_roast_for_the_grid_blend() -> None:
    profiles = [_profile("near", mass=390.0, agtron=55.0),
                _profile("far", mass=310.0, agtron=59.0)]
    selected, count, source, _ = _choose_coherent_history(profiles, 400.0, 55.0)
    assert selected["id"] == "near"
    assert count == 2
    assert source.key == "blend"
    assert source.label == "grid/profile blend (n=2)"


def test_three_observations_use_the_medoid() -> None:
    selected, count, source, _ = _choose_coherent_history(
        [_profile("low", -2.0), _profile("middle"), _profile("high", 3.0)], 400.0, 55.0)
    assert selected["id"] == "middle"
    assert count == 3
    assert source.key == "learned"
    assert source.label == "medoid (n=3)"


def test_ground_cohort_is_preferred_without_pooling_whole_measurements() -> None:
    profiles = [_profile("ground-a", -1.0), _profile("ground-b", 1.0),
                _profile("whole", 0.0, basis="whole")]
    selected, count, _, basis = _choose_coherent_history(profiles, 400.0, 55.0)
    assert basis == "ground"
    assert count == 2
    assert selected["id"].startswith("ground-")


def test_whole_cohort_is_used_when_ground_has_fewer_than_two_complete_roasts() -> None:
    profiles = [_profile("ground", basis="ground"),
                _profile("whole-a", -1.0, basis="whole"),
                _profile("whole-b", 1.0, basis="whole")]
    selected, count, _, basis = _choose_coherent_history(profiles, 400.0, 55.0)
    assert basis == "whole"
    assert count == 2
    assert selected["id"].startswith("whole-")


# ── Graded fallback: the thermal skeleton alone ──────────────────────────────
# A roast that logged no sliders is sparse, not broken. It still knows where
# this coffee cracks and finishes. Consulted ONLY below two complete profiles,
# i.e. exactly where the plan would otherwise be pure grid.

def _skeleton(name: str, fc: float, drop: float, **over: object) -> dict:
    profile = {"id": name, "batch_g": 400.0, "agtron": 55.0, "color_basis": "ground",
               "dry_time_min": 5.0, "maillard_time_min": 4.5, "dev_time_min": 2.4,
               "fc_bt_c": fc, "drop_bt_c": drop, "drop_ror_c": 5.0}
    profile.update(over)
    return profile


def _complete(name: str, fc: float, drop: float) -> dict:
    return _skeleton(name, fc, drop, heater_dry=72.0, heater_maillard=62.0,
                     heater_dev=45.0, heater_fc=49.0, heater_de=67.0,
                     airflow_dry=20.0, airflow_maillard=30.0, airflow_dev=40.0,
                     dev_trajectory={0: {0.75: 40.0}}, pre_de_descent=(90.0, 2.0))


def test_a_skeleton_cohort_still_carries_the_thermal_targets() -> None:
    """No complete profile at all: the plan used to fall entirely back to the
    grid, discarding first crack and phase timings it had measured."""
    selected, count, source, basis = _choose_coherent_history(
        [_skeleton("a", 196.0, 212.0), _skeleton("b", 197.0, 213.0)], 400.0, 55.0)
    assert count == 2 and basis == "ground"
    assert selected is not None and selected["fc_bt_c"] in (196.0, 197.0)
    assert "heater_dry" not in selected


def test_the_skeleton_source_scores_as_partial_history() -> None:
    """Learned from a real roast, but the plan knows nothing of the hand that
    produced it — neither grid-only nor a fully supported plan."""
    result = TilauScopeRoastPlan._resolve_plan_confidence(
        fc_source=_PlanSource("skeleton", 3, "skeleton (n=3)"), timing_source=_PlanSource("skeleton", 3, "skeleton (n=3)"),
        drop_source=_PlanSource("skeleton", 3, "skeleton (n=3)"), fc_bt_mad_c=0.4,
        soak_dcharge_c=0.0, soak_dheater_pct=0,
        minutes_since_last_drop=None, ror_scale=1.0)
    assert result.level == "partial history"
    assert result.tol_factor == 1.0


def test_a_complete_cohort_is_never_displaced_by_skeleton_roasts() -> None:
    """The guard that makes the tier safe: with two complete profiles the
    skeleton branch must not run at all, so a plan that already learns the
    burner and the airflow can never be quietly downgraded."""
    complete = [_complete("a", 196.0, 212.0), _complete("b", 197.0, 213.0)]
    selected, count, _source, _basis = _choose_coherent_history(complete, 400.0, 55.0)
    assert count == 2
    assert selected is not None and selected["heater_dry"] == 72.0

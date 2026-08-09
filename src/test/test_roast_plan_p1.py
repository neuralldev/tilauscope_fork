"""P1 acceptance tests for coherent historical roast selection."""

from __future__ import annotations

import copy

from tilauscope.roast_plan_model import (
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
    assert (selected, count, source, basis) == (None, 0, "grid", None)


def test_one_observation_is_reference_only() -> None:
    selected, count, source, _ = _choose_coherent_history([_profile("only")], 400.0, 55.0)
    assert selected["id"] == "only"
    assert count == 1
    assert source == "reference only (n=1)"


def test_two_observations_choose_one_real_roast_for_the_grid_blend() -> None:
    profiles = [_profile("near", mass=390.0, agtron=55.0),
                _profile("far", mass=310.0, agtron=59.0)]
    selected, count, source, _ = _choose_coherent_history(profiles, 400.0, 55.0)
    assert selected["id"] == "near"
    assert count == 2
    assert source == "grid/profile blend (n=2)"


def test_three_observations_use_the_medoid() -> None:
    selected, count, source, _ = _choose_coherent_history(
        [_profile("low", -2.0), _profile("middle"), _profile("high", 3.0)], 400.0, 55.0)
    assert selected["id"] == "middle"
    assert count == 3
    assert source == "medoid (n=3)"


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

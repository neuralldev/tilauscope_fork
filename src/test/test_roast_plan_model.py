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

"""L1 — the roast plan model's pure decision logic.

These are the functions where a regression is invisible until a roast comes out
wrong: back-to-back charge correction, the learned-vs-grid adoption policy,
phase attribution, turning-point location, curve construction.

Style note: assertions target the *law*, not the current numbers, wherever the
numbers are tuning values. A test that pins a tuning constant would fail on
every legitimate model improvement and teach us to ignore the suite.
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from tilauscope.roast_plan_model import TilauScopeRoastPlan, heat_soak_correction
from tilauscope.tilauscope_types import AGTRON_SCALES

# scipy/PCHIP work is slow enough that hypothesis' default deadline is noise.
_PROPERTY = settings(
    max_examples=60, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ── heat_soak_correction — back-to-back charge correction ────────────────────

def test_heat_soak_full_soak_at_immediate_recharge() -> None:
    """Charging straight after a DROP applies the full documented correction."""
    dcharge, dheater, tau = heat_soak_correction(0.0, 0.5, 0.5)
    assert dcharge == pytest.approx(-7.0)   # -(4 + 6*0.5) * soak(=1)
    assert dheater == -5                    # -round(5 * 1)
    assert tau == pytest.approx(27.0)       # 12 + 30*0.5


def test_heat_soak_decays_to_neutral_after_a_long_wait() -> None:
    """Below 5 % soak the machine is considered thermally neutral again."""
    _, _, tau = heat_soak_correction(0.0, 0.5, 0.5)
    # soak < 0.05  <=>  minutes > tau * ln(20)
    long_wait = tau * math.log(20.0) + 1.0
    assert heat_soak_correction(long_wait, 0.5, 0.5) == (0.0, 0, pytest.approx(tau))


def test_heat_soak_charge_correction_has_a_hard_floor() -> None:
    """The worst case (cast-iron drum, instant recharge) stops at -10 °C."""
    dcharge, _, _ = heat_soak_correction(0.0, 1.0, 1.0)
    assert dcharge == pytest.approx(-10.0)


def test_heat_soak_clamps_out_of_range_machine_ratios() -> None:
    """Nonsensical thermal_mass / heat_retention are clamped, not propagated."""
    assert heat_soak_correction(0.0, 5.0, 5.0) == heat_soak_correction(0.0, 1.0, 1.0)
    assert heat_soak_correction(0.0, -3.0, -3.0) == heat_soak_correction(0.0, 0.0, 0.0)


def test_heat_soak_treats_negative_wait_as_immediate() -> None:
    assert heat_soak_correction(-30.0, 0.4, 0.6) == heat_soak_correction(0.0, 0.4, 0.6)


def test_heat_soak_correction_shrinks_as_the_wait_grows() -> None:
    """Monotonic decay: waiting longer can never ask for a *colder* charge."""
    waits = [0.0, 5.0, 10.0, 20.0, 40.0, 80.0]
    charges = [heat_soak_correction(w, 0.5, 0.5)[0] for w in waits]
    assert all(a <= b for a, b in pairwise(charges))


@given(
    minutes=st.floats(min_value=-10.0, max_value=600.0),
    mass=st.floats(min_value=0.0, max_value=1.0),
    retention=st.floats(min_value=0.0, max_value=1.0),
)
@_PROPERTY
def test_heat_soak_stays_inside_its_physical_envelope(
    minutes: float, mass: float, retention: float,
) -> None:
    """Whatever the inputs, the correction never asks for something absurd."""
    dcharge, dheater, tau = heat_soak_correction(minutes, mass, retention)
    assert -10.0 <= dcharge <= 0.0      # never heats the charge, never below the floor
    assert -5 <= dheater <= 0           # never raises the burner
    assert 12.0 <= tau <= 42.0          # 12 + 30*mr, mr in [0,1]


# ── _adopt_learned — the learned-vs-grid adoption policy ─────────────────────

def test_adopt_learned_trusts_the_median_from_three_roasts() -> None:
    value, source = TilauScopeRoastPlan._adopt_learned(200.0, 210.0, 3)
    assert value == pytest.approx(210.0)
    assert 'learned' in source and 'n=3' in source


def test_adopt_learned_blends_half_and_half_at_two_roasts() -> None:
    value, source = TilauScopeRoastPlan._adopt_learned(200.0, 210.0, 2)
    assert value == pytest.approx(205.0)
    assert 'blend' in source


def test_adopt_learned_falls_back_to_grid_below_two_roasts() -> None:
    for n in (0, 1):
        value, source = TilauScopeRoastPlan._adopt_learned(200.0, 210.0, n)
        assert value == pytest.approx(200.0)
        assert source == 'grid'


def test_adopt_learned_falls_back_to_grid_when_nothing_was_learned() -> None:
    """`learned=None` is how the caller signals an implausible value."""
    assert TilauScopeRoastPlan._adopt_learned(200.0, None, 99) == (200.0, 'grid')


@given(
    grid=st.floats(min_value=-500.0, max_value=500.0),
    learned=st.one_of(st.none(), st.floats(min_value=-500.0, max_value=500.0)),
    n=st.integers(min_value=0, max_value=50),
)
@_PROPERTY
def test_adopt_learned_never_extrapolates(
    grid: float, learned: float | None, n: int,
) -> None:
    """The adopted value always sits between the grid and the learned value.

    This is the guard rail for cross-roast learning: the policy may weight the
    history, but it may never produce a value outside the interval the two
    sources bracket.
    """
    value, source = TilauScopeRoastPlan._adopt_learned(grid, learned, n)
    lo, hi = (grid, grid) if learned is None else (min(grid, learned), max(grid, learned))
    assert lo - 1e-9 <= value <= hi + 1e-9
    assert source


# ── _which_phase — phase attribution of a historical sample ──────────────────

@pytest.mark.parametrize(('t', 'expected'), [
    (10.0, 1),    # before dry_end            -> DRY
    (300.0, 1),   # exactly dry_end           -> DRY (inclusive bound)
    (400.0, 2),   # between dry_end and fc    -> MAILLARD
    (600.0, 2),   # exactly fc_start          -> MAILLARD (inclusive bound)
    (650.0, 3),   # between fc and drop       -> DEVELOPMENT
    (700.0, 3),   # exactly drop              -> DEVELOPMENT
    (900.0, 0),   # after drop                -> out of scope
])
def test_which_phase_maps_a_timestamp_to_its_phase(
    plan_model: TilauScopeRoastPlan, t: float, expected: int,
) -> None:
    phases = {'dry_end': 300.0, 'fc_start': 600.0, 'drop': 700.0}
    assert plan_model._which_phase(t, phases) == expected


def test_which_phase_refuses_to_guess_when_fc_is_unmarked(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Without FC, post-drying samples are ambiguous and must be discarded.

    Labelling them DEVELOPMENT used to pollute the phase statistics with
    Maillard crashes and flicks — the whole point of returning 0 here.
    """
    phases = {'dry_end': 300.0, 'fc_start': None, 'drop': 700.0}
    assert plan_model._which_phase(200.0, phases) == 1    # DRY is still knowable
    assert plan_model._which_phase(500.0, phases) == 0    # ambiguous -> out of scope
    assert plan_model._which_phase(690.0, phases) == 0


def test_which_phase_returns_out_of_scope_without_a_drop(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._which_phase(100.0, {'dry_end': 300.0, 'fc_start': 600.0}) == 0


# ── _calculate_rpm_percentage — no-context fallback ──────────────────────────

@pytest.mark.parametrize(('rpm', 'expected'), [
    (34.0, '40%'),    # bottom of the range, lifted by the 40 % floor
    (10.0, '40%'),    # below range -> clamped
    (51.0, '50%'),    # mid range
    (68.0, '100%'),   # top of the range
    (200.0, '100%'),  # above range -> clamped
])
def test_rpm_percentage_fallback_clamps_and_formats(
    plan_model: TilauScopeRoastPlan, rpm: float, expected: str,
) -> None:
    assert plan_model._calculate_rpm_percentage(rpm) == expected


def test_rpm_percentage_fallback_snaps_to_the_step(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Output is quantised to the drum's step, never a raw interpolation."""
    for rpm in (35.0, 40.0, 45.0, 52.0, 60.0):
        pct = plan_model._calculate_rpm_percentage(rpm)
        assert pct.endswith('%')
        assert float(pct[:-1]) % 5.0 == 0.0


def test_rpm_percentage_floor_is_overridable(plan_model: TilauScopeRoastPlan) -> None:
    assert plan_model._calculate_rpm_percentage(34.0, min_rpm_percent=0.0) == '0%'


# ── _get_agtron_category ─────────────────────────────────────────────────────

def test_agtron_category_matches_the_declared_scale(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Every category returned must be one whose range really contains the value."""
    for scale in AGTRON_SCALES:
        midpoint = (scale.agtron_range.min_value + scale.agtron_range.max_value) / 2.0
        name = plan_model._get_agtron_category(midpoint)
        matching = next(s for s in AGTRON_SCALES if s.name == name)
        assert matching.agtron_range.min_value <= midpoint <= matching.agtron_range.max_value


def test_agtron_category_is_empty_outside_the_scale(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._get_agtron_category(-5.0) == ''
    assert plan_model._get_agtron_category(500.0) == ''
    assert plan_model._get_agtron_category('not a number') == ''


def test_agtron_category_passes_through_an_explicit_scale(
    plan_model: TilauScopeRoastPlan,
) -> None:
    scale = AGTRON_SCALES[0]
    assert plan_model._get_agtron_category(scale) == scale.name


# ── _clean_delta_bt — forward fill of a recorded RoR channel ─────────────────

def test_clean_delta_bt_forward_fills_gaps(plan_model: TilauScopeRoastPlan) -> None:
    assert plan_model._clean_delta_bt([None, 1.0, None, None, 3.0]) == [0.0, 1.0, 1.0, 1.0, 3.0]


def test_clean_delta_bt_handles_degenerate_inputs(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._clean_delta_bt([]) == []
    assert plan_model._clean_delta_bt([None, None]) == [0.0, 0.0]


# ── _estimate_dt — per-log sampling interval ─────────────────────────────────

def test_estimate_dt_reads_the_median_interval(plan_model: TilauScopeRoastPlan) -> None:
    assert plan_model._estimate_dt([0.0, 1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert plan_model._estimate_dt([0.0, 2.0, 4.0, 6.0]) == pytest.approx(2.0)


def test_estimate_dt_is_robust_to_a_single_outlier_gap(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Median, not mean: one recording pause must not rescale the whole log."""
    assert plan_model._estimate_dt([0.0, 1.0, 2.0, 300.0, 301.0, 302.0]) == pytest.approx(1.0)


def test_estimate_dt_falls_back_when_timestamps_are_unusable(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._estimate_dt([]) == 1.0
    assert plan_model._estimate_dt([5.0]) == 1.0
    assert plan_model._estimate_dt([1.0, 1.0, 1.0]) == 1.0   # no positive delta


def test_estimate_dt_stays_inside_plausible_sampling_rates(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._estimate_dt([0.0, 60.0, 120.0]) == pytest.approx(10.0)
    assert plan_model._estimate_dt([0.0, 0.01, 0.02]) == pytest.approx(0.25)


# ── _find_turning_point_index — TP location ──────────────────────────────────

def test_turning_point_is_the_bt_minimum_not_the_ror_minimum(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """TP is where BT bottoms out, which is *after* the steepest cooling.

    Using the RoR minimum mislocated the TP systematically; this test pins the
    corrected definition.
    """
    # BT falls from 200 to a minimum at t=90 s, then climbs again.
    bt = [200.0 - 1.5 * t for t in range(91)] + [65.0 + 0.8 * t for t in range(1, 60)]
    assert plan_model._find_turning_point_index(bt, dt=1.0) == 90


def test_turning_point_search_ignores_the_charge_instant(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """A spurious minimum in the first 15 s belongs to the charge, not the TP."""
    bt = [0.0] + [200.0 - 1.0 * t for t in range(1, 200)]
    assert plan_model._find_turning_point_index(bt, dt=1.0) >= 15


def test_turning_point_handles_empty_and_blank_curves(
    plan_model: TilauScopeRoastPlan,
) -> None:
    assert plan_model._find_turning_point_index([], dt=1.0) == 0
    assert plan_model._find_turning_point_index([None] * 200, dt=1.0) == 15


# ── _build_pchip_curve — the planned BT/RoR curve ────────────────────────────

def _waypoints() -> list[dict[str, float]]:
    return [
        {'time_min': 0.0, 'bt': 200.0},
        {'time_min': 1.5, 'bt': 95.0},
        {'time_min': 5.0, 'bt': 150.0},
        {'time_min': 9.0, 'bt': 196.0},
        {'time_min': 10.5, 'bt': 205.0},
        {'time_min': 11.5, 'bt': 210.0},
    ]


def test_pchip_curve_is_sampled_every_second() -> None:
    curve = TilauScopeRoastPlan._build_pchip_curve(_waypoints())
    times = curve['time_min']
    assert len(times) == len(curve['bt_plan']) == len(curve['ror_plan'])
    assert times[0] == pytest.approx(0.0)
    assert times[1] - times[0] == pytest.approx(1.0 / 60.0)


def test_pchip_curve_passes_through_its_anchors() -> None:
    """The plan must honour the milestones it was built from."""
    waypoints = _waypoints()
    curve = TilauScopeRoastPlan._build_pchip_curve(waypoints)
    times = np.asarray(curve['time_min'])
    bt = np.asarray(curve['bt_plan'])
    for wp in waypoints:
        idx = int(np.argmin(np.abs(times - wp['time_min'])))
        assert bt[idx] == pytest.approx(wp['bt'], abs=1.0)


def test_pchip_curve_echoes_its_waypoints_unchanged() -> None:
    """Consumers re-read the anchors from the curve; they must not be rewritten."""
    waypoints = _waypoints()
    curve = TilauScopeRoastPlan._build_pchip_curve(waypoints)
    assert curve['waypoints'] == waypoints


def test_pchip_curve_survives_a_drop_glued_to_first_crack() -> None:
    """A very short development must not produce non-increasing knot times."""
    waypoints = _waypoints()
    waypoints[-2] = {'time_min': 11.5, 'bt': 205.0}   # equal to the drop time
    curve = TilauScopeRoastPlan._build_pchip_curve(waypoints)
    assert len(curve['bt_plan']) > 0
    assert not np.any(np.isnan(curve['bt_plan']))


# The curve is emitted with np.round(..., 2) applied AFTER the clip, so a value
# may sit half a centidegree outside the declared bound. Physically irrelevant,
# but the assertion has to know about it.
_ROUNDING_SLACK = 0.005


@given(
    charge_bt=st.floats(min_value=150.0, max_value=230.0),
    rest=st.lists(
        st.tuples(
            st.floats(min_value=0.5, max_value=20.0),
            st.floats(min_value=60.0, max_value=230.0),
        ),
        min_size=2, max_size=7, unique_by=lambda p: round(p[0], 3),
    ),
)
@_PROPERTY
def test_pchip_curve_stays_within_its_declared_bounds(
    charge_bt: float, rest: list[tuple[float, float]],
) -> None:
    """Whatever the anchors, the emitted curve respects the documented clipping.

    A plan escaping these bounds would drive the assistant, the alarms and the
    PDF report with physically impossible targets.

    The first anchor is pinned at t=0 because that is CHARGE: a real plan always
    starts there, and letting the strategy start later would only exercise the
    interpolator's extrapolation regime, which no plan consumer can reach.
    """
    ordered = [(0.0, charge_bt), *sorted(rest)]
    assume(all(b[0] - a[0] > 0.05 for a, b in pairwise(ordered)))
    waypoints = [{'time_min': t, 'bt': bt} for t, bt in ordered]

    curve = TilauScopeRoastPlan._build_pchip_curve(waypoints)
    bt = np.asarray(curve['bt_plan'])
    ror = np.asarray(curve['ror_plan'])
    times = np.asarray(curve['time_min'])

    assert len(bt) == len(ror) == len(times)
    assert np.all(np.diff(times) > 0)
    assert np.all(bt >= 20.0 - _ROUNDING_SLACK)
    assert np.all(bt <= ordered[-1][1] + 10.0 + _ROUNDING_SLACK)
    assert np.all(ror >= -2.0 - _ROUNDING_SLACK)
    assert np.all(ror <= 28.0 + _ROUNDING_SLACK)


# ── format_time ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(('minutes', 'expected'), [
    (0.0, '00:00'),
    (1.5, '01:30'),
    (12.0, '12:00'),
    (9.75, '09:45'),
    (0.008, '00:00'),   # rounds to the nearest second
])
def test_format_time_renders_minutes_as_mmss(
    plan_model: TilauScopeRoastPlan, minutes: float, expected: str,
) -> None:
    assert plan_model.format_time(minutes) == expected

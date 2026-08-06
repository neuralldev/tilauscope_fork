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
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from tilauscope.bean_energy import FloorProfile
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


# ── _build_heater_ramp_c — plancher de Maillard ──────────────────────────────
# Maillard est endothermique : la rampe ne doit jamais poser le feu de
# DÉVELOPPEMENT avant le FC (« ça mijote »). Spec wiki/BeanEnergy-MaillardFloor-Spec.md.

_TP_C, _DE_C, _FC_C = 95.0, 150.0, 189.0


def _ramp(plan_model: TilauScopeRoastPlan, **kw: Any) -> list[dict]:
    args: dict[str, Any] = {'h_dry': 72.0, 'h_mai': 57.0, 'h_pre_fc': 45.0,
                            'floor': None, 'dry_end_ror_c': 0.0,
                            'pre_de_pct': 0.0}
    args.update(kw)
    return plan_model._build_heater_ramp_c(
        _TP_C, _DE_C, _FC_C, 12.0, 50.0, 1.0,
        args['h_dry'], args['h_mai'], args['h_pre_fc'],
        lambda v: v, heater_max_pct=80.0, floor=args['floor'],
        dry_end_ror_c=args['dry_end_ror_c'], pre_de_pct=args['pre_de_pct'])


def test_heater_ramp_without_a_floor_still_lands_on_its_pre_fc_step(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Forme de référence : sans plancher, l'escalier descend jusqu'au palier
    pre-FC. Le plancher ne doit pas être une réécriture de cette géométrie."""
    ramp = _ramp(plan_model)
    assert ramp
    assert ramp[-1]['heater'] == 45
    assert [e['heater'] for e in ramp] == sorted(
        (e['heater'] for e in ramp), reverse=True)


def test_heater_ramp_never_descends_under_the_maillard_floor(
    plan_model: TilauScopeRoastPlan,
) -> None:
    floor = FloorProfile(level_pct=65.0, release_fraction=0.75)
    ramp = _ramp(plan_model, floor=floor)
    # Le plancher court du DRY END au palier PRE-FC : sa fin de courbe EST la
    # baisse anti-rebond qui se pose sur ce palier.
    pre_fc = _FC_C - 12.0 * 50.0 / 60.0
    assert any(e['bt'] >= _DE_C for e in ramp)
    for entry in ramp:
        bt = float(entry['bt'])
        if bt < _DE_C:
            continue
        u = (bt - _DE_C) / (pre_fc - _DE_C)
        assert entry['heater'] >= math.floor(floor.at(u))


def test_the_floor_keeps_the_descent_monotone_across_the_dry_end(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Un plancher qui ne mordrait qu'à partir du DRY END ferait REMONTER le feu
    à l'entrée du Maillard. Il vaut son niveau plat avant : le grain n'entre pas
    en Maillard déjà affamé."""
    high = FloorProfile(level_pct=70.0, release_fraction=0.75)
    ramp = _ramp(plan_model, h_dry=74.0, floor=high)
    assert ramp
    assert [e['heater'] for e in ramp] == sorted(
        (e['heater'] for e in ramp), reverse=True)
    for entry in ramp:
        if entry['bt'] < _DE_C:
            assert entry['heater'] >= 70


def test_a_floor_under_the_ladder_changes_nothing(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Le plancher ne peut que RELEVER une consigne, jamais l'abaisser."""
    low = FloorProfile(level_pct=56.0, release_fraction=0.75)   # fin de courbe 51
    assert (_ramp(plan_model, h_pre_fc=60.0, floor=low)
            == _ramp(plan_model, h_pre_fc=60.0))


def test_the_authority_cliff_binds_every_plan(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Sous ~50 % le brûleur rend +0,03 °C/min par % : ce n'est plus un levier.
    Aucun plancher, si bas soit-il, ne laisse descendre le palier pre-FC en
    dessous — donc un escalier qui visait 45 % avant le FC est relevé."""
    tiny = FloorProfile(level_pct=30.0, release_fraction=0.75)
    assert _ramp(plan_model, floor=tiny)[-1]['heater'] >= 50


def test_the_floor_absorbs_the_steps_it_swallows_instead_of_repeating_them(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Un palier ramené par le plancher à la valeur du précédent n'est pas une
    consigne : l'annoncer ferait un geste à faire qui ne change rien."""
    floor = FloorProfile(level_pct=65.0, release_fraction=0.75)
    heaters = [e['heater'] for e in _ramp(plan_model, floor=floor)]
    assert len(heaters) == len(set(heaters))
    assert heaters == sorted(heaters, reverse=True)


# ── _planned_ror_at — lecture de la pente sur la courbe planifiée ────────────

def _curve(times: list[float], rors: list[float]) -> dict:
    return {'time_min': times, 'ror_plan': rors}


def test_planned_ror_at_reads_the_slope_at_the_requested_instant(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """R_DE se lit sur la courbe, pas sur une constante — la vérification du
    Maillard y est très sensible."""
    curve = _curve([0.0, 1.0, 2.0, 3.0], [20.0, 15.0, 12.0, 9.0])
    assert plan_model._planned_ror_at(curve, 2.0) == 12.0


def test_planned_ror_at_picks_the_nearest_sample() -> None:
    """La courbe est échantillonnée à la seconde ; un jalon tombe rarement
    pile dessus."""
    curve = _curve([0.0, 1.0, 2.0], [20.0, 15.0, 12.0])
    assert TilauScopeRoastPlan._planned_ror_at(curve, 1.6) == 12.0
    assert TilauScopeRoastPlan._planned_ror_at(curve, 1.4) == 15.0


@pytest.mark.parametrize('curve', [
    {}, None, [], 'not a curve',
    {'time_min': [], 'ror_plan': []},
    {'time_min': [0.0, 1.0]},                       # ror_plan manquant
    {'ror_plan': [10.0]},                           # time_min manquant
])
def test_planned_ror_at_returns_zero_on_a_degenerate_curve(curve) -> None:
    """La vérification se TAIT plutôt que de lever : c'est un diagnostic
    optionnel, il ne doit jamais faire échouer une génération de plan."""
    assert TilauScopeRoastPlan._planned_ror_at(curve, 5.0) == 0.0


def test_planned_ror_at_never_returns_a_negative_slope() -> None:
    """Un R_DE négatif ferait diverger R_FC = (moyenne*(k+1) - R_DE)/k."""
    curve = _curve([0.0, 1.0], [-4.0, -1.0])
    assert TilauScopeRoastPlan._planned_ror_at(curve, 0.0) == 0.0


# ── Garde-fous physiques de durée, sur de vrais plans ────────────────────────
# Ils viennent de la MACHINE, pas de la grille de style : sous 4:30 le séchage
# est hors d'atteinte sur un tambour de cette taille, sous 3:00 il faudrait
# chauffer au point de brûler le grain. Les constantes sont locales à
# generate_roast_plan — on teste l'invariant observable, pas la valeur.

def _mmss(value: str) -> float:
    """"MM:SS" -> minutes."""
    minutes, seconds = value.split(':')
    return int(minutes) + int(seconds) / 60.0


@pytest.fixture(scope='module')
def corpus_plans() -> list[dict]:
    """Un plan par scénario du corpus de fixtures, généré de bout en bout."""
    import corpus_harness as H
    import corpus_snapshot as S

    H.install_qt_shims()
    plans = []
    for scenario in S.SCENARIOS:
        model = H.make_plan_model(H.CORPUS_DIR)
        bean = H.make_bean(scenario.uuid, scenario.bean_name,
                           process=scenario.process,
                           altitude=int(scenario.altitude_m))
        result = model.generate_roast_plan(
            bean, H.agtron(scenario.target), scenario.ambient_c,
            scenario.humidity_pct, scenario.charge_g, scenario.altitude_m,
            None, False, scenario.minutes_since_drop)
        plans.append(result[0] if isinstance(result, tuple) else result)
    return plans


def test_planned_drying_never_falls_under_the_machine_floor(
    corpus_plans: list[dict],
) -> None:
    assert corpus_plans
    for plan in corpus_plans:
        assert _mmss(plan['Dry Phase']) >= 4.5 - 1e-9, plan['Bean Name']


def test_planned_maillard_never_falls_under_the_machine_floor(
    corpus_plans: list[dict],
) -> None:
    for plan in corpus_plans:
        assert _mmss(plan['Maillard Phase']) >= 3.0 - 1e-9, plan['Bean Name']


def test_a_duration_floor_extends_the_total_it_never_shortens_a_phase(
    corpus_plans: list[dict],
) -> None:
    """L'ordre d'ancrage est dev → total → séchage → Maillard. Quand un
    garde-fou mord, c'est le TOTAL qui absorbe — jamais une autre phase."""
    for plan in corpus_plans:
        total = _mmss(plan['Total Time'])
        parts = sum(_mmss(plan[k]) for k in
                    ('Dry Phase', 'Maillard Phase', 'Development Phase'))
        # 2 s de tolérance : chaque phase est affichée en MM:SS, donc arrondie
        # à la seconde — la somme de trois arrondis peut s'écarter de l'arrondi
        # de la somme. Ce n'est pas une dérive du modèle.
        assert total == pytest.approx(parts, abs=2.0 / 60.0), plan['Bean Name']


def test_development_is_the_professional_band_untouched_by_the_floors(
    corpus_plans: list[dict],
) -> None:
    """Le développement est une durée absolue dictée par le niveau visé : il ne
    doit jamais payer pour un garde-fou appliqué en amont."""
    for plan in corpus_plans:
        dev = _mmss(plan['Development Phase'])
        assert 1.0 <= dev <= 4.0, f"{plan['Bean Name']}: dev={plan['Development Phase']}"


@pytest.mark.parametrize(('column', 'lever'), [
    ('Heater (%) (Dry|Mai|Dev)', 'heater'),
    ('Airflow (%) (Dry|Mai|Dev)', 'airflow'),
])
def test_the_dev_column_states_where_the_dev_ramp_actually_lands(
    corpus_plans: list[dict], column: str, lever: str,
) -> None:
    """Le plan ne peut pas annoncer une cible de dev que sa propre rampe ne tient pas.

    Cette colonne n'est pas décorative : l'AutoPilot en fait sa cible DEV
    (`_AP_LEVER_KEYS`) et, sur torréfacteur read-only, elle est lue mot pour mot
    par l'opérateur (`_phase_reco_text`). Un écart, c'est une consigne fausse,
    pas une coquille de PDF.

    L'air a divergé du brûleur pendant un moment : la colonne sortait de la
    grille de base alors que la rampe adoptait la cible apprise ET le plancher
    de soutien qui ouvre l'air à mesure que le feu descend.
    """
    for plan in corpus_plans:
        posted = [e[lever] for e in (plan.get('Dev Ramp') or []) if lever in e]
        if not posted:
            continue
        column_value = float(str(plan[column]).split('|')[2].strip().rstrip('%'))
        assert column_value == pytest.approx(float(posted[-1])), (
            f"{plan['Bean Name']}: la colonne {lever} dev annonce {column_value:.0f}% "
            f"mais la Dev Ramp finit à {posted[-1]}%"
        )


def test_the_maillard_ror_verification_is_reported_on_every_plan(
    corpus_plans: list[dict],
) -> None:
    """R_FC est la valeur d'ARRIVÉE : la moyenne seule ne dit pas où on atterrit,
    et c'est l'atterrissage qui décide du FC."""
    for plan in corpus_plans:
        assert 'Target ROR at FC' in plan
        assert plan['Maillard Conflict'] in ('', 'acceleration', 'crash', 'illegible')
        if not plan['Maillard Conflict']:
            # sans conflit, l'arrivée est sous la moyenne et au-dessus du crash
            assert float(plan['Target ROR at FC']) < float(plan['Target ROR Maillard'])
            assert float(plan['Target ROR at FC']) >= 3.5


# ── _maillard_conflict — les trois refus ────────────────────────────────────
# Aucun plan du corpus ne les déclenche : ce sont les roasts que Tilau a
# réellement tenus. C'est justement pourquoi la décision est un helper pur.

def test_no_conflict_on_a_healthy_maillard() -> None:
    """Descente franche du RoR, arrivée bien au-dessus du plancher de crash,
    brûleur qui recule doucement : rien à signaler."""
    assert TilauScopeRoastPlan._maillard_conflict(14.0, 9.0, 12.0, 3.5) == ''


def test_conflict_acceleration_when_the_ror_would_have_to_climb() -> None:
    """Trop de degrés à couvrir dans le temps imparti — flick garanti."""
    assert TilauScopeRoastPlan._maillard_conflict(9.0, 11.0, 5.0, 3.5) == 'acceleration'
    # égalité comprise : un RoR plat en Maillard est déjà le défaut
    assert TilauScopeRoastPlan._maillard_conflict(9.0, 9.0, 5.0, 3.5) == 'acceleration'


def test_conflict_crash_when_the_ror_collapses_before_first_crack() -> None:
    """Profil plat, pain grillé."""
    assert TilauScopeRoastPlan._maillard_conflict(14.0, 2.0, 5.0, 3.5) == 'crash'


def test_conflict_illegible_when_the_burner_cannot_come_down_fast_enough() -> None:
    """Contrainte d'APPRENTISSAGE, pas de physique : au-delà de 5 % par 30 s on
    ne voit plus ce qu'on fait, donc on ne peut plus rien tirer du geste.
    Sur 3 min de Maillard le budget est de 30 %."""
    assert TilauScopeRoastPlan._maillard_conflict(14.0, 9.0, 25.0, 3.0) == ''
    assert TilauScopeRoastPlan._maillard_conflict(14.0, 9.0, 35.0, 3.0) == 'illegible'


def test_a_broken_geometry_outranks_an_unreadable_descent() -> None:
    """Un plan qui cumule les deux est d'abord un problème de géométrie : dire
    « baisse trop vite » masquerait la vraie cause."""
    assert TilauScopeRoastPlan._maillard_conflict(9.0, 11.0, 99.0, 3.0) == 'acceleration'
    assert TilauScopeRoastPlan._maillard_conflict(14.0, 1.0, 99.0, 3.0) == 'crash'


def test_the_verification_stays_silent_without_a_reference_slope() -> None:
    """Courbe absente ou dégénérée : on ne diagnostique pas dans le vide."""
    assert TilauScopeRoastPlan._maillard_conflict(0.0, 9.0, 99.0, 0.1) == ''


# ── _verify_maillard_ror — dérivation R_FC et note opérateur ────────────────
# Ce que cette étape ajoute par-dessus _planned_ror_at (lecture de R_DE) et
# _maillard_conflict (le verdict trois voies) : la dérivation R_FC = (moyenne*
# (k+1) - R_DE)/k, et la mise en forme de la note opérateur pour le conflit
# retenu.

def test_verify_maillard_ror_derives_r_fc_from_the_average_and_r_de(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """R_FC = (moyenne*(k+1) - R_DE)/k — chiffres ronds, vérifiables à la main.
    moyenne=10, R_DE=16, k=2 -> R_FC = (10*3 - 16)/2 = 7.0."""
    curve = _curve([0.0, 1.0, 2.0], [20.0, 16.0, 12.0])
    ror_fc_c, _conflict, _note = plan_model._verify_maillard_ror(
        curve=curve, dry_time_min=1.0, maillard_time_min=3.5,
        ma_bt_temperature=40.0, ror_maillard=10.0, heater_dry=70.0,
        heater_pre_fc=60.0, ror_scale=1.0, mode='C', decay_k=2.0)
    assert ror_fc_c == pytest.approx(7.0)


def test_verify_maillard_ror_falls_back_to_the_average_without_a_reference_slope(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """R_DE == 0 (courbe dégénérée) : le garde-fou `if _r_de_c > 0.0 and _k > 0.0`
    laisse R_FC égal à la moyenne, et _maillard_conflict se tait sur r_de_c<=0."""
    ror_fc_c, conflict, note = plan_model._verify_maillard_ror(
        curve={}, dry_time_min=1.0, maillard_time_min=3.5,
        ma_bt_temperature=40.0, ror_maillard=10.0, heater_dry=70.0,
        heater_pre_fc=60.0, ror_scale=1.0, mode='C', decay_k=2.0)
    assert ror_fc_c == pytest.approx(10.0)
    assert conflict == ''
    assert note == ''


def test_verify_maillard_ror_produces_a_non_empty_note_on_conflict(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Un conflit détecté doit produire une note opérateur formatée, pas juste
    un code — c'est ce que le call site publie dans history['actions']."""
    curve = _curve([0.0, 1.0], [9.0, 9.0])   # R_DE=9 -> conflit 'acceleration'
    ror_fc_c, conflict, note = plan_model._verify_maillard_ror(
        curve=curve, dry_time_min=1.0, maillard_time_min=3.5,
        ma_bt_temperature=40.0, ror_maillard=10.0, heater_dry=70.0,
        heater_pre_fc=60.0, ror_scale=1.0, mode='C', decay_k=2.0)
    assert conflict == 'acceleration'
    assert note != ''
    assert isinstance(note, str) and len(note) > 20   # formatted text, not a bare code


# ── _water_activity_effect — moisture-reading adjustment ────────────────────
# Pure stage: the two branches are asymmetric and touch disjoint fields — the
# high-WA branch never moves the charge temperature, the low-WA branch never
# touches heater/airflow/extraction. Nothing else in the codebase states this.

def test_water_activity_effect_is_neutral_when_unmeasured() -> None:
    """WA == 0.0 means 'not measured' — no adjustment applies."""
    effect = TilauScopeRoastPlan._water_activity_effect(0.0)
    assert effect.d_dry_time_min == 0.0
    assert effect.d_heater_dry_pct == 0.0
    assert effect.d_airflow_pct == 0.0
    assert effect.d_extraction_pct == 0.0
    assert effect.d_charge_c == 0.0


def test_water_activity_effect_is_neutral_inside_the_ideal_band() -> None:
    """0.55-0.65 is the ideal storage band — no adjustment applies."""
    effect = TilauScopeRoastPlan._water_activity_effect(0.60)
    assert effect.d_dry_time_min == 0.0
    assert effect.d_heater_dry_pct == 0.0
    assert effect.d_airflow_pct == 0.0
    assert effect.d_extraction_pct == 0.0
    assert effect.d_charge_c == 0.0


def test_water_activity_effect_high_reading_extends_drying_and_leaves_charge_alone() -> None:
    """Above 0.65: drying extended, heater/airflow/extraction boosted — but the
    charge temperature is untouched (only the low-WA branch moves it)."""
    effect = TilauScopeRoastPlan._water_activity_effect(0.75)
    wa_factor = (0.75 - 0.65) / 0.05
    assert effect.d_dry_time_min == pytest.approx(wa_factor * 0.20)
    assert effect.d_heater_dry_pct == pytest.approx(wa_factor * 2.0)
    assert effect.d_airflow_pct == pytest.approx(wa_factor * 1.5)
    assert effect.d_extraction_pct == pytest.approx(wa_factor * 2.0)
    assert effect.d_charge_c == 0.0


def test_water_activity_effect_low_reading_shortens_drying_and_leaves_heater_alone() -> None:
    """Below 0.55: drying shortened and charge lowered — but heater/airflow/
    extraction are untouched (only the high-WA branch moves them)."""
    effect = TilauScopeRoastPlan._water_activity_effect(0.45)
    wa_factor = (0.55 - 0.45) / 0.05
    assert effect.d_dry_time_min == pytest.approx(-wa_factor * 0.15)
    assert effect.d_charge_c == pytest.approx(-wa_factor * 1.5)
    assert effect.d_heater_dry_pct == 0.0
    assert effect.d_airflow_pct == 0.0
    assert effect.d_extraction_pct == 0.0


# ── Un plan complet SUR un grain dont l'activité de l'eau est mesurée ────────
# Les quatre tests ci-dessus couvrent l'étage ; ils n'ont pas couvert
# l'assemblage qui le consomme. Aucun grain du corpus gelé ne porte de mesure
# d'aw, donc "Water Activity Used" prenait toujours sa branche "Not measured" —
# et un nom orphelin dans l'autre branche a atteint l'opérateur en NameError
# (2026-08-06). Le plan doit se générer de bout en bout, aw renseignée.

@pytest.mark.parametrize('wa_reading', [0.72, 0.45])
def test_a_plan_generates_end_to_end_when_water_activity_is_measured(
    wa_reading: float,
) -> None:
    import corpus_harness as H
    import corpus_snapshot as S

    H.install_qt_shims()
    scenario = S.SCENARIOS[0]
    model = H.make_plan_model(H.CORPUS_DIR)
    bean = H.make_bean(scenario.uuid, scenario.bean_name,
                       process=scenario.process,
                       altitude=int(scenario.altitude_m),
                       water_activity=wa_reading)
    result = model.generate_roast_plan(
        bean, H.agtron(scenario.target), scenario.ambient_c,
        scenario.humidity_pct, scenario.charge_g, scenario.altitude_m,
        None, False, scenario.minutes_since_drop)
    plan = result[0] if isinstance(result, tuple) else result
    assert plan['Water Activity Used'] == f'{wa_reading:.3f}'


def test_an_unmeasured_water_activity_still_reads_not_measured() -> None:
    """The other side of the branch, so the fix above cannot regress into
    always formatting a number."""
    import corpus_harness as H
    import corpus_snapshot as S

    H.install_qt_shims()
    scenario = S.SCENARIOS[0]
    model = H.make_plan_model(H.CORPUS_DIR)
    bean = H.make_bean(scenario.uuid, scenario.bean_name,
                       process=scenario.process,
                       altitude=int(scenario.altitude_m))
    result = model.generate_roast_plan(
        bean, H.agtron(scenario.target), scenario.ambient_c,
        scenario.humidity_pct, scenario.charge_g, scenario.altitude_m,
        None, False, scenario.minutes_since_drop)
    plan = result[0] if isinstance(result, tuple) else result
    assert plan['Water Activity Used'] == 'Not measured'


# ── _base_phase_durations — nominal total/dry/development split ─────────────
# Pure stage 1 of the phase-duration split (banc 2026-08-05): the geometry-only
# numbers, before water activity or cross-roast calibration ever touch them.

def _constraints(total_time=(24.0, 26.0), development_time=(2.0, 3.0)) -> Any:
    """Minimal stand-in for RoasterBasicPlanPerPhase — only the two fields
    _base_phase_durations reads."""
    from types import SimpleNamespace
    return SimpleNamespace(total_time=total_time, development_time=development_time)


def test_base_phase_durations_total_is_the_style_band_mean() -> None:
    total, _dry, _dev = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(total_time=(20.0, 24.0)), density=700.0, humidity=12.0)
    assert total == pytest.approx(22.0)


def test_base_phase_durations_development_is_the_professional_band_mean() -> None:
    """Development is an absolute duration from the professional band, moved
    into this stage from the old calibration block — not derived from DTR."""
    _total, _dry, dev = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(development_time=(1.5, 2.5)), density=700.0, humidity=12.0)
    assert dev == pytest.approx(2.0)


def test_base_phase_durations_dry_is_half_the_total_at_neutral_density_and_humidity() -> None:
    """density=700 g/L and humidity=12% are the zero points of their respective
    correction terms — drying collapses to exactly half the total."""
    total, dry, _dev = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(total_time=(20.0, 20.0)), density=700.0, humidity=12.0)
    assert dry == pytest.approx(total * 0.5)


def test_base_phase_durations_denser_or_wetter_beans_dry_longer() -> None:
    """Both correction terms are additive on top of the 50 % share."""
    _t, dry_neutral, _d = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(total_time=(20.0, 20.0)), density=700.0, humidity=12.0)
    _t, dry_denser, _d = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(total_time=(20.0, 20.0)), density=900.0, humidity=12.0)
    _t, dry_wetter, _d = TilauScopeRoastPlan._base_phase_durations(
        roast_constraints=_constraints(total_time=(20.0, 20.0)), density=700.0, humidity=14.0)
    assert dry_denser > dry_neutral
    assert dry_wetter > dry_neutral


# ── _calibrate_and_floor_phase_durations — calibration then machine floors ──
# Pure stage 2 (banc 2026-08-05). The golden corpus exercises the adoption
# branches but only trips one floor across all scenarios, never both — these
# tests hit the floors directly, and prove the ordering guarantee: floors run
# AFTER calibration, so a learned value the adoption window admits but the
# machine cannot reach still gets raised.

def test_a_low_drying_duration_is_raised_to_the_floor(plan_model: TilauScopeRoastPlan) -> None:
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=3.0, total_time_min=20.0, dev_time_min=2.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert result.dry_time_min == pytest.approx(4.5)


def test_a_low_maillard_duration_is_raised_to_the_floor(plan_model: TilauScopeRoastPlan) -> None:
    # dry=10, dev=2, total=12.5 -> baseline maillard = 0.5, well under the floor.
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=10.0, total_time_min=12.5, dev_time_min=2.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert result.maillard_time_min == pytest.approx(3.0)


def test_a_drying_floor_leaves_maillard_untouched(plan_model: TilauScopeRoastPlan) -> None:
    """No phase pays for another: only drying is below floor here, so
    Maillard keeps exactly its pre-floor value (20 - 3 - 2 = 15)."""
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=3.0, total_time_min=20.0, dev_time_min=2.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert result.dry_time_min == pytest.approx(4.5)
    assert result.maillard_time_min == pytest.approx(15.0)


def test_a_maillard_floor_leaves_drying_untouched(plan_model: TilauScopeRoastPlan) -> None:
    """No phase pays for another: only Maillard is below floor here, so
    drying keeps exactly the value it was passed in with."""
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=10.0, total_time_min=12.5, dev_time_min=2.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert result.dry_time_min == pytest.approx(10.0)
    assert result.maillard_time_min == pytest.approx(3.0)


def test_development_duration_never_appears_in_the_floored_result(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Development only enters as an input to the Maillard-by-subtraction
    baseline (total - dry - dev) — it has no floor of its own and is not part
    of the returned result at all, so it can never be 'raised' by this stage."""
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=8.0, total_time_min=20.0, dev_time_min=2.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert not hasattr(result, 'dev_time_min')
    # changing dev only shifts the maillard baseline linearly, one-for-one
    result_more_dev = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=8.0, total_time_min=20.0, dev_time_min=3.0,
        drying_time_band=(4.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0)
    assert result.maillard_time_min - result_more_dev.maillard_time_min == pytest.approx(1.0)


def test_a_learned_drying_duration_admitted_by_the_adoption_window_is_still_floored(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The whole reason the floors run LAST: the calibration's adoption window
    admits a 2.5 min learned drying duration (it is inside [2.5, 8.0] and the
    style band with its ±0.5 min margin), but the machine cannot physically dry
    that fast. Inverting the order would let it through unflagged."""
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=5.0, total_time_min=20.0, dev_time_min=3.0,
        drying_time_band=(2.0, 6.0), maillard_time_band=(3.0, 6.0),
        t_dry_raw=2.5, t_fc_raw=6.5, t_n=3)
    assert result.timing_source.startswith('learned')
    assert result.dry_time_min == pytest.approx(4.5)


# ── _resolve_drop_and_dev_ror — learned drop, FC→DROP coherence, drop/dev RoR
# Pure stage 4 (banc 2026-08-05): learned-colour adoption of the drop BT, the
# coherence rebuild that fires when a learned FC and a grid-derived drop cross
# (drop < fc + minimum development slope), and the RoR-at-drop derivation with
# its floor. The −0.323 °C/Agtron-pt slope and its ±15 pt cap that produce
# history["drop_bt_learned_c"] live upstream in _analyze_historical_roasts —
# out of scope for this extraction — so this stage only ever sees the
# already-corrected learned value; its own guard on that value is the ±3 °C
# style-band clamp exercised below.

def test_resolve_drop_and_dev_ror_without_history_uses_the_grid(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """No history at all: the grid+inertia drop estimate passes through
    untouched and the source says so."""
    result = plan_model._resolve_drop_and_dev_ror(
        drop_bt_temperature=200.0, drop_min=195.0, drop_max=205.0,
        drop_learned_c=None, drop_samples=0,
        drop_ror_learned_c=None, drop_ror_samples=0, fc_bt=185.0, dev_time_min=3.0, dev_ror_expected=5.0,
        agtron_ratio=0.5, charge_weight=400.0, density=700.0,
        water_activity=0.0, nominal_weight_g=400.0, heat_retention=0.65,
        is_fir_nir=True)
    assert result.drop_source == 'grid'
    assert result.drop_bt_temperature == pytest.approx(200.0)


def test_a_learned_drop_beyond_the_style_band_is_clamped_to_it(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """A biased history (moved probe, atypical lot) can never pull the plan
    out of the target style: the learned value (210, within the ±8 °C
    plausibility gate but past the ±3 °C style band at 208) is clamped to the
    band edge before adoption, not used raw."""
    result = plan_model._resolve_drop_and_dev_ror(
        drop_bt_temperature=200.0, drop_min=195.0, drop_max=205.0,
        drop_learned_c=210.0, drop_samples=3,
        drop_ror_learned_c=None, drop_ror_samples=0,
        fc_bt=190.0, dev_time_min=1.0, dev_ror_expected=5.0,
        agtron_ratio=0.5, charge_weight=400.0, density=700.0,
        water_activity=0.0, nominal_weight_g=400.0, heat_retention=0.65,
        is_fir_nir=True)
    assert result.drop_source.startswith('learned')
    assert result.drop_bt_temperature == pytest.approx(208.0)  # drop_max + 3.0


def test_an_incoherent_learned_drop_is_rebuilt_from_first_crack(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The FC anchor can be LEARNED while the drop still comes from the grid —
    the two references can cross and produce drop_bt < fc_bt, a physically
    impossible geometry. Once the drop falls under the minimum development
    slope from FC, the slope takes authority and the drop is rebuilt from FC;
    the source becomes 'coherence'.

    floor = dev_ror_expected*0.8 = 4.0; coherent = fc_bt + floor*dev_time_min
    = 190 + 4.0*3.0 = 202.0, above the grid drop of 195."""
    result = plan_model._resolve_drop_and_dev_ror(
        drop_bt_temperature=195.0, drop_min=195.0, drop_max=210.0,
        drop_learned_c=None, drop_samples=0,
        drop_ror_learned_c=None, drop_ror_samples=0, fc_bt=190.0, dev_time_min=3.0, dev_ror_expected=5.0,
        agtron_ratio=0.5, charge_weight=400.0, density=700.0,
        water_activity=0.0, nominal_weight_g=400.0, heat_retention=0.65,
        is_fir_nir=True)
    assert result.drop_source == 'coherence'
    assert result.drop_bt_temperature == pytest.approx(202.0)


def test_the_coherence_rebuild_is_capped_at_the_style_ceiling(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Unbounded, the coherence rebuild can push the drop above the style
    band's ceiling (fix 2026-08-05) — it must be capped there instead, even
    though that means the rebuilt drop no longer exactly matches the FC-derived
    slope. Same inputs as the rebuild test above, but drop_max lowered to 200,
    below the 202.0 the rebuild would otherwise produce."""
    result = plan_model._resolve_drop_and_dev_ror(
        drop_bt_temperature=195.0, drop_min=195.0, drop_max=200.0,
        drop_learned_c=None, drop_samples=0,
        drop_ror_learned_c=None, drop_ror_samples=0, fc_bt=190.0, dev_time_min=3.0, dev_ror_expected=5.0,
        agtron_ratio=0.5, charge_weight=400.0, density=700.0,
        water_activity=0.0, nominal_weight_g=400.0, heat_retention=0.65,
        is_fir_nir=True)
    assert result.drop_source == 'coherence'
    assert result.drop_bt_temperature == pytest.approx(200.0)


def test_the_development_ror_never_falls_below_its_floor(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The theoretical minimum development slope is a floor on dev_ror, not
    just an input to the coherence rebuild: rounding the rebuilt drop to one
    decimal (203.32 -> 203.3) can still leave the geometric slope (drop-fc)/
    dev_time_min a hair under the floor (3.994.. vs 4.0) — the floor catches
    that residual, replacing the old cosmetic 0.5 floor (fix 2026-08-04)."""
    result = plan_model._resolve_drop_and_dev_ror(
        drop_bt_temperature=195.0, drop_min=195.0, drop_max=210.0,
        drop_learned_c=None, drop_samples=0,
        drop_ror_learned_c=None, drop_ror_samples=0, fc_bt=190.0, dev_time_min=3.33, dev_ror_expected=5.0,
        agtron_ratio=0.5, charge_weight=400.0, density=700.0,
        water_activity=0.0, nominal_weight_g=400.0, heat_retention=0.65,
        is_fir_nir=True)
    assert result.drop_source == 'coherence'
    assert result.dev_ror == pytest.approx(4.0)


# ── Ancre apprise au DRY END (geste anti-flick) ─────────────────────────────
# Ce n'est PAS un geste unique : c'est le point d'arrivée du séchage, appris de
# la main de l'opérateur. L'émettre d'un bloc produirait des sauts infaisables.

def test_a_learned_dry_end_value_is_reached_by_steps_not_by_one_jump(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """80 % à mi-séchage et 55 % au DRY END, c'est 25 points : cinq crans, pas
    un saut. La limite d'observabilité est 5 % par 30 s."""
    ramp = _ramp(plan_model, h_dry=80.0, h_mai=54.0, h_pre_fc=50.0,
                 dry_end_ror_c=14.0, pre_de_pct=55.0)
    before_de = [e for e in ramp if e['bt'] <= _DE_C]
    assert len(before_de) >= 5
    for previous, entry in zip(before_de, before_de[1:], strict=False):
        assert previous['heater'] - entry['heater'] <= 5


def test_the_descent_starts_early_enough_to_land_on_the_learned_value(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Plus la baisse apprise est franche, plus la tenue du feu de séchage
    s'arrête tôt — sinon la valeur au DRY END est inatteignable proprement."""
    gentle = _ramp(plan_model, h_dry=72.0, h_mai=60.0, h_pre_fc=55.0,
                   dry_end_ror_c=14.0, pre_de_pct=67.0)
    steep = _ramp(plan_model, h_dry=72.0, h_mai=60.0, h_pre_fc=55.0,
                  dry_end_ror_c=14.0, pre_de_pct=60.0)
    assert steep[0]['bt'] < gentle[0]['bt']


def test_without_history_no_burner_move_is_scheduled_during_drying(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Le geste anti-flick n'appartient pas au plan de base : sans historique,
    le réglage de charge traverse le séchage."""
    ramp = _ramp(plan_model, h_dry=72.0, dry_end_ror_c=14.0, pre_de_pct=0.0)
    assert ramp
    assert all(e['bt'] >= _DE_C - 10.0 for e in ramp)


def test_a_learned_value_under_the_maillard_floor_is_ignored(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Le plancher ne peut que RELEVER : si la main apprise passe dessous, il
    n'y a pas de creux à rejouer, et la tenue du feu ne doit pas reculer pour
    un geste qui n'aura pas lieu."""
    with_low = _ramp(plan_model, h_dry=72.0, h_mai=65.0, h_pre_fc=60.0,
                     dry_end_ror_c=14.0, pre_de_pct=58.0)
    without = _ramp(plan_model, h_dry=72.0, h_mai=65.0, h_pre_fc=60.0,
                    dry_end_ror_c=14.0, pre_de_pct=0.0)
    assert with_low == without


# ── _extract_pre_de_descent — le premier geste de descente effective ────────
# La valeur tenue au DRY END est l'état d'ARRIVÉE du séchage : elle confond une
# conduite normale et une correction de RoR. C'est le premier geste descendant
# qui distingue les deux.

def _profile(events: list[tuple[float, float]], dry_end_sec: float = 240.0) -> dict:
    """Un profil minimal : une seconde par échantillon, CHARGE à l'index 0."""
    times = [float(t) for t, _ in events]
    grid = sorted({0.0, *times, dry_end_sec})
    return {
        'timex': grid,
        'timeindex': [0, grid.index(dry_end_sec), 0, 0, 0, 0, 0, 0],
        'specialevents': [grid.index(t) for t, _ in events],
        'specialeventstype': [3] * len(events),
        # events_internal_to_external_value : interne = % / 10 + 1
        'specialeventsvalue': [v / 10.0 + 1.0 for _, v in events],
    }


def test_pre_de_descent_measures_the_lead_and_the_step_size(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Main mesurée : charge à 75, premier geste à 1:38, crans de 2-3 %."""
    plan_model.lastprofiledata = _profile(
        [(2, 75), (98, 73), (110, 70), (147, 66), (154, 62)], dry_end_sec=217)
    lead, step = plan_model._extract_pre_de_descent({'dry_end': 217.0})
    assert lead == pytest.approx(217 - 98)
    # crans réels 2 · 3 · 4 · 4 → médiane 3.5, très loin du plafond de 5 %
    assert step == pytest.approx(3.5)


def test_the_charge_setting_is_the_baseline_not_the_first_gesture(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Le réglage de charge est posé dans le bruit des premières secondes. On
    écarte ce bruit mais on GARDE sa valeur : sinon le premier vrai geste passe
    pour la référence et on perd un cran."""
    plan_model.lastprofiledata = _profile(
        [(2, 65), (2, 90), (3, 75), (98, 73), (110, 70)], dry_end_sec=217)
    lead, _ = plan_model._extract_pre_de_descent({'dry_end': 217.0})
    assert lead == pytest.approx(217 - 98)   # et non 217 - 110


def test_no_gesture_before_dry_end_is_the_normal_case(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Réglage de charge juste, rien à corriger : ce n'est pas une anomalie,
    c'est le plan de base."""
    plan_model.lastprofiledata = _profile([(2, 75), (98, 75)], dry_end_sec=217)
    assert plan_model._extract_pre_de_descent({'dry_end': 217.0}) is None


def test_a_rise_before_dry_end_is_not_a_descent(
    plan_model: TilauScopeRoastPlan,
) -> None:
    plan_model.lastprofiledata = _profile(
        [(2, 60), (98, 65), (150, 70)], dry_end_sec=217)
    assert plan_model._extract_pre_de_descent({'dry_end': 217.0}) is None


def test_pre_de_descent_survives_a_profile_without_events(
    plan_model: TilauScopeRoastPlan,
) -> None:
    plan_model.lastprofiledata = {'timex': [], 'timeindex': []}
    assert plan_model._extract_pre_de_descent({'dry_end': 217.0}) is None
    plan_model.lastprofiledata = _profile([(2, 75)], dry_end_sec=217)
    assert plan_model._extract_pre_de_descent({}) is None


# ── _charge_setup — charge band, modulation, and heat-soak (banc 2026-08-05) ─
# Pure stage: the process sets the band in measured BT, bean/ambient constants
# modulate a few degrees inside it (capped at ±5°C), and heat soak is applied
# last, after the band clamp, so it can push the charge under the band floor —
# that is its purpose (design validé 2026-07-04).

def _charge(process_type_lower="washed", density=700.0, culture_altitude=1000.0,
            humidity=11.0, ambient_temp_c=20.0, minutes_since_last_drop=None,
            thermal_mass_idx=0.65, heat_retention_idx=0.65):
    """Neutral-modulation defaults: density=700, altitude<=1000, humidity=11
    and ambient=20 each zero out their own modulation term, so the caller only
    has to move the one input under test."""
    return TilauScopeRoastPlan._charge_setup(
        process_type_lower=process_type_lower, density=density,
        culture_altitude=culture_altitude, humidity=humidity,
        ambient_temp_c=ambient_temp_c, minutes_since_last_drop=minutes_since_last_drop,
        thermal_mass_idx=thermal_mass_idx, heat_retention_idx=heat_retention_idx)


def test_charge_setup_washed_process_lands_in_its_band() -> None:
    result = _charge(process_type_lower="washed")
    assert result.band == (180.0, 190.0)
    assert 180.0 <= result.temperature_c <= 190.0


def test_charge_setup_natural_process_lands_in_its_band() -> None:
    result = _charge(process_type_lower="natural")
    assert result.band == (170.0, 180.0)
    assert 170.0 <= result.temperature_c <= 180.0


def test_charge_setup_decaf_process_lands_in_its_band() -> None:
    result = _charge(process_type_lower="decaf")
    assert result.band == (160.0, 170.0)
    assert 160.0 <= result.temperature_c <= 170.0


def test_charge_setup_decaf_washed_resolves_to_decaf_not_washed() -> None:
    """decaf is the more specific label and must win even when a process word
    ('washed') also appears in the same string, e.g. 'decaf washed'."""
    result = _charge(process_type_lower="decaf washed")
    assert result.band == (160.0, 170.0)


def test_charge_setup_anaerobic_label_lands_on_the_natural_band() -> None:
    """Fermented/anaerobic processes group with the naturals (owner ruling):
    they carry the same surface sugars from extended mucilage/fruit contact."""
    result = _charge(process_type_lower="anaerobic fermentation")
    assert result.band == (170.0, 180.0)


def test_charge_setup_unrecognised_process_falls_back_to_washed() -> None:
    result = _charge(process_type_lower="gesha")
    assert result.band == (180.0, 190.0)


def test_charge_setup_modulation_is_capped_and_stays_inside_the_band() -> None:
    """All four contributions pushed positive and extreme — density 1000,
    altitude 3500, humidity 20, ambient -10 — sum far past the ±5°C cap, but
    the result never leaves the process band."""
    result = _charge(process_type_lower="washed", density=1000.0, culture_altitude=3500.0,
                      humidity=20.0, ambient_temp_c=-10.0)
    assert result.temperature_c - result.nominal_temperature_c == pytest.approx(5.0)
    assert result.band[0] <= result.temperature_c <= result.band[1]


def test_charge_setup_zero_readings_are_treated_as_unmeasured_and_stay_silent(caplog) -> None:
    """0.0 is the codebase-wide 'not measured' sentinel for density and
    humidity — absent, not implausible; must not warn."""
    with caplog.at_level('WARNING'):
        result = _charge(density=0.0, humidity=0.0)
    assert not [r for r in caplog.records if 'out of plausible' in r.getMessage()]
    assert result.temperature_c == pytest.approx(result.nominal_temperature_c)


def test_charge_setup_out_of_window_density_is_ignored_and_logged(caplog) -> None:
    """The corpus has sensor/entry errors (density read as 2500) that used to
    saturate the modulation with no warning; out-of-window now contributes 0
    and is logged."""
    with caplog.at_level('WARNING'):
        result = _charge(density=2500.0)
    assert any('out of plausible' in r.getMessage() for r in caplog.records)
    assert result.temperature_c == pytest.approx(result.nominal_temperature_c)


def test_charge_setup_applies_heat_soak_after_the_band_clamp() -> None:
    """Batch 2+: the heat-soak correction must be able to push the charge
    under the band floor — that is its purpose (design validé 2026-07-04)."""
    result = _charge(process_type_lower="decaf", minutes_since_last_drop=0.0)
    assert result.soak_dcharge_c < 0.0
    assert result.temperature_c == pytest.approx(
        max(120.0, result.nominal_temperature_c + result.soak_dcharge_c))


# ── _resolve_burner_setpoints — grid/learned dry/Maillard/dev/pre-FC, ───────
# Maillard energy floor
# Pure stage (banc 2026-08-05): the process/humidity grid base, the learned
# heater profile adoption (drops the grid corrections at n>=3, they are
# already embodied in the learned value), the Maillard energy floor (can only
# ever raise a setpoint), and the learned pre-FC setpoint (fallback = the dev
# column). Defaults below: washed process, heater_cmfc=(0.85, 0.75, 0.60),
# humidity/ambient_humidity/agtron_mean all inside their neutral windows (no
# heater_compensation), density/water_activity/ambient_temp_c at the
# codebase-wide "unmeasured" sentinel (0.0) — so the Maillard floor collapses
# to the washed process base (level=62.0, release_fraction=0.75) with no
# modulation, and stays below the default grid dry/Maillard setpoints (80/70).

def _burner(plan_model: TilauScopeRoastPlan, *, humidity=10.0, ambient_humidity=50.0,
            is_light_roast=False, is_fir_nir=False, agtron_mean=60.0,
            process_type_lower="washed", process_type="Washed",
            density=0.0, bean_varieties="", bean_country="", water_activity=0.0,
            ambient_temp_c=0.0, heater_cmfc=(0.85, 0.75, 0.60),
            cal_heater_dry_pct=0.0, cal_heater_mai_pct=0.0, soak_dheater_pct=0,
            heater_max_pct=100.0, heater_samples=0, heater_dry_learned=None,
            heater_mai_learned=None, heater_dev_learned=None,
            heater_fc_learned=None, heater_fc_samples=0) -> Any:
    from types import SimpleNamespace
    return plan_model._resolve_burner_setpoints(
        humidity=humidity, ambient_humidity=ambient_humidity,
        is_light_roast=is_light_roast, is_fir_nir=is_fir_nir,
        agtron_mean=agtron_mean, process_type_lower=process_type_lower,
        process_type=process_type, density=density,
        bean_varieties=bean_varieties, bean_country=bean_country,
        water_activity=water_activity, ambient_temp_c=ambient_temp_c,
        roast_constraints=SimpleNamespace(heater_cmfc=heater_cmfc),
        cal_heater_dry_pct=cal_heater_dry_pct, cal_heater_mai_pct=cal_heater_mai_pct,
        soak_dheater_pct=soak_dheater_pct, heater_max_pct=heater_max_pct,
        heater_samples=heater_samples, heater_dry_learned=heater_dry_learned,
        heater_mai_learned=heater_mai_learned, heater_dev_learned=heater_dev_learned,
        heater_fc_learned=heater_fc_learned, heater_fc_samples=heater_fc_samples)


def test_burner_setpoints_without_history_uses_the_grid(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """No learned heater history: the process/humidity grid base passes
    through untouched and the source says so. Pre-FC's fallback is the dev
    column (doctrine — the floor exists precisely to correct this fallback
    when it sits too low, see the next tests)."""
    result = _burner(plan_model)
    assert result.heater_source == 'grid'
    assert result.heater_dry == pytest.approx(80.0)       # 85 - 5 (washed)
    assert result.heater_maillard == pytest.approx(70.0)  # 75 - 5
    assert result.heater_dev == pytest.approx(55.0)       # 60 - 5
    assert result.heater_fc_source == 'grid'
    assert result.heater_pre_fc == pytest.approx(result.heater_dev)
    assert result.heater_tp == pytest.approx(75.0)         # heater_dry - 5


def test_learned_heater_profile_at_three_samples_replaces_the_grid_without_reapplying_its_corrections(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """At n>=3 the learned median IS the setpoint: the grid's process/humidity
    corrections must NOT be re-added on top, they are already embodied in
    what the operator actually held on this machine."""
    result = _burner(
        plan_model, heater_samples=3,
        heater_dry_learned=72.0, heater_mai_learned=68.0, heater_dev_learned=58.0)
    assert result.heater_source.startswith('learned')
    assert result.heater_dry == pytest.approx(72.0)
    assert result.heater_maillard == pytest.approx(68.0)
    assert result.heater_dev == pytest.approx(58.0)


def test_the_energy_floor_raises_a_maillard_setpoint_below_it_and_leaves_a_higher_one_untouched(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The floor can only RAISE — every application is a max(). Here the grid
    Maillard setpoint (50) sits below the washed floor (level 62, flat until
    release_fraction 0.75, so at(0.5)==level) and gets raised to it, while the
    grid dry setpoint (75), already above the floor, is left untouched."""
    result = _burner(plan_model, heater_cmfc=(0.80, 0.55, 0.45))
    assert result.heater_dry == pytest.approx(75.0)        # 80 - 5, already above floor
    assert result.heater_maillard == pytest.approx(62.0)   # 55 - 5 = 50, raised to the floor


def test_the_energy_floor_never_lowers_a_setpoint_above_it(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """A learned value well above the floor must survive unmodified — the
    floor is a one-sided max(), never a min()."""
    result = _burner(
        plan_model, heater_samples=3,
        heater_dry_learned=90.0, heater_mai_learned=90.0, heater_dev_learned=90.0)
    assert result.heater_dry == pytest.approx(90.0)
    assert result.heater_maillard == pytest.approx(90.0)


def test_the_machine_ceiling_caps_every_setpoint(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The burner ceiling comes from the machine (heater_max_pct), not a flat
    100 — every setpoint, including the floor-raised ones and the pre-FC
    fallback, must be clamped to it."""
    result = _burner(plan_model, heater_cmfc=(0.95, 0.95, 0.95), heater_max_pct=50.0)
    assert result.heater_dry == pytest.approx(50.0)
    assert result.heater_maillard == pytest.approx(50.0)
    assert result.heater_dev == pytest.approx(50.0)
    assert result.heater_pre_fc == pytest.approx(50.0)


# ── _resolve_heater_ramp — pre-FC anchor, Dev Ramp coherence, learned ───────
# pre-dry-end anti-flick gesture, and the built heater ramp
# Pure stage (banc 2026-08-05). Defaults below reuse the _TP_C/_DE_C/_FC_C
# anchors from the _build_heater_ramp_c tests above (95/150/189), a 6-minute
# Maillard, mid-range dev_inertia (0.5), and a neutral floor (level_pct=50,
# release_fraction=0.75 — its released end, at(1.0), is exactly the
# FLOOR_ABSOLUTE_PCT the module clamps to, so it never raises the default
# 50 % pre-FC/dev setpoints). No learned pre-dry-end history by default, so
# no anti-flick gesture fires.

def _heater_ramp(plan_model: TilauScopeRoastPlan, *, dry_bt_temperature=150.0,
                  fc_bt=189.0, maillard_time_min=6.0, dev_inertia=0.5,
                  expected_tp_bt=95.0, dry_ror_average=8.0,
                  heater_dry=75.0, heater_maillard=65.0, heater_dev=50.0,
                  heater_pre_fc=50.0, dev_free_pct=50.0,
                  floor=None, heater_max_pct=100.0,
                  heater_resolution_pct=1.0, has_heater_control=True,
                  heater_de_learned=None, heater_de_samples=0,
                  pre_de_descent_samples=0, pre_de_lead_learned=None,
                  pre_de_step_learned=None) -> Any:
    if floor is None:
        floor = FloorProfile(level_pct=50.0, release_fraction=0.75)
    return plan_model._resolve_heater_ramp(
        dry_bt_temperature=dry_bt_temperature, fc_bt=fc_bt,
        maillard_time_min=maillard_time_min, dev_inertia=dev_inertia,
        expected_tp_bt=expected_tp_bt, dry_ror_average=dry_ror_average,
        to_native=lambda v: v,
        heater_dry=heater_dry, heater_maillard=heater_maillard, heater_dev=heater_dev,
        heater_pre_fc=heater_pre_fc, dev_free_pct=dev_free_pct,
        floor=floor, heater_max_pct=heater_max_pct,
        heater_resolution_pct=heater_resolution_pct, has_heater_control=has_heater_control,
        heater_de_learned=heater_de_learned, heater_de_samples=heater_de_samples,
        pre_de_descent_samples=pre_de_descent_samples,
        pre_de_lead_learned=pre_de_lead_learned,
        pre_de_step_learned=pre_de_step_learned)


def test_pre_fc_anchor_leads_first_crack_by_the_anticipation_delay(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The pre-FC anchor is not a clock offset — it is the Maillard slope
    (FC−dry_bt over the Maillard duration) applied over fc_anticipation_sec,
    subtracted from FC. Both derive from dev_inertia (higher inertia →
    anticipates earlier, doctrine bounds [15, 90] s)."""
    result = _heater_ramp(plan_model, dev_inertia=0.5, maillard_time_min=6.0)
    fc_anticipation_sec = 20.0 + 70.0 * 0.5   # 55.0, inside [15, 90]
    assert result.fc_anticipation_sec == pytest.approx(fc_anticipation_sec)
    ror_maillard_c = (189.0 - 150.0) / 6.0    # 6.5 °C/min
    bt_lead_c = ror_maillard_c * fc_anticipation_sec / 60.0
    assert result.pre_fc_c == pytest.approx(189.0 - bt_lead_c)


def test_pre_fc_setpoint_is_raised_to_the_floors_released_end(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The pre-FC step still belongs to Maillard: its fallback (the dev
    column) can sit well below the grain's energy demand there. The floor's
    RELEASED end (at(1.0), not the flat level) is what borders it — that
    released end IS the small anti-rebound reduction landing on the pre-FC
    step, per doctrine."""
    floor = FloorProfile(level_pct=70.0, release_fraction=0.75)
    result = _heater_ramp(plan_model, heater_pre_fc=50.0, floor=floor)
    assert result.heater_pre_fc == pytest.approx(65.0)   # 70 - RELEASE_DROP_PCT(5)


def test_pre_fc_setpoint_never_exceeds_the_maillard_level(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """A pre-FC value learned hotter than the Maillard median (a separate
    cohort — heater_fc_learned vs the phase median) must be capped to it: the
    fire never climbs back up before first crack. Without this cap,
    _build_heater_ramp_c falls into its non-monotone fallback and faithfully
    draws the descend-then-rise staircase — a gesture no operator can execute
    (2026-08-06 field report, Costa Rica Catuai natural, light, 400 g)."""
    result = _heater_ramp(plan_model, heater_maillard=46.0, heater_pre_fc=51.0)
    assert result.heater_pre_fc == pytest.approx(46.0)


def test_pre_fc_setpoint_capped_by_maillard_still_respects_the_floor(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The Maillard cap applies AFTER the floor raise, not instead of it: a
    floor-raised pre-FC that is still below the (also floor-raised) Maillard
    level must pass through unchanged."""
    floor = FloorProfile(level_pct=70.0, release_fraction=0.75)
    result = _heater_ramp(
        plan_model, heater_maillard=68.0, heater_pre_fc=50.0, floor=floor)
    assert result.heater_pre_fc == pytest.approx(65.0)   # 70 - RELEASE_DROP_PCT(5)


def test_development_setpoint_never_drops_more_than_the_cap_below_pre_fc(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The Dev Ramp holds the fire in development — it never descends more
    than the drop cap below the (possibly floor-raised) pre-FC step. The
    formatted heater summary is built AFTER this recalculation, so it must
    reflect the raised value, not the original grid/learned one."""
    floor = FloorProfile(level_pct=70.0, release_fraction=0.75)
    result = _heater_ramp(
        plan_model, heater_dry=75.0, heater_maillard=65.0,
        heater_dev=50.0, dev_free_pct=50.0, heater_pre_fc=50.0, floor=floor)
    assert result.heater_pre_fc == pytest.approx(65.0)   # raised by the floor, see above
    assert result.heater_dev == pytest.approx(59.0)      # 65 - _DEV_BURNER_DROP_CAP(6)
    assert result.heater == ["75%", "65%", "59%"]


def test_a_rejected_pre_dry_end_anchor_also_rejects_its_learned_lead(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """heater_dry already reflects the Maillard floor's raise (done in
    _resolve_burner_setpoints, upstream of this stage) — when the learned
    pre-dry-end value no longer sits meaningfully below it, the anti-flick
    gesture doesn't fire (`pre_de_active` False). The learned lead/step must
    be rejected WITH it: reading them for a gesture that never happens would
    start the burner descent early for nothing, so the doctrine lead/step
    (_HOLD_LEAD_SEC / _OBSERVABLE_PCT) must survive untouched even though
    plausible learned lead/step values are supplied."""
    result = _heater_ramp(
        plan_model, heater_dry=80.0,
        heater_de_learned=80.0, heater_de_samples=3,
        pre_de_descent_samples=5, pre_de_lead_learned=200.0, pre_de_step_learned=3.0)
    assert result.pre_de_active is False
    assert result.heater_pre_de == pytest.approx(80.0)
    assert result.de_lead_sec == pytest.approx(30.0)   # _HOLD_LEAD_SEC, learned 200 rejected
    assert result.de_step_pct == pytest.approx(5.0)    # _OBSERVABLE_PCT, learned 3 rejected


# ── _resolve_drum_speed — ONE setup value for all three phases ──────────────
# Pure stage (banc 2026-08-05). Doctrine (2026-07-11): the drum is chosen
# ONCE at charge from batch weight and density, then held — never an
# in-roast gesture, hence a single value published across dry/Maillard/dev.

def _drum(plan_model: TilauScopeRoastPlan, *, charge_weight=400.0, density=700.0,
          batch_optimal_g=400.0, drum_variable_speed=True,
          drum_min_setting=0.0, drum_step_rpm=1.0,
          drum_min_rpm=34.0, drum_max_rpm=68.0) -> Any:
    return plan_model._resolve_drum_speed(
        charge_weight=charge_weight, density=density,
        batch_optimal_g=batch_optimal_g, drum_variable_speed=drum_variable_speed,
        drum_min_setting=drum_min_setting, drum_step_rpm=drum_step_rpm,
        drum_min_rpm=drum_min_rpm, drum_max_rpm=drum_max_rpm)


def test_drum_speed_is_the_same_value_for_all_three_phases(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The plan emits ONE setup value, published identically for dry/Maillard/
    dev — nothing in this stage may ever diverge the three columns, per the
    "never moved during a roast" doctrine."""
    result = _drum(plan_model, charge_weight=350.0, density=720.0)
    assert result.drum_speed_pct[0] == result.drum_speed_pct[1] == result.drum_speed_pct[2]


def test_a_fixed_speed_drum_yields_the_skip_marker(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """A machine with no variable-speed drum must never publish a number —
    the "--" marker tells downstream consumers (alarm factory, PDF) to skip
    drum events entirely."""
    result = _drum(plan_model, drum_variable_speed=False)
    assert result.drum_speed_pct == ["--", "--", "--"]


def test_drum_percentage_rounds_down_to_the_machine_step(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The %-space snap is a FLOOR, not a round to nearest: rounding up
    pushed a borderline batch past what the machine can actually settle at
    (owner fix 2026-08-04, see RoasterContext.rpm_to_percent). Chosen inputs
    place the raw RPM setpoint at 71 out of a [0, 150] RPM range with a step
    of 10: rounded to the nearest RPM step that's 70 RPM, which maps to
    46.67% of a [0, 100] setting range — floored to 40%, not rounded to 50%."""
    import types
    from tilauscope.roasters import RoasterContext
    fake_ctx = types.SimpleNamespace(
        drum_variable_speed=True, drum_min_rpm=0.0, drum_max_rpm=150.0,
        drum_step_rpm=10.0, drum_min_setting=0.0)
    fake_ctx.rpm_to_percent = types.MethodType(RoasterContext.rpm_to_percent, fake_ctx)
    plan_model._roaster_ctx = fake_ctx
    result = _drum(
        plan_model, charge_weight=339.33333333333337, density=700.0,
        batch_optimal_g=400.0, drum_min_setting=0.0, drum_step_rpm=10.0,
        drum_min_rpm=0.0, drum_max_rpm=150.0)
    assert result.drum_speed_pct[0] == "40%"


# ── _resolve_airflow_extraction — airflow/extraction base, Maillard Air ─────
# Ramp, Development Ramp
# Pure stage (banc 2026-08-05). Defaults below: no AirWave (self._airwave_present
# stays False on a fresh plan_model), push-air machine, neutral humidity (no
# compensation), airflow_resolution_pct 5.0 — the same shape the corpus
# scenarios exercise.

def _airflow(plan_model: TilauScopeRoastPlan, *, airflow_dependency_index=0.65,
             humidity=10.0, ambient_humidity=50.0, inlet_air_mode="push",
             airflow_resolution_pct=5.0, dry_bt_temperature=150.0, fc_bt=189.0,
             pre_fc_c=185.0, drop_bt_temperature=200.0,
             heater_pre_fc=55.0, heater_dev=50.0, has_heater_control=True,
             heater_resolution_pct=1.0, dev_trajectory_learned=None,
             dev_traj_samples=0, airwave_present=False) -> Any:
    plan_model._airwave_present = airwave_present
    return plan_model._resolve_airflow_extraction(
        airwave_present=False,
airflow_dependency_index=airflow_dependency_index, humidity=humidity,
        ambient_humidity=ambient_humidity, inlet_air_mode=inlet_air_mode,
        airflow_resolution_pct=airflow_resolution_pct,
        dry_bt_temperature=dry_bt_temperature, fc_bt=fc_bt, pre_fc_c=pre_fc_c,
        drop_bt_temperature=drop_bt_temperature, to_native=lambda v: v,
        heater_pre_fc=heater_pre_fc, heater_dev=heater_dev,
        has_heater_control=has_heater_control,
        heater_resolution_pct=heater_resolution_pct,
        dev_trajectory_learned=dev_trajectory_learned, dev_traj_samples=dev_traj_samples)


def test_the_maillard_air_ramp_opens_progressively_and_never_closes(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The airflow ramp chases the smoke that arrives with browning: every
    step from mid-Maillard to first crack must be at least as open as the
    one before it (monotone rise, never a dip)."""
    result = _airflow(plan_model)
    assert result.air_ramp
    for a, b in pairwise(result.air_ramp):
        assert b["airflow"] >= a["airflow"]


def test_development_ramp_lowers_the_burner_while_raising_the_air(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The Dev Ramp couples the two gestures: the burner comes down from its
    pre-FC step while the air opens further to support the reaction — both
    move across the same span of steps (doctrine: "together")."""
    result = _airflow(plan_model, heater_pre_fc=60.0, heater_dev=48.0)
    assert result.dev_ramp
    heater_steps = [e["heater"] for e in result.dev_ramp if "heater" in e]
    airflow_steps = [e["airflow"] for e in result.dev_ramp if "airflow" in e]
    assert heater_steps, "the burner must move across the ramp"
    assert airflow_steps, "the air must move across the ramp"
    assert heater_steps[-1] < heater_steps[0]
    assert airflow_steps[-1] > airflow_steps[0]


def test_the_burner_never_falls_more_than_the_drop_cap_in_development(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The burner is HELD in development, never collapsed — a deep drop was
    tested and refuted (it crashes more), hence the drop cap below the pre-FC
    step (banc 2026-07-11)."""
    result = _airflow(plan_model, heater_pre_fc=70.0, heater_dev=20.0)
    heater_steps = [e["heater"] for e in result.dev_ramp if "heater" in e]
    assert heater_steps
    assert min(heater_steps) >= 70.0 - 6.0   # _DEV_BURNER_DROP_CAP


# ── _resolve_plan_confidence — confidence level, tolerance, heat-soak note ──
# Pure stage (banc 2026-08-05, design validé 2026-07-04): scores the three
# source strings (grid/blend/learned), demotes a scattered high-confidence
# history to medium, derives the tightening tolerance factor and translated
# display string, and emits the back-to-back heat-soak note. Defaults below:
# all three sources "grid" (score 0 → low), no MAD reading, no heat-soak
# correction — so a bare call is the low-confidence, no-note baseline.

def _confidence(plan_model: TilauScopeRoastPlan, *, fc_source="grid",
                 timing_source="grid", drop_source="grid",
                 fc_bt_mad_c=None, soak_dcharge_c=0.0, soak_dheater_pct=0,
                 minutes_since_last_drop=None, ror_scale=1.0) -> Any:
    return plan_model._resolve_plan_confidence(
        fc_source=fc_source, timing_source=timing_source, drop_source=drop_source,
        fc_bt_mad_c=fc_bt_mad_c, soak_dcharge_c=soak_dcharge_c,
        soak_dheater_pct=soak_dheater_pct,
        minutes_since_last_drop=minutes_since_last_drop, ror_scale=ror_scale)


def test_three_grid_sources_give_the_lowest_confidence(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """All three sources "grid" score 0 — the floor of the scale."""
    result = _confidence(plan_model, fc_source="grid", timing_source="grid",
                          drop_source="grid")
    assert result.level == "low"


def test_three_fully_learned_sources_give_the_highest_confidence(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Three "learned (n=N)" sources score 2 each (6, >= 4) — the ceiling."""
    result = _confidence(
        plan_model, fc_source="learned (n=5)", timing_source="learned (n=5)",
        drop_source="learned (n=5)")
    assert result.level == "high"


def test_a_blend_label_scores_as_a_blend_not_as_fully_learned(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """"learned/grid blend (n=2)" contains "blend" and must score 1, not 2 —
    a startswith("learned") check alone would misclassify it as fully
    learned. Two blend sources (score 1+1=2) plus one grid (0) land at
    medium, never high."""
    result = _confidence(
        plan_model, fc_source="learned/grid blend (n=2)",
        timing_source="learned/grid blend (n=2)", drop_source="grid")
    assert result.level == "medium"


def test_a_scattered_first_crack_history_demotes_high_to_medium(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """Three learned sources alone reach high, but a FC MAD above 2.5°C —
    badly marked milestones or heterogeneous batches — demotes it back to
    medium, even though the history is plentiful."""
    full_learned = _confidence(
        plan_model, fc_source="learned (n=5)", timing_source="learned (n=5)",
        drop_source="learned (n=5)")
    assert full_learned.level == "high"
    scattered = _confidence(
        plan_model, fc_source="learned (n=5)", timing_source="learned (n=5)",
        drop_source="learned (n=5)", fc_bt_mad_c=2.6)
    assert scattered.level == "medium"


def test_the_tolerance_factor_tightens_as_confidence_rises(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """1.35 (low) relaxes the bands, 0.8 (high) tightens them — the factor
    must strictly decrease as confidence climbs, never the other way round."""
    low = _confidence(plan_model, fc_source="grid", timing_source="grid",
                       drop_source="grid")
    medium = _confidence(plan_model, fc_source="learned (n=5)",
                          timing_source="grid", drop_source="grid")
    high = _confidence(plan_model, fc_source="learned (n=5)",
                        timing_source="learned (n=5)", drop_source="learned (n=5)")
    assert low.tol_factor == pytest.approx(1.35)
    assert medium.tol_factor == pytest.approx(1.0)
    assert high.tol_factor == pytest.approx(0.8)
    assert low.tol_factor > medium.tol_factor > high.tol_factor


def test_the_back_to_back_note_needs_both_a_negative_correction_and_a_time(
    plan_model: TilauScopeRoastPlan,
) -> None:
    """The heat-soak note fires only when the correction is negative AND a
    time since the last drop was supplied — either alone stays silent."""
    both = _confidence(plan_model, soak_dcharge_c=-3.0, soak_dheater_pct=-4,
                        minutes_since_last_drop=6.0)
    assert both.soak_note

    no_time = _confidence(plan_model, soak_dcharge_c=-3.0, soak_dheater_pct=-4,
                           minutes_since_last_drop=None)
    assert no_time.soak_note is None

    no_correction = _confidence(plan_model, soak_dcharge_c=0.0,
                                 soak_dheater_pct=0, minutes_since_last_drop=6.0)
    assert no_correction.soak_note is None


# ── Section 5 of the PDF — the heater/airflow trajectories ──────────────────
# The drawing is not tested (it is FPDF geometry); what is tested is the DATA
# behind it, because it is derived and can be silently wrong: the plan anchors
# every step on bean temperature, and the graph has to place them on a time
# axis. See _control_trajectories for why the scan starts at the turning point.

def _new_pdf():
    """A fresh builder. Registering the Unicode family opens the font files,
    and fpdf2 only releases them at output(), so use this only for tests that
    actually render."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF
    return BuildPRoastPlanPDF(orientation='P', unit='mm', format='A4', temp_unit='C')


_PDF_SHARED: Any = None


def _pdf():
    """One shared builder for the data-only tests below.

    They exercise _control_trajectories / _entry_settings / _control_gestures,
    which read the plan dict and never touch typography. Building one instance
    per test would hold four font descriptors open per test for nothing."""
    global _PDF_SHARED
    if _PDF_SHARED is None:
        _PDF_SHARED = _new_pdf()
    return _PDF_SHARED


def _traj_plan(**overrides: Any) -> dict:
    """A plan carrying the four keys the trajectories are built from, over a
    BT curve that falls to a turning point before rising — the real shape."""
    times = [i * 0.1 for i in range(101)]            # 0 .. 10 min
    # 180 -> 90 (TP at 1 min) -> 210 at 10 min
    bts: list[float] = []
    for t in times:
        bts.append(180.0 - 90.0 * (t / 1.0) if t <= 1.0
                   else 90.0 + 120.0 * ((t - 1.0) / 9.0))
    plan = {
        "bt_plan_curve": {
            "time_min": times, "bt_plan": bts,
            "waypoints": [
                {"key": "charge", "time_min": 0.0, "bt": 180.0},
                {"key": "tp", "time_min": 1.0, "bt": 90.0},
                {"key": "dry_end", "time_min": 5.5, "bt": 150.0},
                {"key": "fc_start", "time_min": 8.5, "bt": 190.0},
                {"key": "drop", "time_min": 10.0, "bt": 210.0},
            ],
        },
        "Heater (%) (Dry|Mai|Dev)": "70% | 60% | 45%",
        "Airflow (%) (Dry|Mai|Dev)": "20% | 30% | 40%",
        "Drum Speed (%) (Dry|Mai|Dev)": "85% | 85% | 85%",
        "Heater Ramp": [{"heater": 65, "bt": 152.0}, {"heater": 55, "bt": 175.0}],
        "Air Ramp": [{"bt": 178.0, "airflow": 35}],
        "Dev Ramp": [{"bt": 195.0, "heater": 50, "airflow": 45}],
    }
    plan.update(overrides)
    return plan


def test_control_trajectories_hold_the_charge_value_until_the_ramp_takes_over() -> None:
    """The burner does not move at CHARGE and does not move at DRY END: it
    holds its charge value until the anticipated ramp's first step."""
    heater, _, ms = _pdf()._control_trajectories(_traj_plan())
    assert heater[0] == (0.0, 70.0)
    # First move lands after the turning point and near dry end, not at t=0.
    assert heater[1][0] > ms["tp"]
    assert heater[1][1] == 65.0


def test_control_trajectories_place_steps_after_the_turning_point() -> None:
    """The guard that matters: BT falls from the charge temperature to the TP
    before it rises, so 152 °C exists TWICE on the curve. A scan from t=0 would
    resolve the first dry-end step against the charge descent and draw it in the
    first seconds of the roast."""
    heater, _, ms = _pdf()._control_trajectories(_traj_plan())
    for t, _v in heater[1:]:
        assert t > ms["tp"], f'step placed at {t:.2f} min, before TP {ms["tp"]}'


def test_control_trajectories_descend_the_heater_and_climb_the_airflow() -> None:
    """The plan's shape: burner only ever comes down, airflow only ever goes
    up. A trajectory that reversed would mean the ramps were mis-assembled."""
    heater, airflow, _ = _pdf()._control_trajectories(_traj_plan())
    assert [v for _t, v in heater] == sorted((v for _t, v in heater), reverse=True)
    assert [v for _t, v in airflow] == sorted(v for _t, v in airflow)


def test_control_trajectories_step_the_airflow_up_at_dry_end() -> None:
    """Airflow is posted per phase, so the Maillard value lands exactly on the
    dry-end milestone — unlike the burner, which is ramp-governed."""
    _, airflow, ms = _pdf()._control_trajectories(_traj_plan())
    assert (ms["dry_end"], 30.0) in airflow


def test_control_trajectories_carry_both_levers_through_development() -> None:
    """The Dev Ramp governs heater AND airflow after first crack; both final
    values must come from it, not from the phase summary."""
    heater, airflow, _ = _pdf()._control_trajectories(_traj_plan())
    assert heater[-1][1] == 50.0
    assert airflow[-1][1] == 45.0


def test_control_trajectories_are_empty_without_a_planned_curve() -> None:
    """No curve means no time axis, so the PDF section is skipped rather than
    printing a titled blank page."""
    heater, airflow, ms = _pdf()._control_trajectories({"Heater Ramp": [{"heater": 60, "bt": 150}]})
    assert heater == [] and airflow == [] and ms == {}


# ── Section 4 — settings AT PHASE ENTRY ─────────────────────────────────────
# The old table printed a per-phase average. A mean is not a setting anyone
# dials, and reading it as one posts the middle of the ramp at the start of the
# phase. These tests pin the entry reading instead.

def test_entry_settings_read_the_value_held_when_the_milestone_is_crossed() -> None:
    """Burner: the charge value is still held at dry end (the descent starts
    just after it), and the pre-FC value is what arrives at first crack."""
    rows = dict(_pdf()._entry_settings(_traj_plan()))
    assert rows['Heater (%)'] == ['70%', '70%', '55%']


def test_entry_settings_step_the_airflow_at_dry_end_but_not_at_fc() -> None:
    """Airflow is posted at each phase, so it moves at dry end; at first crack
    the Dev Ramp takes over, so the value crossing FC is still the Maillard one."""
    rows = dict(_pdf()._entry_settings(_traj_plan()))
    assert rows['Airflow (%)'] == ['20%', '30%', '35%']


def test_entry_settings_are_not_the_phase_average() -> None:
    """The guard against a silent revert to the old table: the summary string
    says 60% for Maillard, and the entry column must not echo it."""
    plan = _traj_plan()
    assert plan['Heater (%) (Dry|Mai|Dev)'].split('|')[1].strip() == '60%'
    rows = dict(_pdf()._entry_settings(plan))
    assert rows['Heater (%)'][1] != '60%'


def test_entry_settings_repeat_the_drum_across_every_column() -> None:
    """Drum speed is a setup value: one setting for the whole roast."""
    rows = dict(_pdf()._entry_settings(_traj_plan()))
    assert rows['Drum Speed (%)'] == ['85%', '85%', '85%']


# ── Section 5 — the gesture checklist ───────────────────────────────────────

def test_control_gestures_are_chronological_and_carry_both_levers() -> None:
    gestures = _pdf()._control_gestures(_traj_plan())
    assert [g['t'] for g in gestures] == sorted(g['t'] for g in gestures)
    assert {g['lever'] for g in gestures} == {'Heater', 'Airflow'}


def test_control_gestures_state_the_move_not_the_level() -> None:
    """Each row is a gesture: where the lever comes from and where it goes.
    A row whose from == to would be an instruction to do nothing."""
    for g in _pdf()._control_gestures(_traj_plan()):
        assert g['frm'] != g['to']


def test_control_gestures_label_the_phase_each_move_falls_in() -> None:
    gestures = _pdf()._control_gestures(_traj_plan())
    _, _, ms = _pdf()._control_trajectories(_traj_plan())
    for g in gestures:
        expected = ('Dry' if g['t'] < ms['dry_end']
                    else 'Maillard' if g['t'] < ms['fc_start'] else 'Development')
        assert g['phase'] == expected


def test_control_gestures_are_empty_without_a_planned_curve() -> None:
    assert _pdf()._control_gestures({'Heater Ramp': [{'heater': 60, 'bt': 150}]}) == []


# ── The roast-plan PDF must survive every shipped language ──────────────────
# FPDF's core fonts are latin-1 and RAISE on anything else, which took the whole
# plan down for 18 of the 35 languages (2026-08-06): a single word like CHARGE
# translated to "ÚČTOVAT" or "投豆" was enough. A registered Unicode family
# renders an unknown glyph blank instead, so the worst case is a gap, never a
# missing report.

_HARD_STRINGS = [
    ('cs', 'ÚČTOVAT'), ('ru', 'Загрузить бобы'), ('el', 'ΦΟΡΤΩΜΑ'),
    ('zh', '投豆'), ('ja', '/分'), ('ko', '투입'),
    ('he', 'טען'), ('ar', 'تحميل'), ('th', 'เริ่มใส่เมล็ด'),
    ('fr', 'Brûleur à 70 %'), ('tr', 'Giriş'), ('vi', 'Nạp Liệu'),
]


@pytest.mark.parametrize(('lang', 'text'), _HARD_STRINGS, ids=[l for l, _ in _HARD_STRINGS])
def test_the_pdf_renders_every_shipped_language_without_raising(lang: str, text: str) -> None:
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font('helvetica', '', 12)
    pdf.cell(0, 8, f'{lang}: {text}')      # must not raise
    assert pdf.output()


def test_the_pdf_uses_the_unicode_family_not_a_core_font() -> None:
    """The guard against a silent revert: if the bundled fonts go missing the
    builder degrades to 'helvetica' on purpose, and the languages above break
    again. Ship-time, the Unicode family must be the one in use."""
    assert _pdf()._family == 'tilauplan'


@pytest.mark.parametrize('style', ['', 'B', 'I'])
def test_every_font_style_the_report_uses_is_registered(style: str) -> None:
    """A style the report asks for but never registered raises 'Undefined
    font' at render time - only on the page that happens to use it."""
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font('helvetica', style, 10)
    pdf.cell(0, 6, 'Séquence des paliers')
    assert pdf.output()


# ── Bidirectional scripts in the PDF ────────────────────────────────────────
# FPDF draws glyphs in the order given, with no shaping and no reordering, so
# Arabic would come out as disconnected letters and a number inside a
# right-to-left sentence would land on the wrong side. Same pair as Artisan's
# own graph labels: arabic_reshaper (joining) then get_display (visual order).

_AR = 'تحميل الحبوب 200 درجة'
_HE = 'טען פולים 200 מעלות'


def _is_presentation_form(ch: str) -> bool:
    """Arabic contextual forms live in FE70-FEFF (and FB50-FDFF)."""
    cp = ord(ch)
    return 0xFE70 <= cp <= 0xFEFF or 0xFB50 <= cp <= 0xFDFF


def test_bidi_leaves_left_to_right_text_untouched() -> None:
    """The common path must not pay for the rare one, and must not risk
    mangling a French or Cyrillic string."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF as B
    for text in ('Brûleur à 70 %', 'Загрузить 200', '投豆 200°C', 'Step sequence', ''):
        assert B._bidi(text) == text


def test_bidi_joins_arabic_letters() -> None:
    """Joining is what makes the script readable: the output must be in
    contextual forms, not the isolated letters of the source."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF as B
    out = B._bidi(_AR)
    assert any(_is_presentation_form(c) for c in out)
    assert not any(_is_presentation_form(c) for c in _AR)


def test_bidi_reorders_so_numbers_land_inside_the_sentence() -> None:
    """A right-to-left run puts its digits in visual order; without the bidi
    pass '200' drifts to the end of the line."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF as B
    for src in (_AR, _HE):
        out = B._bidi(src)
        assert out != src
        assert '200' in out


def test_bidi_does_not_reshape_hebrew() -> None:
    """Hebrew does not join; running the Arabic reshaper over it would be
    wrong. Only the reordering step applies."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF as B
    out = B._bidi(_HE)
    assert not any(_is_presentation_form(c) for c in out)
    assert sorted(out) == sorted(_HE)      # a pure permutation


def test_bidi_order_of_the_two_steps_is_not_interchangeable() -> None:
    """Reshaping AFTER reordering computes the joining forms on a reversed
    string and unjoins it again. This pins the correct order."""
    import arabic_reshaper
    from bidi import get_display
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF as B
    correct = B._bidi(_AR)
    inverted = arabic_reshaper.reshape(get_display(_AR))
    assert correct != inverted


@pytest.mark.parametrize('method', ['cell', 'multi_cell', 'text'])
def test_every_text_method_routes_through_the_bidi_pass(method: str) -> None:
    """Routed centrally on purpose: one un-routed call site would leave a
    single label unjoined, which is what nobody catches in review."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF
    seen: list = []

    class Spy(BuildPRoastPlanPDF):
        @classmethod
        def _bidi(cls, text):
            seen.append(text)
            return super()._bidi(text)

    pdf = Spy(orientation='P', unit='mm', format='A4', temp_unit='C')
    pdf.add_page()
    pdf.set_font('helvetica', '', 10)
    if method == 'cell':
        pdf.cell(0, 6, _AR)
    elif method == 'multi_cell':
        pdf.multi_cell(0, 6, _AR)
    else:
        pdf.text(10, 10, _AR)
    assert _AR in seen
    assert pdf.output()


def test_a_full_plan_page_renders_with_arabic_content() -> None:
    """End to end: a bean name in Arabic must not break the report."""
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 7, _AR)
    pdf.ln(9)                    # cell(w=0) leaves the cursor at the right margin
    pdf.set_font('helvetica', 'I', 9)
    pdf.multi_cell(0, 4, _HE)
    assert pdf.output()


@pytest.mark.parametrize('style', ['positional', 'text_kwarg', 'txt_alias'])
def test_the_bidi_pass_survives_every_fpdf_call_style(style: str) -> None:
    """fpdf accepts the string third, as text= or as the deprecated txt=
    alias. An override that assumed one form broke the graph labels (which use
    txt=) with 'multiple values for argument text' - and only on the page that
    draws them, so no unit test would have caught it."""
    from tilauscope.roast_plan_model import BuildPRoastPlanPDF
    seen: list = []

    class Spy(BuildPRoastPlanPDF):
        @classmethod
        def _bidi(cls, text):
            seen.append(text)
            return super()._bidi(text)

    pdf = Spy(orientation='P', unit='mm', format='A4', temp_unit='C')
    pdf.add_page()
    pdf.set_font('helvetica', '', 10)
    if style == 'positional':
        pdf.multi_cell(60, 5, _AR)
    elif style == 'text_kwarg':
        pdf.multi_cell(w=60, h=5, text=_AR)
    else:
        # Still accepted by fpdf, and still reached the graph labels until this
        # batch renamed them; the warning is expected, the routing is the point.
        with pytest.warns(DeprecationWarning):
            pdf.multi_cell(w=60, h=5, txt=_AR)
    assert _AR in seen
    assert pdf.output()

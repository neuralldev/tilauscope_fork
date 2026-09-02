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

"""L2 — characterisation tests against a frozen corpus of real roasts.

These tests do not claim the plan is *good*: that is not specifiable. They
claim it is *unchanged*. Fifty-one complete real roasts are committed under
``fixtures/corpus`` — the Skywalker family at the root, plus ``cormorant`` and
``kaleido`` subdirectories so a second and third machine type are covered — and
one deliberately incomplete recording alongside them, so exclusion stays
visible. The model's reading of them, what it learns across them, and the plans
it produces are frozen in ``golden/corpus.json``.

Change the model and the suite shows you a field-by-field diff of what moved,
on real coffee. You then either accept the change (``make golden``, review the
git diff, commit) or discover you broke something.

A handful of tests alongside the snapshot assert *why* each scenario is in the
corpus — that the weight filter really excludes, that n=2 really blends. Those
would still hold if the numbers legitimately moved, so they say something the
snapshot cannot.
"""

from __future__ import annotations

import json
from typing import Any

import corpus_harness as H
import corpus_snapshot as S
import pytest

pytestmark = pytest.mark.slow


# ── snapshot fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def golden() -> dict[str, Any]:
    if not H.GOLDEN_PATH.is_file():
        pytest.fail(
            f'no golden snapshot at {H.GOLDEN_PATH}. Create it with `make golden`, '
            'then review the generated file before committing it.',
        )
    return json.loads(H.GOLDEN_PATH.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def current(qapp: Any) -> dict[str, Any]:  # noqa: ARG001  # forces the offscreen app
    return json.loads(json.dumps(S.build(), sort_keys=True, default=str))


def _diff(name: str, expected: Any, actual: Any, path: str = '') -> list[str]:
    """Field-level differences, so a failure names what moved rather than dumping."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            here = f'{path}.{key}' if path else key
            if key not in expected:
                out.append(f'  + {here} = {actual[key]!r} (new)')
            elif key not in actual:
                out.append(f'  - {here} = {expected[key]!r} (gone)')
            else:
                out.extend(_diff(name, expected[key], actual[key], here))
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f'  ~ {path}: length {len(expected)} -> {len(actual)}']
        out = []
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            out.extend(_diff(name, e, a, f'{path}[{i}]'))
        return out
    if expected != actual:
        return [f'  ~ {path}: {expected!r} -> {actual!r}']
    return []


def _assert_matches(section: str, key: str, golden: dict, current: dict) -> None:
    expected = golden.get(section, {}).get(key)
    actual = current.get(section, {}).get(key)
    if expected == actual:
        return
    lines = _diff(key, expected, actual) or ['  (structural difference)']
    shown = lines[:40]
    more = '' if len(lines) <= 40 else f'\n  ... and {len(lines) - 40} more'
    pytest.fail(
        f'{section}/{key} drifted from the golden snapshot:\n'
        + '\n'.join(shown) + more
        + '\n\nIf the change is intended: `make golden`, review the diff, commit.',
    )


# ── the snapshot itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [p.name for p in H.corpus_files()])
def test_roast_analysis_is_unchanged(
    name: str, golden: dict[str, Any], current: dict[str, Any],
) -> None:
    """What the engine reads in each recorded roast: TP, phases, RoR, events."""
    _assert_matches('roasts', name, golden, current)


@pytest.mark.parametrize('scenario', [s.name for s in S.SCENARIOS])
def test_learned_history_is_unchanged(
    scenario: str, golden: dict[str, Any], current: dict[str, Any],
) -> None:
    """What the engine learns across roasts of the same bean."""
    _assert_matches('history', scenario, golden, current)


@pytest.mark.parametrize('scenario', [s.name for s in S.SCENARIOS])
def test_generated_plan_is_unchanged(
    scenario: str, golden: dict[str, Any], current: dict[str, Any],
) -> None:
    """The end-to-end plan produced for each scenario."""
    _assert_matches('plans', scenario, golden, current)


# ── the corpus's own premises ────────────────────────────────────────────────
#
# The snapshot freezes numbers. These freeze *intent*: each fixture group is in
# the corpus to exercise one branch, and if a refactor stopped reaching that
# branch the snapshot could still pass while the coverage quietly vanished.

def test_corpus_covers_every_adoption_branch(current: dict[str, Any]) -> None:
    """The fixed corpus reaches the P1 grid, reference and two-roast paths.

    The n>=3 medoid branch is covered with purpose-built profiles in
    test_roast_plan_p1.py; this corpus deliberately contains no three-roast
    cohort with every timing, heater, airflow and finish field populated.
    """
    sources = {
        name: plan.get('History Profile Source', '')
        for name, plan in current['plans'].items()
    }
    joined = ' | '.join(f'{k}={v}' for k, v in sorted(sources.items()))
    assert any(s == 'grid' for s in sources.values()), f'no grid path: {joined}'
    assert any(s == 'reference only (n=1)' for s in sources.values()), (
        f'no one-roast reference path: {joined}')
    assert any(s == 'grid/profile blend (n=2)' for s in sources.values()), (
        f'no two-roast blend path: {joined}')


def test_weight_filter_shrinks_history_for_a_mismatched_batch(
    current: dict[str, Any],
) -> None:
    """Same bean, different batch size: the 400 g roasts must stop qualifying.

    A 250 g and a 450 g batch of one bean have incomparable RoR curves; if this
    filter ever stopped biting, the model would learn from roasts it cannot
    compare, and the failure would be invisible in the output.
    """
    big = current['history']['gr2-400-medium']
    small = current['history']['gr2-250-medium']
    assert big is not None, 'the matching 400 g reference unexpectedly disappeared'
    assert small is None, 'the mismatched 400 g histories leaked into the 250 g plan'


def test_a_bean_with_no_history_falls_back_entirely_to_the_grid(
    current: dict[str, Any],
) -> None:
    assert current['history']['unknown-350-light'] is None
    plan = current['plans']['unknown-350-light']
    assert plan['History Support'] == 'grid only'
    for field in ('FC Temp Source', 'Phase Timing Source', 'Drop Temp Source',
                  'Heater Source', 'Drop ROR Source'):
        assert plan[field] == 'grid', f'{field} claims history it does not have'


def test_back_to_back_lowers_the_charge_by_the_heat_soak_correction(
    current: dict[str, Any],
) -> None:
    """The plan's charge drop must equal the correction the L1 unit tests pin.

    L1 proves the formula in isolation; this proves the plan actually applies
    it. Neither test alone would catch the wiring being cut.
    """
    from tilauscope.roast_plan_model import heat_soak_correction

    cold = current['plans']['gr2-400-medium']
    hot = current['plans']['gr2-400-medium-back-to-back']

    soak = hot['Heat Soak']
    assert soak is not None, 'no heat-soak block on a back-to-back plan'
    assert cold['Heat Soak'] is None, 'heat soak applied without a previous drop'

    # `Charge Temp` is published as a whole degree, so a difference of two of
    # them is quantised: each end can round half a degree away from the value
    # the law produced, and their difference by a full one. A tighter bound
    # than that does not test the wiring, it tests where the rounding landed —
    # which is why this passed or failed on the plan's mood. A soak that were
    # cut, halved or inverted still moves the difference by whole degrees and
    # is still caught. The law itself is pinned unrounded just below.
    applied = float(hot['Charge Temp']) - float(cold['Charge Temp'])
    assert applied == pytest.approx(soak['dcharge'], abs=_CHARGE_ROUNDING_C)
    assert soak['dcharge'] < 0 and soak['dheater'] <= 0

    # And the value itself is the documented law, not a coincidence.
    expected, _, _ = heat_soak_correction(
        soak['mins'],
        H.make_plan_model(H.CORPUS_DIR)._roaster_ctx.thermal_mass_index,
        H.make_plan_model(H.CORPUS_DIR)._roaster_ctx.heat_retention_index,
    )
    assert soak['dcharge'] == pytest.approx(expected, abs=0.05)


_GR2_UUID = 'a82364a8-e9ad-447c-a3d8-5f49111dc3ee'

#: The plan publishes its charge as a whole degree. Comparing the DIFFERENCE of
#: two published charges against a continuous law therefore carries up to one
#: full degree of quantisation — half from each end.
_CHARGE_ROUNDING_C = 1.0


def _charge_of(moisture_pct: float, minutes_since_drop: float | None) -> float:
    """Charge BT for one back-to-back request, at a given measured moisture.

    Deliberately cold: ambient 10 °C, humidity 30 % and a neutral density push
    the pre-soak charge near the bottom of the natural band, which is the
    only place the water floor can reach the heat-soak correction. A plan built
    in mild conditions never exercises this at all — which is exactly why the
    bug survived the existing back-to-back test above.
    """
    model = H.make_plan_model(H.CORPUS_DIR)
    bean = H.make_bean(_GR2_UUID, '74110 GR2', process='Natural', altitude=1800,
                       density=700.0, last_humidity=moisture_pct)
    result = model.generate_roast_plan(
        bean, H.agtron('Medium'), 10.0, 30.0, 400.0, 1800.0,
        None, False, minutes_since_drop,
    )
    plan = result[0] if isinstance(result, tuple) else result
    return float(plan['Charge Temp'])


@pytest.mark.parametrize('moisture_pct', [0.0, 9.5, 8.5])
def test_measuring_the_water_never_eats_the_heat_soak(
    moisture_pct: float,
) -> None:
    """The soak keeps its full authority whatever the water reading says.

    The heat soak is allowed below the process band — that is its purpose. The
    water floor used to be applied to the already-soaked charge, so a dry bean
    clawed the charge back up to the band bottom while the published "Heat Soak"
    block still announced the full figure: measuring the water made the plan
    worse than leaving it unmeasured.
    """
    from tilauscope.roast_plan_model import heat_soak_correction

    context = H.make_plan_model(H.CORPUS_DIR)._roaster_ctx
    expected, _, _ = heat_soak_correction(
        0.0, context.thermal_mass_index, context.heat_retention_index)

    # Same quantisation as the test above: both charges are whole degrees.
    applied = _charge_of(moisture_pct, 0.0) - _charge_of(moisture_pct, None)
    assert applied == pytest.approx(expected, abs=_CHARGE_ROUNDING_C)


def _plan(**bean_fields: Any) -> dict[str, Any]:
    model = H.make_plan_model(H.CORPUS_DIR)
    fields: dict[str, Any] = {'process': 'Natural', 'altitude': 1800}
    fields.update(bean_fields)
    bean = H.make_bean(_GR2_UUID, '74110 GR2', **fields)
    result = model.generate_roast_plan(
        bean, H.agtron('Medium'), 20.0, 50.0, 400.0, 1800.0, None, False, None)
    return result[0] if isinstance(result, tuple) else result


def test_the_charge_follows_the_water_mass_and_the_aw_never_moves_it() -> None:
    """End to end, on the bean that proves the two are separate.

    KoJoYo Sindoro Java reads 12.5 % moisture — a real mass of water to heat —
    and aw 0.54, meaning that water leaves reluctantly. The charge answers the
    MASS; the aw has no say there, whatever it reads.
    """
    wet = float(_plan(last_humidity=12.5)['Charge Temp'])
    wet_with_low_aw = float(_plan(last_humidity=12.5, water_activity=0.54)['Charge Temp'])
    wet_with_high_aw = float(_plan(last_humidity=12.5, water_activity=0.70)['Charge Temp'])
    neutral = float(_plan(last_humidity=10.5)['Charge Temp'])

    assert wet > neutral, 'a wetter bean takes a hotter charge'
    assert wet_with_low_aw == pytest.approx(wet), 'the aw leaked into the charge'
    assert wet_with_high_aw == pytest.approx(wet), 'the aw leaked into the charge'


def test_culture_altitude_is_ignored_when_density_is_measured() -> None:
    """Altitude is a proxy for density; the measurement always wins."""
    with_density = float(_plan(density=700.0, altitude=1800)['Charge Temp'])
    sea_level = float(_plan(density=700.0, altitude=1)['Charge Temp'])
    assert with_density == pytest.approx(sea_level), (
        'culture altitude still leaked into the charge behind a measured density')


def test_ambient_humidity_no_longer_touches_the_plan() -> None:
    """It does not act on the roast in progress — only between roasts, by
    drifting the green's water activity in storage."""
    model = H.make_plan_model(H.CORPUS_DIR)
    bean = H.make_bean(_GR2_UUID, '74110 GR2', process='Natural', altitude=1800)

    def _at(humidity_pct: float) -> dict[str, Any]:
        result = H.make_plan_model(H.CORPUS_DIR).generate_roast_plan(
            bean, H.agtron('Medium'), 20.0, humidity_pct, 400.0, 1800.0,
            None, False, None)
        plan = result[0] if isinstance(result, tuple) else result
        return {k: v for k, v in plan.items() if k != 'Ambient Humidity'}

    assert model is not None
    assert _at(20.0) == _at(95.0), 'ambient humidity still moves a plan output'


def test_the_water_term_alone_still_cannot_leave_the_process_band() -> None:
    """Water modulates INSIDE the band — only structure and the heat soak are
    allowed out of it. The driest bean there is must still land in the band."""
    band_bottom, band_top = 170.0, 180.0  # _CHARGE_CEILING_BY_PROCESS['natural']
    driest = _charge_of(5.5, None)
    assert band_bottom <= driest <= band_top
    assert _charge_of(9.5, None) > driest


def test_every_scenario_documents_why_it_exists() -> None:
    """A fixture nobody can justify is a fixture nobody will maintain."""
    for scenario in S.SCENARIOS:
        assert len(scenario.why) > 30, f'{scenario.name} has no real rationale'


def test_corpus_fixtures_are_present_and_parseable() -> None:
    """The count is pinned on purpose: losing a fixture must be a decision, not
    an accident. Growing the corpus is legitimate — update this number and
    regenerate the golden in the same commit, so the snapshot always describes
    the roasts that are actually on disk."""
    files = H.corpus_files()
    assert len(files) == 51, f'expected 51 committed roasts, found {len(files)}'
    for path in files:
        profile = H.read_alog(path)
        assert profile.get('timeindex'), f'{path.name} has no milestones'

    # A bean uuid is what lets the plan learn from a roast BY IDENTITY, which is
    # the only path a scenario ever takes. The corpus also carries imported
    # reference roasts — other machines, coffees that were never in BeanCave —
    # and those legitimately have none: they cover the reading layer and the
    # fuzzy-name fallback instead. Both counts are pinned so the balance between
    # the two cannot drift unnoticed.
    identified = [p for p in files if H.bean_uuid(H.read_alog(p))]
    assert len(identified) == 26, (
        f'expected 26 uuid-identified roasts, found {len(identified)}')


def test_golden_file_is_committed_and_current(golden: dict[str, Any]) -> None:
    """The golden must describe the corpus that is actually on disk."""
    assert set(golden['roasts']) == {p.name for p in H.corpus_files()}
    assert set(golden['plans']) == {s.name for s in S.SCENARIOS}

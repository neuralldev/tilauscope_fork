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
claim it is *unchanged*. Twelve real roasts are committed under
``fixtures/corpus``; the model's reading of them, what it learns across them,
and the plans it produces are frozen in ``golden/corpus.json``.

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

    applied = float(hot['Charge Temp']) - float(cold['Charge Temp'])
    assert applied == pytest.approx(soak['dcharge'], abs=0.15)
    assert soak['dcharge'] < 0 and soak['dheater'] <= 0

    # And the value itself is the documented law, not a coincidence.
    expected, _, _ = heat_soak_correction(
        soak['mins'],
        H.make_plan_model(H.CORPUS_DIR)._roaster_ctx.thermal_mass_index,
        H.make_plan_model(H.CORPUS_DIR)._roaster_ctx.heat_retention_index,
    )
    assert soak['dcharge'] == pytest.approx(expected, abs=0.05)


def test_every_scenario_documents_why_it_exists() -> None:
    """A fixture nobody can justify is a fixture nobody will maintain."""
    for scenario in S.SCENARIOS:
        assert len(scenario.why) > 30, f'{scenario.name} has no real rationale'


def test_corpus_fixtures_are_present_and_parseable() -> None:
    files = H.corpus_files()
    assert len(files) == 12, f'expected 12 committed roasts, found {len(files)}'
    for path in files:
        profile = H.read_alog(path)
        assert profile.get('timeindex'), f'{path.name} has no milestones'
        assert H.bean_uuid(profile), f'{path.name} carries no bean uuid'


def test_golden_file_is_committed_and_current(golden: dict[str, Any]) -> None:
    """The golden must describe the corpus that is actually on disk."""
    assert set(golden['roasts']) == {p.name for p in H.corpus_files()}
    assert set(golden['plans']) == {s.name for s in S.SCENARIOS}

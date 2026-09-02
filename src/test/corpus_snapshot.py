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

"""Builds the golden snapshot: what the plan model makes of the fixture corpus.

Three sections, each answering a different question:

``roasts``
    What does the engine *read* in a recorded roast — turning point, phase
    boundaries, RoR envelope, crashes and flicks. Pure per-roast analysis.

``history``
    What does it *learn* across roasts of the same bean. This is where the
    adoption policy lives (grid / blend at n=2 / learned at n>=3), and where a
    silent regression costs the most.

``plans``
    What plan comes out end to end, for a fixed scenario matrix.

Everything is rounded and sorted so the JSON diff is stable and readable. The
BT curve is stored as its anchors plus one sample per minute: freezing all 700
points would make every diff unreadable, which defeats the purpose, while the
anchors plus a coarse grid still catch any real change of shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, NamedTuple

import corpus_harness as H

if TYPE_CHECKING:
    from pathlib import Path

#: Decimal places kept for every float. Enough to catch a real change, coarse
#: enough that platform-level floating-point noise cannot flip the golden.
PRECISION: Final[int] = 3


class Scenario(NamedTuple):
    """One plan request, chosen to exercise a specific branch of the model."""

    name: str
    why: str
    uuid: str
    bean_name: str
    process: str
    target: str
    charge_g: float
    ambient_c: float
    humidity_pct: float
    altitude_m: float
    minutes_since_drop: float | None = None
    #: The lot's own physics. Defaulted to the harness bean so every scenario
    #: written before the density dead band keeps its exact snapshot.
    density_g_l: float = 700.0
    moisture_pct: float = 10.5


#: Bean identities present in the committed corpus.
_GR2: Final[str] = 'a82364a8-e9ad-447c-a3d8-5f49111dc3ee'
_CORTES: Final[str] = '330efff2-49f8-41c4-b1e7-e972a2d6a3a2'
_MBINGA: Final[str] = '283ab376-9e0f-4e11-8b2b-080e9d5240ed'
_CATURRA: Final[str] = '94ee0778-f239-4457-91d6-d33153c17e6f'
_BARAZILIE: Final[str] = '2d1a0dd8-2f15-4cb5-a8c9-41cfb583bb49'

SCENARIOS: Final[tuple[Scenario, ...]] = (
    Scenario(
        'gr2-400-medium',
        'three 400 g roasts of this bean qualify -> learned path (n>=3)',
        _GR2, '74110 GR2', 'Natural', 'Medium', 400.0, 21.0, 55.0, 1800.0,
    ),
    Scenario(
        'gr2-250-medium',
        'same bean at 250 g: the 400 g roasts fall outside the +-25% weight '
        'filter, so history collapses to a single sample',
        _GR2, '74110 GR2', 'Natural', 'Medium', 250.0, 21.0, 55.0, 1800.0,
    ),
    Scenario(
        'cortes-400-medium',
        'exactly two qualifying roasts -> 50/50 blend between grid and learned',
        _CORTES, 'Cortes', 'Washed', 'Medium', 400.0, 20.0, 48.0, 1500.0,
    ),
    Scenario(
        'mbinga-400-medium-decaf',
        'decaf; both quality filters bite here — of the three roasts, one has '
        'ambient 0/0 (disconnected sensor) and one is a 250 g batch outside '
        'the +-25% weight window, leaving a single usable sample',
        _MBINGA, 'Mbinga', 'Washed Decaf', 'Medium', 400.0, 22.0, 44.0, 1400.0,
    ),
    Scenario(
        'unknown-350-light',
        'no history at all -> every parameter must fall back to the grid',
        'no-such-bean-uuid', 'Unknown Origin', 'Washed', 'Light', 350.0,
        19.0, 60.0, 1200.0,
    ),
    Scenario(
        'unknown-250-light',
        'small batch on a light target: the turning point sits high, so little '
        'climb is left before the dry end while Maillard still has its full '
        'span — the case where the envelope would put Maillard above drying, '
        'which this machine never does',
        'no-such-bean-uuid', 'Unknown Origin', 'Washed', 'Light', 250.0,
        19.0, 60.0, 1200.0,
    ),
    Scenario(
        'unknown-150-light',
        'the smallest batch the machine takes: the turning point sits at its '
        'measured plateau, drying is short, and Maillard has to be led faster '
        'than the nominal envelope to stay under it',
        'no-such-bean-uuid', 'Unknown Origin', 'Anaerobic Fermentation', 'Light',
        150.0, 30.8, 62.0, 1200.0,
    ),
    Scenario(
        'gr2-400-medium-back-to-back',
        'same request as the first, 8 minutes after a DROP -> heat-soak '
        'correction must lower the charge and the starting burner',
        _GR2, '74110 GR2', 'Natural', 'Medium', 400.0, 21.0, 55.0, 1800.0,
        minutes_since_drop=8.0,
    ),
    Scenario(
        'caturra-300-medium-dense',
        'a genuinely hard lot at 770 g/L: the only branch left above the '
        'density dead band, where the structure term is allowed to carry the '
        'charge past the ceiling its process alone would impose — and at half '
        'slope, so a dense bean can no longer claim the +4.9 C it used to. No '
        'roast of it in the corpus, so the schedule falls to the grid and the '
        'density is the one thing moving the plan',
        _CATURRA, 'Caturra', 'Natural', 'Medium', 300.0, 21.0, 52.0, 1850.0,
        density_g_l=770.0, moisture_pct=12.9,
    ),
    Scenario(
        'barazilie-250-medium-soft',
        'a genuinely soft lot at 660 g/L: the branch below the dead band, the '
        'one Hoos actually endorses — charged cooler and given less power '
        'early, because it scorches where a harder bean would not. Asked at '
        'Medium Light because that is the colour its one corpus roast '
        'actually reached (68 whole), so the colour gate lets it through and '
        'the learned path runs on a single sample beside the density branch. '
        'A wet lot at 12.2 % on an anaerobic process stacks the moisture term '
        'on top',
        _BARAZILIE, 'Barazilie', 'Anaerobic Fermentation', 'Medium Light',
        250.0, 22.0, 58.0, 800.0,
        density_g_l=660.0, moisture_pct=12.2,
    ),
)


def _round(value: Any) -> Any:
    """Recursively round floats so the golden diff is stable across machines."""
    if isinstance(value, float):
        return round(value, PRECISION)
    if isinstance(value, dict):
        return {str(k): _round(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def _curve_digest(curve: dict[str, Any] | None) -> dict[str, Any] | None:
    """Anchors verbatim, plus one BT/RoR sample per minute.

    Storing the full 1 s grid would bury any real change under 700 lines of
    noise; the anchors are what the plan actually promises, and a per-minute
    sample is dense enough that no plausible reshaping slips through.
    """
    if not curve:
        return None
    times = curve.get('time_min') or []
    bt = curve.get('bt_plan') or []
    ror = curve.get('ror_plan') or []
    samples = []
    for minute in range(int(times[-1]) + 1) if times else []:
        idx = min(minute * 60, len(times) - 1)
        samples.append({'min': minute, 'bt': _round(bt[idx]), 'ror': _round(ror[idx])})
    return {
        'n_points': len(times),
        'waypoints': _round(curve.get('waypoints')),
        'per_minute': samples,
    }


def snapshot_roast(model: Any, path: Path) -> dict[str, Any]:
    """What the engine reads in one recorded roast."""
    profile = H.read_alog(path)
    delta_bt, timex, bt, tp_index, phases = model._get_delta_bt(path.name)

    crashes, flicks = model._find_flicks_crashes(delta_bt, timex, phases, tp_index)

    drop_s = phases.get('drop') or 0.0
    dry_s = phases.get('dry_end')
    fc_s = phases.get('fc_start')
    return _round({
        'date': profile.get('roastisodate', ''),
        'uuid': H.bean_uuid(profile),
        'unit': profile.get('mode', 'C'),
        'green_weight_g': (profile.get('weight') or [0.0])[0],
        'batch_position': profile.get('roastbatchpos'),
        'n_samples': len(timex),
        'dt_s': model._estimate_dt(timex),
        'turning_point': {
            'index': tp_index,
            'time_s': timex[tp_index],
            'bt_c': bt[tp_index],
        },
        'milestones_s': {'dry_end': dry_s, 'fc_start': fc_s, 'drop': drop_s},
        'milestones_bt_c': {
            'charge': bt[0],
            'drop': bt[-1],
        },
        'dtr_pct': (round((drop_s - fc_s) / drop_s * 100.0, 1)
                    if fc_s and drop_s else None),
        'ror': {
            'min': min(delta_bt),
            'max': max(delta_bt),
            'at_drop': delta_bt[-1],
        },
        'crashes': crashes,
        'flicks': flicks,
    })


def snapshot_history(model: Any, scenario: Scenario) -> dict[str, Any] | None:
    """What the engine learns across roasts of the same bean."""
    bean = H.make_bean(
        scenario.uuid, scenario.bean_name,
        process=scenario.process, altitude=int(scenario.altitude_m),
        density=scenario.density_g_l, last_humidity=scenario.moisture_pct,
    )
    history = model._analyze_historical_roasts(
        bean, H.agtron(scenario.target), scenario.charge_g,
    )
    if history is None:
        return None
    out = {k: v for k, v in history.items() if k != 'graph'}
    graph = history.get('graph') or {}
    out['graph_summary'] = {
        'n_points': len(graph.get('time_min') or []),
        'keys': sorted(graph.keys()),
    }
    return _round(out)


def snapshot_plan(model: Any, scenario: Scenario) -> dict[str, Any]:
    """The plan produced end to end for one scenario."""
    bean = H.make_bean(
        scenario.uuid, scenario.bean_name,
        process=scenario.process, altitude=int(scenario.altitude_m),
        density=scenario.density_g_l, last_humidity=scenario.moisture_pct,
    )
    result = model.generate_roast_plan(
        bean, H.agtron(scenario.target),
        scenario.ambient_c, scenario.humidity_pct, scenario.charge_g,
        scenario.altitude_m, None, False, scenario.minutes_since_drop,
    )
    plan = result[0] if isinstance(result, tuple) else result
    out = {k: v for k, v in plan.items() if k != 'bt_plan_curve'}
    out['bt_plan_curve'] = _curve_digest(plan.get('bt_plan_curve'))
    return _round(out)


def build() -> dict[str, Any]:
    """The complete snapshot. Deterministic: same corpus in, same JSON out."""
    H.install_qt_shims()

    roasts: dict[str, Any] = {}
    for path in H.corpus_files():
        # A fresh model per roast: _get_delta_bt caches the last profile on the
        # instance, and the history memo must not leak between fixtures.
        # Rooted on the roast's OWN directory: the corpus grew subdirectories
        # for the other machine types (cormorant, kaleido) and the model
        # resolves a roast by name inside its alog directory — rooted on the
        # corpus top level, every one of those raised FileNotFoundError.
        roasts[path.name] = snapshot_roast(H.make_plan_model(path.parent), path)

    history: dict[str, Any] = {}
    plans: dict[str, Any] = {}
    for scenario in SCENARIOS:
        history[scenario.name] = snapshot_history(
            H.make_plan_model(H.CORPUS_DIR), scenario,
        )
        plans[scenario.name] = snapshot_plan(
            H.make_plan_model(H.CORPUS_DIR), scenario,
        )

    return {
        'reference': {
            'roaster': H.REFERENCE_ROASTER,
            'precision': PRECISION,
            'scenarios': {s.name: s.why for s in SCENARIOS},
        },
        'roasts': roasts,
        'history': history,
        'plans': plans,
    }

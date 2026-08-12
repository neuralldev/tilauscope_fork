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

"""L2 harness — running the plan model against recorded roasts, headlessly.

THE COUPLING PROBLEM
--------------------
The plan model does not read RoR from the .alog file: it *recomputes* it, via
``self.parent.qmc.recomputeDeltas()`` and Artisan's smoothing settings. So the
history pipeline cannot run without a ``qmc``, and a ``qmc`` normally means the
whole application.

The way out is to keep Artisan's **algorithm** and fake only its
**configuration**. ``artisanlib.canvas`` imports headlessly (two shims: a
QApplication must exist, and it must answer ``artisanviewerMode``) *without*
pulling ``artisanlib.main``, so ``tgraphcanvas.recomputeDeltas`` — the real
thing, bit for bit — can be bound to the stub below. What the stub supplies is
exactly what a live ``qmc`` supplies: filter widths, RoR limits, unit.

WHAT THE GOLDEN THEREFORE MEANS
-------------------------------
The snapshot freezes the model's behaviour **under a declared reference
configuration** (:class:`ReferenceQmc`, Artisan's own defaults for °C
operation), not under whatever smoothing the developer happens to have set
today. That is deliberate: a regression net must move only when the model
moves. If Artisan changes a default upstream, the golden will not drift
silently — the constants here are the contract, and changing them is a visible
edit.
"""

from __future__ import annotations

import ast
import re
import types
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from tilauscope.tilauscope_types import AgtronScale, GreenBean

CORPUS_DIR: Final[Path] = Path(__file__).resolve().parent / 'fixtures' / 'corpus'
GOLDEN_PATH: Final[Path] = Path(__file__).resolve().parent / 'golden' / 'corpus.json'

#: The roaster every fixture was recorded on (Skywalker V2 / Cyberroaster).
REFERENCE_ROASTER: Final[str] = 'ITOP Cyberroaster'

_UUID_RE: Final[re.Pattern[str]] = re.compile(r'uuid:\s*([0-9a-f-]{36})', re.IGNORECASE)


#: Strong reference to the QApplication. PyQt6 does not keep one, and a
#: collected instance makes QCoreApplication.instance() return None again —
#: which surfaces far away, as `NoneType has no attribute applicationName`
#: inside artisanlib.util.getDataDirectory().
_APP: Any = None


def install_qt_shims() -> Any:
    """Make ``artisanlib.canvas`` importable outside the full application.

    Two things block it: ``getDataDirectory()`` dereferences
    ``QCoreApplication.instance()``, and ``plus.stock`` reads
    ``app.artisanviewerMode``, an attribute Artisan's own QApplication subclass
    defines. Neither needs the real application to be meaningful here.
    """
    global _APP  # noqa: PLW0603  # process-wide singleton, by Qt's design
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    if not hasattr(_APP, 'artisanviewerMode'):
        _APP.artisanviewerMode = False
    return _APP


class ReferenceQmc:
    """Artisan's RoR/smoothing configuration, frozen at its documented defaults.

    Values mirror ``tgraphcanvas.__init__`` (artisanlib/canvas.py). RoR limits
    are given in °C/min — the defaults are initialised in °F there and converted
    by Artisan when the unit is °C, which is the only mode this corpus uses.
    """

    # -- unit & smoothing (canvas.py:1749, 1759-1773) -------------------------
    mode: str = 'C'
    curvefilter: int = 3
    interpolateDropsflag: bool = True
    optimalSmoothing: bool = False
    polyfitRoRcalc: bool = False
    deltaETfilter: int = 7
    deltaBTfilter: int = 7
    deltaETsamples: int = 6
    deltaBTsamples: int = 6

    # -- outlier handling (canvas.py:2079-2083, 2331, 2342) -------------------
    filterDropOuts: bool = True
    median_filter_factor_RoR: int = 3
    RoRlimitFlag: bool = True
    RoRlimit: int = 45        # °C/min
    RoRlimitm: int = -10      # °C/min
    maxRoRlimit: int = 170

    # -- math channels, unused by this corpus (canvas.py:1572-1573) -----------
    DeltaETfunction: str = ''
    DeltaBTfunction: str = ''

    # -- live-recording state: always off when replaying a file ---------------
    flagon: bool = False
    flagstart: bool = False

    def __init__(self) -> None:
        from artisanlib.canvas import tgraphcanvas

        # The real Artisan algorithm, bound to this configuration-only host.
        self.recomputeDeltas = types.MethodType(tgraphcanvas.recomputeDeltas, self)

    def eval_math_expression_RT(self, *_args: Any, **_kwargs: Any) -> Any:
        """Only reached when a Delta math channel is configured; none is here."""
        raise AssertionError(
            'eval_math_expression_RT called: a DeltaET/BT function is set on the '
            'reference config, which the corpus does not model.',
        )


class ReferenceParent:
    """Stands in for Artisan's ApplicationWindow: the model only wants ``qmc``."""

    def __init__(self) -> None:
        self.qmc = ReferenceQmc()


def make_plan_model(alog_directory: Path) -> Any:
    """A ``TilauScopeRoastPlan`` wired to the fixture corpus and the reference machine."""
    from tilauscope.roast_plan_model import TilauScopeRoastPlan
    from tilauscope.roasters import RoasterManager

    ctx = RoasterManager().get_roast_context(REFERENCE_ROASTER)
    if ctx is None:
        raise RuntimeError(f'roaster {REFERENCE_ROASTER!r} missing from roasters.json')
    model = TilauScopeRoastPlan(parent=ReferenceParent(), roaster_ctx=ctx)
    # __init__ reads alogDirectory from QSettings (empty in the sandbox); point
    # it at the committed corpus so history analysis is reproducible.
    model.alog_directory = str(alog_directory)
    return model


# ── fixture metadata ─────────────────────────────────────────────────────────

def read_alog(path: Path) -> dict[str, Any]:
    return ast.literal_eval(path.read_text(encoding='utf-8'))


def bean_uuid(profile: dict[str, Any]) -> str:
    match = _UUID_RE.search(profile.get('beans') or '')
    return match.group(1) if match else ''


def corpus_files() -> list[Path]:
    """Return complete roasts, including origin-specific subdirectories."""
    return [path for path in sorted(CORPUS_DIR.rglob('*.alog'))
            if is_complete_roast(read_alog(path))]


def incomplete_corpus_files() -> list[Path]:
    """Expose incomplete recordings so exclusion remains visible and tested."""
    return [path for path in sorted(CORPUS_DIR.rglob('*.alog'))
            if not is_complete_roast(read_alog(path))]


def is_complete_roast(profile: dict[str, Any]) -> bool:
    """A replay needs explicit CHARGE and DROP markers."""
    timeindex = profile.get('timeindex', [])
    return (len(timeindex) > 6
            and int(timeindex[0]) >= 0
            and int(timeindex[6]) > int(timeindex[0]))


@dataclass(frozen=True)
class FixtureControlScenario:
    roaster_name: str
    slider_visibilities: tuple[int, int, int, int]


def control_scenario_for(path: Path) -> FixtureControlScenario:
    """Read machine identity from Artisan data; add only missing slider metadata."""
    identity = str(read_alog(path).get('roastertype') or '').strip()
    # Legacy Roastetta files do not persist eventslidervisibilities. This mask
    # describes the test configuration, not an inference from the directory.
    visibilities = (0, 0, 0, 0) if identity == 'Cormorant' else (1, 1, 0, 1)
    return FixtureControlScenario(identity, visibilities)


@cache
def _roaster_context(name: str) -> Any:
    from tilauscope.roasters import RoasterManager

    context = RoasterManager().get_roast_context(name)
    if context is None:
        raise RuntimeError(f'roaster {name!r} missing from roasters.json')
    return context


def controls_observable_for(path: Path) -> bool:
    """Intersect fixture slider configuration with its roasters.json structure."""
    from tilauscope.guidance_observer import observable_control_levers

    scenario = control_scenario_for(path)
    context = _roaster_context(scenario.roaster_name)
    return bool(observable_control_levers(
        scenario.slider_visibilities,
        has_airflow_control=context.has_airflow_control,
        drum_variable_speed=context.drum_variable_speed,
        has_heater_control=context.has_heater_control,
    ))


def make_bean(uuid: str, name: str, **overrides: Any) -> GreenBean:
    """A GreenBean carrying just the identity and physics the plan model reads."""
    from tilauscope.tilauscope_types import GreenBean

    fields: dict[str, Any] = {
        'name': name, 'uuid': uuid,
        'density': 700.0, 'last_humidity': 10.5, 'altitude': 1800,
        'process': 'Washed', 'country': '',
    }
    fields.update(overrides)
    return GreenBean(**fields)


def agtron(name: str) -> AgtronScale:
    from tilauscope.tilauscope_types import AGTRON_SCALES

    return next(s for s in AGTRON_SCALES if s.name == name)

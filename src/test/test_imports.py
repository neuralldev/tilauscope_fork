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

"""L0 — the import portico.

Every module of ``tilauscope`` must import cleanly in a headless process.
This catches the failures that never show up in a normal run because the guilty
module is only reached from a rarely-used screen: syntax errors, module-scope
``NameError``, circular imports, and third-party dependencies that were added
to the code but never to ``requirements.txt`` (the recurring packaging trap —
the installer only fails weeks later, on the build machine).

Each import runs in a **fresh subprocess** that installs the settings sandbox
as its first statement. That isolation is not a style choice: several modules
transitively import ``artisanlib.main``, which writes to real preferences at
module scope. In-process importing would clobber the developer's live Artisan
configuration.

Imports are launched concurrently where possible, then asserted one module per
test, so the report names exactly which module broke instead of a single opaque
failure.

One trap is worth knowing about. A module that pulls ``artisanlib.main`` builds
a real Artisan application object during import, and Artisan enforces
single-instance: it calls ``sys.exit(0)`` when it believes another instance is
live. That leaves the child process with status 0, so a naive portico reports
the module as importing cleanly when its import was in fact abandoned half way.
Both halves of the fix matter — those modules are imported serially, and
``SystemExit`` is caught and reported as the failure it is.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404  # trusted, fully-constructed argv, no shell
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final, NamedTuple

import _guard
import pytest

SRC_DIR: Final[Path] = Path(__file__).resolve().parent.parent
TEST_DIR: Final[Path] = Path(__file__).resolve().parent
PKG_DIR: Final[Path] = SRC_DIR / 'tilauscope'

#: Per-module import budget. Generous: the contaminated modules pull the whole
#: Artisan application (matplotlib, scipy, the full UI tree) on first import.
IMPORT_TIMEOUT_S: Final[int] = 180

#: Modules known not to import headless yet. Every entry is technical debt with
#: a reason attached; the list must shrink over time, never grow silently.
KNOWN_UNIMPORTABLE: Final[dict[str, str]] = {}

#: Modules that import ``artisanlib.main`` at runtime scope (not under
#: ``TYPE_CHECKING``). Importing any of them binds the real Artisan preference
#: identity, which is why the whole portico is subprocess-isolated.
#:
#: This is a frozen debt baseline, not an approval. Most of these only need the
#: symbol as a type annotation and could move under ``TYPE_CHECKING``, as
#: alarms/devices/onboarding/mqttbridge/menu_extension already do. The test
#: below fails if the list GROWS — new contamination is a regression.
ARTISAN_MAIN_IMPORTERS: Final[frozenset[str]] = frozenset({
    'difluid',
    'displayscope',
    # pid_autotune left this set on 2026-09-01: its ApplicationWindow import
    # moved under TYPE_CHECKING. Locked in — it must not come back.
    'roast_asssistant',
    'tilau_intelligence',
    'tilauambient',
    'tilaulogger',
})

# Child program: sandbox first, import second, re-verify third — then leave via
# os._exit().
#
# The hard exit is load-bearing, not tidiness. Modules that pull artisanlib.main
# start non-daemon threads (BLE scan, MQTT, update check) as a side effect of
# import; a normal interpreter shutdown then waits on them forever and the
# import looks like a timeout even though it succeeded in two seconds. Skipping
# finalisation also sidesteps the known Qt/BLE teardown crash, which would
# otherwise report a false failure here.
#
# SystemExit is caught explicitly and reported as a failure. Artisan's
# single-instance guard calls sys.exit(0) from inside Artisan.__init__ when it
# believes another instance is running; letting that propagate would end the
# child with status 0 and the module would be reported as importing cleanly
# when in fact its import was abandoned half way.
_CHILD: Final[str] = """
import os, sys, traceback
sys.path.insert(0, sys.argv[1])
try:
    import _guard
    _guard.install(sys.argv[2])
    import importlib
    importlib.import_module(sys.argv[3])
    _guard.verify(sys.argv[2])
except SystemExit as exc:
    print(f'module called sys.exit({exc.code}) during import: '
          'the import did not complete', file=sys.stderr)
    traceback.print_exc()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1)
except BaseException:
    traceback.print_exc()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1)
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
"""


class ImportResult(NamedTuple):
    module: str
    returncode: int
    output: str


def _dotted(path: Path) -> str:
    """`tilauscope/window/parts.py` -> `window.parts`, the importable suffix.

    Modules live in subpackages too, and a bare stem cannot name them: two
    packages may hold the same file name, and `tilauscope.parts` is not
    importable. Everything that walks the package is keyed on this.
    """
    return '.'.join(path.relative_to(PKG_DIR).with_suffix('').parts)


def _package_modules() -> list[Path]:
    """Every importable module of the package, subpackages INCLUDED.

    Recursive on purpose. A non-recursive glob left `cave/`, `window/`,
    `graph/`, `widgets/` and `tools/` — 39 modules, better than a quarter of
    the package — outside every check built on this list, which is where the
    unguarded `artisanlib.main` imports of `window.parts`, `window.sidebar`
    and `cave.printing` sat unnoticed.
    """
    return sorted(
        p for p in PKG_DIR.rglob('*.py')
        if p.stem != '__init__' and not p.stem.startswith('.')
    )


def _module_names() -> list[str]:
    return [_dotted(p) for p in _package_modules()]


def _import_one(module: str, sandbox: Path) -> ImportResult:
    env = dict(os.environ)
    env[_guard.SANDBOX_ENV] = str(sandbox)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join([str(SRC_DIR), str(TEST_DIR)])
    try:
        proc = subprocess.run(  # noqa: S603  # argv is fully constructed, shell=False
            [sys.executable, '-c', _CHILD, str(TEST_DIR), str(sandbox),
             f'tilauscope.{module}'],
            cwd=str(SRC_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ImportResult(module, -1, f'timed out after {IMPORT_TIMEOUT_S}s')
    return ImportResult(module, proc.returncode, (proc.stdout + proc.stderr).strip())


@pytest.fixture(scope='session')
def import_results(sandbox: Path) -> dict[str, ImportResult]:
    """Import every module once per session, in two passes.

    Pass 1 runs the ordinary modules concurrently — each child gets its own
    sandbox subdirectory so they never race on the same .ini file.

    Pass 2 runs the modules that pull ``artisanlib.main`` **one at a time**.
    Importing one of those builds a real Artisan application object, and
    Artisan enforces single-instance: run two at once and every child but the
    first decides another instance is live, flips to viewer mode and calls
    sys.exit(0) mid-import. Serialising is the whole fix — these modules import
    perfectly well on their own, in about two seconds each.
    """
    modules = _module_names()
    heavy = [m for m in modules if m in ARTISAN_MAIN_IMPORTERS]
    light = [m for m in modules if m not in ARTISAN_MAIN_IMPORTERS]

    results: dict[str, ImportResult] = {}
    workers = min(len(light), (os.cpu_count() or 4)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(
            lambda m: _import_one(m, sandbox / 'imports' / m), light,
        ):
            results[result.module] = result

    for module in heavy:
        results[module] = _import_one(module, sandbox / 'imports' / module)
    return results


@pytest.mark.slow
@pytest.mark.parametrize('module', _module_names())
def test_module_imports_headless(
    module: str, import_results: dict[str, ImportResult],
) -> None:
    """``tilauscope.<module>`` imports in a clean headless process."""
    result = import_results[module]
    if module in KNOWN_UNIMPORTABLE and result.returncode != 0:
        pytest.xfail(KNOWN_UNIMPORTABLE[module])
    assert result.returncode == 0, (
        f'import tilauscope.{module} failed (rc={result.returncode}):\n{result.output}'
    )


def test_no_new_artisanlib_main_contamination() -> None:
    """No new module may import ``artisanlib.main`` outside ``TYPE_CHECKING``.

    Importing it executes a settings migration that writes to the user's real
    Artisan preferences, and drags the whole application into any process that
    only wanted a helper. The existing offenders are frozen in
    :data:`ARTISAN_MAIN_IMPORTERS`; this test fails when the set changes, in
    either direction — growth is a regression, shrinkage means the baseline
    should be updated to lock the improvement in.
    """
    found: set[str] = set()
    for path in _package_modules():
        for line in path.read_text(encoding='utf-8').splitlines():
            # Column 0 == runtime scope. Indented imports are inside
            # `if TYPE_CHECKING:` or a function, and are harmless.
            if line.startswith(('from artisanlib.main ', 'import artisanlib.main')):
                found.add(_dotted(path))
                break

    new = found - ARTISAN_MAIN_IMPORTERS
    assert not new, (
        f'new unguarded `artisanlib.main` import in: {sorted(new)}. '
        'Move it under `if TYPE_CHECKING:` (see alarms.py / devices.py) or, if the '
        'symbol is needed at runtime, extend ARTISAN_MAIN_IMPORTERS deliberately.'
    )
    gone = ARTISAN_MAIN_IMPORTERS - found
    assert not gone, (
        f'{sorted(gone)} no longer import artisanlib.main — remove them from '
        'ARTISAN_MAIN_IMPORTERS so the improvement cannot regress.'
    )


def test_sandbox_actually_redirects_settings(sandbox: Path) -> None:
    """The seal itself is under test: a default QSettings lands in the sandbox."""
    assert _guard.settings_file().is_relative_to(sandbox.resolve())


def test_pure_logic_modules_do_not_pull_artisan_main() -> None:
    """The modules L1 tests rely on stay free of the heavyweight import.

    If one of them ever grows an ``artisanlib.main`` dependency, the unit suite
    silently turns into a full-application import and stops being fast or safe.
    """
    pure = ['roast_plan_model', 'roasters', 'tilauscope_types', 'guidance_core',
            'guidance_observer',
            'guidance_replay',
            'guidance_risk',
            'guidance_phase',
            'guidance_trajectory',
            'guidance_advice',
            'guidance_session',
            'storage_advisor', 'brew_advisor', 'roast_insights']
    offenders = sorted(set(pure) & ARTISAN_MAIN_IMPORTERS)
    assert not offenders, f'pure-logic modules now import artisanlib.main: {offenders}'

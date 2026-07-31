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

"""Session-wide setup for the TilauScope test suite.

The sandbox is installed at *import* time, not in a fixture: pytest imports
this module before any test module, so the Qt settings redirection is in place
before the first ``tilauscope`` import can build a ``QSettings``.  Doing it in
a fixture would already be too late.  See ``_guard.py`` for why this matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import _guard  # noqa: E402  # must be imported before anything pulls in Qt settings
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Installed on import — deliberately at module scope, see the docstring above.
_SANDBOX = _guard.install()


@pytest.fixture(scope='session')
def sandbox() -> Path:
    """Directory every QSettings write is confined to for this session."""
    return _SANDBOX


@pytest.fixture(scope='session', autouse=True)
def _sandbox_still_sealed() -> Iterator[None]:
    """Re-verify the sandbox after the session.

    Guards against a test importing a module that rebinds the Qt settings
    backend mid-run: the seal is checked before *and* after, so a late escape
    cannot pass unnoticed just because setup was clean.
    """
    _guard.verify(_SANDBOX)
    yield
    _guard.verify(_SANDBOX)


@pytest.fixture(scope='session')
def qapp() -> Iterator[Any]:
    """Offscreen ``QApplication`` for tests that genuinely need a Qt event loop.

    Opt-in on purpose. Pure-logic tests must not request it: the cheapest way
    to stay safe is to not instantiate Qt at all.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # Not calling quit()/deleteLater(): the session-scoped instance is torn down
    # with the process, and destroying it early breaks later Qt-owned objects.


@pytest.fixture
def plan_model() -> Any:
    """A ``TilauScopeRoastPlan`` with no Artisan parent and no roaster context.

    This is the no-context fallback path the model documents for plan previews
    and unit tests: ``mode`` stays 'C' and machine constants come from the
    generic defaults rather than a loaded roaster.
    """
    from tilauscope.roast_plan_model import TilauScopeRoastPlan

    return TilauScopeRoastPlan(parent=None, roaster_ctx=None)

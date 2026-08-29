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

"""Wake-lock ownership and lifecycle regressions for TilauScope."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event
from typing import Any

import pytest


@pytest.mark.usefixtures('qapp')  # owns the Qt objects QThread needs
def test_wake_controller_start_is_idempotent_and_finish_releases(
    monkeypatch: Any,
) -> None:
    from tilauscope import wake_classes

    acquired = Event()
    released = Event()

    @contextmanager
    def fake_presenting() -> Iterator[None]:
        acquired.set()
        try:
            yield
        finally:
            released.set()

    monkeypatch.setattr(wake_classes.keep, 'presenting', fake_presenting)
    controller = wake_classes.TilauController()

    controller.start()
    assert acquired.wait(1)
    first_thread = controller._thread  # pylint: disable=protected-access
    controller.start()
    assert controller._thread is first_thread  # pylint: disable=protected-access

    controller.finish()

    assert released.wait(1)
    assert controller._thread is None  # pylint: disable=protected-access
    assert controller._worker is None  # pylint: disable=protected-access

    # Repeated shutdown is intentionally harmless (closeEvent + aboutToQuit).
    controller.finish()

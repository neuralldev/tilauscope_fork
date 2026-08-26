# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Artisan's once-a-second reading has to reach the window, mixins or not.

The window is assembled from slices. Qt registers a class's slots in that
class's own metaobject, and a QObject built from several QObject-derived bases
receives only the first one's — so when the slices were QWidget subclasses, the
``@pyqtSlot`` on the live update sat in a metaobject nobody consulted, and
connecting Artisan's signal to it failed outright at construction with a
complaint about a slot taking no arguments.

Every earlier check passed through that: the source was identical to the
character, the decorator was intact, the imports resolved, 1136 tests were
green. Only starting the application found it. This is the runtime half.
"""

from __future__ import annotations

from typing import Any


def _live_window(qapp: Any) -> tuple[Any, Any]:
    """The live slice, mixed in behind another one exactly as the window does it.

    LiveMixin is used because it holds the slot that actually broke and because
    it can be imported without pulling in Artisan.
    """
    del qapp
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QWidget

    from tilauscope.window.live import LiveMixin

    class _Ahead(QWidget):
        """Stands in for a slice listed before the live one.

        Deliberately a QWidget: that is what every slice used to be, and it is
        the arrangement that hid the live slot's metaobject. Keeping it that way
        here means this test still fails if the live slice becomes a widget
        again.
        """

    class _Source(QObject):
        # the real shape of qmc.tilauUpdateSignal
        tilauUpdateSignal = pyqtSignal(int, object, object, bool)

    class _Window(_Ahead, LiveMixin, QWidget):
        def __init__(self) -> None:
            super().__init__(None)
            self.seen: list[tuple[Any, ...]] = []

        def _apply_artisan_update(self, data: Any, value: Any = None,
                                  raw: Any = None, button: Any = True) -> None:
            self.seen.append((data, value, raw, button))

    return _Window(), _Source()


def test_the_live_update_can_be_connected_at_all(qapp: Any) -> None:
    """The exact call that failed: connect Artisan's signal to the window."""
    window, source = _live_window(qapp)
    source.tilauUpdateSignal.connect(window.update_ui_from_artisan)


def test_a_reading_actually_arrives(qapp: Any) -> None:
    """Connecting is not enough; the four arguments have to survive the trip."""
    window, source = _live_window(qapp)
    source.tilauUpdateSignal.connect(window.update_ui_from_artisan)
    source.tilauUpdateSignal.emit(12, 218.4, 219.0, True)
    assert window.seen == [(12, 218.4, 219.0, True)]


def test_a_failing_update_never_escapes_into_the_sample_loop(qapp: Any) -> None:
    """The slot's guard: Artisan's updateLCDs must not see our exceptions."""
    window, source = _live_window(qapp)

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('something in the panel gave up')

    window._apply_artisan_update = _explode
    source.tilauUpdateSignal.connect(window.update_ui_from_artisan)
    source.tilauUpdateSignal.emit(10, None, None, True)   # must not raise

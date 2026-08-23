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

"""Hot-reconfiguration contract for TilauScope's custom event panel."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _Signal:
    def __init__(self) -> None:
        self.slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self.slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in self.slots:
            slot(*args)


class _Geometry:
    @staticmethod
    def topLeft() -> tuple[int, int]:  # noqa: N802 - Qt API shape
        return (12, 34)


class _Panel:
    def __init__(self, *_args: Any) -> None:
        self.event_fired = _Signal()
        self.visible = True
        self.deleted = False
        self.width = 0
        self.position: Any = None

    def isVisible(self) -> bool:  # noqa: N802 - Qt API shape
        return self.visible

    @staticmethod
    def geometry() -> _Geometry:
        return _Geometry()

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def deleteLater(self) -> None:  # noqa: N802 - Qt API shape
        self.deleted = True

    def setFixedWidth(self, width: int) -> None:  # noqa: N802 - Qt API shape
        self.width = width

    def update_panel_height(self) -> None:
        pass

    def move(self, position: Any) -> None:
        self.position = position


class _ButtonManager:
    @staticmethod
    def from_artisan_settings(conf: Any, mode: str) -> tuple[Any, str]:
        return conf, mode


def test_rebuilt_event_panel_keeps_its_notification_connection(
    qapp: Any, monkeypatch: Any,
) -> None:
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas
    from tilauscope import displayscope

    assert tgraphcanvas is not None
    monkeypatch.setattr(displayscope, 'ButtonManager', _ButtonManager)
    monkeypatch.setattr(displayscope, 'EventPanel', _Panel)

    old_panel = _Panel()
    received: list[tuple[str, str, str, str]] = []
    scope = SimpleNamespace(
        artisan_conf=SimpleNamespace(mode='C'),
        theme={},
        event_panel=old_panel,
        btn_manager=object(),
        width=lambda: 640,
        align_panels=lambda: None,
        handle_event_fired=lambda *event: received.append(event),
    )

    displayscope.TilauScope.update_events_from_artisan(scope)
    scope.event_panel.event_fired.emit('FC', 'mark', '03:14', '#ffaa00')

    assert old_panel.deleted is True
    assert scope.event_panel is not old_panel
    assert scope.event_panel.width == 640
    assert scope.event_panel.position == (12, 34)
    assert scope.event_panel.visible is True
    assert received == [('FC', 'mark', '03:14', '#ffaa00')]

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

"""Simulator pause/resume transitions on TilauScope's timer."""

from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any


class _IntervalTimer:
    def __init__(self) -> None:
        self.interval = 600

    def setInterval(self, interval: int) -> None:  # noqa: N802 - Qt API shape
        self.interval = interval


def _scope(*, running: bool = True, charged: bool = True) -> SimpleNamespace:
    qmc = SimpleNamespace(
        flagon=True,
        flagstart=True,
        timeindex=[0 if charged else -1, 0, 0, 0, 0, 0, 0, 0],
    )
    aw = SimpleNamespace(qmc=qmc, sample_loop_running=running)
    styles: list[str] = []
    status_updates: list[bool] = []
    scope = SimpleNamespace(
        _is_simulator=True,
        _timer_state="roasting" if charged else "preheat",
        aw=aw,
        p_timer=_IntervalTimer(),
        update_status_text=lambda: status_updates.append(True),
        _styles=styles,
        _status_updates=status_updates,
    )

    def update_style(self: SimpleNamespace, state: str) -> None:
        self._timer_state = state
        self._styles.append(state)

    def toggle_simulator() -> None:
        aw.sample_loop_running = not aw.sample_loop_running

    scope._update_timer_style = MethodType(update_style, scope)
    scope._sync_simulator_timer_style = MethodType(
        _tilauscope()._sync_simulator_timer_style, scope,
    )
    aw.superusermodeLeftClicked = toggle_simulator
    return scope


def _tilauscope() -> Any:
    from tilauscope.displayscope import TilauScope

    return TilauScope


def _prepare_artisan_import(qapp: Any) -> None:
    """Give Artisan's import-time services their normal QApplication shape."""
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas

    assert tgraphcanvas is not None


def test_timer_click_immediately_shows_simulator_pause(qapp: Any) -> None:
    _prepare_artisan_import(qapp)
    scope = _scope(running=True)

    _tilauscope().timer_clicked(scope)

    assert scope.aw.sample_loop_running is False
    assert scope._timer_state == "paused"
    assert scope.p_timer.interval == 300
    assert scope._status_updates == [True]


def test_timer_click_restores_roasting_style_on_resume(qapp: Any) -> None:
    _prepare_artisan_import(qapp)
    scope = _scope(running=False)
    scope._timer_state = "paused"

    _tilauscope().timer_clicked(scope)

    assert scope.aw.sample_loop_running is True
    assert scope._timer_state == "roasting"
    assert scope.p_timer.interval == 600


def test_simulator_auto_charge_promotes_dark_timer_to_roasting(qapp: Any) -> None:
    """A CHARGE outside TilauScope must still clear the preheat appearance."""
    _prepare_artisan_import(qapp)
    scope = _scope(running=True, charged=True)
    scope._timer_state = "idle"

    scope._sync_simulator_timer_style()

    assert scope._timer_state == "roasting"
    assert scope._styles == ["roasting"]
    assert scope.p_timer.interval == 600


def test_simulator_preheat_promotes_dark_timer_to_fixed_preheat(qapp: Any) -> None:
    """Recording before CHARGE is active and must never look stopped."""
    _prepare_artisan_import(qapp)
    scope = _scope(running=True, charged=False)
    scope._timer_state = "idle"

    scope._sync_simulator_timer_style()

    assert scope._timer_state == "preheat"
    assert scope._styles == ["preheat"]
    assert scope.p_timer.interval == 600


def test_preheat_timer_is_light_and_has_no_opacity_effect(qapp: Any) -> None:
    from PyQt6.QtWidgets import QLabel
    from PyQt6.QtWidgets import QGraphicsOpacityEffect
    from tilauscope.tilauscope_types import THEME

    _prepare_artisan_import(qapp)
    label = QLabel("00:10")
    opacity = QGraphicsOpacityEffect(label)
    label.setGraphicsEffect(opacity)
    scope = SimpleNamespace(timer_lbl=label, timer_opacity=opacity)

    _tilauscope()._update_timer_style(scope, "preheat")

    assert label.graphicsEffect() is None
    assert scope.timer_opacity is None
    assert THEME['TEXT'].lower() in label.styleSheet().lower()


def test_simulator_sync_does_not_overwrite_emergency_timer(qapp: Any) -> None:
    _prepare_artisan_import(qapp)
    scope = _scope(running=True, charged=True)
    scope._timer_state = "emergency"

    scope._sync_simulator_timer_style()

    assert scope._timer_state == "emergency"
    assert scope._styles == []


def test_timer_click_before_recording_does_not_toggle_superuser_mode(qapp: Any) -> None:
    _prepare_artisan_import(qapp)
    scope = _scope()
    scope.aw.qmc.flagstart = False
    calls: list[bool] = []
    scope.aw.superusermodeLeftClicked = lambda: calls.append(True)

    _tilauscope().timer_clicked(scope)

    assert calls == []

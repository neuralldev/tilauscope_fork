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

"""STOP before CHARGE is an interruption, not a completed roast."""

from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any


class _WidgetDouble:
    def __init__(self) -> None:
        self.text = ''

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API shape
        self.text = text

    def setToolTip(self, _text: str) -> None:  # noqa: N802 - Qt API shape
        pass

    def setVisible(self, _visible: bool) -> None:  # noqa: N802 - Qt API shape
        pass

    def set_active(self, _active: bool) -> None:
        pass

    def reset_alert(self) -> None:
        pass

    def init_minmax(self) -> None:
        pass


def _scope(tilauscope: Any, *, charged: bool) -> SimpleNamespace:
    qmc = SimpleNamespace(
        device=0,
        flagstart=True,
        timeindex=[0 if charged else -1, 0, 0, 0, 0, 0, 0, 0],
    )

    def toggle_recorder(_pressed: bool) -> None:
        qmc.flagstart = False

    qmc.ToggleRecorder = toggle_recorder
    lcd = _WidgetDouble()
    scope = SimpleNamespace(
        aw=SimpleNamespace(
            qmc=qmc,
            simulator=None,
            tilauPreheatingPid=None,
            messagelabel=_WidgetDouble(),
        ),
        is_roasting=True,
        preheating=not charged,
        roast_bridge=SimpleNamespace(notify_roast_state=lambda _state: None),
        btn_reset=_WidgetDouble(),
        btn_start_stop=_WidgetDouble(),
        phases={'DRY': _WidgetDouble()},
        msg_lbl=_WidgetDouble(),
        lcds=SimpleNamespace(tg_lcd=lcd, te_lcd=lcd, ror_lcd=lcd),
        _update_timer_style=lambda _state: None,
        _hide_automation_banner=lambda: None,
        handle_preheat=lambda _show: None,
        update_status_text=lambda: None,
        update_button_style=lambda *_args: None,
        set_button_style=lambda *_args: None,
        set_button_state=lambda *_args: None,
        _clear_cooling_face=lambda: None,
    )
    scope._has_charged_roast = MethodType(tilauscope._has_charged_roast, scope)
    return scope


def _tilauscope(qapp: Any) -> Any:
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas
    from tilauscope.displayscope import TilauScope

    assert tgraphcanvas is not None
    return TilauScope


def test_stop_during_preheat_does_not_schedule_post_roast_dialog(
    qapp: Any, monkeypatch: Any,
) -> None:
    tilauscope = _tilauscope(qapp)
    from tilauscope import displayscope

    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        displayscope, 'QTimer',
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )
    scope = _scope(tilauscope, charged=False)

    tilauscope.toggle_start_stop(scope, False)

    assert scheduled == []
    assert 'Preheating interrupted' in scope.msg_lbl.text


def test_stop_after_charge_still_schedules_post_roast_dialog(
    qapp: Any, monkeypatch: Any,
) -> None:
    tilauscope = _tilauscope(qapp)
    from tilauscope import displayscope

    scheduled: list[tuple[int, Any]] = []
    monkeypatch.setattr(
        displayscope, 'QTimer',
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )
    scope = _scope(tilauscope, charged=True)
    scope._open_roast_result_dialog = lambda: None

    tilauscope.toggle_start_stop(scope, False)

    assert len(scheduled) == 1
    assert scheduled[0][0] == 800
    assert 'Roasting has ended' in scope.msg_lbl.text

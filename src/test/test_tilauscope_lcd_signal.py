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

"""Regression tests for the live LCD signal consumed by TilauScope."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class _Signal:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def emit(self, *args: Any) -> None:
        self.calls.append(args)


class _LCD:
    def display(self, _value: Any) -> None:
        pass


class _Label:
    def __init__(self) -> None:
        self.value = ''

    def text(self) -> str:
        return self.value

    def setText(self, value: str) -> None:  # noqa: N802 - Qt API shape
        self.value = value


def _canvas_double() -> SimpleNamespace:
    signal = _Signal()
    return SimpleNamespace(
        LCDdecimalplaces=True,
        flagon=True,
        tilauUpdateSignal=signal,
        aw=SimpleNamespace(
            lcd2=_LCD(),
            lcd3=_LCD(),
            lcd4=_LCD(),
            lcd5=_LCD(),
            ser=SimpleNamespace(showFujiLCDs=False),
            WebLCDs=False,
            nLCDS=0,
        ),
        updateLargeDeltaLCDs=lambda **_kwargs: None,
        updateLargeLCDsReadingsSignal=_Signal(),
        updateLargeLCDsSignal=_Signal(),
        updateLargeExtraLCDs=lambda **_kwargs: None,
    )


def test_ror_no_reading_sentinel_is_not_emitted_as_raw_measurement(qapp: Any) -> None:
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas

    canvas = _canvas_double()
    tgraphcanvas.updateLCDs(
        canvas, None, [100.0], [200.0], [5.0], [-1.0], [], [], idx=-1,
    )

    ror_call = next(call for call in canvas.tilauUpdateSignal.calls if call[0] == 13)
    assert ror_call[1] == 'u.u'
    assert ror_call[2] is None


def test_valid_negative_ror_is_still_emitted(qapp: Any) -> None:
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas

    canvas = _canvas_double()
    tgraphcanvas.updateLCDs(
        canvas, None, [100.0], [200.0], [5.0], [-2.5], [], [], idx=-1,
    )

    ror_call = next(call for call in canvas.tilauUpdateSignal.calls if call[0] == 13)
    assert ror_call[1] == '-2.5'
    assert ror_call[2] == -2.5


def test_roast_screen_defensively_ignores_a_raw_ror_sentinel(qapp: Any) -> None:  # noqa: ARG001
    from tilauscope.displayscope import TilauScope

    received: list[tuple[str, Any]] = []
    ror_lcd = SimpleNamespace(
        lbl_value=_Label(),
        set_alert_value=lambda value: received.append(('alert', value)),
        set_ror_color=lambda value, mode: received.append(('color', (value, mode))),
        update_minmax=lambda value: received.append(('minmax', value)),
    )
    scope = SimpleNamespace(
        aw=SimpleNamespace(qmc=SimpleNamespace(mode='C', timeindex=[0] * 8)),
        extra_panel=SimpleNamespace(isVisible=lambda: False),
        lcds=SimpleNamespace(ror_lcd=ror_lcd),
        is_roasting=True,
    )

    TilauScope._apply_artisan_update(scope, 13, 'u.u', -1.0)

    assert ror_lcd.lbl_value.text() == 'u.u'
    assert received == []

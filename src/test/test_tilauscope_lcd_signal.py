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


def _value_font_px(readout: Any) -> int:
    sheet = readout.lbl_value.styleSheet()
    size = sheet.split('font-size:')[1].split('px')[0]
    return int(size.strip())


def test_ror_readout_keeps_its_size_across_colour_bands(qapp: Any) -> None:  # noqa: ARG001
    """The rate-of-rise readout is the larger of the three (docs/the-window.md).

    ``set_ror_color`` rewrites the whole value stylesheet, so it has to carry
    the size the readout was built at — it used to emit a smaller one, and the
    counter shrank for good on the first band crossing of every roast.
    """
    from tilauscope.widgets.readouts import LCDReadout

    ror = LCDReadout('RoR °C/m', '#89B4FA', is_main=True)
    bt = LCDReadout('BT °C', '#FAB387')
    built = _value_font_px(ror)

    assert built > _value_font_px(bt), 'the RoR readout is built larger than BT'

    for value in (3.0, 12.0, 18.0, 25.0, 7.0):
        ror.set_ror_color(value, 'C')
        assert _value_font_px(ror) == built


def test_overshoot_pulse_stops_when_the_value_comes_back_down(qapp: Any) -> None:  # noqa: ARG001
    """Crossing the alert target and coming back must leave no pulse behind.

    The repaint shortcut compares against a ratio cached before the crossing,
    so a value returning close to where it left kept the alert pulsing over a
    reading that was back in range — the rate of rise crosses its 20 °C/min
    threshold in both directions during a normal climb.
    """
    from PyQt6.QtCore import QAbstractAnimation

    from tilauscope.widgets.readouts import LCDReadout

    def _readout() -> Any:
        return LCDReadout('RoR °C/m', '#89B4FA', is_main=True,
                          alert_target=20.0, alert_range=10.0)

    ror = _readout()
    ror.set_alert_value(19.5)     # inside the approach band
    ror.set_alert_value(20.3)     # over target — the pulse starts
    assert ror._pulsing is True

    ror.set_alert_value(19.55)    # back under, within the shortcut's tolerance
    assert ror._pulsing is False
    assert ror._pulse_anim.state() == QAbstractAnimation.State.Stopped

    # and the face is the one this reading would have shown all along
    never_crossed = _readout()
    never_crossed.set_alert_value(19.55)
    assert ror._current_bg.name() == never_crossed._current_bg.name()

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Two widgets that paid a stylesheet parse where a repaint would do.

A Qt stylesheet is text: every assignment reparses it and re-polishes the
widget and its children. The overshoot readout did that on every frame of an
800 ms pulse loop, on the same event loop that samples the probes; the value
roller did it once per entry, and its SV column runs 0-250 in Celsius and
0-482 in Fahrenheit. The roller also opened on an arithmetic guess at where
the current value was, and usually missed the screen.

Neither cost was a crash, and neither was ever going to be. What these tests
hold is the shape: the pulse repaints, the roller's cost does not follow its
range, and it opens on the value the operator came to change.

Both widgets are imported directly — they know nothing of Artisan, which is
what earned them a place in ``tilauscope.widgets``.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# The pulsing readout
# ---------------------------------------------------------------------------

def _readout(qapp: Any) -> Any:
    """An overshoot-capable readout that counts what it is asked to do."""
    del qapp  # the fixture only has to exist before a widget is built
    from tilauscope.widgets.readouts import LCDReadout

    class _Counted(LCDReadout):
        sheets = 0
        repaints = 0

        def setStyleSheet(self, sheet: str) -> None:  # noqa: N802 - Qt API shape
            self.sheets = getattr(self, 'sheets', 0) + 1
            super().setStyleSheet(sheet)

        def update(self, *args: Any) -> None:  # noqa: N802
            self.repaints = getattr(self, 'repaints', 0) + 1
            super().update(*args)

    return _Counted('BT °C', '#89B4FA', alert_target=230.0, alert_range=30.0)


def test_the_pulse_repaints_it_does_not_restyle(qapp: Any) -> None:
    """The frames of the overshoot animation must not touch the stylesheet."""
    from PyQt6.QtGui import QColor

    lcd = _readout(qapp)
    settled = lcd.sheets
    for step in range(60):          # one second of pulse at the frame rate
        lcd._bg_color_prop = QColor(0x3A + step % 32, 0, 0)
    assert lcd.sheets == settled, 'the sheet is set once, at construction'


def test_every_frame_of_the_pulse_reaches_the_paint(qapp: Any) -> None:
    """Guards the shortcut that skips an unchanged colour.

    The animated property setter used to assign the colour attribute itself
    before delegating. With a repaint that returns early when the colour has
    not moved, that assignment would make the comparison always find them
    equal — and the pulse would sit frozen on its first frame.
    """
    from PyQt6.QtGui import QColor

    lcd = _readout(qapp)
    before = lcd.repaints
    frames = [QColor(0x3A + step, 0, 0) for step in range(12)]
    for colour in frames:
        lcd._bg_color_prop = colour
    assert lcd.repaints - before == len(frames)
    assert lcd._bg_color_prop == frames[-1]


def test_a_colour_that_has_not_moved_costs_nothing(qapp: Any) -> None:
    """Half the samples land on the colour already showing."""
    from PyQt6.QtGui import QColor

    lcd = _readout(qapp)
    lcd._bg_color_prop = QColor('#3a0000')
    before, sheets = lcd.repaints, lcd.sheets
    for _ in range(30):
        lcd._bg_color_prop = QColor('#3a0000')
    assert lcd.repaints == before, 'a colour already showing was repainted'
    assert lcd.sheets == sheets, 'a colour already showing was restyled'


def test_the_approach_colours_still_move_the_background(qapp: Any) -> None:
    """The gradual warm-up towards the target is the reason this widget exists."""
    lcd = _readout(qapp)
    seen = []
    for value in (150.0, 205.0, 215.0, 225.0, 229.5):
        lcd.set_alert_value(value)
        seen.append(lcd._bg_color_prop.name())
    assert len(set(seen)) == len(seen), f'expected five distinct shades, got {seen}'
    assert seen[0] == lcd._BG_NEUTRAL.name()


def test_the_readout_paints_its_own_box(qapp: Any) -> None:
    """No stylesheet background means the widget owes the fill itself."""
    from PyQt6.QtGui import QColor, QImage

    lcd = _readout(qapp)
    lcd.resize(118, 90)
    lcd.set_alert_value(229.5)          # deep in the alert band
    image = QImage(118, 90, QImage.Format.Format_ARGB32)
    image.fill(0)
    lcd.render(image)
    assert QColor(image.pixel(59, 45)) == lcd._bg_color_prop, 'centre is unpainted'


# ---------------------------------------------------------------------------
# The value roller
# ---------------------------------------------------------------------------

def _roller(qapp: Any, low: int, high: int, step: int = 1,
            current: int | None = None) -> tuple[Any, list[int], list[str]]:
    """A roller over the given range, plus the values and sheets it produced."""
    del qapp
    from tilauscope.widgets import controls

    sheets: list[str] = []

    class _CountedButton(controls.QPushButton):  # type: ignore[name-defined]
        def setStyleSheet(self, sheet: str) -> None:  # noqa: N802
            sheets.append(sheet)
            super().setStyleSheet(sheet)

    # Swapped only for the construction, which is where the entries are built.
    original = controls.QPushButton
    controls.QPushButton = _CountedButton
    try:
        picked: list[int] = []
        roller = controls.SmartRoller(low if current is None else current,
                                      '#89B4FA', picked.append, low, high, step)
    finally:
        controls.QPushButton = original
    return roller, picked, sheets


def test_opening_the_roller_does_not_scale_with_its_range(qapp: Any) -> None:
    """A ten-entry roller and a 251-entry one must cost the same in stylesheets."""
    _, _, short = _roller(qapp, 0, 10)
    _, _, full = _roller(qapp, 0, 250)
    assert len(short) == len(full) == 0, (
        f'per-entry styling is back: {len(short)} then {len(full)} sheets'
    )


def test_the_range_is_still_covered_entry_by_entry(qapp: Any) -> None:
    for low, high, step in ((0, 250, 1), (0, 100, 5), (30, 60, 2)):
        roller, _, _ = _roller(qapp, low, high, step)
        wanted = list(range(low, high + 1, step))
        assert roller.content_layout.count() == len(wanted)
        assert roller.content_layout.itemAt(0).widget().text() == str(wanted[0])
        assert roller.content_layout.itemAt(-1 + len(wanted)).widget().text() == str(
            wanted[-1])


def test_every_entry_reports_its_own_value(qapp: Any) -> None:
    """The value used to travel in a closure per entry; now it rides the button."""
    for low, high, step in ((0, 250, 1), (0, 100, 5), (30, 60, 2)):
        roller, picked, _ = _roller(qapp, low, high, step)
        wanted = list(range(low, high + 1, step))
        for index in (0, 1, len(wanted) // 2, len(wanted) - 1):
            roller.content_layout.itemAt(index).widget().click()
        assert picked == [wanted[i] for i in
                          (0, 1, len(wanted) // 2, len(wanted) - 1)]


def test_exactly_one_entry_is_marked_as_the_current_value(qapp: Any) -> None:
    """The mark is what the single stylesheet keys the highlight off."""
    roller, _, _ = _roller(qapp, 0, 250, current=188)
    marked = [
        roller.content_layout.itemAt(i).widget()
        for i in range(roller.content_layout.count())
        if roller.content_layout.itemAt(i).widget().property('current') == 'true'
    ]
    assert [button.text() for button in marked] == ['188']


def test_the_current_entry_is_the_one_that_is_highlighted(qapp: Any) -> None:
    """Rendered proof: the accent pill lands on the selected row, not elsewhere."""
    from PyQt6.QtGui import QColor, QImage

    accent = QColor('#89B4FA').rgb()
    roller, _, _ = _roller(qapp, 0, 250, current=2)
    roller.show()
    roller.container.ensurePolished()
    image = QImage(75, 350, QImage.Format.Format_ARGB32)
    image.fill(0)
    roller.render(image)
    rows = {y for y in range(350) for x in range(75) if image.pixel(x, y) == accent}
    assert rows, 'the selected entry is not filled with the accent colour'
    # entries are 38 px tall and the third one is the one selected
    assert min(rows) > 38, f'the highlight sits too high: rows {min(rows)}-{max(rows)}'


def _entry(roller: Any, value: int) -> Any:
    return next(
        roller.content_layout.itemAt(i).widget()
        for i in range(roller.content_layout.count())
        if roller.content_layout.itemAt(i).widget().text() == str(value)
    )


def _offset_from_centre(roller: Any, value: int) -> tuple[int, int, int]:
    """Where the entry's middle sits inside the visible window."""
    roller.show()
    roller._centre_on_current()
    entry = _entry(roller, value)
    viewport = roller.scroll.viewport().height()
    middle = (entry.y() + entry.height() // 2
              - roller.scroll.verticalScrollBar().value())
    return middle, viewport, middle - viewport // 2


def test_the_roller_opens_centred_on_the_current_value(qapp: Any) -> None:
    """It used to open on an arithmetic guess, and usually missed the screen.

    The old position multiplied the value by 52 px where an entry occupies 44,
    and counted values rather than entries — so on the setpoint roller the
    number the operator had come to change was some thirty entries above the
    visible window.
    """
    for low, high, step, current in ((0, 250, 1, 188), (0, 100, 5, 50),
                                     (0, 100, 1, 50), (30, 60, 2, 46)):
        roller, _, _ = _roller(qapp, low, high, step, current=current)
        middle, viewport, offset = _offset_from_centre(roller, current)
        assert 0 <= middle <= viewport, (
            f'range({low},{high},{step}) current={current}: the entry is not '
            f'even on screen ({middle} of {viewport})'
        )
        assert abs(offset) <= 1, (
            f'range({low},{high},{step}) current={current}: off centre by {offset}'
        )


def test_the_ends_of_the_range_settle_against_the_edges(qapp: Any) -> None:
    """Nothing to centre against past the first and last entry.

    The scrollbar clamps on its own; what matters is that both stay visible
    rather than the column hanging off the edge.
    """
    for current in (0, 250):
        roller, _, _ = _roller(qapp, 0, 250, current=current)
        middle, viewport, _ = _offset_from_centre(roller, current)
        assert 0 <= middle <= viewport, f'entry {current} is off screen'


def test_a_value_between_two_steps_still_opens_somewhere_sensible(qapp: Any) -> None:
    """A roller stepping by 5 has no entry for 47; the nearest one is centred."""
    roller, _, _ = _roller(qapp, 0, 100, 5, current=47)
    roller.show()
    roller._centre_on_current()
    assert roller._current_btn.text() == '45'
    entry = roller._current_btn
    viewport = roller.scroll.viewport().height()
    middle = (entry.y() + entry.height() // 2
              - roller.scroll.verticalScrollBar().value())
    assert abs(middle - viewport // 2) <= 1

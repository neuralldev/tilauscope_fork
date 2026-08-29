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

"""Contracts for the custom-button editor.

The canvas claims to show what the roast screen will show. That claim rests on
three pure functions: where the tray ends, where the rounded groups break, and
how a stored event type reads back as two plain-word choices. All three are
ported from Artisan rather than invented, so they are pinned here — a drift
would not raise, it would just draw a lie.

The last test builds the dialog itself against a stubbed application window.
Nothing else constructs it, so a renamed attribute on either side of that
boundary would otherwise only be found by opening the menu.

The floating bar cannot be built here — importing it pulls in ``artisanlib.main``
and that costs unrelated tests their log records. It is built in a child; see
``test_event_panel_groups.py``, which reuses the stubs below.
"""

from __future__ import annotations

_APP = None


def _app():
    global _APP  # noqa: PLW0603 - Qt requires one process-wide strong reference
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _specs(visibility: list[bool]):
    from tilauscope.custom_buttons import ButtonSpec

    return [ButtonSpec(label='b', visible=v) for v in visibility]


def test_hidden_buttons_before_the_first_visible_one_form_the_tray() -> None:
    from tilauscope.button_layout import first_visible

    # Artisan skips them when filling rows, so they take no slot and only an
    # alarm can reach them.
    assert first_visible(_specs([False, False, True, True])) == 2
    assert first_visible(_specs([True, False, True])) == 0
    # No visible button at all: Artisan falls back to 0 and places everything.
    assert first_visible(_specs([False, False])) == 0


def test_a_gap_splits_the_rounded_group() -> None:
    from tilauscope.button_layout import round_codes

    # Four visible buttons, a gap third: [0][1] ┊ [3][4] — two groups, each
    # rounded on its outer edge. Codes: 1 left, 2 right, 3 both, 0 square.
    # The gap carries a code of its own, never drawn.
    rows = _specs([True, True, False, True, True])
    codes = round_codes(rows, per_row=5, first=0)
    assert [codes[i] for i in (0, 1, 3, 4)] == [1, 2, 1, 2]

    # Without the gap the four are one welded group.
    rows = _specs([True, True, True, True])
    assert round_codes(rows, per_row=4, first=0) == [1, 0, 0, 2]

    # A lone button in its row is rounded on both sides.
    assert round_codes(_specs([True]), per_row=4, first=0) == [3]


def test_event_type_splits_into_a_name_and_a_mode_and_back() -> None:
    from tilauscope.button_labels import (
        MODE_OFFSET, MODE_PERCENT, MODE_SET, NO_EVENT,
        join_event_type, split_event_type,
    )

    assert split_event_type(NO_EVENT) == (-1, MODE_SET)
    assert split_event_type(2) == (2, MODE_SET)
    assert split_event_type(7) == (2, MODE_OFFSET)
    assert split_event_type(11) == (2, MODE_PERCENT)

    # Every type the editor can write survives the round trip unchanged; the
    # roasting engine and the .aset format both read these integers.
    for stored in [NO_EVENT, *range(4), *range(5, 9), *range(9, 13)]:
        etype, mode = split_event_type(stored)
        assert join_event_type(etype, mode) == stored

    # Out of range collapses to "records nothing" rather than to a wrong event.
    assert join_event_type(9, MODE_SET) == NO_EVENT


def test_state_sequences_render_differently_pressed_and_released() -> None:
    _app()
    from tilauscope.button_labels import subst_button_label

    etypes = ['Air', 'Drum', 'Damper', 'Burner', '--']
    released = subst_button_label('\\3', 4, etypes, 0.0, 'C', state=0)
    pressed = subst_button_label('\\3', 4, etypes, 0.0, 'C', state=1)
    assert released != pressed
    assert '\\3' not in released

    # A state-free sequence reads the same either way.
    assert (subst_button_label('\\1', 4, etypes, 0.0, 'C', state=0)
            == subst_button_label('\\1', 4, etypes, 0.0, 'C', state=1))

    # The event name comes from the roaster's own labels.
    assert subst_button_label('\\t', 3, etypes, 0.0, 'C') == 'Burner'


class _Qmc:
    mode = 'C'
    etypes = ['Air', 'Drum', 'Damper', 'Burner', '--']

    @staticmethod
    def eventsInternal2ExternalValue(v):
        from artisanlib.util import events_internal_to_external_value
        return events_internal_to_external_value(v)

    def eventsvalues(self, v):
        return str(self.eventsInternal2ExternalValue(v))

    def etypesf(self, i):
        return self.etypes[i] if 0 <= i < len(self.etypes) else '--'

    @staticmethod
    def str2eventsvalue(s):
        from artisanlib.util import events_external_to_internal_value
        return events_external_to_internal_value(int(s)) if s.strip() else -1


class _FakeWindow:
    """Stands in for the TilauScope window, which owns the floating bar."""

    def __init__(self):
        self.bar_rebuilds = 0

    def update_events_from_artisan(self):
        self.bar_rebuilds += 1


class _Conf:
    """The slice of ArtisanSettings the button factory actually reads."""

    def __init__(self, aw):
        self.aw = aw
        self.mode = aw.qmc.mode
        self.slider_names = [n.upper() for n in aw.qmc.etypes]


def _FakeManager(aw):  # noqa: N802 - reads as a constructor at the call site
    from tilauscope.window.parts import ButtonManager

    return ButtonManager.from_artisan_settings(_Conf(aw), aw.qmc.mode)


class _Aw:
    buttonpalettemaxlen_min = 2
    buttonpalettemaxlen_max = 50
    buttonlistmaxlen = 4
    NUMBER_OF_EXTRABUTTON_ROWS = 10

    def __init__(self):
        self.qmc = _Qmc()
        self.extraeventslabels = ['Preheat', 'Burner\n+5', 'Burner\n-5', '', '\\t\n70', 'Air \\1']
        self.extraeventsdescriptions = ['a', 'b', 'c', '', 'd', 'e']
        self.extraeventstypes = [4, 8, 8, 4, 1, 0]
        self.extraeventsvalues = [0.0, 1.5, 0.5, 0.0, 8.0, 11.0]
        self.extraeventsactions = [4, 0, 0, 0, 0, 19]
        self.extraeventsactionstrings = ['cmd', '', '', '', '', 'x']
        self.extraeventsvisibility = [0, 1, 1, 0, 1, 1]
        self.extraeventbuttoncolor = ['#808080'] * 6
        self.extraeventbuttontextcolor = ['#ffffff'] * 6
        self.realigned = 0
        self.tilauscope_main = _FakeWindow()

    def realignbuttons(self):
        self.realigned += 1

    def settooltip(self):
        pass

    def update_extraeventbuttons_visibility(self):
        pass


def test_the_editor_builds_and_applies():
    app = _app()
    from PyQt6.QtWidgets import QWidget
    from tilauscope.custom_buttons import CustomButtonManager

    parent = QWidget()
    aw = _Aw()
    dlg = CustomButtonManager(parent, aw)
    app.processEvents()

    # tray holds the one hidden button above every visible one; the empty
    # hidden button at index 3 is a gap inside a row
    assert set(dlg._tiles) == set(range(6))
    assert dlg._tiles[0].face.text() == 'Preheat'
    assert dlg._tiles[4].face.text() == 'Drum\n70'
    assert dlg._tiles[5].face.text() == 'Air ON'
    assert dlg._tiles[1].caption.text().startswith('Burner')

    # A gap inside the rows is drawn as the breathing space it produces, not as
    # a lost slot; a hidden button in the tray is a real button and keeps both
    # its width and its label.
    from tilauscope.custom_buttons import _GAP_W, _TILE_W

    assert dlg._tiles[3].width() == _GAP_W
    assert dlg._tiles[3].face.text() == ''
    assert dlg._tiles[0].width() == _TILE_W
    assert dlg._tiles[0].face.text() == 'Preheat'

    # Captions are cut to the tile rather than run into the neighbour, and the
    # whole text stays reachable on hover.
    from PyQt6.QtGui import QFontMetrics

    caption = dlg._tiles[5].caption
    metrics = QFontMetrics(caption.font())
    assert metrics.horizontalAdvance(caption.text()) <= _TILE_W
    assert caption.toolTip().startswith('Air')

    # A hidden button that carries something is not a separator: it keeps its
    # width and its label, so it cannot disappear into a 24 px sliver.
    dlg._select(3)
    dlg.label.setText('BURNER')
    assert not dlg._tiles[3].is_gap
    assert dlg._tiles[3].width() == _TILE_W
    assert dlg._tiles[3].face.text() == 'BURNER'
    dlg.label.setText('')
    assert dlg._tiles[3].is_gap
    assert dlg._tiles[3].width() == _GAP_W

    dlg._select(4)
    assert dlg.value.text() == '70'
    assert dlg.event_name.currentIndex() == 2   # Drum
    assert dlg.event_mode.currentIndex() == 0   # set to
    assert dlg.rendered.text() == 'Drum ⏎ 70'

    # a drop moves the button and flips visibility only when it crosses over
    dlg._on_drop(5, 1, False)
    assert aw.extraeventslabels[1] == 'Burner\n+5'
    dlg._apply()
    assert aw.realigned == 1
    # Artisan's bar and TilauScope's are two sets of widgets; applying has to
    # rebuild both or the floating bar keeps firing the previous buttons.
    assert aw.tilauscope_main.bar_rebuilds == 1
    assert aw.extraeventslabels[1] == 'Air \\1'
    assert aw.extraeventsvisibility[1] == 1
    parent.deleteLater()


def test_a_gap_ends_a_welded_group() -> None:
    from tilauscope.button_layout import split_groups, tray_and_rows

    # tray, then two buttons, a gap, two more: one row holding two groups.
    rows = _specs([False, True, True, False, True, True])
    tray, chunks = tray_and_rows(rows, per_row=8)
    assert tray == [0]
    assert chunks == [[1, 2, 3, 4, 5]]
    assert split_groups(chunks[0], rows) == [[1, 2], [4, 5]]

    # Rows are hard boundaries: four buttons at two per row are two groups,
    # never one welded run of four.
    rows = _specs([True] * 4)
    _tray, chunks = tray_and_rows(rows, per_row=2)
    assert chunks == [[0, 1], [2, 3]]
    assert [split_groups(c, rows) for c in chunks] == [[[0, 1]], [[2, 3]]]

    # A row of nothing but gaps yields no group, so the bar draws no line for it.
    rows = _specs([True, False, False])
    _tray, chunks = tray_and_rows(rows, per_row=1)
    assert [split_groups(c, rows) for c in chunks] == [[[0]], [], []]


def test_corner_radii_weld_the_middle_of_a_group() -> None:
    from tilauscope.button_layout import corner_radii

    assert corner_radii(0, 1) == (6, 6)             # alone: rounded both sides
    assert [corner_radii(i, 3) for i in range(3)] == [(6, 0), (0, 0), (0, 6)]

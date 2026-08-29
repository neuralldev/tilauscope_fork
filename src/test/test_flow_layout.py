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

"""Placement contracts for the wrapping layout.

Two surfaces share it and want opposite things: the extra-counters panel fills
from the left, the event-button bar centres. Centring is opt-in for that reason,
and the default has to stay exactly where it was — a layout that quietly moved
every counter would look like a rendering glitch, not like a regression.
"""

from __future__ import annotations

_APP = None
#: Qt owns widgets by parent; nothing here has one, so the hosts are kept alive
#: for the session rather than collected mid-test.
_HOSTS: list = []


def _app():
    global _APP  # noqa: PLW0603 - Qt requires one process-wide strong reference
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _laid_out(widths: list[int], box_w: int, *, centered: bool,
              break_after: list[int] | None = None) -> list[tuple[int, int]]:
    """Lay out boxes of the given widths and report their (x, y) corners."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QWidget

    from tilauscope.widgets.flow_layout import FlowLayout

    _app()
    host = QWidget()
    _HOSTS.append(host)
    layout = FlowLayout(host, margin=10, spacing=10, centered=centered)
    cells = []
    for position, width in enumerate(widths):
        cell = QWidget(host)
        cell.setFixedSize(width, 20)
        layout.addWidget(cell)
        cells.append(cell)
        if break_after and position in break_after:
            layout.addBreak()
    layout.setGeometry(QRect(0, 0, box_w, 400))
    return [(c.x(), c.y()) for c in cells]


def test_the_default_still_fills_from_the_left_margin() -> None:
    # Usable width is 229 (a 250 box, less both margins, and Qt's right edge is
    # inclusive). Two 100-wide cells and their spacing make 210 and fit; a third
    # would make 320 and wraps.
    placed = _laid_out([100, 100, 100], box_w=250, centered=False)
    assert [x for x, _y in placed] == [10, 120, 10]
    assert [y for _x, y in placed] == [10, 10, 40]


def test_centring_moves_the_block_and_keeps_one_left_edge() -> None:
    # A wide line and a narrow one, in a box with room to spare. Both start at
    # the same x: what is centred is the block, not each line.
    placed = _laid_out([100, 100, 100], box_w=400, centered=True,
                       break_after=[1])
    xs = [x for x, _y in placed]
    assert xs[0] == xs[2], 'the short line does not share the block left edge'
    assert xs[0] > 10, 'the block was not moved off the left margin'
    assert xs[1] == xs[0] + 110

    # Centred on the widest line: 210 wide inside 379 of usable width.
    assert xs[0] == 10 + (379 - 210) // 2


def test_a_block_wider_than_the_box_falls_back_to_the_left_margin() -> None:
    # Nothing may be pushed off the left edge to centre it: the offset floors
    # at zero, which is the behaviour the panel had before centring existed.
    placed = _laid_out([300, 300], box_w=200, centered=True)
    assert [x for x, _y in placed] == [10, 10]
    assert placed[0][1] != placed[1][1], 'the two cells should be on two lines'


def test_a_break_ends_a_line_the_width_could_have_held() -> None:
    placed = _laid_out([50, 50, 50], box_w=400, centered=False, break_after=[0])
    ys = [y for _x, y in placed]
    assert ys[0] != ys[1], 'the break did not end the first line'
    assert ys[1] == ys[2], 'the second line was cut without a break'

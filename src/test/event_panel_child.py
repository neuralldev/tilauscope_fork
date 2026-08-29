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

"""The floating event-button bar is actually built here, in a child.

Nothing else in the suite constructs it, and the editor's canvas now claims to
show what this bar will show — a claim only a built bar can check.

It runs in a child because importing it pulls in ``artisanlib.main``: in a
process where another TilauScope is running that import registers this process
as the ArtisanViewer, and every later isolated test then exits(0). It also
rewires logging, which silently costs unrelated ``caplog`` assertions their
records — three of them, when this first ran in-process.

Run directly for a quick look: ``python test/event_panel_child.py``.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))          # _guard, and the stubs in the test module
sys.path.insert(0, str(_HERE.parent))   # the `tilauscope` package itself

import _guard  # noqa: E402  # before anything can touch Qt settings

_SANDBOX = _guard.install(sys.argv[1] if len(sys.argv) > 1 else None)

CHECKS: dict[str, object] = {}


def check(fn):  # noqa: ANN001, ANN201
    CHECKS[fn.__name__] = fn
    return fn


def _panel(per_row: int):
    """A bar built over the shared stubs, at the given buttons-per-row."""
    from PyQt6.QtWidgets import QApplication

    import test_custom_buttons as stubs
    from tilauscope.window.parts import EventPanel

    QApplication.instance() or QApplication([])
    aw = stubs._Aw()  # noqa: SLF001 - the stubs are this suite's own
    aw.buttonlistmaxlen = per_row
    return EventPanel(stubs._FakeManager(aw), theme=None, parent=None)  # noqa: SLF001


def _groups(panel) -> list:  # noqa: ANN001
    return [panel.flow_layout.itemAt(i).widget()
            for i in range(panel.flow_layout.count())]


@check
def a_gap_splits_the_bar_into_two_welded_groups() -> None:
    from PyQt6.QtWidgets import QFrame

    # Buttons 1 and 2, a gap at 3, then 4 and 5, on a row wide enough for all.
    panel = _panel(per_row=8)
    groups = _groups(panel)
    assert all(isinstance(g, QFrame) for g in groups), 'a group is not a container'
    sizes = [g.layout().count() for g in groups]
    assert sizes == [2, 2], f'expected two welded pairs, got {sizes}'
    assert not panel.flow_layout._break_after, (  # noqa: SLF001
        'one row should need no forced break')


@check
def the_ends_of_a_group_are_the_only_rounded_corners() -> None:
    panel = _panel(per_row=8)
    group = _groups(panel)[0].layout()
    first = group.itemAt(0).widget().styleSheet()
    last = group.itemAt(1).widget().styleSheet()
    assert 'border-top-left-radius: 6px' in first, 'group does not open rounded'
    assert 'border-top-right-radius: 0px' in first, 'group welds on the wrong side'
    assert 'border-top-left-radius: 0px' in last, 'group welds on the wrong side'
    assert 'border-top-right-radius: 6px' in last, 'group does not close rounded'


@check
def a_row_boundary_is_a_break_the_width_cannot_undo() -> None:
    # Two per row cuts the run the gap alone would not have cut.
    panel = _panel(per_row=2)
    sizes = [g.layout().count() for g in _groups(panel)]
    assert sizes == [2, 1, 1], f'rows were not honoured, got {sizes}'
    assert panel.flow_layout._break_after, (  # noqa: SLF001
        'the row boundary left no forced break')


@check
def the_weld_between_two_buttons_outweighs_the_block_outline() -> None:
    from tilauscope.tilauscope_types import THEME

    panel = _panel(per_row=8)
    group = _groups(panel)[0].layout()
    first = group.itemAt(0).widget().styleSheet()
    last = group.itemAt(1).widget().styleSheet()
    assert f"border-right: 1px solid {THEME['SURFACE1']}" in first, (
        'the edge inside the block is no lighter than its outline')
    assert f"border-right: 1px solid {THEME['BORDER']}" in last, (
        'the block closes on the wrong edge colour')
    assert 'border-left: 5px solid' in first, (
        'the identity stripe no longer matches the milestone strip')


@check
def the_block_is_centred_in_a_bar_wider_than_it_needs() -> None:
    from PyQt6.QtCore import QRect

    panel = _panel(per_row=2)
    # Force a width well past what the buttons need, then lay out at it.
    panel.flow_layout.setGeometry(QRect(0, 0, 1400, 400))
    groups = _groups(panel)
    xs = [g.x() for g in groups]
    assert xs[0] > 10, f'the block sits on the left margin, at x={xs[0]}'
    # Two per row puts each group on its own line. They open at the same x
    # whatever their width, because what is centred is the block, not the line.
    lines = {}
    for g in groups:
        lines.setdefault(g.y(), []).append(g.x())
    assert len(lines) == 3, f'expected three lines, got {len(lines)}'
    opens = [min(v) for v in lines.values()]
    assert len(set(opens)) == 1, f'the lines do not share a left edge: {opens}'
    assert len({g.width() for g in groups}) > 1, (
        'every line came out the same width, so nothing was proven')


def main() -> int:
    results: dict[str, str | None] = {}
    for name, fn in CHECKS.items():
        try:
            fn()
            results[name] = None
        except Exception:  # noqa: BLE001 - every failure is reported, none aborts
            results[name] = traceback.format_exc()
    print('---JSON---')  # noqa: T201 - the child's only channel back
    print(json.dumps(results))  # noqa: T201
    return 0


if __name__ == '__main__':
    sys.exit(main())

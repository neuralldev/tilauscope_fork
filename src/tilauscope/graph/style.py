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

"""One visual vocabulary for every roast curve the application draws.

Four screens draw the same roast through two different engines: the live canvas
paints with QPainter, while the BeanCave viewer, the roast card and the phone
client go through matplotlib. They used to each carry their own greys, their own
type sizes and their own idea of what a milestone looks like, so the same roast
read as four products.

What a milestone *is* — a rule, a dot, a chip naming it and its reading — is
stated here once. What changes between the screens is only the reading distance
and where the chip is anchored: at arm's length during a roast the chips stack
above the plot so none of them sits on the curve head the eye keeps returning
to; at a desk afterwards they sit on their own point, where the extra locality
is worth more than the clearance.

Colours are hex strings, not QColor: matplotlib takes them as they are and the
Qt side wraps them where it already wraps every other theme token.
"""

from __future__ import annotations

from typing import Any, Final

from PyQt6.QtWidgets import QApplication

from tilauscope.graph.common import fmt_clock, fmt_temp
from tilauscope.tilauscope_types import THEME

# ── grounds ──────────────────────────────────────────────────────────────────
#: The page a chart is drawn on.
PAGE_GROUND: Final[str] = THEME['BG']
#: The plotting rectangle itself — an inset, one step darker than the page, so
#: the chart reads as a panel rather than as a hole in the window.
PLOT_GROUND: Final[str] = THEME['SURFACE']

# ── frame ────────────────────────────────────────────────────────────────────
GRID: Final[str] = THEME['BORDER']
GRID_WIDTH: Final[float] = 1.0
#: Plot border and axis spines.
FRAME: Final[str] = THEME['OVERLAY0']
#: Graduations are structure, not prose — quieter than any label beside them.
TICK: Final[str] = THEME['OVERLAY0']
#: Axis titles ("Time (min)", "Temp (°C)").
AXIS: Final[str] = THEME['SUBTEXT']

# ── milestones ───────────────────────────────────────────────────────────────
#: A marked milestone: dashed, because the operator put it there.
RULE: Final[str] = THEME['OVERLAY1']
RULE_WIDTH: Final[float] = 1.0
#: The turning point: dotted and brighter, because it is computed from the
#: readings rather than marked. The difference must survive a phase ground.
RULE_TP: Final[str] = THEME['SUBTEXT']
RULE_TP_WIDTH: Final[float] = 1.4
#: The dot says which point of the curve the chip belongs to.
DOT_RADIUS: Final[float] = 4.0
#: A ring of page colour detaches the dot from the curve running under it.
DOT_HALO: Final[str] = THEME['BG']
DOT_HALO_WIDTH: Final[float] = 2.0
#: The chip: an inset darker than the plot ground it sits on, so it never
#: competes with the assistant's own call to action.
CHIP_FILL: Final[str] = THEME['CRUST']
CHIP_FILL_ALPHA: Final[float] = 0.85
CHIP_OUTLINE: Final[str] = THEME['BORDER']
CHIP_OUTLINE_WIDTH: Final[float] = 1.0
CHIP_TEXT: Final[str] = THEME['SUBTEXT1']
CHIP_RADIUS: Final[float] = 3.0

# ── type sizes, in points ────────────────────────────────────────────────────
# One skin, three reading distances. A chip read at arm's length over a hot drum
# is not the same object as one read at a desk, and neither is a thumbnail.
FS_AXIS: Final[int] = 12
FS_TICK: Final[int] = 11
FS_LEGEND: Final[int] = 10
#: Live canvas — arm's length.
FS_CHIP_LIVE: Final[int] = 11
#: Roast viewer and its snapshots — desk distance.
FS_CHIP_REVIEW: Final[int] = 9
#: Roast card and phone client — a thumbnail names its milestones, nothing more.
FS_CHIP_THUMB: Final[int] = 8
FS_TICK_THUMB: Final[int] = 8


def chip_bbox(*, alpha: float = CHIP_FILL_ALPHA) -> dict[str, Any]:
    """The milestone chip as matplotlib draws it, for an `annotate` bbox."""
    return {
        'boxstyle': f'round,pad={CHIP_RADIUS / 10.0:.2f}',
        'fc': CHIP_FILL,
        'alpha': alpha,
        'ec': CHIP_OUTLINE,
        'lw': CHIP_OUTLINE_WIDTH,
    }


def _unit(mode: str) -> str:
    return (QApplication.translate('tilauscope', '°F') if mode == 'F'
            else QApplication.translate('tilauscope', '°C'))


def milestone_chip_ladder(label: str, temp: float | None, mode: str,
                          seconds: float | None, *, sep: str = '  ') -> list[str]:
    """Chip texts for one milestone, richest first.

    `temp` is already in the operator's unit — this formats, it never converts.

    A milestone that cannot show everything gives up its clock before its
    reading, and its reading before its name: on a dark roast FC END, SECOND
    CRACK and SC END fall within a minute of each other, and a milestone nobody
    can name is worth less than one without its temperature. A caller with room
    for all of it takes the first entry and ignores the rest.
    """
    if temp is None:
        return [label]
    reading = f'{fmt_temp(temp)} {_unit(mode)}'
    if seconds is None:
        return [f'{label}{sep}{reading}', label]
    # `sep` parts the name from its reading; the reading itself stays on one
    # line whatever the caller does with the name, so a stacked chip is two
    # rows tall and not three.
    return [f'{label}{sep}{reading}  {fmt_clock(seconds)}',
            f'{label}{sep}{reading}',
            label]

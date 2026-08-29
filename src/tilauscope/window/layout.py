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

"""Fixed geometry and styling the window is laid out against.

Numbers rather than behaviour: header slot widths, row insets, the parent
stylesheet Artisan's own window is given while TilauScope is open.
"""

from __future__ import annotations

from typing import Final

from tilauscope.tilauscope_types import THEME


# Explicit insets for every slider row (the 4 event sliders + SV), so the rows
# line up regardless of platform: the style's default margin differs between a
# widget-installed layout (~12 px macOS, 9 Windows) and a nested one (0).
_SLIDER_ROW_MARGINS: Final[tuple[int, int, int, int]] = (11, 2, 11, 2)

# SV lives outside the fixed-height event-control stack.  In the compact panel
# that layout boundary visually eats part of one regular row pitch; restore the
# missing distance so BURNER → SV matches the spacing of the four rows above.
_SV_ROW_GAP_CORRECTION_PX: Final[int] = 8

# Two-row header geometry — mockups/header-controls-professional-390.html.
# The primary row budget is exact: pane 390 - pane margins 20 = 370 usable.
# The 24 px taken by the drag handle immediately before the timer is paid for
# by the compact START width; otherwise the row overflows and its last items
# are painted on top of each other.
_HDR2_GAP:      Final[int] = 6

_HDR2_MARGINS:  Final[tuple[int, int, int, int]] = (4, 0, 4, 0)

_HDR2_MENU:     Final[tuple[int, int]] = (32, 32)

_HDR2_POWER:    Final[tuple[int, int]] = (91, 32)

_HDR2_START:    Final[tuple[int, int]] = (95, 32)

# Sized on the longest label the button carries, not on the English one:
# a fixed box shows every language the same width, and the French RESET is
# twice the letters. The 14 px over the English fit come out of the row's
# own slack (362 of 370 used), so nothing else on the row moves.
_HDR2_RESET:    Final[tuple[int, int]] = (86, 28)

_HDR2_BEANCAVE: Final[tuple[int, int]] = (92, 28)

_HDR2_LEVEL:    Final[tuple[int, int]] = (31, 28)

_HDR2_SWAP:     Final[tuple[int, int]] = (31, 28)

# Emergency heat cut. A crossed-out flame, not a label: the word shouted louder
# than anything else on the row. Wider than the 31 px icon buttons beside it so
# the target stays easy to hit under stress and the control keeps its own rank —
# it is the only critical-coloured item of the header.
_HDR2_ESTOP:    Final[tuple[int, int]] = (40, 28)

# Compact drag target directly to the left of the primary-row timer.
_HDR2_DRAG_W:   Final[int] = 24

# Header timer: pinned to the width of "-88:88" since the countdown before
# CHARGE can go negative. Single authority for the size across every timer state.
_TIMER_FONT_PX: Final[int] = 25

# Keep the legacy slider available as a one-line rollback while the segmented
# control is validated in live roasting.
_USE_SEGMENTED_SLIDER: Final[bool] = True

# Style à appliquer au parent pour la cohérence visuelle
PARENT_TILAUSTYLE = f"""
    /* On cible uniquement le widget avec cet ID précis */
    QWidget#CentralWidget {{
        background-color: #0F0F12;
        border: 1px solid {THEME['BORDER']};
        border-radius: 10px; /* Vos coins arrondis ici */
    }}

    /* On réinitialise explicitement les bordures pour les enfants directs ou indirects */
    #CentralWidget QWidget {{
        border-radius: 0px;
        border: none;
    }}
"""

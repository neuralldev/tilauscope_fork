#
# ABOUT
# The four automatic milestones: their defaults, and the choice Roast Setup makes
# for one roast only.

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

"""Auto Charge, Auto Drop (Artisan's Auto Mark flags), Auto Dry End and Auto First Crack.

Configuration › Detection (and Artisan's Events dialog) sets the defaults; Roast Setup
sets them for the roast it starts, and the defaults come back at the STOP of that roast
once charged, or at any OFF. While a roast holds its own choice, the defaults wait aside:
what Configuration › Detection shows and the settings save is them. A flag an alarm or a
button changes during the roast stays with that roast.
"""

from __future__ import annotations

from typing import Any

KEYS: tuple[str, ...] = ('charge', 'drop', 'dry_end', 'first_crack')


def _current(aw: Any) -> dict[str, bool]:
    return {'charge': bool(aw.qmc.autoChargeFlag), 'drop': bool(aw.qmc.autoDropFlag),
            'dry_end': bool(aw.TilauScopeDEMarkFlag), 'first_crack': bool(aw.TilauScopeFCMarkFlag)}


def _apply(aw: Any, values: dict[str, bool]) -> None:
    aw.qmc.autoChargeFlag = values['charge']
    aw.qmc.autoDropFlag = values['drop']
    aw.TilauScopeDEMarkFlag = values['dry_end']
    aw.TilauScopeFCMarkFlag = values['first_crack']


def defaults(aw: Any) -> dict[str, bool]:
    """The defaults, whether or not a roast holds its own choice."""
    held = getattr(aw, '_tilau_auto_marks_defaults', None)
    return dict(held) if held is not None else _current(aw)


def set_defaults(aw: Any, values: dict[str, bool]) -> None:
    """Configuration › Detection: during a roast with its own choice, kept for its end."""
    held = getattr(aw, '_tilau_auto_marks_defaults', None)
    if held is not None:
        held.update(values)
    else:
        _apply(aw, {**_current(aw), **values})


def choose_for_roast(aw: Any, values: dict[str, bool]) -> None:
    """Roast Setup: these milestones for the roast it starts only."""
    if getattr(aw, '_tilau_auto_marks_defaults', None) is None:
        aw._tilau_auto_marks_defaults = _current(aw)
    _apply(aw, {**_current(aw), **values})


def end_roast(aw: Any) -> None:
    """When the roast ends: the defaults again."""
    held = getattr(aw, '_tilau_auto_marks_defaults', None)
    if held is not None:
        _apply(aw, held)
        aw._tilau_auto_marks_defaults = None

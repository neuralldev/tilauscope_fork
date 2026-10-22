#
# ABOUT
# Plain-language reading of a green-bean physical measure, for TilauScope.
#
# Turns a raw density / humidity / water-activity figure into the word a roaster
# would use for it, plus the colour that word deserves. Shared by the bean sheet
# (read view) and the bean form (edit view) so a value can never read "normal"
# in one place and be flagged in the other.
#
# The bands are NOT defined here: they are the ones the energy model and the
# storage advisor already use. This module only names them.
#
# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version. It is provided for educational
# purposes and is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from tilaucore import bean_qualifiers as _core
from tilauscope.tilauscope_types import THEME

# The rule and the words live in tilaucore (shared with the tablet); here they are
# translated and coloured for the desktop.
_COLOUR: dict[str | None, str | None] = {None: None, _core.WARNING: THEME['WARNING'], _core.CRITICAL: THEME['CRITICAL']}


def physical_qualifier(kind: str, value: float) -> tuple[str, str | None]:
    """Return (word, colour) for a physical measure — ("", None) if not measured.

    kind is 'density' | 'humidity' | 'aw'. Colour is None inside the usual
    range, so the caller leaves its normal text colour alone.
    """
    word, level = _core.physical_qualifier(kind, value)
    if word is None:
        return "", None
    return QApplication.translate(*word), _COLOUR[level]


def screen_size_options() -> list[tuple[str, str]]:
    """(key, label) of every size class, Unknown first — keys of SCREEN_SIZE_RANGES."""
    return [(key, QApplication.translate(*label)) for key, label in _core.SCREEN_SIZE_OPTIONS]


def screen_size_label(key: str) -> str:
    """Label of a size class, or '' when unknown."""
    if not key:
        return ''
    return dict(screen_size_options()).get(key, '')

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

from tilauscope.bean_energy import (
    AW_BOUND_BELOW,
    AW_FREE_ABOVE,
    HUMIDITY_HIGH_PCT,
    HUMIDITY_LOW_PCT,
)
from tilauscope.storage_advisor import DEFAULT_THRESHOLDS
from tilauscope.tilauscope_types import THEME

# Density has no single reference constant in the energy model (it modulates
# continuously around 700 g/l), so the two ends are the ones the coach's advice
# already names to the operator.
DENSITY_LIGHT_BELOW: float = 650.0
DENSITY_DENSE_ABOVE: float = 780.0


def physical_qualifier(kind: str, value: float) -> tuple[str, str | None]:
    """Return (word, colour) for a physical measure — ("", None) if not measured.

    kind is 'density' | 'humidity' | 'aw'. Colour is None inside the usual
    range, so the caller leaves its normal text colour alone.
    """
    if not value or value <= 0.0:
        return "", None
    if kind == 'density':
        if value < DENSITY_LIGHT_BELOW:
            return QApplication.translate("tilauscope_beancave", "light"), THEME['WARNING']
        if value > DENSITY_DENSE_ABOVE:
            return QApplication.translate("tilauscope_beancave", "dense"), THEME['WARNING']
        return QApplication.translate("tilauscope_beancave", "standard"), None
    if kind == 'humidity':
        if value < HUMIDITY_LOW_PCT:
            return QApplication.translate("tilauscope_beancave", "dry — old crop"), THEME['WARNING']
        if value > HUMIDITY_HIGH_PCT:
            return QApplication.translate("tilauscope_beancave", "moist"), THEME['WARNING']
        return QApplication.translate("tilauscope_beancave", "normal"), None
    if kind == 'aw':
        if value < AW_BOUND_BELOW:
            return QApplication.translate("tilauscope_beancave", "bound water"), THEME['WARNING']
        if value >= DEFAULT_THRESHOLDS.risk:
            return QApplication.translate("tilauscope_beancave", "free water — storage risk"), THEME['CRITICAL']
        if value > AW_FREE_ABOVE:
            return QApplication.translate("tilauscope_beancave", "free water"), THEME['WARNING']
        return QApplication.translate("tilauscope_beancave", "typical"), None
    return "", None

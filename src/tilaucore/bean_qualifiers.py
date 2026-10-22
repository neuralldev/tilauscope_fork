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
# Tilau 2025-2026

"""Plain-language reading of a green-bean physical measure, shared by both apps.

Turns a raw density / humidity / water-activity figure into the word a roaster
would use for it, plus how much attention it deserves. The bands are NOT defined
here: they are the ones the energy model and the storage advisor already use.
This module only names them.

Words are English source text with their translation context, marked for the
desktop's translation tools; the desktop translates them on display and gives
each level its theme colour, the tablet shows them as they are.
"""

from __future__ import annotations

from tilaucore.bean_energy import AW_BOUND_BELOW, AW_FREE_ABOVE, HUMIDITY_HIGH_PCT, HUMIDITY_LOW_PCT, match_variety_family
from tilaucore.storage_advisor import DEFAULT_THRESHOLDS

DENSITY_LIGHT_BELOW: float = 650.0
DENSITY_DENSE_ABOVE: float = 780.0

# How much attention a reading deserves: None inside the usual range.
WARNING = 'warning'
CRITICAL = 'critical'


def QT_TRANSLATE_NOOP(context: str, text: str) -> tuple[str, str]:  # noqa: N802  (the name the tools look for)
    """Marks a text for the desktop's translation tools; it is translated on display."""
    return context, text


def physical_qualifier(kind: str, value: float) -> tuple[tuple[str, str] | None, str | None]:
    """((context, word), level) for a physical measure — (None, None) if not measured.

    kind is 'density' | 'humidity' | 'aw'.
    """
    if not value or value <= 0.0:
        return None, None
    if kind == 'density':
        if value < DENSITY_LIGHT_BELOW:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "light"), WARNING
        if value > DENSITY_DENSE_ABOVE:
            return QT_TRANSLATE_NOOP("tilauscope_common", "dense"), WARNING
        return QT_TRANSLATE_NOOP("tilauscope_common", "standard"), None
    if kind == 'humidity':
        if value < HUMIDITY_LOW_PCT:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "dry — old crop"), WARNING
        if value > HUMIDITY_HIGH_PCT:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "moist"), WARNING
        return QT_TRANSLATE_NOOP("tilauscope_common", "normal"), None
    if kind == 'aw':
        if value < AW_BOUND_BELOW:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "bound water"), WARNING
        if value >= DEFAULT_THRESHOLDS.risk:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "free water — storage risk"), CRITICAL
        if value > AW_FREE_ABOVE:
            return QT_TRANSLATE_NOOP("tilauscope_beancave", "free water"), WARNING
        return QT_TRANSLATE_NOOP("tilauscope_beancave", "typical"), None
    return None, None


# GreenBean.screen_size key → Artisan (beansize_min, beansize_max), in 1/64".
# Unknown ('' or any other key) writes (0, 0), Artisan's own "not set".
SCREEN_SIZE_RANGES: dict[str, tuple[int, int]] = {
    'large':    (17, 18),
    'medium':   (15, 16),
    'small':    (13, 14),
    'peaberry': (13, 14),
}

# (key, label) of every size class, Unknown first — keys of SCREEN_SIZE_RANGES.
SCREEN_SIZE_OPTIONS: list[tuple[str, tuple[str, str]]] = [
    ('', QT_TRANSLATE_NOOP("tilauscope_beancave", "Unknown")),
    ('large', QT_TRANSLATE_NOOP("tilauscope_beancave", "Large — AA, Supremo, 17/18+")),
    ('medium', QT_TRANSLATE_NOOP("tilauscope_beancave", "Medium — AB, Excelso, 15/16")),
    ('small', QT_TRANSLATE_NOOP("tilauscope_beancave", "Small — 14/15 and below")),
    ('peaberry', QT_TRANSLATE_NOOP("tilauscope_beancave", "Peaberry — PB")),
]


def family_pace(varieties: str | None) -> tuple[str | None, tuple[str, str]]:
    """(family name, (context, words)) of the bean family line; the name is None when not known."""
    family = match_variety_family(varieties)
    if family is None:
        return None, QT_TRANSLATE_NOOP("tilauscope_beancave", "not known — standard pace")
    name, delta = family
    if delta > 0:
        return name, QT_TRANSLATE_NOOP("tilauscope_common", "wants a faster roast")
    if delta < 0:
        return name, QT_TRANSLATE_NOOP("tilauscope_common", "takes a slower roast")
    return name, QT_TRANSLATE_NOOP("tilauscope_common", "keeps the standard pace")

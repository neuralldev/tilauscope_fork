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

"""The summary of one roast, shared by both apps: its facts read from the
profile, and the tiles that show them (roasted weight, roast time, drop
temperature, colour).

Texts are English source text with their translation context, and their
arguments; the desktop translates them on display, the tablet shows them as they
are. A tile's sub line is a list of such parts, joined by " · ".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from tilaucore.alog_index import _to_grams
from tilaucore.bean_qualifiers import QT_TRANSLATE_NOOP
from tilaucore.roast_colour import AGTRON_SCALES, get_agtron_color

DASH = '—'

Text = tuple[str, str]                  # (context, English source)
Part = tuple[Text, tuple]               # a text and its {0}, {1} arguments


def mss(seconds: float) -> str:
    """m:ss, the way roast times are read."""
    total = int(round(seconds))
    return f'{total // 60}:{total % 60:02d}'


def _number(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(number) or math.isinf(number) else number


@dataclass(frozen=True)
class RoastFacts:
    """What the tiles show about one roast, read from its profile."""
    weight_in_g: float
    weight_out_g: float
    total_s: float          # CHARGE to DROP; 0 when either is unmarked
    development_s: float    # first crack to DROP; 0 when first crack is unmarked
    drop_bt: float
    first_crack_bt: float
    unit: str               # the profile's own, 'C' or 'F'
    ground: float
    whole: float

    @property
    def has_result(self) -> bool:
        """A roasted weight or a colour — what the result form records."""
        return self.weight_out_g > 0 or self.ground > 0 or self.whole > 0


def roast_facts(profile: Mapping) -> RoastFacts:
    computed = profile.get('computed')
    if not isinstance(computed, dict):
        computed = {}
    drop_s = _number(computed.get('DROP_time')) or _number(computed.get('totaltime'))
    first_crack_s = _number(computed.get('FCs_time'))
    weight = profile.get('weight')
    return RoastFacts(
        weight_in_g=_to_grams(weight, 0),
        weight_out_g=_to_grams(weight, 1),
        total_s=drop_s,
        development_s=drop_s - first_crack_s if 0 < first_crack_s < drop_s else 0.0,
        drop_bt=_number(computed.get('DROP_BT')),
        first_crack_bt=_number(computed.get('FCs_BT')),
        unit='F' if str(profile.get('mode') or 'C').upper() == 'F' else 'C',
        ground=_number(profile.get('ground_color')),
        whole=_number(profile.get('whole_color')),
    )


def colour_category(value: float) -> str:
    """The roast level a colour reading falls in, or '' outside the scale."""
    for scale in AGTRON_SCALES:
        if scale.agtron_range.min_value <= value <= scale.agtron_range.max_value:
            return scale.name
    return ''


@dataclass(frozen=True)
class Tile:
    caption: Text
    value: str = DASH
    sub: tuple[Part, ...] = ()
    swatch: str = ''                # the colour of the dot beside the value, or none
    swatch_filled: bool = True      # a hollow ring (whole bean) instead of a filled dot
    cost: float | None = None       # roast cost, in the purchase currency, when the price is known
    cost_per_roasted_kg: float | None = None


_ROASTED_WEIGHT = QT_TRANSLATE_NOOP('tilauscope_common', 'Roasted weight')
_ROAST_TIME = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Roast time')
_DROP_TEMPERATURE = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Drop temperature')
_COLOUR = QT_TRANSLATE_NOOP('tilauscope_common', 'Colour')
_NOT_RECORDED = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Not recorded')
_LOSS_FROM = QT_TRANSLATE_NOOP('tilauscope_beancave', '−{0} % from {1} g')
_DEVELOPMENT = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Development {0}')
_FIRST_CRACK_AT = QT_TRANSLATE_NOOP('tilauscope_beancave', 'First crack at {0}')
_GROUND_LEVEL = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Ground · {0}')
_GROUND = QT_TRANSLATE_NOOP('Label', 'Ground')
_WHOLE_LEVEL = QT_TRANSLATE_NOOP('tilauscope_beancave', 'Whole bean · {0}')
_WHOLE = QT_TRANSLATE_NOOP('tilauscope_common', 'Whole bean')
CAPTIONS: tuple[Text, ...] = (_ROASTED_WEIGHT, _ROAST_TIME, _DROP_TEMPERATURE, _COLOUR)


def _not_recorded(caption: Text) -> Tile:
    return Tile(caption, DASH, ((_NOT_RECORDED, ()),))


def _degrees(value: float, unit: str) -> str:
    return f'{value:.0f} °{unit}'


def roast_tiles(facts: RoastFacts | None, price_per_kg: float = 0.0) -> list[Tile]:
    """Roasted weight, roast time, drop temperature and colour — each with what it means.

    Without facts (the roast is still loading, or could not be read) every tile
    keeps its caption and shows a dash, so nothing moves when the figures land.
    A colour names its roast level, ground or whole bean alike.
    """
    if facts is None:
        return [Tile(caption) for caption in CAPTIONS]

    if facts.weight_out_g > 0:
        sub: tuple[Part, ...] = ()
        cost = per_kg = None
        if facts.weight_in_g > 0:
            loss = max(0.0, (facts.weight_in_g - facts.weight_out_g) / facts.weight_in_g * 100.0)
            sub = ((_LOSS_FROM, (f'{loss:.0f}', f'{facts.weight_in_g:.0f}')),)
            if price_per_kg > 0:
                cost = facts.weight_in_g / 1000.0 * price_per_kg
                per_kg = cost / (facts.weight_out_g / 1000.0)
        weight = Tile(_ROASTED_WEIGHT, f'{facts.weight_out_g:.0f} g', sub, cost=cost, cost_per_roasted_kg=per_kg)
    else:
        weight = _not_recorded(_ROASTED_WEIGHT)

    if facts.total_s > 0:
        sub = ((_DEVELOPMENT, (mss(facts.development_s),)),) if facts.development_s > 0 else ()
        duration = Tile(_ROAST_TIME, mss(facts.total_s), sub)
    else:
        duration = _not_recorded(_ROAST_TIME)

    if facts.drop_bt > 0:
        sub = (((_FIRST_CRACK_AT, (_degrees(facts.first_crack_bt, facts.unit),)),)
               if facts.first_crack_bt > 0 else ())
        drop = Tile(_DROP_TEMPERATURE, _degrees(facts.drop_bt, facts.unit), sub)
    else:
        drop = _not_recorded(_DROP_TEMPERATURE)

    if facts.ground > 0:
        category = colour_category(facts.ground)
        sub = ((_GROUND_LEVEL, (category,)),) if category else ((_GROUND, ()),)
        colour = Tile(_COLOUR, f'{facts.ground:.0f}', sub, get_agtron_color(facts.ground))
    elif facts.whole > 0:
        # A whole bean reads a shade darker than its ground equivalent: hollow dot.
        category = colour_category(facts.whole)
        sub = ((_WHOLE_LEVEL, (category,)),) if category else ((_WHOLE, ()),)
        colour = Tile(_COLOUR, f'{facts.whole:.0f}', sub, get_agtron_color(facts.whole), swatch_filled=False)
    else:
        colour = _not_recorded(_COLOUR)
    return [weight, duration, drop, colour]


def english(part: Part) -> str:
    """A text part as the tablet shows it."""
    return part[0][1].format(*part[1])


def english_short_date(epoch: int) -> str:
    """'12 Sep': a day as the tablet writes it (the desktop passes its own, in the interface language)."""
    d = datetime.fromtimestamp(epoch)
    return f"{d.day} {d.strftime('%b')}"


def roast_name(epoch: int, batch: str, *, in_sentence: bool = False,
               short_date: Callable[[int], str] = english_short_date) -> str:
    """'12 Sep · #44' — '12 Sep (#44)' inside a sentence — or whichever part is known."""
    when = short_date(epoch) if epoch > 0 else ''
    if when and batch:
        return f"{when} ({batch})" if in_sentence else f"{when} · {batch}"
    return when or batch

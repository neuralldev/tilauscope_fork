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

"""Green coffee records and their files, shared by the desktop and the tablet.

beancave.json, tastings.json and brewlog.json are written and read here, giving
exactly the JSON the desktop wrote with mashumaro: fields in declaration order,
json.dumps defaults. Reading follows mashumaro's rules too: a missing key takes
its default, an unknown key is ignored, a value is converted to the field's type
(1200 → 1200.0 for a float, "2025" → 2025 for an int, even null → "None" for a
text and False for a flag), and a value that cannot be converted fails the whole
file with ValueError.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from enum import Enum
import json
import types
import typing
from typing import Any, TypeVar


@dataclass
class BrewDialIn:
    """One accepted brew dial-in for a bean, keyed by brew method.

    Stores the corrected recipe plus what produced it, so a later brew of the
    same bean reopens on the setting that actually tasted right instead of the
    generic recommendation. One entry per method (latest wins).
    """
    method_id: str = ''
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    # What the engine recommended before the correction. A dial-in is a relative
    # adjustment: storing the base lets the same ratio be re-applied to a different roast of the same bean.
    base_grind_um: int = 0
    base_temp_c: float = 0.0
    base_ratio: float = 0.0       # the N in 1:N before the correction
    dose_g: float = 0.0
    taste: list[str] = field(default_factory=list)   # TasteCode values reported
    diagnosis: str = ''                              # DiagnosisCode value
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    iso_date: str = ''


# One measured extraction, kept for analysis — not for reopening. `dial_ins` above
# answers "what setting should I reopen on"; this append-only journal answers "did the last change do anything" (own file: brewlog.json).
@dataclass
class BrewSample:
    method_id: str = ''
    iso_date: str = ''
    # ── the cause: what was actually brewed ──
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    dose_g: float = 0.0
    # ── what the engine had recommended before any correction ──
    base_grind_um: int = 0
    base_ratio: float = 0.0
    base_temp_c: float = 0.0
    # ── the target: needed to recompute the gap once the engine has moved on ──
    planned_time_s: int = 0
    planned_water_g: float = 0.0
    # ── the consequence ──
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    # The clean filter signal. Total time is mostly the operator's pour
    # schedule; only the final drain reflects the bed, hence the grind. False when
    # no scale was on the line — never estimated, the gap is left visible.
    drawdown_s: int = 0
    drawdown_valid: bool = False
    # Where the two measurements above came from: "scale" (Acaia) or "manual" (machines
    # with an integrated scale no cup fits over) — a later fit must tell the two populations apart.
    measured_source: str = 'scale'
    # ── the context, without which the two above cannot be compared ──
    agtron: float = 0.0
    days_off_roast: int = -1
    espresso_style: str = ''
    # ── the verdict that justified recording this at all ──
    taste: list[str] = field(default_factory=list)
    diagnosis: str = ''


@dataclass
class BrewLog:
    """Journal of measured extractions, keyed by GreenBean.uuid.

    Lives in brewlog.json beside beancave.json. Its absence is a normal state:
    nothing depends on it to brew.
    """
    version: int = 1
    entries: dict[str, list[BrewSample]] = field(default_factory=dict)


@dataclass
class RoastTasting:
    """What the operator thought of one roast once rested; keyed by its Artisan roastUUID."""
    bean_uuid: str = ''
    iso_date: str = ''
    verdict: str = ''       # '' | 'yes' | 'almost' | 'no'
    defects: list[str] = field(default_factory=list)   # keys of tasting_log.DEFECT_CHANGES
    notes: str = ''


@dataclass
class TastingLog:
    """Tastings of roasts, in tastings.json beside beancave.json."""
    version: int = 1
    entries: dict[str, RoastTasting] = field(default_factory=dict)


@dataclass
class GreenBean:
    name: str = ''
    farm: str = ''
    country: str = ''
    supplier: str = ''
    category: str = ''
    process: str = ''
    crop: int = 0
    density: float = 0.0
    last_humidity: float = 0.0
    water_activity: float = 0.0
    altitude: int = 0
    species: str = ""
    varieties: str = ""
    weight_left: float = 0.0 # input green beans left in stock
    flavour_notes: str = ''
    sca: float = 0.0
    count: int = 0
    weight: float = 0.0 # calculation of total weight roasted from alogs
    # --- Blend Fields ---
    is_blend: bool = False
    bean1_ratio: float = 100.0
    bean2_name: str = ''
    bean2_ratio: float = 0.0
    bean3_name: str = ''
    bean3_ratio: float = 0.0
    blend_notes: str = ''
    tips: str = ''
    # Sack identifiers attached to this bean (labelled bags). Fully
    # optional: an empty list is a normal, permanent state — nothing depends
    # on a sack being registered. weight_left stays the single global stock.
    sacks: list[str] = field(default_factory=list)
    # Storage conditioning for the water-activity advisor (Stockage tab).
    # Language-neutral key: '' (unknown) | 'vacuum' | 'grainpro' | 'ecotact' | 'bocal' | 'toile'.
    # Sealed conditionings suspend the moisture-drift trend (no air exchange).
    conditioning: str = ''
    # Accepted brew dial-ins, one per brew method (latest wins). Optional and
    # additive: an empty list is the normal state for a bean never brewed with taste feedback.
    dial_ins: list[BrewDialIn] = field(default_factory=list)
    # Size class key of SCREEN_SIZE_RANGES; '' = unknown.
    screen_size: str = ''
    # Purchase price per kg of green, in the system currency; 0 = unknown.
    price_per_kg: float = 0.0
    uuid:str = ''
    # roastUUID of the roast the operator marked as this crop's reference; '' = none.
    reference_roast_uuid: str = ''


@dataclass
class ReferenceProfile:
    title: str =''
    count: int = 0
    avg_drop_bt: float = 0.0
    avg_weight_loss : float = 0.0
    avg_roast_color : float = 0.0
    avg_total_time_min : float = 0.0
    avg_dtr_pct : float = 0.0


@dataclass
class BeanCaveContainer:
    green_beans: list[GreenBean] = field(default_factory=list)
    reference_profiles: list[ReferenceProfile] = field(default_factory=list)


T = TypeVar('T')
_SCALARS = (str, int, float, bool)


def _convert(kind: Any, value: Any) -> Any:
    if kind in _SCALARS:
        return kind(value)
    if is_dataclass(kind):
        return from_dict(kind, value)
    if isinstance(kind, type) and issubclass(kind, Enum): # by value, as written in the file
        return kind(value)
    origin, args = typing.get_origin(kind), typing.get_args(kind)
    if origin in (typing.Union, types.UnionType) and type(None) in args: # X | None
        if value is None:
            return None
        return _convert(next(a for a in args if a is not type(None)), value)
    if origin is list:
        return [_convert(args[0], item) for item in value]
    if origin is dict:
        return {_convert(args[0], key): _convert(args[1], item) for key, item in value.items()}
    raise TypeError(f'no reader for {kind!r}')


def from_dict(kind: type[T], data: dict) -> T:
    """A record from its dict: missing keys take their default, unknown keys are ignored."""
    if not isinstance(data, dict):
        raise ValueError(f'{kind.__name__} needs an object')
    hints = typing.get_type_hints(kind)
    values = {}
    for item in fields(kind):
        if item.name in data:
            try:
                values[item.name] = _convert(hints[item.name], data[item.name])
            except (TypeError, AttributeError) as error: # int(None), a list that is not one…
                raise ValueError(f'{kind.__name__}.{item.name}: {error}') from error
        elif item.default is MISSING and item.default_factory is MISSING:
            raise ValueError(f'{kind.__name__}.{item.name} is missing')
    return kind(**values)


def to_dict(record: Any) -> dict:
    return asdict(record)


def from_json(kind: type[T], text: str) -> T:
    return from_dict(kind, json.loads(text))


def to_json(record: Any) -> str:
    """The file text, as the desktop always wrote it."""
    return json.dumps(asdict(record))

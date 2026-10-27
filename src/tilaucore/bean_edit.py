# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""How a green coffee record is edited, zone by zone, shared by both apps: the
fields of each zone, their limits, the fields a new coffee needs, and how the
entered values become the record (`apply`)."""

from __future__ import annotations

from typing import Any

from tilaucore.beans import GreenBean

ZONES: dict[str, tuple[str, ...]] = {
    'essentials': ('name', 'country', 'crop', 'weight_left'),
    'provenance': ('farm', 'supplier', 'altitude', 'price_per_kg'),
    'characteristics': ('is_blend', 'bean1_ratio', 'bean2_name', 'bean2_ratio', 'bean3_name', 'bean3_ratio',
                        'category', 'process', 'species', 'varieties', 'density', 'last_humidity',
                        'water_activity', 'screen_size'),
    'sensory': ('sca', 'flavour_notes', 'tips'),
}

# Number fields: (lowest, highest, decimals), as the editors' spin boxes hold them.
NUMBERS: dict[str, tuple[float, float, int]] = {
    'crop': (0, 2100, 0),
    'weight_left': (0.0, 100000.0, 0),
    'altitude': (0, 3000, 0),
    'price_per_kg': (0.0, 10_000_000.0, 2),  # wide enough for JPY and KRW
    'bean1_ratio': (0.0, 100.0, 0),
    'bean2_ratio': (0.0, 100.0, 0),
    'bean3_ratio': (0.0, 100.0, 0),
    'density': (0.0, 800.0, 0),
    'last_humidity': (0.0, 15.0, 1),
    'water_activity': (0.0, 2.0, 2),
    'sca': (0.0, 100.0, 1),
}

# A new coffee is created once these are filled.
REQUIRED_TO_CREATE: tuple[str, ...] = ('name', 'country', 'category', 'process', 'species', 'varieties')


def missing_to_create(values: dict[str, Any]) -> list[str]:
    """The required fields still empty in `values`."""
    return [key for key in REQUIRED_TO_CREATE if not str(values.get(key) or '').strip()]


def apply(bean: GreenBean, zone: str, values: dict[str, Any], countries: list[str]) -> None:
    """Writes the values of one zone ('all' for every zone) into `bean`, or ValueError.

    Text is stripped; numbers keep their editor's limits and decimals. A country the
    closed list cannot show reads blank: left blank, the record keeps it. A single
    origin drops the blend components.
    """
    zones = list(ZONES) if zone == 'all' else [zone]
    if any(z not in ZONES for z in zones):
        raise ValueError(f"Unknown zone {zone!r}")
    for z in zones:
        for key in ZONES[z]:
            if key not in values:
                raise ValueError(f"Missing field {key!r}")
    if 'essentials' in zones and not str(values['name']).strip():
        raise ValueError("The bean needs a name.")
    for z in zones:
        for key in ZONES[z]:
            value = values[key]
            if key == 'is_blend':
                bean.is_blend = bool(value)
            elif key in NUMBERS:
                low, high, decimals = NUMBERS[key]
                number = float(value or 0)
                if not low <= number <= high:
                    raise ValueError(f"{key} is between {low:g} and {high:g}")
                number = round(number, decimals)
                setattr(bean, key, int(number) if isinstance(getattr(bean, key), int) else float(number))
            elif key == 'country':
                country = str(value or '').strip()
                if country or (bean.country or '') in countries:
                    bean.country = country
            else:
                setattr(bean, key, str(value or '').strip())
    if 'characteristics' in zones and not bean.is_blend:
        bean.bean1_ratio, bean.bean2_name, bean.bean2_ratio, bean.bean3_name, bean.bean3_ratio = 100.0, '', 0.0, '', 0.0

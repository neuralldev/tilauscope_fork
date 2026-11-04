# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""BeanCave alone takes a roast's green weight from stock when Artisan saves it.

Inside TilauScope the stock goes down when Roast Setup starts the roast. Alone,
Artisan records the roast, so the stock goes down when the roast comes back to
the roasts folder: once per roast, and only for a roast linked to a coffee of the
library (one BeanCave prepared). The roasts already there when BeanCave alone
first runs are taken as counted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tilaucore.beans import BeanCaveContainer, GreenBean


@dataclass(frozen=True)
class Taken:
    """One roast taken from one coffee's stock."""
    bean: GreenBean
    grams: float


def _finished(record: Any) -> bool:
    computed = record.computed or {}
    return bool(record.roast_uuid) and not record.simulated and not record.shared \
        and float(computed.get('DROP_time') or 0.0) > 0.0


def take_new_roasts(cave: BeanCaveContainer, records: Iterable[Any]) -> list[Taken]:
    """Take the newly saved roasts from stock; the cave remembers them. Empty on the first run."""
    finished = [r for r in records if _finished(r)]
    if cave.stock_taken_roasts is None:
        cave.stock_taken_roasts = sorted({r.roast_uuid for r in finished})
        return []
    counted = set(cave.stock_taken_roasts)
    beans = {b.uuid: b for b in cave.green_beans if b.uuid}
    taken: list[Taken] = []
    for record in sorted(finished, key=lambda r: r.roastepoch or r.mtime):
        if record.roast_uuid in counted:
            continue
        counted.add(record.roast_uuid)
        bean = beans.get(record.uuid)
        if bean is None or record.weight_in_g <= 0.0:
            continue   # a roast Artisan made without BeanCave: the stock is not touched
        grams = min(float(bean.weight_left or 0.0), float(record.weight_in_g))
        bean.weight_left = max(0.0, float(bean.weight_left or 0.0) - float(record.weight_in_g))
        taken.append(Taken(bean, grams))
    cave.stock_taken_roasts = sorted(counted)
    return taken

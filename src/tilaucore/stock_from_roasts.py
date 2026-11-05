# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""BeanCave alone takes a roast's green weight from stock when Artisan saves it.

Inside TilauScope the stock goes down when Roast Setup starts the roast. Alone,
Artisan records the roast, so the stock goes down when the roast comes back to
the roasts folder: once per roast, and only for a roast linked to a coffee of the
library that Artisan, not TilauScope, recorded; a roast saved with no coffee waits
until it is linked to one. The roasts already there when BeanCave alone
first runs, or when it is pointed at another roasts folder, are taken as counted.
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


def _waits(record: Any) -> bool:
    """A roast Artisan saved that may still be linked to a coffee: it used some green."""
    return not getattr(record, 'recorded_by_tilauscope', False) and record.weight_in_g > 0.0


def take_new_roasts(cave: BeanCaveContainer, records: Iterable[Any], baseline: bool = False) -> list[Taken]:
    """Take the newly saved roasts from stock; the cave remembers them. Empty on the first
    run, and with `baseline` (another roasts folder): those roasts are only counted.

    A roast that arrives with no coffee of the library waits for one: once linked, it is
    taken from that coffee's stock, once.
    """
    finished = [r for r in records if _finished(r)]
    if cave.stock_taken_roasts is None or baseline:
        cave.stock_taken_roasts = sorted(set(cave.stock_taken_roasts or ()) | {r.roast_uuid for r in finished})
        return []
    counted = set(cave.stock_taken_roasts)
    waiting = set(cave.stock_awaiting_link or ()) & {r.roast_uuid for r in finished}
    beans = {b.uuid: b for b in cave.green_beans if b.uuid}
    taken: list[Taken] = []
    for record in sorted(finished, key=lambda r: r.roastepoch or r.mtime):
        if record.roast_uuid in counted and record.roast_uuid not in waiting:
            continue
        new = record.roast_uuid not in counted
        counted.add(record.roast_uuid)
        if getattr(record, 'recorded_by_tilauscope', False):
            waiting.discard(record.roast_uuid)
            continue   # TilauScope took its stock when the roast started
        bean = beans.get(record.uuid)
        if bean is None or record.weight_in_g <= 0.0:
            if new and _waits(record):
                waiting.add(record.roast_uuid)   # a roast Artisan made without BeanCave
            continue
        waiting.discard(record.roast_uuid)
        grams = min(float(bean.weight_left or 0.0), float(record.weight_in_g))
        bean.weight_left = max(0.0, float(bean.weight_left or 0.0) - float(record.weight_in_g))
        taken.append(Taken(bean, grams))
    cave.stock_taken_roasts = sorted(counted)
    cave.stock_awaiting_link = sorted(waiting)
    return taken


def awaiting_link(cave: BeanCaveContainer, records: Iterable[Any]) -> list[Any]:
    """The roasts still waiting for a coffee of the library, oldest first."""
    waiting = set(cave.stock_awaiting_link or ())
    beans = {b.uuid for b in cave.green_beans if b.uuid}
    return sorted((r for r in records if r.roast_uuid in waiting and r.uuid not in beans),
                  key=lambda r: r.roastepoch or r.mtime)

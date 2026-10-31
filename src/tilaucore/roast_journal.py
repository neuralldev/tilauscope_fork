# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A coffee's journal: each roast, what it tried and how it tasted, read from the
roast index and the tastings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tilaucore import tasting_log
from tilaucore.beans import RoastTasting


@dataclass
class JournalRow:
    """One roast of a coffee in its journal."""
    roast_uuid: str
    epoch: int
    weight_in_g: float
    tasting: RoastTasting | None
    tried: dict[str, Any] | None    # the change its plan recorded, with its values
    suggested: str                  # defect whose change the tasting before asked; never recorded as done
    first: bool                     # the coffee's first roast


def journal_rows(bean_uuid: str, records: Iterable[Any],
                 tastings: dict[str, RoastTasting]) -> list[JournalRow]:
    """The coffee's own roasts, latest first. A shared or simulated roast is no trial of it."""
    uuid = (bean_uuid or '').lower()
    if not uuid:
        return []
    roasts = sorted((m for m in records if (m.uuid or '').lower() == uuid
                     and not m.simulated and not getattr(m, 'shared', False)),
                    key=lambda m: m.roastepoch or m.mtime)
    rows: list[JournalRow] = []
    before = None
    for roast in roasts:
        tried = getattr(roast, 'tasting_change', None)
        asked = None
        if not tried and before is not None and not before.exclude_learning:
            asked = tasting_log.next_change(tastings.get(before.roast_uuid))
        rows.append(JournalRow(
            roast_uuid=roast.roast_uuid or '', epoch=int(roast.roastepoch or roast.mtime or 0),
            weight_in_g=float(roast.weight_in_g or 0.0),
            tasting=tastings.get(roast.roast_uuid) if roast.roast_uuid else None,
            tried=tried, suggested=asked[0] if asked else '', first=before is None))
        before = roast
    rows.reverse()
    return rows


def next_step(rows: list[JournalRow]) -> tuple[str, str]:
    """What the latest roast leaves to do: (kind, defect), kind one of 'taste', 'change', 'same', 'tick'."""
    tasting = rows[0].tasting if rows else None
    if tasting is None:
        return 'taste', ''
    change = tasting_log.next_change(tasting)
    if change is not None:
        return 'change', change[0]
    return ('same', '') if tasting.verdict == 'yes' else ('tick', '')

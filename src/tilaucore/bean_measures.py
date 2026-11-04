# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The dated history of a coffee's water activity and moisture.

The record's fields keep the latest value, which is what the plan reads. Here,
each change of value leaves a dated `Measure`, and the roasts already on disk
give the values stamped before this history existed. Nothing judges the
readings: drawing conclusions from them is the operator's.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
import re
from typing import Any, Final

from tilaucore.bean_edit import NUMBERS
from tilaucore.beans import GreenBean, Measure

#: Each kind of measure and the record field holding its latest value.
FIELDS: Final[dict[str, str]] = {'aw': 'water_activity', 'moisture': 'last_humidity'}
#: Water activity has no field in a roast; some carry it in their beans text.
_ROAST_AW: Final[re.Pattern[str]] = re.compile(r'Water activity: ([0-9.]+)')


def series(bean: GreenBean, kind: str) -> list[Measure]:
    """The measures of one kind, oldest first."""
    return sorted((m for m in bean.measures if m.kind == kind), key=lambda m: m.iso_date)


def sync(bean: GreenBean, today: str) -> None:
    """Adds today's value of each field that moved. A second change the same day
    replaces the first: a corrected typo leaves no point."""
    for kind, name in FIELDS.items():
        value = float(getattr(bean, name) or 0.0)
        if value <= 0.0:
            continue
        history = series(bean, kind)
        last = history[-1] if history else None
        if last is None or last.value != value:
            if last is not None and last.iso_date == today:
                last.value = value
            else:
                bean.measures.append(Measure(today, kind, value))


def _stamp(iso_date: str, kind: str, raw: Any) -> Measure | None:
    """A dated value of an old file, or None when it cannot be a measure."""
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return None
    _low, high, decimals = NUMBERS[FIELDS[kind]]
    if not 0.0 < value <= high:
        return None
    return Measure(iso_date, kind, round(value, decimals))


def roast_stamps(records: Iterable[Any]) -> dict[str, list[Measure]]:
    """The usable values stamped in roasts, by bean uuid."""
    stamps: dict[str, list[Measure]] = defaultdict(list)
    for record in records:
        if record.simulated or record.shared or not record.uuid or record.roastepoch <= 0:
            continue
        iso_date = datetime.fromtimestamp(record.roastepoch).date().isoformat()
        aw = _ROAST_AW.search(record.bean_field or '')
        found = [_stamp(iso_date, 'aw', aw.group(1) if aw else None)]
        found.append(_stamp(iso_date, 'moisture', record.computed.get('moisture_greens')))
        stamps[record.uuid] += [stamp for stamp in found if stamp is not None]
    return {uuid: found for uuid, found in stamps.items() if found}


def library_stamps(beans: Iterable[dict[str, Any]], iso_date: str) -> dict[str, list[Measure]]:
    """The usable values of an old copy of the library, by bean uuid. A copy only
    dates a value at the latest: the operator may have set it earlier."""
    stamps: dict[str, list[Measure]] = {}
    for bean in beans:
        found = [_stamp(iso_date, kind, bean.get(name)) for kind, name in FIELDS.items()]
        if bean.get('uuid') and any(found):
            stamps[bean['uuid']] = [stamp for stamp in found if stamp is not None]
    return stamps


def merge_stamps(bean: GreenBean, stamps: list[Measure]) -> bool:
    """Adds the changes of value stamped before the bean's first measure of each
    kind. Safe to repeat: a second pass finds nothing older. True when any was added."""
    added = False
    for kind in FIELDS:
        history = series(bean, kind)
        first_date = history[0].iso_date if history else None
        previous: Measure | None = None
        for stamp in sorted((s for s in stamps if s.kind == kind), key=lambda s: s.iso_date):
            if first_date is not None and stamp.iso_date >= first_date:
                break
            if previous is not None and previous.iso_date == stamp.iso_date:
                previous.value = stamp.value
            elif previous is None or previous.value != stamp.value:
                previous = Measure(stamp.iso_date, kind, stamp.value)
                bean.measures.append(previous)
                added = True
    return added

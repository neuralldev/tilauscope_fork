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
# Tilau 2026

"""The memory of a coffee's last roast, shared by both apps: read from the roast
index and the tastings for the bean sheet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from tilaucore import tasting_log
from tilaucore.beans import RoastTasting
from tilaucore.roast_levels import measured_level


def format_batch_label(prefix: str, nr: int, pos: int | None = None) -> str:
    """Render an Artisan batch identity as a display string.

    Mirrors Artisan's convention: ``{prefix}{nr} (pos)``.
    Returns an empty string when ``nr <= 0`` (batch system inactive or
    not yet assigned — the number is assigned by Artisan at DROP).
    """
    if nr is None or nr <= 0:
        return ""
    label = f"{prefix or ''}{int(nr)}"
    if pos:
        label += f" ({int(pos)})"
    return label


def roast_batch_tag(prefix: str, nr: int) -> str:
    """A roast's batch as BeanCave shows it — "#44" — or "" when it has no batch number."""
    label = format_batch_label((prefix or '').lstrip('#'), nr)
    return f"#{label}" if label else ""

@dataclass
class RoastMemory:
    """The last roast of a coffee, read for the bean sheet."""
    count: int                      # roasts of this coffee on file
    epoch: int                      # when the last one was roasted
    roast_uuid: str
    weight_in_g: float
    level: str | None               # read from the arrival pair, not the colour
    dev_pct: float | None           # development, share of the total time
    loss_pct: float | None
    colour: float | None            # as measured: ground first, else whole
    colour_basis: str               # 'ground' | 'whole' | ''
    rest_days: int                  # calendar days since the roast, -1 unknown
    tasting: RoastTasting | None
    change: tuple[str, str, float] | None   # (defect, lever, delta) for the next roast
    batch: str = ''                 # "#44", or '' when the roast has no batch number
    plan_reference: str = ''        # roastUUID of the reference its plan stood on, '' if none


def last_roast(bean_uuid: str, records: Iterable[Any], tastings: dict[str, RoastTasting],
               mode: str = 'C', ctx_for: Callable[[str], Any] | None = None,
               now: datetime | None = None) -> RoastMemory | None:
    """The memory of this coffee's most recent real roast, or None if it has none.

    `ctx_for` gives the roaster record of the machine a roast ran on, so its level
    is read against that machine's probe offset.
    """
    uuid = (bean_uuid or '').lower()
    if not uuid:
        return None
    roasts = [m for m in records if (m.uuid or '').lower() == uuid and not m.simulated]
    if not roasts:
        return None
    last = max(roasts, key=lambda m: m.roastepoch or m.mtime)
    return _memory_of(last, len(roasts), tastings, mode, ctx_for, now)


def _memory_of(last: Any, count: int, tastings: dict[str, RoastTasting], mode: str,
               ctx_for: Callable[[str], Any] | None, now: datetime | None) -> RoastMemory:
    computed = last.computed or {}
    ctx = ctx_for(last.roastertype) if ctx_for is not None else None
    level, _ = measured_level(computed, last.mode or mode, ctx)
    dev_pct = None
    try:
        fcs_t = float(computed.get('FCs_time') or 0.0)
        drop_t = float(computed.get('DROP_time') or 0.0)
        if 0 < fcs_t < drop_t:
            dev_pct = (drop_t - fcs_t) / drop_t * 100.0
    except (TypeError, ValueError):
        pass
    loss_pct = None
    if last.weight_in_g > 0 and 0 < last.weight_out_g < last.weight_in_g:
        loss_pct = (last.weight_in_g - last.weight_out_g) / last.weight_in_g * 100.0
    colour, basis = None, ''
    if last.ground_color > 0:
        colour, basis = float(last.ground_color), 'ground'
    elif last.whole_color > 0:
        colour, basis = float(last.whole_color), 'whole'
    epoch = int(last.roastepoch or last.mtime or 0)
    today = (now or datetime.now().astimezone()).date()
    rest_days = ((today - datetime.fromtimestamp(epoch, tz=UTC).astimezone().date()).days
                 if epoch > 0 else -1)
    tasting = tastings.get(last.roast_uuid) if last.roast_uuid else None
    batch = roast_batch_tag(getattr(last, 'batch_prefix', ''), int(getattr(last, 'batch_nr', 0) or 0))
    return RoastMemory(
        count=count, epoch=epoch, roast_uuid=last.roast_uuid or '',
        weight_in_g=float(last.weight_in_g or 0.0), level=level, dev_pct=dev_pct,
        loss_pct=loss_pct, colour=colour, colour_basis=basis, rest_days=rest_days,
        tasting=tasting, change=tasting_log.next_change(tasting), batch=batch,
        plan_reference=str(getattr(last, 'plan_reference_uuid', '') or ''))

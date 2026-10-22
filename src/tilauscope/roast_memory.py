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

"""What BeanCave remembers of a coffee's last roast: how it ran, how it tasted,
and the one change the next roast makes.

Builds no widget and reads no file: the caller hands in the roast index records
and the tastings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

# The last-roast memory lives in the library shared with the tablet; the
# reference state and the tasting readiness stay here until the plan moves.
from tilaucore.roast_memory import RoastMemory, _memory_of, last_roast  # noqa: F401
from tilauscope.tilauscope_types import RoastTasting


@dataclass
class ReferenceState:
    """What the sheet says the next plan of a coffee stands on."""
    status: str                     # used | not_tasted_yes | excluded | missing | drift | inherited
    memory: RoastMemory | None      # the reference roast, read like a last roast
    verdict: str = ''               # its verdict, when it is no longer Yes
    crop: int = 0                   # inherited: the previous harvest's year


def reference_state(bean: Any, beans: Iterable[Any], records: Iterable[Any],
                    tastings: dict[str, RoastTasting], last: RoastMemory | None,
                    mode: str = 'C', ctx_for: Callable[[str], Any] | None = None,
                    now: datetime | None = None) -> ReferenceState | None:
    """The coffee's reference roast as the next plan sees it, or None when there is none.

    A crop without a reference and with fewer than two roasts of its own stands on
    the previous harvest's reference, as the plan does.
    """
    records = list(records)
    ref = str(getattr(bean, 'reference_roast_uuid', '') or '')
    if ref:
        return _designated(ref, records, tastings, last, mode, ctx_for, now)
    if last is not None and last.count >= 2:
        return None
    from tilauscope.roast_plan_model import previous_crop  # noqa: PLC0415
    prev = previous_crop(bean, list(beans))
    prev_ref = str(getattr(prev, 'reference_roast_uuid', '') or '') if prev is not None else ''
    if not prev_ref:
        return None
    state = _designated(prev_ref, records, tastings, None, mode, ctx_for, now)
    if state.status != 'used':
        return None
    return ReferenceState('inherited', state.memory, crop=int(prev.crop or 0))


def _designated(ref: str, records: list, tastings: dict[str, RoastTasting],
                last: RoastMemory | None, mode: str, ctx_for: Callable[[str], Any] | None,
                now: datetime | None) -> ReferenceState:
    record = next((m for m in records if m.roast_uuid == ref), None)
    if record is None:
        return ReferenceState('missing', None)
    memory = _memory_of(record, 1, tastings, mode, ctx_for, now)
    tasting = tastings.get(ref)
    if tasting is None or tasting.verdict != 'yes':
        return ReferenceState('not_tasted_yes', memory, verdict=tasting.verdict if tasting else '')
    if getattr(record, "exclude_learning", False) or getattr(record, "simulated", False):
        return ReferenceState('excluded', memory)
    if (last is not None and last.roast_uuid != ref
            and last.plan_reference == ref
            and last.tasting is not None and last.tasting.verdict != 'yes'):
        return ReferenceState('drift', memory)
    return ReferenceState('used', memory)


def ready_to_taste(memory: RoastMemory | None) -> bool:
    """Rested past its degassing and not tasted yet — the same reading the Roasts tab asks on."""
    if memory is None or memory.tasting is not None or not memory.roast_uuid or memory.rest_days < 0:
        return False
    from tilauscope.brew_advisor import RestStatus, rest_window  # noqa: PLC0415
    return rest_window(memory.colour or 0.0, memory.rest_days).status != RestStatus.FRESH

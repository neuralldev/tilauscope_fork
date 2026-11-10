#
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

"""DROP from the drop door's contact, on the main thread (wiki/Drop-Door-Contact-Spec.md).

The probe's poller caches the last door frame; `tick()` runs on each BT sample, hands new
frames to tilaucore.drop_door and marks DROP the way Artisan's own auto DROP does
(autoDropIdx, then markDropSignal), whatever the auto DROP box says. No I/O here.
"""

from __future__ import annotations

import bisect
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from artisanlib.util import stringfromseconds
from tilaucore.drop_door import DoorState, DropDoor

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # pylint: disable=unused-import


class DoorStatus(Enum):
    READY = 'ready'
    OPEN = 'open'
    NOT_WIRED = 'not_wired'
    OFFLINE = 'offline'   # no probe, or the probe is not connected
    UPDATE = 'update'     # the probe's firmware has no door contact


def _probe_link(aw: ApplicationWindow) -> Any:
    return getattr(getattr(aw, 'bleTilauScopeDevice', None), 'bme280', None)


class DropDoorWatch:
    """One per window. A new probe connection object (each ON) starts a new DropDoor."""

    def __init__(self) -> None:
        self._link: Any = None
        self._door = DropDoor()
        self._last_read_at: float | None = None
        self._charged = False
        self.dropped_at: str | None = None   # roast time of the DROP the door marked this session

    def status(self, aw: ApplicationWindow) -> DoorStatus:
        link = _probe_link(aw)
        if link is None or not getattr(link, 'is_connected', False):
            return DoorStatus.OFFLINE
        if link.door_supported is False:
            return DoorStatus.UPDATE
        if link is not self._link:
            return DoorStatus.NOT_WIRED   # not read yet on this connection
        return {DoorState.READY: DoorStatus.READY, DoorState.OPEN: DoorStatus.OPEN,
                DoorState.NOT_WIRED: DoorStatus.NOT_WIRED}[self._door.state]

    def tick(self, aw: ApplicationWindow) -> None:
        link = _probe_link(aw)
        if link is None:
            return
        if link is not self._link:
            self._link, self._door, self._last_read_at, self._charged = link, DropDoor(), None, False
            self.dropped_at = None
        qmc = aw.qmc
        charged = bool(qmc.flagstart) and qmc.timeindex[0] > -1
        dropped = qmc.timeindex[6] > 0
        if charged and not self._charged:
            self._door.charge()
            self.dropped_at = None
        self._charged = charged
        if dropped:
            self._door.stop()   # marked by hand or from the curve first: the door has nothing left to mark
        reading = link.door_reading()
        if reading is None or reading[0] == self._last_read_at:
            return
        self._last_read_at = reading[0]
        opened_at = self._door.read(reading[1], reading[0])
        if opened_at is None or not charged or dropped:
            return
        # the opening on the roast clock (its base runs faster under the simulator)
        now = qmc.timeclock.elapsedMilli()
        at = now - (time.monotonic() - opened_at) * qmc.timeclock.getBase() / 1000.0
        timex = qmc.timex
        if not timex:
            return
        idx = min(bisect.bisect_left(timex, at), len(timex) - 1)
        if idx > 0 and at - timex[idx - 1] < timex[idx] - at:
            idx -= 1
        idx = max(qmc.timeindex[0] + 1, idx)
        qmc.autoDropIdx = idx
        qmc.markDropSignal.emit(False)
        self.dropped_at = stringfromseconds(timex[min(idx, len(timex) - 1)] - timex[qmc.timeindex[0]])

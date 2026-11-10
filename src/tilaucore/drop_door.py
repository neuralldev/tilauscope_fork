# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""DROP from the drop door's contact on the TilauProbe (wiki/Drop-Door-Contact-Spec.md).

The door is never opened during a roast (the beans would fall out): the first opening after
CHARGE is the drop. The probe counts the openings and says how long ago the last one was, so
an opening is never lost between two reads or during a BLE dropout, and DROP lands on the
moment the door opened, not on the read that saw it. Pure: the app reads the probe, gives the
frames and its clock, and marks the milestone.
"""

from __future__ import annotations

import struct
from enum import Enum
from typing import Final, NamedTuple

# Frame, 12 bytes, the probe's usual framing:
#   [0:2]  header      uint16  0x5555
#   [2]    open        uint8   0 closed, 1 open
#   [3:5]  open_count  uint16  openings since the probe started
#   [5:9]  since_ms    uint32  ms since the last opening, 0xFFFFFFFF = none yet
#   [9]    checksum    uint8   sum of [2:9] & 0xFF
#   [10:12] footer     uint16  0xAAAA
_FRAME: Final = struct.Struct("<HBHIBH")
FRAME_SIZE: Final[int] = _FRAME.size
_NEVER: Final[int] = 0xFFFFFFFF


class DoorFrame(NamedTuple):
    open: bool
    open_count: int
    since_open_ms: int | None  # None: no opening since the probe started


def parse_frame(payload: bytes | bytearray) -> DoorFrame | None:
    """The door frame, else None (short, bad framing or bad checksum)."""
    if len(payload) < FRAME_SIZE:
        return None
    header, state, count, since, checksum, footer = _FRAME.unpack(bytes(payload[:FRAME_SIZE]))
    if header != 0x5555 or footer != 0xAAAA or checksum != sum(payload[2:9]) & 0xFF or state > 1:
        return None
    return DoorFrame(state == 1, count, None if since == _NEVER else since)


def build_frame(frame: DoorFrame) -> bytes:
    """The bytes the probe sends for `frame` (the simulator and the tests)."""
    since = _NEVER if frame.since_open_ms is None else frame.since_open_ms
    body = struct.pack("<BHI", int(frame.open), frame.open_count & 0xFFFF, since & _NEVER)
    return struct.pack("<H", 0x5555) + body + struct.pack("<BH", sum(body) & 0xFF, 0xAAAA)


class DoorState(Enum):
    READY = "ready"          # read closed: an opening after CHARGE is the drop
    OPEN = "open"
    NOT_WIRED = "not_wired"  # never read closed: nothing plugged in, or the cable is cut


class DropDoor:
    """The contact's state over one app session.

    Armed by the first frame that reads closed (a contact that is not there reads open, so it
    never arms). Stays armed through BLE dropouts: the probe's count says what happened meanwhile.
    A count lower than the last one means the probe restarted: disarmed until it reads closed again.
    CHARGE takes the count as the roast's reference, so the previous roast's drop never counts.
    """

    def __init__(self) -> None:
        self.armed = False
        self._last_count: int | None = None
        self._last_open = True
        self._reference: int | None = None

    @property
    def state(self) -> DoorState:
        if not self.armed:
            return DoorState.NOT_WIRED
        return DoorState.OPEN if self._last_open else DoorState.READY

    def read(self, frame: DoorFrame, read_at_s: float) -> float | None:
        """A fresh frame, read at `read_at_s`: when the door opened on that clock if this is the
        roast's drop (once per roast), else None."""
        if self._last_count is not None and frame.open_count < self._last_count:
            self.armed = False
            self._reference = None
        self._last_count = frame.open_count
        self._last_open = frame.open
        if not frame.open:
            self.armed = True
        if self._reference is None or frame.open_count <= self._reference or frame.since_open_ms is None:
            return None
        self._reference = None
        return read_at_s - frame.since_open_ms / 1000.0

    def charge(self) -> bool:
        """CHARGE was marked: the openings from now on are this roast's. True when the contact counts."""
        self._reference = self._last_count if self.armed else None
        return self._reference is not None

    def stop(self) -> None:
        """The roast ended without the door's DROP (marked by hand, from the curve, or abandoned)."""
        self._reference = None

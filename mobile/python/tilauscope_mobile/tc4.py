# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Offline decoder for TD5325A TC4 BLE captures after CHAN;1200.

No BLE connection or initialization: connecting this controller can energize
outputs. A hardware driver requires the verified burner-off handshake first.
Field mapping is based on src/tilauscope/tc4ble.py; no desktop module is imported.
"""

from dataclasses import dataclass

from .session import Reading, finite


@dataclass(frozen=True)
class TC4Frame:
    reading: Reading
    ambient_c: float
    burner_echo: float | None
    airflow_echo: float | None


def decode(line: bytes) -> TC4Frame:
    fields = line.decode("ascii").strip().split(",")
    if len(fields) < 3:
        raise ValueError("Incomplete TC4 frame")
    ambient, et, bt = (float(value) for value in fields[:3])
    if not finite(ambient):
        raise ValueError("Invalid ambient temperature")

    def echo(index: int) -> float | None:
        if len(fields) <= index:
            return None
        try:
            value = float(fields[index])
        except ValueError:
            return None
        return value if finite(value) and 0 <= value <= 100 else None

    return TC4Frame(Reading(bt, None if et == -1 else et), ambient, echo(3), echo(4))


class TC4Decoder:
    """CRLF framing for fragmented notifications, with stale-callback rejection."""

    MAX_LINE_BYTES = 4096

    def __init__(self) -> None:
        self.generation = 0
        self._buffer = bytearray()

    def reset(self) -> int:
        self.generation += 1
        self._buffer.clear()
        return self.generation

    def feed(self, data: bytes, *, generation: int) -> list[TC4Frame]:
        if generation != self.generation:
            return []
        # Bound both incomplete lines and incoming batches before allocating.
        if len(self._buffer) + len(data) > self.MAX_LINE_BYTES:
            self._buffer.clear()
            raise ValueError("TC4 receive buffer limit exceeded")
        self._buffer.extend(data)
        frames = []
        while b"\r\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\r\n")
            self._buffer = bytearray(rest)
            try:
                frames.append(decode(bytes(line)))
            except (ValueError, UnicodeError):
                # Boot/status lines and malformed measurements are not telemetry.
                continue
        return frames

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
# TiLau 2026

"""Bookoo Themis / Mini scale driver.

Protocol: https://github.com/BooKooCode/OpenSource (bookoo_mini_scale/protocols.md).
The scale streams 20-byte weight frames (~10 Hz) and has no stable flag.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce
from typing import Final, override

from tilauscope.scales import BOOKOO_SERVICE_UUID
from tilauscope.scales.base import ScaleBLE

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")


class BookooUUID(StrEnum):
    WEIGHT_NOTIFY = "0000ff11-0000-1000-8000-00805f9b34fb"
    COMMAND_WRITE = "0000ff12-0000-1000-8000-00805f9b34fb"


FRAME_LENGTH: Final[int] = 20
WEIGHT_HEADER: Final[bytes] = b"\x03\x0b"
COMMAND_HEADER: Final[bytes] = b"\x03\x0a"
SIGN_NEGATIVE: Final[int] = 0x2D  # '-'
SIGN_POSITIVE: Final[int] = 0x2B  # '+'

CMD_TARE: Final[int] = 0x01
CMD_TIMER_START: Final[int] = 0x04
CMD_TIMER_STOP: Final[int] = 0x05
CMD_TIMER_RESET: Final[int] = 0x06


@dataclass(frozen=True)
class BookooFrame:
    weight_g: float
    battery: int
    sign_byte: int


def _xor(data: bytes) -> int:
    return reduce(lambda a, b: a ^ b, data, 0)


class BookooProtocol:
    """Frame parsing and command building, no Qt / BLE."""

    @staticmethod
    def parse(data: bytes) -> BookooFrame | str:
        """Return the decoded frame, or the reject reason ('length', 'header', 'checksum')."""
        if len(data) != FRAME_LENGTH:
            return "length"
        if data[:2] != WEIGHT_HEADER:
            return "header"
        if _xor(data[:19]) != data[19]:
            return "checksum"
        sign_byte = data[6]
        raw = int.from_bytes(data[7:10], "big")
        weight = raw / 100.0
        if sign_byte == SIGN_NEGATIVE:
            weight = -weight
        return BookooFrame(weight, data[13], sign_byte)

    @staticmethod
    def command(cmd: int, d1: int = 0, d2: int = 0) -> bytes:
        body = COMMAND_HEADER + bytes((cmd, d1, d2))
        return body + bytes((_xor(body),))

    @classmethod
    def tare(cls) -> bytes:
        return cls.command(CMD_TARE)

    @classmethod
    def timer_start(cls) -> bytes:
        return cls.command(CMD_TIMER_START)

    @classmethod
    def timer_stop(cls) -> bytes:
        return cls.command(CMD_TIMER_STOP)

    @classmethod
    def timer_reset(cls) -> bytes:
        return cls.command(CMD_TIMER_RESET)


class BookooBLE(ScaleBLE):
    KEY = "bookoo"

    def __init__(self) -> None:
        super().__init__()
        self._battery: int | None = None
        # service only: the advertised name is not guaranteed; the address pins the device
        self.add_device_description(BOOKOO_SERVICE_UUID)
        self.add_notify(BookooUUID.WEIGHT_NOTIFY, self.notify_callback)
        self.add_write(BOOKOO_SERVICE_UUID, BookooUUID.COMMAND_WRITE)

    @override
    def on_connect(self) -> None:
        self._battery = None
        super().on_connect()

    def notify_callback(self, _sender: object, data: bytearray) -> None:
        raw = bytes(data)
        try:
            self.diag.frame(raw)
            frame = BookooProtocol.parse(raw)
            if isinstance(frame, str):
                self.diag.reject(frame, raw)
                return
            if frame.sign_byte not in (SIGN_NEGATIVE, SIGN_POSITIVE):
                self.diag.once("sign", "unexpected sign byte 0x%02x", frame.sign_byte)
            self.weight_changed_signal.emit(frame.weight_g, False)
            if frame.battery != self._battery:
                self._battery = frame.battery
                self.diag.once("battery", "battery %d %%", frame.battery)
                self.battery_changed_signal.emit(frame.battery)
        except Exception:  # pylint: disable=broad-except
            self.diag.reject("exception", raw)

    @override
    def send_tare(self) -> None:
        self.send_command("tare", BookooProtocol.tare())

    @override
    def send_start_timer(self) -> None:
        self.send_command("timer_start", BookooProtocol.timer_start())

    @override
    def send_stop_timer(self) -> None:
        self.send_command("timer_stop", BookooProtocol.timer_stop())

    @override
    def send_reset_timer(self) -> None:
        self.send_command("timer_reset", BookooProtocol.timer_reset())

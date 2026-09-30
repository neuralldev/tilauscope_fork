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

"""Decent Scale Bluetooth driver.

Protocol: https://decentespresso.com/decentscale_api

- DecentProtocol: pure frame parser and command builders (no Qt, no BLE).
- DecentBLE: ClientBLE transport registered in tilauscope.scales.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, override, TYPE_CHECKING

if TYPE_CHECKING:
    from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import

from tilauscope.scales import DECENT_SERVICE_UUID
from tilauscope.scales.base import ScaleBLE

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")


class DecentUUID(StrEnum):
    NOTIFY = "0000fff4-0000-1000-8000-00805f9b34fb"
    WRITE = "000036f5-0000-1000-8000-00805f9b34fb"


HEADER: Final[int] = 0x03
TYPE_WEIGHT_STABLE: Final[int] = 0xCE
TYPE_WEIGHT_CHANGING: Final[int] = 0xCA
TYPE_BUTTON: Final[int] = 0xAA
LENGTHS: Final[tuple[int, ...]] = (7, 10)  # firmware <= 1.1, firmware >= 1.2 (timestamp)

CMD_TARE: Final[int] = 0x0F
CMD_TIMER: Final[int] = 0x0B
CMD_LED_HEARTBEAT: Final[int] = 0x0A
TIMER_STOP: Final[int] = 0x00
TIMER_RESET: Final[int] = 0x02
TIMER_START: Final[int] = 0x03


@dataclass(frozen=True)
class DecentFrame:
    kind: str  # 'weight' or 'button'
    weight_g: float = 0.0
    stable: bool = False
    button: int = 0
    press: int = 0


class DecentProtocol:
    """Pure Decent Scale frame codec."""

    @staticmethod
    def checksum(data: bytes) -> int:
        """XOR of all bytes."""
        x = 0
        for b in data:
            x ^= b
        return x

    @staticmethod
    def _command(cmd: int, b2: int = 0, b3: int = 0, b4: int = 0, b5: int = 0) -> bytes:
        body = bytes([HEADER, cmd, b2, b3, b4, b5])
        return body + bytes([DecentProtocol.checksum(body)])

    @staticmethod
    def tare() -> bytes:
        return DecentProtocol._command(CMD_TARE)

    @staticmethod
    def timer_start() -> bytes:
        return DecentProtocol._command(CMD_TIMER, TIMER_START)

    @staticmethod
    def timer_stop() -> bytes:
        return DecentProtocol._command(CMD_TIMER, TIMER_STOP)

    @staticmethod
    def timer_reset() -> bytes:
        return DecentProtocol._command(CMD_TIMER, TIMER_RESET)

    @staticmethod
    def heartbeat() -> bytes:
        return DecentProtocol._command(CMD_LED_HEARTBEAT, 0x03, 0xFF, 0xFF)

    @staticmethod
    def parse(data: bytes) -> DecentFrame | str:
        """Return the decoded frame, or the reject reason."""
        if len(data) not in LENGTHS:
            return "length"
        if data[0] != HEADER:
            return "header"
        if DecentProtocol.checksum(data[:-1]) != data[-1]:
            return "checksum"
        kind = data[1]
        if kind in (TYPE_WEIGHT_STABLE, TYPE_WEIGHT_CHANGING):
            raw = int.from_bytes(data[2:4], "big", signed=True)
            return DecentFrame("weight", weight_g=raw / 10.0, stable=kind == TYPE_WEIGHT_STABLE)
        if kind == TYPE_BUTTON:
            return DecentFrame("button", button=data[2], press=data[3])
        return "unknown type"


HEARTBEAT: Final[bytes] = DecentProtocol.heartbeat()


class DecentBLE(ScaleBLE):
    KEY = "decent"

    def __init__(self) -> None:
        super().__init__()
        self.add_device_description(DECENT_SERVICE_UUID, "Decent Scale")
        self.add_notify(DecentUUID.NOTIFY, self.notify_callback)
        self.add_write(DECENT_SERVICE_UUID, DecentUUID.WRITE)
        self.set_heartbeat(3)  # must be set before start()

    def notify_callback(self, _sender: 'BleakGATTCharacteristic', data: bytearray) -> None:
        raw = bytes(data)
        try:
            self.diag.frame(raw)
            frame = DecentProtocol.parse(raw)
            if isinstance(frame, str):
                self.diag.reject(frame, raw)
                return
            self.diag.once("variant", "format %d bytes", len(raw))
            if frame.kind == "weight":
                self.weight_changed_signal.emit(frame.weight_g, frame.stable)
            else:
                # Tare button number is not documented: log only.
                self.diag.once(f"button{frame.button}{frame.press}", "button %d press %d",
                               frame.button, frame.press)
        except Exception:  # pylint: disable=broad-except
            self.diag.reject("exception", raw)

    @override
    def heartbeat(self) -> None:
        # the keep-alive loop also runs while scanning; only a live link gets it
        if self.connected()[0] is not None:
            self.send_command("heartbeat", HEARTBEAT)

    @override
    def send_tare(self) -> None:
        self.send_command("tare", DecentProtocol.tare())

    @override
    def send_start_timer(self) -> None:
        self.send_command("timer start", DecentProtocol.timer_start())

    @override
    def send_stop_timer(self) -> None:
        self.send_command("timer stop", DecentProtocol.timer_stop())

    @override
    def send_reset_timer(self) -> None:
        self.send_command("timer reset", DecentProtocol.timer_reset())

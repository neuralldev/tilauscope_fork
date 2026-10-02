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


"""DiFluid Omni Bluetooth driver (roast colour only).

Protocol: https://github.com/DiFluid/difluid-sdk-demo (docs/protocolOmni.md,
docs/difluid-protocol.md), firmware V016 or later.

- OmniProtocol: pure frame codec and reassembler (no Qt, no BLE).
- OmniBLE: ClientBLE transport.
- DifluidOmni: the ColorMeter facade registered in tilauscope.colormeters.
"""

import logging
import math
import struct
import time
from typing import Final, override, TYPE_CHECKING

from PyQt6.QtCore import pyqtSignal, pyqtSlot

from artisanlib.ble_port import ClientBLE

if TYPE_CHECKING:
    from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import

from tilauscope.colormeters import ColorReading, OMNI_SERVICE_UUID, SampleBasis
from tilauscope.colormeters.base import ColorMeter
from tilauscope.scales.base import FrameDiagnostics

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

OMNI_DIALOG_UUID: Final[str] = "0000aa01-0000-1000-8000-00805f9b34fb"  # clear text channel

PREAMBLE: Final[bytes] = b"\xdf\xdf"
FRAME_OVERHEAD: Final[int] = 6   # preamble(2) + function + command + length + checksum
COMMAND_SPACING_S: Final[float] = 0.05   # same pause as the AirWave between two writes

FUNC_INFO: Final[int] = 0
FUNC_SETTINGS: Final[int] = 1
FUNC_ACTION: Final[int] = 3
CMD_INFO_MODEL: Final[int] = 1
CMD_INFO_FIRMWARE: Final[int] = 2
CMD_SETTINGS_AGTRON_STANDARD: Final[int] = 1
CMD_ACTION_AGTRON_RESULT: Final[int] = 3
AGTRON_STANDARD_SCA: Final[int] = 1
SAMPLE_BEAN: Final[int] = 0
SAMPLE_POWDER: Final[int] = 1


class OmniProtocol:
    """Pure DiFluid frame codec: DF DF | function | command | length | data | checksum.

    A colour result is a 74-byte frame and may span several notifications, so
    feed() keeps the unfinished tail until the rest arrives.
    """

    def __init__(self) -> None:
        self._buf = b""

    def reset(self) -> None:
        self._buf = b""

    @staticmethod
    def build(function: int, command: int, data: bytes = b"") -> bytes:
        body = PREAMBLE + bytes([function, command, len(data)]) + data
        return body + bytes([sum(body) & 0xFF])

    def feed(self, chunk: bytes) -> tuple[list[tuple[int, int, bytes]], list[bytes]]:
        """Add a notification. Returns the complete (function, command, data)
        frames and the byte runs rejected on checksum."""
        buf = self._buf + chunk
        frames: list[tuple[int, int, bytes]] = []
        rejected: list[bytes] = []
        i = buf.find(PREAMBLE)
        while i >= 0:
            if i + 5 > len(buf):
                break                         # header incomplete
            end = i + FRAME_OVERHEAD + buf[i + 4]
            if end > len(buf):
                break                         # frame incomplete, wait for the rest
            frame = buf[i:end]
            if sum(frame[:-1]) & 0xFF == frame[-1]:
                frames.append((frame[2], frame[3], frame[5:-1]))
                i = buf.find(PREAMBLE, end)
            else:
                # not a frame start (or corrupted): resync on the next preamble
                rejected.append(frame)
                i = buf.find(PREAMBLE, i + 2)
        if i >= 0:
            self._buf = buf[i:]
        else:
            # keep a lone trailing 0xDF: it may be the first half of a preamble
            self._buf = buf[-1:] if buf.endswith(PREAMBLE[:1]) else b""
        return frames, rejected

    @staticmethod
    def parse_agtron_result(data: bytes) -> ColorReading | str:
        """Decode struct coffee_agtron_sdk_result_t, or return the reject reason.

        Only the sample type and the average are read; the histogram and the
        variance that follow are ignored.
        """
        if len(data) < 8:
            return "length"
        sample, value = struct.unpack_from("<if", data)
        if not math.isfinite(value) or value <= 0:
            return "value"
        basis = {SAMPLE_BEAN: SampleBasis.WHOLE, SAMPLE_POWDER: SampleBasis.GROUND}.get(sample)
        return ColorReading(round(value, 1), basis)


GET_MODEL: Final[bytes] = OmniProtocol.build(FUNC_INFO, CMD_INFO_MODEL)
GET_FIRMWARE: Final[bytes] = OmniProtocol.build(FUNC_INFO, CMD_INFO_FIRMWARE)
SET_AGTRON_SCA: Final[bytes] = OmniProtocol.build(
    FUNC_SETTINGS, CMD_SETTINGS_AGTRON_STANDARD, bytes([AGTRON_STANDARD_SCA]))


class OmniBLE(ClientBLE):  # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    reading_signal = pyqtSignal(object)   # ColorReading

    KEY: Final[str] = "difluid_omni"

    def __init__(self, address: str) -> None:
        super().__init__()
        self.diag = FrameDiagnostics(self.KEY)
        self._protocol = OmniProtocol()
        self._is_stopping = False
        self.add_device_description(OMNI_SERVICE_UUID, "")
        self.add_notify(OMNI_DIALOG_UUID, self.notify_callback)
        self.add_write(OMNI_SERVICE_UUID, OMNI_DIALOG_UUID)
        self.diag.connecting(address)
        self.start(case_sensitive=False, address=address)

    def send_command(self, label: str, payload: bytes) -> bool:
        ok = self.send(payload)
        self.diag.command(label, payload, ok)
        return ok

    @override
    def on_connect(self) -> None:
        service_uuid, device_name = self.connected()
        self.diag.connected(service_uuid, device_name)
        self._protocol.reset()
        self.connected_signal.emit()

    @override
    def start_notifications(self) -> None:
        # Artisan's BLE layer turns notifications on after on_connect: the
        # commands go out once their replies can be heard.
        super().start_notifications()
        # the colour fields are Agtron SCA: the device scale is set on every connection
        for label, payload in (("get model", GET_MODEL), ("get firmware", GET_FIRMWARE),
                               ("set agtron SCA", SET_AGTRON_SCA)):
            self.send_command(label, payload)
            time.sleep(COMMAND_SPACING_S)

    @override
    def on_disconnect(self) -> None:
        self.diag.disconnected()
        if not self._is_stopping:
            self.disconnected_signal.emit()

    @override
    def stop(self) -> None:
        self._is_stopping = True
        super().stop()

    def notify_callback(self, _sender: 'BleakGATTCharacteristic', data: bytearray) -> None:
        raw = bytes(data)
        try:
            self.diag.frame(raw)
            frames, rejected = self._protocol.feed(raw)
            for bad in rejected:
                self.diag.reject("checksum", bad)
            for function, command, payload in frames:
                self._handle(function, command, payload)
        except Exception:  # pylint: disable=broad-except
            self.diag.reject("exception", raw)

    def _handle(self, function: int, command: int, data: bytes) -> None:
        if (function, command) == (FUNC_ACTION, CMD_ACTION_AGTRON_RESULT):
            reading = OmniProtocol.parse_agtron_result(data)
            if isinstance(reading, str):
                self.diag.reject(f"agtron result {reading}", data)
                return
            _logd.debug("[%s] reading %.1f basis=%s", self.KEY, reading.value, reading.basis)
            self.reading_signal.emit(reading)
        elif (function, command) == (FUNC_SETTINGS, CMD_SETTINGS_AGTRON_STANDARD):
            if data[:1] == bytes([AGTRON_STANDARD_SCA]):
                _logd.debug("[%s] agtron standard SCA confirmed", self.KEY)
            else:
                _log.warning("[%s] agtron standard not SCA (reply %s): readings may be on another scale",
                             self.KEY, data.hex(" "))
        elif function == FUNC_INFO and command in (CMD_INFO_MODEL, CMD_INFO_FIRMWARE):
            _logd.debug("[%s] %s %s (%s)", self.KEY,
                        "model" if command == CMD_INFO_MODEL else "firmware",
                        data.rstrip(b"\x00").decode("ascii", "replace"), data.hex(" "))
        else:
            self.diag.once(f"frame{function}.{command}", "unused frame function=%d command=%d %s",
                           function, command, data.hex(" "))


class DifluidOmni(ColorMeter):
    def __init__(self, address: str) -> None:
        super().__init__()
        self.ble = OmniBLE(address)
        self.ble.connected_signal.connect(self._relay_connected)
        self.ble.disconnected_signal.connect(self._relay_disconnected)
        self.ble.reading_signal.connect(self._relay_reading)

    @pyqtSlot()
    def _relay_connected(self) -> None:
        self.connected_signal.emit()

    @pyqtSlot()
    def _relay_disconnected(self) -> None:
        self.disconnected_signal.emit()

    @pyqtSlot(object)
    def _relay_reading(self, reading: ColorReading) -> None:
        self.reading_signal.emit(reading)

    @override
    def stop(self) -> None:
        self._drop_subscribers()
        self.ble.stop()

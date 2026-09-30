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

"""Shared layers of the TilauScope Bluetooth scale drivers.

- FrameDiagnostics: debug trail of one BLE session (support without the hardware).
- ScaleBLE: ClientBLE base every driver subclasses (protocol + UUIDs only).
- TilauBLEScale: the artisanlib.scale.Scale facade the ScaleManager drives.
"""

import logging
import time
from collections.abc import Callable
from typing import Final, override

from PyQt6.QtCore import pyqtSignal, pyqtSlot

from artisanlib.ble_port import ClientBLE
from artisanlib.scale import Scale

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

FIRST_FRAMES_LOGGED: Final[int] = 20    # raw frames dumped after each connect
REJECT_LOG_PERIOD_S: Final[float] = 5.0  # at most one rejected-frame line per period


class FrameDiagnostics:
    """Debug trail of one scale session: first frames, rejects, commands, summary.

    Called from the BLE thread; it only logs and counts.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        self._reset()

    def _reset(self) -> None:
        self.frames = 0
        self.rejected = 0
        self._hidden_rejects = 0
        self._last_reject_log = 0.0
        self._t0 = time.monotonic()
        self._once: set[str] = set()
        self._heartbeat_logged = False

    def connecting(self, address: str | None) -> None:
        _logd.debug("[%s] connect start address=%s", self.key, address)

    def connected(self, service_uuid: str | None, device_name: str | None) -> None:
        self._reset()
        _logd.debug("[%s] connected service=%s name=%s", self.key, service_uuid, device_name)

    def frame(self, data: bytes) -> None:
        self.frames += 1
        if self.frames <= FIRST_FRAMES_LOGGED:
            _logd.debug("[%s] frame %d len=%d %s", self.key, self.frames, len(data), data.hex(" "))

    def reject(self, reason: str, data: bytes) -> None:
        self.rejected += 1
        now = time.monotonic()
        if now - self._last_reject_log < REJECT_LOG_PERIOD_S:
            self._hidden_rejects += 1
            return
        _logd.debug("[%s] frame rejected (%s) len=%d %s (+%d rejects not logged)",
                    self.key, reason, len(data), data.hex(" "), self._hidden_rejects)
        self._last_reject_log = now
        self._hidden_rejects = 0

    def once(self, tag: str, msg: str, *args: object) -> None:
        """Log msg once per connection (variant detected, first weight…)."""
        if tag in self._once:
            return
        self._once.add(tag)
        _logd.debug("[%s] " + msg, self.key, *args)

    def command(self, label: str, payload: bytes, ok: bool) -> None:
        if label == "heartbeat":
            if ok and self._heartbeat_logged:
                return
            self._heartbeat_logged = True
        _logd.debug("[%s] command %s %s sent=%s", self.key, label, payload.hex(" "), ok)

    def disconnected(self) -> None:
        _logd.debug("[%s] disconnected after %.0f s frames=%d rejected=%d",
                    self.key, time.monotonic() - self._t0, self.frames, self.rejected)


class ScaleBLE(ClientBLE):  # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    """BLE transport of one scale family. Subclasses register their UUIDs,
    parse notifications in notify_callback and build the command frames."""

    weight_changed_signal = pyqtSignal(float, bool)  # g, stable
    battery_changed_signal = pyqtSignal(int)         # %
    tare_pressed_signal = pyqtSignal()
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()

    KEY: str = ""  # registry key, prefixes every log line

    def __init__(self) -> None:
        super().__init__()
        self.diag = FrameDiagnostics(self.KEY)

    def send_command(self, label: str, payload: bytes) -> bool:
        ok = self.send(payload)
        self.diag.command(label, payload, ok)
        return ok

    # to be implemented by subclasses
    def send_tare(self) -> None: ...
    def send_start_timer(self) -> None: ...
    def send_stop_timer(self) -> None: ...
    def send_reset_timer(self) -> None: ...

    @override
    def on_connect(self) -> None:
        service_uuid, device_name = self.connected()
        self.diag.connected(service_uuid, device_name)
        self.connected_signal.emit()

    @override
    def on_disconnect(self) -> None:
        self.diag.disconnected()
        self.disconnected_signal.emit()


class TilauBLEScale(Scale):  # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    """Scale facade over a ScaleBLE transport — the TilauScope twin of AcaiaBluetooth."""

    def __init__(self, model: int, ident: str | None, name: str | None, ble: ScaleBLE,
                 connected_handler: Callable[[], None] | None = None,
                 disconnected_handler: Callable[[], None] | None = None) -> None:
        super().__init__(model, ident, name)
        self.ble = ble
        self.scale_connected = False
        self._connected_handler = connected_handler
        self._disconnected_handler = disconnected_handler
        self._last_sent: tuple[int, bool] | None = None
        ble.weight_changed_signal.connect(self._on_weight)
        ble.tare_pressed_signal.connect(self.tare_pressed_signal)
        ble.battery_changed_signal.connect(self.battery_changed_signal)
        ble.connected_signal.connect(self.on_connect)
        ble.disconnected_signal.connect(self.on_disconnect)

    @override
    def is_connected(self) -> bool:
        return self.scale_connected

    @override
    def connect_scale(self, device_logging: bool) -> None:
        self.ble.setLogging(device_logging)
        self.ble.diag.connecting(self.ident)
        self.ble.start(address=self.ident)

    @override
    def disconnect_scale(self) -> None:
        self.ble.stop()  # releases ClientBLE._running so a later connect is accepted
        self.on_disconnect()  # stop() does not emit it

    @override
    def tare_scale(self) -> None:
        self.ble.send_tare()

    # Starting resets first, as AcaiaBluetooth does: the brew timer starts from zero.
    @override
    def set_timer(self, on: bool) -> None:
        if on:
            self.ble.send_reset_timer()
            self.ble.send_start_timer()
        else:
            self.ble.send_stop_timer()

    # These scales notify ~10 times per second. Re-emitting an unchanged weight
    # would restart the ScaleManager stable timer forever and no stable weight
    # would ever come out: forward only a change of the rounded gram or of stability.
    @pyqtSlot(float, bool)
    def _on_weight(self, weight: float, stable: bool) -> None:
        key = (round(weight), stable)
        if key == self._last_sent:
            return
        if self._last_sent is None:
            self.ble.diag.once("first_weight", "first weight %.2f g stable=%s", weight, stable)
        self._last_sent = key
        self.weight_changed_signal.emit(float(key[0]), stable)

    @pyqtSlot()
    def on_connect(self) -> None:
        self._last_sent = None
        self.scale_connected = True
        if self._connected_handler is not None:
            self._connected_handler()
        self.connected_signal.emit()

    @pyqtSlot()
    def on_disconnect(self) -> None:
        self.scale_connected = False
        if self._disconnected_handler is not None:
            self._disconnected_handler()
        self.disconnected_signal.emit()

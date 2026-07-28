#
# ABOUT
# trp_client — generic TRP (Tilauscope Roaster Protocol) client, one class for
# every roaster controller that speaks the protocol.

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

"""
trp_client.py — transport + protocol client for TRP (Tilauscope Roaster
Protocol, see /TRP/specifications.md), the serial handshake protocol that
lets any roasting controller (Arduino, ESP32, STM32, ...) identify itself
and its host machine without a dedicated Python driver per model.

Design
    * ONE client class for every TRP-speaking controller. There is no
      per-roaster subclass: the controller self-identifies at handshake
      (DEVICE/MANUFACTURER/MODEL/ROASTER_ID/CAPS, spec §4 + §19) and this
      client resolves that identity against RoasterManager's profile
      database. Adding a new roaster model is a data change (roasters.json
      + firmware identity strings), never a new Python module — mirrors
      tilauscope/roasters.py's RoasterContext, which already separates
      "what the machine is" from "what code drives it".
    * Falls back to CAPS-only "generic mode" (spec §19.4) when the
      identity does not resolve to a known profile: no profile-dependent
      feature (thermal indices, RPM mapping, ...) is used, but raw
      GET/SET/STREAM I/O still works against whatever CAPS the controller
      advertised.
    * Required transport is USB CDC serial (spec §2); BLE/TCP/WebSerial are
      optional at the protocol level and are not implemented here — plug a
      different byte-stream source into `_SerialReader`'s role if needed.
    * A dedicated reader thread owns all blocking serial I/O so the Qt
      thread is never blocked on a read() call (mirrors tc4ble.py's
      dedicated-thread-per-transport pattern).
    * The protocol is half-duplex per spec §17 ("every command shall
      receive exactly one acknowledgement"), except while STREAM ON is
      active: DATA lines then arrive unsolicited. This client does not
      distinguish solicited from unsolicited DATA — both surface via
      dataReceived, same as tc4ble's poll-driven sampleReady signal.
"""

from __future__ import annotations

import argparse
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Final, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyserial is required for trp_client") from exc

from tilauscope.roasters import RoasterContext, RoasterManager

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# ── Protocol constants (spec §2, §4) ────────────────────────────────────────
DEFAULT_BAUD: Final[int] = 115200
_LINE_TERM: Final[bytes] = b"\n"
_HELLO: Final[str] = "HELLO TRP/1.0"
_READ_CHUNK: Final[int] = 256
_SERIAL_READ_TIMEOUT_S: Final[float] = 0.2   # bounds the reader thread's poll loop

_FIELD_SPLIT_RE: Final[re.Pattern] = re.compile(r"[;\s]+")
_DOMAINS: Final[set[str]] = {"SERIAL","BLE", "TCP", "WEBSERIAL"}  # valid transport domains

# specification §2: BLE service/characteristic UUIDs for TRP
_TRP_PREFIX = "TRP_DEVICE_" 
_TRP_ADVERTISED_SERVICE = "0006f00d-6000-1000-8000-00805f9b34fb"  # BLE service UUID for TRP (spec §2.3)
_TRP_ADVERTISED_CHARACTERISTIC = "0006beef-60000-1000-8000-00805f9b34fb"  # BLE characteristic UUID for TRP (spec §2.3)
_TRP_ADVERTISED_CHARACTERISTIC_WRITE = "0006feed-6000-1000-8000-00805f9b34fb"  # BLE characteristic UUID for TRP write (spec §2.3)

# specification for TRP broadcast on TCP (spec §2.4)
#todo

def parse_fields(remainder: str) -> dict[str, str]:
    """Parse 'KEY=VALUE KEY=VALUE' or 'KEY=VALUE;KEY=VALUE' into a dict.

    The spec is not fully consistent on the separator (space in §3/§4,
    semicolon in §6/§7/§13) — both are accepted uniformly.
    """
    fields: dict[str, str] = {}
    for token in _FIELD_SPLIT_RE.split(remainder.strip()):
        if not token or "=" not in token:
            continue
        key, _, value = token.partition("=")
        fields[key.strip().upper()] = value.strip()
    return fields


@dataclass(slots=True)
class TRPIdentity:
    """Identity announced by a TRP device at handshake (spec §4, §19.1)."""

    device: str = ""
    manufacturer: str = ""
    model: str = ""
    roaster_id: str = ""
    serial_number: str = ""
    firmware: str = ""
    mcu: str = ""
    caps: frozenset[str] = field(default_factory=frozenset)

    def has_cap(self, name: str) -> bool:
        return name.strip().upper() in self.caps

    @property
    def is_identified(self) -> bool:
        """True once at least the controller DEVICE field was received."""
        return bool(self.device)

    def update_from_info(self, remainder: str) -> None:
        """Merge one 'INFO <remainder>' line's fields into this identity
        (spec §4/§19.1). Called once per INFO line received during handshake;
        fields absent from *remainder* are left untouched."""
        fields = parse_fields(remainder)
        if "DEVICE" in fields:
            self.device = fields["DEVICE"]
        if "MANUFACTURER" in fields:
            self.manufacturer = fields["MANUFACTURER"]
        if "MODEL" in fields:
            self.model = fields["MODEL"]
        if "ROASTER_ID" in fields:
            self.roaster_id = fields["ROASTER_ID"]
        if "SERIAL" in fields:
            self.serial_number = fields["SERIAL"]
        if "FW" in fields:
            self.firmware = fields["FW"]
        if "MCU" in fields:
            self.mcu = fields["MCU"]
        if "CAPS" in fields:
            self.caps = frozenset(
                c.strip().upper() for c in fields["CAPS"].split(",") if c.strip()
            )


def resolve_roaster(identity: "TRPIdentity",
                     roaster_manager: Optional[RoasterManager] = None) -> Optional[RoasterContext]:
    """Resolve a handshake identity to a machine profile (spec §19.2):
    ROASTER_ID exact -> (MANUFACTURER, MODEL) exact -> MODEL-only fuzzy ->
    None (generic mode, spec §19.4). Pure function so both TRPClient (BLE/TCP
    bench use) and comm.py's synchronous serial device (Artisan's shared
    serial port) share one resolution rule instead of duplicating it."""
    rm = roaster_manager or RoasterManager()
    roaster = None
    try:
        if identity.roaster_id:
            roaster = rm.get_by_roaster_id(identity.roaster_id)
        if roaster is None and identity.manufacturer and identity.model:
            roaster = rm.get_by_name(identity.manufacturer, identity.model)
        if roaster is None and identity.model:
            roaster = rm.get_by_display_name(identity.model)
    except FileNotFoundError:
        _logd.warning("TRP: roasters.json not found — staying in generic mode")
        roaster = None

    context = RoasterContext.from_roaster(roaster) if roaster else None
    if context is None:
        _logd.info(
            "TRP: no profile match for DEVICE=%s MANUFACTURER=%s MODEL=%s ROASTER_ID=%s "
            "— generic mode",
            identity.device, identity.manufacturer, identity.model, identity.roaster_id,
        )
    else:
        _logd.info("TRP: resolved profile %s", context.display_name)
    return context

# ─────────────────────────────────────────────────────────────────────────────
# Transport split todo: the serial reader thread is currently embedded in this module, but
# it could be factored out into a separate transport class so
# the TRPClient class can be reused with other transports (BLE, TCP sockets)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# BLE thread — owns all blocking I/O
# ─────────────────────────────────────────────────────────────────────────────
#todo autoscan BLE devices, connect to the one that advertises _TRP_ADVERTISED_SERVICE, and read/write _TRP_ADVERTISED_CHARACTERISTIC. The BLE transport is not implemented yet, but the TRPClient class is designed to be transport-agnostic, so it can be reused with a BLE transport once implemented.

# ─────────────────────────────────────────────────────────────────────────────
# Serial reader thread — owns all blocking I/O
# ─────────────────────────────────────────────────────────────────────────────

class _SerialReader(QThread):
    """Reads LF-terminated lines from an open serial port on its own thread."""

    lineReceived  = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, ser: "serial.Serial") -> None:
        super().__init__()
        self._ser = ser
        self._running = True

    def run(self) -> None:
        buf = bytearray()
        while self._running:
            try:
                chunk = self._ser.read(_READ_CHUNK)
            except Exception as e:  # noqa: BLE001 - port closed/unplugged mid-read
                if self._running:
                    self.errorOccurred.emit(str(e))
                return
            if not chunk:
                continue
            buf.extend(chunk)
            while _LINE_TERM in buf:
                line, _, rest = buf.partition(_LINE_TERM)
                buf = bytearray(rest)
                text = line.decode("utf-8", "ignore").strip("\r")
                if text:
                    self.lineReceived.emit(text)

    def stop(self) -> None:
        self._running = False

# ─────────────────────────────────────────────────────────────────────────────
# TRPClient
# ─────────────────────────────────────────────────────────────────────────────

class TRPClient(QObject):
    """Generic client for any TRP-speaking roaster controller.

    Usage::

        client = TRPClient()
        client.identityReady.connect(on_identity)
        client.dataReceived.connect(on_data)
        client.connect("/dev/tty.usbmodem1101")
        ...
        client.stream_on(250)
    """

    identityReady = pyqtSignal(object)       # TRPIdentity
    stateChanged  = pyqtSignal(str)          # 'connected'|'disconnected'|'error'
    dataReceived  = pyqtSignal(dict)         # GET/GET ALL reply or STREAM push
    eventReceived = pyqtSignal(str, dict)    # EVENT TYPE=<name>, remaining fields
    errorReceived = pyqtSignal(str)          # ERR <reason>
    logReceived   = pyqtSignal(str)          # LOG <message>

    def __init__(self, roaster_manager: Optional[RoasterManager] = None,
                 parent: Optional[QObject] = None,
                 domain: Optional[str] = None) -> None:
        super().__init__(parent)
        self._domain  = domain if domain in _DOMAINS else "SERIAL" # default to SERIAL if not specified or invalid
        self._roaster_manager = roaster_manager or RoasterManager()
        self._ser: Optional["serial.Serial"] = None
        self._reader: Optional[_SerialReader] = None
        self._write_lock = threading.Lock()

        self._identity = TRPIdentity()
        self._roaster_context: Optional[RoasterContext] = None
        self._handshake_pending = False
        self._streaming = False
        self._connected = False

    # ── port discovery (mirrors tc4ble's scan() entry point) ────────────────
    @staticmethod
    def list_ports() -> list[str]:
        """Blocking discovery of candidate serial ports for the config dialog."""
        return [p.device for p in list_ports.comports()]

    # ── connection lifecycle ─────────────────────────────────────────────────
    @pyqtSlot(str, int)
    def connect(self, port: str, baud: int = DEFAULT_BAUD) -> None:
        """Open *port* and start the TRP handshake (spec §4).

        Non-blocking beyond the serial port open itself: the handshake
        completes asynchronously as INFO/OK lines arrive on the reader
        thread, ending in an identityReady + stateChanged('connected') pair
        (or stateChanged('error') if the port fails to open).
        """
        try:
            self._ser = serial.Serial(port, baudrate=baud, timeout=_SERIAL_READ_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            _logd.exception("TRPClient: failed to open %s", port)
            self.stateChanged.emit("error")
            self.errorReceived.emit(str(e))
            return

        self._identity = TRPIdentity()
        self._roaster_context = None
        self._handshake_pending = True
        self._streaming = False

        self._reader = _SerialReader(self._ser)
        self._reader.lineReceived.connect(self._on_line)
        self._reader.errorOccurred.connect(self._on_reader_error)
        self._reader.start()

        self._write(_HELLO)

    @pyqtSlot()
    def disconnect(self) -> None:
        """Close the port and stop the reader thread. Idempotent."""
        self._streaming = False
        if self._reader is not None:
            self._reader.stop()
            self._reader.wait(1000)
            self._reader = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            self._ser = None
        was_connected = self._connected
        self._connected = False
        if was_connected:
            self.stateChanged.emit("disconnected")

    def close(self) -> None:
        """Alias used by the config dialog on teardown (mirrors other devices)."""
        self.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected

    # ── identity / roaster resolution (spec §19.2) ───────────────────────────
    @property
    def identity(self) -> TRPIdentity:
        return self._identity

    @property
    def roaster_context(self) -> Optional[RoasterContext]:
        """The resolved machine profile, or None in generic mode (§19.4)."""
        return self._roaster_context

    @property
    def generic_mode(self) -> bool:
        return self._connected and self._roaster_context is None

    def has_cap(self, name: str) -> bool:
        return self._identity.has_cap(name)

    def _resolve_roaster(self) -> None:
        """Resolution order per spec §19.2 — delegates to the shared
        resolve_roaster() so this client and comm.py's serial device agree."""
        self._roaster_context = resolve_roaster(self._identity, self._roaster_manager)

    # ── high-level commands (spec §5-§14) ────────────────────────────────────
    def ping(self) -> None:
        self._write("PING")

    def get(self, key: str) -> None:
        self._write(f"GET {key.upper()}")

    def get_all(self) -> None:
        self._write("GET ALL")

    def set(self, key: str, value) -> None:
        self._write(f"SET {key.upper()} {value}")

    def cmd(self, name: str) -> None:
        self._write(f"CMD {name.upper()}")

    def stream_on(self, period_ms: int = 250) -> None:
        self._streaming = True
        self._write(f"STREAM ON {int(period_ms)}")

    def stream_off(self) -> None:
        self._streaming = False
        self._write("STREAM OFF")

    def get_config(self) -> None:
        self._write("CONFIG")

    def set_config(self, **kwargs) -> None:
        pairs = ";".join(f"{k.upper()}={v}" for k, v in kwargs.items())
        self._write(f"CONFIG {pairs}")

    def log_on(self) -> None:
        self._write("LOG ON")

    def log_off(self) -> None:
        self._write("LOG OFF")

    def send_raw(self, line: str) -> None:
        """Escape hatch for commands not covered by the helpers above."""
        self._write(line.strip())

    # ── transport write ──────────────────────────────────────────────────────
    def _write(self, line: str) -> None:
        if self._ser is None:
            _logd.warning("TRPClient: send while disconnected: %r", line)
            return
        with self._write_lock:
            try:
                self._ser.write((line + "\n").encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                _logd.exception("TRPClient: write failed")
                self.errorReceived.emit(str(e))
        _logd.debug("TRP TX %r", line)

    # ── line dispatch (spec §3) ───────────────────────────────────────────────
    @pyqtSlot(str)
    def _on_line(self, line: str) -> None:
        _logd.debug("TRP RX %r", line)
        tag, _, remainder = line.partition(" ")
        tag = tag.upper()

        if tag == "INFO":
            self._on_info(remainder)
        elif tag == "OK":
            self._on_ok()
        elif tag == "ERR":
            self.errorReceived.emit(remainder.strip())
        elif tag == "DATA":
            self.dataReceived.emit(parse_fields(remainder))
        elif tag == "EVENT":
            fields = parse_fields(remainder)
            event_type = fields.pop("TYPE", "")
            self.eventReceived.emit(event_type, fields)
        elif tag == "LOG":
            self.logReceived.emit(remainder)
        elif tag == "PONG":
            pass  # liveness only; caller can watch for absence via a timer if needed
        else:
            _logd.debug("TRPClient: unrecognized line %r", line)

    def _on_info(self, remainder: str) -> None:
        self._identity.update_from_info(remainder)

    def _on_ok(self) -> None:
        if not self._handshake_pending:
            return  # OK acknowledging a later SET/CMD — nothing to do here
        self._handshake_pending = False
        self._connected = True
        self._resolve_roaster()
        self.identityReady.emit(self._identity)
        self.stateChanged.emit("connected")

    def _on_reader_error(self, message: str) -> None:
        _logd.error("TRPClient: reader error: %s", message)
        self.errorReceived.emit(message)
        self.disconnect()
        self.stateChanged.emit("error")


# ── standalone validation harness (no Artisan involved) ─────────────────────
def _main() -> None:
    import sys
    from PyQt6.QtCore import QCoreApplication, QTimer

    p = argparse.ArgumentParser(description="TRPClient standalone test")
    p.add_argument("port", nargs="?", help="serial port (omit to list candidates)")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--stream", type=int, help="enable STREAM at this period (ms)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if not args.port:
        print("Available ports:", TRPClient.list_ports())
        return

    app = QCoreApplication(sys.argv)
    client = TRPClient()
    client.identityReady.connect(
        lambda ident: print(f"[identity] {ident} generic={client.generic_mode}")
    )
    client.stateChanged.connect(lambda s: print(f"[state] {s}"))
    client.dataReceived.connect(lambda d: print(f"[data] {d}"))
    client.eventReceived.connect(lambda t, f: print(f"[event] {t} {f}"))
    client.errorReceived.connect(lambda m: print(f"[err] {m}"))
    client.connect(args.port, args.baud)

    if args.stream is not None:
        QTimer.singleShot(1000, lambda: client.stream_on(args.stream))

    def _quit() -> None:
        client.close()
        QTimer.singleShot(250, app.quit)

    QTimer.singleShot(int(args.seconds * 1000), _quit)
    app.exec()


if __name__ == "__main__":
    _main()

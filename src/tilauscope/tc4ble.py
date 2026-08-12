#
# ABOUT
# tc4ble — standalone BLE transport + control for a TC4-over-BLE roaster

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
tilau_tc4ble.py — standalone BLE transport + control for a TC4-over-BLE roaster
(Skywalker V2 / "Cyberroaster", BLE bridge TD5325A), self-contained with its
own asyncio I/O thread; the sampling thread reads via read_latest().

Safety: connecting alone makes the controller assert a default actuator state
that INCLUDES the burner, so OT1,0 is forced first at connect and re-asserted
before every disconnect.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import time                                  # monotonic clock for the RX watchdog
from typing import Optional, Final, Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

try:
    from bleak import BleakClient
except ImportError as exc:  # pragma: no cover
    raise ImportError("bleak is required for tilau_tc4ble") from exc

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# Name prefix advertised by the Skywalker V2 BLE bridge (model number string).
SKYWALKER_PREFIX = "TD5325A"

# ── Protocol constants ──────────────────────────────────────────────────────
FF01_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"   # TC4 telemetry (RX)
FF02_WRITE  = "0000ff02-0000-1000-8000-00805f9b34fb"   # TC4 commands  (TX)

_CMD_TERM  = "\n"          # TC4 commands are LF-terminated
_LINE_TERM = b"\r\n"       # telemetry lines are CRLF-terminated
_CHAN_INIT = "CHAN;1200"   # logical->physical channel map (Artisan default)
_READ_CMD  = "READ"        # one CSV line per poll
_POLL_S    = 1.0           # poll cadence; keep <= qmc sample interval / 2

# CSV field order after CHAN;1200: ambient, ET, BT, <actuator/config echoes...> firmware labels inverted vs physical probes: field[1]=drum(ET), field[2]=bean(BT)
_IDX_AMBIENT     = 0
_IDX_BT          = 2  # physical probe swap: firmware field[2] = bean (BT), field[1] = drum (ET)
_IDX_ET          = 1
_IDX_BURNER_ECHO  = 3      # CSV field that echoes the OT1 (burner) duty  [confirmed]
_IDX_AIRFLOW_ECHO = 4      # CSV field that echoes the OT2 (airflow) duty [confirmed]

_VERIFY_TRIES  = 6         # OT1,0 re-assert attempts at connect before fail-safe
_VERIFY_WAIT_S = 0.4       # settle time between assert and echo verification

_CONNECT_AIRFLOW = 20      # airflow asserted at connect (BLE default is undefined)
_DRUM_DEFAULT    = 80      # drum duty the controller assumes at connect (never echoed)

# ── Link-recovery guard ───────────────────────────────────────
# On a link drop above ~50°C the controller emergency-stops (burner to 0, fans
# on). On reconnect we re-assert airflow/drum and sync burner DOWN to the
# echoed value (0) — heat is never re-applied automatically.
_RX_STALL_S       = 3.0    # no telemetry for this long -> force a clean reconnect
_RX_STALL_CHECK_S = 1.0    # watchdog wake cadence
_RECONNECT_CAP_S  = 2.0    # reconnect backoff ceiling (roast is time-critical)
_GUARD_CMD        = "GUARD"  # intercepted pseudo-command (GUARD,ON/GUARD,OF), never sent to FF02

# TC4 output channels (OTx,<level>). OT4 wired for completeness though seldom used.
OT_BURNER  = 1
OT_AIRFLOW = 2
OT_DRUM    = 3
OT_EXHAUST = 4

# Per-actuator clamp ranges (mirror the Artisan slider min/max).
_CLAMP = {
    OT_BURNER:  (0, 100),
    OT_AIRFLOW: (0, 100),
    OT_DRUM:    (60, 100),
    OT_EXHAUST: (1, 4),
}


class _BleLoop(threading.Thread):
    """Owns a private asyncio loop so BLE I/O never touches the Qt / RT threads."""

    def __init__(self) -> None:
        super().__init__(name="TilauTC4BLE-loop", daemon=True)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            # Drain cancellation before Python finalization; otherwise
            # CoreBluetooth may deliver into callback objects already destroyed.
            pending = list(asyncio.all_tasks(self._loop))
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def submit(self, coro):
        """Schedule a coroutine on the loop from any thread; returns a Future."""
        self._ready.wait()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> bool:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if threading.current_thread() is not self:
            self.join(timeout=3.0)
        return not self.is_alive()


class TilauTC4BLE(QObject):
    """TC4-over-BLE roaster transport with safe burner handling."""

    sampleReady  = pyqtSignal(float, float, float, float, float)  # ambient, BT, ET
    stateChanged = pyqtSignal(str)                  # 'connected'|'disconnected'|'error'
    safetyAlert  = pyqtSignal(str)                  # safety condition identifier
    roastInterrupted = pyqtSignal(str, float, int)  # reason, last_bt, burner_echo
    guardChanged     = pyqtSignal(bool)             # recovery guard armed/disarmed

    def __init__(self, address: str, poll_s: float = _POLL_S,
                 parent: Optional[QObject] = None,
                 is_live: Optional[Callable[[], bool]] = None) -> None:
        super().__init__(parent)
        self._address = address
        self._poll_s = poll_s
        # Predicate telling whether a roast is live (Artisan
        # flagon/flagstart). The recovery protocol only runs if it was live AT
        # THE DROP. Injected to keep tc4ble decoupled from Artisan internals.
        self._is_live: Callable[[], bool] = is_live or (lambda: False)
        self._ble = _BleLoop()
        self._ble.start()
        self._client: Optional[BleakClient] = None
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._latest: Optional[tuple[float, float, float]] = None
        self._mtu = 20
        self._poll_task: Optional[asyncio.Future] = None
        self._connected = False
        self._burner_echo: Optional[int] = None   # last OT1 duty read from field 3
        self._airflow_echo: Optional[int] = None  # last OT2 duty read from field 4
        self._cmd_drum = _DRUM_DEFAULT             # drum has no echo; track commanded
        self._cmd_airflow = _CONNECT_AIRFLOW       # airflow commanded; restored after a drop
        self._cmd_burner = 0                       # last commanded OT1 duty
        self._mismatch = 0                         # consecutive burner overshoot count
        self._closing = False                      # True during an intentional disconnect
        self._connect_task: Optional[asyncio.Future] = None   # in-flight connect, for clean cancel
        # ── link-recovery guard state ( ) ──────────────────────────
        self._guard_armed = True                   # GUARD,OF disarms; armed by default
        self._last_rx = 0.0                        # monotonic ts of last parsed telemetry
        self._restore_pending = False              # was-live captured at the drop
        self._recovering = False                   # a reconnect driver is active (idempotency)
        self._reconnect_task: Optional[asyncio.Future] = None
        self._watchdog_task: Optional[asyncio.Future] = None
        self._epoch = 0                            # connection generation (poll/watchdog lifetime)

    # ── public Qt-thread API ────────────────────────────────────────────────
    @pyqtSlot()
    def connect(self) -> None:
        self._ble.submit(self._connect())

    @pyqtSlot()
    def disconnect(self) -> None:
        self._ble.submit(self._disconnect())

    def read_latest(self) -> Optional[tuple[float, float, float]]:
        """Non-blocking cache read for the sampling thread: (ambient, BT, ET)."""
        with self._lock:
            return self._latest

    # ── fork device contract (Celsius accessors, like the other BLE devices) ─
    def getAmbient(self) -> float:
        latest = self.read_latest()
        return latest[0] if latest else -1

    def getBT(self) -> float:
        latest = self.read_latest()
        return latest[1] if latest else -1

    def getET(self) -> float:
        latest = self.read_latest()
        return latest[2] if latest else -1

    def getBurner(self) -> float:
        # OT1 duty echo (%) for an extra device channel.
        return self._burner_echo if self._burner_echo is not None else -1

    def getAirflow(self) -> float:
        # OT2 duty echo (%) for an extra device channel.
        return self._airflow_echo if self._airflow_echo is not None else -1

    def getDrum(self) -> float:
        # Drum duty is never echoed by READ; report the last commanded value.
        return float(self._cmd_drum)

    def getCmdAirflow(self) -> float:
        # Commanded airflow duty (field-4 echo is UNCONFIRMED); authoritative
        # for the UI slider sync at connect and after a recovery re-assert.
        return float(self._cmd_airflow)

    # no scan interface here: config-dialog discovery goes through
    # the common ClientBLE stack (artisanlib.ble_port) like every other device;
    # this class is the live roast transport only (see close() for teardown).

    def send(self, cmd: str) -> None:
        """Queue a raw TC4 command (used by the 'TilauScope Command' slider)."""
        # Intercept the GUARD,ON / GUARD,OF pseudo-command: it arms
        # or disarms the link-recovery guard and is NEVER forwarded to FF02.
        head, _, val = cmd.strip().partition(",")
        if head.upper() == _GUARD_CMD:
            self.set_guard(val.strip().upper().startswith("ON"))
            return
        cmd = self._normalize_cmd(cmd)   # firmware wants integer duty (OT2,25 not OT2,25.0)
        self._track_cmd(cmd)
        _logd.debug("TilauTC4BLE: send %r", cmd)
        self._ble.submit(self._write(cmd + _CMD_TERM))   ## restore: actually queue the write

    def set_guard(self, armed: bool) -> None:
        """Arm/disarm the link-loss recovery protocol (GUARD,ON / GUARD,OF)."""
        if armed == self._guard_armed:
            return
        self._guard_armed = armed
        _logd.info("TilauTC4BLE: recovery guard %s", "armed" if armed else "disarmed")
        self.guardChanged.emit(armed)

    @property
    def guard_armed(self) -> bool:
        return self._guard_armed

    @staticmethod
    def _normalize_cmd(cmd: str) -> str:
        # Coerce 'OTn,<float>' to 'OTn,<int>': the TC4 firmware expects integer
        # duty; a trailing '.0' from a slider value can be rejected outright.
        head, sep, val = cmd.strip().partition(",")
        if sep and head.upper().startswith("OT"):
            try:
                return f"{head},{int(float(val))}"
            except ValueError:
                pass
        return cmd.strip()

    def _track_cmd(self, cmd: str) -> None:
        # Mirror commanded duties for actuators not (reliably) echoed by READ so
        # getDrum()/getAirflow() and the post-drop recovery snapshot stay
        # truthful regardless of the call path (raw send() or set_output()).
        try:
            head, _, val = cmd.strip().partition(",")
            duty = int(float(val))
        except (ValueError, AttributeError):
            return
        h = head.upper()
        if h == f"OT{OT_DRUM}":
            self._cmd_drum = duty
        elif h == f"OT{OT_AIRFLOW}":
            self._cmd_airflow = duty
        elif h == f"OT{OT_BURNER}":
            self._cmd_burner = duty

    def set_output(self, channel: int, level: float) -> None:
        """Set an OT output, clamped to its actuator range."""
        lo, hi = _CLAMP.get(channel, (0, 100))
        value = int(max(lo, min(hi, round(level))))
        _logd.debug("TilauTC4BLE: setting output %d to %f", channel, level)
        if channel == OT_BURNER:
            self._cmd_burner = value   # track commanded heat for the safety monitor
        self.send(f"OT{channel},{value}")

    def set_burner(self, level: float) -> None:
        self.set_output(OT_BURNER, level)

    def set_airflow(self, level: float) -> None:
        self.set_output(OT_AIRFLOW, level)

    def set_drum(self, level: float) -> None:
        self.set_output(OT_DRUM, level)

    def set_exhaust(self, level: float) -> None:
        self.set_output(OT_EXHAUST, level)

    @property
    def connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        """Tear down the link and the BLE loop thread (call on app shutdown)."""
        try:
            self._ble.submit(self._disconnect()).result(timeout=3)
        except Exception:  # noqa: BLE001 - best-effort shutdown
            pass
        if not self._ble.stop():
            _logd.warning("TilauTC4BLE: BLE loop did not stop cleanly")

    # ── coroutines (run on the private BLE loop) ────────────────────────────
    async def _connect(self) -> None:
        self._connect_task = asyncio.current_task()   # track so close() can cancel a pending connect
        try:
            self._closing = False
            self._client = BleakClient(
                self._address, disconnected_callback=self._on_disconnect
            )
            await self._client.connect()
            self._mtu = max(20, getattr(self._client, "mtu_size", 23) - 3)
            # Subscribe before init so the OT1 echo is available for verification.
            await self._client.start_notify(FF01_NOTIFY, self._on_notify)
            # Init the TC4 channel map (this may reset outputs to a default state).
            await self._write(_CHAN_INIT + _CMD_TERM)
            # SAFETY: connecting alone asserts a default burner state (observed
            # 100%). A single OT1,0 is unreliable (it races CHAN), so assert and
            # VERIFY against the field-3 echo, retrying, before going live.
            if not await self._verified_burner_off():
                _logd.error("TilauTC4BLE: burner OFF unconfirmed — fail-safe disconnect")
                self.safetyAlert.emit("burner_off_unconfirmed")
                self._closing = True
                await self._client.disconnect()
                self.stateChanged.emit("error")
                return
            # STATE: burner is now 0. Assert a sane airflow; drum keeps the
            # controller default (not echoed), tracked as commanded.
            #await self._write(f"OT{OT_AIRFLOW},{_CONNECT_AIRFLOW}" + _CMD_TERM)
            self._cmd_drum = _DRUM_DEFAULT
            self._connected = True
            self._last_rx = time.monotonic()       # seed before the watchdog starts
            self._epoch += 1                        # new generation; invalidates any stale task
            epoch = self._epoch
            self._poll_task = asyncio.ensure_future(self._poll(epoch))
            self._watchdog_task = asyncio.ensure_future(self._rx_watchdog(epoch))
            _logd.info("TilauTC4BLE connected: %s", self._address)
            self.stateChanged.emit("connected")
            self._recovering = False               # link is back
            if self._restore_pending:              # reconnected into a live roast
                if self._guard_armed:
                    await self._restore_after_drop()
                self._restore_pending = False
        except Exception as e:  # noqa: BLE001
            _logd.exception(e)
            self.stateChanged.emit("error")
        finally:
            self._connect_task = None              # connect settled (ok/err/cancel)

    async def _verified_burner_off(self) -> bool:
        """Assert OT1,0 and confirm the field-3 echo reads 0; retry, else fail."""
        self._cmd_burner = 0
        for attempt in range(_VERIFY_TRIES):
            await self._write(f"OT{OT_BURNER},0" + _CMD_TERM)
            await self._write(_READ_CMD + _CMD_TERM)
            await asyncio.sleep(_VERIFY_WAIT_S)
            if self._burner_echo == 0:
                _logd.info("TilauTC4BLE: burner verified off (attempt %d)", attempt + 1)
                return True
        return False

    # ── link-recovery protocol ( ) ────────────────────────────────
    async def _restore_after_drop(self) -> None:
        """Re-assert mechanical state after a reconnect into a live roast.

        Heat is NEVER re-applied here: the firmware emergency already forced the
        burner to 0, so we re-push last airflow & drum and sync the burner
        command DOWN to the echoed value. Artisan then shows reality (0) and the
        operator deliberately resumes gas or presses STOP.
        """
        last_bt = self._latest[1] if self._latest else -1.0
        await self._write(f"OT{OT_AIRFLOW},{self._cmd_airflow}" + _CMD_TERM)
        await self._write(f"OT{OT_DRUM},{self._cmd_drum}" + _CMD_TERM)
        await self._write(_READ_CMD + _CMD_TERM)   # refresh the burner echo
        await asyncio.sleep(_VERIFY_WAIT_S)
        echo = self._burner_echo if self._burner_echo is not None else 0
        self._cmd_burner = echo                    # baseline the safety monitor to reality
        _logd.info("TilauTC4BLE: live link recovered — airflow=%d drum=%d, burner held at %d",
                   self._cmd_airflow, self._cmd_drum, echo)
        # main.py syncs the Artisan burner slider to <echo> on this signal.
        self.roastInterrupted.emit("link_recovered", float(last_bt), int(echo))

    def _handle_unexpected_drop(self, reason: str) -> None:
        """Single, idempotent entry point for an unexpected link loss.

        Called by bleak's disconnected_callback and by the RX-stall watchdog.
        Captures whether a roast was live AT THE DROP and starts the reconnect
        driver; telemetry reconnection runs even when the guard is disarmed.
        """
        self._connected = False
        if self._closing or self._recovering:
            return
        self._recovering = True
        self._restore_pending = bool(self._is_live())
        _logd.warning("TilauTC4BLE: unexpected link loss (%s): %s", reason, self._address)
        self.safetyAlert.emit("link_lost")
        self.stateChanged.emit("disconnected")
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        # Reconnect by known UUID (no scan, limits CoreBluetooth contention) with
        # a short, capped backoff: a roast cannot wait. _connect() runs the
        # recovery protocol on success.
        delay = 0.0
        try:
            while not self._closing and not self._connected:
                if delay:
                    await asyncio.sleep(delay)
                await self._connect()
                if self._connected:
                    break
                delay = min(_RECONNECT_CAP_S, delay * 2 or 0.5)
        finally:
            self._recovering = False

    async def _rx_watchdog(self, epoch: int) -> None:   # bound to its connection generation
        # A zombie link (CoreBluetooth "connected" but silent) does NOT fire the
        # disconnected_callback, yet the firmware still emergency-stops. If no
        # telemetry arrives for _RX_STALL_S, force a clean reconnect so recovery
        # can run.
        try:
            while self._connected and epoch == self._epoch:
                await asyncio.sleep(_RX_STALL_CHECK_S)
                if self._connected and epoch == self._epoch and (time.monotonic() - self._last_rx) > _RX_STALL_S:
                    _logd.warning("TilauTC4BLE: RX stall (>%.1fs) — forcing reconnect", _RX_STALL_S)
                    self._connected = False
                    try:
                        if self._client and self._client.is_connected:
                            await asyncio.wait_for(self._client.disconnect(), 3.0)
                    except Exception:  # noqa: BLE001
                        pass
                    self._handle_unexpected_drop("rx_stall")
                    return
        except asyncio.CancelledError:
            pass

    async def _disconnect(self) -> None:
        try:
            self._closing = True
            # Abort an in-flight connect before tearing down: a pending
            # connect destroyed by loop stop leaves a half-open CoreBluetooth link
            # on macOS that blocks every subsequent reconnection.
            if self._connect_task is not None and not self._connect_task.done():
                self._connect_task.cancel()
                try:
                    await self._connect_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            if self._client and self._client.is_connected:
                # SAFETY: re-assert burner off before handing control back.
                await self._write(f"OT{OT_BURNER},0" + _CMD_TERM)
            self._connected = False
            if self._reconnect_task is not None:   # stop any reconnect driver
                self._reconnect_task.cancel()
                self._reconnect_task = None
            if self._watchdog_task is not None:    # stop the RX watchdog
                self._watchdog_task.cancel()
                self._watchdog_task = None
            if self._poll_task is not None:
                self._poll_task.cancel()
                self._poll_task = None
            if self._client is not None:
                try:
                    await self._client.stop_notify(FF01_NOTIFY)
                except Exception:  # noqa: BLE001
                    pass
                await self._client.disconnect()
        except Exception as e:  # noqa: BLE001
            _logd.exception(e)
        finally:
            self.stateChanged.emit("disconnected")

    async def _poll(self, epoch: int) -> None:     # bound to its connection generation
       # Nothing streams unsolicited: the controller answers one CSV line per READ.
        try:
            while self._connected and epoch == self._epoch:
                await self._write(_READ_CMD + _CMD_TERM)
                await asyncio.sleep(self._poll_s)
        except asyncio.CancelledError:
            pass

    async def _write(self, text: str) -> None:
        if not (self._client and self._client.is_connected):
            return
        data = text.encode()
        for off in range(0, len(data), self._mtu):
            await self._client.write_gatt_char(
                FF02_WRITE, data[off:off + self._mtu], response=False
            )
        _logd.debug("TX %r", text)

    # ── notify handling ─────────────────────────────────────────────────────
    def _on_notify(self, _ch, data: bytearray) -> None:
        # Accumulate then split on CRLF; the bridge may fragment or coalesce frames.
        self._buf.extend(data)
        while _LINE_TERM in self._buf:
            line, _, rest = self._buf.partition(_LINE_TERM)
            self._buf = bytearray(rest)
            self._parse(bytes(line))

    def _parse(self, line: bytes) -> None:
        try:
            _logd.debug("received TC4 line: %r", line)
            parts = line.decode("ascii", "ignore").split(",")
            ambient = float(parts[_IDX_AMBIENT])
            bt = float(parts[_IDX_BT])
            et = float(parts[_IDX_ET])
        except (ValueError, IndexError):
            _logd.debug("unparsable TC4 line: %r", line)
            return
        # Actuator duty echoes (field 3 burner, field 4 airflow).
        try:
            self._burner_echo = int(float(parts[_IDX_BURNER_ECHO]))
        except (ValueError, IndexError):
            self._burner_echo = None
        try:   # airflow duty echo (field 4) for the actuator extra-device
            self._airflow_echo = int(float(parts[_IDX_AIRFLOW_ECHO]))
        except (ValueError, IndexError):
            self._airflow_echo = None
        with self._lock:
            self._latest = (ambient, bt, et)
            self._last_rx = time.monotonic()   # telemetry freshness for the watchdog
            self.sampleReady.emit(ambient, bt, et,
                              float(self._burner_echo if self._burner_echo is not None else -1),
                              float(self._airflow_echo if self._airflow_echo is not None else -1))
            self._monitor_burner()
        _logd.debug("RX ambient=%.1f BT=%.1f ET=%.1f OT1=%s OT2=%s",
                   ambient, bt, et, self._burner_echo, self._airflow_echo)

    def _monitor_burner(self) -> None:
        # Defence in depth: the burner must never exceed the commanded level.
        # Re-assert the command on any overshoot (self-correcting, cheap) and
        # raise a sustained-fault alert after repeated mismatches.
        echo = self._burner_echo
        if echo is None or echo <= self._cmd_burner:
            self._mismatch = 0
            return
        asyncio.ensure_future(
            self._write(f"OT{OT_BURNER},{self._cmd_burner}" + _CMD_TERM)
        )
        self._mismatch += 1
        _logd.warning("TilauTC4BLE: burner echo=%d > commanded=%d, re-asserting",
                     echo, self._cmd_burner)
        if self._mismatch >= 2:
            self.safetyAlert.emit("burner_overshoot")

    def _on_disconnect(self, _client) -> None:
        if self._closing:
            self._connected = False
            # Intentional disconnect: _disconnect() emits the state change.
            _logd.debug("TilauTC4BLE: link closed (intentional)")
            return
        # Unexpected link loss mid-session: hand off to the recovery protocol
        # (capture live state, reconnect, restore mechanical state, hold heat).
        self._handle_unexpected_drop("link_lost")


# ── standalone validation harness (no Artisan involved) ─────────────────────
def _main() -> None:
    import sys
    from PyQt6.QtCore import QCoreApplication, QTimer

    p = argparse.ArgumentParser(description="TilauTC4BLE standalone test")
    p.add_argument("address", help="BLE peripheral UUID/MAC of the TD5325A")
    p.add_argument("--seconds", type=float, default=20.0, help="run duration")
    p.add_argument("--drum", type=int,
                   help="safe control test: set drum %% (60-100), no heat")
    p.add_argument("--airflow", type=int,
                   help="safe control test: set airflow %% (0-100), no heat")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    app = QCoreApplication(sys.argv)
    dev = TilauTC4BLE(args.address)
    dev.sampleReady.connect(
        lambda a, bt, et, ot1, ot2: print(f"ambient={a:.1f}  BT={bt:.1f}  ET={et:.1f} Bruleur={ot1}  Airflow={ot2}")
    )
    dev.stateChanged.connect(lambda s: print(f"[state] {s}"))
    dev.safetyAlert.connect(lambda s: print(f"[SAFETY] {s}"))
    dev.connect()

    if args.airflow is not None:
        # Mechanical-only control check (no heat); fires a few seconds in.
        QTimer.singleShot(4000, lambda: dev.set_airflow(args.airflow))

    if args.drum is not None:
        # Mechanical-only control check (no heat); fires a few seconds in.
        QTimer.singleShot(5000, lambda: dev.set_drum(args.drum))

    def _quit() -> None:
        dev.close()
        QTimer.singleShot(250, app.quit)   # let the queued disconnect signal flush

    QTimer.singleShot(int(args.seconds * 1000), _quit)
    app.exec()


if __name__ == "__main__":
    _main()

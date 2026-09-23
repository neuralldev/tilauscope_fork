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

# courtesy to Difluid team which provided the API structure of packets exchanged through BLE
# and V005 firmware update though the app (this is mandatory for this coupling to work)

# AUTHOR
# TiLau 2025

import logging
import struct
from contextlib import contextmanager
from enum import StrEnum, IntEnum
import time
from typing import Final
from artisanlib.ble_port import ClientBLE
from artisanlib.util import fromFtoCstrict
from artisanlib.main import ApplicationWindow # pylint: disable=unused-import
import threading
from dataclasses import dataclass

from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import
from PyQt6.QtCore import pyqtSlot, pyqtSignal, QDateTime,  QObject, QMutex, QMutexLocker
from PyQt6.QtWidgets import QApplication

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")
from tilauscope.tilauscope_types import RoastingPhase

AIRWAVE_PREFIX= "AirWave " # all devices start with this name
MAX_DILFUID_WINDOW_LENGTH = 60 # maximum data window set to 50 to allow exchange of long packets, by default ble_port truncates to 20 bytes packets

class AirwaveUUID(StrEnum):
    AIRWAVE_SERVICE_UUID = "000000e3-0000-1000-8000-00805f9b34fb" # service UUID to discover devices
    AIRWAVE_DIALOG_UUID  = "0000aa01-0000-1000-8000-00805f9b34fb" # clear text channel characteristic

class AirwaveFanMode(IntEnum):
    STANDARD=0
    EXTREME=1
    FAN=2
    UNKNOWN = -1

class AirwaveLanguages(IntEnum):
    CHINESE1=0
    CHINESE2=1
    ENGLISH=2
    JAPANESE=3
    KOREAN=4

class AirwaveFanLimits(IntEnum):
    MINIMUM=30
    MAXIMUM=100

class AirwaveFunctions(IntEnum):
    DEVICEINFO=0
    DEVICESETTING=1
    DEVICEACTIONS=3

class AirwaveCommands(IntEnum):
    # FUNCTION 0 / DEVICE INFO
    SERIALNUMBER=0
    DEVICEMODEL=1
    FIRMWARE=2
    # FUNCTION 1 / DEVICE SETTINGS
    LANGUAGE = 0 #AirwaveLanguages
    HOSTNAME = 1 # (Firmware v400 min)
    # FUNCTION 3 / DEVICE ACTIONS
    POSITION = 0 # AiwaveFanMode
    FAN = 1 # AirwaveSpeed
    STATUS = 2 # AirwaveState
    TEMPERATURE = 3 # get temperatures from device
    ROASTINGSTAGE = 4 #AirwaveEvents (firmware V500 min)
    AUTOMODE = 5 # AirwaveState (firmware V500 min)

class AirwaveSpeed(IntEnum):
    MINIMUM=30
    MAXIMUM=100

class AirwaveState(IntEnum):
    ON = 1
    OFF = 0
    UNKNOWN = -1

class AirwaveEvents(IntEnum):
    ROASTING_STAGE_PREHEAT  = 0 # preheating
    ROASTING_STAGE_CHARGE   = 1 # charge event
    ROASTING_STAGE_DRY      = 2 # dry end
    ROASTING_STAGE_FCs      = 3 # First crack start
    ROASTING_STAGE_SCs      = 4 # second carack start
    ROASTING_STAGE_DROP     = 5 # cooling start

class AirwaveControlMode(IntEnum):
    AIRWAVE_CONTROL_MANUAL = 0
    AIRWAVE_CONTROL_AUTO = 1

class DiFluidProtocol:
    PREAMBLE = b'\xdf\xdf'

    def build_full_message(self, function: AirwaveFunctions, command: AirwaveCommands, data: bytes = b'') -> bytes:
        length = len(data)
        payload = self.PREAMBLE + struct.pack('BBB', function, command, length) + data
        checksum = (sum(payload) & 0xFF)
        return payload + struct.pack('B', checksum)

    def parse_messages_by_delimiter(self, received_bytes: bytes, delimiter: bytes = PREAMBLE) -> list[bytes]:
        """Cut a notification into frames, walking by the declared length.

        Frame layout: preamble(2) | function | command | length | data | checksum,
        so a frame is 6 + length bytes and carries its own size at offset 4.

        Splitting on the preamble instead would treat any 0xDF 0xDF *inside* a
        body as a frame boundary. That is reachable: a TEMPERATURE reply carries
        two raw float32, and 111.936 °C encodes as 3B DF DF 42 — the frame was
        cut in two, both halves failed their checksum, and the reading was lost.
        Roughly one reading in 22 000 for the inlet band, 1 in 65 536 for the
        catalyst band.
        """
        buf = bytes(received_bytes)
        messages: list[bytes] = []
        i = buf.find(delimiter)          # skip anything before the first frame
        while i >= 0:
            if i + 5 > len(buf):
                break                    # header incomplete, nothing to size on
            end = i + 6 + buf[i + 4]     # header(5) + data(length) + checksum(1)
            if end <= len(buf):
                messages.append(buf[i:end])
                i = buf.find(delimiter, end)
            else:
                # The declared length overruns what arrived: either a truncated
                # tail, or a corrupted header. Resync on the next preamble so a
                # good frame behind a bad one is still delivered; if there is
                # none, find() returns -1 and the walk ends.
                i = buf.find(delimiter, i + 2)
        return messages

    def parse_full_message(self, payload: bytes) -> dict:
        if len(payload) < 6 or not payload.startswith(self.PREAMBLE) :
            return {'valid': False, 'error': 'Invalid preamble or length'}

        function = payload[2]
        command = payload[3]
        length = payload[4]

        if len(payload) < 5 + length + 1: # header (3) + preamble (2) + data + checksum (1)
            return {'valid': False, 'error': 'Payload too short for declared length'}

        data = payload[5:5+length]
        checksum = payload[5+length]
        expected_checksum = (sum(payload[:5+length]) & 0xFF)

        valid = checksum == expected_checksum
        if not valid:
            return {'valid': False, 'error': 'Checksum mismatch'}

        return {
            'function': function,
            'command': command,
            'length': length,
            'data': data,
            'checksum': checksum,
            'valid': valid
        }

#  class for BLE communication with the Difluid Airwave device
class AirwaveBLE(ClientBLE, DiFluidProtocol): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()     # issued on connect
    disconnected_signal = pyqtSignal()  # issued on disconnect
    unsolicited_event_signal = pyqtSignal(dict) # issued when an information/request is received from the Airwave whthout prior request

    def __init__(self, device_uuid:str):
        super().__init__()
        # Latest reply per (function, command), each stamped with the monotonic clock.
        # A shared queue let two waiters steal each other's frames: the temperature
        # read runs on the sampling thread while a setter waits on the actuator
        # worker. Keeping only the latest reply and stamping it lets every waiter
        # decide for itself whether what it sees answers its own request.
        self._responses: dict[tuple[int, int], tuple[float, dict]] = {}
        # Per-key count of replies we are expecting; see commanding().
        self._quiet: dict[tuple[int, int], int] = {}
        self._resp_cv = threading.Condition()
        # Dedup command queue: key=(function,command), value=latest entry, ordered by last write.
        # Active from creation until first successful connect; cleared on bleStop.
        self._cmd_queue: dict[tuple[int, int], dict] = {}
        self._queue_lock = threading.Lock()
        self.is_connected:bool  = False
        # configuration
        self.add_device_description(AirwaveUUID.AIRWAVE_SERVICE_UUID,"")
        self.add_notify(AirwaveUUID.AIRWAVE_DIALOG_UUID, self.notify_callback)
        self.add_write(AirwaveUUID.AIRWAVE_SERVICE_UUID, AirwaveUUID.AIRWAVE_DIALOG_UUID)
        self.start(case_sensitive=False, address=device_uuid)
        self._send_lock = threading.Lock()

    def on_connect(self) -> None:
        self.is_connected = True
        self._drain_queue()
        self.connected_signal.emit()

    def on_disconnect(self) -> None:
        self.is_connected = False
        self.disconnected_signal.emit() # On émet le signal

    # notify callback processes the messages received by the Airwave on the notify characteristic
    def notify_callback(self, _sender:'BleakGATTCharacteristic', data:bytearray) -> None:
        messages = self.parse_messages_by_delimiter(data)
        for msg_bytes in messages:
            parsed_msg = self.parse_full_message(msg_bytes)
            if parsed_msg.get('valid'):
                #_logd.debug("process incoming message ")
                if parsed_msg.get('function') == AirwaveFunctions.DEVICEACTIONS and parsed_msg.get('command') == AirwaveCommands.ROASTINGSTAGE: # this is airwave rosting monitoring request
                    self.unsolicited_event_signal.emit(parsed_msg)
                elif parsed_msg.get('function') == AirwaveFunctions.DEVICESETTING and parsed_msg.get('command')== AirwaveCommands.HOSTNAME: # this is airwave hostname requeet
                    self.unsolicited_event_signal.emit(parsed_msg)
                else:
                   self._store_response(parsed_msg)
            else:
               _log.error("invalid message received on difluid callback")

    # Frames that can mean "somebody turned a knob on the extractor". Anything
    # else the device sends back is an answer to a request of ours.
    SPONTANEOUS_KEYS: Final[frozenset] = frozenset({
        (int(AirwaveFunctions.DEVICEACTIONS), int(AirwaveCommands.POSITION)),
        (int(AirwaveFunctions.DEVICEACTIONS), int(AirwaveCommands.FAN)),
        (int(AirwaveFunctions.DEVICEACTIONS), int(AirwaveCommands.STATUS)),
    })

    @contextmanager
    def commanding(self, *keys: tuple[int, int]):
        """Claim the replies to `keys` for the duration of the block.

        Claimed before the write goes out, and held across a whole compound
        sequence. Setting the position makes the device return the wind
        percentage of that mode on its own: unclaimed, that echo would read as a
        gesture on the extractor and drag the lever to the mode default.
        """
        ks = [(int(f), int(c)) for f, c in keys]
        with self._resp_cv:
            for k in ks:
                self._quiet[k] = self._quiet.get(k, 0) + 1
        try:
            yield
        finally:
            with self._resp_cv:
                for k in ks:
                    left = self._quiet.get(k, 0) - 1
                    if left > 0:
                        self._quiet[k] = left
                    else:
                        self._quiet.pop(k, None)

    def _store_response(self, msg: dict) -> None:
        key = (int(msg['function']), int(msg['command']))
        with self._resp_cv:
            self._responses[key] = (time.monotonic(), msg)
            spontaneous = key in self.SPONTANEOUS_KEYS and not self._quiet.get(key)
            self._resp_cv.notify_all()
        if spontaneous:
            self.unsolicited_event_signal.emit(msg)

    def await_response(self, function: int, command: int, after: float, timeout: float) -> dict | None:
        """Return the reply to (function, command) stored after ``after``, else None.

        ``after`` is a monotonic stamp taken before the request went out, so a
        reply already sitting there is never mistaken for the answer to this
        request. The device sends a fan echo of its own after a mode change:
        without the stamp that echo answers the next speed request for free.
        """
        key = (int(function), int(command))
        deadline = time.monotonic() + timeout
        with self._resp_cv:
            while True:
                entry = self._responses.get(key)
                if entry is not None and entry[0] > after:
                    return entry[1]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._resp_cv.wait(remaining)

    # A command queued before the link came up describes a roast state that has
    # since moved on. Past this age it is dropped rather than replayed: an
    # actuator has no memory, and re-applying a stale setpoint is worse than
    # applying nothing.
    QUEUED_COMMAND_TTL: Final[float] = 30.0

    def _drain_queue(self) -> None:
        """Drain dedup queue on connect. Sends in last-occurrence order, fire-and-forget."""
        with self._queue_lock:
            pending = list(self._cmd_queue.values())
            self._cmd_queue.clear()
        now = time.monotonic()
        fresh = []
        for entry in pending:
            age = now - entry['queued_at']
            if age <= self.QUEUED_COMMAND_TTL:
                fresh.append(entry)
            else:
                _logd.warning(
                    f"airwave: dropping stale queued cmd f={entry['function']} "
                    f"c={entry['command']} ({age:.0f}s old)")
        pending = fresh
        if not pending:
            return
        _logd.debug(f"draining {len(pending)} queued airwave command(s)")
        for entry in pending:
            msg = self.build_full_message(entry['function'], entry['command'], entry['data'])
            try:
                self.send(
                    message=msg,
                    response=entry['answer'],
                    write_characteristic=AirwaveUUID.AIRWAVE_DIALOG_UUID,
                    chunk=MAX_DILFUID_WINDOW_LENGTH,
                )
                time.sleep(0.05)
            except Exception as e:  # noqa: BLE001
                _log.error(f"drain send error: {e}")
    # calls sublayer BLE stop so the device releases handles and loops across characteristics and notifications
    def bleStop(self) -> None:
        with self._queue_lock:
            self._cmd_queue.clear()
        self.stop()
        # now wait for all the ble async queues to flush before killing the object
        from tilauscope.tilau_ble_scanner import wait_ble_client_released  # noqa: PLC0415
        wait_ble_client_released(self)

    # ble_port.py implementation of connection rely on presence of both UUID and Name of device read from the Bluetooth layers
    def isconnected(self) -> bool:
        c = self.connected() # just retrieve UUID is enough to check for connection
        return c[0] is not None

    # write a request to the Airwave device with Function, Command and Data to send
    def send_command(
        self,
        function: AirwaveFunctions,
        command: AirwaveCommands,
        data: bytes = b'',
        answer: bool = True,
    ) -> str | None:
        with self._send_lock:
            if not self.isconnected():
                # Dedup: pop old slot then re-insert so position = last occurrence.
                key = (int(function), int(command))
                with self._queue_lock:
                    self._cmd_queue.pop(key, None)
                    self._cmd_queue[key] = {'function': function, 'command': command, 'data': data,
                                            'answer': answer, 'queued_at': time.monotonic()}
                _logd.debug(f"queued airwave cmd f={function} c={command} (queue={len(self._cmd_queue)})")
                return None
            # Connected: direct send, bypass queue
            msg = self.build_full_message(function, command, data)
            try:
                # ClientBLE.send() reports delivery: a failing write_gatt_char is
                # caught chunk by chunk and never surfaces as an exception, so
                # without this check every dropped write still answered "ok".
                if not self.send(message=msg, response=answer,
                                 write_characteristic=AirwaveUUID.AIRWAVE_DIALOG_UUID,
                                 chunk=MAX_DILFUID_WINDOW_LENGTH):
                    return "error: write not delivered"
                return "ok"
            except Exception as e:  # noqa: BLE001
                return f"error occurred {e}"

@dataclass(slots=True)
class AirwaveStateData:
    # `speed` and `mode` hold what the device has CONFIRMED; they move only on a
    # reply from it. Writing the setpoint into `speed` before the send made every
    # display optimistic: the lever showed a speed the extractor never applied.
    # `speed_requested` keeps the last value asked of the extractor by anyone —
    # the duct guard needs it to tell its own cut from a gesture on the lever.
    speed: int = 0
    mode: int = -1
    speed_requested: int = 0
    sn: str = "unknown"
    firmware: str = "unknown"
    model: str = "unknown"
    last_inlet: float = 25.0
    last_catalyst: float = 25.0
    last_fanspeed: int = AirwaveSpeed.MINIMUM # minimum fanspeed for Airwave
    holdon: bool = True
    state: int = AirwaveState.UNKNOWN

@dataclass(slots=True)
class OmnifluxBinding:
    """Holds resolved indices into Artisan's extraXXX arrays for the Omniflux."""
    color_device_idx: int = -1      # index in extradevices for MODBUS34
    roc_device_idx:   int = -1      # index in extradevices for MODBUS56
    valid: bool = False

def detect_omniflux_devices(aw: ApplicationWindow) -> OmnifluxBinding:
    """
    Scan Artisan extra-devices to locate the Omniflux Agtron/RoC channels.
    Must be called after charge (qmc data is available) or on settings load.
    """
    binding = OmnifluxBinding()
    qmc = aw.qmc
    modbus = getattr(aw, 'modbus', None)

    if modbus is None:
        _logd.warning("omniflux detect: no modbus object found")
        return binding

    # Verify RTU serial mode is engaged
    if getattr(modbus, 'type', '') != 0 or not getattr(modbus, 'comport', None):
        _logd.warning("omniflux detect: modbus not in serial RTU mode or comport not detected")
        return binding

    # verify channels and register settings which are expected on MODBUS34
    match = (
        modbus.inputDeviceIds[0], modbus.inputDeviceIds[1],
        modbus.inputDeviceIds[2], modbus.inputDeviceIds[3],
        modbus.inputDeviceIds[4], modbus.inputDeviceIds[5],
        modbus.inputRegisters[0], modbus.inputRegisters[1],
        modbus.inputRegisters[2], modbus.inputRegisters[3],
        modbus.inputRegisters[4], modbus.inputRegisters[5],
        modbus.inputCodes[2], modbus.inputCodes[3],
        modbus.inputModes[2], modbus.inputModes[3],
        modbus.inputDivs[2], modbus.inputDivs[3]
    ) == (1, 1, 2, 2, 3, 3, 10, 11, 12, 13, 14, 15, 3, 3, 'C', 'C', 1, 1)

    if not match:
        return binding

    n = len(qmc.extradevices)
    for i in range(n):
        n1 = qmc.extraname1[i].strip().upper() if i < len(qmc.extraname1) else ""
        n2 = qmc.extraname2[i].strip().upper() if i < len(qmc.extraname2) else ""

        # Color device: name has "AGTRON", registers 12+13
        if "AGTRON" in n1 and "ROC" in n2:
            binding.color_device_idx = i
            binding.roc_device_idx = i
            _logd.debug(f"omniflux detect: color device found at extra index {i}")
            break

    binding.valid = binding.color_device_idx >= 0
    if not binding.valid:
        _logd.warning("omniflux detect: color device not found — color PID layer disabled")
    return binding

# Main class used by the Artisan software
class Difluid(QObject): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    succionspeed_changed_signal = pyqtSignal(int)  # issued on fan power % change, see AirwaveSpeed class
    mode_changed_signal = pyqtSignal(int)  # issued on mode change, see AirwaveFanMode class
    state_changed_signal = pyqtSignal(bool)  # issued on switch changed on/off, see AirwaveState class
    #todo : implement the manual/auto mode for V500 firmware
    roastingstage_request_signal = pyqtSignal() # sends the roasting stage requested by the Airwave
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()

    # Settling time left to the device after a mode change before the next subcommand.
    MODE_SETTLE_DELAY: Final[float] = 0.3

    # How long a setter waits for the device to echo back what it applied.
    CONFIRM_TIMEOUT: Final[float] = 1.0
    # A speed that comes back different is re-sent this many times, no more: the
    # extractor is an actuator, not a negotiation.
    FAN_CONFIRM_RETRIES: Final[int] = 1

    # Garde thermique de la gaine. Limite materielle : rien a voir avec la
    # conduite du roast, d'ou un garde qui tourne des que l'extracteur est
    # connecte, enregistrement ou non.
    DUCT_LIMIT_DEFAULT: Final[float] = 80.0   # degC
    DUCT_MAX_CUT_PCT: Final[float] = 15.0     # retrait maximal, en points de ventilateur
    DUCT_HYSTERESIS_C: Final[float] = 2.0     # marge de relache, evite le battement
    DUCT_ORIGIN: Final[str] = "duct guard"    # origine des consignes du garde dans la file

    # The three fan modes the settings table may hold. An unknown value falls back
    # to STD: defaulting to EXTREME would put the extractor at maximum on nothing
    # more than a legacy or corrupted setting.
    FAN_MODES: Final[dict[str, int]] = {
        "FAN": AirwaveFanMode.FAN,
        "STD": AirwaveFanMode.STANDARD,
        "EXT": AirwaveFanMode.EXTREME,
    }
    FAN_MODE_FALLBACK: Final[str] = "STD"

    # map event command to roasting stages
    AirwaveEventsMap = {
        "PREHEAT":  (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_PREHEAT),
        "CHARGE":  (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_CHARGE),
        "DRY":     (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_DRY),
        "FCS":     (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_FCs),
        "SCS":     (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_SCs),
        "DROP":    (AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_DROP)
        }

    def __init__(self, name:str):
        super().__init__()
        self.state = AirwaveStateData()
        _logd.debug("difluid class start")
        self.shutdown_lock = QMutex()
        self.is_shutting_down = False
        self.aw:ApplicationWindow|None = None
        self.is_connected = False
        self.command_running = False
        self.airwave = AirwaveBLE(name)
        # check if airwave is used in extradevices to follow inlet and catalyst temps
        self.extradevicenumber:int = -1
        self._inlet_binding_warned: bool = False
        # if detected that Damper is mapped to airwave, add the logic to move slider from pid as well
        self.pilotDamperSlider:bool = False

        self.omniflux: OmnifluxBinding

        # Actuation asynchrone. Les appelants tournent sur le thread GUI
        # (sample_processing, cf. canvas.py) : une écriture BLE y bloque jusqu'à
        # 5 s (ble_port.write) et retient profileDataSemaphore pendant ce temps.
        # La décision reste dans le tick, l'émission part sur ce worker.
        self._pid_pending: list[tuple[str, str]] = []  # (commands, origin)
        self._pid_cv = threading.Condition()
        self._pid_stop = False
        self._pid_worker: threading.Thread | None = None

        # Garde thermique de la gaine : points de ventilateur actuellement
        # retires, valeur a restituer, et derniere consigne envoyee par le garde.
        self._duct_cut: float = 0.0
        self._duct_base: int | None = None
        self._duct_last_sent: int | None = None
        self._duct_last_target: int | None = None

        self._setup_connections()

    def _setup_connections(self):
        self.airwave.connected_signal.connect(self._relay_connected)
        self.airwave.disconnected_signal.connect(self._relay_disconnected)
        self.airwave.unsolicited_event_signal.connect(self._handle_unsolicited_event)

    # Nombre de commandes en attente au-delà duquel la plus ancienne consigne est
    # jetée : un actionneur n'a pas de mémoire, seule la dernière consigne compte.
    # Seuls FAN et MODE sont des consignes : une marche, un arrêt, un passage en
    # CONTROL ou un armement ne sont remplacés par rien et passent en dernier.
    PID_QUEUE_MAX: Final[int] = 8

    @staticmethod
    def _subcommands(commands: str) -> list[str]:
        """The subcommands of a sequence, separated by ',' or ';', left unstripped."""
        return commands.replace(';', ',').split(',')

    def dispatch_async(self, commands: str, origin: str = "") -> None:
        """Queue an actuator command for the worker thread and return at once.

        Every actuator command goes through here, so a compound sequence runs to
        the end before the next one starts: nothing can slip between a mode
        change and the speed that follows it. Callers run on the GUI and
        sampling threads, where a BLE write blocks for up to five seconds.

        Consecutive pure ``FAN n`` commands coalesce — only the latest setpoint
        is worth sending. A compound ``MODE x,FAN n`` or ``FAN n;POWER OFF``
        never coalesces, so a mode change or a stop is never swallowed by a
        later speed change.
        """
        if not commands:
            return

        def fan_only(cmd: str) -> bool:
            subs = self._subcommands(cmd)
            return len(subs) == 1 and subs[0].strip().upper().startswith("FAN ")

        with self._pid_cv:
            if self._pid_stop:
                return
            if fan_only(commands) and self._pid_pending and fan_only(self._pid_pending[-1][0]):
                self._pid_pending[-1] = (commands, origin)
            else:
                self._pid_pending.append((commands, origin))
                if len(self._pid_pending) > self.PID_QUEUE_MAX:
                    victim = next((i for i, (cmd, _) in enumerate(self._pid_pending)
                                   if all(sub.strip().upper().startswith(("FAN ", "MODE "))
                                          for sub in self._subcommands(cmd))), 0)
                    dropped = self._pid_pending.pop(victim)
                    _logd.warning(f"airwave dispatch: queue full, dropped {dropped[0]!r}")
            self._pid_cv.notify()
        self._ensure_pid_worker()

    def _ensure_pid_worker(self) -> None:
        if self._pid_worker is not None and self._pid_worker.is_alive():
            return
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                return
        self._pid_worker = threading.Thread(
            target=self._pid_worker_loop, name="airwave-actuator", daemon=True
        )
        self._pid_worker.start()

    def _pid_worker_loop(self) -> None:
        while True:
            with self._pid_cv:
                while not self._pid_pending and not self._pid_stop:
                    self._pid_cv.wait(timeout=1.0)
                if self._pid_stop:
                    return
                command, origin = self._pid_pending.pop(0)
            # Queued by the duct guard before a stop ran: a stopped extractor
            # takes no speed, and the write would only come back unconfirmed.
            # The guard wrote it down as it queued it: put back what the
            # extractor confirmed, and say the speed shown was not applied.
            if origin == self.DUCT_ORIGIN and self.state.state == AirwaveState.OFF:
                self.state.speed_requested = self.state.last_fanspeed = self.state.speed
                self._report_failure(command, origin, "extractor stopped")
                continue
            try:
                result = self.send_command(command, origin=origin)
                if result not in ("ok", ""):
                    self._report_failure(command, origin, str(result))
            except Exception as e:  # noqa: BLE001
                _logd.warning(f"airwave dispatch: {command!r} failed: {e}")
                self._report_failure(command, origin, str(e))

    def _report_failure(self, command: str, origin: str, reason: str) -> None:
        """Surface an actuator command the extractor did not confirm.

        Silence here is what let a dropped speed pass for an applied one: the
        lever moved, the roast carried on, and nothing said otherwise.
        """
        _logd.warning(f"airwave [{origin or 'direct'}]: {command!r} not confirmed — {reason}")
        aw = self.aw
        if aw is None:
            return
        try:
            aw.sendmessageSignal.emit(
                QApplication.translate(
                    "tilauscope",
                    "Extractor did not confirm '{0}' ({1})").format(command, reason),
                True, None)
        except Exception:  # pylint: disable=broad-except
            pass

    def _stop_pid_worker(self) -> None:
        with self._pid_cv:
            self._pid_stop = True
            self._pid_pending.clear()
            self._pid_cv.notify_all()
        worker = self._pid_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self._pid_worker = None

    # Completes the hostname handshake: the AirWave only lifts its control lock
    # (state.holdon) once it knows the host name, normally by asking on connect — but a
    # BLE reconnect within the same power session (macOS keeps the link cached) skips
    # that request, so we announce proactively instead. Idempotent, safe to call twice.
    def _ensure_control_session(self) -> None:
        try:
            if self.aw is not None and self.aw.bleAirwaveEmulateOmniflux:
                if not getattr(self, 'omnifluxmode', False):
                    self.armOmniflux()
            else:
                self.SendHostName()
            self.state.holdon = False
        except Exception:  # pylint: disable=broad-except
            pass

    def _relay_connected(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down: return
        self.is_connected = True
        # proactively handshake on the fresh-connect path (see _ensure_control_session)
        self._ensure_control_session()
        self.connected_signal.emit()

    def _relay_disconnected(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down: return
        self.is_connected = False
        # Sequences still queued describe a roast state the link has since missed.
        # They are dropped rather than replayed on reconnect.
        with self._pid_cv:
            if self._pid_pending:
                _logd.warning(f"airwave: dropping {len(self._pid_pending)} queued command(s) on disconnect")
                self._pid_pending.clear()
        self.disconnected_signal.emit()

    def disconnect(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                return
            self.is_shutting_down = True
        _logd.debug("start disconnecting difluid airwave..")

        # Le worker écrit sur le lien BLE : il doit être arrêté avant bleStop().
        self._stop_pid_worker()

        try:
            self.airwave.unsolicited_event_signal.disconnect()
            self.airwave.connected_signal.disconnect()
            self.airwave.disconnected_signal.disconnect()
        except:
            pass

        start_time = QDateTime.currentMSecsSinceEpoch() / 1000.0
        while ((QDateTime.currentMSecsSinceEpoch() / 1000.0) - start_time < 1) and self.command_running:
            time.sleep(0.05)
        # stop airwave ble engine
        self.airwave.bleStop()

    def _airwave_inlet_series(self) -> list[float] | None:
        """Return the extra-device series carrying the AirWave inlet, or None.

        ``extradevicenumber`` is a position in Artisan's extra-device arrays,
        captured once at identification. Loading a profile overwrites the device
        configuration, so that position can fall out of range or come to name a
        different device's channel. Both are checked before the series is used.
        """
        aw = self.aw
        if aw is None or getattr(aw, 'qmc', None) is None:
            return None
        idx = self.extradevicenumber
        qmc = aw.qmc
        try:
            # Artisan ne remplit extratemp1 qu'en enregistrement : hors roast il
            # porte encore la courbe precedente, dont le dernier echantillon est
            # le plus chaud et ne bouge plus. Meme convention que le coeur
            # d'Artisan (eval_math_expression) : le tampon de monitoring en
            # surveillance seule, et rien du tout hors acquisition — la garde
            # retombe alors sur la lecture de l'appareil lui-meme.
            if qmc.flagstart:
                series = qmc.extratemp1
            elif qmc.flagon:
                series = qmc.on_extratemp1
            else:
                return None
            if idx < 0 or idx >= len(qmc.extradevices) or idx >= len(series):
                return None
            if qmc.extradevices[idx] != qmc.tilau_devices["difluid"]["id"]:
                if not self._inlet_binding_warned:
                    self._inlet_binding_warned = True
                    _logd.warning(
                        f"airwave pid: extra device {idx} no longer maps to the AirWave "
                        "— falling back to the reading from the device itself"
                    )
                return None
            return series[idx]
        except (AttributeError, IndexError, KeyError, TypeError):
            return None

    def identify_extrade_devices(self, aw: ApplicationWindow) -> None:
        if aw is not None and aw.qmc is not None:
            for i in range(len(aw.qmc.extradevices)): # fix bug on device identification which is not fixed anymore
                if aw.qmc.extradevices[i] ==  aw.qmc.tilau_devices["difluid"]["id"]: # 25/11/21 bug fix
                    _logd.debug(f" Difluid identify_extrade_devices: found extradevice {i} ")
                    self.extradevicenumber = i
                    break
            self.aw = aw
            self._inlet_binding_warned = False
            self.pilotDamperSlider = aw.eventslidervisibilities[2]==1 and aw.eventslideractions[2]==20 # Damper is checked, verify that it is mapped to Diflui
            _logd.debug(f"airwave mapped to damper slider = {self.pilotDamperSlider}")
        self.omniflux = detect_omniflux_devices(aw)

    # the message received from the Airwave are processed here if they were not issued by a request from our side
    @pyqtSlot(dict)
    def _handle_unsolicited_event(self, parsed_msg: dict) -> None:
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                return
        self.command_running = True
        command = parsed_msg.get('command')
        function = parsed_msg.get('function')
        data = parsed_msg.get('data')
        if function == AirwaveFunctions.DEVICEACTIONS:
            if command == AirwaveCommands.ROASTINGSTAGE:
                self.answerToOmniflux()
            elif data:
                self._adopt_device_change(command, data)
        elif function == AirwaveFunctions.DEVICESETTING and command == AirwaveCommands.HOSTNAME:
                # Device Ask Host Name, this is the first request sent by the roaster and it MUST be answered
                if self.aw is not None and self.aw.bleAirwaveEmulateOmniflux:
                    self.armOmniflux()
                    self.state.holdon = False
                else:
                    self.SendHostName()
                    self.state.holdon = False
        self.command_running =False

    def _adopt_device_change(self, command: int, data: bytes) -> None:
        """Take in a change made on the extractor itself.

        Nobody here asked for this frame, so it is a hand on the device. The
        speed becomes the standing setpoint as well as the confirmed value: the
        duct guard has to restore what the operator chose, not the value it had
        cut down to. The lever follows through the change signal, which moves it
        without dispatching its action — echoing the gesture back would be the
        very loop this driver was fixed to stop.
        """
        try:
            value = int.from_bytes(data, 'big')
            if command == AirwaveCommands.POSITION:
                self.state.mode = AirwaveFanMode(value)
                self.mode_changed_signal.emit(int(self.state.mode))
            elif command == AirwaveCommands.FAN:
                self.state.speed = value
                self.state.speed_requested = value
                self.succionspeed_changed_signal.emit(value)
            elif command == AirwaveCommands.STATUS:
                self.state.state = AirwaveState(value)
                self.state_changed_signal.emit(bool(self.state.state))
            else:
                return
            _logd.info(f"airwave: changed on the device itself — cmd={int(command)} value={value}")
        except (ValueError, TypeError) as e:
            _logd.warning(f"airwave: unreadable device change cmd={command}: {e}")

   # emulate omniflux and send the command to put airwave in slave mode
    def armOmniflux(self):
        _logd.debug("arm omniflux")
        self.omnifluxmode = True
        self.SendHostName("OmniFlux") # force a name recognized as OmniFlux device
        self.send_command("CONTROL AUTO", nohold=True) # in auto mode, Airwave ask for roasting stage and we must answer

    # stop OmniFlux emulation and get back to normal airwave mode
    def disarmOmniflux(self):
        _logd.debug("disarm omniflux")
        self.send_command("CONTROL MANUAL")
        self.omnifluxmode = False

    def currentroastingphase(self)->int:
        if self.aw is None  or len(self.aw.qmc.timeindex)==0:
            return -2 # not started
        i:int=6
        for i in range(6,-1,-1):
            if self.aw.qmc.timeindex[i] > 0:
                break
        if self.aw.qmc.timeindex[RoastingPhase.CHARGE] == -1:
            return -1 # preheating

        return i # return 0 to 6 index

    # answer to omniflux sending the actual roasting phase from Artisan
    # as device is asking for status 10 times per second or so lets use the shortest code to anwser
    def answerToOmniflux(self):
        i = self.currentroastingphase()
        if i == -2:
            _logd.debug("answering omniflux roasting not yet started")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_PREHEAT, False)
        if i == -1:
            _logd.debug("answering omniflux roasting phase is preheat")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_PREHEAT, False)
        if i == 0:
            _logd.debug("answering omniflux roasting phase drying")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_CHARGE, False)
        if i == 1:
            _logd.debug("answering omniflux roasting phase maillard")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_DRY, False)
        if i in [2,3]:
            _logd.debug("answering omniflux roasting phase dev, after FC")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_FCs, False)
        if i in [4,5]:
            _logd.debug("answering omniflux roasting phase dev, after SC")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_SCs, False)
        if i == 6:
            _logd.debug("answering omniflux roasting phase drop, cooling")
            return self.set_state(AirwaveCommands.ROASTINGSTAGE, AirwaveEvents.ROASTING_STAGE_DROP, False)
        _logd.debug(f"answering omniflux phase unknown ({i})")
        return False

    # hostname must be sent as a 30 bytes array padded with 0x00
    def SendHostName(self, default:str="TilauScope"):
        self.command_running = True
        _logd.debug(f"send name={default}")
        byte_series = bytearray(30)
        hostname:str= default
        bytes_to_copy = hostname.encode('utf-8')
        byte_series[:len(bytes_to_copy)] = bytes_to_copy
        self.airwave.send_command(AirwaveFunctions.DEVICESETTING, AirwaveCommands.HOSTNAME, byte_series)
        self.command_running = False

    # sends a command to the Airwave
    def send_command(self, commands:str, nohold:bool=False, origin:str=""):
        #parse commands for
        # FAN 30-100
        # MODE STD/EXT/FAN
        # POWER ON/OFF
        # EVENT PREHEAT,CHARGE,TP,FCS,DE,SCS,DROP (only for Omniflux mode)
        # ONMINFLUX ARM/DISARM

#        _logd.debug(f"difluid interpreter received command {commands}")
        if self.state.holdon and not nohold:
            # Self-heal the control session. If we are actually connected but
            # still holding (e.g. a BLE reconnect where the AirWave never re-requested the
            # hostname, so on_connect/_relay_connected did not clear holdon), complete the
            # handshake now so this command — and every subsequent one — goes through.
            if self.airwave.isconnected():
                self._ensure_control_session()
            if self.state.holdon:
                _logd.warning(f"airwave [{origin or 'direct'}]: {commands!r} dropped, control session not open")
                return ""
        # Held across the whole sequence, not per frame: between a mode change
        # and the speed behind it the device sends the mode's own wind
        # percentage, and that echo is ours, not a hand on the extractor.
        with self.airwave.commanding(
                (AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.POSITION),
                (AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.FAN),
                (AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.STATUS)):
            return self._run_sequence(commands, origin)

    def _run_sequence(self, commands: str, origin: str):
        """Apply every subcommand of `commands`, in order, to the end."""
        messages = self._subcommands(commands)
        # Every subcommand runs: a compound like "MODE STD,FAN 30" must apply the
        # speed too, otherwise the AirWave keeps the mode default (75%). A
        # subcommand that fails never aborts the rest either — "FAN 30,POWER OFF"
        # must still try to stop the extractor when the speed was not confirmed.
        results = []
        mode_seen = False
        last_fan: int | None = None
        for idx, c in enumerate(messages):
            _logd.debug(f"difluid interpreter processing subcommand {c}")
            c1  = c.strip() # remove any blanks at start and end
            c1  = c1.upper() # convert all commands in upper case
            s = c1.split() # now break command in <command> <argument>
            if len(s) != 2: #missing argument
                _logd.debug(f"difluid interpreter no argument found in command {c}")
                continue
            command = s[0]
            if command.startswith("FAN"):
                try:
                    fanspeed = int(s[1])
                except ValueError:
                    results.append(f"fanspeed not a number {s[1]}")
                    continue
                if AirwaveSpeed.MINIMUM <= fanspeed <= AirwaveSpeed.MAXIMUM:
                    last_fan = fanspeed
                    results.append(self.set_succionspeed(fanspeed))
                else:
                    results.append(f"fanspeed out of authorized values {s[1]}")
            elif command.startswith("MODE"):
                if s[1] == "STD":
                    results.append(self.set_mode(AirwaveFanMode.STANDARD))
                elif s[1] == "EXT":
                    results.append(self.set_mode(AirwaveFanMode.EXTREME))
                elif s[1] == "FAN":
                    results.append(self.set_mode(AirwaveFanMode.FAN))
                else:
                    results.append(f"unknown mode {s[1]}")
                    continue
                mode_seen = True
                # The device applies the mode default speed itself; leave it time to
                # settle so a following FAN value is not overwritten by that default.
                if idx < len(messages) - 1:
                    time.sleep(self.MODE_SETTLE_DELAY)
            elif command.startswith("POWER"):
                if s[1] == "ON":
                    results.append(self.set_state(AirwaveCommands.STATUS, AirwaveState.ON))
                elif s[1] == "OFF":
                    results.append(self.set_state(AirwaveCommands.STATUS, AirwaveState.OFF))
                else:
                    results.append(f"unknown state {s[1]}")
            elif command.startswith("EVENT"):
                _logd.debug(f"send {s[1]} map event")
                ev = self.AirwaveEventsMap.get(s[1])
                if ev is None:
                    results.append(f"unknown event {s[1]}")
                else:
                    results.append(self.set_state(ev[0], ev[1], False))
            elif command.startswith("CONTROL"):
                if s[1] == "MANUAL":
                    results.append(self.set_state(AirwaveCommands.AUTOMODE, AirwaveControlMode.AIRWAVE_CONTROL_MANUAL))
                elif s[1] == "AUTO":
                    results.append(self.set_state(AirwaveCommands.AUTOMODE, AirwaveControlMode.AIRWAVE_CONTROL_AUTO))
                else:
                    results.append(f"unknown control mode {s[1]}")
            elif command.startswith("OMNIFLUX"):
                if s[1] == "ARM":
                    self.armOmniflux()
                    results.append("omniflux armed")
                elif s[1] == "DISARM":
                    self.disarmOmniflux()
                    results.append("omniflux disarmed")
                else:
                    results.append(f"command {s[1]} must be arm or disarm")
            else:
                results.append(f"unknown command {command}")
            _logd.info(f"airwave [{origin or 'direct'}]: {c1} -> {results[-1] if results else 'skipped'}")
        # The mode default is applied by the device itself and can land after our
        # speed did. Read the speed back once and re-apply if it slipped; bounded
        # to a single correction, never a loop.
        if mode_seen and last_fan is not None:
            time.sleep(self.MODE_SETTLE_DELAY)
            actual = self.ask_succionspeed()
            if actual != last_fan:
                _logd.warning(
                    f"airwave [{origin or 'direct'}]: fan read back {actual}% after the mode "
                    f"change, re-applying {last_fan}%")
                results.append(self.set_succionspeed(last_fan))
        if not results:
            return "send command, no command found"
        return results[-1]

    # ask from BLE for value
    # answer to qtsignal emission, a command is requested from the main thread
    # syntax from Artisan should be such as airwave("GET FAN"), if "GET" found, only command is sent
    def get_command(self, command:str):
        command  = command.strip() # remove any blanks at start and end
        command  = command.upper() # convert all commands in upper case
        #_logd.debug(f"difluid interpreter get process {command}")
        if command.startswith("FAN"):
            self.state.last_fanspeed = self.ask_succionspeed()
            return self.state.last_fanspeed
        if command.startswith("MODE"):
            return self.ask_mode()
        if command.startswith("STATE"):
            return self.ask_state()
        if command.startswith("SN"):
            return self.ask_device_sn()
        if command.startswith("FW"):
            return self.ask_firmware_version()
        if command.startswith("INLET"):
            t = self.ask_temperatures()
            return t["inlet"]
        if command.startswith("CATALYST"):
            t = self.ask_temperatures()
            return t["catalyst"]
        if command.startswith("TEMP"):
            t = self.ask_temperatures()
            self.state.last_inlet = t['inlet']
            self.state.last_catalyst = t['catalyst']
            return t
        if command.startswith("EVENT"):
            return self.ask_event()
        if command.startswith("CONTROL"):
            return self.ask_control_mode()
        return ""

    # wait for an answer from device for a certain time to push in the queue
    def get_response(self, func: int, cmd: int, timeout: float = 1.0, after: float = 0.0) -> dict|None:
        """Reply to (func, cmd) stored after ``after``, or None on timeout."""
        return self.airwave.await_response(func, cmd, after, timeout)

    def _request(self, function: int, command: int, payload: bytes = b'',
                 timeout: float | None = None) -> dict | None:
        """Send one request and wait for the reply that answers it.

        The stamp is taken before the write so a reply already in hand cannot
        pass for this one, and the reply is claimed so reading a value is not
        mistaken for somebody changing it on the extractor.
        """
        with self.airwave.commanding((function, command)):
            mark = time.monotonic()
            if self.airwave.send_command(function, command, payload, True) != "ok":
                return None
            return self.airwave.await_response(
                function, command, mark, self.CONFIRM_TIMEOUT if timeout is None else timeout)
    #   getters

    def ask_device_sn(self):
        self.command_running = True
        self.airwave.send_command(AirwaveFunctions.DEVICEINFO, AirwaveCommands.SERIALNUMBER, b'', True)
        response = self.get_response(AirwaveFunctions.DEVICEINFO, AirwaveCommands.SERIALNUMBER)
        self.state.sn = str(response['data'], 'utf-8') if response and response["valid"] else ""
        self.command_running = False
        return self.state.sn

    def ask_device_model(self):
        self.command_running = True
        self.airwave.send_command(AirwaveFunctions.DEVICEINFO, AirwaveCommands.DEVICEMODEL, b'', True)
        response = self.get_response(AirwaveFunctions.DEVICEINFO, AirwaveCommands.DEVICEMODEL)
        self.state.model = str(response['data'], 'utf-8') if response and response["valid"] else ""
        self.command_running = False
        return self.state.model

    def ask_firmware_version(self):
        self.command_running = True
        self.airwave.send_command(AirwaveFunctions.DEVICEINFO, AirwaveCommands.FIRMWARE, b'', True)
        response = self.get_response(AirwaveFunctions.DEVICEINFO, AirwaveCommands.FIRMWARE)
        self.state.firmware = str(response['data'], 'utf-8') if response and response["valid"] else ""
        self.command_running = False
        return self.state.firmware

    def ask_state(self):
        self.command_running = True
        response = self._request(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.STATUS)
        if response and response["valid"] and response['data']:
            self.state.state = AirwaveState(int.from_bytes(response['data'], 'big'))
            self.command_running = False
            return self.state.state
        self.command_running = False
        return -1

    def ask_mode(self):
        self.command_running = True
        response = self._request(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.POSITION)
        if response and response["valid"] and response['data']:
            self.state.mode = AirwaveFanMode(int.from_bytes(response['data'], 'big'))
            self.command_running = False
            return self.state.mode
        self.command_running = False
        return -1

    def ask_succionspeed(self):
        self.command_running = True
        response = self._request(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.FAN)
        if response and response["valid"] and response['data']:
            self.state.speed = int.from_bytes(response['data'], 'big')
            self.command_running = False
            return self.state.speed
        self.command_running = False
        return -1

    def ask_temperatures(self) -> dict:
        self.command_running = True
        # Freshness matters most here: this runs every sampling tick and feeds the
        # duct guard. A cached reply would keep reporting the last good reading
        # long after the link went down.
        response = self._request(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.TEMPERATURE)
        #_logd.debug(f"ask_temperatures response={response['valid']} data={response['data']}")
        if response and response["valid"] and response['data']:
            try:
                catalyst, inlet = struct.unpack('<ff', response['data'])
                self.command_running = False
                res = {
                    'inlet': round(inlet,1),
                    'catalyst': round(catalyst,1)
                }
                self.state.last_inlet = res['inlet']
                self.state.last_catalyst = res['catalyst']
                return res
            except struct.error:
                #_logd.error(f"unpacking packet error: {e}")
                pass
        self.command_running = False
        return {
            'inlet': -1.0,
            'catalyst': -1.0
        }

    def ask_event(self):
        self.command_running = True
        response = self.get_response(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.ROASTINGSTAGE)
        if response and response["valid"] and response['data']:
            return int.from_bytes(response['data'], 'big')
        self.command_running = False
        return -1

    def ask_control_mode(self):
        self.command_running = True
        response = self._request(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.AUTOMODE)
        if response and response["valid"] and response['data']:
            self.command_running = False
            return int.from_bytes(response['data'], 'big')
        self.command_running = False
        return -1

    # setters
    def set_state(self, subcommand:AirwaveCommands = AirwaveCommands.STATUS, value: int = 0, answer:bool = True):
        allowed = {AirwaveCommands.ROASTINGSTAGE: AirwaveEvents,
                   AirwaveCommands.AUTOMODE: AirwaveControlMode}.get(subcommand, AirwaveState)
        if value is None or value not in allowed:
            return False
        self.command_running = True
        payload = struct.pack('B', value)
        mark = time.monotonic()
        r = self.airwave.send_command(AirwaveFunctions.DEVICEACTIONS, subcommand, payload, answer)
        # Only the running state is confirmed here. The roasting-stage answers go
        # out through this same setter several times a second and must not wait,
        # and their reply is not a state at all.
        if r == "ok" and answer and subcommand == AirwaveCommands.STATUS:
            reply = self.airwave.await_response(
                AirwaveFunctions.DEVICEACTIONS, subcommand, mark, self.CONFIRM_TIMEOUT)
            if reply is None:
                r = "timeout: no power confirmation"
            else:
                self.state.state = AirwaveState(int.from_bytes(reply['data'], 'big'))
                self.state_changed_signal.emit(bool(self.state.state))
                if int(self.state.state) != int(value):
                    r = f"mismatch: power {int(self.state.state)} != {int(value)}"
        _logd.debug(f"set state return = {r}")
        self.command_running = False
        return r

    def set_mode(self, value: int):
        if value is None or value not in AirwaveFanMode:
            return False
        self.command_running = True
        payload = struct.pack('B', value)
        mark = time.monotonic()
        r = self.airwave.send_command(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.POSITION, payload)
        if r == "ok":
            reply = self.airwave.await_response(
                AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.POSITION, mark, self.CONFIRM_TIMEOUT)
            if reply is None:
                r = "timeout: no mode confirmation"
            else:
                self.state.mode = AirwaveFanMode(int.from_bytes(reply['data'], 'big'))
                self.mode_changed_signal.emit(int(self.state.mode))
                if int(self.state.mode) != int(value):
                    r = f"mismatch: mode {int(self.state.mode)} != {int(value)}"
        self.command_running = False
        return r

    def set_succionspeed(self, value: int):
        if value is None or value < AirwaveSpeed.MINIMUM or value > AirwaveSpeed.MAXIMUM:
            return False
        self.command_running = True
        self.state.speed_requested = int(value)
        payload = struct.pack('B', value)
        r = "not sent"
        for attempt in range(self.FAN_CONFIRM_RETRIES + 1):
            mark = time.monotonic()
            r = self.airwave.send_command(AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.FAN, payload)
            if r != "ok":
                break
            reply = self.airwave.await_response(
                AirwaveFunctions.DEVICEACTIONS, AirwaveCommands.FAN, mark, self.CONFIRM_TIMEOUT)
            if reply is None:
                r = "timeout: no speed confirmation"
            else:
                self.state.speed = int.from_bytes(reply['data'], 'big')
                self.succionspeed_changed_signal.emit(int(self.state.speed))
                if self.state.speed == int(value):
                    r = "ok"
                    break
                r = f"mismatch: speed {self.state.speed} != {value}"
            if attempt < self.FAN_CONFIRM_RETRIES:
                _logd.warning(f"airwave: fan {value}% not confirmed ({r}) — retrying")
        self.command_running = False
        return r

    def update_artisan_slider(self, slider_idx: int, value: int):
        """Move the lever and dispatch its slider action (simulator / display only).

        Unlike updateArtisanDamperSlider this records no roast event; the action
        is still fired, which is what actuates the device outside the simulator.
        """
        if not self.aw: return

        # Mise à jour synchronisée avec l'historique Artisan
        self.aw.block_quantification_sampling_ticks[slider_idx] = self.aw.sampling_ticks_to_block_quantifiction
        self.aw.moveslider(slider_idx, value)
        self.aw.extraeventsactionslastvalue[slider_idx] = self.aw.eventslidervalues[slider_idx]
        self.aw.fireslideraction(slider_idx)

    def updateArtisanDamperSlider(self, slidernr:int, slidervalue:int, fire_action:bool=True) -> int:
            # Named, not a bare value and unit: the plain shape is what a gesture on
            # a control writes, and a channel the extractor drove itself would
            # otherwise be read back afterwards as something the operator did.
            # The shared transaction owns the event codec, the quantifier block and
            # the clamp; it records through a queued signal, so the profile lock we
            # are running under (the guard is called from sample_processing) is not an
            # issue and no longer has to be bypassed.
            # fire_action=False moves and records the lever without dispatching the
            # slider action, whose Airwave write would block the GUI thread; the
            # caller then sends the value itself, asynchronously.
            # '{0}' est la place de la valeur appliquée : sans elle l'événement
            # enregistré ne portait que le nom du canal.
            self.aw.applyTilauSliderCommand(slidernr, slidervalue, fire_action, f'Airwave S{slidernr}:{{0}}%')
            # moveslider() clamps to the slider limits: send what was applied.
            try:
                return int(self.aw.eventslidervalues[slidernr])
            except (AttributeError, IndexError, TypeError, ValueError):
                return slidervalue

    def _get_omniflux_live(self)-> tuple[float, float]:
        # read registers from modbus if connected
        aw = self.aw
        if aw is None or not self.omniflux.valid:
            return -1.0, -1.0

        ci = self.omniflux.color_device_idx
        ri = self.omniflux.roc_device_idx
        qmc = aw.qmc
        try:
            color_series = qmc.extratemp1[ci][-1] if qmc.flagstart else qmc.RTextratemp1[ci]
            agtron = color_series if color_series else -1.0
        except (IndexError, TypeError):
            agtron = -1.0
        try:
            roc_series = qmc.extratemp2[ri][-1] if qmc.flagstart else qmc.RTextratemp2[ri]
            roc = roc_series if roc_series else -1.0
        except (IndexError, TypeError):
            roc = -1.0
        return agtron, roc

    # ── Garde thermique de la gaine ──────────────────────────────────────────

    def _duct_limit(self) -> float:
        """Limite de gaine retenue : la plus basse des valeurs enregistrees.

        Le reglage est stocke par phase, mais la protection ne depend pas de la
        phase — on prend donc la plus protectrice.
        """
        limits: list[float] = []
        params = getattr(self.aw, "bleAirwavepidparms", None) if self.aw is not None else None
        if isinstance(params, dict):
            for row in params.values():
                try:
                    v = float(row[4])
                except (IndexError, TypeError, ValueError):
                    continue
                if 40.0 <= v <= 200.0:
                    limits.append(v)
        return min(limits) if limits else self.DUCT_LIMIT_DEFAULT

    def duct_overheat_guard(self, simulator: bool = False) -> None:
        """Ralentit l'extracteur quand la gaine chauffe. Ne l'accelere jamais.

        Tourne dans le tick d'echantillonnage d'Artisan : aucune exception ne
        doit s'en echapper, sinon le reste du tick est abandonne.
        """
        try:
            self._duct_overheat_guard(simulator)
        except Exception as e:  # noqa: BLE001
            _logd.warning(f"airwave duct guard: tick aborted: {e}")

    def _duct_overheat_guard(self, simulator: bool) -> None:
        if simulator or self.aw is None or not self.airwave.isconnected():
            return
        # A stopped extractor takes no speed: each one would come back
        # unconfirmed. The cut in hand is kept, so a restart on the cut speed
        # still returns to the setting it was taken from.
        if self.state.state == AirwaveState.OFF:
            return

        # Lecture inlet — la serie extra passe par comm.AIRWAVE, qui la convertit
        # en °F quand qmc.mode vaut 'F' ; state.last_inlet vient brut du device.
        inlet = float(self.state.last_inlet)
        series = self._airwave_inlet_series()
        if series:
            inlet = (fromFtoCstrict(series[-1])
                     if self.aw.qmc.mode == 'F' else float(series[-1]))
        if inlet <= 0.0:
            return

        limit = self._duct_limit()
        # The setpoint, not the confirmation: the confirmation lands a moment
        # later, and the guard would read its own cut as a gesture on the lever
        # and rebase on the value it had just taken away.
        current = int(self.state.speed_requested) or int(self.state.last_fanspeed)
        if current <= 0:
            return

        # Le plan ou l'operateur a bouge le ventilateur : c'est la nouvelle valeur
        # a restituer, et la coupe repart de la.
        if self._duct_last_sent is None or current != self._duct_last_sent:
            self._duct_base = current

        # Retrait vise : 1 point par degre au-dessus de la limite, borne.
        if inlet >= limit:
            wanted = min(self.DUCT_MAX_CUT_PCT, inlet - limit)
        elif inlet <= limit - self.DUCT_HYSTERESIS_C:
            wanted = 0.0
        else:
            wanted = self._duct_cut          # zone morte : on ne bouge pas

        if wanted == 0.0 and self._duct_cut == 0.0:
            self._duct_last_sent = None
            self._duct_last_target = None
            return

        step = float(getattr(self.aw, 'bleAirwavepidRamp', 2) or 2)
        if wanted > self._duct_cut:
            self._duct_cut = min(wanted, self._duct_cut + step)
        elif wanted < self._duct_cut:
            self._duct_cut = max(wanted, self._duct_cut - step)

        base = self._duct_base if self._duct_base is not None else current
        target = int(max(float(AirwaveSpeed.MINIMUM),
                         min(float(AirwaveFanLimits.MAXIMUM), base - self._duct_cut)))
        if target == self._duct_last_target:
            return

        applied = target
        if self.pilotDamperSlider:
            applied = self.updateArtisanDamperSlider(2, target, fire_action=False)
        self.dispatch_async(f"FAN {applied}", origin=self.DUCT_ORIGIN)
        # Ce qui est memorise est ce qui a ete ENVOYE, pas ce qui etait vise : le
        # slider borne la valeur, et l'appareil renvoie son echo sur `applied`.
        # Memoriser `target` ferait relire cet echo comme un geste operateur et
        # rebaserait _duct_base sur la valeur deja coupee — le ventilateur ne
        # remonterait jamais a sa consigne d'origine a la releve de la garde.
        self.state.speed_requested = applied
        self.state.last_fanspeed = applied
        self._duct_last_sent = applied
        self._duct_last_target = target
        _logd.info(
            f"airwave duct guard: inlet={inlet:.1f}C limit={limit:.1f}C "
            f"cut={self._duct_cut:.1f} base={base} => fan={applied}%"
        )
        if self._duct_cut == 0.0:
            self._duct_last_sent = None
            self._duct_last_target = None

    def reset_pid_state(self) -> None:
        """Clear the per-roast extractor state (speed, guard).

        The device object outlives a roast: without this a duct cut taken on one
        roast would carry into the next.
        """
        self.state.last_fanspeed = AirwaveSpeed.MINIMUM
        self._duct_cut = 0.0
        self._duct_base = None
        self._duct_last_sent = None
        self._duct_last_target = None
        with self._pid_cv:
            self._pid_pending.clear()


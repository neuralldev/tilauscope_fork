#
# ABOUT
# Lebrew RoastSee C1 support for Artisan

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

# dialog and code gathered from my own device and reverse eng.

# AUTHOR
# TiLau 2025

#  Service: bc41e50b-91cd-4916-9152-02d52446ac3a
#  Characteristic: 0000ff01-0000-1000-8000-00805f9b34fb ['read', 'write']
#  Characteristic: 0000ff02-0000-1000-8000-00805f9b34fb ['read', 'write']
#  Characteristic: 0000ff03-0000-1000-8000-00805f9b34fb ['read', 'write', 'notify']

import logging
from enum import IntEnum,StrEnum
from typing import Final
import queue
import struct
import time
import re

from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import
from bleak.backends.device import BLEDevice  # pylint: disable=unused-import

from PyQt6.QtCore import pyqtSignal, QObject # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtCore import pyqtSlot

from artisanlib.ble_port import ClientBLE

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

# RoastSee C1 support
C1_PREFIX= "RoastSee C1" # all C1 devices start with this name
HEADER1:Final[int]      = 0x55 # this is the header byte for C1 data exchange
# RoastSee AquaGauge
AG_PREFIX = "RoastSee AquaGauge"

class C1UUID(StrEnum):
    C1_SERVICE_UUID = "bc41e50b-91cd-4916-9152-02d52446ac3a" # service UUID to discover devices 3aac4624d50252911649cd910be541bc
    C1_DIALOG_UUID  = "0000ff03-0000-1000-8000-00805f9b34fb" # clear text channel characteristic

class AGUUID(StrEnum):
    AG_SERVICE_UUID = "000000ff-0000-1000-8000-00805f9b34fb" # service UUID to discover devices
    AG_DIALOG_UUID  = "0000ff01-0000-1000-8000-00805f9b34fb" # clear text channel characteristic

# LebrewBLE class for BLE communication with the Lebrew RoastSee C1 device

class C1MessageType(IntEnum):
    READ_COLOR = 1 # 0x01

class C1Protocol:
    def parse_full_message(self, payload: bytearray) -> dict:
        if len(payload) < 3 or payload[0] != C1MessageType.READ_COLOR:
            return {'valid': False, 'error': 'Invalid length'}
        (f, d) = struct.unpack('>BH', payload[:3])
        return {"valid": True, "function":int(f), "data":float(d)}

    def build_full_message(self, function: int, command: int, data: bytes = b'') -> bytes:
        return struct.pack('BB', function, command) + data

def _drop(signal) -> None:
    """Disconnect every slot from *signal*, tolerating none being connected.

    PyQt raises TypeError from a no-argument disconnect() when the signal has
    no slots left. Callers of stop() routinely disconnect their own slots
    first, so that is the normal case — and an exception here used to abort
    stop() before it reached the BLE client, leaving the scan running.
    """
    try:
        signal.disconnect()
    except TypeError:
        pass


class LebrewC1BLE(ClientBLE, C1Protocol): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()     # issued on connect
    disconnected_signal = pyqtSignal()  # issued on disconnect
    color_changed_signal = pyqtSignal(float)  # issued on color change

    def __init__(self,  device_uuid:str, decimals:int=1):
        super().__init__()
        # handlers
        self.responses: queue.Queue = queue.Queue() # buffer for notifications
        self._is_stopping = False  # Drapeau d'arrêt
        self.color_read: float = 0.0
        self.rounding: int = decimals

        self.setLogging(True)
        self.add_device_description(C1UUID.C1_SERVICE_UUID,"")
        self.add_notify(C1UUID.C1_DIALOG_UUID, self.notify_callback)
        self.add_read(C1UUID.C1_DIALOG_UUID, C1UUID.C1_DIALOG_UUID)
        self.add_write(C1UUID.C1_DIALOG_UUID, C1UUID.C1_DIALOG_UUID)
        self.start(case_sensitive=False, address=device_uuid)

    def setLogging(self, b:bool) -> None:
        self._logging = b

    def notify_callback(self, _sender:'BleakGATTCharacteristic', data:bytearray) -> None:
        parsed_msg = self.parse_full_message(data)
        if parsed_msg.get('valid'):
            value = round(parsed_msg['data'] / 100.0, self.rounding)
            self.color_read = value
            self.color_changed_signal.emit(value)
        else:
            _logd.debug("invalid message")

    def bleStop(self):
        self.stop()
        # now wait for all the ble async queues to flush before killing the object
        while self._ble_client is not None:
            time.sleep(0.1)

    def isconnected(self) -> bool:
        c = self.connected() # just retrieve UUID is enough to check for connection
        return c[0] is not None

    def on_connect(self) -> None:
        self.is_connected = True
        self.connected_signal.emit()

    def on_disconnect(self) -> None:
        self.is_connected = False
        if not self._is_stopping: # N'émet que si on ne ferme pas volontairement
            self.disconnected_signal.emit()

    def stop(self):
        self._is_stopping = True
        # Vider la queue pour débloquer d'éventuels threads en attente
        while not self.responses.empty():
            try: self.responses.get_nowait()
            except: break
        super().stop()

    def send_command(self, function: int, command: int, data: bytes = b'')->bool:
        if not self.isconnected():
            return False
        msg = self.build_full_message(function, command, data)
        try:
            self.send(msg, True, C1UUID.C1_DIALOG_UUID)
            return True
        except Exception as e:
            _log.error(f"error occurred {e}")
            return False

class LebrewColorChecker(QObject): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    color_changed_signal = pyqtSignal(float) # Transmet la valeur de la couleur

    def __init__(self,  name:str):
        super().__init__()
        self.c1 = LebrewC1BLE(name)
        self.c1.connected_signal.connect(self._relay_connected)
        self.c1.disconnected_signal.connect(self._relay_disconnected)
        self.c1.color_changed_signal.connect(self._on_color_changed)

    def _relay_connected(self):
        self.connected_signal.emit()

    def _relay_disconnected(self):
        self.disconnected_signal.emit()

    @pyqtSlot(float)
    def _on_color_changed(self, color: float):
        self.color_changed_signal.emit(color)

    def stop(self):
        _drop(self.color_changed_signal)
        _drop(self.connected_signal)
        _drop(self.disconnected_signal)
        self.c1.stop()

# LebrewBLE class for BLE communication with the Lebrew AquaGauge device

class AGMessageType(IntEnum):
    READ_WA = 1 # 0x01
    SIGNATURE = 2
    ERROR = 99

class AGProtocol:

    EXPECTED_SIGNATURE = bytearray(b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e')

    # lebrew Aqua gauge sends a signature message on connect, we can use it to validate that we are talking to the right device and not some random BLE device with a similar name
    def validate_signature(self, data):
        if data == self.EXPECTED_SIGNATURE:
            return True
        else:
            return False

    # lebrew Aqua gauge sends data in the format "aw=0.85,dew=12.3" as a bytearray, we need to parse it to extract the water activity and dew point values
    def parse_lebrew_data(self, raw_data):
        # Conversion du bytearray en string et retrait des caractères nuls
        try:
            line = raw_data.decode('ascii').strip('\x00')

            match = re.search(r"aw=([-+]?\d*\.\d+|\d+),dew=([-+]?\d*\.\d+|\d+)", line)

            if match:
                aw_val = float(match.group(1))
                dew_val = float(match.group(2))

                # Validation de cohérence simple
                if 0 <= aw_val <= 1.0:
                    return {"valid": True, "type": AGMessageType.READ_WA, "aw": aw_val, "dew": dew_val}
                else:
                    _logd.warning(f"Alerte : Valeur aw hors norme : {aw_val}")

        except Exception as e:
            _logd.debug(f"Erreur de lecture : {e}")

        return {"valid": False, "type": AGMessageType.ERROR, "error": "Invalid data format"}

    def parse_full_message(self, payload: bytearray) -> dict:
        if self.validate_signature(payload):
            return {'valid': True, 'type': AGMessageType.SIGNATURE, 'data': payload}
        return self.parse_lebrew_data(payload)

    def build_full_message(self, function: int, command: int, data: bytes = b'') -> bytes:
        return struct.pack('BB', function, command) + data

class LebrewAGBLE(ClientBLE, AGProtocol): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()     # issued on connect
    disconnected_signal = pyqtSignal()  # issued on disconnect
    wa_changed_signal = pyqtSignal(float)  # issued on water activity change

    def __init__(self,  device_uuid:str, decimals:int=2):
        super().__init__()
        # handlers
        self.responses: queue.Queue = queue.Queue() # buffer for notifications
        self._is_stopping = False  # Drapeau d'arrêt
        self.water_activity_read: float = 0.0
        self.wa_changed : bool = False
        self.rounding: int = decimals
        self._device_uuid: str = device_uuid
        self._known_device: 'BLEDevice | None' = None  # fourni par TilauBLEScanner
        self._connecting: bool = False  # verrou anti-double connexion
        _log.info(f"LebrewAGBLE: Initializing with device UUID: {device_uuid} and rounding: {decimals}")
        self.setLogging(True)
        self.add_device_description(AGUUID.AG_SERVICE_UUID,"")
        self.add_notify(AGUUID.AG_DIALOG_UUID, self.notify_callback)
        self.add_read(AGUUID.AG_DIALOG_UUID, AGUUID.AG_DIALOG_UUID)
        self.add_write(AGUUID.AG_DIALOG_UUID, AGUUID.AG_DIALOG_UUID)
        # NE PAS appeler start() ici — TilauBLEScanner fournira le device
        # via on_devices_found(). Cela évite un scan BLE concurrent au démarrage.

    def setLogging(self, b:bool) -> None:
        self._logging = b

    def notify_callback(self, _sender:'BleakGATTCharacteristic', data:bytearray) -> None:
        parsed_msg = self.parse_full_message(data)
        if parsed_msg['type'] == AGMessageType.SIGNATURE and parsed_msg.get('valid'):
            _log.info("LebrewAGBLE: Device signature received, device is authentic.")
            return
        if parsed_msg.get('valid') and parsed_msg['type'] == AGMessageType.READ_WA:
            self.water_activity_read = parsed_msg['aw']
            _logd.debug(f"got {self.water_activity_read}")
            self.wa_changed_signal.emit(parsed_msg['aw'])
        else:
            _logd.debug("invalid message from lebrew aqua gauge")

    def bleStop(self):
        self.stop()
        # now wait for all the ble async queues to flush before killing the object
        while self._ble_client is not None:
            time.sleep(0.1)

    def isconnected(self) -> bool:
        c = self.connected() # just retrieve UUID is enough to check for connection
        return c[0] is not None

    def connect_direct(self, bd: 'BLEDevice') -> None:
        """Connexion directe via ble.connect_known() — bypass scan."""
        if self._connecting or self._running:
                return
        self._connecting = True
        self._known_device = bd
        _logd.debug(f"LebrewAGBLE: connect_direct to {bd.name} {bd.address}")
        self.start(case_sensitive=False, address=self._device_uuid, connect_timeout=10)
        self._connecting = False

    def scan_and_connect_override(
            self,
            device_descriptions: tuple[dict,dict], # upstream tuple (was dict)
            blacklist: set,
            case_sensitive: bool,
            disconnected_callback,
            scan_timeout: float,
            connect_timeout: float,
            address: str | None = None,
    ):
        from artisanlib.ble_port import ble
        if self._known_device is not None:
            bd = self._known_device
            self._known_device = None
            return ble.connect_known(
                bd, AGUUID.AG_SERVICE_UUID, disconnected_callback, connect_timeout
            )
        from artisanlib.ble_port import ble
        return ble.scan_and_connect(
            device_descriptions, blacklist, case_sensitive,
            disconnected_callback, scan_timeout, connect_timeout, address
        )

    def on_connect(self) -> None:
        self.is_connected = True
        _log.info("LebrewAGBLE: Connected to device")
        self.connected_signal.emit()

    def on_disconnect(self) -> None:
        self.is_connected = False
        _log.info("LebrewAGBLE: Disconnected from device")
        if not self._is_stopping: # N'émet que si on ne ferme pas volontairement
            self.disconnected_signal.emit()

    def stop(self):
        self._is_stopping = True
        # Vider la queue pour débloquer d'éventuels threads en attente
        while not self.responses.empty():
            try: self.responses.get_nowait()
            except: break
        super().stop()

    def send_command(self, function: int, command: int, data: bytes = b'')->bool:
        if not self.isconnected():
            return False
        msg = self.build_full_message(function, command, data)
        try:
            self.send(msg, True, AGUUID.AG_DIALOG_UUID)
            return True
        except Exception as e:
            _log.error(f"error occurred {e}")
            return False

class LebrewWaterActivityChecker(QObject): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    wa_changed_signal = pyqtSignal(float) # Transmet la valeur de la couleur

    def __init__(self,  name:str):
        super().__init__()
        self.ag = LebrewAGBLE(name)
        self.ag.connected_signal.connect(self._relay_connected)
        self.ag.disconnected_signal.connect(self._relay_disconnected)
        self.ag.wa_changed_signal.connect(self._on_wa_changed)

    def _relay_connected(self):
        self.connected_signal.emit()

    def _relay_disconnected(self):
        self.disconnected_signal.emit()

    @pyqtSlot(float)
    def _on_wa_changed(self, wa: float):
        self.wa_changed_signal.emit(wa)

    @pyqtSlot(list)
    def on_devices_found(self, devices: list) -> None:
        """Slot branché sur TilauBLEScanner.devices_found; filtre sur l'UUID connue du AquaGauge."""
        if self.ag._connecting or self.ag._running:
            return
        for bd, _ad in devices:
            if bd.address.upper() == self.ag._device_uuid.upper():
                _log.info(f"LebrewWaterActivityChecker: device spotted — {bd.name} {bd.address}")
                self.ag.connect_direct(bd)
                return

    def stop(self):
        _drop(self.wa_changed_signal)
        _drop(self.connected_signal)
        _drop(self.disconnected_signal)
        self.ag.stop()
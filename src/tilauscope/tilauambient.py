#
# ABOUT
# Tilauscope ambient service BLE5, requires ESP32 and BME-280
# please flash tilauscope-ambient.bin and run

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

# all code is new and has not been copied from any existing project

# AUTHOR
# TiLau 2025


#define SERVICE_UUID        "f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c01"
#define ENV_DATA_CHAR_UUID  "f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c05"
#define ENV_AUDIO_UUIS      "f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c04" 

import logging
from enum import StrEnum
from typing import Final, TYPE_CHECKING
import queue
import struct
import time
import threading  # à ajouter en tête de fichier avec les autres imports

if TYPE_CHECKING:
    from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import

from PyQt6.QtCore import pyqtSignal, QDateTime, QObject # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtCore import QMutex, QMutexLocker

from artisanlib.ble_port import ClientBLE
from artisanlib.main import ApplicationWindow # pylint: disable=unused-import

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

TILAUAMBIENT_PREFIX= "TLSCAM" # all devices start with this name

class TILAUAMBIENT_UUID(StrEnum): 
    TILAU_AMBIENT_SERVICE_UUID  = "f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c01" # service UUID to discover devices 3aac4624d50252911649cd910be541bc
    TILAU_AMBIENT_DIALOG_UUID  = "f3b6a2a0-8c4e-4e1f-9c2d-1a7f5b9a1c05" # clear text channel characteristic, read 
    TILAU_AUDIO_DIALOG_UUID    = "f3b6e2a0-8c4e-4e1f-9c2d-1a7f5b9a1c04" # clear text channel characteristic, read write

class TilauAmbientData:
    __slots__ = ('temperature', 'humidity', 'pressure', 'altitude', 'valid')
  
    temperature:float
    humidity:float
    pressure:float
    altitude:float
    valid:bool
    
    def __init__(self, t:float, h:float, p:float, a:float, v:bool):
        self.temperature = t
        self.humidity = h
        self.pressure = p
        self.altitude = a
        self.valid = v

class TilauAudioData:
    __slots__ = ('counter', 'validity')

    counter:int
    validity:bool
    
    def __init__(self, c:int, v:bool):
        self.counter = c
        self.validity = v

class TilauBaseProtocol:
    TPREAMBLE: Final = b'\x55\x55'
    TTRAILER:  Final = b'\xaa\xaa'

    @staticmethod
    def calculate_checksum(data: bytes | bytearray) -> int:
        return sum(data) & 0xFF  # & 0xFF est plus rapide que % 256


class TilauAmbientProtocol(TilauBaseProtocol):
    # EnvData ESP32 packed (17 bytes total):
    #   [0:2]   header    uint16  0x5555
    #   [2:4]   temp_x10  int16   signed (températures négatives possibles)
    #   [4:6]   hum_x10   int16   signed
    #   [6:10]  press_x10 int32   signed
    #   [10:14] alt_x10   int32   signed
    #   [14]    checksum  uint8
    #   [15:17] footer    uint16  0xAAAA
    # Checksum couvre payload[2:14] = 12 bytes de données
    _STRUCT = struct.Struct('<hhiiB')  # h=int16 signed, i=int32 signed — supports negative temperatures

    def parse_full_message(self, payload: bytearray) -> TilauAmbientData:
        if len(payload) < 17:
            _logd.warning(f"ambient payload trop court: {len(payload)} < 17")
            return TilauAmbientData(0, 0, 0, 0, False)

        # Checksum calculé sur les 12 bytes de données (sans header, checksum, footer)
        calculated_checksum = self.calculate_checksum(payload[2:14])

        # Unpack : 13 bytes = temp(2) + hum(2) + press(4) + alt(4) + checksum(1)
        temp_x10, hum_x10, press_x10, alt_x10, received_checksum = self._STRUCT.unpack(payload[2:15])

        if received_checksum != calculated_checksum:
            _logd.warning(f"ambient: checksum KO recu=0x{received_checksum:02X} calcule=0x{calculated_checksum:02X}")
            return TilauAmbientData(0, 0, 0, 0, False)

        header = struct.unpack('<H', payload[0:2])[0]
        footer = struct.unpack('<H', payload[15:17])[0]
        if header != 0x5555 or footer != 0xAAAA:
            _logd.warning(f"ambient: header/footer invalides h=0x{header:04X} f=0x{footer:04X}")
            return TilauAmbientData(0, 0, 0, 0, False)

        # Temperature plausibility gate: ambient roasting band -10..50 °C.
        # Out-of-band -> whole reading invalid (clean gate for sampling + plan consumer).
        if not (-100 <= temp_x10 <= 500):
            _logd.warning(f"ambient: temp out of band {temp_x10 / 10.0:.1f}C, reading dropped")
            return TilauAmbientData(0, 0, 0, 0, False)

        temp_float:float  = round(temp_x10  / 10.0, 1)
        hum_float:float   = round(hum_x10   / 10.0, 1) if 0 <= hum_x10 <= 1000 else 0.0
        press_float:float = round(press_x10 / 10.0, 1) if press_x10 > 0 else 0.0
        # alt_x10 est l'altitude brute calculée par readAltitude() côté ESP32.
        # Sa précision dépend de SEALEVELPRESSURE_HPA dans main.cpp (paramètre météo du jour).
        # On la transmet telle quelle sans filtrage arbitraire.
        alt_float:float   = round(alt_x10 / 10.0, 1)

        _logd.debug(f"ambient parsed: temp={temp_float} hum={hum_float} press={press_float} alt={alt_float}")
        return TilauAmbientData(temp_float, hum_float, press_float, alt_float, True)
    
    def build_full_message(self, function: int, command: int, data: bytes = b'') -> bytes:
        length = len(data)
        payload = struct.pack('BBB', function, command, length) + data
        checksum = (sum(payload) & 0xFF)
        return self.TPREAMBLE + payload + struct.pack('B', checksum) + self.TTRAILER

class TilauAudioProtocol(TilauBaseProtocol):
    # AudioData ESP32 (packed) :
    #   header      uint16  2 B   0x5555
    #   crack_count int32   4 B
    #   checksum    uint8   1 B
    #   footer      uint16  2 B   0xAAAA
    #   Total                9 B
    AUDIO_STRUCT      = struct.Struct('<HiBH')  # H=header i=int32_counter B=checksum H=footer
    AUDIO_STRUCT_SIZE = 9

    def parse_full_message_audio(self, payload: bytearray) -> TilauAudioData:
        # garde sur la taille avant tout acces
        if len(payload) < self.AUDIO_STRUCT_SIZE:
            _logd.warning(f"audio payload trop court: {len(payload)} < {self.AUDIO_STRUCT_SIZE}")
            return TilauAudioData(0, False)

        header, counter, received_checksum, footer = self.AUDIO_STRUCT.unpack(payload[:self.AUDIO_STRUCT_SIZE])

        if header != 0x5555 or footer != 0xAAAA:
            _logd.warning(f"audio: header/footer invalides h=0x{header:04X} f=0x{footer:04X}")
            return TilauAudioData(0, False)

        # checksum calcule sur les 4 octets de crack_count (payload[2:6], int32)
        calculated_checksum = self.calculate_checksum(payload[2:6])
        if received_checksum != calculated_checksum:
            _logd.warning(f"audio: checksum KO recu=0x{received_checksum:02X} calcule=0x{calculated_checksum:02X}")
            return TilauAudioData(0, False)

        return TilauAudioData(counter, True)
    
    def build_full_message_audio(self, command: int) -> bytes:
        payload = struct.pack('<h', command)
        checksum = (sum(payload) & 0xFF)
        return self.TPREAMBLE + payload + struct.pack('B', checksum) + self.TTRAILER

# Commandes audio (miroir des #define C)
COMMAND_RUNCALIBRATION  = 0x0000   # phase 1 : machine a vide (avant charge)
COMMAND_START_SAMPLING  = 0x0001
COMMAND_STOP_SAMPLING   = 0x0002
COMMAND_CALIBRATIONSTATE= 0x0003
COMMAND_SAMPLINGSTATUS  = 0x0004
COMMAND_GETCRACKCOUNTER = 0x0005
COMMAND_RUN_MAILLARD_CALIBRATION = 0x0006  # phase 2 : grains dans le tambour, apres DE
COMMAND_AUDIO_SELFTEST  = 0x0007
COMMAND_DEBUG_ON        = 0x0010
COMMAND_DEBUG_OFF       = 0x0011
# Les anciennes COMMAND_RAISERATIO/DECREASERATIO (0x0006/0x0007, 0x0506/0x0507)
# ont ete retirees du firmware : 0x0006 et 0x0007 y sont desormais la calibration
# MAILLARD et l'auto-test d'acquisition. Ne pas les reintroduire.
        
# Ambient class for BLE communication with the ESP32 + BME 280 probe
class TilauAmbientBLE(ClientBLE, TilauAmbientProtocol, TilauAudioProtocol): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()     # issued on connect
    disconnected_signal = pyqtSignal()  # issued on disconnect
    datareceived_signal = pyqtSignal()

    def __init__(self,  uuid:str):    
        super().__init__()

        # handlers
        self.responses: queue.Queue = queue.Queue() # buffer for notifications

        self.temperature: float = 0
        self.humidity: float = 0
        self.pressure: float = 0
        
        self.crackcounterstarted:bool = False
        
        self.setLogging(True)
        self.add_device_description(TILAUAMBIENT_UUID.TILAU_AMBIENT_SERVICE_UUID,"")
        # ambient support
        # self.add_notify(TILAUAMBIENT_UUID.TILAU_AMBIENT_DIALOG_UUID, self.notify_callback)
        self.add_read(TILAUAMBIENT_UUID.TILAU_AMBIENT_SERVICE_UUID, TILAUAMBIENT_UUID.TILAU_AMBIENT_DIALOG_UUID)
        # audio support
        self.add_read(TILAUAMBIENT_UUID.TILAU_AMBIENT_SERVICE_UUID, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
        self.add_write(TILAUAMBIENT_UUID.TILAU_AMBIENT_SERVICE_UUID, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
        self.start(case_sensitive=False, address=uuid)

        self.is_connected = False
        
    def notify_callback(self, _sender:'BleakGATTCharacteristic', data:bytearray) -> None:
        parsed_msg = self.parse_full_message(data)
        if parsed_msg.valid:
            _logd.debug(f"notified {parsed_msg.valid} t={parsed_msg.temperature:.1f} h={parsed_msg.humidity:.1f} p{parsed_msg.pressure:.1f}")
            self.responses.put_nowait(parsed_msg)
            self.datareceived_signal.emit()
        else:
            _logd.info("invalid message")

    def bleStop(self):
        self.stop()
        # now wait for all the ble async queues to flush before killing the object
        while self._ble_client is not None:
            time.sleep(0.1)

    def isconnected(self) -> bool:
        c = self.connected() # just retrieve UUID is enough to check for connection
        return c[0] is not None

    def on_connect(self) -> None: # pylint: disable=no-self-use
        self.is_connected = True
        self.connected_signal.emit() # On émet le signal au lieu d'appeler un handler
 
    def on_disconnect(self) -> None: # pylint: disable=no-self-use
        self.is_connected = False
        self.disconnected_signal.emit() # On émet le signal

    def askAmbient(self) -> TilauAmbientData:
        #_logd.info("ask ambient")
        try:
            payload = self.read(TILAUAMBIENT_UUID.TILAU_AMBIENT_DIALOG_UUID)
        except Exception as e:
            _logd.warning(f"askAmbient read failed: {e}")
            return TilauAmbientData(0,0,0,0,False)
        if payload is None:
            return TilauAmbientData(0,0,0,0,False)
        return self.parse_full_message(bytearray(payload))
  
    # for later use
    def send_command(self, function: int, command: int, data: bytes = b'')->bool:
        if not self.isconnected(): 
            return False
        msg = self.build_full_message(function, command, data)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AMBIENT_DIALOG_UUID)
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False
        
    # audio features
    
    def getCrackCounter(self):
        try:
            payload = self.read(TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
        except Exception as e:
            _logd.warning(f"getCrackCounter read failed: {e}")
            return TilauAudioData(0,False)
        #_logd.debug(f"get crack counter {payload}")
        if payload is None :
            return TilauAudioData(0,False)
        return self.parse_full_message_audio(bytearray(payload))

    def startCalibration(self):
        """Phase 1 : calibration EMPTY (machine a vide, moteur tournant, avant charge).

        Remet aussi le compteur de cracks a zero cote sonde. Prerequis a la phase
        MAILLARD : le firmware refuse la phase 2 tant que EMPTY n'est pas valide.
        """
        if not self.isconnected():
            _logd.info("calibration aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_RUNCALIBRATION)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            _logd.info("CALIB_START phase=EMPTY ts=%s", __import__('datetime').datetime.now().isoformat(timespec='seconds'))
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False

    def startMaillardCalibration(self):
        """Phase 2 : calibration MAILLARD (grains dans le tambour, apres DE).

        A declencher une fois le bruit de charge retombe et avant la zone de FC.
        Le firmware l'ignore si la phase EMPTY n'a pas ete faite (trace serie
        "MAILLARD ... EMPTY manquante"), et la detection ne demarre qu'avec les
        deux profils valides.
        """
        if not self.isconnected():
            _logd.info("maillard calibration aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_RUN_MAILLARD_CALIBRATION)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            _logd.info("CALIB_START phase=MAILLARD ts=%s", __import__('datetime').datetime.now().isoformat(timespec='seconds'))
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False

    def getCalibrationState(self):
        """Demande l'etat des deux phases (reponse sur le port serie de la sonde).

        Il n'y a pas de retour BLE : la sonde imprime EMPTY=.. MAILLARD=.. ready=..
        """
        if not self.isconnected():
            _logd.info("calibration state aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_CALIBRATIONSTATE)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False

    def startCountingCracks(self):
        if not self.isconnected():
            _logd.info("crack count start aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_START_SAMPLING)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            self.crackcounterstarted = True
            _logd.info("DETECT_START ts=%s", __import__('datetime').datetime.now().isoformat(timespec='seconds'))
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False

    def stopCountingCracks(self):
        if not self.isconnected():
            _logd.info("crack count stop aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_STOP_SAMPLING)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            self.crackcounterstarted = False
            _logd.info("DETECT_STOP ts=%s", __import__('datetime').datetime.now().isoformat(timespec='seconds'))
            return True
        except Exception as e:
            _logd.error(f"error occurred {e}")
            return False

    def startDebug(self) -> bool:
        """Active la verbosité série étendue sur la sonde (COMMAND_DEBUG_ON)."""
        if not self.isconnected():
            _logd.info("startDebug aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_DEBUG_ON)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            _logd.info("probe serial debug enabled")
            return True
        except Exception as e:
            _logd.error(f"startDebug error: {e}")
            return False

    def stopDebug(self) -> bool:
        """Désactive la verbosité série étendue sur la sonde (COMMAND_DEBUG_OFF)."""
        if not self.isconnected():
            _logd.info("stopDebug aborted not connected")
            return False
        msg = self.build_full_message_audio(COMMAND_DEBUG_OFF)
        try:
            self.send(msg, True, TILAUAMBIENT_UUID.TILAU_AUDIO_DIALOG_UUID)
            _logd.info("probe serial debug disabled")
            return True
        except Exception as e:
            _logd.error(f"stopDebug error: {e}")
            return False

class TilauAmbient(QObject): # pyright: ignore [reportGeneralTypeIssues] # Argument to class must be a base class
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
  
    def __init__(self,  uuid:str, aw: ApplicationWindow):
        super().__init__() 
        # mutex
        self.shutdown_lock = QMutex()
        self.is_shutting_down = False

        self.bme280 = TilauAmbientBLE(uuid)
        self.bme280.connected_signal.connect(self._relay_connected)
        self.bme280.disconnected_signal.connect(self._relay_disconnected)        
        self.extradevicenumber = -1  # -1 = aucun device "tilau56" trouvé (slot 0 reste exploitable)
        self.is_connected = False
        self._command_idle = threading.Event()
        self._command_idle.set()   # au démarrage : libre
        
        self.aw = aw
        if aw is not None and aw.qmc is not None:
            for i in range(len(aw.qmc.extradevices)): # fix bug on device identification which is not fixed anymore
                if aw.qmc.extradevices[i] == aw.qmc.tilau_devices["tilau56"]["id"]: # 25/11/21 bug fix
                    _logd.debug(f" Tilauscope Ambian identify_extrade_devices: found extradevice {i} ")
                    self.extradevicenumber = i
                    break

    def _relay_connected(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down: return
        self.is_connected = True
        self.connected_signal.emit()

    def _relay_disconnected(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down: return
        self.is_connected = False
        self.disconnected_signal.emit()

    def disconnect(self):
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                return
            self.is_shutting_down = True
        _logd.debug("start disconnecting tilauambient...")

        try:
            self.bme280.connected_signal.disconnect()
            self.bme280.disconnected_signal.disconnect()
        except:
            pass
        if not self._command_idle.wait(timeout=1.0):
            _logd.warning("disconnect: timeout waiting for command to finish, forcing stop")
        self.bme280.bleStop()

    # answer to qtsignal emission, a command is requested from the main thread
    def get_ambient(self, command:str)-> TilauAmbientData :
        self._command_idle.clear()   # signale "commande en cours"
        try:
            command  = command.strip() # remove any blanks at start and end
            command  = command.upper() # convert all commands in upper case
            #_logd.info(f"tilau ambient interpreter get process {command}")
            if command.startswith("AMBIENT"):
                return self.bme280.askAmbient()
            return TilauAmbientData(0,0,0,0,False)
        finally:
            self._command_idle.set()   # signale "module libre"
  
    def ScanForTilauAmbientBLEDevices(self, __:bool = False) -> str:
        _logd.info('Scan for TilauScope BLE devices')
        tempbt = ClientBLE()
        try:
            self.devices = tempbt.scan()
            for d in self.devices:
                ble_device = d[0]
                if ble_device is not None and ble_device.name is not None and ble_device.name.startswith(TILAUAMBIENT_PREFIX): 
                    _logd.info(f"found {ble_device.address}")
                    return ble_device.address
            _logd.info("Tilauscope scan for BLE devices not found")
            return ""
        finally:
            tempbt.stop()
    
    def ReadBlockCrackCounter(self) -> int:
        """Lit le dernier compteur de crack depuis les arrays Artisan.
        - flagstart=True  : extratemp1/2 (profil permanent)
        - flagstart=False : RTextratemp1/2 (buffer RT, alimente a chaque cycle)
        """
        if self.extradevicenumber < 0:
            return -1
        idx = self.extradevicenumber
        qmc = self.aw.qmc
        try:
            if qmc.flagstart:
                arr = qmc.extratemp2[idx] if idx % 2 == 0 else qmc.extratemp1[idx]
                return int(arr[-1]) if arr and arr[-1] != -1 else -1
            elif qmc.flagon:
                rt = qmc.RTextratemp2 if idx % 2 == 0 else qmc.RTextratemp1
                return int(rt[idx]) if idx < len(rt) and rt[idx] != -1 else -1
            return -1
        except (IndexError, TypeError):
            return -1
    
        # sends a command to the probe
    def send_command(self, commands:str):
        # commandes supportees (separees par des virgules) :
        #   CAL / CALEMPTY / CAL1 -> calibration phase 1 : machine a vide, avant charge
        #   CALMAILLARD / CAL2    -> calibration phase 2 : grains dans le tambour, apres DE
        #   CALSTATE              -> etat des deux phases (trace sur le port serie de la sonde)
        #   START  -> demarrer le comptage (exige les DEUX phases valides)
        #   STOP   -> arreter le comptage
        #   DEBUG  -> activer la verbosite serie etendue sur la sonde
        #   NODEBUG -> desactiver la verbosite serie etendue
        #
        # Correspondance exacte (pas de startswith) : "CAL" est un prefixe de
        # "CALMAILLARD", un match par prefixe lancerait la phase 1 a la place de la 2.
        verbs = {
            "CAL":         (self.bme280.startCalibration,         "calibration EMPTY (phase 1) started"),
            "CALEMPTY":    (self.bme280.startCalibration,         "calibration EMPTY (phase 1) started"),
            "CAL1":        (self.bme280.startCalibration,         "calibration EMPTY (phase 1) started"),
            "CALMAILLARD": (self.bme280.startMaillardCalibration, "calibration MAILLARD (phase 2) started"),
            "CAL2":        (self.bme280.startMaillardCalibration, "calibration MAILLARD (phase 2) started"),
            "CALSTATE":    (self.bme280.getCalibrationState,      "calibration state requested"),
            "START":       (self.bme280.startCountingCracks,      "counting cracks started"),
            "STOP":        (self.bme280.stopCountingCracks,       "counting cracks stopped"),
            "DEBUG":       (self.bme280.startDebug,               "probe debug enabled"),
            "NODEBUG":     (self.bme280.stopDebug,                "probe debug disabled"),
        }

        messages = commands.split(',')
        results = []
        for c in messages:
            _logd.debug(f"tilauscope interpreter processing subcommand {c}")
            command = c.strip().upper()
            if not command:
                continue
            _logd.debug(f"tilauscope interpreter set process {command}")
            entry = verbs.get(command)
            if entry is None:
                results.append(f"unknown command '{c.strip()}' (valid: {', '.join(verbs)})")
                continue
            action, label = entry
            action()
            results.append(label)
        return ', '.join(results) if results else "no command found"

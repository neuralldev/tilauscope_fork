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

# Niimbot BLE label printer protocol (B21S / D110M V4). Packet framing derived
# from https://github.com/AndBondStyle/niimprint and https://printers.niim.blue.

# AUTHOR
# TiLau 2025

import logging
import os
import struct
import time
import numpy as np
from PIL import Image
from artisanlib.ble_port import ClientBLE
from enum import Enum, StrEnum, IntEnum
import queue
import threading

from collections.abc import Callable
from typing import Final, TYPE_CHECKING

from bleak.backends.characteristic import BleakGATTCharacteristic  # pylint: disable=unused-import
from bleak.backends.device import BLEDevice  # pylint: disable=unused-import

if TYPE_CHECKING:
    from bleak import BleakClient  # pylint: disable=unused-import

#pylint: disable-next = E, W, R, C
from PyQt6.QtCore import pyqtSignal, pyqtSlot # @Reimport @UnresolvedImport @UnusedImport
from PyQt6.QtWidgets import QApplication

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

NIIMBOT_INITIAL_PACKET = "C10101C1"
NIIMBOT_PREFIX= "B21" # all devices start with this name
MAX_BLE_CHUNK_SIZE = 220
NIIMBOT_HEARTBEAT_S: Final[float] = 5.0          # keep-alive period while the printer is linked
# Two heartbeats in a row with nothing back from the printer, plus a margin.
NIIMBOT_SILENT_AFTER_S: Final[float] = 2 * NIIMBOT_HEARTBEAT_S + 1.0
MAX_ROWS_PER_BLOCK = 200     # La limite de lignes par transaction de données (dépassement -> 0xD3)
FLOW_CONTROL_DELAY = 0.06    # Délai d'envoi de paquet 0x85 (60ms)
_PACKET_INTERVAL_S = 0.02    # Délai entre 2 écritures BLE (1 paquet/écriture, flux D110M V4)
PIXEL_COUNT_THRESHOLD = 7 # Le seuil pour basculer en 0x84
PRINTER_RESUME_CODE = 179    # Supposons 0xB3 = 179 (code non listé pour 'Ready to Resume')

PACKET_END_MARKER = b'\xaa\xaa' # Le marqueur de fin de paquet Niimbot
# Seuil pour basculer de 0x84 (Séquences <= 7) à 0x85 (Bitmap)
MAX_RLE_RUN_LENGTH = 7

class NiimbotUUID(StrEnum):   #e7810a71-73ae-499d-8c15-faa9aef0c3f2
    NIIMBOT_SERVICE0_UUID   = "e7810a71-73ae-499d-8c15-faa9aef0c3f2" # service UUID to discover devices
    NIIMBOT_CHAR0_UUID      = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f" # print characteristic
    NIIMBOT_SERVICE1_UUID   = "0000ff10-0000-1000-8000-00805f9b34fb" # clear text channel characteristic
    NIIMBOT_CHAR1_UUID      = "0000ff11-0000-1000-8000-00805f9b34fb" # clear text channel characteristic
    NIIMBOT_CHAR2_UUID      = "0000ff12-0000-1000-8000-00805f9b34fb" # clear text channel characteristic

## Niimbot Packet Structure
# [0x55, 0x55, type, len, data..., checksum, 0xAA, 0xAA] — ack packets return type+1.

class NiimbotPacket:
    PREAMBLE = 0x55
    ENDING   = 0xAA

    def __init__(self, type_: int, data: bytes):
        self.type: int = type_
        self.data: bytes = data

    def get_type(self) -> int:
        return self.type

    def get_data(self) -> bytes:
        return self.data

    @classmethod
    def from_bytes(cls, pkt: bytes):
        if pkt[:2] != bytes((cls.PREAMBLE, cls.PREAMBLE)):
            raise ValueError("Invalid Niimbot packet preamble")
        if pkt[-2:] != bytes((cls.ENDING, cls.ENDING)):
            raise ValueError("Invalid Niimbot packet ending")
        type_ = pkt[2]
        len_ = pkt[3]
        data = pkt[4 : 4 + len_]

        checksum = type_ ^ len_
        for i in data:
            checksum ^= i
        if checksum != pkt[-3]:
            raise ValueError("Invalid Niimbot packet checksum")

        return cls(type_, data)

    def to_bytes(self) -> bytes:
        checksum = self.type ^ len(self.data)
        for i in self.data:
            checksum ^= i
        return bytes(
            (
                self.PREAMBLE, self.PREAMBLE,
                self.type, len(self.data),
                *self.data,
                checksum,
                self.ENDING, self.ENDING
            )
        )

class Niimprint_InfoEnum(IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    LANGUAGETYPE = 6
    AUTOSHUTDOWNTIME = 7
    DEVICETYPE = 8
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12
    PAPERTYPE = 30

class Niimprint_RequestCodeEnum(IntEnum):
    GET_INFO = 64  # 0x40
    GET_RFID = 26  # 0x1A
    HEARTBEAT = 220  # 0xDC
    SET_LABEL_TYPE = 35  # 0x23
    SET_LABEL_DENSITY = 33  # 0x21
    START_PRINT = 1  # 0x01
    END_PRINT = 243  # 0xF3
    START_PAGE_PRINT = 3  # 0x03
    END_PAGE_PRINT = 227  # 0xE3
    ALLOW_PRINT_CLEAR = 32  # 0x20
    SET_DIMENSION = 19  # 0x13
    SET_QUANTITY = 21  # 0x15
    GET_PRINT_STATUS = 163  # 0xA3
    GET_PAPER_TYPE = 30 # 0x2A
    PrintBitmapRowIndexed =  131 #0x83
    PrintEmptyRow = 132 #0x84
    PrintBitmapRow = 133 #0x85
    ANTIFAKE = 11 #0x0B
    PRINTER_ACK = 211 # 0xD3

class Niimprint_ErrorCodeEnum(IntEnum):
    SUCCESS = 0
    ERROR = 1
    NOT_IMPLEMENTED = 2
    PARAMETER_ERROR = 3
    NO_PAPER = 4
    OVERHEAT = 5
    LOW_VOLTAGE = 6
    BUSY = 7
    OUT_OF_MEMORY = 8
    PRINTING = 9
    NO_RFID = 10
    RFID_ERROR = 11
    NO_LABEL = 12
    LABEL_ERROR = 13
    NOT_DEFINED = 218
    BAD_VALUE = 219

class Niimprint_WarningCodeEnum(IntEnum):
    NO_WARNING = 0
    NEARLY_OUT_OF_PAPER = 1
    NEARLY_OUT_OF_BATTERY = 2

class Niimprint_PaperType(IntEnum):
    UNKNOWN = 0
    WITH_GAPS = 1
    BLACK = 2
    CONTINUOUS = 3
    PERFORATED = 4
    TRANSPARENT = 5
    PVCTAG = 6
    BLACKMARKGAP = 10
    HEARTSHRINKTUBE = 11

class NiimbotPrintOutcome(Enum):
    """How a label print ended. Compare with `is`: an outcome has no truth value,
    so a caller still testing `if not print_image(...)` fails loudly instead of
    reading a failure as a success."""
    PRINTED = "printed"          # the printer reported the page done
    FAILED = "failed"            # stopped before any label data was sent: nothing printed
    UNCONFIRMED = "unconfirmed"  # label data sent, never reported done: it may be out, or blank

    def __bool__(self) -> bool:
        raise TypeError("compare a NiimbotPrintOutcome with `is`, not as a boolean")

def unconfirmed_pill_text() -> str:
    """Short status of a label the printer never confirmed, for the progress pill."""
    return QApplication.translate("tilauscope_label", "Not confirmed — check the label")

def unconfirmed_message() -> str:
    """What to do with a label the printer never confirmed."""
    return QApplication.translate("tilauscope_label",
        "Check the label before printing it again — the printer did not confirm it, "
        "so it may have come out correctly or blank.")

# Measured on the B21S: a label takes 4-6 s to send, then each copy about 1.2 s to come out.
_SEND_S: Final[float] = 5.0
_COPY_OUT_S: Final[float] = 1.2

def copies_progress(sent: float, labels_out: int, copies: int) -> float:
    """Share of a run of copies done, for a ring that fills once over the run.

    The label is sent once, then the printer puts the copies out one by one;
    each part weighs the time it takes, and the ring is full only when the last
    copy is out.
    """
    copies = max(1, copies)
    if labels_out >= copies:
        return 1.0
    send_share = _SEND_S / (_SEND_S + _COPY_OUT_S * copies)
    sent = min(max(sent, 0.0), 1.0)
    return send_share * sent + (1.0 - send_share) * max(labels_out, 0) / copies

class NiimbotHeartbeat:
    def __init__(self)->None:
        self.closingstate: int|None = None
        self.powerlevel: int|None = None
        self.paperstate: int|None = None
        self.rfidreadstate: int|None = None
        self.valid:bool = False

class NiimbotRFIDinfo:
    def __init__(self)->None:
        self.type: int|None = None # paper type
        self.used_len: int|None = None # remaining labels on the roll
        self.total_len: int|None = None # total labels of the roll
        self.barcode: str|None = None # barcode read from rfid (used to find paper size on web site)
        self.uuid: str|None = None # uuid of rfid (not used)
        self.serial:str|None = None # serial of paper roll (not used)
        self.valid:bool = False

class NiimbotBLE(ClientBLE):
    at_connected    = pyqtSignal()
    at_disconnected = pyqtSignal()
    error           = pyqtSignal(str)
    # Emitted for every keep-alive answer (NIIMBOT_HEARTBEAT_S) and at the start of a print.
    # Payload : (NiimbotHeartbeat, NiimbotRFIDinfo | None)
    status_updated  = pyqtSignal(object, object)
    # Progression d'impression : (lignes_envoyées, lignes_totales).
    # Émis depuis le thread worker pendant _print_image_locked → slot GUI
    # en QueuedConnection (comme status_updated).
    print_progress  = pyqtSignal(int, int)

    # How long a request waits for its own answer; measured answers take 60–120 ms.
    _ANSWER_TIMEOUT_S: float = 1.0
    # Packets the printer sends instead of an answer: not supported (0x00) and
    # print error (0xDB), as in niimprint and niimbluelib, plus 0xDA.
    _ERROR_PACKET_TYPES: Final[frozenset[int]] = frozenset({0x00, 0xDA, 0xDB})

    def __init__(self, known_uuid: str | None = None):
        super().__init__()
        self._packetbuf = bytearray()
        self.responses: queue.Queue = queue.Queue()
        self.loglocal: str = ''
        self.printerack: bool = False
        self.printer_ready_to_resume: bool = False
        self.paperstyle: Niimprint_PaperType
        self.remaining_labels: int = 0
        self.total_labels: int = 0
        self.paper_height = 0
        self.paper_width = 0
        # Why the last print failed, translated for display ("" unless it failed).
        self.print_failure: str = ""
        # Labels the printer reported done in the last print, copies included.
        self.labels_confirmed: int = 0
        # UUID mémorisé depuis les settings — court-circuite le scan par préfixe
        self.device_uuid: str | None = known_uuid
        self._resume_event = threading.Event()
        self._connecting = False   # verrou léger anti-double connexion
        self._known_device: 'BLEDevice | None' = None  # fourni par TilauBLEScanner
        self.aw = None  # référence ApplicationWindow pour auto-save UUID
        # Verrou exclusif : empêche le polling heartbeat de s'intercaler
        # pendant une séquence d'impression (_transceive non-rentrant).
        self._ble_lock = threading.Lock()
        # True while _transceive waits for its answer: a heartbeat answer is then left to it.
        self._exchange_active = False
        # time.monotonic() of the last packet the printer sent, whatever it was.
        self.last_seen: float | None = None
        # ── Traceur TX/RX horodaté (diagnostic « étiquettes blanches ») ───────
        # Chaque envoi et chaque notification est estampillé (time.perf_counter).
        # Purement observationnel : ne change RIEN au flux. Vidé au début d'une
        # impression, dumpé dans ~/Downloads/tilau_print_trace.txt à la fin.
        self._trace: list = []            # [(t, "TX"|"RX", "0x85", size)]
        self._trace_on: bool = False      # actif seulement pendant une impression

    def _tr(self, direction: str, label: str, size: int) -> None:
        """Estampille un échange TX/RX. GIL-safe (append sur list)."""
        if self._trace_on:
            self._trace.append((time.perf_counter(), direction, label, size))

    def _dump_trace(self, header: str) -> None:
        """Vide le traceur (horodatage relatif, delta, sens, type de paquet) dans
        ~/Downloads/tilau_print_trace.txt."""
        self._trace_on = False
        events = self._trace
        self._trace = []
        if not events:
            return
        try:
            from pathlib import Path as _P
            t0 = events[0][0]
            prev = t0
            out = [f"=== TRACE {time.strftime('%H:%M:%S')} {header} ===",
                   f"    {'t+ms':>9}  {'Δms':>8}  dir  packet        size"]
            for t, direction, label, size in events:
                rel = (t - t0) * 1000.0
                dlt = (t - prev) * 1000.0
                prev = t
                out.append(f"    {rel:9.2f}  {dlt:8.2f}  {direction:<3}  {label:<12}  {size:>4}")
            # Résumé : nb TX, nb RX, durée totale, temps d'encodage exclu.
            n_tx = sum(1 for e in events if e[1] == "TX")
            n_rx = sum(1 for e in events if e[1] == "RX")
            span = (events[-1][0] - t0) * 1000.0
            out.append(f"    total: {n_tx} TX, {n_rx} RX, span={span:.1f}ms")
            out.append("")
            with open(_P.home() / "Downloads" / "tilau_print_trace.txt", "a", encoding="utf-8") as _f:
                _f.write("\n".join(out) + "\n")
            _logd.warning(f"[PRINTTRACE] {n_tx} TX / {n_rx} RX / span={span:.1f}ms")
        except Exception as _e:
            _logd.warning(f"[PRINTTRACE] dump failed: {_e}")

    def disconnect(self) -> None:
        """
        Ferme la connexion BLE et effectue le nettoyage.
        """
        if self._ble_client is not None:
            _logd.debug("Closing BLE connection.")
            self._ble_client.close()
            self._ble_client = None

    @pyqtSlot(list)
    def on_devices_found(self, devices: list) -> None:
        """Slot branché sur TilauBLEScanner.devices_found : filtre sur NIIMBOT_PREFIX
        et lance connect_direct() si trouvé."""
        if self._connecting or self._running:
            return  # déjà connecté ou connexion en cours
        for bd, _ad in devices:
            # Si UUID mémorisé → connexion directe par adresse, pas de scan préfixe
            if self.device_uuid and bd.address.upper() == self.device_uuid.upper():
                _logd.debug(f"NiimbotBLE: device spotted by scanner — {bd.name} {bd.address}")
                self.connect_direct(bd)
                return
            # Sinon : scan par préfixe (premier démarrage, UUID inconnu)
            if not self.device_uuid and bd.name is not None and bd.name.startswith(NIIMBOT_PREFIX):
                _logd.debug(f"NiimbotBLE: device spotted by scanner — {bd.name} {bd.address}")
                self.connect_direct(bd)
                return

    def connect_direct(self, bd: 'BLEDevice') -> None:
        """Connexion directe au BLEDevice fourni par TilauBLEScanner : stocke bd dans
        _known_device puis appelle start(), qui redirige vers ble.connect_known()."""
        if self._connecting or self._running:
            _logd.debug("NiimbotBLE: connect_direct ignored — already connecting/connected")
            return
        self._connecting = True
        self.device_uuid = bd.address  # mis à jour à chaque connexion (UUID peut changer si BT reset)
        self._known_device = bd
        _logd.debug(f"NiimbotBLE: connect_direct to {bd.name} {bd.address}")

        self.add_device_description(NiimbotUUID.NIIMBOT_SERVICE0_UUID, "")
        self.add_write(NiimbotUUID.NIIMBOT_SERVICE0_UUID, NiimbotUUID.NIIMBOT_CHAR0_UUID)
        self.add_notify(NiimbotUUID.NIIMBOT_CHAR0_UUID, self.notify_callback)

        # Armed before start(): ClientBLE's keep-alive loop ends at once if the
        # frequency is still 0 when the link starts.
        self.set_heartbeat(NIIMBOT_HEARTBEAT_S)
        # start() crée un AsyncLoopThread et soumet _connect_and_keep_alive.
        # _connect() appellera notre scan_and_connect() overridé ci-dessous
        # qui redirige vers ble.connect_known() sans scan BLE.
        self.start(
            case_sensitive=False,
            address=self.device_uuid,
            scan_timeout=3,
            connect_timeout=10,
        )
        self._connecting = False

    def scan_and_connect_override(
            self,
            device_descriptions: tuple[dict,dict], # upstream tuple (was dict)
            blacklist: set,
            case_sensitive: bool,
            disconnected_callback: 'Callable',
            scan_timeout: float,
            connect_timeout: float,
            address: str | None = None,
    ) -> 'tuple[BleakClient | None, str | None, str | None]':
        """Appelé par ClientBLE._connect() à la place de ble.scan_and_connect().
        Si _known_device est défini, bypass le scan et connecte directement.
        """
        from artisanlib.ble_port import ble
        if self._known_device is not None:
            bd = self._known_device
            self._known_device = None
            return ble.connect_known(
                bd,
                NiimbotUUID.NIIMBOT_SERVICE0_UUID,
                disconnected_callback,
                connect_timeout,
            )
        # Pas de known_device — scan standard
        from artisanlib.ble_port import ble
        return ble.scan_and_connect(
            device_descriptions, blacklist, case_sensitive,
            disconnected_callback, scan_timeout, connect_timeout, address
        )

    def stop_scan(self) -> None:
        """Compatibilité — TilauBLEScanner gère l'arrêt du scan central."""
        self.stop()

    def initialize(self) -> None:
        self.send(bytes.fromhex(NIIMBOT_INITIAL_PACKET))

    def notify_callback(self, _sender:'BleakGATTCharacteristic', data:bytearray) -> None:
        try:
            packet = NiimbotPacket.from_bytes(data)
            _logd.debug(f"Notification received: {self.format_hex(data)} packettype={packet.type} to process")
        except ValueError: # if disconnect happens while receiving bytes
            self._tr("RX", "invalid", len(data))
            _logd.debug("Received invalid packet, likely due to disconnection. Ignoring.")
            return
        self._tr("RX", f"0x{packet.type:02x}", len(packet.data))
        self.last_seen = time.monotonic()
        if packet.data==b"\xC2\x01\x03\xC0": # this is the sequence received with sending the initial packet
            _logd.debug("Niimbot initial acknowledge received")
        elif packet.type == Niimprint_RequestCodeEnum.PRINTER_ACK:
            _logd.debug("Niimbot printer acknowledge data")
            self.printerack = True
        elif packet.type == PRINTER_RESUME_CODE:
            _logd.debug("Niimbot printer ready to resume received")
            self.last_b3_packet_data = packet
            self.printer_ready_to_resume = True
        elif (packet.type == Niimprint_RequestCodeEnum.HEARTBEAT + 1
              and not self._exchange_active and not self._ble_lock.locked()):
            # A keep-alive answer nobody is waiting for: straight to the status strip.
            self.status_updated.emit(self.parse_heartbeat(packet.data), None)
        else:
            _logd.debug("Niimbot packet received queued")
            self.responses.put_nowait(packet)

    def is_connected(self) -> bool:
        connected_service_UUID, connected_device_name = self.connected()
        if connected_device_name is not None:
            _logd.debug(f"connected_service_UUID={connected_service_UUID}, connected_device_name={connected_device_name}")
        else:
            _logd.debug("not connected")
        return connected_service_UUID is not None

    def on_connect(self) -> None:
        super().on_connect()
        _logd.debug("Niimbot Printer connected")
        # Auto-save UUID si découvert par scan préfixe (pas encore mémorisé)
        # ou mise à jour de la liste pour que devices.py affiche le device sans redémarrage.
        if self.device_uuid and self.aw is not None:
            if not getattr(self.aw, "bleNiimbotDeviceName", None):
                self.aw.bleNiimbotDeviceName = self.device_uuid
                _logd.debug(f"NiimbotBLE: UUID auto-sauvegardé {self.device_uuid}")
                # Persister immédiatement dans QSettings
                try:
                    from PyQt6.QtCore import QSettings
                    s = QSettings()
                    s.setValue("niimbot", self.device_uuid)
                except Exception:
                    pass
            # Toujours mettre à jour la liste — visible dans devices.py sans redémarrage
            self.aw.bleNiimbotDeviceslist = [self.device_uuid]
        self.at_connected.emit() # On émet le signal personnalisé

    def on_disconnect(self) -> None:
        super().on_disconnect()
        _logd.debug("Niimbot Printer disconnected")
        self.at_disconnected.emit() # On émet le signal personnalisé

    def _packet_to_int(self, x):
        return int.from_bytes(x, "big")

    def format_hex(self, data: bytes) -> str:
        if len(data) == 0:
            return "<empty>"
        return " ".join(f"{b:02x}" for b in data)

    # Sends a request and returns the printer's answer to THAT request. Answers
    # to other requests are dropped; no answer, or an error packet, returns an
    # empty packet of type -1. While it waits, heartbeat answers are left to it.
    def _transceive(self, reqcode, data, respoffset=1, nowait:bool=False, extrawait:float=0.0) -> NiimbotPacket:
        self._exchange_active = True
        try:
            return self._exchange(reqcode, data, respoffset, nowait, extrawait)
        finally:
            self._exchange_active = False

    def _exchange(self, reqcode, data, respoffset, nowait:bool, extrawait:float) -> NiimbotPacket:
        respcode = respoffset + reqcode
        empty = NiimbotPacket(-1, b"")
        # Whatever is still queued answers a request that already gave up.
        while True:
            try:
                late = self.responses.get_nowait()
            except queue.Empty:
                break
            _logd.debug(f"_transceive({hex(reqcode)}): late answer type={hex(late.type)} dropped")
        packet = NiimbotPacket(reqcode, data)
        self._tr("TX", f"0x{reqcode:02x}", len(data))
        self.send(message=packet.to_bytes(),chunk=MAX_BLE_CHUNK_SIZE)
        time.sleep(0.02)
        if nowait:
            return empty
        deadline = time.perf_counter() + self._ANSWER_TIMEOUT_S + extrawait
        while (remaining := deadline - time.perf_counter()) > 0:
            try:
                rpacket = self.responses.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if rpacket.type == respcode:
                r = int(rpacket.data[0]) if rpacket.data != b'' else -1
                _logd.debug(f"printer answer {hex(reqcode)} -> {hex(respcode)} data[0]=({r})")
                return rpacket
            if rpacket.type in self._ERROR_PACKET_TYPES:
                _logd.error(f"printer refused {hex(reqcode)}: type={hex(rpacket.type)} detail={rpacket.data.hex() or 'none'}")
                return empty
            _logd.debug(f"_transceive({hex(reqcode)}): unrelated answer type={hex(rpacket.type)} dropped")
        _logd.warning(f"no answer from the printer to {hex(reqcode)} (expected {hex(respcode)})")
        return empty

    # retrieve information from the printer by sending a query and translate answer according to returned information
    # call transceive to send the data and awaits answer, then interpret return. information is gathered via notify
    def get_info(self, key: Niimprint_InfoEnum)->str:
        _logd.debug(f"get_info key={key}")
        packet: NiimbotPacket = self._transceive(Niimprint_RequestCodeEnum.GET_INFO, bytes((key,)), key)
        if packet is not None and packet.data != b"":
            #_logd.debug(f"get_info key={key} data={self.format_hex(packet.data)}")
            match key:
                case Niimprint_InfoEnum.DEVICESERIAL:
                    return packet.get_data().hex()
                case Niimprint_InfoEnum.SOFTVERSION:
                    return str(self._packet_to_int(packet.get_data()) / 100.0)
                case Niimprint_InfoEnum.HARDVERSION:
                    return str(self._packet_to_int(packet.get_data()) / 100.0)
                case _:
                    return str(self._packet_to_int(packet.get_data()))
        else:
            _logd.error(f"get_info key={key} no data")
            return ""

    def get_serial_number(self):
        return self.get_info(Niimprint_InfoEnum.DEVICESERIAL)

    def get_hardware_version(self):
        return self.get_info(Niimprint_InfoEnum.HARDVERSION)

    def get_software_version(self):
        return self.get_info(Niimprint_InfoEnum.SOFTVERSION)

    # Label type of the loaded roll, read from the roll's RFID tag: the B21S
    # answers the info-30 query with "not supported" (type 0x00, payload 01).
    def get_paper_type(self, rfid: NiimbotRFIDinfo | None = None) -> Niimprint_PaperType:
        known = {t.value for t in Niimprint_PaperType if t != Niimprint_PaperType.UNKNOWN}
        if rfid is not None and rfid.valid and rfid.type in known:
            pt = Niimprint_PaperType(rfid.type)
            _logd.debug(f"get_paper_type: RFID type={rfid.type} → {pt.name}")
            return pt
        p = self.get_info(Niimprint_InfoEnum.PAPERTYPE)
        if p == "":
            return Niimprint_PaperType.UNKNOWN
        try:
            val = int(p)
        except (ValueError, TypeError):
            return Niimprint_PaperType.UNKNOWN
        if val in known:
            pt = Niimprint_PaperType(val)
            _logd.debug(f"get_paper_type: raw={val} → {pt.name}")
            return pt  # retourner la valeur native sans remapping
        _logd.warning(f"get_paper_type: unknown value {val}")
        return Niimprint_PaperType.UNKNOWN

    # get rfid information, to identify paper
    # Parsing défensif : ne lève jamais, un format inattendu ne doit pas casser la connexion.
    def get_rfid(self):
        packet: NiimbotPacket = self._transceive(Niimprint_RequestCodeEnum.GET_RFID, b"\x01")
        data = packet.data
        rfidinfo = NiimbotRFIDinfo()
        if len(data) == 0 or data[0] == 0:
            return rfidinfo # by default valid = false
        try:
            rfidinfo.uuid = data[0:8].hex()
            idx = 8
            barcode_len = data[idx]
            idx += 1
            rfidinfo.barcode = data[idx : idx + barcode_len].decode(errors="replace")
            idx += barcode_len
            serial_len = data[idx]
            idx += 1
            rfidinfo.serial = data[idx : idx + serial_len].decode(errors="replace")
            idx += serial_len
            tail = data[idx:]
            # >HHB = total_len(2) used_len(2) type(1). Le firmware récent peut
            # ajouter des octets en fin ; on ne lit que les 5 premiers.
            if len(tail) >= 5:
                rfidinfo.total_len, rfidinfo.used_len, rfidinfo.type = struct.unpack(">HHB", tail[:5])
            elif len(tail) >= 4:
                rfidinfo.total_len, rfidinfo.used_len = struct.unpack(">HH", tail[:4])
            rfidinfo.valid = True
        except Exception as e:
            # Format inconnu (ex. après MAJ firmware) : on loggue le brut pour
            # pouvoir le décoder, mais on garde le barcode si on l'a déjà lu.
            _logd.warning(
                f"get_rfid: RFID payload inattendu ({len(data)} octets), "
                f"parse partiel: {e} — raw={self.format_hex(data)}"
            )
            rfidinfo.valid = rfidinfo.barcode is not None
        return rfidinfo

    # used to wait for printer to be ready when idle, should not be used if sending data in a row
    def get_heartbeat(self) -> NiimbotHeartbeat:
        return self.parse_heartbeat(
            self._transceive(Niimprint_RequestCodeEnum.HEARTBEAT, b"\x01").data)

    # Keep-alive, called by ClientBLE every NIIMBOT_HEARTBEAT_S on the printer's own
    # BLE loop, never on the GUI thread. Asks for the state without waiting: the
    # answer comes back through notify_callback. Skipped while a print or a
    # request/answer exchange owns the link.
    def heartbeat(self) -> None:
        if self._exchange_active or self._ble_lock.locked():
            return
        try:
            self.send(message=NiimbotPacket(Niimprint_RequestCodeEnum.HEARTBEAT, b"\x01").to_bytes(),
                      chunk=MAX_BLE_CHUNK_SIZE)
        except Exception as e:  # noqa: BLE001 — a dead link shows up as silence
            _logd.debug(f"heartbeat not sent: {e}")

    def is_silent(self, now: float) -> bool:
        """True once the printer has sent nothing for two heartbeats in a row."""
        return self.last_seen is None or now - self.last_seen > NIIMBOT_SILENT_AFTER_S

    @staticmethod
    def parse_heartbeat(data: bytes) -> NiimbotHeartbeat:
        hb : NiimbotHeartbeat = NiimbotHeartbeat()
        match len(data):
            case 20:
                hb.paperstate = data[18]
                hb.rfidreadstate = data[19]
            case 13:
                hb.closingstate = data[9]
                hb.powerlevel = data[10]
                hb.paperstate = data[11]
                hb.rfidreadstate = data[12]
            case 19:
                hb.closingstate = data[15]
                hb.powerlevel = data[16]
                hb.paperstate = data[17]
                hb.rfidreadstate = data[18]
            case 10:
                hb.closingstate = data[8]
                hb.powerlevel = data[9]
                hb.rfidreadstate = None
            case 9:
                hb.closingstate = data[8]
        hb.valid = bool(data)   # no answer says nothing about the cover
        return hb

    # set the label to be used; returns the printer's answer (type -1: none)
    def set_label_type(self, n: Niimprint_PaperType) -> NiimbotPacket:
        _logd.debug(f"set_label_type: sending type={n.value} ({n.name})")
        return self._transceive(Niimprint_RequestCodeEnum.SET_LABEL_TYPE, bytes((n,)), 16)

    # set label density to print from 1 to 5; returns the printer's answer (type -1: none)
    def set_label_density(self, n) -> NiimbotPacket:
        if not 1 <= n <= 5:
            raise ValueError("Label density must be between 1 and 5")
        return self._transceive(Niimprint_RequestCodeEnum.SET_LABEL_DENSITY, bytes((n,)), 16)

    # must be sent at the beginning of the sequence
    # (start print) [(start page) (set dimension) (send data) (end page) waint (start page)...(end page) wait] (end print)
    def start_print(self):
        packet = self._transceive(Niimprint_RequestCodeEnum.START_PRINT, b"\x01")
        status= False
        if packet.data != b"":
            status = bool(packet.data[0])
        return status

    # must be sent to end the print, it ejects the last page as well; returns the answer (type -1: none)
    def end_print(self) -> NiimbotPacket:
        return self._transceive(Niimprint_RequestCodeEnum.END_PRINT, b"\x01")

    # must be sent at the end of the page data; returns the answer (type -1: none)
    def end_page_print(self) -> NiimbotPacket:
        return self._transceive(Niimprint_RequestCodeEnum.END_PAGE_PRINT, b"\x01")

    # ── D110M V4 print flow (firmware B21S récent) ───────────────────────────
    # Découvert via niimblue : le firmware mis à jour parle le protocole
    # « D110M V4 » et plus l'ancien « B21 V1 ». Layouts issus de niimbluelib.

    def print_start_9b(self, total_pages: int = 1, color: int = 0, speed: int = 0) -> NiimbotPacket:
        # PrintStart 0x01 — payload 9 octets :
        #   totalPages(u16 BE), 0,0,0,0, color(1), speed(1), flag(1)
        data = struct.pack(">H", total_pages) + bytes([0, 0, 0, 0, color, speed, 0])
        return self._transceive(Niimprint_RequestCodeEnum.START_PRINT, data)

    def set_page_size_13b(self, rows: int, cols: int, copies: int = 1) -> NiimbotPacket:
        # SetPageSize 0x13 — payload 13 octets :
        #   rows(u16) cols(u16) copies(u16) cutHeight(u16) cutType(1) 0x00
        #   sendAll(1) partHeight(u16)  (tout à 0 sauf rows/cols/copies)
        data = struct.pack(">HHHHBBBH", rows, cols, copies, 0, 0, 0, 0, 0)
        return self._transceive(Niimprint_RequestCodeEnum.SET_DIMENSION, data)

    def print_status_oneway(self) -> None:
        # PrintStatus 0xA3 en début de page, envoyé sans attendre de réponse.
        try:
            pkt = NiimbotPacket(Niimprint_RequestCodeEnum.GET_PRINT_STATUS, b"").to_bytes()
            self._tr("TX", "0xa3", 0)
            self.send(message=pkt, chunk=MAX_BLE_CHUNK_SIZE)
        except Exception as e:
            _logd.warning(f"print_status_oneway failed: {e}")

    ## no idea what this is but I implemented it
    def set_antifake(self):
        packet = self._transceive(Niimprint_RequestCodeEnum.ANTIFAKE, b"\x01")
        status= False
        if packet.data != b"":
            status = bool(packet.data[0])
        return status

    def _get_niimbot_packets(self, image: Image.Image) -> list[tuple[bytes, int]]:
        # Encodage vectorisé numpy. Mode "1" : 0 = noir, 255 = blanc, donc
        # np.array → bool où True = blanc ; l'encre (noir) est ~arr.
        arr   = np.array(image.convert("1"), dtype=bool)
        black = ~arr                              # True là où il y a de l'encre
        row_has_ink = black.any(axis=1)           # ligne non vide ?
        # packbits MSB-first : bit 7 = colonne de gauche → format protocole 0x85.
        row_bytes = np.packbits(black, axis=1)

        # En-tête 0x85 « split mode » (D110M V4) = [y(2, BE), c0, c1, c2, repeat(1)]
        # où c0/c1/c2 = pixels noirs par tiers de ligne (128 colonnes), bornés à 255.
        seg = np.empty((image.height, 3), dtype=np.int64)
        seg[:, 0] = black[:, 0:128].sum(axis=1)
        seg[:, 1] = black[:, 128:256].sum(axis=1)
        seg[:, 2] = black[:, 256:384].sum(axis=1)
        row_count = seg.sum(axis=1).copy()   # total noirs/ligne (avant clip) → choix 0x83/0x85
        np.clip(seg, 0, 255, out=seg)

        # Lignes vides → 0x84 ; lignes avec encre → 0x83 (≤ 6 pixels) ou 0x85 (bitmap).
        # NB : cette imprimante n'accepte PAS une ligne 0x85 tout-à-zéro — il
        # faut impérativement passer par 0x84 pour les lignes vides.
        # Identical consecutive rows go out as one packet with a repeat count, as niimbluelib
        # sends them; a run never crosses a MAX_ROWS_PER_BLOCK boundary and its count is one byte.
        same_as_above = np.zeros(image.height, dtype=bool)
        same_as_above[1:] = (row_bytes[1:] == row_bytes[:-1]).all(axis=1)
        niimbot_packets: list[tuple[bytes, int]] = []
        y = 0
        while y < image.height:
            run = 1
            while (y + run < image.height and same_as_above[y + run]
                   and (y + run) % MAX_ROWS_PER_BLOCK != 0 and run < 255):
                run += 1
            if not row_has_ink[y]:
                pkt = NiimbotPacket(Niimprint_RequestCodeEnum.PrintEmptyRow,
                                    struct.pack(">HB", y, run)).to_bytes()
            else:
                header = struct.pack(">HBBBB", y,
                                     int(seg[y, 0]), int(seg[y, 1]), int(seg[y, 2]), run)
                if int(row_count[y]) <= 6:
                    # ≤ 6 pixels → 0x83 « indexed » : indices de colonnes (u16 BE)
                    # des pixels noirs. C'est ce que niimblue envoie pour ces lignes
                    # fines ; un firmware strict rejette un 0x85 à leur place.
                    idx = b"".join(struct.pack(">H", int(x)) for x in np.flatnonzero(black[y]))
                    pkt = NiimbotPacket(Niimprint_RequestCodeEnum.PrintBitmapRowIndexed,
                                        header + idx).to_bytes()
                else:
                    pkt = NiimbotPacket(Niimprint_RequestCodeEnum.PrintBitmapRow,
                                        header + row_bytes[y].tobytes()).to_bytes()
            niimbot_packets.append((pkt, run))
            y += run
        return niimbot_packets

    def _wait_print_finished_by_status(self, total_pages: int = 1,
                                       poll_interval: float = 0.3,
                                       timeout: float = 12.0,
                                       stop_requested: Callable[[], bool] | None = None,
                                       on_label_out: Callable[[int, int], None] | None = None) -> int | None:
        """Sonde le print-status (0xA3 → réponse 0xB3) jusqu'à `page >= total_pages`.
        À appeler ENTRE pageEnd et printEnd : le firmware D110M V4 brûle l'étiquette
        durant cette phase ; couper trop tôt éjecte une étiquette blanche.

        Returns how many labels the printer reports out: all of them, or up to the
        label being printed when `stop_requested` turned true. None when no new
        label came out for `timeout` seconds — the wait restarts at each label, so
        a long run of copies is not taken for a stall. Page 0 is the stale count
        read just after pageEnd, never a label out."""
        last_page = -1                      # -1: no status heard yet
        stop_after: int | None = None
        last_out = time.perf_counter()
        while (time.perf_counter() - last_out) < timeout:
            if stop_after is None and stop_requested is not None and stop_requested():
                stop_after = max(last_page, 0) + 1   # the label being printed still comes out
                _logd.debug(f"print run stopped by the operator after label {stop_after}.")
            self.printer_ready_to_resume = False
            self.last_b3_packet_data = None
            try:
                self._tr("TX", "0xa3", 0)
                self.send(
                    message=NiimbotPacket(
                        Niimprint_RequestCodeEnum.GET_PRINT_STATUS, b"").to_bytes(),
                    chunk=MAX_BLE_CHUNK_SIZE)
            except Exception as e:
                _logd.warning(f"status poll send failed: {e}")
            t_poll = time.perf_counter()
            while ((time.perf_counter() - t_poll) < poll_interval
                   and not self.printer_ready_to_resume):
                time.sleep(0.02)
            if self.printer_ready_to_resume and self.last_b3_packet_data is not None:
                data = self.last_b3_packet_data.data
                if len(data) >= 4:
                    page = int.from_bytes(data[0:2], "big")
                    pp, pf = data[2], data[3]
                    self._tr("RX", f"st p={page} {pp}/{pf}", len(data))
                    if page > max(last_page, 0):
                        last_out = time.perf_counter()
                        if on_label_out is not None:
                            on_label_out(min(page, total_pages), total_pages)
                    last_page = max(last_page, page)
                    if page >= total_pages or (stop_after is not None and page >= stop_after):
                        _logd.debug(f"print finished (page={page}/{total_pages}).")
                        return min(page, total_pages)
        _logd.warning(f"status poll timeout (last page={last_page}/{total_pages}).")
        return None

    def _answered(self, step: str, packet: NiimbotPacket) -> bool:
        """True when the printer answered this print step. A zero status is only
        logged: the older firmware used it for "not ready yet", and the status poll
        after pageEnd is what says whether the label came out."""
        if packet.type < 0:
            _logd.warning(f"print step {step}: no answer from the printer")
            return False
        if not packet.data or packet.data[0] == 0:
            _logd.warning(f"print step {step}: answered with status {packet.data.hex() or 'none'}")
        return True

    def _abort(self, reason: str, step: str) -> NiimbotPrintOutcome:
        """Nothing reached the print head: keep the reason for display and give up."""
        _logd.error(f"print aborted at {step}: {reason}")
        self.print_failure = reason
        self.error.emit(reason)
        self._dump_trace(f"ABORT {step}")
        return NiimbotPrintOutcome.FAILED

    def print_image(self, image: Image.Image, density: int =3,
                    labelsize:Niimprint_PaperType = Niimprint_PaperType.CONTINUOUS,
                    copies: int = 1, stop_requested: Callable[[], bool] | None = None,
                    on_label_out: Callable[[int, int], None] | None = None) -> NiimbotPrintOutcome:
        # Acquiert le verrou exclusif BLE : le keep-alive (heartbeat) ne s'intercale
        # pas pendant une impression.
        with self._ble_lock:
            return self._print_image_locked(
                image, density, labelsize, max(1, int(copies)), stop_requested, on_label_out)

    def _print_image_locked(self, image: Image.Image, density: int, labelsize: Niimprint_PaperType,
                            copies: int = 1, stop_requested: Callable[[], bool] | None = None,
                            on_label_out: Callable[[int, int], None] | None = None) -> NiimbotPrintOutcome:
        # Ajustement défensif à la taille physique du papier (203.2 DPI).
        _B21S_DPI: float = 203.2
        phys_h = round(self.paper_height * _B21S_DPI / 25.4) if self.paper_height > 0 else image.height
        if phys_h != image.height:
            _logd.debug(
                f"print_image: image={image.height}px, papier physique={phys_h}px "
                f"({self.paper_height}mm @ {_B21S_DPI}DPI) — padding automatique."
            )
            img_padded = Image.new("1", (image.width, phys_h), 1)
            img_padded.paste(image.crop((0, 0, image.width, min(image.height, phys_h))), (0, 0))
            image = img_padded

        # Traceur TX/RX horodaté, activé via TILAU_NIIMBOT_TRACE=1, dumpé en fin d'impression.
        self._trace = []
        self._trace_on = bool(os.environ.get("TILAU_NIIMBOT_TRACE"))
        self.print_failure = ""
        self.labels_confirmed = 0

        niimbot_packets_with_lines = self._get_niimbot_packets(image)
        total_packets = len(niimbot_packets_with_lines)

        _logd.debug(f"Total Niimbot packets: {total_packets}. Total lines: {image.height}")

        # Compteur de progression : 0 / total avant d'envoyer le premier bloc.
        self.print_progress.emit(0, image.height)

        # last check that print can be done
        hb = self.get_heartbeat()  # Pour s'assurer que la connexion est active
        # Émettre le statut pour que l'overlay reflète l'état réel avant impression
        self.status_updated.emit(hb, None)
        no_answer = QApplication.translate("tilauscope_label", "the printer did not answer")
        if not hb.valid:
            return self._abort(no_answer, "heartbeat")
        cover_open = QApplication.translate("tilauscope_label","cover is opened, cannot print")
        if hb.paperstate is not None and hb.paperstate != 0:
            return self._abort(cover_open, "cover open")
        if hb.closingstate is not None and hb.closingstate != 0:
            return self._abort(cover_open, "cover open")
        # ── Flux D110M V4 : setDensity, setLabelType, printStart, printStatus,
        # setPageSize, lignes image (0x84/0x85), pageEnd, printEnd.
        # An unanswered setup step stops the print: nothing has reached the head yet.
        if not self._answered("setDensity", self.set_label_density(density)):
            return self._abort(no_answer, "setDensity")
        if not self._answered("setLabelType", self.set_label_type(labelsize)):
            return self._abort(no_answer, "setLabelType")
        # From printStart on, a job may be open on the printer: close it before giving up.
        # Copies are one job: the label goes out once with the count, as niimbluelib sends it.
        ready = self._answered("printStart", self.print_start_9b(copies))
        if ready:
            self.print_status_oneway()
            ready = self._answered(
                "setPageSize", self.set_page_size_13b(image.height, image.width, copies))
        if not ready:
            self.end_print()
            return self._abort(no_answer, "page setup")

        time.sleep(0.02)
        # Chaque paquet Niimbot est écrit individuellement : regrouper plusieurs
        # paquets dans une même écriture BLE désynchronise le firmware → blanc.
        n = max(1, total_packets)
        for i, (pkt_bytes, _lines) in enumerate(niimbot_packets_with_lines):
            self._tr("TX", f"0x{pkt_bytes[2]:02x}", len(pkt_bytes) - 7)
            self.send(message=pkt_bytes, chunk=MAX_BLE_CHUNK_SIZE)
            time.sleep(_PACKET_INTERVAL_S)
            self.print_progress.emit(
                min(int(image.height * (i + 1) / n), image.height), image.height)
        self.print_progress.emit(image.height, image.height)

        # pageEnd → ATTENDRE la fin réelle d'impression (poll status) → printEnd.
        # Le firmware D110M V4 brûle l'étiquette APRÈS pageEnd ; sonder 0xA3
        # jusqu'à page==totalPages avant de couper évite l'éjection blanche.
        # Only the status poll decides the outcome; the pageEnd and printEnd answers are logged.
        self._answered("pageEnd", self.end_page_print())
        # A stop ends the wait after the label being printed; printEnd then closes the job.
        confirmed = self._wait_print_finished_by_status(
            total_pages=copies, stop_requested=stop_requested, on_label_out=on_label_out)
        self._answered("printEnd", self.end_print())
        self.labels_confirmed = confirmed or 0
        outcome = NiimbotPrintOutcome.UNCONFIRMED if confirmed is None else NiimbotPrintOutcome.PRINTED
        _logd.debug(f"End of print sequence sent (D110M V4): {outcome.value}, "
                    f"{self.labels_confirmed}/{copies} labels.")
        # Vide la trace TX/RX horodatée dans ~/Downloads/tilau_print_trace.txt.
        self._dump_trace(f"img={image.width}x{image.height} density={density} copies={copies} "
                         f"confirmed={self.labels_confirmed} packets={total_packets} "
                         f"outcome={outcome.value}")
        return outcome
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
# -*- coding: utf-8 -*-

# tilauscope/tilau_ble_scanner.py
#
# Scanner BLE centralisé pour Beancave.
#
# Architecture :
#   - Un seul cycle de scan toutes les 8s (3s discover + 5s pause)
#   - Le scan tourne dans la loop du singleton ble = BLE() de ble_port
#     (même loop que tous les BleakClient) — évite les conflits CBCentralManager
#     sur macOS Core Bluetooth qui n'accepte qu'un seul gestionnaire BLE actif.
#   - Les résultats sont émis via devices_found(list) — chaque worker filtre
#     par adresse ou préfixe de nom, le scanner ne connaît pas les workers.
#
# Auteur : TiLau 2025

import asyncio
import logging
import threading

from typing import Final, TYPE_CHECKING

from concurrent.futures import CancelledError

from bleak import BleakScanner
from bleak.exc import BleakBluetoothNotAvailableError, BleakError

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

_log: Final[logging.Logger] = logging.getLogger(__name__)

SCAN_DURATION : Final[float] = 3.0   # durée du discover BLE (incompressible macOS)
SCAN_PAUSE    : Final[float] = 5.0   # pause entre cycles → cycle total = 8s


class TilauBLEScanner(QObject):
    """
    Scanner BLE centralisé, cycle 8 secondes.

    Tous les scans sont soumis dans la loop du singleton ble de ble_port —
    la seule loop compatible avec BleakClient sur macOS Core Bluetooth.

    Usage :
        self._ble_scanner = TilauBLEScanner()
        self._ble_scanner.devices_found.connect(self.np.on_devices_found)
        self._ble_scanner.start()
        # à la fermeture :
        self._ble_scanner.stop()
    """

    devices_found = pyqtSignal(list)  # list[tuple[BLEDevice, AdvertisementData]]

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._adapter_missing = False  # aucun adaptateur BLE présent → scans désactivés
        # concurrent.futures.Future du discover en cours — annulé à l'arrêt pour
        # stopper le scan CoreBluetooth SANS attendre le timeout (jusqu'à 18s).
        # Sinon un scan reste actif et son callback didDiscoverPeripheral peut
        # rentrer en Python pendant _Py_Finalize → crash natif à la fermeture.
        self._current_fut: "object | None" = None

    # ── API publique ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            _log.warning("TilauBLEScanner already running")
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._scan_loop,
            name="TilauBLEScanner",
            daemon=True,
        )
        self._thread.start()
        _log.info("TilauBLEScanner started — cycle %.0fs+%.0fs", SCAN_DURATION, SCAN_PAUSE)

    def stop(self) -> None:
        if not self._running:
            return
        _log.info("TilauBLEScanner stopping…")
        self._running = False
        self._stop_event.set()
        # Annuler le discover en vol : propage CancelledError dans la loop ble,
        # BleakScanner.__aexit__ appelle stopScan() → CoreBluetooth cesse de
        # scanner immédiatement, le thread de scan débloque et sort proprement.
        fut = self._current_fut
        if fut is not None:
            try:
                fut.cancel()
            except Exception:  # pylint: disable=broad-except
                pass
        if self._thread is not None:
            self._thread.join(timeout=SCAN_DURATION + 1.0)
            if self._thread.is_alive():
                _log.warning("TilauBLEScanner thread did not stop cleanly")
            self._thread = None

    # ── Boucle interne ────────────────────────────────────────────────────────

    def _scan_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                devices = self._do_scan()
                if devices and not self._stop_event.is_set():
                    self.devices_found.emit(devices)
                    _log.debug("TilauBLEScanner: %d device(s) found", len(devices))
            except BleakBluetoothNotAvailableError:
                # Aucun adaptateur Bluetooth présent (ex. PC de bureau sans dongle).
                # Inutile de retenter toutes les 8s : on logue une seule fois et on
                # coupe la boucle de scan pour ne pas polluer les logs.
                self._adapter_missing = True
                self._running = False
                _log.info(
                    "TilauBLEScanner: no Bluetooth adapter found — scanner disabled"
                )
                break
            except BleakError as e:
                _log.error("TilauBLEScanner: BLE error — %s", e)
                self._stop_event.wait(timeout=5.0)
            except Exception as e:  # pylint: disable=broad-except
                _log.exception("TilauBLEScanner: unexpected error — %s", e)
                self._stop_event.wait(timeout=5.0)

            if self._running and not self._stop_event.is_set():
                self._stop_event.wait(timeout=SCAN_PAUSE)

        _log.info("TilauBLEScanner thread exited")

    def _do_scan(self) -> "list[tuple[BLEDevice, AdvertisementData]]":
        """
        Lance BleakScanner.discover dans la loop du singleton ble de ble_port.
        C'est la même loop que tous les BleakClient — un seul CBCentralManager
        actif sur macOS, pas de conflit inter-loop.
        """
        from artisanlib.ble_port import ble

        # S'assurer que la loop de ble est démarrée
        if ble._asyncLoopThread is None:
            ble._asyncLoopThread = __import__(
                'artisanlib.async_comm', fromlist=['AsyncLoopThread']
            ).AsyncLoopThread()

        loop = ble._asyncLoopThread.loop

        async def _scan_with_lock() -> dict:
            # Utiliser le même lock que scan_and_connect pour éviter
            # qu'un scan et une connexion tournent simultanément dans
            # la loop de ble — Core Bluetooth n'est pas réentrant.
            if ble._scan_and_connect_lock is None:
                ble._scan_and_connect_lock = asyncio.Lock()
            async with ble._scan_and_connect_lock:
                return await BleakScanner.discover(
                    timeout=SCAN_DURATION, return_adv=True
                )

        fut = asyncio.run_coroutine_threadsafe(_scan_with_lock(), loop)
        self._current_fut = fut  # exposé à stop() pour annulation immédiate
        try:
            # Bloquant dans le thread TilauBLEScanner — pas dans la loop ble.
            # Timeout = scan + attente lock (max connect_timeout = 10s) + marge.
            raw: dict = fut.result(timeout=SCAN_DURATION + 15.0)
            return list(raw.values())
        except BleakBluetoothNotAvailableError:
            # Laisser remonter à _scan_loop qui désactive le scanner et logue
            # une seule fois (sinon spam ERROR à chaque cycle).
            raise
        except CancelledError:
            # Arrêt demandé (stop()) : le discover a été annulé, scan stoppé.
            return []
        except TimeoutError:
            _log.warning("TilauBLEScanner: discover timeout")
            return []
        except Exception as e:
            _log.error("TilauBLEScanner: discover error — %s", e)
            return []
        finally:
            self._current_fut = None
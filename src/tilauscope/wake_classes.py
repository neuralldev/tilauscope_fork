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


import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from wakepy import keep

from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)


class TilauWorkerThread(QObject):
    """Holds the wakepy keep.presenting lock for the duration of a roast.

    Runs in a dedicated QThread. Stop is driven by QThread.requestInterruption()
    called from TilauController.finish() — no cross-thread attribute access needed.
    """
    finished = pyqtSignal()

    def run(self) -> None:
        _log.debug('TilauScope wake: acquiring keep-awake lock')
        try:
            with keep.presenting():
                while not QThread.currentThread().isInterruptionRequested():
                    QThread.msleep(500)
        except Exception:  # pylint: disable=broad-except
            _log.exception('TilauScope wake: exception in keep.presenting')
        finally:
            _log.debug('TilauScope wake: keep-awake lock released')
            self.finished.emit()


class TilauController(QObject):
    """Manages the wake-lock lifecycle, driven by roast ON/OFF signals.

    Usage (canvas.py):
        self.tilau_ssbserver = TilauController()
        # on roast start:
        self.tilau_ssbserver.start()
        # on roast stop / reset / app close:
        self.tilau_ssbserver.terminatingSignal.emit()
    """
    terminatingSignal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._worker: TilauWorkerThread | None = None
        self.terminatingSignal.connect(self.finish)

    def start(self) -> None:
        """Activate keep-awake. No-op if already running."""
        if self._thread is not None and self._thread.isRunning():
            return
        _log.info('TilauScope wake: prevent sleep/hibernation started')
        self._launch_thread()

    @pyqtSlot()
    def finish(self) -> None:
        """Deactivate keep-awake. Safe to call multiple times."""
        if self._thread is None:
            return
        _log.info('TilauScope wake: releasing sleep lock')
        self._thread.requestInterruption()  # signals worker loop to exit
        self._thread.quit()
        self._thread.wait(3000)             # max 3s — keep.presenting releases quickly
        self._thread = None
        self._worker = None

    def _launch_thread(self) -> None:
        thread = QThread()
        worker = TilauWorkerThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        # thread ref kept on self for .wait() in finish() — no deleteLater on thread

        self._thread = thread
        self._worker = worker
        thread.start()
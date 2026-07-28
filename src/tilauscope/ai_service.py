#
# ABOUT
# ai service

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
# TiLau 2025

from __future__ import annotations

import logging
import threading
from enum import StrEnum
from typing import Final, Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from tilauscope.ai_support import TilauAIConfig

_log: Final[logging.Logger] = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Task type registry
# Each consumer registers a unique task type string.
# TilauAIService uses it as the mutex key → one active job per task type.
# ─────────────────────────────────────────────────────────────────────────────

class AITask(StrEnum):
    BEAN_EXTRACT   = "BEAN_EXTRACT"    # beancave: scrape URL → GreenBean
    ALARM_NARRATIVE = "ALARM_NARRATIVE" # visualalarm: timeline → markdown narrative
    ROAST_SUMMARY  = "ROAST_SUMMARY"   # roast_properties: post-roast session summary
    BREW_ADVICE    = "BREW_ADVICE"     # beancave: brew recipe refinement pass

# ─────────────────────────────────────────────────────────────────────────────
# Internal worker
# Runs a callable in a QThread. Reports token stream and final result.
# The callable receives a CancelToken and must check it periodically.
# ─────────────────────────────────────────────────────────────────────────────

class _CancelToken:
    """Thread-safe cancellation flag passed into worker callables."""
    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class _AIWorker(QObject):
    """
    Generic QObject worker.
    work_fn signature: (cancel_token: _CancelToken, on_token: Callable[[str], None]) -> Any
    The callable must:
      - call on_token(chunk) for each streamed token (or not at all for batch mode)
      - return the final assembled result as a str (or any picklable value)
      - raise on error
    """
    token   = pyqtSignal(str)          # partial token during streaming
    finished = pyqtSignal(object)      # final result (str or structured)
    error    = pyqtSignal(str)         # error message

    def __init__(self, work_fn: Callable, cancel_token: _CancelToken) -> None:
        super().__init__()
        self._work_fn     = work_fn
        self._cancel_token = cancel_token

    def run(self) -> None:
        try:
            result = self._work_fn(
                self._cancel_token,
                lambda chunk: self.token.emit(chunk),
            )
            if not self._cancel_token.is_cancelled:
                self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            if not self._cancel_token.is_cancelled:
                self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# TilauAIService  –  attach to aw as  aw.tilau_ai_service = TilauAIService(aw.tilau_aiConfig)
# ─────────────────────────────────────────────────────────────────────────────

class TilauAIService(QObject):
    """
    Centralized AI task dispatcher for TilauScope.

    Usage
    -----
        # Connect once (e.g. in the consumer widget __init__):
        aw.tilau_ai_service.token_received.connect(self._on_token)
        aw.tilau_ai_service.task_finished.connect(self._on_finished)
        aw.tilau_ai_service.task_error.connect(self._on_error)
        aw.tilau_ai_service.task_busy.connect(self._on_busy)

        # Submit a task (returns False if task_type already running):
        ok = aw.tilau_ai_service.submit(AITask.BEAN_EXTRACT, payload, work_fn)

        # Cancel if needed:
        aw.tilau_ai_service.cancel(AITask.BEAN_EXTRACT)

    Signals carry the task_type str so consumers can filter for their own tasks.
    """

    # ── Public signals ────────────────────────────────────────────────────────
    task_started  = pyqtSignal(str)           # (task_type)
    task_busy     = pyqtSignal(str)           # (task_type) already running
    token_received = pyqtSignal(str, str)     # (task_type, token_chunk)
    task_finished  = pyqtSignal(str, object)  # (task_type, result)
    task_error     = pyqtSignal(str, str)     # (task_type, error_msg)
    task_cancelled = pyqtSignal(str)          # (task_type)

    def __init__(self, ai_config: TilauAIConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ai_config: TilauAIConfig = ai_config

        # Active slots: task_type → (QThread, _AIWorker, _CancelToken)
        self._active: dict[str, tuple[QThread, _AIWorker, _CancelToken]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def is_busy(self, task_type: str) -> bool:
        """Return True if a job of this type is currently running."""
        return task_type in self._active

    def submit(
        self,
        task_type: str,
        work_fn: Callable[[_CancelToken, Callable[[str], None]], Any],
    ) -> bool:
        """
        Submit a task.

        work_fn receives (cancel_token, on_token_callback) and must return
        the final result.  Call on_token_callback(chunk) for streaming.

        Returns False and emits task_busy if the task_type is already running.
        """
        if task_type in self._active:
            _log.info("TilauAIService: task %s already running → busy", task_type)
            self.task_busy.emit(task_type)
            return False

        cancel_token = _CancelToken()
        thread  = QThread(self)
        worker  = _AIWorker(work_fn, cancel_token)
        worker.moveToThread(thread)

        # Wire signals
        thread.started.connect(worker.run)
        worker.token.connect(
            lambda chunk, tt=task_type: self.token_received.emit(tt, chunk)
        )
        worker.finished.connect(
            lambda result, tt=task_type: self._on_worker_finished(tt, result)
        )
        worker.error.connect(
            lambda msg, tt=task_type: self._on_worker_error(tt, msg)
        )
        # Cleanup on thread finish
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._active[task_type] = (thread, worker, cancel_token)
        self.task_started.emit(task_type)
        thread.start()
        _log.info("TilauAIService: started task %s", task_type)
        return True

    def cancel(self, task_type: str) -> None:
        """Request cancellation of a running task. Non-blocking for the caller."""
        entry = self._active.pop(task_type, None)
        if entry is None:
            return
        thread, _worker, cancel_token = entry
        _log.info("TilauAIService: cancelling task %s", task_type)
        cancel_token.cancel()
        thread.quit()
        # Give the thread up to 3 seconds to finish cleanly before we
        # let the QThread object be garbage-collected. Without this wait()
        # Qt logs "QThread: Destroyed while thread is still running".
        if not thread.wait(3000):
            _log.warning("TilauAIService: thread for %s did not stop in time", task_type)
        self.task_cancelled.emit(task_type)

    def cancel_all(self) -> None:
        """Cancel all running tasks. Call on application shutdown."""
        for task_type in list(self._active):
            self.cancel(task_type)

    # ── Internal slots ────────────────────────────────────────────────────────

    def _on_worker_finished(self, task_type: str, result: Any) -> None:
        self._cleanup(task_type)
        self.task_finished.emit(task_type, result)
        _log.info("TilauAIService: task %s finished", task_type)

    def _on_worker_error(self, task_type: str, msg: str) -> None:
        self._cleanup(task_type)
        self.task_error.emit(task_type, msg)
        _log.error("TilauAIService: task %s error: %s", task_type, msg)

    def _cleanup(self, task_type: str) -> None:
        entry = self._active.pop(task_type, None)
        if entry:
            thread, _worker, _token = entry
            thread.quit()
            # thread.wait() is NOT called here — the worker has already
            # finished (this is called from worker.finished/error signals),
            # so quit() returns immediately. deleteLater handles object cleanup.
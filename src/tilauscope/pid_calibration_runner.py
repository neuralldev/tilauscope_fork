# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Qt clock adapter for the PID calibration coordinator.

This object contains no machine-specific reading or writing code.  Those
boundaries are injected and the class is deliberately not connected to the
visible start button yet.  Its job is to guarantee one-second observation,
acknowledgement routing, manual-override latching and terminal journal export.
"""

from __future__ import annotations

import time
import math
from collections import deque
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal

from tilauscope.pid_calibration import (
    CalibrationCommand,
    CalibrationReadinessReport,
    CalibrationSample,
    LiveCalibrationCoordinator,
)


def temperature_to_c(value: float, unit: str) -> float:
    """Convert an absolute Artisan temperature to the protocol's °C unit."""
    return (value - 32.0) / 1.8 if unit.upper() == "F" else value


class LiveCalibrationSampleObserver:
    """Create canonical samples and reject a source whose clock stops moving."""

    def __init__(
        self,
        *,
        read_temperature: Callable[[], float | None],
        read_source_token: Callable[[], object | None],
        temperature_unit: str,
        stale_after_sec: float = 3.5,
    ) -> None:
        self.read_temperature = read_temperature
        self.read_source_token = read_source_token
        self.temperature_unit = temperature_unit
        self.stale_after_sec = stale_after_sec
        self._last_token: object | None = None
        self._last_token_change_sec: float | None = None
        self._history: deque[tuple[float, float]] = deque(maxlen=8)

    def sample(self, elapsed_sec: float, manual_override: bool) -> CalibrationSample:
        """Read one point; an absent, invalid or stale source fails closed."""
        native = self.read_temperature()
        token = self.read_source_token()
        if token is not None and (
            self._last_token_change_sec is None or token != self._last_token
        ):
            self._last_token = token
            self._last_token_change_sec = elapsed_sec
        communication_ok = bool(
            token is not None
            and self._last_token_change_sec is not None
            and elapsed_sec - self._last_token_change_sec <= self.stale_after_sec
        )
        sensor_valid = bool(
            native is not None
            and native != -1.0
            and math.isfinite(native)
            and communication_ok
        )
        temperature_c = (
            temperature_to_c(native, self.temperature_unit)
            if sensor_valid and native is not None
            else math.nan
        )
        if sensor_valid:
            self._history.append((elapsed_sec, temperature_c))
        ror = 0.0
        if len(self._history) >= 2:
            first_at, first_temperature = self._history[0]
            dt = elapsed_sec - first_at
            if dt > 0.1:
                ror = (temperature_c - first_temperature) / dt * 60.0
        return CalibrationSample(
            now_sec=elapsed_sec,
            temperature_c=temperature_c,
            ror_c_per_min=ror,
            sensor_valid=sensor_valid,
            communication_ok=communication_ok,
            manual_override=manual_override,
        )


# Every broad catch is an intentional hardware, sensor or disk exception
# boundary and is immediately converted to the coordinator's fail-safe path.
# pylint: disable=broad-exception-caught
class PIDCalibrationRunner(QObject):
    """Drive a live coordinator from Qt while keeping all effects injectable."""

    progress = pyqtSignal(str, int)
    finished = pyqtSignal(str, str)

    def __init__(
        self,
        coordinator: LiveCalibrationCoordinator,
        *,
        readiness_provider: Callable[[], CalibrationReadinessReport],
        sample_provider: Callable[[float, bool], CalibrationSample],
        runtime_stop_provider: Callable[[bool, bool], str | None],
        applied_signal: Any,
        manual_signal: Any,
        persist_journal: Callable[[LiveCalibrationCoordinator], None],
        review_only: bool = False,
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.coordinator = coordinator
        self.readiness_provider = readiness_provider
        self.sample_provider = sample_provider
        self.runtime_stop_provider = runtime_stop_provider
        self.persist_journal = persist_journal
        self.review_only = review_only
        self.clock = clock
        self._started_at: float | None = None
        self._manual_override = False
        self._finalized = False
        self.journal_persisted = False
        self._applied_signal = applied_signal
        self._manual_signal = manual_signal
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self._applied_signal.connect(self._acknowledge)
        self._manual_signal.connect(self._manual_moved)

    def start(self) -> CalibrationCommand:
        """Recheck readiness, take the first sample and start the Qt clock."""
        if self._started_at is not None:
            raise RuntimeError("calibration runner already started")
        self._started_at = self.clock()
        try:
            command = self.coordinator.start(
                self.sample_provider(0.0, False),
                readiness=self.readiness_provider(),
            )
        except Exception:  # noqa: BLE001 - live observation boundary
            command = self.coordinator.abort("runner_start_failed", now_sec=0.0)
        if self.coordinator.phase == "running":
            self.timer.start()
            self._emit_progress(command)
        else:
            self._finalize()
        return command

    def abort(self, reason: str = "operator_cancelled") -> CalibrationCommand:
        """Stop through the coordinator's single zero-and-rollback path."""
        elapsed = self._elapsed()
        command = self.coordinator.abort(reason, now_sec=elapsed)
        self._finalize()
        return command

    def close(self) -> None:
        """Disconnect after forcing a safe stop if the runner is active."""
        if self.coordinator.phase == "running":
            self.abort("runner_closed")
        self.timer.stop()
        for signal, callback in (
            (self._applied_signal, self._acknowledge),
            (self._manual_signal, self._manual_moved),
        ):
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError, ValueError):
                pass

    def _elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self.clock() - self._started_at)

    def _tick(self) -> None:
        if self.coordinator.phase != "running":
            self._finalize()
            return
        elapsed = self._elapsed()
        try:
            sample = self.sample_provider(elapsed, self._manual_override)
            stop_reason = self.runtime_stop_provider(
                self._manual_override, sample.communication_ok
            )
            command = self.coordinator.update(
                sample, runtime_stop_reason=stop_reason
            )
        except Exception:  # noqa: BLE001 - live observation boundary
            command = self.coordinator.abort(
                "sample_or_interlock_failed", now_sec=elapsed
            )
        self._emit_progress(command)
        if self.coordinator.phase != "running":
            self._finalize()

    def _acknowledge(
        self, heater_slider: int, applied_power: int, action_fired: bool
    ) -> None:
        self.coordinator.acknowledge(
            heater_slider=heater_slider,
            applied_power_pct=applied_power,
            action_fired=action_fired,
            now_sec=self._elapsed(),
        )
        if self.coordinator.phase != "running" and not self._finalized:
            self._finalize()

    def _manual_moved(self, _slider: int, _value: int) -> None:
        self._manual_override = True

    def _emit_progress(self, command: CalibrationCommand) -> None:
        self.progress.emit(command.phase, min(600, round(self._elapsed())))

    def _finalize(self) -> None:
        if self._finalized:
            return
        # Terminal zero acknowledgements can be delivered synchronously while
        # this method is dispatching them. Mark finalization first so that the
        # nested signal cannot persist or emit `finished` a second time.
        self._finalized = True
        self.timer.stop()
        if self.review_only and self.coordinator.phase == "complete":
            self.coordinator.abort(
                "pilot_completed_pending_review", now_sec=self._elapsed()
            )
        elif self.coordinator.phase == "complete":
            self.coordinator.request_zero_after_complete(now_sec=self._elapsed())
        try:
            self.persist_journal(self.coordinator)
            self.journal_persisted = True
        except Exception:  # noqa: BLE001 - disk boundary must fail safe too
            if self.coordinator.phase == "complete":
                self.coordinator.abort(
                    "journal_persistence_failed", now_sec=self._elapsed()
                )
                try:
                    self.persist_journal(self.coordinator)
                    self.journal_persisted = True
                except Exception:  # noqa: BLE001 - already at zero and restored
                    self.journal_persisted = False
            if not self.journal_persisted:
                self.coordinator.reason = (
                    "journal_persistence_failed"
                    if self.coordinator.reason is None
                    else f"{self.coordinator.reason};journal_persistence_failed"
                )
        self.finished.emit(
            self.coordinator.phase, self.coordinator.reason or ""
        )
# pylint: enable=broad-exception-caught

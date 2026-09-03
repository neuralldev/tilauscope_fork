"""Qt-clock boundary tests for the live PID calibration runner."""

from __future__ import annotations

from typing import Any

from tilauscope.pid_calibration import (
    CalibrationLimits,
    CalibrationProtocol,
    CalibrationReadinessInputs,
    CalibrationSample,
    LiveCalibrationCoordinator,
    evaluate_calibration_readiness,
)
from tilauscope.pid_calibration_runner import (
    LiveCalibrationSampleObserver,
    PIDCalibrationRunner,
    temperature_to_c,
)


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)

    def disconnect(self, callback: Any) -> None:
        self.callbacks.remove(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


class _Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


def test_absolute_fahrenheit_conversion_is_not_a_simple_scale() -> None:
    assert temperature_to_c(32.0, "F") == 0.0
    assert temperature_to_c(212.0, "F") == 100.0


def test_live_observer_computes_canonical_ror_and_rejects_frozen_source() -> None:
    values = {"temperature": 212.0, "token": 1}
    observer = LiveCalibrationSampleObserver(
        read_temperature=lambda: values["temperature"],
        read_source_token=lambda: values["token"],
        temperature_unit="F",
        stale_after_sec=3.5,
    )

    first = observer.sample(0.0, False)
    values.update(temperature=213.8, token=2)
    second = observer.sample(2.0, False)
    frozen = observer.sample(5.6, False)

    assert first.temperature_c == 100.0
    assert second.temperature_c == 101.0
    assert second.ror_c_per_min == 30.0
    assert not frozen.sensor_valid
    assert not frozen.communication_ok


def _readiness():
    return evaluate_calibration_readiness(CalibrationReadinessInputs(
        monitoring_active=True,
        machine_identity_known=True,
        roast_started=False,
        software_pid_selected=True,
        gain_scheduling_active=False,
        artisan_pid_active=False,
        sensor_valid=True,
        stable_sample_count=30,
        holding_point_confirmed=True,
        temperature_span_c=0.0,
        max_abs_ror_c_per_min=0.0,
        heater_slider=3,
        heater_action_configured=True,
        airflow_path_configured=True,
        extractor_not_cooling=True,
        hot_minutes_used=7.0,
        hot_minutes_budget=30.0,
        hot_minutes_required=10.5,
        actuator_direction_normal=True,
        current_power_pct=30.0,
        power_min_pct=0.0,
        power_max_pct=80.0,
        required_power_room_pct=13.0,
        simulator_active=False,
        preheat_pid_active=False,
        rollback_snapshot_available=True,
        machine_empty_confirmed=True,
        airflow_safe_confirmed=True,
        supervision_confirmed=True,
    ))


def _runner(*, journal_raises: bool = False):
    requests: list[tuple[int, int, bool]] = []
    restores: list[bool] = []
    journals: list[str] = []
    applied = _Signal()
    manual = _Signal()
    clock = _Clock()
    coordinator = LiveCalibrationCoordinator(
        CalibrationProtocol(
            CalibrationLimits(target_c=200.0, baseline_power_pct=30.0),
            current_kp=10.0,
            current_ki=0.15,
            current_kd=0.0,
        ),
        heater_slider=3,
        zero_output_qualified=True,
        request_power=lambda slider, power, fire: requests.append(
            (slider, power, fire)
        ),
        apply_candidate=lambda _candidate: None,
        restore_config=lambda: restores.append(True),
    )

    def persist(value: LiveCalibrationCoordinator) -> None:
        journals.append(value.phase)
        if journal_raises:
            raise OSError("disk full")

    runner = PIDCalibrationRunner(
        coordinator,
        readiness_provider=_readiness,
        sample_provider=lambda elapsed, manual_override: CalibrationSample(
            elapsed, 200.0, 0.0, manual_override=manual_override
        ),
        runtime_stop_provider=(
            lambda manual_override, communication_ok:
            "manual_override" if manual_override else (
                None if communication_ok else "communication_lost"
            )
        ),
        applied_signal=applied,
        manual_signal=manual,
        persist_journal=persist,
        clock=clock,
    )
    return runner, coordinator, requests, restores, journals, applied, manual, clock


def test_runner_routes_ack_and_manual_override_to_one_safe_stop(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, applied, manual, clock = _runner()
    runner.start()
    assert requests == [(3, 30, True)]
    applied.emit(3, 30, True)

    manual.emit(3, 29)
    clock.now += 1.0
    runner._tick()

    assert coordinator.phase == "safe_stop"
    assert coordinator.reason == "manual_override"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]
    assert journals == ["safe_stop"]
    runner.close()


def test_runner_close_is_fail_safe_and_persists_once(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, _applied, _manual, _clock = _runner()
    runner.start()
    runner.close()

    assert coordinator.reason == "runner_closed"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]
    assert journals == ["safe_stop"]


def test_runner_start_exception_still_requests_zero_and_rollback(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, _applied, _manual, _clock = _runner()
    runner.sample_provider = lambda _elapsed, _manual: (_ for _ in ()).throw(
        RuntimeError("sensor")
    )
    runner.start()

    assert coordinator.reason == "runner_start_failed"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]
    assert journals == ["safe_stop"]
    runner.close()


def test_review_only_success_is_cut_to_zero_and_rolled_back(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, _applied, _manual, _clock = _runner()
    runner.review_only = True
    coordinator.phase = "complete"

    runner._finalize()

    assert coordinator.phase == "safe_stop"
    assert coordinator.reason == "pilot_completed_pending_review"
    assert requests == [(3, 0, True)]
    assert restores == [True]
    assert journals == ["safe_stop"]
    assert runner.journal_persisted
    runner.close()


def test_accepted_success_is_cut_to_zero_without_rolling_back(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, applied, _manual, _clock = _runner()
    coordinator.phase = "complete"

    runner._finalize()

    assert coordinator.phase == "complete"
    assert requests == [(3, 0, True)]
    assert restores == []
    assert coordinator.shutdown_command_dispatched is False
    applied.emit(3, 0, True)
    assert coordinator.shutdown_command_dispatched is True
    assert journals == ["complete"]
    runner.close()


def test_journal_failure_is_visible_after_safe_stop(qapp: Any) -> None:  # noqa: ARG001
    runner, coordinator, requests, restores, journals, _applied, _manual, _clock = (
        _runner(journal_raises=True)
    )
    runner.start()
    runner.close()

    assert coordinator.phase == "safe_stop"
    assert coordinator.reason == "runner_closed;journal_persistence_failed"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]
    assert journals == ["safe_stop"]
    assert not runner.journal_persisted

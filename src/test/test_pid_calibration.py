"""Simulation tests for the ten-minute PID calibration protocol."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
import math

import pytest

from tilauscope.pid_calibration import (
    CalibrationCommand,
    CalibrationLimits,
    CalibrationPoint,
    CalibrationPhase,
    CalibrationProtocol,
    CalibrationReadinessInputs,
    CalibrationRuntimeInterlocks,
    CalibrationSample,
    CalibrationTiming,
    IdentificationError,
    LiveCalibrationCoordinator,
    ZeroOutputQualification,
    evaluate_calibration_readiness,
    identify_local_fopdt,
    runtime_interlock_reason,
    verify_calibration_audit,
)


def _ready_facts(**changes: object) -> CalibrationReadinessInputs:
    facts: dict[str, object] = {
        "monitoring_active": True,
        "machine_identity_known": True,
        "roast_started": False,
        "software_pid_selected": True,
        "gain_scheduling_active": False,
        "artisan_pid_active": False,
        "sensor_valid": True,
        "stable_sample_count": 45,
        "max_abs_error_c": 0.2,
        "temperature_span_c": 0.1,
        "max_abs_ror_c_per_min": 0.1,
        "heater_slider": 3,
        "heater_action_configured": True,
        "actuator_direction_normal": True,
        "current_power_pct": 30.0,
        "power_min_pct": 0.0,
        "power_max_pct": 80.0,
        "required_power_room_pct": 13.0,
        "simulator_active": False,
        "preheat_pid_active": False,
        "rollback_snapshot_available": True,
        "machine_empty_confirmed": True,
        "airflow_safe_confirmed": True,
        "supervision_confirmed": True,
    }
    facts.update(changes)
    return CalibrationReadinessInputs(**facts)  # type: ignore[arg-type]


def test_live_readiness_requires_every_automatic_and_human_gate() -> None:
    report = evaluate_calibration_readiness(_ready_facts())
    assert report.ready
    assert report.blocking_codes == ()


@pytest.mark.parametrize(
    ("change", "value", "blocking_code"),
    [
        ("monitoring_active", False, "monitoring_active"),
        ("machine_identity_known", False, "machine_identity_known"),
        ("roast_started", True, "no_roast_running"),
        ("software_pid_selected", False, "software_pid_selected"),
        ("gain_scheduling_active", True, "gain_scheduling_disabled"),
        ("artisan_pid_active", True, "artisan_pid_stopped"),
        ("sensor_valid", False, "sensor_valid"),
        ("stable_sample_count", 29, "sensor_stable"),
        ("max_abs_error_c", 0.71, "sensor_stable"),
        ("temperature_span_c", 0.21, "sensor_stable"),
        ("max_abs_ror_c_per_min", 0.41, "sensor_stable"),
        ("heater_slider", None, "heater_slider_configured"),
        ("heater_action_configured", False, "heater_action_configured"),
        ("actuator_direction_normal", False, "normal_actuator_direction"),
        ("current_power_pct", None, "power_headroom"),
        ("current_power_pct", 75.0, "power_headroom"),
        ("simulator_active", True, "no_simulator"),
        ("preheat_pid_active", True, "preheat_pid_stopped"),
        ("rollback_snapshot_available", False, "rollback_snapshot_available"),
        ("machine_empty_confirmed", False, "machine_empty_confirmed"),
        ("airflow_safe_confirmed", False, "airflow_safe_confirmed"),
        ("supervision_confirmed", False, "supervision_confirmed"),
    ],
)
def test_live_readiness_fails_closed(
    change: str, value: object, blocking_code: str
) -> None:
    facts = _ready_facts(**{change: value})
    report = evaluate_calibration_readiness(facts)
    assert not report.ready
    assert blocking_code in report.blocking_codes


@pytest.mark.parametrize(
    ("change", "value", "reason"),
    [
        ("monitoring_active", False, "monitoring_stopped"),
        ("roast_started", True, "roast_started"),
        ("software_pid_selected", False, "external_pid_selected"),
        ("machine_identity_unchanged", False, "machine_identity_changed"),
        ("artisan_pid_active", True, "artisan_pid_started"),
        ("simulator_active", True, "simulator_started"),
        ("preheat_pid_active", True, "preheat_pid_started"),
        ("manual_override", True, "manual_override"),
        ("communication_ok", False, "communication_lost"),
    ],
)
def test_runtime_interlocks_map_every_live_fact_to_a_stop_reason(
    change: str, value: bool, reason: str
) -> None:
    facts: dict[str, bool] = {
        "monitoring_active": True,
        "roast_started": False,
        "software_pid_selected": True,
        "machine_identity_unchanged": True,
        "artisan_pid_active": False,
        "simulator_active": False,
        "preheat_pid_active": False,
        "manual_override": False,
        "communication_ok": True,
    }
    facts[change] = value
    assert runtime_interlock_reason(
        CalibrationRuntimeInterlocks(**facts)
    ) == reason


def test_runtime_interlocks_accept_only_the_nominal_live_state() -> None:
    assert runtime_interlock_reason(CalibrationRuntimeInterlocks(
        monitoring_active=True,
        roast_started=False,
        software_pid_selected=True,
        machine_identity_unchanged=True,
        artisan_pid_active=False,
        simulator_active=False,
        preheat_pid_active=False,
        manual_override=False,
        communication_ok=True,
    )) is None


def test_zero_output_qualification_requires_software_and_physical_proof() -> None:
    readiness = evaluate_calibration_readiness(_ready_facts())
    qualification = ZeroOutputQualification(timeout_sec=15.0)

    assert qualification.start(readiness, heater_slider=3, now_sec=10.0)
    assert qualification.phase == "command_requested"
    assert not qualification.acknowledge(
        heater_slider=2, applied_power_pct=0, action_fired=True, now_sec=11.0
    )
    assert qualification.acknowledge(
        heater_slider=3, applied_power_pct=0, action_fired=True, now_sec=11.0
    )
    assert qualification.phase == "software_zero_confirmed"
    assert qualification.confirm_physical_shutdown(
        heater_is_off=True, now_sec=12.0
    )
    assert qualification.phase == "qualified"


def test_zero_output_qualification_refuses_changed_readiness() -> None:
    readiness = evaluate_calibration_readiness(
        _ready_facts(roast_started=True)
    )
    qualification = ZeroOutputQualification()

    assert not qualification.start(readiness, heater_slider=3, now_sec=0.0)
    assert qualification.phase == "failed"
    assert qualification.reason == "readiness_changed"


def test_zero_output_qualification_rejects_nonzero_acknowledgement() -> None:
    qualification = ZeroOutputQualification()
    qualification.start(
        evaluate_calibration_readiness(_ready_facts()),
        heater_slider=3,
        now_sec=0.0,
    )

    assert not qualification.acknowledge(
        heater_slider=3, applied_power_pct=1, action_fired=True, now_sec=1.0
    )
    assert qualification.phase == "failed"
    assert qualification.reason == "zero_not_applied"


@pytest.mark.parametrize("phase", ["command_requested", "software_zero_confirmed"])
def test_zero_output_qualification_times_out_fail_safe(phase: str) -> None:
    qualification = ZeroOutputQualification(timeout_sec=15.0)
    qualification.start(
        evaluate_calibration_readiness(_ready_facts()),
        heater_slider=3,
        now_sec=0.0,
    )
    if phase == "software_zero_confirmed":
        qualification.acknowledge(
            heater_slider=3,
            applied_power_pct=0,
            action_fired=True,
            now_sec=1.0,
        )

    assert qualification.poll(15.01) == "failed"
    assert qualification.reason == "qualification_timeout"


def _run_virtual_plant(
    *,
    gain_c_per_pct: float = 0.15,
    tau_sec: float = 55.0,
    delay_sec: int = 5,
    target_margin_c: float = 2.0,
    sensor_noise_c: float = 0.0,
) -> tuple[CalibrationProtocol, CalibrationCommand, dict[int, str]]:
    baseline_power = 30.0
    target = 200.0
    protocol = CalibrationProtocol(
        CalibrationLimits(
            target_c=target,
            baseline_power_pct=baseline_power,
            target_margin_c=target_margin_c,
        ),
        current_kp=10.0,
        current_ki=0.15,
        current_kd=0.0,
    )
    delayed_powers = deque(
        [baseline_power] * (delay_sec + 1), maxlen=delay_sec + 1
    )
    temperature = target
    previous_measurement = target
    phases: dict[int, str] = {}
    command: CalibrationCommand | None = None

    for second in range(601):
        measurement = temperature + sensor_noise_c * math.sin(
            2.0 * math.pi * second / 30.0
        )
        ror = (measurement - previous_measurement) * 60.0 if second else 0.0
        sample = CalibrationSample(float(second), measurement, ror)
        command = protocol.start(sample) if second == 0 else protocol.update(sample)
        phases[second] = command.phase
        if command.done:
            break
        delayed_powers.append(command.power_pct)
        delayed_power = delayed_powers[0]
        previous_measurement = measurement
        offset = temperature - target
        offset += (
            gain_c_per_pct * (delayed_power - baseline_power) - offset
        ) / tau_sec
        temperature = target + offset

    assert command is not None
    return protocol, command, phases


def test_noisy_sensor_is_refused_instead_of_producing_false_gains() -> None:
    protocol, command, _phases = _run_virtual_plant(
        sensor_noise_c=0.8,
        target_margin_c=5.0,
    )

    assert command.phase == "refused"
    assert command.restore_config
    assert protocol.candidate is None
    assert command.reason in {
        "positive_response_not_confirmed",
        "signal_to_noise_too_low",
        "model_error_too_high",
    }


def test_inverted_thermal_response_cannot_produce_a_candidate() -> None:
    protocol, command, _phases = _run_virtual_plant(
        gain_c_per_pct=-0.15,
        target_margin_c=5.0,
    )

    assert command.phase == "refused"
    assert command.restore_config
    assert protocol.candidate is None
    assert command.reason == "positive_response_not_confirmed"
    assert max(_phases) == 150


def test_complete_virtual_test_identifies_and_accepts_safe_candidate() -> None:
    protocol, command, phases = _run_virtual_plant()

    assert command.done
    assert command.phase == "complete"
    assert phases[0] == "baseline"
    assert phases[60] == "step_up"
    assert phases[150] == "recover_up"
    assert phases[240] == "step_down"
    assert phases[330] == "recover_down"
    assert phases[420] == "identifying"
    assert phases[450] == "validating"
    assert phases[570] == "deciding"
    assert phases[600] == "complete"

    assert protocol.plant is not None
    assert protocol.plant.gain_c_per_pct == pytest.approx(0.15, abs=0.005)
    assert protocol.plant.tau_sec == pytest.approx(55.0, abs=5.0)
    assert protocol.plant.delay_sec == pytest.approx(5.0, abs=1.0)
    assert protocol.candidate is not None
    assert protocol.candidate.kd == 0.0
    assert protocol.validation_result is not None
    assert protocol.validation_result.accepted
    assert abs(protocol.validation_result.final_error_c) < 1.0


def test_ten_minutes_only_proposes_for_a_slow_machine() -> None:
    protocol, command, _phases = _run_virtual_plant(
        gain_c_per_pct=0.30,
        tau_sec=150.0,
        delay_sec=5,
        target_margin_c=5.0,
    )

    assert command.phase == "refused"
    assert command.restore_config
    assert command.power_pct == 0.0
    assert command.reason == "validation_window_too_short_for_inertia"
    assert protocol.validation_result is not None
    assert not protocol.validation_result.accepted


def test_identification_rejects_an_invisible_response() -> None:
    points = [
        CalibrationPoint(float(second), 200.0, 30.0)
        for second in range(420)
    ]
    with pytest.raises(IdentificationError, match="response_too_small"):
        identify_local_fopdt(
            points,
            timing=CalibrationTiming(),
            baseline_power_pct=30.0,
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"sensor_valid": False}, "sensor_invalid"),
        ({"temperature_c": float("nan")}, "sensor_invalid"),
        ({"communication_ok": False}, "communication_lost"),
        ({"roast_started": True}, "roast_started"),
        ({"manual_override": True}, "manual_override"),
        ({"temperature_c": 202.1}, "temperature_limit"),
        ({"ror_c_per_min": 30.1}, "ror_limit"),
        ({"now_sec": 4.0}, "sensor_timeout"),
    ],
)
def test_every_live_fault_forces_zero_and_requests_rollback(
    changes: dict[str, object], reason: str
) -> None:
    protocol = CalibrationProtocol(
        CalibrationLimits(target_c=200.0, baseline_power_pct=30.0),
        current_kp=10.0,
        current_ki=0.1,
        current_kd=0.0,
    )
    first = CalibrationSample(0.0, 200.0, 0.0)
    assert not protocol.start(first).done

    fault = replace(
        CalibrationSample(1.0, 200.0, 0.0),
        **changes,
    )
    command = protocol.update(fault)

    assert command.phase == "safe_stop"
    assert command.power_pct == 0.0
    assert command.restore_config
    assert command.done
    assert command.reason == reason


def test_test_refuses_when_power_or_temperature_headroom_is_too_small() -> None:
    no_power_room = CalibrationProtocol(
        CalibrationLimits(
            target_c=200.0,
            baseline_power_pct=76.0,
            power_max_pct=80.0,
        ),
        current_kp=10.0,
        current_ki=0.1,
        current_kd=0.0,
    )
    no_temperature_room = CalibrationProtocol(
        CalibrationLimits(
            target_c=200.0,
            baseline_power_pct=30.0,
            target_margin_c=1.0,
        ),
        current_kp=10.0,
        current_ki=0.1,
        current_kd=0.0,
    )
    sample = CalibrationSample(0.0, 200.0, 0.0)

    assert no_power_room.start(sample).reason == "insufficient_power_room"
    assert no_temperature_room.start(sample).reason == (
        "insufficient_temperature_room"
    )


def _live_coordinator(
    *, zero_qualified: bool = True
) -> tuple[
    LiveCalibrationCoordinator,
    list[tuple[int, int, bool]],
    list[object],
    list[bool],
]:
    power_requests: list[tuple[int, int, bool]] = []
    candidates: list[object] = []
    restores: list[bool] = []
    protocol = CalibrationProtocol(
        CalibrationLimits(target_c=200.0, baseline_power_pct=30.0),
        current_kp=10.0,
        current_ki=0.15,
        current_kd=0.0,
    )
    coordinator = LiveCalibrationCoordinator(
        protocol,
        heater_slider=3,
        zero_output_qualified=zero_qualified,
        request_power=lambda slider, power, fire: power_requests.append(
            (slider, power, fire)
        ),
        apply_candidate=candidates.append,
        restore_config=lambda: restores.append(True),
    )
    return coordinator, power_requests, candidates, restores


def test_live_coordinator_requires_zero_qualification_without_side_effect() -> None:
    coordinator, requests, _candidates, restores = _live_coordinator(
        zero_qualified=False
    )
    command = coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )

    assert command.phase == "refused"
    assert command.reason == "zero_output_not_qualified"
    assert requests == []
    assert restores == []


def test_live_coordinator_ack_mismatch_forces_zero_and_one_rollback() -> None:
    coordinator, requests, _candidates, restores = _live_coordinator()
    coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )

    assert requests == [(3, 30, True)]
    assert not coordinator.acknowledge(
        heater_slider=3,
        applied_power_pct=29,
        action_fired=True,
    )
    assert coordinator.phase == "safe_stop"
    assert coordinator.reason == "actuator_value_mismatch"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]
    coordinator.update(CalibrationSample(1.0, 200.0, 0.0))
    assert restores == [True]


def test_live_coordinator_ack_timeout_forces_zero_and_rollback() -> None:
    coordinator, requests, _candidates, restores = _live_coordinator()
    coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )

    command = coordinator.poll(1.51)

    assert command is not None
    assert command.reason == "actuator_ack_timeout"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]


def test_fail_safe_audit_is_chained_and_detects_any_later_change() -> None:
    coordinator, _requests, _candidates, _restores = _live_coordinator()
    coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )
    coordinator.poll(1.51)

    events = coordinator.audit_events
    assert verify_calibration_audit(events)
    assert "emergency_stop" in {event.kind for event in events}
    assert "config_restored" in {event.kind for event in events}

    changed = list(events)
    changed[0] = replace(changed[0], temperature_c=199.0)
    assert not verify_calibration_audit(tuple(changed))


def test_live_coordinator_runtime_interlock_forces_zero_and_rollback() -> None:
    coordinator, requests, _candidates, restores = _live_coordinator()
    coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )
    coordinator.acknowledge(
        heater_slider=3,
        applied_power_pct=30,
        action_fired=True,
    )

    command = coordinator.update(
        CalibrationSample(1.0, 200.0, 0.0),
        runtime_stop_reason="monitoring_stopped",
    )

    assert command.phase == "safe_stop"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]


@pytest.mark.parametrize(
    "phase",
    [
        "baseline",
        "step_up",
        "recover_up",
        "step_down",
        "recover_down",
        "identifying",
        "validating",
        "deciding",
    ],
)
def test_runtime_interlock_cuts_and_rolls_back_from_every_phase(
    phase: CalibrationPhase,
) -> None:
    coordinator, requests, _candidates, restores = _live_coordinator()
    coordinator.start(
        CalibrationSample(0.0, 200.0, 0.0),
        readiness=evaluate_calibration_readiness(_ready_facts()),
    )
    coordinator.acknowledge(
        heater_slider=3,
        applied_power_pct=30,
        action_fired=True,
    )
    coordinator.protocol.phase = phase
    coordinator.last_command = CalibrationCommand(
        phase=phase,
        power_pct=30.0,
        target_c=200.0,
    )

    command = coordinator.update(
        CalibrationSample(1.0, 200.0, 0.0),
        runtime_stop_reason="injected_fault",
    )

    assert command.phase == "safe_stop"
    assert command.reason == "injected_fault"
    assert requests[-1] == (3, 0, True)
    assert restores == [True]


def test_live_coordinator_completes_virtual_plant_and_keeps_candidate() -> None:
    coordinator, requests, candidates, restores = _live_coordinator()
    delayed_powers = deque([30.0] * 6, maxlen=6)
    temperature = 200.0
    previous_temperature = temperature

    for second in range(601):
        ror = (temperature - previous_temperature) * 60.0 if second else 0.0
        sample = CalibrationSample(float(second), temperature, ror)
        if second == 0:
            command = coordinator.start(
                sample,
                readiness=evaluate_calibration_readiness(_ready_facts()),
            )
        else:
            command = coordinator.update(sample)
        if coordinator.pending is not None:
            pending = coordinator.pending
            assert coordinator.acknowledge(
                heater_slider=pending.heater_slider,
                applied_power_pct=pending.power_pct,
                action_fired=True,
            )
        if command.done:
            break
        current_power = float(coordinator.last_requested_power or 0)
        delayed_powers.append(current_power)
        previous_temperature = temperature
        offset = temperature - 200.0
        offset += (0.15 * (delayed_powers[0] - 30.0) - offset) / 55.0
        temperature = 200.0 + offset

    assert coordinator.phase == "complete"
    assert len(candidates) == 1
    assert restores == []
    assert requests[0] == (3, 30, True)
    assert requests[-1] == (3, 30, True)
    assert verify_calibration_audit(coordinator.audit_events)
    kinds = [event.kind for event in coordinator.audit_events]
    assert kinds.count("candidate_applied") == 1
    assert kinds.count("complete") == 1
    assert kinds.count("sample") == 601

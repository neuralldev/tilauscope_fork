"""Fail-safe sensor policy for the Tilau preheat controller."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

from artisanlib.util import fromFtoCstrict
from tilauscope.tilaupid import TilauPreheatPID
from tilauscope.tilaupid_adaptative import StabilisationDetector
from tilauscope.tilaupid_safety import PreheatSensorGuard, SensorSafetyLimits


@pytest.mark.parametrize("value, reason", [
    (-1.0, "sensor_missing"),
    (float("nan"), "sensor_non_finite"),
    (float("inf"), "sensor_non_finite"),
    (-20.0, "sensor_out_of_range"),
    (400.0, "sensor_out_of_range"),
])
def test_invalid_samples_are_rejected(value: float, reason: str) -> None:
    decision = PreheatSensorGuard().evaluate(value, 1.0)
    assert not decision.valid
    assert not decision.control_allowed
    assert decision.reason == reason


def test_native_fahrenheit_is_safe_after_canonical_conversion() -> None:
    decision = PreheatSensorGuard().evaluate(fromFtoCstrict(392.0), 1.0)
    assert decision.valid
    assert decision.control_allowed


def test_implausible_temperature_jump_is_rejected() -> None:
    guard = PreheatSensorGuard()
    assert guard.evaluate(100.0, 0.0).control_allowed
    decision = guard.evaluate(110.0, 1.0)
    assert decision.reason == "sensor_implausible_ror"


def test_simulator_skips_wall_clock_checks_but_rejects_bad_values() -> None:
    guard = PreheatSensorGuard(SensorSafetyLimits(frozen_after_sec=5.0))
    assert guard.evaluate(100.0, 0.0, temporal_checks=False).control_allowed

    jumped = guard.evaluate(130.0, 1.0, temporal_checks=False)
    unchanged = guard.evaluate(
        130.0,
        20.0,
        burner_pct=80.0,
        target_c=200.0,
        temporal_checks=False,
    )
    missing = guard.evaluate(-1.0, 21.0, temporal_checks=False)

    assert jumped.control_allowed
    assert unchanged.control_allowed
    assert missing.reason == "sensor_missing"


def test_one_bad_sample_requires_three_good_samples_before_recovery() -> None:
    guard = PreheatSensorGuard()
    assert guard.evaluate(100.0, 0.0).control_allowed
    assert not guard.evaluate(-1.0, 1.0).control_allowed
    assert not guard.evaluate(100.5, 2.0).control_allowed
    assert not guard.evaluate(101.0, 3.0).control_allowed
    recovered = guard.evaluate(101.5, 4.0)
    assert recovered.valid
    assert recovered.control_allowed
    assert not guard.degraded


def test_three_consecutive_bad_samples_latch_until_reset() -> None:
    guard = PreheatSensorGuard()
    guard.reset(10.0)
    guard.evaluate(-1.0, 11.0)
    guard.evaluate(-1.0, 12.0)
    fault = guard.evaluate(-1.0, 13.0)
    assert fault.latched
    assert not guard.evaluate(100.0, 14.0).control_allowed

    guard.reset(20.0)
    assert guard.evaluate(100.0, 21.0).control_allowed


def test_watchdog_detects_absent_initial_and_late_samples() -> None:
    guard = PreheatSensorGuard(SensorSafetyLimits(stale_after_sec=3.0))
    guard.reset(10.0)
    assert guard.stale_reason(13.0) is None
    assert guard.stale_reason(13.01) == "sensor_timeout"

    guard.evaluate(100.0, 20.0)
    assert guard.stale_reason(23.01) == "sensor_timeout"


def test_unchanged_sensor_under_high_heat_is_detected_as_frozen() -> None:
    guard = PreheatSensorGuard(SensorSafetyLimits(
        frozen_after_sec=5.0,
        max_abs_ror_c_per_min=1000.0,
    ))
    assert guard.evaluate(100.0, 0.0, burner_pct=80.0, target_c=200.0).control_allowed
    frozen = guard.evaluate(100.0, 5.01, burner_pct=80.0, target_c=200.0)
    assert frozen.reason == "sensor_frozen"


def test_force_safe_output_bypasses_smoothing_and_commands_zero() -> None:
    calls: list[tuple[int, int]] = []
    pid = SimpleNamespace(
        cfg=SimpleNamespace(heater_slider=3),
        prev_power=80,
        _update_artisan_slider=lambda slider, power: calls.append((slider, power)),
    )
    TilauPreheatPID._force_safe_output(pid, "test_fault")
    assert calls == [(3, 0)]
    assert pid.prev_power == 0


class _Signal:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def emit(self, *args) -> None:
        self.events.append(args)


class _Timer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _PIDControl:
    def __init__(self) -> None:
        self.sv = 200.0

    def setSV(self, value: float) -> None:
        self.sv = value


def _fake_aw() -> SimpleNamespace:
    slider_moves: list[tuple[int, int]] = []
    qmc = SimpleNamespace(
        mode="C",
        deltaBTspan=15.0,
        ambientTempSource=0,
        ambientHumiditySource=0,
        ambientPressureSource=0,
        eventRecordActionSignal=_Signal(),
        eventsExternal2InternalValue=lambda value: value,
    )
    return SimpleNamespace(
        qmc=qmc,
        pidcontrol=_PIDControl(),
        simulator=object(),
        extraeventsactionslastvalue=[0, 0, 0, 0, 0],
        moveslider=lambda slider, power: slider_moves.append((slider, power)),
        sendmessageSignal=_Signal(),
        slider_moves=slider_moves,
    )


def _minimal_stop_pid(*, learning_allowed: bool = True) -> SimpleNamespace:
    learned: list[bool] = []
    safe: list[str] = []

    def force_safe(reason: str) -> None:
        safe.append(reason)

    return SimpleNamespace(
        active=True,
        _learning_allowed=learning_allowed,
        _safety_watchdog=_Timer(),
        aw=SimpleNamespace(qmc=SimpleNamespace(eventRecordActionSignal=_Signal())),
        _on_preheat_complete=lambda: learned.append(True),
        _force_safe_output=force_safe,
        _pending_start_sv_native=200.0,
        learned=learned,
        safe=safe,
    )


def test_charge_hands_off_and_learns_only_from_a_clean_session() -> None:
    pid = _minimal_stop_pid()
    TilauPreheatPID.stop(pid, reason="charge")
    assert pid.learned == [True]
    assert pid.safe == []
    assert not pid.active

    degraded = _minimal_stop_pid(learning_allowed=False)
    TilauPreheatPID.stop(degraded, reason="charge")
    assert degraded.learned == []


def test_operator_abort_cuts_heat_and_does_not_learn() -> None:
    pid = _minimal_stop_pid()
    TilauPreheatPID.stop(pid, reason="operator_abort")
    assert pid.safe == ["operator_abort"]
    assert pid.learned == []


def test_simulator_still_cuts_a_missing_sample_and_latches_repetition(qapp) -> None:
    assert qapp is not None
    aw = _fake_aw()
    pid = TilauPreheatPID(aw)
    pid.start()

    pid.cycle(100.0)
    assert aw.slider_moves[-1] == (3, 80)

    pid.cycle(-1.0)
    assert aw.slider_moves[-1] == (3, 0)
    assert pid.active

    pid.cycle(-1.0)
    pid.cycle(-1.0)
    assert not pid.active
    assert pid._fault_reason == "sensor_missing"
    assert aw.sendmessageSignal.events

    # An explicit START after a latched stop remains the recovery operation.
    pid.start()
    assert pid.active
    assert pid._fault_reason is None
    pid.stop()


def test_start_reuses_loaded_history_and_duplicate_is_idempotent(qapp) -> None:
    assert qapp is not None
    aw = _fake_aw()
    pid = TilauPreheatPID(aw)
    history_loads: list[bool] = []
    pid._load_history = lambda: history_loads.append(True)

    pid.start()
    first_start_time = pid.start_time
    first_target = pid.cfg.target_sv
    pid.start(180.0)

    assert history_loads == []
    assert pid.start_time == first_start_time
    assert pid.cfg.target_sv == first_target
    assert pid.active
    pid.stop()


def test_accelerated_simulator_jump_does_not_latch_pid(qapp) -> None:
    assert qapp is not None
    aw = _fake_aw()
    pid = TilauPreheatPID(aw)
    pid.start()

    assert not pid._safety_watchdog.isActive()
    pid.cycle(30.0)
    pid.cycle(60.0)

    assert pid.active
    assert pid._fault_reason is None
    pid.stop()


def test_real_input_starts_temporal_watchdog(qapp) -> None:
    assert qapp is not None
    aw = _fake_aw()
    aw.simulator = None
    pid = TilauPreheatPID(aw)
    pid.start()

    assert pid._safety_watchdog.isActive()
    pid.stop()
    assert not pid._safety_watchdog.isActive()


def test_latched_fault_cuts_heat_stops_watchdog_and_notifies_operator() -> None:
    safety_events = _Signal()
    messages = _Signal()
    timer = _Timer()
    safe: list[str] = []
    latched: list[str] = []

    def latch(reason: str) -> None:
        latched.append(reason)

    def force_safe(reason: str) -> None:
        safe.append(reason)

    pid = SimpleNamespace(
        active=True,
        _fault_reason=None,
        _learning_allowed=True,
        _sensor_guard=SimpleNamespace(latch=latch),
        _force_safe_output=force_safe,
        _safety_watchdog=timer,
        _pending_start_sv_native=200.0,
        aw=SimpleNamespace(
            qmc=SimpleNamespace(eventRecordActionSignal=safety_events),
            sendmessageSignal=messages,
        ),
    )

    TilauPreheatPID._trip_fault(pid, "sensor_timeout")

    assert safe == ["sensor_timeout"]
    assert latched == ["sensor_timeout"]
    assert timer.stopped
    assert not pid.active
    assert not pid._learning_allowed
    assert safety_events.events
    assert messages.events


def test_stabilisation_detector_reset_forgets_previous_preheat() -> None:
    detector = StabilisationDetector()
    detector._temps = deque([200.0] * 5, maxlen=30)
    detector._times = deque([1.0, 2.0, 3.0, 4.0, 5.0], maxlen=30)
    detector.seconds_stable = 18.0
    detector._stable_since = 1.0

    detector.reset()

    assert not detector._temps
    assert not detector._times
    assert detector.seconds_stable == 0.0
    assert detector._stable_since is None

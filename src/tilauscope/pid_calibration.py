# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure simulation core for the ten-minute PID calibration protocol.

This module deliberately owns no Qt object and sends no actuator command.  It
turns timestamped observations into requested power values so every transition,
identification decision and safety stop can be exercised with a virtual plant
before the protocol is connected to a real roaster.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


CalibrationPhase = Literal[
    "idle",
    "baseline",
    "step_up",
    "recover_up",
    "step_down",
    "recover_down",
    "identifying",
    "validating",
    "deciding",
    "complete",
    "refused",
    "safe_stop",
]

ReadinessCode = Literal[
    "monitoring_active",
    "machine_identity_known",
    "no_roast_running",
    "software_pid_selected",
    "gain_scheduling_disabled",
    "artisan_pid_stopped",
    "sensor_valid",
    "sensor_stable",
    "holding_point_confirmed",
    "heater_slider_configured",
    "heater_action_configured",
    "airflow_path_configured",
    "extractor_not_cooling",
    "hot_time_budget",
    "normal_actuator_direction",
    "power_headroom",
    "no_simulator",
    "preheat_pid_stopped",
    "rollback_snapshot_available",
    "machine_empty_confirmed",
    "airflow_safe_confirmed",
    "supervision_confirmed",
]

ZeroQualificationPhase = Literal[
    "idle",
    "command_requested",
    "software_zero_confirmed",
    "qualified",
    "failed",
]

LiveCoordinatorPhase = Literal[
    "idle",
    "running",
    "complete",
    "refused",
    "safe_stop",
]

AuditEventKind = Literal[
    "sample",
    "start_refused",
    "started",
    "power_requested",
    "power_acknowledged",
    "candidate_applied",
    "emergency_stop",
    "cooling_requested",
    "config_restored",
    "config_restore_failed",
    "complete",
]


@dataclass(frozen=True, slots=True)
class CalibrationTiming:
    """Normative phase boundaries, in seconds after the active test starts."""

    baseline_end: float = 60.0
    step_up_end: float = 150.0
    recover_up_end: float = 240.0
    step_down_end: float = 330.0
    recover_down_end: float = 420.0
    calculation_end: float = 450.0
    validation_bump_end: float = 510.0
    validation_end: float = 570.0
    total_end: float = 600.0


@dataclass(frozen=True, slots=True)
class CalibrationLimits:
    """Safety and identifiability limits in canonical °C and percent power."""

    target_c: float
    baseline_power_pct: float
    power_min_pct: float = 0.0
    power_max_pct: float = 80.0
    absolute_temp_max_c: float = 250.0
    target_margin_c: float = 2.0
    open_loop_margin_c: float = 10.0
    max_abs_ror_c_per_min: float = 30.0
    stale_after_sec: float = 3.5
    max_step_pct: float = 10.0
    min_step_pct: float = 2.0
    target_step_rise_c: float = 4.0
    # Machine knowledge, when it exists: degC of equilibrium temperature per
    # heater point, and the fraction of that equilibrium a 90-second phase
    # actually covers.  Both absent on a machine whose inertia was never
    # measured, which is exactly what the first run produces.
    thermal_gain_c_per_pct: float | None = None
    step_response_fraction: float | None = None

    @property
    def step_pct(self) -> float:
        """Protocol section 4.1: the step is sized to raise the probe by about
        `target_step_rise_c`, never a fixed fraction of the machine's range."""
        desired = self.min_step_pct
        gain = self.thermal_gain_c_per_pct
        fraction = self.step_response_fraction
        if (
            gain is not None and gain > 0.0
            and fraction is not None and fraction > 0.0
        ):
            desired = self.target_step_rise_c / (gain * fraction)
        desired = max(self.min_step_pct, min(self.max_step_pct, desired))
        room = min(
            self.power_max_pct - self.baseline_power_pct,
            self.baseline_power_pct - self.power_min_pct,
        )
        return min(desired, max(0.0, room - 3.0))

    @property
    def validation_step_c(self) -> float:
        """Closed-loop bump, sized for the machine and independent of the
        open-loop excursion allowance."""
        return min(3.0, max(1.5, 0.015 * self.target_c))

    @property
    def validation_ceiling_c(self) -> float:
        """Ceiling for the closed-loop phases.

        Section 7 allows the validation bump up to 2 degC of overshoot, so the
        stop of section 8 is counted from the raised setpoint, not from the
        holding target.
        """
        return min(
            self.absolute_temp_max_c,
            self.target_c + self.validation_step_c + self.target_margin_c,
        )

    @property
    def open_loop_ceiling_c(self) -> float:
        """Protocol section 8: the open-loop steps move the holding point on
        purpose, so they get their own margin, capped by the absolute limit."""
        return min(
            self.absolute_temp_max_c,
            self.target_c + self.open_loop_margin_c,
        )

    @property
    def validation_authority_pct(self) -> float:
        """Power the validation PI may command, around the holding power.

        The candidate was identified on a +/- `step_pct` envelope; twice that
        gives the loop authority to track the bump without ever asking for the
        raw duty limit of the machine.
        """
        return 2.0 * self.step_pct


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    """One observation supplied by a simulator or, later, the live observer."""

    now_sec: float
    temperature_c: float
    ror_c_per_min: float
    sensor_valid: bool = True
    communication_ok: bool = True
    roast_started: bool = False
    manual_override: bool = False


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    """Recorded sample with the power that was requested during its interval."""

    elapsed_sec: float
    temperature_c: float
    power_pct: float


@dataclass(frozen=True, slots=True)
class IdentifiedPlant:
    """Local first-order-plus-dead-time model around the holding point."""

    gain_c_per_pct: float
    tau_sec: float
    delay_sec: float
    rmse_c: float
    noise_c: float
    response_span_c: float
    n_samples: int
    gain_up_c_per_pct: float
    gain_down_c_per_pct: float
    # Protocol section 5.1: the baseline moves during an open-loop run, by an
    # amount comparable to the step response.  Fitted, never ignored.
    drift_c_per_min: float = 0.0


@dataclass(frozen=True, slots=True)
class PIDCandidate:
    """Artisan parallel-form software PID gains."""

    kp: float
    ki: float
    kd: float
    lambda_sec: float
    integral_time_sec: float
    # True when the retained pair is the safety clamp, not the SIMC design: the
    # run is a step towards the right gains, not the final answer.
    clamped: bool = False


@dataclass(frozen=True, slots=True)
class CalibrationCommand:
    """Side-effect-free instruction returned by :class:`CalibrationProtocol`."""

    phase: CalibrationPhase
    power_pct: float
    target_c: float
    apply_candidate: bool = False
    restore_config: bool = False
    done: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationPoint:
    """One closed-loop observation used to accept or reject the candidate."""

    elapsed_sec: float
    temperature_c: float
    target_c: float
    power_pct: float


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Human-translatable facts behind the automatic decision."""

    accepted: bool
    reason: str | None
    bump_response_c: float
    final_error_c: float
    error_crossings: int
    longest_saturation_sec: float


PreparationPhase = Literal[
    "idle",
    "approaching",
    "confirming",
    "adjusting",
    "ready",
    "failed",
]


@dataclass(frozen=True, slots=True)
class PreparationSample:
    """One observation of the machine while it is being brought to its point."""

    now_sec: float
    temperature_c: float
    heater_pct: float
    preheat_active: bool
    preheat_settled: bool
    sensor_valid: bool = True


@dataclass(frozen=True, slots=True)
class PreparationCommand:
    """Side-effect-free instruction for the Qt layer driving the preparation."""

    phase: PreparationPhase
    start_preheat: bool = False
    hand_over: bool = False
    set_heater_pct: int | None = None
    seconds_observed: float = 0.0
    drift_c_per_min: float = 0.0
    span_c: float = 0.0
    holding_point_c: float | None = None
    holding_power_pct: float | None = None
    reason: str | None = None


class PreparationSequence:
    """Protocol section 3.3: approach, hand-over, open-loop confirmation.

    Nobody has to reach a temperature.  TilauPID parks the machine near its
    setpoint and hands over with the burner left where it holds; this sequence
    then proves, in open loop, that the burner really is the equilibrium power,
    and the mean it measures becomes the calibration temperature.
    """

    WINDOW_SEC: float = 30.0
    MAX_DRIFT_C_PER_MIN: float = 0.5
    MAX_SPAN_C: float = 0.25
    MAX_CORRECTIONS: int = 1

    def __init__(self, *, heater_resolution_pct: float = 1.0) -> None:
        self.phase: PreparationPhase = "idle"
        self.reason: str | None = None
        self.corrections_used = 0
        self.holding_point_c: float | None = None
        self.holding_power_pct: float | None = None
        self._resolution = max(1.0, float(heater_resolution_pct))
        self._window: deque[tuple[float, float]] = deque()
        self._handover_power: float | None = None

    def update(self, sample: PreparationSample) -> PreparationCommand:
        if self.phase in {"ready", "failed"}:
            return self._command()
        if not sample.sensor_valid or not math.isfinite(sample.temperature_c):
            return self._fail("sensor_invalid")

        if self.phase == "idle":
            # An already running preheat is adopted with its own setpoint.
            self.phase = "approaching"
            return self._command(start_preheat=not sample.preheat_active)

        if self.phase == "approaching":
            if not sample.preheat_active:
                return self._fail("preheat_stopped")
            if not sample.preheat_settled:
                return self._command()
            self._handover_power = sample.heater_pct
            self._window.clear()
            self.phase = "confirming"
            return self._command(hand_over=True)

        if self.phase == "adjusting":
            self._window.clear()
            self.phase = "confirming"
            return self._command()

        return self._confirm(sample)

    def _confirm(self, sample: PreparationSample) -> PreparationCommand:
        if sample.preheat_active:
            return self._fail("preheat_resumed")
        self._window.append((sample.now_sec, sample.temperature_c))
        while (
            len(self._window) > 1
            and sample.now_sec - self._window[0][0] > self.WINDOW_SEC
        ):
            self._window.popleft()
        observed = self._window[-1][0] - self._window[0][0]
        drift = self._drift_c_per_min()
        span = self._span_c()
        if observed < self.WINDOW_SEC or len(self._window) < 10:
            return self._command(
                seconds_observed=observed, drift_c_per_min=drift, span_c=span
            )
        if abs(drift) <= self.MAX_DRIFT_C_PER_MIN and span <= self.MAX_SPAN_C:
            self.phase = "ready"
            self.holding_point_c = statistics.mean(
                value for _time, value in self._window
            )
            self.holding_power_pct = sample.heater_pct
            return self._command(
                seconds_observed=observed, drift_c_per_min=drift, span_c=span
            )
        if self.corrections_used >= self.MAX_CORRECTIONS:
            return self._fail(
                "holding_point_not_reachable",
                seconds_observed=observed,
                drift_c_per_min=drift,
                span_c=span,
            )
        # The sign of the drift says which way the notch is wrong, and the
        # actuator is an integer: there is exactly one other candidate.
        self.corrections_used += 1
        step = -self._resolution if drift > 0.0 else self._resolution
        proposed = int(round(sample.heater_pct + step))
        self.phase = "adjusting"
        return self._command(
            set_heater_pct=proposed,
            seconds_observed=observed,
            drift_c_per_min=drift,
            span_c=span,
        )

    def _drift_c_per_min(self) -> float:
        if len(self._window) < 3:
            return 0.0
        times = [point[0] for point in self._window]
        values = [point[1] for point in self._window]
        mean_time = statistics.mean(times)
        mean_value = statistics.mean(values)
        denominator = sum((time - mean_time) ** 2 for time in times)
        if denominator < 1e-9:
            return 0.0
        slope = sum(
            (time - mean_time) * (value - mean_value)
            for time, value in zip(times, values, strict=True)
        ) / denominator
        return slope * 60.0

    def _span_c(self) -> float:
        if not self._window:
            return math.inf
        values = [point[1] for point in self._window]
        return max(values) - min(values)

    def _fail(self, reason: str, **fields: object) -> PreparationCommand:
        self.phase = "failed"
        self.reason = reason
        return self._command(**fields)

    def _command(self, **fields: object) -> PreparationCommand:
        return PreparationCommand(
            phase=self.phase,
            reason=self.reason,
            holding_point_c=self.holding_point_c,
            holding_power_pct=self.holding_power_pct,
            **fields,  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class CalibrationReadinessInputs:
    """Facts observed or explicitly confirmed before a live calibration."""

    monitoring_active: bool
    machine_identity_known: bool
    roast_started: bool
    software_pid_selected: bool
    gain_scheduling_active: bool
    artisan_pid_active: bool
    sensor_valid: bool
    stable_sample_count: int
    temperature_span_c: float
    max_abs_ror_c_per_min: float
    heater_slider: int | None
    heater_action_configured: bool
    holding_point_confirmed: bool
    airflow_path_configured: bool
    extractor_not_cooling: bool
    hot_minutes_used: float
    hot_minutes_budget: float
    hot_minutes_required: float
    actuator_direction_normal: bool
    current_power_pct: float | None
    power_min_pct: float
    power_max_pct: float
    required_power_room_pct: float
    simulator_active: bool
    preheat_pid_active: bool
    rollback_snapshot_available: bool
    machine_empty_confirmed: bool
    airflow_safe_confirmed: bool
    supervision_confirmed: bool


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    code: ReadinessCode
    passed: bool


@dataclass(frozen=True, slots=True)
class CalibrationReadinessReport:
    """Complete, deterministic checklist; unknown facts fail closed."""

    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blocking_codes(self) -> tuple[ReadinessCode, ...]:
        return tuple(check.code for check in self.checks if not check.passed)


@dataclass(frozen=True, slots=True)
class CalibrationRuntimeInterlocks:
    """Application facts that must remain true throughout all live phases."""

    monitoring_active: bool
    roast_started: bool
    software_pid_selected: bool
    machine_identity_unchanged: bool
    artisan_pid_active: bool
    simulator_active: bool
    preheat_pid_active: bool
    manual_override: bool
    communication_ok: bool


def runtime_interlock_reason(
    facts: CalibrationRuntimeInterlocks,
) -> str | None:
    """Return the first deterministic reason requiring an immediate stop."""
    if not facts.monitoring_active:
        return "monitoring_stopped"
    if facts.roast_started:
        return "roast_started"
    if not facts.software_pid_selected:
        return "external_pid_selected"
    if not facts.machine_identity_unchanged:
        return "machine_identity_changed"
    if facts.artisan_pid_active:
        return "artisan_pid_started"
    if facts.simulator_active:
        return "simulator_started"
    if facts.preheat_pid_active:
        return "preheat_pid_started"
    if facts.manual_override:
        return "manual_override"
    if not facts.communication_ok:
        return "communication_lost"
    return None


def evaluate_calibration_readiness(
    facts: CalibrationReadinessInputs,
) -> CalibrationReadinessReport:
    """Evaluate every live-test prerequisite without touching Qt or hardware."""
    stable = (
        facts.sensor_valid
        and facts.stable_sample_count >= 30
        and facts.temperature_span_c <= 0.20
        and facts.max_abs_ror_c_per_min <= 0.4
    )
    power_room = (
        facts.current_power_pct is not None
        and facts.current_power_pct - facts.power_min_pct
        >= facts.required_power_room_pct
        and facts.power_max_pct - facts.current_power_pct
        >= facts.required_power_room_pct
    )
    checks = (
        ReadinessCheck("monitoring_active", facts.monitoring_active),
        ReadinessCheck("machine_identity_known", facts.machine_identity_known),
        ReadinessCheck("no_roast_running", not facts.roast_started),
        ReadinessCheck("software_pid_selected", facts.software_pid_selected),
        ReadinessCheck(
            "gain_scheduling_disabled", not facts.gain_scheduling_active
        ),
        ReadinessCheck("artisan_pid_stopped", not facts.artisan_pid_active),
        ReadinessCheck("sensor_valid", facts.sensor_valid),
        ReadinessCheck("sensor_stable", stable),
        # Section 3.3: the machine was handed over and proved, in open loop,
        # that its heat setting really is the equilibrium power.
        ReadinessCheck(
            "holding_point_confirmed", facts.holding_point_confirmed
        ),
        ReadinessCheck(
            "heater_slider_configured", facts.heater_slider is not None
        ),
        ReadinessCheck(
            "heater_action_configured", facts.heater_action_configured
        ),
        # Section 3.1: without a commandable airflow the test cannot cool the
        # machine when it ends, so it must not start.
        ReadinessCheck(
            "airflow_path_configured", facts.airflow_path_configured
        ),
        # Section 3.2: an extractor above its cooling threshold chills the drum
        # for the whole run, moving the operating point away from a roast.
        ReadinessCheck("extractor_not_cooling", facts.extractor_not_cooling),
        # Section 3.4: the element only takes so many continuous minutes hot.
        ReadinessCheck(
            "hot_time_budget",
            facts.hot_minutes_used + facts.hot_minutes_required
            <= facts.hot_minutes_budget,
        ),
        ReadinessCheck(
            "normal_actuator_direction", facts.actuator_direction_normal
        ),
        ReadinessCheck("power_headroom", power_room),
        ReadinessCheck("no_simulator", not facts.simulator_active),
        ReadinessCheck("preheat_pid_stopped", not facts.preheat_pid_active),
        ReadinessCheck(
            "rollback_snapshot_available", facts.rollback_snapshot_available
        ),
        ReadinessCheck(
            "machine_empty_confirmed", facts.machine_empty_confirmed
        ),
        ReadinessCheck(
            "airflow_safe_confirmed", facts.airflow_safe_confirmed
        ),
        ReadinessCheck(
            "supervision_confirmed", facts.supervision_confirmed
        ),
    )
    return CalibrationReadinessReport(checks)


class ZeroOutputQualification:
    """Session-only proof that the centralized heater transaction applies 0%."""

    def __init__(self, *, timeout_sec: float = 15.0) -> None:
        self.timeout_sec = timeout_sec
        self.phase: ZeroQualificationPhase = "idle"
        self.heater_slider: int | None = None
        self.reason: str | None = None
        self._requested_at: float | None = None

    def start(
        self,
        readiness: CalibrationReadinessReport,
        *,
        heater_slider: int | None,
        now_sec: float,
    ) -> bool:
        if self.phase != "idle":
            raise RuntimeError("zero-output qualification already started")
        if not readiness.ready:
            self.phase = "failed"
            self.reason = "readiness_changed"
            return False
        if heater_slider is None:
            self.phase = "failed"
            self.reason = "heater_slider_unavailable"
            return False
        self.phase = "command_requested"
        self.heater_slider = heater_slider
        self._requested_at = now_sec
        return True

    def acknowledge(
        self,
        *,
        heater_slider: int,
        applied_power_pct: int,
        action_fired: bool,
        now_sec: float,
    ) -> bool:
        if self.phase != "command_requested":
            return False
        if self._timed_out(now_sec):
            return False
        if heater_slider != self.heater_slider:
            return False
        if not action_fired:
            self.phase = "failed"
            self.reason = "heater_action_not_fired"
            return False
        if applied_power_pct != 0:
            self.phase = "failed"
            self.reason = "zero_not_applied"
            return False
        self.phase = "software_zero_confirmed"
        return True

    def confirm_physical_shutdown(
        self, *, heater_is_off: bool, now_sec: float
    ) -> bool:
        if self.phase != "software_zero_confirmed":
            return False
        if self._timed_out(now_sec):
            return False
        if not heater_is_off:
            self.phase = "failed"
            self.reason = "heater_still_on"
            return False
        self.phase = "qualified"
        self.reason = None
        return True

    def poll(self, now_sec: float) -> ZeroQualificationPhase:
        self._timed_out(now_sec)
        return self.phase

    def invalidate(self, reason: str) -> None:
        """Fail a pending proof when the machine/control identity changes."""
        self.phase = "failed"
        self.reason = reason

    def _timed_out(self, now_sec: float) -> bool:
        if (
            self._requested_at is not None
            and now_sec - self._requested_at > self.timeout_sec
            and self.phase in {"command_requested", "software_zero_confirmed"}
        ):
            self.phase = "failed"
            self.reason = "qualification_timeout"
            return True
        return False


class IdentificationError(ValueError):
    """Raised when the active trace cannot support a safe tuning decision."""


def _power_at(
    points: list[CalibrationPoint], times: list[float], elapsed_sec: float
) -> float:
    index = bisect.bisect_right(times, elapsed_sec) - 1
    return points[max(0, index)].power_pct


def _model_unit_response(
    points: list[CalibrationPoint],
    baseline_power_pct: float,
    tau_sec: float,
    delay_sec: float,
) -> list[float]:
    response = [0.0]
    state = 0.0
    times = [point.elapsed_sec for point in points]
    for previous, current in zip(points, points[1:], strict=False):
        dt = current.elapsed_sec - previous.elapsed_sec
        if not 0.0 < dt <= 5.0:
            response.append(state)
            continue
        delayed_power = _power_at(
            points, times, previous.elapsed_sec - delay_sec
        )
        delta_power = delayed_power - baseline_power_pct
        state += dt * (delta_power - state) / tau_sec
        response.append(state)
    return response


def _fit_gain_and_drift(
    unit: list[float], observed: list[float], elapsed: list[float]
) -> tuple[float, float] | None:
    """Least squares of ``observed = gain * unit + drift * elapsed``.

    Section 5.1: at one point of heater resolution the hold drifts by degrees
    over the measurement, which a gain-only fit would charge to the gain.
    """
    s_uu = sum(u * u for u in unit)
    s_ut = sum(u * t for u, t in zip(unit, elapsed, strict=True))
    s_tt = sum(t * t for t in elapsed)
    s_uy = sum(u * y for u, y in zip(unit, observed, strict=True))
    s_ty = sum(t * y for t, y in zip(elapsed, observed, strict=True))
    determinant = s_uu * s_tt - s_ut * s_ut
    if abs(determinant) < 1e-9:
        return None
    gain = (s_uy * s_tt - s_ty * s_ut) / determinant
    drift = (s_uu * s_ty - s_ut * s_uy) / determinant
    return gain, drift


def identify_local_fopdt(
    points: list[CalibrationPoint],
    *,
    timing: CalibrationTiming,
    baseline_power_pct: float,
    max_drift_c: float = 8.0,
) -> IdentifiedPlant:
    """Fit a bounded local FOPDT model to the open-loop part of one test."""
    qualified = [
        point for point in points
        if 0.0 <= point.elapsed_sec <= timing.recover_down_end
        and math.isfinite(point.temperature_c)
        and math.isfinite(point.power_pct)
    ]
    if len(qualified) < 300:
        raise IdentificationError("not_enough_samples")

    baseline_values = [
        point.temperature_c
        for point in qualified
        if point.elapsed_sec <= timing.baseline_end
    ]
    if len(baseline_values) < 30:
        raise IdentificationError("baseline_too_short")
    baseline_temp = statistics.median(baseline_values)
    noise = statistics.pstdev(baseline_values)
    observed = [point.temperature_c - baseline_temp for point in qualified]
    response_span = max(observed) - min(observed)
    if response_span < 1.5:
        raise IdentificationError("response_too_small")
    if response_span / max(0.02, noise) < 5.0:
        raise IdentificationError("signal_to_noise_too_low")

    fit_start = next(
        (index for index, point in enumerate(qualified)
         if point.elapsed_sec >= timing.baseline_end),
        len(qualified),
    )
    best_rmse = math.inf
    best_gain = 0.0
    best_tau = 0.0
    best_delay = 0.0
    best_drift = 0.0
    useful_observed = observed[fit_start:]
    fit_origin_sec = (
        qualified[fit_start].elapsed_sec if fit_start < len(qualified)
        else timing.baseline_end
    )
    useful_elapsed = [
        point.elapsed_sec - fit_origin_sec for point in qualified[fit_start:]
    ]
    tau_candidates = tuple(float(value) for value in range(5, 601, 5))
    for delay in range(21):
        for tau in tau_candidates:
            unit = _model_unit_response(
                qualified, baseline_power_pct, tau, float(delay)
            )
            useful_unit = unit[fit_start:]
            solution = _fit_gain_and_drift(
                useful_unit, useful_observed, useful_elapsed
            )
            if solution is None:
                continue
            gain, drift = solution
            if gain <= 0.0:
                continue
            squared_error = sum(
                (actual - gain * model - drift * moment) ** 2
                for model, actual, moment in zip(
                    useful_unit, useful_observed, useful_elapsed, strict=True
                )
            )
            rmse = math.sqrt(squared_error / len(useful_observed))
            if rmse < best_rmse:
                best_rmse = rmse
                best_gain = gain
                best_tau = tau
                best_delay = float(delay)
                best_drift = drift

    if not math.isfinite(best_rmse):
        raise IdentificationError("no_physical_model")
    span_sec = useful_elapsed[-1] if useful_elapsed else 0.0
    if abs(best_drift * span_sec) > max_drift_c:
        raise IdentificationError("baseline_drifted_too_far")
    rmse = best_rmse
    gain = best_gain
    tau = best_tau
    identified_delay = best_delay
    if rmse > 0.40:
        raise IdentificationError("model_error_too_high")
    best_unit = _model_unit_response(
        qualified, baseline_power_pct, tau, identified_delay
    )
    # The up/down comparison must see the same drift-free signal as the main
    # fit, otherwise a drifting baseline reads as a one-sided response.
    detrended = [
        value - best_drift * (point.elapsed_sec - fit_origin_sec)
        for point, value in zip(qualified, observed, strict=True)
    ]

    def interval_gain(start: float, end: float) -> float:
        pairs = [
            (model, actual)
            for point, model, actual in zip(
                qualified, best_unit, detrended, strict=True
            )
            if start <= point.elapsed_sec < end
        ]
        denominator = sum(model * model for model, _actual in pairs)
        if denominator < 1e-9:
            raise IdentificationError("one_sided_response_missing")
        return sum(model * actual for model, actual in pairs) / denominator

    gain_up = interval_gain(timing.baseline_end, timing.recover_up_end)
    gain_down = interval_gain(timing.recover_up_end, timing.recover_down_end)
    if gain_up <= 0.0 or gain_down <= 0.0:
        raise IdentificationError("inconsistent_response_direction")
    relative_gain_gap = abs(gain_up - gain_down) / max(
        1e-9, (gain_up + gain_down) / 2.0
    )
    if relative_gain_gap > 0.30:
        raise IdentificationError("response_too_nonlinear")
    return IdentifiedPlant(
        gain_c_per_pct=gain,
        tau_sec=tau,
        delay_sec=identified_delay,
        rmse_c=rmse,
        noise_c=noise,
        response_span_c=response_span,
        n_samples=len(qualified),
        gain_up_c_per_pct=gain_up,
        gain_down_c_per_pct=gain_down,
        drift_c_per_min=best_drift * 60.0,
    )


def _bounded_gain(proposed: float, current: float, *, maximum: float) -> float:
    proposed = max(0.0, min(maximum, proposed))
    if current <= 0.0:
        return proposed
    return max(current / 2.0, min(current * 2.0, proposed))


def tune_simc_candidate(
    plant: IdentifiedPlant,
    *,
    current_kp: float,
    current_ki: float,
) -> PIDCandidate:
    """Return the conservative SIMC PI candidate specified by the protocol."""
    lambda_sec = max(3.0 * plant.delay_sec, 0.5 * plant.tau_sec, 20.0)
    kp = plant.tau_sec / (
        plant.gain_c_per_pct * (lambda_sec + plant.delay_sec)
    )
    integral_time = min(plant.tau_sec, 4.0 * (lambda_sec + plant.delay_sec))
    ki = kp / integral_time
    bounded_kp = _bounded_gain(kp, current_kp, maximum=100.0)
    bounded_ki = _bounded_gain(ki, current_ki, maximum=5.0)
    return PIDCandidate(
        kp=bounded_kp,
        ki=bounded_ki,
        kd=0.0,
        lambda_sec=lambda_sec,
        # Report the integral time the retained pair implements, not the one the
        # unclamped design asked for.
        integral_time_sec=(
            bounded_kp / bounded_ki if bounded_ki > 0.0 else integral_time
        ),
        clamped=(
            not math.isclose(bounded_kp, kp, rel_tol=1e-9)
            or not math.isclose(bounded_ki, ki, rel_tol=1e-9)
        ),
    )


def _pid_power(
    *,
    candidate: PIDCandidate,
    error_c: float,
    previous_error_c: float,
    integral_pct: float,
    dt: float,
    power_min: float,
    power_max: float,
) -> tuple[float, float]:
    derivative = (error_c - previous_error_c) / dt if dt > 0.0 else 0.0
    proposed_integral = integral_pct + candidate.ki * error_c * dt
    raw = candidate.kp * error_c + proposed_integral + candidate.kd * derivative
    output = max(power_min, min(power_max, raw))
    saturated_high = raw > power_max and error_c > 0.0
    saturated_low = raw < power_min and error_c < 0.0
    if saturated_high or saturated_low:
        raw = candidate.kp * error_c + integral_pct + candidate.kd * derivative
        output = max(power_min, min(power_max, raw))
        return output, integral_pct
    return output, proposed_integral


class CalibrationProtocol:
    """Deterministic state machine for a simulated ten-minute calibration."""

    def __init__(
        self,
        limits: CalibrationLimits,
        *,
        current_kp: float,
        current_ki: float,
        current_kd: float,
        timing: CalibrationTiming | None = None,
    ) -> None:
        self.limits = limits
        self.timing = timing or CalibrationTiming()
        self.current_kp = current_kp
        self.current_ki = current_ki
        self.current_kd = current_kd
        self.phase: CalibrationPhase = "idle"
        self.points: list[CalibrationPoint] = []
        self.plant: IdentifiedPlant | None = None
        self.candidate: PIDCandidate | None = None
        self.validation_result: ValidationResult | None = None
        self.reason: str | None = None
        self._started_at: float | None = None
        self._last_sample_at: float | None = None
        self._last_power = limits.baseline_power_pct
        self._validation_integral = limits.baseline_power_pct
        self._validation_error = 0.0
        self._candidate_announced = False
        self._validation_points: list[ValidationPoint] = []

    def start(self, sample: CalibrationSample) -> CalibrationCommand:
        if self.phase != "idle":
            raise RuntimeError("calibration already started")
        if self.limits.step_pct < self.limits.min_step_pct:
            return self._stop("refused", "insufficient_power_room")
        if (
            self.limits.open_loop_ceiling_c
            <= self.limits.target_c + 1.5
            or self.limits.validation_ceiling_c
            <= self.limits.target_c + self.limits.validation_step_c
        ):
            return self._stop("refused", "insufficient_temperature_room")
        self._started_at = sample.now_sec
        self._last_sample_at = sample.now_sec
        self.phase = "baseline"
        return self.update(sample)

    def _stop(
        self, phase: Literal["refused", "safe_stop"], reason: str
    ) -> CalibrationCommand:
        self.phase = phase
        self.reason = reason
        self._last_power = 0.0
        return CalibrationCommand(
            phase=phase,
            power_pct=0.0,
            target_c=self.limits.target_c,
            restore_config=True,
            done=True,
            reason=reason,
        )

    def _safety_reason(self, sample: CalibrationSample) -> str | None:
        if not sample.sensor_valid or not math.isfinite(sample.temperature_c):
            return "sensor_invalid"
        if not sample.communication_ok:
            return "communication_lost"
        if sample.roast_started:
            return "roast_started"
        if sample.manual_override:
            return "manual_override"
        if (
            self._last_sample_at is not None
            and sample.now_sec < self._last_sample_at
        ):
            return "non_monotonic_time"
        if (
            self._last_sample_at is not None
            and sample.now_sec - self._last_sample_at
            > self.limits.stale_after_sec
        ):
            return "sensor_timeout"
        if sample.temperature_c > self._temperature_ceiling():
            return "temperature_limit"
        if abs(sample.ror_c_per_min) > self.limits.max_abs_ror_c_per_min:
            return "ror_limit"
        return None

    def _temperature_ceiling(self) -> float:
        """Ceiling for the phase in progress: the open-loop steps are allowed to
        move the holding point, the closed-loop phases are not."""
        if self.phase in {"validating", "deciding", "complete"}:
            return self.limits.validation_ceiling_c
        return self.limits.open_loop_ceiling_c

    def _phase_for(self, elapsed: float) -> CalibrationPhase:
        boundaries: tuple[tuple[float, CalibrationPhase], ...] = (
            (self.timing.baseline_end, "baseline"),
            (self.timing.step_up_end, "step_up"),
            (self.timing.recover_up_end, "recover_up"),
            (self.timing.step_down_end, "step_down"),
            (self.timing.recover_down_end, "recover_down"),
            (self.timing.calculation_end, "identifying"),
            (self.timing.validation_end, "validating"),
            (self.timing.total_end, "deciding"),
        )
        for end, phase in boundaries:
            if elapsed < end:
                return phase
        return "complete"

    def _evaluate_validation(self) -> ValidationResult:
        if self.plant is None or len(self._validation_points) < 120:
            return ValidationResult(
                False, "validation_too_short", 0.0, math.inf, 0, 0.0
            )
        points = self._validation_points
        initial_values = [
            point.temperature_c
            for point in points
            if point.elapsed_sec < self.timing.calculation_end + 10.0
        ] or [point.temperature_c for point in points[:15]]
        initial_temp = statistics.median(initial_values)
        bump_values = [
            point.temperature_c
            for point in points
            if point.elapsed_sec < self.timing.validation_bump_end
        ] or [point.temperature_c for point in points]
        bump_response = max(bump_values) - initial_temp
        final_values = [point.temperature_c for point in points[-15:]]
        final_error = self.limits.target_c - statistics.mean(final_values)

        deadband = max(0.20, 2.0 * self.plant.noise_c)
        signs: list[int] = []
        for point in points:
            if point.elapsed_sec < self.timing.validation_bump_end:
                continue
            error = point.target_c - point.temperature_c
            sign = 1 if error > deadband else -1 if error < -deadband else 0
            if sign and (not signs or sign != signs[-1]):
                signs.append(sign)
        crossings = max(0, len(signs) - 1)

        saturation_start: float | None = None
        longest_saturation = 0.0
        for point in points:
            saturated = (
                point.power_pct <= self.limits.power_min_pct + 0.01
                or point.power_pct >= self.limits.power_max_pct - 0.01
            )
            if saturated and saturation_start is None:
                saturation_start = point.elapsed_sec
            elif not saturated and saturation_start is not None:
                longest_saturation = max(
                    longest_saturation, point.elapsed_sec - saturation_start
                )
                saturation_start = None
        if saturation_start is not None:
            longest_saturation = max(
                longest_saturation,
                points[-1].elapsed_sec - saturation_start,
            )

        reason: str | None = None
        if self.plant.tau_sec > 120.0:
            reason = "validation_window_too_short_for_inertia"
        elif bump_response < min(0.5, 0.30 * self.limits.validation_step_c):
            reason = "candidate_response_too_small"
        elif abs(final_error) > 1.0:
            reason = "candidate_did_not_return_to_target"
        elif crossings >= 3:
            reason = "candidate_oscillates"
        elif longest_saturation > 30.0:
            reason = "candidate_saturates_too_long"
        return ValidationResult(
            accepted=reason is None,
            reason=reason,
            bump_response_c=bump_response,
            final_error_c=final_error,
            error_crossings=crossings,
            longest_saturation_sec=longest_saturation,
        )

    def _positive_step_is_confirmed(self) -> bool:
        """Require early physical evidence that more command means more heat."""
        baseline = [
            point.temperature_c
            for point in self.points
            if self.timing.baseline_end - 15.0 <= point.elapsed_sec
            < self.timing.baseline_end
        ]
        step_end = [
            point.temperature_c
            for point in self.points
            if self.timing.step_up_end - 15.0 <= point.elapsed_sec
            < self.timing.step_up_end
        ]
        if len(baseline) < 10 or len(step_end) < 10:
            return False
        noise = statistics.pstdev(baseline)
        minimum_response = max(0.35, 4.0 * noise)
        return statistics.median(step_end) - statistics.median(baseline) >= (
            minimum_response
        )

    def update(self, sample: CalibrationSample) -> CalibrationCommand:
        if self.phase in {"refused", "safe_stop", "complete"}:
            return CalibrationCommand(
                phase=self.phase,
                power_pct=self._last_power,
                target_c=self.limits.target_c,
                restore_config=self.phase != "complete",
                done=True,
                reason=self.reason,
            )
        if self._started_at is None:
            raise RuntimeError("calibration has not started")
        safety_reason = self._safety_reason(sample)
        if safety_reason is not None:
            return self._stop("safe_stop", safety_reason)

        previous_sample_at = self._last_sample_at
        elapsed = sample.now_sec - self._started_at
        self._last_sample_at = sample.now_sec
        requested_phase = self._phase_for(elapsed)

        if (
            requested_phase == "recover_up"
            and self.phase == "step_up"
            and not self._positive_step_is_confirmed()
        ):
            return self._stop("refused", "positive_response_not_confirmed")

        if requested_phase == "complete":
            self.validation_result = self._evaluate_validation()
            if not self.validation_result.accepted:
                return self._stop(
                    "refused",
                    self.validation_result.reason or "candidate_rejected",
                )
            self.phase = "complete"
            self._last_power = self.limits.baseline_power_pct
            return CalibrationCommand(
                phase="complete",
                power_pct=self._last_power,
                target_c=self.limits.target_c,
                done=True,
            )

        if requested_phase == "identifying" and self.plant is None:
            self.phase = "identifying"
            try:
                self.plant = identify_local_fopdt(
                    self.points,
                    timing=self.timing,
                    baseline_power_pct=self.limits.baseline_power_pct,
                    max_drift_c=self.limits.target_step_rise_c,
                )
                self.candidate = tune_simc_candidate(
                    self.plant,
                    current_kp=self.current_kp,
                    current_ki=self.current_ki,
                )
            except IdentificationError as exc:
                return self._stop("refused", str(exc))

        self.phase = requested_phase
        apply_candidate = False
        target = self.limits.target_c
        if self.phase == "baseline":
            power = self.limits.baseline_power_pct
        elif self.phase == "step_up":
            power = self.limits.baseline_power_pct + self.limits.step_pct
        elif self.phase in {"recover_up", "recover_down", "identifying"}:
            power = self.limits.baseline_power_pct
        elif self.phase == "step_down":
            power = self.limits.baseline_power_pct - self.limits.step_pct
        elif self.phase in {"validating", "deciding"}:
            if self.candidate is None:
                return self._stop("refused", "candidate_unavailable")
            if not self._candidate_announced:
                self._validation_integral = self.limits.baseline_power_pct
                self._validation_error = 0.0
                self._candidate_announced = True
                apply_candidate = True
            if elapsed < self.timing.validation_bump_end:
                target += self.limits.validation_step_c
            error = target - sample.temperature_c
            power, self._validation_integral = _pid_power(
                candidate=self.candidate,
                error_c=error,
                previous_error_c=self._validation_error,
                integral_pct=self._validation_integral,
                dt=max(
                    0.01,
                    sample.now_sec - (
                        previous_sample_at
                        if previous_sample_at is not None
                        else sample.now_sec
                    ),
                ),
                power_min=max(
                    self.limits.power_min_pct,
                    self.limits.baseline_power_pct
                    - self.limits.validation_authority_pct,
                ),
                power_max=min(
                    self.limits.power_max_pct,
                    self.limits.baseline_power_pct
                    + self.limits.validation_authority_pct,
                ),
            )
            self._validation_error = error
        else:
            self.phase = "complete"
            self._last_power = self.limits.baseline_power_pct
            return CalibrationCommand(
                phase="complete",
                power_pct=self._last_power,
                target_c=self.limits.target_c,
                done=True,
            )

        self._last_power = max(
            self.limits.power_min_pct,
            min(self.limits.power_max_pct, power),
        )
        self.points.append(CalibrationPoint(
            elapsed_sec=elapsed,
            temperature_c=sample.temperature_c,
            power_pct=self._last_power,
        ))
        if self.phase in {"validating", "deciding"}:
            self._validation_points.append(ValidationPoint(
                elapsed_sec=elapsed,
                temperature_c=sample.temperature_c,
                target_c=target,
                power_pct=self._last_power,
            ))
        return CalibrationCommand(
            phase=self.phase,
            power_pct=self._last_power,
            target_c=target,
            apply_candidate=apply_candidate,
        )


@dataclass(frozen=True, slots=True)
class CalibrationAuditEvent:
    sequence: int
    timestamp_sec: float
    kind: AuditEventKind
    phase: str
    temperature_c: float | None
    ror_c_per_min: float | None
    target_c: float | None
    power_pct: int | None
    reason: str | None
    previous_hash: str
    event_hash: str


def _audit_hash(
    *,
    sequence: int,
    timestamp_sec: float,
    kind: AuditEventKind,
    phase: str,
    temperature_c: float | None,
    ror_c_per_min: float | None,
    target_c: float | None,
    power_pct: int | None,
    reason: str | None,
    previous_hash: str,
) -> str:
    payload = json.dumps(
        {
            "kind": kind,
            "phase": phase,
            "power_pct": power_pct,
            "previous_hash": previous_hash,
            "reason": reason,
            "ror_c_per_min": ror_c_per_min,
            "sequence": sequence,
            "target_c": target_c,
            "temperature_c": temperature_c,
            "timestamp_sec": timestamp_sec,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_calibration_audit(events: tuple[CalibrationAuditEvent, ...]) -> bool:
    """Verify sequence, hash chain and every immutable event payload."""
    previous_hash = "0" * 64
    for sequence, event in enumerate(events):
        if event.sequence != sequence or event.previous_hash != previous_hash:
            return False
        expected = _audit_hash(
            sequence=event.sequence,
            timestamp_sec=event.timestamp_sec,
            kind=event.kind,
            phase=event.phase,
            temperature_c=event.temperature_c,
            ror_c_per_min=event.ror_c_per_min,
            target_c=event.target_c,
            power_pct=event.power_pct,
            reason=event.reason,
            previous_hash=event.previous_hash,
        )
        if event.event_hash != expected:
            return False
        previous_hash = event.event_hash
    return True


@dataclass(frozen=True, slots=True)
class PendingPowerCommand:
    heater_slider: int
    power_pct: int
    issued_at_sec: float


# Injected Qt/hardware callbacks are an exception boundary: every exception,
# including a third-party one, must become a safe stop and rollback.
# pylint: disable=broad-exception-caught
class LiveCalibrationCoordinator:
    """Fail-safe boundary between the pure protocol and a live actuator.

    All side effects are injected.  This class is therefore testable without
    Qt and is not, by itself, reachable from the user interface.
    """

    def __init__(
        self,
        protocol: CalibrationProtocol,
        *,
        heater_slider: int,
        zero_output_qualified: bool,
        request_power: Callable[[int, int, bool], None],
        apply_candidate: Callable[[PIDCandidate], None],
        restore_config: Callable[[], None],
        cool_machine: Callable[[], None] | None = None,
        acknowledgement_timeout_sec: float = 1.5,
    ) -> None:
        self.protocol = protocol
        self.heater_slider = heater_slider
        self.zero_output_qualified = zero_output_qualified
        self.request_power = request_power
        self.apply_candidate = apply_candidate
        self.restore_config = restore_config
        self.cool_machine = cool_machine
        self.acknowledgement_timeout_sec = acknowledgement_timeout_sec
        self.phase: LiveCoordinatorPhase = "idle"
        self.reason: str | None = None
        self.pending: PendingPowerCommand | None = None
        self.last_requested_power: int | None = None
        self.last_command: CalibrationCommand | None = None
        self._restored = False
        self._complete_after_ack = False
        # None means that no terminal 0% command has been requested yet.
        # True confirms only dispatch through Artisan's configured action; the
        # operator must still confirm that the physical heater is off.
        self.shutdown_command_dispatched: bool | None = None
        self._audit_events: list[CalibrationAuditEvent] = []
        self._last_timestamp_sec = 0.0

    @property
    def audit_events(self) -> tuple[CalibrationAuditEvent, ...]:
        return tuple(self._audit_events)

    def start(
        self,
        sample: CalibrationSample,
        *,
        readiness: CalibrationReadinessReport,
    ) -> CalibrationCommand:
        if self.phase != "idle":
            raise RuntimeError("live calibration already started")
        self._last_timestamp_sec = sample.now_sec
        self._record_sample(sample)
        if not readiness.ready:
            return self._refuse_without_side_effect(
                "readiness_changed", sample.now_sec
            )
        if not self.zero_output_qualified:
            return self._refuse_without_side_effect(
                "zero_output_not_qualified", sample.now_sec
            )
        self.phase = "running"
        command = self.protocol.start(sample)
        self._record("started", timestamp_sec=sample.now_sec)
        return self._execute(command, sample.now_sec)

    def update(
        self,
        sample: CalibrationSample,
        *,
        runtime_stop_reason: str | None = None,
    ) -> CalibrationCommand:
        if self.phase != "running":
            if self.last_command is None:
                raise RuntimeError("live calibration has not started")
            return self.last_command
        self._last_timestamp_sec = sample.now_sec
        self._record_sample(sample)
        if runtime_stop_reason is not None:
            return self._emergency_stop(
                runtime_stop_reason, now_sec=sample.now_sec
            )
        if self.pending is not None:
            if (
                sample.now_sec - self.pending.issued_at_sec
                > self.acknowledgement_timeout_sec
            ):
                return self._emergency_stop(
                    "actuator_ack_timeout", now_sec=sample.now_sec
                )
            if self.last_command is None:
                raise RuntimeError("pending command without protocol state")
            return self.last_command
        return self._execute(self.protocol.update(sample), sample.now_sec)

    def acknowledge(
        self,
        *,
        heater_slider: int,
        applied_power_pct: int,
        action_fired: bool,
        now_sec: float | None = None,
    ) -> bool:
        timestamp = self._last_timestamp_sec if now_sec is None else now_sec
        self._last_timestamp_sec = timestamp
        pending = self.pending
        if pending is None:
            return False
        if heater_slider != pending.heater_slider:
            return False
        if self.phase in {"complete", "safe_stop", "refused"} and pending.power_pct == 0:
            self.pending = None
            self.shutdown_command_dispatched = bool(
                action_fired and applied_power_pct == 0
            )
            if self.shutdown_command_dispatched:
                self._record(
                    "power_acknowledged",
                    timestamp_sec=timestamp,
                    power_pct=0,
                )
            return self.shutdown_command_dispatched
        if self.phase != "running":
            return False
        if not action_fired:
            self._emergency_stop("heater_action_not_fired", now_sec=timestamp)
            return False
        if applied_power_pct != pending.power_pct:
            self._emergency_stop("actuator_value_mismatch", now_sec=timestamp)
            return False
        self.pending = None
        self._record(
            "power_acknowledged",
            timestamp_sec=timestamp,
            power_pct=applied_power_pct,
        )
        if self._complete_after_ack:
            self._complete_after_ack = False
            self.phase = "complete"
            self._record("complete", timestamp_sec=timestamp)
        return True

    def poll(self, now_sec: float) -> CalibrationCommand | None:
        self._last_timestamp_sec = now_sec
        if (
            self.phase == "running"
            and self.pending is not None
            and now_sec - self.pending.issued_at_sec
            > self.acknowledgement_timeout_sec
        ):
            return self._emergency_stop(
                "actuator_ack_timeout", now_sec=now_sec
            )
        return None

    def abort(self, reason: str, *, now_sec: float) -> CalibrationCommand:
        """Request the same fail-safe zero and rollback path from an adapter."""
        if self.phase in {"safe_stop", "refused"} and self.last_command is not None:
            return self.last_command
        return self._emergency_stop(reason, now_sec=now_sec)

    def request_zero_after_complete(self, *, now_sec: float) -> None:
        """Stop heat after an accepted run without rolling back its PID gains."""
        if self.phase != "complete":
            raise RuntimeError("calibration is not complete")
        self._last_timestamp_sec = now_sec
        self.pending = PendingPowerCommand(
            heater_slider=self.heater_slider,
            power_pct=0,
            issued_at_sec=now_sec,
        )
        self.last_requested_power = 0
        self.shutdown_command_dispatched = False
        self._record(
            "power_requested",
            timestamp_sec=now_sec,
            power_pct=0,
            reason="test_complete",
        )
        try:
            self.request_power(self.heater_slider, 0, True)
        except Exception:  # noqa: BLE001 - physical confirmation remains mandatory
            self.pending = None
        self._cool_down(now_sec)

    def _execute(
        self, command: CalibrationCommand, now_sec: float
    ) -> CalibrationCommand:
        self.last_command = command
        if command.phase in {"safe_stop", "refused"} or command.restore_config:
            return self._emergency_stop(
                command.reason or "protocol_requested_rollback",
                refused=command.phase == "refused",
                now_sec=now_sec,
            )
        if command.apply_candidate:
            candidate = self.protocol.candidate
            if candidate is None:
                return self._emergency_stop(
                    "candidate_unavailable", refused=True, now_sec=now_sec
                )
            try:
                self.apply_candidate(candidate)
            except Exception:  # noqa: BLE001 - callback is the safety boundary
                return self._emergency_stop(
                    "candidate_apply_failed", now_sec=now_sec
                )
            self._record("candidate_applied", timestamp_sec=now_sec)
        if not self._issue_power(round(command.power_pct), now_sec):
            assert self.last_command is not None
            return self.last_command
        if command.done:
            if self.pending is None:
                self.phase = "complete"
                self._record("complete", timestamp_sec=now_sec)
            else:
                self._complete_after_ack = True
        return command

    def _issue_power(self, power_pct: int, now_sec: float) -> bool:
        if power_pct == self.last_requested_power:
            return True
        self.pending = PendingPowerCommand(
            heater_slider=self.heater_slider,
            power_pct=power_pct,
            issued_at_sec=now_sec,
        )
        self.last_requested_power = power_pct
        self._record(
            "power_requested",
            timestamp_sec=now_sec,
            power_pct=power_pct,
        )
        try:
            self.request_power(self.heater_slider, power_pct, True)
        except Exception:  # noqa: BLE001 - callback is the safety boundary
            self._emergency_stop("actuator_request_failed", now_sec=now_sec)
            return False
        return self.phase == "running"

    def _restore_once(self, now_sec: float) -> None:
        if self._restored:
            return
        self._restored = True
        try:
            self.restore_config()
            self._record("config_restored", timestamp_sec=now_sec)
        except Exception:  # noqa: BLE001 - retain the original stop reason
            self.reason = (
                "config_restore_failed"
                if self.reason is None
                else f"{self.reason};config_restore_failed"
            )
            self._record(
                "config_restore_failed",
                timestamp_sec=now_sec,
                reason=self.reason,
            )

    def _emergency_stop(
        self,
        reason: str,
        *,
        refused: bool = False,
        now_sec: float | None = None,
    ) -> CalibrationCommand:
        timestamp = self._last_timestamp_sec if now_sec is None else now_sec
        self._last_timestamp_sec = timestamp
        self.phase = "refused" if refused else "safe_stop"
        self.reason = reason
        self.pending = PendingPowerCommand(
            heater_slider=self.heater_slider,
            power_pct=0,
            issued_at_sec=timestamp,
        )
        self._complete_after_ack = False
        self.last_requested_power = 0
        self.shutdown_command_dispatched = False
        self._record(
            "emergency_stop",
            timestamp_sec=timestamp,
            power_pct=0,
            reason=reason,
        )
        self._record(
            "power_requested",
            timestamp_sec=timestamp,
            power_pct=0,
            reason="emergency_stop",
        )
        try:
            self.request_power(self.heater_slider, 0, True)
        except Exception:  # noqa: BLE001 - restoration must still be attempted
            self.pending = None
        self._cool_down(timestamp)
        self._restore_once(timestamp)
        command = CalibrationCommand(
            phase="refused" if refused else "safe_stop",
            power_pct=0.0,
            target_c=self.protocol.limits.target_c,
            restore_config=True,
            done=True,
            reason=self.reason,
        )
        self.last_command = command
        return command

    def _cool_down(self, timestamp: float) -> None:
        """Protocol section 8.2: cutting the heat does not cool a hot drum.

        Terminal only.  Opening the airflow mid-measurement would change the
        very machine being identified, so this is never called while running.
        """
        if self.cool_machine is None:
            return
        try:
            self.cool_machine()
        except Exception:  # noqa: BLE001 - a failed cool-down must not mask the stop
            return
        self._record("cooling_requested", timestamp_sec=timestamp)

    @staticmethod
    def _finite_or_none(value: float | None) -> float | None:
        if value is None or not math.isfinite(value):
            return None
        return value

    def _record_sample(self, sample: CalibrationSample) -> None:
        reason = (
            "non_finite_temperature"
            if not math.isfinite(sample.temperature_c)
            else None
        )
        self._record(
            "sample",
            timestamp_sec=sample.now_sec,
            temperature_c=sample.temperature_c,
            ror_c_per_min=sample.ror_c_per_min,
            reason=reason,
        )

    def _record(
        self,
        kind: AuditEventKind,
        *,
        timestamp_sec: float,
        temperature_c: float | None = None,
        ror_c_per_min: float | None = None,
        power_pct: int | None = None,
        reason: str | None = None,
    ) -> None:
        sequence = len(self._audit_events)
        previous_hash = (
            self._audit_events[-1].event_hash
            if self._audit_events else "0" * 64
        )
        target = (
            self.last_command.target_c
            if self.last_command is not None
            else self.protocol.limits.target_c
        )
        clean_timestamp = self._finite_or_none(timestamp_sec)
        if clean_timestamp is None:
            raise ValueError("audit timestamp must be finite")
        clean_temperature = self._finite_or_none(temperature_c)
        clean_ror = self._finite_or_none(ror_c_per_min)
        clean_target = self._finite_or_none(target)
        event_hash = _audit_hash(
            sequence=sequence,
            timestamp_sec=clean_timestamp,
            kind=kind,
            phase=self.protocol.phase,
            temperature_c=clean_temperature,
            ror_c_per_min=clean_ror,
            target_c=clean_target,
            power_pct=power_pct,
            reason=reason,
            previous_hash=previous_hash,
        )
        self._audit_events.append(CalibrationAuditEvent(
            sequence=sequence,
            timestamp_sec=clean_timestamp,
            kind=kind,
            phase=self.protocol.phase,
            temperature_c=clean_temperature,
            ror_c_per_min=clean_ror,
            target_c=clean_target,
            power_pct=power_pct,
            reason=reason,
            previous_hash=previous_hash,
            event_hash=event_hash,
        ))

    def _refuse_without_side_effect(
        self, reason: str, now_sec: float
    ) -> CalibrationCommand:
        self.phase = "refused"
        self.reason = reason
        self._record(
            "start_refused", timestamp_sec=now_sec, reason=reason
        )
        command = CalibrationCommand(
            phase="refused",
            power_pct=0.0,
            target_c=self.protocol.limits.target_c,
            done=True,
            reason=reason,
        )
        self.last_command = command
        return command
# pylint: enable=broad-exception-caught


def run_reference_simulation(
    *,
    current_kp: float,
    current_ki: float,
) -> CalibrationProtocol:
    """Exercise all 600 seconds against a harmless deterministic virtual plant.

    This is a software self-test, not a model of the connected roaster.  It is
    intentionally kept here so the UI cannot accidentally substitute a live
    heater command for a simulated one.
    """
    target = 200.0
    baseline_power = 30.0
    delay_sec = 5
    plant_gain = 0.15
    plant_tau = 55.0
    protocol = CalibrationProtocol(
        CalibrationLimits(
            target_c=target,
            baseline_power_pct=baseline_power,
            thermal_gain_c_per_pct=plant_gain,
            step_response_fraction=1.0 - math.exp(-90.0 / plant_tau),
        ),
        current_kp=current_kp,
        current_ki=current_ki,
        current_kd=0.0,
    )
    delayed_powers = deque(
        [baseline_power] * (delay_sec + 1), maxlen=delay_sec + 1
    )
    temperature = target
    previous_temperature = target
    for second in range(601):
        ror = (temperature - previous_temperature) * 60.0 if second else 0.0
        sample = CalibrationSample(float(second), temperature, ror)
        command = protocol.start(sample) if second == 0 else protocol.update(sample)
        if command.done:
            break
        delayed_powers.append(command.power_pct)
        delayed_power = delayed_powers[0]
        previous_temperature = temperature
        offset = temperature - target
        offset += (
            plant_gain * (delayed_power - baseline_power) - offset
        ) / plant_tau
        temperature = target + offset
    return protocol

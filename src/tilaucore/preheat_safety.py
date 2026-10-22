# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure sensor-safety state for the Tilau preheat controller."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SensorSafetyLimits:
    """Plausibility limits in canonical °C and monotonic seconds."""

    min_temp_c: float = -10.0
    max_temp_c: float = 350.0
    max_abs_ror_c_per_min: float = 120.0
    # The implausible-RoR test divides by the interval between two samples. On a
    # fast sampling rate one probe LSB spans a fraction of a second and reads as
    # hundreds of °C/min, so the test is skipped below this interval.
    min_ror_dt_sec: float = 1.0
    stale_after_sec: float = 3.5
    invalid_limit: int = 3
    recovery_valid_samples: int = 3
    # A probe alternating valid/invalid never reaches invalid_limit consecutive
    # failures nor recovery_valid_samples consecutive successes: without this
    # bound it would hold control off, silently, for the whole preheat.
    degraded_timeout_sec: float = 20.0
    frozen_after_sec: float = 15.0
    frozen_epsilon_c: float = 0.05
    frozen_min_burner: float = 40.0
    frozen_min_error_c: float = 10.0


@dataclass(frozen=True, slots=True)
class SensorSafetyDecision:
    """Result of one sample check.

    ``valid`` describes the sample itself. ``control_allowed`` remains false
    during recovery, until enough consecutive valid samples have arrived.
    """

    valid: bool
    control_allowed: bool
    latched: bool
    reason: str | None = None


class PreheatSensorGuard:
    """Validate samples and hold the degraded/fault-latched state.

    The class deliberately has no Qt or Artisan dependency, so the safety
    policy can be exhaustively unit-tested without an application instance.
    """

    def __init__(self, limits: SensorSafetyLimits | None = None) -> None:
        self.limits = limits or SensorSafetyLimits()
        self.reset(0.0)

    def reset(self, now: float) -> None:
        self.started_at = float(now)
        self.last_valid_at: float | None = None
        self.last_valid_temp_c: float | None = None
        self.last_change_at = float(now)
        self.last_change_temp_c: float | None = None
        self.consecutive_invalid = 0
        self.consecutive_valid = 0
        self.degraded = False
        self.degraded_since: float | None = None
        self.latched = False
        self.reason: str | None = None

    def latch(self, reason: str) -> None:
        self.degraded = True
        if self.degraded_since is None:
            self.degraded_since = self.started_at
        self.latched = True
        self.reason = reason

    def stale_reason(self, now: float) -> str | None:
        reference = self.last_valid_at if self.last_valid_at is not None else self.started_at
        if float(now) - reference > self.limits.stale_after_sec:
            return "sensor_timeout"
        return None

    def evaluate(
        self,
        temp_c: float,
        now: float,
        *,
        burner_pct: float = 0.0,
        target_c: float | None = None,
        temporal_checks: bool = True,
    ) -> SensorSafetyDecision:
        if self.latched:
            return SensorSafetyDecision(False, False, True, self.reason or "sensor_fault")

        now = float(now)

        try:
            value = float(temp_c)
        except (TypeError, ValueError):
            return self._invalid("sensor_non_numeric", now)

        if not math.isfinite(value):
            return self._invalid("sensor_non_finite", now)
        if value == -1.0:
            return self._invalid("sensor_missing", now)
        if not self.limits.min_temp_c <= value <= self.limits.max_temp_c:
            return self._invalid("sensor_out_of_range", now)

        if (
            temporal_checks
            and self.last_valid_at is not None
            and self.last_valid_temp_c is not None
        ):
            dt = now - self.last_valid_at
            if dt >= self.limits.min_ror_dt_sec:
                ror = (value - self.last_valid_temp_c) / (dt / 60.0)
                if abs(ror) > self.limits.max_abs_ror_c_per_min:
                    return self._invalid("sensor_implausible_ror", now)

        if not temporal_checks:
            # Profile replay is driven by its own (possibly accelerated) clock.
            # Keep value validation, but do not compare that clock to wall time.
            self.last_change_temp_c = value
            self.last_change_at = now
        elif (
            self.last_change_temp_c is None
            or abs(value - self.last_change_temp_c) >= self.limits.frozen_epsilon_c
        ):
            self.last_change_temp_c = value
            self.last_change_at = now
        elif (
            target_c is not None
            and burner_pct >= self.limits.frozen_min_burner
            and float(target_c) - value >= self.limits.frozen_min_error_c
            and now - self.last_change_at > self.limits.frozen_after_sec
        ):
            return self._invalid("sensor_frozen", now)

        self.last_valid_at = now
        self.last_valid_temp_c = value
        self.consecutive_invalid = 0

        if self.degraded:
            self.consecutive_valid += 1
            if self.consecutive_valid < self.limits.recovery_valid_samples:
                if self._degraded_too_long(now):
                    reason = self.reason or "sensor_unstable"
                    self.latched = True
                    return SensorSafetyDecision(False, False, True, reason)
                return SensorSafetyDecision(True, False, False, "sensor_recovering")
            self.degraded = False
            self.degraded_since = None
            self.reason = None
        else:
            self.consecutive_valid = 0

        return SensorSafetyDecision(True, True, False)

    def _degraded_too_long(self, now: float) -> bool:
        """True once control has been withheld longer than the bounded window."""
        if self.degraded_since is None:
            return False
        return now - self.degraded_since > self.limits.degraded_timeout_sec

    def _invalid(self, reason: str, now: float) -> SensorSafetyDecision:
        self.degraded = True
        if self.degraded_since is None:
            self.degraded_since = float(now)
        self.reason = reason
        self.consecutive_invalid += 1
        self.consecutive_valid = 0
        if (self.consecutive_invalid >= self.limits.invalid_limit
                or self._degraded_too_long(now)):
            self.latched = True
        return SensorSafetyDecision(False, False, self.latched, reason)

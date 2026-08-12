# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure live observation and action-provenance contracts for roast guidance."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum


class Lever(Enum):
    AIR = "air"
    DRUM = "drum"
    EXT = "ext"
    HEATER = "heater"


def controls_observable(slider_visibilities: object) -> bool:
    """Whether the current configuration exposes at least one control channel."""
    try:
        return any(bool(value) for value in slider_visibilities[:4])  # type: ignore[index]
    except (TypeError, AttributeError):
        return False


def observable_control_levers(
    slider_visibilities: object,
    *,
    has_airflow_control: bool,
    drum_variable_speed: bool,
    has_heater_control: bool,
    has_external_control: bool = False,
) -> frozenset[Lever]:
    """Intersect roaster capabilities with enabled acquisition sliders."""
    try:
        visible = tuple(bool(value) for value in slider_visibilities[:4])  # type: ignore[index]
    except (TypeError, AttributeError):
        return frozenset()
    if len(visible) < 4:
        return frozenset()
    return frozenset(
        lever for enabled, capable, lever in (
            (visible[0], has_airflow_control, Lever.AIR),
            (visible[1], drum_variable_speed, Lever.DRUM),
            (visible[2], has_external_control, Lever.EXT),
            (visible[3], has_heater_control, Lever.HEATER),
        ) if enabled and capable)


@dataclass(frozen=True)
class ResponseLagParams:
    """Time before judging the physical response of each manual lever."""

    air_s: float = 12.0
    drum_s: float = 25.0
    ext_s: float = 12.0


def response_lag_s(
    lever: Lever, heater_lag_s: float, params: ResponseLagParams | None = None,
) -> float:
    """Return a non-negative observation delay for the changed lever."""
    p = params or ResponseLagParams()
    lag = {
        Lever.AIR: p.air_s,
        Lever.DRUM: p.drum_s,
        Lever.EXT: p.ext_s,
        Lever.HEATER: heater_lag_s,
    }[lever]
    return max(0.0, float(lag))


def response_window_s(
    levers: list[Lever] | tuple[Lever, ...], heater_lag_s: float,
    params: ResponseLagParams | None = None,
) -> float:
    """Use the slowest physical response for one simultaneous action batch."""
    if not levers:
        return 0.0
    return max(response_lag_s(lever, heater_lag_s, params) for lever in levers)


class ActionSource(Enum):
    OPERATOR = "operator"
    AUTO = "auto"
    ALARM_AUTOMATION = "alarm_automation"
    PLAN_AUTOMATION = "plan_automation"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LeverAction:
    at_s: float
    lever: Lever
    previous: float
    value: float
    source: ActionSource


@dataclass(frozen=True)
class _ExpectedAction:
    value: float
    source: ActionSource
    expires_at_s: float
    tolerance: float


class ActionProvenanceTracker:
    """Classify lever changes against short-lived declared expectations."""

    def __init__(self) -> None:
        self._last: dict[Lever, float] = {}
        self._expected: dict[Lever, _ExpectedAction] = {}

    def reset(self) -> None:
        self._last.clear()
        self._expected.clear()

    def expect(
        self,
        lever: Lever,
        value: float,
        source: ActionSource,
        now_s: float,
        *,
        ttl_s: float = 8.0,
        tolerance: float = 0.5,
    ) -> None:
        self._expected[lever] = _ExpectedAction(
            value=float(value), source=source,
            expires_at_s=now_s + max(0.0, ttl_s), tolerance=max(0.0, tolerance))

    def observe(
        self,
        values: dict[Lever, float | None],
        now_s: float,
        *,
        unexplained_source: ActionSource = ActionSource.OPERATOR,
    ) -> list[LeverAction]:
        actions: list[LeverAction] = []
        for lever, raw in values.items():
            if raw is None or not math.isfinite(float(raw)):
                continue
            value = float(raw)
            previous = self._last.get(lever)
            self._last[lever] = value
            if previous is None or value == previous:
                continue
            expected = self._expected.get(lever)
            if expected is not None and now_s <= expected.expires_at_s \
                    and abs(value - expected.value) <= expected.tolerance:
                source = expected.source
                self._expected.pop(lever, None)
            else:
                if expected is not None and now_s > expected.expires_at_s:
                    self._expected.pop(lever, None)
                source = unexplained_source
            actions.append(LeverAction(now_s, lever, previous, value, source))
        return actions


@dataclass(frozen=True)
class ObservationParams:
    stability_window_s: float = 12.0
    stability_hold_s: float = 8.0
    min_points: int = 5
    spread_abs: float = 2.0
    spread_rel: float = 0.25


@dataclass(frozen=True)
class TrajectoryObservation:
    ror: float | None
    ror_median: float | None
    ror_spread: float | None
    stable: bool
    viable: bool


class LiveTrajectoryObserver:
    """Time-based RoR stability observer, independent of sampling frequency."""

    def __init__(self, params: ObservationParams | None = None) -> None:
        self.p = params or ObservationParams()
        self._ror: deque[tuple[float, float]] = deque(maxlen=256)
        self._stable_since: float | None = None

    def reset(self) -> None:
        self._ror.clear()
        self._stable_since = None

    def update(self, now_s: float, ror: float | None, *, viability_floor: float) -> TrajectoryObservation:
        if ror is not None and math.isfinite(float(ror)):
            self._ror.append((now_s, float(ror)))
        cutoff = now_s - self.p.stability_window_s
        while self._ror and self._ror[0][0] < cutoff:
            self._ror.popleft()
        values = [value for _at, value in self._ror]
        median = sorted(values)[len(values) // 2] if values else None
        spread = max(values) - min(values) if values else None
        enough_span = bool(self._ror) and now_s - self._ror[0][0] >= self.p.stability_window_s * 0.75
        candidate = (
            len(values) >= self.p.min_points
            and enough_span
            and median is not None
            and spread is not None
            and spread <= max(self.p.spread_abs, abs(median) * self.p.spread_rel)
        )
        if candidate:
            if self._stable_since is None:
                self._stable_since = now_s
        else:
            self._stable_since = None
        stable = self._stable_since is not None and now_s - self._stable_since >= self.p.stability_hold_s
        viable = ror is not None and math.isfinite(float(ror)) and float(ror) > viability_floor
        return TrajectoryObservation(ror, median, spread, stable, viable)

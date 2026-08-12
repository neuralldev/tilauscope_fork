# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Local consequence projection for an operator-driven roast trajectory.

The projector never writes into the roast plan and never proposes a lever
position. It answers only: if the recently observed RoR tendency continues,
when and in what state will the next physical milestone be reached?
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectionParams:
    window_s: float = 35.0
    min_span_s: float = 15.0
    min_points: int = 8
    max_sample_age_s: float = 5.0
    max_eta_s: float = 8.0 * 60.0
    min_ror: float = 0.5
    max_relative_residual: float = 0.35


@dataclass(frozen=True)
class TrajectoryProjection:
    eta_s: float
    terminal_ror: float
    projected_phase_duration_s: float
    projected_dtr: float | None
    confidence: float
    ror_slope_per_min: float


class OperatorTrajectoryProjector:
    """Project a short-horizon milestone from time/BT/RoR samples."""

    def __init__(self, params: ProjectionParams | None = None) -> None:
        self.p = params or ProjectionParams()
        self._samples: deque[tuple[float, float, float]] = deque(maxlen=512)

    def reset(self) -> None:
        self._samples.clear()

    def update(self, now_s: float, bt: float, ror: float | None) -> None:
        if not (math.isfinite(now_s) and math.isfinite(bt)):
            return
        if ror is None or not math.isfinite(float(ror)):
            return
        self._samples.append((float(now_s), float(bt), float(ror)))
        cutoff = now_s - self.p.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def project(
        self,
        *,
        now_s: float,
        target_bt: float,
        phase_started_s: float,
        fc_started_s: float | None = None,
    ) -> TrajectoryProjection | None:
        samples = list(self._samples)
        if len(samples) < self.p.min_points:
            return None
        if now_s < samples[-1][0] or now_s - samples[-1][0] > self.p.max_sample_age_s:
            return None
        span_s = samples[-1][0] - samples[0][0]
        if span_s < self.p.min_span_s:
            return None
        bt_now = samples[-1][1]
        delta_bt = target_bt - bt_now
        if delta_bt <= 0:
            return TrajectoryProjection(
                eta_s=0.0,
                terminal_ror=max(0.0, samples[-1][2]),
                projected_phase_duration_s=max(0.0, now_s - phase_started_s),
                projected_dtr=self._project_dtr(now_s, 0.0, fc_started_s),
                confidence=1.0,
                ror_slope_per_min=0.0,
            )

        # Least-squares RoR(t), with t in minutes relative to the newest sample.
        xs = [(at - samples[-1][0]) / 60.0 for at, _bt, _ror in samples]
        ys = [ror for _at, _bt, ror in samples]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = 0.0 if den <= 1e-12 else (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / den)
        intercept = mean_y - slope * mean_x  # predicted RoR at newest sample
        if intercept < self.p.min_ror:
            return None

        eta_min = self._solve_eta_minutes(delta_bt, intercept, slope)
        if eta_min is None:
            return None
        eta_s = eta_min * 60.0
        if eta_s < 0.0 or eta_s > self.p.max_eta_s:
            return None
        terminal = intercept + slope * eta_min
        if terminal < self.p.min_ror:
            return None

        fitted = [intercept + slope * x for x in xs]
        rms = math.sqrt(sum(
            (actual - fit) ** 2 for actual, fit in zip(ys, fitted, strict=True)) / len(ys))
        relative_residual = rms / max(abs(mean_y), self.p.min_ror)
        if relative_residual > self.p.max_relative_residual:
            return None
        span_conf = min(1.0, span_s / self.p.window_s)
        fit_conf = max(0.0, 1.0 - relative_residual / self.p.max_relative_residual)
        horizon_conf = max(0.0, 1.0 - eta_s / self.p.max_eta_s * 0.5)
        confidence = max(0.0, min(1.0, span_conf * fit_conf * horizon_conf))
        return TrajectoryProjection(
            eta_s=eta_s,
            terminal_ror=terminal,
            projected_phase_duration_s=max(0.0, now_s - phase_started_s) + eta_s,
            projected_dtr=self._project_dtr(now_s, eta_s, fc_started_s),
            confidence=confidence,
            ror_slope_per_min=slope,
        )

    @staticmethod
    def _solve_eta_minutes(delta_bt: float, ror_now: float, slope: float) -> float | None:
        # Integral of RoR(t): delta BT = r0*t + 1/2*slope*t².
        if abs(slope) < 1e-6:
            return delta_bt / ror_now if ror_now > 0 else None
        discriminant = ror_now * ror_now + 2.0 * slope * delta_bt
        if discriminant < 0:
            return None
        root = math.sqrt(discriminant)
        candidates = [(-ror_now + root) / slope, (-ror_now - root) / slope]
        positive = [value for value in candidates if value >= 0.0]
        return min(positive) if positive else None

    @staticmethod
    def _project_dtr(now_s: float, eta_s: float, fc_started_s: float | None) -> float | None:
        if fc_started_s is None or fc_started_s < 0.0 or now_s < fc_started_s:
            return None
        total = now_s + eta_s
        if total <= 0.0:
            return None
        return (total - fc_started_s) / total * 100.0

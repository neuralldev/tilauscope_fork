# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure end-to-end orchestration for one live guided-roast session."""

from __future__ import annotations

from dataclasses import dataclass

from tilauscope.guidance_advice import AdviceCandidate, AdviceSelector, GuidanceOutput
from tilauscope.guidance_core import (
    GuidanceArbiter,
    GuidanceDecision,
    GuidanceMode,
    GuidanceParams,
)
from tilauscope.guidance_observer import (
    ActionProvenanceTracker,
    LiveTrajectoryObserver,
    ObservationParams,
    TrajectoryObservation,
)
from tilauscope.guidance_trajectory import (
    OperatorTrajectoryProjector,
    ProjectionParams,
    TrajectoryProjection,
)
from tilauscope.guidance_risk import GuidanceRiskEngine, RiskParams, RiskSignal


@dataclass(frozen=True)
class GuidanceSample:
    wall_s: float
    roast_s: float
    bt: float
    ror: float | None
    target_ror: float | None
    target_bt: float | None
    phase_started_s: float
    viability_floor: float
    viability_active: bool = True
    viability_requires_established: bool = False
    fc_started_s: float | None = None
    authority_hold: bool = False
    #: Factor turning a °C/min threshold into the unit `ror` carries (1.8 in °F).
    #: The session frame is the operator's unit; only the doctrine constants
    #: buried in the engines are stated in °C and need it.
    ror_scale: float = 1.0


@dataclass(frozen=True)
class GuidanceSessionState:
    decision: GuidanceDecision
    observation: TrajectoryObservation
    projection: TrajectoryProjection | None
    plan_deviation_rel: float | None
    risks: tuple[RiskSignal, ...]


class GuidanceSession:
    """Own all pure guidance state and advance it with one normalized sample."""

    def __init__(
        self,
        *,
        guidance_params: GuidanceParams | None = None,
        observation_params: ObservationParams | None = None,
        projection_params: ProjectionParams | None = None,
        risk_params: RiskParams | None = None,
        minimum_advice_confidence: float = 0.35,
    ) -> None:
        self.arbiter = GuidanceArbiter(guidance_params)
        self.actions = ActionProvenanceTracker()
        self.observer = LiveTrajectoryObserver(observation_params)
        self.projector = OperatorTrajectoryProjector(projection_params)
        self.selector = AdviceSelector(minimum_confidence=minimum_advice_confidence)
        self.risks = GuidanceRiskEngine(risk_params)
        self.actions_observable = True

    def reset(self) -> GuidanceDecision:
        self.actions.reset()
        self.observer.reset()
        self.projector.reset()
        self.risks.reset()
        return self.arbiter.reset()

    def reset_phase(self) -> None:
        self.observer.reset()
        self.projector.reset()
        self.risks.reset()

    def set_auto(self, armed: bool) -> GuidanceDecision:
        return self.arbiter.set_auto(armed)

    def operator_action(self, now_s: float, lag_s: float | None = None) -> GuidanceDecision:
        if not self.actions_observable:
            return self.arbiter.decision()
        return self.arbiter.operator_action(now_s, lag_s)

    def set_actions_observable(self, observable: bool) -> None:
        """Declare whether this session can observe actuator channels."""
        self.actions_observable = bool(observable)

    def tick(self, sample: GuidanceSample) -> GuidanceSessionState:
        observation = self.observer.update(
            sample.wall_s, sample.ror, viability_floor=sample.viability_floor,
            ror_scale=sample.ror_scale)
        self.projector.update(sample.roast_s, sample.bt, sample.ror)
        deviation = None
        if sample.ror is not None and sample.target_ror is not None and sample.target_ror > 0:
            deviation = abs(sample.ror - sample.target_ror) / sample.target_ror
        risks = self.risks.evaluate(
            sample.wall_s, sample.ror, sample.viability_floor,
            active=sample.viability_active,
            require_established=sample.viability_requires_established)
        projection = None
        if sample.target_bt is not None and sample.target_bt > 0:
            projection = self.projector.project(
                now_s=sample.roast_s,
                target_bt=sample.target_bt,
                phase_started_s=sample.phase_started_s,
                fc_started_s=sample.fc_started_s,
                ror_scale=sample.ror_scale,
            )
        projection_credible = (
            projection is not None
            and projection.confidence >= self.selector.minimum_confidence)
        if self.arbiter.mode is not GuidanceMode.AUTO and not (
                sample.authority_hold and not risks):
            decision = self.arbiter.tick(
                sample.wall_s,
                plan_deviation_rel=deviation,
                trajectory_stable=observation.stable and projection_credible,
                trajectory_viable=observation.viable and not risks,
                risk_active=bool(risks),
            )
        else:
            decision = self.arbiter.decision()
        return GuidanceSessionState(decision, observation, projection, deviation, risks)

    def select(self, candidates: list[AdviceCandidate], now_s: float) -> GuidanceOutput:
        return self.selector.select(
            candidates, self.arbiter.decision(), now_s,
            actions_observable=self.actions_observable)

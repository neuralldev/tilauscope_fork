# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure decision core for manual guidance and AUTO authority.

The roast plan is a reference, not an unconditional source of instructions.
This module decides whether plan-relative directional advice is still allowed.
It deliberately contains no Qt or Artisan dependency so transitions can be
tested independently of the live panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GuidanceMode(Enum):
    """Current authority used by the live roast guidance."""

    PLAN = "plan"
    OBSERVE_ACTION = "observe_action"
    ADAPTIVE = "adaptive"
    SAFETY_ONLY = "safety_only"
    AUTO = "auto"


@dataclass(frozen=True)
class GuidanceParams:
    """Timing and hysteresis for guidance-authority transitions."""

    operator_lag_s: float = 45.0
    plan_return_rel: float = 0.15
    plan_return_hold_s: float = 15.0


@dataclass(frozen=True)
class GuidanceDecision:
    mode: GuidanceMode
    directional_plan_advice: bool
    reason: str


class GuidanceArbiter:
    """Small state machine selecting the authority of live guidance.

    An operator action opens an attribution window. Once its effect is
    observable, a roast which remains away from plan but is stable, viable and
    projectable becomes an operator trajectory. An illegible trajectory falls
    back to safety-only guidance; neither state may issue a command whose sole
    rationale is returning to plan.
    """

    def __init__(self, params: GuidanceParams | None = None) -> None:
        self.p = params or GuidanceParams()
        self._mode = GuidanceMode.PLAN
        self._observing_until = 0.0
        self._plan_return_since: float | None = None
        self._safety_origin: GuidanceMode | None = None
        self._reason = "session started on plan"

    @property
    def mode(self) -> GuidanceMode:
        return self._mode

    def reset(self) -> GuidanceDecision:
        self._mode = GuidanceMode.PLAN
        self._observing_until = 0.0
        self._plan_return_since = None
        self._safety_origin = None
        self._reason = "session reset"
        return self.decision()

    def set_auto(self, armed: bool) -> GuidanceDecision:
        if armed:
            self._mode = GuidanceMode.AUTO
            self._safety_origin = None
            self._reason = "AUTO explicitly armed"
        elif self._mode is GuidanceMode.AUTO:
            self._mode = GuidanceMode.PLAN
            self._safety_origin = None
            self._reason = "AUTO released; manual guidance starts from plan"
        return self.decision()

    def operator_action(self, now_s: float, lag_s: float | None = None) -> GuidanceDecision:
        lag = max(0.0, self.p.operator_lag_s if lag_s is None else lag_s)
        deadline = now_s + lag
        if self._mode is GuidanceMode.OBSERVE_ACTION:
            # Several physical responses may overlap. A later fast-lever move
            # must not erase the remaining inertia of an earlier slow one.
            self._observing_until = max(self._observing_until, deadline)
        else:
            self._observing_until = deadline
        self._mode = GuidanceMode.OBSERVE_ACTION
        self._safety_origin = None
        self._plan_return_since = None
        self._reason = "waiting for the operator action to affect the roast"
        return self.decision()

    def tick(
        self,
        now_s: float,
        *,
        plan_deviation_rel: float | None,
        trajectory_stable: bool,
        trajectory_viable: bool,
        risk_active: bool = False,
    ) -> GuidanceDecision:
        if self._mode is GuidanceMode.AUTO:
            return self.decision()

        if risk_active:
            if self._mode is not GuidanceMode.SAFETY_ONLY:
                self._safety_origin = self._mode
            self._mode = GuidanceMode.SAFETY_ONLY
            self._reason = "physical risk preempts guidance authority"
            return self.decision()

        if self._mode is GuidanceMode.SAFETY_ONLY and self._safety_origin is not None:
            origin = self._safety_origin
            if origin is GuidanceMode.PLAN:
                self._mode = GuidanceMode.PLAN
                self._safety_origin = None
                self._reason = "physical risk cleared; plan authority restored"
                return self.decision()
            if origin is GuidanceMode.OBSERVE_ACTION:
                self._mode = GuidanceMode.OBSERVE_ACTION
                self._safety_origin = None
                self._reason = "physical risk cleared; action response observation resumed"
                # Continue below: the original actuator deadline still applies.
            elif origin is GuidanceMode.ADAPTIVE:
                if trajectory_stable and trajectory_viable:
                    self._mode = GuidanceMode.ADAPTIVE
                    self._safety_origin = None
                    self._reason = "physical risk cleared; operator trajectory restored"
                return self.decision()

        if self._mode is GuidanceMode.OBSERVE_ACTION:
            if now_s < self._observing_until:
                return self.decision()
            if self._plan_return_ready(now_s, plan_deviation_rel):
                self._mode = GuidanceMode.PLAN
                self._reason = "operator action returned the roast to plan"
            elif plan_deviation_rel is not None and plan_deviation_rel <= self.p.plan_return_rel:
                self._reason = "confirming a durable return to the plan band"
            elif trajectory_stable and trajectory_viable:
                self._mode = GuidanceMode.ADAPTIVE
                self._reason = "stable viable operator trajectory"
            else:
                self._mode = GuidanceMode.SAFETY_ONLY
                self._reason = "operator trajectory is not reliable enough to steer"
            return self.decision()

        if self._mode in (GuidanceMode.ADAPTIVE, GuidanceMode.SAFETY_ONLY):
            if self._plan_return_ready(now_s, plan_deviation_rel):
                self._mode = GuidanceMode.PLAN
                self._reason = "roast durably returned to the plan band"
            elif self._mode is GuidanceMode.SAFETY_ONLY and trajectory_stable and trajectory_viable:
                self._mode = GuidanceMode.ADAPTIVE
                self._reason = "operator trajectory became stable and viable"
            elif self._mode is GuidanceMode.ADAPTIVE and not trajectory_viable:
                self._mode = GuidanceMode.SAFETY_ONLY
                self._safety_origin = None
                self._reason = "operator trajectory lost its viability"
        return self.decision()

    def _plan_return_ready(self, now_s: float, deviation: float | None) -> bool:
        if deviation is None or deviation > self.p.plan_return_rel:
            self._plan_return_since = None
            return False
        if self._plan_return_since is None:
            self._plan_return_since = now_s
        return now_s - self._plan_return_since >= self.p.plan_return_hold_s

    def decision(self) -> GuidanceDecision:
        return GuidanceDecision(
            mode=self._mode,
            directional_plan_advice=self._mode in (GuidanceMode.PLAN, GuidanceMode.AUTO),
            reason=self._reason,
        )

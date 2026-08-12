# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure, plan-independent physical risk signals for guided roasting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class RiskKind(Enum):
    STALL = 'stall'


@dataclass(frozen=True)
class RiskSignal:
    kind: RiskKind
    value: float
    threshold: float


@dataclass(frozen=True)
class RiskParams:
    confirm_s: float = 3.0
    severe_ratio: float = 0.5
    clear_ratio: float = 1.15
    clear_hold_s: float = 3.0


class GuidanceRiskEngine:
    """Evaluate absolute viability without selecting advice or authority."""

    def __init__(self, params: RiskParams | None = None) -> None:
        self.p = params or RiskParams()
        self.reset()

    def reset(self) -> None:
        self._below_since: float | None = None
        self._clear_since: float | None = None
        self._stall_active = False
        self._viability_established = False

    def evaluate(
        self, now_s: float, ror: float | None, viability_floor: float,
        *, active: bool = True, require_established: bool = False,
    ) -> tuple[RiskSignal, ...]:
        if not active or ror is None or not math.isfinite(float(ror)):
            self.reset()
            return ()
        value = float(ror)
        floor = max(0.0, float(viability_floor))
        if require_established and not self._viability_established:
            if value > floor * self.p.clear_ratio:
                self._viability_established = True
            return ()
        self._viability_established = True
        if self._stall_active:
            if value > floor * self.p.clear_ratio:
                if self._clear_since is None:
                    self._clear_since = now_s
                if now_s - self._clear_since >= self.p.clear_hold_s:
                    self.reset()
                    return ()
            else:
                self._clear_since = None
            return (RiskSignal(RiskKind.STALL, value, floor),)

        severe = value <= floor * self.p.severe_ratio
        if value <= floor:
            if self._below_since is None:
                self._below_since = now_s
            if severe or now_s - self._below_since >= self.p.confirm_s:
                self._stall_active = True
                self._clear_since = None
                return (RiskSignal(RiskKind.STALL, value, floor),)
        else:
            self._below_since = None
        return ()

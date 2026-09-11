# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Typed advice candidates and the single guidance-output selector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from tilauscope.guidance_core import GuidanceDecision, GuidanceMode


class AdviceCategory(IntEnum):
    INFORMATION = 10
    CONSEQUENCE = 20
    ACTION = 30
    WAIT = 40
    SAFETY = 50


class AdviceSeverity(IntEnum):
    INFO = 10
    WARNING = 20
    CRITICAL = 30


@dataclass(frozen=True)
class AdviceCandidate:
    key: str
    text: str
    category: AdviceCategory
    severity: AdviceSeverity = AdviceSeverity.INFO
    confidence: float = 1.0
    expires_at_s: float | None = None
    allowed_modes: frozenset[GuidanceMode] | None = None
    requires_plan_authority: bool = False


@dataclass(frozen=True)
class GuidanceOutput:
    candidate: AdviceCandidate | None
    silent_reason: str

    @property
    def text(self) -> str:
        return self.candidate.text if self.candidate is not None else ""


class AdviceSelector:
    """Select exactly one eligible candidate, or explicit silence."""

    def __init__(self, *, minimum_confidence: float = 0.35) -> None:
        self.minimum_confidence = minimum_confidence

    def select(
        self,
        candidates: list[AdviceCandidate],
        decision: GuidanceDecision,
        now_s: float,
        *,
        actions_observable: bool = True,
    ) -> GuidanceOutput:
        eligible: list[tuple[int, AdviceCandidate]] = []
        for position, candidate in enumerate(candidates):
            if not candidate.text or candidate.confidence < self.minimum_confidence:
                continue
            if candidate.expires_at_s is not None and now_s > candidate.expires_at_s:
                continue
            if candidate.allowed_modes is not None and decision.mode not in candidate.allowed_modes:
                continue
            if candidate.requires_plan_authority and not decision.directional_plan_advice:
                continue
            if candidate.category is AdviceCategory.ACTION and not actions_observable:
                continue
            eligible.append((position, candidate))
        if not eligible:
            return GuidanceOutput(None, "no eligible useful advice")
        _position, winner = max(
            eligible,
            key=lambda item: (
                int(item[1].category), int(item[1].severity),
                item[1].confidence, -item[0]),
        )
        return GuidanceOutput(winner, "")

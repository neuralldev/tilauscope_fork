# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.

"""Pure phase fallback for roasts whose milestones are not marked."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class GuidancePhase(IntEnum):
    DRYING = 0
    MAILLARD = 1
    DEVELOPMENT = 2


class PhaseSource(Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"


class PendingMilestone(Enum):
    DRY_END = "DE"
    FC_START = "FC"


@dataclass(frozen=True)
class PhaseResolution:
    phase: GuidancePhase
    inferred: bool
    reason: str


@dataclass(frozen=True)
class PhaseTransition:
    phase: GuidancePhase
    source: PhaseSource
    changed: bool
    confirmed: bool


class GuidancePhaseTracker:
    """Keep monotone phase authority and independent milestone provenance."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = GuidancePhase.DRYING
        self._observed = {GuidancePhase.DRYING}

    @property
    def source(self) -> PhaseSource:
        return (PhaseSource.OBSERVED if self.phase in self._observed
                else PhaseSource.INFERRED)

    @property
    def confirmed_phase(self) -> GuidancePhase:
        """Latest contiguous phase backed by actual roast milestones."""
        if GuidancePhase.MAILLARD not in self._observed:
            return GuidancePhase.DRYING
        if GuidancePhase.DEVELOPMENT not in self._observed:
            return GuidancePhase.MAILLARD
        return GuidancePhase.DEVELOPMENT

    @property
    def pending_milestone(self) -> PendingMilestone | None:
        """First event still required to confirm the inferred chronology."""
        if GuidancePhase.MAILLARD not in self._observed:
            return PendingMilestone.DRY_END
        if GuidancePhase.DEVELOPMENT not in self._observed:
            return PendingMilestone.FC_START
        return None

    def infer(self, phase: GuidancePhase) -> PhaseTransition:
        changed = phase > self.phase
        if changed:
            self.phase = phase
        return PhaseTransition(
            self.phase,
            self.source,
            changed,
            False,
        )

    def observe(self, phase: GuidancePhase) -> PhaseTransition:
        confirmed = phase not in self._observed
        self._observed.add(phase)
        changed = phase > self.phase
        if changed:
            self.phase = phase
        return PhaseTransition(
            self.phase,
            self.source,
            changed,
            confirmed,
        )


def resolve_phase_from_plan_temperature(
    current: GuidancePhase,
    bt: float,
    dry_end_bt: float | None,
    fc_start_bt: float | None,
    *,
    turning_point_seen: bool = True,
) -> PhaseResolution:
    """Advance a missing phase marker from plan BT, never move backwards."""
    if not turning_point_seen:
        return PhaseResolution(current, False, "waiting for the rising post-TP branch")
    phase = current
    if fc_start_bt is not None and fc_start_bt > 0 and bt >= fc_start_bt:
        phase = max(phase, GuidancePhase.DEVELOPMENT)
    elif dry_end_bt is not None and dry_end_bt > 0 and bt >= dry_end_bt:
        phase = max(phase, GuidancePhase.MAILLARD)
    if phase is current:
        return PhaseResolution(current, False, "current phase remains valid")
    return PhaseResolution(
        phase, True, "missing milestone inferred from plan temperature")

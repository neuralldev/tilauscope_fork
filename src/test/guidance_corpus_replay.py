# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""L2 replay utilities for the pure guided-roast decision session.

Recorded event streams contain both actuator changes and informational events.
Only concrete numeric lever changes are treated as operator actions here.  The
replay deliberately does not try to infer whether an old alarm emitted them;
that provenance is not persisted in legacy ``.alog`` files.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tilauscope.guidance_core import GuidanceMode
from tilauscope.guidance_observer import ActionSource, Lever, response_window_s
from tilauscope.guidance_phase import (
    GuidancePhase, GuidancePhaseTracker, resolve_phase_from_plan_temperature,
)
from tilauscope.guidance_replay import recorded_actions
from tilauscope.guidance_risk import RiskKind
from tilauscope.guidance_session import GuidanceSample, GuidanceSession


@dataclass(frozen=True)
class ReplayMetrics:
    profile: str
    samples: int
    actions: int
    automatic_actions: int
    manual_actions: int
    observed_manual_actions: int
    curve_only: bool
    inferred_phase_entries: int
    transitions: tuple[GuidanceMode, ...]
    observe_entries: int
    adaptive_entries: int
    safety_entries: int
    plan_returns: int
    mode_seconds: tuple[tuple[GuidanceMode, float], ...]
    stall_entries: int
    stall_seconds: float
    stall_samples: int
    stall_entries_by_phase: tuple[int, int, int]
    projection_count: int
    projection_mae_s: float | None
    confident_projection_mae_s: float | None


def corpus_summary(metrics: list[ReplayMetrics]) -> dict[str, Any]:
    """Compact deterministic digest used as the L2 calibration baseline."""
    mode_seconds = dict.fromkeys(GuidanceMode, 0.0)
    for item in metrics:
        for mode, seconds in item.mode_seconds:
            mode_seconds[mode] += seconds
    projections = sum(item.projection_count for item in metrics)
    weighted_error = sum(
        (item.projection_mae_s or 0.0) * item.projection_count for item in metrics)
    return {
        'profiles': len(metrics),
        'actions': sum(item.actions for item in metrics),
        'alarm_automation': sum(item.automatic_actions for item in metrics),
        'manual_actions': sum(item.manual_actions for item in metrics),
        'observed_manual_actions': sum(item.observed_manual_actions for item in metrics),
        'curve_only_profiles': sum(item.curve_only for item in metrics),
        'inferred_phase_entries': sum(item.inferred_phase_entries for item in metrics),
        'observe_entries': sum(item.observe_entries for item in metrics),
        'adaptive_entries': sum(item.adaptive_entries for item in metrics),
        'safety_entries': sum(item.safety_entries for item in metrics),
        'plan_returns': sum(item.plan_returns for item in metrics),
        'projection_count': projections,
        'projection_mae_s': round(weighted_error / projections, 3) if projections else None,
        'mode_seconds': {
            mode.value: round(mode_seconds[mode], 1) for mode in GuidanceMode
        },
        'stall_entries': sum(item.stall_entries for item in metrics),
        'stall_seconds': round(sum(item.stall_seconds for item in metrics), 1),
        'stall_samples': sum(item.stall_samples for item in metrics),
        'stall_entries_by_phase': [
            sum(item.stall_entries_by_phase[phase] for item in metrics)
            for phase in range(3)
        ],
    }

def replay_profile(
    model: Any, path: Path, *, apply_manual_actions: bool = True,
    controls_observable: bool = True,
) -> ReplayMetrics:
    """Replay one roast through ``GuidanceSession`` and collect stable metrics."""
    import corpus_harness as H

    profile = H.read_alog(path)
    relative_profile = path.relative_to(H.CORPUS_DIR).as_posix()
    ror, timex, bt, tp_idx, phases = model._get_delta_bt(relative_profile)
    actions = recorded_actions(profile)
    action_pos = 0
    session = GuidanceSession()
    session.set_actions_observable(controls_observable)
    transitions = [GuidanceMode.PLAN]
    mode_seconds = dict.fromkeys(GuidanceMode, 0.0)
    previous_sample_s: float | None = None
    stall_active = False
    stall_entries = 0
    stall_seconds = 0.0
    stall_samples = 0
    stall_entries_by_phase = [0, 0, 0]
    projection_errors: list[tuple[float, float]] = []
    phase_started_s = 0.0
    previous_phase = -1
    inferred_phase_entries = 0
    observed_manual_actions = 0
    phase_tracker = GuidancePhaseTracker()

    dry_s = float(phases['dry_end']) if phases.get('dry_end') else None
    fc_s = float(phases['fc_start']) if phases.get('fc_start') else None
    drop_s = float(phases.get('drop') or timex[-1])
    milestones = ((dry_s, 0.5), (fc_s, 3.0), (drop_s, 0.8))
    targets_bt = (160.0, 196.0, float(bt[-1]))
    for phase_idx, target_s in enumerate((dry_s, fc_s, drop_s)):
        if target_s is not None:
            target_idx = min(range(len(timex)), key=lambda n: abs(timex[n] - target_s))
            targets_bt = (*targets_bt[:phase_idx], float(bt[target_idx]),
                          *targets_bt[phase_idx + 1:])
    risk_phase_known = bool(dry_s and fc_s)
    for i, now_s in enumerate(timex):
        if i >= len(bt) or i >= len(ror) or not math.isfinite(float(ror[i])):
            continue
        if dry_s is not None and now_s >= dry_s:
            phase_tracker.observe(GuidancePhase.MAILLARD)
        if fc_s is not None and now_s >= fc_s:
            phase_tracker.observe(GuidancePhase.DEVELOPMENT)
        phase = int(phase_tracker.phase)
        fallback = resolve_phase_from_plan_temperature(
            GuidancePhase(phase), float(bt[i]),
            targets_bt[0] if dry_s is None else None,
            targets_bt[1] if fc_s is None and (phase >= 1 or dry_s is None) else None,
            turning_point_seen=i >= tp_idx)
        if fallback.inferred:
            transition = phase_tracker.infer(fallback.phase)
            phase = int(transition.phase)
            inferred_phase_entries += int(transition.changed)
        phase_changed = phase != previous_phase
        if phase_changed:
            if previous_phase >= 0:
                session.reset_phase()
            phase_started_s = float(now_s)
            previous_phase = phase
        if previous_sample_s is not None:
            elapsed = max(0.0, float(now_s) - previous_sample_s)
            mode_seconds[session.arbiter.mode] += elapsed
            if stall_active:
                stall_seconds += elapsed
        if phase_changed:
            stall_active = False
        previous_sample_s = float(now_s)
        operator_levers: list[Lever] = []
        while action_pos < len(actions) and actions[action_pos].at_s <= now_s:
            if (apply_manual_actions and controls_observable
                    and actions[action_pos].source is ActionSource.OPERATOR):
                lever = {0: Lever.AIR, 1: Lever.DRUM, 2: Lever.EXT,
                         3: Lever.HEATER}[actions[action_pos].lever]
                operator_levers.append(lever)
                observed_manual_actions += 1
            action_pos += 1
        if operator_levers:
            session.operator_action(float(now_s), response_window_s(
                operator_levers, session.arbiter.p.operator_lag_s))

        target_s, floor = milestones[phase]
        # A phase-local robust reference avoids pretending that legacy files
        # persisted the exact plan which was authoritative during recording.
        lo = max(0, i - 15)
        valid = [float(v) for v in ror[lo:i + 1] if math.isfinite(float(v)) and float(v) > 0]
        target_ror = sorted(valid)[len(valid) // 2] if valid else None
        state = session.tick(GuidanceSample(
            wall_s=float(now_s), roast_s=float(now_s), bt=float(bt[i]), ror=float(ror[i]),
            target_ror=target_ror, target_bt=targets_bt[phase],
            phase_started_s=phase_started_s, viability_floor=floor,
            # A phase floor has no physical meaning when the recording omitted
            # its Dry End or FC marker. Keep that roast for authority and ETA
            # calibration, but do not manufacture a phase-specific risk.
            viability_active=risk_phase_known and (phase != 0 or i >= tp_idx),
            viability_requires_established=(phase == 0),
            fc_started_s=fc_s if phase == 2 else None,
            authority_hold=(phase == 0 and (
                i < tp_idx or float(now_s) - float(timex[tp_idx]) < 45.0)),
        ))
        current_stall = any(risk.kind is RiskKind.STALL for risk in state.risks)
        if current_stall:
            stall_samples += 1
        if current_stall and not stall_active:
            stall_entries += 1
            stall_entries_by_phase[phase] += 1
        stall_active = current_stall
        if state.decision.mode is not transitions[-1]:
            transitions.append(state.decision.mode)
        if state.projection is not None and target_s is not None and target_s >= now_s:
            error = abs(state.projection.eta_s - (target_s - now_s))
            projection_errors.append((error, state.projection.confidence))

    errors = [error for error, _confidence in projection_errors]
    confident = [error for error, confidence in projection_errors if confidence >= 0.35]
    automatic_actions = sum(a.source is ActionSource.ALARM_AUTOMATION for a in actions)
    manual_actions = sum(a.source is ActionSource.OPERATOR for a in actions)
    return ReplayMetrics(
        profile=relative_profile, samples=len(timex), actions=len(actions),
        automatic_actions=automatic_actions, manual_actions=manual_actions,
        observed_manual_actions=observed_manual_actions,
        curve_only=not controls_observable,
        inferred_phase_entries=inferred_phase_entries,
        transitions=tuple(transitions), projection_count=len(errors),
        observe_entries=sum(mode is GuidanceMode.OBSERVE_ACTION for mode in transitions),
        adaptive_entries=sum(mode is GuidanceMode.ADAPTIVE for mode in transitions),
        safety_entries=sum(mode is GuidanceMode.SAFETY_ONLY for mode in transitions),
        plan_returns=max(0, sum(mode is GuidanceMode.PLAN for mode in transitions) - 1),
        mode_seconds=tuple((mode, round(seconds, 3))
                           for mode, seconds in mode_seconds.items()),
        stall_entries=stall_entries, stall_seconds=round(stall_seconds, 3),
        stall_samples=stall_samples,
        stall_entries_by_phase=tuple(stall_entries_by_phase),
        projection_mae_s=sum(errors) / len(errors) if errors else None,
        confident_projection_mae_s=(sum(confident) / len(confident) if confident else None),
    )

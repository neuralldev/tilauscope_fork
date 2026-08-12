"""Tests for plan-temperature phase fallback."""

from tilauscope.guidance_phase import (
    GuidancePhase,
    GuidancePhaseTracker,
    PendingMilestone,
    PhaseSource,
    resolve_phase_from_plan_temperature,
)


def test_plan_temperature_advances_missing_dry_end() -> None:
    result = resolve_phase_from_plan_temperature(
        GuidancePhase.DRYING, 161.0, 160.0, 196.0)

    assert result.phase is GuidancePhase.MAILLARD
    assert result.inferred


def test_plan_temperature_can_recover_both_missing_markers() -> None:
    result = resolve_phase_from_plan_temperature(
        GuidancePhase.DRYING, 198.0, 160.0, 196.0)

    assert result.phase is GuidancePhase.DEVELOPMENT
    assert result.inferred


def test_temperature_fallback_never_moves_phase_backwards() -> None:
    result = resolve_phase_from_plan_temperature(
        GuidancePhase.DEVELOPMENT, 150.0, 160.0, 196.0)

    assert result.phase is GuidancePhase.DEVELOPMENT
    assert not result.inferred


def test_missing_plan_temperatures_do_not_invent_a_phase() -> None:
    result = resolve_phase_from_plan_temperature(
        GuidancePhase.DRYING, 200.0, None, None)

    assert result.phase is GuidancePhase.DRYING
    assert not result.inferred


def test_hot_charge_reading_is_not_a_phase_crossing_before_tp() -> None:
    result = resolve_phase_from_plan_temperature(
        GuidancePhase.DRYING, 205.0, 160.0, 196.0,
        turning_point_seen=False)

    assert result.phase is GuidancePhase.DRYING
    assert not result.inferred


def test_late_observed_marker_confirms_without_moving_backwards() -> None:
    tracker = GuidancePhaseTracker()
    inferred = tracker.infer(GuidancePhase.DEVELOPMENT)

    confirmed = tracker.observe(GuidancePhase.MAILLARD)

    assert inferred.source is PhaseSource.INFERRED
    assert tracker.source is PhaseSource.INFERRED
    assert confirmed.phase is GuidancePhase.DEVELOPMENT
    assert confirmed.source is PhaseSource.INFERRED
    assert confirmed.confirmed
    assert not confirmed.changed


def test_observed_current_phase_replaces_inferred_source_once() -> None:
    tracker = GuidancePhaseTracker()
    tracker.infer(GuidancePhase.MAILLARD)

    first = tracker.observe(GuidancePhase.MAILLARD)
    duplicate = tracker.observe(GuidancePhase.MAILLARD)

    assert first.source is PhaseSource.OBSERVED
    assert tracker.source is PhaseSource.OBSERVED
    assert first.confirmed
    assert not duplicate.confirmed


def test_inference_does_not_consume_missing_milestones() -> None:
    tracker = GuidancePhaseTracker()

    tracker.infer(GuidancePhase.DEVELOPMENT)

    assert tracker.confirmed_phase is GuidancePhase.DRYING
    assert tracker.pending_milestone is PendingMilestone.DRY_END


def test_late_markers_advance_confirmation_in_event_order() -> None:
    tracker = GuidancePhaseTracker()
    tracker.infer(GuidancePhase.DEVELOPMENT)

    tracker.observe(GuidancePhase.MAILLARD)
    assert tracker.confirmed_phase is GuidancePhase.MAILLARD
    assert tracker.pending_milestone is PendingMilestone.FC_START

    tracker.observe(GuidancePhase.DEVELOPMENT)
    assert tracker.confirmed_phase is GuidancePhase.DEVELOPMENT
    assert tracker.pending_milestone is None


def test_fc_alone_cannot_skip_missing_dry_end_confirmation() -> None:
    tracker = GuidancePhaseTracker()
    tracker.infer(GuidancePhase.DEVELOPMENT)

    tracker.observe(GuidancePhase.DEVELOPMENT)

    assert tracker.confirmed_phase is GuidancePhase.DRYING
    assert tracker.pending_milestone is PendingMilestone.DRY_END

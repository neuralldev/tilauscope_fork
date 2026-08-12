"""Tests for typed guidance candidate selection."""

from tilauscope.guidance_advice import (
    AdviceCandidate,
    AdviceCategory,
    AdviceSelector,
    AdviceSeverity,
)
from tilauscope.guidance_core import GuidanceDecision, GuidanceMode


def decision(mode: GuidanceMode, plan: bool = False) -> GuidanceDecision:
    return GuidanceDecision(mode, plan, "test")


def test_safety_outranks_wait_and_consequence() -> None:
    selector = AdviceSelector()
    candidates = [
        AdviceCandidate("projection", "FC in 1:20", AdviceCategory.CONSEQUENCE),
        AdviceCandidate("wait", "observe", AdviceCategory.WAIT),
        AdviceCandidate("crash", "support now", AdviceCategory.SAFETY,
                        AdviceSeverity.CRITICAL),
    ]
    assert selector.select(candidates, decision(GuidanceMode.ADAPTIVE), 10.0).text == "support now"


def test_global_safety_outranks_response_wait() -> None:
    candidates = [
        AdviceCandidate("stall", "stall risk", AdviceCategory.SAFETY,
                        AdviceSeverity.CRITICAL),
        AdviceCandidate("wait", "observe response", AdviceCategory.WAIT,
                        allowed_modes=frozenset({GuidanceMode.OBSERVE_ACTION})),
    ]

    output = AdviceSelector().select(
        candidates, decision(GuidanceMode.OBSERVE_ACTION), 10.0)

    assert output.text == "stall risk"


def test_plan_action_is_ineligible_without_plan_authority() -> None:
    candidate = AdviceCandidate(
        "return", "burner toward plan", AdviceCategory.ACTION,
        requires_plan_authority=True)
    output = AdviceSelector().select([candidate], decision(GuidanceMode.ADAPTIVE), 0.0)
    assert not output.text
    assert output.silent_reason


def test_mode_and_expiry_are_enforced() -> None:
    candidate = AdviceCandidate(
        "wait", "observe", AdviceCategory.WAIT, expires_at_s=5.0,
        allowed_modes=frozenset({GuidanceMode.OBSERVE_ACTION}))
    selector = AdviceSelector()
    assert selector.select([candidate], decision(GuidanceMode.PLAN, True), 2.0).text == ""
    assert selector.select([candidate], decision(GuidanceMode.OBSERVE_ACTION), 6.0).text == ""


def test_low_confidence_projection_results_in_explicit_silence() -> None:
    candidate = AdviceCandidate(
        "projection", "uncertain projection", AdviceCategory.CONSEQUENCE,
        confidence=0.2)
    output = AdviceSelector().select([candidate], decision(GuidanceMode.ADAPTIVE), 0.0)
    assert output.candidate is None
    assert output.silent_reason == "no eligible useful advice"


def test_equal_priority_keeps_first_candidate_stable() -> None:
    candidates = [
        AdviceCandidate("first", "first", AdviceCategory.INFORMATION),
        AdviceCandidate("second", "second", AdviceCategory.INFORMATION),
    ]
    output = AdviceSelector().select(candidates, decision(GuidanceMode.PLAN, True), 0.0)
    assert output.text == "first"


def test_curve_only_rejects_actions_but_keeps_curve_commentary() -> None:
    candidates = [
        AdviceCandidate("action", "raise heater", AdviceCategory.ACTION),
        AdviceCandidate("curve", "RoR is declining", AdviceCategory.CONSEQUENCE),
    ]

    output = AdviceSelector().select(
        candidates, decision(GuidanceMode.PLAN, True), 0.0,
        actions_observable=False)

    assert output.text == "RoR is declining"


def test_curve_only_never_filters_safety() -> None:
    candidate = AdviceCandidate(
        "stall", "stall detected", AdviceCategory.SAFETY,
        AdviceSeverity.CRITICAL)

    output = AdviceSelector().select(
        [candidate], decision(GuidanceMode.PLAN, True), 0.0,
        actions_observable=False)

    assert output.text == "stall detected"

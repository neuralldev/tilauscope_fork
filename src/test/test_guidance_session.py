"""End-to-end scenarios for the pure guided-roast session engine."""

from dataclasses import replace

from tilauscope.guidance_advice import AdviceCandidate, AdviceCategory
from tilauscope.guidance_core import GuidanceMode, GuidanceParams
from tilauscope.guidance_observer import ObservationParams
from tilauscope.guidance_risk import RiskKind
from tilauscope.guidance_risk import RiskParams
from tilauscope.guidance_session import GuidanceSample, GuidanceSession
from tilauscope.guidance_trajectory import ProjectionParams


def session() -> GuidanceSession:
    return GuidanceSession(
        guidance_params=GuidanceParams(
            operator_lag_s=5.0, plan_return_rel=0.15, plan_return_hold_s=5.0),
        observation_params=ObservationParams(
            stability_window_s=4.0, stability_hold_s=1.0, min_points=4),
        projection_params=ProjectionParams(
            window_s=8.0, min_span_s=4.0, min_points=4, max_eta_s=300.0),
    )


def sample(at: float, ror: float, *, target_ror: float = 8.0) -> GuidanceSample:
    return GuidanceSample(
        wall_s=at, roast_s=at, bt=170.0 + at * ror / 60.0, ror=ror,
        target_ror=target_ror, target_bt=185.0, phase_started_s=0.0,
        viability_floor=3.0)


def test_manual_departure_waits_then_becomes_adaptive_with_projection() -> None:
    guided = session()
    for second in range(7):
        guided.tick(sample(float(second), 8.0))
    guided.operator_action(7.0)
    for second in range(8, 12):
        assert guided.tick(sample(float(second), 11.0)).decision.mode is GuidanceMode.OBSERVE_ACTION
    state = guided.tick(sample(12.0, 11.0))
    assert state.decision.mode is GuidanceMode.ADAPTIVE
    assert state.projection is not None


def test_adaptive_trajectory_losing_viability_enters_safety_only() -> None:
    guided = session()
    for second in range(7):
        guided.tick(sample(float(second), 10.0))
    guided.operator_action(7.0)
    for second in range(8, 14):
        state = guided.tick(sample(float(second), 10.0))
    assert state.decision.mode is GuidanceMode.ADAPTIVE
    state = guided.tick(sample(14.0, 2.0))
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY


def test_return_to_plan_requires_continuous_hold() -> None:
    guided = session()
    for second in range(7):
        guided.tick(sample(float(second), 10.0))
    guided.operator_action(7.0)
    for second in range(8, 14):
        guided.tick(sample(float(second), 10.0))
    assert guided.arbiter.mode is GuidanceMode.ADAPTIVE
    for second in range(14, 19):
        assert guided.tick(sample(float(second), 8.0)).decision.mode is GuidanceMode.ADAPTIVE
    assert guided.tick(sample(19.0, 8.0)).decision.mode is GuidanceMode.PLAN


def test_auto_contract_ignores_manual_adaptation_until_released() -> None:
    guided = session()
    assert guided.set_auto(True).mode is GuidanceMode.AUTO
    for second in range(10):
        assert guided.tick(sample(float(second), 2.0)).decision.mode is GuidanceMode.AUTO
    assert guided.set_auto(False).mode is GuidanceMode.PLAN


def test_phase_reset_keeps_authority_but_discards_old_projection_history() -> None:
    guided = session()
    for second in range(8):
        guided.tick(sample(float(second), 10.0))
    guided.operator_action(8.0, lag_s=0.0)
    guided.tick(sample(9.0, 10.0))
    mode = guided.arbiter.mode
    guided.reset_phase()
    state = guided.tick(sample(10.0, 10.0))
    assert state.decision.mode is mode
    assert state.projection is None


def test_stall_risk_remains_visible_during_action_response_wait() -> None:
    guided = session()
    guided.operator_action(0.0, lag_s=30.0)

    state = guided.tick(sample(5.0, 1.0))

    assert state.decision.mode is GuidanceMode.SAFETY_ONLY
    assert state.risks[0].kind is RiskKind.STALL


def test_stable_but_unprojectable_trajectory_does_not_become_adaptive() -> None:
    guided = session()
    guided.operator_action(0.0, lag_s=0.0)
    for second in range(1, 8):
        current = replace(
            sample(float(second), 8.0, target_ror=4.0), target_bt=None)
        state = guided.tick(current)

    assert state.observation.stable
    assert state.projection is None
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY


def test_active_stall_hysteresis_vetoes_adaptive_authority() -> None:
    guided = GuidanceSession(
        guidance_params=GuidanceParams(operator_lag_s=0.0),
        observation_params=ObservationParams(
            stability_window_s=1.0, stability_hold_s=0.0, min_points=2,
            spread_abs=100.0),
        projection_params=ProjectionParams(
            window_s=4.0, min_span_s=1.0, min_points=2, max_eta_s=300.0),
        risk_params=RiskParams(confirm_s=0.0, clear_hold_s=2.0),
        minimum_advice_confidence=0.2,
    )
    guided.operator_action(0.0, lag_s=0.0)
    guided.tick(sample(0.0, 1.0))
    state = guided.tick(sample(1.0, 1.0))
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY

    # RoR is viable again, but the active risk has not cleared its hold.
    state = guided.tick(sample(2.0, 4.0))
    assert state.risks
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY
    state = guided.tick(sample(3.0, 4.0))
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY
    state = guided.tick(sample(4.0, 4.0))
    assert not state.risks
    assert state.decision.mode is GuidanceMode.ADAPTIVE


def test_curve_only_session_filters_action_candidates() -> None:
    guided = session()
    guided.set_actions_observable(False)

    output = guided.select([
        AdviceCandidate("action", "raise heater", AdviceCategory.ACTION),
        AdviceCandidate("curve", "trajectory projects late", AdviceCategory.CONSEQUENCE),
    ], 0.0)

    assert output.text == "trajectory projects late"


def test_curve_only_session_cannot_enter_operator_observation() -> None:
    guided = session()
    guided.set_actions_observable(False)

    decision = guided.operator_action(10.0)

    assert decision.mode is GuidanceMode.PLAN


def test_stabilization_hold_defers_non_physical_authority_judgement() -> None:
    guided = session()
    guided.operator_action(0.0, lag_s=0.0)

    state = guided.tick(replace(sample(10.0, 8.0), authority_hold=True))

    assert not state.risks
    assert state.decision.mode is GuidanceMode.OBSERVE_ACTION


def test_stabilization_hold_never_masks_physical_risk() -> None:
    guided = session()
    guided.operator_action(0.0, lag_s=30.0)

    state = guided.tick(replace(sample(1.0, 1.0), authority_hold=True))

    assert state.risks
    assert state.decision.mode is GuidanceMode.SAFETY_ONLY

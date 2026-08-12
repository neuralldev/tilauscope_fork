"""Pure tests for the guided-roast authority state machine."""

from tilauscope.guidance_core import GuidanceArbiter, GuidanceMode, GuidanceParams


def arbiter() -> GuidanceArbiter:
    return GuidanceArbiter(GuidanceParams(
        operator_lag_s=30.0, plan_return_rel=0.15, plan_return_hold_s=10.0))


def test_operator_action_suspends_plan_directional_advice() -> None:
    a = arbiter()
    decision = a.operator_action(100.0)
    assert decision.mode is GuidanceMode.OBSERVE_ACTION
    assert not decision.directional_plan_advice
    decision = a.tick(129.0, plan_deviation_rel=0.40,
                      trajectory_stable=True, trajectory_viable=True)
    assert decision.mode is GuidanceMode.OBSERVE_ACTION


def test_fast_followup_cannot_shorten_pending_slow_response() -> None:
    arbiter = GuidanceArbiter()
    arbiter.operator_action(0.0, lag_s=55.0)   # heater
    arbiter.operator_action(5.0, lag_s=12.0)   # air

    assert arbiter.tick(
        20.0, plan_deviation_rel=0.5,
        trajectory_stable=True, trajectory_viable=True,
    ).mode is GuidanceMode.OBSERVE_ACTION
    assert arbiter.tick(
        55.0, plan_deviation_rel=0.5,
        trajectory_stable=True, trajectory_viable=True,
    ).mode is GuidanceMode.ADAPTIVE


def test_slow_followup_extends_pending_fast_response() -> None:
    arbiter = GuidanceArbiter()
    arbiter.operator_action(0.0, lag_s=12.0)   # air
    arbiter.operator_action(5.0, lag_s=55.0)   # heater

    assert arbiter.tick(
        20.0, plan_deviation_rel=0.5,
        trajectory_stable=True, trajectory_viable=True,
    ).mode is GuidanceMode.OBSERVE_ACTION
    assert arbiter.tick(
        60.0, plan_deviation_rel=0.5,
        trajectory_stable=True, trajectory_viable=True,
    ).mode is GuidanceMode.ADAPTIVE


def test_physical_risk_preempts_plan_then_restores_it() -> None:
    arbiter = GuidanceArbiter()

    assert arbiter.tick(
        10.0, plan_deviation_rel=0.0,
        trajectory_stable=False, trajectory_viable=False, risk_active=True,
    ).mode is GuidanceMode.SAFETY_ONLY
    assert arbiter.tick(
        11.0, plan_deviation_rel=0.0,
        trajectory_stable=True, trajectory_viable=True, risk_active=False,
    ).mode is GuidanceMode.PLAN


def test_risk_during_response_wait_restores_pending_deadline() -> None:
    arbiter = GuidanceArbiter()
    arbiter.operator_action(0.0, lag_s=30.0)
    assert arbiter.tick(
        5.0, plan_deviation_rel=0.5,
        trajectory_stable=False, trajectory_viable=False, risk_active=True,
    ).mode is GuidanceMode.SAFETY_ONLY
    assert arbiter.tick(
        10.0, plan_deviation_rel=0.5,
        trajectory_stable=True, trajectory_viable=True, risk_active=False,
    ).mode is GuidanceMode.OBSERVE_ACTION

def test_viable_persistent_departure_becomes_adaptive() -> None:
    a = arbiter()
    a.operator_action(100.0)
    decision = a.tick(130.0, plan_deviation_rel=0.40,
                      trajectory_stable=True, trajectory_viable=True)
    assert decision.mode is GuidanceMode.ADAPTIVE
    assert not decision.directional_plan_advice


def test_uncertain_departure_becomes_safety_only() -> None:
    a = arbiter()
    a.operator_action(100.0)
    decision = a.tick(130.0, plan_deviation_rel=0.40,
                      trajectory_stable=False, trajectory_viable=True)
    assert decision.mode is GuidanceMode.SAFETY_ONLY
    assert not decision.directional_plan_advice


def test_action_that_recovers_plan_restores_plan_authority() -> None:
    a = arbiter()
    a.operator_action(100.0)
    decision = a.tick(130.0, plan_deviation_rel=0.10,
                      trajectory_stable=True, trajectory_viable=True)
    assert decision.mode is GuidanceMode.OBSERVE_ACTION
    decision = a.tick(140.0, plan_deviation_rel=0.10,
                      trajectory_stable=True, trajectory_viable=True)
    assert decision.mode is GuidanceMode.PLAN
    assert decision.directional_plan_advice


def test_a_single_in_band_sample_does_not_reclaim_plan_authority() -> None:
    a = arbiter()
    a.operator_action(100.0)
    a.tick(130.0, plan_deviation_rel=0.40,
           trajectory_stable=True, trajectory_viable=True)
    assert a.mode is GuidanceMode.ADAPTIVE
    assert a.tick(131.0, plan_deviation_rel=0.10,
                  trajectory_stable=True, trajectory_viable=True).mode is GuidanceMode.ADAPTIVE
    assert a.tick(132.0, plan_deviation_rel=0.40,
                  trajectory_stable=True, trajectory_viable=True).mode is GuidanceMode.ADAPTIVE


def test_auto_is_an_explicit_plan_contract() -> None:
    a = arbiter()
    assert a.set_auto(True).mode is GuidanceMode.AUTO
    decision = a.tick(999.0, plan_deviation_rel=0.80,
                      trajectory_stable=False, trajectory_viable=False)
    assert decision.mode is GuidanceMode.AUTO
    assert decision.directional_plan_advice

    assert a.set_auto(False).mode is GuidanceMode.PLAN

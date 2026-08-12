from tilauscope.guidance_risk import GuidanceRiskEngine, RiskKind, RiskParams


def test_viability_floor_emits_stall_at_or_below_threshold() -> None:
    engine = GuidanceRiskEngine(RiskParams(confirm_s=2.0))

    assert engine.evaluate(0.0, 3.1, 3.0) == ()
    assert engine.evaluate(1.0, 3.0, 3.0) == ()
    risk = engine.evaluate(3.0, 3.0, 3.0)[0]
    assert risk.kind is RiskKind.STALL
    assert (risk.value, risk.threshold) == (3.0, 3.0)


def test_missing_ror_does_not_invent_a_physical_risk() -> None:
    assert GuidanceRiskEngine().evaluate(0.0, None, 3.0) == ()


def test_pre_turning_point_disables_stall_evaluation() -> None:
    assert GuidanceRiskEngine().evaluate(0.0, -8.0, 0.5, active=False) == ()


def test_post_tp_recovery_must_establish_viability_before_stall_guard_arms() -> None:
    engine = GuidanceRiskEngine(RiskParams(confirm_s=1.0))

    assert engine.evaluate(0.0, 0.1, 0.5, require_established=True) == ()
    assert engine.evaluate(2.0, 0.6, 0.5, require_established=True) == ()
    assert engine.evaluate(3.0, 0.4, 0.5, require_established=True) == ()
    assert engine.evaluate(4.0, 0.4, 0.5, require_established=True)[0].kind is RiskKind.STALL


def test_severe_stall_is_immediate_and_clearance_has_hysteresis() -> None:
    engine = GuidanceRiskEngine(RiskParams(clear_hold_s=2.0))

    assert engine.evaluate(0.0, 1.0, 3.0)[0].kind is RiskKind.STALL
    assert engine.evaluate(1.0, 3.2, 3.0)  # not enough recovery margin
    assert engine.evaluate(2.0, 3.6, 3.0)  # clear hold starts
    assert engine.evaluate(3.0, 3.6, 3.0)  # still held
    assert engine.evaluate(4.0, 3.6, 3.0) == ()

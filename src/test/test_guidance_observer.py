"""Pure tests for live trajectory observation and lever provenance."""

from tilauscope.guidance_observer import (
    ActionProvenanceTracker,
    ActionSource,
    Lever,
    LiveTrajectoryObserver,
    ObservationParams,
    ResponseLagParams,
    controls_observable,
    observable_control_levers,
    response_lag_s,
    response_window_s,
)


def test_disabled_slider_configuration_is_curve_only() -> None:
    assert not controls_observable([0, 0, 0, 0])
    assert controls_observable([0, 0, 0, 1])


def test_observable_levers_intersect_machine_and_configuration() -> None:
    levers = observable_control_levers(
        [1, 1, 1, 1], has_airflow_control=False,
        drum_variable_speed=True, has_heater_control=True)

    assert levers == frozenset({Lever.DRUM, Lever.HEATER})
    assert not observable_control_levers(
        [0, 0, 0, 0], has_airflow_control=True,
        drum_variable_speed=True, has_heater_control=True)


def test_response_lag_is_specific_to_the_changed_lever() -> None:
    params = ResponseLagParams(air_s=10.0, drum_s=20.0, ext_s=8.0)

    assert response_lag_s(Lever.AIR, 55.0, params) == 10.0
    assert response_lag_s(Lever.DRUM, 55.0, params) == 20.0
    assert response_lag_s(Lever.EXT, 55.0, params) == 8.0
    assert response_lag_s(Lever.HEATER, 55.0, params) == 55.0


def test_action_batch_uses_slowest_response_independent_of_order() -> None:
    params = ResponseLagParams(air_s=10.0, drum_s=20.0, ext_s=8.0)

    assert response_window_s([Lever.AIR, Lever.HEATER], 55.0, params) == 55.0
    assert response_window_s([Lever.HEATER, Lever.AIR], 55.0, params) == 55.0
    assert response_window_s([Lever.EXT, Lever.DRUM], 55.0, params) == 20.0


def test_expected_auto_echo_is_not_classified_as_operator() -> None:
    tracker = ActionProvenanceTracker()
    tracker.observe({Lever.HEATER: 70.0}, 0.0)
    tracker.expect(Lever.HEATER, 65.0, ActionSource.AUTO, 1.0)
    actions = tracker.observe({Lever.HEATER: 65.0}, 2.0)
    assert len(actions) == 1
    assert actions[0].source is ActionSource.AUTO


def test_unexplained_change_is_operator_action() -> None:
    tracker = ActionProvenanceTracker()
    tracker.observe({Lever.AIR: 30.0}, 0.0)
    actions = tracker.observe({Lever.AIR: 35.0}, 1.0)
    assert actions[0].source is ActionSource.OPERATOR


def test_expired_expectation_does_not_hide_operator_action() -> None:
    tracker = ActionProvenanceTracker()
    tracker.observe({Lever.HEATER: 70.0}, 0.0)
    tracker.expect(Lever.HEATER, 60.0, ActionSource.PLAN_AUTOMATION, 1.0, ttl_s=2.0)
    actions = tracker.observe({Lever.HEATER: 60.0}, 4.0)
    assert actions[0].source is ActionSource.OPERATOR


def test_alarm_expectation_does_not_become_operator_takeover() -> None:
    tracker = ActionProvenanceTracker()
    tracker.observe({Lever.HEATER: 70.0}, 0.0)
    tracker.expect(Lever.HEATER, 60.0, ActionSource.ALARM_AUTOMATION, 10.0)

    actions = tracker.observe({Lever.HEATER: 60.0}, 10.1)

    assert len(actions) == 1
    assert actions[0].source is ActionSource.ALARM_AUTOMATION


def test_stability_requires_a_time_window_and_hold() -> None:
    observer = LiveTrajectoryObserver(ObservationParams(
        stability_window_s=8.0, stability_hold_s=4.0, min_points=5))
    result = None
    for second in range(13):
        result = observer.update(float(second), 8.0 + (0.1 if second % 2 else 0.0),
                                 viability_floor=3.0)
    assert result is not None
    assert result.stable
    assert result.viable


def test_unstable_or_low_ror_is_not_a_viable_stable_trajectory() -> None:
    observer = LiveTrajectoryObserver(ObservationParams(
        stability_window_s=4.0, stability_hold_s=0.0, min_points=4))
    result = None
    for second, ror in enumerate((8.0, 3.0, 9.0, 2.0, 8.0)):
        result = observer.update(float(second), ror, viability_floor=3.0)
    assert result is not None
    assert not result.stable

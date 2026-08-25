"""°F is convert(°C), never a second set of numbers.

Every threshold TilauScope owns is stated in °C. The engines are fed values in
the unit Artisan displays, so each of these paths has to scale or convert at
the point of comparison. A °F operator must get the SAME physical behaviour —
these tests pin that, one path per test.
"""

import math

from artisanlib.util import convertTemp, fromCtoFstrict

from tilauscope.guidance_observer import LiveTrajectoryObserver, ObservationParams
from tilauscope.guidance_trajectory import OperatorTrajectoryProjector, ProjectionParams

F_SCALE = 1.8

# The graph package pulls in Qt widget modules. Every test here imports it from
# inside the test, the way the rest of the suite does: importing it at collection
# time builds that state before the QApplication fixture exists, and the curve's
# own tests then read a different world than the one they set up.


def test_a_gap_scales_and_never_takes_the_freezing_offset() -> None:
    from tilauscope.graph.common import delta_scale
    # A DIFFERENCE of 5 °C is 9 °F. 32 is the offset and belongs to absolutes.
    assert delta_scale('C') == 1.0
    assert 5.0 * delta_scale('F') == 9.0


def test_share_bands_are_the_same_physical_band_in_both_units() -> None:
    from tilauscope.graph.common import within_share
    # 5 % of a 200 °C target is 10 °C. Read in °F the target is 392 and the band
    # must still be 10 °C — 18 °F — not 5 % of 392.
    assert within_share(10.0, 200.0, 0.05, 'C')
    assert not within_share(10.5, 200.0, 0.05, 'C')

    target_f = fromCtoFstrict(200.0)
    assert within_share(10.0 * F_SCALE, target_f, 0.05, 'F')
    assert not within_share(10.5 * F_SCALE, target_f, 0.05, 'F')


def test_share_band_rejects_a_meaningless_target() -> None:
    from tilauscope.graph.common import within_share
    assert not within_share(1.0, 0.0, 0.05, 'C')
    assert not within_share(1.0, -5.0, 0.05, 'F')


def _ticks(mode: str) -> list[int]:
    from tilauscope.graph.curve import _temp_axis_c
    lo, hi, step = _temp_axis_c(mode)
    out: list[int] = []
    value = lo
    while value <= hi + 1e-6:
        out.append(round(convertTemp(value, 'C', mode)))
        value += step
    return out


def test_the_chart_axis_is_labelled_in_round_figures_of_the_operators_unit() -> None:
    # An axis is read, not computed: 104 · 176 · 248 is not reading Fahrenheit.
    assert _ticks('C') == [40, 80, 120, 160, 200, 240]
    assert _ticks('F') == [100, 160, 220, 280, 340, 400, 460]


def test_both_axes_frame_the_same_physical_window() -> None:
    from tilauscope.graph.curve import _ror_axis_c, _temp_axis_c
    lo_c, hi_c, _step = _temp_axis_c('C')
    lo_f, hi_f, _step_f = _temp_axis_c('F')
    assert math.isclose(lo_c, lo_f, abs_tol=3.0)
    assert math.isclose(hi_c, hi_f, abs_tol=3.0)

    top_c, step_c = _ror_axis_c('C')
    top_f, step_f = _ror_axis_c('F')
    assert math.isclose(top_c, 24.0)
    assert math.isclose(top_f, 25.0)
    assert math.isclose(step_f * F_SCALE, 15.0)
    assert math.isclose(step_c, 8.0)


def _feed(observer: LiveTrajectoryObserver, values: list[float], scale: float) -> bool:
    at = 0.0
    result = None
    for value in values:
        result = observer.update(at, value, viability_floor=0.5 * scale,
                                 ror_scale=scale)
        at += 1.0
    assert result is not None
    return result.stable


def test_rate_stability_is_judged_on_the_same_spread_in_both_units() -> None:
    params = ObservationParams(stability_window_s=12.0, stability_hold_s=4.0,
                               min_points=5, spread_abs=2.0, spread_rel=0.25)
    # A 1.8 °C/min spread around 5.5 °C/min sits inside the absolute band (the
    # relative one is narrower here, so the absolute is what decides). The same
    # curve read in °F spreads 3.24 °F/min: unscaled, the °F operator would be
    # told the rate is unstable while the °C operator is told it is settled.
    celsius = [5.0, 5.5, 6.4, 5.2, 4.6, 5.4, 6.4, 5.1, 5.3, 5.6, 4.6, 5.5,
               5.2, 4.6, 5.7, 6.4, 5.1, 5.4, 4.6, 6.4]
    assert _feed(LiveTrajectoryObserver(params), celsius, 1.0)
    fahrenheit = [v * F_SCALE for v in celsius]
    assert _feed(LiveTrajectoryObserver(params), fahrenheit, F_SCALE)


def _projection(scale: float) -> object:
    params = ProjectionParams(window_s=60.0, min_span_s=15.0, min_points=8,
                              max_sample_age_s=5.0, min_ror=0.5)
    projector = OperatorTrajectoryProjector(params)
    bt_c, at = 150.0, 0.0
    for _ in range(20):
        ror_c = 6.0
        bt = bt_c if scale == 1.0 else fromCtoFstrict(bt_c)
        projector.update(at, bt, ror_c * scale)
        bt_c += ror_c / 60.0
        at += 1.0
    target = 160.0 if scale == 1.0 else fromCtoFstrict(160.0)
    return projector.project(now_s=at - 1.0, target_bt=target,
                             phase_started_s=0.0, ror_scale=scale)


def test_a_milestone_projection_lands_at_the_same_moment_in_both_units() -> None:
    in_c = _projection(1.0)
    in_f = _projection(F_SCALE)
    assert in_c is not None and in_f is not None
    assert math.isclose(in_c.eta_s, in_f.eta_s, rel_tol=0.02)

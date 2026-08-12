"""Tests for local operator-trajectory consequence projection."""

import pytest

from tilauscope.guidance_trajectory import OperatorTrajectoryProjector, ProjectionParams


def projector() -> OperatorTrajectoryProjector:
    return OperatorTrajectoryProjector(ProjectionParams(
        window_s=30.0, min_span_s=10.0, min_points=6, max_eta_s=300.0))


def feed(
    p: OperatorTrajectoryProjector,
    *,
    ror_start: float,
    slope: float = 0.0,
    start_s: float = 0.0,
) -> None:
    bt = 170.0
    for second in range(0, 31, 2):
        minute = second / 60.0
        ror = ror_start + slope * minute
        p.update(start_s + float(second), bt, ror)
        bt += ror / 30.0


def test_constant_ror_projects_milestone_and_phase_duration() -> None:
    p = projector()
    feed(p, ror_start=10.0)
    projection = p.project(now_s=30.0, target_bt=180.0, phase_started_s=0.0)
    assert projection is not None
    assert projection.eta_s == pytest.approx(30.0, abs=2.0)
    assert projection.terminal_ror == pytest.approx(10.0)
    assert projection.projected_phase_duration_s == pytest.approx(60.0, abs=2.0)


def test_declining_ror_uses_integrated_slope() -> None:
    p = projector()
    feed(p, ror_start=12.0, slope=-4.0)
    projection = p.project(now_s=30.0, target_bt=180.0, phase_started_s=0.0)
    assert projection is not None
    assert projection.ror_slope_per_min == pytest.approx(-4.0)
    assert projection.terminal_ror < 10.0


def test_development_projection_includes_final_dtr() -> None:
    p = projector()
    feed(p, ror_start=10.0, start_s=270.0)
    projection = p.project(
        now_s=300.0, target_bt=180.0, phase_started_s=240.0, fc_started_s=240.0)
    assert projection is not None
    assert projection.projected_dtr == pytest.approx(27.3, abs=0.5)


def test_insufficient_history_has_no_projection() -> None:
    p = projector()
    p.update(0.0, 170.0, 10.0)
    assert p.project(now_s=0.0, target_bt=180.0, phase_started_s=0.0) is None


def test_trajectory_that_stalls_before_target_is_rejected() -> None:
    p = projector()
    feed(p, ror_start=5.0, slope=-10.0)
    assert p.project(now_s=30.0, target_bt=190.0, phase_started_s=0.0) is None

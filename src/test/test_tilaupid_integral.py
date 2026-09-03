"""Slow hold-integral behaviour for the Tilau preheat controller."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from tilauscope.tilaupid import PIDConfig, SlowHoldIntegrator, TilauPreheatPID


def _step(
    integral: SlowHoldIntegrator,
    *,
    now: float,
    error: float = 1.0,
    ror: float = 0.0,
    base: float = 40.0,
    ceiling: float = 80.0,
) -> float:
    return integral.update(
        error_c=error,
        ror_c_per_min=ror,
        base_output_pct=base,
        output_max_pct=ceiling,
        now=now,
    )


def test_integral_stays_off_during_ramp_and_approach() -> None:
    integral = SlowHoldIntegrator(ki_pct_per_c_sec=1.0, arm_sec=0.0)

    assert _step(integral, now=0.0, error=10.0, ror=8.0) == 0.0
    assert _step(integral, now=1.0, error=1.0, ror=2.0) == 0.0
    assert _step(integral, now=2.0, error=1.0, ror=0.0) == 0.0


def test_integral_arms_only_after_continuous_quiet_hold() -> None:
    integral = SlowHoldIntegrator(
        ki_pct_per_c_sec=1.0,
        arm_sec=3.0,
        max_dt_sec=2.0,
    )

    assert _step(integral, now=0.0) == 0.0
    assert _step(integral, now=1.0) == 0.0
    assert _step(integral, now=2.0) == 0.0
    assert _step(integral, now=3.0) == pytest.approx(1.0)


def test_interrupted_sampling_rearms_instead_of_integrating_a_time_gap() -> None:
    integral = SlowHoldIntegrator(
        ki_pct_per_c_sec=1.0,
        arm_sec=1.0,
        max_dt_sec=2.0,
    )
    _step(integral, now=0.0)
    assert _step(integral, now=1.0) == pytest.approx(1.0)

    # A five-second gap is not integrated and invalidates the continuous dwell.
    assert _step(integral, now=6.0) == pytest.approx(0.0)
    assert _step(integral, now=7.0) == pytest.approx(0.0)
    assert _step(integral, now=8.0) == pytest.approx(1.0)


def test_integral_is_bounded_and_has_conditional_anti_windup() -> None:
    bounded = SlowHoldIntegrator(
        ki_pct_per_c_sec=10.0,
        limit_pct=6.0,
        arm_sec=0.0,
    )
    _step(bounded, now=0.0)
    assert _step(bounded, now=1.0) == pytest.approx(6.0)
    assert _step(bounded, now=2.0) == pytest.approx(6.0)

    saturated_high = SlowHoldIntegrator(ki_pct_per_c_sec=1.0, arm_sec=0.0)
    _step(saturated_high, now=0.0, base=80.0)
    assert _step(saturated_high, now=1.0, base=80.0) == 0.0

    saturated_low = SlowHoldIntegrator(ki_pct_per_c_sec=1.0, arm_sec=0.0)
    _step(saturated_low, now=0.0, error=-1.0, base=0.0)
    assert _step(saturated_low, now=1.0, error=-1.0, base=0.0) == 0.0


def test_integral_unwinds_when_the_controller_leaves_hold() -> None:
    integral = SlowHoldIntegrator(
        ki_pct_per_c_sec=2.0,
        arm_sec=0.0,
        unwind_pct_per_sec=0.5,
    )
    _step(integral, now=0.0)
    assert _step(integral, now=1.0) == pytest.approx(2.0)
    assert _step(integral, now=2.0, error=-3.0, ror=-2.0) == pytest.approx(1.5)
    assert _step(integral, now=3.0, error=-3.0, ror=-2.0) == pytest.approx(1.0)


def test_reset_forgets_correction_and_dwell() -> None:
    integral = SlowHoldIntegrator(ki_pct_per_c_sec=1.0, arm_sec=0.0)
    _step(integral, now=0.0)
    _step(integral, now=1.0)
    assert integral.correction == pytest.approx(1.0)

    integral.reset()

    assert integral.correction == 0.0
    assert integral._eligible_since is None
    assert integral._last_time is None


class _AmbientCorrector:
    @staticmethod
    def compute_factor(_ambient: object) -> float:
        return 1.0


def _pid_harness(integrator: SlowHoldIntegrator) -> TilauPreheatPID:
    cfg = PIDConfig()
    harness = SimpleNamespace(
        cfg=cfg,
        p_ss=40.0,
        lead_sec=5.0,
        ambient_cache=None,
        _ambient_corrector=_AmbientCorrector(),
        _hold_integrator=integrator,
        _to_c=lambda value: value,
        effective_max_burner=lambda: cfg.max_burner,
    )
    return cast(TilauPreheatPID, harness)


def test_control_law_adds_integral_only_after_hold_qualification() -> None:
    integral = SlowHoldIntegrator(
        ki_pct_per_c_sec=5.0,
        arm_sec=0.0,
        limit_pct=6.0,
    )
    pid = _pid_harness(integral)

    first, _ = TilauPreheatPID.compute_fuzzy_power(pid, 199.0, 0.0, now=0.0)
    second, _ = TilauPreheatPID.compute_fuzzy_power(pid, 199.0, 0.0, now=1.0)

    assert first == 45  # P_ss 40 + Kp 5, integral only arms
    assert second == 50  # same proportional command + five integral points


def test_hard_overtemperature_cut_resets_integral() -> None:
    integral = SlowHoldIntegrator(correction=4.0)
    pid = _pid_harness(integral)

    burner, _ = TilauPreheatPID.compute_fuzzy_power(pid, 202.0, 0.0, now=1.0)

    assert burner == 0
    assert integral.correction == 0.0


def test_default_integral_is_deliberately_slow() -> None:
    integral = SlowHoldIntegrator()
    for second in range(61):
        _step(integral, now=float(second), error=1.0)

    # Ten-second arming delay, then 50 seconds × 0.02 %/(°C·s).
    assert integral.correction == pytest.approx(1.02)


def test_sv_command_resets_integral_and_reloads_continuous_law() -> None:
    integral = SlowHoldIntegrator(correction=4.0)
    applied_sv: list[float] = []
    pid = cast(
        TilauPreheatPID,
        SimpleNamespace(
            active=True,   # only a live preheat re-stamps the profile marker
            cfg=PIDConfig(),
            p_ss=20.0,
            lead_sec=5.0,
            _to_c=lambda value: value,
            _unit=lambda: "C",
            _precompute_targets=lambda: None,
            _hold_integrator=integral,
            load_law_params=lambda: (42.0, 6.5),
            aw=SimpleNamespace(
                qmc=SimpleNamespace(tilau_preheat_sv_c=200.0),
                pidcontrol=SimpleNamespace(setSV=applied_sv.append),
            ),
        ),
    )

    TilauPreheatPID.processcommand(pid, "SV", "205.5")

    assert pid.cfg.target_sv == pytest.approx(205.5)
    assert (pid.p_ss, pid.lead_sec) == pytest.approx((42.0, 6.5))
    assert integral.correction == 0.0
    assert pid.aw.qmc.tilau_preheat_sv_c == pytest.approx(205.5)
    assert applied_sv == [205.5]


def test_pid_config_applies_flat_and_nested_values() -> None:
    cfg = PIDConfig.from_mapping(
        {
            "max_burner": 72,
            "heater_slider": 1,
            "pid": {"kp": 3.5, "polling_dt": 0.5, "fan_enabled": "on"},
        },
        target_sv=205.0,
    )
    assert cfg.target_sv == pytest.approx(205.0)
    assert cfg.max_burner == pytest.approx(72.0)
    assert cfg.heater_slider == 1
    assert cfg.kp == pytest.approx(3.5)
    assert cfg.polling_dt == pytest.approx(0.5)
    assert cfg.fan_enabled is True


@pytest.mark.parametrize("config", [
    {"max_burner": 101},
    {"polling_dt": 0},
    {"heater_slider": 4},
    {"pid": {"fan_enabled": "perhaps"}},
    {"lead_sec_min": 8, "lead_sec_max": 4},
    {"pid": []},
])
def test_pid_config_rejects_unsafe_values(config: dict) -> None:
    with pytest.raises(ValueError):
        PIDConfig.from_mapping(config, target_sv=200.0)


def test_slider_update_uses_application_signal_when_available() -> None:
    emitted: list[tuple[int, int, bool]] = []
    signal = SimpleNamespace(emit=lambda *args: emitted.append(args))
    aw = SimpleNamespace(
        simulator=None,
        tilaupidSliderCommandSignal=signal,
        moveslider=lambda *_args: pytest.fail("direct widget access"),
    )
    pid = cast(TilauPreheatPID, SimpleNamespace(aw=aw))

    TilauPreheatPID._update_artisan_slider(pid, 3, 64)

    assert emitted == [(3, 64, True)]

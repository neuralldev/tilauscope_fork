"""Offline thermal identification and shadow-promotion safety gates."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from tilauscope.tilaupid_thermal import (
    ThermalModelCandidate,
    ThermalPromotionState,
    ThermalShadowResult,
    ThermalShadowSession,
    ThermalTrace,
    identify_thermal_model,
    load_candidate,
    save_candidate,
)
from tilauscope.tools.extract_thermal_model import extract_trace


def _candidate(**overrides: object) -> ThermalModelCandidate:
    values: dict[str, object] = {
        "machine_fingerprint": "itopcyberroaster",
        "control_channel": "BT",
        "heating_gain_c_per_sec": 0.65,
        "cooling_coeff_per_sec": 0.00055,
        "response_lag_sec": 2.0,
        "derivative_rmse_c_per_sec": 0.02,
        "rollout_rmse_c": 1.0,
        "cross_validation_rmse_c": 1.2,
        "n_profiles": 4,
        "n_samples": 1000,
        "generated_at": "2026-08-09T12:00:00+00:00",
    }
    values.update(overrides)
    return ThermalModelCandidate(**values)  # type: ignore[arg-type]


def _synthetic_trace(profile: int, *, noisy: bool = True) -> ThermalTrace:
    gain, loss, lag = 0.65, 0.00055, 2
    ambient = 18.0 + profile
    times = [float(second) for second in range(361)]
    burners: list[float] = []
    for second in range(361):
        if second < 30 + profile * 3:
            burner = 20.0 + profile * 5.0
        elif second < 235 - profile * 4:
            burner = 76.0 + profile
        elif second < 285:
            burner = 48.0 - profile * 2.0
        else:
            burner = 36.0 + profile
        burners.append(burner)
    physical = ambient
    temperatures = [physical]
    for second in range(1, 361):
        delayed = burners[max(0, second - lag)]
        physical += gain * (delayed / 100.0) ** 2 - loss * (physical - ambient)
        noise = 0.03 * math.sin(second * 0.37 + profile) if noisy else 0.0
        temperatures.append(physical + noise)
    return ThermalTrace(
        times_sec=tuple(times),
        temperatures_c=tuple(temperatures),
        burner_pct=tuple(burners),
        ambient_c=ambient,
        source=f"synthetic-{profile}",
    )


def test_offline_identification_recovers_quadratic_thermal_model() -> None:
    candidate = identify_thermal_model(
        [_synthetic_trace(i) for i in range(4)],
        machine_fingerprint="itopcyberroaster",
        control_channel="BT",
        generated_at="2026-08-09T12:00:00+00:00",
    )

    assert candidate.heating_gain_c_per_sec == pytest.approx(0.65, abs=0.08)
    assert candidate.cooling_coeff_per_sec == pytest.approx(0.00055, abs=0.00025)
    assert candidate.response_lag_sec == pytest.approx(2.0, abs=2.0)
    assert candidate.cross_validation_rmse_c < 2.0
    assert 30.0 < candidate.equilibrium_power_pct(200.0, 20.0) < 50.0


def test_candidate_sidecar_round_trip_and_context_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    candidate = _candidate()

    save_candidate(path, candidate)

    loaded = load_candidate(path)
    assert loaded == candidate
    assert loaded.fingerprint == candidate.fingerprint
    assert _candidate(control_channel="ET").fingerprint != candidate.fingerprint


def test_invalid_candidate_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")

    with pytest.raises(ValueError):
        load_candidate(path)


def test_offline_extractor_uses_bt_burner_timebase_and_ignores_cooking_exclusion(
    tmp_path: Path,
) -> None:
    source = _synthetic_trace(0)
    path = tmp_path / "real.alog"
    path.write_text(repr({
        "mode": "C",
        "roastepoch": 1_800_000_000.0,
        "roastertype": "ITOP Cyberroaster",
        "pidSource": 1,
        "tilau_preheat_sv_c": 185.0,
        "tilau_exclude_learning": True,
        "timex": list(source.times_sec),
        "timeindex": [len(source.times_sec) - 1, -1, -1, -1, -1, -1, -1, -1],
        "temp1": [300.0] * len(source.times_sec),  # ET: must not be selected
        "temp2": list(source.temperatures_c),      # Artisan BT
        "ambientTemp": source.ambient_c,
        "tilau_name_map": {0: "skywalker_pf"},
        "extraname1": ["{3}"],
        "extratemp1": [list(source.burner_pct)],
        "extraname2": ["{0}"],
        "extratemp2": [[20.0] * len(source.times_sec)],
        "extratimex": [list(source.times_sec)],
    }), encoding="utf-8")

    extracted = extract_trace(path)

    assert extracted is not None
    machine, channel, trace = extracted
    assert (machine, channel) == ("itopcyberroaster", "BT")
    assert max(trace.temperatures_c) < 200.0
    assert trace.burner_pct == source.burner_pct


def test_shadow_replays_model_without_producing_a_control_output() -> None:
    candidate = _candidate()
    trace = _synthetic_trace(0, noisy=False)
    shadow = ThermalShadowSession(candidate)

    for now, temperature, burner in zip(
        trace.times_sec, trace.temperatures_c, trace.burner_pct, strict=True
    ):
        # observe() has no return value and no actuator dependency by design.
        assert shadow.observe(
            now=now,
            temperature_c=temperature,
            burner_pct=burner,
            ambient_c=trace.ambient_c,
        ) is None
    result = shadow.finish()

    assert result.qualified
    assert result.passed
    assert result.rmse_c < 1.0


def _result(*, passed: bool, qualified: bool = True) -> ThermalShadowResult:
    return ThermalShadowResult(
        qualified=qualified,
        passed=passed,
        duration_sec=300.0,
        n_samples=300,
        rmse_c=1.0 if passed else 20.0,
        bias_c=0.2 if passed else 10.0,
        p95_abs_error_c=2.0 if passed else 30.0,
        reason="passed" if passed else "prediction_error",
    )


def test_promotion_needs_three_consecutive_passes_and_regression_withdraws_it() -> None:
    state = ThermalPromotionState()
    state = state.advance(_result(passed=True))
    state = state.advance(_result(passed=True))
    assert not state.active
    state = state.advance(_result(passed=True))
    assert state.active

    state = state.advance(_result(passed=False))
    assert not state.active
    assert state.consecutive_passes == 0
    assert state.failed_sessions == 1


def test_unqualified_shadow_does_not_change_promotion_evidence() -> None:
    state = ThermalPromotionState(consecutive_passes=2, qualified_sessions=2)

    assert state.advance(_result(passed=False, qualified=False)) == state

"""Qualification and isolation of TilauPID cross-roast learning."""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QSettings

import tilauscope.tilaupid_adaptative as adaptive_module
from tilauscope.tilaupid_adaptative import (
    AdaptiveMemory,
    AdaptivePIDMixin,
    AlogScanner,
    AmbientConditions,
    RoastPreheatMetrics,
    StabilisationDetector,
    _robust_centre,
    _robust_peak,
)


def _aw(machine: str = "ITOP Cyberroaster", source: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        qmc=SimpleNamespace(
            roastertype_setup=machine,
            roastertype=machine,
            machinesetup=machine,
        ),
        pidcontrol=SimpleNamespace(pidSource=source),
        simulator=None,
    )


def _alog_profile(
    *,
    machine: str = "ITOP Cyberroaster",
    source: int = 1,
    excluded: bool = False,
) -> dict:
    timex = list(range(61))
    control = [180.0 + min(t, 30) * (20.0 / 30.0) for t in timex]
    profile = {
        "mode": "C",
        "roastertype": machine,
        "machinesetup": machine,
        "pidSource": source,
        "tilau_preheat_sv_c": 200.0,
        "timex": timex,
        "timeindex": [60, -1, -1, -1, -1, -1, -1, -1],
        "temp1": control if source not in (0, 1) else [150.0] * len(timex),
        "temp2": control if source in (0, 1) else [150.0] * len(timex),
        "ambientTemp": 20.0,
        "ambient_humidity": 50.0,
        "ambient_pressure": 1013.25,
        "roastepoch": 1_800_000_000.0,
        "specialeventstype": [],
        "specialeventsStrings": [],
        "specialeventsvalue": [],
        "specialevents": [],
        "tilau_name_map": {0: "skywalker_pf"},
        "extraname1": ["{3}"],
        "extratemp1": [[40.0] * len(timex)],
        "extraname2": [],
        "extratemp2": [],
        "extratimex": [timex],
    }
    if excluded:
        profile["tilau_exclude_learning"] = True
    return profile


def _write_alog(path: Path, profile: dict) -> None:
    path.write_text(repr(profile), encoding="utf-8")


def test_history_uses_only_same_machine_and_control_channel(tmp_path: Path) -> None:
    scanner = AlogScanner(str(tmp_path), aw=_aw())
    valid = tmp_path / "valid.alog"
    other_machine = tmp_path / "other-machine.alog"
    other_source = tmp_path / "other-source.alog"
    excluded = tmp_path / "excluded.alog"
    _write_alog(valid, _alog_profile())
    _write_alog(other_machine, _alog_profile(machine="Kaleido M10"))
    _write_alog(other_source, _alog_profile(source=2))
    _write_alog(excluded, _alog_profile(excluded=True))

    metric = scanner._extract_metrics(valid)

    assert metric is not None
    assert metric.was_stable
    assert metric.hold_mean_power == pytest.approx(40.0)
    assert scanner._extract_metrics(other_machine) is None
    assert scanner._extract_metrics(other_source) is None
    # The exclusion flag governs cooking/roast-plan learning, not preheat physics.
    assert scanner._extract_metrics(excluded) is not None


def test_scan_stops_as_soon_as_the_memory_window_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read ceiling is a ceiling, not a target.

    `window` is the memory depth AND the denominator of the learning confidence
    (n/window), so it must not double as the I/O budget: widening the search by
    raising it would dilute every correction. The scanner therefore stops the
    moment it holds `window` usable roasts, and only keeps digging when they
    are scarce.
    """
    for i in range(4):
        path = tmp_path / f"valid-{i}.alog"
        _write_alog(path, _alog_profile())
        os.utime(path, (100.0 + i, 100.0 + i))

    scanner = AlogScanner(str(tmp_path), window=2, aw=_aw())
    opened: list[str] = []
    original_extract = scanner._extract_metrics

    def tracked_extract(path: Path) -> RoastPreheatMetrics | None:
        opened.append(path.name)
        return original_extract(path)

    monkeypatch.setattr(scanner, "_extract_metrics", tracked_extract)
    metrics = scanner.load_window()

    assert len(metrics) == 2
    # newest-first, and not one profile opened past the second hit
    assert opened == ["valid-3.alog", "valid-2.alog"]


def test_scan_digs_past_the_window_when_usable_roasts_are_scarce(tmp_path: Path) -> None:
    """A recent run of unusable profiles no longer starves the learning.

    The budget used to be `window` itself, so three unrelated roasts on top of
    the pile left a window of one with nothing at all.
    """
    valid = tmp_path / "old-valid.alog"
    wrong_1 = tmp_path / "new-wrong-machine.alog"
    wrong_2 = tmp_path / "new-wrong-source.alog"
    _write_alog(valid, _alog_profile())
    _write_alog(wrong_1, _alog_profile(machine="Other roaster"))
    _write_alog(wrong_2, _alog_profile(source=2))
    os.utime(valid, (100.0, 100.0))
    os.utime(wrong_1, (200.0, 200.0))
    os.utime(wrong_2, (300.0, 300.0))

    scanner = AlogScanner(str(tmp_path), window=1, aw=_aw())
    metrics = scanner.load_window()

    assert len(metrics) == 1


def test_read_ceiling_is_honoured(tmp_path: Path) -> None:
    """Never open more than `scan_budget` profiles, however big the archive."""
    for i in range(12):
        path = tmp_path / f"wrong-{i:02d}.alog"
        _write_alog(path, _alog_profile(machine="Other roaster"))
        os.utime(path, (100.0 + i, 100.0 + i))

    scanner = AlogScanner(str(tmp_path), window=1, aw=_aw(), scan_budget=4)
    assert scanner.scan_budget == 4
    assert len(scanner._list_recent()) == 4
    assert scanner.load_window() == []


def test_read_ceiling_defaults_clear_of_the_memory_window() -> None:
    """The default ceiling must never fall back to `window`, which is the bug
    this whole split exists to prevent."""
    assert AlogScanner("", window=1, aw=_aw()).scan_budget >= 50
    assert AlogScanner("", window=30, aw=_aw()).scan_budget >= 150


def test_robust_statistics_reject_single_sample_spikes() -> None:
    values = [10.0] * 19 + [1000.0]
    assert _robust_centre(values) == pytest.approx(10.0)
    assert _robust_peak(values) == pytest.approx(10.0)


def test_stabilisation_requires_a_complete_observation_window() -> None:
    detector = StabilisationDetector(window_sec=5.0, polling_dt=1.0)
    for now in (0.0, 1.0, 2.0, 4.9):
        detector.update(200.0, 200.0, now=now)
    assert not detector.has_full_window()
    detector.update(200.0, 200.0, now=5.0)
    assert detector.has_full_window()


def test_stabilisation_window_uses_elapsed_time_not_sample_count() -> None:
    detector = StabilisationDetector(window_sec=5.0, polling_dt=1.0)
    for now in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        detector.update(200.0, 200.0, now=now)
    assert not detector.has_full_window()

    detector.update(200.0, 200.0, now=5.0)
    assert detector.has_full_window()

    detector.update(200.0, 200.0, now=10.1)
    assert list(detector._times) == [5.0, 10.1]


def test_stability_cannot_arm_before_full_elapsed_window() -> None:
    detector = StabilisationDetector(window_sec=5.0, polling_dt=1.0)
    for now in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        detector.update(200.0, 200.0, now=now)
    assert detector._stable_since is None

    detector.update(200.0, 200.0, now=5.0)
    assert detector._stable_since == pytest.approx(5.0)


class _Detector(StabilisationDetector):
    def __init__(self, *, full: bool = True, temp: float = 200.0, slope: float = 0.0):
        self.full = full
        self.temp = temp
        self.slope = slope

    def has_full_window(self) -> bool:
        return self.full

    def mean_temp(self) -> float:
        return self.temp

    def slope_c_per_min(self) -> float:
        return self.slope


@dataclass
class _Config:
    target_sv: float = 200.0
    p_ss_default: float = 20.0
    lead_sec_default: float = 6.0
    lead_sec_min: float = 1.0
    lead_sec_max: float = 15.0
    max_burner: float = 80.0


class _LearningHarness(AdaptivePIDMixin):
    def __init__(self, *, machine: str = "ITOP Cyberroaster", source: int = 1):
        self.cfg = _Config()
        self.aw = _aw(machine, source)
        self._alog_scanner = AlogScanner("", aw=self.aw)
        self._adaptive_memory = AdaptiveMemory(window=10)
        self._stabilisation_detector = _Detector()
        self._ambient_factor = 1.0
        self._session_start_time = 0.0
        self._session_reached_sv = True
        self._session_reach_time = 50.0
        self._session_filtered_max_bt = 205.0
        self._session_hold_samples = [40.0] * 20 + [100.0]
        self._session_hold_started_at = 70.0
        self._session_hold_last_at = 95.0
        self.p_ss = 20.0
        self.lead_sec = 6.0


@pytest.fixture(autouse=True)
def _clear_learning_settings() -> None:
    settings = QSettings()
    settings.remove("tilaupid/v3")
    settings.remove("tilaupid/v4")
    settings.remove("tilaupid/law_version")
    settings.sync()


def test_learning_rejects_short_session(monkeypatch: pytest.MonkeyPatch) -> None:
    learner = _LearningHarness()
    learner._session_start_time = 50.0
    monkeypatch.setattr(adaptive_module.time, "perf_counter", lambda: 100.0)

    assert not learner._learn_law_params()
    assert learner.p_ss == 20.0
    assert learner.lead_sec == 6.0
    assert not QSettings().contains(learner._law_param_keys()[0])


def test_qualified_learning_uses_median_and_bounds_each_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learner = _LearningHarness()
    monkeypatch.setattr(adaptive_module.time, "perf_counter", lambda: 100.0)

    assert learner._learn_law_params()

    # Raw EMA targets 26% and the overshoot asks +1.4s; per-session limits apply.
    assert learner.p_ss == pytest.approx(22.0)
    assert learner.lead_sec == pytest.approx(6.8)
    prefix = learner._law_key_prefix()
    settings = QSettings()
    assert settings.value(f"{prefix}/last_evidence") == "overshoot+stable_hold"
    assert settings.value(f"{prefix}/n_updates", 0, int) == 1


def test_persistence_is_contextual_traceable_and_rollbackable() -> None:
    learner = _LearningHarness()
    other_machine = _LearningHarness(machine="Kaleido M10")
    other_channel = _LearningHarness(source=2)

    assert learner._law_param_keys() != other_machine._law_param_keys()
    assert learner._law_param_keys() != other_channel._law_param_keys()

    learner._save_law_params(22.0, 6.8, "first")
    learner._save_law_params(23.0, 7.1, "second")
    assert learner.rollback_law_params()

    settings = QSettings()
    k_pss, k_lead = learner._law_param_keys()
    assert settings.value(k_pss, 0.0, float) == pytest.approx(22.0)
    assert settings.value(k_lead, 0.0, float) == pytest.approx(6.8)
    assert settings.value(f"{learner._law_key_prefix()}/last_evidence") == "rollback"


def test_context_refresh_follows_roast_setup_changes() -> None:
    learner = _LearningHarness()
    original_keys = learner._law_param_keys()
    assert learner.aw is not None
    learner.aw.qmc.roastertype_setup = "Kaleido M10"
    learner.aw.pidcontrol.pidSource = 2

    assert learner._refresh_learning_context()

    assert learner._law_param_keys() != original_keys
    assert "/kaleidom10/ET/" in learner._law_key_prefix()
    assert not learner._refresh_learning_context()


def _save_node(
    learner: _LearningHarness,
    sv: float,
    p_ss: float,
    lead: float,
) -> None:
    learner.cfg.target_sv = sv
    learner._save_law_params(p_ss, lead, "test")


def test_law_values_interpolate_linearly_between_exact_sv_nodes() -> None:
    learner = _LearningHarness()
    _save_node(learner, 190.0, 30.0, 4.0)
    _save_node(learner, 210.0, 50.0, 8.0)
    learner.cfg.target_sv = 200.0

    p_ss, lead = learner.load_law_params()

    assert p_ss == pytest.approx(40.0)
    assert lead == pytest.approx(6.0)
    assert "interpolated:190.0↔210.0°C" in learner.format_law_diagnostic()


def test_seed_diagnostic_does_not_claim_linear_evidence() -> None:
    learner = _LearningHarness()

    diagnostic = learner.format_law_diagnostic()

    assert "seed/default; updates=0; last=none" in diagnostic


def test_interpolation_is_continuous_across_old_bucket_boundary() -> None:
    learner = _LearningHarness()
    _save_node(learner, 200.0, 30.0, 5.0)
    _save_node(learner, 210.0, 50.0, 7.0)

    learner.cfg.target_sv = 204.9
    below = learner.load_law_params()
    learner.cfg.target_sv = 205.1
    above = learner.load_law_params()

    assert below == pytest.approx((39.8, 5.98))
    assert above == pytest.approx((40.2, 6.02))


def test_edge_reuse_and_large_interpolation_gaps_are_bounded() -> None:
    learner = _LearningHarness()
    _save_node(learner, 200.0, 40.0, 8.0)

    learner.cfg.target_sv = 214.0
    assert learner.load_law_params() == pytest.approx((21.333333, 6.133333))
    learner.cfg.target_sv = 216.0
    assert learner.load_law_params() == pytest.approx((20.0, 6.0))

    _save_node(learner, 250.0, 60.0, 10.0)
    learner.cfg.target_sv = 225.0
    assert learner.load_law_params() == pytest.approx((20.0, 6.0))


def test_edge_blend_rejoins_fallback_without_a_step() -> None:
    learner = _LearningHarness()
    _save_node(learner, 200.0, 50.0, 9.0)

    learner.cfg.target_sv = 214.9
    just_inside = learner.load_law_params()
    learner.cfg.target_sv = 215.1
    just_outside = learner.load_law_params()

    assert just_inside == pytest.approx((20.2, 6.02))
    assert just_outside == pytest.approx((20.0, 6.0))


def test_learning_persists_at_real_sv_to_tenth_degree() -> None:
    learner = _LearningHarness()
    _save_node(learner, 203.7, 42.0, 6.5)

    assert learner._law_key_prefix().endswith("/nodes/sv_2037")
    assert QSettings().contains(f"{learner._law_key_prefix()}/p_ss")


def test_v3_buckets_migrate_to_v4_nodes_with_metadata() -> None:
    learner = _LearningHarness()
    settings = QSettings()
    old_prefix = "tilaupid/v3/itopcyberroaster/BT/sv_200"
    settings.setValue(f"{old_prefix}/p_ss", 41.0)
    settings.setValue(f"{old_prefix}/lead", 6.2)
    settings.setValue(f"{old_prefix}/n_updates", 3)
    settings.setValue(f"{old_prefix}/last_evidence", "stable_hold")
    settings.setValue("tilaupid/law_version", 3)

    learner._migrate_persisted_law()

    new_prefix = "tilaupid/v4/itopcyberroaster/BT/nodes/sv_2000"
    assert settings.value(f"{new_prefix}/p_ss", 0.0, float) == pytest.approx(41.0)
    assert settings.value(f"{new_prefix}/lead", 0.0, float) == pytest.approx(6.2)
    assert settings.value(f"{new_prefix}/n_updates", 0, int) == 3
    assert settings.value(f"{new_prefix}/last_evidence") == "stable_hold"


def test_corpus_seed_ignores_unstable_hold_power() -> None:
    learner = _LearningHarness()
    stable = RoastPreheatMetrics(
        timestamp=1_800_000_000.0,
        target_sv=200.0,
        hold_mean_power=40.0,
        was_stable=True,
        target_is_recorded_sv=True,
        ambient=AmbientConditions(),
    )
    unstable = RoastPreheatMetrics(
        timestamp=1_800_000_001.0,
        target_sv=200.0,
        hold_mean_power=90.0,
        was_stable=False,
        target_is_recorded_sv=True,
        ambient=AmbientConditions(),
    )
    learner._adaptive_memory = AdaptiveMemory(window=10)
    learner._adaptive_memory._history = deque([stable, unstable], maxlen=10)

    summary = learner.law_corpus_summary(200.0)

    assert summary["n_held"] == 1
    assert summary["p_ss_median"] == pytest.approx(40.0)

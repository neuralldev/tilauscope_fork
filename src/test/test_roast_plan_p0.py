"""P0 acceptance tests for the Skywalker V2 roast-plan revision."""

from __future__ import annotations

import pytest

from tilauscope.roast_plan_model import (
    _PlanSource,
    TilauScopeRoastPlan,
    _fit_fc_charge_regression,
    _heater_authority_notes,
    _learning_log_is_eligible,
    _selected_roast_color,
)


@pytest.mark.parametrize(("extra", "eligible"), [
    ({}, True),
    ({"tilau_exclude_learning": False}, True),
    ({"tilau_exclude_learning": True}, False),
    ({"tilau_simulated": True}, False),
    ({"tilau_simulated": True, "tilau_exclude_learning": False}, False),
])
def test_learning_flags_are_legacy_compatible(extra: dict, eligible: bool) -> None:
    data = {"computed": {"ambient_temperature": 20.0, "ambient_humidity": 50.0}, **extra}
    assert _learning_log_is_eligible(data) is eligible


@pytest.mark.parametrize(("temperature", "humidity"), [
    (555.0, 50.0), (-11.0, 50.0), (61.0, 50.0), (20.0, 0.0), (20.0, 101.0),
])
def test_aberrant_ambient_readings_are_rejected(temperature: float, humidity: float) -> None:
    data = {"computed": {"ambient_temperature": temperature, "ambient_humidity": humidity}}
    assert not _learning_log_is_eligible(data)


def test_ground_colour_has_priority_over_the_lighter_maximum() -> None:
    assert _selected_roast_color({"whole_color": 71.3, "ground_color": 73.1}) == (73.1, "ground")


def test_whole_colour_is_only_a_fallback() -> None:
    assert _selected_roast_color({"whole_color": 71.3, "ground_color": 0}) == (71.3, "whole")
    assert _selected_roast_color({}) == (None, None)


def test_fc_regression_refuses_three_points() -> None:
    assert _fit_fc_charge_regression([170, 180, 190], [195, 196, 197])["status"] == "refused"


def test_fc_regression_refuses_a_narrow_charge_range() -> None:
    result = _fit_fc_charge_regression([180, 181, 182, 183, 184], [195, 196, 197, 198, 199])
    assert result["status"] == "refused"
    assert result["charge_range_c"] == 4.0


def test_fc_regression_must_beat_leave_one_out_median() -> None:
    result = _fit_fc_charge_regression([170, 175, 180, 185, 190], [195, 197, 196, 197, 195])
    assert result["status"] == "refused"
    assert result["regression_mae_c"] is not None
    assert result["baseline_mae_c"] is not None


def test_pre_fc_low_authority_warns_without_clamping() -> None:
    values = [80.0, 60.0, 43.0]
    notes = _heater_authority_notes(values, 45.0, 50.0)
    assert values[-1] == 43.0
    assert notes and "low-authority" in notes[0]


def test_development_value_is_not_part_of_the_authority_check() -> None:
    assert _heater_authority_notes([80.0, 60.0, 50.0], 45.0, 50.0) == []


def test_valid_245_maillard_is_not_raised_to_three_minutes(plan_model: TilauScopeRoastPlan) -> None:
    result = plan_model._calibrate_and_floor_phase_durations(
        dry_time_min=4.0, total_time_min=8.75, dev_time_min=2.0,
        drying_time_band=(3.5, 5.0), maillard_time_band=(2.5, 4.0),
        t_dry_raw=4.0, t_fc_raw=6.75, t_n=3,
        charge_weight_g=200.0, batch_optimal_g=400.0, thermal_inertia=0.45)
    assert result.maillard_time_min == pytest.approx(2.75)


def test_consistent_history_tightens_the_tolerance_band() -> None:
    """Three sources learned and a tight FC dispersion: the plan knows this
    coffee, so the coach and the EOR bilan read it more strictly (×0.8)."""
    result = TilauScopeRoastPlan._resolve_plan_confidence(
        fc_source=_PlanSource("learned", 5, "learned (n=5)"), timing_source=_PlanSource("learned", 5, "learned (n=5)"),
        drop_source=_PlanSource("learned", 5, "learned (n=5)"), fc_bt_mad_c=0.2,
        soak_dcharge_c=0.0, soak_dheater_pct=0,
        minutes_since_last_drop=None, ror_scale=1.0)
    assert result.display == "consistent history"
    assert result.tol_factor == 0.8


def test_the_authority_note_names_the_roaster_it_is_talking_about() -> None:
    """The wording used to hard-code "the Skywalker V2" and "45–50%", so any
    other machine declaring these fields quoted the wrong name and the wrong
    numbers at its owner. Both now come from the roaster being planned for."""
    note = _heater_authority_notes([40.0], 38.0, 44.0, "Cormorant CR600g")[0]
    assert "Cormorant CR600g" in note
    assert "38" in note and "44" in note
    assert "Skywalker" not in note


def test_the_authority_note_stays_readable_without_a_roaster_name() -> None:
    note = _heater_authority_notes([40.0], 45.0, 50.0)[0]
    assert "this roaster" in note


# ── Provenance: a key for the code, a label for the eye ──────────────────────

def test_a_source_key_never_carries_the_sample_count() -> None:
    """The count belongs to the label. A key that moved with n is a key every
    caller has to parse — which is how `== "learned"` came to be written."""
    _value, source = TilauScopeRoastPlan._adopt_learned(200.0, 210.0, 7)
    assert source.key == "learned"
    assert source.n == 7
    assert source.label == "learned (n=7)"


def test_the_fc_charge_regression_is_gated_on_the_key_not_the_label() -> None:
    """Regression test for a condition that was never true. The gate read
    `fc_source == "learned"` while the label has always been "learned (n=3)",
    so the validated FC/charge regression had never run once. Anything that
    compares a source to display text is the same bug waiting to happen."""
    _value, source = TilauScopeRoastPlan._adopt_learned(196.0, 199.0, 4)
    assert source != "learned"          # the old gate: silently false forever
    assert source.key == "learned"      # what the code must ask instead


def test_a_small_batch_is_a_sample_like_any_other() -> None:
    """Batch mass is no longer grounds for refusal (doctrine corrected
    2026-08-11): the rear-elevation loading technique keeps the probe immersed,
    so a 244 g roast measures its own first crack as truthfully as a 400 g one.
    These are the six real roasts of the one bean whose fit validates; four of
    them used to be discarded on weight alone, which left the fit below the
    minimum sample count and silently refused."""
    charges = [171.0, 179.0, 184.0, 185.0, 185.5, 193.0]
    fcs = [177.8, 189.0, 191.4, 185.9, 180.5, 196.2]
    assert _fit_fc_charge_regression(charges, fcs)["status"] == "adopted"


def test_leave_one_out_is_the_only_gate_the_regression_has() -> None:
    """Nothing upstream of the validation may reject a sample, so a refusal can
    only ever mean the fit failed to beat the median baseline."""
    charges = [171.0, 179.0, 184.0, 185.0, 185.5, 193.0]
    noise = [190.0, 184.0, 193.0, 181.0, 196.0, 186.0]
    refused = _fit_fc_charge_regression(charges, noise)
    assert refused["status"] == "refused"
    assert refused["n"] == 6          # every roast took part in the attempt


# ── The turning point follows the MASS, not the charge temperature ───────────
# Measured 2026-08-11 on the 94 usable Skywalker roasts: r(TP, charge) = +0.29,
# r(TP, mass) = -0.75. The old `charge x 0.55` was unbiased on average and wrong
# everywhere, the two errors cancelling: +9 C on a full drum, -25 C on a small
# batch. Nothing in the suite noticed a 25 C move, hence these tests.

_TP = TilauScopeRoastPlan._tp_placeholder_c


def test_a_small_batch_turns_higher_than_a_full_drum_at_the_same_charge() -> None:
    """Same charge temperature, less coffee: less mass to heat, so the bean
    probe never falls as far. This is the whole point of the correction."""
    small = _TP(180.0, 250.0, 400.0)
    full = _TP(180.0, 400.0, 400.0)
    assert small > full + 15.0


def test_the_turning_point_matches_what_the_machine_actually_does() -> None:
    """Both medians come from the corpus: 119 C under 320 g, 93 C above, at the
    charge temperatures actually used in each class."""
    assert _TP(171.7, 250.0, 400.0) == pytest.approx(119.0, abs=6.0)
    assert _TP(184.9, 400.0, 400.0) == pytest.approx(93.1, abs=6.0)


def test_a_batch_at_nominal_takes_the_measured_nominal_anchor() -> None:
    """The dip is read from the anchor table, not fitted by a formula: a roaster
    loaded exactly to nominal takes the anchor measured at that ratio (n=27),
    which is the best-sampled row of the table."""
    assert _TP(180.0, 400.0, 400.0) == pytest.approx(180.0 * (1.0 - 0.5014))


def test_an_unknown_batch_or_machine_falls_back_to_the_nominal_anchor() -> None:
    """Neither argument may be required: the curve must still be drawable when
    the roaster is unknown or the weight has not been entered. The fallback is
    the nominal anchor rather than an average across ratios, which would
    describe no real batch."""
    assert _TP(180.0) == pytest.approx(180.0 * (1.0 - 0.5014))
    assert _TP(180.0, 250.0, 0.0) == pytest.approx(_TP(180.0))
    assert _TP(180.0, 0.0, 400.0) == pytest.approx(_TP(180.0))


def test_an_absurd_batch_cannot_push_the_turning_point_out_of_the_drum() -> None:
    """A 50 g sample or a triple overload must still yield a drawable curve.

    Below the first anchor the MEASURED plateau holds — the dip stops deepening
    under roughly 150 g of a 400 g machine. The low clamp sits below that
    plateau on purpose: raised to the plateau value it would flatten the whole
    bottom of the table and the measured anchors would never be reached.
    """
    assert _TP(180.0, 50.0, 400.0) == pytest.approx(180.0 * (1.0 - 0.2962))
    assert _TP(180.0, 150.0, 400.0) == pytest.approx(_TP(180.0, 50.0, 400.0))
    assert _TP(180.0, 1200.0, 400.0) == pytest.approx(180.0 * 0.35)


def test_the_mass_term_is_relative_to_each_machine_nominal_weight() -> None:
    """Checked against the Cormorant corpus (nominal 450 g, roasts at 500 g):
    predicted dip share 0.531 for 0.544 measured. A machine-neutral form is what
    lets one measured law serve a roaster it was not fitted on."""
    cormorant = _TP(190.6, 500.0, 450.0)
    assert cormorant == pytest.approx(190.6 * (1.0 - 0.544), abs=3.0)


def test_the_curve_and_the_announced_turning_point_are_one_model() -> None:
    """There used to be a second, independent formula publishing "Estimated TP"
    (charge - 30x(1.5-inertia) - mass/50). It read +43 C high on the corpus and
    contradicted the printed curve by ~50 C."""
    import inspect
    source = inspect.getsource(TilauScopeRoastPlan.generate_roast_plan)
    assert "_tp_dip_const" not in source
    assert "tp_temperature: float = _tp_bt_c" in source

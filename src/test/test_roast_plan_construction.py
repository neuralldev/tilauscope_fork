# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2026

"""Behaviour of the plan-construction pieces the golden snapshot cannot pin.

The corpus snapshot freezes what the plan *produces* on real coffee, which is
exactly why it says nothing about the branches real coffee does not exercise:
every committed roast has an empty variety field, one roast intent, and a batch
size inside the measured anchors. The rules below are the ones that decide what
the plan says, stated on their own inputs rather than read back off a snapshot.
"""

from __future__ import annotations

from typing import Any

import pytest

from tilauscope.bean_energy import match_variety_family
from tilauscope.roast_plan_model import (
    _DEV_DESTINATION_BONUS_SEC,
    TilauScopeRoastPlan,
    _resolve_green_moisture,
    _resolve_green_structure,
)
from tilauscope.tilauscope_types import (
    GREEN_MOISTURE_NEUTRAL_PCT,
    WEIGHT_LOSS_TOLERANCE_PCT,
    weight_loss_target,
    weight_loss_target_from_plan,
)


# ── the cultivar family prior ────────────────────────────────────────────────
# A declared prior, not a learned one: it is read off the variety typed on the
# coffee's record, so what it must get right is when to stay quiet.

@pytest.mark.parametrize(("varieties", "family", "delta"), [
    ("Gesha", "Ethiopian", +4.0),
    ("Ethiopian Heirloom", "Ethiopian", +4.0),
    ("Maragogype", "Typica", +4.0),
    ("Caturra", "Bourbon", -4.0),
    ("SL28", "Bourbon", -4.0),
    # Punctuation, case and accents are what hand-typed records actually carry.
    ('Geisha (Panama) "Gesha"', "Ethiopian", +4.0),
])
def test_a_named_variety_resolves_to_its_family(
        varieties: str, family: str, delta: float) -> None:
    assert match_variety_family(varieties) == (family, delta)


def test_a_timor_hybrid_is_read_through_its_other_parent() -> None:
    """Castillo and Catimor carry the Timor Hybrid, but the pace comes from the
    Caturra in them — so they are Bourbon, and must not fall through to a
    keyword match on a parent name listed later in the table."""
    assert match_variety_family("Castillo") == ("Bourbon", -4.0)
    assert match_variety_family("Catimor") == ("Bourbon", -4.0)
    assert match_variety_family("Sarchimor") == ("Bourbon", -4.0)


@pytest.mark.parametrize("varieties", [
    None, "", "   ", "Pacamara", "Centroamericano H1", "Robusta", "Icatu",
])
def test_an_unplaced_variety_says_nothing(varieties: "str | None") -> None:
    """Half the vocabulary is deliberately silent. `None` is the majority case
    and the intended one — a prior that guesses is worse than no prior."""
    assert match_variety_family(varieties) is None


@pytest.mark.parametrize("varieties", [
    "Bourbon, Gesha", "Caturra, Typica", "Typica / SL28", "Gesha and Caturra",
])
def test_a_lot_naming_two_families_gets_no_prior(varieties: str) -> None:
    """The families pull four degrees in opposite directions. Resolving by the
    order of the table would hand a two-family lot a full-confidence prior on
    half of what it is; the honest answer is silence."""
    assert match_variety_family(varieties) is None


def test_two_keywords_of_the_SAME_family_still_resolve() -> None:
    """The Timor hybrids and the Bourbons are two rows for one family, so a
    record naming both is a resolution, not a conflict — the ambiguity rule is
    on the family name, never on the row."""
    assert match_variety_family("Castillo, Caturra") == ("Bourbon", -4.0)


# ── where the family prior is allowed to land ────────────────────────────────

def _charge(varieties: str = "", family_weight: float = 1.0,
            process_type_lower: str = "washed") -> Any:
    return TilauScopeRoastPlan._charge_setup(
        process_type_lower=process_type_lower,
        varieties=varieties, family_weight=family_weight,
        moisture=_resolve_green_moisture(10.5),
        structure=_resolve_green_structure(700.0, 0.0),
        ambient_temp_c=20.0, minutes_since_last_drop=None,
        thermal_mass_idx=0.65, heat_retention_idx=0.65)


def test_the_family_moves_the_charge_the_plan_will_actually_use() -> None:
    plain = _charge()
    ethiopian = _charge("Gesha")
    bourbon = _charge("Caturra")
    assert ethiopian.temperature_c == pytest.approx(plain.temperature_c + 4.0)
    assert bourbon.temperature_c == pytest.approx(plain.temperature_c - 4.0)
    assert ethiopian.family_name == "Ethiopian"
    assert ethiopian.family_delta_c == pytest.approx(+4.0)


def test_a_blend_halves_the_prior_and_an_unknown_variety_cancels_it() -> None:
    """`family_weight` is confidence in the genetic identity, not a tuning
    knob: a weight of 0 must reproduce the behaviour from before the family
    term existed, to the degree."""
    plain = _charge()
    assert _charge("Gesha", family_weight=0.5).temperature_c == pytest.approx(
        plain.temperature_c + 2.0)
    assert _charge("Gesha", family_weight=0.0).temperature_c == pytest.approx(
        plain.temperature_c)
    assert _charge("Gesha", family_weight=0.0).family_name == ""


def test_the_family_prior_never_reaches_the_learned_first_crack() -> None:
    """`nominal_temperature_c` is what the FC regression is evaluated at, and
    that regression is fitted on charges actually practised. Letting a variety
    typed on a record shift it would move a measured prediction by a declared
    figure — the family was scoped to the charge, and stops there."""
    plain = _charge()
    for varieties in ("Gesha", "Caturra", "Maragogype"):
        moved = _charge(varieties)
        assert moved.nominal_temperature_c == pytest.approx(
            plain.nominal_temperature_c)
        assert moved.temperature_c != pytest.approx(plain.temperature_c)


def test_the_process_ceiling_still_wins_over_the_family() -> None:
    """Hoos' own precedence: the process adds a layer, it does not erase the
    genetics — but the process risk is a surface one, so it caps. A Typica
    natural cannot be charged like a Typica washed."""
    natural = _charge("Gesha", process_type_lower="natural")
    washed = _charge("Gesha", process_type_lower="washed")
    assert natural.temperature_c <= natural.band[1]
    assert natural.temperature_c < washed.temperature_c


# ── the weight-loss target ───────────────────────────────────────────────────

def test_an_unknown_colour_has_no_weight_loss_target() -> None:
    assert weight_loss_target(None) is None
    assert weight_loss_target("") is None
    assert weight_loss_target("Not A Colour") is None


def test_the_target_follows_the_water_the_lot_carries() -> None:
    """A dry lot and a wet one stopped at the same colour cannot lose the same
    fraction: the water is part of what leaves. One point of moisture is one
    point of loss, which the old colour-only table could not express."""
    dry = weight_loss_target("Medium", moisture_pct=9.0, dev_time_min=2.0)
    wet = weight_loss_target("Medium", moisture_pct=13.0, dev_time_min=2.0)
    assert wet.target - dry.target == pytest.approx(4.0)


def test_a_moisture_outside_the_plausible_window_counts_as_not_measured() -> None:
    """0.0 is the wire sentinel for an empty field, and 40 % is a typo. Both
    must fall back to the neutral figure rather than aiming at nonsense."""
    neutral = weight_loss_target(
        "Medium", moisture_pct=GREEN_MOISTURE_NEUTRAL_PCT, dev_time_min=2.0)
    for absurd in (0.0, 4.9, 20.1, 40.0):
        assert weight_loss_target(
            "Medium", moisture_pct=absurd, dev_time_min=2.0).target == pytest.approx(
                neutral.target)


def test_a_longer_development_burns_more_dry_matter() -> None:
    short = weight_loss_target("Medium", moisture_pct=10.5, dev_time_min=1.5)
    long = weight_loss_target("Medium", moisture_pct=10.5, dev_time_min=2.5)
    assert long.target > short.target


def test_an_unknown_development_falls_back_to_the_colour_own_band() -> None:
    """Not "no development" but "development not known": zeroing the term would
    silently aim every colour at the reference development and under-aim a
    medium roast. The fallback is the level's own conventional duration."""
    from tilauscope.tilauscope_types import ROASTING_BASIC_BASE

    row = next(p for p in ROASTING_BASIC_BASE.plans if p.name == "Medium")
    conventional = sum(row.development_time) / 2.0
    assert weight_loss_target("Medium", moisture_pct=10.5,
                              dev_time_min=0.0).target == pytest.approx(
        weight_loss_target("Medium", moisture_pct=10.5,
                           dev_time_min=conventional).target)


def test_the_bean_can_never_be_asked_to_lose_less_than_its_water() -> None:
    """A development short enough to drive the dry-matter term negative would
    mean the bean came out lighter than the water it held, which cannot happen."""
    target = weight_loss_target("Very Light", moisture_pct=12.0, dev_time_min=0.1)
    assert target.target >= 12.0


def test_the_target_carries_a_tolerance_band_around_it() -> None:
    target = weight_loss_target("Medium", moisture_pct=10.5, dev_time_min=2.0)
    assert target.low == pytest.approx(target.target - WEIGHT_LOSS_TOLERANCE_PCT)
    assert target.high == pytest.approx(target.target + WEIGHT_LOSS_TOLERANCE_PCT)


# ── reading that target back off a plan ──────────────────────────────────────

def test_the_plan_reader_names_the_keys_once() -> None:
    """Four call sites used to re-derive this from the plan, each naming the
    keys itself. They now go through one reader, so a renamed key breaks in one
    place instead of drifting silently in three."""
    plan = {"Target Agtron": "Medium", "Bean Humidity": "12.9",
            "Development Phase (min)": "2.10"}
    assert weight_loss_target_from_plan(plan) == weight_loss_target(
        "Medium", moisture_pct=12.9, dev_time_min=2.10)


@pytest.mark.parametrize("plan", [
    None, {},
    # A plan saved before these keys existed, and one with junk in them.
    {"Target Agtron": "Medium"},
    {"Target Agtron": "Medium", "Bean Humidity": "", "Development Phase (min)": "N/A"},
])
def test_the_plan_reader_survives_a_plan_that_predates_the_keys(plan: Any) -> None:
    """It must never raise on an old plan: the panels call it on whatever the
    session happens to hold."""
    result = weight_loss_target_from_plan(plan)
    assert result is None or result.target > 0.0


def test_the_moisture_the_reader_needs_is_published_only_once() -> None:
    """"Green Moisture" was an exact duplicate of "Bean Humidity" — same value,
    same format, two keys for one number, which is two chances to read the
    stale one."""
    import inspect

    source = inspect.getsource(TilauScopeRoastPlan.generate_roast_plan)
    assert '"Green Moisture"' not in source
    assert source.count('"Bean Humidity":') == 1


# ── the roast destination ────────────────────────────────────────────────────

@pytest.mark.parametrize(("stored", "expected"), [
    ("filter", "filter"), ("espresso", "espresso"), ("omni", "omni"),
    ("  Espresso  ", "espresso"), ("ESPRESSO", "espresso"),
    ("", "omni"), ("nonsense", "omni"), (None, "omni"),
])
def test_the_destination_setting_is_normalised(
        stored: "str | None", expected: str, monkeypatch: Any) -> None:
    from PyQt6.QtCore import QSettings

    monkeypatch.setattr(
        QSettings, "value",
        lambda _self, _k, default=None, _t=None: (
            stored if stored is not None else default))
    assert TilauScopeRoastPlan._read_roast_destination() == expected


def test_the_three_destinations_differ_only_by_development_seconds() -> None:
    """Filter is the reference; the others buy development, and nothing else.
    Ordering is the claim: an espresso is developed longer than an omni."""
    assert _DEV_DESTINATION_BONUS_SEC["filter"] == 0.0
    assert (_DEV_DESTINATION_BONUS_SEC["filter"]
            < _DEV_DESTINATION_BONUS_SEC["omni"]
            < _DEV_DESTINATION_BONUS_SEC["espresso"])


@pytest.mark.slow
def test_changing_the_destination_changes_the_next_plan_from_the_SAME_engine(
        qapp: Any, monkeypatch: Any) -> None:  # noqa: ARG001  # forces the offscreen app
    """The setup dialog and the guided assistant both cache their engine, so a
    destination read once at construction stayed frozen: clicking Espresso
    recomputed the same omni plan, and the roast then ran on an intent the
    screen had never shown. One engine, two destinations, two development
    times — that is the whole claim."""
    import corpus_harness as H

    H.install_qt_shims()
    model = H.make_plan_model(H.CORPUS_DIR)
    bean = H.make_bean('a82364a8-e9ad-447c-a3d8-5f49111dc3ee', '74110 GR2',
                       process='Natural')

    def _plan_for(destination: str) -> float:
        monkeypatch.setattr(TilauScopeRoastPlan, '_read_roast_destination',
                            staticmethod(lambda: destination))
        result = model.generate_roast_plan(
            bean, H.agtron('Medium'), 21.0, 55.0, 400.0, 1800.0, None, False, None)
        plan = result[0] if isinstance(result, tuple) else result
        return float(plan['Development Phase (min)'])

    filter_dev = _plan_for('filter')
    espresso_dev = _plan_for('espresso')
    omni_dev = _plan_for('omni')

    # The key is published rounded to 1/100 min, so the gap is checked to that.
    assert espresso_dev - filter_dev == pytest.approx(
        _DEV_DESTINATION_BONUS_SEC['espresso'] / 60.0, abs=0.011)
    assert omni_dev - filter_dev == pytest.approx(
        _DEV_DESTINATION_BONUS_SEC['omni'] / 60.0, abs=0.011)
    assert filter_dev < omni_dev < espresso_dev


# ── the turning point, between the measured anchors ──────────────────────────

_TP = TilauScopeRoastPlan._tp_placeholder_c


def test_the_dip_is_read_ACROSS_the_anchors_not_stepped_between_them() -> None:
    """The table is four measured load steps; a batch landing between two of
    them must be read across the pair. Stepping instead would make the plan jump
    by degrees at an arbitrary batch weight."""
    lo, hi = 0.625, 0.875
    mid = _TP(180.0, (lo + hi) / 2.0 * 400.0, 400.0)
    assert _TP(180.0, hi * 400.0, 400.0) < mid < _TP(180.0, lo * 400.0, 400.0)
    # Linear across the pair, not merely monotonic.
    assert mid == pytest.approx(180.0 * (1.0 - (0.3155 + 0.4386) / 2.0))


def test_the_dip_deepens_monotonically_with_the_batch() -> None:
    """More mass in the drum, colder turning point — over the whole usable
    range, with no reversal at an anchor boundary."""
    dips = [_TP(180.0, g, 400.0) for g in range(50, 501, 25)]
    assert all(later <= earlier for earlier, later in zip(dips, dips[1:]))


def test_the_nominal_fallback_does_not_need_an_exact_float_anchor() -> None:
    """The unknown-batch fallback used to be `next(... if ratio == 1.0)`: an
    exact float equality against the table, which raises StopIteration rather
    than falling back if the anchors are ever re-measured to 0.999."""
    assert _TP(180.0) == pytest.approx(180.0 * (1.0 - 0.5014))
    anchors = TilauScopeRoastPlan._TP_DIP_ANCHORS
    patched = tuple((0.999 if r == 1.0 else r, s, n) for r, s, n in anchors)
    try:
        TilauScopeRoastPlan._TP_DIP_ANCHORS = patched  # type: ignore[misc]
        assert _TP(180.0) == pytest.approx(180.0 * (1.0 - 0.5014))
    finally:
        TilauScopeRoastPlan._TP_DIP_ANCHORS = anchors  # type: ignore[misc]


# ── the drying rate-of-rise law ──────────────────────────────────────────────

def _timing(envelope: tuple[float, float, float, float] = (16.0, 12.0, 8.0, 5.0),
            tp_bt_c: float = 100.0, dry_bt_c: float = 160.0,
            **kwargs: Any) -> Any:
    return TilauScopeRoastPlan._envelope_timing(
        envelope=envelope, tp_time_min=1.25, tp_bt_c=tp_bt_c, dry_bt_c=dry_bt_c,
        fc_bt_c=196.0, dev_time_min=1.0, drop_ror_c=5.0, **kwargs)


def test_the_drying_slope_is_read_off_the_climb_the_batch_has_to_make() -> None:
    """The plan used to credit every batch with the same average slope, which
    made small batches dry too fast on paper. The slope now follows the rise:
    a long climb starts from a low turning point where the peak is really
    available, a short one does not."""
    intercept = TilauScopeRoastPlan._DRY_ROR_RISE_INTERCEPT
    per_c = TilauScopeRoastPlan._DRY_ROR_PER_RISE_C
    # Climbs where the law is the only thing acting: below roughly 40 °C the
    # Maillard arbitration re-derives the slope, above roughly 65 the envelope
    # cap takes over — both are asserted on their own further down.
    for rise in (40.0, 50.0, 60.0):
        timing = _timing(tp_bt_c=160.0 - rise, dry_bt_c=160.0)
        assert timing.dry_ror_c == pytest.approx(intercept + per_c * rise)


def test_a_shorter_climb_is_given_a_gentler_slope() -> None:
    short = _timing(tp_bt_c=120.0, dry_bt_c=160.0)
    long = _timing(tp_bt_c=100.0, dry_bt_c=160.0)
    assert short.dry_ror_c < long.dry_ror_c


def test_the_law_can_never_promise_more_than_the_envelope() -> None:
    """The cap is the envelope's own drying average — the law is a fit, and a
    fit that asks the machine for more than its measured envelope is asking for
    a curve it cannot draw."""
    envelope = (16.0, 12.0, 8.0, 5.0)
    cap = (envelope[0] + envelope[1]) / 2.0
    assert _timing(envelope, tp_bt_c=20.0, dry_bt_c=160.0).dry_ror_c <= cap + 1e-9


def test_a_low_envelope_machine_is_not_handed_the_floor_ABOVE_its_ceiling() -> None:
    """`_clamp(v, lo, hi)` returns `lo` when lo > hi, so a floor fixed at 6
    would come out above the ceiling on a machine whose drying envelope
    averages under 6 °C/min — the guard demanding more than the envelope
    promises, which is the reverse of a guard. No shipped roaster is that slow;
    the inversion is what is being pinned, not the machine."""
    slow = (5.0, 3.0, 2.5, 2.0)
    cap = (slow[0] + slow[1]) / 2.0
    assert cap < TilauScopeRoastPlan._DRY_ROR_MIN_C  # the premise of the test
    assert _timing(slow, tp_bt_c=155.0, dry_bt_c=160.0).dry_ror_c <= cap + 1e-9


def test_the_drying_floor_can_never_lengthen_the_drying_it_guards() -> None:
    """The floor is an absurdity guard, not a style: a minimum longer than what
    the law already asks for would silently add time to every large batch."""
    free = _timing()
    guarded = _timing(dry_floor_min=free.dry_time_min + 5.0)
    assert guarded.dry_time_min == pytest.approx(free.dry_time_min)


def test_the_drying_floor_still_lengthens_where_the_guard_lives() -> None:
    """The same floor is passed to two stages with two different powers, and
    reading only the first one makes the absurdity guard look dead.

    In `_envelope_timing` it arrives capped at the deduced drying, so it can
    only hold a negative water correction back — the sibling test above pins
    that. Here, in the stage that runs after the envelope AND after the learned
    calibration, it is applied in full and RAISES: a drying the machine cannot
    physically reach is lifted to what it can, and the total extends. Kill this
    and nothing else in the pipeline catches an unreachable drying."""
    floor = TilauScopeRoastPlan._dry_floor_min(400.0, 400.0, 0.45)
    result = TilauScopeRoastPlan._calibrate_and_floor_phase_durations(
        TilauScopeRoastPlan.__new__(TilauScopeRoastPlan),
        dry_time_min=floor - 2.0, total_time_min=9.0, dev_time_min=1.5,
        drying_time_band=(1.0, 8.0), maillard_time_band=(1.0, 8.0),
        t_dry_raw=None, t_fc_raw=None, t_n=0,
        charge_weight_g=400.0, batch_optimal_g=400.0, thermal_inertia=0.45)
    assert result.dry_time_min == pytest.approx(floor)


def test_the_drying_floor_follows_the_mass() -> None:
    """A fixed 4:30 was wrong at both ends. The floor is the machine's own
    limit at full burner, and a nearly empty drum still costs its fixed share
    of heating — so it falls with the batch without falling to nothing."""
    small = TilauScopeRoastPlan._dry_floor_min(150.0, 400.0, 0.45)
    full = TilauScopeRoastPlan._dry_floor_min(400.0, 400.0, 0.45)
    assert small < full
    # Tilau's own anchors on the Skywalker, burner at 100 %.
    assert full == pytest.approx(4.0, abs=0.05)
    assert small == pytest.approx(3.0, abs=0.15)
    # The empty drum keeps the fixed cost of heating itself.
    assert TilauScopeRoastPlan._dry_floor_min(0.0, 400.0, 0.45) > 0.5 * full

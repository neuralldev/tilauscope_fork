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

"""What the post-roast verdict is allowed to say.

The debrief is the only place in the application that judges a finished roast,
so the contracts that matter are: it compares against the plan frozen before
the roast and nothing else, it says so plainly when there is no plan, and it
never turns a colour deviation into advice.
"""

from __future__ import annotations

import copy

from tilauscope.roast_debrief import build_debrief


_COMPUTED = {
    "CHARGE_time": 0.0, "CHARGE_BT": 192.7,
    "TP_time": 80.0, "TP_BT": 99.2,
    "DRY_time": 332.0, "DRY_BT": 154.8,
    "FCs_time": 520.0, "FCs_BT": 186.8,
    "DROP_time": 636.0, "DROP_BT": 198.7,
    "dryphasetime": 332.0, "midphasetime": 188.0, "finishphasetime": 116.0,
    "totaltime": 636.0, "weight_loss": 14.3,
}

_PROFILE = {
    "computed": _COMPUTED, "weight": [400.0, 343.0, "g"],
    "ground_color": 62.0, "color_system": "Agtron", "mode": "C",
}

_SNAPSHOT = {
    "predicted": {
        "milestones": {
            "dry_end": {"time_s": 324.0, "bt_c": 154.0},
            "first_crack": {"time_s": 532.0, "bt_c": 187.0},
            "drop": {"time_s": 640.0, "bt_c": 198.0},
        },
        "target_color_agtron": 60.0,
    },
}


def _profile(**overrides):
    profile = copy.deepcopy(_PROFILE)
    computed = overrides.pop("computed", None)
    if computed:
        profile["computed"].update(computed)
    profile.update(overrides)
    return profile


def test_a_roast_within_the_plan_is_reported_as_on_plan():
    debrief = build_debrief(_profile(), _SNAPSHOT, "C")
    assert debrief.has_plan
    assert debrief.severity == "ok"
    assert "nothing to change" in debrief.next_time
    # every milestone deviation is signed, so the reader knows which way
    assert debrief.deltas["first_crack"].time_s == -12.0
    assert debrief.deltas["dry_end"].time_s == 8.0


def test_an_early_drop_names_the_drop_and_the_gesture_that_fixes_it():
    debrief = build_debrief(
        _profile(computed={"FCs_time": 512.0, "FCs_BT": 185.1,
                           "DROP_time": 564.0, "DROP_BT": 193.4,
                           "finishphasetime": 52.0}),
        _SNAPSHOT, "C")
    assert debrief.severity == "attention"
    assert "early" in debrief.headline
    # the gesture is the planned drop temperature, not a clock time
    assert "198" in debrief.next_time
    assert debrief.figures["dtr"].severity == "attention"


def test_without_a_snapshot_the_verdict_says_so_instead_of_inventing_one():
    debrief = build_debrief(_profile(), None, "C")
    assert not debrief.has_plan
    assert debrief.severity == "none"
    assert debrief.deltas == {}
    assert "No plan" in debrief.headline
    # the figures survive; only the comparison is gone
    assert debrief.figures["dtr"].value == "18.2 %"
    assert "planned" not in debrief.figures["dtr"].band


def test_a_snapshot_that_never_saw_a_drop_is_treated_as_no_plan():
    aborted = {"predicted": {"milestones": {"dry_end": {"time_s": 324.0}},
                             "target_color_agtron": 60.0}}
    debrief = build_debrief(_profile(), aborted, "C")
    assert not debrief.has_plan
    assert debrief.severity == "none"


def test_a_colour_deviation_is_stated_but_never_becomes_advice():
    # A roast well off its colour target, otherwise exactly on plan.
    debrief = build_debrief(_profile(ground_color=48.0), _SNAPSHOT, "C")
    assert debrief.severity == "ok"
    assert "planned 60" in debrief.figures["colour"].band
    # no validated DROP↔Agtron slope exists, so the colour cannot prescribe one
    assert "Agtron" not in debrief.next_time
    assert "colour" not in debrief.next_time.lower()


def test_a_missing_roasted_weight_leaves_a_hole_with_its_reason():
    profile = _profile(weight=[400.0, 0.0, "g"])
    profile["computed"].pop("weight_loss")
    debrief = build_debrief(profile, _SNAPSHOT, "C")
    assert debrief.figures["weight_loss"].value == "—"
    assert debrief.figures["weight_loss"].band


def test_the_rate_of_rise_is_reported_as_a_reference_not_a_ceiling():
    # Above the roaster reference is common and is not a fault.
    debrief = build_debrief(_profile(), _SNAPSHOT, "C",
                            peak_ror_reference_c=16.0, peak_ror_c=18.4)
    assert debrief.figures["peak_ror"].severity == "neutral"
    assert "16" in debrief.figures["peak_ror"].band


def test_the_rate_of_rise_uses_the_selected_fahrenheit_unit():
    debrief = build_debrief(_profile(mode="F"), _SNAPSHOT, "F",
                            peak_ror_reference_c=16.0, peak_ror_c=18.4)
    peak = debrief.figures["peak_ror"]
    assert peak.value == "33.1"
    assert "°F/min" in peak.band
    assert "29" in peak.band
    assert "°C/min" not in peak.band


def test_an_unmarked_first_crack_cannot_produce_a_development_figure():
    profile = _profile()
    profile["computed"]["FCs_time"] = 0.0
    profile["computed"]["FCs_BT"] = 0.0
    debrief = build_debrief(profile, _SNAPSHOT, "C")
    assert debrief.figures["dtr"].value == "—"
    assert debrief.figures["dev_rise"].value == "—"

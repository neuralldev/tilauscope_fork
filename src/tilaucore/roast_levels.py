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
# Tilau 2025-2026

"""Roast levels, shared by both apps: the base plan table by level and the
level a roast ran, read from its arrival pair (drop temperature, development)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass
class RoasterBasicPlanPerPhase:
   # No charge temperature here: charge is owned by _CHARGE_FLOOR_C and
   # _CHARGE_CEILING_BY_PROCESS in roast_plan_model (a single machine floor,
   # a ceiling per process, in measured BT).
   name: str
   heater_cmfc: tuple[float, float, float]
   total_time: tuple[float, float]
   drying_time: tuple[float, float]
   maillard_time: tuple[float, float]
   development_time: tuple[float, float]
   dtr_pct: tuple[float, float]
   drop_temp: tuple[int, int]
   fc_temp:int
   dry_temp:int

@dataclass
class RoasterBasicPlan:
    plans: list[RoasterBasicPlanPerPhase]

# Base roast-plan table by Agtron category (names match AGTRON_SCALES), before
# any per-roast correction (FIR/NIR light-roast tweak, BT-probe deviation).
# Single source shared by the plan generator (roast_plan_model.py, which
# deep-copies this before applying its corrections) and the BeanCave coach
# (beancave.py, which reads it as-is for post-roast reference ranges) so the
# two never judge a roast against different fundamentals.
ROASTING_BASIC_BASE: RoasterBasicPlan = RoasterBasicPlan(
    plans=[
        RoasterBasicPlanPerPhase(
            name="Very Light",
            heater_cmfc=(0.85, 0.70, 0.50),
            total_time=(7.5, 8.75),
            drying_time=(3.5, 4.0),
            maillard_time=(3.0, 3.5),
            development_time=(1.0, 1.25),
            dtr_pct=(0.13, 0.15),
            drop_temp=(197, 203),
            fc_temp=194,
            dry_temp=153,
        ),
        RoasterBasicPlanPerPhase(
            name="Light",
            heater_cmfc=(0.85, 0.70, 0.50),
            total_time=(8.25, 10.25),
            drying_time=(3.5, 4.5),
            maillard_time=(3.5, 4.0),
            development_time=(1.25, 1.75),
            dtr_pct=(0.15, 0.17),
            drop_temp=(203, 208),
            fc_temp=195,
            dry_temp=155,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium Light",
            heater_cmfc=(0.75, 0.65, 0.45),
            total_time=(9.75, 11.25),
            drying_time=(4.5, 5.0),
            maillard_time=(3.75, 4.25),
            development_time=(1.5, 2.0),
            dtr_pct=(0.16, 0.19),
            drop_temp=(208, 213),
            fc_temp=196,
            dry_temp=158,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium",
            heater_cmfc=(0.75, 0.60, 0.45),
            total_time=(11.0, 12.75),
            drying_time=(4.75, 5.25),
            maillard_time=(4.25, 4.75),
            development_time=(2.0, 2.75),
            dtr_pct=(0.18, 0.22),
            drop_temp=(212, 217),
            fc_temp=198,
            dry_temp=160,
        ),
        RoasterBasicPlanPerPhase(
            name="Medium Dark",
            heater_cmfc=(0.70, 0.60, 0.40),
            total_time=(12.0, 13.5),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(2.5, 3.0),
            dtr_pct=(0.20, 0.23),
            drop_temp=(217, 222),
            fc_temp=200,
            dry_temp=162,
        ),
        RoasterBasicPlanPerPhase(
            name="Dark",
            heater_cmfc=(0.70, 0.60, 0.42),
            total_time=(12.25, 13.75),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(2.75, 3.25),
            dtr_pct=(0.22, 0.24),
            drop_temp=(221, 226),
            fc_temp=202,
            dry_temp=163,
        ),
        RoasterBasicPlanPerPhase(
            name="Very Dark",
            heater_cmfc=(0.72, 0.62, 0.44),
            total_time=(12.5, 14.0),
            drying_time=(5.0, 5.5),
            maillard_time=(4.5, 5.0),
            development_time=(3.0, 3.5),
            dtr_pct=(0.23, 0.26),
            drop_temp=(224, 229),
            fc_temp=203,
            dry_temp=164,
        ),
        RoasterBasicPlanPerPhase(
            name="Extremely Dark",
            heater_cmfc=(0.72, 0.62, 0.44),
            total_time=(13.0, 14.5),
            drying_time=(5.0, 5.5),
            maillard_time=(4.75, 5.25),
            development_time=(3.25, 3.75),
            dtr_pct=(0.24, 0.27),
            drop_temp=(228, 236),
            fc_temp=204,
            dry_temp=165,
        ),
    ]
)

# On the arrival pair, one degree at drop is worth two seconds of development:
# a hotter drop and a shorter development land on the same colour. That
# equivalence is what lets the two be read on a single axis.
ARRIVAL_SECONDS_PER_DEGREE: float = 2.0


def arrival_index(drop_bt_c: float, dev_time_min: float) -> float:
    """The arrival pair on one axis, in °C-equivalent."""
    return drop_bt_c + (dev_time_min * 60.0) / ARRIVAL_SECONDS_PER_DEGREE


# What a roast level read from the arrival is worth on a home machine, in °C.
# These roasters are built from low-cost parts — a drop temperature is not a
# laboratory measurement — so a level is only ever resolved to about this much,
# and an arrival this close to a neighbouring level could be read either way.
# A roaster record may carry its own figure (RoasterContext.arrival_uncertainty_c).
ARRIVAL_UNCERTAINTY_DEFAULT_C: float = 3.0


def roast_level_from_arrival_detail(drop_bt_c: "float | None", dev_time_min: "float | None",
                                    drop_offset_c: float = 0.0,
                                    uncertainty_c: float = ARRIVAL_UNCERTAINTY_DEFAULT_C
                                    ) -> "tuple[str | None, str | None]":
    """(level, neighbour) — the level the roast ran, and the level it could just
    as well be read as when the arrival lands within `uncertainty_c` of it.

    See `roast_level_from_arrival` for how the level itself is read. The
    neighbour is None whenever the arrival sits clear inside one band.
    """
    if drop_bt_c is None or dev_time_min is None:
        return None, None
    try:
        drop_v, dev_v = float(drop_bt_c), float(dev_time_min)
    except (TypeError, ValueError):
        return None, None
    if drop_v <= 0 or dev_v <= 0:
        return None, None
    measured = arrival_index(drop_v, dev_v)
    scored = []
    for plan in ROASTING_BASIC_BASE.plans:
        lo = arrival_index(plan.drop_temp[0] + drop_offset_c, plan.development_time[0])
        hi = arrival_index(plan.drop_temp[1] + drop_offset_c, plan.development_time[1])
        dist = 0.0 if lo <= measured <= hi else (lo - measured if measured < lo else measured - hi)
        # Reference bands overlap at their edges; inside two of them the closer
        # centre wins, so the verdict never depends on the table's order.
        scored.append((dist, abs(measured - (lo + hi) / 2.0), plan.name))
    scored.sort()
    level = scored[0][2]
    neighbour = (scored[1][2]
                 if len(scored) > 1 and scored[1][0] <= uncertainty_c
                 else None)
    return level, neighbour


def roast_level_from_arrival(drop_bt_c: "float | None", dev_time_min: "float | None",
                             drop_offset_c: float = 0.0) -> "str | None":
    """The roast level a roast actually ran, read from what it did.

    The level is a property of the roast, not of the bean's colour: the colour
    is the result and is expected to agree with it. So the category is read from
    the arrival pair — how long the bean developed and how hot it left — against
    the same per-level reference the plan generator prescribes
    (ROASTING_BASIC_BASE), with the two traded off at ARRIVAL_SECONDS_PER_DEGREE.

    `drop_offset_c` is the roaster's bean-probe deviation at drop
    (RoasterContext.bt_offsets[3]), added to the reference the same way
    the plan generator adds it, so the comparison happens in the temperature
    the machine actually shows. Returns None when either half of the pair is
    missing — half an arrival says nothing.
    """
    if drop_bt_c is None or dev_time_min is None:
        return None
    try:
        drop_v, dev_v = float(drop_bt_c), float(dev_time_min)
    except (TypeError, ValueError):
        return None
    if drop_v <= 0 or dev_v <= 0:
        return None
    return roast_level_from_arrival_detail(drop_v, dev_v, drop_offset_c)[0]


def probe_drop_offset_c(ctx: Any) -> float:
    """The bean probe's deviation at drop for the machine that ran the roast.

    Same value and same sign the plan generator applies to the reference drop
    window, so a level read here and a level prescribed there mean the same
    temperature on the operator's own display.
    """
    offsets = getattr(ctx, 'bt_offsets', None) if ctx is not None else None
    if offsets and len(offsets) >= 4:
        try:
            return float(offsets[3])
        except (TypeError, ValueError):
            pass
    return 0.0


def arrival_uncertainty_c(ctx: Any) -> float:
    """What a level read from this machine's arrival is worth, in °C."""
    try:
        return float(getattr(ctx, 'arrival_uncertainty_c', None)
                     or ARRIVAL_UNCERTAINTY_DEFAULT_C)
    except (TypeError, ValueError):
        return ARRIVAL_UNCERTAINTY_DEFAULT_C


def measured_level(computed: dict, mode: str, ctx: Any) -> tuple[str | None, str | None]:
    """(level, neighbour) for a roast, from its arrival pair.

    `neighbour` is the level the arrival could just as well be read as when it
    lands on a band edge — None when the reading is clear-cut.
    """
    try:
        drop_bt = float(computed.get('DROP_BT') or 0.0)
        fcs_t = float(computed.get('FCs_time') or 0.0)
        drop_t = float(computed.get('DROP_time') or 0.0)
    except (TypeError, ValueError):
        return None, None
    if drop_bt <= 0 or fcs_t <= 0 or drop_t <= fcs_t:
        return None, None
    # The reference table is in °C — convert at the boundary, once.
    drop_c = (drop_bt - 32.0) * 5.0 / 9.0 if mode == 'F' else drop_bt
    return roast_level_from_arrival_detail(drop_c, (drop_t - fcs_t) / 60.0,
                                           probe_drop_offset_c(ctx),
                                           arrival_uncertainty_c(ctx))

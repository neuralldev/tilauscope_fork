# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The rate of rise TilauScope recomputes (tilaucore.ror), with the smoothing level and the
RoR limits of Artisan's canvas.

The rate Artisan computes while sampling, and the one it saves in a roast file,
stay Artisan's own.
"""

from __future__ import annotations

from typing import Any

from tilaucore.ror import RoRSettings, rate_of_rise, window_for


def ror_settings(qmc: Any) -> RoRSettings:
    """The smoothing level and the RoR limits of Artisan's canvas."""
    return RoRSettings(window_s=window_for(qmc.deltaBTspan, qmc.deltaBTfilter), limit=qmc.RoRlimitFlag,
                       limit_min=max(-qmc.maxRoRlimit, qmc.RoRlimitm), limit_max=min(qmc.maxRoRlimit, qmc.RoRlimit))


def recompute_deltas(qmc: Any, timex: Any, charge_idx: int, drop_idx: int, et: Any,
                     bt: Any) -> tuple[list[float | None] | None, list[float | None]]:
    """(ET rate or None when no ET is given, BT rate) between CHARGE and DROP, the whole roast when unmarked."""
    settings, times = ror_settings(qmc), list(timex)
    start, end = (charge_idx if charge_idx > -1 else 0), (drop_idx if drop_idx > 0 else None)
    return (None if et is None else rate_of_rise(times, list(et), settings, start, end),
            rate_of_rise(times, list(bt), settings, start, end))

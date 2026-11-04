# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The rate of rise TilauScope draws and reads, computed by tilaucore with the RoR
settings of Artisan's canvas: one standard method, whatever variant Artisan offers.

The rate Artisan computes while sampling, and the one it saves in a roast file,
stay Artisan's own.
"""

from __future__ import annotations

from typing import Any

from tilaucore.artisan_compat import RoRSettings
from tilaucore.artisan_compat import recompute_deltas as _recompute_deltas


def ror_settings(qmc: Any) -> RoRSettings:
    """The RoR settings of Artisan's canvas."""
    return RoRSettings(curvefilter=qmc.curvefilter, interpolate_drops=qmc.interpolateDropsflag,
                       delta_samples=qmc.deltaBTsamples, delta_filter=qmc.deltaBTfilter,
                       median_filter_factor=qmc.median_filter_factor_RoR, filter_dropouts=qmc.filterDropOuts,
                       limit=qmc.RoRlimitFlag, limit_min=max(-qmc.maxRoRlimit, qmc.RoRlimitm),
                       limit_max=min(qmc.maxRoRlimit, qmc.RoRlimit),
                       et_delta_samples=qmc.deltaETsamples, et_delta_filter=qmc.deltaETfilter)


def recompute_deltas(qmc: Any, timex: Any, charge_idx: int, drop_idx: int, et: Any, bt: Any,
                     et_samples: int | None = None,
                     bt_samples: int | None = None) -> tuple[list[float | None] | None, list[float | None]]:
    """qmc.recomputeDeltas, standard method, with the canvas's settings."""
    return _recompute_deltas(list(timex), charge_idx, drop_idx, None if et is None else list(et), list(bt),
                             ror_settings(qmc), bool(getattr(qmc, 'flagon', False)), et_samples, bt_samples)

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

"""Temperature-unit boundaries of the post-roast review panel."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def test_peak_ror_is_normalized_from_the_live_fahrenheit_mode(qapp: Any) -> None:  # noqa: ARG001
    from tilauscope.roast_review_panel import RoastReviewPanel

    qmc = SimpleNamespace(
        mode='F',
        timex=[0.0, 1.0, 2.0],
        temp2=[350.0, 351.0, 352.0],
        stemp2=[],
        timeindex=[0, 0, 0, 0, 0, 0, 2, 0],
        TPalarmtimeindex=0,
        optimalSmoothing=True,
        recomputeDeltas=lambda *_args, **_kwargs: ([], [None, 18.0, 36.0]),
    )
    panel = SimpleNamespace(aw=SimpleNamespace(qmc=qmc))

    peak_c = RoastReviewPanel._peak_ror(panel)

    assert peak_c == pytest.approx(20.0)

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

"""Identity and invalidation contracts for the fallback RoR cache."""

from __future__ import annotations

from typing import Any


class _Profile:
    def __init__(self, ror: float) -> None:
        # Both profiles deliberately have the exact structural key used by the
        # former cache: same length, endpoints, CHARGE and DROP.
        self.timex = [0.0, 1.0, 2.0]
        self.timeindex = [0, 0, 0, 0, 0, 0, 0, 0]
        self.stemp1 = [100.0, 101.0, 102.0]
        self.stemp2 = [150.0, 151.0, 152.0]
        self.delta1: list[float] = []
        self.delta2: list[float] = []
        self.ror = ror
        self.recomputations = 0

    def recomputeDeltas(self, *_args: Any) -> tuple[list[float], list[float]]:  # noqa: N802 - Artisan API
        self.recomputations += 1
        values = [self.ror] * len(self.timex)
        return values, values


def test_equal_shape_profiles_do_not_share_the_fallback_ror() -> None:
    from tilauscope.graph.common import reset_rise_cache, rise_series

    reset_rise_cache()
    first = _Profile(2.0)
    second = _Profile(8.0)

    assert rise_series(first) == [2.0, 2.0, 2.0]
    assert rise_series(second) == [8.0, 8.0, 8.0]
    assert first.recomputations == 1
    assert second.recomputations == 1


def test_replacing_temperature_arrays_invalidates_the_same_profile_cache() -> None:
    from tilauscope.graph.common import reset_rise_cache, rise_series

    reset_rise_cache()
    profile = _Profile(3.0)
    assert rise_series(profile) == [3.0, 3.0, 3.0]

    profile.ror = 7.0
    profile.stemp1 = list(profile.stemp1)
    profile.stemp2 = list(profile.stemp2)

    assert rise_series(profile) == [7.0, 7.0, 7.0]
    assert profile.recomputations == 2

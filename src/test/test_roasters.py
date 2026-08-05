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

"""Roaster / RoasterContext coverage for maillard_ror_decay.

Pure model-layer tests (no Qt, no I/O beyond reading the shipped
roasters.json), mirroring the heater_max_pct precedent.
"""

from __future__ import annotations

from tilauscope.roasters import Roaster, RoasterContext, RoasterManager, RoasterType, HeatingType


def _minimal_roaster(**overrides) -> Roaster:
    """A bare-minimum Roaster with only the required fields filled in."""
    defaults = {
        'manufacturer': 'Test',
        'model': 'Bench',
        'roaster_type': RoasterType.DRUM,
        'heating_type': HeatingType.ELECTRIC,
        'technology': [],
        'batch_capacity_min_g': 100,
        'batch_capacity_max_g': 500,
    }
    defaults.update(overrides)
    return Roaster(**defaults)


def test_maillard_ror_decay_defaults_to_two_when_undeclared():
    roaster = _minimal_roaster()
    ctx = RoasterContext.from_roaster(roaster)
    assert ctx.maillard_ror_decay == 2.0


def test_maillard_ror_decay_carries_through_when_declared():
    roaster = _minimal_roaster(maillard_ror_decay=3.0)
    ctx = RoasterContext.from_roaster(roaster)
    assert ctx.maillard_ror_decay == 3.0


def test_every_roasters_json_entry_declares_a_decay_consistent_with_its_technology():
    manager = RoasterManager()
    manager.load_json(RoasterManager._DEFAULT_JSON)
    assert manager.roasters, 'roasters.json produced no entries'
    for roaster in manager.roasters:
        expected = 2.0 if roaster.is_radiant_electric else 3.0
        assert roaster.maillard_ror_decay == expected, (
            f'{roaster.manufacturer} {roaster.model}: '
            f'maillard_ror_decay={roaster.maillard_ror_decay!r} '
            f'inconsistent with is_radiant_electric={roaster.is_radiant_electric!r}'
        )

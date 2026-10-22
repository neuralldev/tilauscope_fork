#
# ABOUT
# Beancave

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

# The roasters and their plan context live in the library shared with the tablet;
# this module mirrors the configured one into Artisan.

from typing import Any, Final
import logging

from tilaucore.roasters import *  # noqa: F403  pylint: disable=wildcard-import,unused-wildcard-import
from tilaucore.roasters import HeatingType, RoasterContext, RoasterManager

_logd: Final[logging.Logger] = logging.getLogger('tilau')
# ============================================================
# QMC SYNC — push the TilauScope-configured roaster into Artisan
# ============================================================

# HeatingType -> qmc.roasterheating code (0: ??, 1: LPG, 2: NG, 3: Elec)
_QMC_HEATING_CODE: dict[HeatingType, int] = {
    HeatingType.GAS: 2,
    HeatingType.ELECTRIC: 3,
    HeatingType.INFRARED: 3,
    HeatingType.INDUCTION: 3,
    HeatingType.HYBRID: 3,
    HeatingType.WOOD: 0,
    HeatingType.COAL: 0,
}


def sync_roaster_to_qmc(aw: object, name: str | None) -> bool:
    """Single call site to mirror the TilauScope-configured
    roaster (aw.tilau_roaster) into Artisan's Machine-setup qmc fields
    (roastertype_setup/roastersize_setup/roasterheating_setup/machinesetup),
    so the canvas x-axis label / stats annotation (built from those _setup
    fields, see canvas.py default_xlabel_text/buildStat) reflect the roaster
    picked in TilauScope config instead of a stale manual Artisan setup.
    No-op if *name* is empty or not found in the registry, or if qmc is
    mid-roast (never rewrite an in-progress roast's machine identity).
    Returns True if qmc was updated."""
    if not name:
        return False
    qmc = getattr(aw, 'qmc', None)
    if qmc is None or getattr(qmc, 'flagstart', False):
        return False

    manager = RoasterManager()
    roaster = manager.get_by_display_name(name)
    ctx = manager.get_roast_context(name)
    if roaster is None or ctx is None:
        return False

    qmc.roastertype_setup = ctx.display_name
    qmc.machinesetup = ctx.display_name

    batch_g = ctx.batch_max_g   # Artisan's machine capacity, the key of its energy defaults
    if batch_g:
        kg = batch_g / 1000.0
        qmc.roastersize_setup = kg
        qmc.roastersize_setup_default = kg

    heating_code = _QMC_HEATING_CODE.get(roaster.heating_type, 0)
    qmc.roasterheating_setup = heating_code
    qmc.roasterheating_setup_default = heating_code

    # mirror into the live (non-"_setup") fields too: they only get copied
    # from *_setup at CHARGE otherwise, and the canvas label reads *_setup
    # directly, but stats annotation (buildStat n==5) reads the live field.
    qmc.roastertype = qmc.roastertype_setup
    qmc.roastersize = qmc.roastersize_setup
    qmc.roasterheating = qmc.roasterheating_setup

    try:
        qmc.redraw()
    except Exception:
        _logd.exception('TilauScope: sync_roaster_to_qmc redraw failed')

    return True


def sync_operator_to_qmc(aw: object, name: str) -> None:
    """Write the operator's name into Artisan's setup default (persisted with
    the settings, copied into each new roast) and into the current roast,
    unless one is recording."""
    qmc = getattr(aw, 'qmc', None)
    if qmc is None:
        return
    qmc.operator_setup = name.strip()
    if not getattr(qmc, 'flagstart', False):
        qmc.operator = qmc.operator_setup


# ============================================================
# ROAST CONTEXT RESOLUTION (single owner of the aw-level cache)
# ============================================================

#: Marks "nothing resolved yet" — distinct from the empty name (no roaster),
#: which is a legitimate cached result.
_NO_CACHED_NAME: Final[object] = object()


def roast_context_for(aw: Any, name: str | None = None) -> RoasterContext | None:
    """Single resolver for the selected roaster's context, cached on *aw*.

    Sole writer of ``aw._tilau_roast_context``, ``aw._tilau_inlet_air_mode`` and
    ``aw._tilau_has_et``:
    every reader goes through here, so a roaster change in Devices can never
    leave two components reasoning on two different machines.

    *name* defaults to ``aw.tilau_roaster``. The empty string and the literal
    ``'None'`` both mean "no roaster" and resolve to None, as does an unknown
    name. The resolution is cached together with the name it was made for, so
    a None result is cached too and roasters.json is read once per selection.
    Never raises: a missing or broken registry yields None.
    """
    if name is None:
        name = str(getattr(aw, 'tilau_roaster', '') or '')
    name = str(name or '')
    if name == 'None':
        name = ''

    if getattr(aw, '_tilau_roast_context_name', _NO_CACHED_NAME) == name:
        return getattr(aw, '_tilau_roast_context', None)

    context: RoasterContext | None = None
    if name:
        try:
            context = RoasterManager(name).get_roast_context()
        except Exception:  # pylint: disable=broad-except
            _logd.exception('TilauScope: roaster context lookup failed for %r', name)
            context = None

    aw._tilau_roast_context = context
    aw._tilau_roast_context_name = name
    # Inlet air path (push/pull) for the pull-aware advice; no roaster = push.
    aw._tilau_inlet_air_mode = (
        getattr(context, 'inlet_air_mode', 'push') if context is not None else 'push')
    # ET stays shown unless the machine is declared without the probe.
    aw._tilau_has_et = getattr(context, 'has_et_probe', None) is not False
    return context


def invalidate_roast_context(aw: Any) -> None:
    """Drop the cached resolution so the next roast_context_for() re-resolves."""
    aw._tilau_roast_context_name = _NO_CACHED_NAME

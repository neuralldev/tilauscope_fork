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


"""Bluetooth roast colour meter registry.

Each supported colour meter family is described once here. The Settings dialog
detects meters through this registry, and every screen that reads a colour
builds its driver through create_color_meter(). Adding a brand = one driver
module + one entry.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from tilauscope.colormeters.base import ColorMeter

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

MODEL_SETTINGS_KEY: Final[str] = "tilauscope/color_meter_model"
DEFAULT_MODEL_KEY: Final[str] = "lebrew_c1"   # the only model before the registry existed

OMNI_SERVICE_UUID: Final[str] = "000000e0-0000-1000-8000-00805f9b34fb"

# Name fragments that flag a nearby device as a possible colour meter the
# registry does not recognise (diagnostic log only).
_CANDIDATE_HINTS: Final[tuple[str, ...]] = ("omni", "difluid", "lighttells", "cm-", "roastsee c")


class SampleBasis(StrEnum):
    WHOLE = "whole"
    GROUND = "ground"


@dataclass(frozen=True)
class ColorReading:
    value: float                # on the Agtron scale the device reports
    basis: SampleBasis | None   # None = the device does not say, the screen asks


@dataclass(frozen=True)
class ColorMeterModel:
    key: str                        # stable, persisted under MODEL_SETTINGS_KEY
    name_prefixes: tuple[str, ...]  # advertised BLE name prefixes
    detect_uuid: str | None         # detection fallback when the name is missing or unknown
    factory: "Callable[[str], ColorMeter]"   # address -> connected-on-creation driver


def _c1(address: str) -> "ColorMeter":
    from tilauscope.lebrewroastsee import LebrewColorChecker
    return LebrewColorChecker(address)


def _omni(address: str) -> "ColorMeter":
    from tilauscope.colormeters.difluid_omni import DifluidOmni
    return DifluidOmni(address)


COLOR_METER_MODELS: Final[tuple[ColorMeterModel, ...]] = (
    # same prefix as lebrewroastsee.C1_PREFIX (kept in sync by test_colormeter_registry)
    ColorMeterModel("lebrew_c1", ("RoastSee C1",), None, _c1),
    # advertised name not documented: detected by its product-specific service UUID
    ColorMeterModel("difluid_omni", (), OMNI_SERVICE_UUID, _omni),
)


def model_for_advertisement(name: str | None, service_uuids: list[str] | None) -> ColorMeterModel | None:
    """The registered model matching an advertisement: name prefix first, then service UUID."""
    if name:
        for m in COLOR_METER_MODELS:
            if any(name.startswith(p) for p in m.name_prefixes):
                return m
    uuids = {u.casefold() for u in (service_uuids or [])}
    for m in COLOR_METER_MODELS:
        if m.detect_uuid is not None and m.detect_uuid.casefold() in uuids:
            return m
    return None


def match_rule(model: ColorMeterModel, name: str | None) -> str:
    """Which rule matched, for the detection log: 'prefix' or 'service'."""
    if name and any(name.startswith(p) for p in model.name_prefixes):
        return "prefix"
    return "service"


def is_color_meter_candidate(name: str | None) -> bool:
    """True for a device whose name hints at a colour meter (unrecognised-candidate log)."""
    low = (name or "").casefold()
    return any(h in low for h in _CANDIDATE_HINTS)


def model_by_key(key: str | None) -> ColorMeterModel | None:
    return next((m for m in COLOR_METER_MODELS if m.key == key), None)


def all_prefixes() -> tuple[str, ...]:
    return tuple(p for m in COLOR_METER_MODELS for p in m.name_prefixes)


def configured_model_key() -> str:
    """The model of the configured colour meter; the C1 when none was ever stored."""
    from PyQt6.QtCore import QSettings
    return QSettings().value(MODEL_SETTINGS_KEY, DEFAULT_MODEL_KEY, type=str) or DEFAULT_MODEL_KEY


def store_model_key(key: str) -> None:
    from PyQt6.QtCore import QSettings
    QSettings().setValue(MODEL_SETTINGS_KEY, key)


def create_color_meter(key: str | None, address: str) -> "ColorMeter | None":
    """Build and start the driver of a colour meter model; None for an unknown key."""
    m = model_by_key(key)
    if m is None:
        _log.warning("colormeters: no driver for model key %s", key)
        return None
    _logd.debug("[%s] create_color_meter address=%s", m.key, address)
    return m.factory(address)

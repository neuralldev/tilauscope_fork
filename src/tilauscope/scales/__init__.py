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

"""Bluetooth scale registry.

Each supported scale family is described once here. The Settings dialog detects
scales through this registry, and Artisan's ScaleManager builds the TilauScope
drivers through create_scale(). Adding a brand = one driver module + one entry.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.scale import Scale

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

DECENT_SERVICE_UUID: Final[str] = "0000fff0-0000-1000-8000-00805f9b34fb"
BOOKOO_SERVICE_UUID: Final[str] = "00000ffe-0000-1000-8000-00805f9b34fb"

# Name fragments that flag a nearby device as a possible scale the registry
# does not recognise (diagnostic log only).
_CANDIDATE_HINTS: Final[tuple[str, ...]] = ("scale", "decent", "bookoo")


@dataclass(frozen=True)
class ScaleModel:
    key: str                        # stable, never renumbered
    model_id: int                   # persisted in aw.scale1_model; TilauScope ids start at 100
    name_prefixes: tuple[str, ...]  # advertised BLE name prefixes
    detect_uuid: str | None         # detection fallback when the name is missing or truncated;
                                    # None when the service UUID is generic (Decent FFF0 = Santoker R too)
    factory: "Callable[[int, str, str, Callable[[], None], Callable[[], None]], Scale] | None"
                                    # None = built by Artisan itself (Acaia)


def _decent(model_id: int, ident: str, name: str,
            connected_handler: Callable[[], None],
            disconnected_handler: Callable[[], None]) -> "Scale":
    from tilauscope.scales.base import TilauBLEScale
    from tilauscope.scales.decent import DecentBLE
    return TilauBLEScale(model_id, ident, name, DecentBLE(), connected_handler, disconnected_handler)


def _bookoo(model_id: int, ident: str, name: str,
            connected_handler: Callable[[], None],
            disconnected_handler: Callable[[], None]) -> "Scale":
    from tilauscope.scales.base import TilauBLEScale
    from tilauscope.scales.bookoo import BookooBLE
    return TilauBLEScale(model_id, ident, name, BookooBLE(), connected_handler, disconnected_handler)


def _acaia_prefixes() -> tuple[str, ...]:
    try:
        from artisanlib.acaia import ACAIA_SCALE_NAMES
        return tuple(prefix for prefix, _product in ACAIA_SCALE_NAMES)
    except Exception:  # pylint: disable=broad-except
        return ("ACAIAS-P", "ACAIA", "LUNAR-", "PROCHBT", "PEARLS", "PEARL-",
                "CINCO", "PYXIS", "UMBRA", "COSMO-10", "COSMO-100")


SCALE_MODELS: Final[tuple[ScaleModel, ...]] = (
    ScaleModel("acaia",  0,   _acaia_prefixes(), None,                None),
    ScaleModel("decent", 100, ("Decent Scale",), None,                _decent),
    ScaleModel("bookoo", 101, ("BOOKOO_SC",),    BOOKOO_SERVICE_UUID, _bookoo),
)


def model_for_advertisement(name: str | None, service_uuids: list[str] | None) -> ScaleModel | None:
    """The registered model matching an advertisement: name prefix first, then service UUID."""
    if name:
        for m in SCALE_MODELS:
            if any(name.startswith(p) for p in m.name_prefixes):
                return m
    uuids = {u.casefold() for u in (service_uuids or [])}
    for m in SCALE_MODELS:
        if m.detect_uuid is not None and m.detect_uuid.casefold() in uuids:
            return m
    return None


def match_rule(model: ScaleModel, name: str | None) -> str:
    """Which rule matched, for the detection log: 'prefix' or 'service'."""
    if name and any(name.startswith(p) for p in model.name_prefixes):
        return "prefix"
    return "service"


def is_scale_candidate(name: str | None) -> bool:
    """True for a device whose name hints at a scale (unrecognised-candidate log)."""
    low = (name or "").casefold()
    return any(h in low for h in _CANDIDATE_HINTS)


def model_by_id(model_id: int | None) -> ScaleModel | None:
    return next((m for m in SCALE_MODELS if m.model_id == model_id), None)


def all_prefixes() -> tuple[str, ...]:
    return tuple(p for m in SCALE_MODELS for p in m.name_prefixes)


def create_scale(model_id: int, ident: str, name: str,
                 connected_handler: Callable[[], None],
                 disconnected_handler: Callable[[], None]) -> "Scale | None":
    """Build the driver of a TilauScope scale model; None for an unknown id."""
    m = model_by_id(model_id)
    if m is None or m.factory is None:
        _log.warning("scales: no TilauScope driver for model id %s", model_id)
        return None
    _logd.debug("[%s] create_scale id=%s ident=%s name=%s", m.key, model_id, ident, name)
    return m.factory(model_id, ident, name, connected_handler, disconnected_handler)

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The settings BeanCave alone keeps for itself (wiki/BeanCave-Standalone-Spec.md §11).

TilauScope's Artisan window loads and saves its device choices; BeanCave alone has
no such window, so the stand-in does it here, under the same keys and groups as
TilauScope. On first launch they are taken over from TilauScope when it is
installed: afterwards each application keeps its own.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from PyQt6.QtCore import QSettings

_log = logging.getLogger(__name__)

# macOS: Core Bluetooth UUID — Windows: MAC address (as TilauScope's settings load).
_BLE_ID: Final = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})$")

#: Window attribute <- key in the Device group, a Bluetooth identifier each.
_DEVICES: Final[dict[str, str]] = {
    'bleTilauScopeDeviceName': 'tilauscopeamb',
    'bleRoastSeeDeviceName': 'lbrsc1',
    'bleRoastSeeAGDeviceName': 'lbrsag',
    'bleNiimbotDeviceName': 'niimbot',
}
_SCALE: Final[tuple[str, ...]] = ('scale1_model', 'scale1_id', 'scale1_name')

#: Everything taken over from TilauScope on first launch.
_TAKEN_OVER: Final[tuple[str, ...]] = (
    *(f'Device/{key}' for key in _DEVICES.values()),
    'Device/tilaumqttbridge', 'Device/tilauai',
    *(f'Scales/{key}' for key in _SCALE),
    'mqtt/sensors', 'tilauscope/label_size_mm', 'tilauscope/currency', 'tilauscope/color_meter_model',
)


def tilauscope_settings() -> QSettings:
    """TilauScope's own settings on this computer (empty when it was never run).
    Qt names them by organisation domain on macOS, by organisation name elsewhere."""
    import platform  # noqa: PLC0415
    return QSettings('tilauscope.org' if platform.system() == 'Darwin' else 'TilauScope', 'TilauScope')


def take_over(own: QSettings, tilauscope: QSettings) -> list[str]:
    """Copy TilauScope's device and integration choices BeanCave does not have yet."""
    taken = []
    for key in _TAKEN_OVER:
        if tilauscope.contains(key) and not own.contains(key):
            own.setValue(key, tilauscope.value(key))
            taken.append(key)
    if taken:
        _log.info('settings taken over from TilauScope: %s', ', '.join(taken))
    return taken


def load(window: Any, settings: QSettings) -> None:
    """Device choices onto the stand-in window, as TilauScope's settings load puts them on Artisan's."""
    for attr, key in _DEVICES.items():
        value = str(settings.value(f'Device/{key}', '') or '')
        setattr(window, attr, value if _BLE_ID.match(value) else None)
    model = settings.value('Scales/scale1_model', None)
    try:
        window.scale1_model = int(model) if model not in (None, '') else None
    except (TypeError, ValueError):
        window.scale1_model = None
    window.scale1_id = settings.value('Scales/scale1_id', None) or None
    window.scale1_name = settings.value('Scales/scale1_name', None) or None


def save(window: Any, settings: QSettings) -> None:
    """What the settings window chose, back under TilauScope's keys."""
    for attr, key in _DEVICES.items():
        settings.setValue(f'Device/{key}', getattr(window, attr, None) or '')
    for key in _SCALE:
        value = getattr(window, key, None)
        if value is None:
            settings.remove(f'Scales/{key}')
        else:
            settings.setValue(f'Scales/{key}', value)
    settings.setValue('Device/tilaumqttbridge', window.mqttConfig.to_dict())
    settings.setValue('Device/tilauai', window.tilau_aiConfig.to_dict())
    settings.setValue('tilauscoperoaster', getattr(window, 'tilau_roaster', '') or '')
    settings.sync()

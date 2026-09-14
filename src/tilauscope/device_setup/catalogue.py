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

"""What the Devices window offers: every Artisan meter, and extra devices by use.

Devices are named by their registry label and turned into an id only when
needed. TilauScope's ids are positional (``device_registry.TILAU_DEVICES``), so
a literal id here would silently point at another device after an upstream
addition.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from PyQt6.QtCore import QT_TRANSLATE_NOOP

from artisanlib.device_registry import (DEVICE_ID_NONE, DEVICES, TILAU_DEVICES,
                                        get_device_id, get_device_name,
                                        is_non_serial_device)
from tilauscope.device_setup.artisan_defaults import METER_BRANCHES

TC4_DEVICE_ID: Final[int] = 19

#: The roaster meters TilauScope supports, listed first.
PINNED_METERS: Final[tuple[str, ...]] = ('Skywalker V2', 'SkyCommand V1', 'TRP Roaster (BT/ET)')

#: Meters linked over Bluetooth in TilauScope Config › Sensors — no port here.
BLUETOOTH_METERS: Final[frozenset[str]] = frozenset({'Skywalker V2', 'SkyCommand V1'})

#: Meters connected through Artisan's port dialog (its Modbus, S7 and WebSocket
#: tabs). They are not in NON_SERIAL_DEVICES, so they have to be named.
PORT_DIALOG_METERS: Final[frozenset[str]] = frozenset({'MODBUS', 'S7', 'WebSocket'})


@lru_cache(maxsize=1)
def meter_names() -> tuple[str, ...]:
    """Every meter Artisan's own list shows and its meter chain acts on, sorted as Artisan lists them.

    The chain keeps branches for retired meters, some writing an id Artisan now
    gives another device; its list hides them, and so does this one.
    """
    listed = {name for name in DEVICES if not name.startswith(('+', '-'))}
    tilau = {d['label'] for d in TILAU_DEVICES.values()}
    return tuple(sorted((set(METER_BRANCHES) | tilau) & listed))


def meter_name_of(device_id: int) -> str | None:
    """The Meter-list name of ``device_id``, or None when the list cannot show it."""
    if device_id < 1:   # get_device_name(0) would read the first entry of the list
        return None
    name = get_device_name(device_id)
    if name not in meter_names():
        return None
    return name if get_device_id(name) == device_id else None


def meter_uses_usb_port(name: str | None) -> bool:
    """Whether choosing ``name`` means choosing the port ``aw.ser`` opens."""
    if not name or name in PORT_DIALOG_METERS:
        return False
    try:
        device_id = get_device_id(name)
    except ValueError:
        return False
    return device_id != DEVICE_ID_NONE and not is_non_serial_device(device_id)


# ── extra devices ────────────────────────────────────────────────────────────

GROUP_HARDWARE: Final[str] = QT_TRANSLATE_NOOP('tilauscope_devices', 'TilauScope hardware')
GROUP_CONTROLS: Final[str] = QT_TRANSLATE_NOOP('tilauscope_devices', 'Roaster controls')
GROUP_TC4: Final[str] = QT_TRANSLATE_NOOP('tilauscope_devices', 'TC4 board')
GROUP_NETWORK: Final[str] = QT_TRANSLATE_NOOP('tilauscope_devices', 'Network')
GROUP_CALCULATED: Final[str] = QT_TRANSLATE_NOOP('tilauscope_devices', 'Calculated')

GROUPS: Final[tuple[str, ...]] = (GROUP_HARDWARE, GROUP_CONTROLS, GROUP_TC4,
                                  GROUP_NETWORK, GROUP_CALCULATED)


@dataclass(frozen=True)
class ExtraKind:
    """One entry of the Add a device menu: an Artisan extra device and its defaults."""

    key: str
    label: str                    # registry label, '+' included when it has one
    title: str                    # QT_TRANSLATE_NOOP literal: card title and menu entry
    group: str
    names: tuple[str, str]        # default channel names; '' marks a channel the device leaves unused
    show: tuple[bool, bool]       # default "Show counter" per channel
    requires: str | None = None   # key of a device that has to be declared before this one

    def device_id(self) -> int:
        return get_device_id(self.label)


# Channel names are what TilauScope reads a channel by: TLFC classifies as the
# crack counter (tilauscope_types.classify_extra_channel), {3}/{0} are the
# burner and air event names Artisan substitutes (the Skywalker machine preset).
EXTRA_KINDS: Final[tuple[ExtraKind, ...]] = (
    ExtraKind('airwave', 'Difluid AirWave',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'Difluid AirWave — inlet & catalyst'),
              GROUP_HARDWARE, ('Inlet', 'Catalyst'), (True, False)),
    ExtraKind('tilau12', 'TilauScope Ambient 12',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TilauAmbient — temperature & humidity'),
              GROUP_HARDWARE, ('Room temp', 'Humidity'), (False, False)),
    # TILAUSCOPE34 re-reads the block TILAUSCOPE12 fetched (comm.py)
    ExtraKind('tilau34', 'TilauScope Ambient 34',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TilauAmbient — pressure & altitude'),
              GROUP_HARDWARE, ('Pressure', 'Altitude'), (False, False), requires='tilau12'),
    ExtraKind('tilau56', 'TilauScope Ambient 56',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TilauAmbient — crack counter'),
              GROUP_HARDWARE, ('TLFC', ''), (True, False)),
    ExtraKind('skywalker_pf', '+Skywalker V2 (Burner/Airflow)',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'Skywalker V2 — burner & airflow'),
              GROUP_CONTROLS, ('{3}', '{0}'), (True, True)),
    ExtraKind('skycommand_pf', '+SkyCommand V1 (Burner/Airflow)',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'SkyCommand V1 — burner & airflow'),
              GROUP_CONTROLS, ('{3}', '{0}'), (True, True)),
    ExtraKind('trp_hf', '+TRP Roaster (Heater/Fan)',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TRP Roaster — heater & fan'),
              GROUP_CONTROLS, ('{3}', '{0}'), (True, True)),
    ExtraKind('tc4_34', '+ArduinoTC4 34',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TC4 board — channels 3 & 4'),
              GROUP_TC4, ('T3', 'T4'), (True, True)),
    ExtraKind('tc4_56', '+ArduinoTC4 56',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TC4 board — channels 5 & 6'),
              GROUP_TC4, ('T5', 'T6'), (True, True)),
    ExtraKind('tc4_78', '+ArduinoTC4 78',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'TC4 board — channels 7 & 8'),
              GROUP_TC4, ('T7', 'T8'), (True, True)),
    ExtraKind('mqtt12', 'TilauScope MQTT 12',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'MQTT sensors 1 & 2'),
              GROUP_NETWORK, ('MQTT 1', 'MQTT 2'), (True, True)),
    ExtraKind('mqtt34', 'TilauScope MQTT 34',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'MQTT sensors 3 & 4'),
              GROUP_NETWORK, ('MQTT 3', 'MQTT 4'), (True, True)),
    ExtraKind('mqtt56', 'TilauScope MQTT 56',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'MQTT sensors 5 & 6'),
              GROUP_NETWORK, ('MQTT 5', 'MQTT 6'), (True, True)),
    ExtraKind('mqtt78', 'TilauScope MQTT 78',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'MQTT sensors 7 & 8'),
              GROUP_NETWORK, ('MQTT 7', 'MQTT 8'), (True, True)),
    ExtraKind('mqtt910', 'TilauScope MQTT 910',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'MQTT sensors 9 & 10'),
              GROUP_NETWORK, ('MQTT 9', 'MQTT 10'), (True, True)),
    ExtraKind('virtual', '+Virtual',
              QT_TRANSLATE_NOOP('tilauscope_devices', 'Calculated channels'),
              GROUP_CALCULATED, ('Extra 1', 'Extra 2'), (True, True)),
)

#: Where TilauAmbient puts room conditions, as (catalogue key, channel). Artisan
#: reads an extra device as ``extratx, extrat2, extrat1`` (canvas.py), and
#: TILAUSCOPE12 returns (humidity, temperature), TILAUSCOPE34 (altitude, pressure).
TILAUAMBIENT_SOURCES: Final[dict[str, tuple[str, int]]] = {
    'temperature': ('tilau12', 1),
    'humidity':    ('tilau12', 2),
    'pressure':    ('tilau34', 1),
}


def kind_title(kind: ExtraKind) -> str:
    """The card title in the chosen language — the literal is declared above."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.translate('tilauscope_devices', kind.title)


def group_title(group: str) -> str:
    from PyQt6.QtWidgets import QApplication
    return QApplication.translate('tilauscope_devices', group)


def kind_by_key(key: str) -> ExtraKind:
    return next(kind for kind in EXTRA_KINDS if kind.key == key)


def kind_of(device_id: int) -> ExtraKind | None:
    for kind in EXTRA_KINDS:
        try:
            if kind.device_id() == device_id:
                return kind
        except ValueError:
            continue
    return None


def device_title(device_id: int) -> str:
    """Artisan's name for a device outside the catalogue, '+' dropped."""
    name = get_device_name(device_id)
    return name[1:] if name.startswith('+') else name


@lru_cache(maxsize=1)
def artisan_extra_names() -> tuple[str, ...]:
    """What Artisan's extra-device table offers: no '-' device, no NONE, '+' dropped."""
    names = (d[1:] if d.startswith('+') else d
             for d in DEVICES if not d.startswith('-') and d != 'NONE')
    return tuple(sorted(set(names)))


def extra_device_id(name: str) -> int:
    """The id behind an ``artisan_extra_names()`` entry (the '+' put back if needed)."""
    try:
        return get_device_id(name)
    except ValueError:
        return get_device_id(f'+{name}')

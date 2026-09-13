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

"""The Devices window's working copy, and the one place it is written to Artisan.

The window edits a ``DeviceDraft``; nothing reaches ``aw`` until ``apply``. That
is what makes Cancel mean "nothing happened" — Artisan's own dialog writes
colours, visibilities, additions and removals as you click, and its Cancel
undoes none of them.

A row is a device together with what was recorded through it. Moving a row
moves its readings; changing its device only changes what Artisan believes it
is — the fix for a roast saved under an older device numbering, where every
reading is right and only the device types are wrong. Ambient sources point at a
row, not at an index, so moving or removing a device cannot make a source slide
onto its neighbour.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from tilauscope.device_setup import artisan_mirror as mirror
from tilauscope.device_setup.catalogue import (TC4_DEVICE_ID, TILAUAMBIENT_SOURCES,
                                               kind_by_key, kind_of, meter_name_of,
                                               meter_uses_usb_port)

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

AMBIENT_KEYS: Final[tuple[str, ...]] = ('temperature', 'humidity', 'pressure')
_SOURCE_ATTR: Final[dict[str, str]] = {
    'temperature': 'ambientTempSource',
    'humidity': 'ambientHumiditySource',
    'pressure': 'ambientPressureSource',
}
_HARDWARE_ATTR: Final[dict[str, str]] = {
    'temperature': 'ambient_temperature_device',
    'humidity': 'ambient_humidity_device',
    'pressure': 'ambient_pressure_device',
}
#: Artisan's ambient source index: 0 none, 1 ET, 2 BT, then two per extra device.
FIRST_EXTRA_SOURCE: Final[int] = 3
#: The names Artisan gives a channel it knows nothing about.
_PLACEHOLDER_NAMES: Final[frozenset[str]] = frozenset({'', 'Extra 1', 'Extra 2'})

_uids = itertools.count(1)

#: An ambient source: a (row uid, channel) pair, or a raw index kept as it was.
Source = tuple[int, int] | int


@dataclass
class ExtraRow:
    device_id: int
    names: list[str]
    show: list[bool]
    origin: int | None = None   # index in qmc.extradevices when the window opened
    uid: int = field(default_factory=lambda: next(_uids))

    @property
    def kind_key(self) -> str | None:
        kind = kind_of(self.device_id)
        return kind.key if kind is not None else None


@dataclass
class DeviceDraft:
    device: int            # qmc.device when the window opened
    mode: str              # 'meter', 'tc4', or 'other' for a PID or Program left untouched
    meter: str | None
    comport: str
    tc4_channels: list[str]   # ET, BT, AT
    tc4_filter: list[int]
    pid_firmware: bool
    rows: list[ExtraRow]
    ambient: dict[str, Source]
    ambient_hardware: dict[str, int]   # non-zero: Artisan's own sensor feeds it


def snapshot(aw: 'ApplicationWindow') -> DeviceDraft:
    qmc = aw.qmc
    rows = [ExtraRow(device_id=qmc.extradevices[i],
                     names=[qmc.extraname1[i], qmc.extraname2[i]],
                     show=[bool(aw.extraLCDvisibility1[i]), bool(aw.extraLCDvisibility2[i])],
                     origin=i)
            for i in range(len(qmc.extradevices))]
    ambient: dict[str, Source] = {}
    for key in AMBIENT_KEYS:
        index = int(getattr(qmc, _SOURCE_ATTR[key]))
        slot = (index - FIRST_EXTRA_SOURCE) // 2
        if index >= FIRST_EXTRA_SOURCE:
            # out of range reads as none, as Artisan's dialog resets it
            ambient[key] = (rows[slot].uid, 1 if index % 2 else 2) if slot < len(rows) else 0
        else:
            ambient[key] = index
    meter = meter_name_of(qmc.device)
    mode = 'tc4' if qmc.device == TC4_DEVICE_ID else 'meter' if meter is not None else 'other'
    return DeviceDraft(
        device=qmc.device, mode=mode, meter=meter, comport=str(aw.ser.comport),
        tc4_channels=[aw.ser.arduinoETChannel, aw.ser.arduinoBTChannel, aw.ser.arduinoATChannel],
        tc4_filter=[int(v) for v in aw.ser.ArduinoFILT],
        pid_firmware=bool(qmc.PIDbuttonflag),
        rows=rows, ambient=ambient,
        ambient_hardware={key: int(getattr(qmc, _HARDWARE_ATTR[key])) for key in AMBIENT_KEYS},
    )


def is_stale(aw: 'ApplicationWindow', original: DeviceDraft) -> bool:
    """Artisan's devices changed under the open window — loading a roast file does that."""
    return (aw.qmc.device != original.device
            or list(aw.qmc.extradevices) != [row.device_id for row in original.rows])


def uses_usb_port(draft: DeviceDraft) -> bool:
    return draft.mode == 'tc4' or (draft.mode == 'meter' and meter_uses_usb_port(draft.meter))


# ── editing rows ─────────────────────────────────────────────────────────────

def row_index(draft: DeviceDraft, uid: int) -> int | None:
    return next((i for i, row in enumerate(draft.rows) if row.uid == uid), None)


def new_row(device_id: int) -> ExtraRow:
    kind = kind_of(device_id)
    if kind is None:
        return ExtraRow(device_id=device_id, names=['Extra 1', 'Extra 2'], show=[True, True])
    return ExtraRow(device_id=device_id, names=list(kind.names), show=list(kind.show))


def add_kind(draft: DeviceDraft, key: str, capacity: int) -> list[ExtraRow]:
    """Add a catalogue device, and first the one it needs. [] when there is no room."""
    kind = kind_by_key(key)
    wanted = []
    if kind.requires is not None and not any(row.kind_key == kind.requires for row in draft.rows):
        wanted.append(kind_by_key(kind.requires).device_id())
    wanted.append(kind.device_id())
    if len(draft.rows) + len(wanted) > capacity:
        return []
    added = [new_row(device_id) for device_id in wanted]
    draft.rows.extend(added)
    return added


def add_device(draft: DeviceDraft, device_id: int, capacity: int) -> ExtraRow | None:
    """Add any Artisan extra device (the Other entry). None when there is no room."""
    kind = kind_of(device_id)
    if kind is not None:
        added = add_kind(draft, kind.key, capacity)
        return added[-1] if added else None
    if len(draft.rows) >= capacity:
        return None
    row = new_row(device_id)
    draft.rows.append(row)
    return row


def move_row(draft: DeviceDraft, uid: int, index: int) -> bool:
    """Put the row ``uid`` at ``index`` of the list without it. True when it moved."""
    current = row_index(draft, uid)
    if current is None:
        return False
    row = draft.rows.pop(current)
    index = max(0, min(index, len(draft.rows)))
    draft.rows.insert(index, row)
    return index != current


def change_device(draft: DeviceDraft, row: ExtraRow, device_id: int) -> None:
    """Tell Artisan what this row really is; its readings and typed names stay.

    Only a channel still carrying Artisan's placeholder name takes the new
    device's name, and a channel the new device leaves unused stops showing a
    counter.
    """
    del draft   # the draft's other rows are untouched; kept for the call's symmetry
    if row.device_id == device_id:
        return
    kind = kind_of(device_id)
    defaults = kind.names if kind is not None else ('Extra 1', 'Extra 2')
    for channel in (0, 1):
        if row.names[channel].strip() in _PLACEHOLDER_NAMES:
            row.names[channel] = defaults[channel]
        if kind is not None and not kind.names[channel]:
            row.show[channel] = False
    row.device_id = device_id


def dependents(draft: DeviceDraft, row: ExtraRow) -> list[ExtraRow]:
    """Rows that read through ``row`` and have to go when it goes."""
    key = row.kind_key
    if key is None:
        return []
    return [other for other in draft.rows
            if other is not row and other.kind_key is not None
            and kind_by_key(other.kind_key).requires == key]


def remove_row(draft: DeviceDraft, row: ExtraRow) -> None:
    """Remove ``row`` and its dependents; sources pointing at them fall back to none."""
    gone = {row.uid} | {other.uid for other in dependents(draft, row)}
    draft.rows = [other for other in draft.rows if other.uid not in gone]
    for key, source in draft.ambient.items():
        if isinstance(source, tuple) and source[0] in gone:
            draft.ambient[key] = 0


def is_misordered(draft: DeviceDraft, row: ExtraRow) -> bool:
    """A device declared before the one it reads through — it reads nothing."""
    key = row.kind_key
    requires = kind_by_key(key).requires if key is not None else None
    if requires is None:
        return False
    index = row_index(draft, row.uid)
    return not any(other.kind_key == requires for other in draft.rows[:index])


# ── ambient ──────────────────────────────────────────────────────────────────

def _tilauambient_rows(draft: DeviceDraft) -> dict[str, ExtraRow]:
    """The first TilauAmbient 12, and the first 34 declared after it."""
    found: dict[str, ExtraRow] = {}
    for row in draft.rows:
        if row.kind_key == 'tilau12' and 'tilau12' not in found:
            found['tilau12'] = row
        elif row.kind_key == 'tilau34' and 'tilau12' in found and 'tilau34' not in found:
            found['tilau34'] = row
    return found


def tilauambient_sources(draft: DeviceDraft) -> dict[str, Source]:
    """What each ambient source would be if TilauAmbient fed it (declared rows only)."""
    rows = _tilauambient_rows(draft)
    return {key: (rows[kind_key].uid, channel)
            for key, (kind_key, channel) in TILAUAMBIENT_SOURCES.items() if kind_key in rows}


def tilauambient_in_use(draft: DeviceDraft) -> bool:
    wanted = tilauambient_sources(draft)
    return all(draft.ambient_hardware[key] or draft.ambient.get(key) == wanted.get(key, -1)
               for key in AMBIENT_KEYS)


def use_tilauambient(draft: DeviceDraft, capacity: int) -> bool:
    """Declare what TilauAmbient needs and point the three sources at it."""
    rows = _tilauambient_rows(draft)
    missing = [key for key in ('tilau12', 'tilau34') if key not in rows]
    if len(draft.rows) + len(missing) > capacity:
        return False
    for key in missing:
        draft.rows.append(new_row(kind_by_key(key).device_id()))
    for key, source in tilauambient_sources(draft).items():
        if not draft.ambient_hardware[key]:
            draft.ambient[key] = source
    return True


# ── writing to Artisan ───────────────────────────────────────────────────────

def apply_extras(aw: 'ApplicationWindow', draft: DeviceDraft, original: DeviceDraft) -> dict[int, int]:
    """Remove, append, reorder, retype and rename extra devices.

    Returns each row's final index by uid. Removals come first, so the devices
    kept sit in their original relative order; new ones are appended behind
    them, and a single permutation then puts every device in its drafted slot.
    """
    qmc = aw.qmc
    kept = sorted(row.origin for row in draft.rows if row.origin is not None)
    for x in sorted((row.origin for row in original.rows if row.origin not in kept), reverse=True):
        mirror.remove_extra_device(aw, x)

    slot_of_origin = {origin: i for i, origin in enumerate(kept)}
    current: dict[int, int] = {}
    for row in draft.rows:
        if row.origin is not None:
            current[row.uid] = slot_of_origin[row.origin]
    for row in draft.rows:
        if row.origin is None:
            current[row.uid] = mirror.add_extra_device(aw, row.device_id)
    mirror.reorder_extra_devices(aw, [current[row.uid] for row in draft.rows])

    first_ids = {row.origin: row.device_id for row in original.rows}
    index_of: dict[int, int] = {}
    for i, row in enumerate(draft.rows):
        index_of[row.uid] = i
        if row.origin is not None and first_ids[row.origin] != row.device_id:
            mirror.set_extra_device(aw, i, row.device_id)
        qmc.extraname1[i], qmc.extraname2[i] = row.names
        aw.extraLCDvisibility1[i], aw.extraLCDvisibility2[i] = row.show
    aw.ensureCorrectExtraDeviceListLength()
    for i, row in enumerate(draft.rows):
        aw.extraLCDlabel1[i].setText(aw.extra_lcd_label_fmt.format(qmc.device_name_subst(row.names[0])))
        aw.extraLCDlabel2[i].setText(aw.extra_lcd_label_fmt.format(qmc.device_name_subst(row.names[1])))
    return index_of


def apply_ambient(aw: 'ApplicationWindow', draft: DeviceDraft, index_of: dict[int, int]) -> None:
    for key in AMBIENT_KEYS:
        if draft.ambient_hardware[key]:
            continue
        source = draft.ambient[key]
        if isinstance(source, tuple):
            uid, channel = source
            value = FIRST_EXTRA_SOURCE + 2 * index_of[uid] + channel - 1 if uid in index_of else 0
        else:
            value = source
        setattr(aw.qmc, _SOURCE_ATTR[key], value)


def apply_device(aw: 'ApplicationWindow', draft: DeviceDraft, parent: Any = None) -> str | None:
    """Channels, meter or TC4, firmware flag and port — okEvent's order."""
    qmc, ser = aw.qmc, aw.ser
    ser.arduinoETChannel, ser.arduinoBTChannel, ser.arduinoATChannel = draft.tc4_channels
    ser.ArduinoFILT = list(draft.tc4_filter)
    message = None
    if draft.mode == 'tc4':
        message = mirror.apply_tc4(aw)
    elif draft.mode == 'meter' and draft.meter:
        message = mirror.apply_meter(aw, draft.meter, parent)
        if draft.meter != 'NONE':
            qmc.delay = max(qmc.delay, qmc.min_delay)
    qmc.PIDbuttonflag = draft.pid_firmware
    if uses_usb_port(draft) and draft.comport:
        ser.comport = draft.comport
    return message


def apply(aw: 'ApplicationWindow', draft: DeviceDraft, original: DeviceDraft, parent: Any = None) -> None:
    index_of = apply_extras(aw, draft, original)
    apply_ambient(aw, draft, index_of)
    mirror.hide_control_readouts(aw)
    message = apply_device(aw, draft, parent)
    mirror.refresh(aw, meter_mode=draft.mode == 'meter', message=message)

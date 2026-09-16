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
onto its neighbour; alarms and formulas, which Artisan keeps by number, are
renumbered on Save.
"""

from __future__ import annotations

import itertools
import re
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
#: Artisan's alarm source index: below 0 none or a RoR, 0 ET, 1 BT, then two per extra device.
FIRST_EXTRA_ALARM_SOURCE: Final[int] = 2
#: BT, where Artisan's alarm table puts a source it cannot show.
_ALARM_FALLBACK_SOURCE: Final[int] = 1
#: Artisan's slider quantifier source index: 0 ET, 1 BT, then two per extra device.
FIRST_EXTRA_QUANTIFIER_SOURCE: Final[int] = 2
#: ET, Artisan's default quantifier source.
_QUANTIFIER_FALLBACK_SOURCE: Final[int] = 0
#: Where a button palette keeps the quantifier on flags and sources (main.py makePalette).
PALETTE_QUANTIFIER_ACTIVE: Final[int] = 14
PALETTE_QUANTIFIER_SOURCE: Final[int] = 15
#: The software PID's input: 0 or 1 BT, 2 ET, then two per extra device.
FIRST_EXTRA_PID_SOURCE: Final[int] = 3
#: What pidcontrol.externalPIDControl() returns for the TC4 PID firmware, which the window can switch.
_TC4_FIRMWARE_PID: Final[int] = 3
#: A formula names readings Y1 ET, Y2 BT, then two per extra device.
FIRST_EXTRA_READING: Final[int] = 3
_READING: Final[re.Pattern[str]] = re.compile(r'(?<![\w.])Y(\d{1,2})(?!\d)')
#: Artisan's own formulas, which name extra readings the same way.
MAIN_FORMULAS: Final[tuple[str, ...]] = ('ETfunction', 'BTfunction', 'DeltaETfunction', 'DeltaBTfunction')
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
    formulas: list[str] = field(default_factory=lambda: ['', ''])   # edited in Artisan, read here
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
    main_formulas: dict[str, str]      # MAIN_FORMULAS, edited in Artisan, read here
    pid_source: int                    # pidcontrol.pidSource
    pid_external_elsewhere: bool       # a MODBUS, S7 or Kaleido PID reads pid_source as its own channel


def snapshot(aw: 'ApplicationWindow') -> DeviceDraft:
    qmc = aw.qmc
    rows = [ExtraRow(device_id=qmc.extradevices[i],
                     names=[qmc.extraname1[i], qmc.extraname2[i]],
                     show=[bool(aw.extraLCDvisibility1[i]), bool(aw.extraLCDvisibility2[i])],
                     formulas=[str(expressions[i] or '') if i < len(expressions) else ''
                               for expressions in (qmc.extramathexpression1, qmc.extramathexpression2)],
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
        main_formulas={attr: str(getattr(qmc, attr) or '') for attr in MAIN_FORMULAS},
        pid_source=int(aw.pidcontrol.pidSource),
        pid_external_elsewhere=int(aw.pidcontrol.externalPIDControl()) not in (0, _TC4_FIRMWARE_PID),
    )


def is_stale(aw: 'ApplicationWindow', original: DeviceDraft) -> bool:
    """Artisan's devices changed under the open window — loading a roast file does that.

    Everything the window reads is compared, not just the device ids: a roast
    with the same devices still brings its own names, counters, sources and
    formulas, which Save would otherwise overwrite.
    """
    current = snapshot(aw)
    if len(current.rows) != len(original.rows):
        return True
    uid_of = {row.uid: kept.uid for row, kept in zip(current.rows, original.rows, strict=True)}
    for row in current.rows:
        row.uid = uid_of[row.uid]
    current.ambient = {key: (uid_of[source[0]], source[1]) if isinstance(source, tuple) else source
                       for key, source in current.ambient.items()}
    return current != original


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


def _readings(expression: str) -> list[tuple[int, int, bool]]:
    """(slot when the window opened, channel, current value) of each extra reading a formula names.

    ``Y3[-1]`` and ``Y3{CHARGE}`` take recorded values, already calculated.
    """
    found = []
    for match in _READING.finditer(expression):
        number = int(match.group(1))
        if number >= FIRST_EXTRA_READING:
            slot, channel = divmod(number - FIRST_EXTRA_READING, 2)
            found.append((slot, channel, expression[match.end():match.end() + 1] not in ('[', '{')))
    return found


def _deleted_with(draft: DeviceDraft, row: ExtraRow) -> tuple[set[int], set[int]]:
    """Uids of ``row`` and of the rows Delete takes with it, and their slots when the window opened."""
    gone = [row, *dependents(draft, row)]
    return {other.uid for other in gone}, {other.origin for other in gone if other.origin is not None}


def formula_readers(draft: DeviceDraft, row: ExtraRow) -> list[ExtraRow | str]:
    """Rows, then MAIN_FORMULAS by name, whose formula uses ``row`` or a device deleted with it.

    A deleted device's reading numbers pass to the next device, so such a formula
    would read that one.
    """
    gone, slots = _deleted_with(draft, row)

    def uses_gone(expression: str) -> bool:
        return any(slot in slots for slot, _channel, _current in _readings(expression))

    readers: list[ExtraRow | str] = [other for other in draft.rows
                                     if other.uid not in gone and any(map(uses_gone, other.formulas))]
    readers.extend(attr for attr, expression in draft.main_formulas.items() if uses_gone(expression))
    return readers


def is_pid_input(draft: DeviceDraft, row: ExtraRow) -> bool:
    """``row``, or a device deleted with it, holds the reading the software PID regulates on.

    An external PID reads its input as its own channel number, never an extra device.
    """
    if draft.pid_external_elsewhere or (draft.mode == 'tc4' and draft.pid_firmware):
        return False
    return (draft.pid_source >= FIRST_EXTRA_PID_SOURCE
            and (draft.pid_source - FIRST_EXTRA_PID_SOURCE) // 2 in _deleted_with(draft, row)[1])


def calculated_reading_below(draft: DeviceDraft, row: ExtraRow) -> ExtraRow | None:
    """A row below ``row`` whose reading ``row``'s formula takes while it has its own formula.

    Artisan calculates the rows from the top: that formula gets the reading
    before the formula of its own row is applied.
    """
    by_origin = {other.origin: other for other in draft.rows if other.origin is not None}
    index = row_index(draft, row.uid) or 0
    for expression in row.formulas:
        for slot, channel, current in _readings(expression):
            other = by_origin.get(slot)
            if (current and other is not None and other is not row and other.formulas[channel].strip()
                    and (row_index(draft, other.uid) or 0) > index):
                return other
    return None


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


def _slots_after_save(original: DeviceDraft, index_of: dict[int, int]) -> dict[int, int | None]:
    """Each device's slot when the window opened → its slot after Save, None when removed."""
    return {row.origin: index_of.get(row.uid) for row in original.rows if row.origin is not None}


def _moved_channel(index: int, first: int, slots: dict[int, int | None]) -> int | None:
    """A channel index after Save, ``first`` being the first extra channel in its numbering.

    An index below ``first`` names no extra device and stays. None when the
    device it names is not saved.
    """
    if index < first:
        return index
    slot, channel = divmod(index - first, 2)
    new_slot = slots.get(slot)
    return None if new_slot is None else first + 2 * new_slot + channel


def apply_alarms(aw: 'ApplicationWindow', original: DeviceDraft, index_of: dict[int, int]) -> None:
    """Keep every alarm on the reading it watches; one whose device is not saved is switched off.

    The alarm table and each stored alarm set name their reading by index, which
    a move or a removal would otherwise hand to another device.
    """
    qmc = aw.qmc
    _renumber_sources([(qmc.alarmsource, qmc.alarmflag),
                       *((alarmset['sources'], alarmset['flags']) for alarmset in qmc.alarmsets)],
                      FIRST_EXTRA_ALARM_SOURCE, _ALARM_FALLBACK_SOURCE, _slots_after_save(original, index_of))


def apply_quantifiers(aw: 'ApplicationWindow', original: DeviceDraft, index_of: dict[int, int]) -> None:
    """Keep every slider quantifier on the reading it follows; one whose device is not saved is switched off.

    The quantifiers and each stored button palette name their reading by index,
    as alarms do.
    """
    _renumber_sources([(aw.eventquantifiersource, aw.eventquantifieractive),
                       *((palette[PALETTE_QUANTIFIER_SOURCE], palette[PALETTE_QUANTIFIER_ACTIVE])
                         for palette in aw.buttonpalette if len(palette) > PALETTE_QUANTIFIER_SOURCE)],
                      FIRST_EXTRA_QUANTIFIER_SOURCE, _QUANTIFIER_FALLBACK_SOURCE,
                      _slots_after_save(original, index_of))


def _renumber_sources(tables: list[tuple[list[int], list[int]]], first: int, fallback: int,
                      slots: dict[int, int | None]) -> None:
    """Renumber (sources, on flags) tables in place; an entry whose device is not saved goes off on ``fallback``."""
    seen: set[int] = set()
    for sources, flags in tables:
        if id(sources) in seen:   # renumbered twice, a shared list would land on the wrong reading
            continue
        seen.add(id(sources))
        for i, source in enumerate(sources):
            moved = _moved_channel(int(source), first, slots)
            if moved is None:
                sources[i] = fallback
                if i < len(flags):
                    flags[i] = 0
            else:
                sources[i] = moved


def _renumbered(expression: str, slots: dict[int, int | None]) -> str:
    def renumber(match: re.Match[str]) -> str:
        number = int(match.group(1))
        moved = _moved_channel(number, FIRST_EXTRA_READING, slots)
        return match.group(0) if moved is None or moved == number else f'Y{moved}'
    return _READING.sub(renumber, expression)


def apply_formulas(aw: 'ApplicationWindow', original: DeviceDraft, index_of: dict[int, int]) -> None:
    """Keep every formula on the readings it names, which it names by number.

    A reading of a removed device keeps its number: Delete refuses a device a
    formula uses.
    """
    slots = _slots_after_save(original, index_of)
    qmc = aw.qmc
    for attr in ('extramathexpression1', 'extramathexpression2'):
        setattr(qmc, attr, [_renumbered(expression, slots) if expression else expression
                            for expression in getattr(qmc, attr)])
    for attr in MAIN_FORMULAS:
        if getattr(qmc, attr):
            setattr(qmc, attr, _renumbered(getattr(qmc, attr), slots))


def apply_pid_source(aw: 'ApplicationWindow', original: DeviceDraft, index_of: dict[int, int]) -> None:
    """Keep the software PID on the reading it regulates on; runs once the device is set.

    An external PID reads pidSource as its own channel number. A reading of a
    removed device keeps its number: Delete refuses the device the PID reads.
    """
    pid = aw.pidcontrol
    if pid.externalPIDControl():
        return
    moved = _moved_channel(int(pid.pidSource), FIRST_EXTRA_PID_SOURCE, _slots_after_save(original, index_of))
    if moved is not None:
        pid.pidSource = moved


def apply(aw: 'ApplicationWindow', draft: DeviceDraft, original: DeviceDraft, parent: Any = None) -> None:
    index_of = apply_extras(aw, draft, original)
    apply_ambient(aw, draft, index_of)
    apply_alarms(aw, original, index_of)
    apply_quantifiers(aw, original, index_of)
    apply_formulas(aw, original, index_of)
    mirror.hide_control_readouts(aw)
    message = apply_device(aw, draft, parent)
    apply_pid_source(aw, original, index_of)
    mirror.refresh(aw, meter_mode=draft.mode == 'meter', message=message)

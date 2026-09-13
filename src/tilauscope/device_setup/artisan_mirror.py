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

"""The pieces of Artisan's device dialog that have to run without the dialog.

Each function cites the lines of ``artisanlib/devices.py`` it replays. Upstream
changing any of them breaks ``test_device_setup_tripwire.py`` rather than
drifting away from this copy in silence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final

from PyQt6.QtWidgets import QApplication

from artisanlib.device_registry import TILAU_DEVICES
from tilauscope.device_setup.artisan_defaults import (EXTRA_DEVSSETTINGS, EXTRA_SSETTINGS,
                                                      METER_BRANCHES)

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

#: Meter branches that do more than set data (``artisan_defaults.SPECIAL_METERS``),
#: each replayed in ``apply_meter``.
HAND_MIRRORED_METERS: Final[frozenset[str]] = frozenset({'IKAWA', 'NONE', 'Omega HH506RA'})

TC4_DEVICE_ID: Final[int] = 19
_TC4_SERIAL: Final[dict[str, Any]] = {
    'baudrate': 115200, 'bytesize': 8, 'parity': 'N', 'stopbits': 1, 'timeout': 0.8}
_TRP_SERIAL: Final[dict[str, Any]] = {
    'baudrate': 115200, 'bytesize': 8, 'parity': 'N', 'stopbits': 1, 'timeout': 0.4}
_EXTRA_SERIAL_FALLBACK: Final[tuple[int, int, str, int, float]] = (9600, 8, 'O', 1, 0.5)

# Every list Artisan keeps in step per extra device — the ones delextradevice
# pops (the tripwire compares). The curve lines are handled apart: they only
# hold the visible curves.
_QMC_PER_DEVICE: Final[tuple[str, ...]] = (
    'extradevices', 'extradevicecolor1', 'extradevicecolor2',
    'extratimex', 'extratemp1', 'extratemp2', 'extrastemp1', 'extrastemp2',
    'extractimex1', 'extractimex2', 'extractemp1', 'extractemp2',
    'extralinestyles1', 'extralinestyles2', 'extradrawstyles1', 'extradrawstyles2',
    'extralinewidths1', 'extralinewidths2', 'extramarkers1', 'extramarkers2',
    'extramarkersizes1', 'extramarkersizes2',
    'extraname1', 'extraname2', 'extramathexpression1', 'extramathexpression2',
)
_AW_FIXED_LENGTH: Final[tuple[str, ...]] = (   # always aw.nLCDS long
    'extraLCDvisibility1', 'extraLCDvisibility2', 'extraCurveVisibility1', 'extraCurveVisibility2',
    'extraDelta1', 'extraDelta2', 'extraFill1', 'extraFill2',
)
_AW_SERIAL: Final[tuple[str, ...]] = (
    'extracomport', 'extrabaudrate', 'extrabytesize', 'extraparity',
    'extrastopbits', 'extratimeout', 'extraser',
)


# ── extra devices ────────────────────────────────────────────────────────────

def remove_extra_device(aw: 'ApplicationWindow', x: int) -> None:
    """``DeviceAssignmentDlg.delextradevice`` (devices.py ≈3252) without its table and redraw."""
    aw.qmc.extradevices.pop(x)
    aw.qmc.extradevicecolor1.pop(x)
    aw.qmc.extradevicecolor2.pop(x)
    aw.qmc.extratimex.pop(x)
    aw.qmc.extratemp1.pop(x)
    aw.qmc.extratemp2.pop(x)
    aw.qmc.extrastemp1.pop(x)
    aw.qmc.extrastemp2.pop(x)
    aw.qmc.extractimex1.pop(x)
    aw.qmc.extractimex2.pop(x)
    aw.qmc.extractemp1.pop(x)
    aw.qmc.extractemp2.pop(x)
    aw.qmc.extralinestyles1.pop(x)
    aw.qmc.extralinestyles2.pop(x)
    aw.qmc.extradrawstyles1.pop(x)
    aw.qmc.extradrawstyles2.pop(x)
    aw.qmc.extralinewidths1.pop(x)
    aw.qmc.extralinewidths2.pop(x)
    aw.qmc.extramarkers1.pop(x)
    aw.qmc.extramarkers2.pop(x)
    aw.qmc.extramarkersizes1.pop(x)
    aw.qmc.extramarkersizes2.pop(x)

    # the curve lines list only holds the visible curves
    before1 = sum(1 for j in range(x) if aw.extraCurveVisibility1[j])
    before2 = sum(1 for j in range(x) if aw.extraCurveVisibility2[j])
    if aw.extraCurveVisibility1[x]:
        aw.qmc.extratemp1lines.pop(before1)
    if aw.extraCurveVisibility2[x]:
        aw.qmc.extratemp2lines.pop(before2)

    # lists of constant length aw.nLCDS
    aw.extraLCDvisibility1.pop(x)
    aw.extraLCDvisibility1.append(False)
    aw.extraLCDvisibility2.pop(x)
    aw.extraLCDvisibility2.append(False)
    aw.extraCurveVisibility1.pop(x)
    aw.extraCurveVisibility1.append(True)
    aw.extraCurveVisibility2.pop(x)
    aw.extraCurveVisibility2.append(True)
    aw.extraDelta1.pop(x)
    aw.extraDelta1.append(False)
    aw.extraDelta2.pop(x)
    aw.extraDelta2.append(False)
    aw.extraFill1.pop(x)
    aw.extraFill1.append(0)
    aw.extraFill2.pop(x)
    aw.extraFill2.append(0)

    aw.qmc.extraname1.pop(x)
    aw.qmc.extraname2.pop(x)
    aw.qmc.extramathexpression1.pop(x)
    aw.qmc.extramathexpression2.pop(x)
    aw.updateLCDproperties()

    if len(aw.extracomport) > x:
        aw.extracomport.pop(x)
    if len(aw.extrabaudrate) > x:
        aw.extrabaudrate.pop(x)
    if len(aw.extrabytesize) > x:
        aw.extrabytesize.pop(x)
    if len(aw.extraparity) > x:
        aw.extraparity.pop(x)
    if len(aw.extrastopbits) > x:
        aw.extrastopbits.pop(x)
    if len(aw.extratimeout) > x:
        aw.extratimeout.pop(x)
    if len(aw.extraser) > x:
        if aw.extraser[x].SP.is_open:
            aw.extraser[x].SP.close()
            time.sleep(0.7)   # macOS disables a serial port reopened too fast after closing
        aw.extraser.pop(x)


def reorder_extra_devices(aw: 'ApplicationWindow', order: list[int]) -> None:
    """Put the device now at ``order[i]`` into slot ``i``, its recorded readings with it.

    Artisan's own dialog cannot move a device; this moves every list it keeps
    per device together, so a device keeps its readings, names, colours and
    serial settings wherever it lands.
    """
    qmc = aw.qmc
    n = len(order)
    if sorted(order) != list(range(len(qmc.extradevices))):
        raise ValueError('order must list every extra device once')
    if order == list(range(n)):
        return
    # lines first: which device a line belongs to is read from the visibility not yet moved
    for lines_attr, visibility in (('extratemp1lines', aw.extraCurveVisibility1),
                                   ('extratemp2lines', aw.extraCurveVisibility2)):
        lines = getattr(qmc, lines_attr)
        visible = [j for j in range(n) if visibility[j]]
        if len(lines) == len(visible):   # otherwise the next redraw rebuilds them anyway
            by_device = dict(zip(visible, lines, strict=True))
            setattr(qmc, lines_attr, [by_device[j] for j in order if visibility[j]])
    for attr in _QMC_PER_DEVICE:
        values = getattr(qmc, attr)
        if len(values) >= n:
            setattr(qmc, attr, [values[j] for j in order] + list(values[n:]))
    for attr in _AW_FIXED_LENGTH + _AW_SERIAL:
        values = getattr(aw, attr)
        if len(values) >= n:
            setattr(aw, attr, [values[j] for j in order] + list(values[n:]))


def extra_serial_settings(device_id: int) -> tuple[int, int, str, int, float]:
    """Artisan's serial defaults for an extra device (okEvent ≈4902-4908)."""
    if device_id < len(EXTRA_DEVSSETTINGS) and EXTRA_DEVSSETTINGS[device_id] < len(EXTRA_SSETTINGS):
        return EXTRA_SSETTINGS[EXTRA_DEVSSETTINGS[device_id]]
    return _EXTRA_SERIAL_FALLBACK


def set_extra_device(aw: 'ApplicationWindow', i: int, device_id: int) -> None:
    """Give slot ``i`` its device type and that type's serial defaults."""
    aw.qmc.extradevices[i] = device_id
    baudrate, bytesize, parity, stopbits, timeout = extra_serial_settings(device_id)
    aw.extrabaudrate[i] = baudrate
    aw.extrabytesize[i] = bytesize
    aw.extraparity[i] = parity
    aw.extrastopbits[i] = stopbits
    aw.extratimeout[i] = timeout


def add_extra_device(aw: 'ApplicationWindow', device_id: int) -> int:
    """Append an extra device the way the Add button does, then give it its type."""
    aw.addDevice()
    i = len(aw.qmc.extradevices) - 1
    set_extra_device(aw, i, device_id)
    return i


# ── main device ──────────────────────────────────────────────────────────────

def hide_control_readouts(aw: 'ApplicationWindow') -> None:
    """okEvent ≈3602-3606: PID buttons and LCDs start hidden before the device is set."""
    aw.buttonCONTROL.setVisible(False)
    aw.LCD6frame.setVisible(False)
    aw.LCD7frame.setVisible(False)
    aw.qmc.resetlinecountcaches()


def apply_tc4(aw: 'ApplicationWindow') -> str | None:
    """okEvent ≈3685-3695. The channels and filter are written by the caller, as okEvent does."""
    if aw.qmc.device == TC4_DEVICE_ID:
        return None
    aw.qmc.device = TC4_DEVICE_ID
    for param, value in _TC4_SERIAL.items():
        setattr(aw.ser, param, value)
    aw.ser.ArduinoIsInitialized = 0   # the board is initialised again with the new settings
    return QApplication.translate('tilauscope_devices', 'Device set to TC4 board')


def apply_meter(aw: 'ApplicationWindow', name: str, parent: Any = None) -> str | None:
    """okEvent's meter chain (≈3701-4673) for one meter name.

    A guarded branch only acts when the device changes, as in Artisan: choosing
    the meter already in use keeps whatever serial settings it has.
    """
    tilau = {d['label']: key for key, d in TILAU_DEVICES.items()}
    if name in tilau:   # the TILAU branch, ≈4662-4673
        aw.qmc.device = TILAU_DEVICES[tilau[name]]['id']
        if tilau[name] == 'trp_btet':
            for param, value in _TRP_SERIAL.items():
                setattr(aw.ser, param, value)
        return QApplication.translate('tilauscope_devices', 'Device set to {0}').format(name)

    branch = METER_BRANCHES.get(name)
    if branch is None:
        return None
    device_id, serial, only_on_change = branch
    if only_on_change and aw.qmc.device == device_id:
        return None
    aw.qmc.device = device_id
    for param, value in serial.items():
        setattr(aw.ser, param, value)

    if name == 'Omega HH506RA':
        aw.ser.HH506RAid = 'X'   # the meter gets re-initialised with the new settings
    elif name == 'NONE':
        aw.eventsbuttonflag = 1   # manual input needs the event button
        aw.buttonEVENT.setVisible(True)
    elif name == 'IKAWA':
        if aw.app.getBluetoothPermission(request=True) is False:
            from PyQt6.QtWidgets import QMessageBox

            from tilauscope.tilauscope_types import show_styled_message
            show_styled_message(
                parent,
                QApplication.translate('tilauscope_devices', 'Bluetooth'),
                QApplication.translate(
                    'tilauscope_devices',
                    'Bluetooth access was denied. Allow TilauScope in the system '
                    'Bluetooth settings, then choose the meter again.'),
                QMessageBox.Icon.Warning)
    return QApplication.translate('tilauscope_devices', 'Device set to {0}').format(name)


def refresh(aw: 'ApplicationWindow', *, meter_mode: bool, message: str | None) -> None:
    """The tail of okEvent (≈4680, 4929-4961, 5055-5079) that Devices needs."""
    aw.showControlButton()
    if meter_mode:
        aw.pidbuttonFrame.setVisible(False)
        aw.LCD6frame.setVisible(False)
        aw.LCD7frame.setVisible(False)
    main = getattr(aw, 'tilauscope_main', None)
    if main is not None:
        main.update_extradevices_from_artisan()
    aw.updateLCDproperties()
    aw.qmc.disconnectProbes()   # every port closes and reopens with the new settings
    if aw.largeExtraLCDs_dialog:
        aw.largeExtraLCDs_dialog.reLayout()
    aw.qmc.intChannel.cache_clear()
    aw.qmc.clearLCDs()
    aw.qmc.redraw(recomputeAllDeltas=False)
    if message:
        aw.sendmessage(message)

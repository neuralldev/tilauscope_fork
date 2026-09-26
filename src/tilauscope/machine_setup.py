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
# Tilau 2026

"""Machine setup of a roasters.json roaster: the functional part of its Artisan preset.

`machine=True` in Artisan's settings loader only gates `[MachineSetup]`; every
other section of the file is applied. So the preset is filtered to what makes
the roaster measure and obey (device, links, sliders, buttons, PID, probe
smoothing) before Artisan loads it, and never carries display settings,
alarms, the owner's ports or the identifiers of their own devices.

Module top level is stdlib only: tools/ reuses `functional_text` offline.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow
    from tilauscope.roasters import ArtisanSetup

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Sections applied whole.
KEEP_SECTIONS: Final[frozenset[str]] = frozenset({
    'Device', 'ExtraDev', 'ExtraComm', 'SerialPort', 'Modbus', 'S7', 'WebSocket',
    'Sliders', 'ExtraEventButtons', 'DefaultButtons', 'Quantifiers',
    'ArduinoPID', 'PXR', 'PXG4', 'deltaDTA', 'RoC',
    'MachineSetup', 'EnergyDefaults', 'EnergyUse',
})

# Sections of which only these keys are applied.
KEEP_KEYS: Final[dict[str, frozenset[str]]] = {
    'General': frozenset({
        'Delay', 'Oversampling', 'dropDuplicates', 'dropDuplicatesLimit', 'dropSpikes',
        'ETfunction', 'BTfunction', 'DeltaETfunction', 'DeltaBTfunction',
        'AmbientTempSource', 'ExtraEventSamplingDelay', 'KeepON',
        'curvefilter', 'filterDropOuts', 'optimalSmoothing',
    }),
    'events': frozenset({
        'etypes', 'default_etypes_set', 'autoCharge', 'autoChargeMode',
        'autoDrop', 'autoDropMode', 'markTP', 'chargeTimer', 'chargeTimerPeriod',
    }),
    'Units': frozenset({'weight'}),
}

# Keys of kept sections that belong to the owner of the file, not to the machine:
# serial ports, their own paired devices, their elevation, remote credentials,
# TilauScope's own preferences stored among the device settings.
DROP_KEYS: Final[dict[str, frozenset[str]]] = {
    'Device': frozenset({
        'difluidaw', 'difluidomniflux', 'lbrsag', 'lbrsc1', 'niimbot', 'skywalkertc4', 'elevation',
        'phidgetServerID', 'phidgetPassword', 'phidgetRemoteFlag', 'phidgetRemoteOnlyFlag',
        'yoctoServerID', 'yoctoRemoteFlag', 'device_logging', 'tilauai', 'tilaumqttbridge',
    }),
    'SerialPort': frozenset({'comport'}),
    'Modbus': frozenset({'comport'}),
}
DROP_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    'Device': ('difluidpid', 'difluidcolorpid', 'tilauscope', 'shelly_'),
}

_SLIDER_VIS_BACKUP_KEY: Final[str] = 'tilauscope/slider_vis_backup'  # devices.py read-only snapshot


def _keeps(section: str, key: str) -> bool:
    if section in KEEP_SECTIONS:
        return (key not in DROP_KEYS.get(section, frozenset())
                and not key.startswith(DROP_PREFIXES.get(section, ())))
    return key in KEEP_KEYS.get(section, frozenset())


def functional_text(text: str) -> str:
    """The lines of an .aset that set up the machine, section headers included."""
    out: list[str] = []
    section = 'General'
    pending: str | None = None   # header written only once a key survives
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
            pending = line
            continue
        if not stripped or '=' not in stripped:
            continue
        if _keeps(section, stripped.split('=', 1)[0].strip()):
            if pending is not None:
                if out:
                    out.append('')
                out.append(pending)
                pending = None
            out.append(line)
    return '\n'.join(out) + '\n'


# ── roasters.json ──────────────────────────────────────────────────────────

def setups_for(roaster_name: str) -> list[ArtisanSetup]:
    """The ways to link *roaster_name*, first one the default."""
    from tilauscope.roasters import RoasterManager
    roaster = RoasterManager().get_by_display_name(roaster_name)
    return list(roaster.artisan_setups) if roaster is not None else []


def preset_path(setup: ArtisanSetup) -> str | None:
    from artisanlib.util import getResourcePath
    path = os.path.join(getResourcePath(), 'Machines', *setup.preset.split('/'))
    return path if os.path.isfile(path) else None


def preset_device(path: str) -> int | None:
    """The main device id a preset selects, read without applying anything.

    A TilauScope device is read back through its stable key, as Artisan's loader
    does: its stored id moves whenever upstream adds a device.
    """
    from PyQt6.QtCore import QSettings
    from artisanlib.device_registry import tilau_ids
    s = QSettings(path, QSettings.Format.IniFormat)
    try:
        value = s.value('Device/id')
        return tilau_ids([int(value)], s.value('Device/tilau_device', ''))[0] if value is not None else None
    except (TypeError, ValueError):
        return None


# Flags that tell apart the links sharing one device: Kaleido (138) serial/network,
# Santoker (134) serial/network/Bluetooth. Another device's flags are leftovers.
_LINK_FLAGS: Final[dict[int, tuple[str, ...]]] = {
    138: ('kaleidoSerial',),
    134: ('santokerSerial', 'santokerBLE'),
}


def link_in_use(aw: ApplicationWindow, path: str) -> bool:
    """Whether the roaster is linked the way this preset links it right now."""
    from PyQt6.QtCore import QSettings
    device = preset_device(path)
    if device is None or device != getattr(aw.qmc, 'device', None):
        return False
    s = QSettings(path, QSettings.Format.IniFormat)
    return all(
        (str(s.value(f'Device/{flag}', 'false')).lower() == 'true') == bool(getattr(aw, flag, False))
        for flag in _LINK_FLAGS.get(device, ()))


def preset_controls(path: str, default_names: list[str]) -> tuple[list[str], list[int], int]:
    """(visible slider names, milestone buttons that send a command, visible command buttons)."""
    from PyQt6.QtCore import QSettings
    s = QSettings(path, QSettings.Format.IniFormat)

    def ints(key: str) -> list[int]:
        try:
            return [int(v) for v in (s.value(key) or [])]
        except (TypeError, ValueError):
            return []

    names = [str(n) for n in (s.value('events/etypes') or [])]
    sliders = [(names[i] if i < len(names) and names[i] else default_names[i])
               for i, visible in enumerate(ints('Sliders/slidervisibilities'))
               if visible and ints('Sliders/slideractions')[i:i + 1] != [0] and i < len(default_names)]
    milestones = [i for i, action in enumerate(ints('DefaultButtons/buttonactions')) if action]
    buttons = sum(1 for v in ints('ExtraEventButtons/extraeventsvisibility') if v)
    return sliders, milestones, buttons


_PLACEHOLDER_HOST: Final[str] = '127.0.0.1'   # Artisan's default for every roaster address


def host_target(path: str) -> tuple[str, tuple[str, ...]] | None:
    """(preset key, aw attribute path) of the roaster address a network preset needs.

    Mirrors the address prompts of Artisan's Config › Machine, plus the Santoker
    over Wi-Fi, whose address Artisan takes from the preset without asking.
    """
    from PyQt6.QtCore import QSettings
    s = QSettings(path, QSettings.Format.IniFormat)

    def flag(key: str) -> bool:
        return str(s.value(key, 'false')).lower() == 'true'

    device = preset_device(path)
    if device == 138 and not flag('Device/kaleidoSerial'):
        return 'Device/kaleidoHost', ('kaleidoHost',)
    if device == 134 and not flag('Device/santokerSerial') and not flag('Device/santokerBLE'):
        return 'Device/santokerHost', ('santokerHost',)
    if device == 164:
        return 'Device/mugmaHost', ('mugmaHost',)
    if device == 79:
        return 'S7/host', ('s7', 'host')
    if device == 111:
        return 'WebSocket/host', ('ws', 'host')
    if device == 29 and str(s.value('Modbus/type', 0)) in ('3', '4'):   # MODBUS TCP or UDP
        return 'Modbus/host', ('modbus', 'host')
    return None


def suggested_host(aw: ApplicationWindow, path: str) -> str:
    """The address the operator already set, else the preset's own, as Artisan offers it."""
    from PyQt6.QtCore import QSettings
    target = host_target(path)
    if target is None:
        return ''
    key, attrs = target
    obj = aw
    for name in attrs[:-1]:
        obj = getattr(obj, name)
    current = str(getattr(obj, attrs[-1], '') or '')
    if current and current != _PLACEHOLDER_HOST:
        return current
    return str(QSettings(path, QSettings.Format.IniFormat).value(key, '') or current)


def _set_host(aw: ApplicationWindow, path: str, host: str) -> None:
    target = host_target(path)
    if target is None or not host:
        return
    obj = aw
    for name in target[1][:-1]:
        obj = getattr(obj, name)
    setattr(obj, target[1][-1], host)


# Devices whose serial port Artisan's Config › Machine asks for (Fuji, Center 301,
# TC4, Hottop, Behmor, HB/ARC…), MODBUS serial aside.
_SERIAL_PORT_DEVICES: Final[frozenset[int]] = frozenset({0, 9, 19, 53, 101, 115, 126, 196})


def port_target(path: str) -> tuple[str, str] | None:
    """(aw attribute, field) of the serial port a preset opens, None when it opens none.

    Mirrors the port prompt of Artisan's Config › Machine: the Kaleido and the
    Santoker share a device between serial and network links, told apart by a flag.
    TilauScope's own serial devices (the TRP roaster) open the main port too.
    """
    from PyQt6.QtCore import QSettings
    from artisanlib.device_registry import TILAU_DEVICES
    s = QSettings(path, QSettings.Format.IniFormat)

    def flag(key: str) -> bool:
        return str(s.value(key, 'false')).lower() == 'true'

    device = preset_device(path)
    if device == 29 and str(s.value('Modbus/type', 0)) in ('0', '1', '2'):   # MODBUS serial
        return 'modbus', 'comport'
    if (device in _SERIAL_PORT_DEVICES
            or any(d['id'] == device and not d['nonserial'] for d in TILAU_DEVICES.values())
            or (device == 134 and flag('Device/santokerSerial') and not flag('Device/santokerBLE'))
            or (device == 138 and flag('Device/kaleidoSerial'))):
        return 'ser', 'comport'
    return None


def saved_port(aw: ApplicationWindow, path: str) -> str:
    target = port_target(path)
    return str(getattr(getattr(aw, target[0]), target[1], '') or '') if target else ''


def usb_serial_ports() -> list[tuple[str, str]]:
    """(device, description) of the USB serial ports plugged in now."""
    try:
        import serial.tools.list_ports
        return [(p.device, p.product or p.description or '')
                for p in serial.tools.list_ports.comports() if p.vid is not None]
    except Exception:  # pylint: disable=broad-except
        _log.exception('serial port listing failed')
        return []


def auto_port(saved: str, ports: list[tuple[str, str]]) -> str | None:
    """The port to use without asking: the saved one still plugged in, or the only one."""
    devices = [d for d, _ in ports]
    if saved in devices:
        return saved
    return devices[0] if len(devices) == 1 else None


# ── apply ──────────────────────────────────────────────────────────────────

def _reset_functional(aw: ApplicationWindow) -> None:
    """Factory values for what a preset may leave out, so nothing of the previous machine survives."""
    qmc = aw.qmc
    aw.resetExtraDevices()
    n = aw.eventsliders
    aw.eventslidervisibilities = [0] * n
    aw.eventslideractions = [0] * n
    aw.eventslidercommands = [''] * n
    aw.eventslideroffsets = [0.0] * n
    aw.eventsliderfactors = [1.0] * n
    aw.eventslidermin = [0] * n
    aw.eventslidermax = [100] * n
    aw.eventsliderBernoulli = [0] * n
    aw.eventslidercoarse = [0] * n
    aw.eventslidertemp = [0] * n
    aw.eventsliderunits = [''] * n
    qmc.buttonactions = [0] * len(qmc.buttonactions)
    qmc.buttonactionstrings = [''] * len(qmc.buttonactionstrings)
    qmc.extrabuttonactions = [0] * len(qmc.extrabuttonactions)
    qmc.extrabuttonactionstrings = [''] * len(qmc.extrabuttonactionstrings)
    qmc.xextrabuttonactions = [0] * len(qmc.xextrabuttonactions)
    qmc.xextrabuttonactionstrings = [''] * len(qmc.xextrabuttonactionstrings)
    for name in ('extraeventstypes', 'extraeventsvalues', 'extraeventsactions',
                 'extraeventsvisibility', 'extraeventsactionstrings', 'extraeventslabels',
                 'extraeventsdescriptions', 'extraeventbuttoncolor', 'extraeventbuttontextcolor'):
        setattr(aw, name, [])
    aw.eventquantifieractive = [0] * len(aw.eventquantifieractive)
    qmc.etypes = qmc.etypesdefault[:]
    qmc.ETfunction = ''
    qmc.BTfunction = ''
    qmc.DeltaETfunction = ''
    qmc.DeltaBTfunction = ''


def _set_first_batch(aw: ApplicationWindow, grams: int) -> None:
    from artisanlib.util import convertWeight, weight_units
    qmc = aw.qmc
    unit = qmc.weight[2]
    qmc.last_batchsize = float(grams)
    qmc.end_weight_est = 0
    qmc.weight = (convertWeight(grams, 0, weight_units.index(unit)), 0, unit)


def apply(aw: ApplicationWindow, roaster_name: str, setup: ArtisanSetup, port: str | None,
          host: str | None = None) -> bool:
    """Load the functional part of *setup*'s preset and the roaster's own figures.

    Refused while monitoring or recording: the sampling loop reads the very
    extra devices and slider arrays this replaces.
    """
    from PyQt6.QtCore import QSettings, QTimer
    from artisanlib.device_registry import PHIDGET_DEVICES
    from tilauscope.devices import apply_airwave_damper_mapping
    from tilauscope.roasters import RoasterManager, sync_roaster_to_qmc

    if aw.qmc.flagon or aw.qmc.flagstart:
        _log.warning('machine setup refused: monitoring is on')
        return False
    path = preset_path(setup)
    if path is None:
        _log.warning('machine preset missing: %s', setup.preset)
        return False
    with open(path, encoding='utf-8') as f:
        text = functional_text(f.read())
    fd, tmp = tempfile.mkstemp(suffix='.aset')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        _reset_functional(aw)
        aw.loadSettings(fn=tmp, remember=False, machine=True, reload=False)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    target = port_target(path)
    if target is not None and port:
        setattr(getattr(aw, target[0]), target[1], port)
    if host:
        _set_host(aw, path, host)
    aw.tilau_roaster = roaster_name
    aw.tilau_roaster_readonly = setup.read_only
    QSettings().remove(_SLIDER_VIS_BACKUP_KEY)  # the preset now owns slider visibility
    sync_roaster_to_qmc(aw, roaster_name)
    roaster = RoasterManager().get_by_display_name(roaster_name)
    if roaster is not None:
        _set_first_batch(aw, roaster.optimal_batch_capacity_g or roaster.batch_capacity_max_g)

    qmc = aw.qmc
    if qmc.device in PHIDGET_DEVICES or any(d in PHIDGET_DEVICES for d in qmc.extradevices):
        QTimer.singleShot(700, qmc.startPhidgetManager)  # as Artisan's Config › Machine
    apply_airwave_damper_mapping(aw)  # a paired AirWave keeps its slider
    aw.establish_etypes()
    _log.info('machine set up for %s from %s', roaster_name, setup.preset)
    return True

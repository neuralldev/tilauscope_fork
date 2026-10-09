#
# ABOUT
# Health checks of a recorded roast file, for the Roast Profile Maintenance window
#
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

"""Symptoms a software or instrument fault leaves in a .alog — never a judgement
of the roast itself. Pure functions over a parsed profile, no Qt.

A finding is ``(code, args)``; the maintenance window words it. Duplicates and
broken coffee links need the whole folder or BeanCave, so the window finds those.
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Final, cast

from artisanlib.device_registry import TILAU_DEVICES
from artisanlib.util import events_external_to_internal_value
from tilauscope.energy_model import ROASTER
from tilauscope.tilaupid_adaptative import AlogScanner
from tilauscope.tilauscope_types import RoastingPhase, marked, normalize_timeindex

Finding = tuple[str, tuple]

# Finding codes, in the order the window shows them (most severe first).
DEVICE_SHIFT: Final[str] = 'device_shift'
PREHEAT_COMMANDS: Final[str] = 'preheat_commands'
DUPLICATE: Final[str] = 'duplicate'
POWER_METER: Final[str] = 'power_meter'
BT_GAPS: Final[str] = 'bt_gaps'
MILESTONE_ORDER: Final[str] = 'milestone_order'
ROR_OUTLIER: Final[str] = 'ror_outlier'
ORPHAN_BEAN: Final[str] = 'orphan_bean'
SIMULATED: Final[str] = 'simulated'
SEVERITY: Final[tuple[str, ...]] = (
    DEVICE_SHIFT, PREHEAT_COMMANDS, DUPLICATE, POWER_METER, BT_GAPS,
    MILESTONE_ORDER, ROR_OUTLIER, ORPHAN_BEAN, SIMULATED)

# Milestone-order violations (args of MILESTONE_ORDER).
DRY_BEFORE_TP: Final[str] = 'dry_before_tp'
FC_BEFORE_DRY: Final[str] = 'fc_before_dry'
FC_AFTER_DROP: Final[str] = 'fc_after_drop'

# Power-meter symptoms (first arg of POWER_METER).
METER_EMPTY: Final[str] = 'empty'
METER_SILENT: Final[str] = 'silent'
METER_IDLE: Final[str] = 'idle'

# Burner commands written back from the echo channel, kept so Undo can remove them.
REBUILT_KEY: Final[str] = 'tilau_heater_events_rebuilt'

_MIN_SAMPLES: Final[int] = 10
_ACTUATOR: Final[str] = 'actuator'   # slider echo: a percentage 0–100
_COUNTER: Final[str] = 'counter'     # never decreases
# What channel 1 and channel 2 of each TilauScope device can read (°C for
# temperatures); None is not checked. MQTT channels carry whatever the user maps.
_SIGNATURES: Final[dict[str, tuple]] = {
    'skywalker_pf':  (_ACTUATOR, _ACTUATOR),
    'skycommand_pf': (_ACTUATOR, _ACTUATOR),
    'trp_hf':        (_ACTUATOR, _ACTUATOR),
    'difluid':       (('temp', 0.0, 500.0), ('temp', 0.0, 500.0)),
    'tilau12':       (('temp', -10.0, 60.0), ('plain', 0.0, 100.0)),
    'tilau34':       (('plain', 700.0, 1100.0), ('plain', -500.0, 5000.0)),
    'tilau56':       (_COUNTER, None),
}
EVENT_KEYS: Final[tuple[str, ...]] = (
    'specialevents', 'specialeventstype', 'specialeventsvalue', 'specialeventsStrings')

_METER_SILENCE_S: Final[float] = 180.0   # three report periods of a ~60 s push meter
_METER_IDLE_W: Final[float] = 50.0       # an idle heater reads ~10 W, a heating one hundreds
_BT_GAP_COUNT: Final[int] = 5
_BT_GAP_S: Final[float] = 10.0
_ROR_WINDOW_S: Final[float] = 30.0
_ROR_RANGE_C: Final[tuple[float, float]] = (-20.0, 40.0)   # °C/min


def _valid(v: object) -> bool:
    return isinstance(v, (int, float)) and v != -1


def _channel(data: dict, slot: int, channel: int) -> tuple[list, list]:
    """(values, times) of one extra-device channel; empty when absent."""
    values = data.get(f'extratemp{channel}') or []
    times = data.get('extratimex') or []
    if slot >= len(values) or slot >= len(times):
        return [], []
    return list(values[slot] or []), list(times[slot] or [])


def _fits(sig: object, vals: list[float], fahrenheit: bool) -> bool:
    if sig == _ACTUATOR:
        return all(0.0 <= v <= 100.0 for v in vals)
    if sig == _COUNTER:
        return all(v >= 0.0 for v in vals) and all(b >= a for a, b in zip(vals, vals[1:], strict=False))
    kind, lo, hi = cast(tuple[str, float, float], sig)
    if kind == 'temp' and fahrenheit:
        lo, hi = lo * 1.8 + 32.0, hi * 1.8 + 32.0
    return all(lo <= v <= hi for v in vals)


def _slot_keys(data: dict) -> dict[int, str]:
    """TilauScope device each extra-device slot opens as, the way Artisan loads it."""
    key_of_id = {d['id']: k for k, d in TILAU_DEVICES.items()}
    name_map: dict[int, str] = {}
    for raw_slot, key in (data.get('tilau_name_map') or {}).items():
        try:
            name_map[int(raw_slot)] = key
        except (TypeError, ValueError):
            continue
    keys: dict[int, str] = {}
    for slot, dev in enumerate(data.get('extradevices') or []):
        key = name_map.get(slot)
        if key not in TILAU_DEVICES:
            key = key_of_id.get(dev)
        if key is not None:
            keys[slot] = key
    return keys


def device_shift(data: dict) -> Finding | None:
    """Channels whose readings the device they open as cannot produce."""
    fahrenheit = data.get('mode') == 'F'
    wrong = []
    for slot, key in _slot_keys(data).items():
        for channel, sig in enumerate(_SIGNATURES.get(key, ()), start=1):
            if sig is None:
                continue
            vals = [float(v) for v in _channel(data, slot, channel)[0] if _valid(v)]
            if len(vals) >= _MIN_SAMPLES and not _fits(sig, vals, fahrenheit):
                wrong.append((TILAU_DEVICES[key]['label'].lstrip('+'), channel,
                              round(min(vals)), round(max(vals))))
    return (DEVICE_SHIFT, tuple(wrong)) if wrong else None


def _pid_preheat(data: dict) -> bool:
    """Same proof as the PID scanner: the recorded SV, or its start event."""
    if data.get('tilau_preheat_sv_c') is not None:
        return True
    return any(t == 4 and s == 'TilauPID Preheat started'
               for t, s in zip(data.get('specialeventstype') or [],
                               data.get('specialeventsStrings') or [], strict=False))


def preheat_commands(data: dict, heater_slider: int) -> list[tuple[int, int]] | None:
    """Burner commands of a TilauPID preheat that reached neither the event list
    nor a burner channel the PID reads, read back from the echo of `heater_slider`.

    Returns [(sample index, percent)] — one command per change up to CHARGE — or
    None when the PID already has its hold power or nothing can be read back.
    """
    ti = normalize_timeindex(data.get('timeindex', []))
    timex = data.get('timex') or []
    if not marked(ti, RoastingPhase.CHARGE) or ti[RoastingPhase.CHARGE] >= len(timex):
        return None
    if not _pid_preheat(data) or REBUILT_KEY in data:
        return None
    if len({len(data.get(k) or []) for k in EVENT_KEYS}) != 1:
        return None
    charge = ti[RoastingPhase.CHARGE]
    if (AlogScanner._heater_events(data, charge) is not None  # noqa: SLF001
            or AlogScanner._burner_channel(data) is not None):  # noqa: SLF001
        return None
    # Artisan labels the echo channel of slider n `{n}`
    for slot, name in enumerate(data.get('extraname1') or []):
        if str(name) != f'{{{heater_slider}}}':
            continue
        values, times = _channel(data, slot, 1)
        before = [(t, float(v)) for t, v in zip(times, values, strict=False)
                  if _valid(v) and t <= timex[charge]]
        if len(before) < _MIN_SAMPLES or not _fits(_ACTUATOR, [v for _t, v in before], False):
            return None
        commands: list[tuple[int, int]] = []
        for t, v in before:
            if not commands or commands[-1][1] != round(v):
                commands.append((max(0, bisect_right(timex, t) - 1), round(v)))
        return commands if len(commands) >= 2 else None
    return None


def _event_rows(data: dict) -> list[tuple]:
    return list(zip(*(data.get(k) or [] for k in EVENT_KEYS), strict=True))


def _with_event_rows(data: dict, rows: list[tuple]) -> dict:
    out = dict(data)
    for i, k in enumerate(EVENT_KEYS):
        out[k] = [r[i] for r in rows]
    return out


def rebuild_preheat_commands(data: dict, heater_slider: int) -> dict | None:
    """`data` with the missing preheat commands written as TilauPID events, or None."""
    commands = preheat_commands(data, heater_slider)
    if commands is None:
        return None
    added = [(idx, heater_slider, events_external_to_internal_value(pct), f'S{heater_slider}:{pct}%')
             for idx, pct in commands]
    # stable sort: events already recorded keep their order at a shared index
    out = _with_event_rows(data, sorted(_event_rows(data) + added, key=lambda r: r[0]))
    out[REBUILT_KEY] = [list(a) for a in added]
    return out


def undo_preheat_commands(data: dict) -> dict | None:
    """`data` without the commands rebuild_preheat_commands added, or None when
    its event lists no longer line up."""
    if len({len(data.get(k) or []) for k in EVENT_KEYS}) != 1:
        return None
    pending = [tuple(a) for a in data.get(REBUILT_KEY) or []]
    rows = []
    for row in _event_rows(data):
        if row in pending:
            pending.remove(row)
        else:
            rows.append(row)
    out = _with_event_rows(data, rows)
    out.pop(REBUILT_KEY, None)
    return out


def rebuilt_count(data: dict) -> int:
    return len(data.get(REBUILT_KEY) or [])


def power_meter(data: dict) -> Finding | None:
    """A power meter that recorded nothing, fell silent, or never saw the heater."""
    ti = normalize_timeindex(data.get('timeindex', []))
    for channel in (1, 2):
        for slot, name in enumerate(data.get(f'extraname{channel}') or []):
            if str(name).strip().lower() != ROASTER:
                continue
            values, times = _channel(data, slot, channel)
            if not any(_valid(v) for v in values):
                return (POWER_METER, (METER_EMPTY,))
            silence, start = 0.0, None
            for v, t in zip(values, times, strict=False):
                if _valid(v):
                    start = None
                else:
                    start = t if start is None else start
                    silence = max(silence, t - start)
            if silence >= _METER_SILENCE_S:
                return (POWER_METER, (METER_SILENT, round(silence)))
            if marked(ti, RoastingPhase.CHARGE) and marked(ti, RoastingPhase.DROP):
                roast = [v for v in values[ti[RoastingPhase.CHARGE]:ti[RoastingPhase.DROP] + 1]
                         if _valid(v)]
                if roast and max(roast) < _METER_IDLE_W:
                    return (POWER_METER, (METER_IDLE,))
            return None
    return None


def _roast_span(data: dict) -> tuple[list[float], list[float], int, int] | None:
    """(timex, BT, CHARGE, DROP) when both are marked inside the curve."""
    ti = normalize_timeindex(data.get('timeindex', []))
    timex = data.get('timex') or []
    bt = data.get('temp2') or []
    if not (marked(ti, RoastingPhase.CHARGE) and marked(ti, RoastingPhase.DROP)):
        return None
    charge, drop = ti[RoastingPhase.CHARGE], ti[RoastingPhase.DROP]
    if not 0 <= charge < drop < min(len(timex), len(bt)):
        return None
    return timex, bt, charge, drop


def _bt_ok(v: object) -> bool:
    return isinstance(v, (int, float)) and v > 0


def bt_gaps(data: dict) -> Finding | None:
    span = _roast_span(data)
    if span is None:
        return None
    timex, bt, charge, drop = span
    missing = sum(1 for i in range(charge, drop + 1) if not _bt_ok(bt[i]))
    longest, last = 0.0, None
    for i in range(charge, drop + 1):
        if _bt_ok(bt[i]):
            if last is not None:
                longest = max(longest, timex[i] - timex[last])
            last = i
    if missing >= _BT_GAP_COUNT or longest > _BT_GAP_S:
        return (BT_GAPS, (missing, round(longest)))
    return None


def _turning_point(bt: list[float], charge: int, drop: int) -> int | None:
    valid = [i for i in range(charge, drop + 1) if _bt_ok(bt[i])]
    return min(valid, key=lambda i: bt[i]) if valid else None


def milestone_order(data: dict) -> Finding | None:
    span = _roast_span(data)
    if span is None:
        return None
    _timex, bt, charge, drop = span
    ti = normalize_timeindex(data.get('timeindex', []))
    tp = _turning_point(bt, charge, drop)
    dry = ti[RoastingPhase.DRYEND] if marked(ti, RoastingPhase.DRYEND) else None
    fcs = ti[RoastingPhase.FCSTART] if marked(ti, RoastingPhase.FCSTART) else None
    wrong = []
    if dry is not None and tp is not None and dry <= tp:
        wrong.append(DRY_BEFORE_TP)
    if fcs is not None and dry is not None and fcs <= dry:
        wrong.append(FC_BEFORE_DRY)
    if fcs is not None and fcs >= drop:
        wrong.append(FC_AFTER_DROP)
    return (MILESTONE_ORDER, tuple(wrong)) if wrong else None


def ror_outlier(data: dict) -> Finding | None:
    """A rate of rise no bean in a drum produces: the probe jumped."""
    span = _roast_span(data)
    if span is None:
        return None
    timex, bt, charge, drop = span
    tp = _turning_point(bt, charge, drop)
    if tp is None:
        return None
    scale = 1.8 if data.get('mode') == 'F' else 1.0
    worst = 0.0
    for j in range(tp, drop + 1):
        if timex[j] - timex[tp] < 2 * _ROR_WINDOW_S or not _bt_ok(bt[j]):
            continue
        k = bisect_right(timex, timex[j] - _ROR_WINDOW_S) - 1
        if k < 0 or not _bt_ok(bt[k]) or timex[j] <= timex[k]:
            continue
        ror = 60.0 * (bt[j] - bt[k]) / (timex[j] - timex[k]) / scale
        if not _ROR_RANGE_C[0] <= ror <= _ROR_RANGE_C[1] and abs(ror) > abs(worst):
            worst = ror
    return (ROR_OUTLIER, (round(worst),)) if worst else None


def check_alog(data: dict, heater_slider: int) -> list[Finding]:
    """Every finding a single file shows on its own, most severe first."""
    percents = [p for _i, p in preheat_commands(data, heater_slider) or []]
    findings = [f for f in (
        device_shift(data),
        (PREHEAT_COMMANDS, (len(percents), min(percents), max(percents))) if percents else None,
        power_meter(data),
        bt_gaps(data),
        milestone_order(data),
        ror_outlier(data),
        (SIMULATED, ()) if data.get('tilau_simulated') is True else None,
    ) if f is not None]
    return sorted(findings, key=lambda f: SEVERITY.index(f[0]))

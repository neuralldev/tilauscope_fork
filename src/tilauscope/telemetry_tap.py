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
# Tilau 2025-2026

#
# telemetry_tap.py
#
# ## TILAU ## Upward telemetry bridge for remote control (Phase 1b).
#
# Lives on the Qt main thread. Subscribes to qmc.tilauUpdateSignal (~1 Hz TIMER
# ticks), builds a light `telemetry` delta and a full `snapshot` from plain qmc
# arrays, and hands them to TilauWebHost, which fans them out to WebSocket
# observers off-thread (call_soon_threadsafe). See
# wiki/RemoteControl-Protocol-v1.md §3 (the Bridge) and §5 (message shapes).
#
# Doctrine respected:
#   - never block the ~1 Hz loop: does nothing when no phone is connected, and
#     only builds a (downsampled) snapshot then;
#   - broad try/except so a telemetry glitch can never disturb Artisan's LCDs;
#   - reads only plain-python qmc data, emits only via the host (no Qt off-thread).

import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot

_log = logging.getLogger(__name__)

# qmc.timeindex slots we surface as markers (amateur set — FCe/SCe omitted).
_MARKERS = ((0, 'CHARGE'), (1, 'DRYe'), (2, 'FCs'), (4, 'SCs'), (6, 'DROP'))
_SERIES_MAX = 200  # downsample cap for the snapshot series


def _read_sliders(aw) -> dict:
    """Current values (%) of the enabled event sliders, keyed `slider{i}` to match
    the welcome channel ids (§5 recalage). Skips SV and sliders disabled in
    Artisan config, mirroring displayscope / the command bridge."""
    try:
        from tilauscope.roast_asssistant import _read_slider_pct
        out = {}
        vis = getattr(aw, 'eventslidervisibilities', None)
        for i in range(4):  # SV (index 4) excluded
            try:
                if vis is not None and not bool(vis[i]):
                    continue
            except Exception:  # noqa: BLE001
                pass
            v = _read_slider_pct(aw, i)
            if v is not None:
                out[f'slider{i}'] = v
        return out
    except Exception:  # noqa: BLE001
        return {}


def _num(v) -> Optional[float]:
    # Artisan uses -1 as the "no reading" sentinel; NaN also occurs.
    try:
        if v is None:
            return None
        f = float(v)
        if f != f or f <= -1:  # NaN or sentinel
            return None
        return round(f, 1)
    except Exception:  # noqa: BLE001
        return None


class TelemetryTap(QObject):
    def __init__(self, aw, host) -> None:
        super().__init__()
        self._aw = aw
        self._host = host
        self._last_sec = -1
        self._last_sliders = None  # last broadcast slider dict (omit when unchanged, §5)
        self._last_marks = set()   # milestones already announced (event dedup, §5)
        try:
            aw.qmc.tilauUpdateSignal.connect(self._on_update)
            _log.info("TelemetryTap connected to tilauUpdateSignal")
        except Exception as e:  # noqa: BLE001
            _log.warning("TelemetryTap not connected: %s", e)

    @pyqtSlot(int, object, object, bool)
    def _on_update(self, data, _value=None, _raw=None, _button=True) -> None:
        try:
            if data != 10:  # only the 1 Hz TIMER tick
                return
            qmc = self._aw.qmc
            if not getattr(qmc, 'flagon', False):
                return
            timex = qmc.timex
            if not timex:
                return
            now = float(timex[-1])
            sec = int(now)
            if sec <= self._last_sec:  # 1 Hz cap
                return
            self._last_sec = sec

            # nobody watching -> do no work at all
            if not self._host.has_clients():
                return

            ti = qmc.timeindex
            charged = bool(ti and ti[0] > -1)
            charge_t = float(timex[ti[0]]) if charged else None
            bt = _num(qmc.temp2[-1]) if qmc.temp2 else None
            et = _num(qmc.temp1[-1]) if qmc.temp1 else None
            ror = _num(qmc.delta2[-1]) if getattr(qmc, 'delta2', None) else None
            phase = self._phase(qmc, ti, charged)

            tele = {'bt': bt, 'et': et, 'ror': ror, 'phase': phase,
                    'clock': round(now, 1)}
            if charge_t is not None:
                tele['t'] = round(now - charge_t, 1)
            sliders = _read_sliders(self._aw)
            if sliders != self._last_sliders:  # §5: omit when unchanged
                tele['sliders'] = sliders
                self._last_sliders = sliders
            self._host.publish_telemetry(tele)
            self._host.publish_snapshot(
                self._snapshot(qmc, ti, charged, charge_t, now, phase))

            # milestone events — source-agnostic (a mark set on the desktop OR
            # from a remote command is announced once, §5). Set shrinks on RESET.
            marks = set()
            for idx, name in _MARKERS:
                if idx >= len(ti):
                    continue
                pos = ti[idx]
                if (pos > -1) if idx == 0 else (pos > 0):
                    marks.add(name)
            for name in (marks - self._last_marks):
                ev = {'kind': 'milestone', 'name': name}
                if charge_t is not None:
                    ev['t'] = round(now - charge_t, 1)
                self._host.publish_event(ev)
            # a milestone can also be UNDONE (desktop toggle or remote undo) — tell
            # the phone so its progress pips shrink back (§5). Additive field.
            for name in (self._last_marks - marks):
                self._host.publish_event({'kind': 'milestone', 'name': name,
                                          'state': 'removed'})
            self._last_marks = marks
        except Exception:  # noqa: BLE001  never disturb Artisan's refresh
            return

    @staticmethod
    def _phase(qmc, ti, charged: bool) -> str:
        if not charged:
            return 'preheat' if getattr(qmc, 'flagon', False) else 'idle'
        try:
            if ti[6] > 0:
                return 'cooling'
            if ti[2] > 0:
                return 'development'
            if ti[1] > 0:
                return 'maillard'
        except Exception:  # noqa: BLE001
            pass
        return 'drying'

    def _snapshot(self, qmc, ti, charged, charge_t, now, phase) -> dict:
        base = charge_t if charge_t is not None else 0.0
        timex = qmc.timex or []
        n = len(timex)
        step = max(1, n // _SERIES_MAX)
        t_ser, bt_ser, et_ser, ror_ser = [], [], [], []
        temp1, temp2 = qmc.temp1 or [], qmc.temp2 or []
        delta2 = getattr(qmc, 'delta2', None) or []
        for i in range(0, n, step):
            t_ser.append(round(float(timex[i]) - base, 1))
            bt_ser.append(_num(temp2[i]) if i < len(temp2) else None)
            et_ser.append(_num(temp1[i]) if i < len(temp1) else None)
            ror_ser.append(_num(delta2[i]) if i < len(delta2) else None)

        markers = []
        for idx, name in _MARKERS:
            try:
                pos = ti[idx]
                marked = (pos > -1) if idx == 0 else (pos > 0)
                if marked and pos < n:
                    markers.append({'name': name,
                                    't': round(float(timex[pos]) - base, 1),
                                    'bt': _num(temp2[pos]) if pos < len(temp2) else None})
            except Exception:  # noqa: BLE001
                continue

        return {'phase': phase, 'charge_marked': charged, 'clock': round(now, 1),
                'recording': bool(getattr(qmc, 'flagstart', False)),
                'series': {'t': t_ser, 'bt': bt_ser, 'et': et_ser, 'ror': ror_ser},
                'markers': markers, 'sliders': _read_sliders(self._aw)}

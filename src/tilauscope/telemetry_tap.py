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
import math
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot

_log = logging.getLogger(__name__)


def _lcd_seconds(qmc, timex, ti) -> Optional[int]:
    """Artisan's LCD timer value, in whole seconds, computed EXACTLY like
    canvas.updateLCDtime + stringfromseconds so the phone shows the same number
    as the desktop: a live wall clock (timeclock.elapsedMilli, which returns
    seconds) referenced to DROP, else CHARGE, else monitor start; round-half-up.
    Only meaningful while recording (flagstart) — None otherwise."""
    try:
        if not getattr(qmc, 'flagstart', False):
            return None
        tx = float(qmc.timeclock.elapsedMilli())  # seconds, despite the name
        if len(ti) == 8 and ti[6] != 0 and len(timex) > ti[6]:
            ts = tx - float(timex[ti[6]])          # since DROP (cooling)
        elif len(ti) > 0 and ti[0] != -1 and len(timex) > ti[0]:
            ts = tx - float(timex[ti[0]])          # since CHARGE
        else:
            ts = tx                                # monitoring, before CHARGE
        return int(math.floor(ts + 0.5))
    except Exception:  # noqa: BLE001
        return None

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


def _axf(v) -> Optional[float]:
    # plain float for axis limits — NO sentinel filtering (a temp/RoR axis floor
    # can legitimately be <= -1, unlike a live reading).
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _axes(qmc) -> dict:
    """Artisan's configured axis bounds so the phone graph keeps the same shape and
    limits as the desktop canvas (temp = y, RoR = z, in the current unit)."""
    return {'tmin': _axf(getattr(qmc, 'ylimit_min', None)),
            'tmax': _axf(getattr(qmc, 'ylimit', None)),
            'rmin': _axf(getattr(qmc, 'zlimit_min', None)),
            'rmax': _axf(getattr(qmc, 'zlimit', None))}


def _colors(qmc) -> dict:
    """Artisan's own curve colours, straight from the user-configurable palette.

    The phone must draw BT/ET/RoR in exactly the hues the desktop uses: the same
    curve in two different colours on two screens is precisely the sort of thing
    that gets misread mid-roast. Missing keys are simply omitted and the client
    keeps its built-in defaults.
    """
    pal = getattr(qmc, 'palette', None) or {}
    out = {}
    for key, name in (('bt', 'bt'), ('et', 'et'), ('deltabt', 'ror')):
        try:
            v = pal.get(key)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(v, str) and v:
            out[name] = v
    return out


class TelemetryTap(QObject):
    def __init__(self, aw, host) -> None:
        super().__init__()
        self._aw = aw
        self._host = host
        self._last_sec = -1
        self._last_sliders = None  # last broadcast slider dict (omit when unchanged, §5)
        self._last_marks = set()   # milestones already announced (event dedup, §5)
        self._last_recording = None  # last announced flagstart (None = not yet known)
        self._last_on = None         # last announced flagon (None = not yet known)
        self._last_axes = None       # last broadcast axis bounds (omit when unchanged)
        self._last_colors = None     # last broadcast curve colours (omit when unchanged)
        try:
            aw.qmc.tilauUpdateSignal.connect(self._on_update)
            _log.info("TelemetryTap connected to tilauUpdateSignal")
        except Exception as e:  # noqa: BLE001
            _log.warning("TelemetryTap not connected: %s", e)

    @pyqtSlot(int, object, object, bool)
    def _on_update(self, data, _value=None, _raw=None, _button=True) -> None:
        try:
            # 10 = timer LCD, 12 = BT LCD. Both beat at 1 Hz, but the timer tick is
            # emitted from updateLCDtime(), which is guarded by `flagstart and
            # flagon` — it therefore goes SILENT the instant recording stops, and
            # cannot carry the two events the phone most needs to hear: the STOP
            # itself and the RESET that follows. The BT LCD comes from updateLCDs(),
            # which keeps running for as long as monitoring is on. It is what drives
            # the state watch below. During recording both fire and the 1 Hz
            # watermark de-duplicates them.
            if data not in (10, 12):
                return
            qmc = self._aw.qmc
            # state first: a STOP or a RESET must be announced even though this very
            # tick may be the last one we ever get (see sync_state).
            self._state_watch(qmc)
            if not bool(getattr(qmc, 'flagon', False)):
                self._last_sec = -1  # sampling stopped: the next run starts fresh
                return
            # monitoring but not recording: nothing new lands in the recording
            # arrays (Artisan samples into on_timex/on_temp* then), so there is no
            # telemetry to send — the state watch above was the whole job.
            rec = bool(getattr(qmc, 'flagstart', False))
            if not rec:
                return
            timex = qmc.timex
            if not timex:
                # RESET empties the series. Forget the 1 Hz watermark here too, or
                # the next session (which restarts near t=0) would be swallowed
                # tick after tick as "already seen" until it outran the old roast.
                self._last_sec = -1
                return
            now = float(timex[-1])
            sec = int(now)
            if sec < self._last_sec:  # clock ran backwards -> RESET / new session
                self._last_sec = -1
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

            ltime = _lcd_seconds(qmc, timex, ti)  # match the desktop LCD exactly
            # `recording` rides along on every tick (additive field): the edge event
            # below only fires if the tap already observed the PREVIOUS state, which
            # it cannot when the change happened while no phone was connected or
            # while monitoring was off. Carrying the level as well as the edge lets
            # the client reconcile every second instead of trusting one message.
            tele = {'bt': bt, 'et': et, 'ror': ror, 'phase': phase,
                    'clock': round(now, 1), 'ltime': ltime, 'recording': rec}
            if charge_t is not None:
                tele['t'] = round(now - charge_t, 1)
            sliders = _read_sliders(self._aw)
            if sliders != self._last_sliders:  # §5: omit when unchanged
                tele['sliders'] = sliders
                self._last_sliders = sliders
            # Axis bounds used to travel in the snapshot only, i.e. once per
            # connection: a phone that connected before the first real snapshot
            # existed was stuck auto-scaling forever, and nobody saw Artisan's own
            # axis adjustment at DROP. Sent here whenever they actually change.
            axes = _axes(qmc)
            if axes != self._last_axes:
                tele['axes'] = axes
                self._last_axes = axes
            colors = _colors(qmc)  # follow a palette/theme change on the desktop
            if colors != self._last_colors:
                tele['colors'] = colors
                self._last_colors = colors
            self._host.publish_telemetry(tele)
            self._host.publish_snapshot(
                self._snapshot(qmc, ti, charged, charge_t, now, phase, ltime))

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

    def sync_state(self) -> None:
        """Publish any pending monitor / recorder / session change immediately.

        Called from displayscope.update_status_text(), which already runs at every
        point where TilauScope knows the desktop state changed. The tick-driven
        path cannot carry this on its own: STOP in simulator mode takes monitoring
        down with it, and once Artisan stops sampling there is no further tick to
        announce anything. Same thread as the tick path (Qt main), so no locking.
        """
        try:
            self._state_watch(self._aw.qmc)
        except Exception:  # noqa: BLE001  never disturb the caller's UI refresh
            return

    def _state_watch(self, qmc) -> None:
        """Diff the desktop's durable state against what the phone was last told.

        Deliberately cheap (a few attribute reads and one emptiness test): it runs
        on every tick as well as on demand. Each transition is announced once.
        """
        on = bool(getattr(qmc, 'flagon', False))
        if on != self._last_on:
            if self._last_on is not None:
                self._host.publish_event({'kind': 'monitor',
                                          'state': 'on' if on else 'off'})
                if not on:
                    # the stored snapshot was built while still sampling; correct it
                    # so a phone connecting later doesn't see a live view
                    self._host.patch_snapshot(monitoring=False)
            self._last_on = on

        # recorder — source-agnostic: a START/STOP pressed on the DESKTOP has to
        # reach the phone too (the bridge only announces the phone's own commands).
        rec = bool(getattr(qmc, 'flagstart', False))
        if rec != self._last_recording:
            if self._last_recording is not None:
                self._host.publish_event({'kind': 'recorder',
                                          'state': 'started' if rec else 'stopped'})
                self._host.patch_snapshot(recording=rec)
            self._last_recording = rec

        # RESET wipes the series and every milestone. `_last_sec >= 0` means we did
        # have a roast in hand, so this fires exactly once per reset — not on every
        # tick of an idle desktop that has simply never recorded anything.
        if not qmc.timex and self._last_sec >= 0:
            self._host.publish_event({'kind': 'session', 'state': 'reset'})
            self._last_sec = -1
            self._last_marks = set()
            self._last_sliders = None
            # a phone connecting after the reset must not be handed the old roast
            self._host.patch_snapshot(
                phase='idle', charge_marked=False, recording=False, ltime=None,
                series={'t': [], 'bt': [], 'et': [], 'ror': []}, markers=[])

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

    def _snapshot(self, qmc, ti, charged, charge_t, now, phase, ltime=None) -> dict:
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
                'recording': bool(getattr(qmc, 'flagstart', False)), 'ltime': ltime,
                'monitoring': bool(getattr(qmc, 'flagon', False)),
                'axes': _axes(qmc), 'colors': _colors(qmc),
                'series': {'t': t_ser, 'bt': bt_ser, 'et': et_ser, 'ror': ror_ser},
                'markers': markers, 'sliders': _read_sliders(self._aw)}

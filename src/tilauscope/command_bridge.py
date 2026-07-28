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
# command_bridge.py
#
# ## TILAU ## Downward command path for remote control (Phase 2a).
#
# Lives on the Qt main thread. The WS control server (webcontrol.py, loop thread)
# hands it *jobs* through a queued Qt signal — never touching qmc/widgets from the
# async thread (protocol §2/§3, invariant §8). The bridge applies `set_slider` via
# the exact canonical human gesture (reusing roast_asssistant._apply_slider_value)
# and reports the value actually applied back for the `ack` recalage; it also hosts
# the desktop takeover-confirmation modal (controller lock, protocol §7).
#
# Doctrine: reuse the existing slider helpers (single source of the canonical
# sequence), broad try/except so a remote command can never disturb Artisan.

import logging
import os

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

_log = logging.getLogger(__name__)

# Skywalker rig slider index map (see roast_asssistant._read_slider_pct):
#   0 = integrated airflow, 1 = drum, 2 = damper (AirWave extraction), 3 = burner.
# `heat` resolves dynamically (config, fallback 3); air/drum are fixed for now and
# will move to a per-roaster resolver when a second roaster needs it.
_AIR_EXTRACT_IDX = 2
_DRUM_IDX = 1

# milestone name (protocol §5) -> qmc mark signal (canvas.py). Emitting the signal
# is the exact desktop mark-button path (displayscope: markChargeSignal.emit(False)).
_MARK_SIGNALS = {
    'CHARGE': 'markChargeSignal', 'DRYe': 'markDRYSignal', 'DRY': 'markDRYSignal',
    'FCs': 'markFCsSignal', 'FCe': 'markFCeSignal',
    'SCs': 'markSCsSignal', 'SCe': 'markSCeSignal', 'DROP': 'markDropSignal',
}

_TAKEOVER_TTL = 20  # seconds before a takeover request auto-denies (safe default)

_BG = "#1E1E2E"; _SURFACE = "#313244"; _OVERLAY = "#45475A"
_TEXT = "#CDD6F4"; _SUB = "#A6ADC8"; _ACCENT = "#89B4FA"
_RED = "#F38BA8"; _GREEN = "#A6E3A1"; _YELLOW = "#F9E2AF"


class CommandBridge(QObject):
    """Applies remote commands on the Qt main thread (protocol §6 sequence).

    submit(job) is thread-safe (queued signal); every job carries a `done`
    callback the caller uses to marshal the result back onto its own loop.
    """

    _job = pyqtSignal(object)

    def __init__(self, aw) -> None:
        super().__init__()
        self._aw = aw
        self._job.connect(self._on_job)  # AutoConnection -> queued to main thread
        # welcome channels, from real Artisan slider config, built on the main
        # thread and cached (plain data → safe to read from the WS loop thread).
        self._channels = self._build_channels()

    # ---- capabilities (welcome channels, §5) --------------------------------

    def _build_channels(self) -> list:
        """Advertise every ENABLED event slider (0-3; SV/index 4 excluded), each
        with its Artisan-configured name (`qmc.etypes[i]`, like displayscope) and
        real bounds/step (`eventslidermin/max`, `eventSliderStepSize`). A slider
        disabled in Artisan (`eventslidervisibilities`) is not exposed. Built once
        on the main thread and cached (plain data → safe on the WS loop thread)."""
        aw = self._aw
        try:
            etypes = list(getattr(aw.qmc, 'etypes', []) or [])
        except Exception:  # noqa: BLE001
            etypes = []
        out = []
        for i in range(4):  # 4 event sliders; SV (index 4) intentionally excluded
            try:
                if not bool(aw.eventslidervisibilities[i]):
                    continue  # slider disabled in Artisan config -> not exposed
            except Exception:  # noqa: BLE001
                pass
            label = str(etypes[i]) if i < len(etypes) and etypes[i] else f'Slider {i + 1}'
            try:
                mn = int(aw.eventslidermin[i])
                mx = int(aw.eventslidermax[i])
                step = int(aw.eventSliderStepSize(i)) or 1
            except Exception:  # noqa: BLE001
                mn, mx, step = 0, 100, 1
            ch = {'id': f'slider{i}', 'label': label, 'status': 'controllable',
                  'min': mn, 'max': mx, 'step': step, 'unit': '%'}
            if i == _DRUM_IDX:
                ch['advisory_midroast'] = 'drum_midroast'
            elif i == _AIR_EXTRACT_IDX:
                ch['coupled'] = True  # pull machine: airflow coupled with extraction
            out.append(ch)
        return out

    def channels(self) -> list:
        """Cached welcome channels (plain data; safe to read off the main thread)."""
        return list(self._channels)

    # ---- public (any thread) ------------------------------------------------

    def submit(self, job: dict) -> None:
        self._job.emit(job)

    # ---- main-thread execution ----------------------------------------------

    @pyqtSlot(object)
    def _on_job(self, job: object) -> None:
        try:
            kind = job.get('kind')
            done = job.get('done')
            if kind == 'set_slider':
                res = self._apply_set_slider(job.get('channel'), job.get('value'))
            elif kind == 'mark':
                res = self._do_mark(job.get('milestone'))
            elif kind == 'recorder':
                res = self._do_recorder(job.get('op'), job.get('save'))
            elif kind == 'save':
                res = self._persist_roast()
            elif kind == 'discard':
                res = self._do_discard(job.get('confirm'))
            elif kind == 'confirm_takeover':
                res = self._confirm_takeover(job.get('requester_name') or 'A phone')
            else:
                res = {'status': 'rejected', 'reason': 'BAD_MESSAGE'}
            if done is not None:
                done(res)
        except Exception:  # noqa: BLE001  never disturb the main thread
            _log.exception("command bridge job failed")
            done = job.get('done') if isinstance(job, dict) else None
            if done is not None:
                with_suppress(done, {'status': 'rejected', 'reason': 'BAD_MESSAGE'})

    # ---- set_slider ---------------------------------------------------------

    def _resolve_idx(self, channel: str):
        # primary scheme: sliderN -> event slider index N (mirrors displayscope)
        if channel.startswith('slider') and channel[6:].isdigit():
            n = int(channel[6:])
            return n if 0 <= n <= 3 else None
        # legacy semantic ids (kept for the browser test page / back-compat)
        if channel == 'heat':
            from tilauscope.roast_asssistant import _burner_slider_idx
            return _burner_slider_idx(self._aw)
        if channel in ('air', 'extract', 'air_extract'):
            return _AIR_EXTRACT_IDX
        if channel == 'drum':
            return _DRUM_IDX
        return None

    def _apply_set_slider(self, channel, value) -> dict:
        from tilauscope.roast_asssistant import _apply_slider_value, _read_slider_pct
        idx = self._resolve_idx(str(channel))
        if idx is None:
            return {'status': 'rejected', 'reason': 'CHANNEL_ABSENT', 'channel': channel}
        # slider disabled in Artisan config (mirrors displayscope visibility) (§6)
        try:
            if not bool(self._aw.eventslidervisibilities[idx]):
                return {'status': 'rejected', 'reason': 'CHANNEL_ABSENT', 'channel': channel}
        except Exception:  # noqa: BLE001
            pass
        # display-only (no hardware wired to this slider) -> refuse cleanly (§6)
        try:
            if int(self._aw.eventslideractions[idx]) == 0:
                return {'status': 'rejected', 'reason': 'CHANNEL_READONLY', 'channel': channel}
        except Exception:  # noqa: BLE001
            pass
        try:
            requested = float(value)
        except (TypeError, ValueError):
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE', 'channel': channel}
        ok = _apply_slider_value(self._aw, idx, requested)
        applied = _read_slider_pct(self._aw, idx)
        if not ok or applied is None:
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE', 'channel': channel}
        # applied may differ from requested via bounds clamp or step rounding (§6)
        status = 'ok' if applied == int(round(requested)) else 'clamped'
        advisory = 'drum_midroast' if (idx == _DRUM_IDX and self._midroast()) else None
        return {'status': status, 'channel': channel,
                'applied_value': applied, 'advisory': advisory}

    def _midroast(self) -> bool:
        try:
            ti = self._aw.qmc.timeindex
            return bool(ti and ti[0] > -1 and ti[6] == 0)  # CHARGE marked, no DROP
        except Exception:  # noqa: BLE001
            return False

    # ---- mark (milestones) --------------------------------------------------

    def _do_mark(self, milestone) -> dict:
        name = _MARK_SIGNALS.get(str(milestone))
        if name is None:
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}
        sig = getattr(self._aw.qmc, name, None)
        if sig is None:
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}
        sig.emit(False)  # same call as the desktop mark button; the milestone
        # `event` is broadcast source-agnostically by TelemetryTap on the next tick
        return {'status': 'ok'}

    # ---- recorder (START / STOP) --------------------------------------------

    def _do_recorder(self, op, save=None) -> dict:
        tm = getattr(self._aw, 'tilauscope_main', None)
        if tm is None:  # remote piloting needs the TilauScope window (2a limitation)
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}
        roasting = bool(getattr(tm, 'is_roasting', False))
        if op == 'start':
            if not roasting:
                tm.toggle_start_stop(True)   # guards no-meter + sets state (§ reuse)
            if bool(getattr(tm, 'is_roasting', False)):
                self._broadcast_event({'kind': 'recorder', 'state': 'started'})
                return {'status': 'ok'}
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}
        if op == 'stop':
            return self._recorder_stop(tm, roasting, save)
        return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}

    def _recorder_stop(self, tm, roasting, save) -> dict:
        """STOP with the §5 save flag: None=desktop default, False=don't write
        (non-destructive), True=persist even if autosave is off."""
        if save is None:  # follow the desktop autosave setting (OffRecorder decides)
            if roasting:
                tm.toggle_start_stop(False)
            self._broadcast_event({'kind': 'recorder', 'state': 'stopped'})
            return {'status': 'ok'}
        # explicit control: suppress OffRecorder's own autosave, decide here
        qmc = self._aw.qmc
        old = qmc.autosaveflag
        try:
            qmc.autosaveflag = 0
            if roasting:
                tm.toggle_start_stop(False)
        finally:
            qmc.autosaveflag = old
        if not save:  # stopped, nothing written (non-destructive "finish on Artisan")
            self._broadcast_event({'kind': 'recorder', 'state': 'stopped', 'saved': False})
            return {'status': 'ok', 'saved': False}
        r = self._persist_roast()  # force a save even if autosave is off
        saved = r.get('status') == 'ok'
        self._broadcast_event({'kind': 'recorder', 'state': 'stopped',
                               'saved': saved, 'path': r.get('path')})
        # the STOP itself always succeeded; report ok and let `saved`/`reason`
        # tell the client the save couldn't happen (e.g. INCOMPLETE_ROAST).
        if saved:
            return {'status': 'ok', 'saved': True, 'path': r.get('path')}
        return {'status': 'ok', 'saved': False, 'reason': r.get('reason')}

    # ---- save / discard (persistence, §5) -----------------------------------

    def _persist_roast(self) -> dict:
        """Force-save the current roast, no dialog. CHARGE+DROP required (§8 inv.7).

        Saves into the TilauScope roast folder (`alogDirectory`, set in Bean Cave
        settings) — that is where every TilauScope roast lives (roast list, plan
        model). It is preferred over Artisan's `autosavepath` so a phone save does
        not land in the system Documents folder. Reuses fileSave (explicit path =
        no dialog)."""
        aw = self._aw
        qmc = aw.qmc
        try:
            if not qmc.timex or len(qmc.timex) < 3:
                return {'status': 'rejected', 'reason': 'NOTHING_TO_SAVE', 'saved': False}
            ti = qmc.timeindex
            if not (ti and ti[0] != -1 and ti[6] != 0):  # CHARGE and DROP marked
                return {'status': 'rejected', 'reason': 'INCOMPLETE_ROAST', 'saved': False}
            from PyQt6.QtCore import QSettings
            alog_dir = QSettings().value('alogDirectory', '', str)
            directory = ''
            for cand in (alog_dir, qmc.autosavepath):  # TilauScope folder first
                if cand and os.path.isdir(str(cand)):
                    directory = str(cand)
                    break
            if not directory:
                return {'status': 'rejected', 'reason': 'NOTHING_TO_SAVE', 'saved': False}
            prefix = ''
            if qmc.autosaveprefix:
                prefix = qmc.autosaveprefix
            elif qmc.batchcounter > -1 and qmc.roastbatchnr > 0:
                prefix = qmc.batchprefix + str(qmc.roastbatchnr)
            elif qmc.batchprefix:
                prefix = qmc.batchprefix
            path = os.path.join(directory, aw.generateFilename(prefix=prefix))
            if bool(aw.fileSave(path)):
                return {'status': 'ok', 'saved': True, 'path': path}
            return {'status': 'rejected', 'reason': 'NOTHING_TO_SAVE', 'saved': False}
        except Exception:  # noqa: BLE001
            _log.exception("remote save failed")
            return {'status': 'rejected', 'reason': 'NOTHING_TO_SAVE', 'saved': False}

    def _do_discard(self, confirm) -> dict:
        """Throw away the current roast (destructive, §5 — requires confirm)."""
        if not confirm:
            return {'status': 'rejected', 'reason': 'CONFIRM_REQUIRED'}
        aw = self._aw
        qmc = aw.qmc
        tm = getattr(aw, 'tilauscope_main', None)
        try:
            if tm is not None and bool(getattr(tm, 'is_roasting', False)):
                old = qmc.autosaveflag  # stop first, writing nothing
                try:
                    qmc.autosaveflag = 0
                    tm.toggle_start_stop(False)
                finally:
                    qmc.autosaveflag = old
            # mark clean so reset() won't pop a desktop "save changes?" prompt —
            # the discard was already confirmed on the phone
            qmc.fileClean()
            qmc.reset()
            self._broadcast_event({'kind': 'recorder', 'state': 'stopped', 'saved': False})
            return {'status': 'ok'}
        except Exception:  # noqa: BLE001
            _log.exception("remote discard failed")
            return {'status': 'rejected', 'reason': 'BAD_MESSAGE'}

    def _broadcast_event(self, payload: dict) -> None:
        host = getattr(self._aw, 'tilau_web_host', None)
        if host is not None:
            try:
                host.publish_event(payload)  # thread-safe fan-out
            except Exception:  # noqa: BLE001
                pass

    # ---- takeover confirmation (controller lock, §7) ------------------------

    def _confirm_takeover(self, requester_name: str) -> bool:
        parent = getattr(self._aw, 'tilauscope_main', None) or self._aw
        try:
            dlg = _ControlRequestDialog(requester_name, parent)
            return dlg.exec() == QDialog.DialogCode.Accepted
        except Exception:  # noqa: BLE001
            _log.exception("takeover dialog failed")
            return False  # fail safe -> deny


def with_suppress(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        pass


class _ControlRequestDialog(QDialog):
    """Centered Catppuccin modal: a second phone asks to take over piloting.

    Explicit operator decision (protocol §7 — never a silent takeover); auto-denies
    on the countdown so an unattended desktop keeps the current controller.
    """

    def __init__(self, requester_name: str, parent=None) -> None:
        super().__init__(parent)
        self._left = _TAKEOVER_TTL
        # StaysOnTop + raise/activate on show: a frameless translucent dialog can
        # otherwise render BEHIND the (also frameless) TilauScope window on macOS.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        card = QFrame()
        card.setObjectName("CtrlReq")
        card.setStyleSheet(
            f"#CtrlReq {{ background-color:{_BG}; border:2px solid {_YELLOW};"
            f" border-radius:15px; }}"
            f"QLabel {{ color:{_TEXT}; background:transparent; border:none; }}")
        root.addWidget(card)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(24, 20, 24, 20)
        inner.setSpacing(12)

        title = QLabel(QApplication.translate("tilauscope_beancave", "📱 CONTROL REQUEST"))
        title.setStyleSheet(f"color:{_YELLOW};font-size:14px;font-weight:800;letter-spacing:1px;")
        inner.addWidget(title)

        body = QLabel(QApplication.translate("tilauscope_beancave",
                      "“{name}” wants to take over piloting.\n"
                      "The current controller will be switched to observer.").format(name=requester_name))
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{_TEXT};font-size:13px;")
        inner.addWidget(body)

        self._count = QLabel()
        self._count.setStyleSheet(f"color:{_SUB};font-family:'JetBrains Mono';font-size:11px;")
        inner.addWidget(self._count)

        btns = QHBoxLayout()
        deny = QPushButton(QApplication.translate("tilauscope_beancave", "Deny"))
        deny.clicked.connect(self.reject)
        deny.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{_SUB}; border:1px solid {_OVERLAY};"
            f" border-radius:8px; padding:8px 16px; }}"
            f"QPushButton:hover {{ color:{_TEXT}; border-color:{_SUB}; }}")
        allow = QPushButton(QApplication.translate("tilauscope_beancave", "Allow"))
        allow.clicked.connect(self.accept)
        allow.setStyleSheet(
            f"QPushButton {{ background:{_GREEN}; color:{_BG}; border:none;"
            f" border-radius:8px; padding:8px 18px; font-weight:700; }}"
            f"QPushButton:hover {{ background:#B9F0B0; }}")
        btns.addStretch(); btns.addWidget(deny); btns.addWidget(allow)
        inner.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._update_count()
        # force to front once the nested exec() loop is running (macOS z-order)
        QTimer.singleShot(0, self._to_front)

    def _to_front(self) -> None:
        self.raise_()
        self.activateWindow()

    def showEvent(self, e) -> None:  # noqa: N802 (Qt override)
        super().showEvent(e)
        self.raise_()
        self.activateWindow()

    def _tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.reject()  # auto-deny
            return
        self._update_count()

    def _update_count(self) -> None:
        self._count.setText(QApplication.translate("tilauscope_beancave",
                            "Auto-denies in {n}s").format(n=self._left))

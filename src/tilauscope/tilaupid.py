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
# TiLau 2025

import logging
import math
import time
import types
from collections.abc import Mapping
from typing import Final,TYPE_CHECKING
from collections import deque

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

from PyQt6.QtCore import QMetaObject, QSettings, Qt, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from artisanlib.util import fromFtoCstrict, fromCtoFstrict
from tilaucore.preheat import AmbientConditions, AmbientCorrector, PIDConfig, PreheatLaw, SlowHoldIntegrator  # noqa: F401
from tilaucore.preheat_controller import PreheatController
from tilauscope.tilaupid_adaptative import AdaptivePIDMixin
from tilauscope.tilaupid_safety import SensorSafetyLimits
from tilauscope.probe_visibility import et_available_for

_logd: Final[logging.Logger] = logging.getLogger("tilau")


# depending on tilauscope settings selecting the roaster, it will adjust accordingly, if using Airwave % of fan is added
# Roaster                   zone_fuzzy_start    coast_lookahead_sec fan_brake_power
# Gas drum, moderate mass   0.84                8                   25-35%
# Gas drum, heavy cast iron 0.80                12                  35-45%
# Electric drum             0.86-0.88           6                   15-25%
# Fluid bed                 0.88                4                   10-20%
# for testing purpose the setting is fixed for SW on electric drum


class TilauPreheatPID(AdaptivePIDMixin, PreheatController):
    # ── Learning-maturity badge constants (annotation + TilauScope window) ──
    # Marker → glyph/colour for the two capability lines (holding power, braking
    # anticipation); level → segment fill/colour/label key for the EXPERIENCE band.
    _BADGE_MARKER_GLYPH: Final[dict[str, str]] = {"check": "✓", "approx": "≈", "learning": "~"}
    _BADGE_MARKER_COLOR: Final[dict[str, str]] = {"check": "#A6E3A1", "approx": "#89B4FA", "learning": "#F9E2AF"}
    _BADGE_LEVEL_FILL: Final[dict[str, int]] = {"Learning": 1, "Estimated": 2, "Tuned": 3, "Calibrated": 4}
    _BADGE_LEVEL_COLOR: Final[dict[str, str]] = {
        "Learning": "#F9E2AF", "Estimated": "#89B4FA", "Tuned": "#89B4FA", "Calibrated": "#A6E3A1",
    }
    _BADGE_LEVEL_LABEL_KEY: Final[dict[str, str]] = {
        "Learning": "LevelLearning", "Estimated": "LevelEstimated",
        "Tuned": "LevelTuned", "Calibrated": "LevelCalibrated",
    }
    _BADGE_HOLD_TEXT_KEY: Final[dict[str, str]] = {
        "check": "CapHold_check", "approx": "CapHold_approx", "learning": "CapHold_learning",
    }
    _BADGE_LEAD_TEXT_KEY: Final[dict[str, str]] = {
        "check": "CapLead_check", "approx": "CapLead_approx", "learning": "CapLead_learning",
    }

    def __init__(self, aw: 'ApplicationWindow', config: dict | None= None):
        self.aw = aw

        # ── Temperature unit helpers ──────────────────────────────────────────
        # All internal PID maths are in °C; _to_c()/_to_native() convert at the boundary.
        # Each helper reads self.aw.qmc.mode live, so a unit change at runtime is handled transparently.

        def _to_c(self, val: float) -> float:
            """Convert a value from the current Artisan unit to °C."""
            return fromFtoCstrict(val) if self.aw.qmc.mode == 'F' else val

        def _to_native(self, val_c: float) -> float:
            """Convert a °C value to the current Artisan unit for display."""
            return fromCtoFstrict(val_c) if self.aw.qmc.mode == 'F' else val_c

        def _unit(self) -> str:
            return self.aw.qmc.mode   # 'C' or 'F' for log strings

        # Bind helpers as instance methods
        self._to_c       = types.MethodType(_to_c,       self)
        self._to_native  = types.MethodType(_to_native,  self)
        self._unit       = types.MethodType(_unit,        self)

        c = config or {}
        tg = c.get("targets", {"target_sv": 200})
        if not isinstance(tg, Mapping):
            raise ValueError("PID config section 'targets' must be a mapping")

        # target_sv from config is expected in the current Artisan unit; store internally in °C
        _raw_sv = tg.get("target_sv", self.aw.pidcontrol.sv)
        self.cfg = PIDConfig.from_mapping(c, target_sv=self._to_c(_raw_sv))
        # Initialisation dynamique du RoR basée sur Artisan

        # Every window below is a DURATION in seconds; the number of samples that
        # spans it depends on the operator-settable sampling interval, so it is
        # derived in _apply_sampling_cadence() at the end of __init__ and again at
        # each start(). The declarations here only fix the attribute types.
        self._init_controller_state()
        self._safety_watchdog = QTimer()
        self._safety_watchdog.timeout.connect(self._watchdog_tick)
        # Bind every cadence-dependent window to the real sampling interval.
        self._apply_sampling_cadence()

        #le fallback sur cfg fonctionne donc correctement au premier appel. Mais le threshold calculé à l'init n'intègre pas encore les corrections adaptatives. Ce n'est pas un bug — il sera recalculé au prochain start()
        # Variables pré-calculées
        self._precompute_targets()
        _logd.debug(
            f"Control law ready | display_win={self.ror_span_sec}s ctrl_win={self.cfg.ror_short_sec}s "
            f"SV={self._to_native(self.cfg.target_sv):.1f}°{self._unit()} "
            f"Kp={self.cfg.kp}%/°C Ki_hold={self.cfg.hold_ki_pct_per_c_sec}%/(°C·s) "
            f"fan={'ON' if self.cfg.fan_enabled else 'OFF'}"
        )

        # ── Adaptive learning init ────────────────────────────────────────────
        # alog_dir : répertoire des fichiers .alog Artisan.
        settings = QSettings()
        self.alog_directory = settings.value('alogDirectory', "", str)


        self._adaptive_init(
            alog_dir=self.alog_directory,
            window=c.get("adaptive_window", 10),
            # Read ceiling, distinct from the memory window: how deep the scanner
            # may go when usable preheats are scarce. None = derive from window.
            scan_budget=c.get("adaptive_scan_budget"),
            ambient=self.get_real_time_ambients(),
            aw=self.aw
        )

    # ── Get ambients if any temperature source ────────────────────────────────────

    @staticmethod
    def _map_ambient_source(src: int | None, qmc: object) -> float | None:
        """Résout un index de source ambiante Artisan vers sa valeur float courante.

        Définie comme méthode statique (pas de closure) pour éviter toute
        réallocation à chaque cycle de torréfaction.
        """
        if src is None or src == 0:
            return None
        if src == 1:
            return qmc.on_temp1[-1] if qmc.on_temp1 else None
        elif src == 2:
            return qmc.on_temp2[-1] if qmc.on_temp2 else None
        elif src > 2:
            # Extra-device channels from 3, as Artisan numbers them (canvas.py
            # ambient source): 3/4 = first device, 5/6 = second, …
            # Extra channels : après un run simulateur, RTextratemp1/2[idx] peut
            # être un float scalaire (dernière valeur RT) plutôt qu'une liste.
            # On vérifie explicitement le type avant tout accès par index.
            idx = ((src - 1) // 2) - 1
            try:
                if src % 2 == 1:  # impair → extratemp1
                    series = qmc.on_extratemp1
                    rt     = qmc.RTextratemp1
                else:             # pair → extratemp2
                    series = qmc.on_extratemp2
                    rt     = qmc.RTextratemp2
                if (len(series) > idx
                        and qmc.flagstart
                        and isinstance(series[idx], (list, deque))
                        and len(series[idx]) > 0):
                    return float(series[idx][-1])
                if qmc.flagon:
                    if isinstance(rt, (list, deque)) and len(rt) > idx:
                        return float(rt[idx])  # RT array is a list of float, not a list of list
            except (IndexError, TypeError, AttributeError):
                pass
        return None

    def get_real_time_ambients(self) -> AmbientConditions | None:
        qmc = self.aw.qmc  # résolution unique — évite 7 lookups chaînés self.aw.qmc
        t = qmc.ambientTempSource
        h = qmc.ambientHumiditySource
        p = qmc.ambientPressureSource
        if not (t or h or p):
            return None
        ms = self._map_ambient_source
        # AmbientConditions is a °C frame; the mapped channels carry the DISPLAY unit.
        _t_raw = ms(t, qmc)
        if _t_raw is not None and qmc.mode == 'F':
            _t_raw = fromFtoCstrict(_t_raw)
        # A failed ambient probe reports -1, which the plausibility band accepts as
        # a real temperature: it would add ~6% burner to the hold for the whole
        # preheat and poison the corpus weighting axis. Reject it explicitly, and
        # do not let a truthiness test turn a genuine 0.0 into the default either.
        return AmbientConditions(
            temp_ambient=self._ambient_or(_t_raw, 20.0),
            humidity    =self._ambient_or(ms(h, qmc), 50.0),
            pressure    =self._ambient_or(ms(p, qmc), 1013.25),
        )

    @staticmethod
    def _ambient_or(value: float | None, default: float) -> float:
        """Ambient channel reading, or the default when absent or sentinel."""
        if value is None:
            return default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(v) or v == -1.0:
            return default
        return v

    # ── Sampling cadence: measured, never assumed ────────────────────────
    def _sampling_dt(self) -> float:
        """Live sampling interval in seconds, read from Artisan.

        qmc.delay is in milliseconds and operator-settable from 100 ms upward.
        Every window, timeout and watchdog below is a duration, so all of them
        must follow it instead of a hard-coded 1 Hz assumption.
        """
        try:
            dt = float(getattr(self.aw.qmc, "delay", 1000.0)) / 1000.0
        except (TypeError, ValueError):
            return 1.0
        if not math.isfinite(dt) or dt <= 0.0:
            return 1.0
        return min(30.0, max(0.1, dt))

    def _apply_sampling_cadence(self) -> None:
        """Re-derive every cadence-dependent window from the live interval.

        Called at construction and at each start(): the operator can change the
        sampling rate between two preheats.
        """
        self.cfg.polling_dt = self._sampling_dt()
        dt = self.cfg.polling_dt
        self.ror_span_sec = getattr(self.aw.qmc, "deltaBTspan", 15.0)
        self.window_size = max(2, round(self.ror_span_sec / dt))
        self.short_window_size = max(2, round(self.cfg.ror_short_sec / dt))
        self.temp_history = deque(maxlen=self.window_size)
        self.time_history = deque(maxlen=self.window_size)
        self.temp_history_short = deque(maxlen=self.short_window_size)
        self.time_history_short = deque(maxlen=self.short_window_size)
        self._sensor_guard.limits = SensorSafetyLimits(
            stale_after_sec=max(3.5, dt * 3.5),
            min_ror_dt_sec=max(1.0, dt),
        )
        self._safety_watchdog.setInterval(max(250, int(dt * 500)))
        self._hold_integrator.max_dt_sec = max(2.5, dt * 2.5)
        detector = getattr(self, "_stabilisation_detector", None)
        if detector is not None:
            detector.polling_dt = dt

    def _control_clock(self) -> float:
        """Monotonic seconds on the same time base as the samples themselves.

        Accelerated profile replay advances the recorded profile faster than wall
        time. Dividing a replayed temperature delta by wall seconds returns N× the
        real slope, so the projection would brake N× too early and the simulated
        preheat would stall short of SV.
        """
        now = time.perf_counter()
        if getattr(self.aw, 'simulator', None) is None:
            return now
        try:
            speed = float(self.aw.qmc.timeclock.getBase()) / 1000.0
        except (AttributeError, TypeError, ValueError):
            return now
        return now * speed if speed > 0.0 else now

    def _stop_watchdog(self) -> None:
        """Stop the timer on the thread that owns it.

        cycle() — hence stop() and _trip_fault() — runs on Artisan's sampling
        thread, while the timer lives on the GUI thread. A direct stop() there is
        refused by Qt and leaves the timer armed for the life of the manager.
        """
        timer = self._safety_watchdog
        try:
            if timer.thread() is QThread.currentThread():
                timer.stop()
            else:
                QMetaObject.invokeMethod(timer, "stop", Qt.ConnectionType.QueuedConnection)
        except (RuntimeError, TypeError):
            _logd.exception("TilauPID could not stop its safety watchdog")

    # ── Learning-maturity badge (EXPERIENCE band + capability lines) ───────
    # Built once per start(); the canvas annotation and the TilauScope window
    # only concatenate the cached HTML — no QSettings/corpus read on a redraw.

    # One block glyph per notch. A run of several widened the badge past the text
    # lines and stretched the whole annotation; a single glyph reads as a notch and
    # keeps the EXPERIENCE row narrower than the sentences below it.
    _BADGE_SEG_BLOCK: Final[str] = "&#9608;"

    @classmethod
    def _badge_segments_html(cls, fill_n: int, color: str) -> str:
        """4 segments drawn with block glyphs. Table cells with a px width/height and a
        background colour are NOT honoured by Qt's rich-text subset — the cell collapses
        to its glyph and the bar renders as a row of dots. Glyph runs always render."""
        seg = cls._BADGE_SEG_BLOCK
        gap = "&nbsp;"
        filled = gap.join(seg for _ in range(fill_n))
        empty = gap.join(seg for _ in range(4 - fill_n))
        parts = []
        if filled:
            parts.append(f'<span style="color:{color};">{filled}</span>')
        if empty:
            parts.append(f'<span style="color:#45475A;">{gap if filled else ""}{empty}</span>')
        return f'<span style="font-size:13px;">{"".join(parts)}</span>'

    @classmethod
    def _badge_capability_line(cls, marker: str, text: str) -> str:
        if not text:   # missing label set: a bare marker glyph says nothing
            return ""
        glyph = cls._BADGE_MARKER_GLYPH[marker]
        color = cls._BADGE_MARKER_COLOR[marker]
        return (
            f'<span style="color:{color};font-weight:bold;font-size:12px;">{glyph}</span>'
            f'<span style="color:#CDD6F4;font-size:11px;"> {text}</span>'
        )

    def _build_learning_badge_html(self, L: dict) -> str:
        """EXPERIENCE band (segments + level/counter [+ sub-line]) and the two
        capability lines, as one cached HTML fragment for the canvas annotation."""
        b = self.learning_badge
        if not b:
            return ""
        level = b["level"]
        level_color = self._BADGE_LEVEL_COLOR[level]
        fill_n = 0 if b["is_sim"] else self._BADGE_LEVEL_FILL[level]
        segments = self._badge_segments_html(fill_n, level_color)

        sub_line = ""
        # A simulated preheat learns nothing, so the level colour would be a lie:
        # the caution yellow marks it as evidence that will not be kept.
        text_color = level_color
        if b["is_sim"]:
            level_text = L.get("SimNotRecorded", "Simulation — not recorded")
            text_color = self._BADGE_LEVEL_COLOR["Learning"]
        else:
            level_word = L.get(self._BADGE_LEVEL_LABEL_KEY[level], level)
            if level in ("Calibrated", "Tuned"):
                counter = L.get("CounterPreheats", "{n} preheats").format(n=b["n_updates"])
                level_text = f"{level_word} &middot; {counter}"
            elif level == "Estimated":
                # An edge-blend node, or a seed carried by the braking knob alone, can
                # reach this level with no calibrated hold to count. Announcing
                # "0 roasts" would contradict the level: the sub-line says it instead.
                level_text = level_word
                if b["n_roasts"] > 0:
                    counter = L.get("CounterRoasts", "{n} roasts").format(n=b["n_roasts"])
                    level_text = f"{level_word} &middot; {counter}"
                sub_line = L.get("EstimatedSub", "Adjusted from nearby setpoints")
            else:  # Learning: no evidence to count yet
                level_text = level_word
                sub_line = L.get("FirstPreheatSub", "First preheat at this setpoint")

        sub_line_html = (
            f'<div><span style="color:#6C7086;font-size:10px;">{sub_line}</span></div>'
            if sub_line else ""
        )
        cap_hold = self._badge_capability_line(
            b["hold_marker"], L.get(self._BADGE_HOLD_TEXT_KEY[b["hold_marker"]], ""))
        cap_lead = self._badge_capability_line(
            b["lead_marker"], L.get(self._BADGE_LEAD_TEXT_KEY[b["lead_marker"]], ""))

        # Segments and level word share one line: a two-column table would collapse
        # (Qt honours neither `width:100%` nor a px cell width in rich text).
        return f"""
                    <div style="margin-top:5px;"><span style="color:#6C7086;font-size:10px;">{L.get('Experience', 'EXPERIENCE')}</span></div>
                    <div>{segments}<span style="color:{text_color};font-weight:bold;font-size:11px;"> &nbsp;{level_text}</span></div>
                    {sub_line_html}
                    <div style="margin-top:4px;">{cap_hold}</div>
                    <div>{cap_lead}</div>
                    """

    def _build_learning_badge_compact_html(self, L: dict) -> str:
        """TilauScope window mirror: segments + the level word only — no counter,
        no room (see get_pid_status in displayscope.py)."""
        b = self.learning_badge
        if not b:
            return ""
        level = b["level"]
        level_color = self._BADGE_LEVEL_COLOR[level]
        fill_n = 0 if b["is_sim"] else self._BADGE_LEVEL_FILL[level]
        segments = self._badge_segments_html(fill_n, level_color)
        level_word = (L.get("SimNotRecorded", "Simulation — not recorded") if b["is_sim"]
                      else L.get(self._BADGE_LEVEL_LABEL_KEY[level], level))
        # Same rule as the canvas badge: a simulated run never wears a level colour.
        text_color = self._BADGE_LEVEL_COLOR["Learning"] if b["is_sim"] else level_color
        return (
            f'{segments}'
            f'<span style="color:{text_color};font-weight:bold;font-size:11px;"> &nbsp;{level_word}</span>'
        )

    # ── The shared controller's hooks (tilaucore.preheat_controller), from Artisan ──
    def _guard_clock(self) -> float:
        return time.perf_counter()

    def _display_ror_span(self) -> float:
        return getattr(self.aw.qmc, "deltaBTspan", 15.0)

    def _command_output(self, slider_nr: int, power: int) -> None:
        self._update_artisan_slider(slider_nr, power)

    def _record_event(self, value: float, text: str) -> None:
        # eventRecordActionSignal est en QueuedConnection — safe depuis le sémaphore ET hors sémaphore
        # signature : pyqtSignal(int, float, str, bool) → EventRecordActionSlot(eventtype, eventvalue, description, doupdategraphics)
        self.aw.qmc.eventRecordActionSignal.emit(4, value, text, False)

    def _record_start_marker(self, sv_native: float) -> None:
        # Emit the deferred "Preheat started" marker now that a real sample has
        # landed (cycle() is driven by the sampling loop ⇒ qmc.timex is non-empty here),
        # so EventRecordAction actually persists it. Queued signal = thread-safe, no
        # semaphore deadlock. SV encoded to Artisan's internal event value for a clean
        # round-trip on read (see events_external/internal_to_value).
        sv_internal = self.aw.qmc.eventsExternal2InternalValue(round(sv_native))
        self.aw.qmc.eventRecordActionSignal.emit(4, sv_internal, "TilauPID Preheat started", False)

    def _notify_fault(self, reason: str) -> None:
        if reason.startswith("control_exception"):
            message = QApplication.translate(
                "Message", "Preheat stopped because its controller encountered an error.")
        elif reason == "sensor_timeout":
            message = QApplication.translate(
                "Message", "Preheat stopped: no valid temperature reading was received.")
        else:
            message = QApplication.translate(
                "Message", "Preheat stopped: the temperature reading is invalid.")
        self.aw.sendmessageSignal.emit(message, True, None)

    def _before_start(self) -> None:
        # Without an ET probe the only input is BT, whatever Artisan's settings,
        # a loaded profile or a pidSource() command last set.
        if not et_available_for(self.aw):
            self.aw.pidcontrol.pidSource = 1

    def _announce_target(self, sv: float) -> None:
        self.aw.pidcontrol.setSV(int(sv))  # Artisan SV stays in native unit

    def _mark_preheat(self) -> None:
        # getProfile writes qmc.tilau_preheat_sv_c into the alog.
        self.aw.qmc.tilau_preheat_sv_c = float(self.cfg.target_sv)

    def _start_watchdog(self) -> None:
        # Profile replay has its own clock and may run faster than wall
        # time. The physical-sensor watchdog is therefore meaningful only on a
        # real input; malformed simulator values are still checked in cycle().
        if self.aw.simulator is None:
            self._safety_watchdog.start()
        else:
            self._safety_watchdog.stop()

    def _schedule_learning(self) -> None:
        # CHARGE calls us with qmc.profileDataSemaphore held: learning ends in two
        # full QSettings flushes, which would stall the sampling thread at the most
        # timing-critical moment. Nothing it reads is protected by that semaphore
        # (session state is PID-owned), so defer it one event-loop turn.
        QTimer.singleShot(0, self._deferred_preheat_complete)

    def _after_safe_zero(self) -> None:
        self._zero_behind_queued_commands()

    def _render_learning_badge(self) -> None:
        try:
            L = self.aw.qmc._tilau_labels
        except Exception:  # noqa: BLE001 - a missing label set must not block the annotation
            L = {}
        self.learning_badge_html = self._build_learning_badge_html(L)
        self.learning_badge_compact_html = self._build_learning_badge_compact_html(L)

    def _clear_preheat_sv_marker(self) -> None:
        """Drop the `tilau_preheat_sv_c` stamp from qmc.

        The key survives until the next reset(), so an aborted preheat finished by
        hand on the slider would still be saved as a guided one and mined as PID
        evidence — undoing, through the corpus, the learning ban set here.
        """
        try:
            self.aw.qmc.tilau_preheat_sv_c = None
        except AttributeError:
            pass

    def _zero_behind_queued_commands(self) -> None:
        """Send the zero again behind any command a cycle already queued to the GUI thread.

        From the GUI thread the safe zero is applied at once, ahead of those
        commands; from the sampling thread it is queued after them already.
        """
        app = QApplication.instance()
        if app is not None and app.thread() is QThread.currentThread():
            QTimer.singleShot(0, self._resend_safe_zero)

    def _resend_safe_zero(self) -> None:
        if self.active:   # a preheat started since owns the burner
            return
        try:
            self._update_artisan_slider(self.cfg.heater_slider, 0)
        except Exception:  # noqa: BLE001 - an exception escaping a timer callback closes the app
            _logd.exception("TilauPID could not resend its safe zero")

    def _update_artisan_slider(self, slider_nr: int, power: int) -> None:
        """
        Déplace le slider Artisan et enregistre l'événement.

        En mode simulateur :
          - moveslider() met à jour l'UI normalement.
          - EventRecordAction avec takeLock=True peut deadlocker si la sémaphore
            est tenue par sample_processing().  On utilise donc le signal queued
            (eventRecordActionSignal) dans tous les cas, et on saute fireslideraction
            qui enverrait une commande matérielle inexistante.
        """
        signal = getattr(self.aw, "tilaupidSliderCommandSignal", None)
        if signal is not None:
            # ApplicationWindow owns the signal and its receiving slot. Qt therefore
            # queues this complete UI/hardware transaction when cycle() runs in the
            # sampling worker, preserving command order without touching widgets here.
            signal.emit(slider_nr, power, getattr(self.aw, 'simulator', None) is None)
            return

        # Lightweight non-Qt harness compatibility. Production ApplicationWindow
        # always provides tilaupidSliderCommandSignal.
        self.aw.moveslider(slider_nr, power)
        self.aw.extraeventsactionslastvalue[slider_nr] = power
        ev_value = self.aw.qmc.eventsExternal2InternalValue(power)
        self.aw.qmc.eventRecordActionSignal.emit(slider_nr, ev_value, f"S{slider_nr}:{power}%", False)
        if getattr(self.aw, 'simulator', None) is None:
            self.aw.fireslideraction(slider_nr)


    def processcommand(self, cmd: str, value: str | None = None):
        if not cmd:
            return

        # Nettoyage et normalisation de la commande
        match cmd.upper().strip():
            case "START":
                # Conversion sécurisée de la valeur si présente
                try:
                    val = float(value) if value and value.strip() else None
                    self.start(val)  # val is in native unit; start() converts to °C
                except ValueError:
                    _logd.error(f"Valeur SV invalide pour START: {value}")
                    self.start() # Start avec la valeur par défaut

            case "STOP":
                self.stop()

            case "SV":
                if value:
                    try:
                        sv_native = float(value)
                        self.cfg.target_sv = self._to_c(sv_native)  # store in °C internally
                        self._precompute_targets() # Crucial pour la réactivité du PID
                        # A bias accumulated for one setpoint is invalid at another.
                        self._hold_integrator.reset()
                        # Resolve the continuous learned law immediately; keeping
                        # the previous SV's P_ss/lead until the next START would defeat the
                        # interpolation precisely when the operator adjusts the setpoint.
                        self.p_ss, self.lead_sec = self.load_law_params()
                        # Only a live preheat owns the marker: re-stamping it while
                        # stopped or faulted would re-declare a hand-driven session
                        # as guided in the saved profile.
                        if self.active:
                            self.aw.qmc.tilau_preheat_sv_c = float(self.cfg.target_sv)
                        # set artisan pid target in native unit
                        self.aw.pidcontrol.setSV(sv_native)
                        _logd.debug(f"SV mis à jour via Displayscope : {sv_native:.1f}°{self._unit()} ({self.cfg.target_sv:.1f}°C interne)")
                    except ValueError:
                        _logd.error(f"Valeur SV invalide : {value}")

            case "FAN":
                # Runtime toggle: FAN ON / FAN OFF
                if value and value.upper().strip() == "ON":
                    self.cfg.fan_enabled = True
                    _logd.debug("Fan-assist braking enabled.")
                elif value and value.upper().strip() == "OFF":
                    self.cfg.fan_enabled = False
                    if self.prev_fan != 0:
                        self._update_artisan_slider(self.cfg.fan_slider, 0)
                        self.prev_fan = 0
                    _logd.debug("Fan-assist braking disabled, damper closed.")

            case _:
                _logd.warning(f"Commande Displayscope inconnue : {cmd}")

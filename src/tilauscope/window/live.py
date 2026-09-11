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

"""The sampling path, and everything it repaints.

Artisan emits a reading roughly once a second; this is the slot that receives
it and the surfaces it drives — the readouts, the status line, the automation
banner, the timer's own appearance, and the warnings that take over the phase
box when the machine goes quiet.

Nothing here may become expensive. It runs on the same event loop as the
sampling itself, so file access, widget construction and re-translation all
belong somewhere else.
"""

from __future__ import annotations

import logging
from typing import Final
import time

from PyQt6.QtCore import QRect, QTimer, pyqtSlot
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect
from tilauscope.tilauscope_types import THEME
from tilauscope.window.layout import _TIMER_FONT_PX
from tilauscope.window.parts import ButtonManager, EventPanel, ExtraCountersPanel


_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

# Consecutive samples with no usable probe reading before the panel says the
# machine has gone silent. At 1 Hz that is ~5 s: long enough to ride out the
# misses a device produces on startup, short enough that the operator is not
# left reading an empty counter and guessing.
_NO_READING_SAMPLES: Final[int] = 5


class LiveMixin:
    """What the once-a-second reading from Artisan reaches.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    def _update_timer_style(self, state: str) -> None:
        """
        Update the timer look for idle, preheat, roasting, paused or emergency.
        """
        self._timer_state = state

        # Ensure the opacity effect attribute exists
        if not hasattr(self, "timer_opacity"):
            self.timer_opacity = None

        if state in ("preheat", "roasting", "engaged"):
            # An active session is always readable: light colour, no blinking.
            # "engaged" is retained for monitoring-only compatibility.
            if self.timer_lbl.graphicsEffect() is not None:
                self.timer_lbl.setGraphicsEffect(None)
            self.timer_opacity = None
            self.timer_lbl.setStyleSheet(
                f"font-size: {_TIMER_FONT_PX}px; font-weight: 900; color: {THEME['TEXT']}; " # Lighter gray/white
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )

        elif state == "emergency":
            # HEAT CUT: critical red, steady. Not blinking — the operator has a
            # drum to empty, not a light show to read.
            if self.timer_lbl.graphicsEffect() is not None:
                self.timer_lbl.setGraphicsEffect(None)
            self.timer_opacity = None
            self.timer_lbl.setStyleSheet(
                f"font-size: {_TIMER_FONT_PX}px; font-weight: 900; color: {THEME['CRITICAL']}; "
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )

        elif state == "paused":
            # PAUSED (Simulation): Orange color, Blinking enabled
            if self.timer_opacity is None:
                self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
            self.timer_lbl.setGraphicsEffect(self.timer_opacity)
            self.timer_lbl.setStyleSheet(
                f"font-size: {_TIMER_FONT_PX}px; font-weight: 900; color: #FAB387; " # Orange
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )

        else: # "idle"
            # IDLE: Dark gray, slow pulse
            if self.timer_opacity is None:
                self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
            self.timer_lbl.setGraphicsEffect(self.timer_opacity)
            self.timer_lbl.setStyleSheet(
                f"font-size: {_TIMER_FONT_PX}px; font-weight: 900; color: {THEME['BORDER']}; " # Dark gray
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )

    def _sync_simulator_timer_style(self) -> None:
        """Make the timer reflect the complete current simulator state.

        Auto-CHARGE can update ``timeindex`` without taking the same UI path as
        the local CHARGE button.  Synchronising only pause/resume left the timer
        permanently in its dark pre-charge style even though the roast clock
        was already running.
        """
        if not self._is_simulator:
            return

        qmc = self.aw.qmc
        paused = bool(qmc.flagon and qmc.flagstart and not self.aw.sample_loop_running)
        current_state = getattr(self, "_timer_state", "idle")
        if current_state == "emergency":
            return
        if paused:
            if current_state != "paused":
                self._update_timer_style("paused")
            self.p_timer.setInterval(300)
        else:
            # Before CHARGE the recording is preheating; after CHARGE the
            # regular steady roasting style is authoritative. Both are light
            # and fixed. Do
            # this on every state mismatch, not only when resuming a pause:
            # simulator auto-CHARGE may transition directly idle → roasting.
            expected = "roasting" if qmc.timeindex[0] > -1 else "preheat"
            if current_state != expected:
                self._update_timer_style(expected)
            self.p_timer.setInterval(600)

    def pulse(self):
        """
        Handles the blinking/pulsing animation.
        Called by p_timer (e.g., every 600ms).
        """
        self._follow_idle_changes()
        state = getattr(self, "_timer_state", "idle")

        # 1. Every active non-paused state is steady: ensure no stale opacity
        # effect survives a transition and stop before the pulse logic.
        if state in ("preheat", "roasting", "engaged", "emergency"):
            if self.timer_lbl.graphicsEffect() is not None:
                self.timer_lbl.setGraphicsEffect(None)
            return

        # 2. Manage the opacity for "paused" (blink) or "idle" (slow pulse)
        if self.timer_opacity is not None:
            if state == "paused":
                # Hard toggle for blinking
                new_opacity = 0.0 if self.timer_opacity.opacity() > 0.5 else 1.0
                self.timer_opacity.setOpacity(new_opacity)
            else: # "idle"
                # Soft pulse logic
                current = self.timer_opacity.opacity()
                # Toggle between 0.3 and 1.0 for idle visibility
                self.timer_opacity.setOpacity(1.0 if current < 1.0 else 0.4)

    def _follow_idle_changes(self) -> None:
        """Keep the curve current when no sample is arriving to do it.

        Opening a roast from a file changes everything the curve draws and sends
        no sample at all: the window used to keep showing the previous roast
        until something else — switching windows, usually — happened to repaint
        it. Only while nothing is sampling, and only on an actual change, so a
        screen sitting still is not repainted twice a second.
        """
        if self.curve is None:
            return
        try:
            qmc = self.aw.qmc
            if qmc.flagon:
                return          # samples are driving it
            signature = (len(qmc.timex), tuple(qmc.timeindex), self.aw.curFile)
        except (AttributeError, TypeError):
            return
        if signature == getattr(self, "_idle_signature", None):
            return
        self._idle_signature = signature
        self.curve.tick()

    def _show_cooled_face(self) -> None:
        """Paint the "cooled" state of the phase box. Split from handle_cool_end
        so a COOL END marked in Artisan can show it without emitting the mark back."""
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate(
            "tilauscope_window",
            "✅ ROASTER IS NOW COOLED\nSafe to switch off."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()
        self.phase_container.setStyleSheet(
            "background: #0F0F12; border-radius: 15px; border: 1px solid #A6E3A166;")

    # ──────────────────────────────────────────────────────────────
    def _update_automation_banner(self) -> None:
        """Surface, in the status zone, any Artisan automation that drives the
        roast: PID active (from CHARGE) and the background playback modes.

        Called once per second from the TIMER path (data==10). Cheap: builds a
        short token list and only touches the widget when the set changes.
        """
        qmc = self.aw.qmc
        tokens: list[str] = []

        # Artisan PID piloting the heat — only meaningful once CHARGE is marked
        if self.is_pid_active and qmc.timeindex and qmc.timeindex[0] > -1:
            tokens.append(self.str_automation_pid)

        # Background playback modes — same flags as check_playback_before_start()
        # so the START warning and this in-roast banner stay consistent.
        if qmc.backgroundPlaybackEvents:
            tokens.append(self.str_automation_replay_events)
        if qmc.backgroundPlaybackDROP:
            tokens.append(self.str_automation_auto_drop)
        if qmc.backgroundReproduce:
            tokens.append(self.str_automation_playback_aid)

        key = tuple(tokens)
        if key == self._automation_prev:
            return
        self._automation_prev = key

        if not tokens:
            self.automation_lbl.hide()
            return
        self.automation_lbl.setText(f"{self.str_automation_prefix} — {' · '.join(tokens)}")
        self.automation_lbl.show()

    def _hide_automation_banner(self) -> None:
        """Hide the automation banner and reset its cache (roast end / OFF)."""
        self._automation_prev = None
        self.automation_lbl.hide()

    def _track_probe_silence(self, valid_reading: bool) -> None:
        """Count consecutive samples carrying no usable probe reading.

        Runs once per sample: an integer compare, and a repaint at the two
        transitions only. A device can be configured, opened and still return
        nothing (cable out), and the panel would otherwise keep announcing a
        preheat it cannot measure.
        """
        if valid_reading:
            self._clear_no_reading_face()
            return
        if self._no_reading_samples >= _NO_READING_SAMPLES:
            return
        self._no_reading_samples += 1
        if self._no_reading_samples < _NO_READING_SAMPLES:
            return
        # The drop is not the end of the need: the cooling is steered on the
        # falling temperature, and its automatic detection reads the same probe.
        if self._emergency_latched:
            return
        # A recording that has measured nothing has nothing to record, so it is
        # stopped and the banner says so. Past CHARGE the beans are in the drum:
        # stopping would not cool them, it would only throw the trace away.
        if self.is_roasting and not self._milestone_marked(0):
            QTimer.singleShot(0, self._stop_recording_no_reading)
        else:
            self._show_no_reading_face()

    def _show_no_reading_face(self, stopped: bool = False) -> None:
        """Say the machine has gone silent, where the preheat banner was.

        The preheat banner goes rather than sharing the box: it names a target
        and a maturity nothing can back without a reading, and the warning has
        to be the only thing in the operator's eye.
        """
        try:
            if not self._no_reading_shown:
                # Keep the box exactly as it stands rather than reasoning about
                # what it held: preheat, dropping, cooling and cooled all live
                # here, and a restore that enumerates them forgets one.
                self._saved_face = (
                    self.msg_lbl.text(), self.msg_lbl.styleSheet(),
                    not self.msg_lbl.isHidden(), self.phase_container.styleSheet(),
                    [not w.isHidden() for w in self._phase_widgets()],
                )
            self._no_reading_shown = True
            for widget in self._phase_widgets():
                widget.hide()
            text = f"{self.str_no_reading_title}\n{self.str_no_reading_body}"
            if stopped:
                text += f"\n{self.str_no_reading_stopped}"
            self.msg_lbl.setText(text)
            self.msg_lbl.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 15px; font-weight: 900;"
                " border: none;")
            self.msg_lbl.show()
            self.msg_lbl.raise_()
            self.phase_container.setStyleSheet(
                f"background: {THEME['CRUST']}; border-radius: 15px;"
                f" border: 2px solid {THEME['CRITICAL']};")
        except Exception:  # pylint: disable=broad-except
            _log.exception('no-reading: painting the banner failed')

    def _clear_no_reading_face(self) -> None:
        """Give the box back to whatever it was showing before the silence."""
        self._no_reading_samples = 0
        if not self._no_reading_shown:
            return
        self._no_reading_shown = False
        saved = getattr(self, '_saved_face', None)
        if saved is None:
            return
        self._saved_face = None
        try:
            text, style, shown, container_style, phase_shown = saved
            self.msg_lbl.setStyleSheet(style)
            self.msg_lbl.setText(text)
            self.msg_lbl.setVisible(shown)
            if shown:
                self.msg_lbl.raise_()
            self.phase_container.setStyleSheet(container_style)
            for widget, visible in zip(self._phase_widgets(), phase_shown):
                widget.setVisible(visible)
        except Exception:  # pylint: disable=broad-except
            _log.exception('no-reading: restoring the box failed')

    def update_extradevices_from_artisan(self):
        # if extradevicesdisplay strategy have been changed, we must rebuild ExtraCounterPanel to update the display
        _logd.debug("Updating extra devices display from Artisan changes...")
                # Initialize the managed buttons
        visible:bool = False
        if self.extra_panel is not None:
            # extracoutner panel
            visible = self.extra_panel.isVisible()
            self.extra_panel.hide()
            self.extra_panel.deleteLater() # Clear the old panel to avoid duplicates
            self.extra_panel = None
        self.extra_panel = ExtraCountersPanel(self.artisan_conf, self.theme, self)
        self.extra_panel.reset_counters() # Initialize counters
        self.align_extra_panel() # Align the panel based on current window geometry
        if visible:
            self.extra_panel.show()
        else:
            self.extra_panel.hide() # Caché

    def update_events_from_artisan(self):
        # if buttons have changed, we must rebuild event buttons to update the button bar
        _logd.debug("Updating events display from Artisan changes...")
        # 1. Capturer géométrie AVANT destruction
        old_geo: QRect | None = None
        visible = False
        if self.event_panel is not None:
            visible = self.event_panel.isVisible()
            old_geo = self.event_panel.geometry()   # ← snapshot avant deleteLater
            self.event_panel.hide()
            self.event_panel.deleteLater()
            self.event_panel = None
            self.btn_manager = None

        # 2. Rebuild
        self.btn_manager = ButtonManager.from_artisan_settings(
            self.artisan_conf, self.artisan_conf.mode
        )
        self.event_panel = EventPanel(self.btn_manager, self.theme, self)
        # Each EventPanel owns its signal: the connection made on the old
        # instance is not inherited by its replacement.
        self.event_panel.event_fired.connect(self.handle_event_fired)

        # 3. Fixer la largeur EN PREMIER (critique pour heightForWidth)
        self.event_panel.setFixedWidth(self.width())

        # 4. Recalculer la hauteur avec une largeur connue
        self.event_panel.update_panel_height()

        # 5. Restaurer position : ancienne géométrie > QSettings > fallback align_panels
        if old_geo is not None:
            # Réutiliser directement la position avant rebuild
            self.event_panel.move(old_geo.topLeft())
        else:
            # Première fois : fallback sur align_panels
            self.align_panels()

        # 6. Visibilité
        if visible:
            self.event_panel.show()
        else:
            self.event_panel.hide()

    @pyqtSlot(int, object, object, bool)
    def update_ui_from_artisan(self, data, value=None, raw=None, buttonState=True):
        """Signal slot for qmc.tilauUpdateSignal. Guarded so no exception can
        propagate back into Artisan's sample loop (updateLCDs)."""
        try:
            self._apply_artisan_update(data, value, raw, buttonState)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception('tilau update failed (data=%s): %s', data, e)

    def _apply_artisan_update(self, data, value=None, raw=None, buttonState=True):
        # buttonState is used to know if we need to update button style (on event trigger) or not (on event reset)
        """Update labels with live data from Artisan."""
        # data values
        # extra devices values are collected every cycle
        # roasting events
        # 0 = CHARGE
        # 1 = DRY END
        # 2 = FIRST CRACK START
        # 3 = END OF FC
        # 4 = SECOND CRACK START
        # 5 = SC END
        # 6 = DROP
        # 7 = COOLING
        # main values to mirror from Artisan
        # 12 = BT
        # 11 = ET
        # 13 = Delta BT
        # 10 = Timer
        qmc = self.aw.qmc  # Cache reference
        val_str = str(value) if value is not None else ""

        # 1. Extra Panel Update — throttled to ≤ 1 Hz. This slot fires on every
        # channel (BT/ET/RoR/TIMER…, ~4×/sample) and BT/ET/RoR keep firing while
        # only monitoring — where data==10 does NOT (updateLCDtime guards on
        # flagstart). So a time throttle, not a data==10 gate, caps the cost
        # without freezing the panel during monitoring. First call after the
        # panel is shown runs immediately (timestamp stays stale while hidden).
        # None is a real state, not a transient: the panel is dropped and
        # rebuilt whenever the extra devices change, and a rebuild that failed
        # would otherwise raise here on every single sample — the guard around
        # this slot would swallow it and the whole live display would stop.
        if self.extra_panel is not None and self.extra_panel.isVisible():
            _now = time.monotonic()
            if _now - self._last_extra_update >= 0.9:
                self._last_extra_update = _now
                self.extra_panel.update_values()

        # 2. Handle Events
        if data == 12:  # BT event
            # One tick per sample: BT fires under monitoring as well as under
            # recording, which the timer channel does not — and the preheat has
            # to be drawn before there is a roast to record.
            if self.curve is not None:
                self.curve.tick()
            if self.lcds.tg_lcd.lbl_value.text() != val_str:
                self.lcds.tg_lcd.lbl_value.setText(val_str)
            fv = raw if isinstance(raw, (int, float)) else None
            # -1 is Artisan's no-reading sentinel; updateLCDs normally sends
            # None for it, so this only guards an alternate producer.
            self._track_probe_silence(fv is not None and fv != -1)

            if fv is not None:
                self.lcds.tg_lcd.set_alert_value(fv)
                if self._minmax_open():
                    self.lcds.tg_lcd.update_minmax(fv)

                self.curr_bt = fv
                try:
                    p = qmc.phases
                    # phase_defs: (key, phase_index 0-based in self.phases, p start idx, p end idx)
                    # Phases passées → 100%, phase active → calcul, phases futures → 0%
                    phase_keys = self._PHASE_KEYS       # ordered (class constant)
                    phase_bounds = self._PHASE_BOUNDS   # indices dans qmc.phases
                    active_idx = phase_keys.index(self.current_phase) if self.current_phase in phase_keys else -1
                    for i, (key, (si, ei)) in enumerate(zip(phase_keys, phase_bounds)):
                        # past DROP there is no running phase: every block stays
                        # full instead of falling through to the "not reached" 0 %
                        if self._drop_done or i < active_idx:
                            self.phases[key].set_progress(100)
                        elif i == active_idx:
                            span = p[ei] - p[si]
                            prog = ((fv - p[si]) / span * 100) if span > 0 else 0
                            self.phases[key].set_progress(max(0, min(100, prog)))
                        else:
                            self.phases[key].set_progress(0)
                except (IndexError, ValueError):
                    pass

                # ── Détection automatique du refroidissement post-DROP ────────────
                # Seuil : chute BT > 10°C en moins de 30s après DROP
                if (self._drop_done
                        and not self._cooling_detected
                        and self._bt_at_drop is not None
                        and self._bt_drop_timestamp is not None):
                    try:
                        current_time = qmc.timex[-1] if qmc.timex else None
                        if current_time is not None:
                            elapsed = current_time - self._bt_drop_timestamp
                            if 0 < elapsed <= 30 and (self._bt_at_drop - fv) >= 10:
                                self.handle_cooling()
                    except (IndexError, TypeError):
                        pass

        elif data == 11:  # ET event
            if self.lcds.te_lcd.lbl_value.text() != val_str:
                self.lcds.te_lcd.lbl_value.setText(val_str)
            fv = raw if isinstance(raw, (int, float)) else None
            if fv is not None:
                self.lcds.te_lcd.set_alert_value(fv)
                if self._minmax_open():
                    self.lcds.te_lcd.update_minmax(fv)

        elif data == 13:  # DELTABT (RoR) event
            if self.lcds.ror_lcd.lbl_value.text() != val_str:
                self.lcds.ror_lcd.lbl_value.setText(val_str)
            # ``-1`` is Artisan's no-reading sentinel.  Keep this defensive
            # guard even though updateLCDs normally converts it to ``None`` so
            # alternate signal producers cannot turn it into a real RoR.
            fv = raw if isinstance(raw, (int, float)) and raw != -1 else None
            if fv is not None:
                self.lcds.ror_lcd.set_alert_value(fv)
                self.lcds.ror_lcd.set_ror_color(fv, qmc.mode)
                if self._minmax_open():
                    self.lcds.ror_lcd.update_minmax(fv)

        elif data == 10:  # TIMER event
            self.timer_lbl.setText(val_str)

            if not qmc.flagon or not self.is_roasting:
                return

            # Parse Artisan's own timer value (format "MM:SS") — the single source of truth.
            # This eliminates any drift between our wall-clock and Artisan's internal clock.
            try:
                parts = val_str.split(":")
                total_secs = int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                return

            # Frequency Capping (1Hz). Artisan's timer is not monotonic: it
            # restarts at 00:00 at DROP (cooling clock) and counts down when the
            # charge timer is armed. Only a repeated second is dropped, never a
            # lower one, or every consumer below stays frozen for the whole cooling.
            if total_secs == self.last_update_second:
                return
            self.last_update_second = total_secs

            # SV sync — checked once per second max (SV changes rarely)
            sv = int(self.aw.pidcontrol.sv if self.aw.pidcontrol.sv is not None else 0)
            if sv != int(self.aw.sliderSV.value()):
                # reflect the PID setpoint on Artisan's SV slider without
                # re-triggering Artisan's own slider action (programmatic mirror).
                self.aw.sliderSV.blockSignals(True)
                self.aw.sliderSV.setValue(sv)
                self.aw.sliderSV.blockSignals(False)

            # Update Phase Stats — phase_starts now stores Artisan timer seconds at phase start
            if self.current_phase and self.phase_starts.get(self.current_phase) is not None:
                elapsed = total_secs - self.phase_starts[self.current_phase]
                self.phases[self.current_phase].update_stats(elapsed, max(total_secs, 1))

                if self.current_phase in ("MAI", "DEV") and self.phase_starts.get("DRY") is not None and self.phase_starts.get("MAI") is not None:
                    dry_dur = self.phase_starts["MAI"] - self.phase_starts["DRY"]
                    self.phases["DRY"].update_stats(dry_dur, max(total_secs, 1))
                    if self.current_phase == "DEV" and self.phase_starts.get("DEV") is not None:
                        mai_dur = self.phase_starts["DEV"] - self.phase_starts["MAI"]
                        self.phases["MAI"].update_stats(mai_dur, max(total_secs, 1))

            # Fallback sync for pause/resume changes made from Artisan itself.
            # A click in this window is synchronized immediately in
            # timer_clicked(), because pausing stops this TIMER signal.
            self._sync_simulator_timer_style()

            # Build Status Text
            status_parts = []
            if qmc.flagstart:
                status_parts.append(self.str_roastsession.upper())

            if self._is_simulator:
                sim_text = self.str_simulator
                if not self.aw.sample_loop_running:
                    sim_text += f" {self.str_paused}"
                else:
                    speed = int(qmc.timeclock.getBase() / 1000)
                    if speed > 1: sim_text += f" x{speed}"
                status_parts.append(sim_text)

            # Auto-flags
            self.check_pid_status()
            self._update_automation_banner()   # red-on-amber automation notice
            ti = qmc.timeindex
            if ti:
                if ti[0] == -1:  # Pre-charge
                    # get_pid_status() ne dépend pas de BT — toujours calculé
                    # _is_pid_target_close() nécessite BT — optionnel
                    # The drum is there: the charge instruction takes the line the
                    # maturity badge was using. That badge has been on screen for
                    # the whole climb and says nothing about the next two seconds,
                    # which is all this box has room for.
                    ready = (self._is_pid_target_close(self.curr_bt)
                             if self.curr_bt is not None else False)
                    p_text = self.get_pid_status(with_badge=not ready)
                    if (getattr(self, "prev_pidtext", None) != p_text
                            and not self._no_reading_shown):
                        self.prev_pidtext = p_text
                        # separator must be <br>, not \n: msg_lbl is in AutoText
                        # mode and Qt's rich-text sniffing stops at the first newline, so
                        # a leading "\n" made it render the whole message as plain text —
                        # the <br>/<b> of the "ready to charge" line showed up literally.
                        self.msg_lbl.setText(f"{self.str_preheating}<br>{p_text}")
                    if qmc.autoChargeFlag: status_parts.append(self.str_autocharge)
                # Unmarked sentinel differs by index: CHARGE uses -1 (0 is a
                # valid index), DRY/FC/DROP use 0 — both at init and when a
                # mark is undone.
                elif ti[1] == 0 and (qmc.autoDRYenabled or self.aw.TilauScopeDEMarkFlag):
                    status_parts.append(self.str_autodry)
                elif ti[2] == 0 and (qmc.autoFCsenabled or self.aw.bleTilauScopeautomarkFC or self.aw.TilauScopeFCMarkFlag):
                    status_parts.append(self.str_autofc)
                elif ti[2] > 0 and ti[6] == 0 and qmc.autoDROPenabled:
                    status_parts.append(self.str_autodrop)

            new_status = " - ".join(status_parts)
            if getattr(self, '_last_simulator_status', None) != new_status:
                self._last_simulator_status = new_status
                self.status_lbl.setText(new_status)

            self.check_sliders_update()

            if (self.roast_assistant.isVisible() or getattr(self, '_assistant_anchored', False)) and self.roast_assistant.is_active:
                self.roast_bridge.tick(data)

        elif 0 <= data <= 7:  # Shared logic for Charge through Cool
            # A milestone changes the frame, the phase grounds and the marks all
            # at once. Waiting for the next sample to redraw would show the mark
            # a second after the operator made it.
            if self.curve is not None:
                self.curve.tick()
            self._handle_milestone_events(data, buttonState)

    def update_status_text(self):
        try:
            if not hasattr(self, 'aw') or not self.aw or not hasattr(self.aw, 'qmc') or not self.aw.qmc: # artisan is not correctly initialized yet
                return
            self._sync_wake_lock()
            status_text = "ARTISAN "+(QApplication.translate("tilauscope_window","CONNECTED") if self.aw.qmc.flagon else QApplication.translate("tilauscope_window","OFFLINE"))
            # if there is an alarm set selected

            # Guided mode is the sole control authority: suppress all
            # alarm ACTIONS via the native lever (conditions still evaluated,
            # nothing fired). Re-asserted here so it survives the reset that clears
            # silent_alarms (canvas ~15151); this method is the single point where
            # alarm-suppression state and its banner display stay in sync.
            if getattr(self, "_operator_level", "guided") == "guided":
                self.aw.qmc.silent_alarms = True
                alarm_set = QApplication.translate("tilauscope_window", " 🔕 ALARM-SET='<b>{0}</b>' SUSPENDED").format(self.aw.qmc.alarmsetlabel.upper()) if self.aw.qmc.alarmsetlabel != "" else ""
            else:
                alarm_set = QApplication.translate("tilauscope_window", " ALARM-SET='<b>{0}</b>'").format(self.aw.qmc.alarmsetlabel.upper()) if self.aw.qmc.alarmsetlabel != "" else ""
            status_text += alarm_set
            # if roast started
            # ground truth is Artisan's flagstart, NOT is_roasting: our own flag
            # drifts whenever recording is toggled outside our button (Artisan STOP,
            # a remote command, the simulator). This method is the single sync point.
            self.is_roasting = bool(self.aw.qmc.flagstart)
            # The guided assistant is started/stopped by the recording state edge,
            # emitted here for the same reason: a roast started outside our START/STOP
            # button (Artisan, simulator, remote command, alarm) must still be picked
            # up, or the assistant stays on its idle page with no plan adopted.
            _prev_roasting = getattr(self, '_last_flagstart', None)
            # Frozen BEFORE the body, not after: the body re-enters this method
            # (the replay teardown below restores the operator level, and
            # _apply_operator_level ends on update_status_text). Left until the
            # end, the nested call still saw the old value and fired the whole
            # edge a second time — a second roast-state notify and a second
            # queued roast review. Same trap as ToggleRecorder's re-entry.
            self._last_flagstart = self.is_roasting
            if _prev_roasting is not None and _prev_roasting != self.is_roasting:
                try:
                    self.roast_bridge.notify_roast_state(self.is_roasting)
                except Exception as e:  # pylint: disable=broad-except
                    _log.debug("roast state notify: %s", e)
                # Artisan re-shows its own milestone bar at every
                # OnRecorder (applyStandardButtonVisibility) — TilauScope has its
                # own milestone row, so that bar must go back down whatever
                # started the recording, not only our own button.
                if self.is_roasting:
                    self._hide_artisan_standard_buttons()
                else:
                    # A replay never carries over to the next roast, and the
                    # level it borrowed comes back — whatever ended the
                    # recording. Our own STOP button does this too; a STOP from
                    # Artisan, from an alarm action or from the phone reaches
                    # only this edge, and used to leave replay_enabled set, the
                    # level button locked and the operator stuck in Expert.
                    try:
                        if self.replay_enabled:
                            self._disable_roast_replay()
                        self._restore_replay_level()
                    except Exception as e:  # pylint: disable=broad-except
                        _log.debug("replay teardown at roast end: %s", e)
                # START locks Expert in place, STOP releases it.
                self._refresh_level_lock()
                # A recording that just ended leaves the controls with nothing
                # to steer: the review takes their place. Deferred so the stop
                # path (result dialog, save, cooling) finishes first.
                if not self.is_roasting:
                    QTimer.singleShot(0, self.show_roast_review)
                else:
                    self.hide_roast_review()
            if self.is_roasting: # replace text with roast information
                status_text = self.str_roastsession.upper()
            # now check for simulation mode
            simulator_text =""
            self._is_simulator = bool(self.aw.simulator)
            if self._is_simulator:
                simulator_text = " - "+self.str_simulator if hasattr(self, "str_simulator") else "" # Fix 2026/04/15
                # "paused" only means something while the scope is still ON: with
                # monitoring off the loop is stopped, not paused, and the status
                # already says OFFLINE — claiming a pause on top of it is wrong.
                if not self.aw.sample_loop_running and self.aw.qmc.flagon:
                    simulator_text += " "+ self.str_paused
                else:
                    b= self.aw.qmc.timeclock.elapsedMilli()
                    try:
                        b_val = float(b)
                        if b_val > 1000.0:
                            simulator_text += f" x{round(b_val * 0.001, 0)}"
                    except (TypeError, ValueError):
                        pass
            # store concatened text
            self.status_lbl.setText(f"{status_text}{simulator_text}")
            self.status_lbl.setStyleSheet(f"color: {THEME['SUCCESS'] if self.aw.qmc.flagon else THEME['CRITICAL']}; border: none; background:transparent;")
            self.update_button_style(self.btn_power, self.aw.qmc.flagon, False, False, True)
            self.update_button_style(self.btn_start_stop, self.aw.qmc.flagstart, False, False, True)
            # remote clients live off Artisan's sampling ticks, which
            # stop with the sampling itself — a STOP that also takes monitoring down
            # (simulator) would never reach the phone. This method already runs at
            # every point where the desktop state changed, so it is the natural
            # place to push it. Guarded: the status bar must never break for it.
            try:
                tap = getattr(self.aw, 'tilau_telemetry_tap', None)
                if tap is not None:
                    tap.sync_state()
            except Exception as e:  # pylint: disable=broad-except
                _log.debug("remote sync_state: %s", e)
        except Exception as e:
            _log.error(e)

    def timer_clicked(self):
        # Artisan only treats this click as simulator pause while recording.
        # Before START the same routine toggles its unrelated superuser mode.
        if self._is_simulator and self.aw.qmc.flagon and self.aw.qmc.flagstart:
            self.aw.superusermodeLeftClicked()
            # Pausing stops Artisan's TIMER signal, so the visual transition
            # must be applied synchronously from the post-click ground truth.
            self._sync_simulator_timer_style()
            self.update_status_text()

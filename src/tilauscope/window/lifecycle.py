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

"""A roast from preheat to cooling, and the replay that can stand in for one.

A slice of the roasting window. It is a mixin rather than a collaborator: the
window is one object with one set of attributes, and these methods read and
write it exactly as they did when they sat in the same file. What the split
buys is a boundary to read within, not a decoupling.
"""

from __future__ import annotations

import logging
import math
from typing import Final
import os

from PyQt6.QtCore import QSettings, QTime, QTimer
from PyQt6.QtWidgets import QApplication
from pathlib import Path
from tilauscope.roasters import invalidate_roast_context, roast_context_for
from tilauscope.theme_qss import tooltip_qss
from tilauscope.tilauscope_types import THEME
from tilauscope.widgets.dialogs import PlaybackWarningDlg


_log: Final[logging.Logger] = logging.getLogger(__name__)


def _has_usable_bt_trace(values: object) -> bool:
    """Return whether a background BT series contains a real reading.

    Artisan stores smoothed background temperatures in a NumPy array.  Its
    truth value is deliberately undefined once it contains more than one
    element, so this check must inspect readings instead of calling bool() on
    the container.  ``-1`` is Artisan's missing-reading sentinel.
    """
    try:
        for value in values:  # type: ignore[union-attr]
            if value is None:
                continue
            reading = float(value)
            if math.isfinite(reading) and reading != -1.0:
                return True
    except (TypeError, ValueError):
        return False
    return False


class LifecycleMixin:
    """A roast from preheat to cooling, and the replay that can stand in for one.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    # button CHARGE was pressed in the displayscope, update display and inform Artisan
    def start_roast(self, auto=False):
        if not self.aw.qmc.flagstart: # do not allow to press CHARGE before roast is really recorded
            return
        self.start_time = QTime.currentTime()
        self._update_timer_style("roasting")
        for btn in self.event_buttons.values():
            btn.setEnabled(True)
        # Réinitialiser les trackers min/max au CHARGE
        for lcd in (self.lcds.tg_lcd, self.lcds.te_lcd, self.lcds.ror_lcd):
            lcd.init_minmax()

    # Enter preheating stage,
    # engaged when start/stop button is pressed or Artisan STARTS
    def handle_preheat(self, show:bool = True):
        self.preheating = show
        # show or hide the individual phase widgets to make room for the message
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                if show :
                    widget.hide()
                else:
                    widget.show()
        if show:
            # Update and show the message
            status = self.get_pid_status()
            self.msg_lbl.setText(self.str_preheating + status)
            self.msg_lbl.show()
            self.msg_lbl.raise_()  # Force the label to the top of the stack
            # Style the container to highlight preheating mode
            self.phase_container.setStyleSheet(f"background: {THEME['CRUST']}; border-radius: 15px; border: 1px solid #F38BA866;")
            # Entering preheat owns the light, fixed timer state. Leaving preheat
            # does not: the caller already knows whether the next state is
            # roasting (CHARGE) or idle (STOP before CHARGE).
            self._update_timer_style("preheat")
        else:
            self.phase_container.setStyleSheet(f"background: {THEME['CRUST']}; border-radius: 15px; border: none;")
            # hide messag and show roasting phases zones
            self.msg_lbl.hide()
        if hasattr(self, 'roast_bridge'):
            self.roast_bridge.notify_preheat(show)

    def refresh_preheat_status(self) -> None:
        """Refresh the preheat banner after a PID control change."""
        if self.preheating:
            self.msg_lbl.setText(self.str_preheating + self.get_pid_status())

    # update display on DROP, then inform artisan
    def handle_drop(self):
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate("tilauscope_window","▼ DROPPING ROASTED COFFEE..."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()  # Force the label to the top of the stack
        self.phase_container.setStyleSheet(f"background: {THEME['CRUST']}; border-radius: 15px; border: 1px solid #F38BA866;")
        self.aw.qmc.markDropSignal.emit(False)
        # Armer la détection de refroidissement
        self._arm_cooling_detection()

    # arm/disarm shared by the UI/keyboard path (handle_drop) and the
    # Artisan milestone path (_handle_milestone_events, data==6) so the auto
    # cooling detection works regardless of how DROP was marked.
    def _arm_cooling_detection(self) -> None:
        self._drop_done = True
        self._cooling_detected = False
        try:
            self._bt_at_drop = float(self.aw.qmc.temp2[-1]) if self.aw.qmc.temp2 else None
            self._bt_drop_timestamp = self.aw.qmc.timex[-1] if self.aw.qmc.timex else None
        except (IndexError, TypeError):
            self._bt_at_drop = None
            self._bt_drop_timestamp = None

    def _clear_cooling_face(self) -> None:
        """Put the phase box back the way it was before the cooling message.

        The cooling and cooled messages both hide the phase blocks and repaint
        the box; nothing put either back, so the badge outlived the roast it
        belonged to.
        """
        self._disarm_cooling_detection()
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget is not None:
                widget.show()
        self.phase_container.setStyleSheet(
            f"background: {self.theme['BG']}; border-radius: 10px;"
            f" border: 1px solid {THEME['BORDER']}; margin-top: 10px;")

    def _disarm_cooling_detection(self) -> None:
        self._drop_done = False
        self._cooling_detected = False
        self._bt_at_drop = None
        self._bt_drop_timestamp = None

    def handle_cooling(self):
        """Déclenché automatiquement quand BT chute de >10°C en <30s après DROP."""
        self._cooling_detected = True
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate(
            "tilauscope_window",
            "❄ COOLING IN PROGRESS\nSet drum & airflow high — or prepare for back-to-back roast."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()
        self.phase_container.setStyleSheet(
            "background: #0F0F12; border-radius: 15px; border: 1px solid #89DCEB66;")

    # update display on COOL END, then inform artisan
    def handle_cool(self):
        """Compatibilité — redirige vers handle_cool_end."""
        self.handle_cool_end()

    def handle_cool_end(self):
        self._show_cooled_face()
        self.aw.qmc.markCoolSignal.emit(False)
        # Réinitialiser les flags de refroidissement
        self._disarm_cooling_detection()

    def _roaster_supports_profile_replay(self) -> bool:
        """Return the selected roaster's declared Replay capability.

        roast_context_for() owns the resolution and its aw-level cache; an
        unknown or absent roaster resolves to no context and is deliberately
        incompatible, matching RoastSetupDialog's safe default.
        """
        return bool(getattr(roast_context_for(self.aw), "supports_profile_replay", False))

    def refresh_replay_capability(self) -> None:
        """Re-resolve the selected roaster and realign everything reasoning on
        it — the header REPLAY button and the assistant's advisor. Called after
        the roaster changes in Devices; never raises into its caller.
        """
        try:
            invalidate_roast_context(self.aw)
            self._refresh_replay_button()
            assistant = getattr(self, "roast_assistant", None)
            if assistant is not None:
                assistant.reload_roaster_context()
        except Exception:  # pylint: disable=broad-except
            _log.exception("TilauScope: refresh_replay_capability failed")

    def arm_roast_replay(self, reaction_time_s: float) -> None:
        """Arms replay for the upcoming CHARGE. Called by RoastSetupDialog._on_ok()
        or the header button.

        A replay session has no plan of its own to guide — Guided is locked
        out immediately so launch_guided_assistant() (fired right after by
        the same workflow) becomes a no-op.
        """
        if not self._roaster_supports_profile_replay():
            self.replay_enabled = False
            self._refresh_replay_button()
            return
        self.replay_enabled = True
        self.replay_reaction_time_s = reaction_time_s
        self._apply_operator_level("expert")
        self._refresh_replay_button()

    def _disable_roast_replay(self) -> None:
        """Turns replay off immediately — the emergency-override path."""
        self.replay_enabled = False
        try:
            qmc = self.aw.qmc
            qmc.backgroundReproduce = False
            qmc.turn_playback_event_OFF()
        except Exception:  # pylint: disable=broad-except
            pass
        self._refresh_level_lock()
        self._refresh_replay_button()

    def _replay_externally_active(self) -> bool:
        """True if Artisan's native Background dialog already has playback
        engaged — bypassing this button/RoastSetupDialog entirely is a valid,
        pre-existing way to use it, and the icon must not lie about it."""
        try:
            qmc = self.aw.qmc
            return bool(qmc.backgroundPlaybackEvents or qmc.backgroundReproduce)
        except Exception:  # pylint: disable=broad-except
            return False

    def _toggle_replay_button(self) -> None:
        """Header REPLAY button: OFF at any time (including a replay armed
        natively via Artisan's own Background dialog), ON only while
        pre-CHARGE and a background curve is loaded (see _refresh_replay_button)."""
        if self.replay_enabled or self._replay_externally_active():
            self._disable_roast_replay()
        else:
            try:
                pre_charge = self.aw.qmc.timeindex[0] == -1
                has_background = self.aw.qmc.backgroundprofile is not None
            except Exception:  # pylint: disable=broad-except
                pre_charge, has_background = False, False
            if (self._roaster_supports_profile_replay()
                    and pre_charge and has_background):
                self.arm_roast_replay(self.replay_reaction_time_s)
        self._refresh_replay_button()

    def _refresh_replay_button(self) -> None:
        """Keep the header REPLAY button in sync with replay_enabled,
        eligibility, and any playback armed natively via Artisan's own
        Background dialog (see _replay_externally_active)."""
        try:
            pre_charge = self.aw.qmc.timeindex[0] == -1
            has_background = self.aw.qmc.backgroundprofile is not None
        except Exception:  # pylint: disable=broad-except
            pre_charge, has_background = False, False
        supports_replay = self._roaster_supports_profile_replay()
        if self.replay_enabled and not supports_replay:
            # Capability may change while the window stays open (Devices).
            # Disarm our automation immediately; the recursive refresh returns
            # here with replay_enabled already false.
            self._disable_roast_replay()
            return
        lit = self.replay_enabled or self._replay_externally_active()
        can_arm = supports_replay and pre_charge and has_background
        self.btn_replay.blockSignals(True)
        self.btn_replay.setChecked(lit)
        self.btn_replay.blockSignals(False)
        self.btn_replay.setEnabled(lit or can_arm)
        _col = "#89B4FA" if lit else THEME['SUBTEXT']
        self.btn_replay.setStyleSheet(
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {_col};"
            f" border: 1px solid {_col}; border-radius: 6px;"
            f" font-size: 15px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {THEME['BG']}; }}"
            f"QPushButton:disabled {{ color: {THEME['BORDER']};"
            f" border: 1px solid {THEME['BORDER']}; }}"
            + tooltip_qss()
        )
        if lit:
            _tip = QApplication.translate("tilauscope_window", "Roast Replay: ON — click to stop")
        elif not supports_replay:
            _tip = QApplication.translate("tilauscope_window", "Roast Replay — not supported by this roaster")
        elif can_arm:
            _tip = QApplication.translate("tilauscope_window", "Roast Replay — replays the loaded background curve")
        elif not pre_charge:
            _tip = QApplication.translate("tilauscope_window", "Roast Replay — available only before CHARGE")
        else:
            _tip = QApplication.translate("tilauscope_window", "Roast Replay — load a background curve before CHARGE to enable")
        self.btn_replay.setToolTip(_tip)

    def _engage_replay(self) -> None:
        """Engages Artisan's real playback engine at CHARGE — called from
        _handle_milestone_events (data==0). Picks the replay strategy:
        read-only roasters get the aid message only (no sliders to move);
        controllable ones get full slider replay, tracking BT once available
        (Artisan itself falls back to time-based before TP, see
        canvas.py playbackevent()) with a time-based fallback if the
        background curve has no usable BT trace.
        """
        qmc = self.aw.qmc
        if not self._roaster_supports_profile_replay():
            self._disable_roast_replay()
            return
        if qmc.backgroundprofile is None:
            # armed but nothing to replay after all
            self.replay_enabled = False
            self._refresh_replay_button()
            return
        readonly = bool(getattr(self.aw, "tilau_roaster_readonly", False))
        qmc.backgroundReproduce = True
        if not readonly:
            has_bt = _has_usable_bt_trace(qmc.stemp2B)
            qmc.replayType = 1 if has_bt else 0
            qmc.specialeventplayback = [True, True, True, True]
            qmc.specialeventplaybackramp = [True, True, True, True]
            qmc.ramp_lookahead = max(0, int(round(self.replay_reaction_time_s)))
            qmc.turn_playback_event_ON()
        self._refresh_replay_button()

    def toggle_roast_assistant(self):
        """Toggle the roast assistant open/closed (placement is centralised)."""
        self._assistant_open = not getattr(self, '_assistant_open', False)
        self.update_button_style(self.btn_assistant, self._assistant_open, False, False, True)
        if self._assistant_open:
            self.roast_assistant.populate_bean_list()   # refresh bean identification on open
        self._place_assistant()

    def _has_charged_roast(self) -> bool:
        """True only after CHARGE: preheating alone is not a roast result."""
        return self._milestone_marked(0)

    def show_roast_review(self) -> None:
        """Hand the whole left column over to the roast review.

        A roast being consulted is not being steered: the machine controls, the
        readouts and the status line all describe a live session and say nothing
        about a finished one, so they go and the review takes the space. There
        is no way in and no way out — START or RESET brings the column back.
        """
        try:
            if (self.aw.qmc.flagstart or not self._has_charged_roast()
                    or not self.roast_review.has_roast()):
                return
            self.roast_review.refresh()
            self._review_shown = True
            self._set_live_column_visible(False)
            self._place_assistant()
        except Exception as e:  # pylint: disable=broad-except
            _log.warning("show_roast_review: %s", e)

    def hide_roast_review(self) -> None:
        """Give the column back to the live session (START, RESET)."""
        if not hasattr(self, "roast_review"):
            return   # called from a status refresh before the panel is built
        try:
            if not self._review_shown:
                return
            self._review_shown = False
            self._set_live_column_visible(True)
            self._place_assistant()
        except Exception as e:  # pylint: disable=broad-except
            _log.warning("hide_roast_review: %s", e)

    def _open_roast_card(self) -> None:
        """The full card, over the panel: same figures, plus the curve."""
        try:
            from tilauscope.roast_card import RoastCardDialog
            from tilauscope.roast_debrief import profile_from_qmc, display_name
            profile = profile_from_qmc(self.aw)
            RoastCardDialog(profile, self, bean_name=display_name(profile)).exec()
        except Exception as e:  # pylint: disable=broad-except
            _log.warning("_open_roast_card: %s", e)

    def _enter_roast_weights(self) -> None:
        """Weight/colour entry from the review, then take the new values in."""
        # The review may describe a roast other than the row currently selected
        # in BeanCave.  Carry the identity frozen when this review was built;
        # never let a later UI selection decide which coffee the edit belongs to.
        profile = self.roast_review.reviewed_profile()
        if profile is None:
            _log.warning("review result form skipped: no reviewed profile snapshot")
            return
        self._open_roast_result_dialog(profile)
        if getattr(self, '_review_shown', False):
            self.roast_review.refresh()

    # ── Opening on a session Artisan is already running ──────────────────
    def _adopt_live_artisan_state(self) -> None:
        """Take over a monitoring/recording session started before this window.

        Every control here is built idle. MONITOR is a checkable button, so an
        unchecked one on a live session reads as "start" at the first click: it
        paints the engaged look, then hands Artisan a ToggleMonitor that stops
        the running session — display and reality inverted from then on.
        """
        try:
            qmc = self.aw.qmc
            if not qmc.flagon:
                return

            # monitoring on — same widget set as the ON branch of toggle_power()
            self.btn_power.setChecked(True)
            self.update_button_style(self.btn_power, True, False, True)
            self.btn_power.setToolTip(QApplication.translate('Tooltip', 'Stop monitoring'))
            self.update_button_style(self.btn_start_stop, True)
            self.update_button_style(self.btn_assistant, True)
            self.update_button_style(self.swap_button, False)
            self.update_button_style(self.btn_reset, not qmc.flagstart)
            for btn in self.event_buttons.values():
                btn.setEnabled(True)
            self.event_panel.show()
            self._update_timer_style("engaged")

            if not qmc.flagstart:
                self.update_status_text()
                return

            # recording on
            self.is_roasting = True
            self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Stop recording'))
            self._hide_artisan_standard_buttons()
            self._refresh_level_lock()
            self.aw.messagelabel.setVisible(False)

            ti = qmc.timeindex
            timex = qmc.timex
            if ti[0] <= -1 or len(timex) <= ti[0]:
                # recording, drum not charged yet: the roast is still preheating
                self.handle_preheat(True)
                self.roast_bridge.notify_roast_state(True)
                self.roast_bridge.notify_phase("PREHEAT")
                self.update_status_text()
                return

            charge_t = timex[ti[0]]
            now_secs = max(int(round(timex[-1] - charge_t)), 1)

            def _secs(idx: int) -> int:
                return int(round(timex[idx] - charge_t))

            def _marked(idx: int) -> bool:
                # the sentinel itself lives in _milestone_marked(); here it only
                # has to be paired with a bounds check, since every caller below
                # indexes timex with the mark it just accepted.
                return self._milestone_marked(idx) and len(timex) > ti[idx]

            self.handle_preheat(False)
            self.start_roast(auto=True)
            self.set_phase("DRY", 0)
            phase = "DRY"
            if _marked(1):
                mai_start = _secs(ti[1])
                self.phases["DRY"].update_stats(mai_start, now_secs)
                self.set_phase("MAI", mai_start)
                phase = "MAI"
            if _marked(2):
                dev_start = _secs(ti[2])
                self.phases["MAI"].update_stats(dev_start - (self.phase_starts["MAI"] or 0), now_secs)
                self.set_phase("DEV", dev_start)
                phase = "DEV"
            if _marked(6):
                drop_secs = _secs(ti[6])
                self.phases["DEV"].update_stats(drop_secs - (self.phase_starts["DEV"] or 0), max(drop_secs, 1))
                # past DROP the timer counts the cooling: the development stats
                # must stop following it, exactly as the DROP milestone does
                self._freeze_phases_at_drop()
                self._drop_done = True
                self._cooling_detected = False
                phase = "COOL"
                if _marked(7):
                    self._disarm_cooling_detection()
                else:
                    # arm on the recorded DROP sample, not on the current one:
                    # the drum may already have been cooling for a while
                    self._bt_at_drop = float(qmc.temp2[ti[6]]) if len(qmc.temp2) > ti[6] else None
                    self._bt_drop_timestamp = timex[ti[6]]

            marked = [i for i in range(8) if _marked(i)]
            if marked:
                last = marked[-1]
                # the last mark stays clickable so it can be undone — except a
                # DROP, which the milestone handler locks down like the rest
                for i in marked:
                    self.mark_button_active(i, disable_button=(i != last or last == 6))

            self.roast_bridge.notify_roast_state(True)
            self.roast_bridge.notify_phase(phase)
            self.update_status_text()
        except Exception as e:  # never let a partial adoption block the window
            _log.error(e)

    def _stop_all_automation(self) -> None:
        """Cut everything that could re-apply heat a second later. Each step is
        isolated: one failing branch must never skip the ones after it."""
        aw = self.aw
        try:
            tpid = getattr(aw, 'tilauPreheatingPid', None)
            if tpid is not None and getattr(tpid, 'active', False):
                tpid.stop('emergency')       # already commands burner zero
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: preheat PID stop failed')
        try:
            if aw.pidcontrol.pidActive:
                aw.pidcontrol.pidOff()
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: Artisan PID off failed')
        try:
            # Owns the whole replay side — the flag, the header button and the
            # level lock — which the raw qmc writes below cannot reach. Without
            # it the button kept reading ON over a replay already cut dead.
            self._disable_roast_replay()
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: disabling roast replay failed')
        try:
            # Deliberately redundant with the call above: on an emergency path
            # each flag is worth setting twice rather than once behind a guard.
            qmc = aw.qmc
            qmc.backgroundPlaybackEvents = False
            qmc.backgroundPlaybackDROP = False
            qmc.backgroundReproduce = False
            qmc.alarmsflag = 0           # an alarm can fire a slider action
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: disabling playback/alarms failed')
        try:
            assistant = getattr(self, 'roast_assistant', None)
            if assistant is not None:
                assistant.emergency_disengage()
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: assistant disengage failed')

    def _stop_recording_no_reading(self) -> None:
        """Stop the recording, then paint the banner over what the stop left."""
        try:
            self.toggle_start_stop(False, force=True)
        except Exception:  # pylint: disable=broad-except
            _log.exception('no-reading: stopping the recording failed')
        self._show_no_reading_face(stopped=True)

    def handle_reset(self):
        self._clear_emergency_state()
        self._clear_no_reading_face()
        # Nothing left on screen to review once the canvas is cleared.
        self.hide_roast_review()
        self.aw.qmc.resetButtonAction()

    def _save_current_roast_silently(self) -> bool:
        """Sauvegarde l'alog courant sans dialogue : autosave Artisan si
        configuré, sinon écriture directe dans le répertoire alog TilauScope
        (même nomenclature generateFilename). Marque le profil « propre » pour
        que le RESET qui suit ne déclenche pas l'invite de sauvegarde.
        False si aucune destination n'existe — la relance est alors abandonnée
        plutôt que de risquer le roast."""
        try:
            qmc = self.aw.qmc
            if qmc.autosaveflag and qmc.autosavepath:
                return self.aw.automaticsave(interactive=False) is not None
            from artisanlib.util import serialize
            directory = qmc.autosavepath or QSettings().value('alogDirectory', '', str)
            if not directory or not Path(str(directory)).is_dir():
                _log.warning("relaunch: no save directory (autosavepath/alogDirectory) — aborted")
                return False
            prefix = qmc.autosaveprefix or (
                (qmc.batchprefix + str(qmc.roastbatchnr)) if qmc.roastbatchnr > 0
                else qmc.batchprefix)
            filename = self.aw.generateFilename(prefix=prefix)
            path = os.path.join(str(directory), filename)
            pf = self.aw.getProfile()
            if pf is None:
                return False
            serialize(path, pf)
            self.aw.setCurrentFile(path, False)
            qmc.fileCleanSignal.emit()
            self.aw.sendmessage(QApplication.translate(
                'Message', 'Profile {0} saved in: {1}').format(filename, str(directory)))
            _log.info("relaunch: silent save %s", path)
            return True
        except Exception as e:  # pylint: disable=broad-except
            _log.warning(f"relaunch silent save failed: {e}")
            return False

    #build end of roast message
    def build_end_of_roast(self)->str:
        try:
            # total time of roast from charge to drop
            total_sec = self.aw.qmc.timex[self.aw.qmc.timeindex[6]]-self.aw.qmc.timex[self.aw.qmc.timeindex[0]]+1
            m, s = divmod(int(total_sec), 60)
            str_total_time = f"{m:02d}:{s:02d}"
            # build DTR
            dtr = (self.aw.qmc.timex[self.aw.qmc.timeindex[6]]-self.aw.qmc.timex[self.aw.qmc.timeindex[2]]) * 100.0/ total_sec
            str_dtr = f"{dtr:.0f}%"
            # delta T
            temp_at_fc = self.aw.qmc.temp2[self.aw.qmc.timeindex[2]]
            temp_at_drop = self.aw.qmc.temp2[self.aw.qmc.timeindex[6]]
            delta_temp  = temp_at_drop - temp_at_fc
            str_delta_t =  f"{delta_temp:.1f}°{self.aw.qmc.mode}"
        except Exception:
            str_total_time = "--:--"
            str_dtr = "--"
            str_delta_t="--.-"
        # Literal at the call, values substituted after: an f-string here is
        # invisible to the extractor and would ship in English everywhere.
        return QApplication.translate(
            "tilauscope_window",
            "Total time: {0} - DTR {1} - Dev ΔT {2}",
        ).format(str_total_time, str_dtr, str_delta_t)

    def check_playback_before_start(self):
        """
        Méthode à appeler juste après le clic sur 'START'
        """
        active_modes = []
        # Accès aux flags via le Quality Management Controller (qmc) d'Artisan
        if self.aw.qmc.backgroundReproduce:
            active_modes.append(QApplication.translate("CheckBox", "Playback Aid"))
        if self.aw.qmc.backgroundPlaybackEvents:
            active_modes.append(QApplication.translate("CheckBox","Playback Events"))
        if self.aw.qmc.backgroundPlaybackDROP:
            active_modes.append(QApplication.translate("CheckBox","Playback DROP"))

        if active_modes:
            dlg = PlaybackWarningDlg(self.aw, active_modes)
            dlg.exec()

            if dlg.result_code == PlaybackWarningDlg.CANCEL:
                return False # On stoppe le processus de démarrage

            elif dlg.result_code == PlaybackWarningDlg.DISABLE_AND_START:
                # Désactivation propre via les méthodes d'Artisan pour mettre à jour l'UI
                self.aw.qmc.backgroundReproduce = False
                self.aw.qmc.turn_playback_event_OFF()
                self.aw.qmc.backgroundPlaybackDROP = False

        return True # On autorise le démarrage

    # Handle START/STOP button action
    def toggle_start_stop(self, pressed, force=False):
        if force :
            pressed = False

        if not self.is_roasting and self.aw.qmc.device == 18 and self.aw.simulator is None:
            self.msg_lbl.setText(QApplication.translate(
                "tilauscope_window",
                "⚠ No meter connected — configure a device in Machine > Device."))
            self.msg_lbl.show()
            self.msg_lbl.raise_()
            return

        # only warn about active automations when STARTING a roast;
        # the dialog must never pop up on STOP (is_roasting already True).
        if not self.is_roasting and not self.check_playback_before_start():
            return
        # snapshot BEFORE ToggleRecorder: Artisan calls back into
        # update_status_text() synchronously, which resyncs self.is_roasting on
        # flagstart. Reading the flag after the call therefore reports the NEW
        # state, and a START was taken for a STOP — post-roast result dialog
        # popping up 800 ms after pressing START.
        was_roasting = self.is_roasting
        had_charge = was_roasting and self._has_charged_roast()
        self.aw.qmc.ToggleRecorder(pressed)
        if not was_roasting :
            self.aw._tilaupid_user_disabled = False
            # update roasting flag
            self.is_roasting = True
            # Reset timing state so phase counters start fresh
            self.last_update_second = -1
            self.phase_starts = {"DRY": None, "MAI": None, "DEV": None}
            self.current_phase = None
            # Recording is active while waiting for CHARGE: clear and steady.
            self._update_timer_style("preheat")
            self._hide_artisan_standard_buttons()
            # start preheating
            self.handle_preheat(True)
            #. disable reset button
            self.update_button_style(self.btn_reset, False)
            self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Stop recording'))
            # Masquer messagelabel Artisan : le flux est redirigé vers le ticker
            self.aw.messagelabel.setVisible(False)
            self.roast_bridge.notify_roast_state(True)
        else:
            # update roasting flag
            self.is_roasting = False
            self._update_timer_style("idle")   # back to grey pulse
            self.roast_bridge.notify_roast_state(False)   # stops the assistant
            self._hide_automation_banner()   # clear automation notice at roast end
            if self.replay_enabled:
                self._disable_roast_replay()   # a replay session never carries over to the next roast
            if self.preheating:
                self.handle_preheat(False)
                self.preheating = False
            self.update_status_text()
            # at end of roast enable reset button to clear the screen
            self.update_button_style(self.btn_reset, True)
            # only the TilauScope preheating PID is piloted here; Artisan's own PID is left untouched.
            if self.aw.tilauPreheatingPid is not None and self.aw.tilauPreheatingPid.active:
                self.aw.tilauPreheatingPid.stop(reason="recording_stop")
            self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Start recording'))
            # Ouvrir roast properties 800ms après la fin pour laisser Artisan terminer.
            # Mode batch (relance back-to-back) : PAS de formulaire — la saisie
            # poids/couleur est différée dans Repair ALogs (design validé), le
            # roast est sauvegardé incomplet silencieusement par la relance.
            if (had_charge and not self.aw.simulator
                    and not getattr(self, '_relaunch_pending', False)):
                QTimer.singleShot(800, self._open_roast_result_dialog)
            # reset phases display to normal
            for p in self.phases.values():
                p.set_active(False)
            for n in range (0,8): # reset buttons styles
                self.set_button_style(n, True)
                self.set_button_state(n, False)
            # The cooling face survived the stop: handle_cooling() hides the
            # phase blocks and paints the box cyan, and replacing the text alone
            # left the badge on screen over a roast that had ended.
            self._clear_cooling_face()
            # now update the current message label to display main info on roast session
            if had_charge:
                self.msg_lbl.setText(QApplication.translate(
                    "tilauscope_window",
                    "Roasting has ended — press OFF to see the figures."))
            else:
                self.msg_lbl.setText(QApplication.translate(
                    "tilauscope_window",
                    "Preheating interrupted — monitoring remains active."))
            # Restaurer messagelabel Artisan : fin de torréfaction
            self.aw.messagelabel.setVisible(True)
            # Réinitialiser les alertes de fond et tooltips min/max
            for lcd in (self.lcds.tg_lcd, self.lcds.te_lcd, self.lcds.ror_lcd):
                lcd.reset_alert()
                lcd.init_minmax()

    def _open_roast_result_dialog(self, review_profile: dict | None = None) -> None:
        """Ouvre RoastResultDialog en fin de roast — même pattern que
        BeancaveDlg.on_roast_finished_clicked."""
        # The callback is delayed by 800ms. Re-check the live profile so a
        # preheat interruption (or a RESET during the delay) never opens a
        # post-roast form for a roast that did not reach CHARGE.
        if not self._has_charged_roast():
            _log.info("post-roast result skipped: recording stopped before CHARGE")
            return
        try:
            from tilauscope.roast_properties import RoastResultDialog

            # reset() (ON/RESET) may have wiped qmc.title/qmc.beans.
            # Restore the live values stashed at setup so the save filename
            # and the .alog bean linkage are correct. Live DROP path only: a
            # review owns its own frozen identity and must never consume a
            # stale live-session stash.
            qmc = self.aw.qmc
            if review_profile is None:
                default_title = QApplication.translate('Scope Title', 'TilauScope')
                stash_title = getattr(self.aw, '_tilau_live_title', '')
                stash_beans = getattr(self.aw, '_tilau_live_beans', '')
                if stash_title and (not qmc.title or qmc.title == default_title):
                    qmc.title = stash_title
                    qmc.title_show_always = True
                if stash_beans and not getattr(qmc, 'beans', ''):
                    qmc.beans = stash_beans
                bean_description = getattr(qmc, 'beans', '') or ''
            else:
                bean_description = str(review_profile.get('beans') or '')

            # green_weight depuis qmc.weight
            green_weight = 0.0
            try:
                green_weight = float(self.aw.qmc.weight[0])
            except (ValueError, TypeError, IndexError):
                pass

            # Passing no bean deliberately activates UUID resolution from the
            # roast description.  BeanCave's currently highlighted row is not
            # evidence about the roast being edited.
            dlg = RoastResultDialog(
                None,
                self.aw,
                green_weight=green_weight,
                bean_description=bean_description,
            )
            dlg.exec()
        except Exception as e:
            _log.warning(f"_open_roast_result_dialog: {e}")

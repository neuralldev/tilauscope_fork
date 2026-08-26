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

"""The machine controls and the set-point: reading them, moving them, committing them.

A slice of the roasting window. It is a mixin rather than a collaborator: the
window is one object with one set of attributes, and these methods read and
write it exactly as they did when they sat in the same file. What the split
buys is a boundary to read within, not a decoupling.
"""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from tilauscope.graph.common import within_share


_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")


# Coalescing window for slider commits: a burst of +/- clicks within
# this delay sends a single hardware command with the final value instead of
# one command (and one recorded event) per click.
_SLIDER_COMMIT_DEBOUNCE_MS: Final[int] = 300


class SlidersMixin:
    """The machine controls and the set-point: reading them, moving them, committing them.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    def _apply_slider_visibility_mirror(self) -> None:
        """Mirror Artisan's per-slider visibilities (eventslidervisibilities,
        idx 0-3) onto the slider rows: a slider disabled on the Artisan side is
        hidden here too. Called at build time and re-callable from the config
        dialog when the roaster changes. The SV slider (idx 4) is never
        touched. """
        try:
            vis = self.aw.eventslidervisibilities
            for i, row_w in enumerate(getattr(self, "_slider_row_widgets", [])):
                row_w.setVisible(bool(vis[i]) if i < len(vis) else True)
        except Exception:
            _logd.exception("TilauScope: _apply_slider_visibility_mirror failed")

    def _get_pid_target(self)->str:
        # pidcontrol.sv est mis à jour par processcommand("sv") ET processcommand("start")
        # via setSV() — c'est le signal que l'alarme a été traitée pour cette session.
        # Tant qu'il ne correspond pas au slider, l'alarme n'est pas encore passée
        # → on retourne "" pour ne rien afficher plutôt qu'une valeur obsolète.
        try:
            # When TilauPID drives the preheat, ITS target is the truth and
            # needs no confirmation from Artisan: aw.pidcontrol.sv is only ever set
            # by branches that require Artisan's own PID path (external PID / Control
            # flag), so on a slider-driven roaster it stays None forever and the
            # status message was stuck on "TilauPID is initializing" for the whole
            # preheat.
            pid = self.aw.tilauPreheatingPid
            if pid is not None and pid.active:
                sv_native = int(round(pid.sv_native()))
                return str(sv_native) if sv_native > 0 else ""
            sv_pid = self.aw.pidcontrol.sv       # None ou valeur native
            sv_slider = self.sld_list[4].value() # toujours un int, valeur native
            if sv_pid is not None and sv_slider > 0 and int(sv_pid) == sv_slider:
                # alarme traitée — valeur confirmée pour cette session (> 0 évite "0" à l'init)
                return str(sv_slider)
            # alarme pas encore traitée → rien à afficher
            return ""
        except Exception:
            return ""

    def _is_pid_target_close(self, bt: float) -> bool:
        """Whether the drum has reached its target.

        It used to return a "prepare to charge" line for this panel. The chart
        already says CHARGE NOW on the head of the climb, where the operator is
        looking, so the panel said the same thing a third time — this now only
        reports the state, and the badge gives up its line to nothing.
        """
        pid = self.aw.tilauPreheatingPid
        if pid and pid.active:
            sv = pid.sv_native()   # cfg.target_sv est °C interne ; bt est natif
            delta = sv - float(bt)
            # Même bande que la courbe et l'annotation — jugée en °C.
            return (delta <= 0) or within_share(delta, sv, 0.05, self.aw.qmc.mode)
        return False

    def _tilaupid_armed(self) -> bool:
        """True quand TilauPID pilote CE préchauffage.

        L'objet TilauPreheatPID est recréé à chaque passage du monitoring en ON :
        son existence ne prouve rien. Le préchauffage est piloté par TilauPID
        s'il tourne déjà, ou si une commande START lui est armée (RoastSetup) —
        ce second test couvre la fenêtre où la commande est en file mais pas
        encore traitée.
        """
        pid = self.aw.tilauPreheatingPid
        if getattr(self.aw, '_tilaupid_user_disabled', False):
            return False
        if pid is None:
            return False
        if pid.active:
            return True
        try:
            actions = self.aw.qmc.xextrabuttonactions
            strings = self.aw.qmc.xextrabuttonactionstrings
            return (len(actions) > 1 and actions[1] == 5
                    and len(strings) > 1
                    and strings[1].lower().startswith('tilaupid(start'))
        except Exception:
            return False

    # build a string with the current pid status depending on artisan or tilaupid usage
    def get_pid_status(self, with_badge: bool = True):
            # Aucun PID en jeu → "with no PID"
            tilaupid_armed = self._tilaupid_armed()
            if not tilaupid_armed and not self.is_pid_active:
                return self.str_nopid
            # Si TilauPID est armé mais la cible n'est pas encore confirmée → message init
            if tilaupid_armed and not self.is_pid_active:
                target = self._get_pid_target()
                if not target:
                    return self.str_tilaupidinit
                # NBSP (not a plain space) between value and unit: the label word-wraps
                # and would otherwise drop "°C" alone on the next line. A literal
                #   survives .upper() where an &nbsp; entity would not.
                base = (self.str_tilaupid + f" {target} °{self.aw.qmc.mode}").upper()
                # Learning-maturity mini-badge (segments + level word, cached on the PID
                # at start() — see TilauPreheatPID._compute_learning_badge). Appended
                # AFTER .upper() so its HTML markup/colours are not case-mangled.
                pid = self.aw.tilauPreheatingPid
                badge = (getattr(pid, 'learning_badge_compact_html', '')
                         if (pid is not None and with_badge) else '')
                # Own block with a top margin: a bare <br> glued the badge to the
                # two-line preheat headline with no breathing room.
                return f'{base}<div style="margin-top:10px;">{badge}</div>' if badge else base
            pid_text = self.str_artisanpid if self.is_pid_active else ""
            target = self._get_pid_target()
            pid_target = f" {target} °{self.aw.qmc.mode}" if target else ""
            return pid_text.upper() + pid_target

    def check_pid_status(self):
        # tracks Artisan PID active state for the preheating status
        # message only — the PID button/piloting was removed (handled by Artisan).
        if self.aw.pidcontrol.pidActive != self.is_pid_active:
            self.is_pid_active = self.aw.pidcontrol.pidActive

    def _apply_sv_lock(self, locked: bool) -> None:
        """Enable/disable the whole SV row. No-op unless the state actually flips,
        so this stays O(1) on the pulse path. """
        if locked == self._sv_locked or not self._sv_widgets:
            return
        self._sv_locked = locked
        tip = QApplication.translate(
            "tilauscope_window",
            "Set point driven by TilauPID while preheating"
        ) if locked else ""
        for w in self._sv_widgets:
            w.setEnabled(not locked)
            w.setToolTip(tip)

    def check_sliders_update(self):
        aw = self.aw
        # mirror-only: copying Artisan values into our sliders must not
        # re-fire the move/release handlers back toward Artisan. The visible
        # value labels still refresh (their valueChanged lambda is not guarded).
        self._syncing_from_artisan = True
        try:
            # 1. Handle the first 4 sliders — use pre-computed tuple (no per-call allocation)
            for i, art_slider in enumerate(self._artisan_sliders):
                # a value the operator still holds — handle down, or a click
                # inside the debounce window — has not reached Artisan yet:
                # mirroring here would snap the slider back under the finger.
                if self._slider_holds_user_value(i):
                    continue
                new_val = art_slider.value()
                if self.sld_list[i].value() != new_val:
                    self.sld_list[i].setValue(new_val)
            # 2. Handle the SV slider logic (index 4)
            pid = aw.tilauPreheatingPid
            # while the guided preheat runs, the SV displayed IS TilauPID's
            # target — it is overwritten on every pulse, so editing it can only look
            # broken. Lock the row instead of letting the operator fight the PID.
            self._apply_sv_lock(pid is not None and pid.active)
            if not self._slider_holds_user_value(4):
                if pid is not None and pid.active:
                    target_val = int(pid.sv_native())  # slider SV est en unité native
                    if target_val != self.sld_list[4].value():
                        self.sld_list[4].setValue(target_val)
                else:
                    sv_val = aw.sliderSV.value()
                    if self.sld_list[4].value() != sv_val:
                        self.sld_list[4].setValue(sv_val)
        finally:
            self._syncing_from_artisan = False

    def update_pid_from_artisan(self,sv:int, move:bool = True, init:bool = False):
        if self._slider_holds_user_value(4):
            return  # what the operator holds wins over the echo from Artisan
        slider_sv = self.sld_list[4].value()
        if slider_sv != int(sv) :
            self.sld_list[4].setValue(int(sv))

    def _slider(self, n):
        """Control `n`, or None before the window has built its controls."""
        try:
            return self.sld_list[n]
        except (AttributeError, IndexError, TypeError):
            return None

    def slider_value(self, n) -> int | None:
        """Current value of control `n`; None when there is no such control."""
        slider = self._slider(n)
        return None if slider is None else int(slider.value())

    def set_slider_value(self, n, value, immediate: bool = False) -> bool:
        """Set control `n` and send it out to Artisan. Clamped to its range.

        Returns whether the control exists. What the machine actually received
        is what Artisan applied, which the commit mirrors back onto the slider.
        """
        slider = self._slider(n)
        if slider is None:
            return False
        slider.setValue(max(slider.minimum(), min(slider.maximum(), int(value))))
        self.handle_ui_input_released(n, immediate)
        return True

    def mirror_slider_from_artisan(self, n, value) -> None:
        """Show a value Artisan already holds. Never travels back outward.

        The opposite direction to set_slider_value, and telling the two apart is
        the whole point of this pair: called from Artisan's own LCD slots, a
        commit here would push our value over the one that just arrived.
        """
        slider = self._slider(n)
        if slider is None or self._slider_holds_user_value(n):
            return  # a handle still held wins over the echo
        self._syncing_from_artisan = True
        try:
            slider.setValue(int(value))
        finally:
            self._syncing_from_artisan = False

    def handle_ui_input_released(self, n, immediate: bool = False):
        if self.init or self._syncing_from_artisan:
            return
        timer = self._slider_commit_timers.get(n)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(_SLIDER_COMMIT_DEBOUNCE_MS)
            timer.timeout.connect(lambda idx=n: self._commit_slider_value(idx))
            self._slider_commit_timers[n] = timer
        if immediate:
            timer.stop()
            self._commit_slider_value(n)
        else:
            timer.start()   # restart: the window slides on every new click

    def _has_pending_commit(self, n) -> bool:
        """True while slider `n` holds a click that has not reached Artisan yet."""
        timer = self._slider_commit_timers.get(n)
        return timer is not None and timer.isActive()

    def _slider_holds_user_value(self, n) -> bool:
        """True while slider `n` shows a value Artisan has not received yet.

        Two ways to be in that state: the handle is still held down — a drag
        only commits on release — or a click sits in the debounce window. Both
        must fence off the mirror in check_sliders_update(), or the next sample
        overwrites the gesture in progress.
        """
        if self._has_pending_commit(n):
            return True
        try:
            return bool(self.sld_list[n].isSliderDown())
        except (AttributeError, IndexError):
            return False

    def flush_pending_slider_commits(self):
        """Fire any debounced slider commit still pending (window close, etc.)."""
        for n, timer in self._slider_commit_timers.items():
            if timer.isActive():
                timer.stop()
                try:
                    self._commit_slider_value(n)
                except Exception as e:      # never let a flush break the caller
                    _log.error(e)

    def _commit_slider_value(self, n):
        """Push the current slider value to Artisan (hardware + event record)."""
        if self.init or self._syncing_from_artisan:
            return
        if n in [0,1,2,3]:
            # Artisan's own slider transaction, not a copy of it: quantify to the
            # configured step, publish through moveslider(), then let
            # recordsliderevent() own the event value codec, the quantifier block
            # and the hardware action. A local copy drifted on negative values and
            # on zero, so the curve could disagree with what the roaster received.
            slidervalue = self.aw.applySliderStepSize(n, int(round(self.sld_list[n].value())))
            self.aw.moveslider(n, slidervalue)
            # moveslider() clamps to the Artisan min/max: mirror back what was
            # really applied, so our slider never shows a value nothing received.
            applied = self.aw.eventslidervalues[n]
            if self.sld_list[n].value() != applied:
                self._syncing_from_artisan = True
                try:
                    self.sld_list[n].setValue(applied)
                finally:
                    self._syncing_from_artisan = False
            self.aw.recordsliderevent(n)
        else:
            slidervalue = self.sld_list[n].value()
            self.aw.pidcontrol.setSV(slidervalue,True)
            # setSV only reaches Artisan's own SV slider when Artisan's PID
            # path is configured (external PID, ArduinoTC4, Kaleido or the Control
            # flag). On a slider-driven roaster none of those branches run, so
            # aw.sliderSV kept its old value and check_sliders_update snapped our
            # slider right back. Mirror it ourselves; signals stay blocked so this
            # cannot re-enter Artisan's SV chain.
            if self.aw.sliderSV.value() != slidervalue:
                self.aw.sliderSV.blockSignals(True)
                self.aw.sliderSV.setValue(slidervalue)
                self.aw.sliderSV.blockSignals(False)

    def handle_ui_input_move(self, n, value):
        if self.init or self._syncing_from_artisan:
            return
        # add action to slider
        if n in [0,1,2,3]:
            slider_lcd:dict[int, callable[int]] = {
                0:self.aw.updateSlider1LCD,
                1:self.aw.updateSlider2LCD,
                2:self.aw.updateSlider3LCD,
                3:self.aw.updateSlider4LCD
                }
            slider_lcd[n](value)
        else:
            # SV behaves like sliders 0-3: moving it only refreshes the LCD.
            # The set-point reaches the PID at commit (release) only, so a drag or
            # a burst of +/- clicks does not retarget the PID at each step.
            self.aw.updateSVSliderLCD(int(round(value)))

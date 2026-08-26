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

"""CHARGE through DROP: marking them, and the phase blocks that follow them.

A slice of the roasting window. It is a mixin rather than a collaborator: the
window is one object with one set of attributes, and these methods read and
write it exactly as they did when they sat in the same file. What the split
buys is a boundary to read within, not a decoupling.
"""

from __future__ import annotations

import logging
from typing import Final
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from artisanlib.util import toDim
from tilauscope.theme_qss import with_tooltip
from tilauscope.tilauscope_types import THEME


_log: Final[logging.Logger] = logging.getLogger(__name__)


class MilestonesMixin:
    """CHARGE through DROP: marking them, and the phase blocks that follow them.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    def _update_phase_subtitle(self,phase:str)->str:
        # check if there are phases defined on artisan
        if self.aw.qmc.phasesbuttonflag:
            if phase == "DRY":
                return QApplication.translate("tilauscope_window", "Auto")
            if phase == "MAI" :
                return QApplication.translate("tilauscope_window", "Auto")
            if phase == "DEV" :
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[3]) + "°" + self.aw.qmc.mode
            return ""
        else:
            if phase == "DRY":
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[1]) + "°" + self.aw.qmc.mode
            if phase == "MAI":
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[2]) + "°" + self.aw.qmc.mode
            if phase == "DEV":
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[3]) + "°" + self.aw.qmc.mode
            return ""

    # updates phase_start structure with current timer value for given phase (key) and highlight the current phase using set_active
    def set_phase(self, key, artisan_secs: int = 0):
        self.current_phase = key
        for k, widget in self.phases.items():
            widget.set_active(k == key)
        self.last_phase = key
        # Store Artisan timer seconds at phase transition — same source as data==10
        self.phase_starts[key] = artisan_secs

    def _phase_wheel(self, widget, event) -> None:
        """Ajuste qmc.phases[idx] de ±1° par cran de molette/trackpad.

        Bornes absolues : 60-250°C / 140-482°F (converties selon qmc.mode).
        Bornes relatives adaptatives :
          - premier éditable (DRY, idx=first) : lo=abs_lo,      hi=phases[idx+1]-1
          - milieu (MAI)                       : lo=phases[idx-1]+1, hi=phases[idx+1]-1
          - dernier éditable (DEV, idx=last)   : lo=phases[idx-1]+1, hi=abs_hi
        first/last calculés dynamiquement depuis len(phases).
        Guards : flagon, phasesbuttonflag+DRY/MAI.
        """
        qmc = self.aw.qmc
        if qmc.flagon:
            return
        idx = widget._phase_idx          # 1=DRY, 2=MAI, 3=DEV
        key = widget._phase_key
        if qmc.phasesbuttonflag and key in ("DRY", "MAI"):
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        # Accumuler le delta pour normaliser souris (±120/cran) et trackpad (flux continu)
        # Un step ne se déclenche que quand l'accumulation atteint ±120
        attr = f"_wheel_acc_{widget._phase_key}"
        acc = getattr(self, attr, 0) + delta
        if abs(acc) < 120:
            setattr(self, attr, acc)
            return
        step = 1 if acc > 0 else -1
        setattr(self, attr, 0)  # reset après déclenchement

        phases = qmc.phases              # liste mutable [below_dry, dry, mai, dev, ...]
        n = len(phases)
        first_editable = 1              # DRY
        last_editable  = n - 1         # DEV (dernier index valide)

        # Bornes absolues en fonction de l'unité Artisan
        if qmc.mode == 'F':
            abs_lo, abs_hi = 140, 482   # ≈ 60°C / 250°C en Fahrenheit
        else:
            abs_lo, abs_hi = 60, 250

        # Bornes relatives adaptatives
        if idx == first_editable:
            lo = abs_lo
            hi = phases[idx + 1] - 1 if idx + 1 < n else abs_hi
        elif idx == last_editable:
            lo = phases[idx - 1] + 1 if idx > 0 else abs_lo
            hi = abs_hi
        else:
            lo = phases[idx - 1] + 1 if idx > 0 else abs_lo
            hi = phases[idx + 1] - 1 if idx + 1 < n else abs_hi

        new_val = max(lo, min(hi, phases[idx] + step))
        if new_val == phases[idx]:
            return
        phases[idx] = new_val
        widget.update_subtitle(self._update_phase_subtitle(key))
        # Flash bordure 150 ms dans la couleur de la phase
        flash = (f"PhaseWidget {{ background: {self.theme['BG']}; border-radius: 10px;"
                 f" border: 2px solid {widget.phase_color}; }}")
        idle  = "PhaseWidget { background: transparent; border: none; }"
        widget.setStyleSheet(flash)
        QTimer.singleShot(150, lambda w=widget, s=idle: w.setStyleSheet(s))

    def _freeze_phases_at_drop(self) -> None:
        """Close the phase display at DROP: every block full, none of them running.

        Past DROP Artisan's timer counts the cooling, so nothing here may be
        recomputed from it any more.
        """
        self.current_phase = None
        for phase in self.phases.values():
            phase.set_progress(100)
            phase.set_active(False)

    def _milestone_marked(self, idx: int) -> bool:
        """True when milestone `idx` of qmc.timeindex carries a real mark.

        The unmarked sentinel differs by index, and by index only: CHARGE (0)
        uses -1 because 0 is a valid sample index, every milestone after it
        uses 0. Artisan reads it the same way (canvas.py markDryEnd/markDrop).
        Single reader, so the two conventions can never drift apart again.
        """
        try:
            timeindex = self.aw.qmc.timeindex
            return timeindex[0] > -1 if idx == 0 else timeindex[idx] > 0
        except (AttributeError, IndexError, TypeError):
            return False

    def _milestone_key_allowed(self, target: int, prerequisite: int) -> bool:
        """Whether an F-key may act on milestone `target`.

        Marking it needs `prerequisite` in place; undoing it needs its own mark
        — a mark the operator made must stay reachable to be taken back.
        """
        return self.is_roasting and (self._milestone_marked(prerequisite)
                                     or self._milestone_marked(target))

    def _phase_widgets(self) -> list:
        """The three phase blocks, in order."""
        return [w for w in (self.phase_box.itemAt(i).widget()
                            for i in range(self.phase_box.count())) if w is not None]

    # visual indication that a button event is triggered
    def mark_button_active(self, event:int, state:bool=False, disable_button:bool=False):
        """Visually disables a button when its event is triggered."""
        button_key,button_color = self.events[event]
        button_color_todim = toDim(self.artisan_conf.get_lightened_color(button_color))
        btn = self.event_buttons[button_key]
        btn.setEnabled(not disable_button)
        if btn:
            if disable_button:
                btn.setToolTip(QApplication.translate("tilauscope_window", "This event is already recorded"))
                btn.setStyleSheet(with_tooltip(f"""
                    QPushButton:disabled {{
                        background: {THEME['BORDER']};
                        color: {button_color};
                        border-radius: 8px;
                        border: 1px solid {THEME['SURFACE1']};
                        border-left: 5px solid {THEME['SURFACE2']};
                        font-size: 11px;
                        font-weight: bold;
                        text-align: left;
                        padding: 0 4px 0 9px;
                    }}
                """))
                return
            if not state: # button flat
                btn.setToolTip(QApplication.translate("tilauscope_window", "Click to cancel marking of this event"))
                btn.setStyleSheet(with_tooltip(f"""
                    QPushButton {{
                        background: {THEME['BORDER']};
                        color: {THEME['SURFACE2']};
                        border-radius: 8px;
                        border: 1px solid {THEME['SURFACE1']};
                        border-left: 5px solid {THEME['SURFACE2']};
                        font-size: 11px;
                        font-weight: bold;
                        text-align: left;
                        padding: 0 4px 0 9px;
                    }}
                    /* Bordure grise transparente au survol */
                    QPushButton:hover {{
                        background: {button_color_todim};
                        border: 1px solid rgba(148, 163, 184, 0.2);
                        border-left: 5px solid {button_color};
                    }}
                    /* Flash de couleur et effet d'enfoncement au clic */
                    QPushButton:pressed {{
                        background: {button_color};
                        color: {THEME['CRUST']};
                        padding-left: 18px;
                        padding-top: 2px;
                    }}
                """))
            else: # not flat button
                btn.setToolTip(QApplication.translate("tilauscope_window", "Click to mark this event"))
                btn.setStyleSheet(with_tooltip(f"""
                QPushButton {{
                    background: {THEME['BG']};
                    color: {THEME['TEXT']};
                    border-radius: 8px;
                    border: 1px solid transparent;
                    border-left: 5px solid {button_color};
                    font-size: 11px;
                    font-weight: bold;
                    text-align: left;
                    padding: 0 4px 0 9px;
                }}

                /* Bordure grise transparente au survol */
                QPushButton:hover {{
                    background: #28283D;
                    border: 1px solid rgba(148, 163, 184, 0.2);
                    border-left: 5px solid {button_color};
                }}

                /* Flash de couleur et effet d'enfoncement au clic */
                QPushButton:pressed {{
                    background: {button_color};
                    color: {THEME['CRUST']};
                    padding-left: 18px;
                    padding-top: 2px;
                }}
                """))

    def _handle_milestone_events(self, data, buttonState: bool):
        """Extracted helper for standard roast events to keep main func clean."""
        self.current_event = data
        # Use the last Artisan timer value we received — same source as data==10,
        # so phase_starts and total_secs are always in the same unit with no drift.
        artisan_secs = self.last_update_second if self.last_update_second >= 0 else 0

        if data == 0:  # CHARGE
            if buttonState:
                self.last_update_second = -1
                self.handle_preheat(False)
                self.start_roast(auto=True)
                self.set_phase("DRY", 0)
                self.mark_button_active(0)
                self.roast_bridge.notify_phase("DRY")
                if self.replay_enabled:
                    self._engage_replay()
            else:
                self.current_phase = None
                self.phase_starts = {"DRY": None, "MAI": None, "DEV": None}
                self.phases["DRY"].update_stats(0, 1)
                self.phases["MAI"].update_stats(0, 1)
                self.phases["DEV"].update_stats(0, 1)
                for p in self.phases.values():
                    p.set_active(False)
                self.handle_preheat(True)
                self.mark_button_active(0, state=True)
                self.roast_bridge.notify_phase("PREHEAT")
        elif data == 1:  # DRY END
            if buttonState:
                dry_elapsed = artisan_secs - (self.phase_starts["DRY"] or 0)
                self._set_phase_completed("DRY", dry_elapsed, "MAI", 1)
                self.phase_starts["MAI"] = artisan_secs
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, disable_button=False)
                self.roast_bridge.notify_phase("MAI")
            else:
                self.phase_starts["MAI"] = None
                self.phases["MAI"].update_stats(0, 1)
                self.phases["MAI"].set_active(False)
                self.set_phase("DRY", self.phase_starts["DRY"] or 0)
                self.mark_button_active(1, state=True)
                self.mark_button_active(0, state=True)
                self.roast_bridge.notify_phase("DRY")
        elif data == 2:  # FC START
            if buttonState:
                mai_elapsed = artisan_secs - (self.phase_starts["MAI"] or 0)
                self._set_phase_completed("MAI", mai_elapsed, "DEV", 2)
                self.phase_starts["DEV"] = artisan_secs
                self.roast_bridge.notify_phase("DEV")
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, disable_button=True)
                self.mark_button_active(2)
            else:
                self.phase_starts["DEV"] = None
                self.phases["DEV"].update_stats(0, 1)
                self.phases["DEV"].set_active(False)
                self.set_phase("MAI", self.phase_starts["MAI"] or 0)
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, state=True)
                self.mark_button_active(2, state=True)
                self.roast_bridge.notify_phase("MAI")
        elif data in (3, 4, 5):  # FC END, SC START, SC END
            self.mark_button_active(data, state=not buttonState)
        elif data == 6:  # DROP
            if buttonState:
                # Horodatage wall-clock du DROP : survit au RESET d'Artisan,
                # consommé par la correction heat-soak du prochain plan
                # (minutes_since_last_drop) et la reco d'attente back-to-back.
                self.aw._tilau_last_drop_wall = time.time()
                # Artisan restarts its timer at 00:00 for the cooling: the
                # development stats must be closed on the roast clock here, then
                # left alone — recomputing them against the cooling seconds would
                # subtract a roast-relative start from a 00:0x value.
                if self.phase_starts.get("DEV") is not None and artisan_secs > 0:
                    self.phases["DEV"].update_stats(artisan_secs - self.phase_starts["DEV"], max(artisan_secs, 1))
                self._freeze_phases_at_drop()
                for n in range(1, 7):
                    self.mark_button_active(n, disable_button=True)
                self.roast_bridge.notify_phase("COOL")
                self.roast_assistant.update_batch()   # rafraîchit le badge batch (DROP + UNDO DROP)
                self._arm_cooling_detection()   # arm even when DROP is marked from Artisan
            else:
                # keep the recorded DEV start: set_phase() defaults it to 0,
                # which would count the development from CHARGE after an undo.
                # _clear_cooling_face() disarms and puts the phase blocks back:
                # the DROPPING / COOLING message was painted over them.
                self._clear_cooling_face()   # DROP undone
                self.set_phase("DEV", self.phase_starts.get("DEV") or 0)
                self.mark_button_active(6, state=True)
                self.roast_bridge.notify_phase("DEV")
        elif data == 7:  # COOL END
            if buttonState:
                self._show_cooled_face()   # also when COOL END is marked in Artisan
                self.roast_bridge.notify_phase("COOL")
                self.mark_button_active(7)
                self._disarm_cooling_detection()
            else:
                # undoing COOL END puts the roast back in the cooling, not back
                # in development: the beans have been dropped either way
                self._drop_done = True
                self.handle_cooling()
                self.mark_button_active(7, state=True)
                self.mark_button_active(6)
                self.roast_bridge.notify_phase("COOL")

    def _set_phase_completed(self, phase_key, duration, next_phase, btn_idx):
        m, s = divmod(int(duration), 60)
        self.phases[phase_key].stats.setText(f"{m:02d}:{s:02d}")
        self.phases[phase_key].bar.setValue(100)
        self.set_phase(next_phase)
        self.mark_button_active(btn_idx)

    def refresh_phase_subtitles(self) -> None:
        """Re-read the phase temperatures into the three phase blocks.

        Called when Artisan's phases dialog changes them; it used to walk this
        window's widget dictionary and call a private method on each entry.
        """
        try:
            for key, widget in self.phases.items():
                widget.update_subtitle(self._update_phase_subtitle(key))
        except Exception:  # pylint: disable=broad-except
            _log.exception('refresh_phase_subtitles failed')

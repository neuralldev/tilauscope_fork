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

"""The heat cut: what it commands, and what the window shows while it is latched.

A slice of the roasting window. It is a mixin rather than a collaborator: the
window is one object with one set of attributes, and these methods read and
write it exactly as they did when they sat in the same file. What the split
buys is a boundary to read within, not a decoupling.
"""

from __future__ import annotations

import logging
from typing import Final

from tilauscope.header_icons import COL_DISABLED, COL_ESTOP, SVG_HEATCUT, apply_icon
from tilauscope.tilauscope_types import THEME


_log: Final[logging.Logger] = logging.getLogger(__name__)


class EmergencyMixin:
    """The heat cut: what it commands, and what the window shows while it is latched.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    def _refresh_emergency_visibility(self) -> None:
        """Show the heat cut only while something can be hot: monitoring on,
        or the cut already latched. Called from the state transitions, never
        from the sampling path."""
        try:
            btn = getattr(self, 'btn_estop', None)
            if btn is not None:
                btn.setVisible(bool(self.aw.qmc.flagon) or self._emergency_latched)
        except Exception:  # pylint: disable=broad-except
            pass

    def _emergency_slider_targets(self) -> list[tuple[int, int, str]]:
        """(slider, value, name) triples for the safe state, in the order they
        must be sent: burner to zero first, then airflow and extraction wide
        open. A slider with no action mapped commands no hardware, so it is
        reported back as manual instead of being moved for show.

        The drum is deliberately absent: stopping it scorches the beans against
        the hot wall, and its speed is a setup parameter, never a lever.
        """
        aw = self.aw
        out: list[tuple[int, int, str]] = []
        try:
            # Same resolver as the assistant and the preheat page. Imported
            # here to keep that module off this one's import cost: nothing in
            # the tree imports displayscope back, so there is no cycle.
            from tilauscope.roast_asssistant import _burner_slider_idx
            burner = _burner_slider_idx(aw)
        except Exception:  # pylint: disable=broad-except
            burner = 3
        # Extraction: identified by its action, not by an index — the AirWave
        # is mapped onto the damper slider only when one is configured.
        extraction = None
        for i in range(4):
            try:
                if int(aw.eventslideractions[i]) == 20:   # Difluid Airwave Command
                    extraction = i
            except Exception:  # pylint: disable=broad-except
                continue
        # Airflow is slider 0 everywhere else in the app — the guidance lever
        # map, the quick-adjust tiles, the assistant. It is a position, not a
        # label: reading it off the event name matched only an untranslated
        # 'Air'. What decides here is the machine, not the wording — a roaster
        # with no airflow control has nothing to open, and its slider 0 is
        # something else that must not be driven to maximum.
        ctx = getattr(aw, '_tilau_roast_context', None)
        air = 0 if (ctx is None
                    or bool(getattr(ctx, 'has_airflow_control', True))) else None

        def _add(idx: int | None, value: int, name: str) -> None:
            if idx is None:
                return
            try:
                out.append((idx, int(value), name))
            except Exception:  # pylint: disable=broad-except
                pass

        _add(burner, int(self.aw.eventslidermin[burner]), self.str_emergency_burner)
        if air is not None and air != extraction:
            _add(air, int(self.aw.eventslidermax[air]), self.str_emergency_air)
        if extraction is not None:
            _add(extraction, int(self.aw.eventslidermax[extraction]),
                 self.str_emergency_extraction)
        return out

    def _command_safe_state(self) -> tuple[list[str], list[str]]:
        """Send the safe setpoints. Returns (commanded, manual) lever names —
        manual holds whatever this machine exposes no command for, which the
        operator has to do by hand."""
        commanded: list[str] = []
        manual: list[str] = []
        signal = getattr(self.aw, 'tilaupidSliderCommandSignal', None)
        fire = getattr(self.aw, 'simulator', None) is None
        for idx, value, name in self._emergency_slider_targets():
            try:
                if not int(self.aw.eventslideractions[idx]):
                    manual.append(name)   # nothing mapped: moving it is theatre
                    continue
                if signal is not None:
                    # Same queued UI + hardware transaction the preheat PID uses
                    # for its own safe-off, so command order is preserved.
                    signal.emit(idx, value, fire)
                else:
                    self.aw.moveslider(idx, value)
                    if fire:
                        self.aw.fireslideraction(idx)
                commanded.append(name)
            except Exception:  # pylint: disable=broad-except
                _log.exception('emergency: safe command failed on slider %s', idx)
                manual.append(name)
        return commanded, manual

    def handle_emergency(self) -> None:
        """Emergency heat cut.

        Stops every automation that could re-apply heat, then commands burner
        zero with airflow and extraction wide open. Monitoring and recording
        keep running — this locks the automations, not the observation — and no
        DROP is marked: emptying the drum is a physical gesture, so the panel
        asks the operator for it instead of faking the event.
        """
        self._emergency_latched = True
        # is_roasting is deliberately left alone: the recording keeps running,
        # and clearing it here would desync the STOP path that reads it.
        self._stop_all_automation()
        commanded, manual = self._command_safe_state()
        self._show_emergency_state(commanded, manual)
        _log.warning('EMERGENCY heat cut — commanded: %s / manual: %s',
                     ', '.join(commanded) or '-', ', '.join(manual) or '-')

    def _show_emergency_state(self, commanded: list[str], manual: list[str]) -> None:
        """Paint the latched state: what the app just did, and the one gesture
        left to the operator."""
        try:
            self.update_button_style(self.btn_power, False, True)
            self._update_timer_style('emergency')
            apply_icon(self.btn_estop, SVG_HEATCUT, COL_DISABLED)
            self.btn_estop.setEnabled(False)
            self.btn_estop.show()

            done = ' · '.join(commanded) if commanded else self.str_emergency_nothing
            self.status_lbl.setText(f"{self.str_emergency_status} — {done}")
            self.status_lbl.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 11px; font-weight: 900;"
                " border: none; background: transparent;")

            for i in range(self.phase_box.count()):
                widget = self.phase_box.itemAt(i).widget()
                if widget:
                    widget.hide()
            gesture = (self.str_emergency_manual_burner if manual
                       else self.str_emergency_empty_drum)
            self.msg_lbl.setText(f"{self.str_emergency_title}\n{gesture}")
            self.msg_lbl.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 20px; font-weight: 900;"
                " border: none; min-height: 100px")
            self.msg_lbl.show()
            self.msg_lbl.raise_()
            self.phase_container.setStyleSheet(
                f"background: {THEME['CRUST']}; border-radius: 15px;"
                f" border: 2px solid {THEME['CRITICAL']};")
        except Exception:  # pylint: disable=broad-except
            # The machine is already safe at this point; a paint failure must
            # not surface as a crash on top of an emergency.
            _log.exception('emergency: painting the latched state failed')

    def _clear_emergency_state(self) -> None:
        """Release the latch and give the panel its normal look back."""
        if not self._emergency_latched:
            return
        self._emergency_latched = False
        try:
            apply_icon(self.btn_estop, SVG_HEATCUT, COL_ESTOP)
            self.btn_estop.setToolTip(self.str_emergency_tip)
            self.btn_estop.setEnabled(True)
            self.msg_lbl.hide()
            self.msg_lbl.setStyleSheet(
                f"color: {THEME['TEAL']}; font-size: 16px; font-weight: 800; border: none")
            for i in range(self.phase_box.count()):
                widget = self.phase_box.itemAt(i).widget()
                if widget:
                    widget.show()
            self.phase_container.setStyleSheet(
                f"background: {THEME['CRUST']}; border-radius: 15px; border: none;")
            self.status_lbl.setStyleSheet('')
            self._update_timer_style('idle')
        except Exception:  # pylint: disable=broad-except
            _log.exception('emergency: clearing the latched state failed')
        self._refresh_emergency_visibility()

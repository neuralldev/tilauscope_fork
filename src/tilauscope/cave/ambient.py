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

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import

#import matplotlib.pyplot as plt




from PyQt6.QtCore import pyqtSlot # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QMessageBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (show_styled_message,
                                         THEME)
from tilauscope.cave.common import (
    _log, _logd)
from tilauscope.cave.widgets import (
    _DensityFloatWindow)


class AmbientMixin:
    """The measured surroundings: the ambient probe, the water-activity gauge
    and the density scale.

    Separate instruments, grouped because each is a reading that arrives from
    outside. The ambient probe is held here for the roast setup sheet, which
    reads it.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    def setup_storage_tab_ui(self) -> None:
        """Build the Stockage (conservation) tab in its own module."""
        from tilauscope.beancave_storage_tab import StorageTab
        layout = QVBoxLayout(self.storage_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        self.storage_tab_widget = StorageTab(self)
        layout.addWidget(self.storage_tab_widget)

    @pyqtSlot(int)
    def _on_beancave_tab_changed(self, index: int) -> None:
        """Start/stop the Storage tab's ambient polling with its visibility."""
        if getattr(self, 'tab_widget', None) is None:
            return
        current = self.tab_widget.widget(index)
        st = getattr(self, 'storage_tab_widget', None)
        if st is not None:
            if current is getattr(self, 'storage_tab', None):
                st.on_shown()
            else:
                st.on_hidden()

    # ── Density measurement window ─────────────────────────────────────────
    @pyqtSlot()
    def _open_density_window(self) -> None:
        """Toggle the scale-piloted density measurement window (show / hide)."""
        if self._density_window is not None and self._density_window.isVisible():
            self._density_window.hide()
            return
        sm = getattr(self.aw, "scale_manager", None)
        if sm is None or not sm.is_scale1_configured():
            show_styled_message(
                self,
                QApplication.translate("tilauscope_common", "No scale configured"),
                QApplication.translate("tilauscope_beancave",
                    "Pair your scale in TilauScope Config › Sensors to measure density."),
                QMessageBox.Icon.Information,
            )
            return
        if self._density_window is None:
            self._density_window = _DensityFloatWindow(self)
            self._density_window.density_picked.connect(self._receive_density)
            self._density_window.tare_requested.connect(self._on_density_tare)
            self._connect_density_scale()
        geo = self.geometry()
        self._density_window.move(geo.right() + 12, geo.top() + 80)
        self._density_window.show()
        self._density_window.raise_()

    def _connect_density_scale(self) -> None:
        try:
            sm = self.aw.scale_manager
            self._density_scale_was_connected = sm.is_scale1_connected()
            sm.scale1_weight_changed_signal.connect(self._density_window.update_weight)
            sm.scale1_stable_weight_changed_signal.connect(self._density_window.update_weight)
            sm.scale1_disconnected_signal.connect(self._density_window.scale_disconnected)
            if not self._density_scale_was_connected:
                sm.connect_scale1_signal.emit(False)
            else:
                last = sm.get_scale1_last_weight()
                if last is not None:
                    self._density_window.update_weight(last)
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            _log.warning("Density scale not available: %s", exc)

    def _disconnect_density_scale(self) -> None:
        sm = getattr(self.aw, "scale_manager", None)
        if sm is None or not sm.is_scale1_configured() or self._density_window is None:
            return
        for _sig, _slot in (
            (sm.scale1_weight_changed_signal,        self._density_window.update_weight),
            (sm.scale1_stable_weight_changed_signal, self._density_window.update_weight),
            (sm.scale1_disconnected_signal,          self._density_window.scale_disconnected),
        ):
            try:
                _sig.disconnect(_slot)
            except (TypeError, RuntimeError):
                pass
        try:
            if not self._density_scale_was_connected:
                sm.disconnect_scale1_signal.emit()
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            _log.error(exc)

    @pyqtSlot()
    def _on_density_tare(self) -> None:
        try:
            self.aw.scale_manager.tare_scale1_signal.emit()
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            _log.error("Density tare failed: %s", exc)

    @pyqtSlot(float)
    def _receive_density(self, density: float) -> None:
        """Transfer the measured density (g/l) into the density field."""
        value = round(density)
        current = self.density_input.value()
        if current <= 0.0:
            self.density_input.setValue(value)
            return
        reply = show_styled_message(
            self,
            QApplication.translate("tilauscope_beancave", "Replace Density?"),
            QApplication.translate("tilauscope_beancave",
                "Current density is <b>{0} g/l</b>.<br>Replace with measured <b>{1} g/l</b>?"
            ).format(int(current), value),
            QMessageBox.Icon.Question,
            rich=True,
            width=400,
            buttons=[QApplication.translate("tilauscope_beancave", "Replace"),
                     QApplication.translate("Button", "Cancel")],
        )
        if reply == 0:   # the index of the button pressed, -1 when closed
            self.density_input.setValue(value)

    def _set_wa_label_state(self, connected: bool) -> None:
        # Reapply the FULL label stylesheet (must mirror the one set at
        # creation): a bare "color: ..." rule would drop font-size/background/
        # border/padding. Only the text color toggles between connected (theme
        # green) and idle (default subtext). unpolish/polish forces Qt to
        # re-evaluate the stylesheet so the repaint actually happens.
        _color = THEME['SUCCESS'] if connected else THEME['SUBTEXT']
        self.water_activity_label.setStyleSheet(
            f"color:{_color};font-size:11px;background:transparent;border:none;padding:0;")
        _style = self.water_activity_label.style()
        if _style is not None:
            _style.unpolish(self.water_activity_label)
            _style.polish(self.water_activity_label)
        self.water_activity_label.update()

    @pyqtSlot()
    def slotStartLebrewAG(self):
        if self.bleRoastSeeAGDevice is not None :
            _logd.debug("lebrew Roastsee AG is connected")
            self.bleRoastSeeAGDevice.is_connected = True
            self._set_wa_label_state(True)

    @pyqtSlot()
    def slotStopLebrewAG(self):
        if self.bleRoastSeeAGDevice is not None :
            _logd.debug("lebrew Roastsee AG is disconnected")
            self.bleRoastSeeAGDevice.is_connected = False
            self._set_wa_label_state(False)


    @pyqtSlot()
    def stopLebrewAGmanager(self) -> None:
        device = self.bleRoastSeeAGDevice
        if device is None:
            return
        # LebrewWaterActivityChecker owns a ClientBLE and exposes stop().
        # QObject.disconnect() only disconnects Qt signal connections; it does
        # not stop the BLE runner and is not the lifecycle API for this object.
        self.bleRoastSeeAGDevice = None
        try:
            device.stop()
        except Exception as exc:  # noqa: BLE001
            _log.error("Lebrew AquaGauge cleanup failed: %s", exc, exc_info=True)
        else:
            _logd.debug('lebrew ag manager stopped')

    # ── TilauAmbient probe (same managed pattern as Lebrew above) ─────────────
    @pyqtSlot()
    def slotStartTilauAmbient(self) -> None:
        if self.bleTilauAmbientDevice is not None:
            _logd.debug("TilauAmbient probe connected")
            self.bleTilauAmbientDevice.is_connected = True

    @pyqtSlot()
    def slotStopTilauAmbient(self) -> None:
        if self.bleTilauAmbientDevice is not None:
            _logd.debug("TilauAmbient probe disconnected")
            self.bleTilauAmbientDevice.is_connected = False

    @pyqtSlot()
    def stopTilauAmbientManager(self) -> None:
        # Teardown is unconditional: an adapter switched off mid-session must not
        # leave the probe connected and its transport unjoined.
        if self.bleTilauAmbientDevice is not None:
            try:
                self.bleTilauAmbientDevice.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.bleTilauAmbientDevice = None
        _logd.debug('tilau ambient manager stopped')

    @pyqtSlot(float)
    def on_read_water_activity(self, wa:float):
        """
        Called by signal from background task.
        """
        # Update the text with the current value
        self.aw_overlay.update_value(wa)
        # Lot 5: forward the reading to an open Characteristics
        # editor (💧 annex window) — registered/cleared by ZoneEditorDialog.
        # That reading is for the editor's bean, not the one in the main form.
        _aw_cb = getattr(self, '_aw_capture_cb', None)
        if _aw_cb is None:
            self.water_activity_input.setValue(wa) # inject the value directly without triggering the button click event again
        else:
            try:
                _aw_cb(wa)
            except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                _logd.debug(f"aw capture forward skipped: {e}")

        # Show if not already visible
        if not self.aw_overlay.isVisible():
            # Position it bottom-right of the main window
            geo = self.geometry()
            self.aw_overlay.move(geo.x() + geo.width() - self.aw_overlay.width() - 20,
                                geo.y() + geo.height() - self.aw_overlay.height() - 20)
            self.aw_overlay.show()

        # Restart the timer for 2000ms.
        # If this function is called again before 2s, the previous timer is canceled.
        self.aw_hide_timer.start(2000)
        if self.bleRoastSeeAGDevice is None:
            return

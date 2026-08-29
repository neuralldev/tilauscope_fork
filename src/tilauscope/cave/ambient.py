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
import requests

#import matplotlib.pyplot as plt




from PyQt6.QtCore import (pyqtSlot) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QMessageBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (show_styled_message,
                                         THEME)
from tilauscope.cave.common import (
    _log, _logd)
from tilauscope.cave.widgets import (
    _DensityFloatWindow)


class AmbientMixin:
    """The measured surroundings: the ambient probe, the weather fallback, the
    water-activity gauge and the density scale.

    Four separate instruments, grouped because each is a reading that arrives
    from outside and lands in the bean record.

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
        """Keep the probe button state fresh when the plan tab opens."""
        if getattr(self, 'tab_widget', None) is None:
            return
        current = self.tab_widget.widget(index)
        if current is getattr(self, 'roast_plan_tab', None):
            self._refresh_tilauambient_btn()
        # start/stop the Stockage tab's ambient polling with visibility
        st = getattr(self, 'storage_tab_widget', None)
        if st is not None:
            if current is getattr(self, 'storage_tab', None):
                st.on_shown()
            else:
                st.on_hidden()

    def _refresh_tilauambient_btn(self) -> None:
        """Couple the two ambient sources to probe detection:
        probe connected → probe button ON / weather button OFF; no probe → the
        opposite. Both react together because every connect/disconnect/tab-open
        path funnels through here."""
        btn = getattr(self, 'tilauambient_btn', None)
        if btn is None:
            return
        dev = getattr(self, 'bleTilauAmbientDevice', None)
        active = dev is not None and getattr(dev, 'is_connected', False)

        # Probe button — enabled only when the probe is connected.
        btn.setEnabled(active)
        btn.setToolTip(
            QApplication.translate("tilauscope_beancave",
                "Read temperature, humidity and pressure from the connected TilauAmbient probe.")
            if active else
            QApplication.translate("tilauscope_beancave",
                "TilauAmbient probe not detected. Connect it in the device settings first."))

        # Weather button — the mutually-exclusive fallback: disabled while the
        # probe is the live source, enabled when no probe is detected.
        wbtn = getattr(self, 'weather_btn', None)
        if wbtn is not None:
            wbtn.setEnabled(not active)
            wbtn.setToolTip(
                QApplication.translate("tilauscope_beancave",
                    "The TilauAmbient probe is connected and used as the ambient source.")
                if active else
                QApplication.translate("tilauscope_beancave",
                    "Fill temperature, humidity, pressure and altitude from the online weather for your location."))

    @pyqtSlot()
    def _get_tilauambient_conditions(self) -> None:
        """Fill the ambient fields from the live TilauAmbient probe."""
        dev = getattr(self, 'bleTilauAmbientDevice', None)
        if dev is None or not getattr(dev, 'is_connected', False):
            self._refresh_tilauambient_btn()
            return
        try:
            data = dev.get_ambient("AMBIENT")
        except Exception as e:  # noqa: BLE001
            _logd.warning(f"_get_tilauambient_conditions: read failed: {e}")
            data = None
        if data is None or not getattr(data, 'valid', False):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "TilauAmbient probe"),
                QApplication.translate("tilauscope_beancave", "No valid reading from the TilauAmbient probe. Please try again."),
                QMessageBox.Icon.Warning)
            return
        # Temperature honours the display unit (probe reports °C).
        if "Ambient Temperature" in self.roast_plan_inputs:
            val = data.temperature if self.aw.qmc.mode == "C" else (data.temperature * 9 / 5) + 32
            self.roast_plan_inputs["Ambient Temperature"].setValue(float(val))
        if "Atmospheric Pressure" in self.roast_plan_inputs:
            self.roast_plan_inputs["Atmospheric Pressure"].setValue(float(data.pressure))
        self._check_plan_inputs()

    @pyqtSlot()
    def _get_weather_conditions(self):
        """
        Gathers current location weather conditions and injects them into
        the roast plan input fields. Works on Windows and Mac.
        """
        # The lookup turns the operator's IP address into a town, which means
        # handing that address to a third party. Asked once, remembered on yes.
        from tilauscope.tilau_privacy_ui import (  # noqa: PLC0415
            ensure_geo_consent, hand_over_to_manual_entry,
        )
        if not ensure_geo_consent(self):
            # "I'll type it" is the other way of filling the same three fields.
            hand_over_to_manual_entry(
                self.roast_plan_inputs.get("Ambient Temperature"))
            return

        try:
            # 1. Geolocation via IP (Cross-platform)
            geo_res = requests.get("http://ip-api.com/json/", timeout=5)
            geo_res.raise_for_status()
            geo_data = geo_res.json()

            lat = geo_data.get("lat")
            lon = geo_data.get("lon")
            city = geo_data.get("city", "Unknown")

            if lat is None or lon is None:
                raise ValueError(QApplication.translate("tilauscope_beancave", "Could not detect location."))

            # 2. Weather Data (Fixed Open-Meteo URL)
            # We use lowercase 'true' for elevation and ensure params are standard
            weather_url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,surface_pressure",
                "elevation": "nan", # Using 'nan' or omitting usually returns elevation in header/body
            }

            # Re-attempting with the specific structure Open-Meteo prefers
            w_res = requests.get(weather_url, params=params, timeout=5)
            w_res.raise_for_status()
            w_data = w_res.json()

            current = w_data.get("current", {})
            temp_c = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            pressure = current.get("surface_pressure")
            elevation = w_data.get("elevation")

            # 3. Injection into UI Fields
            # Temp Handling (Convert to F if Artisan is in Fahrenheit)
            if "Ambient Temperature" in self.roast_plan_inputs and temp_c is not None:
                val = temp_c if self.aw.qmc.mode == "C" else (temp_c * 9/5) + 32
                self.roast_plan_inputs["Ambient Temperature"].setValue(val)

            if "Atmospheric Pressure" in self.roast_plan_inputs and pressure is not None:
                self.roast_plan_inputs["Atmospheric Pressure"].setValue(float(pressure))

            if "Altitude" in self.roast_plan_inputs and elevation is not None:
                self.roast_plan_inputs["Altitude"].setValue(float(elevation))

            _logd.debug(f"Weather updated for {city}: {temp_c}°C, {humidity}%, {pressure}hPa")

        except Exception as e:
            _logd.error(f"Weather Fetch Error: {e}")
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Weather Error"), QApplication.translate("tilauscope_beancave", "Failed to retrieve weather data: ")+f"{e}", QMessageBox.Icon.Warning)

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
                QApplication.translate("tilauscope_beancave", "No scale configured"),
                QApplication.translate("tilauscope_beancave",
                    "Configure scale 1 in Artisan to measure density."),
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
        )
        if reply == QMessageBox.StandardButton.Ok:
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
            self._refresh_tilauambient_btn()

    @pyqtSlot()
    def slotStopTilauAmbient(self) -> None:
        if self.bleTilauAmbientDevice is not None:
            _logd.debug("TilauAmbient probe disconnected")
            self.bleTilauAmbientDevice.is_connected = False
            self._refresh_tilauambient_btn()

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
        self.water_activity_input.setValue(wa) # inject the value directly without triggering the button click event again
        # Lot 5: forward the reading to an open Characteristics
        # editor (💧 annex window) — registered/cleared by ZoneEditorDialog.
        _aw_cb = getattr(self, '_aw_capture_cb', None)
        if _aw_cb is not None:
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

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
import re # For sorting alog files
from pathlib import Path

#import matplotlib.pyplot as plt


from artisanlib.widgets import MyQDoubleSpinBox


from PyQt6.QtCore import (Qt, pyqtSlot, QSettings) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtWidgets import (QApplication, QComboBox, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,  # @UnusedImport @Reimport  @UnresolvedImport
                                QPushButton, QWidget, QGridLayout, QGroupBox, QStyledItemDelegate, QListView, QFrame, QCheckBox, QMessageBox, QDoubleSpinBox) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import (AGTRON_SCALES, AgtronScale, THEME, ProbeDeviation, ProbeDeviationInterval)
from tilauscope.roasters import RoasterContext
from tilauscope.cave.common import (
    _log, _logd)


class PlanTabMixin:
    """The Roast plan tab: choosing a bean and a past roast, then producing a plan.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    # ── Roast Plan tab — independent bean / roast selectors ──────────────────────

    def _populate_roaster_list(self) -> None:
        _log.info("populate roasters")
        if not hasattr(self, 'roaster_combo') or self.roaster_manager is None:
            return
        self.roaster_combo.blockSignals(True)
        self.roaster_combo.clear()
        self.roaster_combo.addItems(self.roaster_manager.get_display_names())
        index = self.roaster_combo.findText(self.current_roaster_model)
        if index >= 0:
            self.roaster_combo.setCurrentIndex(index)
        self.roaster_combo.blockSignals(False)

    def _populate_plan_bean_combo(self) -> None:
        _log.info("populate plan beans")
        """Sync plan_bean_combo with the current cave contents. Preserves selection."""
        if not hasattr(self, 'plan_bean_combo'):
            return
        prev = self.plan_bean_combo.currentIndex()
        self.plan_bean_combo.blockSignals(True)
        self.plan_bean_combo.clear()
        if self.cave and self.cave.green_beans:
            for b in self.cave.green_beans:
                crop = str(b.crop) if b.crop else "–"
                self.plan_bean_combo.addItem(f"{b.name}  ({b.country} · {b.process} · {crop})", userData={"uuid":b.uuid, "name":b.name})
        self.plan_bean_combo.blockSignals(False)
        # restore index if still valid
        target = prev if 0 <= prev < self.plan_bean_combo.count() else 0
        self.plan_bean_combo.setCurrentIndex(target)
        self._on_plan_bean_changed(self.plan_bean_combo.currentIndex())

    def _populate_plan_roast_combo(self) -> None:
        if not hasattr(self, 'plan_roast_combo'):
            return
        self.plan_roast_combo.blockSignals(True)
        self.plan_roast_combo.clear()

        search_for_item = self.plan_bean_combo.currentIndex()
        data = self.plan_bean_combo.itemData(search_for_item)
        current_uuid = data["uuid"]
        #search for matching alogs
        found = False
        for record in self._metadata_cache.records.values():
            if record.uuid==current_uuid:
                found = True
                self.plan_roast_combo.addItem(
                    self.formater_nom_fichier_cafe(record.filename),
                    userData={"uuid" : record.uuid, "filename": record.filename})

        if not found:
            self.plan_roast_combo.addItem(QApplication.translate("tilauscope_beancave", "— no roasts found for this bean —"))

        self.plan_roast_combo.blockSignals(False)

    @pyqtSlot(int)
    def _on_plan_bean_changed(self, index: int) -> None:
        """Called when the user picks a bean in the Roast Plan tab."""
        if not self.initialized or not hasattr(self, 'status_label'):
            return
        if self.cave is None or index < 0 or index >= len(self.cave.green_beans):
            self.status_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Status: please select a green bean above."))
            self.status_label.setStyleSheet("color: orange;")
            if self.input_group:
                self.input_group.setEnabled(False)
            # Still refresh the roast combo to show "select a bean first"
            self._populate_plan_roast_combo()
            return
        bean = self.cave.green_beans[index]
        self.current_bean_name = bean.name
        self.status_label.setText(
            QApplication.translate("tilauscope_beancave", "Status: Generating plan for") +
            f" '{bean.name}'.")
        self.status_label.setStyleSheet(f"color: {THEME['ACCENT']};")
        if self.input_group:
            self.input_group.setEnabled(True)
        # Mirror selection in the main-tab datatable (cosmetic only, non-blocking)
        if self.datatable.rowCount() > index:
            self.datatable.blockSignals(True)
            self.datatable.selectRow(index)
            self.datatable.blockSignals(False)
        # Refresh the roast combo to show only this bean's roasts
        self._populate_plan_roast_combo()
        self._check_plan_inputs()

    @pyqtSlot(int)
    def _on_plan_roast_changed(self, index: int) -> None:
        """Called when the user picks a reference roast in the Roast Plan tab.
        index 0 = 'none' header; actual files start at 1.
        Uses _plan_roast_filemap to resolve combo position → real filename."""

        current_record = self.plan_roast_combo.currentData()
        if current_record is None:
            return

        filepath = Path(self.alog_directory) / current_record["filename"]
        try:
            data = self.get_alog_data(filepath)
            if data is None:
                return
            self.lastprofiledata = data
            self._update_roast_plan_values()
        except Exception as e:
            _logd.warning(f"_on_plan_roast_changed: could not load {filepath}: {e}")

    @pyqtSlot()
    def _update_roast_plan_ui_state(self):
        """Checks if a bean is selected and enables/disables the roast plan UI."""

        if not self.initialized:
            return
        selected_rows = self.datatable.selectionModel().selectedRows()
        if not selected_rows or len(selected_rows) < 1:
            return
        row = selected_rows[0].row()
        if self.cave is None:
            return
        # Keep the plan combo in sync when the user selects via the main table
        if hasattr(self, 'plan_bean_combo') and 0 <= row < self.plan_bean_combo.count():
            self.plan_bean_combo.blockSignals(True)
            self.plan_bean_combo.setCurrentIndex(row)
            self.plan_bean_combo.blockSignals(False)
        # delegate to the plan-tab handler for UI state
        self._on_plan_bean_changed(row)

    def _update_roast_plan_values(self):
        def get_theoretical_pressure(altitude_m: float) -> float:
            """ Calcule la pression atmosphérique standard en hPa pour une altitude donnée. """
            P0 = 1013.25  # hPa au niveau de la mer
            T0 = 288.15   # 15°C en Kelvin
            L = 0.0065    # Taux de baisse de température par mètre
            exponent = 5.255 # Résultat de (g*M)/(R*L)

            pressure = P0 * (1 - (L * altitude_m) / T0) ** exponent
            return round(pressure, 2)

        if not self.roast_plan_inputs :
            return
        if not self.lastprofiledata :
            return
        computed = self.lastprofiledata.get("computed", {})
        profile_roast_temperature = computed.get("ambient_temperature", 0.0)
        profile_roast_pressure    = computed.get("ambient_pressure", get_theoretical_pressure(self.aw.qmc.elevation if not None else 0.0))
        profile_roast_altitude    = self.aw.qmc.elevation
        profile_roast_weight      = computed.get("weightin",0.0)

        self.roast_plan_inputs["Ambient Temperature"].setValue(profile_roast_temperature)
        self.roast_plan_inputs["Atmospheric Pressure"].setValue(profile_roast_pressure)
        self.roast_plan_inputs["Altitude"].setValue(profile_roast_altitude)
        self.roast_plan_inputs["Batch Weight"].setValue(profile_roast_weight)

    @pyqtSlot()
    def _check_plan_inputs(self):
        """Checks if all required double spin boxes have non-zero values."""
        self._update_plan_stepper()   # keep the header in sync
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        if self.generate_plan_btn is None or self.input_group is None:
            return

        if not self.input_group.isEnabled():
            self.generate_plan_btn.setEnabled(False)
            self.injectinartisan_btn.setEnabled(False) #type:ignore
            return

        all_filled = True
        for input_box in self.roast_plan_inputs.values():
            if input_box.value() == 0.0:
                all_filled = False
                break

        self.generate_plan_btn.setEnabled(all_filled)
        self.injectinartisan_btn.setEnabled(False) #type:ignore

    @pyqtSlot()
    def _inject_roast_plan(self):
        if not hasattr(self, "last_roast_plan_generated"):
            return
        from tilauscope.roast_plan_model import InjectRoastPlanToArtisan
        plan = InjectRoastPlanToArtisan(self.last_roast_plan_generated, mode=self.aw.qmc.mode)
        plan.inject()
        self._show_message(self, QApplication.translate("tilauscope_beancave","Injection in Artisan"), QApplication.translate("tilauscope_beancave","The base of the roasting plan, phases and alarms have been injected into Artisan. Get ready to roast!"), QMessageBox.Icon.Information)
        return

    @pyqtSlot()
    def reset_settings(self) -> None:
        """Resets the roast plan deviation settings to default values on the GUI."""
        if not self.initialized:
            return

        for key, (start_input, end_input) in self.dev_inputs.items():
            default_start = -8.0
            default_end = -10.0
            start_input.setValue(default_start)
            end_input.setValue(default_end)

    @pyqtSlot()
    def _generate_roast_plan_profile(self):
        """Generates a simple text file with the collected roast plan data."""
        if self.cave is None:
            return
        roaster_name = self.roaster_combo.currentText()
        roast_context:RoasterContext = self.roaster_manager.get_roast_context(roaster_name)
        bt_deviation = ProbeDeviation(
            probe_id="BT_Main",
            bt_at_charge=ProbeDeviationInterval(
                start_min=self.dev_inputs["bt_at_charge"][0].value() if self.probe_override else roast_context.bt_offsets[0],
                end_min=self.dev_inputs["bt_at_charge"][1].value() if self.probe_override else roast_context.bt_offsets[0]
            ),
            bt_at_de=ProbeDeviationInterval(
                start_min=self.dev_inputs["bt_at_de"][0].value() if self.probe_override else roast_context.bt_offsets[1],
                end_min=self.dev_inputs["bt_at_de"][1].value() if self.probe_override else roast_context.bt_offsets[1]
            ),
            bt_at_fc=ProbeDeviationInterval(
                start_min=self.dev_inputs["bt_at_fc"][0].value() if self.probe_override else roast_context.bt_offsets[2],
                end_min=self.dev_inputs["bt_at_fc"][1].value() if self.probe_override else roast_context.bt_offsets[2]
            ),
            bt_at_drop=ProbeDeviationInterval(
                start_min=self.dev_inputs["bt_at_drop"][0].value() if self.probe_override else roast_context.bt_offsets[3],
                end_min=self.dev_inputs["bt_at_drop"][1].value() if self.probe_override else roast_context.bt_offsets[3]
            )
        )

        # Collect data
        target_roast = AGTRON_SCALES[7-self.roast_level_combo.currentIndex()]
        ## Ambient humidity is no longer a plan input (it does not act on the
        ## roast in progress) but stays on the record for the storage advice.
        _ambient_humidity_pct = float(getattr(self.aw.qmc, "ambient_humidity", 0.0) or 0.0)

        data = {
            "Target Roast Level": target_roast.name,
            f"Ambient Temperature (°{self.aw.qmc.mode})": self.roast_plan_inputs.get("Ambient Temperature").value(), #type:ignore
            ## Still RECORDED (it matters for storage), just no longer entered by
            ## hand: read the live ambient probe rather than a field.
            "Ambient Humidity (%)": _ambient_humidity_pct,
            "Atmospheric Pressure (hPa)": self.roast_plan_inputs.get("Atmospheric Pressure").value(), #type:ignore
            "Altitude (m)": self.roast_plan_inputs.get("Altitude").value(), #type:ignore
            "Batch Weight (g)": self.roast_plan_inputs.get("Batch Weight").value(), #type:ignore
        }

        row = self.plan_bean_combo.currentIndex()
        if row < 0 or row >= len(self.cave.green_beans):
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave",
                    "Please select a green bean in the selection bar above."),
                QMessageBox.Icon.Warning)
            return
        bean = self.cave.green_beans[row]
        plan_content = f"--- Roast Plan for: {bean.name} ---\n"
        self.current_bean_name = bean.name

        for key, value in data.items():
            plan_content += f"{key}: {value}\n"

        plan_content += "\n--- Roast Plan detail ---\n"

        try:
            from tilauscope.roast_plan_model import TilauScopeRoastPlan
            roast_plan = TilauScopeRoastPlan(self.aw, roaster_ctx=roast_context)
            precog, graph_data , crashes, flicks= roast_plan.generate_roast_plan(bean, target_roast,self.roast_plan_inputs.get("Ambient Temperature").value(), _ambient_humidity_pct,self.roast_plan_inputs.get("Batch Weight").value(),self.roast_plan_inputs.get("Altitude").value(), bt_deviation=bt_deviation) #type:ignore
            for key, value in precog.items():
                plan_content += f"{key}: {value}\n"
            _logd.debug(plan_content)   # plan summary now goes to the log (on-screen text zone removed)
            self.last_roast_plan_generated = data | precog
            if self.save_roast_pdf(self.last_roast_plan_generated, target_roast, graph_data, crashes, flicks, roaster_ctx=roast_context):
                self.injectinartisan_btn.setEnabled(True) #type:ignore
                self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "Roast plan"),
                    QApplication.translate("tilauscope_beancave", "Your roast plan is ready !"))
        except Exception as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Could not generate roast plan file: ") + str(e),
                QMessageBox.Icon.Critical)

    def save_roast_pdf(self, plan_data:dict, target_agtron: AgtronScale, graph_data:dict, crashes:list, flicks:list, roaster_ctx=None):
        bean_name = plan_data.get('Bean Name', 'roast_plan').replace(' ', '_').replace('/', '-')
        initialPath = f"Roast_Plan_{bean_name}_{target_agtron.name}_{target_agtron.agtron_range.min_value}-{target_agtron.agtron_range.max_value}Ag.pdf"

        from PyQt6.QtCore import QStandardPaths

        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )

        default_path = str(Path(downloads_dir) / initialPath)

        fileName = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave",'Save profile to PDF'),
            default_path,
            QApplication.translate("tilauscope_beancave", "PDF Files (*.pdf);;All Files (*)")
        )

        if fileName:
            try:
                from tilauscope.roast_plan_model import BuildPRoastPlanPDF, TilauscopeAlarmFactory
                pdf = BuildPRoastPlanPDF(orientation='P', unit='mm', format='A4',temp_unit=self.aw.qmc.mode, roaster_ctx=roaster_ctx)
                pdf.create_pdf_report(plan_data, graph_data, crashes, flicks)
                pdf.output(fileName)
                _logd.debug(f"\nPlan saved successfully to: {fileName}")
                alarm_factory = TilauscopeAlarmFactory(plan_data)
                # replace .pdf by .alrm in filename
                aset_filename = re.sub(r'\.pdf$', '.alrm', fileName, flags=re.IGNORECASE)
                alarm_factory.export(aset_filename)
                self.try_to_open_file(fileName)
                return True
            except Exception as e:
                _logd.debug(f"\nError saving PDF file. {e}")
                return False
            # now generate aset of alarms

        return False

    # ── Roasting-plan batch preferences, remembered across sessions ──────────
    # The roast level is stored by SCALE NAME, never by combo index: the combo is
    # built from reversed(AGTRON_SCALES), so an index means nothing on its own and
    # would silently point at a different roast level if that list ever changes.
    _PLAN_PREF_WEIGHT: str = 'tilauscope/plan_last_batch_weight'
    _PLAN_PREF_LEVEL: str  = 'tilauscope/plan_last_roast_level'

    def _restore_plan_batch_prefs(self) -> None:
        """Reload the last batch weight and roast level, then start saving them.

        Never raises: an unreadable preference simply leaves the field on its
        built-in default, which is the pre-existing behaviour.
        """
        try:
            settings = QSettings()
            weight = settings.value(self._PLAN_PREF_WEIGHT, 0.0, type=float)
            spin = self.roast_plan_inputs.get("Batch Weight")
            if spin is not None and weight > 0.0:
                spin.setValue(min(weight, spin.maximum()))

            level_name = settings.value(self._PLAN_PREF_LEVEL, '', type=str)
            if level_name:
                names = [a.name for a in AGTRON_SCALES]
                if level_name in names:
                    # combo is reversed(AGTRON_SCALES) — mirror the position
                    idx = len(names) - 1 - names.index(level_name)
                    if 0 <= idx < self.roast_level_combo.count():
                        self.roast_level_combo.setCurrentIndex(idx)
        except Exception as e:
            _logd.debug(f"_restore_plan_batch_prefs: {e}")

        try:
            spin = self.roast_plan_inputs.get("Batch Weight")
            if spin is not None:
                spin.valueChanged.connect(self._save_plan_batch_prefs)
            self.roast_level_combo.currentIndexChanged.connect(self._save_plan_batch_prefs)
        except Exception as e:
            _logd.debug(f"_restore_plan_batch_prefs (connect): {e}")

    def _save_plan_batch_prefs(self) -> None:
        """Persist the current batch weight and roast level."""
        try:
            settings = QSettings()
            spin = self.roast_plan_inputs.get("Batch Weight")
            if spin is not None:
                settings.setValue(self._PLAN_PREF_WEIGHT, float(spin.value()))
            idx = self.roast_level_combo.currentIndex()
            if 0 <= idx < len(AGTRON_SCALES):
                # mirror of the reversed() build order used by the combo
                settings.setValue(self._PLAN_PREF_LEVEL,
                                  AGTRON_SCALES[len(AGTRON_SCALES) - 1 - idx].name)
        except Exception as e:
            _logd.debug(f"_save_plan_batch_prefs: {e}")

    def setup_roast_plan_tab_ui(self) -> None:
        """Creates and returns the Roast Plan tab UI with a 3-column layout."""
        tab_widget = QWidget()
        main_layout = QVBoxLayout(tab_widget)
        main_layout.setSpacing(6)

        # ── Selection bar (decoupled from the other tabs) ─────────────────────────
        sel_frame = QFrame()
        sel_frame.setObjectName("PlanSelBar")
        sel_frame.setStyleSheet(f"""
            #PlanSelBar {{
                background: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
            }}
        """)
        sel_layout = QHBoxLayout(sel_frame)
        sel_layout.setContentsMargins(12, 8, 12, 8)
        sel_layout.setSpacing(16)

        # Bean selector
        bean_lbl = QLabel("🫘 " + QApplication.translate("tilauscope_beancave", "Green bean:"))
        bean_lbl.setStyleSheet(f"color:{THEME['TEXT']}; font-size:12px;")
        self.plan_bean_combo = QComboBox()
        self.plan_bean_combo.setMinimumWidth(260)
        self.plan_bean_combo.setItemDelegate(QStyledItemDelegate())
        self.plan_bean_combo.setView(QListView())
        self.plan_bean_combo.setToolTip(
            QApplication.translate("tilauscope_beancave",
                "Select the green bean you want to plan for. "
                "Independent from the Green Beans tab selection."))
        self.plan_bean_combo.currentIndexChanged.connect(self._on_plan_bean_changed)

        # Roast selector
        roast_lbl = QLabel("📋 " + QApplication.translate("tilauscope_beancave", "Reference roast:"))
        roast_lbl.setStyleSheet(f"color:{THEME['TEXT']}; font-size:12px;")
        self.plan_roast_combo = QComboBox()
        self.plan_roast_combo.setMinimumWidth(200)
        self.plan_roast_combo.setItemDelegate(QStyledItemDelegate())
        self.plan_roast_combo.setView(QListView())
        self.plan_roast_combo.setToolTip(
            QApplication.translate("tilauscope_beancave",
                "Optionally pick a past roast to pre-fill ambient conditions "
                "(temperature, humidity, pressure). Independent from the Roast Viewer tab."))
        self.plan_roast_combo.currentIndexChanged.connect(self._on_plan_roast_changed)

        sel_layout.addWidget(bean_lbl)
        sel_layout.addWidget(self.plan_bean_combo, 1)
        sel_layout.addSpacing(8)
        sel_layout.addWidget(roast_lbl)
        sel_layout.addWidget(self.plan_roast_combo, 1)

        # Centered fixed-max-width wizard column inside a vertical
        # scroll area — expanding the offsets panel scrolls instead of
        # compacting the whole layout (Bean → Conditions → Target).
        self._plan_wizard = QWidget()
        self._plan_wizard.setObjectName("planWizard")
        self._plan_wizard.setStyleSheet(f"#planWizard {{ background:{THEME['BG']}; }}")
        self._plan_wizard.setMaximumWidth(900)
        self._plan_wlay = QVBoxLayout(self._plan_wizard)
        self._plan_wlay.setContentsMargins(0, 0, 0, 0)
        self._plan_wlay.setSpacing(10)
        self._plan_wlay.addWidget(self._build_plan_stepper())
        self._plan_wlay.addWidget(sel_frame)

        plan_scroll = QScrollArea()
        plan_scroll.setWidgetResizable(True)
        plan_scroll.setFrameShape(QFrame.Shape.NoFrame)
        plan_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        plan_scroll.setStyleSheet(f"QScrollArea {{ border:none; background:{THEME['BG']}; }}")
        plan_scroll.viewport().setStyleSheet(f"background:{THEME['BG']};")
        scroll_body = QWidget()
        scroll_body.setObjectName("planScrollBody")
        scroll_body.setStyleSheet(f"#planScrollBody {{ background:{THEME['BG']}; }}")
        scroll_v = QVBoxLayout(scroll_body)
        scroll_v.setContentsMargins(12, 4, 12, 12)
        scroll_row = QHBoxLayout()
        scroll_row.addStretch(1)
        scroll_row.addWidget(self._plan_wizard)
        scroll_row.addStretch(1)
        scroll_v.addLayout(scroll_row)
        scroll_v.addStretch(1)   # keep the column pinned to the top when short
        plan_scroll.setWidget(scroll_body)
        main_layout.addWidget(plan_scroll)

        # ── Status label ──────────────────────────────────────────────────────────
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setContentsMargins(0, 4, 0, 4)
        self._plan_wlay.addWidget(self.status_label)

        # Stepper-based roast plan layout (Bean → Conditions → Target).
        # All original widgets are preserved; only their arrangement changed.
        # self.input_group is kept as the logical enable/disable gate for the
        # whole parameter area (toggled in _validate_plan_selection); it now wraps
        # the Conditions + Target cards and is rendered flat (no title/border).

        # Create the parameter widgets (roaster, roast level, environment fields)
        self.roaster_combo = QComboBox()
        self.roaster_combo.setMinimumWidth(150)
        self.roaster_combo.setItemDelegate(QStyledItemDelegate())
        self.roaster_combo.setView(QListView())
        self.roaster_combo.currentIndexChanged.connect(self._on_roaster_model_changed)
        self.roaster_combo.currentIndexChanged.connect(self._update_plan_stepper)

        self.roast_level_combo = QComboBox()
        self.roast_level_combo.setItemDelegate(QStyledItemDelegate())
        self.roast_level_combo.setView(QListView())
        for a in reversed(AGTRON_SCALES):
            agtron = int((a.agtron_range.max_value + a.agtron_range.min_value) * 0.5)
            self.roast_level_combo.addItem(f"{a.name} ({agtron} Agtron - {a.description})")
        self.roast_level_combo.setToolTip(QApplication.translate("tilauscope_beancave","Select the desired final roast color (Agtron reference)."))

        # Environmental and Batch Fields (QDoubleSpinBox)
        input_definitions = [
            ("Ambient Temperature", f"°{self.aw.qmc.mode}", 0.0, 50.0 if self.aw.qmc.mode=='C' else 122, 1.0, 1, QApplication.translate("tilauscope_beancave","Current ambient temperature in the roasting area. Important for charge temperature calculation.")), # fix 2026/04/26 farenheit check was not done
            ## Ambient humidity removed from the roast setup 2026-08-11: it does
            ## not act on the roast in progress. Its real influence is BETWEEN
            ## roasts, drifting the green's water activity in storage — it is
            ## still recorded on the roast file and still drives the storage
            ## advice. See wiki/WaterActivity-Altitude-Spec.md §2.3.
            ("Atmospheric Pressure", "hPa", 0.0, 1100.0, 1.0, 0, QApplication.translate("tilauscope_beancave","Current atmospheric pressure. Used for boiling point and thermodynamics.")),
            ("Altitude", "m", 0.0, 5000.0, 10.0, 0, QApplication.translate("tilauscope_beancave","Altitude of the roasting location. Affects thermodynamic calculations.")),
            ("Batch Weight", "g", 0.0, 20000.0, 100.0, 0, QApplication.translate("tilauscope_beancave","Total weight of green beans to roast in this batch.")),
        ]
        for label, suffix, min_val, max_val, step, decimals, tooltip in input_definitions:
            spin_box = MyQDoubleSpinBox()
            spin_box.setRange(min_val, max_val)
            spin_box.setSingleStep(step)
            spin_box.setDecimals(decimals)
            spin_box.setSuffix(f" {suffix}")
            spin_box.setToolTip(tooltip)
            spin_box.valueChanged.connect(self._check_plan_inputs)
            self.roast_plan_inputs[label] = spin_box

        # Batch weight and roast level survive a restart: a roaster
        # works through a bag at one batch size, on one roast level, over many
        # sessions. The ambient fields are deliberately NOT remembered — they
        # describe the room right now and are refilled from the weather or the
        # probe. Restored before the save handlers are connected, so restoring
        # does not write back what it just read.
        self._restore_plan_batch_prefs()

        # ── flat wrapper card group (Conditions + Target) ─────────────────────────
        self.input_group.setTitle("")   #type:ignore
        self.input_group.setFlat(True)
        self.input_group.setStyleSheet("QGroupBox{border:none;margin:0;padding:0;}")
        params_layout = QVBoxLayout(self.input_group)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(14)

        _MUTED = THEME['OVERLAY0']
        _MAUVE = THEME['MAUVE']
        _CRUST = THEME['CRUST']

        def _card(step_no: str, title: str, active: bool = False,
                  right: str = "", right_color: str = ""):
            card = QFrame()
            card.setObjectName("planCard")
            border = THEME['ACCENT'] if active else THEME['BORDER']
            card.setStyleSheet(
                f"QFrame#planCard{{background:{THEME['SURFACE']};border:1px solid {border};border-radius:11px;}}")
            v = QVBoxLayout(card)
            v.setContentsMargins(16, 14, 16, 16)
            v.setSpacing(12)
            hdr = QHBoxLayout(); hdr.setSpacing(9)
            badge = QLabel(step_no)
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            done = step_no == "✓"
            bg = THEME['SUCCESS'] if done else (THEME['ACCENT'] if active else THEME['BORDER'])
            fg = _CRUST if (done or active) else _MUTED
            badge.setStyleSheet(
                f"background:{bg};color:{fg};border-radius:10px;font-weight:700;font-size:11px;")
            ct = QLabel(title.upper())
            ct.setProperty('variant', 'eyebrow')
            hdr.addWidget(badge); hdr.addWidget(ct); hdr.addStretch()
            if right:
                rl = QLabel(right)
                rl.setStyleSheet(
                    f"font-size:11px;color:{right_color or _MUTED};background:transparent;border:none;")
                hdr.addWidget(rl)
            v.addLayout(hdr)
            return card, v

        # ── STEP 2 · Ambient conditions (compact tiles) ───────────────────────────
        cond_card, cond_v = _card(
            "2", QApplication.translate("tilauscope_beancave", "Ambient conditions"),
            active=True,
            right="☂ " + QApplication.translate("tilauscope_beancave", "weather sync"),
            right_color=THEME['TODAY'])
        # Four labelled fields across — native spinbox styling (from the global
        # QSS) so the values are always visible; a caption sits above each field.
        tiles_grid = QGridLayout()
        tiles_grid.setHorizontalSpacing(12)
        tiles_grid.setVerticalSpacing(5)
        _tile_defs = [
            ("Ambient Temperature", QApplication.translate("tilauscope_beancave", "Temperature")),
            ("Atmospheric Pressure",QApplication.translate("tilauscope_beancave", "Pressure")),
            ("Altitude",            QApplication.translate("tilauscope_beancave", "Altitude")),
        ]
        for col, (key, short) in enumerate(_tile_defs):
            cap = QLabel(short.upper())
            cap.setProperty('variant', 'eyebrow')
            sb = self.roast_plan_inputs[key]
            sb.setMinimumHeight(32)   # keep the value legible under the global QSS
            tiles_grid.addWidget(cap, 0, col)
            tiles_grid.addWidget(sb, 1, col)
            tiles_grid.setColumnStretch(col, 1)
        cond_v.addLayout(tiles_grid)

        # Two ways to fill the ambient fields, side by side: online weather and
        # the live TilauAmbient probe (the latter enabled only when connected).
        self.weather_btn = QPushButton(
            "☂  " + QApplication.translate("tilauscope_beancave", "Online weather"))
        self.weather_btn.setToolTip(QApplication.translate("tilauscope_beancave","Fill temperature, humidity, pressure and altitude from the online weather for your location."))
        self.weather_btn.setMinimumHeight(36)
        self.weather_btn.setMaximumWidth(300)
        self.weather_btn.clicked.connect(self._get_weather_conditions)
        self.weather_btn.setStyleSheet(f"""
            QPushButton {{ background:rgba(250,179,135,0.16); color:{THEME['TEXT']};
                border:1px solid {THEME['TODAY']}; border-radius:8px;
                font-size:12px; padding:8px 18px; }}
            QPushButton:hover:enabled {{ background:rgba(250,179,135,0.28); }}
            QPushButton:disabled {{ background:{THEME['SURFACE']}; color:{THEME['OVERLAY1']}; border:1px solid {THEME['BORDER']}; }}
        """)

        self.tilauambient_btn = QPushButton(
            "🌡  " + QApplication.translate("tilauscope_beancave", "TilauAmbient probe"))
        self.tilauambient_btn.setMinimumHeight(36)
        self.tilauambient_btn.setMaximumWidth(300)
        self.tilauambient_btn.clicked.connect(self._get_tilauambient_conditions)
        self.tilauambient_btn.setStyleSheet(f"""
            QPushButton {{ background:{tint('ACCENT', 0.16)}; color:{THEME['TEXT']};
                border:1px solid {THEME['ACCENT']}; border-radius:8px;
                font-size:12px; padding:8px 18px; }}
            QPushButton:hover:enabled {{ background:{tint('ACCENT', 0.28)}; }}
            QPushButton:disabled {{ background:{THEME['SURFACE']}; color:{THEME['OVERLAY1']}; border:1px solid {THEME['BORDER']}; }}
        """)

        cond_btns = QHBoxLayout(); cond_btns.setSpacing(10)
        cond_btns.addStretch(1)
        cond_btns.addWidget(self.weather_btn)
        cond_btns.addWidget(self.tilauambient_btn)
        cond_btns.addStretch(1)
        cond_v.addLayout(cond_btns)
        self._refresh_tilauambient_btn()
        params_layout.addWidget(cond_card)

        # ── STEP 3 · Target profile & batch ───────────────────────────────────────
        target_card, target_v = _card(
            "3", QApplication.translate("tilauscope_beancave", "Target profile & batch"))
        combo_row = QHBoxLayout(); combo_row.setSpacing(14)
        for lbl_txt, combo in [
            (QApplication.translate("tilauscope_beancave", "Roaster model"), self.roaster_combo),
            (QApplication.translate("tilauscope_beancave", "Roast level"), self.roast_level_combo),
        ]:
            fld = QVBoxLayout(); fld.setSpacing(6)
            l = QLabel(lbl_txt)
            l.setStyleSheet(
                f"font-size:12px;color:{THEME['SUBTEXT']};background:transparent;border:none;")
            combo.setMinimumHeight(32)
            fld.addWidget(l); fld.addWidget(combo)
            combo_row.addLayout(fld, 1)
        target_v.addLayout(combo_row)

        # Batch weight — deliberately separated from the ambient block (mauve accent).
        # Native spinbox styling so the value stays visible.
        batch = QFrame(); batch.setObjectName("planBatch")
        batch.setStyleSheet(
            f"QFrame#planBatch{{background:{THEME['BG']};border:1px solid #6C5A8C;border-radius:9px;}}")
        bl = QHBoxLayout(batch); bl.setContentsMargins(14, 10, 14, 10); bl.setSpacing(12)
        btitle = QVBoxLayout(); btitle.setSpacing(2)
        bt_lbl = QLabel("⚖ " + QApplication.translate("tilauscope_beancave", "Batch weight"))
        bt_lbl.setProperty('variant', 'eyebrow')
        bt_lbl.setStyleSheet(f"color: {_MAUVE};")
        bd_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Green to load — sizes the plan"))
        bd_lbl.setStyleSheet(f"font-size:11px;color:{_MUTED};background:transparent;border:none;")
        btitle.addWidget(bt_lbl); btitle.addWidget(bd_lbl)
        bl.addLayout(btitle); bl.addStretch()
        bw = self.roast_plan_inputs["Batch Weight"]
        bw.setMinimumHeight(32)
        bw.setMaximumWidth(170)
        bl.addWidget(bw)
        target_v.addWidget(batch)
        params_layout.addWidget(target_card)
        self._plan_wlay.addWidget(self.input_group)

        # ── Probe deviation offsets (collapsible "advanced" accordion) ─────────────
        # DOCTRINE: always °C. Machine calibration deltas (same frame as
        # RoasterContext.bt_offsets) consumed by the °C-internal plan maths.
        self.offsets_toggle_btn = QPushButton()
        self.offsets_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.offsets_toggle_btn.setStyleSheet(f"""
            QPushButton {{ background:{THEME['BG']}; color:{THEME['SUBTEXT']};
                border:1px solid {THEME['BORDER']}; border-radius:9px;
                font-size:12px; padding:11px 14px; text-align:left; }}
            QPushButton:hover {{ border-color:{THEME['ACCENT']}; }}
        """)
        self.offsets_toggle_btn.clicked.connect(self._toggle_offsets_accordion)

        self.probe_dev_group = QGroupBox(QApplication.translate("tilauscope_beancave","Probe Deviation Offsets")+" (°C)")
        probe_layout = QGridLayout()
        self.cb_lock_to_roaster = QCheckBox(QApplication.translate("tilauscope_beancave", "Use offsets from Roaster Model (Disable manual override)"))
        self.cb_lock_to_roaster.setChecked(self.probe_override)
        self.cb_lock_to_roaster.toggled.connect(self.update_offset_fields_state)
        probe_layout.addWidget(self.cb_lock_to_roaster, 0, 0, 1, 2)

        milestones = ["Charge", "Dry End (DE)", "First Crack (FC)", "Drop"]
        self.dev_inputs = {} # Dictionary to store widgets
        for i, label in enumerate(milestones):
            probe_layout.addWidget(QLabel(label), i+1, 0)
            start_input = QDoubleSpinBox()
            start_input.setRange(-50.0, 50.0)
            start_input.setSuffix(" min")
            start_input.setToolTip(QApplication.translate("tilauscope_beancave","Minimum deviation from target temperature at this milestone."))
            end_input = QDoubleSpinBox()
            end_input.setRange(-50.0, 50.0)
            end_input.setSuffix(" max")
            end_input.setToolTip(QApplication.translate("tilauscope_beancave","Maximum deviation from target temperature at this milestone."))
            probe_layout.addWidget(start_input, i+1, 1)
            probe_layout.addWidget(end_input, i+1, 2)
            key = ["bt_at_charge", "bt_at_de", "bt_at_fc", "bt_at_drop"][i]
            self.dev_inputs[key] = (start_input, end_input)

        self.savesettings_btn = QPushButton(QApplication.translate("tilauscope_beancave","Save settings"))
        self.savesettings_btn.setToolTip(QApplication.translate("tilauscope_beancave","save settings for further usage of roasting plans"))
        self.savesettings_btn.clicked.connect(self.save_settings)
        probe_layout.addWidget(self.savesettings_btn, 5, 1)
        self.defaultsettings_btn = QPushButton(QApplication.translate("tilauscope_beancave","Default settings"))
        self.defaultsettings_btn.setToolTip(QApplication.translate("tilauscope_beancave","Reset parameters to default values on GUI only. Please save them if needed."))
        self.defaultsettings_btn.clicked.connect(self.reset_settings)
        probe_layout.addWidget(self.defaultsettings_btn, 5, 2)
        self.update_offset_fields_state(self.probe_override)
        self.probe_dev_group.setLayout(probe_layout)
        self.probe_dev_group.setVisible(False)   # collapsed by default
        self._toggle_offsets_accordion(refresh_only=True)  # sets the button caption

        self._plan_wlay.addWidget(self.offsets_toggle_btn)
        self._plan_wlay.addWidget(self.probe_dev_group)

        # ── Primary action · Generate, then Inject ────────────────────────────────
        self.generate_plan_btn = QPushButton(
            "⚡  " + QApplication.translate("tilauscope_beancave","Generate Roast Plan"))
        self.generate_plan_btn.setToolTip(QApplication.translate("tilauscope_beancave","Creates a suggested roasting strategy based on the current parameters."))
        self.generate_plan_btn.setEnabled(False)
        self.generate_plan_btn.clicked.connect(self._generate_roast_plan_profile)
        self.generate_plan_btn.setMinimumHeight(44)
        self.generate_plan_btn.setMaximumWidth(420)
        self.generate_plan_btn.setStyleSheet(f"""
            QPushButton {{ background:{THEME['SUCCESS']}; color:{_CRUST}; border:none; border-radius:8px;
                font-weight:700; font-size:14px; padding:11px 28px; }}
            QPushButton:hover:enabled {{ background:#B5EBA5; }}
            QPushButton:disabled {{ background:{THEME['SURFACE']}; color:{_MUTED};
                border:1px solid {THEME['BORDER']}; }}
        """)
        self._plan_wlay.addWidget(self.generate_plan_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        # Inject button (unlocks once a plan is generated). The plan itself is
        # delivered as a PDF + alarm set + background curve, so no on-screen text
        # dump is needed here.
        self.injectinartisan_btn = QPushButton(QApplication.translate("tilauscope_beancave","Inject in Artisan"))
        self.injectinartisan_btn.setToolTip(QApplication.translate("tilauscope_beancave","Inject all the suggestions in various artisan parameters including background curve."))
        self.injectinartisan_btn.setEnabled(False)
        self.injectinartisan_btn.clicked.connect(self._inject_roast_plan)
        inject_row = QHBoxLayout()
        inject_row.addStretch()
        inject_row.addWidget(self.injectinartisan_btn)
        self._plan_wlay.addLayout(inject_row)

        # Initial population now that the widgets exist
        self._populate_plan_bean_combo()   # this also calls _on_plan_bean_changed → _populate_plan_roast_combo
        self._populate_roaster_list()
        self._update_plan_stepper()
        self.roast_plan_tab.setLayout(main_layout)

    def _build_plan_stepper(self) -> QWidget:
        """Build the 3-step progress header (Bean → Conditions → Target)."""
        steps = [
            QApplication.translate("tilauscope_beancave", "Bean"),
            QApplication.translate("tilauscope_beancave", "Conditions"),
            QApplication.translate("tilauscope_beancave", "Target & plan"),
        ]
        self._plan_step_badges = []   # type: list[QLabel]
        self._plan_step_texts = []    # type: list[QLabel]
        self._plan_step_lines = []    # type: list[QFrame]  (len == n-1)

        frame = QFrame()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(6, 2, 6, 8)
        lay.setSpacing(0)
        for i, name in enumerate(steps):
            badge = QLabel(str(i + 1))
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._plan_step_badges.append(badge)
            txt = QLabel(f"{i + 1} · {name}")
            self._plan_step_texts.append(txt)
            lay.addWidget(badge)
            lay.addSpacing(8)
            lay.addWidget(txt)
            if i < len(steps) - 1:
                line = QFrame()
                line.setFixedHeight(2)
                self._plan_step_lines.append(line)
                lay.addSpacing(12)
                lay.addWidget(line, 1)
                lay.addSpacing(12)
        self._update_plan_stepper()
        return frame

    def _set_plan_step_state(self, idx: int, state: str) -> None:
        """Style one stepper badge/text as done / current / wait."""
        badge = self._plan_step_badges[idx]
        txt = self._plan_step_texts[idx]
        crust, muted = THEME['CRUST'], THEME['OVERLAY0']
        if state == "done":
            badge.setText("✓")
            badge.setStyleSheet(
                f"background:{THEME['SUCCESS']};color:{crust};border-radius:11px;"
                "font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-size:12px;color:{THEME['TEXT']};")
        elif state == "current":
            badge.setText(str(idx + 1))
            badge.setStyleSheet(
                f"background:{THEME['ACCENT']};color:{crust};border-radius:11px;"
                "font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-size:12px;color:{THEME['TEXT']};")
        else:  # wait
            badge.setText(str(idx + 1))
            badge.setStyleSheet(
                f"background:{THEME['BORDER']};color:{muted};border-radius:11px;"
                "font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-size:12px;color:{THEME['SUBTEXT']};")

    @pyqtSlot()
    def _update_plan_stepper(self) -> None:
        """Refresh stepper state from the current field values."""
        if not getattr(self, "_plan_step_badges", None):
            return

        def _val(k: str) -> float:
            w = self.roast_plan_inputs.get(k)
            return w.value() if w is not None else 0.0

        bean_combo = getattr(self, "plan_bean_combo", None)
        roaster_combo = getattr(self, "roaster_combo", None)
        step1 = (bean_combo is not None
                 and bean_combo.currentIndex() >= 0
                 and bool(bean_combo.currentText()))
        step2 = (_val("Ambient Temperature") > 0
                 and _val("Atmospheric Pressure") > 0)
        step3 = (_val("Batch Weight") > 0
                 and roaster_combo is not None
                 and roaster_combo.currentIndex() >= 0)

        states = ["current", "wait", "wait"]
        states[0] = "done" if step1 else "current"
        if step1:
            states[1] = "done" if step2 else "current"
        if step1 and step2:
            states[2] = "done" if step3 else "current"
        for i, s in enumerate(states):
            self._set_plan_step_state(i, s)
        for i, line in enumerate(self._plan_step_lines):
            on = states[i] == "done"
            line.setStyleSheet(f"background:{THEME['SUCCESS'] if on else THEME['BORDER']};border:none;")

    def _toggle_offsets_accordion(self, checked: bool = False, refresh_only: bool = False) -> None:
        """Show/hide the probe-offset panel and update the caption."""
        if not refresh_only:
            self.probe_dev_group.setVisible(not self.probe_dev_group.isVisible())
        chev = "▴" if self.probe_dev_group.isVisible() else "▾"
        self.offsets_toggle_btn.setText(
            "🔒  " + QApplication.translate(
                "tilauscope_beancave", "Probe deviation offsets — locked to roaster model")
            + f"        {chev}")

    def update_offset_fields_state(self, checked: bool):
        """
        If checked, we gray out and disable the fields.
        """
        for start, end in self.dev_inputs.values():
            start.setEnabled(checked)
            end.setEnabled(checked)
        self.probe_override = checked
        self.savesettings_btn.setEnabled(checked)
        self.defaultsettings_btn.setEnabled(checked)

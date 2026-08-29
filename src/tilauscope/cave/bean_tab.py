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

import json
import uuid
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import
from datetime import datetime
from pathlib import Path

#import matplotlib.pyplot as plt




from PyQt6.QtCore import (QModelIndex, Qt, pyqtSlot, QSettings, QThread) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QColor) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QComboBox, QWidget, QHeaderView, QTableWidgetItem, QAbstractItemView,
                                QMessageBox, QDialog) # @UnusedImport @Reimport  @UnresolvedImport

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import (GreenBean, BeanCaveContainer, GREEN_BEAN_COLUMNS, show_styled_message,
                                         THEME, TilauProgressDialog, _IS_WINDOWS)
from tilauscope.header_icons import SVG_PROG_AI
from tilauscope.sack_manager import SackPool, confirm_release, prompt_release_if_emptied  # sack labels (Lot 1, §9.3)
from tilauscope.bean_qualifiers import physical_qualifier  # plain-language reading of density/humidity/aw
from tilauscope.tilau_wheel import FlavorSelectorDialog
from tilauscope.cave.common import (
    _log, _logd, greencave_headers, BEANCAVE_FILE_NAME,
    _atomic_write_text)
from tilauscope.cave.widgets import (
    SmoothHoverFilter,
    URLInputDialog)
from tilauscope.cave.workers import (
    BeanAIWorker)


class BeanTabMixin:
    """The Beans tab: the catalogue, the record form and everything that edits it.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    def _update_variety(self, var: str) -> None:
        if hasattr(self, 'varieties_combo'):
            self.varieties_combo.blockSignals(True)
            self.varieties_combo.clear()
            try:
                self.varieties_combo.addItems(self.coffee_bean_types[var])
            except Exception:
                pass
            self.varieties_combo.addItem(
                QApplication.translate("tilauscope_beancave", "Other"))
            self.varieties_combo.blockSignals(False)
            # clear() wipes WA_Hover + stylesheet — restore them
            self._reattach_hover(self.varieties_combo)
        else:
            self._pending_variety = var

    def _update_methods(self, cat: str) -> None:
        if hasattr(self, 'process_combo'):
            self.process_combo.blockSignals(True)
            self.process_combo.clear()
            try:
                self.process_combo.addItems(self.coffee_processing_methods[cat])
            except Exception:
                pass
            self.process_combo.addItem(
                QApplication.translate("tilauscope_beancave", "Other"))
            self.process_combo.blockSignals(False)
            # clear() wipes WA_Hover + stylesheet — restore them
            self._reattach_hover(self.process_combo)
        else:
            self._pending_category = cat

    def _reattach_hover(self, widget: QWidget) -> None:
        """
        Re-arm hover detection after a combo.clear() call.
        clear() resets WA_Hover to False and loses the animated stylesheet,
        so we must explicitly restore both before the widget is repainted.
        """
        if not hasattr(self, 'hover_filter'):
            return
        # Remove any stale registration then re-add — avoids double-firing
        widget.removeEventFilter(self.hover_filter)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.setStyleSheet(
            f"background-color: {THEME['SURFACE']};"
            f"border: 1px solid {THEME['BORDER']};"
        )
        widget.installEventFilter(self.hover_filter)

    def _install_hover_filter(self, combo: QComboBox) -> None:
        """Install (or reinstall) a SmoothHoverFilter on a combo."""
        # Remove any existing filter of this type first
        attr = f'_hover_{id(combo)}'
        old = getattr(self, attr, None)
        if old is not None:
            combo.removeEventFilter(old)
        f = SmoothHoverFilter(combo)
        combo.installEventFilter(f)
        setattr(self, attr, f)   # keep reference alive on self

    @pyqtSlot()
    def _toggle_blend_fields(self) -> None:
        """
        V3 — Gère la visibilité conditionnelle selon le type (Single Origin / Blend).

        Single Origin : Species + Variety dans groupe Botany (row 1), Blend group caché.
        Blend         : Species masqués, varieties_combo re-parenté dans blend_group_box
                        (Bean 1 col 0-1), Blend group visible.
        Ratio 1       : éditable uniquement en Blend (forcé à 100% en SO).
        """
        is_blend = self.type_combo.currentText() == "Blend"

        # ── Re-parentage de varieties_combo selon le mode ─────────────────
        if hasattr(self, "_gl2_botany") and hasattr(self, "_gl4_blend")                 and hasattr(self, "varieties_combo"):
            if is_blend:
                # Déplacer dans blend_group_box (col 0-1, row 0)
                self._gl4_blend.addWidget(self._blend_bean1_lbl,  0, 0)
                self._gl4_blend.addWidget(self.varieties_combo,   0, 1)
                self.varieties_combo.setVisible(True)
                self._blend_bean1_lbl.setVisible(True)
            else:
                # Remettre dans Botany (row 1, col 2-3)
                if hasattr(self, "_blend_bean1_lbl"):
                    self._blend_bean1_lbl.setVisible(False)
                self._gl2_botany.addWidget(self._variety_row_lbl, 1, 2)
                self._gl2_botany.addWidget(self.varieties_combo,  1, 3)
                self.varieties_combo.setVisible(True)

        # ── Blend group ───────────────────────────────────────────────────
        if hasattr(self, "blend_group_box"):
            self.blend_group_box.setVisible(is_blend)

        # ── Species + label Variety dans Botany : masqués en Blend ───────
        for _w in (
            getattr(self, "_species_row_lbl", None),
            getattr(self, "species_combo",    None),
            getattr(self, "_variety_row_lbl", None),
        ):
            if _w is not None:
                _w.setVisible(not is_blend)

        # ── Ratio 1 : éditabilité ─────────────────────────────────────────
        self.bean1_ratio_input.setEnabled(is_blend)
        if not is_blend:
            self.bean1_ratio_input.setValue(100.0)

        # ── Mise à jour des listes de composants Blend ────────────────────
        if is_blend:
            self._update_blend_component_list()

    def _update_blend_component_list(self) -> None:
        """Populates the component comboboxes with Single Origin bean names."""
        if not hasattr(self, 'bean2_combo'):
            return

        # Get names of all existing Single Origin beans (beans that are not blends themselves)
        # Test the content, not the attribute: it is declared empty and only filled once the
        # parameter file has been read, so a file that failed to load must degrade here.
        single_origin_names = list(getattr(self, 'coffee_bean_types', {}).get('Arabica', []))
        if not single_origin_names:
            single_origin_names = []
            single_origin_names.insert(0, QApplication.translate("tilauscope_beancave","N/A - Select a bean")) # Default option

        # Store the currently selected items to restore them after updating the list
        current_bean2 = self.bean2_combo.currentText()
        current_bean3 = self.bean3_combo.currentText()

        self.bean2_combo.clear()
        self.bean3_combo.clear()

        self.bean2_combo.addItems(single_origin_names)
        self.bean3_combo.addItems(single_origin_names)

        # Restore selection
        if current_bean2 in single_origin_names:
            self.bean2_combo.setCurrentText(current_bean2)
        if current_bean3 in single_origin_names:
            self.bean3_combo.setCurrentText(current_bean3)



    def update_ui_visibility(self) -> None:
        """Hides form + datatable and shows empty state message when needed. V2-compatible."""
        has_beans = self.cave is not None and len(self.cave.green_beans) > 0

        if not self.is_directory_defined:
            self.empty_state_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Please configure the BeanCave database and ALog directories in Configuration > BeanCave first.")
            )
            show_form = False
        elif not has_beans:
            self.empty_state_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Your bean cave is empty. Please define your first bean using the 'Add' button.")
            )
            self.add_button.setEnabled(True)
            show_form = False
        else:
            show_form = True

        self.form_group_box.setVisible(show_form)
        # Lot 5: visibility drives the rich list; datatable stays hidden
        self.catalogue_list.setVisible(show_form)
        self.empty_state_label.setVisible(not show_form)
        if hasattr(self, '_notice_bar'):
            self._notice_bar.setVisible(show_form)


    @pyqtSlot()
    def _open_sack_labels(self) -> None:
        from tilauscope.sack_manager import SackLabelsDialog
        dlg = SackLabelsDialog(self)
        dlg.exec()

    # New-sack guided assistant (design v4 §5) — Green Beans header button
    @pyqtSlot()
    def _open_new_sack_wizard(self) -> None:
        try:
            from tilauscope.beancave_sack_wizard import NewSackWizard
            wiz = NewSackWizard(self)
            wiz.adjustSize()
            parent_geo = self.geometry()
            wiz.move(parent_geo.center().x() - wiz.width() // 2,
                     parent_geo.center().y() - wiz.height() // 2)
            wiz.exec()
        except Exception:  # noqa: BLE001
            _logd.exception("new sack wizard failed")

    # Same assistant, entered on the selected bean — new-crop flow only
    @pyqtSlot()
    def _open_new_crop_wizard(self) -> None:
        try:
            bean = self._current_selected_bean()
            if bean is None:
                return
            from tilauscope.beancave_sack_wizard import NewSackWizard
            wiz = NewSackWizard(self, source_bean=bean)
            wiz.adjustSize()
            parent_geo = self.geometry()
            wiz.move(parent_geo.center().x() - wiz.width() // 2,
                     parent_geo.center().y() - wiz.height() // 2)
            wiz.exec()
        except Exception:  # noqa: BLE001
            _logd.exception("new crop wizard failed")

    # Syncs the catalogue rich list selection to the hidden datatable
    @pyqtSlot(int)
    def _on_catalogue_row_activated(self, index: int) -> None:
        if 0 <= index < self.datatable.rowCount():
            self.datatable.selectRow(index)

    # Switches the right pane from the read sheet to the edit form
    def _enter_edit_mode(self, _zone: object = None) -> None:
        if hasattr(self, '_right_stack'):
            self._right_stack.setCurrentIndex(1)

    # ✎ opens a targeted modal editor for that zone
    @pyqtSlot(str)
    def _open_zone_editor(self, zone: str) -> None:
        try:
            bean = self._current_selected_bean()
            if bean is None:
                return
            from tilauscope.beancave_zone_editors import ZoneEditorDialog
            dlg = ZoneEditorDialog(self, bean, zone)
            dlg.adjustSize()
            geo = self.geometry()
            dlg.move(geo.center().x() - dlg.width() // 2,
                     geo.center().y() - dlg.height() // 2)
            dlg.exec()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("zone editor failed")

    # Lot 5 step D — Add: full expert editor on a blank record
    @pyqtSlot()
    def _open_full_bean_editor(self) -> None:
        try:
            if self.cave is None:
                self.cave = BeanCaveContainer(green_beans=[], reference_profiles=[])
            if getattr(self.cave, 'green_beans', None) is None:
                self.cave.green_beans = []
            from tilauscope.beancave_zone_editors import ZoneEditorDialog
            bean = GreenBean()
            bean.uuid = str(uuid.uuid4())
            dlg = ZoneEditorDialog(self, bean, 'all', create=True)
            dlg.adjustSize()
            geo = self.geometry()
            # anchor near the top of the BeanCave window — the stacked form is
            # tall, centring on the middle pushed it below the screen edge
            dlg.move(geo.center().x() - max(dlg.width(), dlg.sizeHint().width()) // 2,
                     geo.y() + 50)
            dlg.exec()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("full bean editor failed")

    def _current_selected_bean(self) -> GreenBean | None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return None
        rows = self.datatable.selectionModel().selectedRows()  # type: ignore
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self.cave.green_beans):
            return self.cave.green_beans[row]
        return None

    def select_bean_by_uuid(self, uuid_str: str) -> None:
        """Select the catalogue row carrying this uuid (col 0 UserRole)."""
        try:
            for r in range(self.datatable.rowCount()):
                it = self.datatable.item(r, 0)
                if it is not None and it.data(Qt.ItemDataRole.UserRole) == uuid_str:
                    self.datatable.selectRow(r)
                    return
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"select_bean_by_uuid skipped: {e}")

    @pyqtSlot()
    def _sync_catalogue_selection(self) -> None:
        try:
            rows = self.datatable.selectionModel().selectedRows()  # type: ignore
            self.catalogue_list.select_index(rows[0].row() if rows else -1)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"catalogue selection sync skipped: {e}")

    # ------- QR scan → record routing (spec wiki/QR-Scan-Spec.md §3.3) -------

    @pyqtSlot()
    def on_click_scan_qr(self) -> None:
        """Header 📷 SCAN button: open the webcam scan dialog and route the result."""
        try:
            from tilauscope.qr_scan import ScanQRDialog, scanner_available
            ok, reason = scanner_available()
            if not ok:
                self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "QR scan unavailable"),
                    reason, QMessageBox.Icon.Warning)
                return
            dlg = ScanQRDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_kind:
                return
            if dlg.result_kind == 'roast':
                self._open_roast_card_from_scan(dlg.result_id)
            elif dlg.result_kind == 'bean':
                self._open_bean_sheet_from_scan(dlg.result_id)
            elif dlg.result_kind == 'sack':
                self._open_bean_sheet_from_sack_scan(dlg.result_id)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.error(f"QR scan failed: {e}", exc_info=True)

    def _open_roast_card_from_scan(self, roast_uuid: str) -> None:
        """Resolve an Artisan roastUUID via the alog metadata cache and show the card."""
        meta = next((m for m in self._metadata_cache.records.values()
                     if m.roast_uuid.lower() == roast_uuid.lower()), None)
        if meta is None:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Roast not found"),
                QApplication.translate("tilauscope_beancave",
                    "No roast with this identifier in the ALog directory.\n"
                    "If the application just started, indexing may still be "
                    "running — try again in a few seconds."),
                QMessageBox.Icon.Warning)
            return
        profile = self.get_alog_data(meta.filepath_str)
        if not profile:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave",
                    "The roast file could not be read.")
                + f"\n{meta.filename}",
                QMessageBox.Icon.Warning)
            return
        # resolve the source green bean for the card link (absent if unresolved)
        bean = None
        try:
            uuid_match = self.uuid_pattern.search(str(profile.get('beans', '') or ''))
            if uuid_match and hasattr(self, 'uuidmap'):
                bean = self.uuidmap.get(uuid_match.group(1))
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"scan: source bean resolution skipped: {e}")
        on_open_bean = None
        if bean is not None and getattr(bean, 'uuid', None):
            bean_uuid = bean.uuid
            on_open_bean = lambda: self._open_bean_sheet_from_scan(bean_uuid)  # noqa: E731
        from tilauscope.roast_card import RoastCardDialog
        card = RoastCardDialog(profile, self,
                               bean_name=(bean.name if bean is not None else ""),
                               on_open_bean=on_open_bean)
        card.exec()

    def _open_bean_sheet_from_scan(self, uuid_str: str) -> None:
        """Bring BeanCave to front on the catalogue with this bean selected."""
        if not hasattr(self, 'uuidmap') or uuid_str not in self.uuidmap:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Bean not found"),
                QApplication.translate("tilauscope_beancave",
                    "No green bean with this identifier in the BeanCave catalogue."),
                QMessageBox.Icon.Warning)
            return
        try:
            self.tab_widget.setCurrentWidget(self.main_tab)
            self.select_bean_by_uuid(uuid_str)
            self.raise_()
            self.activateWindow()
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.error(f"scan: bean sheet opening failed: {e}", exc_info=True)

    def _open_bean_sheet_from_sack_scan(self, sack_id: str) -> None:
        """Resolve a sack label to its owning coffee and open that record."""
        bean_uuid = self._resolve_sack(sack_id)
        if not bean_uuid:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Sack not found"),
                QApplication.translate("tilauscope_beancave",
                    "This label is not currently attached to any coffee in the "
                    "BeanCave catalogue."),
                QMessageBox.Icon.Warning)
            return
        self._open_bean_sheet_from_scan(bean_uuid)

    @pyqtSlot()
    def open_profile_maintenance(self) -> None:
        if not self.alog_directory or not Path(self.alog_directory).is_dir():
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Directory Error"),
                QApplication.translate("tilauscope_beancave",
                    "Please select a valid ALog directory first."))
            return
        from tilauscope.alog_repair import AlogRepairDialog
        self._alog_repair_dlg = AlogRepairDialog(self, self.aw)  # keep ref (non-modal)
        self._alog_repair_dlg.repaired.connect(lambda _p: self.trigger_cache_refresh())
        self._alog_repair_dlg.show()

    def populate_table(self) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans') or not self.is_directory_defined:
            return

        self.datatable.setSortingEnabled(False)
        beans = self.cave.green_beans

        self.datatable.setRowCount(len(beans))
        self.datatable.setColumnCount(len(GREEN_BEAN_COLUMNS))
        self.datatable.clearSelection()

        def safe_float(val):
            try:
                return float(str(val).replace(',', '.'))
            except ValueError:
                return 0.0

        for row, bean in enumerate(beans):
            for col, value_fn in enumerate(GREEN_BEAN_COLUMNS):
                try:
                    value = value_fn(bean)
                except Exception as e:
                    _log.error(f"Error processing bean {bean.name}: {e}")
                    value = "Error"
                    continue
                item = QTableWidgetItem(value)
                if col in [6,7,8,9,10,11,14,16,17,18]: # Numeric fields to align right
                    item.setData(Qt.ItemDataRole.EditRole, safe_float(value))
                if col == 0:
                    # stash the bean uuid on the first column so a row can be
                    # resolved back to its green_beans entry regardless of visual order.
                    item.setData(Qt.ItemDataRole.UserRole, getattr(bean, 'uuid', ''))
                self.datatable.setItem(row, col, item)
            # catalogue color codes (design v4 §2):
            # out-of-stock rows dimmed; crop-age badge on the Crop cell.
            try:
                if (getattr(bean, 'weight_left', 0.0) or 0.0) <= 0:
                    _dim = QColor(THEME['OVERLAY0'])  # Catppuccin overlay0
                    for _c in range(len(GREEN_BEAN_COLUMNS)):
                        _it = self.datatable.item(row, _c)
                        if _it is not None:
                            _it.setForeground(_dim)
                _crop = int(getattr(bean, 'crop', 0) or 0)
                # crop == 0 (unset) is excluded — it is not a 2026-year-old harvest
                if _crop > 0:
                    _age = datetime.now().year - _crop
                    _crop_it = self.datatable.item(row, 6)
                    if _crop_it is not None and _age >= 2:
                        _crop_it.setForeground(QColor(THEME['CRITICAL'] if _age >= 3 else THEME['WARNING']))
                        _f = _crop_it.font()
                        _f.setBold(True)
                        _crop_it.setFont(_f)
                        _crop_it.setToolTip(QApplication.translate(
                            "tilauscope_beancave", "Harvest is {0} years old").format(_age))
            except Exception as e:
                _logd.debug(f"color-code row {row} skipped: {e}")
        self.datatable.setRowCount(len(self.cave.green_beans)) # fix 2026/03/30 wrong indent, was called a lot inside the loop, now called once at the end to adjust to the final number of beans after processing
        self.datatable.clearSelection() # Clear existing selection
        # Qt's built-in sort is deliberately left OFF: green_beans (the list)
        # is the single source of truth and every accessor indexes it by visual row.
        # Header clicks reorder the list via sort_by_column() then repopulate, so the
        # visual order and the list order can never diverge. (fix: dual-sort desync)
        self.datatable.setSortingEnabled(False)

        # Lot 5: refresh the visible rich list from the same beans
        if hasattr(self, 'catalogue_list'):
            self.catalogue_list.set_beans(beans)

        self.update_ui_visibility()

        if len(beans) ==0:
            # by default disable all buttons
            self.add_button.setEnabled(True)
            self.clear_button.setEnabled(False)
            self.generate_label_button.setEnabled(False)
            self.inject_from_ai_button.setEnabled(False)
            self.update_button.setEnabled(False)
            self.generate_qr_button.setEnabled(False)
            self.generate_card_button.setEnabled(False)
            self.roast.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.new_crop_button.setEnabled(False)

        elif len(beans) > 0:
            # Select the first row, which will trigger load_selected_bean_into_form
            self.datatable.selectRow(0)
            # Lot 5: datatable stays hidden — the rich list is the view
            self.add_button.setEnabled(True)
            self.clear_button.setEnabled(False)
            self.generate_label_button.setEnabled(True)
            self.inject_from_ai_button.setEnabled(True)
            self.update_button.setEnabled(False)
            self.generate_qr_button.setEnabled(True)
            self.generate_card_button.setEnabled(True)
            self.roast.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.new_crop_button.setEnabled(True)
        else:
            # If the table is empty, ensure the form is cleared
            self.clear_form()
        # Keep the Roast Plan tab selectors in sync
        self._populate_plan_bean_combo()

    @pyqtSlot()
    def load_selected_bean_into_form(self) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return
        selected_rows = self.datatable.selectionModel().selectedRows() # type: ignore
        if not selected_rows:
            self.clear_form()
            # freeze the buttons
            self.update_button.setEnabled(False)
            self.generate_qr_button.setEnabled(False)
            self.generate_card_button.setEnabled(False)
            self.roast.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.new_crop_button.setEnabled(False)
            return

        row = selected_rows[0].row() # Prend la première ligne sélectionnée
        if row < len(self.cave.green_beans):
            bean = self.cave.green_beans[row]
            self.name_input.setText(bean.name)
            self.farm_input.setText(bean.farm)
            self.country_combo.setCurrentText(bean.country)
            self.supplier_input.setText(bean.supplier)

            self.category_process_combo.setCurrentText(bean.category if bean.category else "")
            self._update_methods(bean.category)
            self.process_combo.setCurrentText(bean.process if bean.process else "")

            self.crop_input.setValue(bean.crop)
            self._update_crop_age_indicator(int(bean.crop))  # true value (0 = unset, no colour)
            self.density_input.setValue(bean.density)
            self.last_humidity_input.setValue(bean.last_humidity)
            self.water_activity_input.setValue(bean.water_activity)
            self._update_physical_qualifiers()  # unchanged values emit no signal
            self.altitude_input.setValue(bean.altitude)
            self.weight_input.setValue(bean.weight)

            self.species_combo.setCurrentText(bean.species if bean.species else "")
            self._update_variety(bean.species)
            self.varieties_combo.setCurrentText(bean.varieties if bean.varieties else "")

            self.weight_left_input.setValue(bean.weight_left)
            self.flavour_notes_input.setText(bean.flavour_notes)
            self.sca_input.setValue(bean.sca)
            self._set_form_sacks(getattr(bean, 'sacks', None) or [])

            # --- Blend Fields ---
            if bean.is_blend:
                self.type_combo.setCurrentText("Blend")
            else:
                self.type_combo.setCurrentText("Single Origin")

            self._update_blend_component_list() # Met à jour la liste des grains disponibles

            self.bean1_ratio_input.setValue(bean.bean1_ratio)
            # Assurez-vous que le texte est dans la liste avant de définir
            bean2_text = bean.bean2_name if bean.bean2_name else QApplication.translate("tilauscope_beancave","N/A - Select a bean")
            if bean2_text in [self.bean2_combo.itemText(i) for i in range(self.bean2_combo.count())]:
                self.bean2_combo.setCurrentText(bean2_text)
            else:
                self.bean2_combo.setCurrentIndex(0) # Sinon, sélectionnez le défaut
            self.bean2_ratio_input.setValue(bean.bean2_ratio)

            bean3_text = bean.bean3_name if bean.bean3_name else QApplication.translate("tilauscope_beancave","N/A - Select a bean")
            if bean3_text in [self.bean3_combo.itemText(i) for i in range(self.bean3_combo.count())]:
                self.bean3_combo.setCurrentText(bean3_text)
            else:
                self.bean3_combo.setCurrentIndex(0) # Sinon, sélectionnez le défaut
            self.bean3_ratio_input.setValue(bean.bean3_ratio)

            self.blend_notes_input.setText(bean.blend_notes)
            # --------------------

            # ── V2 : mise à jour notice bar ─────────────────────────────
            if hasattr(self, '_notice_name_label'):
                self._notice_name_label.setText(bean.name or "—")

            if hasattr(self, '_type_tag_label'):
                if bean.is_blend:
                    self._type_tag_label.setText(QApplication.translate("tilauscope_beancave","Blend"))
                    self._type_tag_label.setStyleSheet(
                        f"background:rgba(166,227,161,25);border:1px solid rgba(166,227,161,60);"
                        f"border-radius:4px;color:{THEME['SUCCESS']};font-size:10px;padding:1px 6px;"
                    )
                else:
                    self._type_tag_label.setText(QApplication.translate("tilauscope_beancave","Single Origin"))
                    self._type_tag_label.setStyleSheet(
                        f"background:{tint('ACCENT', 25)};border:1px solid {tint('ACCENT', 60)};"
                        f"border-radius:4px;color:{THEME['ACCENT']};font-size:10px;padding:1px 6px;"
                    )
            # now update roast plan accordingly
            self._update_roast_plan_ui_state()
            self.update_button.setEnabled(True)
            self.generate_qr_button.setEnabled(True)
            self.generate_card_button.setEnabled(True)
            # Only allow roasting a bean that is actually in stock.
            in_stock = (getattr(bean, "weight_left", 0.0) or 0.0) > 0
            self.roast.setEnabled(in_stock)
            self.roast.setToolTip(
                QApplication.translate("tilauscope_beancave", "Start a roast with this bean")
                if in_stock else
                QApplication.translate("tilauscope_beancave", "Out of stock — refill this bean before roasting")
            )
            self.remove_button.setEnabled(True)

            # Lot 5: refresh the read sheet and return to it
            if hasattr(self, 'bean_sheet'):
                self.bean_sheet.set_bean(bean)
                self._right_stack.setCurrentIndex(0)

        else:
            self.clear_form()

    def _update_crop_age_indicator(self, crop: int) -> None:
        """Colour the crop field by harvest age (orange = 2y, red = 3y+).

        crop == 0 (unset) clears the indicator — note the spinbox clamps to
        its 2020 minimum, so explicit calls with the bean's true crop value
        (load/clear paths) win over the clamped valueChanged signal.
        """
        try:
            color = None
            age = 0
            if crop > 0:
                age = datetime.now().year - crop
                if age >= 3:
                    color = THEME['CRITICAL']
                elif age == 2:
                    color = THEME['WARNING']
            base_tip = QApplication.translate("tilauscope_beancave", "Year of Harvesting.")
            if color:
                self.crop_input.setStyleSheet(
                    self._crop_base_style +
                    f"TilauSpinBox {{ color: {color}; }}")
                self.crop_input.setToolTip(base_tip + " " + QApplication.translate(
                    "tilauscope_beancave", "Harvest is {0} years old").format(age))
            else:
                self.crop_input.setStyleSheet(self._crop_base_style)
                self.crop_input.setToolTip(base_tip)
        except Exception as e:
            _logd.debug(f"crop age indicator skipped: {e}")

    # ── physical measures: plain-language qualifier ──────────────
    # Words and bands live in bean_qualifiers, shared with the read-only bean
    # sheet, so a field can never read "normal" where the sheet flags it.
    def _update_physical_qualifier(self, kind: str, value: float) -> None:
        """Append the qualifier to the field suffix and colour the field."""
        try:
            widget = {'density': self.density_input,
                      'humidity': self.last_humidity_input,
                      'aw': self.water_activity_input}[kind]
            word, color = physical_qualifier(kind, value)
            base = self._phys_base_suffix[kind]
            widget.setSuffix(f"{base} ({word})" if word else base)
            style = self._phys_base_style[kind]
            if color:
                style += f"TilauSpinBox {{ color: {color}; }}"
            widget.setStyleSheet(style)
        except Exception as e:
            _logd.debug(f"physical qualifier skipped ({kind}): {e}")

    def _update_physical_qualifiers(self) -> None:
        """Refresh all three qualifiers — for paths that set values silently."""
        self._update_physical_qualifier('density', self.density_input.value())
        self._update_physical_qualifier('humidity', self.last_humidity_input.value())
        self._update_physical_qualifier('aw', self.water_activity_input.value())

    # ── sack chips (design v4 §6) ────────────────────────────────
    def _set_form_sacks(self, sacks: list[str]) -> None:
        """Mirror a bean's sack list into the form chips (label + row hidden when empty)."""
        self._current_sacks = list(sacks or [])
        self.sack_chips.set_sacks(self._current_sacks)
        self._sacks_lbl.setVisible(bool(self._current_sacks))

    @pyqtSlot(str)
    def _on_sack_released(self, sack_id: str) -> None:
        """✕ on a chip: the physical bag is empty — detach the label from the
        bean, persist, and return the label to the reusable pool."""
        try:
            if self.cave is None or not hasattr(self.cave, 'green_beans'):
                return
            if not confirm_release(self, sack_id):
                return
            row = self.datatable.currentRow()
            if 0 <= row < len(self.cave.green_beans):
                bean = self.cave.green_beans[row]
                bean.sacks = [s for s in (getattr(bean, 'sacks', None) or []) if s != sack_id]
                self.save_green_beans()
                SackPool.release(sack_id)
                self._set_form_sacks(bean.sacks)
                # Lot 5: reflect the release on the sheet and the list
                if hasattr(self, 'bean_sheet'):
                    self.bean_sheet.set_bean(bean)
                if hasattr(self, 'catalogue_list') and self.cave is not None:
                    self.catalogue_list.set_beans(self.cave.green_beans)
                _logd.debug(f"Sack {sack_id} released from '{bean.name}' back to the free pool")
        except Exception as e:
            _logd.error(f"Sack release failed for {sack_id}: {e}")


    @pyqtSlot()
    def update_selected_bean(self) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        selected_row_index = self.datatable.currentRow()

        if selected_row_index == -1:
            _logd.warning("No row selected for update.")
            return

        if selected_row_index < len(self.cave.green_beans):
            # Create a new GreenBean object with the current form data
            existing_bean = self.cave.green_beans[selected_row_index]
            current_count = existing_bean.count
            # captured before the record is replaced, to detect the 0 g
            # transition once the new values are in (design v4 §9.3).
            prev_weight_left = float(getattr(existing_bean, 'weight_left', 0.0) or 0.0)
            # Déterminer si le type est 'Blend' pour nettoyer les champs inutiles
            is_blend_selected = self.type_combo.currentText() == "Blend"
            new_bean_data = GreenBean(
                name=self.name_input.text(),
                farm=self.farm_input.text(),
                country=self.country_combo.currentText(),
                supplier=self.supplier_input.text(),
                category=self.category_process_combo.currentText(),
                process=self.process_combo.currentText(),
                crop=int(self.crop_input.value()),
                density=self.density_input.value(),
                last_humidity=self.last_humidity_input.value(),
                water_activity=self.water_activity_input.value(),
                altitude=int(self.altitude_input.value()),
                species=self.species_combo.currentText(),
                varieties=self.varieties_combo.currentText(),
                weight_left=self.weight_left_input.value(),
                flavour_notes=self.flavour_notes_input.text(),
                sca=self.sca_input.value(),
                count=current_count,
                weight=existing_bean.weight,  # preserve roasted total on update
                # --- Blend Fields (Mis à jour) ---
                is_blend=is_blend_selected,
                bean1_ratio=self.bean1_ratio_input.value(),
                bean2_name=self.bean2_combo.currentText() if is_blend_selected else '',
                bean2_ratio=self.bean2_ratio_input.value() if is_blend_selected else 0.0,
                bean3_name=self.bean3_combo.currentText() if is_blend_selected else '',
                bean3_ratio=self.bean3_ratio_input.value() if is_blend_selected else 0.0,
                blend_notes=self.blend_notes_input.text(),
                # unique identifier
                uuid=existing_bean.uuid, # preserve uuid
                # tips
                tips=existing_bean.tips,
                sacks=list(self._current_sacks),  # preserve sack labels on update
                # Fields managed by other BeanCave views must survive an edit
                # performed from this form.
                conditioning=existing_bean.conditioning,
                dial_ins=list(existing_bean.dial_ins),
            )
            self.cave.green_beans[selected_row_index] = new_bean_data
            if existing_bean.uuid != new_bean_data.uuid:
                self.uuidmap.pop(existing_bean.uuid, None)
            self.uuidmap[new_bean_data.uuid] = new_bean_data
            _logd.debug(f"Green bean updated at {selected_row_index}: {new_bean_data.name}")
            self.save_green_beans()
            # stock just hit 0 g: offer to reclaim this bean's labels
            # (design v4 §9.3, shared helper — never duplicate this check).
            if prompt_release_if_emptied(self, new_bean_data, prev_weight_left, self.save_green_beans):
                self._set_form_sacks(new_bean_data.sacks)
            self.populate_table()

            # Find the updated item and scroll to it
            updated_items = self.datatable.findItems(new_bean_data.name, Qt.MatchFlag.MatchExactly)
            if updated_items:
                updated_item = updated_items[0]
                self.datatable.scrollToItem(updated_item, QAbstractItemView.ScrollHint.PositionAtTop)
                self.datatable.selectRow(updated_item.row())
        else:
            _logd.warning(f"Invalid row selected for update: {selected_row_index}")

    def refresh_home(self) -> None:
        """Refresh the home view when returning to BeanCave after a roast (headless).

        Green-bean edits — including the roast's stock decrease — are already
        persisted to disk by update_selected_bean(), so reloading from disk is
        safe and picks up the latest stock. trigger_cache_refresh() re-indexes the
        .alog roast history so computed fields (e.g. Total roasted) are current.
        """
        try:
            self.load_green_beans()
            self.populate_table()
        except Exception:  # noqa: BLE001
            _logd.exception("BeanCave refresh_home: reload/populate failed")
        try:
            self.trigger_cache_refresh()
        except Exception:  # noqa: BLE001
            _logd.exception("BeanCave refresh_home: cache refresh failed")

    @pyqtSlot()
    def confirm_and_delete(self):
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        selected_rows = self.datatable.selectionModel().selectedRows() # type: ignore
        if not selected_rows or len(selected_rows)>1:
            return
        bean:GreenBean  = self.cave.green_beans[selected_rows[0].row()]
        # Lot 5: styled confirmation (same dialog family as the rest)
        reply = show_styled_message(
            self,
            QApplication.translate("tilauscope_beancave", "Confirm Deletion"),
            QApplication.translate("tilauscope_beancave",
                "Delete <b>{0}</b>?<br>This action cannot be undone.").format(bean.name),
            QMessageBox.Icon.Question,
            rich=True,
            width=420,
            buttons=[
                QApplication.translate("tilauscope_beancave", "Delete"),
                QApplication.translate("tilauscope_beancave", "Cancel"),
            ],
        )
        if reply == 0:
            self.remove_green_bean(selected_rows[0])
            _logd.debug(f"Bean {bean.name} deleted.")
        else:
            _logd.debug("Deletion cancelled.")

    def remove_green_bean(self, index:QModelIndex) -> None:
        removed_bean = self.cave.green_beans[index.row()]
        del self.cave.green_beans[index.row()]
        self.uuidmap.pop(removed_bean.uuid, None)
        self.save_green_beans()
        self.populate_table()
        self.clear_form()


    @pyqtSlot(int)
    def sort_by_column(self, column_index: int) -> None:
        # Déterminer la clé de tri en fonction de l'index de la colonne
        sort_key_map = {
            0: 'name',
            1: 'farm',
            2: 'country',
            3: 'supplier',
            4: 'category',
            5: 'process',
            6: 'crop',
            7: 'density',
            8: 'last_humidity',
            9: 'water_activity',
            10: 'altitude',
            11: 'species',
            12: 'varieties',
            13: 'weight_left',
            14: 'flavour_notes',
            15: 'sca',
            16: 'count',
            17: 'weight',
        }

        sort_key = sort_key_map.get(column_index)
        if not sort_key:
            return

        # Basculer l'ordre de tri si la même colonne est cliquée à nouveau
        if self.last_sorted_column == column_index:
            if self.sort_order == Qt.SortOrder.AscendingOrder:
                self.sort_order = Qt.SortOrder.DescendingOrder
            else:
                self.sort_order = Qt.SortOrder.AscendingOrder
        else:
            self.sort_order = Qt.SortOrder.AscendingOrder

        self.last_sorted_column = column_index

        # To this (handles numeric conversion safely):
        def get_sortable_val(bean, key):
            val = getattr(bean, key)
            if key in ['weight', 'stock', 'sca', 'density', 'crop', 'count', 'last_humidity', 'water_activity', 'altitude', 'weight_left', 'bean1_ratio', 'bean2_ratio', 'bean3_ratio']:
                try:
                    return float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    return 0.0
            return str(val).lower()

        # Remember the selected bean so we can restore the highlight after the rebuild.
        selected_uuid = ""
        cur = self.datatable.currentItem()
        if cur is not None:
            anchor = self.datatable.item(cur.row(), 0)
            if anchor is not None:
                selected_uuid = anchor.data(Qt.ItemDataRole.UserRole) or ""

        self.cave.green_beans.sort(key=lambda b: get_sortable_val(b, sort_key),
                    reverse=(self.sort_order == Qt.SortOrder.DescendingOrder))

        # Sorting reorders the list; rebuild the table so the visual order
        # matches green_beans exactly (Qt's built-in sort is disabled — see populate_table).
        self.populate_table()
        self.datatable.horizontalHeader().setSortIndicator(column_index, self.sort_order) # type: ignore

        # Restore the previous selection by uuid (populate_table defaults to row 0).
        if selected_uuid:
            for r in range(self.datatable.rowCount()):
                anchor = self.datatable.item(r, 0)
                if anchor is not None and anchor.data(Qt.ItemDataRole.UserRole) == selected_uuid:
                    self.datatable.selectRow(r)
                    break

    def _is_readable_directory(self, directory:Path) -> bool:
        try:
            return directory.exists() and directory.is_dir() and os.access(str(directory), os.R_OK)
        except Exception as e:
            _logd.error(f'Error checking directory readability for {directory}: {e}')
            return False

    def _is_readable_file(self, file_path:Path) -> bool:
        try:
            return file_path.exists() and file_path.is_file() and os.access(str(file_path), os.R_OK)
        except Exception as e:
            _logd.error(f'Error checking file readability for {file_path}: {e}')
            return False

    def load_green_beans(self, selection: str | None = None) -> None:
        beancave_file_path = Path(self.beancave_directory).expanduser() / BEANCAVE_FILE_NAME

        if beancave_file_path != '' and self._is_readable_directory(Path(self.beancave_directory)) and self._is_readable_file(beancave_file_path):
            try:
                content = beancave_file_path.read_text(encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8')
                self.cave = BeanCaveContainer.from_json(content)
                self.green_beans = self.cave.green_beans
                updated = False
                for bean in self.green_beans:
                    if not hasattr(bean, 'uuid') or bean.uuid is None or bean.uuid == "":
                        bean.uuid = str(uuid.uuid4())
                        updated = True
                    # Older records stored 500.0 as the "empty" sentinel (the field's
                    # former minimum); normalise it to 0 so the roast plan skips the
                    # structure adjustment instead of treating it as a real density.
                    if float(getattr(bean, 'density', 0.0) or 0.0) == 500.0:
                        bean.density = 0.0
                        updated = True
                self.uuidmap = {bean.uuid: bean for bean in self.green_beans if hasattr(bean, 'uuid') and bean.uuid is not None}
                if updated:
                    self.save_green_beans()
            except json.JSONDecodeError as e:
                _logd.error(f'Error reading beancave.json: {e}')
                self._show_message(
                    self, QApplication.translate("tilauscope_beancave","Read Error"),
                    QApplication.translate("tilauscope_beancave","Unable to read file") +
                    f" '{beancave_file_path}'. " +
                    QApplication.translate("tilauscope_beancave","The file might be corrupted."), QMessageBox.Icon.Warning)
            except Exception as e:
                _logd.error(QApplication.translate("tilauscope_beancave","Unexpected error while reading beancave.json")+f": {e}")
                self._show_message(self, "Error", QApplication.translate("tilauscope_beancave","An unexpected error occurred")+f": {e}", QMessageBox.Icon.Warning)
            if selection is not None:
                self.green_beans.insert(0, GreenBean(name=selection))
        else:
            if beancave_file_path != "":
                _logd.error(QApplication.translate("tilauscope_beancave","Directory or file access is not possible"))
                self._show_message(self, "Error", QApplication.translate("tilauscope_beancave","Directory or file access is not possible"), QMessageBox.Icon.Warning)
            else:
                # call first bean assist
                _logd.debug("bean cave is empty, run first bean assistant")
            self.cave = None
            self.green_beans = []
            if selection is not None:
                self.green_beans.insert(0, GreenBean(name=selection))

    def save_green_beans(self) -> None:

        if self.beancave_directory is not None:
            # check if cave is not none before trying to save
            if self.cave is None or self.cave.green_beans is None:
                _logd.warning("No green beans to save.")
                return
            beancave_file_path = Path(self.beancave_directory) / BEANCAVE_FILE_NAME
            try:
                beancave_file_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(
                    beancave_file_path,
                    self.cave.to_json(),
                    encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8',
                )
            except Exception as e:
                _logd.error(f'Error writing to beancave.json: {e}')
                self._show_message(self,
                                    QApplication.translate("tilauscope_beancave","Save Error"),
                                    QApplication.translate("tilauscope_beancave","Unable to save file") + f" '{beancave_file_path}'. " +
                                    QApplication.translate("tilauscope_beancave","Error")+f": {e}", QMessageBox.Icon.Warning)
        else:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Save Error"),
                                QApplication.translate("tilauscope_beancave","Please select a directory to store the JSON beancave file and where your alog files are located. Then exit BeanCave and relaunch it!"),
                                QMessageBox.Icon.Warning)

    @pyqtSlot()
    def clear_form(self) -> None:
        self.name_input.clear()
        self.farm_input.clear()
        self.country_combo.setCurrentIndex(0)
        self.supplier_input.clear()
        self.category_process_combo.setCurrentIndex(0)
        self.process_combo.setCurrentIndex(0)
        self.crop_input.setValue(0)
        self._update_crop_age_indicator(0)  # cleared form shows no age colour
        self.density_input.setValue(0.0)
        self.last_humidity_input.setValue(0.0)
        self.water_activity_input.setValue(0.0)
        self._update_physical_qualifiers()  # cleared form shows no qualifier
        self.altitude_input.setValue(0.0)
        self.species_combo.setCurrentIndex(0)
        self.varieties_combo.setCurrentIndex(0)
        self.weight_left_input.setValue(0.0)
        self.flavour_notes_input.clear()
        self.sca_input.setValue(0.0)
        self._set_form_sacks([])
        # --- Blend Fields ---
        self.type_combo.setCurrentText("Single Origin")
        self.bean1_ratio_input.setValue(100.0)
        self.bean2_combo.setCurrentIndex(0)
        self.bean2_ratio_input.setValue(0.0)
        self.bean3_combo.setCurrentIndex(0)
        self.bean3_ratio_input.setValue(0.0)
        self.blend_notes_input.clear()
        # --------------------
        # Lot 5: empty selection → empty sheet
        if hasattr(self, 'bean_sheet'):
            self.bean_sheet.clear()

    def createdatatable(self) -> None:
        headers = greencave_headers
        self.datatable.setColumnCount(len(headers))
        self.datatable.setHorizontalHeaderLabels(headers)
        self.datatable.horizontalHeader().setSectionsMovable(True) # type: ignore
        self.datatable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # type: ignore
        self.datatable.itemSelectionChanged.connect(self.load_selected_bean_into_form)
        self.datatable.itemSelectionChanged.connect(self._sync_catalogue_selection)  # Lot 5
        self.datatable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)  # type: ignore
        self.datatable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows) # type: ignore
        # Built-in sort stays OFF — sort_by_column() owns ordering (see populate_table).
        self.datatable.setSortingEnabled(False)
        self.datatable.horizontalHeader().sectionClicked.connect(self.sort_by_column) # type: ignore

    def restore_table_state(self) -> None:
        settings = QSettings()
        header:QHeaderView = self.datatable.horizontalHeader() #type:ignore

        order_str = settings.value('BeanCaveColumnOrder', None, str)
        if order_str:
            try:
                logical_indices = [int(i) for i in order_str.split(',')]
                if len(logical_indices) == header.count():
                    for visual_index, logical_index in enumerate(logical_indices):
                        header.moveSection(header.visualIndex(logical_index), visual_index)
                else:
                    _logd.warning("Saved column order does not match current column count. Ignoring saved state.")
            except (ValueError, IndexError) as e:
                _logd.error(f"Error restoring column order from settings: {e}")

        for i in range(header.count()):
            key = f'BeanCaveColumnWidth/{i}'
            if settings.contains(key):
                width = settings.value(key, header.sectionSize(i), type=int)
                header.resizeSection(i, width)

    @pyqtSlot()
    def on_click_select_flavor(self):
        dialog = FlavorSelectorDialog(current_notes=self.flavour_notes_input.text(), parent=self)

        if dialog.exec():
            # Mise à jour de la structure
            self.flavour_notes_input.setText(dialog.get_notes())
            _logd.debug(f"Nouvelles notes : {self.flavour_notes_input}")

    @pyqtSlot()
    def on_click_ai_parse(self):
        dlg = URLInputDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return # User cancelled
        url_to_analyze = dlg.url_input.text().strip()
        if not url_to_analyze:
            return

        # Who receives the page text must be named once per provider.
        from tilauscope.tilau_privacy_ui import (  # noqa: PLC0415
            Gate, ensure_ai_disclosure, show_roast_blocked,
        )
        gate = ensure_ai_disclosure(self, getattr(self, 'ai', None), getattr(self, 'aw', None))
        if gate is Gate.BLOCKED_ROAST:
            show_roast_blocked(self)
            return
        if gate is not Gate.ALLOW:
            return

        # 1. Create and show the non-blocking "Waiting" dialog (frameless/themed,
        # no cancel button so the background thread can't be interrupted mid-flight)
        self.ai_progress = TilauProgressDialog(
            QApplication.translate("tilauscope_beancave", "Reading the supplier page…"),
            self, None, SVG_PROG_AI,
            QApplication.translate("tilauscope_beancave", "about 20 seconds"))
        self.ai_progress.show()

        # 2. Setup the background thread
        self.ai_thread = QThread()

        self.ai_worker = BeanAIWorker(self.ai,
                                      url_to_analyze,
                                      self.coffee_beans_categories,
                                      self.coffee_processing_methods,
                                      self.coffee_producing_countries,
                                      self.coffee_bean_types,
                                      self.coffee_beans_species)
        self.ai_worker.moveToThread(self.ai_thread)

        # Connect signals
        self.ai_worker.finished.connect(self._on_bean_ai_finished)
        self.ai_worker.error.connect(self._on_bean_ai_error)
        self.ai_thread.started.connect(self.ai_worker.run)

        # Cleanup
        self.ai_worker.finished.connect(self.ai_thread.quit)
        self.ai_worker.finished.connect(self.ai_worker.deleteLater)
        self.ai_worker.error.connect(self.ai_thread.quit)        # error ne quittait pas le thread
        self.ai_worker.error.connect(self.ai_worker.deleteLater)
        self.ai_worker.cancelled.connect(self.ai_thread.quit)
        self.ai_worker.cancelled.connect(self.ai_worker.deleteLater)
        self.ai_thread.finished.connect(self.ai_thread.deleteLater)

        self.ai_thread.start()

    def _on_bean_ai_finished(self, bean: GreenBean):
        """Updates the form using direct attribute access."""
        self.ai_progress.close()

        if not bean:
            return

        def update_combo(combo: QComboBox, value:str) -> None:
            if value == '':
                return
            index = combo.findText(value)
            if index > 0:
                combo.setCurrentIndex(index)
            else: # fallback to last value if not found "(usually 'Other')"
                combo.setCurrentIndex(combo.count() - 1)
        self.name_input.setText(bean.name)
        self.farm_input.setText(bean.farm)
        self.supplier_input.setText(bean.supplier)
        self.flavour_notes_input.setText(bean.flavour_notes)
        self.crop_input.setValue(bean.crop)
        self.density_input.setValue(bean.density)
        self.last_humidity_input.setValue(bean.last_humidity)
        self.water_activity_input.setValue(bean.water_activity)
        self.altitude_input.setValue(bean.altitude)
        self.sca_input.setValue(bean.sca)

        update_combo(self.country_combo, bean.country)
        update_combo(self.category_process_combo, bean.category)
        update_combo(self.process_combo, bean.process)
        update_combo(self.species_combo, bean.species)
        update_combo(self.varieties_combo, bean.varieties)

        if bean.is_blend:
            self.type_combo.setCurrentIndex(1)  # Blend
            # Assuming bean.blend_ratios is a list of ratios for each bean in the blend
            self.bean1_ratio_input.setValue(bean.bean1_ratio)
            self.bean2_ratio_input.setValue(bean.bean2_ratio)
            self.bean3_ratio_input.setValue(bean.bean3_ratio)
            update_combo(self.bean2_combo, bean.bean2_name)
            update_combo(self.bean3_combo, bean.bean3_name)
        else:
            self.type_combo.setCurrentIndex(0)  # Single Origin

    def _on_bean_ai_error(self, message):
        self.ai_progress.close()
        self._show_message(self,
                            QApplication.translate("tilauscope_beancave","AI Error"),
                            QApplication.translate("tilauscope_beancave","Failed to extract bean data")+f": {message}",
                            QMessageBox.Icon.Warning)

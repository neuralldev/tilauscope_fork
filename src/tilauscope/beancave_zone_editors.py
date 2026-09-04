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
# Tilau 2025-2026

"""Targeted zone editors for the BeanCave bean sheet.

Each ✎ opens a modal dialog editing only one zone (essentials, provenance, characteristics, sensory) of the selected GreenBean; Save persists and reselects by uuid, Cancel leaves the record untouched.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tilauscope.tilauscope_types import THEME, TilauProgressDialog, show_styled_message
from tilauscope.header_icons import SVG_PROG_AI
from tilauscope.sack_manager import prompt_release_if_emptied  # sack reclaim (§9.3)

_logd = logging.getLogger('tilaudebug')

_MONO = "'JetBrains Mono', monospace"
_DIM = THEME['OVERLAY0']

from tilauscope.theme_qss import apply_tilau_theme


def _zone_title(zone: str) -> str:
    return {
        'essentials': QApplication.translate("tilauscope_beancave", "Essentials"),
        'provenance': QApplication.translate("tilauscope_beancave", "Provenance"),
        'characteristics': QApplication.translate("tilauscope_beancave", "Characteristics"),
        'sensory': QApplication.translate("tilauscope_beancave", "Sensory & notes"),
        'all': QApplication.translate("tilauscope_beancave", "New bean (expert)"),
    }.get(zone, QApplication.translate("tilauscope_beancave", "Edit"))



class _AwFloatWindow(QDialog):
    """Always-on-top card showing the live water-activity probe reading.

    Click the value to transfer it into the editor's Water activity field.
    """

    def __init__(self, parent: ZoneEditorDialog) -> None:
        super().__init__(parent, Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.FramelessWindowHint)
        # frameless translucent window: ground=False, else the grounded base
        # paints the rectangle opaque and squares off the rounded card.
        apply_tilau_theme(self, ground=False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._parent_dialog = parent
        self._value: float | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("awCard")
        card.setStyleSheet(f"""
            QFrame#awCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(4)
        header = QLabel("💧  " + QApplication.translate("tilauscope_beancave", "WATER ACTIVITY"))
        header.setProperty('variant', 'eyebrow')
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl = QLabel("––")
        self._value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_lbl.setProperty('variant', 'readout')
        self._value_lbl.setStyleSheet(f"color: {THEME['ACCENT']};")
        self._value_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value_lbl.setToolTip(QApplication.translate("tilauscope_beancave", "Click to transfer the reading"))
        self._value_lbl.mousePressEvent = self._on_clicked  # type: ignore[method-assign]
        self._hint_lbl = QLabel(QApplication.translate("tilauscope_beancave", "waiting for probe…"))
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:10px;")
        cl.addWidget(header)
        cl.addWidget(self._value_lbl)
        cl.addWidget(self._hint_lbl)
        outer.addWidget(card)
        self.adjustSize()

    def update_value(self, wa: float) -> None:
        self._value = wa
        self._value_lbl.setText(f"{wa:.2f}")
        self._hint_lbl.setText(QApplication.translate("tilauscope_beancave", "tap to use"))

    def set_status(self, text: str) -> None:
        self._hint_lbl.setText(text)

    def _on_clicked(self, _event) -> None:  # noqa: ANN001
        if self._value is not None:
            self._parent_dialog.receive_aw(self._value)


class ZoneEditorDialog(QDialog):
    """Modal editor for one zone of a GreenBean record."""

    def __init__(self, host, bean, zone: str, create: bool = False) -> None:
        # host: BeancaveDlg — lists, save/refresh, aw (scale manager).
        # zone 'all' stacks every section (expert Add); create=True appends
        # the bean to the catalogue on Save instead of updating in place.
        super().__init__(host)
        # frameless translucent window: ground=False, else the grounded base
        # paints the rectangle opaque and squares off the rounded card.
        apply_tilau_theme(self, ground=False)
        self._host = host
        self._bean = bean
        self._zone = zone
        self._create = create
        self._aw = getattr(host, 'aw', None)
        self._scale_window: QDialog | None = None
        self._scale_was_connected = False
        self._density_win: QDialog | None = None
        self._density_was_connected = False
        self._aw_win: _AwFloatWindow | None = None

        self.setWindowTitle(QApplication.translate("tilauscope_beancave", "Edit"))
        self.setMinimumWidth(720 if zone == 'all' else 560)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("ZoneEditorCard")
        card.setStyleSheet(f"""
            #ZoneEditorCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
                background: {THEME['BG']}; color: {THEME['TEXT']};
                font-size: 12px;
                selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 5px 8px; }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
            QPlainTextEdit:focus {{
                border: 1px solid {THEME['ACCENT']};
                background: {THEME['SURFACE']}; }}
            QComboBox {{ background: {THEME['BG']}; color: {THEME['TEXT']};
                font-size: 12px;
                selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']}; border-radius: 7px; padding: 5px 8px; }}
            QComboBox:focus {{ border: 1px solid {THEME['ACCENT']}; }}
            QComboBox QAbstractItemView {{ background: {THEME['SURFACE']};
                color: {THEME['TEXT']}; selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']}; }}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 16, 24, 18)
        lay.setSpacing(12)

        head = _zone_title(zone).upper()
        if bean.name and zone != 'all':
            head += f" — {bean.name.upper()}"
        title = QLabel(head)
        title.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:12px;"
            f"font-weight:800;letter-spacing:2px;")
        title.setWordWrap(True)
        if zone == 'all':
            head_row = QHBoxLayout()
            head_row.addWidget(title, 1)
            ai_btn = QPushButton("✨ " + QApplication.translate("tilauscope_beancave", "Fill from URL"))
            ai_btn.setStyleSheet(self._btn_style(THEME['ACCENT'], THEME['BORDER']))
            ai_btn.setToolTip(QApplication.translate("tilauscope_beancave",
                "Fetch a supplier's product page and let AI fill this form automatically."))
            ai_btn.clicked.connect(self._on_click_ai_parse)
            head_row.addWidget(ai_btn)
            lay.addLayout(head_row)
        else:
            lay.addWidget(title)
        sub = QLabel(
            QApplication.translate("tilauscope_beancave", "Fill what you know — everything can be refined later from the sheet.")
            if zone == 'all' else
            QApplication.translate("tilauscope_beancave", "Only this section is changed. Save writes the record immediately."))
        sub.setStyleSheet(f"color:{_DIM};font-size:11px;")
        lay.addWidget(sub)

        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setContentsMargins(0, 2, 0, 2)
        self._form.setHorizontalSpacing(14)
        self._form.setVerticalSpacing(9)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        if zone == 'all':
            for key in ('essentials', 'provenance', 'characteristics', 'sensory'):
                self._add_section_header(_zone_title(key))
                self._builders()[key]()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setWidget(self._form_host)
            scroll.setMinimumHeight(420)
            scroll.setMaximumHeight(560)
            lay.addWidget(scroll)
        else:
            lay.addWidget(self._form_host)
            builder = self._builders().get(zone)
            if builder is not None:
                builder()

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{THEME['BORDER']};")
        lay.addWidget(sep)

        nav = QHBoxLayout()
        nav.addStretch(1)
        cancel_btn = QPushButton(QApplication.translate("tilauscope_beancave", "Cancel"))
        cancel_btn.setStyleSheet(self._btn_style(THEME['SUBTEXT'], THEME['BORDER']))
        cancel_btn.clicked.connect(self.reject)
        nav.addWidget(cancel_btn)
        save_btn = QPushButton("✓ " + (QApplication.translate("tilauscope_beancave", "Create") if create else QApplication.translate("tilauscope_beancave", "Save")))
        save_btn.setStyleSheet(self._btn_style(THEME['SUCCESS'], THEME['SUCCESS'],
                                               "rgba(166,227,161,0.10)"))
        save_btn.clicked.connect(self._save)
        save_btn.setDefault(True)
        nav.addWidget(save_btn)
        lay.addLayout(nav)
        self._save_btn = save_btn

        if create:
            # Create stays greyed out until every required field (*) is filled
            self._wire_create_gate()
            self._refresh_create_gate()

    @staticmethod
    def _btn_style(color: str, border: str, bg: str = 'transparent') -> str:
        return (f"QPushButton {{ color:{color};background:{bg};"
                f"border:1px solid {border};border-radius:8px;"
                f"padding:6px 16px;font-size:12px; }}"
                f"QPushButton:hover {{ border-color:{THEME['ACCENT']};"
                f"color:{THEME['ACCENT']}; }}"
                f"QPushButton:disabled {{ color:{_DIM};background:transparent;"
                f"border:1px solid {THEME['BORDER']}; }}")

    def _req(self, label: str) -> str:
        """Mark a required field label with * in create mode."""
        return label[:-1] + " *:" if self._create and label.endswith(':') else label

    # ── zone builders ────────────────────────────────────────────────────────
    def _builders(self) -> dict:
        return {
            'essentials': self._build_essentials,
            'provenance': self._build_provenance,
            'characteristics': self._build_characteristics,
            'sensory': self._build_sensory,
        }

    def _add_section_header(self, title: str) -> None:
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            f"color:{_DIM};font-size:10px;"
            f"letter-spacing:2px;padding-top:8px;")
        self._form.addRow(lbl)

    def _build_essentials(self) -> None:
        b = self._bean
        self.name_edit = QLineEdit(b.name or "")
        self.name_edit.setMinimumWidth(300)
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Bean name:")), self.name_edit)

        self.country_combo = QComboBox()
        self.country_combo.setEditable(True)
        self.country_combo.setMinimumWidth(260)
        self.country_combo.addItems([""] + list(getattr(self._host, 'coffee_producing_countries', []) or []))
        self.country_combo.setCurrentText(b.country or "")
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Country:")), self.country_combo)

        self.crop_spin = QSpinBox()
        self.crop_spin.setRange(0, 2100)
        self.crop_spin.setSpecialValueText("—")
        crop_val = int(getattr(b, 'crop', 0) or 0)
        if crop_val == 0 and self._create:
            crop_val = datetime.now().astimezone().year
        self.crop_spin.setValue(crop_val)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Crop year:"), self.crop_spin)

        self.stock_spin = QDoubleSpinBox()
        self.stock_spin.setRange(0.0, 100000.0)
        self.stock_spin.setDecimals(0)
        self.stock_spin.setSuffix(" g")
        self.stock_spin.setValue(getattr(b, 'weight_left', 0.0) or 0.0)
        self.stock_spin.setToolTip(QApplication.translate("tilauscope_beancave", "Remaining stock. With a scale configured, click the ⚖ reading to capture the exact weight."))
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Stock:"), self.stock_spin)

    def _build_provenance(self) -> None:
        b = self._bean
        self.farm_edit = QLineEdit(b.farm or "")
        self.farm_edit.setMinimumWidth(300)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Farm:"), self.farm_edit)
        self.supplier_edit = QLineEdit(b.supplier or "")
        self.supplier_edit.setMinimumWidth(300)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Supplier:"), self.supplier_edit)
        self.altitude_spin = QSpinBox()
        self.altitude_spin.setRange(0, 5000)
        self.altitude_spin.setSuffix(" m")
        self.altitude_spin.setValue(int(getattr(b, 'altitude', 0) or 0))
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Altitude:"), self.altitude_spin)

    def _build_characteristics(self) -> None:
        b = self._bean
        host = self._host

        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(220)
        self.type_combo.addItems([QApplication.translate("tilauscope_beancave", "Single origin"), QApplication.translate("tilauscope_beancave", "Blend")])
        self.type_combo.setCurrentIndex(1 if getattr(b, 'is_blend', False) else 0)
        self.type_combo.currentIndexChanged.connect(self._refresh_blend_visibility)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Type:"), self.type_combo)

        # blend components (hidden for single origin)
        varieties_all = list((getattr(host, 'coffee_bean_types', {}) or {}).get('Arabica', []) or [])
        self._blend_w = QWidget()
        bl = QFormLayout(self._blend_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setHorizontalSpacing(14)
        bl.setVerticalSpacing(7)
        bl.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.bean1_ratio_spin = QDoubleSpinBox()
        self.bean1_ratio_spin.setRange(0.0, 100.0)
        self.bean1_ratio_spin.setDecimals(0)
        self.bean1_ratio_spin.setSuffix(" %")
        self.bean1_ratio_spin.setValue(getattr(b, 'bean1_ratio', 0.0) or 0.0)
        bl.addRow(QApplication.translate("tilauscope_beancave", "This bean:"), self.bean1_ratio_spin)
        self.bean2_combo = QComboBox()
        self.bean2_combo.setEditable(True)
        self.bean2_combo.addItems([""] + varieties_all)
        self.bean2_combo.setCurrentText(getattr(b, 'bean2_name', '') or "")
        self.bean2_ratio_spin = QDoubleSpinBox()
        self.bean2_ratio_spin.setRange(0.0, 100.0)
        self.bean2_ratio_spin.setDecimals(0)
        self.bean2_ratio_spin.setSuffix(" %")
        self.bean2_ratio_spin.setValue(getattr(b, 'bean2_ratio', 0.0) or 0.0)
        r2 = QHBoxLayout()
        r2.addWidget(self.bean2_combo, 1)
        r2.addWidget(self.bean2_ratio_spin)
        bl.addRow(QApplication.translate("tilauscope_beancave", "Component 2:"), r2)
        self.bean3_combo = QComboBox()
        self.bean3_combo.setEditable(True)
        self.bean3_combo.addItems([""] + varieties_all)
        self.bean3_combo.setCurrentText(getattr(b, 'bean3_name', '') or "")
        self.bean3_ratio_spin = QDoubleSpinBox()
        self.bean3_ratio_spin.setRange(0.0, 100.0)
        self.bean3_ratio_spin.setDecimals(0)
        self.bean3_ratio_spin.setSuffix(" %")
        self.bean3_ratio_spin.setValue(getattr(b, 'bean3_ratio', 0.0) or 0.0)
        r3 = QHBoxLayout()
        r3.addWidget(self.bean3_combo, 1)
        r3.addWidget(self.bean3_ratio_spin)
        bl.addRow(QApplication.translate("tilauscope_beancave", "Component 3:"), r3)
        self._form.addRow("", self._blend_w)

        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(260)
        self.category_combo.addItems([""] + list(getattr(host, 'coffee_beans_categories', []) or []))
        self.category_combo.setCurrentText(b.category or "")
        self.category_combo.currentTextChanged.connect(self._refresh_processes)
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Category:")), self.category_combo)

        self.process_combo = QComboBox()
        self.process_combo.setMinimumWidth(300)
        self._refresh_processes(b.category or "")
        self.process_combo.setCurrentText(b.process or "")
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Process:")), self.process_combo)

        self.species_combo = QComboBox()
        self.species_combo.setMinimumWidth(260)
        self.species_combo.addItems([""] + list(getattr(host, 'coffee_beans_species', []) or []))
        self.species_combo.setCurrentText(b.species or "")
        self.species_combo.currentTextChanged.connect(self._refresh_varieties)
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Species:")), self.species_combo)

        self.varieties_combo = QComboBox()
        self.varieties_combo.setEditable(True)
        self.varieties_combo.setMinimumWidth(320)
        self._refresh_varieties(b.species or "")
        self.varieties_combo.setCurrentText(b.varieties or "")
        self._form.addRow(self._req(QApplication.translate("tilauscope_beancave", "Varieties:")), self.varieties_combo)

        self.density_spin = QDoubleSpinBox()
        self.density_spin.setRange(0.0, 2000.0)
        self.density_spin.setDecimals(1)
        self.density_spin.setSuffix(" g/l")
        self.density_spin.setValue(getattr(b, 'density', 0.0) or 0.0)
        if self._zone == 'characteristics':
            # scale-piloted density measurement only in the targeted editor —
            # in the expert Add form the scale already serves the stock field
            measure_btn = QPushButton("⚖ " + QApplication.translate("tilauscope_beancave", "Measure"))
            measure_btn.setStyleSheet(self._btn_style(THEME['ACCENT'], THEME['BORDER']))
            measure_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Measure density with the connected scale (fixed-volume container)."))
            measure_btn.clicked.connect(self._open_density_window)
            dr = QHBoxLayout()
            dr.addWidget(self.density_spin, 1)
            dr.addWidget(measure_btn)
            self._form.addRow(QApplication.translate("tilauscope_beancave", "Density:"), dr)
        else:
            self._form.addRow(QApplication.translate("tilauscope_beancave", "Density:"), self.density_spin)

        self.humidity_spin = QDoubleSpinBox()
        self.humidity_spin.setRange(0.0, 100.0)
        self.humidity_spin.setDecimals(1)
        self.humidity_spin.setSuffix(" %")
        self.humidity_spin.setValue(getattr(b, 'last_humidity', 0.0) or 0.0)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Humidity:"), self.humidity_spin)

        self.wa_spin = QDoubleSpinBox()
        self.wa_spin.setRange(0.0, 2.0)
        self.wa_spin.setDecimals(2)
        self.wa_spin.setSingleStep(0.01)
        self.wa_spin.setValue(getattr(b, 'water_activity', 0.0) or 0.0)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Water activity:"), self.wa_spin)

        self._refresh_blend_visibility()

    def _build_sensory(self) -> None:
        b = self._bean
        self.sca_spin = QDoubleSpinBox()
        self.sca_spin.setRange(0.0, 100.0)
        self.sca_spin.setDecimals(1)
        self.sca_spin.setValue(getattr(b, 'sca', 0.0) or 0.0)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "SCA score:"), self.sca_spin)

        self.flavour_edit = QLineEdit(b.flavour_notes or "")
        self.flavour_edit.setMinimumWidth(280)
        wheel_btn = QPushButton("🎡 " + QApplication.translate("tilauscope_beancave", "Flavors"))
        wheel_btn.setStyleSheet(self._btn_style(THEME['ACCENT'], THEME['BORDER']))
        wheel_btn.clicked.connect(self._open_flavor_wheel)
        fr = QHBoxLayout()
        fr.addWidget(self.flavour_edit, 1)
        fr.addWidget(wheel_btn)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Flavour notes:"), fr)

        self.tips_edit = QPlainTextEdit(getattr(b, 'tips', '') or "")
        self.tips_edit.setFixedHeight(80)
        self._form.addRow(QApplication.translate("tilauscope_beancave", "Roasting tips / memo:"), self.tips_edit)

    # ── dynamic helpers ──────────────────────────────────────────────────────
    def _refresh_blend_visibility(self) -> None:
        self._blend_w.setVisible(self.type_combo.currentIndex() == 1)
        self.adjustSize()

    def _refresh_processes(self, category: str) -> None:
        methods = (getattr(self._host, 'coffee_processing_methods', {}) or {})
        current = self.process_combo.currentText()
        self.process_combo.blockSignals(True)
        self.process_combo.clear()
        self.process_combo.addItems([""] + list(methods.get(category, []) or []))
        self.process_combo.setCurrentText(current)
        self.process_combo.blockSignals(False)

    def _refresh_varieties(self, species: str) -> None:
        types = (getattr(self._host, 'coffee_bean_types', {}) or {})
        current = self.varieties_combo.currentText()
        self.varieties_combo.blockSignals(True)
        self.varieties_combo.clear()
        self.varieties_combo.addItems([""] + list(types.get(species, []) or []))
        self.varieties_combo.setCurrentText(current)
        self.varieties_combo.blockSignals(False)

    # ── AI fill from supplier URL (expert form only, Lot 5 restore) ─────────
    def _on_click_ai_parse(self) -> None:
        from tilauscope.cave.workers import BeanAIWorker
        from tilauscope.cave.widgets import URLInputDialog

        dlg = URLInputDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url_to_analyze = dlg.url_input.text().strip()
        if not url_to_analyze:
            return

        # Who receives the page text must be named once per provider.
        from tilauscope.tilau_privacy_ui import (  # noqa: PLC0415
            Gate, ensure_ai_disclosure, show_roast_blocked,
        )
        gate = ensure_ai_disclosure(self, getattr(self._host, 'ai', None), getattr(self._host, 'aw', None))
        if gate is Gate.BLOCKED_ROAST:
            show_roast_blocked(self)
            return
        if gate is not Gate.ALLOW:
            return

        self._ai_progress = TilauProgressDialog(
            QApplication.translate("tilauscope_beancave", "Reading the supplier page…"),
            self, None, SVG_PROG_AI,
            QApplication.translate("tilauscope_beancave", "about 20 seconds"))
        self._ai_progress.show()

        self._ai_thread = QThread()
        self._ai_worker = BeanAIWorker(
            getattr(self._host, 'ai', None),
            url_to_analyze,
            getattr(self._host, 'coffee_beans_categories', []),
            getattr(self._host, 'coffee_processing_methods', {}),
            getattr(self._host, 'coffee_producing_countries', []),
            getattr(self._host, 'coffee_bean_types', {}),
            getattr(self._host, 'coffee_beans_species', []))
        self._ai_worker.moveToThread(self._ai_thread)

        self._ai_worker.finished.connect(self._on_ai_parse_finished)
        self._ai_worker.error.connect(self._on_ai_parse_error)
        self._ai_thread.started.connect(self._ai_worker.run)

        self._ai_worker.finished.connect(self._ai_thread.quit)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)
        self._ai_worker.error.connect(self._ai_thread.quit)
        self._ai_worker.error.connect(self._ai_worker.deleteLater)
        self._ai_thread.finished.connect(self._ai_thread.deleteLater)

        self._ai_thread.start()

    def _on_ai_parse_finished(self, bean) -> None:
        self._ai_progress.close()
        if not bean:
            return

        def update_combo(combo: QComboBox, value: str) -> None:
            if value:
                combo.setCurrentText(value)

        self.name_edit.setText(bean.name)
        self.farm_edit.setText(bean.farm)
        self.supplier_edit.setText(bean.supplier)
        self.crop_spin.setValue(int(bean.crop or 0))
        self.altitude_spin.setValue(int(bean.altitude or 0))
        update_combo(self.country_combo, bean.country)

        self.category_combo.setCurrentText(bean.category or "")
        self._refresh_processes(bean.category or "")
        self.process_combo.setCurrentText(bean.process or "")
        self.species_combo.setCurrentText(bean.species or "")
        self._refresh_varieties(bean.species or "")
        self.varieties_combo.setCurrentText(bean.varieties or "")

        self.density_spin.setValue(float(bean.density or 0.0))
        self.humidity_spin.setValue(float(bean.last_humidity or 0.0))
        self.wa_spin.setValue(float(bean.water_activity or 0.0))
        self.sca_spin.setValue(float(bean.sca or 0.0))
        self.flavour_edit.setText(bean.flavour_notes)

        if getattr(bean, 'is_blend', False):
            self.type_combo.setCurrentIndex(1)
            self.bean2_combo.setCurrentText(bean.bean2_name or "")
            self.bean2_ratio_spin.setValue(float(bean.bean2_ratio or 0.0))
            self.bean3_combo.setCurrentText(bean.bean3_name or "")
            self.bean3_ratio_spin.setValue(float(bean.bean3_ratio or 0.0))
        else:
            self.type_combo.setCurrentIndex(0)
        self._refresh_blend_visibility()

    def _on_ai_parse_error(self, message: str) -> None:
        self._ai_progress.close()
        show_styled_message(self,
            QApplication.translate("tilauscope_beancave", "AI Error"),
            QApplication.translate("tilauscope_beancave", "Failed to extract bean data") + f": {message}",
            QMessageBox.Icon.Warning)

    # ── create gate: required fields drive the Create button ────────────────
    def _wire_create_gate(self) -> None:
        self.name_edit.textChanged.connect(self._refresh_create_gate)
        for combo in (self.country_combo, self.category_combo, self.process_combo,
                      self.species_combo, self.varieties_combo):
            combo.currentTextChanged.connect(self._refresh_create_gate)
            if combo.isEditable():
                combo.editTextChanged.connect(self._refresh_create_gate)

    def _refresh_create_gate(self, *_args) -> None:
        try:
            ready = all((
                bool(self.name_edit.text().strip()),
                bool(self.country_combo.currentText().strip()),
                bool(self.category_combo.currentText().strip()),
                bool(self.process_combo.currentText().strip()),
                bool(self.species_combo.currentText().strip()),
                bool(self.varieties_combo.currentText().strip()),
            ))
            self._save_btn.setEnabled(ready)
            self._save_btn.setToolTip(
                "" if ready else
                QApplication.translate("tilauscope_beancave", "Fill the required fields (*) : name, country, category, process, species, varieties."))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("create gate refresh failed")

    def _open_flavor_wheel(self) -> None:
        try:
            from tilauscope.tilau_wheel import FlavorSelectorDialog
            dlg = FlavorSelectorDialog(self.flavour_edit.text(), self)
            if dlg.exec():
                self.flavour_edit.setText(dlg.get_notes())
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("flavor wheel unavailable")

    # ── ⚖ Acaia capture on the stock field (essentials only) ────────────────
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._zone in ('essentials', 'all'):
            self._show_scale_window()
        if self._zone in ('characteristics', 'all'):
            self._show_aw_window()

    def _show_scale_window(self) -> None:
        try:
            sm = getattr(self._aw, 'scale_manager', None)
            if sm is None or not sm.is_scale1_configured():
                return
            if self._scale_window is None:
                from tilauscope.roast_properties import _ScaleFloatWindow
                self._scale_window = _ScaleFloatWindow(self)  # type: ignore[arg-type]
                self._scale_was_connected = sm.is_scale1_connected()
                sm.scale1_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.connect(self._scale_window.scale_disconnected)
                if not self._scale_was_connected:
                    sm.connect_scale1_signal.emit(False)
                else:
                    last = sm.get_scale1_last_weight()
                    if last is not None:
                        self._scale_window.update_weight(last)
            geo = self.geometry()
            self._scale_window.move(geo.right() + 12, geo.top() + 40)
            self._scale_window.show()
            self._scale_window.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("zone editor scale window unavailable")

    def receive_scale_weight(self, weight: float) -> None:
        # _ScaleFloatWindow contract: click on the live reading lands here.
        self.stock_spin.setValue(float(weight))

    def _teardown_scale(self) -> None:
        if self._scale_window is None:
            return
        sm = getattr(self._aw, 'scale_manager', None)
        if sm is not None:
            for _sig, _slot in (
                (sm.scale1_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_stable_weight_changed_signal, self._scale_window.update_weight),
                (sm.scale1_disconnected_signal, self._scale_window.scale_disconnected),
            ):
                try:
                    _sig.disconnect(_slot)
                except (TypeError, RuntimeError):
                    pass
            try:
                if not self._scale_was_connected:
                    sm.disconnect_scale1_signal.emit()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception("zone editor scale disconnect failed")
        self._scale_window.close()
        self._scale_window = None

    # ── 💧 Aw annex window (characteristics only) ────────────────────────────
    def _show_aw_window(self) -> None:
        try:
            dev = getattr(self._host, 'bleRoastSeeAGDevice', None)
            if dev is None and getattr(self._aw, 'bleRoastSeeAGDeviceName', None) is None:
                return  # no AquaGauge configured
            if self._aw_win is None:
                self._aw_win = _AwFloatWindow(self)
                # the host forwards every probe reading here while we are open
                self._host._aw_capture_cb = self._aw_win.update_value
                if dev is not None:
                    # seed with the probe's last reading — the AquaGauge only
                    # notifies on measurement events, not continuously
                    last = getattr(getattr(dev, 'ag', None), 'water_activity_read', 0.0) or 0.0
                    if last > 0:
                        self._aw_win.update_value(last)
                    if not getattr(dev, 'is_connected', False):
                        self._aw_win.set_status(QApplication.translate("tilauscope_beancave", "probe not connected…"))
                    # live connection state while the editor is open
                    dev.connected_signal.connect(self._on_aw_probe_connected)
                    dev.disconnected_signal.connect(self._on_aw_probe_disconnected)
            geo = self.geometry()
            # in the expert Add form the ⚖ scale window already sits at the top
            self._aw_win.move(geo.right() + 12,
                              geo.top() + (170 if self._zone == 'all' else 40))
            self._aw_win.show()
            self._aw_win.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("aw annex window unavailable")

    def receive_aw(self, wa: float) -> None:
        self.wa_spin.setValue(float(wa))

    def _on_aw_probe_connected(self) -> None:
        if self._aw_win is not None:
            self._aw_win.set_status(QApplication.translate("tilauscope_beancave", "probe connected — measure to read"))

    def _on_aw_probe_disconnected(self) -> None:
        if self._aw_win is not None:
            self._aw_win.set_status(QApplication.translate("tilauscope_beancave", "probe not connected…"))

    def _teardown_aw(self) -> None:
        if self._aw_win is None:
            return
        try:
            if getattr(self._host, '_aw_capture_cb', None) is self._aw_win.update_value:
                self._host._aw_capture_cb = None
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("aw capture unregister failed")
        dev = getattr(self._host, 'bleRoastSeeAGDevice', None)
        if dev is not None:
            for _sig, _slot in ((dev.connected_signal, self._on_aw_probe_connected),
                                (dev.disconnected_signal, self._on_aw_probe_disconnected)):
                try:
                    _sig.disconnect(_slot)
                except (TypeError, RuntimeError):
                    pass
        self._aw_win.close()
        self._aw_win = None

    # ── ⚖ scale-piloted density window (characteristics only) ───────────────
    def _open_density_window(self) -> None:
        try:
            sm = getattr(self._aw, 'scale_manager', None)
            if sm is None or not sm.is_scale1_configured():
                show_styled_message(
                    self, QApplication.translate("tilauscope_beancave", "No scale configured"),
                    QApplication.translate("tilauscope_beancave", "Configure scale 1 in Artisan to measure density."))
                return
            if self._density_win is None:
                from tilauscope.cave.widgets import _DensityFloatWindow
                self._density_win = _DensityFloatWindow(self)
                self._density_win.density_picked.connect(self._receive_density)
                self._density_win.tare_requested.connect(sm.tare_scale1_signal.emit)
                self._density_was_connected = sm.is_scale1_connected()
                sm.scale1_weight_changed_signal.connect(self._density_win.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._density_win.update_weight)
                sm.scale1_disconnected_signal.connect(self._density_win.scale_disconnected)
                if not self._density_was_connected:
                    sm.connect_scale1_signal.emit(False)
                else:
                    last = sm.get_scale1_last_weight()
                    if last is not None:
                        self._density_win.update_weight(last)
            geo = self.geometry()
            self._density_win.move(geo.right() + 12, geo.top() + 180)
            self._density_win.show()
            self._density_win.raise_()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("density window unavailable")

    def _receive_density(self, density: float) -> None:
        self.density_spin.setValue(round(density))

    def _teardown_density(self) -> None:
        if self._density_win is None:
            return
        sm = getattr(self._aw, 'scale_manager', None)
        if sm is not None:
            for _sig, _slot in (
                (sm.scale1_weight_changed_signal, self._density_win.update_weight),
                (sm.scale1_stable_weight_changed_signal, self._density_win.update_weight),
                (sm.scale1_disconnected_signal, self._density_win.scale_disconnected),
            ):
                try:
                    _sig.disconnect(_slot)
                except (TypeError, RuntimeError):
                    pass
            try:
                if not self._density_was_connected:
                    sm.disconnect_scale1_signal.emit()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception("density scale disconnect failed")
        self._density_win.close()
        self._density_win = None

    def done(self, result: int) -> None:  # noqa: N802
        self._teardown_scale()
        self._teardown_density()
        self._teardown_aw()
        self._teardown_ai()
        super().done(result)

    def _teardown_ai(self) -> None:
        """Join a supplier-page read still in flight.

        The read takes about twenty seconds and the thread has no parent, so
        closing this dialog during one destroyed a running QThread — the abort
        signature this code base already knows — and delivered its result into
        a form that no longer exists.
        """
        from tilauscope.cave.workers import stop_worker_thread  # noqa: PLC0415
        thread = getattr(self, '_ai_thread', None)
        worker = getattr(self, '_ai_worker', None)
        if thread is None:
            return
        slots = ()
        if worker is not None:
            slots = ((worker.finished, self._on_ai_parse_finished),
                     (worker.error, self._on_ai_parse_error))
        stop_worker_thread(thread, worker, slots=slots, name="bean AI read")
        self._ai_thread = None
        self._ai_worker = None

    # ── save ─────────────────────────────────────────────────────────────────
    def _apply_essentials(self) -> bool:
        b = self._bean
        name = self.name_edit.text().strip()
        if not name:
            show_styled_message(self, QApplication.translate("tilauscope_beancave", "Missing name"),
                                QApplication.translate("tilauscope_beancave", "The bean needs a name."))
            return False
        b.name = name
        b.country = self.country_combo.currentText().strip()
        b.crop = int(self.crop_spin.value())
        b.weight_left = float(self.stock_spin.value())
        return True

    def _apply_provenance(self) -> bool:
        b = self._bean
        b.farm = self.farm_edit.text().strip()
        b.supplier = self.supplier_edit.text().strip()
        b.altitude = int(self.altitude_spin.value())
        return True

    def _apply_characteristics(self) -> bool:
        b = self._bean
        is_blend = self.type_combo.currentIndex() == 1
        b.is_blend = is_blend
        if is_blend:
            b.bean1_ratio = float(self.bean1_ratio_spin.value())
            b.bean2_name = self.bean2_combo.currentText().strip()
            b.bean2_ratio = float(self.bean2_ratio_spin.value())
            b.bean3_name = self.bean3_combo.currentText().strip()
            b.bean3_ratio = float(self.bean3_ratio_spin.value())
        else:
            b.bean1_ratio = 100.0
            b.bean2_name = ""
            b.bean2_ratio = 0.0
            b.bean3_name = ""
            b.bean3_ratio = 0.0
        b.category = self.category_combo.currentText().strip()
        b.process = self.process_combo.currentText().strip()
        b.species = self.species_combo.currentText().strip()
        b.varieties = self.varieties_combo.currentText().strip()
        b.density = float(self.density_spin.value())
        b.last_humidity = float(self.humidity_spin.value())
        b.water_activity = float(self.wa_spin.value())
        return True

    def _apply_sensory(self) -> bool:
        b = self._bean
        b.sca = float(self.sca_spin.value())
        b.flavour_notes = self.flavour_edit.text().strip()
        b.tips = self.tips_edit.toPlainText().strip()
        return True

    def _save(self) -> None:
        b = self._bean
        prev_weight = float(getattr(b, 'weight_left', 0.0) or 0.0)  # sack reclaim (§9.3)
        appliers = {
            'essentials': (self._apply_essentials,),
            'provenance': (self._apply_provenance,),
            'characteristics': (self._apply_characteristics,),
            'sensory': (self._apply_sensory,),
            'all': (self._apply_essentials, self._apply_provenance,
                    self._apply_characteristics, self._apply_sensory),
        }.get(self._zone, ())
        try:
            for apply_fn in appliers:
                if not apply_fn():
                    return

            if self._create:
                cave = getattr(self._host, 'cave', None)
                if cave is None or getattr(cave, 'green_beans', None) is None:
                    show_styled_message(self, QApplication.translate("tilauscope_beancave", "Save failed"),
                                        QApplication.translate("tilauscope_beancave", "The bean cave is not available."))
                    return
                cave.green_beans.append(b)
                if not hasattr(self._host, 'uuidmap'):
                    self._host.uuidmap = {}
                self._host.uuidmap[b.uuid] = b

            self._host.save_green_beans()
            # stock just hit 0 g: offer to reclaim this bean's labels
            # (design v4 §9.3, shared helper — never duplicate this check).
            prompt_release_if_emptied(self, b, prev_weight, self._host.save_green_beans)
            self._host.populate_table()
            select = getattr(self._host, 'select_bean_by_uuid', None)
            if callable(select):
                select(getattr(b, 'uuid', ''))
            self.accept()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _logd.exception("zone editor save failed")
            show_styled_message(self, QApplication.translate("tilauscope_beancave", "Save failed"),
                                QApplication.translate("tilauscope_beancave", "The record could not be saved. See the log for details."))

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


from artisanlib.widgets import MyQDoubleSpinBox


from PyQt6.QtCore import (Qt, QTimer, QByteArray, QSize,
                          QT_TRANSLATE_NOOP) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QPixmap, QPainter) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QComboBox, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,  # @UnusedImport @Reimport  @UnresolvedImport
                                QPushButton, QWidget, QGridLayout, QGroupBox, QStyledItemDelegate, QListView, QFrame, QSplitter, QSizePolicy, QStackedWidget) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtSvg import QSvgRenderer  # icônes SVG inline pour ZoomToggleButton

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import tint, tooltip_qss
from tilauscope.tilauscope_types import (THEME)
from tilauscope.sack_manager import SackChipsRow  # sack labels (Lot 1, §9.3)
from tilauscope.beancave_catalogue import CatalogueListWidget  # rich catalogue list (Lot 5)
from tilauscope.beancave_bean_sheet import BeanSheetWidget  # read-first bean sheet (Lot 5)
from tilauscope.cave.common import (
    _SVG_DENSITY,
    _svg_bytes_to_icon)
from tilauscope.cave.widgets import (
    SmoothHoverFilter,
    TilauSpinBox, AwReadingOverlay)


class BeanTabBuildMixin:
    """The one builder for the Beans tab: every widget on it, laid out once.

    Split from the tab's behaviour for the same reason the roasting window
    separates its builders — construction is read once, behaviour is read often.
    """

    def setup_main_tab_ui(self) -> None:
        """
        Main tab — V2 layout.

        Structure :
          QSplitter horizontal
          ├── left pane  : datatable (taille stable)
          └── right pane : notice_bar + QScrollArea(formulaire) + actions_bar
        """
        # ── helpers ────────────────────────────────────────────────────────
        # `currentColor` has nothing to inherit from here: the SVG is rendered
        # into a bare QPixmap, so the keyword resolves to the SVG default —
        # pure black, invisible on a dark button. Name the token instead.
        def _icon_btn(svg_path_d: str, label: str, stroke: str = THEME["TEXT"]) -> QPushButton:
            """QPushButton with inline SVG icon + short text label."""
            btn = QPushButton()
            svg = (
                f'''<svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                  xmlns="http://www.w3.org/2000/svg">
                  <path d="{svg_path_d}" stroke="{stroke}"
                    stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>'''
            ).encode()
            renderer = QSvgRenderer(QByteArray(svg))
            px = QPixmap(QSize(14, 14))
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            renderer.render(p)
            p.end()
            from PyQt6.QtGui import QIcon as _QI
            btn.setIcon(_QI(px))
            btn.setIconSize(QSize(14, 14))
            # Thin space Unicode entre icône et texte
            btn.setText(" " + QApplication.translate("tilauscope_beancave", label))
            return btn

        # ── form input widgets (identiques V1) ──────────────────────────────
        self.name_input = QLineEdit()
        self.name_input.setToolTip(QApplication.translate("tilauscope_beancave","Name of the green beans, often commercial name."))
        self.farm_input = QLineEdit()
        self.farm_input.setToolTip(QApplication.translate("tilauscope_beancave","Name of the farm, region, typical information to understand from where the beans are issued."))
        self.supplier_input = QLineEdit()
        self.supplier_input.setToolTip(QApplication.translate("tilauscope_beancave","Name of the supplier where the beans were purchased."))
        self.flavour_notes_input = QLineEdit()
        self.flavour_notes_input.setToolTip(QApplication.translate("tilauscope_beancave","Flavour notes as given by supplier or cupping session"))

        self.crop_input = TilauSpinBox()
        self.crop_input.setRange(2020, 2999)
        self.crop_input.setDecimals(0)
        self.crop_input.setMinimumHeight(30)
        self.crop_input.setToolTip(QApplication.translate("tilauscope_beancave","Year of Harvesting."))
        # crop-age indicator (design v4 §2) — the field itself turns
        # orange at 2 years, red at 3+, so the age shows even when the list
        # column is out of view.
        self._crop_base_style = self.crop_input.styleSheet()
        self.crop_input.valueChanged.connect(
            lambda v: self._update_crop_age_indicator(int(v)))

        self.density_input = TilauSpinBox()
        # Minimum MUST be 0 = "not measured": every call site tests `value() > 0.0`
        # for emptiness, and a non-zero minimum would read as a plausible real value.
        self.density_input.setRange(0, 800)
        self.density_input.setDecimals(0)
        self.density_input.setSuffix("g/l")
        self.density_input.setSpecialValueText(
            QApplication.translate("tilauscope_beancave", "not measured"))
        self.density_input.setMinimumHeight(30)
        self.density_input.setToolTip(QApplication.translate("tilauscope_beancave","Density of green beans in g/l."))

        self.last_humidity_input = TilauSpinBox()
        self.last_humidity_input.setRange(0, 15.0)
        self.last_humidity_input.setDecimals(1)
        self.last_humidity_input.setSingleStep(0.1)
        self.last_humidity_input.setSuffix("%")
        self.last_humidity_input.setMinimumHeight(30)
        self.last_humidity_input.setToolTip(QApplication.translate("tilauscope_beancave","Green beans humidity in percentage. In general between 9%-13%"))

        self.water_activity_input = TilauSpinBox()
        self.water_activity_input.setRange(0.0, 1.0)
        self.water_activity_input.setDecimals(2)
        # aw is a dimensionless ratio between 0 and 1, not a
        # percentage — the field read "0.52 %", which is the kind of label that
        # makes an operator type 52 and hit the 1.0 ceiling with no explanation.
        self.water_activity_input.setSuffix(" aw")
        self.water_activity_input.setMinimumHeight(30)
        self.water_activity_input.setToolTip(QApplication.translate("tilauscope_beancave","Water activity of green beans, a ratio from 0 to 1 (not a percentage). Specialty green is typically 0.45-0.60."))

        # Plain-language reading appended to the unit, e.g. "790 g/l (dense)".
        # Base suffix and style are kept so the qualifier can be rebuilt on
        # every change without accumulating.
        self._phys_base_suffix = {
            'density':  self.density_input.suffix(),
            'humidity': self.last_humidity_input.suffix(),
            'aw':       self.water_activity_input.suffix(),
        }
        self._phys_base_style = {
            'density':  self.density_input.styleSheet(),
            'humidity': self.last_humidity_input.styleSheet(),
            'aw':       self.water_activity_input.styleSheet(),
        }
        self.density_input.valueChanged.connect(
            lambda v: self._update_physical_qualifier('density', float(v)))
        self.last_humidity_input.valueChanged.connect(
            lambda v: self._update_physical_qualifier('humidity', float(v)))
        self.water_activity_input.valueChanged.connect(
            lambda v: self._update_physical_qualifier('aw', float(v)))

        self.altitude_input = TilauSpinBox()
        self.altitude_input.setRange(0, 3000)
        self.altitude_input.setDecimals(0)
        self.altitude_input.setSuffix("m")
        self.altitude_input.setMinimumHeight(30)
        self.altitude_input.setToolTip(QApplication.translate("tilauscope_beancave","Altitude of beans."))

        self.weight_left_input = TilauSpinBox()
        self.weight_left_input.setRange(0.0, 9999.9)
        self.weight_left_input.setSingleStep(1)
        self.weight_left_input.setSuffix("g")
        self.weight_left_input.setDecimals(1)
        self.weight_left_input.setMinimumHeight(30)
        self.weight_left_input.setToolTip(QApplication.translate("tilauscope_beancave","Store the stock weight of this bean in g."))

        self.weight_input = TilauSpinBox()
        self.weight_input.setSingleStep(1)
        self.weight_input.setSuffix("g")
        self.weight_input.setDecimals(1)
        self.weight_input.setRange(0.0, 99999.9)
        self.weight_input.setReadOnly(True)
        self.weight_input.setButtonSymbols(MyQDoubleSpinBox.ButtonSymbols.NoButtons)
        self.weight_input.setToolTip(QApplication.translate("tilauscope_beancave","Calculated — total weight roasted for this bean type."))

        self.sca_input = TilauSpinBox()
        self.sca_input.setRange(0, 100)
        self.sca_input.setDecimals(2)
        self.sca_input.setMinimumHeight(30)
        self.sca_input.setToolTip(QApplication.translate("tilauscope_beancave","SCA cupping score (80+ = specialty grade)."))

        # ComboBoxes
        self.country_combo = QComboBox()
        self.country_combo.setItemDelegate(QStyledItemDelegate())
        self.country_combo.setView(QListView())
        self.country_combo.addItems(self.coffee_producing_countries)

        self.category_process_combo = QComboBox()
        self.category_process_combo.setItemDelegate(QStyledItemDelegate())
        self.category_process_combo.setView(QListView())
        self.category_process_combo.addItems(self.coffee_beans_categories)
        self.category_process_combo.currentTextChanged.connect(self._update_methods)

        self.process_combo = QComboBox()
        self.process_combo.setItemDelegate(QStyledItemDelegate())
        self.process_combo.setView(QListView())

        self.species_combo = QComboBox()
        self.species_combo.setItemDelegate(QStyledItemDelegate())
        self.species_combo.setView(QListView())
        self.species_combo.addItems(self.coffee_beans_species)
        self.species_combo.currentTextChanged.connect(self._update_variety)

        self.varieties_combo = QComboBox()
        self.varieties_combo.setItemDelegate(QStyledItemDelegate())
        self.varieties_combo.setView(QListView())

        self.type_combo = QComboBox()
        self.type_combo.setItemDelegate(QStyledItemDelegate())
        self.type_combo.setView(QListView())
        self.type_combo.addItems(["Single Origin", "Blend"])
        self.type_combo.setToolTip(QApplication.translate("tilauscope_beancave","Select if this record is for a Single Origin green bean or a Blend."))
        self.type_combo.currentIndexChanged.connect(self._toggle_blend_fields)

        self.bean1_ratio_input = MyQDoubleSpinBox()
        self.bean1_ratio_input.setRange(0.0, 100.0)
        self.bean1_ratio_input.setDecimals(1)
        self.bean1_ratio_input.setSuffix("%")
        self.bean1_ratio_input.setValue(100.0)
        self.bean1_ratio_input.setToolTip(QApplication.translate("tilauscope_beancave","Percentage of first bean in the blend."))

        # The action-bar buttons carry no sheet of their own any more: the
        # window's base stylesheet already draws a neutral button exactly this
        # way. Only what differs from it is still said out loud — Delete asks
        # for `danger-outline`, AI and « Roast finished! » keep their tints.

        # ── Boutons CRUD primaires ──────────────────────────────────────────
        # "+ New sack" is the single accent button of the action bar —
        # Update dresses like the other CRUD buttons to avoid two defaults.
        self.update_button = _icon_btn(
            "M2 7h10M7 2l5 5-5 5", QT_TRANSLATE_NOOP("tilauscope_beancave", "Update"))
        self.update_button.clicked.connect(self.update_selected_bean)
        self.update_button.setToolTip(QApplication.translate("tilauscope_beancave","Update the selected green bean record with the values filled in the form."))

        self.add_button = _icon_btn(
            "M7 2v10M2 7h10", QT_TRANSLATE_NOOP("tilauscope_beancave", "Add"))
        # Lot 5 step D: Add opens the full expert editor on a blank record
        self.add_button.clicked.connect(self._open_full_bean_editor)
        self.add_button.setToolTip(QApplication.translate("tilauscope_beancave","Create a new green bean record in a single expert form. For a guided entry, use « + New sack »."))

        self.clear_button = _icon_btn(
            "M5 4l-3 3 3 3M2 7h9a2 2 0 0 0 0-4H9", QT_TRANSLATE_NOOP("tilauscope_beancave", "Clear"))
        self.clear_button.clicked.connect(self.clear_form)
        self.clear_button.clicked.connect(self._enter_edit_mode)  # Lot 5: a fresh entry needs the form
        self.clear_button.setToolTip(QApplication.translate("tilauscope_beancave","Clear all input fields to their default state."))

        self.remove_button = _icon_btn(
            "M2 4h10M5 4V2.5h4V4M3 4l.7 7.5h6.6L11 4M6 7v3M8 7v3",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Delete"), stroke=THEME["CRITICAL"])
        # Outline, not the filled `danger`: this button stands in a row of
        # equals, and its icon is baked red — a red fill would eat it.
        self.remove_button.setProperty('variant', 'danger-outline')
        self.remove_button.clicked.connect(self.confirm_and_delete)
        self.remove_button.setToolTip(QApplication.translate("tilauscope_beancave","Delete the selected green bean record. A confirmation dialog will appear."))

        # ── Boutons secondaires ─────────────────────────────────────────────
        self.roast = _icon_btn(
            "M7 2c0 2-3 3-3 5.5a3 3 0 0 0 6 0C10 5 7 4 7 2z",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Roast"), stroke=THEME["WARNING"])
        self.roast.clicked.connect(self.on_click_roast_properties)
        self.roast.setToolTip(QApplication.translate("tilauscope_beancave","Set a roast session based on the current selection."))

        self.generate_label_button = _icon_btn(
            "M1.5 3H12.5a1.5 1.5 0 0 1 1.5 1.5v6A1.5 1.5 0 0 1 12.5 12H1.5A1.5 1.5 0 0 1 0 10.5v-6A1.5 1.5 0 0 1 1.5 3zM3 6.5h8M3 8.5h5",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Label"))
        self.generate_label_button.clicked.connect(self.on_print_label_clicked)
        self.generate_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate a printable label for this green bean record."))

        self.generate_qr_button = _icon_btn(
            "M1 1h5v5H1zM8 1h5v5H8zM1 8h5v5H1zM3 3h1v1H3zM10 3h1v1H10zM3 10h1v1H3z",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "QR"))
        self.generate_qr_button.clicked.connect(self.generate_qr_code)
        self.generate_qr_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate a QR code for this green bean record."))

        # Shareable bean card — 1200x630 JPEG for social posts
        self.generate_card_button = _icon_btn(
            "M1 3.5h12v9H1zM4 7a1 1 0 1 0 0-.01M1.6 11.4L5 8.4l2.4 2.2L10 8l3 2.8",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Card"))
        self.generate_card_button.clicked.connect(self.on_export_social_card)
        self.generate_card_button.setToolTip(QApplication.translate("tilauscope_beancave","Export this green bean sheet as a shareable landscape image (JPEG), sized for social networks."))

        self.inject_from_ai_button = _icon_btn(
            "M7 1.5l1.2 3.5H12l-3 2.2 1.1 3.5L7 8.5l-3.1 2.2L5 7.2 2 5h3.8z",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "AI"), stroke=THEME["ACCENT"])
        self.inject_from_ai_button.clicked.connect(self.on_click_ai_parse)
        self.inject_from_ai_button.clicked.connect(self._enter_edit_mode)  # Lot 5: AI fills the form
        self.inject_from_ai_button.setToolTip(QApplication.translate("tilauscope_beancave","Use AI to parse unstructured text and fill the form automatically."))

        # Flavor Wheel — mini SVG wheel comme icône
        _fw_svg = (
            b'''<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
              <g transform="translate(9,9)">
                <path d="M0,-7.5 A7.5,7.5 0 0,1 6.5,-3.75 L0,0 Z" fill="#F38BA8"/>
                <path d="M6.5,-3.75 A7.5,7.5 0 0,1 6.5,3.75 L0,0 Z"  fill="#FAB387"/>
                <path d="M6.5,3.75 A7.5,7.5 0 0,1 0,7.5 L0,0 Z"      fill="#F9E2AF"/>
                <path d="M0,7.5 A7.5,7.5 0 0,1 -6.5,3.75 L0,0 Z"     fill="#A6E3A1"/>
                <path d="M-6.5,3.75 A7.5,7.5 0 0,1 -6.5,-3.75 L0,0 Z" fill="#89B4FA"/>
                <path d="M-6.5,-3.75 A7.5,7.5 0 0,1 0,-7.5 L0,0 Z"   fill="#CBA6F7"/>
                <circle r="2.5" fill="#1E1E2E"/>
              </g>
            </svg>'''
        )
        _fw_renderer = QSvgRenderer(QByteArray(_fw_svg))
        _fw_px = QPixmap(QSize(18, 18))
        _fw_px.fill(Qt.GlobalColor.transparent)
        _fw_p = QPainter(_fw_px)
        _fw_renderer.render(_fw_p)
        _fw_p.end()
        from PyQt6.QtGui import QIcon as _QIFW
        self.flavorselector = QPushButton()
        self.flavorselector.setIcon(_QIFW(_fw_px))
        self.flavorselector.setIconSize(QSize(18, 18))
        self.flavorselector.setText(QApplication.translate("tilauscope_beancave", "Flavors"))
        self.flavorselector.clicked.connect(self.on_click_select_flavor)
        self.flavorselector.setToolTip(QApplication.translate("tilauscope_beancave","Select flavor notes based on a Flavor Wheel."))

        # ── Blend component widgets ─────────────────────────────────────────
        _initial_list = [QApplication.translate("tilauscope_beancave","N/A - Select a bean")]
        self.bean2_combo = QComboBox()
        self.bean2_combo.setItemDelegate(QStyledItemDelegate())
        self.bean2_combo.setView(QListView())
        self.bean2_combo.addItems(_initial_list)
        self.bean2_ratio_input = MyQDoubleSpinBox()
        self.bean2_ratio_input.setRange(0.0, 100.0)
        self.bean2_ratio_input.setDecimals(1)
        self.bean2_ratio_input.setSuffix("%")
        self.bean2_ratio_input.setToolTip(QApplication.translate("tilauscope_beancave","Percentage of second bean type in the blend."))

        self.bean3_combo = QComboBox()
        self.bean3_combo.setItemDelegate(QStyledItemDelegate())
        self.bean3_combo.setView(QListView())
        self.bean3_combo.addItems(_initial_list)
        self.bean3_ratio_input = MyQDoubleSpinBox()
        self.bean3_ratio_input.setRange(0.0, 100.0)
        self.bean3_ratio_input.setDecimals(1)
        self.bean3_ratio_input.setSuffix("%")
        self.bean3_ratio_input.setToolTip(QApplication.translate("tilauscope_beancave","Percentage of third bean type in the blend."))

        self.blend_notes_input = QLineEdit()
        self.blend_notes_input.setMaxLength(256)

        # lock text/combo input height to TilauSpinBox._H so no stylesheet
        # state change (hover/focus border, radius, AA) can shift them by 1px and
        # reflow the form — mirrors the fixed-height guard already on TilauSpinBox.
        for _w in (self.name_input, self.farm_input, self.supplier_input,
                   self.flavour_notes_input, self.blend_notes_input,
                   self.country_combo, self.category_process_combo, self.process_combo,
                   self.species_combo, self.varieties_combo, self.type_combo,
                   self.bean2_combo, self.bean3_combo):
            _w.setFixedHeight(TilauSpinBox._H)

        # ── Hover filter ────────────────────────────────────────────────────
        self.hover_filter = SmoothHoverFilter(self)
        _db_widgets = [
            self.name_input, self.farm_input, self.country_combo, self.supplier_input,
            self.category_process_combo, self.process_combo, self.crop_input,
            self.density_input, self.last_humidity_input, self.weight_input,
            self.type_combo, self.bean1_ratio_input, self.water_activity_input,
            self.altitude_input, self.species_combo,
            self.varieties_combo, self.weight_left_input, self.flavour_notes_input,
            self.sca_input, self.bean2_combo, self.bean2_ratio_input,
            self.bean3_combo, self.bean3_ratio_input, self.blend_notes_input,
        ]
        for w in _db_widgets:
            if w:
                w.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                w.installEventFilter(self.hover_filter)

        # ══════════════════════════════════════════════════════════════════
        # Layout stacked in 5 semantic groups, each with its own accent colour:
        #   Origin & Identity → ACCENT, Botany & Process → MAUVE, Blend → SUCCESS,
        #   Physical measures → SUBTEXT, Computed → WARNING
        # ══════════════════════════════════════════════════════════════════

        _C_ORIGIN  = THEME["ACCENT"]
        _C_BOTANY  = THEME["MAUVE"]
        _C_BLEND   = THEME["SUCCESS"]
        _C_PHYS    = THEME["SUBTEXT"]
        _C_COMP    = THEME["WARNING"]

        # ── Helper : crée un QGroupBox stylisé thème sombre ─────────────────
        def _grp(title: str, accent: str) -> QGroupBox:
            gb = QGroupBox(QApplication.translate("tilauscope_beancave", title))
            gb.setStyleSheet(
                f"QGroupBox{{"
                f"  border: 1px solid {THEME['BORDER']};"
                f"  border-radius: 7px;"
                f"  margin-top: 8px;"
                f"  background: {THEME['SURFACE']};"
                f"}}"
                f"QGroupBox::title{{"
                f"  subcontrol-origin: margin;"
                f"  left: 10px;"
                f"  padding: 0 4px;"
                f"  color: {accent};"
                f"  font-size: 10px;"
                f"  font-weight: 600;"
                f"  text-transform: uppercase;"
                f"  letter-spacing: 1px;"
                f"}}"
            )
            return gb

        # ── Helper : ligne label+widget avec label fixe 120px aligné gauche ─
        def _frow(lbl_text: str, widget: QWidget, parent_layout: QGridLayout,
                  row: int, col_offset: int = 0, span: int = 1) -> None:
            """Ajoute une ligne label (gauche, 120px) + widget dans un QGridLayout."""
            lbl = QLabel(QApplication.translate("tilauscope_beancave", lbl_text))
            lbl.setStyleSheet(
                f"color: {THEME['SUBTEXT']};"
                f"font-size: 11px;"
                f"background: transparent;"
                f"border: none;"
                f"padding: 0;"
            )
            lbl.setFixedWidth(120)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            parent_layout.addWidget(lbl,    row, col_offset * 2)
            parent_layout.addWidget(widget, row, col_offset * 2 + 1, 1, span * 2 - 1)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 1 — Origin & Identity
        # ════════════════════════════════════════════════════════════════════
        self.form_group_box = _grp(QT_TRANSLATE_NOOP("tilauscope_beancave", "Origin & Identity"), _C_ORIGIN)
        _gl1 = QGridLayout(self.form_group_box)
        _gl1.setContentsMargins(10, 18, 10, 10)
        _gl1.setSpacing(5)
        _gl1.setColumnStretch(1, 3)  # champ col gauche
        _gl1.setColumnStretch(3, 3)  # champ col droite
        _gl1.setColumnMinimumWidth(0, 120)  # label gauche
        _gl1.setColumnMinimumWidth(2, 120)  # label droite

        # col gauche : Name (pleine largeur), Farm, Country
        _name_lbl = QLabel(QApplication.translate("tilauscope_beancave","Name"))
        _name_lbl.setProperty('variant', 'caption')
        _name_lbl.setFixedWidth(120)
        _name_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl1.addWidget(_name_lbl,        0, 0)
        _gl1.addWidget(self.name_input,  0, 1, 1, 3)   # span 3 cols → pleine largeur

        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Farm / Region"),  self.farm_input,     _gl1, 1, 0)
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Country"),        self.country_combo,  _gl1, 2, 0)

        # col droite : Supplier, Crop
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Supplier"),       self.supplier_input, _gl1, 1, 1)
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Crop year"),      self.crop_input,     _gl1, 2, 1)

        # Flavour Notes pleine largeur
        _fl_lbl = QLabel(QApplication.translate("tilauscope_beancave","Flavour Notes"))
        _fl_lbl.setProperty('variant', 'caption')
        _fl_lbl.setFixedWidth(120)
        _fl_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl1.addWidget(_fl_lbl,                  3, 0)
        _gl1.addWidget(self.flavour_notes_input, 3, 1, 1, 3)

        # SCA score
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "SCA score"),      self.sca_input,      _gl1, 4, 0)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 2 — Botany & Process
        # ════════════════════════════════════════════════════════════════════
        _sec_botany = _grp(QT_TRANSLATE_NOOP("tilauscope_beancave", "Botany & Process"), _C_BOTANY)
        _gl2 = QGridLayout(_sec_botany)
        _gl2.setContentsMargins(10, 18, 10, 10)
        _gl2.setSpacing(5)
        _gl2.setColumnStretch(1, 3)
        _gl2.setColumnStretch(3, 3)
        _gl2.setColumnMinimumWidth(0, 120)
        _gl2.setColumnMinimumWidth(2, 120)

        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Type"),           self.type_combo,             _gl2, 0, 0)
        # Ratio 1 affiché dans le groupe Blend en mode Blend (géré par _toggle_blend_fields)

        # Species + Variety : ligne 1 — visibles uniquement en Single Origin
        self._species_row_lbl = QLabel(QApplication.translate("tilauscope_beancave","Species"))
        self._species_row_lbl.setProperty('variant', 'caption')
        self._species_row_lbl.setFixedWidth(120)
        self._species_row_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._variety_row_lbl = QLabel(QApplication.translate("tilauscope_beancave","Variety"))
        self._variety_row_lbl.setProperty('variant', 'caption')
        self._variety_row_lbl.setFixedWidth(120)
        self._variety_row_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        _gl2.addWidget(self._species_row_lbl,  1, 0)
        _gl2.addWidget(self.species_combo,     1, 1)
        _gl2.addWidget(self._variety_row_lbl,  1, 2)
        _gl2.addWidget(self.varieties_combo,   1, 3)  # position initiale (SO)

        # Category + Process : ligne 2
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Category"),       self.category_process_combo, _gl2, 2, 0)
        _frow(QT_TRANSLATE_NOOP("tilauscope_beancave", "Process"),        self.process_combo,          _gl2, 2, 1)

        # Stocker la ref au layout Botany pour le re-parentage dans _toggle_blend_fields
        self._gl2_botany = _gl2

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 3 — Physical measures (grille 4 colonnes sur une ligne)
        # ════════════════════════════════════════════════════════════════════
        _sec_phys = _grp(QT_TRANSLATE_NOOP("tilauscope_beancave", "Physical measures"), _C_PHYS)
        _gl3 = QGridLayout(_sec_phys)
        _gl3.setContentsMargins(10, 18, 10, 10)
        _gl3.setSpacing(5)
        for _ci in range(8):
            _gl3.setColumnStretch(_ci, 1 if _ci % 2 == 1 else 0)

        # density-measure button → opens the scale-piloted density window
        self.density_measure_btn = QPushButton()
        self.density_measure_btn.setIcon(_svg_bytes_to_icon(_SVG_DENSITY.encode(), 16))
        self.density_measure_btn.setIconSize(QSize(16, 16))
        self.density_measure_btn.setFixedSize(30, 30)
        self.density_measure_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        self.density_measure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.density_measure_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Measure density with the scale"))
        self.density_measure_btn.setStyleSheet(
            f"QPushButton{{background:{THEME['SURFACE']};border:1px solid {THEME['BORDER']};"
            f"border-radius:6px;}}QPushButton:hover{{border-color:{THEME['ACCENT']};}}"
            + tooltip_qss()
        )
        self.density_measure_btn.clicked.connect(self._open_density_window)
        _dens_box = QWidget()
        _dens_lay = QHBoxLayout(_dens_box)
        _dens_lay.setContentsMargins(0, 0, 0, 0)
        _dens_lay.setSpacing(4)
        _dens_lay.addWidget(self.density_input, 1)
        _dens_lay.addWidget(self.density_measure_btn, 0)

        # 4 colonnes : Altitude | Density | Humidity | Water activity
        for _ci, (_lbl_t, _w) in enumerate([
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Altitude"),       self.altitude_input),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Density"),        _dens_box),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Humidity"),       self.last_humidity_input),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Water activity"), self.water_activity_input),
        ]):
            _lbl3 = QLabel(QApplication.translate("tilauscope_beancave", _lbl_t))
            _lbl3.setProperty('variant', 'caption')
            _lbl3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            _gl3.addWidget(_lbl3, 0, _ci * 2)
            _gl3.addWidget(_w,    0, _ci * 2 + 1)

        self.water_activity_label = _gl3.itemAtPosition(0, 6).widget()  # ref pour update_ui_visibility

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 4 — Blend components (conditionnel)
        # ════════════════════════════════════════════════════════════════════
        self.blend_group_box = _grp(QT_TRANSLATE_NOOP("tilauscope_beancave", "Blend components"), _C_BLEND)
        self.blend_group_box.setStyleSheet(
            self.blend_group_box.styleSheet().replace(
                f"border: 1px solid {THEME['BORDER']};",
                "border: 1px solid rgba(166,227,161,60);"
            )
        )
        _gl4 = QGridLayout(self.blend_group_box)
        _gl4.setContentsMargins(10, 18, 10, 10)
        _gl4.setSpacing(5)
        # Colonnes : lbl | champ | lbl | champ | lbl | champ | lbl | champ
        for _ci4 in [1, 3, 5, 7]:
            _gl4.setColumnStretch(_ci4, 3 if _ci4 in [1, 5] else 1)

        # Ligne 0 : Bean 1 (varieties_combo re-parenté par _toggle_blend_fields)
        #           + Ratio 1 | Bean 2 + Ratio 2
        # Bean 1 label et combo sont injectés dynamiquement — on pré-crée le label
        self._blend_bean1_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Bean 1"))
        self._blend_bean1_lbl.setProperty('variant', 'caption')
        self._blend_bean1_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Bean 1 + varieties_combo ajoutés par _toggle_blend_fields — ici seulement Ratio1/Bean2/Ratio2
        for _ci2, (_lbl_t2, _w2) in enumerate([
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Ratio 1"),  self.bean1_ratio_input),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Bean 2"),   self.bean2_combo),
            (QT_TRANSLATE_NOOP("tilauscope_beancave", "Ratio 2"),  self.bean2_ratio_input),
        ]):
            _lbl4 = QLabel(QApplication.translate("tilauscope_beancave", _lbl_t2))
            _lbl4.setProperty('variant', 'caption')
            _lbl4.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            # cols décalées de 2 pour laisser place à Bean1 (cols 0-1)
            _gl4.addWidget(_lbl4, 0, (_ci2 + 1) * 2)
            _gl4.addWidget(_w2,   0, (_ci2 + 1) * 2 + 1)

        # Stocker ref pour re-parentage dynamique
        self._gl4_blend = _gl4

        # Ligne 1 : Bean 3 + Ratio 3 | Notes
        _lbl_b3 = QLabel(QApplication.translate("tilauscope_beancave","Bean 3"))
        _lbl_b3.setProperty('variant', 'caption')
        _lbl_b3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _lbl_r3 = QLabel(QApplication.translate("tilauscope_beancave","Ratio 3"))
        _lbl_r3.setProperty('variant', 'caption')
        _lbl_r3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl4.addWidget(_lbl_b3,              1, 0)
        _gl4.addWidget(self.bean3_combo,     1, 1)
        _gl4.addWidget(_lbl_r3,              1, 2)
        _gl4.addWidget(self.bean3_ratio_input, 1, 3)

        # Notes blend sur la même ligne (cols 4-7)
        _bl_notes_lbl = QLabel(QApplication.translate("tilauscope_beancave","Notes"))
        _bl_notes_lbl.setProperty('variant', 'caption')
        _gl4.addWidget(_bl_notes_lbl,          1, 4)
        _gl4.addWidget(self.blend_notes_input, 1, 5, 1, 3)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 5 — Computed (Stock + Total roasted)
        # ════════════════════════════════════════════════════════════════════
        _sec_computed = _grp(QT_TRANSLATE_NOOP("tilauscope_beancave", "Computed"), _C_COMP)
        _gl5 = QGridLayout(_sec_computed)
        _gl5.setContentsMargins(10, 18, 10, 10)
        _gl5.setSpacing(5)
        _gl5.setColumnStretch(1, 2)
        _gl5.setColumnStretch(3, 2)
        _gl5.setColumnMinimumWidth(0, 120)
        _gl5.setColumnMinimumWidth(2, 120)

        _stk_lbl = QLabel(QApplication.translate("tilauscope_beancave","Stock left (g)"))
        _stk_lbl.setProperty('variant', 'caption')
        _stk_lbl.setFixedWidth(120)
        _stk_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl5.addWidget(_stk_lbl,              0, 0)
        _gl5.addWidget(self.weight_left_input, 0, 1)

        _tot_lbl = QLabel(QApplication.translate("tilauscope_beancave","Total roasted (g)"))
        _tot_lbl.setProperty('variant', 'caption')
        _tot_lbl.setFixedWidth(120)
        _tot_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        _computed_badge = QLabel(QApplication.translate("tilauscope_beancave","computed — read only"))
        _computed_badge.setStyleSheet(
            f"color: {_C_COMP};"
            f"background: transparent;"
            f"border: 1px solid rgba(224,144,59,60);"
            f"border-radius: 4px;"
            f"padding: 1px 7px;"
            f"font-size: 10px;"
        )
        _gl5.addWidget(_tot_lbl,              0, 2)
        _gl5.addWidget(self.weight_input,     0, 3)
        _gl5.addWidget(_computed_badge,       0, 4)

        # Sack chips row (optional bag labels — invisible when the
        # bean has none, so unequipped users see the form exactly as before).
        self._current_sacks: list[str] = []
        self._sacks_lbl = QLabel(QApplication.translate("tilauscope_beancave","Sacks"))
        self._sacks_lbl.setProperty('variant', 'caption')
        self._sacks_lbl.setFixedWidth(120)
        self._sacks_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._sacks_lbl.setVisible(False)
        self.sack_chips = SackChipsRow()
        self.sack_chips.sackReleased.connect(self._on_sack_released)
        _gl5.addWidget(self._sacks_lbl,  1, 0)
        _gl5.addWidget(self.sack_chips,  1, 1, 1, 4)

        # ════════════════════════════════════════════════════════════════════
        # Form inner — assemblage vertical des 5 groupes
        # ════════════════════════════════════════════════════════════════════
        _form_inner = QWidget()
        _form_inner.setStyleSheet(f"background: {THEME['BG']};")
        _form_inner_layout = QVBoxLayout(_form_inner)
        _form_inner_layout.setContentsMargins(8, 8, 8, 8)
        _form_inner_layout.setSpacing(6)
        _form_inner_layout.addWidget(self.form_group_box)   # 1. Origin & Identity
        _form_inner_layout.addWidget(_sec_botany)           # 2. Botany & Process
        _form_inner_layout.addWidget(self.blend_group_box)  # 3. Blend (conditionnel)
        _form_inner_layout.addWidget(_sec_phys)             # 4. Physical measures
        _form_inner_layout.addWidget(_sec_computed)         # 5. Computed
        _form_inner_layout.addStretch(1)

        _form_scroll = QScrollArea()
        _form_scroll.setWidgetResizable(True)
        _form_scroll.setWidget(_form_inner)
        _form_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {THEME['BG']}; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {THEME['BG']}; }}"
        )
        _form_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ── Notice bar (bean sélectionné + type tag) ────────────────────────
        self._notice_bar = QWidget()
        _nb_layout = QHBoxLayout(self._notice_bar)
        _nb_layout.setContentsMargins(10, 3, 10, 3)
        _nb_layout.setSpacing(6)
        # Lot 5: the pane is read-first now — neutral prefix
        _editing_prefix = QLabel(QApplication.translate("tilauscope_beancave","Bean:"))
        _editing_prefix.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:10px;")
        self._notice_name_label = QLabel("—")
        self._notice_name_label.setStyleSheet(f"color:{THEME['TEXT']};font-weight:600;font-size:11px;")
        self._type_tag_label = QLabel("Single Origin")
        self._type_tag_label.setStyleSheet(
            f"background:{tint('ACCENT', 25)};border:1px solid {tint('ACCENT', 60)};"
            f"border-radius:4px;color:{THEME['ACCENT']};font-size:10px;padding:1px 6px;"
        )
        _nb_layout.addWidget(_editing_prefix)
        _nb_layout.addWidget(self._notice_name_label)
        _nb_layout.addStretch()
        _nb_layout.addWidget(self._type_tag_label)
        self._notice_bar.setStyleSheet(
            f"background:{tint('ACCENT', 12)};border-bottom:1px solid {THEME['BORDER']};"
        )

        # ── Actions bar — une seule ligne ──────────────────────────────────
        # Primaires (Update/Add/Clear/Delete) | séparateur | Secondaires (Roast…Flavors)
        _actions_widget = QWidget()
        _actions_widget.setObjectName("BcActionBar")
        # Cibler uniquement le widget lui-même — ne pas propager aux boutons enfants
        _actions_widget.setStyleSheet(
            f"QWidget#BcActionBar {{"
            f"  background: {THEME['SURFACE']};"
            f"  border-top: 1px solid {THEME['BORDER']};"
            f"}}"
        )
        _actions_layout = QHBoxLayout(_actions_widget)
        _actions_layout.setContentsMargins(8, 5, 8, 5)
        _actions_layout.setSpacing(5)

        # Primaires
        # "New sack" guided assistant — head of the primary zone
        # (validated mock v2: all buttons live in the bottom action bar)
        self.new_sack_button = QPushButton("+ " + QApplication.translate("tilauscope_beancave", "New sack"))
        self.new_sack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_sack_button.setStyleSheet(
            f"QPushButton {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
            f" border: none; border-radius: 6px; padding: 5px 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {THEME['LAVENDER']}; }}")
        self.new_sack_button.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Register an incoming bag of green coffee with a step-by-step "
            "assistant: new bean, restock or new crop — sack labelling stays "
            "optional."))
        self.new_sack_button.clicked.connect(self._open_new_sack_wizard)
        _actions_layout.addWidget(self.new_sack_button)

        # Shortcut of the same assistant, locked on the selected record
        self.new_crop_button = QPushButton("🌱 " + QApplication.translate("tilauscope_beancave", "New crop"))
        self.new_crop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_crop_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['ACCENT']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 6px;"
            f" padding: 5px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; }}"
            f"QPushButton:disabled {{ color: {THEME['SUBTEXT']}; }}")
        self.new_crop_button.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Start the next harvest of the selected coffee: origin, process "
            "and variety are inherited, you only enter the new year, the "
            "weight and the measurements of the lot."))
        self.new_crop_button.clicked.connect(self._open_new_crop_wizard)
        _actions_layout.addWidget(self.new_crop_button)
        _sep_ns = QFrame()
        _sep_ns.setFrameShape(QFrame.Shape.VLine)
        _sep_ns.setFixedHeight(20)
        _sep_ns.setStyleSheet(f"color:{THEME['BORDER']};max-width:1px;")
        _actions_layout.addWidget(_sep_ns)

        # Update/Clear/Flavors/AI are absorbed by the sheet's ✎ zone editors; the
        # widgets stay alive (hidden) so their enabled-state code paths still work.
        _actions_layout.addWidget(self.roast)
        _actions_layout.addWidget(self.generate_label_button)
        _actions_layout.addWidget(self.generate_qr_button)
        _actions_layout.addWidget(self.generate_card_button)

        _sep_crud = QFrame()
        _sep_crud.setFrameShape(QFrame.Shape.VLine)
        _sep_crud.setFixedHeight(20)
        _sep_crud.setStyleSheet(f"color:{THEME['BORDER']};max-width:1px;")
        _actions_layout.addWidget(_sep_crud)
        _actions_layout.addWidget(self.add_button)

        for _hidden in (self.update_button, self.clear_button,
                        self.inject_from_ai_button, self.flavorselector):
            _hidden.setVisible(False)

        # Spacer + Delete isolé à droite
        _actions_layout.addStretch(1)
        _actions_layout.addWidget(self.remove_button)

        # ── Pane droit assembly ─────────────────────────────────────────────
        _right_pane = QWidget()
        _right_layout = QVBoxLayout(_right_pane)
        _right_layout.setContentsMargins(0, 0, 0, 0)
        _right_layout.setSpacing(0)
        _right_layout.addWidget(self._notice_bar)
        # Read-first sheet (page 0) over the edit form (page 1); any ✎ opens the
        # full form, and saving or selecting a bean returns to the sheet.
        self.bean_sheet = BeanSheetWidget()
        self.bean_sheet.editRequested.connect(self._open_zone_editor)
        self.bean_sheet.sackReleased.connect(self._on_sack_released)
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self.bean_sheet)   # 0 — read
        self._right_stack.addWidget(_form_scroll)      # 1 — edit form
        _right_layout.addWidget(self._right_stack, 1)
        _right_layout.addWidget(_actions_widget)

        # ── Pane gauche : datatable ─────────────────────────────────────────
        _left_pane = QWidget()
        _left_layout = QVBoxLayout(_left_pane)
        _left_layout.setContentsMargins(0, 0, 0, 0)
        _left_layout.setSpacing(0)
        # The rich rows list is the visible catalogue; datatable stays in the
        # layout but hidden — it remains the selection model (row == green_beans
        # index) every code path relies on.
        self.catalogue_list = CatalogueListWidget()
        self.catalogue_list.rowActivated.connect(self._on_catalogue_row_activated)
        _left_layout.addWidget(self.catalogue_list, 1)
        _left_layout.addWidget(self.datatable)
        self.datatable.hide()

        # ── Empty state ─────────────────────────────────────────────────────
        self.empty_state_label = QLabel()
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setStyleSheet("font-size:14pt;color:gray;padding:20px;")
        self.empty_state_label.hide()

        # ── QSplitter horizontal ────────────────────────────────────────────
        _splitter = QSplitter(Qt.Orientation.Horizontal)
        _splitter.setHandleWidth(4)
        _splitter.setChildrenCollapsible(False)
        _splitter.setStyleSheet(
            f"QSplitter::handle{{background:{THEME['BORDER']};border-radius:2px;}}"
            f"QSplitter::handle:hover{{background:{THEME['ACCENT']};}}"
        )
        _splitter.addWidget(_left_pane)
        _splitter.addWidget(_right_pane)
        _splitter.setSizes([320, 580])

        # ── Root layout ─────────────────────────────────────────────────────
        main_tab_layout = QVBoxLayout()
        main_tab_layout.setContentsMargins(0, 0, 0, 0)
        main_tab_layout.setSpacing(0)
        main_tab_layout.addWidget(_splitter, 1)
        main_tab_layout.addWidget(self.empty_state_label)

        # ── Overlays ────────────────────────────────────────────────────────
        self.aw_overlay = AwReadingOverlay(self)
        self.aw_hide_timer = QTimer(self)
        self.aw_hide_timer.setSingleShot(True)
        self.aw_hide_timer.timeout.connect(self.aw_overlay.hide)

        # ── Initial visibility ───────────────────────────────────────────────
        self._toggle_blend_fields()
        self.main_tab.setLayout(main_tab_layout)

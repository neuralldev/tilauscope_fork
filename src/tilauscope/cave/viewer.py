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
from contextlib import contextmanager
from functools import partial
import ast  # Import de la bibliothèque ast
import html
import re # For sorting alog files
from datetime import datetime
from pathlib import Path

#import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas


from artisanlib.util import cast  # smooth_list moved from tgraphcanvas to util

from artisanlib.atypes import ProfileData

from PyQt6.QtCore import (QDate, QItemSelection, QItemSelectionModel, QLocale, QModelIndex, QPoint, QTime, QStandardPaths, Qt, pyqtSlot, QSettings, QThread, QTimer, QByteArray, QSize,
                          QT_TRANSLATE_NOOP) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QAction, QPixmap, QCursor, QPainter, QKeySequence, QShortcut) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,  # @UnusedImport @Reimport  @UnresolvedImport
                                QPushButton, QWidget, # @UnusedImport @Reimport  @UnresolvedImport
                                QComboBox, QGridLayout, QLineEdit, QMenu, QStackedWidget, QTimeEdit, QWidgetAction,
                                QFrame,
                                QMessageBox, QDialog, QSplitter, QSizePolicy) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtSvg import QSvgRenderer  # icônes SVG inline pour ZoomToggleButton

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.header_icons import make_icon
from tilauscope.theme_qss import style_combo_popup, styled_popup_view, tint
from tilauscope.tilauscope_types import (THEME, literal_ampersand, standardization_map,
                                         TilauProgressRow)
from tilauscope.roast_timeline import RoastReadyDialog
from tilauscope.cave.common import (
    _log, _logd, _PLOT_PALETTE, _safe_filename,
    ror_span_samples, recompute_profile_deltas, ALOG_CACHE_MAX)
from tilauscope.cave.widgets import (
    ZoomToggleButton, CanvasContainer, HoverTooltip, NiimbotStatusOverlay)
from tilauscope.cave.workers import (
    _AlogLoadWorker, _AlogListWorker)
from tilauscope.cave.roast_list import (
    SORT_COFFEE, SORT_OLDEST, SORT_RECENT, SVG_SEARCH, BeanFacts, RoastFilterProxy, RoastListModel,
    RoastListView, RoastRow, RoastRowDelegate, RoastSearchField, fold, roast_count_text)
from tilauscope.widgets.controls import SegmentedControl
from tilauscope.cave.viewer_detail import (
    CurveMessageLabel, KpiTile, ResultBanner, comparison_tiles, custom_range_error, menu_qss,
    roast_facts, roast_tiles)


class ViewerMixin:
    """The Roast viewer tab: the roast list, and loading a roast off the GUI thread.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    def setup_roast_viewer_tab_ui(self) -> None:
        self.roast_viewer_layout = QVBoxLayout()

        # ── Helper SVG inline identique à l'onglet Green Beans ───────────────
        _FS2 = "12px"
        _R2  = "5px"

        def _vbtn(svg_d: str, label: str, stroke: str = THEME["TEXT"],
                  style_extra: str = "") -> QPushButton:
            """Bouton icône SVG + texte, style canonical application."""
            b = QPushButton()
            svg = (
                f'''<svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                  xmlns="http://www.w3.org/2000/svg">
                  <path d="{svg_d}" stroke="{stroke}"
                    stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>'''
            ).encode()
            renderer = QSvgRenderer(QByteArray(svg))
            px = QPixmap(QSize(14, 14))
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            renderer.render(p)
            p.end()
            from PyQt6.QtGui import QIcon as _QI2
            b.setIcon(_QI2(px))
            b.setIconSize(QSize(14, 14))
            # Thin space Unicode entre icône et texte (Qt ne supporte pas gap CSS)
            b.setText(" " + QApplication.translate("tilauscope_beancave", label))
            # No sheet unless the caller asked for a tint: a plain toolbar
            # button is what the window's base stylesheet already draws.
            if style_extra:
                b.setStyleSheet(style_extra)
            return b

        _SS_ACCENT2 = f"""
            QPushButton {{
                background-color : {tint('ACCENT', 40)};
                color            : {THEME['ACCENT']};
                border           : 1px solid {tint('ACCENT', 100)};
                border-radius    : {_R2};
                padding          : 5px 12px;
                font-size        : {_FS2};
                font-weight      : bold;
            }}
            QPushButton:hover {{
                background-color : {tint('ACCENT', 70)};
            }}
            QPushButton:disabled {{
                color            : {THEME['SUBTEXT']};
                border-color     : {THEME['BORDER']};
                background-color : {THEME['SURFACE']};
            }}
        """
        # ── One roast's actions, beside its name ─────────────────────────────
        self.load_artisan_button_viewer = _vbtn(
            "M2 7h8M7 3l4 4-4 4M12 2v10", QT_TRANSLATE_NOOP("tilauscope_beancave", "Load in Artisan"),
            stroke=THEME["ACCENT"], style_extra=_SS_ACCENT2
        )
        self.load_artisan_button_viewer.clicked.connect(self.load_roast_in_artisan)
        self.load_artisan_button_viewer.setToolTip(QApplication.translate("tilauscope_beancave","Load the selected ALog file into Artisan for detailed analysis."))
        self.load_artisan_button_viewer.setEnabled(False)

        self.load_artisan_background_button_viewer = _vbtn(
            "M3 4h8v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4zM5 4V3a2 2 0 0 1 4 0v1M10 7h2M10 9.5h2",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Background")
        )
        self.load_artisan_background_button_viewer.clicked.connect(self.load_roast_in_artisan_background)
        self.load_artisan_background_button_viewer.setToolTip(QApplication.translate("tilauscope_beancave","Load the selected ALog file into Artisan's background for comparison."))
        self.load_artisan_background_button_viewer.setEnabled(False)

        # Export: the label, the card, the curve image — and the printer's state.
        self.export_button = _vbtn("M7 2v7M4 6l3 3 3-3M2.5 11.5h9",
                                   QT_TRANSLATE_NOOP("tilauscope_beancave", "Export"))
        self.export_button.setStyleSheet(
            "QPushButton { padding-right: 22px; }"
            "QPushButton::menu-indicator { subcontrol-origin: padding;"
            " subcontrol-position: center right; right: 8px; }")
        self.export_button.setEnabled(False)
        export_menu = QMenu(self.export_button)
        export_menu.setStyleSheet(menu_qss())
        self.print_pdf_label_action = export_menu.addAction(
            QApplication.translate("tilauscope_beancave", "Label (PDF)"))
        self.print_pdf_label_action.triggered.connect(self.generate_and_print_pdf_label)
        self.print_label_action = export_menu.addAction(
            QApplication.translate("tilauscope_beancave", "Print label"))
        self.print_label_action.triggered.connect(self.generate_and_print_label)
        self.print_label_action.changed.connect(self._sync_print_label_text)
        self.roast_card_action = export_menu.addAction(
            QApplication.translate("tilauscope_beancave", "Roast card (PNG)"))
        self.roast_card_action.triggered.connect(self.on_export_roast_card)
        self.curve_image_action = export_menu.addAction(
            QApplication.translate("tilauscope_beancave", "Curve image (PNG)"))
        export_menu.addSeparator()
        self.niimbot_overlay = NiimbotStatusOverlay()
        printer_state = QWidgetAction(export_menu)
        printer_state.setDefaultWidget(self.niimbot_overlay)
        export_menu.addAction(printer_state)
        self.export_button.setMenu(export_menu)

        self.more_button = QPushButton("⋯")
        self.more_button.setProperty('variant', 'icon')
        self.more_button.setFixedSize(34, 30)
        self.more_button.setToolTip(QApplication.translate("tilauscope_beancave", "More actions"))
        self.more_button.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        more_menu = QMenu(self.more_button)
        more_menu.setStyleSheet(menu_qss())
        self.roast_finished_action = more_menu.addAction(
            QApplication.translate("tilauscope_beancave", "Record result…"))
        self.roast_finished_action.triggered.connect(self.on_roast_finished_clicked)
        self.planning_action = more_menu.addAction(QApplication.translate("tilauscope_beancave", "Planning"))
        self.planning_action.triggered.connect(self.show_roast_ready_view)
        self.dial_in_action = more_menu.addAction(QApplication.translate("tilauscope_beancave", "Dial-in"))
        self.dial_in_action.triggered.connect(self.show_barista_expert_view)
        self.data_action = more_menu.addAction(QApplication.translate("tilauscope_beancave", "Data"))
        self.data_action.triggered.connect(self.show_data_reader_view)
        more_menu.addSeparator()
        self.refresh_action = more_menu.addAction(QApplication.translate("tilauscope_beancave", "Refresh list"))
        self.refresh_action.triggered.connect(self.list_alog_files)
        self.more_button.setMenu(more_menu)
        for menu in (export_menu, more_menu):
            for action in menu.actions():
                action.setMenuRole(QAction.MenuRole.NoRole)   # macOS moves look-alikes of Quit or About
        for action in (self.print_pdf_label_action, self.print_label_action, self.roast_card_action,
                       self.curve_image_action, self.roast_finished_action, self.planning_action,
                       self.dial_in_action, self.data_action):
            action.setEnabled(False)
        self._sync_print_label_text()

        # ── The detail head: the roast on screen, or the roasts compared ──────
        self.roast_detail_title = QLabel("")
        self.roast_detail_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.roast_detail_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.roast_detail_title.setMinimumWidth(80)
        self.roast_detail_meta = QLabel("")
        self.roast_detail_meta.setProperty('variant', 'secondary')
        self.roast_compare_chips = QLabel("")
        self.roast_compare_chips.setTextFormat(Qt.TextFormat.RichText)
        self.roast_compare_chips.setWordWrap(True)
        self.roast_compare_clear = QPushButton(
            QApplication.translate("tilauscope_beancave", "Clear") + " ✕")
        self.roast_compare_clear.setProperty('variant', 'ghost')
        self.roast_compare_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.roast_compare_clear.clicked.connect(self._leave_comparison)
        self.roast_compare_note = QLabel("")
        self.roast_compare_note.setProperty('variant', 'caption')

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(self.roast_detail_title, 1)
        for widget in (self.load_artisan_button_viewer, self.load_artisan_background_button_viewer,
                       self.export_button, self.more_button):
            title_row.addWidget(widget)
        meta_row = QHBoxLayout()
        meta_row.addWidget(self.roast_detail_meta, 1)
        meta_row.addWidget(self.roast_compare_chips, 1)
        meta_row.addWidget(self.roast_compare_clear)

        self.roast_result_banner = ResultBanner()
        self.roast_result_banner.record_requested.connect(self.on_roast_finished_clicked)

        self.roast_tiles = [KpiTile() for _ in range(4)]
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(8)
        for tile in self.roast_tiles:
            tiles_row.addWidget(tile, 1)

        self._roast_detail_head = QWidget()
        head_layout = QVBoxLayout(self._roast_detail_head)
        head_layout.setContentsMargins(0, 0, 0, 4)
        head_layout.setSpacing(6)
        head_layout.addLayout(title_row)
        head_layout.addLayout(meta_row)
        head_layout.addWidget(self.roast_compare_note)
        head_layout.addWidget(self.roast_result_banner)
        head_layout.addLayout(tiles_row)
        self._show_detail_none()

        splitter = QSplitter(Qt.Orientation.Horizontal) # type: ignore

        # LEFT SIDE: the roast list
        list_widget_container = self._build_roast_list_ui()

        # RIGHT SIDE: the detail head, then Plot, Info & Tabs
        plot_info_container = QWidget()
        plot_info_layout = QVBoxLayout()
        plot_info_layout.addWidget(self._roast_detail_head)

        # The two pages of the curve card: Curve and Statistics
        self.viewer_pages = QStackedWidget()

        # --- Curve page ---
        self.curve_tab = QWidget()
        self.curve_layout = QVBoxLayout(self.curve_tab)
        self.curve_layout.setContentsMargins(0, 0, 0, 0)

        self.fig = Figure(figsize=(7, 4), dpi=100, layout="constrained")
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumSize(400, 300)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        # Fond canvas aligné sur le fond figure (évite les bandes noires de marge)
        self.canvas.setStyleSheet(f"background-color: {_PLOT_PALETTE['background']};")

        self._hover_tooltip = HoverTooltip()

        # ── Bouton zoom : SVG inline, indépendant de la plateforme ──────────
        self.zoom_button = ZoomToggleButton()  # posé sur la ligne de la carte
        self.zoom_button.toggled.connect(self.toggle_canvas_zoom)

        # How several roasts are compared: overlay, consistency or aligned (the View switch).
        self._multi_view_mode = 'overlay'

        # ── Conteneur stable : canvas + overlays (zoom + save markers) ────────
        self.canvas_container = CanvasContainer(self.canvas)

        self.curve_image_action.triggered.connect(lambda _checked=False: self.take_snapshot(self.fig))

        # Save-marker overlay button (ephemeral — visible only after a marker edit)
        self.canvas_container._save_btn.clicked.connect(self._save_timeindex_to_alog)
        # Route canvas right-click / two-finger-tap through eventFilter
        self.canvas.installEventFilter(self)

        self.roast_plot_label = CurveMessageLabel(
            QApplication.translate("tilauscope_beancave", "Select a roast to display the graphs.")
        )
        self.curve_layout.addWidget(self.roast_plot_label)
        self.curve_layout.addWidget(self.canvas_container, 1)  # conteneur = unité de transfert
        self.viewer_pages.addWidget(self.curve_tab)

        # --- Stats Tab ---
        self.stats_tab = QWidget()
        self.stats_layout = QVBoxLayout(self.stats_tab)

        self.roast_info_text = QLabel(QApplication.translate("tilauscope_beancave","Statistics and detailed information (Delta BT, RoR, etc.) will appear here."))
        self.roast_info_text.setWordWrap(True)
        self.roast_info_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.roast_info_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.roast_info_text.setTextFormat(Qt.TextFormat.RichText)  # support HTML tableau multi

        self.stats_scroll = QScrollArea()
        self.stats_scroll.setWidgetResizable(True)
        self.stats_scroll.setWidget(self.roast_info_text)
        self.stats_scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {THEME['BG']}; }}")

        # ── Vue multi : mini-résumé + dot plot (remplace le tableau chargé) ───
        self.stats_multi_widget = QWidget()
        _sm_layout = QVBoxLayout(self.stats_multi_widget)
        _sm_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_summary = QLabel("")
        self.stats_summary.setWordWrap(True)
        self.stats_summary.setTextFormat(Qt.TextFormat.RichText)
        self.stats_summary.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.stats_dot_fig = Figure(figsize=(6, 4), dpi=100, layout="constrained")
        self.stats_dot_canvas = FigureCanvas(self.stats_dot_fig)
        self.stats_dot_canvas.setStyleSheet(f"background-color: {_PLOT_PALETTE['background']};")
        _sm_layout.addWidget(self.stats_summary)
        _sm_layout.addWidget(self.stats_dot_canvas, 1)
        self.stats_multi_widget.setVisible(False)

        self.stats_layout.addWidget(QLabel(QApplication.translate("tilauscope_beancave","Roasting statistics and information")))
        self.stats_layout.addWidget(self.stats_scroll, 1)
        self.stats_layout.addWidget(self.stats_multi_widget, 1)
        self.viewer_pages.addWidget(self.stats_tab)

        # ── The curve card: Curve or Statistics, and the curve's own choices under it ──
        self.detail_page_switch = SegmentedControl(
            [QApplication.translate("tilauscope_beancave", "Curve"),
             QApplication.translate("tilauscope_beancave", "Statistics")], compact=True)
        self.detail_page_switch.set_current(0)
        self.detail_page_switch.changed.connect(self._on_detail_page_changed)
        curve_card = QFrame()
        curve_card.setObjectName('roastCurveCard')
        # The card takes the figure's ground, so the plot shows no seam.
        curve_card.setStyleSheet(
            f"QFrame#roastCurveCard {{ background-color: {_PLOT_PALETTE['background']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}")
        card_layout = QVBoxLayout(curve_card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)
        # The card's own row: the two pages on the left, full screen on the right,
        # clear of the plot — over the canvas the button covered the temperature axis.
        self.curve_header_row = QHBoxLayout()
        self.curve_header_row.setContentsMargins(0, 0, 0, 0)
        self.curve_header_row.addWidget(self.detail_page_switch)
        self.curve_header_row.addStretch(1)
        self.curve_header_row.addWidget(self.zoom_button)
        card_layout.addLayout(self.curve_header_row)
        card_layout.addWidget(self.viewer_pages, 1)

        settings = QSettings()
        self._curve_view = settings.value(self._CURVE_VIEW_KEY, 'both', str)
        if self._curve_view not in self._CURVE_VIEWS:
            self._curve_view = 'both'
        self._curve_range = settings.value(self._CURVE_RANGE_KEY, 'auto', str)
        if self._curve_range not in self._CURVE_RANGES:
            self._curve_range = 'auto'
        self._curve_custom_range = self._parse_custom_range(settings.value(self._CURVE_CUSTOM_KEY, "", str))
        self._curve_show_settings = settings.value(self._CURVE_SETTINGS_KEY, True, bool)

        self.curve_view_switch = SegmentedControl(
            [QApplication.translate("tilauscope_beancave", "Temperatures"),
             QApplication.translate("tilauscope_beancave", "Rate of rise"),
             QApplication.translate("tilauscope_beancave", "Both")], compact=True)
        self.curve_view_switch.set_current(self._CURVE_VIEWS.index(self._curve_view))
        self.curve_view_switch.changed.connect(self._on_curve_view_changed)

        consistency_help = QT_TRANSLATE_NOOP("tilauscope_beancave",
            "<b>Consistency view</b><br>"
            "The reference roast as a solid line, with a shaded "
            "<b>min–max band</b> of all the selected roasts (bean temp &amp; RoR).<br>"
            "A <span style='color:#A6E3A1'>tight band</span> means your roasts are "
            "repeatable; a <span style='color:#F38BA8'>wide band</span> shows where "
            "they drift apart.")
        aligned_help = QT_TRANSLATE_NOOP("tilauscope_beancave",
            "<b>Aligned view (time-warp)</b><br>"
            "Stretches each roast in time so its milestones (CHARGE, TP, DRY END, "
            "FC start, DROP) line up with the reference.<br>"
            "Lets you compare the <b>shape of the bean-temperature rise within each "
            "phase</b>, regardless of how long that phase actually lasted.<br>"
            "<i>BT only — RoR is hidden because warping time distorts its scale.</i>")
        self.compare_view_switch = SegmentedControl(
            [QApplication.translate("tilauscope_beancave", "Overlay"),
             QApplication.translate("tilauscope_beancave", "Consistency"),
             QApplication.translate("tilauscope_beancave", "Aligned")], compact=True)
        self.compare_view_switch.set_current(0)
        self.compare_view_switch.set_tooltip(1, QApplication.translate("tilauscope_beancave", consistency_help))
        self.compare_view_switch.set_tooltip(2, QApplication.translate("tilauscope_beancave", aligned_help))
        self.compare_view_switch.changed.connect(self._on_compare_view_changed)
        self.compare_view_switch.hide()

        self.curve_range_switch = SegmentedControl(
            [QApplication.translate("tilauscope_beancave", "Auto"),
             QApplication.translate("tilauscope_beancave", "0–12 min"),
             QApplication.translate("tilauscope_beancave", "Custom…")], compact=True)
        self.curve_range_switch.set_current(self._CURVE_RANGES.index(self._curve_range))
        self.curve_range_switch.activated.connect(self._on_curve_range_activated)

        self.burner_air_button = QPushButton()
        self.burner_air_button.setObjectName('burnerAirPill')
        self.burner_air_button.setCheckable(True)
        self.burner_air_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.burner_air_button.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Show the burner, air and drum settings under the curve."))
        self.burner_air_button.setStyleSheet(f"""
            QPushButton#burnerAirPill {{
                background: transparent; color: {THEME['SUBTEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 13px; padding: 4px 12px;
            }}
            QPushButton#burnerAirPill:hover {{ color: {THEME['TEXT']}; }}
            QPushButton#burnerAirPill:checked {{
                background-color: {tint('ACCENT', 40)}; color: {THEME['ACCENT']};
                border-color: {tint('ACCENT', 110)};
            }}
        """)
        self.burner_air_button.setChecked(self._curve_show_settings)
        self._sync_burner_air_text()
        self.burner_air_button.toggled.connect(self._on_burner_air_toggled)

        view_caption = QLabel(QApplication.translate("tilauscope_beancave", "View"))
        view_caption.setProperty('variant', 'caption')
        view_switches = QHBoxLayout()
        view_switches.setSpacing(0)
        view_switches.addWidget(self.curve_view_switch)
        view_switches.addWidget(self.compare_view_switch)
        view_group = QVBoxLayout()
        view_group.setSpacing(3)
        view_group.addWidget(view_caption)
        view_group.addLayout(view_switches)
        range_caption = QLabel(QApplication.translate("tilauscope_beancave", "Time range"))
        range_caption.setProperty('variant', 'caption')
        range_group = QVBoxLayout()
        range_group.setSpacing(3)
        range_group.addWidget(range_caption)
        range_group.addWidget(self.curve_range_switch)

        self.curve_bar = QWidget()
        bar = QHBoxLayout(self.curve_bar)
        bar.setContentsMargins(2, 2, 2, 0)
        bar.setSpacing(18)
        bar.addLayout(view_group)
        bar.addLayout(range_group)
        bar.addStretch(1)
        bar.addWidget(self.burner_air_button, 0, Qt.AlignmentFlag.AlignBottom)

        plot_info_layout.addWidget(curve_card, 1)
        plot_info_layout.addWidget(self.curve_bar)
        plot_info_container.setLayout(plot_info_layout)

        splitter.addWidget(list_widget_container)
        splitter.addWidget(plot_info_container)
        splitter.setSizes([340, 860]) # Initial split

        self.roast_viewer_layout.addWidget(splitter, 1)

        self.roast_viewer_tab.setLayout(self.roast_viewer_layout)

        QTimer.singleShot(0, self.list_alog_files)

    #: The order the roast list was left in.
    _ROAST_SORT_KEY: str = 'Beancave/RoastListSort'
    #: What the curve shows, kept from one session to the next.
    _CURVE_VIEW_KEY: str = 'Beancave/RoastCurveView'
    _CURVE_RANGE_KEY: str = 'Beancave/RoastCurveRange'
    _CURVE_CUSTOM_KEY: str = 'Beancave/RoastCurveCustomRange'
    _CURVE_SETTINGS_KEY: str = 'Beancave/RoastCurveSettings'
    _CURVE_VIEWS: tuple[str, ...] = ('temps', 'ror', 'both')
    _CURVE_RANGES: tuple[str, ...] = ('auto', 'fixed', 'custom')

    def _build_roast_list_ui(self) -> QWidget:
        """The left side of the Roasts tab: search, coffee, order, the list and its count."""
        # The selection is kept here, not read off the view: see selected_roast_fnames.
        self._selected_fnames: list[str] = []
        self._selection_silence = 0
        self._list_scanning = False
        self._roast_folder_missing = False
        self._roast_empty_action = ""

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_beancave", "Roasts"))
        title.setProperty('variant', 'title')
        self.roast_total_label = QLabel("")
        self.roast_total_label.setProperty('variant', 'caption')
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.roast_total_label)
        layout.addLayout(head)

        self.roast_search = RoastSearchField()
        self.roast_search.setPlaceholderText(
            QApplication.translate("tilauscope_beancave", "Search coffee, process, batch #"))
        self.roast_search.setClearButtonEnabled(True)
        self.roast_search.addAction(make_icon(SVG_SEARCH, THEME['SUBTEXT'], QSize(14, 14)),
                                    QLineEdit.ActionPosition.LeadingPosition)
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(120)
        self._search_debounce.timeout.connect(self._on_roast_search_settled)
        self.roast_search.textChanged.connect(self._on_roast_search_edited)
        self.roast_search.move_to_list.connect(self._focus_roast_list)
        layout.addWidget(self.roast_search)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.roast_coffee_combo = QComboBox()
        self.roast_coffee_combo.setView(styled_popup_view(min_width=260))
        style_combo_popup(self.roast_coffee_combo)
        self.roast_coffee_combo.addItem(QApplication.translate("tilauscope_beancave", "All coffees"), "")
        self.roast_sort_combo = QComboBox()
        self.roast_sort_combo.setView(styled_popup_view())
        style_combo_popup(self.roast_sort_combo)
        self.roast_sort_combo.addItem(QApplication.translate("tilauscope_beancave", "Most recent"), SORT_RECENT)
        self.roast_sort_combo.addItem(QApplication.translate("tilauscope_beancave", "Oldest first"), SORT_OLDEST)
        self.roast_sort_combo.addItem(QApplication.translate("tilauscope_beancave", "Coffee A–Z"), SORT_COFFEE)
        saved_sort = QSettings().value(self._ROAST_SORT_KEY, SORT_RECENT, str)
        self.roast_sort_combo.setCurrentIndex(max(self.roast_sort_combo.findData(saved_sort), 0))
        for combo in (self.roast_coffee_combo, self.roast_sort_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        filters.addWidget(self.roast_coffee_combo, 3)
        filters.addWidget(self.roast_sort_combo, 2)
        layout.addLayout(filters)

        self._roast_model = RoastListModel(self)
        self._roast_proxy = RoastFilterProxy(self)
        self._roast_proxy.setSourceModel(self._roast_model)
        self._roast_proxy.set_sort(self.roast_sort_combo.currentData() or SORT_RECENT)
        locale_str = getattr(getattr(self.aw, 'qmc', None), 'locale_str', None)
        if isinstance(locale_str, str) and locale_str:
            self._roast_proxy.set_locale(QLocale(locale_str))
        self.roast_list_view = RoastListView()
        self.roast_list_view.setModel(self._roast_proxy)
        self.roast_list_view.setItemDelegate(RoastRowDelegate(self._roast_proxy, self.roast_list_view))
        # A Shift- or Ctrl-click changes the selection several times in a row.
        # The single-shot timer restarts on each change, so the curve loads once,
        # 80 ms after the last one.
        self._selection_debounce = QTimer(self)
        self._selection_debounce.setSingleShot(True)
        self._selection_debounce.setInterval(80)
        self._selection_debounce.timeout.connect(self.load_roast_data_and_plot)
        self.roast_list_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.roast_coffee_combo.currentIndexChanged.connect(self._on_roast_coffee_changed)
        self.roast_sort_combo.currentIndexChanged.connect(self._on_roast_sort_changed)

        empty = QFrame()
        empty.setProperty('variant', 'card')
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        self.roast_empty_title = QLabel("")
        self.roast_empty_title.setProperty('variant', 'title')
        self.roast_empty_text = QLabel("")
        self.roast_empty_text.setProperty('variant', 'secondary')
        self.roast_empty_text.setWordWrap(True)
        for label in (self.roast_empty_title, self.roast_empty_text):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(label)
        self.roast_empty_button = QPushButton("")
        self.roast_empty_button.setProperty('variant', 'outline')
        self.roast_empty_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.roast_empty_button.clicked.connect(self._on_roast_empty_action)
        empty_layout.addWidget(self.roast_empty_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)

        self.roast_list_stack = QStackedWidget()
        self.roast_list_stack.addWidget(self.roast_list_view)
        self.roast_list_stack.addWidget(empty)
        layout.addWidget(self.roast_list_stack, 1)

        self._multi_progress = TilauProgressRow()
        self._multi_progress.hide()
        layout.addWidget(self._multi_progress)

        footer = QHBoxLayout()
        self.roast_count_label = QLabel("")
        self.roast_count_label.setProperty('variant', 'caption')
        self.roast_clear_filters_button = QPushButton(
            QApplication.translate("tilauscope_beancave", "Clear filters"))
        self.roast_clear_filters_button.setProperty('variant', 'ghost')
        self.roast_clear_filters_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.roast_clear_filters_button.clicked.connect(self._clear_roast_filters)
        self.roast_clear_filters_button.hide()
        footer.addWidget(self.roast_count_label)
        footer.addStretch(1)
        footer.addWidget(self.roast_clear_filters_button)
        layout.addLayout(footer)

        find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self.roast_viewer_tab)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(self._focus_roast_search)
        return container

    @pyqtSlot()
    def _reconnect_hover(self) -> None:
        """Reconnecte le bon handler hover selon le mode courant (mono/multi).

        Both hover connections are made here and nowhere else. The leave handler
        used to be connected beside each plot call without ever being dropped,
        so clicking through a session's roasts left one live callback per roast
        and every mouse exit ran them all.
        """
        for cid_attr in ('hover_cid', 'hover_lid'):
            cid = getattr(self, cid_attr, None)
            if cid is not None:
                try:
                    self.canvas.mpl_disconnect(cid)
                except Exception:
                    pass
        handler = self._on_multi_hover if self._multi_mode else self.on_plot_hover
        self.hover_cid = self.canvas.mpl_connect('motion_notify_event', handler)
        self.hover_lid = self.canvas.mpl_connect('figure_leave_event', self.on_plot_leave)

    @pyqtSlot(bool)
    def toggle_canvas_zoom(self, checked: bool = False) -> None:
        self.is_zoomed = checked
        if checked:
            # Transfert du conteneur entier (canvas + bouton) dans le dialog
            self.zoom_dialog = QDialog(self)
            # Le fond du dialogue borde le canvas : sans règle il tombe sur le
            # blanc système. Même teinte que la figure → aucune couture visible.
            self.zoom_dialog.setStyleSheet(
                f"QDialog {{ background-color: {_PLOT_PALETTE['background']}; }}")
            self.zoom_dialog.setWindowTitle(
                QApplication.translate(
                    "tilauscope_beancave",
                    "Curve Full Screen - Press ESC to exit"
                )
            )
            zoom_layout = QVBoxLayout(self.zoom_dialog)
            zoom_layout.setContentsMargins(0, 0, 0, 0)
            # The button follows the curve into the dialog: it is the way back out.
            zoom_head = QHBoxLayout()
            zoom_head.setContentsMargins(8, 8, 8, 0)
            zoom_head.addStretch(1)
            zoom_head.addWidget(self.zoom_button)
            zoom_layout.addLayout(zoom_head)
            zoom_layout.addWidget(self.canvas_container)   # conteneur, pas le canvas nu
            self.zoom_dialog.showMaximized()
            self.zoom_dialog.finished.connect(self.restore_canvas_position)
        else:
            if hasattr(self, "zoom_dialog") and self.zoom_dialog:
                dlg = self.zoom_dialog
                self.zoom_dialog = None
                # Déconnecter avant close() pour éviter le double-appel via finished
                try:
                    dlg.finished.disconnect(self.restore_canvas_position)
                except (TypeError, RuntimeError):
                    pass
                dlg.close()
                self.restore_canvas_position()
                # The canvas is back in the main layout, so the dialog owns
                # nothing now. Without this it stayed parented to the Bean Cave
                # and one dead dialog piled up per full-screen cycle.
                dlg.deleteLater()
        # The button is enabled in multi mode before any single roast has plotted,
        # so the hover annotation may not exist yet. This runs from a Qt slot: an
        # AttributeError here reaches the excepthook and closes the application.
        annotation = getattr(self, 'annotation', None)
        if annotation is not None:
            annotation.set_fontsize(12 if checked else 7)
        self._reconnect_hover()
        self.canvas.draw()

    def restore_canvas_position(self) -> None:
        """Restitue le canvas_container dans son layout d'origine."""
        self.curve_layout.insertWidget(1, self.canvas_container)
        self.curve_header_row.addWidget(self.zoom_button)  # revient sur la ligne de la carte
        # Resynchroniser l'icône si le dialog a été fermé par ESC / bouton OS
        if self.zoom_button.isChecked():
            self.zoom_button.setChecked(False)  # déclenche _sync_icon via toggled
        self._reconnect_hover()
        self.is_zoomed = False

    def show_roast_ready_view(self):
        # Utilise la liste des fichiers .alog déjà chargés par list_alog_files()
        if not self.roast_count() > 0:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Error"), QApplication.translate("tilauscope_beancave","No file found."), QMessageBox.Icon.Warning)
            return
        self._pending_brew_filepath = None
        self._pending_observe_filepath = None
        dlg = RoastReadyDialog(str(self.alog_directory), self._metadata_cache.records, None, aw=self.aw)
        dlg.brew_requested.connect(self._on_timeline_brew_requested)
        dlg.observe_requested.connect(self._on_timeline_observe_requested)
        dlg.exec()
        # The timeline closes itself right after asking to brew; open the advisor
        # once exec() returns so we never stack a modal over the (stays-on-top) timeline.
        fp, self._pending_brew_filepath = self._pending_brew_filepath, None
        if fp:
            self.open_brew_advisor_for(fp)
        # Same deferral for the "observe this roast" hand-off (card title clicked).
        ofp, self._pending_observe_filepath = self._pending_observe_filepath, None
        if ofp:
            self.observe_roast_in_tilauscope(ofp)

    @pyqtSlot(str)
    def _on_timeline_brew_requested(self, filepath: str) -> None:
        self._pending_brew_filepath = filepath

    @pyqtSlot(str)
    def _on_timeline_observe_requested(self, filepath: str) -> None:
        self._pending_observe_filepath = filepath

    def observe_roast_in_tilauscope(self, filepath: str) -> None:
        """Timeline hand-off: load the roast in the main TilauScope window and
        mirror it in the Roast Viewer tab, so the profile is on screen in both
        places at once."""
        fp = Path(filepath)
        if not filepath or not fp.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Error"),
                               QApplication.translate("tilauscope_beancave", "Could not open this roast file."),
                               QMessageBox.Icon.Warning)
            return
        try:
            cur_file = getattr(self.aw, 'curFile', None)
            already_open = bool(cur_file) and Path(cur_file).resolve() == fp.resolve()
            if not already_open:
                self.aw.loadFile(str(fp))
        except Exception as e:
            _logd.error(f"observe_roast_in_tilauscope: failed to load {fp}: {e}")
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Loading error"),
                               QApplication.translate("tilauscope_beancave", "An error occurred while loading file") + f": {e}",
                               QMessageBox.Icon.Critical)
            return
        # Mirror the selection in the Roast Viewer tab and bring it to the front.
        try:
            if self.select_roast(fp.name):
                self.load_roast_data_and_plot()
            tabs = getattr(self, 'tab_widget', None)
            viewer_tab = getattr(self, 'roast_viewer_tab', None)
            if tabs is not None and viewer_tab is not None:
                tabs.setCurrentWidget(viewer_tab)
        except Exception as e:
            _logd.warning(f"observe_roast_in_tilauscope: could not mirror {fp.name} in the viewer: {e}")

    def open_brew_advisor_for(self, filepath: str) -> None:
        """Timeline hand-off: pre-select the roast in the left list and open the
        Brew Advisor for it. Routes through the normal load pipeline so the profile
        is fully enriched (weight loss, phases) before advising."""
        fp = Path(filepath)
        if not filepath or not fp.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Error"),
                               QApplication.translate("tilauscope_beancave", "Could not open this roast file."),
                               QMessageBox.Icon.Warning)
            return
        # Already the loaded roast → advise straight away (full fidelity).
        if self.current_roast_fname() == fp.name and getattr(self, 'lastprofiledata', None):
            self.show_barista_expert_view(self.lastprofiledata)
            return
        if self.select_roast(fp.name):
            # _alog_worker_finished_on_plot_ok opens the advisor once loaded.
            self._pending_brew_after_load = fp.name
            self.load_roast_data_and_plot()
            return
        # Not in the list (rare) → load directly; advice is still valid, minus the
        # computed-only notes (weight loss / development phases).
        data = self.get_alog_data(fp)
        if data:
            self.show_barista_expert_view(data)
        else:
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Error"),
                               QApplication.translate("tilauscope_beancave", "Could not open this roast file."),
                               QMessageBox.Icon.Warning)

    @staticmethod
    def formater_nom_fichier_cafe(nom_fichier_brut):
        nom_intermediaire = nom_fichier_brut
#        for long_name, short_name in self.replacement_map.items():
#           nom_intermediaire = nom_intermediaire.replace(long_name, short_name)

        for variation, standard_name in standardization_map.items():
            nom_intermediaire = re.sub(re.escape(variation), standard_name, nom_intermediaire, flags=re.IGNORECASE)

        nom_nettoye = re.sub(r'[\s\-_\/]+', ' ', nom_intermediaire).strip()
        nom_nettoye = nom_nettoye.replace(' - ', ' ')
        nom_nettoye = nom_nettoye.replace('- ', ' ')
        nom_nettoye = nom_nettoye.replace(' -', ' ')

        # 3. Supprimer tout ce qui est entre parenthèses
        nom_nettoye = re.sub(r'\s*\(.*?\)', '', nom_nettoye).strip()
        date_heure_pattern = r"([\-|_|\s](\d{2}[-|\s]?\d{2}[-|\s]?\d{2})[_ -]?(\d{4})?)\.?$"
        match = re.search(date_heure_pattern, nom_nettoye)

        if match:
            suffixe_brut = match.group(1).strip()
            nom_base = nom_nettoye.replace(suffixe_brut, '').strip()
            nom_propre = re.sub(r'[.\-\s_]+$', '', nom_base).strip()

            chiffres_suffixe = re.findall(r'\d+', suffixe_brut)

            if len(chiffres_suffixe) >= 3:
                date_str = "".join(chiffres_suffixe[:3])
                heure_str = chiffres_suffixe[3] if len(chiffres_suffixe) >= 4 and len(chiffres_suffixe[3]) == 4 else "0000"

                date_format = "%y%m%d%H%M"

                try:
                    dt_objet = datetime.strptime(f"{date_str}{heure_str}", date_format)
                    date_formatee = dt_objet.strftime("%Y/%m/%d at %H:%M")

                    return f"{nom_propre} ({date_formatee})"

                except ValueError:
                    return nom_propre
            else:
                return nom_propre

        else:
            # Si aucun pattern de date/heure n'est trouvé
            return re.sub(r'[.\-\s_]+$', '', nom_nettoye).strip()

    def get_alog_data(self, file_path: str | Path) -> ProfileData | None:
        """Lit, décode et parse un fichier .alog avec mise en cache par date de modification."""
        path = Path(file_path)
        if not path.exists():
            return None

        try:
            current_mtime = path.stat().st_mtime

            # Si le fichier est déjà en cache et n'a pas été modifié.
            # Une seule opération : tester puis indexer laissait une éviction du
            # thread de chargement se glisser entre les deux, et le KeyError
            # ressortait en « lecture impossible », courbe vide.
            cached = self._alog_cache.get(str(path))
            if cached is not None:
                cached_mtime, cached_data = cached
                if current_mtime == cached_mtime:
                    return cached_data

            # Lecture et parsing — format natif Artisan : repr(dict) écrit en UTF-8
            # (cf. artisanlib.util.serialize/deserialize). NE PAS décoder en
            # unicode_escape : les octets UTF-8 des accents seraient mal interprétés
            # (mojibake « café » → « cafÃ© »). literal_eval gère les échappements.
            decoded_content = path.read_text(encoding='utf-8')
            data = cast('ProfileData', ast.literal_eval(decoded_content))

            # Mise en cache — LRU cap 5 : supprimer l'entrée la plus ancienne si nécessaire.
            # Sous verrou : ce cache est écrit par le thread de chargement ET par
            # le thread GUI, et l'éviction (itérer puis supprimer) n'est pas
            # atomique — une lecture concurrente y perdait son résultat sur un
            # « dictionary changed size during iteration ».
            with self._alog_cache_lock:
                if str(path) not in self._alog_cache and len(self._alog_cache) >= ALOG_CACHE_MAX:
                    oldest_key = next(iter(self._alog_cache))
                    del self._alog_cache[oldest_key]
                self._alog_cache[str(path)] = (current_mtime, data)
            return data

        except Exception as e:
            _log.error(f"could not read/parse {path.name}: {e}", exc_info=True)
            return None

    def peek_alog_cache(self, file_path: str | Path) -> ProfileData | None:
        """The parsed profile only if it is ALREADY cached and still current.

        ``get_alog_data`` parses on a miss, so using it as the "is it cached?"
        test made the comparison view read and parse every selected roast on the
        GUI thread — and left the worker branch behind it unreachable, since a
        None answer there means the parsing failed, not that the file was absent
        from the cache.
        """
        path = Path(file_path)
        try:
            entry = self._alog_cache.get(str(path))
            if entry is None:
                return None
            cached_mtime, cached_data = entry
            return cached_data if path.stat().st_mtime == cached_mtime else None
        except OSError:
            return None

    def _stop_list_scan(self) -> None:
        """Stop a folder scan already in flight, and forget it.

        ``list_alog_files`` is reached twice on the way in — once deferred from
        the viewer build, once when the metadata index finishes — and the second
        call used to overwrite the handle to the first. The first kept running,
        still wired to the list it was about to repaint, and invisible to
        teardown because nothing pointed at it any more.

        Every Qt access here can raise on an object ``deleteLater`` already
        collected, so the whole body is guarded: an exception escaping this far
        reaches the application's exception hook, which is not a place a routine
        refresh should ever end up.
        """
        thread = getattr(self, '_list_thread', None)
        worker = getattr(self, '_list_worker', None)
        self._list_thread = None
        self._list_worker = None
        if thread is None:
            return
        try:
            # Both handlers must go before the wait: `finished` would repaint the
            # list from a scan being abandoned, and `_on_list_thread_done` arrives
            # late enough to null the handles of the scan replacing this one.
            for owner, signal_name, slot in (
                    (worker, 'finished', self._on_alog_list_ready),
                    (thread, 'finished', self._on_list_thread_done)):
                if owner is None:
                    continue
                try:
                    getattr(owner, signal_name).disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            if thread.isRunning():
                thread.requestInterruption()   # the worker checks it as it walks
                thread.quit()
                if not thread.wait(2000):
                    # No terminate(): it kills the thread at an arbitrary
                    # instruction and can leave a Qt-internal mutex locked for
                    # good — the next Bean Cave then freezes while it builds a
                    # widget, with no crash and no log. The worker checks
                    # isInterruptionRequested as it walks, so waiting once more
                    # is the safe move.
                    _log.warning('alog list scan did not stop cooperatively — waiting once more')
                    if not thread.wait(2000):
                        _log.error('alog list scan is still running and was left to finish on its own')
        except RuntimeError:
            pass  # Qt object already collected by deleteLater

    @pyqtSlot()
    def list_alog_files(self) -> None:
        # Path("") is PosixPath("."), which is truthy and exists — so an unset
        # setting used to sail past this guard and scan the working directory
        # instead, which startup has already moved to the user data folder.
        raw_dir = str(self.alog_directory or "").strip()
        if not raw_dir or raw_dir == '.':
            _log.warning("no roast folder configured — the roast list stays empty")
            self._show_missing_roast_folder()
            return
        directory = Path(raw_dir)
        if not directory.exists() or not directory.is_dir():
            self.roast_plot_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "The specified ALog directory does not exist or is not a directory."))
            self._show_missing_roast_folder()
            return
        self._roast_folder_missing = False

        # Capture the current selection + scroll BEFORE clearing so a
        # background refresh can restore the user's position (clear() wipes both,
        # so reading currentItem() after the rebuild would always return None → row 0).
        # Guarded: keeps a good snapshot rather than overwriting it with an empty one
        # (the auto-refresh already snapshotted at trigger_cache_refresh time).
        self._snapshot_list_selection()

        # Clear immediately so the UI doesn't show stale data during the scan.
        # Silently: the selection is kept, and a pending reload armed against an
        # empty list would paint "select a roast" over a rebuild the operator
        # never asked for.
        with self._silently():
            self._roast_model.set_rows([])
        self._selection_debounce.stop()

        # One scan at a time: a second one would leave the first running.
        self._stop_list_scan()
        self._list_scanning = True
        self._update_list_chrome()

        # Offload glob + regex formatting to a background thread. The generation
        # names the scan its result belongs to.
        self._list_scan_gen = getattr(self, '_list_scan_gen', 0) + 1
        self._list_thread, self._list_worker = self._launch_worker(
            _AlogListWorker(directory, self._metadata_cache.records, self._bean_facts(), self._list_scan_gen),
            on_ok=self._on_alog_list_ready,
            on_err=lambda e: _log.error(f"roast folder scan failed: {e}"),
            on_done=self._on_list_thread_done,
        )

    @pyqtSlot()
    def _on_list_thread_done(self) -> None:
        self._list_thread = None
        self._list_worker = None
        # A scan that failed painted nothing: stop waiting for it.
        if self._list_scanning:
            self._list_scanning = False
            self._update_list_chrome()

    @pyqtSlot(int, list)
    def _on_alog_list_ready(self, generation: int, items: list) -> None:
        """Called on the main thread when the background file scan is done."""
        # Drop a result from a scan that has since been replaced. Disconnecting
        # the worker cannot do this on its own: by the time a scan is abandoned
        # its result may already be queued, and a queued emission is delivered
        # whatever happens to the connection afterwards. Never sender(): the
        # worker deletes itself as it emits, so by delivery sender() can name an
        # unrelated object (the rows were dropped) or a deleted one (a crash).
        if generation != getattr(self, '_list_scan_gen', 0):
            # Dropping a replaced scan is routine — two run on the way in, and
            # the first is meant to lose. Dropping one with an empty list and no
            # scan behind it is not: nothing will paint, and the operator is
            # left with a blank list the log never mentions. Say that one out loud.
            if (self.roast_count() == 0
                    and getattr(self, '_list_worker', None) is None):
                _log.warning(
                    "a roast scan finished after being replaced, with nothing "
                    "running behind it — the roast list is left empty")
            else:
                _logd.debug("dropping the result of a roast scan that was replaced")
            return

        # This handler owns the painted list, so it replaces every row. Adding to
        # what is there leaves two results appending to each other, and every
        # roast appears twice. Silently: a rebuild is not a selection.
        with self._silently():
            self._roast_model.set_rows(items)
        self._selection_debounce.stop()
        self._list_scanning = False
        self._refresh_coffee_filter()
        self._update_list_chrome()

        if not items:
            _log.warning(f"roast folder scan returned nothing: {self.alog_directory}")
            return
        _log.info(f"roast list painted: {len(items)} roasts")

        if self.roast_count() > 0:
            if not self.hasfinished:
                self.select_roast(self._roast_to_select_on_open())
                self.hasfinished = True
                self.load_roast_data_and_plot()
                self._populate_plan_roast_combo()
            else:
                # Background refresh — the selection outlives the rebuild. When none
                # of it survives (its files are gone, or a concurrent startup refresh
                # left none), fall back to the roast captured before the rescan, then
                # the profile loaded in Artisan, then the order of a fresh open —
                # never blindly to the top row, which would clobber the initial
                # curFile selection.
                listed = {fname for fname, _epoch in self.listed_roasts()}
                kept = [fname for fname in self._selected_fnames if fname in listed]
                if kept:
                    changed = kept != self._selected_fnames
                    self._selected_fnames = kept
                    self._highlight_selected()
                else:
                    cur_file = Path(self.aw.curFile).name if self.aw.curFile else ""
                    target = next((fname for fname in (getattr(self, "_pending_restore_fname", ""), cur_file)
                                   if fname and fname in listed), "") or self._roast_to_select_on_open()
                    changed = self.select_roast(target)
                # Reselecting in silence is deliberate — a background refresh must
                # not reload a curve that is already right. But silence also means
                # nothing repaints, so the one case that must not be left alone is
                # a curve showing something else, or nothing at all.
                shown = self._selected_fnames
                stale = (shown[0] != self._displayed_fname) if len(shown) == 1 else changed
                if shown and stale:
                    self.load_roast_data_and_plot()
                # Restore the scroll position so the list doesn't jump under the cursor.
                self.roast_list_view.verticalScrollBar().setValue(
                    getattr(self, "_pending_restore_scroll", 0))

    @pyqtSlot(int)
    def _on_roaster_model_changed(self, index: int):
        self.current_roaster_model = self.roaster_combo.currentText()
        settings = QSettings()
        settings.setValue("RoastPlan/RoasterModel", self.current_roaster_model)
        _logd.debug(f"Modèle de torréfacteur mis à jour : {self.current_roaster_model}")

    @pyqtSlot()
    def _on_selection_changed(self) -> None:
        """A selection the operator made: keep it, and reload once it settles.

        Selections the code makes itself — a rebuild, a search — pass through
        silently and reload nothing.
        """
        if self._selection_silence:
            return
        self._selected_fnames = self._view_selected_fnames()
        self._remember_selected_roast()
        self._selection_debounce.start()  # restarts when already running

    def _roast_uuid_of(self, filename: str) -> str:
        """The roast's own identity, which a renamed file keeps and a name does not."""
        for meta in self._metadata_cache.records.values():
            if meta.filename == filename:
                return meta.roast_uuid or ""
        return ""

    def _remember_selected_roast(self) -> None:
        """Hold the highlighted roast in memory; `save_settings` writes it out.

        Kept as an attribute rather than written on every click: the operator
        moves through the list freely, and only where they stopped is worth
        carrying to the next session.
        """
        try:
            fname = self.current_roast_fname()
            if fname:
                self._last_roast_uuid = self._roast_uuid_of(fname)
        except (RuntimeError, AttributeError):
            pass

    def _newest_roast_fname(self) -> str:
        """The most recently roasted file in the list, or "".

        The list's first row says nothing about recency: the order is the
        operator's choice. Recency is read from the roast date each row carries —
        the scan works it out from the log, or failing that from the filename.
        """
        best, best_epoch = "", None
        for fname, epoch in self.listed_roasts():
            if best_epoch is None or epoch > best_epoch:
                best, best_epoch = fname, epoch
        return best

    def _roast_to_select_on_open(self) -> str:
        """Where the roast list should land when BeanCave opens.

        In order: the roast open in TilauScope, then the one left highlighted
        last time if it is still there, then the most recent roast.
        """
        listed = {fname for fname, _epoch in self.listed_roasts()}
        cur_file = Path(self.aw.curFile).name if self.aw.curFile else ""
        if cur_file in listed:
            return cur_file

        last_uuid = getattr(self, "_last_roast_uuid", "")
        if last_uuid:
            for meta in self._metadata_cache.records.values():
                if meta.roast_uuid and meta.roast_uuid == last_uuid:
                    if meta.filename in listed:
                        return meta.filename
                    break   # known roast, no longer in this folder

        return self._newest_roast_fname()

    # ── The roast list, read and driven by file name ─────────────────────────
    # Nothing outside these helpers touches the list: printing, plotting and the
    # lifecycle ask for file names. The selection is kept here rather than read
    # off the view, so a search that hides the roast on screen leaves it selected.

    @contextmanager
    def _silently(self):  # noqa: ANN202
        """Selection changes made inside are the code's own: nothing reloads."""
        self._selection_silence += 1
        try:
            yield
        finally:
            self._selection_silence -= 1

    def listed_roasts(self) -> list[tuple[str, int]]:
        """(file name, roast date) of every roast in the folder, whatever the search hides."""
        return [(row.fname, row.epoch) for row in self._roast_model.rows()]

    def shown_roasts(self) -> list[str]:
        """File names the list shows, top to bottom."""
        return [self._roast_proxy.row_at(row).fname for row in range(self._roast_proxy.rowCount())]

    def roast_count(self) -> int:
        """How many roasts the folder holds."""
        return self._roast_model.rowCount()

    def selected_roast_fnames(self) -> list[str]:
        """The roasts the operator selected, top to bottom — kept while a search hides them."""
        return list(self._selected_fnames)

    def current_roast_fname(self) -> str:
        """The roast under the keyboard cursor, else the first one selected, or ""."""
        index = self.roast_list_view.currentIndex()
        if index.isValid():
            return self._roast_proxy.row_at(index.row()).fname
        return self._selected_fnames[0] if self._selected_fnames else ""

    def select_roast(self, fname: str) -> bool:
        """Select this roast alone and remember it, without reloading the curve.

        Silent on purpose: the caller decides whether the curve follows. A roast
        the search hides is selected all the same, only not highlighted. False
        when the folder has no such roast.
        """
        if not fname or self._roast_model.row_of(fname) < 0:
            return False
        self._selected_fnames = [fname]
        self._highlight_selected()
        self._remember_selected_roast()
        return True

    def roast_label(self, fname: str) -> str:
        """The name shown above the curve for this roast, or "" when it is not listed."""
        row = self._roast_model.row_of(fname) if fname else -1
        return self._roast_model.rows()[row].label if row >= 0 else ""

    def _view_selected_fnames(self) -> list[str]:
        rows = sorted(index.row() for index in self.roast_list_view.selectionModel().selectedRows())
        return [self._roast_proxy.row_at(row).fname for row in rows]

    def _highlight_selected(self) -> None:
        """Show the kept selection in the list, as far as the search lets it."""
        proxy, model = self._roast_proxy, self._roast_model
        selection = QItemSelection()
        first = QModelIndex()
        for fname in self._selected_fnames:
            source_row = model.row_of(fname)
            index = proxy.mapFromSource(model.index(source_row, 0)) if source_row >= 0 else QModelIndex()
            if index.isValid():
                selection.select(index, index)
                if not first.isValid():
                    first = index
        with self._silently():
            selection_model = self.roast_list_view.selectionModel()
            selection_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            if first.isValid():
                selection_model.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.roast_list_view.scrollTo(first)
            else:
                selection_model.clearCurrentIndex()

    def _bean_facts(self) -> dict[str, BeanFacts]:
        """What the scan needs from each bean record, copied for its thread."""
        facts: dict[str, BeanFacts] = {}
        for uuid_str, bean in (getattr(self, 'uuidmap', None) or {}).items():
            try:
                facts[uuid_str] = BeanFacts(str(bean.name or ""), str(bean.process or ""),
                                            int(bean.crop or 0), str(bean.farm or ""),
                                            str(bean.country or ""))
            except (AttributeError, TypeError, ValueError):
                continue
        return facts

    def _refresh_coffee_filter(self) -> None:
        """One entry per coffee in the folder, with its roast count; the choice survives a rescan."""
        combo = self.roast_coffee_combo
        chosen = combo.currentData() or ""
        labels: dict[str, str] = {}
        counts: dict[str, int] = {}
        for row in self._roast_model.rows():
            labels.setdefault(row.group, f"{row.title} · {row.crop}" if row.crop else row.title)
            counts[row.group] = counts.get(row.group, 0) + 1
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(QApplication.translate("tilauscope_beancave", "All coffees"), "")
            for group in sorted(labels, key=lambda key: fold(labels[key])):
                combo.addItem(f"{labels[group]} ({counts[group]})", group)
            combo.setCurrentIndex(max(combo.findData(chosen), 0))
        finally:
            combo.blockSignals(False)
        if (combo.currentData() or "") != chosen:
            self._refilter_roasts(lambda: self._roast_proxy.set_group(""))

    def _refilter_roasts(self, change) -> None:  # noqa: ANN001
        """A search, coffee or order change: the list follows, the detail stays."""
        with self._silently():
            change()
        self._highlight_selected()
        self._update_list_chrome()

    def _show_missing_roast_folder(self) -> None:
        with self._silently():
            self._roast_model.set_rows([])
        self._roast_folder_missing = True
        self._list_scanning = False
        self._refresh_coffee_filter()
        self._update_list_chrome()

    def _update_list_chrome(self) -> None:
        """The counts, Clear filters and the empty states, from what the list holds."""
        try:
            total = self._roast_model.rowCount()
            shown = self._roast_proxy.rowCount()
            filtered = self._roast_proxy.is_filtered()
            self.roast_total_label.setText(str(total) if total else "")
            if filtered:
                self.roast_count_label.setText(QApplication.translate(
                    "tilauscope_beancave", "{0} of {1} roasts").format(shown, total))
            else:
                self.roast_count_label.setText(roast_count_text(total))
            self.roast_clear_filters_button.setVisible(filtered)

            text, action = "", ""
            if total == 0 and self._roast_folder_missing:
                title = QApplication.translate("tilauscope_beancave", "Roast folder not found")
                action = 'folder'
            elif total == 0 and not self._list_scanning:
                title = QApplication.translate("tilauscope_beancave", "No roasts yet")
                text = QApplication.translate("tilauscope_beancave",
                                              "Your roasts appear here once the first one is saved.")
            elif total and not shown and self.roast_search.text().strip():
                title = QApplication.translate("tilauscope_beancave", "No roast matches “{0}”").format(
                    self.roast_search.text().strip())
                action = 'search'
            elif total and not shown:
                title = QApplication.translate("tilauscope_beancave", "No roast matches the filters")
                action = 'filters'
            else:
                self.roast_list_stack.setCurrentIndex(0)
                return

            self.roast_empty_title.setText(title)
            self.roast_empty_text.setText(text)
            self.roast_empty_text.setVisible(bool(text))
            if action == 'folder':
                self.roast_empty_button.setText(QApplication.translate("tilauscope_beancave", "Choose folder"))
            elif action == 'search':
                self.roast_empty_button.setText(QApplication.translate("tilauscope_beancave", "Clear search"))
            elif action == 'filters':
                self.roast_empty_button.setText(QApplication.translate("tilauscope_beancave", "Clear filters"))
            self._roast_empty_action = action
            self.roast_empty_button.setVisible(bool(action))
            self.roast_list_stack.setCurrentIndex(1)
        except RuntimeError:
            pass   # the dialog is being torn down

    @pyqtSlot(str)
    def _on_roast_search_edited(self, _text: str) -> None:
        self._search_debounce.start()

    @pyqtSlot()
    def _on_roast_search_settled(self) -> None:
        self._refilter_roasts(lambda: self._roast_proxy.set_query(self.roast_search.text()))

    @pyqtSlot(int)
    def _on_roast_coffee_changed(self, _index: int) -> None:
        group = self.roast_coffee_combo.currentData() or ""
        self._refilter_roasts(lambda: self._roast_proxy.set_group(group))

    @pyqtSlot(int)
    def _on_roast_sort_changed(self, _index: int) -> None:
        mode = self.roast_sort_combo.currentData() or SORT_RECENT
        QSettings().setValue(self._ROAST_SORT_KEY, mode)
        self._refilter_roasts(lambda: self._roast_proxy.set_sort(mode))

    @pyqtSlot()
    def _clear_roast_filters(self) -> None:
        self._search_debounce.stop()
        for widget in (self.roast_search, self.roast_coffee_combo):
            widget.blockSignals(True)
        try:
            self.roast_search.clear()
            self.roast_coffee_combo.setCurrentIndex(0)
        finally:
            for widget in (self.roast_search, self.roast_coffee_combo):
                widget.blockSignals(False)

        def clear() -> None:
            self._roast_proxy.set_query("")
            self._roast_proxy.set_group("")
        self._refilter_roasts(clear)

    @pyqtSlot()
    def _on_roast_empty_action(self) -> None:
        if self._roast_empty_action == 'folder':
            self.select_alog_directory()
        elif self._roast_empty_action in ('search', 'filters'):
            self._clear_roast_filters()

    @pyqtSlot()
    def _focus_roast_list(self) -> None:
        view = self.roast_list_view
        view.setFocus()
        if not view.currentIndex().isValid() and self._roast_proxy.rowCount():
            view.selectionModel().setCurrentIndex(
                self._roast_proxy.index(0, 0), QItemSelectionModel.SelectionFlag.NoUpdate)

    @pyqtSlot()
    def _focus_roast_search(self) -> None:
        self.roast_search.setFocus()
        self.roast_search.selectAll()

    # ── The detail head ──────────────────────────────────────────────────────

    def _row_for(self, fname: str) -> RoastRow | None:
        index = self._roast_model.row_of(fname) if fname else -1
        return self._roast_model.rows()[index] if index >= 0 else None

    def _roast_meta_text(self, row: RoastRow) -> str:
        """The day, time, process, crop and batch of a roast, on one line."""
        parts: list[str] = []
        if row.epoch > 0:
            when = datetime.fromtimestamp(row.epoch)
            day = self._roast_proxy.display_locale().toString(
                QDate(when.year, when.month, when.day), 'dddd d MMMM yyyy')
            parts += [day[:1].upper() + day[1:], when.strftime('%H:%M')]
        if row.process:
            parts.append(row.process)
        if row.crop:
            parts.append(QApplication.translate("tilauscope_beancave", "Crop {0}").format(row.crop))
        if row.batch:
            parts.append(QApplication.translate("tilauscope_beancave", "Batch {0}").format(row.batch))
        return " · ".join(parts)

    def _set_detail_mode(self, mode: str) -> None:
        """Which parts of the head show: 'none', 'single' or 'compare'."""
        single, compare = mode == 'single', mode == 'compare'
        self.roast_detail_meta.setVisible(single)
        self.roast_compare_chips.setVisible(compare)
        self.roast_compare_clear.setVisible(compare)
        self.roast_compare_note.setVisible(compare and bool(self.roast_compare_note.text()))
        for tile in self.roast_tiles[:3]:
            tile.setVisible(single or compare)
        self.roast_tiles[3].setVisible(single)
        if not single:
            self.roast_result_banner.hide()

    def _show_tiles(self, texts: list) -> None:
        for tile, text in zip(self.roast_tiles, texts):
            tile.show_text(text)

    def _show_detail_none(self) -> None:
        self.roast_detail_title.setText("")
        self.roast_detail_title.setToolTip("")
        self._set_detail_mode('none')

    def _show_detail_single(self, fname: str) -> None:
        """Name the roast at once, from the list; its figures follow once it has loaded."""
        row = self._row_for(fname)
        title = row.title if row is not None else Path(fname).stem
        self.roast_detail_title.setText(title)
        self.roast_detail_title.setToolTip(title)
        self.roast_detail_meta.setText(self._roast_meta_text(row) if row is not None else "")
        self._show_tiles(roast_tiles(None))
        self.roast_result_banner.hide()
        self._set_detail_mode('single')

    def _fill_detail_single(self, profile) -> None:  # noqa: ANN001
        """The figures of the roast just loaded, and the banner when its result is missing."""
        # Reached from a load's completion slot: an escape here would close the application.
        try:
            facts = roast_facts(profile) if profile else None
            self._show_tiles(roast_tiles(facts))
            self.roast_result_banner.setVisible(facts is not None and not facts.has_result)
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("the roast's figures could not be shown")

    def _compare_chips_html(self, fnames: list[str]) -> str:
        """Each compared roast, named in its curve's colour."""
        chips = []
        for position, fname in enumerate(fnames):
            row = self._row_for(fname)
            hue = self._MULTI_HUES[position % len(self._MULTI_HUES)]
            name = html.escape(row.title if row is not None else Path(fname).stem)
            when = (datetime.fromtimestamp(row.epoch).strftime('%H:%M')
                    if row is not None and row.epoch > 0 else "")
            chips.append(f'<span style="color:{hue};">●</span>&nbsp;{name}'
                         f'&nbsp;<span style="color:{THEME["SUBTEXT"]};">{when}</span>')
        return "&nbsp;&nbsp;&nbsp; ".join(chips)

    def _show_detail_multi(self, fnames: list[str], selected_count: int) -> None:
        """Name the compared roasts at once; their ranges follow once they have loaded."""
        self.roast_detail_title.setText(
            QApplication.translate("tilauscope_beancave", "{0} roasts compared").format(len(fnames)))
        self.roast_detail_title.setToolTip("")
        self.roast_compare_chips.setText(self._compare_chips_html(fnames))
        self.roast_compare_note.setText(
            QApplication.translate("tilauscope_beancave", "Only the first five selected roasts are drawn.")
            if selected_count > len(fnames) else "")
        self._show_tiles(comparison_tiles(None))
        self._set_detail_mode('compare')

    def _fill_detail_multi(self) -> None:
        """The ranges across the roasts that loaded, named as the curves are drawn."""
        # Reached from a load's completion slot: an escape here would close the application.
        try:
            if not self._multi_curves:
                return
            fnames = [Path(curve['filepath']).name for curve in self._multi_curves]
            self.roast_detail_title.setText(
                QApplication.translate("tilauscope_beancave", "{0} roasts compared").format(len(fnames)))
            self.roast_compare_chips.setText(self._compare_chips_html(fnames))
            facts = [roast_facts(curve['data']) for curve in self._multi_curves if curve.get('data')]
            self._show_tiles(comparison_tiles(facts))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("the comparison figures could not be shown")

    @pyqtSlot()
    def _leave_comparison(self) -> None:
        """Clear: the first roast of the comparison, on its own."""
        if len(self._selected_fnames) > 1 and self.select_roast(self._selected_fnames[0]):
            self.load_roast_data_and_plot()

    @pyqtSlot()
    def _sync_print_label_text(self) -> None:
        """Say so when it is the printer, not the selection, that keeps a label from printing."""
        if getattr(self, "_niimbot_connected", False):
            text = QApplication.translate("tilauscope_beancave", "Print label")
        else:
            text = QApplication.translate("tilauscope_beancave", "Print label — printer not connected")
        if self.print_label_action.text() != text:
            self.print_label_action.setText(text)

    # ── The curve card's choices ─────────────────────────────────────────────

    @staticmethod
    def _parse_custom_range(text: str) -> tuple[float, float]:
        """A saved "start,end" in seconds, or 0–12 min when there is none to read."""
        try:
            start, end = (float(part) for part in text.split(','))
            if 0 <= start < end:
                return start, end
        except ValueError:
            pass
        return 0.0, 720.0

    @pyqtSlot(int)
    def _on_detail_page_changed(self, index: int) -> None:
        self.viewer_pages.setCurrentIndex(index)
        # Full screen expands the curve, and Statistics holds none: left on that
        # page the button opened a curve the card was not showing.
        self.zoom_button.setVisible(index == 0)
        self.curve_bar.setVisible(index == 0)

    @pyqtSlot(int)
    def _on_curve_view_changed(self, index: int) -> None:
        self._curve_view = self._CURVE_VIEWS[index]
        QSettings().setValue(self._CURVE_VIEW_KEY, self._curve_view)
        # A slot: an escape here would close the application.
        try:
            self._apply_curve_view()
            self.canvas.draw_idle()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("the curve view could not be changed")

    @pyqtSlot(int)
    def _on_compare_view_changed(self, index: int) -> None:
        self._multi_view_mode = ('overlay', 'consistency', 'align')[index]
        if self._multi_curves:
            self._plot_multi_curves()

    @pyqtSlot(int)
    def _on_curve_range_activated(self, index: int) -> None:
        mode = self._CURVE_RANGES[index]
        if mode == 'custom' and not self._ask_custom_range():
            # Dismissed: the range in force stays lit.
            self.curve_range_switch.set_current(self._CURVE_RANGES.index(self._curve_range))
            return
        if mode == self._curve_range and mode != 'custom':
            return
        self._curve_range = mode
        QSettings().setValue(self._CURVE_RANGE_KEY, mode)
        try:
            self._apply_time_range()
            self.canvas.draw_idle()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("the curve's time range could not be changed")

    def _ask_custom_range(self) -> bool:
        """Custom…: a start and an end in m:ss, under the switch. False when dismissed."""
        start_s, end_s = self._curve_custom_range
        menu = QMenu(self.curve_range_switch)
        menu.setStyleSheet(menu_qss())
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(10, 8, 10, 8)
        start = QTimeEdit(QTime(0, 0).addSecs(int(start_s)))
        end = QTimeEdit(QTime(0, 0).addSecs(int(end_s)))
        for field in (start, end):
            field.setDisplayFormat("m:ss")
        grid.addWidget(QLabel(QApplication.translate("tilauscope_beancave", "From")), 0, 0)
        grid.addWidget(start, 0, 1)
        grid.addWidget(QLabel(QApplication.translate("tilauscope_beancave", "To")), 1, 0)
        grid.addWidget(end, 1, 1)
        apply_button = QPushButton(QApplication.translate("tilauscope_beancave", "Apply"))
        apply_button.setProperty('variant', 'primary')
        hint = QLabel("")
        hint.setProperty('variant', 'caption')
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['WARNING']};")
        hint.hide()
        applied: list[bool] = []

        def apply() -> None:
            # A range that cannot be read says so here, and the fields stay open:
            # closing on it snapped the switch back with nothing to act on.
            problem = custom_range_error(QTime(0, 0).secsTo(start.time()),
                                         QTime(0, 0).secsTo(end.time()))
            hint.setText(problem)
            hint.setVisible(bool(problem))
            if problem:
                return
            applied.append(True)
            menu.close()

        apply_button.clicked.connect(apply)
        grid.addWidget(apply_button, 2, 0, 1, 2)
        grid.addWidget(hint, 3, 0, 1, 2)
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(panel)
        menu.addAction(holder)
        menu.exec(self.curve_range_switch.mapToGlobal(QPoint(0, self.curve_range_switch.height())))
        if not applied:
            return False
        low = QTime(0, 0).secsTo(start.time())
        high = QTime(0, 0).secsTo(end.time())
        self._curve_custom_range = (float(low), float(high))
        QSettings().setValue(self._CURVE_CUSTOM_KEY, f"{low},{high}")
        return True

    @pyqtSlot(bool)
    def _on_burner_air_toggled(self, checked: bool) -> None:
        self._curve_show_settings = checked
        QSettings().setValue(self._CURVE_SETTINGS_KEY, checked)
        self._sync_burner_air_text()
        self._replot_single()

    def _sync_burner_air_text(self) -> None:
        label = literal_ampersand(
            QApplication.translate("tilauscope_beancave", "Burner & air"))
        self.burner_air_button.setText(f"✓  {label}" if self.burner_air_button.isChecked() else label)



    def load_roast_data_and_plot(self) -> None:
        selected = self.selected_roast_fnames()
        if not selected:
            self.roast_plot_label.setText(QApplication.translate("tilauscope_beancave","Select a roast file to see the curve preview."))
            self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast Information will appear here."))
            self._set_viewer_buttons_enabled(False, multi=False)
            self._show_detail_none()
            return

        self.is_zoomed = False

        if len(selected) == 1:
            # ── MODE MONO — comportement original ────────────────────────────
            self._multi_mode = False
            self._multi_curves.clear()
            self._multi_progress.hide()
            self._set_viewer_buttons_enabled(True, multi=False)
            self._show_detail_single(selected[0])

            # The roast to draw is the SELECTED one, not the current one. Qt
            # tracks the two apart: the current item is the keyboard cursor, and
            # it is None right after the list is rebuilt and stale after a
            # ctrl-click that drops the row it still points at. Reading it here
            # drew another roast than the highlighted one, or raised on None and
            # left the canvas exactly as it was — a blank curve, no log line.
            filepath = Path(self.alog_directory) / selected[0]
            if not filepath.exists():
                _log.error(f"File not found in beancave plot routine: {filepath}")
                return
            self._cancel_alog_thread()
            self._start_alog_load(filepath,
                                  on_ok=self._alog_worker_finished_on_plot_ok,
                                  on_err=self._alog_worker_finished_on_plot_error)
        else:
            # ── MODE MULTI — comparaison ──────────────────────────────────────
            self._multi_mode = True
            self._multi_curves.clear()
            self._set_viewer_buttons_enabled(False, multi=True)
            # Annuler tout chargement en cours (mono ou multi précédent)
            self._cancel_alog_thread()
            # Réinitialiser la queue APRÈS l'annulation
            self._multi_load_queue = []
            self._multi_load_idx = 0

            filepaths = [str(fp) for fp in (Path(self.alog_directory) / fname for fname in selected)
                         if fp.exists()]

            filepaths = filepaths[:5]  # cap à 5 courbes
            if not filepaths:
                return
            self._show_detail_multi([Path(fp).name for fp in filepaths], len(selected))
            self._multi_load_queue = filepaths
            self._multi_progress.setMaximum(len(filepaths))
            self._multi_progress.setValue(0)
            self._multi_progress.show()
            self._load_next_multi_curve()

    # ── Helpers factored out ─────────────────────────────────────────────────

    def _on_multi_alog_thread_done(self) -> None:
        """Null-ifie les refs multi quand le thread Qt est terminé."""
        self._multi_alog_thread = None
        self._multi_alog_worker = None

    def _cancel_alog_thread(self) -> None:
        """Cancel any in-flight load thread (mono or multi).

        The final wait() is unbounded on purpose: this runs on every selection
        change, and returning while the load is still going lets the next one
        start beside it. Threads then pile up reading profiles and connecting
        signals, and Qt deadlocks the next widget construction against them —
        measured at 4 hangs in 10 opens when this wait was bounded.
        """
        # Chemin mono
        if hasattr(self, '_alog_thread') and self._alog_thread is not None:
            try:
                # Disconnect first and unconditionally: a worker that has already
                # emitted finished and whose thread has quit is no longer running,
                # but its queued call is still on its way to a slot that would
                # repaint the load replacing it.
                try:
                    self._alog_worker.finished.disconnect(self._alog_worker_finished_on_plot_ok)
                    self._alog_worker.error.disconnect(self._alog_worker_finished_on_plot_error)
                except (AttributeError, TypeError, RuntimeError):
                    pass
                if self._alog_thread.isRunning():
                    self._alog_thread.requestInterruption()
                    self._alog_thread.quit()
                    if not self._alog_thread.wait(2000):
                        _log.warning("alog load cancellation is still pending")
                        self._alog_thread.wait()
            except (AttributeError, RuntimeError):
                # C++ object already deleted by deleteLater
                pass
            self._alog_thread = None
            self._alog_worker = None
        # Chemin multi
        if hasattr(self, '_multi_alog_thread') and self._multi_alog_thread is not None:
            try:
                # Same as the mono path above: a queued finished from a worker
                # that has already stopped added a phantom roast to the next
                # comparison, after the curve list had been reset.
                try:
                    self._multi_alog_worker.finished.disconnect(self._on_multi_curve_loaded)
                    self._multi_alog_worker.error.disconnect(self._on_multi_curve_error)
                except (AttributeError, TypeError, RuntimeError):
                    pass
                if self._multi_alog_thread.isRunning():
                    self._multi_alog_thread.requestInterruption()
                    self._multi_alog_thread.quit()
                    if not self._multi_alog_thread.wait(2000):
                        _log.warning("multi alog load cancellation is still pending")
                        self._multi_alog_thread.wait()
            except (AttributeError, RuntimeError):
                pass
            self._multi_alog_thread = None
            self._multi_alog_worker = None

    def _start_alog_load(self, filepath: Path, on_ok, on_err,
                         multi: bool = False) -> None:
        """Spin up _AlogLoadWorker for a single file.

        multi=True : chemin comparaison — pas de _on_alog_thread_done ni deleteLater
                     immédiat, le cleanup est géré par _on_multi_curve_loaded.
        multi=False : chemin mono — cleanup complet via _on_alog_thread_done.
        """
        worker = _AlogLoadWorker(parent=self, filepath=filepath, aw=self.aw)
        thread = QThread(self)
        worker.moveToThread(thread)
        # the worker goes with its thread object, never by its own deleteLater (see _launch_worker)
        thread._worker = worker
        thread.started.connect(worker.run)
        worker.finished.connect(on_ok)
        worker.error.connect(on_err)
        if multi:
            # En mode multi : le thread se quitte sur finished/error,
            # puis est détruit proprement ; les refs Python sont gérées
            # par _on_multi_curve_loaded / _on_multi_curve_error.
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            worker.cancelled.connect(thread.quit)
            self._multi_alog_thread = thread
            self._multi_alog_worker = worker
            thread.finished.connect(self._on_multi_alog_thread_done)
            thread.finished.connect(thread.deleteLater)
        else:
            # Chemin mono — comportement original
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            worker.cancelled.connect(thread.quit)
            worker.cancelled.connect(partial(self._alog_load_cancelled, filepath.name))
            thread.finished.connect(self._on_alog_thread_done)
            thread.finished.connect(thread.deleteLater)
            self._alog_thread = thread
            self._alog_worker = worker
            # The roast this load is for. The completion handler cannot ask the
            # list any more: by then the list may have been rebuilt underneath.
            self._loading_fname = filepath.name
        thread.start()

    def _alog_load_cancelled(self, filename: str) -> None:
        """A roast load that was dropped before it produced anything.

        Cancelling is ordinary: clicking down the list replaces one load with the
        next, and the next one paints. What is not ordinary is a cancellation
        with nothing loading behind it — the curve then keeps whatever was on it,
        the operator is told nothing, and the log stays silent. That is exactly
        how a blank viewer with a clean log happens, so it is said out loud here.
        """
        if getattr(self, '_alog_thread', None) is not None:
            _logd.debug(f"roast load of '{filename}' replaced by a newer one")
            return
        _log.warning(
            f"roast load of '{filename}' was cancelled and nothing replaced it — "
            f"the curve is left as it was")
        self.roast_plot_label.setText(QApplication.translate(
            "tilauscope_beancave",
            "Loading was interrupted — select the roast again to see its curve."))

    def _set_viewer_buttons_enabled(self, enabled: bool, multi: bool) -> None:
        """Enable the actions for what is selected: one roast, several, or none."""
        self.refresh_action.setEnabled(True)
        self.zoom_button.setEnabled(enabled or multi)
        # Toggles Consistance / Aligné : visibles uniquement en comparaison multi
        # The view choices follow what is drawn: one roast's curves, or a comparison.
        self.curve_view_switch.setVisible(not multi)
        self.compare_view_switch.setVisible(multi)
        self.burner_air_button.setVisible(not multi)
        # One roast's actions: greyed with none selected, out of the way while comparing.
        mono = enabled and not multi
        for button in (self.load_artisan_button_viewer, self.load_artisan_background_button_viewer,
                       self.export_button):
            button.setVisible(not multi)
            button.setEnabled(mono)
        for action in (self.roast_finished_action, self.print_pdf_label_action, self.planning_action,
                       self.dial_in_action, self.curve_image_action, self.roast_card_action,
                       self.data_action):
            action.setEnabled(mono)
        # The printed label also needs the printer ready (heartbeat answered).
        self.print_label_action.setEnabled(mono and getattr(self, "_niimbot_connected", False))

    def _load_next_multi_curve(self) -> None:
        """Charge séquentiellement la prochaine courbe de la queue multi.
        Le cache est consulté dans le thread UI — thread-safe.
        Si cache hit : on injecte directement les données sans lancer de thread.
        Si cache miss : on lance _AlogLoadWorker."""
        if self._multi_load_idx >= len(self._multi_load_queue):
            self._multi_progress.hide()
            self._plot_multi_curves()
            self._fill_detail_multi()
            return

        fp_str = self._multi_load_queue[self._multi_load_idx]
        fp = Path(fp_str)

        # Cache lookup dans le thread UI — consultation seule, jamais de parsing
        cached_data = self.peek_alog_cache(fp)
        if cached_data is not None:
            # Cache hit — calculer les deltas directement ici (thread UI, safe)
            _logd.debug(f"Multi cache hit: {fp.name}")
            try:
                deltabt = self.evaldeltas(cached_data, "temp2")
                deltaet = self.evaldeltas(cached_data, "temp1")
            except Exception as e:
                _logd.warning(f"evaldeltas cache hit failed: {e}")
                deltabt = None
                deltaet = None
            self._on_multi_curve_loaded(cached_data, deltaet, deltabt)
            return

        # Cache miss — lancer le worker
        _logd.debug(f"Multi cache miss, loading: {fp.name}")
        self._start_alog_load(fp,
                              on_ok=self._on_multi_curve_loaded,
                              on_err=self._on_multi_curve_error,
                              multi=True)

    @pyqtSlot(object, object, object)
    def _on_multi_curve_loaded(self, profiledata, deltaet, deltabt) -> None:
        """Slot appelé quand une courbe multi est chargée (thread ou cache hit)."""
        if self._multi_load_idx >= len(self._multi_load_queue):
            return
        fp = self._multi_load_queue[self._multi_load_idx]
        _logd.debug(f"Multi curve loaded [{self._multi_load_idx+1}/{len(self._multi_load_queue)}]: {Path(fp).name}")
        self._multi_curves.append({
            'filepath': fp,
            'data': profiledata,
            'deltabt': deltabt,
            'deltaet': deltaet,
            'title': profiledata.get('title', Path(fp).stem) if profiledata else Path(fp).stem,
        })
        self._multi_load_idx += 1
        self._multi_progress.setValue(self._multi_load_idx)
        # singleShot(0) laisse le thread courant terminer son cleanup si applicable
        QTimer.singleShot(0, self._load_next_multi_curve)

    @pyqtSlot(str)
    def _on_multi_curve_error(self, err: str) -> None:
        _log.warning(f"Multi load error (skipped): {err}")
        self._multi_load_idx += 1
        self._multi_progress.setValue(self._multi_load_idx)
        QTimer.singleShot(0, self._load_next_multi_curve)

    @pyqtSlot()
    def on_roast_finished_clicked(self) -> None:
        # In comparison mode `lastprofiledata` holds a roast that is not on screen.
        if getattr(self, "_multi_mode", False):
            return
        selected = self.selected_roast_fnames()
        if not selected:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Error"),
                                QApplication.translate("tilauscope_beancave","Please, select a roast session first."), QMessageBox.Icon.Warning)
            return

         # 1. Use the data already in memory
        data = self.lastprofiledata
        if not data:
            return

        # 2. Load the roast in Artisan only if it is not already the open profile.
        ##   TILAU ## reloading from disk would discard any unsaved edits already
        ##   sitting in qmc (e.g. ground/whole colour) — the dialog must work from
        ##   the live qmc when the profile is already open.
        try:
            # The selected roast, not the current one: the current item is the
            # keyboard cursor and is None right after the list is rebuilt, which
            # made the button do nothing at all (the raise below is swallowed).
            filepath = Path(self.alog_directory) / selected[0]
            filename = filepath.name
            cur_file = getattr(self.aw, 'curFile', None)
            already_open = bool(cur_file) and Path(cur_file).resolve() == filepath.resolve()
            if not already_open:
                self.aw.loadFile(str(filepath))
        except Exception as e:
            _logd.error(f"on_roast_finished_clicked: failed to load: {e}")
            return

        # 3. Identify the bean using cached UUID index or parsing
        target_bean = None
        target_uuid = self._alog_file_uuid.get(filename) or self.bean_uuid_from_profile(data)

        if target_uuid:
            target_bean = self.uuidmap.get(target_uuid)

        if target_bean is None:
            selected_rows = self.datatable.selectionModel().selectedRows()
            if selected_rows:
                target_bean = self.cave.green_beans[selected_rows[0].row()]

        if target_bean is None:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Missing Bean"),
                QApplication.translate("tilauscope_beancave", "This roast is not linked to any bean in your cave. Please select the bean in the 'Green Beans' tab first."),
                QMessageBox.Icon.Warning)
            return

        # 4. Get Green Weight
        green_weight = 0.0
        try:
            # weight: [in, out, unit]
            w_info = data.get("weight", [0.0, 0.0, "g"])
            green_weight = float(w_info[0])
        except (ValueError, TypeError, IndexError):
            pass

        from tilauscope.roast_properties import RoastResultDialog
        dlg = RoastResultDialog(target_bean, self.aw, green_weight=green_weight)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # RoastResultDialog has saved the changed profile. Drop it from the read cache, reload the viewer
        # (curve + Advanced Stats) and re-index so the roast list and the
        # reference corpus follow the edit.
        self._alog_cache.pop(str(filepath), None)
        self.load_roast_data_and_plot()
        self.trigger_cache_refresh()

    @pyqtSlot()
    # Export the selected roast as a high-resolution portrait PNG
    def on_export_roast_card(self) -> None:
        # In comparison mode `lastprofiledata` holds a roast that is not on screen.
        if getattr(self, "_multi_mode", False):
            return
        if not self.selected_roast_fnames():
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Please, select a roast session first."),
                QMessageBox.Icon.Warning)
            return
        data = getattr(self, 'lastprofiledata', None)
        if not data:
            return

        # the live green bean record behind this roast, when its UUID resolves
        bean = self.bean_from_profile(data)

        # RoR is not stored in the .alog — recompute it the way the viewer does
        deltabt = None
        try:
            deltabt = self.evaldeltas(data, "temp2")
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"roast card: RoR unavailable: {e}")

        title = str(data.get('title') or 'roast')
        safe_name = _safe_filename(title, "roast")
        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not downloads_dir:
            downloads_dir = str(Path.home() / "Downloads")
        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave", "Save Roast Card"),
            str(Path(downloads_dir) / f"{safe_name}.png"),
            QApplication.translate("tilauscope_beancave", "PNG Images (*.png)"))
        if not file_path:
            return

        try:
            from tilauscope.beancave_roast_card import RoastSocialCard
            if not file_path.lower().endswith(".png"):
                file_path += ".png"
            ok = RoastSocialCard().save_png(
                data, file_path, bean=bean, deltabt=deltabt, ror_unit=self.aw.qmc.mode)
        except Exception as e:
            _logd.error(f"Roast card export failed: {e}", exc_info=True)
            ok = False

        if ok:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Success"),
                QApplication.translate("tilauscope_beancave", "Roast card saved to") + f" {file_path}")
            self.try_to_open_file(file_path)
        else:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "The roast card could not be generated."),
                QMessageBox.Icon.Warning)

    def show_data_reader_view(self) -> None:
        """Open the data reader on the roast the canvas shows.

        One reader at a time. It is not modal, so it follows the roast list:
        each roast that loads while it is open is shown in it.
        """
        if not self.selected_roast_fnames():
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Please, select a roast session first."),
                QMessageBox.Icon.Warning)
            return
        # Not `lastprofiledata`: the Roast Plan tab points it at its own reference roast.
        data = self.displayed_profile()
        if not data:
            return
        title = self._displayed_roast_label()
        if self._data_reader is None:
            from tilauscope.roast_properties import RoastDataReaderDialog
            self._data_reader = RoastDataReaderDialog(dict(data), title=title, parent=self)
        else:
            self._data_reader.set_profile(dict(data), title=title)
        self._data_reader.show()
        self._data_reader.raise_()

    def _refresh_data_reader(self, profiledata) -> None:
        """Show the roast that just loaded in the data reader, when it is open."""
        reader = self._data_reader
        if reader is None or not profiledata:
            return
        try:
            if reader.isVisible():
                reader.set_profile(dict(profiledata), title=self._displayed_roast_label())
        except RuntimeError:
            self._data_reader = None   # C++ side already collected
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            # Called from a Qt slot: an escape would reach the excepthook and close the app.
            _logd.warning(f"data reader refresh failed: {e}")

    def _displayed_roast_label(self) -> str:
        """List label of the roast on the canvas, or "" when it is not in the list."""
        return self.roast_label(getattr(self, '_displayed_fname', ''))

    @pyqtSlot(str)
    def _alog_worker_finished_on_plot_error(self, filename:str):
        _logd.warning(f"Unable to read or decode alog file '{filename}'")
        self.roast_plot_label.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file"))
        self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file."))
        self._fill_detail_single(None)

    @pyqtSlot(object, object, object)
    def _alog_worker_finished_on_plot_ok(self, profiledata, deltaet, deltabt):
        _logd.debug("finished worker")
        self.lastprofiledata = profiledata
        # What is on the canvas is what this load carried. Asking the list here
        # answered "" whenever a background refresh had rebuilt it in the
        # meantime, and a blank booking makes the next refresh believe the
        # canvas shows another roast than it does.
        self._displayed_fname = getattr(self, '_loading_fname', '')
        label = self.roast_label(self._displayed_fname)
        self.display_roast_info(self.lastprofiledata)
        self.plot_bt_curve_preview(self.lastprofiledata, deltaet, deltabt)  # type: ignore
        self._update_roast_plan_values()
        # ── Update header label with roast display name ──────────────────────
        # The detail head names it: the line above the curve is for messages only.
        self.roast_plot_label.setText("")
        self._fill_detail_single(profiledata)
        self._refresh_data_reader(profiledata)
        # ── Timeline hand-off: profile now fully loaded → open the Brew Advisor ──
        pend = getattr(self, "_pending_brew_after_load", None)
        if pend:
            self._pending_brew_after_load = None
            if label and self._displayed_fname == pend:
                self.show_barista_expert_view(self.lastprofiledata)

    @pyqtSlot()
    def _on_alog_thread_done(self) -> None:
        """Clear refs after alog thread finishes normally so _cancel_threads
        and the next file selection won't see a stale thread handle."""
        self._alog_thread = None
        self._alog_worker = None

    def displayed_profile(self) -> ProfileData | None:
        """The profile the canvas is actually showing, read back from its file.

        ``lastprofiledata`` is shared with the Roast Plan tab, which points it at
        its own reference roast. Anything that edits or overwrites the drawn
        roast must resolve it from the file on the canvas instead of trusting
        that handle, or it writes one roast into another one's file.
        """
        fname = getattr(self, '_displayed_fname', '')
        if not fname:
            return None
        try:
            return self.get_alog_data(Path(self.alog_directory) / fname)
        except Exception as e:
            _logd.warning(f"displayed_profile: could not read '{fname}': {e}")
            return None

    def selected_roast_path(self) -> Path | None:
        """Path of the roast selected in the list, or None.

        The guard and the action have to read the same thing. Testing
        ``selectedItems()`` and then acting on ``currentItem()`` answered two
        different roasts as soon as a ctrl-click dropped the current row, or the
        list was rebuilt underneath — so "Load in Artisan", the background curve
        and both labels could be produced for a roast the operator had not
        picked. The placeholder row carries no filename and yields None.
        """
        selected = self.selected_roast_fnames()
        return Path(self.alog_directory) / selected[0] if selected else None

    def displayed_profile_path(self) -> Path | None:
        """Path of the roast on the canvas, or None when nothing is displayed."""
        fname = getattr(self, '_displayed_fname', '')
        return Path(self.alog_directory) / fname if fname else None

    def evaldeltas(self, data: dict, deltaname:str):
        """The recomputed RoR series for one channel of a loaded profile.

        Smoothing the whole roast is the heaviest thing on this path and it runs
        on the GUI thread, so the result is memoised: selecting a roast, editing
        a milestone and drawing the stats all asked for the same series over and
        over, once per repaint. The key carries every setting that changes the
        outcome, so a unit or smoothing change recomputes rather than serving a
        stale curve.
        """
        qmc = self.aw.qmc
        ds = ror_span_samples(qmc, data, deltaname)
        cache_key = (deltaname, qmc.mode, qmc.curvefilter,
                     bool(qmc.interpolateDropsflag), bool(qmc.optimalSmoothing), ds)
        for cached_data, key, cached_deltas in self._deltas_cache:
            if cached_data is data and key == cache_key:
                return cached_deltas

        deltas = recompute_profile_deltas(qmc, data, deltaname, ds)
        self._deltas_cache.append((data, cache_key, deltas))
        del self._deltas_cache[:-5]
        return deltas

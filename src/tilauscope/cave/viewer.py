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

import numpy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # pylint: disable=unused-import
from functools import partial
import ast  # Import de la bibliothèque ast
import re # For sorting alog files
from datetime import datetime
from pathlib import Path

#import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas


from artisanlib.util import fill_gaps, convertTemp, cast, smooth_list  # smooth_list moved from tgraphcanvas to util

from artisanlib.atypes import ProfileData

from PyQt6.QtCore import (QItemSelectionModel, QStandardPaths, Qt, pyqtSlot, QSettings, QThread, QTimer, QByteArray, QSize,
                          QT_TRANSLATE_NOOP) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QPixmap, QCursor, QPainter) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,  # @UnusedImport @Reimport  @UnresolvedImport
                                QPushButton, QWidget, QTabWidget, # @UnusedImport @Reimport  @UnresolvedImport
                                QAbstractItemView,
                                QFrame, QListWidgetItem,
                                QMessageBox, QDialog, QListWidget, QSplitter, QSizePolicy) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtSvg import QSvgRenderer  # icônes SVG inline pour ZoomToggleButton

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import (THEME, standardization_map, RoastingPhase, TilauProgressRow,
                                         marked, normalize_timeindex)
from tilauscope.roast_timeline import RoastReadyDialog
from tilauscope.cave.common import (
    _log, _logd, _PLOT_PALETTE, _SVG_CONSISTENCY, _SVG_ALIGN, _safe_filename, _svg_bytes_to_icon)
from tilauscope.cave.widgets import (
    ZoomToggleButton, CanvasContainer, HoverTooltip, NiimbotStatusOverlay)
from tilauscope.cave.workers import (
    _AlogLoadWorker, _AlogListWorker)


class ViewerMixin:
    """The Roast viewer tab: the roast list, and loading a roast off the GUI thread.

    A plain mixin, deliberately not a QDialog subclass. Qt registers the slots a
    class declares in that class's own metaobject, and a dialog built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice would be unconnectable.
    """


    def setup_roast_viewer_tab_ui(self) -> None:
        self.roast_viewer_layout = QVBoxLayout()
        self.action_bar_layout = QHBoxLayout()
        self.action_bar_layout.setSpacing(5)

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

        def _vsep() -> QFrame:
            """Séparateur vertical entre groupes."""
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedHeight(20)
            sep.setStyleSheet(f"color:{THEME['BORDER']};max-width:1px;")
            return sep

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
        _SS_GREEN2 = f"""
            QPushButton {{
                background-color : rgba(166,227,161,25);
                color            : {THEME['SUCCESS']};
                border           : 1px solid rgba(166,227,161,80);
                border-radius    : {_R2};
                padding          : 5px 12px;
                font-size        : {_FS2};
                font-weight      : bold;
            }}
            QPushButton:hover {{
                background-color : rgba(166,227,161,55);
            }}
            QPushButton:disabled {{
                color            : {THEME['SUBTEXT']};
                border-color     : {THEME['BORDER']};
                background-color : {THEME['SURFACE']};
            }}
        """

        # ── Groupe 1 — Workflow Artisan ───────────────────────────────────────
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

        self.roast_finished_button = _vbtn(
            "M7 2c0 2-3 3-3 5.5a3 3 0 0 0 6 0C10 5 7 4 7 2zM5 11.5h4M7 9v3",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Roast finished!"), stroke=THEME["SUCCESS"], style_extra=_SS_GREEN2
        )
        self.roast_finished_button.clicked.connect(self.on_roast_finished_clicked)
        self.roast_finished_button.setToolTip(QApplication.translate("tilauscope_beancave","Load the roast in Artisan and record results."))
        self.roast_finished_button.setEnabled(False)

        # ── Groupe 2 — Export & Print ─────────────────────────────────────────
        self.print_pdf_label_button = _vbtn(
            "M3 2h6l3 3v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM9 2v3h3M5 7h4M5 9.5h3",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "PDF")
        )
        self.print_pdf_label_button.clicked.connect(self.generate_and_print_pdf_label)
        self.print_pdf_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate and print the label to PDF for the selected roast."))
        self.print_pdf_label_button.setEnabled(False)

        self.print_label_button = _vbtn(
            "M2 4h10v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4zM5 4V2h4v2M5 9h4",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "B21S")
        )
        self.print_label_button.clicked.connect(self.generate_and_print_label)
        self.print_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate and print the label for the selected roast (requires Niimbot B21S)."))
        self.print_label_button.setEnabled(False)  # activé uniquement par niimbot_connected

        self.btn_snapshot = _vbtn(
            "M1 4h12v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4zM1 6h12M5 9.5h4",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Snapshot")
        )
        self.btn_snapshot.setToolTip(QApplication.translate("tilauscope_beancave","Take a PNG snapshot of the current curve."))
        self.btn_snapshot.setEnabled(False)

        # Shareable roast card — 1200x630 JPEG for social posts.
        # Distinct from Snapshot: that one dumps the raw curve, this one composes
        # the bean identity, the roast level and the curve into one image.
        self.btn_roast_card = _vbtn(
            "M1 3.5h12v9H1zM4 7a1 1 0 1 0 0-.01M1.6 11.4L5 8.4l2.4 2.2L10 8l3 2.8",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Card"))
        self.btn_roast_card.setToolTip(QApplication.translate("tilauscope_beancave","Export this roast as a shareable landscape image (JPEG), sized for social networks: green bean, roast level, key figures and the curve."))
        self.btn_roast_card.clicked.connect(self.on_export_roast_card)
        self.btn_roast_card.setEnabled(False)

        # ── Groupe 3 — Analyse & Outils ───────────────────────────────────────
        self.btn_roast_ready = _vbtn(
            "M2 2h4v4H2zM8 2h4v4H8zM2 8h4v4H2zM8 10h4M10 8v4",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Planning")
        )
        self.btn_roast_ready.setToolTip(QApplication.translate("tilauscope_beancave","Open the roast planning view to get roasting time repartition based on the selected roast profile."))
        self.btn_roast_ready.clicked.connect(self.show_roast_ready_view)
        self.btn_roast_ready.setEnabled(False)

        self.btn_dial_in = _vbtn(
            "M7 2a5 5 0 1 0 0 10A5 5 0 0 0 7 2zM7 4v3.5l2 1.2",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Dial-in")
        )
        self.btn_dial_in.setToolTip(QApplication.translate("tilauscope_beancave","Show espresso/filter extraction parameters based on roast color."))
        self.btn_dial_in.clicked.connect(self.show_barista_expert_view)
        self.btn_dial_in.setEnabled(False)

        self.btn_data_reader = _vbtn(
            "M2 2h10v12H2zM4 5h6M4 8h6M4 11h4",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Data")
        )
        self.btn_data_reader.setToolTip(QApplication.translate("tilauscope_beancave","Open a readable, navigable view of the recorded roast data (milestones, events, columns)."))
        self.btn_data_reader.clicked.connect(self.show_data_reader_view)
        self.btn_data_reader.setEnabled(False)

        self.refresh_button = _vbtn(
            "M2 7a5 5 0 1 0 1.2-3.2M2 3v4h4",
            QT_TRANSLATE_NOOP("tilauscope_beancave", "Refresh")
        )
        self.refresh_button.clicked.connect(self.list_alog_files)
        self.refresh_button.setToolTip(QApplication.translate("tilauscope_beancave","Refresh the roast list."))
        self.refresh_button.setEnabled(True)

        # ── Assemblage avec séparateurs de groupes ────────────────────────────
        for _w in (
            self.load_artisan_button_viewer,
            self.load_artisan_background_button_viewer,
            self.roast_finished_button,
            _vsep(),
            self.print_pdf_label_button,
            self.print_label_button,
            self.btn_snapshot,
            self.btn_roast_card,
            _vsep(),
            self.btn_roast_ready,
            self.btn_dial_in,
            self.btn_data_reader,
            self.refresh_button,
        ):
            self.action_bar_layout.addWidget(_w)

        self.action_bar_layout.addStretch(1)

        # Statut imprimante Niimbot — inline à droite de la barre de boutons.
        # Toujours visible, pas de z-order ni d'overlay flottant.
        self.niimbot_overlay = NiimbotStatusOverlay(self)
        self.action_bar_layout.addWidget(self.niimbot_overlay)

        self.roast_viewer_layout.addLayout(self.action_bar_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal) # type: ignore

        # LEFT SIDE: File list
        list_widget_container = QWidget()
        list_widget_layout = QVBoxLayout()
        self.roast_list_widget = QListWidget()
        self.roast_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Debounce : itemSelectionChanged se déclenche N fois pendant Shift+click
        # On reporte le traitement à la fin de la rafale via QTimer
        # itemSelectionChanged se déclenche N fois pendant Shift/Ctrl+click.
        # Un timer single-shot repart à zéro à chaque appel → un seul dispatch
        # 80ms après le dernier changement, quelle que soit la séquence d'events.
        self._selection_debounce = QTimer(self)
        self._selection_debounce.setSingleShot(True)
        self._selection_debounce.setInterval(80)
        self._selection_debounce.timeout.connect(self.load_roast_data_and_plot)
        self.roast_list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.roast_list_widget.installEventFilter(self)
        list_widget_layout.addWidget(QLabel(QApplication.translate("tilauscope_beancave","Roast Files (.alog)")))
        list_widget_layout.addWidget(self.roast_list_widget)
        self._multi_progress = TilauProgressRow()
        self._multi_progress.hide()
        list_widget_layout.addWidget(self._multi_progress)
        list_widget_container.setLayout(list_widget_layout)

        # RIGHT SIDE: Plot, Info & Tabs
        plot_info_container = QWidget()
        plot_info_layout = QVBoxLayout()

        # sub tabs
        self.viewer_tabs = QTabWidget()

        # --- Curve Tab ---
        self.curve_tab = QWidget()
        self.curve_layout = QVBoxLayout(self.curve_tab)

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
        self.zoom_button = ZoomToggleButton()  # parent adopté par CanvasContainer
        self.zoom_button.toggled.connect(self.toggle_canvas_zoom)

        # ── Toggles vue multi : Consistance / Aligné (icônes, visibles en multi) ─
        # Mutuellement exclusifs ; aucun coché = Overlay.
        self._multi_view_mode = 'overlay'
        _mode_btn_ss = f"""
            QPushButton {{
                background-color : {tint('BG', 160)};
                border           : 1px solid rgba(255, 255, 255, 45);
                border-radius    : 8px;
            }}
            QPushButton:hover  {{
                background-color : rgba(60, 60, 90, 200);
                border           : 1px solid rgba(255, 255, 255, 90);
            }}
            QPushButton:checked {{
                background-color : rgba(89, 150, 246, 55);
                border           : 1px solid rgba(89, 150, 246, 180);
            }}
        """

        def _make_mode_btn(svg: bytes, tip: str, slot) -> QPushButton:
            b = QPushButton()
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFixedSize(32, 32)
            b.setIcon(_svg_bytes_to_icon(svg, 16))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(QApplication.translate("tilauscope_beancave", tip))
            b.setStyleSheet(_mode_btn_ss)
            b.setVisible(False)
            b.toggled.connect(slot)
            return b

        self.consistency_button = _make_mode_btn(
            _SVG_CONSISTENCY,
            QT_TRANSLATE_NOOP("tilauscope_beancave",
            "<b>Consistency view</b><br>"
            "The reference roast as a solid line, with a shaded "
            "<b>min–max band</b> of all the selected roasts (bean temp &amp; RoR).<br>"
            "A <span style='color:#A6E3A1'>tight band</span> means your roasts are "
            "repeatable; a <span style='color:#F38BA8'>wide band</span> shows where "
            "they drift apart."),
            self._on_consistency_toggled)
        self.align_button = _make_mode_btn(
            _SVG_ALIGN,
            QT_TRANSLATE_NOOP("tilauscope_beancave",
            "<b>Aligned view (time-warp)</b><br>"
            "Stretches each roast in time so its milestones (CHARGE, TP, DRY END, "
            "FC start, DROP) line up with the reference.<br>"
            "Lets you compare the <b>shape of the bean-temperature rise within each "
            "phase</b>, regardless of how long that phase actually lasted.<br>"
            "<i>BT only — RoR is hidden because warping time distorts its scale.</i>"),
            self._on_align_toggled)

        # ── Conteneur stable : canvas + overlays (zoom + consistance + aligné) ─
        self.canvas_container = CanvasContainer(
            self.canvas, self.zoom_button,
            mode_btns=[self.consistency_button, self.align_button])

        self.btn_snapshot.clicked.connect(partial(self.take_snapshot, self.fig))

        # Save-marker overlay button (ephemeral — visible only after a marker edit)
        self.canvas_container._save_btn.clicked.connect(self._save_timeindex_to_alog)
        # Route canvas right-click / two-finger-tap through eventFilter
        self.canvas.installEventFilter(self)

        self.roast_plot_label = QLabel(
            QApplication.translate("tilauscope_beancave", "Select a roast to display the graphs.")
        )
        self.curve_layout.addWidget(self.roast_plot_label)
        self.curve_layout.addWidget(self.canvas_container, 1)  # conteneur = unité de transfert
        self.viewer_tabs.addTab(self.curve_tab, QApplication.translate("tilauscope_beancave","Roasting Curve"))

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
        self.viewer_tabs.addTab(self.stats_tab, QApplication.translate("tilauscope_beancave","Advanced Stats"))

        # plot tab
        plot_info_layout.addWidget(self.viewer_tabs)
        plot_info_container.setLayout(plot_info_layout)

        splitter.addWidget(list_widget_container)
        splitter.addWidget(plot_info_container)
        splitter.setSizes([300, 900]) # Initial split

        self.roast_viewer_layout.addWidget(splitter, 1)

        self.roast_viewer_tab.setLayout(self.roast_viewer_layout)

        QTimer.singleShot(0, self.list_alog_files)

        self.print_label_button.setEnabled(False)

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
            self.zoom_dialog.setWindowTitle(
                QApplication.translate(
                    "tilauscope_beancave",
                    "Curve Full Screen - Press ESC to exit"
                )
            )
            zoom_layout = QVBoxLayout(self.zoom_dialog)
            zoom_layout.setContentsMargins(0, 0, 0, 0)
            zoom_layout.addWidget(self.canvas_container)   # conteneur, pas le canvas nu
            self.zoom_dialog.showMaximized()
            self.zoom_dialog.finished.connect(self.restore_canvas_position)
        else:
            if hasattr(self, "zoom_dialog") and self.zoom_dialog:
                # Déconnecter avant close() pour éviter le double-appel via finished
                self.zoom_dialog.finished.disconnect(self.restore_canvas_position)
                self.zoom_dialog.close()
                self.restore_canvas_position()
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
        # Resynchroniser l'icône si le dialog a été fermé par ESC / bouton OS
        if self.zoom_button.isChecked():
            self.zoom_button.setChecked(False)  # déclenche _sync_icon via toggled
        self._reconnect_hover()
        self.is_zoomed = False

    def show_roast_ready_view(self):
        # Utilise la liste des fichiers .alog déjà chargés par list_alog_files()
        if not self.roast_list_widget.count() > 0:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Error"), QApplication.translate("tilauscope_beancave","No file found."), QMessageBox.Icon.Warning)
            return
        self._pending_brew_filepath = None
        dlg = RoastReadyDialog(str(self.alog_directory), self._metadata_cache.records, None, aw=self.aw)
        dlg.brew_requested.connect(self._on_timeline_brew_requested)
        dlg.exec()
        # The timeline closes itself right after asking to brew; open the advisor
        # once exec() returns so we never stack a modal over the (stays-on-top) timeline.
        fp, self._pending_brew_filepath = self._pending_brew_filepath, None
        if fp:
            self.open_brew_advisor_for(fp)

    @pyqtSlot(str)
    def _on_timeline_brew_requested(self, filepath: str) -> None:
        self._pending_brew_filepath = filepath

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
        cur = self.roast_list_widget.currentItem()
        cur_fn = (cur.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname") if cur else None
        if cur_fn == fp.name and getattr(self, 'lastprofiledata', None):
            self.show_barista_expert_view(self.lastprofiledata)
            return
        idx = self._find_item_by_metadata(self.roast_list_widget, "raw_fname", fp.name)
        if isinstance(idx, int) and idx >= 0:
            self.roast_list_widget.blockSignals(True)
            self.roast_list_widget.setCurrentRow(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.roast_list_widget.blockSignals(False)
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

            # Si le fichier est déjà en cache et n'a pas été modifié
            if str(path) in self._alog_cache:
                cached_mtime, cached_data = self._alog_cache[str(path)]
                if current_mtime == cached_mtime:
                    return cached_data

            # Lecture et parsing — format natif Artisan : repr(dict) écrit en UTF-8
            # (cf. artisanlib.util.serialize/deserialize). NE PAS décoder en
            # unicode_escape : les octets UTF-8 des accents seraient mal interprétés
            # (mojibake « café » → « cafÃ© »). literal_eval gère les échappements.
            decoded_content = path.read_text(encoding='utf-8')
            data = cast('ProfileData', ast.literal_eval(decoded_content))

            # Mise en cache — LRU cap 5 : supprimer l'entrée la plus ancienne si nécessaire
            if str(path) not in self._alog_cache and len(self._alog_cache) >= 5:
                oldest_key = next(iter(self._alog_cache))
                del self._alog_cache[oldest_key]
            self._alog_cache[str(path)] = (current_mtime, data)
            return data

        except Exception as e:
            _log.error(f"could not read/parse {path.name}: {e}", exc_info=True)
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
            return
        directory = Path(raw_dir)
        if not directory.exists() or not directory.is_dir():
            self.roast_plot_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "The specified ALog directory does not exist or is not a directory."))
            return

        # Capture the current selection + scroll BEFORE clearing so a
        # background refresh can restore the user's position (clear() wipes both,
        # so reading currentItem() after the rebuild would always return None → row 0).
        # Guarded: keeps a good snapshot rather than overwriting it with an empty one
        # (the auto-refresh already snapshotted at trigger_cache_refresh time).
        self._snapshot_list_selection()

        # Clear immediately so the UI doesn't show stale data during the scan.
        # Clearing emits a selection change of its own, and the pending one it
        # arms would fire on an empty list — painting "select a roast" over a
        # rebuild the operator never asked for.
        self.roast_list_widget.clear()
        self._selection_debounce.stop()

        # One scan at a time: a second one would leave the first running.
        self._stop_list_scan()

        # Offload glob + regex formatting to a background thread
        self._list_thread, self._list_worker = self._launch_worker(
            _AlogListWorker(directory, self._metadata_cache.records),
            on_ok=self._on_alog_list_ready,
            on_err=lambda e: _log.error(f"roast folder scan failed: {e}"),
            on_done=self._on_list_thread_done,
        )

    @pyqtSlot()
    def _on_list_thread_done(self) -> None:
        self._list_thread = None
        self._list_worker = None

    @pyqtSlot(list)
    def _on_alog_list_ready(self, items: list) -> None:
        """Called on the main thread when the background file scan is done."""
        # Drop a result from a scan that has since been replaced. Disconnecting
        # the worker cannot do this on its own: by the time a scan is abandoned
        # its result may already be queued, and a queued emission is delivered
        # whatever happens to the connection afterwards.
        sender = self.sender()
        if sender is not None and sender is not getattr(self, '_list_worker', None):
            # Dropping a replaced scan is routine — two run on the way in, and
            # the first is meant to lose. Dropping one with an empty list and no
            # scan behind it is not: nothing will paint, and the operator is
            # left with a blank list the log never mentions. Say that one out loud.
            if (self.roast_list_widget.count() == 0
                    and getattr(self, '_list_worker', None) is None):
                _log.warning(
                    "a roast scan finished after being replaced, with nothing "
                    "running behind it — the roast list is left empty")
            else:
                _logd.debug("dropping the result of a roast scan that was replaced")
            return

        # This handler owns the painted list, so it starts from empty. Clearing
        # only where the scan is launched leaves two results appending to each
        # other, and every roast appears twice.
        self.roast_list_widget.clear()
        self._selection_debounce.stop()

        if not items:
            _log.warning(f"roast folder scan returned nothing: {self.alog_directory}")
            self.roast_list_widget.addItem(
                QApplication.translate("tilauscope_beancave",
                    "No alog files found in the directory."))
            return
        _log.info(f"roast list painted: {len(items)} roasts")

        # Batch-populate using blockSignals so itemSelectionChanged doesn't
        # fire on every addItem, while keeping the widget's visual state intact.
        self.roast_list_widget.blockSignals(True)
        try:
            for raw_fname, display_name, roast_epoch in items:
                item = QListWidgetItem(display_name)
                metadata ={"raw_fname": raw_fname, "roast_epoch": roast_epoch}
                item.setData(Qt.ItemDataRole.UserRole, metadata)
                self.roast_list_widget.addItem(item)
        finally:
            self.roast_list_widget.blockSignals(False)

        if self.roast_list_widget.count() > 0:
            if not self.hasfinished:
                self.roast_list_widget.setCurrentRow(
                    self._row_to_select_on_open(),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.hasfinished = True
                self.btn_snapshot.setEnabled(True)
                self.btn_roast_card.setEnabled(True)
                self.btn_dial_in.setEnabled(True)
                self.btn_roast_ready.setEnabled(True)
                self.btn_data_reader.setEnabled(True)
                self.print_pdf_label_button.setEnabled(True)
                self.load_artisan_background_button_viewer.setEnabled(True)
                self.load_artisan_button_viewer.setEnabled(True)
                self.roast_finished_button.setEnabled(True)
                self.load_roast_data_and_plot()
                self._populate_plan_roast_combo()
            else:
                # Background refresh — restore the selection captured before clear()
                # (currentItem() is None here because the widget was cleared).
                target_row = -1
                cur_fname = getattr(self, "_pending_restore_fname", "")
                if cur_fname:
                    idx = self._find_item_by_metadata(self.roast_list_widget, "raw_fname", cur_fname)
                    if idx is not None and idx >= 0:
                        target_row = idx
                # No captured selection (e.g. a concurrent startup refresh): fall back
                # to the profile currently loaded in Artisan, never blindly to row 0 —
                # otherwise this path would clobber the initial curFile selection.
                if target_row < 0:
                    cur_file = Path(self.aw.curFile).name if self.aw.curFile else ""
                    if cur_file:
                        idx = self._find_item_by_metadata(self.roast_list_widget, "raw_fname", cur_file)
                        if idx is not None and idx >= 0:
                            target_row = idx
                if target_row < 0:
                    # Same order as a fresh open rather than row 0, which is
                    # alphabetical and means nothing to the operator.
                    target_row = self._row_to_select_on_open()
                self.roast_list_widget.blockSignals(True)
                self.roast_list_widget.setCurrentRow(target_row, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.roast_list_widget.blockSignals(False)
                # Reselecting in silence is deliberate — a background refresh must
                # not reload a curve that is already right. But silence also means
                # nothing repaints, so the one case that must not be left alone is
                # a curve showing something else, or nothing at all.
                restored = self.roast_list_widget.currentItem()
                restored_fname = ((restored.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname", "")
                                  if restored else "")
                if restored_fname and restored_fname != self._displayed_fname:
                    self.load_roast_data_and_plot()
                # Restore the scroll position so the list doesn't jump under the cursor.
                self.roast_list_widget.verticalScrollBar().setValue(
                    getattr(self, "_pending_restore_scroll", 0))

    @pyqtSlot(int)
    def _on_roaster_model_changed(self, index: int):
        self.current_roaster_model = self.roaster_combo.currentText()
        settings = QSettings()
        settings.setValue("RoastPlan/RoasterModel", self.current_roaster_model)
        _logd.debug(f"Modèle de torréfacteur mis à jour : {self.current_roaster_model}")

    @pyqtSlot()
    def _on_selection_changed(self) -> None:
        """Redémarre le timer à chaque changement de sélection.
        load_roast_data_and_plot n'est appelé qu'une seule fois,
        80ms après le dernier itemSelectionChanged."""
        self._remember_selected_roast()
        self._selection_debounce.start()  # .start() repart de zéro si déjà en cours

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
            item = self.roast_list_widget.currentItem()
            fname = ((item.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname", "")
                     if item else "")
            if fname:
                self._last_roast_uuid = self._roast_uuid_of(fname)
        except (RuntimeError, AttributeError):
            pass

    def _row_of_newest_roast(self) -> int:
        """Row of the most recently roasted file, or -1.

        The list is ordered by bean name, so its first row is whichever bean
        comes first in the alphabet — not the roast just done. Recency has to be
        read from the roast date, which each row carries — the scan works it out
        from the log, or failing that from the date in the filename.
        """
        best_row, best_epoch = -1, None
        for row in range(self.roast_list_widget.count()):
            item = self.roast_list_widget.item(row)
            epoch = (item.data(Qt.ItemDataRole.UserRole) or {}).get("roast_epoch", 0)
            if best_epoch is None or epoch > best_epoch:
                best_row, best_epoch = row, epoch
        return best_row

    def _row_to_select_on_open(self) -> int:
        """Where the roast list should land when BeanCave opens.

        In order: the roast open in TilauScope, then the one left highlighted
        last time if it is still there, then the most recent roast. Row 0 is the
        last resort, and means nothing beyond "the list is not empty".
        """
        cur_file = Path(self.aw.curFile).name if self.aw.curFile else ""
        if cur_file:
            row = self._find_item_by_metadata(self.roast_list_widget, "raw_fname", cur_file)
            if row is not None and row >= 0:
                return row

        last_uuid = getattr(self, "_last_roast_uuid", "")
        if last_uuid:
            for meta in self._metadata_cache.records.values():
                if meta.roast_uuid and meta.roast_uuid == last_uuid:
                    row = self._find_item_by_metadata(
                        self.roast_list_widget, "raw_fname", meta.filename)
                    if row is not None and row >= 0:
                        return row
                    break   # known roast, no longer in this folder

        newest = self._row_of_newest_roast()
        return newest if newest >= 0 else 0



    def load_roast_data_and_plot(self) -> None:
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self.roast_plot_label.setText(QApplication.translate("tilauscope_beancave","Select a roast file to see the curve preview."))
            self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast Information will appear here."))
            self._set_viewer_buttons_enabled(False, multi=False)
            return

        self.is_zoomed = False

        if len(selected_items) == 1:
            # ── MODE MONO — comportement original ────────────────────────────
            self._multi_mode = False
            self._multi_curves.clear()
            self._multi_progress.hide()
            self._set_viewer_buttons_enabled(True, multi=False)
            # Réactiver le tab stats normal
            self.viewer_tabs.setTabEnabled(self.viewer_tabs.indexOf(self.stats_tab), True)

            # The roast to draw is the SELECTED one, not the current one. Qt
            # tracks the two apart: the current item is the keyboard cursor, and
            # it is None right after the list is rebuilt and stale after a
            # ctrl-click that drops the row it still points at. Reading it here
            # drew another roast than the highlighted one, or raised on None and
            # left the canvas exactly as it was — a blank curve, no log line.
            m = selected_items[0]
            metadata = m.data(Qt.ItemDataRole.UserRole)
            raw_fname = (metadata or {}).get("raw_fname", "")
            if not raw_fname:
                _log.warning("selected roast carries no file name — curve not redrawn")
                return
            filepath = Path(self.alog_directory) / raw_fname
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

            filepaths = []
            for item in selected_items:
                md = item.data(Qt.ItemDataRole.UserRole)
                if md is None:
                    continue
                fp = Path(self.alog_directory) / md["raw_fname"]
                if fp.exists():
                    filepaths.append(str(fp))

            filepaths = filepaths[:5]  # cap à 5 courbes
            if not filepaths:
                return
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
                if self._alog_thread.isRunning():
                    try:
                        self._alog_worker.finished.disconnect(self._alog_worker_finished_on_plot_ok)
                        self._alog_worker.error.disconnect(self._alog_worker_finished_on_plot_error)
                    except (AttributeError, TypeError, RuntimeError):
                        pass
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
                if self._multi_alog_thread.isRunning():
                    try:
                        self._multi_alog_worker.finished.disconnect(self._on_multi_curve_loaded)
                        self._multi_alog_worker.error.disconnect(self._on_multi_curve_error)
                    except (AttributeError, TypeError, RuntimeError):
                        pass
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
            worker.finished.connect(worker.deleteLater)
            worker.error.connect(worker.deleteLater)
            worker.cancelled.connect(worker.deleteLater)
            # Stocker les refs Python AVANT de connecter deleteLater
            self._multi_alog_thread = thread
            self._multi_alog_worker = worker
            # null-ifie la ref Python EN PREMIER, puis deleteLater détruit le C++
            thread.finished.connect(self._on_multi_alog_thread_done)
            thread.finished.connect(thread.deleteLater)
        else:
            # Chemin mono — comportement original
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            worker.cancelled.connect(thread.quit)
            worker.cancelled.connect(partial(self._alog_load_cancelled, filepath.name))
            worker.finished.connect(worker.deleteLater)
            worker.error.connect(worker.deleteLater)
            worker.cancelled.connect(worker.deleteLater)
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
        """Enable/disable action bar buttons depending on selection mode."""
        # Toujours dispo
        self.refresh_button.setEnabled(True)
        self.zoom_button.setEnabled(enabled or multi)
        # Toggles Consistance / Aligné : visibles uniquement en comparaison multi
        self.consistency_button.setVisible(multi)
        self.align_button.setVisible(multi)
        # Mono uniquement — sans B21S (géré exclusivement par niimbot_connected/disconnected)
        mono_only = [
            self.load_artisan_button_viewer,
            self.load_artisan_background_button_viewer,
            self.roast_finished_button,
            self.print_pdf_label_button,
            self.btn_roast_ready,
            self.btn_dial_in,
            self.btn_snapshot,
            self.btn_roast_card,
            self.btn_data_reader,
        ]
        for btn in mono_only:
            btn.setEnabled(enabled and not multi)
        # B21S : activé uniquement si imprimante réellement connectée ET prête (heartbeat OK)
        _niimbot_ok = getattr(self, "_niimbot_connected", False)
        if _niimbot_ok:
            self.print_label_button.setEnabled(enabled and not multi)
        else:
            self.print_label_button.setEnabled(False)

    def _load_next_multi_curve(self) -> None:
        """Charge séquentiellement la prochaine courbe de la queue multi.
        Le cache est consulté dans le thread UI — thread-safe.
        Si cache hit : on injecte directement les données sans lancer de thread.
        Si cache miss : on lance _AlogLoadWorker."""
        if self._multi_load_idx >= len(self._multi_load_queue):
            self._multi_progress.hide()
            self._plot_multi_curves()
            return

        fp_str = self._multi_load_queue[self._multi_load_idx]
        fp = Path(fp_str)

        # Cache lookup dans le thread UI — sans risque de concurrence
        cached_data = self.get_alog_data(fp)
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
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
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
            metadata = selected_items[0].data(Qt.ItemDataRole.UserRole)
            filepath = Path(self.alog_directory) / metadata["raw_fname"]
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
        target_uuid = self._alog_file_uuid.get(filename)
        if not target_uuid:
            bean_field = data.get("beans", "")
            uuid_match = self.uuid_pattern.search(bean_field)
            if uuid_match:
                target_uuid = uuid_match.group(1)

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
    # Export the selected roast as a shareable landscape JPEG
    def on_export_roast_card(self) -> None:
        # In comparison mode `lastprofiledata` holds a roast that is not on screen.
        if getattr(self, "_multi_mode", False):
            return
        if not self.roast_list_widget.selectedItems():
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
        bean = None
        try:
            m = self.uuid_pattern.search(str(data.get('beans', '') or ''))
            if m and hasattr(self, 'uuidmap'):
                bean = self.uuidmap.get(m.group(1))
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _logd.debug(f"roast card: bean resolution skipped: {e}")

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
            str(Path(downloads_dir) / f"{safe_name}.jpg"), "JPEG Images (*.jpg)")
        if not file_path:
            return

        try:
            from tilauscope.beancave_roast_card import RoastSocialCard
            ok = RoastSocialCard().save_jpeg(data, file_path, bean=bean, deltabt=deltabt)
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
        """Open the readable, navigable data reader for the selected roast."""
        if not self.roast_list_widget.selectedItems():
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Please, select a roast session first."),
                QMessageBox.Icon.Warning)
            return
        data = getattr(self, 'lastprofiledata', None)
        if not data:
            return
        title = ""
        try:
            m = self.roast_list_widget.currentItem()
            if m is not None:
                title = m.text()
        except Exception as e:  # noqa: BLE001
            _logd.warning(f"show_data_reader_view: title resolve failed: {e}")
        from tilauscope.roast_properties import RoastDataReaderDialog
        dlg = RoastDataReaderDialog(dict(data), title=title, parent=self)
        dlg.show()

    @pyqtSlot(str)
    def _alog_worker_finished_on_plot_error(self, filename:str):
        _logd.warning(f"Unable to read or decode alog file '{filename}'")
        self.roast_plot_label.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file"))
        self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file."))

    @pyqtSlot(object, object, object)
    def _alog_worker_finished_on_plot_ok(self, profiledata, deltaet, deltabt):
        _logd.debug("finished worker")
        self.lastprofiledata = profiledata
        # What is on the canvas is what this load carried. Asking the list here
        # answered "" whenever a background refresh had rebuilt it in the
        # meantime, and a blank booking makes the next refresh believe the
        # canvas shows another roast than it does.
        self._displayed_fname = getattr(self, '_loading_fname', '')
        row_now = self._find_item_by_metadata(
            self.roast_list_widget, "raw_fname", self._displayed_fname)
        item_now = (self.roast_list_widget.item(row_now)
                    if row_now is not None and row_now >= 0 else None)
        self.display_roast_info(self.lastprofiledata)
        self.plot_bt_curve_preview(self.lastprofiledata, deltaet, deltabt)  # type: ignore
        self._update_roast_plan_values()
        # ── Update header label with roast display name ──────────────────────
        item = item_now
        if item is not None:
            self.roast_plot_label.setText(item.text())
        # ── Timeline hand-off: profile now fully loaded → open the Brew Advisor ──
        pend = getattr(self, "_pending_brew_after_load", None)
        if pend:
            self._pending_brew_after_load = None
            cur_fn = (item.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname") if item is not None else None
            if cur_fn == pend:
                self.show_barista_expert_view(self.lastprofiledata)

    @pyqtSlot()
    def _on_alog_thread_done(self) -> None:
        """Clear refs after alog thread finishes normally so _cancel_threads
        and the next file selection won't see a stale thread handle."""
        self._alog_thread = None
        self._alog_worker = None

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
        cache_key = (deltaname, qmc.mode, qmc.curvefilter,
                     bool(qmc.interpolateDropsflag), bool(qmc.optimalSmoothing))
        for cached_data, key, cached_deltas in self._deltas_cache:
            if cached_data is data and key == cache_key:
                return cached_deltas

        tx = numpy.array(data.get("timex", []))
        timeindex = normalize_timeindex(data.get("timeindex", []))
        rd = timeindex[RoastingPhase.CHARGE] if marked(timeindex, RoastingPhase.CHARGE) else 0
        drop = timeindex[RoastingPhase.DROP]
        unit = data.get("temp_unit", "C")
        temp = [convertTemp(t,unit,self.aw.qmc.mode) for t in data.get(deltaname, [])]

        cf = self.aw.qmc.curvefilter #*2 # we smooth twice as heavy for PID/RoR calculation as for normal curve smoothing
        t1 = smooth_list(data.get("timex", []),(fill_gaps(temp) if self.aw.qmc.interpolateDropsflag else temp),window_len=cf,decay_smoothing=not self.aw.qmc.optimalSmoothing)
        if len(t1)>10 and len(tx) > 10:
            # we start RoR computation 10 readings after CHARGE to avoid this initial peak
            RoR_start = min(rd+10,len(tx)-1)
            _, deltas = self.aw.qmc.recomputeDeltas(tx,RoR_start,drop,None,t1,optimalSmoothing=self.aw.qmc.optimalSmoothing)
        else:
            deltas = None
        self._deltas_cache.append((data, cache_key, deltas))
        del self._deltas_cache[:-5]
        return deltas

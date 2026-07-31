#
# ABOUT
# Beancave

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
# TiLau 2025

# # simple bean cave management
# mod programmed by Tilau (2025)
# manage a json file with a list of green beans and associate roasts to them by name
# manage stock in grams and use them in roast properties to enter basic information on beans
# decrease stock in g when they are selected from roast properties
# this mod does not replace Artisan plus bean management but is a simple inteface for enthousiasts
# credit to https://github.com/AndBondStyle/niimprint for printer support

from matplotlib.axes import Axes
import numpy
import logging
import json
import time
import uuid
import sys
import subprocess
import os
from collections import defaultdict
from typing import Final, Any, override, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon  # pylint: disable=unused-import
from functools import partial
import ast  # Import de la bibliothèque ast
import qrcode # Import de la bibliothèque qrcode
import re # For sorting alog files
import csv
import statistics
import requests
from datetime import datetime
from pathlib import Path

#import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D 
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import MultipleLocator

from PIL import Image
from PIL.ImageQt import ImageQt # Import pour convertir l'image PIL en QImage

from artisanlib.main import ApplicationWindow, getAppPath # noqa: F401 # pylint: disable=unused-import
from artisanlib.widgets import MyQDoubleSpinBox
from artisanlib.util import fill_gaps, convertTemp, cast, fromCtoFstrict, convertWeight, weight_units, smooth_list  ## TILAU ## smooth_list moved from tgraphcanvas to util

from artisanlib.atypes import ProfileData, ComputedProfileInformation

from PyQt6.QtCore import (QMutex, QMutexLocker,QRect, QModelIndex, QItemSelectionModel, QStandardPaths, Qt, pyqtSlot, QSettings, QThread, pyqtSignal, QObject,
                          QEasingCurve,QPoint, QTimer, QPropertyAnimation, QEvent, QVariantAnimation, QByteArray, QSize) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtGui import ( QPixmap, QColor, QCloseEvent, QResizeEvent, QGuiApplication, QCursor, QKeyEvent, QPainter, QPainterPath, QBrush, QAction) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtWidgets import (QApplication, QComboBox, QSizeGrip, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QProgressDialog, QScrollArea,  # @UnusedImport @Reimport  @UnresolvedImport
                                QPushButton, QWidget, QTabWidget, # @UnusedImport @Reimport  @UnresolvedImport
                                QGridLayout, QGroupBox, QTableWidget, QHeaderView, QTableWidgetItem, QAbstractItemView, 
                                QStyledItemDelegate, QListView, QFrame, QCheckBox, QListWidgetItem,
                                QFileDialog, QMessageBox, QDialog, QListWidget, QSplitter, QSizePolicy, QFormLayout, QDoubleSpinBox, QSpinBox, QTextEdit, QProgressBar, QStackedWidget,
                                QMenu) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtSvg import QSvgRenderer  # icônes SVG inline pour ZoomToggleButton

# Import QWebEngineView for both PyQt6 and PyQt5
       
from tilauscope.niimprint import NiimbotBLE, Niimprint_PaperType
from tilauscope.tilau_ble_scanner import TilauBLEScanner
from tilauscope.tilauscope_types import (GreenBean, AGTRON_SCALES, AgtronScale, ReferenceProfile, BeanCaveContainer, GREEN_BEAN_COLUMNS, show_styled_message,
                                         THEME, standardization_map, ProbeDeviation, ProbeDeviationInterval, RoastingPhase, TilauProgressDialog, _IS_MACOS, _IS_WINDOWS)
from tilauscope.roast_timeline import RoastReadyDialog
from tilauscope.sack_manager import SackChipsRow, SackPool, confirm_release, prompt_release_if_emptied  ## TILAU ## sack labels (Lot 1, §9.3)
from tilauscope.beancave_catalogue import CatalogueListWidget  ## TILAU ## rich catalogue list (Lot 5)
from tilauscope.beancave_bean_sheet import BeanSheetWidget  ## TILAU ## read-first bean sheet (Lot 5)
from tilauscope.ai_support import TilauAIConfig
from tilauscope.lebrewroastsee import LebrewWaterActivityChecker
from tilauscope.tilau_wheel import FlavorSelectorDialog
from tilauscope.roasters import RoasterContext, RoasterManager
from tilauscope.alogmanager import AlogCacheCollection, AlogMetadata, _AlogCacheIndexingWorker
from tilauscope.niimprint import NiimbotHeartbeat, NiimbotRFIDinfo
from tilauscope.brew_advisor import BrewInput, WaterProfile
from tilauscope.brew_advisor_dialog import BrewAdvisorDlg

_logd: Final[logging.Logger] = logging.getLogger('tilau')
_log: Final[logging.Logger] = logging.getLogger(__name__)

# ── Fixed Catppuccin-Mocha palette for curve preview plots ──────────────────
# Never read from aw.qmc.palette so Artisan theme customisation cannot pollute
# TilauScope preview rendering.
_PLOT_PALETTE: Final[dict[str, str]] = {
    "background":  "#1E1E2E",   # Mocha Base
    "canvas":      "#1E1E2E",
    "bt":          "#F38BA8",   # Mocha Red
    "et":          "#A6E3A1",   # Mocha Green
    "deltabt":     "#89B4FA",   # Mocha Blue  (RoR BT dashed)
    "deltaet":     "#FAB387",   # Mocha Peach (RoR ET dashed)
    "grid":        "#45475A",   # Mocha Surface 1
    "title":       "#CDD6F4",   # Mocha Text
    "xlabel":      "#CDD6F4",
    "ylabel":      "#CDD6F4",
    # machine sliders (Air / Drum / Airwave / Burner)
    "slider0":     "#89B4FA",   # Blue  – Air
    "slider1":     "#A6E3A1",   # Green – Drum
    "slider2":     "#FAB387",   # Peach – Airwave
    "slider3":     "#F38BA8",   # Red   – Burner
}

# Tailles de police du Roast Viewer — centralisées pour un rendu lisible et cohérent
_FS_TITLE:  Final[int] = 11   # titre du graphe
_FS_AXIS:   Final[int] = 10   # labels d'axe (x / y)
_FS_TICK:   Final[int] = 9    # graduations
_FS_EVENT:  Final[int] = 9    # annotations d'événement (Charge / DE / FCs / Drop)
_FS_HOVER:  Final[int] = 8    # tooltips hover sur la courbe
_FS_LEGEND: Final[int] = 9    # légendes

C0_COLOR_KEY: Final[str] = "RoastColor/C0_Interception"
C_BT_COLOR_KEY: Final[str] = "RoastColor/C_BT"
C_DTR_COLOR_KEY: Final[str] = "RoastColor/C_DTR"
C_WL_COLOR_KEY: Final[str] = "RoastColor/C_WL"
DEFAULT_C0: Final[float] = 328.67
DEFAULT_C_BT: Final[float] = -1.55
DEFAULT_C_DTR: Final[float] = -0.06
DEFAULT_C_WL: Final[float] = -3.61

# Ajout de 'Process' et 'Count' à la liste des en-têtes
greencave_headers = [
            'Name', 'Farm', 'Country', 'Supplier', 'Category', 'Process', 'Crop', 'Density',
            'Humidity', 'Water activity', 'Volume', 'Altitude', 'Specy', 'Variety',
            'Stock', 'Flavour Notes', 'SCA score', 'Roasts','Weight',
            'Blend?', 'Ratio 1', 'Bean 2 Name', 'Ratio 2', 'Bean 3 Name', 'Ratio 3', 'Blend Notes', 'tips', 'uuid',
        ]

# Path to the JSON file
BEANCAVE_FILE_NAME: Final[str] = "beancave.json"


# ─── SVG inline : expand (état normal) ───────────────────────────────────────
_SVG_EXPAND = b"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M2 6V2H6"      stroke="#CCCCCC" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M10 2H14V6"    stroke="#CCCCCC" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M14 10V14H10"  stroke="#CCCCCC" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M6 14H2V10"    stroke="#CCCCCC" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

# ─── SVG inline : collapse (état actif — fenêtre maximisée) ──────────────────
_SVG_COLLAPSE = b"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M5 1V5H1"      stroke="#7EB8FA" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M11 5H15V1"    stroke="#7EB8FA" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M15 11V15H11"  stroke="#7EB8FA" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M1 11H5V15"    stroke="#7EB8FA" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

# Glyphe « Consistance » : courbe montante entourée d'une bande (enveloppe).
_SVG_CONSISTENCY = b"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M1 10.5 C5 7.5 9 4.5 15 1.5 L15 4.5 C9 7.5 5 10.5 1 13.5 Z"
    fill="#CDD6F4" fill-opacity="0.30"/>
  <path d="M1 12 C5 9 9 6 15 3" stroke="#CDD6F4" stroke-width="1.4"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

# Glyphe « Aligné » (time-warp) : deux bornes verticales + double-flèche
# horizontale = étirer/compresser le temps pour aligner les jalons.
_SVG_ALIGN = b"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M2.5 2V14M13.5 2V14" stroke="#CDD6F4" stroke-width="1.5"
    stroke-linecap="round"/>
  <path d="M5 8H11" stroke="#CDD6F4" stroke-width="1.3" stroke-linecap="round"/>
  <path d="M5 8L7 6M5 8L7 10" stroke="#CDD6F4" stroke-width="1.3"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M11 8L9 6M11 8L9 10" stroke="#CDD6F4" stroke-width="1.3"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def _svg_bytes_to_icon(svg_bytes: bytes, size: int = 16) -> "QIcon":
    """
    Rend un SVG (bytes) en QIcon via QSvgRenderer.
    Sans fichier disque, sans ressource .qrc — compatible macOS/Windows/Qt 6.x.
    """
    from PyQt6.QtGui import QIcon
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


## TILAU ## Flask icon for the density-measure button (Catppuccin ACCENT)
_SVG_DENSITY = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    f'<path d="M8 2 v5 L4 16 a1.2 1.2 0 0 0 1.1 1.7 h9.8 A1.2 1.2 0 0 0 16 16 L12 7 V2" '
    f'fill="none" stroke="{THEME["ACCENT"]}" stroke-width="1.4" '
    f'stroke-linejoin="round" stroke-linecap="round"/>'
    f'<line x1="7" y1="2" x2="13" y2="2" stroke="{THEME["ACCENT"]}" '
    f'stroke-width="1.4" stroke-linecap="round"/>'
    f'<path d="M6.2 12 h7.6 l2 4 a1 1 0 0 1 -0.9 1.5 H5.1 A1 1 0 0 1 4.2 16 z" '
    f'fill="{THEME["ACCENT"]}" opacity="0.45"/>'
    f'</svg>'
)


class ZoomToggleButton(QPushButton):
    """
    Bouton zoom/fullscreen checkable avec icônes SVG inline.

    - Icônes chargées une seule fois en variable de classe (lazy).
    - Aucun emoji, aucun texte : rendu identique macOS / Windows.
    - État normal : fond sombre transparent.
    - État actif  : fond bleu teinté.
    - Signal toggled(bool) hérité de QPushButton.
    """

    _icon_normal: "QIcon | None" = None
    _icon_active: "QIcon | None" = None

    _ICON_SIZE = 16
    _BTN_SIZE  = 32

    _SS = """
        QPushButton {
            background-color : rgba(30,  30,  46,  160);
            border            : 1px solid rgba(255, 255, 255, 45);
            border-radius     : 8px;
        }
        QPushButton:hover {
            background-color : rgba(60,  60,  90,  200);
            border           : 1px solid rgba(255, 255, 255, 90);
        }
        QPushButton:checked {
            background-color : rgba(89,  150, 246, 55);
            border           : 1px solid rgba(89,  150, 246, 180);
        }
        QPushButton:disabled {
            opacity : 0.35;
        }
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self._BTN_SIZE, self._BTN_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(
            QApplication.translate("tilauscope_beancave", "Toggle full-screen curve")
        )
        self.setText("")
        self.setStyleSheet(self._SS)

        if ZoomToggleButton._icon_normal is None:
            ZoomToggleButton._icon_normal = _svg_bytes_to_icon(_SVG_EXPAND,   self._ICON_SIZE)
            ZoomToggleButton._icon_active = _svg_bytes_to_icon(_SVG_COLLAPSE, self._ICON_SIZE)

        self.setIcon(ZoomToggleButton._icon_normal)       # type: ignore[arg-type]
        self.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        self.toggled.connect(self._sync_icon)

    @pyqtSlot(bool)
    def _sync_icon(self, checked: bool) -> None:
        icon = ZoomToggleButton._icon_active if checked else ZoomToggleButton._icon_normal
        self.setIcon(icon)  # type: ignore[arg-type]


class SaveMarkerButton(QPushButton):
    """
    Ephemeral overlay button shown when timeindex has been edited but not saved.
    Positioned bottom-right of CanvasContainer, hidden by default.
    """
    _SS = """
        QPushButton {
            background-color : rgba(166, 227, 161, 220);
            color            : #1e1e2e;
            border           : 1px solid rgba(166, 227, 161, 255);
            border-radius    : 6px;
            padding          : 4px 14px;
            font-family      : 'JetBrains Mono', monospace;
            font-size        : 11px;
            font-weight      : bold;
        }
        QPushButton:hover {
            background-color : rgba(166, 227, 161, 255);
        }
        QPushButton:pressed {
            background-color : rgba(100, 180, 100, 255);
        }
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(QApplication.translate("tilauscope_beancave", "💾 Save markers"))
        self.setStyleSheet(self._SS)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.adjustSize()
        self.hide()


class CanvasContainer(QWidget):
    """
    Conteneur Qt stable qui wrappe le FigureCanvas matplotlib.

    - Fournit un parent QWidget dans le layout (curve_layout).
    - Porte le ZoomToggleButton en overlay haut-gauche via son propre resizeEvent.
    - Porte le SaveMarkerButton en overlay bas-droite (caché par défaut).
    - En mode zoom plein-écran, on transfère CE widget dans le QDialog :
      les boutons suivent naturellement (ils sont enfants du conteneur).
    """

    _MARGIN = 8

    def __init__(
        self,
        canvas: FigureCanvas,
        zoom_btn: ZoomToggleButton,
        parent: QWidget | None = None,
        mode_btns: "list[QPushButton] | None" = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(canvas)

        zoom_btn.setParent(self)
        zoom_btn.raise_()
        self._zoom_btn = zoom_btn

        # Toggles optionnels (vues Consistance / Aligné) en overlay, à droite du zoom.
        self._mode_btns = list(mode_btns or [])
        for b in self._mode_btns:
            b.setParent(self)
            b.raise_()

        self._save_btn = SaveMarkerButton(self)
        self._save_btn.raise_()

        self._reposition_buttons()

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_buttons()

    def _reposition_buttons(self) -> None:
        self._zoom_btn.move(self._MARGIN, self._MARGIN)
        x = self._MARGIN + self._zoom_btn.width() + 6
        for b in self._mode_btns:
            b.move(x, self._MARGIN)
            x += b.width() + 6
        bw = self._save_btn.sizeHint().width()
        bh = self._save_btn.sizeHint().height()
        x = self.width()  - bw - self._MARGIN
        y = self.height() - bh - self._MARGIN * 5
        self._save_btn.move(max(0, x), max(0, y))

    # Legacy alias — callers of _reposition_button still work
    def _reposition_button(self) -> None:
        self._reposition_buttons()


def load_cave_beans() -> list:
    """Load green beans from the beancave JSON file.

    Reads the beancave directory from QSettings and returns the bean list.
    Returns an empty list if the file is missing, unreadable, or malformed.
    Replaces BeanHelper — use this wherever only the bean list is needed.
    """
    from PyQt6.QtCore import QSettings
    settings = QSettings()
    directory = settings.value('beancaveDirectory', '', str)
    if not directory:
        return []
    cave_dir  = Path(directory).expanduser()
    cave_file = cave_dir / BEANCAVE_FILE_NAME
    try:
        if not (cave_dir.exists() and cave_dir.is_dir() and os.access(str(cave_dir), os.R_OK)):
            _logd.error(f'Beancave directory not readable: {cave_dir}')
            return []
        if not (cave_file.exists() and cave_file.is_file() and os.access(str(cave_file), os.R_OK)):
            _logd.error(f'Beancave file not readable: {cave_file}')
            return []
        content = cave_file.read_text(encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8')
        cave = BeanCaveContainer.from_json(content)
        return cave.green_beans or []
    except json.JSONDecodeError as e:
        _logd.error(f'load_cave_beans: JSON error in beancave.json: {e}')
    except Exception as e:
        _logd.error(f'load_cave_beans: unexpected error: {e}')
    return []

import ctypes
def apply_mica_acrylic_effect(window):
    """Applies Mica (Win11) or Acrylic (Win10) backdrop."""
    if not _IS_WINDOWS:
        return

    hwnd = int(window.winId())
    dwmapi = ctypes.windll.dwmapi
    
    # 1. Enable Immersive Dark Mode for the title bar
    dark_mode = ctypes.c_int(1)
    dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))

    # 2. Set Backdrop Type (38 is the attribute for backdrop type)
    # 2 = Mica (Win11), 3 = Acrylic (Win10/11)
    backdrop_type = ctypes.c_int(2 if sys.getwindowsversion().build >= 22000 else 3)
    dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop_type), ctypes.sizeof(backdrop_type))

class HoverTooltip(QLabel):
    def __init__(self):               ## ← no parent arg
        super().__init__(
            None,                     ## ← parent=None, top-level window
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool      ## ← Tool, not ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("""
            QLabel {
                background-color: #2e2e2e;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 6px;
                border-radius: 4px;
                font-size: 11px;
            }
        """)
        self.setWordWrap(False)
        self.hide()
    
    def show_at(self, global_pos: QPoint, html: str) -> None:
        self.setText(html)
        self.adjustSize()
        # Décalage pour ne pas être pile sous le curseur
        offset = QPoint(15, 15)
        self.move(global_pos + offset) # move utilise des coordonnées ECRAN
        self.show()

class SmoothHoverFilter(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_border = QColor(THEME.get('BORDER', '#3f3f3f'))
        self.accent_border = QColor(THEME.get('ACCENT', '#0078d4'))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.HoverEnter:
            self.animate(obj, self.base_border, self.accent_border)
            return True   # ← keep returning True so Qt doesn't double-fire
        elif event.type() == QEvent.Type.HoverLeave:
            self.animate(obj, self.accent_border, self.base_border)
            return True
        return super().eventFilter(obj, event)

    def animate(self, widget, start_brd, end_brd):
        anim = QVariantAnimation(widget)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Determine the Qt widget class name for scoped CSS
        # This prevents the rule leaking into child widgets or tooltip scope
        class_name = widget.__class__.__name__

        def update_style(value):
            brd_r = int(start_brd.red()   + (end_brd.red()   - start_brd.red())   * value)
            brd_g = int(start_brd.green() + (end_brd.green() - start_brd.green()) * value)
            brd_b = int(start_brd.blue()  + (end_brd.blue()  - start_brd.blue())  * value)
            color_brd = f"rgb({brd_r}, {brd_g}, {brd_b})"

            widget.setStyleSheet(f"""
                {class_name} {{
                    border: 2px solid {color_brd};
                    border-radius: 5px;
                    padding: 3px;
                    background-color: {THEME.get('SURFACE', '#1e1e2e')};
                    color: {THEME.get('TEXT', 'white')};
                    font-family: 'JetBrains Mono';
                }}
                QToolTip {{
                    background-color: #2D2F3F;
                    color: white;
                    border: 1px solid #585B70;
                    padding: 5px;
                    border-radius: 3px;
                    font-size: 11px;
                    opacity: 255;
                }}
            """)

        anim.valueChanged.connect(update_style)
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

# Add this class near the top of beancave.py, after the imports
# Works identically on macOS (Retina included) and Windows 10/11

class TilauSpinBox(MyQDoubleSpinBox):
    """
    MyQDoubleSpinBox that draws its own inset up/down arrows via paintEvent.
    Fixes macOS Qt6/Fusion ignoring ::up-arrow CSS, and prevents hover-
    triggered window resize.
    """

    _BTN_W  : int = 20   # button column width  (px)
    _ARROW_W: int = 7    # arrow glyph width    (px)
    _ARROW_H: int = 4    # arrow glyph height   (px)
    _H      : int = 28   # fixed widget height  (px)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._H)
        # ── Only style THIS class — do NOT use QDoubleSpinBox here
        # so the parent stylesheet's QDoubleSpinBox rule can't override us
        self.setStyleSheet(f"""
            TilauSpinBox {{
                padding-right : {self._BTN_W + 2}px;
                border        : 1px solid {THEME.get('BORDER', '#3f3f3f')};
                border-radius : 5px;
                background    : {THEME.get('SURFACE', '#1e1e2e')};
                color         : {THEME['TEXT']};
                font-family   : 'JetBrains Mono', monospace;
                font-size     : 12px;
            }}
            TilauSpinBox:focus {{
                border : 1px solid {THEME['ACCENT']};
            }}
            /* Completely suppress the native button subcontrols */
            TilauSpinBox::up-button   {{ width: 0px; border: none; }}
            TilauSpinBox::down-button {{ width: 0px; border: none; }}
            TilauSpinBox::up-arrow    {{ width: 0px; height: 0px; }}
            TilauSpinBox::down-arrow  {{ width: 0px; height: 0px; }}
        """)
        self._up_hovered   = False
        self._down_hovered = False
        self.setMouseTracking(True)

    # ── geometry — use contentsRect() so layout is already resolved ───────

    def _btn_x(self) -> int:
        """Left edge of the button column, inside the border."""
        return self.contentsRect().right() - self._BTN_W + 1

    def _up_rect(self) -> QRect:
        r   = self.contentsRect()
        mid = r.top() + r.height() // 2
        return QRect(self._btn_x(), r.top(), self._BTN_W, mid - r.top())

    def _down_rect(self) -> QRect:
        r   = self.contentsRect()
        mid = r.top() + r.height() // 2
        return QRect(self._btn_x(), mid, self._BTN_W, r.bottom() - mid + 1)

    # ── mouse ─────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        pos      = event.pos()
        up_hot   = self._up_rect().contains(pos)
        down_hot = self._down_rect().contains(pos)
        if up_hot != self._up_hovered or down_hot != self._down_hovered:
            self._up_hovered   = up_hot
            self._down_hovered = down_hot
            self.update()          # repaint only — no geometry change
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._up_hovered or self._down_hovered:
            self._up_hovered   = False
            self._down_hovered = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        pos = event.pos()
        if self._up_rect().contains(pos):
            self.stepUp()
            return
        if self._down_rect().contains(pos):
            self.stepDown()
            return
        super().mousePressEvent(event)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # frame + text drawn by Qt

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        accent  = QColor(THEME['ACCENT'])
        border  = QColor(THEME.get('BORDER', '#3f3f3f'))
        surface = QColor(THEME.get('SURFACE', '#1e1e2e'))
        fg      = QColor(THEME['TEXT'])

        up_r   = self._up_rect()
        down_r = self._down_rect()

        # ── button backgrounds ────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        for rect, hovered in ((up_r, self._up_hovered),
                               (down_r, self._down_hovered)):
            fill = QPainterPath()
            fill.addRoundedRect(
                float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height()), 2, 2)
            p.fillPath(fill, QBrush(accent if hovered else surface))

        # ── separator lines ───────────────────────────────────────────────
        p.setPen(border)
        bx  = self._btn_x()
        cr  = self.contentsRect()
        mid = cr.top() + cr.height() // 2
        p.drawLine(bx, cr.top(),  bx, cr.bottom())   # vertical divider
        p.drawLine(bx, mid, cr.right(), mid)           # horizontal mid

        # ── arrow triangles ───────────────────────────────────────────────
        def draw_triangle(cx: float, cy: float, up: bool) -> None:
            aw = self._ARROW_W / 2.0
            ah = self._ARROW_H / 2.0
            tri = QPainterPath()
            if up:
                tri.moveTo(cx,      cy - ah)
                tri.lineTo(cx + aw, cy + ah)
                tri.lineTo(cx - aw, cy + ah)
            else:
                tri.moveTo(cx - aw, cy - ah)
                tri.lineTo(cx + aw, cy - ah)
                tri.lineTo(cx,      cy + ah)
            tri.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            # Arrow is dark on accent background, light otherwise
            any_hovered = self._up_hovered or self._down_hovered
            arrow_col   = QColor(THEME['BG']) if any_hovered else fg
            p.fillPath(tri, QBrush(arrow_col))

        draw_triangle(
            up_r.x()   + up_r.width()   / 2.0,
            up_r.y()   + up_r.height()  / 2.0,
            up=True)
        draw_triangle(
            down_r.x() + down_r.width()  / 2.0,
            down_r.y() + down_r.height() / 2.0,
            up=False)

        p.end()

class QRCodeDialog(QDialog):
    """
    Dialog d'affichage du QR Code — style uniforme FlavorSelectorDialog.

    Frameless + fond translucide + container arrondi thème Catppuccin Mocha.
    Actions : Copy to Clipboard | Save as PNG | Print | ✕ Close.
    """

    def __init__(
        self,
        bean_name: str,
        pixmap: QPixmap,
        pil_img,                       # PIL.Image pour save/print
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pixmap  = pixmap
        self._pil_img = pil_img

        # ── Root layout avec marge pour l'ombre / border ────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Conteneur principal ──────────────────────────────────────────────
        container = QFrame()
        container.setObjectName("QRContainer")
        container.setStyleSheet(f"""
            #QRContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 15px;
            }}
        """)
        root.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 10, 20, 16)
        inner.setSpacing(10)

        # ── Header ───────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 4, 0, 6)

        title = QLabel(f"QR CODE — {bean_name.upper()}")
        title.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:14px;font-weight:800;"
            f"font-family:'JetBrains Mono';border:none;background:transparent;"
        )

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.reject)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #313244;
                color: #f38ba8;
                border-radius: 15px;
                border: 1px solid #f38ba8;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #f38ba8;
                color: #1e1e2e;
            }
        """)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        inner.addLayout(header)

        # ── QR image ─────────────────────────────────────────────────────────
        qr_label = QLabel()
        # Fond blanc pour le QR (lisibilité des modules noirs)
        scaled = pixmap.scaled(
            280, 280,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        qr_label.setPixmap(scaled)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setStyleSheet(
            "background: white; border-radius: 8px; padding: 8px; border: none;"
        )
        inner.addWidget(qr_label)

        # ── Footer — boutons d'action ─────────────────────────────────────────
        _F  = "'JetBrains Mono', monospace"
        _SS_ACT = f"""
            QPushButton {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME['BORDER']};
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : {_F};
                font-size        : 12px;
            }}
            QPushButton:hover {{
                background-color : {THEME['HOVER']};
                color            : {THEME['BG']};
                border-color     : {THEME['HOVER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
            }}
        """

        footer = QHBoxLayout()
        footer.setSpacing(8)

        self._btn_copy = QPushButton(
            QApplication.translate("tilauscope_beancave", "Copy to Clipboard")
        )
        self._btn_copy.setStyleSheet(_SS_ACT)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)

        btn_save = QPushButton(
            QApplication.translate("tilauscope_beancave", "Save as PNG")
        )
        btn_save.setStyleSheet(_SS_ACT)
        btn_save.clicked.connect(self._save_as_png)

        btn_print = QPushButton(
            QApplication.translate("tilauscope_beancave", "Print")
        )
        btn_print.setStyleSheet(
            f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : {_F};
                font-size        : 12px;
                font-weight      : bold;
            }}
            QPushButton:hover {{
                background-color : {THEME['HOVER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
            """
        )
        btn_print.clicked.connect(self._print)

        footer.addWidget(self._btn_copy)
        footer.addWidget(btn_save)
        footer.addStretch()
        footer.addWidget(btn_print)
        inner.addLayout(footer)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setPixmap(self._pixmap)
        self._btn_copy.setText(
            QApplication.translate("tilauscope_beancave", "Copied! ✓")
        )
        QTimer.singleShot(1500, lambda: self._btn_copy.setText(
            QApplication.translate("tilauscope_beancave", "Copy to Clipboard")
        ))

    def _save_as_png(self) -> None:
        from pathlib import Path
        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        # Extraire le nom du bean depuis le titre
        title_text = self.findChild(QLabel).text() if self.findChild(QLabel) else "QR"
        bean_name = title_text.replace("QR CODE — ", "").replace(" ", "_").lower()
        default_path = str(Path(downloads_dir) / f"QR_{bean_name}.png")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            QApplication.translate("tilauscope_beancave", "Save QR Code"),
            default_path,
            QApplication.translate("tilauscope_beancave", "PNG Files (*.png);;All Files (*)")
        )
        if file_path:
            self._pil_img.save(file_path)

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        print_dialog = QPrintDialog(printer, self)
        if print_dialog.exec() == QPrintDialog.DialogCode.Accepted:
            from PIL.ImageQt import ImageQt as _IQt
            painter = QPainter(printer)
            q_img   = _IQt(self._pil_img)
            rect    = painter.viewport()
            size    = q_img.size()
            size.scale(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.setViewport(rect.x(), rect.y(), size.width(), size.height())
            painter.setWindow(q_img.rect())
            painter.drawImage(0, 0, q_img)
            painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# Floating density window — mirrors _ScaleFloatWindow (roast_properties).   ## TILAU ##
# Pilots scale1 like the weight card; the main clickable value is the
# computed green-bean density (g/l) = round(net_g * 1000 / volume_ml).
# Pure signal interface: density_picked(float) and tare_requested() —
# the window holds no reference to aw.
# ─────────────────────────────────────────────────────────────────────────────
class _DensityFloatWindow(QDialog):
    """Always-on-top card showing live computed density from scale1.

    Click the density value -> density_picked(float) is emitted.
    Net weight and TARE button are secondary controls.
    """

    density_picked = pyqtSignal(float)
    tare_requested = pyqtSignal()

    _VOLUMES_ML: tuple[int, ...] = (50, 100, 200, 250, 500)
    _DEFAULT_VOLUME_ML: int = 100

    def __init__(self, parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._net_g: float | None = None
        self._volume_ml: int = self._DEFAULT_VOLUME_ML
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("densityCard")
        card.setStyleSheet(f"""
            QFrame#densityCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
            QToolTip {{
                background-color: #2D2F3F;
                color: white;
                border: 1px solid #585B70;
                padding: 5px;
                border-radius: 3px;
                font-size: 11px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(4)

        header = QLabel(QApplication.translate("tilauscope_beancave", "🧪  DENSITY"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:10px;letter-spacing:2px;"
            f"font-family:'JetBrains Mono';font-weight:bold;background:transparent;"
        )

        self._density_lbl = QLabel("––– g/l")
        self._density_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._density_lbl.setStyleSheet(
            f"color:{THEME['ACCENT']};font-size:28px;font-weight:bold;"
            f"font-family:'JetBrains Mono';background:transparent;"
        )
        self._density_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._density_lbl.setToolTip(
            f"<span style='font-size:10px;'>"
            f"{QApplication.translate('tilauscope_beancave', 'Click to transfer density')}</span>"
        )
        self._density_lbl.mousePressEvent = self._on_density_clicked  # type: ignore[method-assign]

        hint = QLabel(QApplication.translate("tilauscope_beancave", "tap to use"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:10px;"
            f"font-family:'JetBrains Mono';background:transparent;"
        )

        # volume selector (fixed list)
        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        vol_lbl = QLabel(QApplication.translate("tilauscope_beancave", "volume"))
        vol_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']};font-size:11px;"
            f"font-family:'JetBrains Mono';background:transparent;"
        )
        self._vol_combo = QComboBox()
        for v in self._VOLUMES_ML:
            self._vol_combo.addItem(f"{v} ml", v)
        self._vol_combo.setCurrentIndex(self._VOLUMES_ML.index(self._DEFAULT_VOLUME_ML))
        self._vol_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._vol_combo.setMinimumWidth(96)
        self._vol_combo.view().setMinimumWidth(96)  # popup must fit "500 ml"
        self._vol_combo.currentIndexChanged.connect(self._on_volume_changed)
        vol_row.addStretch(1)
        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self._vol_combo)
        vol_row.addStretch(1)

        # secondary row: net weight + TARE
        sec_row = QHBoxLayout()
        sec_row.setSpacing(8)
        self._net_lbl = QLabel(QApplication.translate("tilauscope_beancave", "net –– g"))
        self._net_lbl.setStyleSheet(
            f"color:{THEME['TEXT']};font-size:12px;"
            f"font-family:'JetBrains Mono';background:transparent;"
        )
        self._tare_btn = QPushButton(QApplication.translate("tilauscope_beancave", "TARE"))
        self._tare_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tare_btn.setStyleSheet(f"""
            QPushButton {{
                background-color:{THEME['BG']};
                color:{THEME['SUBTEXT']};
                border:1px solid {THEME['BORDER']};
                border-radius:8px;
                padding:3px 12px;
                font-size:11px;letter-spacing:1px;
                font-family:'JetBrains Mono';
            }}
            QPushButton:hover {{ border-color:{THEME['ACCENT']}; }}
        """)
        self._tare_btn.clicked.connect(self.tare_requested.emit)
        sec_row.addWidget(self._net_lbl)
        sec_row.addStretch(1)
        sec_row.addWidget(self._tare_btn)

        cl.addWidget(header)
        cl.addWidget(self._density_lbl)
        cl.addWidget(hint)
        cl.addLayout(vol_row)
        cl.addLayout(sec_row)
        outer.addWidget(card)
        self.adjustSize()

    # ── Public slots ─────────────────────────────────────────────────────────
    @pyqtSlot(int)
    def update_weight(self, weight: int) -> None:
        self._net_g = float(weight)
        self._net_lbl.setText(
            QApplication.translate("tilauscope_beancave", "net {0} g").format(weight)
        )
        self._recompute()

    @pyqtSlot()
    def scale_disconnected(self) -> None:
        self._net_g = None
        self._net_lbl.setText(QApplication.translate("tilauscope_beancave", "net –– g"))
        self._density_lbl.setText("––– g/l")

    # ── Interaction ────────────────────────────────────────────────────────
    def _on_volume_changed(self, _idx: int) -> None:
        self._volume_ml = int(self._vol_combo.currentData())
        self._recompute()

    def _recompute(self) -> None:
        if self._net_g is None or self._net_g <= 0.0 or self._volume_ml <= 0:
            self._density_lbl.setText("––– g/l")
            return
        density = round(self._net_g * 1000.0 / self._volume_ml)
        self._density_lbl.setText(f"{density} g/l")

    def _on_density_clicked(self, _event) -> None:  # noqa: ANN001
        if self._net_g is None or self._net_g <= 0.0 or self._volume_ml <= 0:
            return
        self.density_picked.emit(self._net_g * 1000.0 / self._volume_ml)


class BeancaveDlg(QDialog): # 2025-12-23 changed from ArtisanResizeablDialog to QDialog to handle modality
    def __init__(self, aw:'ApplicationWindow', uuid:str="") -> None:
        super().__init__(parent=aw)
        # before setting up information for ui, let's work on security
        self.shutdown_lock = QMutex() # Le verrou
        self.is_shutting_down = False  # Le drapeau
        self._niimbot_connected = False  # True uniquement quand imprimante prête (heartbeat OK)
        self._niimbot_ble_up    = False  # True dès que la connexion BLE est établie (indép. du papier)
        self._niimbot_poll_timer: QTimer | None = None   # timer heartbeat 5 s
        self._niimbot_poll_thread: QThread | None = None # thread du dernier poll
        self._niimbot_prev_closingstate: int | None = None  # pour détecter réouverture capot
        if _IS_WINDOWS:
            # Tool + Window: stays above aw without system-wide StaysOnTopHint (avoids crash on open)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Window
                | Qt.WindowType.Tool
            )
        else:
            # macOS: Dialog keeps the window in aw's z-order stack
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Window
                | Qt.WindowType.Dialog
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if _IS_WINDOWS:
            apply_mica_acrylic_effect(self)

        self._drag_pos = None
        
        self.aw = aw
        self.ai = aw.tilau_aiConfig

        ## TILAU ## scale-piloted density measurement window
        self._density_window: '_DensityFloatWindow | None' = None
        self._density_scale_was_connected: bool = False

        self._roaster_thread: QThread | None = None
        self._ble_thread:     QThread | None = None   # obsolète — conservé pour _cancel_threads
        self._ble_scanner:    TilauBLEScanner | None = None
        self._alog_thread:    QThread | None = None   

        self.coffee_beans_species:list[str] = []
        self.coffee_beans_categories:list[str] = []
        self.coffee_processing_methods:dict[str,list[str]] = {}
        self.coffee_producing_countries:list[str] = []
        self.coffee_bean_types:dict[str,list[str]] = {}

        self.initialized = False
        self.hasfinished = False # used my file load
        self.app = self.aw.app
        self.alog_directory = Path("") # Pour stocker le chemin du répertoire ALog
        self.beancave_directory = Path("") # Nouvelle variable pour le répertoire de beancave.json
        self.is_directory_defined = False
        
        self.C0_COLOR: float = DEFAULT_C0
        self.C_BT_COLOR: float = DEFAULT_C_BT
        self.C_DTR_COLOR: float = DEFAULT_C_DTR
        self.C_WL_COLOR: float = DEFAULT_C_WL
        
        self.roaster_manager:RoasterManager | None = None
        # Charger le fichier JSON (ajustez le chemin selon votre structure)
       
        self.current_roaster_model = "" # Sera peuplé par load_settings
        self.probe_override:bool = False

        # process uuid and actual filename loaded in artisan to preposition cursors
        self.uuid_pattern = re.compile(r'uuid: \s*([a-fA-F0-9-]{36})')

        self.load_parameters()
        self.load_settings()
        
        self.cave: BeanCaveContainer | None = None
        self.load_green_beans()        

        # start the background task to collect alog information and avoid to read from multiple threads the same thing
        self._metadata_cache = AlogCacheCollection()
        self._cache_thread = None
        self._cache_worker = None

        # Create the 5-minute background refresh timer
        self.cache_refresh_timer = QTimer(self)
        self.cache_refresh_timer.setInterval(5 * 60 * 1000) # 5 minutes in milliseconds
        self.cache_refresh_timer.timeout.connect(self.trigger_cache_refresh)

        # Trigger once on initial startup/entry
        self.trigger_cache_refresh()
        self.cache_refresh_timer.start()
        
        self.last_sorted_column = -1
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.last_plot_data: dict|None = None 
        
        self.np: NiimbotBLE|None = None
        self.bleRoastSeeAGDevice: LebrewWaterActivityChecker|None = None
        self.bleTilauAmbientDevice = None  # ## TILAU ## BeanCave-managed ambient probe (BME280), same pattern as Lebrew

        self.deviceID: str = ""
        self.current_bean_name = "" 
        self.roast_plan_inputs: dict[str, QDoubleSpinBox] = {}
        self.status_label: QLabel|None = None
        self.input_group: QGroupBox|None = None
        self.generate_plan_btn: QPushButton|None = None
        self.injectinartisan_btn: QPushButton|None = None
        self.lastprofiledata:ProfileData
        self._alog_cache: dict[str, tuple[float, ProfileData]] = {}  # LRU cap = 5
        self._event_vlines: dict[str, object] = {}   # label → axvline artist
        self._event_annots: dict[str, object] = {}   # label → annotation artist
        self._event_dots:   dict[str, object] = {}   # label → bt dot artist
        self._event_et_dots:   dict[str, object] = {}  # label → et dot artist
        self._event_et_annots: dict[str, object] = {}  # label → et annotation artist
        self._pending_timeindex: list | None = None  # unsaved timeindex edits; None = no pending
        # ── Multi-curve comparison state ──────────────────────────────────────
        self._multi_mode: bool = False           # True dès que ≥2 courbes sélectionnées
        self._multi_curves: list[dict] = []      # [{filepath, data, deltabt, deltaet, color, title}]
        self._multi_load_queue: list[str] = []   # filepaths en attente de chargement
        self._multi_load_idx: int = 0            # index courant dans la queue
        self._multi_alog_thread: QThread | None = None   # thread courant multi
        self._multi_alog_worker: object | None  = None   # worker courant multi
        self._alog_uuid_index:      dict[str, list[str]] = {}  # uuid  → [filename, ...]
        self._alog_file_uuid:       dict[str, str]        = {}  # filename → uuid  (reverse)
        self.datatable = QTableWidget()
        self.datatable.setAlternatingRowColors(True)
        # Optional: Hide the vertical header (row numbers) for a cleaner look
        self.datatable.verticalHeader().setVisible(False)       
        
        self.createdatatable()
        self.apply_modern_theme()
        self.setup_ui()
    
        self.load_settings() #reload settings for deviations
        self._validate_startup_directories()

        #if a bean was given in parameter, search for uuid, then go to the green bean record and the roast itself as well in 3rd tab
        b = self._get_uuid_from_bean_description(uuid) # get uuid and validate that it is in the list

        self.is_directory_defined:bool = str(self.beancave_directory) != "" and str(self.alog_directory) != ""

        # Positioning on the green bean if a bean match was found for the provided uuid parameter
        self.populate_table()
        if b != "":
            # set current record of the datatable pointing to the matched bean's uuid
            for row in range(self.datatable.rowCount()):
                # Use the uuid field (column index 27) to find the match
                uuid_item = self.datatable.item(row, 27)
                if uuid_item and uuid_item.text() == b.uuid:
                    self.datatable.selectRow(row)
                    self.datatable.scrollToItem(uuid_item)
                    QTimer.singleShot(600, self._update_roast_plan_ui_state)
                    break

        # by default disable all buttons
        self.add_button.setEnabled(True)
        self.clear_button.setEnabled(False) 
        self.generate_label_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.inject_from_ai_button.setEnabled(False)
        self.update_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.generate_qr_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.generate_card_button.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.roast.setEnabled(False if self.cave is None or self.cave.green_beans is None or len(self.cave.green_beans) == 0 else True)
        self.remove_button.setEnabled(False)
        self.update_ui_visibility()
        if self.is_directory_defined:
            self.main_tab.setFocus()
        else:
            self.file_management_tab.setFocus()
        self.aw.beanCaveMenuAction.setChecked(True)

        self.oldPos = QPoint()   # null until first mouse press
        self.global_pos = QPoint(0, 0) # For tooltip positioning
        # macOS: explicit raise needed after Tool-window z-order shuffle
        if _IS_MACOS:
            self.raise_()
            self.activateWindow()
        self.initialized = True

        if self.aw:
            self.aw.installEventFilter(self)

        # Replace Artisan AlarmDlg with TilauScope editor
        def _tilau_alarmconfig(_: bool = False) -> None:
            from tilauscope.alarms import TilauAlarmDlg
            dlg = TilauAlarmDlg(self.aw, self.aw)
            dlg.show()
        self.aw.alarmconfig = _tilau_alarmconfig   # type: ignore[method-assign]

        QTimer.singleShot(0, self._start_ble_scanner)

        ## TILAU ## the read-only Records web server is now owned app-level by
        ## TilauWebHost (started with Artisan/TilauScope). BeanCave only supplies
        ## the roast/bean resolvers once its catalogue is loaded.
        self._web_records = None  # deprecated: kept for compatibility, unused
        QTimer.singleShot(0, self._register_web_resolvers)

        ## TILAU ## first-run configuration assistant (once, before what's-new)
        QTimer.singleShot(500, self._maybe_show_onboarding)

    def _maybe_show_onboarding(self) -> None:  ## TILAU ##
        try:
            from tilauscope.onboarding import maybe_show_onboarding
            self._onboarding_dlg = maybe_show_onboarding(self, self.aw)
        except Exception:  # pylint: disable=broad-except
            _logd.exception("onboarding assistant failed to start")

    def _find_item_by_metadata(self, list_widget: QListWidget, key: str, value: Any) :
        """
        Scans the QListWidget for an item containing a specific metadata key-value pair.
        """
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            metadata = item.data(Qt.ItemDataRole.UserRole)
            
            # Check if metadata exists, is a dictionary, and matches our criteria
            if isinstance(metadata, dict) and metadata.get(key) == value:
                return row
                
        return None


    @override
    def eventFilter(self, obj, event):
        if _IS_MACOS and obj == self.aw and event.type() == QEvent.Type.WindowActivate:
            active = QApplication.activeWindow()
            if active is None or active is self.aw:
                QTimer.singleShot(200, self._safe_raise)
        # Canvas right-click / two-finger tap: intercept before Qt default context menu
        if (obj is getattr(self, 'canvas', None)
                and event.type() == QEvent.Type.ContextMenu):
            if not self._multi_mode:
                self._build_marker_menu(event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos(),
                                        event.pos()       if hasattr(event, 'pos')       else None)
            return True  # always consume — prevent Qt's default empty menu
        return super().eventFilter(obj, event)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        """Re-raise BeancaveDlg when macOS moves focus to aw after a Tool window closes."""
        super().changeEvent(event)
        if _IS_MACOS and event.type() == QEvent.Type.WindowDeactivate:
            QTimer.singleShot(150, self._safe_raise)

    @staticmethod
    def _has_visible_child_dialog(roots, exclude=()) -> bool:
        """Return True if any visible QDialog (excluding self) is a descendant of any root."""
        root_set = set(roots)
        exclude_set = set(exclude)
        for widget in QApplication.topLevelWidgets():
            if widget in exclude_set:
                continue
            if not (isinstance(widget, QDialog) and widget.isVisible()):
                continue
            p = widget.parent()
            while p is not None:
                if p in root_set:
                    return True
                p = p.parent()
        return False

    def _safe_raise(self):
        """Bring BeancaveDlg to front only when no descendant dialog is open."""
        if not self.isVisible():
            return
        active = QApplication.activeWindow()
        # Exclude self: BeancaveDlg is itself a QDialog child of aw
        has_child = self._has_visible_child_dialog((self, self.aw), exclude=(self,))
        if active is not None and active is not self.aw and active is not self:
            return
        if has_child:
            QTimer.singleShot(150, self._safe_raise)
            return
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _is_descendant_of(widget, roots) -> bool:
        root_set = set(roots)
        p = widget.parent()
        while p is not None:
            if p in root_set:
                return True
            p = p.parent()
        return False

    def _start_ble_scanner(self) -> None:
        """
        Démarre le scanner BLE centralisé TilauBLEScanner.
        Remplace _BleInitWorker + _scan_and_connect_worker individuels.
        Un seul scan toutes les 8s distribué à tous les workers.
        """
        from artisanlib.ble_port import bluetooth_enabled
        if not bluetooth_enabled():
            _log.warning("Bluetooth non disponible — TilauBLEScanner non démarré")
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Bluetooth N/A"),
                THEME["SUBTEXT"]
            )
            self.print_label_button.setEnabled(False)
            return

        # Créer NiimbotBLE et brancher ses signaux.
        # Si un UUID est mémorisé dans les settings, on le passe directement
        # → TilauBLEScanner connectera par adresse sans scan par préfixe.
        self.np = NiimbotBLE(
            known_uuid=getattr(self.aw, "bleNiimbotDeviceName", None) or None
        )
        self.np.aw = self.aw  # référence pour auto-save UUID après connexion
        self.np.at_connected.connect(self.niimbot_connected)
        self.np.at_disconnected.connect(self.niimbot_disconnected)

        # Créer Lebrew si adresse connue
        if self.aw.bleRoastSeeAGDeviceName is not None and self.bleRoastSeeAGDevice is None:
            self.bleRoastSeeAGDevice = LebrewWaterActivityChecker(self.aw.bleRoastSeeAGDeviceName)
            self.bleRoastSeeAGDevice.connected_signal.connect(self.slotStartLebrewAG)
            self.bleRoastSeeAGDevice.disconnected_signal.connect(self.slotStopLebrewAG)
            self.bleRoastSeeAGDevice.wa_changed_signal.connect(self.on_read_water_activity)

        # ## TILAU ## Ambient probe (TilauAmbient / BME280) — same managed pattern
        # as Lebrew above. It connects by BLE address on construction, so it does
        # not need the centralised scanner (no on_devices_found).
        if self.aw.bleTilauScopeDeviceName not in (None, "", "none") and self.bleTilauAmbientDevice is None:
            try:
                from tilauscope.tilauambient import TilauAmbient
                self.bleTilauAmbientDevice = TilauAmbient(uuid=self.aw.bleTilauScopeDeviceName, aw=self.aw)
                self.bleTilauAmbientDevice.connected_signal.connect(self.slotStartTilauAmbient)
                self.bleTilauAmbientDevice.disconnected_signal.connect(self.slotStopTilauAmbient)
                _log.info("TilauAmbient probe registered (managed by BeanCave)")
            except Exception as exc:  # noqa: BLE001
                _log.warning("TilauAmbient probe init failed: %s", exc)

        # Démarrer le scanner centralisé
        self._ble_scanner = TilauBLEScanner(self)
        self._ble_scanner.devices_found.connect(self.np.on_devices_found)
        if self.bleRoastSeeAGDevice is not None and hasattr(self.bleRoastSeeAGDevice, "on_devices_found"):
            # LebrewWaterActivityChecker doit implémenter on_devices_found(list) pour
            # bénéficier du scanner centralisé. Si la méthode n'existe pas encore,
            # Lebrew continue à scanner de son côté (comportement legacy).
            self._ble_scanner.devices_found.connect(self.bleRoastSeeAGDevice.on_devices_found)
            _log.info("Lebrew branché sur TilauBLEScanner")
        elif self.bleRoastSeeAGDevice is not None:
            _log.info("Lebrew: on_devices_found absent — scan legacy actif")
        self._ble_scanner.start()
        _log.info("TilauBLEScanner started — Niimbot + Lebrew enregistrés")

    ## TILAU ## ------- record web resolvers (server owned by TilauWebHost) -------

    def _resolve_roast(self, roast_uuid: str):
        """roast_uuid -> .alog filepath (or None). Runs on the web server thread;
        reads only plain-python structures (metadata cache dataclasses)."""
        try:
            records = self._metadata_cache.records
            return next((m.filepath_str for m in records.values()
                         if m.roast_uuid.lower() == roast_uuid.lower()), None)
        except Exception:  # noqa: BLE001
            return None

    def _resolve_bean(self, uuid_str: str):
        """bean uuid -> plain dict of GreenBean fields (or None)."""
        try:
            uuidmap = getattr(self, 'uuidmap', None)
            bean = uuidmap.get(uuid_str) if uuidmap else None
            return bean.to_dict() if bean is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _resolve_sack(self, sack_id: str):
        """sack id -> uuid of the bean currently holding it (or None)."""
        try:
            return next((bean.uuid for bean in self.green_beans
                         if sack_id in (getattr(bean, "sacks", None) or [])), None)
        except Exception:  # noqa: BLE001
            return None

    def _register_web_resolvers(self) -> None:
        """Hand BeanCave's roast/bean/sack resolvers to the app-level web host so the
        read-only Records server can answer /roast, /bean and /sack. The server itself
        is started by TilauWebHost with Artisan/TilauScope, not here."""
        try:
            host = getattr(self.aw, 'tilau_web_host', None)
            if host is not None:
                host.set_records_resolvers(self._resolve_roast, self._resolve_bean, self._resolve_sack)
                _log.info("record web resolvers registered with TilauWebHost")
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _log.warning(f"record web resolvers not registered: {e}")

    def _snapshot_list_selection(self) -> None:
        """Record the roast currently highlighted + scroll position so a later
        list rebuild can restore the user's place. Guarded: an empty selection
        never clobbers a previously captured one (e.g. a transient state during
        the startup refresh, when the list is momentarily empty)."""
        try:
            cur_item = self.roast_list_widget.currentItem()
            cur_fname = (
                (cur_item.data(Qt.ItemDataRole.UserRole) or {}).get("raw_fname", "")
                if cur_item else ""
            )
            if cur_fname:
                self._pending_restore_fname = cur_fname
                self._pending_restore_scroll = self.roast_list_widget.verticalScrollBar().value()
        except (RuntimeError, AttributeError):
            pass

    def trigger_cache_refresh(self):
        """Dispatches a background thread execution to re-index the log files."""
        # ## TILAU ## Snapshot the user's selection NOW — at the moment the background
        # refresh is triggered — not later inside list_alog_files (which, at startup,
        # can read a transient empty selection and lose the loaded profile).
        self._snapshot_list_selection()

        # Skip if a previous indexing pass is still running (large/network alog dir):
        # avoids orphaned threads and concurrent writes to _metadata_cache.records.
        try:
            if getattr(self, '_indexer_thread', None) is not None and self._indexer_thread.isRunning():
                _logd.debug("cache refresh: previous indexer still running, skip.")
                return
        except RuntimeError:
            # C++ QThread object already deleted (deleteLater pending) — safe to recreate
            self._indexer_thread = None
            self._indexer_worker = None

        self._indexer_thread = QThread()
        self._indexer_worker = _AlogCacheIndexingWorker(Path(self.alog_directory), self._metadata_cache.records)
        self._indexer_worker.moveToThread(self._indexer_thread)
        
        self._indexer_thread.started.connect(self._indexer_worker.run)
        self._indexer_worker.finished.connect(self._on_cache_indexing_complete)
        self._indexer_worker.finished.connect(self._indexer_thread.quit)
        self._indexer_worker.finished.connect(self._indexer_worker.deleteLater)
        self._indexer_thread.finished.connect(self._indexer_thread.deleteLater)
        self._indexer_thread.start()
        
    def _on_cache_indexing_complete(self, updated_records: dict):
        """Callback when background index updates are fully synced."""
        self._metadata_cache.records = updated_records
        
        # Instantly rebuild lookups from memory without firing off another background thread
        self.update_alog_uuid_indexes()
    
        # Refresh GUI views smoothly
        if self.initialized:
            self.list_alog_files()
            
    def _cancel_threads(self) -> None:
        """Request stop + wait (briefly) for all background threads."""

        # Stop timers that trigger threads
        if hasattr(self, 'cache_refresh_timer'):
            self.cache_refresh_timer.stop()

        # --- Indexer (Cache load) ---
        if hasattr(self, '_indexer_thread') and self._indexer_thread is not None:
            # Disconnect result slot so signal doesn't fire into a half-dead widget.
            try:
                if self._indexer_thread.isRunning():
                    self._indexer_worker.finished.disconnect(self._on_cache_indexing_complete)
                    self._indexer_thread.requestInterruption()  # signal worker de s'arrêter
                    self._indexer_thread.quit()
                    if not self._indexer_thread.wait(2000):     # 2s — scan disque peut être lent
                        _log.warning("indexer thread did not stop — terminate()")
                        self._indexer_thread.terminate()
                        self._indexer_thread.wait()             # bloquant mais nécessaire après terminate
            except (TypeError, RuntimeError):
                pass
            self._indexer_thread = None
            self._indexer_worker = None

        # --- Roaster load ---
        if hasattr(self, '_roaster_thread') and self._roaster_thread is not None:
            # Disconnect result slot so signal doesn't fire into a half-dead widget.
            try:
                if self._roaster_thread.isRunning():
                    self._roaster_worker.finished.disconnect(self._on_roaster_loaded)
                    self._roaster_thread.quit()
                    self._roaster_thread.wait(500)
            except (TypeError, RuntimeError):
                pass
            self._roaster_thread = None
            self._roaster_worker = None

        # --- Alog list thread ---
        if hasattr(self, '_list_thread') and self._list_thread is not None:
            try:
                if self._list_thread.isRunning():
                    self._list_thread.quit()
                    self._list_thread.wait(300)
            except RuntimeError:
                pass  # Qt object already deleted by deleteLater
            self._list_thread = None

        # --- Plan roast files thread ---
        if hasattr(self, '_plan_roast_files_thread') and self._plan_roast_files_thread is not None:
            try:
                if self._plan_roast_files_thread.isRunning():
                    self._plan_roast_files_worker.finished.disconnect(self._on_plan_combo_alog_load)
                    self._plan_roast_files_thread.quit()
                    self._plan_roast_files_thread.wait(500)
            except (RuntimeError, TypeError):
                pass
            self._plan_roast_files_thread = None
            self._plan_roast_files_worker = None

        # --- TilauBLEScanner centralisé ---
        if hasattr(self, '_ble_scanner') and self._ble_scanner is not None:
            try:
                self._ble_scanner.stop()
            except Exception:
                pass
            self._ble_scanner = None

        # --- Debounce timer sélection ---
        if hasattr(self, '_selection_debounce') and self._selection_debounce is not None:
            self._selection_debounce.stop()

        # --- Alog load thread (mono) ---
        if hasattr(self, '_alog_thread') and self._alog_thread is not None:
            try:
                if self._alog_thread.isRunning():
                    self._alog_worker.finished.disconnect()
                    self._alog_worker.error.disconnect()
                    self._alog_thread.quit()
                    self._alog_thread.wait(500)
            except (TypeError, RuntimeError):
                pass
            self._alog_thread = None
            self._alog_worker = None

        # --- Alog load thread (multi) ---
        if hasattr(self, '_multi_alog_thread') and self._multi_alog_thread is not None:
            try:
                if self._multi_alog_thread.isRunning():
                    try:
                        self._multi_alog_worker.finished.disconnect()
                        self._multi_alog_worker.error.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    self._multi_alog_thread.quit()
                    if not self._multi_alog_thread.wait(1000):
                        _log.warning("multi alog thread did not stop — terminate()")
                        self._multi_alog_thread.terminate()
                        self._multi_alog_thread.wait()
            except RuntimeError:
                pass
            self._multi_alog_thread = None
            self._multi_alog_worker = None

        # --- AI thread — attendre la fin propre avant destruction ──────────
        if hasattr(self, 'ai_thread') and self.ai_thread is not None:
            try:
                if self.ai_thread.isRunning():
                    try:
                        self.ai_worker.finished.disconnect(self._on_bean_ai_finished)
                    except (TypeError, RuntimeError):
                        pass
                    self.ai_thread.quit()
                    if not self.ai_thread.wait(2000):   # 2s timeout
                        self.ai_thread.terminate()      # fallback hard-stop
                        self.ai_thread.wait(500)
            except (TypeError, RuntimeError):
                pass
            self.ai_thread = None
            self.ai_worker = None

        # --- Niimbot print thread ---
        if hasattr(self, 'niimbot_thread') and self.niimbot_thread is not None:
            try:
                if self.niimbot_thread.isRunning():
                    self.niimbot_thread.quit()
                    self.niimbot_thread.wait(500)
            except (RuntimeError, TypeError):
                pass
            self.niimbot_thread = None
            self.niimbot_worker = None

        # --- Niimbot heartbeat poll (timer + thread éphémère) ---
        # Stoppe le timer + déconnecte status_updated, puis joint un poll en vol
        # AVANT np.stop() (poll() fait du I/O BLE sous _ble_lock).
        self._stop_niimbot_poll()
        if hasattr(self, '_niimbot_poll_thread') and self._niimbot_poll_thread is not None:
            try:
                if self._niimbot_poll_thread.isRunning():
                    self._niimbot_poll_thread.quit()
                    self._niimbot_poll_thread.wait(1000)
            except (RuntimeError, TypeError):
                pass
            self._niimbot_poll_thread = None

    
    def update_alog_uuid_indexes(self) -> None:
        """
        Replaces the old _AlogIndexWorker by instantly assembling forward/reverse 
        UUID lookups directly out of the active metadata cache collection.
        """
        # Reset existing dictionary indexes
        self._alog_uuid_index = {}  # uuid -> [filename, ...]
        self._alog_file_uuid = {}   # filename -> uuid
        
        for path_str, meta in self._metadata_cache.records.items():
            fname = meta.filename
            uuid_val = meta.uuid
            
            if uuid_val:
                # Recreate the exact mapping layout expected downstream by your application
                self._alog_uuid_index.setdefault(uuid_val, []).append(fname)
                self._alog_file_uuid[fname] = uuid_val

    def _validate_startup_directories(self) -> None:
        """
        Called once at startup after settings are loaded.
        Checks both directories for existence and write access using existing helpers.
        If invalid, clears the bad path, saves settings, and redirects to the File tab.
        """
        problems = []

        # --- Check beancave directory ---
        if self.beancave_directory:
            bc_path = Path(self.beancave_directory)
            if not self._is_readable_directory(bc_path) or not os.access(str(bc_path), os.W_OK):
                problems.append(
                    QApplication.translate("tilauscope_beancave",
                        "Beancave directory is missing or not writable") +
                    f":\n{self.beancave_directory}"
                )
                self.beancave_directory = ""

        # --- Check alog directory ---
        if self.alog_directory:
            al_path = Path(self.alog_directory)
            if not self._is_readable_directory(al_path) or not os.access(str(al_path), os.W_OK):
                problems.append(
                    QApplication.translate("tilauscope_beancave",
                        "ALog directory is missing or not writable") +
                    f":\n{self.alog_directory}"
                )
                self.alog_directory = ""

        if not problems:
            return

        # Persist the cleared paths so stale values don't survive a restart
        self.save_settings()
        self.is_directory_defined = False

        msg = (
            QApplication.translate("tilauscope_beancave",
                "One or more directories configured at startup are no longer valid. "
                "Please select them again in the File Management tab.") +
            "\n\n" +
            "\n".join(problems)
        )
        # Defer the message so the window is fully visible before the dialog appears
        QTimer.singleShot(200, lambda: (
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Directory Error"),
                msg,
                QMessageBox.Icon.Warning
            ),
            self.tab_widget.setCurrentWidget(self.file_management_tab)
        ))
        
    def apply_modern_theme(self):
        # Ensure the central widget has a solid background
        if hasattr(self, 'centralwidget'):
            self.centralwidget.setAutoFillBackground(True)
            self.centralwidget.setObjectName("centralwidget")

        self.setStyleSheet(f"""
            /* 1. Base Window and Container */
            QMainWindow, QWidget#centralwidget, QDialog {{
                background-color: {THEME['BG']};
                color: {THEME['TEXT']};
            }}

            /* 2. Global Text Fix - Force labels to use the Theme Text color */
            QLabel, QCheckBox, QRadioButton, QGroupBox {{
                color: {THEME['TEXT']};
                background: transparent;
            }}

            /* 3. Tables (The core of BeanCave) */
            QTableView QTableCornerButton::section {{
            background-color: {THEME['SURFACE']};
            border: 1px solid {THEME['BORDER']};
            }}
            QTableWidget, QTableView {{
            background-color: {THEME['BG']};
            alternate-background-color: {THEME['SURFACE']}; /* Color for alternating rows */
            color: {THEME['TEXT']};
            gridline-color: {THEME['BORDER']};
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
            border: 1px solid {THEME['BORDER']};
            outline: none;
            }}

            /* 1. The Container of the Tabs */
            QTabWidget::pane {{
                border: 1px solid {THEME['BORDER']};
                background-color: {THEME['BG']};
                top: -1px; /* Overlap border with tab bar */
            }}

            /* 2. The Individual Tab buttons */
            QTabBar::tab {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                padding: 8px 15px;
                border: 1px solid {THEME['BORDER']};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }}

            /* 3. The Active (Selected) Tab */
            QTabBar::tab:selected {{
                background-color: {THEME['BG']}; /* Match the pane background */
                color: {THEME['ACCENT']};      /* Highlight text with accent color */
                border-bottom: 2px solid {THEME['ACCENT']};
                font-weight: bold;
            }}

            /* 4. Hover effect for unselected tabs */
            QTabBar::tab:!selected:hover {{
                background-color: {THEME['HOVER']};
                color: {THEME['BG']};
            }}

            /* 5. Handle Tab Widget background transparency */
            QTabWidget, QStackedWidget {{
                background: transparent;
            }}
                
            /* Header Text Fix */
            QHeaderView::section {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']}; 
                padding: 5px;
                border: 1px solid {THEME['BORDER']};
                font-weight: bold;
            }}

            /* 4. Inputs & Interactive Elements */
            QCheckBox, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background-color: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 4px;
                padding: 4px;
                combobox-popup: 0;
                color: {THEME['TEXT']}; /* Input text color */
                font-family: 'JetBrains Mono';
            }}

            QCheckBox:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {THEME['ACCENT']};  /* Thicker green border */
                padding: 3px;                         /* compensate +1px border so box size is constant (no layout shift) */
                background-color: {THEME['BG']};      /* Slightly darker background to pop */
                font-weight: bold;                    /* Make text bold while editing */
                color: white;                         /* Ensure high contrast */
            }}

            QCheckBox:disabled, QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
                background-color: {THEME['BG']};   /* Slightly darker than surface */
                color: #6272a4;                   /* A muted gray/blue color */
                border: 1px solid {THEME['SURFACE']}; /* Dim the border */           }}
            /* 5. Buttons */
            QPushButton {{
                background-color: #3b4252;
                border: 1px solid {THEME['BORDER']};
                border-radius: 4px;
                padding: 6px 15px;
                color: {THEME['TEXT']};
            }}

            QPushButton:hover {{
                background-color: {THEME['HOVER']};
                border: 1px solid {THEME['ACCENT']};
                color: {THEME['BG']};
            }}
            
            QPushButton:disabled {{
                background-color: {THEME['BG']};   /* Slightly darker than surface */
                color: #6272a4;                   /* A muted gray/blue color */
                border: 1px solid {THEME['SURFACE']}; /* Dim the border */
            }}

            /* ToolBar fix */
            QToolBar {{
                background: {THEME['SURFACE']};
                border-bottom: 1px solid {THEME['BORDER']};
                spacing: 10px;
            }}
            /* MODERN SCROLLBARS */
            QScrollBar:vertical {{
                border: none;
                background: {THEME['BG']};
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['BORDER']};
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {THEME['ACCENT']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
            border: none;
            background: {THEME['BG']};
            height: 12px;
            margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {THEME['BORDER']};
                min-width: 20px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {THEME['ACCENT']};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}

            /* 1. Standalone List Widgets (QListWidget) */
            QListWidget {{
                background-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 4px;
                color: {THEME['TEXT']};
                outline: none;
                padding: 5px;
            }}

            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
                color: {THEME['TEXT']};
            }}

            QListWidget::item:selected {{
                background-color: {THEME['ACCENT']};
                color: {THEME['BG']};
            }}

            QListWidget::item:hover {{
                background-color: {THEME['HOVER']};
                color: {THEME['BG']};
            }}

            QComboBox QAbstractItemView {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                selection-background-color: {THEME['ACCENT']};
                selection-color: {THEME['BG']};
                outline: none;
                /* FIX for macOS white margins */
                margin: 0px;
                padding: 0px;
            }}

            QComboBox QAbstractItemView::viewport {{
                background-color: {THEME['SURFACE']};
            }}

            QComboBox QAbstractItemView::item {{
                min-height: 30px;
                padding-left: 10px;
                background-color: {THEME['SURFACE']};
                }}

            QComboBox QAbstractItemView::item:selected {{
                background-color: {THEME['ACCENT']};
                color: {THEME['BG']};
            }}

            /* 3. ComboBox specific styling to ensure text is visible */
            QComboBox {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 4px;
                padding: 5px;
                padding-left: 10px;
            }}

            QComboBox QScrollBar:vertical {{
                background: {THEME['BG']};
                width: 12px;
                margin: 0px;
            }}

            QComboBox QScrollBar::handle:vertical {{
                background: {THEME['BORDER']};
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
            }}

            /* This removes the Windows-style 'Up' and 'Down' arrow buttons */
            QComboBox QScrollBar::add-line:vertical, 
            QComboBox QScrollBar::sub-line:vertical,
            QComboBox QScrollBar::add-page:vertical, 
            QComboBox QScrollBar::sub-page:vertical{{
                border: none;
                background: none;
                height: 0px;
                width: 0px;
            }}
             QToolTip {{
                background-color: #2D2F3F; /* Gris foncé pour le fond */
                color: white;              /* Texte blanc */
                border: 1px solid #585B70; /* Bordure discrète */
                padding: 5px;
                border-radius: 3px;
                font-size: 11px;
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = event.globalPosition().toPoint()
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = QPoint()   # reset — null QPoint signals "not dragging"

        from artisanlib.ble_port import bluetooth_enabled

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            new_pos = self.pos() + delta
            self.move(new_pos)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)
   
    def load_parameters(self) -> None :
        parameters_file = Path(__file__).parent / "beancave_beans.json"
        if not parameters_file.exists():
            _log.error(f"parameter file {parameters_file} not found")
            return 
        try:
            data = json.loads(parameters_file.read_text(encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8'))
            self.coffee_producing_countries  = data["country"]
            
            #cycle through varieties
            self.coffee_beans_species = data["varieties"]
            for specy in data["varieties"]:
                self.coffee_bean_types[specy] = data[specy]
                
            self.coffee_beans_categories = data["category"]
            for processing in data["category"]:
                self.coffee_processing_methods[processing] = data[processing]
        except Exception as e:
            _log.error(f"error loading parameter file : {e}")

         # --- roasters: kick off background load ---
        self.roaster_manager = RoasterManager()          # empty stub, safe to use immediately
        roaster_path = Path(__file__).parent / "roasters.json"
        self._start_roaster_load(roaster_path)

    def _launch_worker(self, worker, on_ok, on_err=None, *,
                        on_done=None, auto_delete=True) -> tuple:
        """Spin up a worker on a fresh QThread.

        Parameters
        ----------
        worker      : QObject with run(), finished, and optionally error signals.
        on_ok       : slot connected to worker.finished.
        on_err      : slot connected to worker.error (optional).
        on_done     : slot connected to thread.finished (optional).
        auto_delete : if True, call deleteLater on worker and thread when done.
                      Set False when _cancel_threads owns the lifetime.

        Returns (thread, worker) so callers can store refs if needed.
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_ok)
        if on_err is not None:
            worker.error.connect(on_err)
        worker.finished.connect(thread.quit)
        if on_err is not None:
            worker.error.connect(thread.quit)
        if auto_delete:
            worker.finished.connect(worker.deleteLater)
            if on_err is not None:
                worker.error.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
        if on_done is not None:
            thread.finished.connect(on_done)
        thread.start()
        return thread, worker

    def _start_roaster_load(self, roaster_path: Path) -> None:
        self._roaster_thread, self._roaster_worker = self._launch_worker(
            _RoasterLoadWorker(roaster_path),
            on_ok=self._on_roaster_loaded,
            on_err=lambda e: _log.error(f"Roaster load failed: {e}"),
            on_done=self._on_roaster_thread_done,
            auto_delete=False,  # _cancel_threads owns lifetime
        )

    @pyqtSlot(object)
    def _on_roaster_loaded(self, mgr: RoasterManager) -> None:
        self.roaster_manager = mgr
        # UI is already built at this point — just refresh the combo
        if hasattr(self, 'roaster_combo'):
            self._populate_roaster_list()
            _log.info(f"Roasters loaded: {len(mgr.roasters)} entries")

    @pyqtSlot()
    def _on_roaster_thread_done(self) -> None:
        """Clear refs after roaster thread stops normally so _cancel_threads
        won't try to touch an already-idle object."""
        self._roaster_thread = None
        self._roaster_worker = None

    # when_finished() removed: dead code (never connected); secured teardown
    # is now performed authoritatively in closeEvent.
               
    def setup_ui(self) -> None:
        self.main_window_layout = QVBoxLayout(self)
        self.main_window_layout.setContentsMargins(10, 10, 10, 10) # Margin for the border/shadow

        # This is the actual visible window body
        self.container = QFrame()
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet(f"""
            #MainContainer {{
                background-color: {THEME['BG']}; 
                border: 2px solid {THEME['BORDER']};
                border-radius: 15px;
            }}
        """)
        
        # All your existing UI content goes inside this layout
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(20, 10, 20, 20)
        self.main_window_layout.addWidget(self.container)

        size_grip = QSizeGrip(self.container)
        size_grip.setStyleSheet("width: 16px; height: 16px;")
        self.layout.addWidget(size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        # --- MODERN HEADER ---
        header = QHBoxLayout()
        header.setContentsMargins(5, 5, 5, 10)
        
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "BEANCAVE"))
        title_lbl.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 18px; font-weight: 800; font-family: 'JetBrains Mono'; border: none; background: transparent;")
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: #313244;
                color: #f38ba8;
                border-radius: 15px;
                border: 1px solid #f38ba8;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #f38ba8;
                color: #1e1e2e;
            }}
        """)

        header.addWidget(title_lbl)
        header.addStretch()
        ## TILAU ## QR scan entry point (spec wiki/QR-Scan-Spec.md §3.1) — the camera
        ## only runs while the scan dialog is open, hence a button, never always-on.
        self.scan_qr_btn = QPushButton("📷  SCAN")
        self.scan_qr_btn.setFixedHeight(30)
        self.scan_qr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_qr_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Scan a label QR code (roast or green bean)"))
        self.scan_qr_btn.clicked.connect(self.on_click_scan_qr)
        self.scan_qr_btn.setStyleSheet(f"""
            QPushButton {{
                background: #313244;
                color: {THEME['TEXT']};
                border-radius: 15px;
                border: 1px solid {THEME['BORDER']};
                padding: 0 14px;
                font-weight: 800;
                font-family: 'JetBrains Mono';
            }}
            QPushButton:hover {{ background: {THEME['ACCENT']}; color: #1e1e2e; }}
        """)
        header.addWidget(self.scan_qr_btn)
        ## TILAU ## headless home: BeanCave has no menu bar (the Artisan window that
        ## owns it is hidden), so give the home a direct way to open the roast view.
        ## tilauscopeCall() opens TilauScope and hides BeanCave (view-switch).
        if getattr(self.aw, '_tilau_headless', False):
            self.open_tilauscope_btn = QPushButton("▶  TilauScope")
            self.open_tilauscope_btn.setFixedHeight(30)
            self.open_tilauscope_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.open_tilauscope_btn.setToolTip(QApplication.translate(
                "tilauscope_beancave", "Open the roasting view"))
            self.open_tilauscope_btn.clicked.connect(lambda: self.aw.tilauscopeCall())
            self.open_tilauscope_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['ACCENT']};
                    color: #1e1e2e;
                    border-radius: 15px;
                    border: none;
                    padding: 0 14px;
                    font-weight: 800;
                    font-family: 'JetBrains Mono';
                }}
                QPushButton:hover {{ background: #b4befe; }}
                QPushButton:pressed {{ background: #74c7ec; }}
            """)
            header.addWidget(self.open_tilauscope_btn)
        header.addWidget(self.close_btn)
        self.layout.addLayout(header)

        self.tab_widget = QTabWidget()
        self.main_tab = QWidget()
        self.file_management_tab = QWidget()
        self.roast_viewer_tab = QWidget()
        self.roast_plan_tab = QWidget()
        self.storage_tab = QWidget()  ## TILAU ## conservation / water-activity dashboard
        self.status_label = QLabel()
        self.input_group = QGroupBox()

        self.tab_widget.addTab(self.main_tab, QApplication.translate("tilauscope_beancave","Green Beans"))
        self.tab_widget.addTab(self.roast_viewer_tab, QApplication.translate("tilauscope_beancave","Roast Viewer"))
        self.tab_widget.addTab(self.roast_plan_tab, QApplication.translate("tilauscope_beancave","Roasting plan"))
        self.tab_widget.addTab(self.file_management_tab, QApplication.translate("tilauscope_beancave","File Management")) # moved to the last position
        self.tab_widget.addTab(self.storage_tab, QApplication.translate("tilauscope_beancave","Stockage"))  ## TILAU ##
        # ## TILAU ## refresh the TilauAmbient probe button state on entering the plan tab
        self.tab_widget.currentChanged.connect(self._on_beancave_tab_changed)
        self.setup_main_tab_ui()
        self.setup_file_management_tab_ui()
        self.setup_roast_viewer_tab_ui()
        self.setup_roast_plan_tab_ui()
        self.setup_storage_tab_ui()  ## TILAU ##
        self.layout.addWidget(self.tab_widget)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        footer_layout.addWidget(QSizeGrip(self.container))
        self.layout.addLayout(footer_layout)

        settings = QSettings()
        geometry = settings.value('BeanCaveGeometry')
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(100, 100, 1200, 800)

        self.setMinimumSize(800, 500)

        ## TILAU ## A geometry saved on a larger/other monitor may not fit the
        ## current screen (smaller resolution, changed DPI, unplugged display).
        ## Without this, Qt clamps the window itself and spams the log with
        ## "QWindowsWindow::setGeometry: Unable to set geometry …" warnings.
        ## We pre-clamp so the dialog is always fully on-screen and no warning fires.
        self._clamp_geometry_to_screen()

        for combo in self.findChildren(QComboBox):
                combo.setView(QListView())
                combo.setItemDelegate(QStyledItemDelegate())

        for _cb in (
            self.country_combo,
            self.category_process_combo,
            self.process_combo,
            self.species_combo,
            self.varieties_combo,
            self.type_combo,
        ):
            self._install_hover_filter(_cb)

        self.restore_table_state()
        self.update_directory_labels()

    ## TILAU ##
    def _clamp_geometry_to_screen(self) -> None:
        """
        Shrink and reposition the window so it fits entirely within the current
        screen's available area. Prevents Qt "Unable to set geometry" warnings
        when a geometry saved on a bigger/other monitor is restored.
        """
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            frame = self.frameGeometry()

            # Clamp size to the available area (never below the minimum size).
            min_sz = self.minimumSize()
            new_w = max(min_sz.width(), min(frame.width(), avail.width()))
            new_h = max(min_sz.height(), min(frame.height(), avail.height()))
            if (new_w, new_h) != (frame.width(), frame.height()):
                self.resize(new_w, new_h)
                frame = self.frameGeometry()

            # Reposition so the whole frame stays inside the available area.
            new_x = min(max(frame.x(), avail.left()), avail.right() - frame.width())
            new_y = min(max(frame.y(), avail.top()), avail.bottom() - frame.height())
            if (new_x, new_y) != (frame.x(), frame.y()):
                self.move(new_x, new_y)
        except Exception:  # pylint: disable=broad-except
            _log.exception("clamp geometry to screen failed")

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
        profile_roast_humidity    = computed.get("ambient_humidity", 0.0)
        profile_roast_altitude    = self.aw.qmc.elevation
        profile_roast_weight      = computed.get("weightin",0.0)

        self.roast_plan_inputs["Ambient Temperature"].setValue(profile_roast_temperature)
        self.roast_plan_inputs["Ambient Humidity"].setValue(profile_roast_humidity)
        self.roast_plan_inputs["Atmospheric Pressure"].setValue(profile_roast_pressure)
        self.roast_plan_inputs["Altitude"].setValue(profile_roast_altitude)
        self.roast_plan_inputs["Batch Weight"].setValue(profile_roast_weight) 

    @pyqtSlot()
    def _check_plan_inputs(self):
        """Checks if all required double spin boxes have non-zero values."""
        self._update_plan_stepper()   # ## TILAU ## keep the header in sync
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
        
        data = {
            "Target Roast Level": target_roast.name,
            f"Ambient Temperature (°{self.aw.qmc.mode})": self.roast_plan_inputs.get("Ambient Temperature").value(), #type:ignore
            "Ambient Humidity (%)": self.roast_plan_inputs.get("Ambient Humidity").value(), #type:ignore
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
            precog, graph_data , crashes, flicks= roast_plan.generate_roast_plan(bean, target_roast,self.roast_plan_inputs.get("Ambient Temperature").value(), self.roast_plan_inputs.get("Ambient Humidity").value(),self.roast_plan_inputs.get("Batch Weight").value(),self.roast_plan_inputs.get("Altitude").value(), bt_deviation=bt_deviation) #type:ignore
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
                alarms = alarm_factory.generate()
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
                border: 1px solid {THEME.get('BORDER','#3f3f3f')};
                border-radius: 8px;
            }}
        """)
        sel_layout = QHBoxLayout(sel_frame)
        sel_layout.setContentsMargins(12, 8, 12, 8)
        sel_layout.setSpacing(16)

        # Bean selector
        bean_lbl = QLabel("🫘 " + QApplication.translate("tilauscope_beancave", "Green bean:"))
        bean_lbl.setStyleSheet(f"color:{THEME['TEXT']}; font-family:'JetBrains Mono'; font-size:12px;")
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
        roast_lbl.setStyleSheet(f"color:{THEME['TEXT']}; font-family:'JetBrains Mono'; font-size:12px;")
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

        # ## TILAU ## Centered fixed-max-width wizard column inside a vertical
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

        # ## TILAU ## Stepper-based roast plan layout (Bean → Conditions → Target).
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
            ("Ambient Humidity", "%", 0.0, 100.0, 1.0, 1, QApplication.translate("tilauscope_beancave","Relative humidity in the roasting area. Affects heat transfer.")),
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

        # ── flat wrapper card group (Conditions + Target) ─────────────────────────
        self.input_group.setTitle("")   #type:ignore
        self.input_group.setFlat(True)
        self.input_group.setStyleSheet("QGroupBox{border:none;margin:0;padding:0;}")
        params_layout = QVBoxLayout(self.input_group)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.setSpacing(14)

        _MUTED = "#6C7086"
        _MAUVE = "#CBA6F7"
        _CRUST = "#11111B"

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
                f"background:{bg};color:{fg};border-radius:10px;font-family:'JetBrains Mono';font-weight:700;font-size:11px;")
            ct = QLabel(title.upper())
            ct.setStyleSheet(
                f"font-family:'JetBrains Mono';font-size:11px;letter-spacing:1px;color:{_MUTED};background:transparent;border:none;")
            hdr.addWidget(badge); hdr.addWidget(ct); hdr.addStretch()
            if right:
                rl = QLabel(right)
                rl.setStyleSheet(
                    f"font-family:'JetBrains Mono';font-size:11px;color:{right_color or _MUTED};background:transparent;border:none;")
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
            ("Ambient Humidity",    QApplication.translate("tilauscope_beancave", "Humidity")),
            ("Atmospheric Pressure",QApplication.translate("tilauscope_beancave", "Pressure")),
            ("Altitude",            QApplication.translate("tilauscope_beancave", "Altitude")),
        ]
        for col, (key, short) in enumerate(_tile_defs):
            cap = QLabel(short.upper())
            cap.setStyleSheet(
                f"font-family:'JetBrains Mono';font-size:10px;letter-spacing:1px;color:{_MUTED};background:transparent;border:none;")
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
                font-family:'JetBrains Mono'; font-size:12px; padding:8px 18px; }}
            QPushButton:hover:enabled {{ background:rgba(250,179,135,0.28); }}
            QPushButton:disabled {{ background:{THEME['SURFACE']}; color:#6272a4; border:1px solid {THEME['BORDER']}; }}
        """)

        self.tilauambient_btn = QPushButton(
            "🌡  " + QApplication.translate("tilauscope_beancave", "TilauAmbient probe"))
        self.tilauambient_btn.setMinimumHeight(36)
        self.tilauambient_btn.setMaximumWidth(300)
        self.tilauambient_btn.clicked.connect(self._get_tilauambient_conditions)
        self.tilauambient_btn.setStyleSheet(f"""
            QPushButton {{ background:rgba(137,180,250,0.16); color:{THEME['TEXT']};
                border:1px solid {THEME['ACCENT']}; border-radius:8px;
                font-family:'JetBrains Mono'; font-size:12px; padding:8px 18px; }}
            QPushButton:hover:enabled {{ background:rgba(137,180,250,0.28); }}
            QPushButton:disabled {{ background:{THEME['SURFACE']}; color:#6272a4; border:1px solid {THEME['BORDER']}; }}
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
                f"font-family:'JetBrains Mono';font-size:12px;color:{THEME['SUBTEXT']};background:transparent;border:none;")
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
        bt_lbl.setStyleSheet(
            f"font-family:'JetBrains Mono';font-size:11px;letter-spacing:1px;color:{_MAUVE};background:transparent;border:none;")
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
                font-family:'JetBrains Mono'; font-size:12px; padding:11px 14px; text-align:left; }}
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
                font-family:'JetBrains Mono'; font-weight:700; font-size:14px; padding:11px 28px; }}
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
        """## TILAU ## Build the 3-step progress header (Bean → Conditions → Target)."""
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
        """## TILAU ## Style one stepper badge/text as done / current / wait."""
        badge = self._plan_step_badges[idx]
        txt = self._plan_step_texts[idx]
        crust, muted = "#11111B", "#6C7086"
        if state == "done":
            badge.setText("✓")
            badge.setStyleSheet(
                f"background:{THEME['SUCCESS']};color:{crust};border-radius:11px;"
                "font-family:'JetBrains Mono';font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-family:'JetBrains Mono';font-size:12px;color:{THEME['TEXT']};")
        elif state == "current":
            badge.setText(str(idx + 1))
            badge.setStyleSheet(
                f"background:{THEME['ACCENT']};color:{crust};border-radius:11px;"
                "font-family:'JetBrains Mono';font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-family:'JetBrains Mono';font-size:12px;color:{THEME['TEXT']};")
        else:  # wait
            badge.setText(str(idx + 1))
            badge.setStyleSheet(
                f"background:{THEME['BORDER']};color:{muted};border-radius:11px;"
                "font-family:'JetBrains Mono';font-weight:700;font-size:12px;")
            txt.setStyleSheet(f"font-family:'JetBrains Mono';font-size:12px;color:{THEME['SUBTEXT']};")

    @pyqtSlot()
    def _update_plan_stepper(self) -> None:
        """## TILAU ## Refresh stepper state from the current field values."""
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
                 and _val("Ambient Humidity") > 0
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
        """## TILAU ## Show/hide the probe-offset panel and update the caption."""
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

    @pyqtSlot(int)
    def setup_storage_tab_ui(self) -> None:
        """## TILAU ## Build the Stockage (conservation) tab in its own module."""
        from tilauscope.beancave_storage_tab import StorageTab
        layout = QVBoxLayout(self.storage_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        self.storage_tab_widget = StorageTab(self)
        layout.addWidget(self.storage_tab_widget)

    def _on_beancave_tab_changed(self, index: int) -> None:
        """## TILAU ## Keep the probe button state fresh when the plan tab opens."""
        if getattr(self, 'tab_widget', None) is None:
            return
        current = self.tab_widget.widget(index)
        if current is getattr(self, 'roast_plan_tab', None):
            self._refresh_tilauambient_btn()
        ## TILAU ## start/stop the Stockage tab's ambient polling with visibility
        st = getattr(self, 'storage_tab_widget', None)
        if st is not None:
            if current is getattr(self, 'storage_tab', None):
                st.on_shown()
            else:
                st.on_hidden()

    def _refresh_tilauambient_btn(self) -> None:
        """## TILAU ## Couple the two ambient sources to probe detection:
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
        """## TILAU ## Fill the ambient fields from the live TilauAmbient probe."""
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
        if "Ambient Humidity" in self.roast_plan_inputs:
            self.roast_plan_inputs["Ambient Humidity"].setValue(float(data.humidity))
        if "Atmospheric Pressure" in self.roast_plan_inputs:
            self.roast_plan_inputs["Atmospheric Pressure"].setValue(float(data.pressure))
        self._check_plan_inputs()

    @pyqtSlot()
    def _get_weather_conditions(self):
        """
        Gathers current location weather conditions and injects them into 
        the roast plan input fields. Works on Windows and Mac.
        """
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

            if "Ambient Humidity" in self.roast_plan_inputs and humidity is not None:
                self.roast_plan_inputs["Ambient Humidity"].setValue(float(humidity))

            if "Atmospheric Pressure" in self.roast_plan_inputs and pressure is not None:
                self.roast_plan_inputs["Atmospheric Pressure"].setValue(float(pressure))

            if "Altitude" in self.roast_plan_inputs and elevation is not None:
                self.roast_plan_inputs["Altitude"].setValue(float(elevation))

            _logd.debug(f"Weather updated for {city}: {temp_c}°C, {humidity}%, {pressure}hPa")

        except Exception as e:
            _logd.error(f"Weather Fetch Error: {e}")
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Weather Error"), QApplication.translate("tilauscope_beancave", "Failed to retrieve weather data: ")+f"{e}", QMessageBox.Icon.Warning)
    
    def setup_roast_viewer_tab_ui(self) -> None:
        self.roast_viewer_layout = QVBoxLayout()
        self.action_bar_layout = QHBoxLayout()
        self.action_bar_layout.setSpacing(5)

        # ── Helper SVG inline identique à l'onglet Green Beans ───────────────
        _F2  = "'JetBrains Mono', monospace"
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
            _ss_normal = f"""
                QPushButton {{
                    background-color : {THEME['SURFACE']};
                    color            : {THEME['TEXT']};
                    border           : 1px solid {THEME['BORDER']};
                    border-radius    : {_R2};
                    padding          : 5px 12px;
                    font-family      : {_F2};
                    font-size        : {_FS2};
                }}
                QPushButton:hover {{
                    background-color : {THEME['HOVER']};
                    color            : {THEME['BG']};
                    border-color     : {THEME['HOVER']};
                }}
                QPushButton:pressed {{
                    background-color : {THEME['ACCENT']};
                    color            : {THEME['BG']};
                }}
                QPushButton:disabled {{
                    color            : {THEME['SUBTEXT']};
                    border-color     : {THEME['BORDER']};
                }}
            """
            b.setStyleSheet(style_extra if style_extra else _ss_normal)
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
                background-color : rgba(137,180,250,40);
                color            : {THEME['ACCENT']};
                border           : 1px solid rgba(137,180,250,100);
                border-radius    : {_R2};
                padding          : 5px 12px;
                font-family      : {_F2};
                font-size        : {_FS2};
                font-weight      : bold;
            }}
            QPushButton:hover {{
                background-color : rgba(137,180,250,70);
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
                font-family      : {_F2};
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
            "M2 7h8M7 3l4 4-4 4M12 2v10", "Load in Artisan",
            stroke=THEME["ACCENT"], style_extra=_SS_ACCENT2
        )
        self.load_artisan_button_viewer.clicked.connect(self.load_roast_in_artisan)
        self.load_artisan_button_viewer.setToolTip(QApplication.translate("tilauscope_beancave","Load the selected ALog file into Artisan for detailed analysis."))
        self.load_artisan_button_viewer.setEnabled(False)

        self.load_artisan_background_button_viewer = _vbtn(
            "M3 4h8v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4zM5 4V3a2 2 0 0 1 4 0v1M10 7h2M10 9.5h2",
            "Background"
        )
        self.load_artisan_background_button_viewer.clicked.connect(self.load_roast_in_artisan_background)
        self.load_artisan_background_button_viewer.setToolTip(QApplication.translate("tilauscope_beancave","Load the selected ALog file into Artisan's background for comparison."))
        self.load_artisan_background_button_viewer.setEnabled(False)

        self.roast_finished_button = _vbtn(
            "M7 2c0 2-3 3-3 5.5a3 3 0 0 0 6 0C10 5 7 4 7 2zM5 11.5h4M7 9v3",
            "Roast finished!", stroke=THEME["SUCCESS"], style_extra=_SS_GREEN2
        )
        self.roast_finished_button.clicked.connect(self.on_roast_finished_clicked)
        self.roast_finished_button.setToolTip(QApplication.translate("tilauscope_beancave","Load the roast in Artisan and record results."))
        self.roast_finished_button.setEnabled(False)

        # ── Groupe 2 — Export & Print ─────────────────────────────────────────
        self.print_pdf_label_button = _vbtn(
            "M3 2h6l3 3v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM9 2v3h3M5 7h4M5 9.5h3",
            "PDF"
        )
        self.print_pdf_label_button.clicked.connect(self.generate_and_print_pdf_label)
        self.print_pdf_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate and print the label to PDF for the selected roast."))
        self.print_pdf_label_button.setEnabled(False)

        self.print_label_button = _vbtn(
            "M2 4h10v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4zM5 4V2h4v2M5 9h4",
            "B21S"
        )
        self.print_label_button.clicked.connect(self.generate_and_print_label)
        self.print_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate and print the label for the selected roast (requires Niimbot B21S)."))
        self.print_label_button.setEnabled(False)  # activé uniquement par niimbot_connected

        self.btn_snapshot = _vbtn(
            "M1 4h12v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4zM1 6h12M5 9.5h4",
            "Snapshot"
        )
        self.btn_snapshot.setToolTip(QApplication.translate("tilauscope_beancave","Take a PNG snapshot of the current curve."))
        self.btn_snapshot.setEnabled(False)

        ## TILAU ## Shareable roast card — 1200x630 JPEG for social posts.
        ## Distinct from Snapshot: that one dumps the raw curve, this one composes
        ## the bean identity, the roast level and the curve into one image.
        self.btn_roast_card = _vbtn(
            "M1 3.5h12v9H1zM4 7a1 1 0 1 0 0-.01M1.6 11.4L5 8.4l2.4 2.2L10 8l3 2.8",
            "Card")
        self.btn_roast_card.setToolTip(QApplication.translate("tilauscope_beancave","Export this roast as a shareable landscape image (JPEG), sized for social networks: green bean, roast level, key figures and the curve."))
        self.btn_roast_card.clicked.connect(self.on_export_roast_card)
        self.btn_roast_card.setEnabled(False)

        # ── Groupe 3 — Analyse & Outils ───────────────────────────────────────
        self.btn_roast_ready = _vbtn(
            "M2 2h4v4H2zM8 2h4v4H8zM2 8h4v4H2zM8 10h4M10 8v4",
            "Planning"
        )
        self.btn_roast_ready.setToolTip(QApplication.translate("tilauscope_beancave","Open the roast planning view to get roasting time repartition based on the selected roast profile."))
        self.btn_roast_ready.clicked.connect(self.show_roast_ready_view)
        self.btn_roast_ready.setEnabled(False)

        self.btn_dial_in = _vbtn(
            "M7 2a5 5 0 1 0 0 10A5 5 0 0 0 7 2zM7 4v3.5l2 1.2",
            "Dial-in"
        )
        self.btn_dial_in.setToolTip(QApplication.translate("tilauscope_beancave","Show espresso/filter extraction parameters based on roast color."))
        self.btn_dial_in.clicked.connect(self.show_barista_expert_view)
        self.btn_dial_in.setEnabled(False)

        self.btn_data_reader = _vbtn(
            "M2 2h10v12H2zM4 5h6M4 8h6M4 11h4",
            "Data"
        )
        self.btn_data_reader.setToolTip(QApplication.translate("tilauscope_beancave","Open a readable, navigable view of the recorded roast data (milestones, events, columns)."))
        self.btn_data_reader.clicked.connect(self.show_data_reader_view)
        self.btn_data_reader.setEnabled(False)

        self.refresh_button = _vbtn(
            "M2 7a5 5 0 1 0 1.2-3.2M2 3v4h4",
            "Refresh"
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
        self._multi_progress = QProgressBar()
        self._multi_progress.setTextVisible(True)
        self._multi_progress.setFixedHeight(16)
        self._multi_progress.setStyleSheet(
            "QProgressBar { border:1px solid #45475A; border-radius:4px; background:#1e1e2e; text-align:center; font-size:10px; color:#CDD6F4; }"
            "QProgressBar::chunk { background:#89B4FA; border-radius:3px; }"
        )
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
        _mode_btn_ss = """
            QPushButton {
                background-color : rgba(30, 30, 46, 160);
                border           : 1px solid rgba(255, 255, 255, 45);
                border-radius    : 8px;
            }
            QPushButton:hover  {
                background-color : rgba(60, 60, 90, 200);
                border           : 1px solid rgba(255, 255, 255, 90);
            }
            QPushButton:checked {
                background-color : rgba(89, 150, 246, 55);
                border           : 1px solid rgba(89, 150, 246, 180);
            }
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
            "<b>Consistency view</b><br>"
            "The reference roast as a solid line, with a shaded "
            "<b>min–max band</b> of all the selected roasts (bean temp &amp; RoR).<br>"
            "A <span style='color:#A6E3A1'>tight band</span> means your roasts are "
            "repeatable; a <span style='color:#F38BA8'>wide band</span> shows where "
            "they drift apart.",
            self._on_consistency_toggled)
        self.align_button = _make_mode_btn(
            _SVG_ALIGN,
            "<b>Aligned view (time-warp)</b><br>"
            "Stretches each roast in time so its milestones (CHARGE, TP, DRY END, "
            "FC start, DROP) line up with the reference.<br>"
            "Lets you compare the <b>shape of the bean-temperature rise within each "
            "phase</b>, regardless of how long that phase actually lasted.<br>"
            "<i>BT only — RoR is hidden because warping time distorts its scale.</i>",
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

    @pyqtSlot(bool)
    def _reconnect_hover(self) -> None:
        """Reconnecte le bon handler hover selon le mode courant (mono/multi)."""
        if hasattr(self, 'hover_cid'):
            try:
                self.canvas.mpl_disconnect(self.hover_cid)
            except Exception:
                pass
        handler = self._on_multi_hover if self._multi_mode else self.on_plot_hover
        self.hover_cid = self.canvas.mpl_connect('motion_notify_event', handler)

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
        self.annotation.set_fontsize(12 if checked else 7)
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
            _logd.error(f"Erreur lors de la lecture/parsing de {path.name}: {e}")
            return None
        
    @pyqtSlot()
    def list_alog_files(self) -> None:
        if not self.alog_directory:
            return
        directory = Path(self.alog_directory)
        if not directory.exists() or not directory.is_dir():
            self.roast_plot_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "The specified ALog directory does not exist or is not a directory."))
            return

        # ## TILAU ## Capture the current selection + scroll BEFORE clearing so a
        # background refresh can restore the user's position (clear() wipes both,
        # so reading currentItem() after the rebuild would always return None → row 0).
        # Guarded: keeps a good snapshot rather than overwriting it with an empty one
        # (the auto-refresh already snapshotted at trigger_cache_refresh time).
        self._snapshot_list_selection()

        # Clear immediately so the UI doesn't show stale data during the scan
        self.roast_list_widget.clear()

        # Offload glob + regex formatting to a background thread
        self._list_thread, self._list_worker = self._launch_worker(
            _AlogListWorker(directory, self._metadata_cache.records),
            on_ok=self._on_alog_list_ready,
            on_err=lambda e: _logd.error(f"list_alog_files: {e}"),
            on_done=self._on_list_thread_done,
        )

    @pyqtSlot()
    def _on_list_thread_done(self) -> None:
        self._list_thread = None
        self._list_worker = None

    @pyqtSlot(list)
    def _on_alog_list_ready(self, items: list) -> None:
        """Called on the main thread when the background file scan is done."""
        if not items:
            self.roast_list_widget.addItem(
                QApplication.translate("tilauscope_beancave",
                    "No alog files found in the directory."))
            return

        # Batch-populate using blockSignals so itemSelectionChanged doesn't
        # fire on every addItem, while keeping the widget's visual state intact.
        self.roast_list_widget.blockSignals(True)
        try:
            for raw_fname, display_name in items:
                item = QListWidgetItem(display_name)
                metadata ={"raw_fname": raw_fname}
                item.setData(Qt.ItemDataRole.UserRole, metadata)
                self.roast_list_widget.addItem(item)
        finally:
            self.roast_list_widget.blockSignals(False)

        if self.roast_list_widget.count() > 0:
            if not self.hasfinished:
                cur_file = Path(self.aw.curFile).name if self.aw.curFile else ""
                if cur_file =="":
                    index_file =-1
                else:
                    index_file = self._find_item_by_metadata(self.roast_list_widget, "raw_fname", cur_file)
                if index_file is not None and index_file >= 0:
                    self.roast_list_widget.setCurrentRow(index_file, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                else:
                    self.roast_list_widget.setCurrentRow(0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
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
                    target_row = 0
                self.roast_list_widget.blockSignals(True)
                self.roast_list_widget.setCurrentRow(target_row, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.roast_list_widget.blockSignals(False)
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
        self._selection_debounce.start()  # .start() repart de zéro si déjà en cours



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

            m = self.roast_list_widget.currentItem()
            metadata = m.data(Qt.ItemDataRole.UserRole)
            filepath = Path(self.alog_directory) / metadata["raw_fname"]
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
        """Cancel any in-flight load thread (mono or multi)."""
        # Chemin mono
        if hasattr(self, '_alog_thread') and self._alog_thread is not None:
            try:
                if self._alog_thread.isRunning():
                    try:
                        self._alog_worker.finished.disconnect()
                        self._alog_worker.error.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    self._alog_thread.quit()
                    self._alog_thread.wait(300)
            except RuntimeError:
                # C++ object already deleted by deleteLater
                pass
            self._alog_thread = None
            self._alog_worker = None
        # Chemin multi
        if hasattr(self, '_multi_alog_thread') and self._multi_alog_thread is not None:
            try:
                if self._multi_alog_thread.isRunning():
                    try:
                        self._multi_alog_worker.finished.disconnect()
                        self._multi_alog_worker.error.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    self._multi_alog_thread.quit()
                    self._multi_alog_thread.wait(300)
            except RuntimeError:
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
            worker.finished.connect(worker.deleteLater)
            worker.error.connect(worker.deleteLater)
            # Stocker les refs Python AVANT de connecter deleteLater
            self._multi_alog_thread = thread
            self._multi_alog_worker = worker
            # null-ifie la ref Python EN PREMIER, puis deleteLater détruit le C++
            thread.finished.connect(self._on_multi_alog_thread_done)
            thread.finished.connect(thread.deleteLater)
        else:
            # Chemin mono — comportement original
            worker.finished.connect(self._on_alog_thread_done)
            worker.finished.connect(thread.quit)
            worker.error.connect(thread.quit)
            thread.finished.connect(thread.deleteLater)
            self._alog_thread = thread
            self._alog_worker = worker
        thread.start()

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

    # Teintes catégorielles distinctes — une par roast en comparaison (Catppuccin).
    # Le roast est identifié par la couleur ; le type de donnée par le style de
    # trait (BT plein, RoR tireté, ET pointillé fin).
    _MULTI_HUES: tuple = (
        "#89B4FA",  # Blue
        "#FAB387",  # Peach
        "#A6E3A1",  # Green
        "#CBA6F7",  # Mauve
        "#F9E2AF",  # Yellow
        "#94E2D5",  # Teal
        "#F38BA8",  # Red
        "#F5C2E7",  # Pink
    )

    def _make_multi_palette(self, n: int) -> list[tuple[str, str, str, str]]:
        """Génère n quadruplets (bt, et, dbt, ror) — une teinte distincte par roast.

        Les quatre composantes partagent la même teinte : la distinction BT / ET /
        RoR se fait par le style de trait au tracé, pas par la couleur. Au-delà de
        8 roasts, les teintes sont recyclées.
        """
        result = []
        for i in range(n):
            hue = self._MULTI_HUES[i % len(self._MULTI_HUES)]
            result.append((hue, hue, hue, hue))
        return result

    # Jalons HiBean affichés en multi-comparaison (ordre d'affichage)
    _MULTI_MILESTONES: tuple = ('CHARGE', 'TP', 'DRY END', 'FC start', 'DROP')

    def _multi_milestones(self, data: dict) -> dict:
        """Renvoie {label: (x_min, bt_temp, t_sec)} pour CHARGE/TP/DRY END/FC start/DROP.

        x_min/t_sec sont relatifs au CHARGE. TP est recalculé (min BT entre CHARGE
        et DRY END) car Artisan ne le stocke pas dans timeindex.
        """
        if not data:
            return {}
        timex = data.get('timex', [])
        temp2 = data.get('temp2', [])
        ti = (list(data.get('timeindex', [])) + [-1] * 8)[:8]
        charge = ti[RoastingPhase.CHARGE]
        if charge < 0 or charge >= len(timex):
            return {}
        charge_t = timex[charge]
        out: dict = {}

        def _put(label: str, idx: int) -> None:
            if idx is None or idx <= 0 or idx >= len(timex) or idx >= len(temp2):
                return
            if temp2[idx] is None:
                return
            t = timex[idx] - charge_t
            out[label] = (t / 60.0, temp2[idx], t)

        # CHARGE — l'index peut légitimement valoir 0
        if charge < len(temp2) and temp2[charge] is not None:
            out['CHARGE'] = (0.0, temp2[charge], 0.0)
        # TP : minimum de BT entre CHARGE et DRY END (fenêtre 2 min par défaut)
        dryend = ti[RoastingPhase.DRYEND]
        tp_hi = dryend if dryend > charge else min(len(temp2), charge + 120)
        seg = [(k, temp2[k]) for k in range(charge, tp_hi)
               if k < len(temp2) and temp2[k] is not None]
        if seg:
            tp_idx = min(seg, key=lambda kv: kv[1])[0]
            t = timex[tp_idx] - charge_t
            out['TP'] = (t / 60.0, temp2[tp_idx], t)
        _put('DRY END', dryend)
        _put('FC start', ti[RoastingPhase.FCSTART])
        _put('DROP', ti[RoastingPhase.DROP])
        return out

    def _draw_multi_event_markers(self, ax1, palette: list, mode: str) -> None:
        """Bandeau de jalons : lignes-guides + boîtes en haut sur la roast de
        référence (curve[0]). À 3+ roasts : LABEL / temp / temps uniquement (épuré).
        À exactement 2 roasts : on ajoute les Δt/ΔT vs la courbe comparée, là où
        c'est lisible — l'info delta reste ainsi près de la courbe."""
        ref_data = self._multi_curves[0].get('data')
        ref_ms = self._multi_milestones(ref_data)
        if not ref_ms:
            return
        n = len(self._multi_curves)
        # À 2 roasts : jalons de la courbe comparée pour calculer les écarts.
        other_ms = self._multi_milestones(self._multi_curves[1].get('data')) if n == 2 else {}
        ref_col = palette[0][0]
        bbox_style = dict(boxstyle="round,pad=0.3", fc="black", alpha=0.82,
                          ec=ref_col, lw=0.8)
        drop_x = ref_ms.get('DROP', (0.0,))[0] or 1.0
        # Boîtes ancrées juste au-dessus de leur point sur la courbe (offset en
        # points) : elles suivent la courbe quel que soit le zoom, reliées par la
        # ligne-guide. Quinconce vertical pour éviter le chevauchement des jalons
        # proches (FC start / DROP) ; décalage horizontal selon le côté.
        dy_rows = (62, 24)
        for k, label in enumerate(self._MULTI_MILESTONES):
            if label not in ref_ms:
                continue
            x_min, bt, t_sec = ref_ms[label]
            ax1.axvline(x=x_min, color='gray', linestyle=':', linewidth=0.7, alpha=0.45, zorder=2)
            ax1.plot(x_min, bt, marker='o', color=ref_col, markersize=4, zorder=8)
            lines = [label, f"{bt:.1f}°{mode}", self.format_seconds(t_sec)]
            if n == 2 and label in other_ms:
                _, obt, ot_sec = other_ms[label]
                lines.append(f"Δt {t_sec - ot_sec:+.0f}s")   # réf − comparée
                lines.append(f"ΔT {bt - obt:+.1f}°")
            right = x_min >= 0.78 * drop_x
            ha = 'right' if right else 'left'
            dx = -6 if right else 6
            ax1.annotate("\n".join(lines), (x_min, bt),
                         textcoords="offset points", xytext=(dx, dy_rows[k % 2]),
                         ha=ha, va='bottom', fontsize=_FS_EVENT, color='white',
                         bbox=bbox_style, zorder=9)

    # Couleurs de phase désaturées (frais → chaud), indépendantes des teintes roast
    _PHASE_COLORS: tuple = ("#6E94C2", "#C79356", "#B06E7E")  # Drying / Maillard / Dev

    def _draw_phase_ribbon(self, ax, palette: list) -> None:
        """Ruban d'équilibre des phases : une barre horizontale empilée par roast
        (Séchage / Maillard / Développement en %), nom du roast coloré + durée à
        gauche. Le % de développement EST le DTR."""
        bg_color = _PLOT_PALETTE["background"]
        ax.set_facecolor(bg_color)
        rows = [(i, c, self._extract_roast_metrics(c['data']))
                for i, c in enumerate(self._multi_curves) if c.get('data')]
        if not rows:
            ax.axis('off')
            return
        nrows = len(rows)
        labels, label_colors = [], []
        dry_c, mai_c, dev_c = self._PHASE_COLORS
        for row_idx, (i, curve, m) in enumerate(rows):
            y = nrows - 1 - row_idx  # première courbe (référence) en haut
            dry = m.get('drying_pct') or 0.0
            mai = m.get('maillard_pct') or 0.0
            dev = m.get('dtr') or 0.0
            s = dry + mai + dev
            if s > 0:
                dry, mai, dev = dry * 100 / s, mai * 100 / s, dev * 100 / s
            for val, left, lab, col in (
                (dry, 0.0, QApplication.translate("tilauscope_beancave", "Drying"), dry_c),
                (mai, dry, QApplication.translate("tilauscope_beancave", "Maillard"), mai_c),
                (dev, dry + mai, QApplication.translate("tilauscope_beancave", "Dev"), dev_c),
            ):
                ax.barh(y, val, left=left, height=0.55, color=col,
                        edgecolor=bg_color, linewidth=1.2, alpha=0.92)
                if val >= 11:
                    ax.text(left + val / 2, y, f"{lab} {val:.0f}%", ha='center', va='center',
                            fontsize=_FS_TICK - 1, color='#1E1E2E')
            short = (curve['title'][:16] + '…') if len(curve['title']) > 16 else curve['title']
            labels.append(f"{short} · {m.get('total_fmt', '')}")
            label_colors.append(palette[i][0])
        ax.set_xlim(0, 100)
        ax.set_ylim(-0.6, nrows - 0.4)
        ax.set_yticks(range(nrows))
        # y-ticks dans l'ordre d'affichage (haut → bas) : on inverse les labels
        ax.set_yticklabels(list(reversed(labels)), fontsize=_FS_TICK)
        for tick, col in zip(ax.get_yticklabels(), reversed(label_colors)):
            tick.set_color(col)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.tick_params(axis='x', colors=_PLOT_PALETTE['xlabel'], labelsize=_FS_TICK - 1)
        ax.tick_params(axis='y', length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)

    def _draw_residual_strip(self, ax, mode: str) -> None:
        """Bandeau résiduel : écart de BT de chaque roast à la référence (ΔBT),
        centré sur 0. Interpolé sur la grille x de la référence (temps brut, ou
        temps warpé en vue Aligné → écart de forme pur). Partage l'axe x du graphe."""
        bg_color = _PLOT_PALETTE["background"]
        ax.set_facecolor(bg_color)
        if len(self._multi_series) < 2:
            ax.axis('off')
            return
        ref = self._multi_series[0]
        ref_x = numpy.asarray(ref['x'], dtype=float)
        ref_bt = numpy.asarray([v if v is not None else numpy.nan for v in ref['bt']], dtype=float)
        if ref_x.size < 2:
            ax.axis('off')
            return
        ax.axhline(0, color=ref['bt_col'], linewidth=1.3, alpha=0.9, zorder=3)  # référence
        max_abs = 5.0
        for s in self._multi_series[1:]:
            ox = numpy.asarray(s['x'], dtype=float)
            oy = numpy.asarray([v if v is not None else numpy.nan for v in s['bt']], dtype=float)
            valid = ~numpy.isnan(oy)
            if valid.sum() < 2:
                continue
            yi = numpy.interp(ref_x, ox[valid], oy[valid], left=numpy.nan, right=numpy.nan)
            resid = yi - ref_bt
            ax.plot(ref_x, resid, color=s['bt_col'], linewidth=1.0, alpha=0.85, zorder=4)
            finite = resid[~numpy.isnan(resid)]
            if finite.size:
                max_abs = max(max_abs, float(numpy.nanmax(numpy.abs(finite))))
        lim = numpy.ceil(max_abs / 5.0) * 5.0
        ax.set_ylim(-lim, lim)
        from matplotlib.colors import to_hex, to_rgba
        ylab = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 0.75), keep_alpha=True)
        ax.set_ylabel("Δ" + QApplication.translate("Label", "BT") + f" (°{mode})",
                      fontsize=_FS_TICK, color=ylab)
        ax.tick_params(axis='both', colors=ylab, labelsize=_FS_TICK - 1)
        ax.grid(True, alpha=0.2, color=_PLOT_PALETTE['grid'])
        for sp in ax.spines.values():
            sp.set_color(_PLOT_PALETTE['grid'])
        ax.set_xlabel(QApplication.translate("tilauscope_beancave", "Time (min)"),
                      fontsize=_FS_AXIS, color=_PLOT_PALETTE['xlabel'])

    @pyqtSlot(bool)
    def _on_consistency_toggled(self, checked: bool) -> None:
        """Active la vue Consistance (exclusive avec Aligné) et redessine."""
        if checked:
            self.align_button.blockSignals(True)
            self.align_button.setChecked(False)
            self.align_button.blockSignals(False)
            self._multi_view_mode = 'consistency'
        else:
            self._multi_view_mode = 'align' if self.align_button.isChecked() else 'overlay'
        if self._multi_curves:
            self._plot_multi_curves()

    @pyqtSlot(bool)
    def _on_align_toggled(self, checked: bool) -> None:
        """Active la vue Aligné / time-warp (exclusive avec Consistance) et redessine."""
        if checked:
            self.consistency_button.blockSignals(True)
            self.consistency_button.setChecked(False)
            self.consistency_button.blockSignals(False)
            self._multi_view_mode = 'align'
        else:
            self._multi_view_mode = 'consistency' if self.consistency_button.isChecked() else 'overlay'
        if self._multi_curves:
            self._plot_multi_curves()

    def _plot_multi_curves(self) -> None:
        """Trace la superposition de BT, ET et DeltaBT pour toutes les courbes multi."""
        if not self._multi_curves:
            return

        n = len(self._multi_curves)
        palette = self._make_multi_palette(n)

        bg_color = _PLOT_PALETTE["background"]
        mode = self._multi_curves[0]['data'].get('mode', 'C') if self._multi_curves[0]['data'] else 'C'

        from matplotlib.colors import to_hex, to_rgba
        ylabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 0.75), keep_alpha=True)

        self.fig.clear()
        # Deux lignes empilées : graphe principal (BT/ET/RoR) + ruban de phases.
        # Hauteur du ruban proportionnelle au nombre de roasts (sinon les barres
        # s'écrasent et mordent la légende dès 4-5 courbes).
        n_data = sum(1 for c in self._multi_curves if c.get('data')) or 1
        ribbon_h = 0.55 + 0.45 * n_data
        # 4 lignes : graphe / résiduel ΔBT / ruban / bande-légende. Le résiduel
        # partage l'axe x du graphe (l'axe temps vit donc sur le résiduel). La
        # légende a sa propre cellule réservée → pas de chevauchement.
        gs = self.fig.add_gridspec(4, 1, height_ratios=[7.0, 1.5, ribbon_h, 0.5], hspace=0.14)
        ax1 = self.fig.add_subplot(gs[0])
        ax_resid = self.fig.add_subplot(gs[1], sharex=ax1)
        ax_ribbon = self.fig.add_subplot(gs[2])
        ax_legend = self.fig.add_subplot(gs[3])
        ax_legend.axis('off')
        ax_ror = ax1.twinx()
        self.ax1 = ax1
        self.ax2 = None        # pas de slider panel en mode multi
        self.ax_hoovers = ax_ror

        self.fig.set_facecolor(bg_color)
        ax1.set_facecolor(bg_color)
        ax_ror.set_facecolor(bg_color)
        for spine in ax1.spines.values():
            spine.set_color(_PLOT_PALETTE['grid'])
        ax1.tick_params(axis='both', colors=ylabel_alpha_color, labelsize=_FS_TICK)
        ax_ror.tick_params(axis='y',  colors=ylabel_alpha_color, labelsize=_FS_TICK)

        # Modes de vue (n >= 2). consistency : réf + bande min–max. align : time-warp
        # (jalons alignés sur ceux de la référence, BT seul).
        view = getattr(self, '_multi_view_mode', 'overlay')
        consistency = (view == 'consistency' and n >= 2)
        align = (view == 'align' and n >= 2)
        # Jalons de la référence (1ʳᵉ courbe avec données) pour le time-warp.
        ref_warp_ms = {}
        if align:
            for c in self._multi_curves:
                if c.get('data'):
                    ref_warp_ms = self._multi_milestones(c['data'])
                    break

        # Stocker les séries pour hover
        self._multi_series: list[dict] = []

        for i, curve in enumerate(self._multi_curves):
            data = curve['data']
            if not data:
                continue
            bt_col, et_col, dbt_col, ror_col = palette[i]
            timex     = data.get('timex', [])
            temp2     = data.get('temp2', [])
            temp1     = data.get('temp1', [])
            timeindex = data.get('timeindex', [])
            deltabt   = curve['deltabt'] or []

            if not timex or not temp2 or len(timeindex) < 7:
                continue

            charge = timeindex[0]
            drop   = timeindex[6]
            if charge < 0:
                continue
            charge_start = max(0, charge - 10)
            drop_end     = min(len(timex), drop + 10) if drop > 0 else len(timex)

            x_vals = [(t - timex[charge]) / 60.0 for t in timex[charge_start:drop_end]]
            y_bt   = temp2[charge_start:drop_end]
            y_et   = temp1[charge_start:drop_end] if temp1 else []
            y_ror  = [v if v is not None else 0.0 for v in deltabt[charge_start:drop_end]] if deltabt else []

            # Time-warp : remappe le temps de ce roast pour aligner ses jalons sur
            # ceux de la référence (interp linéaire par morceaux). Identité pour la réf.
            plot_x = x_vals
            if align and ref_warp_ms:
                this_ms = self._multi_milestones(data)
                shared = [l for l in self._MULTI_MILESTONES if l in this_ms and l in ref_warp_ms]
                if len(shared) >= 2:
                    xp = [this_ms[l][2] for l in shared]       # temps jalons de ce roast (s)
                    fp = [ref_warp_ms[l][2] for l in shared]   # temps jalons de la référence (s)
                    t_sec = [(t - timex[charge]) for t in timex[charge_start:drop_end]]
                    plot_x = list(numpy.interp(t_sec, xp, fp) / 60.0)

            is_ref = (i == 0)
            if align:
                # Vue alignée : BT seul (le warp fausse l'échelle du RoR).
                ax1.plot(plot_x, y_bt, color=bt_col, zorder=6 if is_ref else 4,
                         linewidth=1.5 if is_ref else 1.0, alpha=1.0 if is_ref else 0.5)
            elif not consistency or is_ref:
                # Type encodé par le style : BT plein, RoR tireté, ET pointillé fin.
                # Réf pleine et un peu plus épaisse ; autres atténués.
                bt_lw     = 1.5 if is_ref else 1.0
                bt_alpha  = 1.0 if is_ref else 0.45
                ror_alpha = 0.85 if is_ref else 0.40
                et_alpha  = 0.45 if is_ref else 0.22
                ax1.plot(x_vals, y_bt, color=bt_col, linewidth=bt_lw, alpha=bt_alpha,
                         zorder=6 if is_ref else 4)
                if y_et:
                    ax1.plot(x_vals, y_et, color=et_col, linewidth=0.8, linestyle=':', alpha=et_alpha)
                if y_ror:
                    ax_ror.plot(x_vals, y_ror, color=ror_col, linewidth=1.0, linestyle='--', alpha=ror_alpha)

            self._multi_series.append({
                'title':    curve['title'],
                'x':        plot_x,
                'bt':       y_bt,
                'et':       y_et,
                'ror':      y_ror,
                'bt_col':   bt_col,
                'et_col':   et_col,
                'dbt_col':  dbt_col,
                'ror_col':  ror_col,
                'timex':    timex,
                'timeindex': timeindex,
                'mode':     mode,
            })

        # ── Bande de consistance : enveloppe min–max sur TOUS les roasts ──────
        # (référence incluse) interpolés sur la grille temps de la référence —
        # sinon, à 2 roasts, min==max et la bande serait invisible. Tracée pour
        # BT (ax1) et RoR (ax_ror), en teinte réf, faible alpha.
        if consistency and len(self._multi_series) >= 2:
            ref_s = self._multi_series[0]
            ref_x = numpy.asarray(ref_s['x'], dtype=float)
            band_col = ref_s['bt_col']

            def _draw_band(key: str, axis) -> None:
                stack = []
                for s in self._multi_series:  # inclut la référence → enveloppe complète
                    ox = numpy.asarray(s['x'], dtype=float)
                    oy = numpy.asarray([v if v is not None else numpy.nan
                                        for v in (s.get(key) or [])], dtype=float)
                    valid = ~numpy.isnan(oy)
                    if valid.sum() < 2:
                        continue
                    stack.append(numpy.interp(ref_x, ox[valid], oy[valid],
                                              left=numpy.nan, right=numpy.nan))
                if not stack:
                    return
                arr = numpy.vstack(stack)
                lo, hi = numpy.nanmin(arr, axis=0), numpy.nanmax(arr, axis=0)
                m = ~(numpy.isnan(lo) | numpy.isnan(hi))
                axis.fill_between(ref_x[m], lo[m], hi[m], color=band_col,
                                  alpha=0.16, linewidth=0, zorder=2)

            if ref_x.size:
                _draw_band('bt', ax1)
                _draw_band('ror', ax_ror)

        ax1.set_facecolor(bg_color)
        # Échelle Y adaptative sur l'ensemble des courbes (BT + ET), ~10–20° d'air
        # au-dessus du pic le plus chaud. Fallback 0–300 si aucune donnée.
        all_temps = [
            v for s in self._multi_series
            for v in ((s['bt'] or []) + (s['et'] or []))
            if v is not None
        ]
        if all_temps:
            t_min = min(all_temps)
            t_max = max(all_temps)
            y_lo = max(0, int(numpy.floor((t_min - 10) / 10.0) * 10))
            # Headroom plus large qu'en mono : laisse la place aux boîtes
            # d'événement ancrées en haut de l'axe (lignes-guides HiBean).
            # À 2 roasts les boîtes portent les Δt/ΔT (5 lignes) → un peu plus d'air.
            head = 30 if len(self._multi_curves) == 2 else 18
            y_hi = int(numpy.ceil((t_max + head) / 10.0) * 10)
            ax1.set_ylim(y_lo, y_hi)
        else:
            ax1.set_ylim(0, 300)
        ax1.set_ylabel(QApplication.translate("Label", "Temp") + f" (°{mode})",
                       fontsize=_FS_AXIS, color=_PLOT_PALETTE['ylabel'])
        # L'axe temps vit sur le résiduel (sous le graphe) → on masque celui d'ax1.
        ax1.tick_params(axis='x', labelbottom=False)
        ax1.grid(True, alpha=0.25, color=_PLOT_PALETTE['grid'])
        # Échelle RoR : axe strictement positif — plancher fixe à 0.
        # Les valeurs négatives restent dans les données (hover tooltip) mais
        # ne font jamais descendre l'axe en dessous de 0.
        if align:
            # Vue alignée : pas de RoR tracé → on masque l'axe de droite (vide).
            ax_ror.set_yticks([])
            ax_ror.set_ylabel('')
        else:
            all_ror = [v for s in self._multi_series for v in (s['ror'] or []) if v is not None]
            if all_ror:
                ror_max = max(max(all_ror), 30)
                ax_ror.set_ylim(0, ror_max + 2)
            else:
                ax_ror.set_ylim(0, 30)
            ax_ror.set_ylabel(QApplication.translate("Label", "RoR") + f" (°{mode}/min)",
                              fontsize=_FS_AXIS, color=ylabel_alpha_color)

        # ── Marqueurs d'événement façon HiBean (lignes-guides + boîtes + Δ) ──
        try:
            self._draw_multi_event_markers(ax1, palette, mode)
        except Exception as e:
            _logd.error(f"_draw_multi_event_markers error: {e}")

        # ── Bandeau résiduel ΔBT vs référence (sous le graphe) ───────────────
        try:
            self._draw_residual_strip(ax_resid, mode)
        except Exception as e:
            _logd.error(f"_draw_residual_strip error: {e}")
            ax_resid.axis('off')

        # ── Ruban d'équilibre des phases (sous le graphe) ────────────────────
        # L'identité des roasts (nom + couleur) est portée par le ruban : la
        # légende ne garde donc que le rappel de style de trait.
        from matplotlib.lines import Line2D as _L2D
        try:
            self._draw_phase_ribbon(ax_ribbon, palette)
        except Exception as e:
            _logd.error(f"_draw_phase_ribbon error: {e}")
            ax_ribbon.axis('off')

        # Rappel de style de trait, ancré sous le ruban. En vue alignée, seul BT
        # est tracé → on n'affiche que BT.
        style_handles = [_L2D([0], [0], color='#CDD6F4', linewidth=2,
                               label=QApplication.translate("Label", "BT"))]
        if not align:
            style_handles += [
                _L2D([0], [0], color='#CDD6F4', linewidth=1.4, linestyle='--',
                     label=QApplication.translate("Label", "RoR")),
                _L2D([0], [0], color='#CDD6F4', linewidth=0.9, linestyle=':',
                     label=QApplication.translate("Label", "ET")),
            ]
        ax_legend.legend(
            handles=style_handles,
            loc='center',
            ncol=len(style_handles),
            fontsize=_FS_LEGEND,
            facecolor='#1e1e2e',
            edgecolor='#45475A',
            labelcolor='white',
            framealpha=0.85,
        )

        # Marqueurs hover — BT + ET sur ax1, RoR sur ax_ror
        # Tous taille 7. Courbe la plus proche : markerfacecolor rempli.
        from matplotlib.lines import Line2D as _Line2D
        self._multi_markers_bt  = []
        self._multi_markers_et  = []
        self._multi_markers_ror = []
        for series in self._multi_series:
            def _mk(col, ax):
                m = _Line2D([0],[0], marker='o', color=col, markersize=7,
                            markerfacecolor='none', markeredgewidth=1.8,
                            linestyle='none', visible=False, zorder=7)
                ax.add_line(m)
                return m
            self._multi_markers_bt.append( _mk(series['bt_col'],  ax1))
            self._multi_markers_et.append( _mk(series['et_col'],  ax1))
            self._multi_markers_ror.append(_mk(series['ror_col'], ax_ror))
        # alias pour compatibilité on_plot_leave
        self._multi_markers = self._multi_markers_bt + self._multi_markers_et + self._multi_markers_ror

        self._reconnect_hover()
        self.canvas.mpl_connect('figure_leave_event', self.on_plot_leave)
        self.last_plot_data = self._multi_curves[0]['data'] if self._multi_curves else None
        self.canvas.draw_idle()
        # Onglet Advanced Stats : dot plot comparatif + mini-résumé (pas le tableau).
        try:
            self._set_stats_view(True)
            self._render_multi_dotplot()
            _mode_label = {
                'overlay':     QApplication.translate("tilauscope_beancave", "Overlay"),
                'consistency': QApplication.translate("tilauscope_beancave", "Consistency"),
                'align':       QApplication.translate("tilauscope_beancave", "Aligned"),
            }.get(view, QApplication.translate("tilauscope_beancave", "Overlay"))
            self.roast_plot_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Comparing {n} roasts · {mode} view — select one to return to single view."
                ).format(n=len(self._multi_curves), mode=_mode_label))
        except Exception as e:
            _logd.error(f"_multi_stats_html error: {e}")

    def _on_multi_hover(self, event) -> None:
        """Hover en mode multi : identifie la courbe BT la plus proche du curseur."""
        if not hasattr(self, '_multi_series') or not self._multi_series:
            return
        if event.inaxes not in (self.ax1, self.ax_hoovers):
            self._hover_tooltip.hide()
            return

        x_data = event.xdata
        if x_data is None:
            self._hover_tooltip.hide()
            return

        # Mode actif : restreint le survol aux courbes réellement tracées.
        view = getattr(self, '_multi_view_mode', 'overlay')
        consistency = (view == 'consistency')
        aligned = (view == 'align')
        # En Consistance seule la référence est tracée → on ne survole qu'elle.
        cand_idx = [0] if (consistency and self._multi_series) else list(range(len(self._multi_series)))

        # Trouver la série dont le BT est le plus proche du y curseur
        y_data = event.ydata
        best_series = None
        best_dist   = float('inf')
        best_t_idx  = 0

        for i in cand_idx:
            series = self._multi_series[i]
            if not series['x'] or not series['bt']:
                continue
            t_idx = min(range(len(series['x'])),
                        key=lambda k, x=x_data: abs(series['x'][k] - x))
            if t_idx < len(series['bt']):
                dist = abs(series['bt'][t_idx] - (y_data or 0))
                if dist < best_dist:
                    best_dist   = dist
                    best_series = series
                    best_t_idx  = t_idx

        if best_series is None:
            self._hover_tooltip.hide()
            # Cacher tous les marqueurs
            if hasattr(self, '_multi_markers'):
                for m in self._multi_markers:
                    m.set_visible(False)
            self.canvas.draw_idle()
            return

        # Marqueurs adaptés au mode : réf seule en Consistance, BT seul en Aligné.
        has_markers = (hasattr(self, '_multi_markers_bt') and
                       len(self._multi_markers_bt) == len(self._multi_series))
        if has_markers:
            for idx, (series, m_bt, m_et, m_ror) in enumerate(zip(
                    self._multi_series,
                    self._multi_markers_bt,
                    self._multi_markers_et,
                    self._multi_markers_ror)):
                if (idx not in cand_idx) or not series['x']:
                    m_bt.set_visible(False)
                    m_et.set_visible(False)
                    m_ror.set_visible(False)
                    continue
                t_idx_m = min(range(len(series['x'])),
                              key=lambda k, x=x_data: abs(series['x'][k] - x))
                is_best = (series is best_series)
                ew = 2.2 if is_best else 1.5
                # BT (toujours tracé dans tous les modes)
                if t_idx_m < len(series['bt']) and series['bt'][t_idx_m] is not None:
                    m_bt.set_data([series['x'][t_idx_m]], [series['bt'][t_idx_m]])
                    m_bt.set_markerfacecolor(series['bt_col'] if is_best else 'none')
                    m_bt.set_markeredgewidth(ew)
                    m_bt.set_visible(True)
                else:
                    m_bt.set_visible(False)
                # ET / RoR : masqués en Aligné (non tracés)
                if (not aligned) and t_idx_m < len(series['et']) and series['et'][t_idx_m] is not None:
                    m_et.set_data([series['x'][t_idx_m]], [series['et'][t_idx_m]])
                    m_et.set_markerfacecolor(series['et_col'] if is_best else 'none')
                    m_et.set_markeredgewidth(ew)
                    m_et.set_visible(True)
                else:
                    m_et.set_visible(False)
                if (not aligned) and t_idx_m < len(series['ror']) and series['ror'][t_idx_m] is not None:
                    m_ror.set_data([series['x'][t_idx_m]], [series['ror'][t_idx_m]])
                    m_ror.set_markerfacecolor(series['ror_col'] if is_best else 'none')
                    m_ror.set_markeredgewidth(ew)
                    m_ror.set_visible(True)
                else:
                    m_ror.set_visible(False)
            self.canvas.draw_idle()

        mode    = best_series['mode']
        x_vals  = best_series['x']
        time_s  = x_vals[best_t_idx] * 60.0
        time_str = self.format_seconds(time_s)

        bt_val  = best_series['bt'][best_t_idx]  if best_t_idx < len(best_series['bt'])  else None
        et_val  = best_series['et'][best_t_idx]  if best_t_idx < len(best_series['et'])  else None
        dbt_val = best_series['ror'][best_t_idx] if best_t_idx < len(best_series['ror']) else None

        def dot(c): return f'<span style="color:{c}; font-size:14px;">&#9632;</span> '

        _time_lbl = QApplication.translate("Label", "Time")
        if aligned:
            _time_lbl = QApplication.translate("tilauscope_beancave", "Aligned time")
        lines = [
            f'<b style="color:#CDD6F4;">{best_series["title"]}</b>',
            f'<b style="color:#CDD6F4;">{_time_lbl} : {time_str}</b>',
        ]
        if bt_val is not None: lines.append(f'{dot(best_series["bt_col"])}BT : {bt_val:.1f}°{mode}')
        # ET / RoR seulement si réellement tracés (pas en Aligné).
        if not aligned:
            if et_val  is not None: lines.append(f'{dot(best_series["et_col"])}ET : {et_val:.1f}°{mode}')
            if dbt_val is not None: lines.append(f'{dot(best_series["ror_col"])}RoR : {dbt_val:.1f}°{mode}/min')
        # En Consistance : étendue BT (min–max) de tous les roasts à cet instant.
        if consistency and len(self._multi_series) >= 2:
            bt_at = []
            for s in self._multi_series:
                if not s['x'] or not s['bt']:
                    continue
                k = min(range(len(s['x'])), key=lambda j, x=x_data: abs(s['x'][j] - x))
                if k < len(s['bt']) and s['bt'][k] is not None:
                    bt_at.append(s['bt'][k])
            if len(bt_at) >= 2:
                _spread_lbl = QApplication.translate("tilauscope_beancave", "BT spread")
                lines.append(f'<span style="color:#9399B2;">{_spread_lbl} : '
                             f'{min(bt_at):.1f}–{max(bt_at):.1f}°{mode}</span>')

        html = '<br>'.join(lines)
        if event.guiEvent is not None:
            global_point = event.guiEvent.globalPosition().toPoint()
        else:
            device_ratio = self.canvas.devicePixelRatioF()
            x_canvas = int(event.x / device_ratio)
            y_canvas = int((self.canvas.height() * device_ratio - event.y) / device_ratio)
            global_point = self.canvas.mapToGlobal(QPoint(x_canvas, y_canvas))
        self._hover_tooltip.show_at(global_point, html)

    @pyqtSlot(bool)
    def on_roast_finished_clicked(self) -> None:
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
            m =  self.roast_list_widget.currentItem()
            metadata = m.data(Qt.ItemDataRole.UserRole)
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

        ## TILAU ## RoastResultDialog only injects into qmc. On the live path
        ## Artisan saves the profile itself at the end of the roast, but here the
        ## roast is already on disk: without an explicit write-back the edited
        ## weight / colour / batch / notes never reach the file, and every reader
        ## downstream (Advanced Stats, roast card, corpus index) keeps showing the
        ## pre-edit values.
        try:
            saved = self.aw.fileSave(str(filepath))
        except Exception as e:  # noqa: BLE001
            _logd.error(f"on_roast_finished_clicked: write-back failed: {e}")
            saved = False
        if not saved:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Save Error"),
                QApplication.translate("tilauscope_beancave",
                    "The roast results could not be written back to the profile file."),
                QMessageBox.Icon.Warning)
            return

        # The file changed on disk: drop it from the read cache, reload the viewer
        # (curve + Advanced Stats) and re-index so the roast list and the
        # reference corpus follow the edit.
        self._alog_cache.pop(str(filepath), None)
        self.load_roast_data_and_plot()
        self.trigger_cache_refresh()

    @pyqtSlot()
    ## TILAU ## Export the selected roast as a shareable landscape JPEG
    def on_export_roast_card(self) -> None:
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
        safe_name = re.sub(r'[^\w\-]+', '-', title).strip('-') or "roast"
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

    @pyqtSlot()
    def _alog_worker_finished_on_plot_error(self, filename:str):
        _logd.warning(f"Unable to read or decode alog file '{filename}'")
        self.roast_plot_label.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file"))
        self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Error reading/parsing file."))

    @pyqtSlot(object, object, object)
    def _alog_worker_finished_on_plot_ok(self, profiledata, deltaet, deltabt):
        _logd.debug("finished worker")
        self.lastprofiledata = profiledata
        self.display_roast_info(self.lastprofiledata)
        self.plot_bt_curve_preview(self.lastprofiledata, deltaet, deltabt)  # type: ignore
        self._update_roast_plan_values()
        # ── Update header label with roast display name ──────────────────────
        item = self.roast_list_widget.currentItem()
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
        tx = numpy.array(data.get("timex", []))
        timeindex = data.get("timeindex", [])
        rd = timeindex[RoastingPhase.CHARGE] if timeindex and timeindex[RoastingPhase.CHARGE] != -1 else 0
        drop = timeindex[RoastingPhase.DROP] if timeindex  else 0
        unit = data.get("temp_unit", "C")
        temp = [convertTemp(t,unit,self.aw.qmc.mode) for t in data.get(deltaname, [])]
                             
        cf = self.aw.qmc.curvefilter #*2 # we smooth twice as heavy for PID/RoR calculation as for normal curve smoothing
        t1 = smooth_list(data.get("timex", []),(fill_gaps(temp) if self.aw.qmc.interpolateDropsflag else temp),window_len=cf,decay_smoothing=not self.aw.qmc.optimalSmoothing)
        if len(t1)>10 and len(tx) > 10:
            # we start RoR computation 10 readings after CHARGE to avoid this initial peak
            RoR_start = min(rd+10,len(tx)-1)
            _, deltas = self.aw.qmc.recomputeDeltas(tx,RoR_start,drop,None,t1,optimalSmoothing=self.aw.qmc.optimalSmoothing)
            return deltas
        return None

    def check_duration(self, phase_name: str, duration_seconds: float) -> str:
        """
        Évalue si la durée absolue d'une phase est typique en utilisant les règles dynamiques.
        """
        duration_minutes = duration_seconds / 60.0
        
        # --- Utilise les règles calculées dynamiquement ---
        rules = self.duration_rules 

        phase_lower = phase_name.lower().strip()
        
        # Assigner la clé de recherche
        if "dry" in phase_lower:
            key = "drying"
        elif "mail" in phase_lower:
            key = "maillard"
        elif "dev" in phase_lower:
            key = "development"
        else:
            return "" 

        # Vérifier si une règle a été calculée pour cette clé
        if key not in rules:
            return QApplication.translate("tilauscope_beancave","Length: N/A (profile to compute)")

        min_duration, max_duration = rules[key]
        # --------------------------------------------------

        if duration_minutes < min_duration:
            return QApplication.translate("tilauscope_beancave","Too short")+f"( {min_duration:.1f}-{max_duration:.1f}m)"
        if duration_minutes > max_duration:
            return QApplication.translate("tilauscope_beancave","Too long")+f" ({min_duration:.1f}-{max_duration:.1f}m)"
        return QApplication.translate("tilauscope_beancave","Length OK")+f" ({duration_minutes:.1f}m)" # fix f-string missing
    
    @staticmethod
    def check_phase(label, pct, min_pct, max_pct):
        if pct < min_pct:
            return f"{label} "+QApplication.translate("tilauscope_beancave","too short")+" ({pct:.1f}%) — < {min_pct}%"
        if pct > max_pct:
            return f"{label} "+QApplication.translate("tilauscope_beancave","too long")+" ({pct:.1f}%) — > {max_pct}%"
        return f"{label} OK ({pct:.1f}%) ✅"
    
    def get_current_probe_deviation(self) -> ProbeDeviation:
        return ProbeDeviation(
            probe_id="main_bt",
            bt_at_charge=ProbeDeviationInterval(
                self.dev_inputs["bt_at_charge"][0].value(), 
                self.dev_inputs["bt_at_charge"][1].value()
            ),
            bt_at_de=ProbeDeviationInterval(
                self.dev_inputs["bt_at_de"][0].value(), 
                self.dev_inputs["bt_at_de"][1].value()
            ),
            bt_at_fc=ProbeDeviationInterval(
                self.dev_inputs["bt_at_fc"][0].value(), 
                self.dev_inputs["bt_at_fc"][1].value()
            ),
            bt_at_drop=ProbeDeviationInterval(
                self.dev_inputs["bt_at_drop"][0].value(), 
                self.dev_inputs["bt_at_drop"][1].value()
            )
    )

    # ── Roast-level awareness (single source of truth for the coach) ──────────
    # Coffee science, not roaster-specific: a lighter target drops cooler, loses
    # less weight and runs a shorter absolute development than a darker target,
    # whatever the machine. Every quantitative coach check routes through here so
    # a deliberately light roast is never judged against medium-roast assumptions.
    @staticmethod
    def roast_level_from_color(roast_color_val):
        """Agtron whole-bean → 'light' | 'medium' | 'dark' | None (higher = lighter)."""
        if roast_color_val is None:
            return None
        try:
            v = float(roast_color_val)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        if v > 65:
            return 'light'
        if v < 45:
            return 'dark'
        return 'medium'

    def roast_level_thresholds(self, roast_color_val):
        """Return (level, thresholds) for the target roast color.

        thresholds carries: dtr (min,max %), wl (min,max %) and drop_c (low,high
        bean-temp window in °C). When the color is unknown we fall back to a
        medium-roast profile but mark the level None so callers can stay cautious.
        """
        level = self.roast_level_from_color(roast_color_val)
        # dev_time = professional-convention development window in absolute minutes
        # (FCs→DROP). For a light roast ~1:00–2:00 is a sound development, so
        # 1:00–1:30 reads as on-target; under ~1:00 is where under-development
        # risk genuinely rises. This is the domain floor the learned data must not
        # override — % development ratio and absolute development time are two
        # complementary readings, not one.
        # DTR rises with darkness: a light roast drops soon after first crack
        # (short development → lower ratio), a dark roast prolongs development
        # (higher ratio). Weight loss likewise rises with darkness.
        table = {
            'light':  {'dtr': (12.0, 20.0), 'wl': (11.0, 15.0), 'drop_c': (188.0, 200.0), 'dev_time': (1.0, 2.0)},
            'medium': {'dtr': (15.0, 24.0), 'wl': (13.0, 18.0), 'drop_c': (198.0, 210.0), 'dev_time': (1.5, 2.75)},
            'dark':   {'dtr': (18.0, 28.0), 'wl': (15.0, 21.0), 'drop_c': (208.0, 222.0), 'dev_time': (2.0, 3.5)},
        }
        return level, table.get(level or 'medium', table['medium'])

    def phase_rules_for_color(self, roast_color_val):
        """Phase-duration ranges for the roast's level, falling back per-phase to
        the pooled rules when the level has too few samples to be reliable."""
        pooled = getattr(self, 'duration_rules', {}) or {}
        by_band = getattr(self, 'duration_rules_by_band', {}) or {}
        level = self.roast_level_from_color(roast_color_val)
        band = by_band.get(level, {}) if level else {}
        out = {}
        for k in ('drying', 'maillard', 'development'):
            if k in band:
                out[k] = band[k]
            elif k in pooled:
                out[k] = pooled[k]
        return out

    def construire_profils_referentiels(self, roast_data_list):
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return
        profils_bruts = defaultdict(lambda: defaultdict(list))
        # Références pour le nettoyage (réutilisez les mêmes que pour la régression)
        WL_MIN, WL_MAX = 10.0, 25.0
        COLOR_MIN, COLOR_MAX = 20.0, 130.0 
        all_dry_times = []
        all_maillard_times = []
        all_dev_times = []
        # Same times, but split by roast-level band so a light roast is later
        # compared to past light roasts rather than a mixed-color average.
        band_dry = {'light': [], 'medium': [], 'dark': []}
        band_mai = {'light': [], 'medium': [], 'dark': []}
        band_dev = {'light': [], 'medium': [], 'dark': []}
        for entry in roast_data_list:
            try:
                titre_grain = entry.get('Title')
                if not titre_grain or titre_grain == 'N/A':
                    continue
                bt_str = entry.get('Drop_BT (°C/°F)', '') if not entry.get('Drop_BT (°C/°F)', '').startswith('N/A') else ''
                bt_str_clean = re.sub(r'[°C°F]', '', bt_str).strip()
                drop_bt = float(bt_str_clean) if bt_str_clean else None
                weight_in = float(entry.get('WeightIn (g)', 0.0))
                weight_out = float(entry.get('WeightOut (g)', 0.0))
                weight_loss= entry.get('WeightLoss (%)', 'N/A')
                ## TILAU ## Roast loss is a fraction OF THE GREEN CHARGE, so the
                ## denominator is weight_in. Dividing by weight_out overstated
                ## every reconstructed value (a real 15 % read 17.6 %) and pushed
                ## roasts past the WL_MAX plausibility gate, which silently
                ## dropped them from the reference profiles.
                if weight_loss == 'N/A' and weight_in > 0.0 and weight_out not in (0.0, weight_in):
                    weight_loss = round((weight_in - weight_out) / weight_in * 100.0, 1)
                elif weight_loss == 'N/A':
                    continue
                try:
                    weight_loss = float(weight_loss)
                except (TypeError, ValueError):
                    continue
                
                roast_color = float(entry.get('RoastColor', -1.0)) #type:ignore
                total_time_min = float(entry.get('TotalTime (min)', -1.0))
                total_time_s = total_time_min * 60.0
                dtr_pct = float(entry.get('DTR%', 0.0))
                if not (drop_bt and WL_MIN <= weight_loss <= WL_MAX and COLOR_MIN <= roast_color <= COLOR_MAX):
                    continue
                profils_bruts[titre_grain]['drop_bt'].append(drop_bt)
                profils_bruts[titre_grain]['weight_loss'].append(weight_loss)
                profils_bruts[titre_grain]['roast_color'].append(roast_color)
                profils_bruts[titre_grain]['total_time'].append(total_time_s)
                profils_bruts[titre_grain]['dtr_pct'].append(dtr_pct)
                dry_time_min = entry.get("DryTime (s)", 0) / 60.0
                maillard_time_min = entry.get("MaillardTime (s)", 0) / 60.0
                dev_time_min = entry.get("DevelopmentTime (s)", 0) / 60.0

                _band = self.roast_level_from_color(roast_color)
                if dry_time_min > 0:
                    all_dry_times.append(dry_time_min)
                    if _band: band_dry[_band].append(dry_time_min)
                if maillard_time_min > 0:
                    all_maillard_times.append(maillard_time_min)
                    if _band: band_mai[_band].append(maillard_time_min)
                if dev_time_min > 0:
                    all_dev_times.append(dev_time_min)
                    if _band: band_dev[_band].append(dev_time_min)
            except Exception as e:
                _logd.warning(f"Erreur lors du traitement de l'entrée {entry}: {e}") 
                continue

        referentiel_final: list[ReferenceProfile] = []

        for titre, metrics in profils_bruts.items():
            if len(metrics["drop_bt"]) < 2:
                continue
            referentiel_final.append(ReferenceProfile(
                title=titre,
                count=len(metrics["drop_bt"]),
                avg_drop_bt=round(statistics.mean(metrics["drop_bt"]), 1),
                avg_weight_loss=round(statistics.mean(metrics["weight_loss"]), 1),
                avg_roast_color=round(statistics.mean(metrics["roast_color"]), 2),
                avg_total_time_min=round(
                    statistics.mean(metrics["total_time"]) / 60.0, 1
                ),
                avg_dtr_pct=round(statistics.mean(metrics["dtr_pct"]), 1),
                )
            )
        self.cave.reference_profiles = referentiel_final

        duration_rules = {}
        
        def calculate_range(times, min_cap, max_cap):
            """Calcul la plage moyenne +/- 1.5 * Écart-type."""
            if len(times) < 2:
                # Pas assez de données, on retourne None ou une valeur par défaut
                return None 
            
            mean = statistics.mean(times)
            stdev = statistics.stdev(times)
            
            # Plage: Moyenne +/- 1.5 * Écart-type
            min_val = max(min_cap, mean - 1.5 * stdev)
            max_val = min(max_cap, mean + 1.5 * stdev)
            
            # S'assurer que la plage est d'au moins 1 minute de large
            if max_val - min_val < 1.0:
                max_val = min_val + 1.0
            v = (round(min_val, 1), round(max_val, 1))
            _logd.debug(f"range computed, start={v[0]} end={v[1]}")    
            return v

        # 1. Calcul pour le Séchage (Dry Phase)
        if all_dry_times:
            # Min/Max Cap ici sont des limites absolues de sécurité
            dry_range = calculate_range(all_dry_times, min_cap=3.0, max_cap=12.0)
            if dry_range:
                duration_rules["drying"] = dry_range
        
        # 2. Calcul pour Maillard (Mid Phase)
        if all_maillard_times:
            maillard_range = calculate_range(all_maillard_times, min_cap=2.0, max_cap=8.0)
            if maillard_range:
                duration_rules["maillard"] = maillard_range

        # 3. Calcul pour le Développement (Finish Phase)
        if all_dev_times:
            dev_range = calculate_range(all_dev_times, min_cap=1.0, max_cap=6.0)
            if dev_range:
                duration_rules["development"] = dev_range

        # Sauvegarde des nouvelles règles
        #self.settings["duration_rules"] = duration_rules
        self.duration_rules = duration_rules # Mise à jour de l'attribut de la classe

        # Per-band rules: only phases with ≥2 samples in the band get a range
        # (calculate_range returns None otherwise), so phase_rules_for_color
        # naturally falls back to the pooled rule when a band is too sparse.
        self.duration_rules_by_band = {}
        for _b in ('light', 'medium', 'dark'):
            br = {}
            dr = calculate_range(band_dry[_b], min_cap=3.0, max_cap=12.0)
            if dr: br['drying'] = dr
            mr = calculate_range(band_mai[_b], min_cap=2.0, max_cap=8.0)
            if mr: br['maillard'] = mr
            vr = calculate_range(band_dev[_b], min_cap=1.0, max_cap=6.0)
            if vr: br['development'] = vr
            if br:
                self.duration_rules_by_band[_b] = br
        _logd.debug(f"Référentiel construit pour {len(referentiel_final)} types de grains.")

        self.save_green_beans()
   
    def predire_couleur_torrefaction(self, data):
        c = data["computed"]
        drop_bt = c.get("DROP_BT", None)
        dtr_pct = round(c.get("finishphasetime", 0) / c.get("totaltime", 1) * 100, 1)
        weight_loss = c.get("weight_loss", 0.0)

        if drop_bt == 0.0 or weight_loss == 0.0:
            return QApplication.translate("tilauscope_beancave","Impossible to predict (data on BT or weight loss missing or null).")

        C0 = self.C0_COLOR   # Interception
        C_BT = self.C_BT_COLOR  # Coefficient de Drop_BT
        C_DTR = self.C_DTR_COLOR # Coefficient de DTR%
        C_WL = self.C_WL_COLOR  # Coefficient de WeightLoss (%)
        MIN_COLOR_VALUE: Final[float] = 10.03 # ou 10.0 pour une marge
        
        profile_descriptions = {
            "Extremely Dark": QApplication.translate("tilauscope_beancave","Very bitter, burnt flavors, suitable for espresso blends."),
            "Very Dark": QApplication.translate("tilauscope_beancave","Strong bitterness, smoky notes, often used for espresso."),
            "Dark": QApplication.translate("tilauscope_beancave","Balanced bitterness and body, with chocolatey undertones."),
            "Medium Dark": QApplication.translate("tilauscope_beancave","Rich flavor with a balance of acidity and body."),
            "Medium": QApplication.translate("tilauscope_beancave","Balanced acidity and body, with a variety of flavor notes."),
            "Medium Light": QApplication.translate("tilauscope_beancave","Bright acidity, fruity and floral notes."),
            "Light": QApplication.translate("tilauscope_beancave","High acidity, pronounced fruity and floral characteristics."),
            "Very Light": QApplication.translate("tilauscope_beancave","Very high acidity, pronounced  floral characteristics.") # fix 2026/02/23 was missing
        }
#        SEUIL_MEDIUM_LIGHT: Final[float] = 14.5 # Seuil entre Medium et Light
#        SEUIL_DARK_MEDIUM: Final[float] = 50  # Seuil entre Dark et Medium
        # Calcul de la valeur de couleur prédite
        pred_color_value = (C0 +
                            C_BT * drop_bt +
                            C_DTR * dtr_pct +
                            C_WL * weight_loss)

        pred_color_value_clipped = max(pred_color_value, MIN_COLOR_VALUE)
        #_logd.debug(f"Predicted color (raw): {C0:.2f} + ({drop_bt:.2f}*{C_BT:.2f}) + ({dtr_pct:.2f}*{C_DTR:.2f}) + ({weight_loss:.2f}*{C_WL:.2f}) = {pred_color_value:.2f}")

        couleur = QApplication.translate("tilauscope_beancave","❌ Unknown")
        profil = QApplication.translate("tilauscope_beancave","Input data out of usual training range.")
        for a in AGTRON_SCALES:
            if  a.agtron_range.min_value <= pred_color_value_clipped <= a.agtron_range.max_value:
                couleur = a.name
                profil = profile_descriptions[a.name]
                break       
        return f"{couleur}\n"+QApplication.translate("tilauscope_beancave","Profile : ")+f"{profil}\n"+QApplication.translate("tilauscope_beancave","(Predicted color: ")+f"{pred_color_value_clipped:.2f})"

    def _get_uuid_from_bean_description(self, bean_field:str)-> str:
        uuid_match = self.uuid_pattern.search(bean_field)
        if uuid_match:
            target_uuid = uuid_match.group(1)
            # Look up the bean in the cave using the existing helper method
            return self.uuidmap.get(target_uuid,"") if uuid_match else ""
        else:
            return "" # no uuid
        
    @pyqtSlot()
    def show_barista_expert_view(self, profiledata=None):
        # Works on the passed profile (timeline hand-off) or the currently loaded
        # roast (the toolbar button). Both carry the same enriched shape (incl.
        # the "computed" block) so the advice is identical either way.
        data = profiledata if profiledata is not None else getattr(self, 'lastprofiledata', None)
        if not data:
            self._show_message(self, QApplication.translate("tilauscope_beancave", "No Data"),
                               QApplication.translate("tilauscope_beancave", "Please select a roast file first."),
                               QMessageBox.Icon.Warning)
            return

        ## TILAU ## The advisor sits behind a boundary with no schema: an .alog is
        ## read with ast.literal_eval, and ProfileData is a TypedDict, which the
        ## runtime does not enforce. Artisan's own writer emits floats, but an
        ## older file, a repaired one or a profile from another tool can carry a
        ## number as text — and a single such field used to abort the whole
        ## dialog with a TypeError deep inside the engine. Coerce once, here,
        ## rather than let every rule downstream assume a type it never checked.
        def _num(v, default: float = 0.0) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _storage_thresholds():
            """The operator's own aw window, or the shipped defaults."""
            try:
                from tilauscope.beancave_storage_tab import load_thresholds  # noqa: PLC0415
                return load_thresholds()
            except Exception as exc:  # noqa: BLE001
                _logd.warning("Brew: storage thresholds unavailable (%s); using defaults", exc)
                from tilauscope.storage_advisor import DEFAULT_THRESHOLDS  # noqa: PLC0415
                return DEFAULT_THRESHOLDS

        ground = _num(data.get("ground_color", 0.0))
        whole = _num(data.get("whole_color", 0.0))
        color_system: str = str(data.get("color_system", "") or "")

        if color_system == "" or (ground == 0.0 and whole == 0.0):
            self._show_message(self, QApplication.translate("tilauscope_beancave", "Missing color data"),
                               QApplication.translate("tilauscope_beancave", "Please enter color information in the roast property first."),
                               QMessageBox.Icon.Warning)
            return

        # Resolve the linked green bean (expert advice requires bean context)
        bean_field = str(data.get('beans', "") or "")
        uuid_match = re.compile(r'uuid: \s*([a-fA-F0-9-]{36})').search(bean_field)
        matched_bean = self.uuidmap.get(uuid_match.group(1)) if uuid_match else None
        if not matched_bean:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Association Error"),
                QApplication.translate("tilauscope_beancave",
                    "This roast is not associated with a green bean in your Beancave. "
                    "Please link it using the 'Set UUID' tool to see expert recommendations."),
                QMessageBox.Icon.Critical)
            return

        # Phase context — development ratio drives extraction guidance
        computed = data.get("computed", {})
        dry = _num(computed.get("dryphasetime", 0))
        mid = _num(computed.get("midphasetime", 0))
        dev = _num(computed.get("finishphasetime", 0))
        total_phase = dry + mid + dev
        dev_ratio = (dev / total_phase) if total_phase > 0 else 0.0

        # Days off roast (degassing) from the ISO roast date
        days_off = -1
        iso = str(data.get("roastisodate", "") or "")
        if iso:
            try:
                rd = datetime.fromisoformat(iso[:10]).date()
                days_off = max(0, (datetime.now().date() - rd).days)
            except Exception:
                days_off = -1

        inp = BrewInput(
            ground_color=ground, whole_color=whole, color_system=color_system,
            weight_loss=_num(computed.get("weight_loss", 0.0)),
            density=_num(getattr(matched_bean, "density", 0.0)),
            water_activity=_num(getattr(matched_bean, "water_activity", 0.0)),
            green_moisture=_num(getattr(matched_bean, "last_humidity", 0.0)),
            dev_ratio=dev_ratio, dev_time_s=int(dev),
            process=str(getattr(matched_bean, "process", "") or ""),
            country=str(getattr(matched_bean, "country", "") or ""),
            altitude=int(_num(getattr(matched_bean, "altitude", 0))),
            variety=str(getattr(matched_bean, "varieties", "") or ""),
            species=str(getattr(matched_bean, "species", "") or ""),
            days_off_roast=days_off,
            water_profile=WaterProfile.AUTO,
            ## TILAU ## The Storage tab owns the aw doctrine, thresholds
            ## included: the brew advice follows the operator's own window
            ## instead of a second hardcoded opinion.
            aw_thresholds=_storage_thresholds(),
        )
        title = str(data.get("title", "") or "") or getattr(matched_bean, "name", "")
        dlg = BrewAdvisorDlg(inp, title=title, aw=self.aw, beancave=self,
                             bean=matched_bean)
        dlg.exec()
    
    def display_roast_info(self, data: ProfileData) -> None:
        # Vue mono : on affiche la fiche HTML (et non le dot plot multi).
        self._set_stats_view(False)

        computed: ComputedProfileInformation = data.get("computed", {})

        def get_ror(key):
            ror = computed.get(key, "N/A")
            try:
                return f"{float(ror):.2f}" if ror != "N/A" else "N/A"
            except ValueError:
                return str(ror)

        # ── Extraction ────────────────────────────────────────────────────
        roasttime      = data.get("roasttime", "N/A")
        date           = data.get("roastdate", "N/A")
        roastertype    = data.get("roastertype", "N/A")
        batch_prefix   = str(data.get("roastbatchprefix", "") or "")
        batch_nr       = int(data.get("roastbatchnr", 0) or 0)
        ## TILAU ## Colour reference: the GROUND reading describes the bean's real
        ## development, the whole-bean value is only the fallback for roasts
        ## measured on whole beans alone. Same rule as the roast card, the label
        ## printer and the brew advisor — Advanced Stats used to read whole_color
        ## only, silently ignoring a ground measurement.
        def _colour_num(v) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        whole_colour   = _colour_num(data.get("whole_color", 0))
        ground_colour  = _colour_num(data.get("ground_color", 0))
        roast_colour   = ground_colour or whole_colour        # ground wins, whole falls back
        roastcolor     = roast_colour if roast_colour > 0 else "N/A"
        colorsystem    = data.get("color_system", "N/A")
        charge_weight  = data.get("weight", ["N/A", None, ""])[0]
        charge_unit    = data.get("weight", ["N/A", None, ""])[2]
        mode           = data.get("mode", "C")

        t_charge = 0
        t_dry    = computed.get("DRY_time", 0)
        t_fcs    = computed.get("FCs_time", 0)
        t_drop   = computed.get("DROP_time", 0)

        drying_auc  = computed.get("dry_phase_AUC", "N/A")
        middle_auc  = computed.get("mid_phase_AUC", "N/A")
        fcs_drop    = computed.get("finish_phase_AUC", "N/A")
        total_auc   = computed.get("AUC", "N/A")
        auc_start   = computed.get("AUCbegin")
        auc_start_str = QApplication.translate("Label", auc_start) if auc_start else ""

        drying      = t_dry - t_charge
        maillard    = t_fcs - t_dry
        development = t_drop - t_fcs
        total       = t_drop - t_charge

        if total > 0:
            drying_pct      = 100 * drying / total
            maillard_pct    = 100 * maillard / total
            development_pct = 100 * development / total
        else:
            drying_pct = maillard_pct = development_pct = 0

        weight_loss = computed.get("weight_loss", 0.0)
        defect_weight = computed.get("roast_defects_loss", 0.0)
        dtr_pct_val = development_pct

        try:
            wl_val = float(weight_loss) if weight_loss not in {0.0, "N/A"} else None
        except (ValueError, TypeError):
            wl_val = None

        _rc_for_rules = roast_colour if roast_colour > 0 else None
        rules = self.phase_rules_for_color(_rc_for_rules)

        # ── Agtron label ──────────────────────────────────────────────────
        agtron_label = ""
        if roast_colour > 0:
            for a in AGTRON_SCALES:
                try:
                    if a.agtron_range.min_value <= roast_colour <= a.agtron_range.max_value:
                        agtron_label = f"{a.name} · {a.description}"
                        break
                except (TypeError, ValueError):
                    pass
        else:
            agtron_label = QApplication.translate("tilauscope_beancave", "not present")

        # ── Colour badge + provenance line ────────────────────────────────
        # The badge carries the reference reading; the line below names which
        # measurement it came from and shows the whole/ground delta when both
        # exist (a wide delta = surface and core developed unevenly).
        _cs = str(colorsystem or "").strip()
        colour_badge_txt = f"{roast_colour:g} {_cs}".strip() if roast_colour > 0 else str(roastcolor)
        colour_detail = ""
        if ground_colour > 0 and whole_colour > 0:
            colour_detail = QApplication.translate(
                "tilauscope_beancave", "ground {0} · whole {1} · Δ {2}").format(
                    f"{ground_colour:g}", f"{whole_colour:g}",
                    f"{abs(ground_colour - whole_colour):g}")
        elif ground_colour > 0:
            colour_detail = QApplication.translate("tilauscope_beancave", "ground")
        elif whole_colour > 0:
            colour_detail = QApplication.translate("tilauscope_beancave", "whole bean")

        # ── CARD_BG : légèrement plus claire que BG pour faire ressortir ──
        # On éclaircit manuellement la couleur de surface
        CARD_BG = "#2a2a3e"   # plus clair que THEME['BG'] (#1E1E2E)

        # ── Helper: badge ─────────────────────────────────────────────────
        def badge(text, kind="neutral"):
            colors = {
                "ok":      "background-color:#1a3a1a; color:#A6E3A1;",
                "warn":    "background-color:#3a2e00; color:#FAB387;",
                "bad":     "background-color:#3a1a1a; color:#F38BA8;",
                "neutral": f"background-color:{THEME['SURFACE']}; color:{THEME['SUBTEXT']};",
                "accent":  f"background-color:{THEME['ACCENT']}; color:{THEME['BG']};",
            }
            s = colors.get(kind, colors["neutral"])
            return (f'<span style="font-size:10px; font-weight:bold; padding:1px 6px; '
                    f'border-radius:4px; {s}">{text}</span>')

        def status_badge_text(val, ok_min, ok_max):
            """Retourne (texte_label, kind) selon position dans la plage."""
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    return QApplication.translate("tilauscope_beancave", "Normal weight loss").split()[0], "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Too short"), "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "Too long"), "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        def dtr_badge_text(val, ok_min, ok_max):
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    # réutilise la clé existante, on prend juste "Optimal"
                    return QApplication.translate("tilauscope_beancave", "Optimal DTR").replace(" DTR",""), "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Low DTR").replace(" DTR",""), "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "High DTR").replace(" DTR",""), "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        def wl_badge_text(val, ok_min, ok_max):
            if val is None:
                return "N/A", "neutral"
            try:
                v = float(val)
                if ok_min <= v <= ok_max:
                    return QApplication.translate("tilauscope_beancave", "Normal weight loss").split()[0], "ok"
                elif v < ok_min:
                    return QApplication.translate("tilauscope_beancave", "Low weight loss").split()[0], "warn"
                else:
                    return QApplication.translate("tilauscope_beancave", "High  weight loss").split()[0], "bad"
            except (TypeError, ValueError):
                return "N/A", "neutral"

        # ── Helper: section title ─────────────────────────────────────────
        def section_title(text):
            return (f'<tr><td colspan="4" style="padding:10px 0 3px 0;">'
                    f'<span style="font-size:10px; font-weight:bold; letter-spacing:1px; '
                    f'color:{THEME["SUBTEXT"]};">{text.upper()}</span>'
                    f'<hr style="border:none; border-top:1px solid {THEME["BORDER"]}; margin:2px 0 0 0;"/>'
                    f'</td></tr>')

        # ── Helper: metric card — hauteur fixe via 2 lignes explicites ────
        def metric_card(label, value, badge_label="", badge_kind="neutral"):
            b_html = badge(badge_label, badge_kind) if badge_label else "&nbsp;"
            return (
                f'<td style="padding:3px; vertical-align:top; width:25%;">'
                f'<table width="100%" cellpadding="0" cellspacing="0" style="'
                f'background-color:{CARD_BG}; border-radius:6px; '
                f'border:1px solid {THEME["BORDER"]}; border-collapse: collapse;">'
                f'<tr>'
                f'<td style="padding:7px 8px 7px 8px; border:none; vertical-align:top;">'
                # --- FIX DE HAUTEUR ICI ---
                f'<div style="min-height:68px; height:68px;">' 
                f'<div style="font-size:10px; color:{THEME["SUBTEXT"]}; margin-bottom:2px;">{label}</div>'
                f'<div style="font-size:13px; font-weight:bold; line-height:1.1; margin-bottom:5px;">{value}</div>'
                f'<div>{b_html}</div>'
                f'</div>'
                # --------------------------
                f'</td>'
                f'</tr>'
                f'</table>'
                f'</td>'
            )
        # ── Helper: key-value row ─────────────────────────────────────────
        def kv_row(label, value):
            return (
                f'<tr>'
                f'<td style="font-size:11px; color:{THEME["SUBTEXT"]}; '
                f'padding:3px 8px 3px 0; white-space:nowrap;">{label}</td>'
                f'<td style="font-size:11px; font-weight:bold; '
                f'padding:3px 0; text-align:right; white-space:nowrap;">{value}</td>'
                f'</tr>'
            )

        # ── Helper: advice row ────────────────────────────────────────────
        def advice_row(icon, text, kind="ok"):
            colors = {
                "ok":   "background-color:#1a3a1a; color:#A6E3A1;",
                "warn": "background-color:#3a2e00; color:#FAB387;",
                "bad":  "background-color:#3a1a1a; color:#F38BA8;",
                "info": "background-color:#0d2a3a; color:#89B4FA;",
            }
            c = colors.get(kind, colors["info"])
            return (
                f'<tr><td colspan="4" style="padding:2px 0;">'
                f'<table width="100%" cellpadding="7" cellspacing="0" '
                f'style="{c} border-radius:5px;">'
                f'<tr>'
                f'<td width="18" style="font-size:13px; vertical-align:top; '
                f'padding-right:6px;">{icon}</td>'
                f'<td style="font-size:11px; line-height:1.5;">{text}</td>'
                f'</tr></table></td></tr>'
            )

        # ── Phase bar ─────────────────────────────────────────────────────
        _dry_label  = QApplication.translate("tilauscope_beancave", "Drying (Charge -> Dry)").split("(")[0].strip()
        _mail_label = QApplication.translate("tilauscope_beancave", "Maillard (Dry -> FCs)").split("(")[0].strip()
        _dev_label  = QApplication.translate("tilauscope_beancave", "Development (FCs -> Drop)").split("(")[0].strip()

        if total > 0:
            dry_w  = max(2, int(drying_pct))
            mail_w = max(2, int(maillard_pct))
            dev_w  = max(2, int(development_pct))

            phase_bar_html = (
                f'<tr><td colspan="4" style="padding:4px 0 2px 0;">'
                # barre colorée
                f'<table width="100%" cellpadding="0" cellspacing="0" style="'
                f'border-radius:4px; border:1px solid {THEME["BORDER"]}; '
                f'border-collapse:collapse;">'
                f'<tr>'
                f'<td width="{dry_w}%" align="center" style="background-color:#1a3050; '
                f'color:#89B4FA; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{drying_pct:.0f}%</td>'
                f'<td width="{mail_w}%" align="center" style="background-color:#3a2800; '
                f'color:#FAB387; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{maillard_pct:.0f}%</td>'
                f'<td width="{dev_w}%" align="center" style="background-color:#1a3a1a; '
                f'color:#A6E3A1; font-size:10px; font-weight:bold; padding:4px 1px;">'
                f'{development_pct:.0f}%</td>'
                f'</tr></table>'
                # légende : 3 cellules alignées à gauche, pas étalées
                f'<table cellpadding="0" cellspacing="0" style="margin-top:5px;">'
                f'<tr>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'padding-right:20px; white-space:nowrap;">'
                f'<span style="color:#89B4FA;">&#9632;</span>&nbsp;'
                f'{_dry_label} {self.format_seconds(int(drying))}</td>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'padding-right:20px; white-space:nowrap;">'
                f'<span style="color:#FAB387;">&#9632;</span>&nbsp;'
                f'{_mail_label} {self.format_seconds(int(maillard))}</td>'
                f'<td style="font-size:10px; color:{THEME["SUBTEXT"]}; '
                f'white-space:nowrap;">'
                f'<span style="color:#A6E3A1;">&#9632;</span>&nbsp;'
                f'{_dev_label} {self.format_seconds(int(development))}</td>'
                f'</tr></table>'
                f'</td></tr>'
            )
        else:
            phase_bar_html = (
                f'<tr><td colspan="4" style="font-size:11px; color:{THEME["SUBTEXT"]};">'
                + QApplication.translate("tilauscope_beancave",
                                        "Roast data (events) is incomplete in the file.")
                + '</td></tr>'
            )

        # Replace the advice_rows generation block with this:

        advice_rows = ""
        roast_color_val = roast_colour if roast_colour > 0 else None

        # Single resolution of the roast-level thresholds, reused by every check.
        roast_level, lvl_th = self.roast_level_thresholds(roast_color_val)
        lvl_dtr_min, lvl_dtr_max = lvl_th['dtr']
        lvl_wl_min,  lvl_wl_max  = lvl_th['wl']
        lvl_label = {
            'light': QApplication.translate("tilauscope_beancave", "(light roast)"),
            'dark':  QApplication.translate("tilauscope_beancave", "(dark roast)"),
        }.get(roast_level, "")

        # Effective weight-loss window, resolved once and shared by the coach
        # advice and the summary badge so they can never disagree. The floor
        # follows the roast level (lighter roasts lose less); a known process
        # only *widens the top* — it must not raise the floor above the level,
        # which would wrongly flag a light natural that the badge calls Normal.
        wl_lo_eff, wl_hi_eff = lvl_wl_min, lvl_wl_max
        wl_proc_hint = ""
        _bean_field = data.get("beans", "")
        _um = re.search(r'uuid:\s*([a-fA-F0-9-]{36})', _bean_field)
        if _um and hasattr(self, 'uuidmap'):
            _linked = self.uuidmap.get(_um.group(1))
            if _linked:
                _proc = getattr(_linked, 'process', '').lower()
                if any(p in _proc for p in ['natural', 'honey', 'anaerobic']):
                    wl_hi_eff = max(wl_hi_eff, 20.0)
                    wl_proc_hint = QApplication.translate("tilauscope_beancave", "(natural/honey)")
                elif 'washed' in _proc:
                    wl_proc_hint = QApplication.translate("tilauscope_beancave", "(washed)")

        # ── 1. DTR% — with roast-level context ────────────────────────────────────
        if dtr_pct_val > 0:
            # Thresholds adapt to the target roast level (lighter roasts run a lower DTR).
            dtr_min_ctx, dtr_max_ctx = lvl_dtr_min, lvl_dtr_max
            if roast_level == 'light':
                dtr_label = QApplication.translate("tilauscope_beancave", "(light roast range)")
            elif roast_level == 'dark':
                dtr_label = QApplication.translate("tilauscope_beancave", "(dark roast range)")
            else:
                dtr_label = ""

            # The ratio is only an under-development signal when the *absolute*
            # development time is also short. When the time is adequate, a low
            # ratio just means the front (drying/Maillard) is long — pointing at
            # "extend development" would be wrong, so we reframe it as info.
            dev_min_conv = lvl_th['dev_time'][0]
            dev_time_adequate = (development / 60.0) >= dev_min_conv

            if dtr_pct_val < dtr_min_ctx:
                if dev_time_adequate:
                    advice_rows += advice_row("ℹ",
                        QApplication.translate("tilauscope_beancave", "DTR low but development time is adequate")
                        + f" ({dtr_pct_val:.1f}% &lt; {dtr_min_ctx:.0f}%, {development/60.0:.1f} min) {dtr_label} — "
                        + QApplication.translate("tilauscope_beancave",
                            "the ratio is low because the front (drying/Maillard) is long; shorten the front if you want a higher ratio, no need to extend development."),
                        "info")
                else:
                    advice_rows += advice_row("⚡",
                        QApplication.translate("tilauscope_beancave", "Short development")
                        + f" ({dtr_pct_val:.1f}% &lt; {dtr_min_ctx:.0f}%) {dtr_label} — "
                        + QApplication.translate("tilauscope_beancave",
                            "Underdeveloped risk: baked/grassy notes. Extend dev phase or raise drop temp."),
                        "warn")
            elif dtr_pct_val > dtr_max_ctx:
                advice_rows += advice_row("⚡",
                    QApplication.translate("tilauscope_beancave", "Long development")
                    + f" ({dtr_pct_val:.1f}% &gt; {dtr_max_ctx:.0f}%) {dtr_label} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Over-development risk: flat, roasty notes dominate. Consider an earlier drop."),
                    "warn")
            else:
                advice_rows += advice_row("✓",
                    QApplication.translate("tilauscope_beancave", "DTR in range")
                    + f" ({dtr_pct_val:.1f}%) {dtr_label}", "ok")

        # ── 2. Weight loss — roast-level window, widened for high-retention process ─
        if wl_val is not None:
            process_hint = wl_proc_hint
            wl_min_ctx, wl_max_ctx = wl_lo_eff, wl_hi_eff
            if wl_val < wl_min_ctx:
                advice_rows += advice_row("⚠",
                    QApplication.translate("tilauscope_beancave", "Low weight loss")
                    + f" ({wl_val:.1f}% &lt; {wl_min_ctx:.0f}%) {process_hint} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Bean may be under-roasted or the batch was unusually dense. Verify scale calibration."),
                    "warn")
            elif wl_val > wl_max_ctx:
                advice_rows += advice_row("⚠",
                    QApplication.translate("tilauscope_beancave", "High weight loss")
                    + f" ({wl_val:.1f}% &gt; {wl_max_ctx:.0f}%) {process_hint} — "
                    + QApplication.translate("tilauscope_beancave",
                        "Roast may be over-developed or airflow too high. Watch for flat cup."),
                    "bad")
            else:
                advice_rows += advice_row("✓",
                    QApplication.translate("tilauscope_beancave", "Weight loss in range")
                    + f" ({wl_val:.1f}%) {process_hint}", "ok")

        # ── 3. Phase durations ────────────────────────────────────────────────────
        # Development time is judged on the professional-convention window for the
        # target level (absolute minutes), so a sound light development of 1:00–1:30
        # reads on-target regardless of the learned average. Drying and Maillard
        # keep the learned, per-level ranges (with pooled fallback).
        rules = dict(rules)
        rules['development'] = lvl_th['dev_time']
        for phase_name_key, phase_key, duration_s in [
            ("Dry Phase",         "drying",      drying),
            ("Maillard Phase",    "maillard",    maillard),
            ("Development Phase", "development", development),
        ]:
            if phase_key in rules and duration_s > 0:
                mn, mx = rules[phase_key]
                actual_min = duration_s / 60.0
                phase_tr = QApplication.translate("tilauscope_beancave", phase_name_key)
                # Development cites the professional standard; the other phases
                # cite the user's own learned range.
                range_lbl = (QApplication.translate('tilauscope_beancave', 'standard for this level')
                             if phase_key == 'development'
                             else QApplication.translate('tilauscope_beancave', 'your usual range'))
                # Drying/Maillard are learned, soft references: a minor drift past
                # the band (< 30 s) is noise, not a fault — stay silent (on-target).
                # Development keeps a hard floor (professional standard, no grace).
                grace = 0.5 if phase_key in ('drying', 'maillard') else 0.0
                if actual_min < mn - grace:
                    # Observational, not a verdict: the range is learned from the
                    # user's own roasts at this level, so a short phase may simply
                    # be the intended style. Development gets the gentlest framing.
                    context = {
                        "drying": QApplication.translate("tilauscope_beancave",
                            "If the cup tastes grassy or green, give the beans a little longer to dry before browning."),
                        "maillard": QApplication.translate("tilauscope_beancave",
                            "Less time for caramelization — body may be lighter and acidity sharper."),
                        "development": QApplication.translate("tilauscope_beancave",
                            "Below the professional minimum for this level — real under-development risk (grassy/baked). Carry more momentum into first crack or drop a little later."),
                    }.get(phase_key, "")
                    advice_rows += advice_row("⏱",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'shorter than usual')}"
                        + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {lvl_label} — {context}",
                        "warn")
                elif actual_min > mx + grace:
                    context = {
                        "drying": QApplication.translate("tilauscope_beancave",
                            "Long drying can reduce caramelization potential and flatten sweetness."),
                        "maillard": QApplication.translate("tilauscope_beancave",
                            "Excessive Maillard may push toward flat, bready notes."),
                        "development": QApplication.translate("tilauscope_beancave",
                            "Over-development: roasty, dark tones may dominate origin character."),
                    }.get(phase_key, "")
                    advice_rows += advice_row("⏱",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'longer than usual')}"
                        + f" ({actual_min:.1f} min, {range_lbl} {mn:.1f}–{mx:.1f} min) {lvl_label} — {context}",
                        "warn")
                else:
                    advice_rows += advice_row("✓",
                        f"{phase_tr} {QApplication.translate('tilauscope_beancave', 'on target')}"
                        + f" ({actual_min:.1f} min)", "ok")

        # ── 4. Cross-check: Drop BT vs DTR consistency ────────────────────────────
        # A low drop temperature is the *goal* on a light roast, so it is only a
        # concern when it lands below the window expected for the target level AND
        # the development ratio is also short — two independent signals agreeing.
        # That concordance is what earns the red flag; either one alone does not.
        drop_bt_val = computed.get('DROP_BT', None)
        if drop_bt_val and dtr_pct_val > 0:
            try:
                drop_bt_f = float(drop_bt_val)
                drop_low_c, drop_high_c = lvl_th['drop_c']
                if mode == 'F':
                    drop_low  = drop_low_c * 9.0 / 5.0 + 32.0
                    drop_high = drop_high_c * 9.0 / 5.0 + 32.0
                else:
                    drop_low, drop_high = drop_low_c, drop_high_c
                if drop_bt_f < drop_low and dtr_pct_val < lvl_dtr_min:
                    advice_rows += advice_row("🔴",
                        QApplication.translate("tilauscope_beancave",
                            "Both the drop temperature and the development ratio land below the "
                            "window expected for this roast level — two signals agreeing on "
                            "under-development. Watch for grassy or baked notes; consider a hotter "
                            "charge or a slower Maillard.") + f" {lvl_label}",
                        "bad")
                elif drop_bt_f > drop_high and dtr_pct_val < lvl_dtr_min:
                    advice_rows += advice_row("🔶",
                        QApplication.translate("tilauscope_beancave",
                            "Drop temperature is higher than expected for this level yet the "
                            "development ratio is short — the bean colour may be darker than "
                            "intended. Watch for scorching; reduce end-heat or drop earlier.") + f" {lvl_label}",
                        "warn")
            except (TypeError, ValueError):
                pass

        # ── 5. RoR at drop — check for crash/flick ────────────────────────────────
        # 5a. RoR at the onset of first crack — momentum entering development.
        #     Roaster-agnostic: a flat/negative RoR at FCs means the bean enters
        #     development with no thermal momentum (stall/crash risk), regardless
        #     of roaster type. No absolute "high" threshold is used here on purpose.
        fcs_ror = computed.get('fcs_ror', None)
        if fcs_ror is not None:
            try:
                fcs_ror_v = float(fcs_ror)
                if fcs_ror_v <= 0:
                    advice_rows += advice_row("🧊",
                        QApplication.translate("tilauscope_beancave",
                            "Flat or negative RoR entering first crack: the roast lost momentum "
                            "right at FC, a strong stall/crash signal. Add a touch of heat just "
                            "before FC next time to carry momentum into development."),
                        "bad")
                elif fcs_ror_v < 2.0 * (1.8 if mode == 'F' else 1.0):
                    # threshold in the log's own unit (2 °C/min ≈ 3.6 °F/min) —
                    # previously the advice was silently disabled on °F logs
                    advice_rows += advice_row("🐌",
                        QApplication.translate("tilauscope_beancave",
                            "Low RoR entering first crack: little momentum into "
                            "development — watch for a stall and baked, flat character."),
                        "warn")
            except (TypeError, ValueError):
                pass

        ror_finish = computed.get('finish_phase_ror', None)
        ror_mid = computed.get('mid_phase_ror', None)
        if ror_finish is not None and ror_mid is not None:
            try:
                ror_f = float(ror_finish)
                ror_m = float(ror_mid)
                if ror_f < 0:
                    advice_rows += advice_row("📉",
                        QApplication.translate("tilauscope_beancave",
                            "Negative RoR in development: temperature crashed before drop. "
                            "This can cause baked character. Maintain at least 1–2°/min through drop."),
                        "bad")
                elif ror_m > 0 and ror_f > ror_m * 1.4:
                    advice_rows += advice_row("📈",
                        QApplication.translate("tilauscope_beancave",
                            "RoR flick detected: rate accelerated significantly in development. "
                            "This may indicate a heat spike. Reduce burner earlier to avoid scorching."),
                        "warn")
            except (TypeError, ValueError):
                pass

        # ── 6. Density context ────────────────────────────────────────────────────
        selected_rows_chk = self.datatable.selectionModel().selectedRows()
        if selected_rows_chk and self.cave and selected_rows_chk[0].row() < len(self.cave.green_beans):
            chk_bean = self.cave.green_beans[selected_rows_chk[0].row()]
            if chk_bean.density > 780:
                advice_rows += advice_row("💎",
                    QApplication.translate("tilauscope_beancave",
                        "Very high density bean (>780 g/l): needs strong initial charge energy. "
                        "If DTR or weight loss is low, consider raising charge temp by 5–8°C next roast."),
                    "info")
            elif 0 < chk_bean.density < 650:
                advice_rows += advice_row("🪶",
                    QApplication.translate("tilauscope_beancave",
                        "Low density bean (<650 g/l): absorbs heat quickly — watch for early FC. "
                        "Reduce heat in Maillard to avoid rushing development."),
                    "info")

        if not advice_rows:
            advice_rows = advice_row("✓",
                QApplication.translate("tilauscope_beancave",
                    "All measured parameters are within the recommended ranges."), "ok")
        selected_rows_chk = self.datatable.selectionModel().selectedRows()
        if selected_rows_chk and self.cave:
            chk_bean = self.cave.green_beans[selected_rows_chk[0].row()]
            if chk_bean.density > 750:
                advice_rows += advice_row("i",
                    QApplication.translate("tilauscope_beancave",
                        "<li><b>High Density:</b> Ensure high energy at start to penetrate the core.</li>")
                    .replace("<li>", "").replace("</li>", "")
                    .replace("<b>", "").replace("</b>", ""), "info")

        if not advice_rows:
            advice_rows = advice_row("✓",
                QApplication.translate("tilauscope_beancave",
                    "✅ All the phases are within the recommendation ranges"), "ok")

        # ── Translated labels ─────────────────────────────────────────────
        _total_time   = QApplication.translate("tilauscope_beancave", "Total Time")
        _weight_loss_l= QApplication.translate("tilauscope_beancave", "Weight loss")
        _bean_weight  = QApplication.translate("tilauscope_beancave", "Green beans weight")
        _roast_weight = QApplication.translate("tilauscope_beancave", "Roasted weight")
        _charge_bt    = QApplication.translate("tilauscope_beancave", "Charge BT")
        _tp           = QApplication.translate("tilauscope_beancave", "Turn Point BT")
        _de           = QApplication.translate("tilauscope_beancave", "Dry End BT")
        _fc           = QApplication.translate("tilauscope_beancave", "FCs BT")
        _drop         = QApplication.translate("tilauscope_beancave", "Drop BT")
        _ror_dry      = QApplication.translate("tilauscope_beancave", "RoR Dry Phase")
        _ror_mai      = QApplication.translate("tilauscope_beancave", "RoR Mid Phase")
        _ror_dev      = QApplication.translate("tilauscope_beancave", "RoR Finish Phase")
        _ror_total    = QApplication.translate("tilauscope_beancave", "RoR Total")
        _auc_dry      = QApplication.translate("tilauscope_beancave", "AUC Dry Phase")
        _auc_middle   = QApplication.translate("tilauscope_beancave", "AUC Maillard Phase")
        _auc_fc       = QApplication.translate("tilauscope_beancave", "AUC Finish phase")
        _auc_total    = QApplication.translate("tilauscope_beancave", "AUC Total")
        _auc_begin    = QApplication.translate("tilauscope_beancave", " - AUC begins from ") if auc_start_str else ""
        _coach_lbl    = QApplication.translate("tilauscope_beancave", "Coach's Advice 🎯") \
                            .replace("<h3>","").replace("</h3>","")
        _weight_inout = f"{_bean_weight} → {_roast_weight}"

        # badges pour les metric cards
        # Badges use the exact same effective windows as the advice above.
        wl_text, wl_kind   = wl_badge_text(wl_val, wl_lo_eff, wl_hi_eff)
        dtr_text, dtr_kind = dtr_badge_text(dtr_pct_val, lvl_dtr_min, lvl_dtr_max)

        auc_suffix = f"{_auc_begin}{auc_start_str}" if auc_start_str else ""

        # ── RoR par phase : 3 metric cards côte à côte ────────────────────
        ror_cards = (
            f'<tr>'
            + metric_card(_ror_dry,
                        f"{get_ror('dry_phase_ror')} °/min")
            + metric_card(_ror_mai,
                        f"{get_ror('mid_phase_ror')} °/min")
            + metric_card(_ror_dev,
                        f"{get_ror('finish_phase_ror')} °/min")
            + metric_card(_ror_total,
                        f"{get_ror('total_ror')} °/min")
            + f'</tr>'
        )

        # ── Assembly ──────────────────────────────────────────────────────
        summary = f"""<html><body style="
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: {THEME['TEXT']};
            background-color: {THEME['BG']};
            margin: 0; padding: 8px;">

    <table width="100%" cellpadding="0" cellspacing="0">

    <!-- HEADER -->
    <tr>
    <td colspan="3" style="padding-bottom:4px;">
        <span style="font-size:14px; font-weight:bold;">{data.get('title','—')}</span>
        {f' &nbsp;<span style="font-size:11px; font-weight:bold; padding:2px 7px; border-radius:4px; background-color:{THEME["ACCENT"]}; color:{THEME["BG"]}">{batch_prefix}{batch_nr}</span>' if batch_nr > 0 else ''}<br/>
        <span style="font-size:11px; color:{THEME['SUBTEXT']};">{date} {roasttime} · {roastertype}</span>
    </td>
    <td align="right" style="vertical-align:top; padding-bottom:4px; white-space:nowrap;">
        {badge(colour_badge_txt, "accent")}
        {f'<br/><span style="font-size:10px; color:{THEME["SUBTEXT"]};">{colour_detail}</span>' if colour_detail else ''}
        <br/><span style="font-size:10px; color:{THEME['SUBTEXT']};">{agtron_label}</span>
    </td>
    </tr>
    <tr><td colspan="4">
    <hr style="border:none; border-top:1px solid {THEME['BORDER']}; margin:4px 0 8px 0;"/>
    </td></tr>

    <!-- RÉSUMÉ : 4 metric cards -->
    {section_title(QApplication.translate("tilauscope_beancave","Summary"))}
    <tr>
    {metric_card(_total_time,
                f"{self.format_seconds(total)}",f"({round(total/60,1)} min)")}
    {metric_card(_weight_loss_l,
                f"{wl_val:.1f} %" if wl_val else "N/A",
                wl_text, wl_kind)}
    {metric_card("DTR",
                f"{dtr_pct_val:.1f} %" if dtr_pct_val else "N/A",
                dtr_text, dtr_kind)}
    {metric_card(_weight_inout,
                f"{computed.get('weightin','?')}{charge_unit} → {computed.get('weightout','?')}{charge_unit}",f"({QApplication.translate("Label","Defects")} {defect_weight}{charge_unit})")}
    </tr>

    <!-- PHASES -->
    {section_title(QApplication.translate("tilauscope_beancave","Phases"))}
    {phase_bar_html}

    <!-- TEMPÉRATURES -->
    {section_title(QApplication.translate("tilauscope_beancave","Charge BT").replace(" BT","") + " & Drop")}
    <tr>
    <td colspan="2" style="vertical-align:top; padding-right:1px;">
        <table cellpadding="0" cellspacing="0">
        {kv_row(_charge_bt,  f"{computed.get('CHARGE_BT','N/A')} °{mode}")}
        {kv_row(_tp,         f"{computed.get('TP_BT','N/A')} °{mode} · {self.format_seconds(computed.get('TP_time',0))}")}
        {kv_row(_de,         f"{computed.get('DRY_BT','N/A')} °{mode}")}
        {kv_row(_fc,         f"{computed.get('FCs_BT','N/A')} °{mode}")}
        {kv_row(_drop,       f"{computed.get('DROP_BT','N/A')} °{mode}")}
        </table>
    </td>
    <td colspan="2" style="vertical-align:top;">
        <table cellpadding="0" cellspacing="0" width="100%">
        {kv_row(_auc_dry,    f"{drying_auc} °{mode}")}
        {kv_row(_auc_middle, f"{middle_auc} °{mode}")}
        {kv_row(_auc_fc,     f"{fcs_drop} °{mode}")}
        {kv_row(_auc_total,  f"{total_auc} °{mode}{auc_suffix}")}
        </table>
    </td>
    </tr>

    <!-- RoR PAR PHASE : 4 metric cards -->
    {section_title(QApplication.translate("tilauscope_beancave","RoR Dry Phase").replace(" Dry Phase","") + " / phase")}
    {ror_cards}

    <!-- CONSEILS -->
    {section_title(_coach_lbl)}
    {advice_rows}

    </table>
    </body></html>"""

        self.roast_info_text.setText(summary)
   
    @staticmethod
    def format_seconds(seconds: float) -> str:
        return f"{int(seconds // 60)}:{int(round(seconds % 60)):02d}"

    def _extract_roast_metrics(self, data: dict) -> dict:
        c = data.get('computed', {})
        mode = data.get('mode', 'C')
        t_charge = 0
        t_dry    = c.get('DRY_time', 0) or 0
        t_fcs    = c.get('FCs_time', 0) or 0
        t_drop   = c.get('DROP_time', 0) or 0
        drying      = t_dry - t_charge
        maillard    = t_fcs - t_dry
        development = t_drop - t_fcs
        total       = t_drop - t_charge
        dtr  = round(100 * development / total, 1) if total > 0 else 0.0
        wl   = c.get('weight_loss', None)
        try: wl = round(float(wl), 1) if wl not in (None, 0.0, 'N/A') else None
        except: wl = None
        def _ror(key):
            v = c.get(key, None)
            try: return round(float(v), 2) if v not in (None, 'N/A') else None
            except: return None
        def _fmt_s(s):
            s = int(s or 0)
            return f"{s//60}:{s%60:02d}"
        charge_w = data.get('weight', [None, None, ''])
        try: w_in  = float(charge_w[0]) if charge_w[0] else None
        except: w_in = None
        try: w_out = float(charge_w[1]) if charge_w[1] else None
        except: w_out = None
        w_unit = charge_w[2] if len(charge_w) > 2 else 'g'
        def _bt(key):
            v = c.get(key, None)
            try: return round(float(v), 1) if v not in (None, 'N/A', 0) else None
            except: return None
        def _auc(key):
            # AUC (area under BT curve above the configured base) — absolute value
            # depends on the user's AUCbase setting, but is consistent across the
            # user's own roasts, so it is surfaced as a consistency metric only.
            v = c.get(key, None)
            try: return int(round(float(v))) if v not in (None, 'N/A', 0) else None
            except: return None
        return {
            'title': data.get('title', '?'), 'date': data.get('roastdate', ''),
            'mode': mode, 'total_s': total, 'total_fmt': _fmt_s(total),
            'drying_s': drying, 'drying_fmt': _fmt_s(drying),
            'drying_pct': round(100*drying/total,1) if total>0 else 0,
            'maillard_s': maillard, 'maillard_fmt': _fmt_s(maillard),
            'maillard_pct': round(100*maillard/total,1) if total>0 else 0,
            'dev_s': development, 'dev_fmt': _fmt_s(development), 'dtr': dtr,
            'wl': wl, 'charge_bt': _bt('CHARGE_BT'), 'drop_bt': _bt('DROP_BT'),
            'tp_bt': _bt('TP_BT'), 'tp_fmt': _fmt_s(c.get('TP_time', 0) or 0),
            'ror_dry': _ror('dry_phase_ror'), 'ror_mid': _ror('mid_phase_ror'),
            'ror_fin': _ror('finish_phase_ror'), 'ror_total': _ror('total_ror'),
            'auc_total': _auc('AUC'), 'auc_dry': _auc('dry_phase_AUC'),
            'auc_mid': _auc('mid_phase_AUC'), 'auc_fin': _auc('finish_phase_AUC'),
            'w_in': w_in, 'w_out': w_out, 'w_unit': w_unit,
        }

    def _generate_multi_coach_advice(self, metrics: list) -> list:
        advices = []
        OK, WARN, INFO = '#A6E3A1', '#F38BA8', '#89DCEB'
        def _c(col, txt): return f'<span style="color:{col};font-weight:600;">{txt}</span>'
        mode = metrics[0].get('mode', 'C') if metrics else 'C'
        tscale = 1.8 if mode == 'F' else 1.0   # cibles/écarts en ° pour le Fahrenheit
        dtrs = [(m['title'][:22], m['dtr']) for m in metrics if m['dtr']]
        if dtrs:
            best  = min(dtrs, key=lambda x: abs(x[1]-20))
            worst = max(dtrs, key=lambda x: abs(x[1]-20))
            advices.append(QApplication.translate("tilauscope_beancave",
                "DTR closest to 20%: {best} ({bv:.1f}%) — furthest: {worst} ({wv:.1f}%)").format(
                    best=_c(OK, best[0]), bv=best[1], worst=_c(WARN, worst[0]), wv=worst[1]))
        wls = [(m['title'][:22], m['wl']) for m in metrics if m['wl']]
        if wls:
            best = min(wls, key=lambda x: abs(x[1]-15))
            advices.append(QApplication.translate("tilauscope_beancave",
                "Weight loss closest to 15%: {best} ({bv:.1f}%)").format(
                    best=_c(OK, best[0]), bv=best[1]))
        rors = [(m['title'][:22], m['ror_total']) for m in metrics if m['ror_total']]
        if rors:
            target = 9 * tscale
            best  = min(rors, key=lambda x: abs(x[1]-target))
            worst = max(rors, key=lambda x: abs(x[1]-target))
            if best[0] != worst[0]:
                advices.append(QApplication.translate("tilauscope_beancave",
                    "RoR Total closest to {tgt:.0f}°/min: {best} ({bv:.2f}) — furthest: {worst} ({wv:.2f})").format(
                        tgt=target, best=_c(OK, best[0]), bv=best[1], worst=_c(WARN, worst[0]), wv=worst[1]))
        drops = [(m['title'][:22], m['drop_bt']) for m in metrics if m['drop_bt']]
        if len(drops) >= 2:
            spread = max(d[1] for d in drops) - min(d[1] for d in drops)
            ok = spread < 5 * tscale
            note = (QApplication.translate("tilauscope_beancave", "consistent ✓") if ok
                    else QApplication.translate("tilauscope_beancave", "variable — check profile consistency"))
            advices.append(QApplication.translate("tilauscope_beancave", "Drop BT spread: {v} — {note}").format(
                v=_c(OK if ok else WARN, f"{spread:.1f}°{mode}"), note=note))
        devs = [(m['title'][:22], m['dev_s']) for m in metrics if m['dev_s']]
        if devs:
            spread_s = max(d[1] for d in devs) - min(d[1] for d in devs)
            mm, ss = int(spread_s)//60, int(spread_s)%60
            ok = spread_s < 30
            note = (QApplication.translate("tilauscope_beancave", "tight ✓") if ok
                    else QApplication.translate("tilauscope_beancave", "consider aligning development phases"))
            advices.append(QApplication.translate("tilauscope_beancave", "Development spread: {v} — {note}").format(
                v=_c(OK if ok else INFO, f"{mm}:{ss:02d}"), note=note))
        return advices

    def _detect_crash_flick(self, data: dict, deltabt: list) -> "str | None":
        """Détecte un accident de RoR en phase de développement (FCs→DROP) :
        'crash' (RoR s'effondre vers 0), 'flick' (RoR rebondit), ou les deux.
        RoR lissé pour éviter les faux positifs ; None si propre."""
        if not data or not deltabt:
            return None
        ti = (list(data.get('timeindex', [])) + [-1] * 8)[:8]
        fcs, drop = ti[RoastingPhase.FCSTART], ti[RoastingPhase.DROP]
        if fcs <= 0 or drop <= fcs:
            return None
        seg = [deltabt[k] for k in range(fcs, min(drop, len(deltabt)))
               if k < len(deltabt) and deltabt[k] is not None]
        if len(seg) < 6:
            return None
        w = 5  # lissage ~5 s
        r = [sum(seg[max(0, k - w + 1):k + 1]) / len(seg[max(0, k - w + 1):k + 1])
             for k in range(len(seg))]
        # Seuils en °/min → mis à l'échelle pour le Fahrenheit (ΔT_F = 1.8·ΔT_C).
        tscale = 1.8 if data.get('mode', 'C') == 'F' else 1.0
        r_min = min(r)
        i_min = r.index(r_min)
        crash = r_min <= 1.0 * tscale                          # RoR tombé à ~0/négatif
        flick = (max(r[i_min:]) - r_min) >= 2.0 * tscale and i_min <= len(r) - 3
        if crash and flick:
            return 'crash+flick'
        if crash:
            return 'crash'
        if flick:
            return 'flick'
        return None

    def _generate_multi_analysis(self, metrics: list) -> str:
        """Analyse en clair (1 paragraphe) de la comparaison : verdict de régularité,
        principal écart, note sur le ratio de développement, accidents de RoR.
        Déterministe."""
        n = len(metrics)
        if n < 2:
            return ""
        OK, WARN, ACC = '#A6E3A1', '#F38BA8', '#89B4FA'
        mode = metrics[0].get('mode', 'C')
        tscale = 1.8 if mode == 'F' else 1.0   # seuils en ° pour le Fahrenheit
        drop_tol = 5 * tscale
        def _c(col, t): return f'<span style="color:{col};font-weight:600;">{t}</span>'
        def _spread(key):
            vals = [m[key] for m in metrics if m.get(key) is not None]
            return (max(vals) - min(vals)) if len(vals) >= 2 else None
        drop_sp, dev_sp = _spread('drop_bt'), _spread('dev_s')
        dtr_sp, tot_sp = _spread('dtr'), _spread('total_s')

        # Verdict de régularité : combien de dimensions sont serrées.
        checks = []
        for sp, tol in ((drop_sp, drop_tol), (dev_sp, 30), (dtr_sp, 3), (tot_sp, 45)):
            if sp is not None:
                checks.append(sp < tol)
        tight = sum(checks)
        if checks and tight == len(checks):
            verdict = QApplication.translate("tilauscope_beancave", "very consistent")
            vcol = OK
        elif checks and tight >= len(checks) * 0.6:
            verdict = QApplication.translate("tilauscope_beancave", "fairly consistent")
            vcol = OK
        else:
            verdict = QApplication.translate("tilauscope_beancave", "uneven")
            vcol = WARN
        parts = [QApplication.translate("tilauscope_beancave",
                 "These {n} roasts are {verdict}.").format(n=n, verdict=_c(vcol, verdict))]

        # Principal écart (rapporté à sa tolérance).
        issues = []
        if drop_sp is not None and drop_sp >= drop_tol:
            issues.append((QApplication.translate("tilauscope_beancave", "drop temperature"),
                           f"{drop_sp:.0f}°{mode}", drop_sp / drop_tol))
        if dev_sp is not None and dev_sp >= 30:
            issues.append((QApplication.translate("tilauscope_beancave", "development time"),
                           f"{int(dev_sp)//60}:{int(dev_sp)%60:02d}", dev_sp / 30))
        if dtr_sp is not None and dtr_sp >= 3:
            issues.append((QApplication.translate("tilauscope_beancave", "development ratio"),
                           f"{dtr_sp:.0f} pts", dtr_sp / 3))
        if tot_sp is not None and tot_sp >= 45:
            issues.append((QApplication.translate("tilauscope_beancave", "total time"),
                           f"{int(tot_sp)//60}:{int(tot_sp)%60:02d}", tot_sp / 45))
        if issues:
            issues.sort(key=lambda x: -x[2])
            name, val, _ = issues[0]
            parts.append(QApplication.translate("tilauscope_beancave",
                         "The biggest difference is in {name} ({val} spread).").format(
                             name=name, val=_c(WARN, val)))
        else:
            parts.append(QApplication.translate("tilauscope_beancave",
                         "All the key milestones line up closely."))

        # Note sur le ratio de développement (cible ~18–22%).
        dtrs = [m['dtr'] for m in metrics if m.get('dtr')]
        if dtrs:
            avg = sum(dtrs) / len(dtrs)
            if avg < 17:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios average {v} — a touch low; a longer development "
                    "could add sweetness.").format(v=_c(ACC, f"{avg:.0f}%")))
            elif avg > 23:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios average {v} — on the high side; a shorter "
                    "development would brighten the cup.").format(v=_c(ACC, f"{avg:.0f}%")))
            else:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Development ratios sit around {v}, in the usual window.").format(
                        v=_c(ACC, f"{avg:.0f}%")))

        # Accidents de RoR (crash / flick) en développement.
        cf = []
        for c in (c for c in self._multi_curves if c.get('data')):
            lab = self._detect_crash_flick(c['data'], c.get('deltabt') or [])
            if lab:
                cf.append((c['title'], lab))
        if not cf:
            parts.append(_c(OK, QApplication.translate("tilauscope_beancave",
                "All roasts keep a clean, declining RoR through development.")))
        else:
            kinds = set()
            for _, lab in cf:
                if 'crash' in lab:
                    kinds.add(QApplication.translate("tilauscope_beancave", "crash"))
                if 'flick' in lab:
                    kinds.add(QApplication.translate("tilauscope_beancave", "flick"))
            kind = " / ".join(sorted(kinds))
            if len(cf) == 1:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "Roast {name} shows a RoR {kind} after first crack — watch for "
                    "stalled, uneven development.").format(
                        name=cf[0][0][:22], kind=_c(WARN, kind)))
            else:
                parts.append(QApplication.translate("tilauscope_beancave",
                    "{k} of {n} roasts show a RoR {kind} after first crack — watch for "
                    "stalled, uneven development.").format(
                        k=len(cf), n=n, kind=_c(WARN, kind)))
        return " ".join(parts)

    def _set_stats_view(self, multi: bool) -> None:
        """Bascule l'onglet Advanced Stats : vue HTML (mono) ↔ dot plot (multi)."""
        if hasattr(self, 'stats_scroll'):
            self.stats_scroll.setVisible(not multi)
        if hasattr(self, 'stats_multi_widget'):
            self.stats_multi_widget.setVisible(multi)

    # Métriques du dot plot multi : (label, clé, formateur de valeur)
    def _render_multi_dotplot(self) -> None:
        """Dot plot comparatif (Advanced Stats multi) : une ligne par métrique,
        un point par roast (sa teinte), référence en anneau. Échelle propre par
        ligne. Remplace l'ancien tableau, trop chargé pour un amateur."""
        metrics = [self._extract_roast_metrics(c['data'])
                   for c in self._multi_curves if c.get('data')]
        fig = self.stats_dot_fig
        fig.clear()
        fig.set_facecolor(_PLOT_PALETTE['background'])
        if not metrics:
            self.stats_dot_canvas.draw_idle()
            self.stats_summary.setText("")
            return
        palette = self._make_multi_palette(len(metrics))
        ax = fig.add_subplot(111)
        ax.set_facecolor(_PLOT_PALETTE['background'])

        def _t(s):
            return self.format_seconds(s or 0)
        # Réutilise les sources de traduction existantes (artisan_fr.ts) :
        # Total/Drying/Maillard/DTR/Weight loss → [tilauscope_beancave],
        # Development → [Label].
        rows = [
            (QApplication.translate("tilauscope_beancave", "Total"),       'total_s',    _t),
            (QApplication.translate("tilauscope_beancave", "Drying"),      'drying_s',   _t),
            (QApplication.translate("tilauscope_beancave", "Maillard"),    'maillard_s', _t),
            (QApplication.translate("Label", "Development"),               'dev_s',      _t),
            (QApplication.translate("tilauscope_beancave", "DTR") + " %",  'dtr',     lambda v: f"{v:.0f}%"),
            (QApplication.translate("tilauscope_beancave", "Drop BT"),     'drop_bt', lambda v: f"{v:.0f}°"),
            (QApplication.translate("tilauscope_beancave", "Weight loss") + " %", 'wl', lambda v: f"{v:.0f}%"),
        ]
        # Roast area (AUC) — added only when the roasts carry the data. The dot
        # plot normalises each row by its own min/max, so AUC is shown purely as
        # a consistency spread (the absolute value depends on the AUCbase setting
        # and is not roaster-comparable). Kept to two rows to stay uncluttered.
        _auc_fmt = lambda v: f"{v:.0f}"
        for label, key in ((QApplication.translate("tilauscope_beancave", "Area total"),       'auc_total'),
                           (QApplication.translate("tilauscope_beancave", "Area development"), 'auc_fin')):
            if any(m.get(key) is not None for m in metrics):
                rows.append((label, key, _auc_fmt))
        nrows = len(rows)
        from matplotlib.colors import to_hex, to_rgba
        muted = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 0.6), keep_alpha=True)
        ylabels = []
        for r_idx, (label, key, fmt) in enumerate(rows):
            y = nrows - 1 - r_idx
            ylabels.append(label)
            vals = [(j, m.get(key)) for j, m in enumerate(metrics)]
            nums = [v for _, v in vals if v is not None]
            if not nums:
                continue
            lo, hi = min(nums), max(nums)
            span = hi - lo
            ax.plot([0.12, 0.88], [y, y], color=_PLOT_PALETTE['grid'], lw=1, alpha=0.5, zorder=1)
            ax.text(0.10, y, fmt(lo), ha='right', va='center', fontsize=_FS_TICK - 1, color=muted)
            ax.text(0.90, y, fmt(hi), ha='left',  va='center', fontsize=_FS_TICK - 1, color=muted)
            for j, v in vals:
                if v is None:
                    continue
                norm = (v - lo) / span if span > 0 else 0.5
                x = 0.12 + norm * 0.76
                is_ref = (j == 0)
                ax.scatter([x], [y], s=95 if is_ref else 55, zorder=5,
                           facecolors=palette[j][0],
                           edgecolors='#CDD6F4' if is_ref else palette[j][0],
                           linewidths=1.7 if is_ref else 0)
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.6, nrows - 0.4)
        ax.set_xticks([])
        ax.set_yticks(range(nrows))
        ax.set_yticklabels(list(reversed(ylabels)), fontsize=_FS_TICK,
                           color=_PLOT_PALETTE['ylabel'])
        ax.tick_params(axis='y', length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(QApplication.translate("tilauscope_beancave",
                     "Comparison — ◉ = reference roast"),
                     fontsize=_FS_AXIS, color=_PLOT_PALETTE['title'])
        self.stats_dot_canvas.draw_idle()

        # Mini-résumé : analyse en clair + écarts notables vs référence.
        analysis = self._generate_multi_analysis(metrics)
        advices = self._generate_multi_coach_advice(metrics)
        html = '<div style="color:#CDD6F4;font-size:12px;font-family:sans-serif;">'
        if analysis:
            html += ('<b style="color:#89B4FA;">' +
                     QApplication.translate("tilauscope_beancave", "Analysis") +
                     f'</b><p style="margin:3px 0 8px 0;line-height:1.4;">{analysis}</p>')
        if advices:
            items = ''.join(f'<li style="margin-bottom:3px;">{a}</li>' for a in advices)
            html += ('<b style="color:#89B4FA;">' +
                     QApplication.translate("tilauscope_beancave", "Notable differences") +
                     f'</b><ul style="margin:4px 0 0 0;padding-left:18px;">{items}</ul>')
        html += '</div>'
        self.stats_summary.setText(html if (analysis or advices) else "")

    def _multi_stats_html(self) -> str:
        if not self._multi_curves:
            return ""
        metrics = [self._extract_roast_metrics(c['data']) for c in self._multi_curves if c.get('data')]
        if not metrics:
            return ""
        n = len(metrics)
        mode = metrics[0]['mode']
        palette = self._make_multi_palette(n)
        TD='#181825'; TH='#1e1e2e'; HDR='#313244'
        BEST_BG='rgba(166,227,161,0.18)'; WARN_BG='rgba(243,139,168,0.15)'
        BEST='#A6E3A1'; WARN='#F38BA8'; NEUT='#CDD6F4'; MUTED='#9399B2'
        F="font-family:'SF Pro Display','Segoe UI',sans-serif;"
        def th(t, w=''):
            ws=f'width:{w};' if w else ''
            return f'<th style="background:{HDR};color:{NEUT};padding:7px 10px;text-align:left;font-size:11px;font-weight:600;border-bottom:1px solid #45475A;{ws}{F}">{t}</th>'
        def lc(t):
            return f'<td style="background:{TH};color:{MUTED};padding:6px 10px;font-size:11px;white-space:nowrap;border-bottom:1px solid #2a2a3a;{F}">{t}</td>'
        def vc(t, bg=None, color=None, bold=False):
            bg=bg or TD; color=color or NEUT; fw='font-weight:700;' if bold else ''
            return f'<td style="background:{bg};color:{color};padding:6px 10px;font-size:12px;text-align:right;border-bottom:1px solid #2a2a3a;{fw}{F}">{t}</td>'
        def sec(t):
            return f'<tr><td colspan="{n+1}" style="background:#252536;color:#89B4FA;padding:5px 10px;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;border-top:1px solid #45475A;{F}">{t}</td></tr>'
        def hrow(label, vals, ideal=None, lower_better=False, fmt=str, warn_fn=None, unit=''):
            nums=[v for v in vals if v is not None]
            cells=[]
            for v in vals:
                if v is None: cells.append(vc('\u2014', color=MUTED)); continue
                bg2=TD; col2=NEUT; bold=False
                if ideal is not None and nums:
                    bv=min(nums, key=lambda x:abs(x-ideal))
                    if v==bv: bg2,col2,bold=BEST_BG,BEST,True
                elif lower_better and nums:
                    if v==min(nums): bg2,col2,bold=BEST_BG,BEST,True
                if warn_fn and warn_fn(v): bg2,col2=WARN_BG,WARN
                cells.append(vc(f'{fmt(v)}{unit}',bg=bg2,color=col2,bold=bold))
            return '<tr>'+lc(label)+''.join(cells)+'</tr>'
        # header
        hdr='<tr>'+th('Metric','150px')
        for i,m in enumerate(metrics):
            bt_col=palette[i][0]
            short=m['title'][:26]+'\u2026' if len(m['title'])>26 else m['title']
            hdr+=f'<th style="background:{HDR};color:{bt_col};padding:7px 10px;font-size:11px;font-weight:700;border-bottom:1px solid #45475A;text-align:right;{F}" title="{m["title"]}">{short}</th>'
        hdr+='</tr>'
        rows=hdr
        rows+=sec('\u23f1 TIME')
        rows+=hrow('Total',    [m['total_s']    for m in metrics], ideal=sum(m['total_s']    for m in metrics)/n, fmt=lambda x: next(m['total_fmt']    for m in metrics if m['total_s']   ==x))
        rows+=hrow('Drying',   [m['drying_s']   for m in metrics], ideal=sum(m['drying_s']   for m in metrics)/n, fmt=lambda x: next(m['drying_fmt']   for m in metrics if m['drying_s']  ==x))
        rows+=hrow('Maillard', [m['maillard_s'] for m in metrics], ideal=sum(m['maillard_s'] for m in metrics)/n, fmt=lambda x: next(m['maillard_fmt'] for m in metrics if m['maillard_s']==x))
        rows+=hrow('Development',[m['dev_s']    for m in metrics], ideal=sum(m['dev_s']      for m in metrics)/n, fmt=lambda x: next(m['dev_fmt']      for m in metrics if m['dev_s']     ==x))
        rows+=sec('\U0001f4ca KEY RATIOS')
        rows+=hrow('DTR %',       [m['dtr'] for m in metrics], ideal=20.0, warn_fn=lambda v:v<15 or v>25, fmt=lambda x:f'{x:.1f}', unit=' %')
        rows+=hrow('Weight loss', [m['wl']  for m in metrics], ideal=15.0, warn_fn=lambda v:v is not None and (v<12 or v>18), fmt=lambda x:f'{x:.1f}', unit=' %')
        rows+=sec(f'\U0001f321 TEMPERATURES (\u00b0{mode})')
        cb_avg = sum(m['charge_bt'] for m in metrics if m['charge_bt'])/max(1,sum(1 for m in metrics if m['charge_bt']))
        db_avg = sum(m['drop_bt']   for m in metrics if m['drop_bt']  )/max(1,sum(1 for m in metrics if m['drop_bt']))
        rows+=hrow('Charge BT',  [m['charge_bt'] for m in metrics], ideal=cb_avg, fmt=lambda x:f'{x:.1f}')
        rows+=hrow('Turn Point', [m['tp_bt']     for m in metrics], lower_better=True, fmt=lambda x:f'{x:.1f}')
        rows+=hrow('Drop BT',    [m['drop_bt']   for m in metrics], ideal=db_avg, fmt=lambda x:f'{x:.1f}')
        rows+=sec('\U0001f525 ROR (\u00b0/min)')
        rows+=hrow('RoR Dry',      [m['ror_dry']   for m in metrics], ideal=12.0, fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Maillard', [m['ror_mid']   for m in metrics], ideal=9.0,  fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Finish',   [m['ror_fin']   for m in metrics], ideal=5.0,  fmt=lambda x:f'{x:.2f}')
        rows+=hrow('RoR Total',    [m['ror_total'] for m in metrics], ideal=9.0,  fmt=lambda x:f'{x:.2f}')
        rows+=sec('\u2696 WEIGHT')
        wcells=[]
        for m in metrics:
            if m['w_in'] and m['w_out']: wcells.append(vc(f"{m['w_in']:.0f}\u2192{m['w_out']:.0f} {m['w_unit']}"))
            else: wcells.append(vc('\u2014', color=MUTED))
        rows+='<tr>'+lc('Green \u2192 Roasted')+''.join(wcells)+'</tr>'
        table=f'<table style="width:100%;border-collapse:collapse;">{rows}</table>'
        # coach advice
        advices=self._generate_multi_coach_advice(metrics)
        coach_html=''
        if advices:
            items=''.join(f'<li style="padding:4px 0;color:{NEUT};font-size:12px;border-bottom:1px solid #2a2a3a;{F}">{a}</li>' for a in advices)
            coach_html=(f'<div style="margin-top:16px;">'
                f'<div style="color:#89B4FA;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:6px 10px;background:#252536;border-radius:6px 6px 0 0;">'
                f'\U0001f9d1\u200d\U0001f3eb COACH\'S COMPARATIVE ADVICE</div>'
                f'<ul style="list-style:none;margin:0;padding:8px 12px;background:{TD};border-radius:0 0 6px 6px;">{items}</ul></div>')
        return f'<div style="padding:8px;">{table}{coach_html}</div>'


    def plot_bt_curve_preview(self, data: ProfileData, deltaet: list, deltabt: list) -> None:
        try:
            # Create lists to hold the curve references
            self.temp_lines = []
            self.setting_lines = []
            self.deltabt = deltabt
            self.deltaet = deltaet
            mode = data.get('mode', 'C')
            timex = data.get('timex', [])
            temp2 = data.get('temp2', []) 
            temp1 = data.get('temp1', [])

            if not timex or not temp2:
                self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast data (BT) is missing in the file."))
                self.fig.clear()
                self.canvas.draw()
                return

            raw_timeindex: list[int] = list(data.get('timeindex', []))
            # Pad to 8 slots — incomplete files may have fewer entries
            timeindex: list[int] = (raw_timeindex + [-1] * 8)[:8]
            computed = data.get('computed', {})

            # Infer CHARGE / DROP from timex boundaries when not set
            if timeindex[RoastingPhase.CHARGE] == -1 or timeindex[RoastingPhase.CHARGE] >= len(timex):
                timeindex[RoastingPhase.CHARGE] = 0
            if timeindex[RoastingPhase.DROP] == -1 or timeindex[RoastingPhase.DROP] >= len(timex):
                timeindex[RoastingPhase.DROP] = len(timex) - 1

            # event_indices for initial marker drawing (only set non-(-1) slots)
            event_indices = {}
            if len(raw_timeindex) >= 7 and computed:
                event_indices['CHARGE'] = timeindex[RoastingPhase.CHARGE]
                event_indices['DRY']    = timeindex[RoastingPhase.DRYEND]
                event_indices['FCs']    = timeindex[RoastingPhase.FCSTART]
                event_indices['DROP']   = timeindex[RoastingPhase.DROP]
            
            charge = timeindex[RoastingPhase.CHARGE]
            charge_start = charge - 10 if charge >= 10 else charge
            drop = timeindex[RoastingPhase.DROP]
            drop_end = drop + 10 if len(timex) >= drop + 10 else drop
            x_vals = [(t-timex[charge]) / 60.0 for t in timex[charge_start:drop_end]]

            y_bt = temp2[charge_start:drop_end]
            y_et = temp1[charge_start:drop_end]

            y_det = deltaet[charge_start:drop_end] if deltaet else []
            y_dbt = deltabt[charge_start:drop_end] if deltabt else []

            y_det = [v if v is not None else 0.0 for v in y_det]
            self.y_dbt = [v if v is not None else 0.0 for v in y_dbt]

            if not x_vals or not y_bt:
                self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Roast data (sliced) is empty. Check charge/drop points."))
                self.fig.clear()
                self.fig.set_facecolor(_PLOT_PALETTE["background"])
                self.canvas.draw_idle()
                return
            
            self.fig.clear() 
            # Create two subplots: ax1 for temperatures, ax2 for machine settings
            # hspace=0 ensures they are close to each other
            ax1:Axes
            ax2:Axes
            ax_hoovers:Axes
            ax1, ax2 = self.fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})

            #ax = self.fig.add_subplot(111)
            self.ax1 = ax1
            self.ax2 = ax2

            bg_color = _PLOT_PALETTE["background"]
            self.fig.set_facecolor(bg_color)
            from matplotlib.colors import to_hex, to_rgba # type:ignore[untyped-import,unused-ignore] # ty:ignore[ignore]

            xlabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['xlabel'], 0.75), keep_alpha=True)
            ylabel_alpha_color = to_hex(to_rgba(_PLOT_PALETTE['ylabel'], 0.75), keep_alpha=True)

            ax1.set_facecolor(bg_color)
            ax1.tick_params(axis='x', colors=xlabel_alpha_color, labelsize=_FS_TICK)
            ax1.tick_params(axis='y', colors=ylabel_alpha_color, labelsize=_FS_TICK)
            ax1.spines['bottom'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['top'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['left'].set_color(_PLOT_PALETTE['grid'])
            ax1.spines['right'].set_color(_PLOT_PALETTE['grid'])
            # Adjust font size for the top plot (Temperatures)
            ax1.tick_params(axis='both', which='major', labelsize=_FS_TICK)

            ax1.plot(x_vals, y_bt, label=QApplication.translate("Label","BT")+f" (°{mode})", color=_PLOT_PALETTE["bt"], linewidth=1.3)
            ax1.plot(x_vals, y_et, label=QApplication.translate("Label","ET")+f" (°{mode})", color=_PLOT_PALETTE["et"], linewidth=1.3)

            ax_hoovers = ax1.twinx() # second axe
            self.ax_hoovers = ax_hoovers # used for plotted hoovers
            
            ax_hoovers.set_facecolor("none")  # transparent – shares bg with ax1
            ax_hoovers.tick_params(axis='y', colors=ylabel_alpha_color, labelsize=_FS_TICK)
            ax_hoovers.spines['right'].set_color(_PLOT_PALETTE['grid'])
            ax_hoovers.spines['left'].set_color(_PLOT_PALETTE['grid'])
            
            #Time
            self.annot_time = ax1.annotate("", xy=(0,0), xytext=(10, 20),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER, color='black',
                bbox=dict(boxstyle="square", fc="w", alpha=0.9))

            # Second line (e.g., BT Temperature)
            self.annot_bt = ax1.annotate("", xy=(0,0), xytext=(10, 10),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER,color=_PLOT_PALETTE['bt'],
                bbox=dict(boxstyle="square", fc="w", alpha=0.9))

            # Third line (e.g., ET Temperature)
            self.annot_et = ax1.annotate("", xy=(0,0), xytext=(10, 0),
                textcoords="offset points", fontweight='bold', fontsize=_FS_HOVER,color=_PLOT_PALETTE['et'],
                bbox=dict(boxstyle="square", fc="w",  alpha=0.9))

            #calc Y_MAX_ROR (multiple of 10)
            if self.y_dbt:
                max_ror = numpy.max(self.y_dbt)
                Y_MAX_ROR = numpy.ceil(max_ror / 10.0) * 10.0
                if (Y_MAX_ROR == 0 and max_ror > 0) or (Y_MAX_ROR < 10 and max_ror > 0): 
                    Y_MAX_ROR = 10
            else:
                Y_MAX_ROR = 30 
            
            ax_hoovers.set_ylim(0, Y_MAX_ROR)
            ax_hoovers.set_ylabel(QApplication.translate("Label","RoR")+" (°/min)", fontsize=_FS_AXIS, color=ylabel_alpha_color)

            ax_hoovers.plot(x_vals, self.y_dbt, label=QApplication.translate("Label","RoR")+" "+QApplication.translate("Label","BT"), color=_PLOT_PALETTE["deltabt"], linestyle='--', linewidth=1.3, alpha=0.85)
            ax_hoovers.plot(x_vals, y_det, label=QApplication.translate("Label","RoR")+" "+QApplication.translate("Label","ET"), color=_PLOT_PALETTE["deltaet"], linestyle='--', linewidth=1.3, alpha=0.85)

            x_min_val = min(x_vals)
            x_max_val = max(x_vals)
            x_start_tick = int(x_min_val) if x_min_val >= 0 or x_min_val.is_integer() else int(x_min_val) - 1
            x_end_tick = int(x_max_val) + 1
            x_ticks = list(range(x_start_tick, x_end_tick))
            x_labels = [str(i) for i in x_ticks]
            ax1.set_xticks(x_ticks)
            ax1.set_xticklabels(x_labels) 
            
            # Échelle Y adaptative : la courbe BT occupe la pleine hauteur au lieu
            # du tiers inférieur d'un 0–300 figé. On garde ~10–20° d'air au-dessus
            # du pic BT (headroom +18° arrondi au 10 supérieur).
            temp_vals = [v for v in (list(y_bt) + list(y_et)) if v is not None]
            if temp_vals:
                t_min = min(temp_vals)
                t_max = max(temp_vals)
                Y_MIN = max(0, int(numpy.floor((t_min - 10) / 10.0) * 10))
                Y_MAX = int(numpy.ceil((t_max + 18) / 10.0) * 10)
                span = Y_MAX - Y_MIN
                Y_STEP = 50 if span > 200 else (25 if span > 100 else 10)
            else:
                Y_MIN, Y_MAX, Y_STEP = 0, 300, 50
            ax1.set_ylim(Y_MIN, Y_MAX)
            y_ticks = list(range(Y_MIN, Y_MAX + Y_STEP, Y_STEP))
            y_labels = [f"{i}" for i in y_ticks]
            ax1.set_yticks(y_ticks)
            ax1.set_yticklabels(y_labels)
            
            bbox_style_dark = dict(
                boxstyle="round,pad=0.3", 
                fc="black", 
                alpha=0.8, 
                ec="lightgray", 
                lw=1
            )

            # Reset tracking dicts then draw all non-(-1) events via shared helper
            self._event_vlines    = {}
            self._event_annots    = {}
            self._event_dots      = {}
            self._event_et_dots   = {}
            self._event_et_annots = {}
            self._pending_timeindex = None  # discard any unsaved edits from previous file
            self._draw_event_markers(ax1, timex, timeindex, temp2, temp1, mode, charge, bbox_style_dark,
                                     idx_min=charge_start, idx_max=drop_end)
            # titles and labels
            ax1.set_title(QApplication.translate("tilauscope_beancave","Curve Preview")+f": {data.get('title', 'Roast')}", fontsize=_FS_TITLE, color=_PLOT_PALETTE["title"])
            ax1.set_xlabel(QApplication.translate("tilauscope_beancave","Time (min)"), fontsize=_FS_AXIS, color=_PLOT_PALETTE['xlabel'])
            ax1.set_ylabel(QApplication.translate("tilauscope_beancave","Time")+f" (°{mode})", fontsize=_FS_AXIS, color=_PLOT_PALETTE['ylabel'])
            ax1.grid(True, alpha=0.3, color=_PLOT_PALETTE['grid']) 
            #self.fig.tight_layout() 
            self.annotation = ax1.annotate(
                '', xy=(0, 0), xytext=(20, 20), textcoords='offset points',
                bbox=dict(boxstyle="round", fc="w", alpha=0.9, ec="lightgray"),
                arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0.5",
                                color="w", linewidth=0.8),
                visible=False, fontsize=_FS_HOVER
            )

            if hasattr(self, 'annot_squares') and self.annot_squares:
                for sq in self.annot_squares:
                    try:
                        if sq in self.ax1.texts:
                            sq.remove()
                    except Exception:
                        pass
                self.annot_squares.clear()
            else:
                self.annot_squares = []
            self.curve_colors = [_PLOT_PALETTE["bt"], _PLOT_PALETTE["et"], _PLOT_PALETTE["deltabt"], _PLOT_PALETTE["deltaet"], 
                                 '#FAB387', '#F38BA8', '#A6E3A1', '#89DCEB']
                                 #self.aw.qmc.EvalueColor[0], self.aw.qmc.EvalueColor[1], self.aw.qmc.EvalueColor[2], self.aw.qmc.EvalueColor[3]]
            for i in range(8):
                # Création d'une annotation par ligne de texte
                self.annot_squares.append(self.ax1.annotate(
                    f"■", 
                    xy=(0,0), 
                    xytext=(20, 20), # Même base que self.annot
                    textcoords="offset points",
                    color=self.curve_colors[7-i],
                    va="top",         # "top" facilite l'alignement depuis le haut du bloc
                    ha="left",
                    visible=False,
                    zorder=10         # S'assure qu'ils sont au-dessus de la box
                ))
            
            # Plotting on the bottom axis
          
            # extra information
            names = data.get('etypes',[])
            event_types = data.get('specialeventstype', [])
            event_values = data.get('specialeventsvalue', [])
            event_times = data.get('specialevents', [])
            default_names = self.aw.qmc.etypesdefault


            # 1. Initialize Markers with high zorder and add them to ax1
            self.bt_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['bt'], markersize=5, visible=False, zorder=5)
            self.et_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['et'], markersize=5, visible=False, zorder=5)
            self.deltabt_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['deltabt'], markersize=5, visible=False, zorder=5)
            self.deltaet_marker = Line2D([0], [0], marker='o', color=_PLOT_PALETTE['deltaet'], markersize=5, visible=False, zorder=5)
            self.slider_marker=[]
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider0"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider1"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider2"], markersize=5, visible=False, zorder=5))
            self.slider_marker.append(Line2D([0], [0], marker='o', color=_PLOT_PALETTE["slider3"], markersize=5, visible=False, zorder=5))

            self.ax1.add_line(self.bt_marker)
            self.ax1.add_line(self.et_marker)
            self.ax_hoovers.add_line(self.deltabt_marker) # RoR marker goes on ax2            # Create the BT marker (dot)
            self.ax_hoovers.add_line(self.deltaet_marker) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[0]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[1]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[2]) # RoR marker goes on ax2            # Create the ET marker (dot)
            self.ax2.add_line(self.slider_marker[3]) # RoR marker goes on ax2            # Create the ET marker (dot)

            self.bt_marker.set_visible(False)
            self.et_marker.set_visible(False)
            self.deltabt_marker.set_visible(False)
            self.deltaet_marker.set_visible(False)
            self.slider_marker[0].set_visible(False)
            self.slider_marker[1].set_visible(False)
            self.slider_marker[2].set_visible(False)
            self.slider_marker[3].set_visible(False)

            # Mapping table for labels/colors (using etypes)
            # Type IDs: 1=Burner, 2=Airflow, 3=Drum, 4=Airwave
            self.machine_config = {
                0: {'label': QApplication.translate("Combobox",names[0]) if names else QApplication.translate("Combobox",default_names[0]), 'color': _PLOT_PALETTE["slider0"], 'marker':None},
                1: {'label': QApplication.translate("Combobox",names[1] if names else QApplication.translate("Combobox",default_names[1])), 'color': _PLOT_PALETTE["slider1"],'marker':None},
                2: {'label': QApplication.translate("Combobox",names[2] if names else QApplication.translate("Combobox",default_names[2])), 'color': _PLOT_PALETTE["slider2"],'marker':None},
                3: {'label': QApplication.translate("Combobox",names[3] if names else QApplication.translate("Combobox",default_names[3])), 'color': _PLOT_PALETTE["slider3"],'marker':None}
            }
            
            # draw steps for each machine setting
            charge_time_abs = timex[charge_start]
          
            for etype, cfg in self.machine_config.items():
                y_stepped = []
               
                # Filter events for this specific type first
                type_times = [t for i, t in enumerate(event_times) if event_types[i] == etype]
                type_vals = [v for i, v in enumerate(event_values) if event_types[i] == etype] 
                timex_events = [t for i, t in enumerate(timex) if i in type_times]    
                
                if not type_times:
                    continue
                
                for x_min in x_vals:
                    # Convert the current plot-minute back to absolute log time
                    current_time_abs = charge_time_abs + (x_min * 60.0)
                    
                    # Find the latest event value that happened BEFORE or AT this time
                    # We look for the max index where event_time <= current_time
                    val = 0.0
                    try:
                        for i in range(len(type_times)):
                            if i<len(timex_events) and timex_events[i] <= current_time_abs: # fix 2026/02/24 check for consistency between event time and timex time to avoid index error
                                val = self.aw.qmc.eventsInternal2ExternalValue(type_vals[i]) # fix 2026/02/20 convert internal to external value for display
                            else:
                                break # Events are sorted by time, so we can stop
                        y_stepped.append(val)
                    except Exception as e:
                        _log.debug(f"Error processing events for type {etype}: {e}")
                        y_stepped.append(0.0) # Default to 0 if there's an error 
                # Only plot if there is actual non-zero data
                if any(v != 0 for v in y_stepped):
                    ax2.step(x_vals, y_stepped, where='post', color=cfg['color'], 
                            label=cfg['label'], linewidth=1.2, alpha=0.9)

            # Final Styling
            ax2.set_facecolor(bg_color)
            ax2.set_ylabel(QApplication.translate("tilauscope_beancave",'Settings %'), color=_PLOT_PALETTE['ylabel'], fontsize=_FS_AXIS)
            ax2.tick_params(axis='y', labelcolor=ylabel_alpha_color)
            ax2.yaxis.set_major_locator(MultipleLocator(10))
            ax2.set_ylim(-5, 110)
            ax2.set_yticks(list(range(0, 101, 50)))
            ax2.grid(True, linestyle=':', alpha=0.3, color=_PLOT_PALETTE['grid'])
            # Only show legend if at least one labelled artist was plotted
            if ax2.get_legend_handles_labels()[0]:
                ax2.legend(
                    loc='upper center',
                    bbox_to_anchor=(0.5, -0.4),
                    fontsize=_FS_LEGEND,
                    ncol=4,
                    facecolor='#1e1e1e',
                    edgecolor='gray',
                    labelcolor='white'
                )
            ax2.tick_params(axis='both', which='major', labelsize=_FS_TICK)
            # Marges gérées par layout="constrained" (cf. création de la figure) —
            # plus de subplots_adjust codé en dur, la légende sous ax2 est prise en compte.
            if hasattr(self, 'hover_cid'):
                self.canvas.mpl_disconnect(self.hover_cid)
            self.curve_colors = [
                _PLOT_PALETTE["bt"],      # BT
                _PLOT_PALETTE["et"],      # ET
                _PLOT_PALETTE["deltabt"], # RoR BT
                _PLOT_PALETTE["deltaet"], # RoR ET
                _PLOT_PALETTE["slider0"],
                _PLOT_PALETTE["slider1"],
                _PLOT_PALETTE["slider2"],
                _PLOT_PALETTE["slider3"],
            ]
            self._reconnect_hover()
            self.hover_lid = self.canvas.mpl_connect("figure_leave_event", self.on_plot_leave)
            # Hide save button — data just loaded, no pending edits
            self.canvas_container._save_btn.hide()
            self.canvas.draw_idle()
            self.last_plot_data = data # type: ignore
            
        except Exception as e:
            _logd.error(f"Error generating plot: {e}")
            self.fig.clear()
            self.fig.set_facecolor(_PLOT_PALETTE["background"])
            self.canvas.draw()
            
            self.roast_info_text.setText(QApplication.translate("tilauscope_beancave","Error generating plot: ")+f"{e}")

    def resizeEvent(self, event: QResizeEvent) -> None: # type: ignore
        redraw = False
        if event is not None: # type: ignore
            super().resizeEvent(event) # type: ignore
            redraw = True
        if redraw:
            try:
                self.canvas.draw()
            except Exception:
                pass

    # search for closest valid heater before xposition
    def findLastValidEvent(self, e:int, xposition:float)->float:
        if self.last_plot_data is None:
            return 0.0
        eventtypes = self.last_plot_data.get('specialeventstype', []) # event type are sliders values 0,1,2,3
        eventvalues = self.last_plot_data.get('specialeventsvalue', []) # event values /10 in %
        timestamp = self.last_plot_data.get('specialevents', [])  # event timestamps in seconds from charge time
        timex= self.last_plot_data.get('timex', []) # time in seconds from charge time
        timeindex= self.last_plot_data.get('timeindex', []) # event time indices
        last_value = -1.0
        
        for d in range(len(eventvalues)):
            if eventtypes[d] == e: #check only event of type e
                v = eventvalues[d] if eventvalues[d] is not None else 0.0
                #if timeindex[0] > -1 and len(timex) > timeindex[0]: #fix 2025/11/20 set start depending on chage time or preheat depending on how it is stored
                #    ts = timex[timestamp[d]]-timex[timeindex[0]]
                #else:
                #    ts = timex[timestamp[d]]
                ts = timestamp[d] if timestamp[d] is not None else 0
                if ts <= xposition:
                    last_value = v
                else:
                    return last_value
        return last_value
    
    @pyqtSlot(float, float)
    def update_markers(self, marker:Line2D, x_data:float, y_val:float):
        # Vérifie si l'objet Qt n'a pas été supprimé par le moteur C++
        if self.canvas is None or self.canvas.isHidden():
            return
        try:
            marker = marker
            marker.set_data([x_data], [y_val])
            marker.set_visible(True)
            #self.canvas.draw_idle()
        except Exception as e:
            _log.debug(f"Error while updating markers: {e}")

    def on_plot_leave(self, event):
        """Fired when the mouse leaves the entire canvas area."""
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
        # Cacher les markers multi si actifs
        if hasattr(self, '_multi_markers'):
            for m in self._multi_markers:
                m.set_visible(False)
            self.canvas.draw_idle()

    # ── Timeindex remark via right-click ──────────────────────────────────────

    # Artisan timeindex slot names (index → display label)
    _TIMEINDEX_LABELS: dict[int, str] = {
        RoastingPhase.CHARGE:  'CHARGE',
        RoastingPhase.DRYEND:  'DRY END',
        RoastingPhase.FCSTART: 'FC start',
        RoastingPhase.FCEND:   'FC end',
        RoastingPhase.SCSTART: 'SC start',
        RoastingPhase.SCEND:   'SC end',
        RoastingPhase.DROP:    'DROP',
        RoastingPhase.COOLEND: 'COOL end',
    }

    def _build_marker_menu(self, global_pos, widget_pos) -> None:
        """
        Build and exec the contextual marker-remark menu.
        global_pos : QPoint — screen position for menu.exec()
        widget_pos : QPoint | None — canvas-widget position for data conversion
        """
        if not hasattr(self, 'ax1') or self.ax1 is None:
            return
        if not hasattr(self, 'lastprofiledata') or not self.lastprofiledata:
            return

        data  = self.lastprofiledata
        timex = data.get('timex', [])
        if not timex:
            return

        # Pad timeindex to 8 slots — incomplete files may have fewer entries
        raw_ti: list[int] = list(data.get('timeindex', []))
        timeindex: list[int] = (raw_ti + [-1] * 8)[:8]

        charge_idx = timeindex[RoastingPhase.CHARGE]
        # If CHARGE is unset, use timex[0] as time origin so click position is still meaningful
        if charge_idx < 0 or charge_idx >= len(timex):
            charge_t = timex[0]
        else:
            charge_t = timex[charge_idx]

        # ── Convert Qt widget pos → matplotlib data x (minutes from CHARGE) ──
        x_min: float | None = None
        if widget_pos is not None:
            canvas_h = self.canvas.height()
            try:
                dpr = self.canvas.devicePixelRatioF()
            except AttributeError:
                dpr = 1.0
            disp_x = widget_pos.x() * dpr
            disp_y = (canvas_h - widget_pos.y()) * dpr
            try:
                inv = self.ax1.transData.inverted()
                x_data, _y_data = inv.transform((disp_x, disp_y))
                x_min = float(x_data)
            except Exception:
                x_min = None

        if x_min is None:
            return

        click_t = charge_t + x_min * 60.0

        # Artisan convention: val==0 means "unset" for all slots except CHARGE
        # val==-1 also means unset; only val>0 is a real placed marker
        set_events: list[tuple[int, float]] = sorted(
            [(slot, timex[val]) for slot, val in enumerate(timeindex)
             if slot < 8 and val > 0 and val < len(timex)],
            key=lambda x: x[1]
        )

        # No events set at all → offer the 4 main slots regardless of click position
        _MAIN_SLOTS = {RoastingPhase.CHARGE, RoastingPhase.DRYEND,
                       RoastingPhase.FCSTART, RoastingPhase.DROP}
        if not set_events:
            ordered = sorted(s for s in _MAIN_SLOTS if timeindex[s] <= 0)
        else:
            left_slot: int | None  = None
            right_slot: int | None = None
            for slot, t in set_events:
                if t <= click_t:
                    left_slot = slot
                elif right_slot is None:
                    right_slot = slot

            in_range = False
            candidates: set[int] = set()
            for slot, _t in set_events:
                if slot == left_slot:
                    in_range = True
                if in_range:
                    candidates.add(slot)
                if slot == right_slot:
                    break

            for slot in range(8):
                if slot in candidates or timeindex[slot] > 0:
                    continue
                if left_slot is not None and right_slot is not None and left_slot < slot < right_slot:
                    candidates.add(slot)
                elif left_slot is not None and right_slot is None and slot > left_slot:
                    candidates.add(slot)
                elif left_slot is None and right_slot is not None and slot < right_slot:
                    candidates.add(slot)

            ordered = sorted(candidates)

        if not ordered:
            return

        # Nearest timex index to click position
        nearest_idx = min(range(len(timex)), key=lambda i: abs(timex[i] - click_t))

        mode  = data.get('mode', 'C')
        temp2 = data.get('temp2', [])
        click_bt  = temp2[nearest_idx] if nearest_idx < len(temp2) else 0.0
        click_mm  = self.format_seconds(click_t - charge_t)

        # ── Hide hover tooltip + annotation before showing menu ────────────
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
        if hasattr(self, 'annotation') and self.annotation is not None:
            self.annotation.set_visible(False)
        if hasattr(self, 'annot_squares'):
            for sq in self.annot_squares:
                sq.set_visible(False)
        for m in [getattr(self, 'bt_marker', None), getattr(self, 'et_marker', None),
                  getattr(self, 'deltabt_marker', None), getattr(self, 'deltaet_marker', None)]:
            if m is not None:
                m.set_visible(False)
        self.canvas.draw_idle()

        # ── Build menu ─────────────────────────────────────────────────────
        menu = QMenu(self.canvas)
        menu.setStyleSheet(
            f"QMenu {{ background-color:{THEME['SURFACE']}; color:{THEME['TEXT']}; "
            f"border:1px solid {THEME['BORDER']}; border-radius:6px; font-size:12px; padding:4px; }}"
            f"QMenu::item {{ padding:4px 18px; }}"
            f"QMenu::item:selected {{ background-color:{THEME['HOVER']}; color:{THEME['BG']}; }}"
            f"QMenu::item:disabled {{ color:{THEME['SUBTEXT']}; }}"
        )
        hdr = menu.addAction(
            QApplication.translate("tilauscope_beancave", f"→ {click_mm}  BT {click_bt:.1f}°{mode}")
        )
        hdr.setEnabled(False)
        menu.addSeparator()

        for slot in ordered:
            label   = self._TIMEINDEX_LABELS.get(slot, f'Event {slot}')
            old_idx = timeindex[slot]
            if old_idx != -1 and old_idx < len(timex):
                old_mm = self.format_seconds(timex[old_idx] - charge_t)
                old_bt = temp2[old_idx] if old_idx < len(temp2) else 0.0
                entry  = f"{label}   {old_mm} → {click_mm}   ({old_bt:.1f}→{click_bt:.1f}°{mode})"
            else:
                entry  = f"{label}   [—] → {click_mm}   ({click_bt:.1f}°{mode})"
            act = QAction(entry, menu)
            act.setData(slot)
            menu.addAction(act)

        chosen = menu.exec(global_pos)
        if chosen is None or not chosen.isEnabled() or chosen.data() is None:
            return

        target_slot: int = chosen.data()
        # Work on pending copy — never mutate the cached lastprofiledata dict
        if self._pending_timeindex is None:
            raw = list(self.lastprofiledata.get('timeindex', []))  # type: ignore[arg-type]
            self._pending_timeindex = (raw + [-1] * 8)[:8]  # always 8 slots
        self._pending_timeindex[target_slot] = nearest_idx
        self._redraw_event_markers()
        # Build a view of lastprofiledata with pending timeindex for stats display
        _display_data = dict(self.lastprofiledata)
        _display_data['timeindex'] = self._pending_timeindex
        self.display_roast_info(_display_data)  # type: ignore[arg-type]
        self.canvas_container._save_btn.show()
        self.canvas_container._reposition_buttons()

    def _draw_event_markers(self, ax1, timex, timeindex, temp2, temp1, mode, charge_idx, bbox_style,
                            idx_min: int = 0, idx_max: int | None = None) -> None:
        """
        Draw all non-(-1) timeindex events onto ax1 and populate tracking dicts.
        idx_min/idx_max: only draw events whose timex index falls within [idx_min, idx_max).
        Must be called with cleared _event_vlines/annots/dots.
        """
        charge_t       = timex[charge_idx]
        if idx_max is None:
            idx_max = len(timex)
        vertical_offsets = [5, 10, 15, 20]
        offset_idx     = 0

        for slot, label in self._TIMEINDEX_LABELS.items():
            if slot >= len(timeindex):
                continue
            index = timeindex[slot]
            # val==0 means unset (Artisan convention), val==-1 also means unset
            if index <= 0 or index >= len(timex):
                continue
            # Skip events outside the visible plot range
            if index < idx_min or index >= idx_max:
                continue

            x_time     = timex[index] - charge_t
            x_min      = x_time / 60.0
            bt_val     = temp2[index] if index < len(temp2) else 0.0
            et_val     = temp1[index] if temp1 and index < len(temp1) else None

            vl = ax1.axvline(x=x_min, color='gray', linestyle=':', linewidth=0.8)
            self._event_vlines[label] = vl

            dot = ax1.plot(x_min, bt_val, marker='o',
                           color=_PLOT_PALETTE['bt'], markersize=3)[0]
            self._event_dots[label] = dot

            ann_text = f"{label}\n{bt_val:.1f}°{mode} ({self.format_seconds(x_time)})"
            y_off    = vertical_offsets[offset_idx % len(vertical_offsets)]
            offset_idx += 1
            ann = ax1.annotate(
                ann_text, (x_min, bt_val),
                textcoords="offset points", xytext=(5, y_off),
                ha='left', fontsize=_FS_EVENT, color='white', bbox=bbox_style,
            )
            self._event_annots[label] = ann

            if et_val is not None:
                et_dot = ax1.plot(x_min, et_val, marker='x',
                                  color=_PLOT_PALETTE['et'], markersize=3)[0]
                self._event_et_dots[label] = et_dot
                et_ann = ax1.annotate(
                    f"ET: {et_val:.1f}°{mode}", (x_min, et_val),
                    textcoords="offset points", xytext=(5, -15),
                    ha='left', fontsize=_FS_EVENT, color='white', bbox=bbox_style,
                )
                self._event_et_annots[label] = et_ann

    def _redraw_event_markers(self) -> None:
        """Remove old event artists from ax1, redraw using pending edits or lastprofiledata timeindex."""
        if not hasattr(self, 'ax1') or self.ax1 is None:
            return
        data      = self.lastprofiledata
        timex     = data.get('timex', [])
        # Use pending edits if present, otherwise fall back to the original profile (padded to 8)
        if self._pending_timeindex is not None:
            timeindex: list[int] = self._pending_timeindex
        else:
            raw = list(data.get('timeindex', []))
            timeindex = (raw + [-1] * 8)[:8]
        temp2     = data.get('temp2', [])
        temp1     = data.get('temp1', [])
        mode      = data.get('mode', 'C')

        # Remove all tracked artists
        for art_dict in (self._event_vlines, self._event_annots, self._event_dots,
                         self._event_et_dots, self._event_et_annots):
            for art in art_dict.values():
                try:
                    art.remove()  # type: ignore[union-attr]
                except Exception:
                    pass
        self._event_vlines.clear()
        self._event_annots.clear()
        self._event_dots.clear()
        self._event_et_dots.clear()
        self._event_et_annots.clear()

        if len(timeindex) < 8 or not timex:
            self.canvas.draw_idle()
            return

        charge_idx = timeindex[RoastingPhase.CHARGE]
        if charge_idx < 0 or charge_idx >= len(timex):
            self.canvas.draw_idle()
            return

        drop_idx   = timeindex[RoastingPhase.DROP]
        idx_min    = charge_idx - 10 if charge_idx >= 10 else charge_idx
        idx_max    = (drop_idx + 10) if drop_idx != -1 and drop_idx + 10 <= len(timex) else drop_idx

        bbox_style = dict(boxstyle="round,pad=0.3", fc="black", alpha=0.8, ec="lightgray", lw=1)
        self._draw_event_markers(self.ax1, timex, timeindex, temp2, temp1, mode, charge_idx, bbox_style,
                                 idx_min=idx_min, idx_max=idx_max)
        self.canvas.draw_idle()

    def _save_timeindex_to_alog(self) -> None:
        """Write updated timeindex back to the .alog file (Artisan native repr format) and invalidate cache."""
        if not hasattr(self, 'lastprofiledata') or not self.lastprofiledata:
            return
        if self._pending_timeindex is None:
            return
        item = self.roast_list_widget.currentItem()
        if item is None:
            return
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not metadata:
            return
        filepath = Path(self.alog_directory) / metadata["raw_fname"]
        try:
            # Artisan native format: repr(dict) written as UTF-8
            # (cf. artisanlib.util.serialize). Read back with ast.literal_eval.
            data_to_write = dict(self.lastprofiledata)
            data_to_write['timeindex'] = self._pending_timeindex
            filepath.write_text(repr(data_to_write), encoding='utf-8')
            # Invalidate LRU cache so next load reads the updated file
            cache_key = str(filepath)
            if cache_key in self._alog_cache:
                del self._alog_cache[cache_key]
            self._pending_timeindex = None
            self.canvas_container._save_btn.hide()
            _log.info(f"Saved updated timeindex to {filepath.name}")
        except Exception as e:
            _log.error(f"_save_timeindex_to_alog: {e}", exc_info=True)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_beancave", "Save Error"),
                str(e),
                QMessageBox.Icon.Critical,
            )

    def on_plot_hover(self, event) -> None:
        if self.ax1 is None or self.last_plot_data is None:
            return

        if event.inaxes not in (self.ax1, self.ax_hoovers):
            self._hover_tooltip.hide()
            # Cacher les marqueurs
            for m in [self.bt_marker, self.et_marker,
                    self.deltabt_marker, self.deltaet_marker]:
                m.set_visible(False)
            for m in self.slider_marker:
                m.set_visible(False)
            self.canvas.draw_idle()
            return

        x_data = event.xdata
        y_data = event.ydata
        if x_data is None or y_data is None:
            self._hover_tooltip.hide()
            return

        timex    = self.last_plot_data.get('timex', [])
        temp1    = self.last_plot_data.get('temp1', [])
        temp2    = self.last_plot_data.get('temp2', [])
        timeindex = self.last_plot_data.get('timeindex', [])
        mode     = self.last_plot_data.get('mode', 'C')

        if not timex or len(timeindex) < 1:
            return

        charge_time_s   = float(timex[timeindex[RoastingPhase.CHARGE]])
        current_time_s  = charge_time_s + (float(x_data) * 60.0)
        time_str        = self.format_seconds(current_time_s - charge_time_s)

        # Trouver l'index le plus proche
        t_idx = 0
        min_diff = float('inf')
        for i, t in enumerate(timex):
            diff = abs(t - current_time_s)
            if diff < min_diff:
                min_diff = diff
                t_idx = i
            if min_diff <= 1:
                break
        # Valeurs à afficher
        try:
            bt_val      = float(temp2[t_idx]) if t_idx < len(temp2) else None
            et_val      = float(temp1[t_idx]) if t_idx < len(temp1) else None
            dbt_val     = float(self.deltabt[t_idx]) if self.deltabt[t_idx] is not None and t_idx < len(self.deltabt) else None
            det_val     = float(self.deltaet[t_idx]) if self.deltaet[t_idx] is not None and t_idx < len(self.deltaet) else None
        except (TypeError, ValueError, IndexError):
            bt_val = et_val = dbt_val = det_val = None

        if bt_val is None or numpy.isnan(bt_val):
            self._hover_tooltip.hide()
            return

        # ── Mise à jour des marqueurs Matplotlib (points sur les courbes) ────────
        self.bt_marker.set_data([x_data], [bt_val])
        self.bt_marker.set_visible(True)
        if et_val is not None:
            self.et_marker.set_data([x_data], [et_val])
            self.et_marker.set_visible(True)
        if dbt_val is not None:
            self.deltabt_marker.set_data([x_data], [dbt_val])
            self.deltabt_marker.set_visible(True)
        if det_val is not None:
            self.deltaet_marker.set_data([x_data], [det_val])
            self.deltaet_marker.set_visible(True)

        # Sliders
        slider_vals = []
        for e in range(4):
            v = self.findLastValidEvent(e, t_idx)
            v1 = self.aw.qmc.eventsInternal2ExternalValue(v) if v >= 0 else -1
            if v1 >= 0:
                self.slider_marker[e].set_data([x_data], [v1])
                self.slider_marker[e].set_visible(True)
                slider_vals.append((e, v1))

        self.canvas.draw_idle()

        # ── Contenu du tooltip Qt ────────────────────────────────────────────────
        names  = self.last_plot_data.get('etypes', self.aw.qmc.etypesdefault)
        colors = self.curve_colors  # défini dans plot_bt_curve_preview

        bt_col = '#04690E'
        et_col = '#E0124C'
        dbt_col = '#1E0AD9'
        det_col = '#E6871B'
        # Couleurs hex pour les pastilles HTML
#        bt_col  = self.aw.qmc.palette.get('bt',       '#04690E')
#        et_col  = self.aw.qmc.palette.get('et',       '#E0124C')
#        dbt_col = self.aw.qmc.palette.get('deltabt',  '#1E0AD9')
#        det_col = self.aw.qmc.palette.get('deltaet',  '#E6871B')

        def dot(color: str) -> str:
            return (f'<span style="color:{color}; '
                    f'font-size:14px; line-height:1;">&#9632;</span> ')

        lines = [
            f'<b style="color:#CDD6F4;">{QApplication.translate("Label","Time")} : {time_str}</b>',
            f'{dot(bt_col)}{QApplication.translate("Label","BT")} : {bt_val:.1f}°{mode}',
        ]
        if et_val is not None:
            lines.append(f'{dot(et_col)}{QApplication.translate("Label","ET")} : {et_val:.1f}°{mode}')
        if dbt_val is not None:
            lines.append(f'{dot(dbt_col)}{QApplication.translate("Label","RoR BT")} : {dbt_val:.1f}°{mode}/min')
        if det_val is not None:
            lines.append(f'{dot(det_col)}{QApplication.translate("Label","RoR ET")} : {det_val:.1f}°{mode}/min')

        slider_colors = [_PLOT_PALETTE[f"slider{i}"] for i in range(4)]
        for e, v1 in slider_vals:
            name = QApplication.translate("Combobox",
                        names[e] if e < len(names)
                        else self.aw.qmc.etypesdefault[e])
            lines.append(f'{dot(slider_colors[e])}{name} : {v1:.0f}%')

        html = '<br>'.join(lines)
        if event.xdata is None or event.ydata is None:
            self._hover_tooltip.hide()
            return

        if event.guiEvent is not None:
            global_point = event.guiEvent.globalPosition().toPoint()
        else:
            ## fallback for non-interactive backends
            device_ratio = self.canvas.devicePixelRatioF()
            x_canvas = int(event.x / device_ratio)
            y_canvas = int((self.canvas.height() * device_ratio - event.y) / device_ratio)
            local_point = QPoint(x_canvas, y_canvas)
            global_point = self.canvas.mapToGlobal(local_point)
        if event.inaxes:
            self._hover_tooltip.show_at(global_point, html)
        else:
            # Hide if we are on the canvas but not on the axes
            if hasattr(self, 'annotation'):
                self.annotation.hide()

    def take_snapshot(self, figure, filename: str|None = None) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        """Opens a file dialog to save the Matplotlib figure as a PNG snapshot."""
        m =  self.roast_list_widget.currentItem()
        metadata = m.data(Qt.ItemDataRole.UserRole)
        f= metadata["raw_fname"]

        from PyQt6.QtCore import QStandardPaths

        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )

        default_path = str(Path(downloads_dir) / f)

        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave","Save Curve Snapshot as PNG"),
            default_path,
            QApplication.translate("tilauscope_beancave", "PN Files (*.png);;All Files (*)")
        )

        if file_path:
            try:
                # Save the Matplotlib figure to the specified file
                # The entire Figure (including axes, labels, etc.) is saved.
                figure.savefig(file_path)
                self._show_message(self, QApplication.translate("tilauscope_beancave","Snapshot Successful"),
                                        QApplication.translate("tilauscope_beancave","The curve has been successfully saved to:")+f"\n{file_path}")
            except Exception as e:
                self._show_message(self, QApplication.translate("tilauscope_beancave","Save Error"),
                                     QApplication.translate("tilauscope_beancave","An error occurred while saving the figure:")+f"\n{e}", QMessageBox.Icon.Critical)
    
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
            f"background-color: {THEME['SURFACE']}; "
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
        if hasattr(self, 'coffee_bean_types'):
            single_origin_names = self.coffee_bean_types['Arabica']
        else:
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
   
    def setup_main_tab_ui(self) -> None:
        """
        Main tab — V2 layout.

        Structure :
          QSplitter horizontal
          ├── left pane  : datatable (taille stable)
          └── right pane : notice_bar + QScrollArea(formulaire) + actions_bar
        """
        # ── helpers ────────────────────────────────────────────────────────
        def _icon_btn(svg_path_d: str, label: str, stroke: str = "currentColor",
                      extra_style: str = "") -> QPushButton:
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
            if extra_style:
                btn.setStyleSheet(extra_style)
            return btn

        def _sm_btn(svg_d: str, label: str, stroke: str = "currentColor") -> QPushButton:
            """Secondary button — same height as primary, smaller padding via _SS_SECONDARY."""
            return _icon_btn(svg_d, label, stroke)

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
        # ## TILAU ## crop-age indicator (design v4 §2) — the field itself turns
        # orange at 2 years, red at 3+, so the age shows even when the list
        # column is out of view.
        self._crop_base_style = self.crop_input.styleSheet()
        self.crop_input.valueChanged.connect(
            lambda v: self._update_crop_age_indicator(int(v)))

        self.density_input = TilauSpinBox()
        self.density_input.setRange(500, 800)
        self.density_input.setDecimals(0)
        self.density_input.setSuffix("g/l")
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
        ## TILAU ## aw is a dimensionless ratio between 0 and 1, not a
        ## percentage — the field read "0.52 %", which is the kind of label that
        ## makes an operator type 52 and hit the 1.0 ceiling with no explanation.
        self.water_activity_input.setSuffix(" aw")
        self.water_activity_input.setMinimumHeight(30)
        self.water_activity_input.setToolTip(QApplication.translate("tilauscope_beancave","Water activity of green beans, a ratio from 0 to 1 (not a percentage). Specialty green is typically 0.45-0.60."))

        self.volume_input = TilauSpinBox()
        self.volume_input.setRange(0.0, 999.999)
        self.volume_input.setDecimals(3)
        self.volume_input.setSuffix("l")
        self.volume_input.setMinimumHeight(30)
        self.volume_input.setToolTip(QApplication.translate("tilauscope_beancave","Volume of green beans based on density in l."))

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

        # ── Stylesheets boutons — identiques aux autres onglets ────────────────
        # Primary  : fond ACCENT, texte BG, font 12px bold  (ex: Update)
        # Normal   : fond ACCENT semi-transparent, texte ACCENT, font 12px (ex: Add, Clear)
        # Danger   : fond CRITICAL semi-transparent, texte CRITICAL  (ex: Delete)
        # Secondary: fond SURFACE, texte TEXT, font 12px  (ex: Roast, Label…)
        _F = "'JetBrains Mono', monospace"
        _FS = "12px"
        _R  = "5px"

        _SS_PRIMARY = f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : {_R};
                padding          : 6px 16px;
                font-family      : {_F};
                font-size        : {_FS};
                font-weight      : bold;
            }}
            QPushButton:hover {{
                background-color : {THEME['HOVER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
            QPushButton:disabled {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['SUBTEXT']};
            }}
        """
        _SS_NORMAL = f"""
            QPushButton {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME['BORDER']};
                border-radius    : {_R};
                padding          : 6px 16px;
                font-family      : {_F};
                font-size        : {_FS};
            }}
            QPushButton:hover {{
                background-color : {THEME['HOVER']};
                color            : {THEME['BG']};
                border-color     : {THEME['HOVER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
            }}
            QPushButton:disabled {{
                color            : {THEME['SUBTEXT']};
            }}
        """
        _SS_DANGER = f"""
            QPushButton {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['CRITICAL']};
                border           : 1px solid {THEME['CRITICAL']};
                border-radius    : {_R};
                padding          : 6px 16px;
                font-family      : {_F};
                font-size        : {_FS};
            }}
            QPushButton:hover {{
                background-color : {THEME['CRITICAL']};
                color            : {THEME['BG']};
            }}
            QPushButton:pressed {{
                background-color : rgba(243,139,168,60);
            }}
            QPushButton:disabled {{
                color            : {THEME['SUBTEXT']};
                border-color     : {THEME['BORDER']};
            }}
        """
        _SS_SECONDARY = f"""
            QPushButton {{
                background-color : {THEME['SURFACE']};
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME['BORDER']};
                border-radius    : {_R};
                padding          : 5px 12px;
                font-family      : {_F};
                font-size        : {_FS};
            }}
            QPushButton:hover {{
                background-color : {THEME['HOVER']};
                color            : {THEME['BG']};
                border-color     : {THEME['HOVER']};
            }}
            QPushButton:pressed {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
            }}
            QPushButton:disabled {{
                color            : {THEME['SUBTEXT']};
            }}
        """

        # ── Boutons CRUD primaires ──────────────────────────────────────────
        ## TILAU ## "+ New sack" is the single accent button of the action bar —
        ## Update dresses like the other CRUD buttons to avoid two defaults.
        self.update_button = _icon_btn(
            "M2 7h10M7 2l5 5-5 5", "Update", extra_style=_SS_NORMAL)
        self.update_button.clicked.connect(self.update_selected_bean)
        self.update_button.setToolTip(QApplication.translate("tilauscope_beancave","Update the selected green bean record with the values filled in the form."))

        self.add_button = _icon_btn(
            "M7 2v10M2 7h10", "Add", extra_style=_SS_NORMAL)
        ## TILAU ## Lot 5 step D: Add opens the full expert editor on a blank record
        self.add_button.clicked.connect(self._open_full_bean_editor)
        self.add_button.setToolTip(QApplication.translate("tilauscope_beancave","Create a new green bean record in a single expert form. For a guided entry, use « + New sack »."))

        self.clear_button = _icon_btn(
            "M5 4l-3 3 3 3M2 7h9a2 2 0 0 0 0-4H9", "Clear", extra_style=_SS_NORMAL)
        self.clear_button.clicked.connect(self.clear_form)
        self.clear_button.clicked.connect(self._enter_edit_mode)  ## TILAU ## Lot 5: a fresh entry needs the form
        self.clear_button.setToolTip(QApplication.translate("tilauscope_beancave","Clear all input fields to their default state."))

        self.remove_button = _icon_btn(
            "M2 4h10M5 4V2.5h4V4M3 4l.7 7.5h6.6L11 4M6 7v3M8 7v3",
            "Delete", stroke=THEME["CRITICAL"], extra_style=_SS_DANGER)
        self.remove_button.clicked.connect(self.confirm_and_delete)
        self.remove_button.setToolTip(QApplication.translate("tilauscope_beancave","Delete the selected green bean record. A confirmation dialog will appear."))

        # ── Boutons secondaires ─────────────────────────────────────────────
        self.roast = _sm_btn(
            "M7 2c0 2-3 3-3 5.5a3 3 0 0 0 6 0C10 5 7 4 7 2z",
            "Roast", stroke=THEME["WARNING"])
        self.roast.setStyleSheet(_SS_SECONDARY)
        self.roast.clicked.connect(self.on_click_roast_properties)
        self.roast.setToolTip(QApplication.translate("tilauscope_beancave","Set a roast session based on the current selection."))

        self.generate_label_button = _sm_btn(
            "M1.5 3H12.5a1.5 1.5 0 0 1 1.5 1.5v6A1.5 1.5 0 0 1 12.5 12H1.5A1.5 1.5 0 0 1 0 10.5v-6A1.5 1.5 0 0 1 1.5 3zM3 6.5h8M3 8.5h5",
            "Label")
        self.generate_label_button.setStyleSheet(_SS_SECONDARY)
        self.generate_label_button.clicked.connect(self.on_print_label_clicked)
        self.generate_label_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate a printable label for this green bean record."))

        self.generate_qr_button = _sm_btn(
            "M1 1h5v5H1zM8 1h5v5H8zM1 8h5v5H1zM3 3h1v1H3zM10 3h1v1H10zM3 10h1v1H3z",
            "QR")
        self.generate_qr_button.setStyleSheet(_SS_SECONDARY)
        self.generate_qr_button.clicked.connect(self.generate_qr_code)
        self.generate_qr_button.setToolTip(QApplication.translate("tilauscope_beancave","Generate a QR code for this green bean record."))

        ## TILAU ## Shareable bean card — 1200x630 JPEG for social posts
        self.generate_card_button = _sm_btn(
            "M1 3.5h12v9H1zM4 7a1 1 0 1 0 0-.01M1.6 11.4L5 8.4l2.4 2.2L10 8l3 2.8",
            "Card")
        self.generate_card_button.setStyleSheet(_SS_SECONDARY)
        self.generate_card_button.clicked.connect(self.on_export_social_card)
        self.generate_card_button.setToolTip(QApplication.translate("tilauscope_beancave","Export this green bean sheet as a shareable landscape image (JPEG), sized for social networks."))

        self.inject_from_ai_button = _sm_btn(
            "M7 1.5l1.2 3.5H12l-3 2.2 1.1 3.5L7 8.5l-3.1 2.2L5 7.2 2 5h3.8z",
            "AI", stroke=THEME["ACCENT"])
        self.inject_from_ai_button.setStyleSheet(_SS_SECONDARY)
        self.inject_from_ai_button.clicked.connect(self.on_click_ai_parse)
        self.inject_from_ai_button.clicked.connect(self._enter_edit_mode)  ## TILAU ## Lot 5: AI fills the form
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
        self.flavorselector.setStyleSheet(_SS_SECONDARY)
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

        ## TILAU ## lock text/combo input height to TilauSpinBox._H so no stylesheet
        ## state change (hover/focus border, radius, AA) can shift them by 1px and
        ## reflow the form — mirrors the fixed-height guard already on TilauSpinBox.
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
            self.volume_input, self.altitude_input, self.species_combo,
            self.varieties_combo, self.weight_left_input, self.flavour_notes_input,
            self.sca_input, self.bean2_combo, self.bean2_ratio_input,
            self.bean3_combo, self.bean3_ratio_input, self.blend_notes_input,
        ]
        for w in _db_widgets:
            if w:
                w.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                w.installEventFilter(self.hover_filter)

        # ══════════════════════════════════════════════════════════════════
        # V3 — Layout stacked : 5 groupes sémantiques
        # ── Couleurs accent par groupe (thème Catppuccin Mocha) ─────────────
        #   Origin & Identity → ACCENT   #89B4FA  (bleu)
        #   Botany & Process  → #CBA6F7  (mauve)
        #   Blend             → SUCCESS  #A6E3A1  (vert teal)
        #   Physical measures → SUBTEXT  #94A3B8  (gris)
        #   Computed          → WARNING  #E0903B  (orange)
        # ══════════════════════════════════════════════════════════════════

        _C_ORIGIN  = THEME["ACCENT"]          # #89B4FA
        _C_BOTANY  = "#CBA6F7"                # mauve
        _C_BLEND   = THEME["SUCCESS"]         # #A6E3A1
        _C_PHYS    = THEME["SUBTEXT"]         # #94A3B8
        _C_COMP    = THEME["WARNING"]         # #E0903B

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
        self.form_group_box = _grp("Origin & Identity", _C_ORIGIN)
        _gl1 = QGridLayout(self.form_group_box)
        _gl1.setContentsMargins(10, 18, 10, 10)
        _gl1.setSpacing(5)
        _gl1.setColumnStretch(1, 3)  # champ col gauche
        _gl1.setColumnStretch(3, 3)  # champ col droite
        _gl1.setColumnMinimumWidth(0, 120)  # label gauche
        _gl1.setColumnMinimumWidth(2, 120)  # label droite

        # col gauche : Name (pleine largeur), Farm, Country
        _name_lbl = QLabel(QApplication.translate("tilauscope_beancave","Name"))
        _name_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _name_lbl.setFixedWidth(120)
        _name_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl1.addWidget(_name_lbl,        0, 0)
        _gl1.addWidget(self.name_input,  0, 1, 1, 3)   # span 3 cols → pleine largeur

        _frow("Farm / Region",  self.farm_input,     _gl1, 1, 0)
        _frow("Country",        self.country_combo,  _gl1, 2, 0)

        # col droite : Supplier, Crop
        _frow("Supplier",       self.supplier_input, _gl1, 1, 1)
        _frow("Crop year",      self.crop_input,     _gl1, 2, 1)

        # Flavour Notes pleine largeur
        _fl_lbl = QLabel(QApplication.translate("tilauscope_beancave","Flavour Notes"))
        _fl_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _fl_lbl.setFixedWidth(120)
        _fl_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl1.addWidget(_fl_lbl,                  3, 0)
        _gl1.addWidget(self.flavour_notes_input, 3, 1, 1, 3)

        # SCA score
        _frow("SCA score",      self.sca_input,      _gl1, 4, 0)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 2 — Botany & Process
        # ════════════════════════════════════════════════════════════════════
        _sec_botany = _grp("Botany & Process", _C_BOTANY)
        _gl2 = QGridLayout(_sec_botany)
        _gl2.setContentsMargins(10, 18, 10, 10)
        _gl2.setSpacing(5)
        _gl2.setColumnStretch(1, 3)
        _gl2.setColumnStretch(3, 3)
        _gl2.setColumnMinimumWidth(0, 120)
        _gl2.setColumnMinimumWidth(2, 120)

        _frow("Type",           self.type_combo,             _gl2, 0, 0)
        # Ratio 1 affiché dans le groupe Blend en mode Blend (géré par _toggle_blend_fields)

        # Species + Variety : ligne 1 — visibles uniquement en Single Origin
        self._species_row_lbl = QLabel(QApplication.translate("tilauscope_beancave","Species"))
        self._species_row_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        self._species_row_lbl.setFixedWidth(120)
        self._species_row_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._variety_row_lbl = QLabel(QApplication.translate("tilauscope_beancave","Variety"))
        self._variety_row_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        self._variety_row_lbl.setFixedWidth(120)
        self._variety_row_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        _gl2.addWidget(self._species_row_lbl,  1, 0)
        _gl2.addWidget(self.species_combo,     1, 1)
        _gl2.addWidget(self._variety_row_lbl,  1, 2)
        _gl2.addWidget(self.varieties_combo,   1, 3)  # position initiale (SO)

        # Category + Process : ligne 2
        _frow("Category",       self.category_process_combo, _gl2, 2, 0)
        _frow("Process",        self.process_combo,          _gl2, 2, 1)

        # Stocker la ref au layout Botany pour le re-parentage dans _toggle_blend_fields
        self._gl2_botany = _gl2

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 3 — Physical measures (grille 4 colonnes sur une ligne)
        # ════════════════════════════════════════════════════════════════════
        _sec_phys = _grp("Physical measures", _C_PHYS)
        _gl3 = QGridLayout(_sec_phys)
        _gl3.setContentsMargins(10, 18, 10, 10)
        _gl3.setSpacing(5)
        for _ci in range(8):
            _gl3.setColumnStretch(_ci, 1 if _ci % 2 == 1 else 0)

        ## TILAU ## density-measure button → opens the scale-piloted density window
        self.density_measure_btn = QPushButton()
        self.density_measure_btn.setIcon(_svg_bytes_to_icon(_SVG_DENSITY.encode(), 16))
        self.density_measure_btn.setIconSize(QSize(16, 16))
        self.density_measure_btn.setFixedSize(30, 30)
        self.density_measure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.density_measure_btn.setToolTip(QApplication.translate(
            "tilauscope_beancave", "Measure density with the scale"))
        self.density_measure_btn.setStyleSheet(
            f"QPushButton{{background:{THEME['SURFACE']};border:1px solid {THEME['BORDER']};"
            f"border-radius:6px;}}QPushButton:hover{{border-color:{THEME['ACCENT']};}}"
            "QToolTip{background-color:#2D2F3F;color:white;border:1px solid #585B70;"
            "padding:5px;border-radius:3px;font-size:11px;}"
        )
        self.density_measure_btn.clicked.connect(self._open_density_window)
        _dens_box = QWidget()
        _dens_box.setStyleSheet("background:transparent;")
        _dens_lay = QHBoxLayout(_dens_box)
        _dens_lay.setContentsMargins(0, 0, 0, 0)
        _dens_lay.setSpacing(4)
        _dens_lay.addWidget(self.density_input, 1)
        _dens_lay.addWidget(self.density_measure_btn, 0)

        # 4 colonnes : Altitude | Density | Humidity | Water activity
        for _ci, (_lbl_t, _w) in enumerate([
            ("Altitude",       self.altitude_input),
            ("Density",        _dens_box),
            ("Humidity",       self.last_humidity_input),
            ("Water activity", self.water_activity_input),
        ]):
            _lbl3 = QLabel(QApplication.translate("tilauscope_beancave", _lbl_t))
            _lbl3.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
            _lbl3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            _gl3.addWidget(_lbl3, 0, _ci * 2)
            _gl3.addWidget(_w,    0, _ci * 2 + 1)

        self.water_activity_label = _gl3.itemAtPosition(0, 6).widget()  # ref pour update_ui_visibility

        # volume_input reste instancié mais non affiché (conservé en base)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 4 — Blend components (conditionnel)
        # ════════════════════════════════════════════════════════════════════
        self.blend_group_box = _grp("Blend components", _C_BLEND)
        self.blend_group_box.setStyleSheet(
            self.blend_group_box.styleSheet().replace(
                f"border: 1px solid {THEME['BORDER']};",
                f"border: 1px solid rgba(166,227,161,60);"
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
        self._blend_bean1_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        self._blend_bean1_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Bean 1 + varieties_combo ajoutés par _toggle_blend_fields — ici seulement Ratio1/Bean2/Ratio2
        for _ci2, (_lbl_t2, _w2) in enumerate([
            ("Ratio 1",  self.bean1_ratio_input),
            ("Bean 2",   self.bean2_combo),
            ("Ratio 2",  self.bean2_ratio_input),
        ]):
            _lbl4 = QLabel(QApplication.translate("tilauscope_beancave", _lbl_t2))
            _lbl4.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
            _lbl4.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            # cols décalées de 2 pour laisser place à Bean1 (cols 0-1)
            _gl4.addWidget(_lbl4, 0, (_ci2 + 1) * 2)
            _gl4.addWidget(_w2,   0, (_ci2 + 1) * 2 + 1)

        # Stocker ref pour re-parentage dynamique
        self._gl4_blend = _gl4

        # Ligne 1 : Bean 3 + Ratio 3 | Notes
        _lbl_b3 = QLabel(QApplication.translate("tilauscope_beancave","Bean 3"))
        _lbl_b3.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _lbl_b3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _lbl_r3 = QLabel(QApplication.translate("tilauscope_beancave","Ratio 3"))
        _lbl_r3.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _lbl_r3.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl4.addWidget(_lbl_b3,              1, 0)
        _gl4.addWidget(self.bean3_combo,     1, 1)
        _gl4.addWidget(_lbl_r3,              1, 2)
        _gl4.addWidget(self.bean3_ratio_input, 1, 3)

        # Notes blend sur la même ligne (cols 4-7)
        _bl_notes_lbl = QLabel(QApplication.translate("tilauscope_beancave","Notes"))
        _bl_notes_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _gl4.addWidget(_bl_notes_lbl,          1, 4)
        _gl4.addWidget(self.blend_notes_input, 1, 5, 1, 3)

        # ════════════════════════════════════════════════════════════════════
        # GROUPE 5 — Computed (Stock + Total roasted)
        # ════════════════════════════════════════════════════════════════════
        _sec_computed = _grp("Computed", _C_COMP)
        _gl5 = QGridLayout(_sec_computed)
        _gl5.setContentsMargins(10, 18, 10, 10)
        _gl5.setSpacing(5)
        _gl5.setColumnStretch(1, 2)
        _gl5.setColumnStretch(3, 2)
        _gl5.setColumnMinimumWidth(0, 120)
        _gl5.setColumnMinimumWidth(2, 120)

        _stk_lbl = QLabel(QApplication.translate("tilauscope_beancave","Stock left (g)"))
        _stk_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
        _stk_lbl.setFixedWidth(120)
        _stk_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _gl5.addWidget(_stk_lbl,              0, 0)
        _gl5.addWidget(self.weight_left_input, 0, 1)

        _tot_lbl = QLabel(QApplication.translate("tilauscope_beancave","Total roasted (g)"))
        _tot_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
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

        # ## TILAU ## Sack chips row (optional bag labels — invisible when the
        # bean has none, so unequipped users see the form exactly as before).
        self._current_sacks: list[str] = []
        self._sacks_lbl = QLabel(QApplication.translate("tilauscope_beancave","Sacks"))
        self._sacks_lbl.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:11px;background:transparent;border:none;padding:0;")
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
        ## TILAU ## Lot 5: the pane is read-first now — neutral prefix
        _editing_prefix = QLabel(QApplication.translate("tilauscope_beancave","Bean:"))
        _editing_prefix.setStyleSheet(f"color:{THEME['SUBTEXT']};font-size:10px;")
        self._notice_name_label = QLabel("—")
        self._notice_name_label.setStyleSheet(f"color:{THEME['TEXT']};font-weight:600;font-size:11px;")
        self._type_tag_label = QLabel("Single Origin")
        self._type_tag_label.setStyleSheet(
            f"background:rgba(137,180,250,25);border:1px solid rgba(137,180,250,60);"
            f"border-radius:4px;color:{THEME['ACCENT']};font-size:10px;padding:1px 6px;"
        )
        _nb_layout.addWidget(_editing_prefix)
        _nb_layout.addWidget(self._notice_name_label)
        _nb_layout.addStretch()
        _nb_layout.addWidget(self._type_tag_label)
        self._notice_bar.setStyleSheet(
            f"background:rgba(137,180,250,12);border-bottom:1px solid {THEME['BORDER']};"
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
        ## TILAU ## "New sack" guided assistant — head of the primary zone
        ## (validated mock v2: all buttons live in the bottom action bar)
        self.new_sack_button = QPushButton("+ " + QApplication.translate("tilauscope_beancave", "New sack"))
        self.new_sack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_sack_button.setStyleSheet(
            f"QPushButton {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
            f" border: none; border-radius: 6px; padding: 5px 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {THEME.get('HOVER', THEME['ACCENT'])}; }}")
        self.new_sack_button.setToolTip(QApplication.translate(
            "tilauscope_beancave",
            "Register an incoming bag of green coffee with a step-by-step "
            "assistant: new bean, restock or new crop — sack labelling stays "
            "optional."))
        self.new_sack_button.clicked.connect(self._open_new_sack_wizard)
        _actions_layout.addWidget(self.new_sack_button)
        _sep_ns = QFrame()
        _sep_ns.setFrameShape(QFrame.Shape.VLine)
        _sep_ns.setFixedHeight(20)
        _sep_ns.setStyleSheet(f"color:{THEME['BORDER']};max-width:1px;")
        _actions_layout.addWidget(_sep_ns)

        # ## TILAU ## Lot 5 step D (validated mock): + New sack | Roast · Label · QR |
        # Add (expert) … Delete. Update/Clear/Flavors/AI are absorbed by the sheet's
        # ✎ zone editors; the widgets stay alive (hidden) for the legacy code paths
        # that still drive their enabled state.
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
        # ## TILAU ## Lot 5: read-first sheet (page 0) over the legacy form (page 1).
        # Step B transition: any ✎ opens the full form; saving or selecting a
        # bean returns to the sheet. Step C will bring targeted zone editors.
        self.bean_sheet = BeanSheetWidget()
        self.bean_sheet.editRequested.connect(self._open_zone_editor)
        self.bean_sheet.sackReleased.connect(self._on_sack_released)
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self.bean_sheet)   # 0 — read
        self._right_stack.addWidget(_form_scroll)      # 1 — edit (legacy form)
        _right_layout.addWidget(self._right_stack, 1)
        _right_layout.addWidget(_actions_widget)

        # ── Pane gauche : datatable ─────────────────────────────────────────
        _left_pane = QWidget()
        _left_layout = QVBoxLayout(_left_pane)
        _left_layout.setContentsMargins(0, 0, 0, 0)
        _left_layout.setSpacing(0)
        # ## TILAU ## Lot 5: the rich rows list is the visible catalogue; the
        # legacy datatable stays in the layout but hidden — it remains the
        # selection model (row == green_beans index) every code path relies on.
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


    def update_ui_visibility(self) -> None:
        """Hides form + datatable and shows empty state message when needed. V2-compatible."""
        has_beans = self.cave is not None and len(self.cave.green_beans) > 0

        if not self.is_directory_defined:
            self.empty_state_label.setText(
                QApplication.translate("tilauscope_beancave",
                    "Please select your directories in the 'File Management' tab first.")
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
        # ## TILAU ## Lot 5: visibility drives the rich list; datatable stays hidden
        self.catalogue_list.setVisible(show_form)
        self.empty_state_label.setVisible(not show_form)
        if hasattr(self, '_notice_bar'):
            self._notice_bar.setVisible(show_form)


    def setup_file_management_tab_ui(self) -> None:
        file_management_layout = QVBoxLayout()

        button_layout = QGridLayout()
        self.select_beancave_directory_button = QPushButton(QApplication.translate("tilauscope_beancave","Select Beancave directory"))
        self.select_beancave_directory_button.clicked.connect(self.select_beancave_directory)
        self.beancave_directory_label = QLabel(QApplication.translate("tilauscope_beancave","Beancave directory")+f": {self.beancave_directory}")
        button_layout.addWidget(self.select_beancave_directory_button, 0, 0)
        button_layout.addWidget(self.beancave_directory_label, 0, 1, 1, 3)

        self.select_alog_directory_button = QPushButton(QApplication.translate("tilauscope_beancave","Select ALog directory"))
        self.select_alog_directory_button.clicked.connect(self.select_alog_directory)
        self.alog_directory_label = QLabel(QApplication.translate("tilauscope_beancave","ALog directory")+f": {self.alog_directory}")
        button_layout.addWidget(self.select_alog_directory_button, 1, 0)
        button_layout.addWidget(self.alog_directory_label, 1, 1, 1, 3)

        self.update_alog_counts_button = QPushButton(QApplication.translate("tilauscope_beancave","Update Roast Sessions"))
        self.update_alog_counts_button.clicked.connect(self.update_alog_counts)
        self.update_alog_counts_button.setToolTip(QApplication.translate("tilauscope_beancave","Scan the ALog directory to count the number of roast sessions associated with each green bean type. This information will be displayed in the main table and can help you track how many times each type of green bean has been roasted."))
        button_layout.addWidget(self.update_alog_counts_button, 2, 0)
        self.update_alog_counts_button.setEnabled(False)

        self.repair_alogs_button = QPushButton(QApplication.translate("tilauscope_beancave","Repair ALogs"))
        self.repair_alogs_button.setToolTip(QApplication.translate("tilauscope_beancave","Browse the ALog directory, audit incomplete roast profiles, link a green bean and complete missing fields one file at a time. A file is rewritten and renamed to its Artisan filename only when you press Record."))
        self.repair_alogs_button.clicked.connect(self._open_alog_repair)
        button_layout.addWidget(self.repair_alogs_button, 2, 1)

        self.export_csv_button = QPushButton(QApplication.translate("tilauscope_beancave","Export Roasts for LLM"))
        self.export_csv_button.clicked.connect(self.export_roast_data_to_csv)
        self.export_csv_button.setToolTip(QApplication.translate("tilauscope_beancave","Export roast session data to a CSV file formatted for use with Large Language Models (LLMs). This can be useful for training AI models, performing data analysis, or sharing roast data in a structured format. The exported CSV will include details of each roast session, such as date, duration, temperature profiles, and associated green bean types."))
        button_layout.addWidget(self.export_csv_button, 3, 0, 1, 1) # Prend 2 colonnes pour l'alignement
        self.export_csv_button.setEnabled(False)

        self.export_logs_button = QPushButton(QApplication.translate("tilauscope_beancave","Export Logs"))
        self.export_logs_button.setToolTip(QApplication.translate("tilauscope_beancave","Export logs for diagnostics."))
        self.export_logs_button.clicked.connect(self.export_logs_for_diagnostics)
        button_layout.addWidget(self.export_logs_button, 3, 1)

        self.export_pid_button = QPushButton(QApplication.translate("tilauscope_beancave","DEV TEST : Roasts for PID"))
        self.export_pid_button.clicked.connect(self.export_pid_analysis_to_csv)
        button_layout.addWidget(self.export_pid_button, 6, 0, 1, 1) # Prend 2 colonnes pour l'alignement
        self.export_pid_button.setEnabled(True)

        self.open_alarms_button = QPushButton(
            QApplication.translate("tilauscope_beancave", "Edit Alarms"))
        self.open_alarms_button.setToolTip(
            QApplication.translate("tilauscope_beancave",
                "Open the TilauScope alarm editor"))
        self.open_alarms_button.clicked.connect(self._open_alarm_editor)
        button_layout.addWidget(self.open_alarms_button, 7, 0, 1, 1)

        # ## TILAU ## Sack ID labels tool moved to the Stockage tab (conservation
        ## dashboard). Handler _open_sack_labels() is kept and reused from there.



        self.set_uuid_in_alog_button = QPushButton(QApplication.translate("tilauscope_beancave","Set UUID in old roast files"))
        self.set_uuid_in_alog_button.clicked.connect(self.update_alogs_with_uuids)
        self.set_uuid_in_alog_button.setToolTip(QApplication.translate("tilauscope_beancave","Update existing ALog roast session files with the UUIDs of the green beans as defined in the Beancave. This will allow for better tracking and association between your green bean records and roast sessions, especially for older roasts that were recorded before UUIDs were implemented. Use this function after defining your green beans and before performing any analysis that relies on UUIDs."))
        button_layout.addWidget(self.set_uuid_in_alog_button, 4, 0, 1, 1) 
        self.set_uuid_in_alog_button.setVisible(False) # hide it for the moment, disabled as should not be necessary anymore
        self.set_uuid_in_alog_button.setEnabled(False)

        ## TILAU ## The "Check for TilauScope update" button used to live here.
        # Update checking is owned by tilauscope.tilau_updater, which reads the
        # installer assets attached to the tilauscope_fork GitHub releases.

        self.file_management_tab.setLayout(file_management_layout)
        
        file_management_layout.addLayout(button_layout)
        file_management_layout.addStretch(3)

    ## TILAU ##
    @pyqtSlot()
    def _open_sack_labels(self) -> None:
        from tilauscope.sack_manager import SackLabelsDialog
        dlg = SackLabelsDialog(self)
        dlg.exec()

    ## TILAU ## New-sack guided assistant (design v4 §5) — Green Beans header button
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

    ## TILAU ## Lot 5 — catalogue rich list ⇄ hidden datatable selection sync
    @pyqtSlot(int)
    def _on_catalogue_row_activated(self, index: int) -> None:
        if 0 <= index < self.datatable.rowCount():
            self.datatable.selectRow(index)

    ## TILAU ## Lot 5 — read sheet ⇄ legacy form (Clear / AI still fill the form)
    def _enter_edit_mode(self, _zone: object = None) -> None:
        if hasattr(self, '_right_stack'):
            self._right_stack.setCurrentIndex(1)

    ## TILAU ## Lot 5 step C — ✎ opens a targeted modal editor for that zone
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

    ## TILAU ## Lot 5 step D — Add: full expert editor on a blank record
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

    ## TILAU ## ------- QR scan → record routing (spec wiki/QR-Scan-Spec.md §3.3) -------

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
    def _open_alarm_editor(self) -> None:
        from tilauscope.alarms import TilauAlarmDlg
        dlg = TilauAlarmDlg(self.aw, self.aw)
        dlg.show()
 
    @pyqtSlot()
    def _open_alog_repair(self) -> None:
        if not self.alog_directory or not Path(self.alog_directory).is_dir():
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Directory Error"),
                QApplication.translate("tilauscope_beancave",
                    "Please select a valid ALog directory in the File Management tab first."))
            return
        from tilauscope.alog_repair import AlogRepairDialog
        self._alog_repair_dlg = AlogRepairDialog(self, self.aw)  # keep ref (non-modal)
        self._alog_repair_dlg.repaired.connect(lambda _p: self.trigger_cache_refresh())
        self._alog_repair_dlg.show()

    @pyqtSlot()
    def export_logs_for_diagnostics(self) -> None:
        from tilauscope.tilau_exceptions import TilauCrashDialog
        tilau_crash_dialog = TilauCrashDialog("other", 0, 0, "Exporting logs for diagnostics...", True)
        tilau_crash_dialog = None

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
                    # ## TILAU ## stash the bean uuid on the first column so a row can be
                    # resolved back to its green_beans entry regardless of visual order.
                    item.setData(Qt.ItemDataRole.UserRole, getattr(bean, 'uuid', ''))
                self.datatable.setItem(row, col, item)
            # ## TILAU ## catalogue color codes (design v4 §2):
            # out-of-stock rows dimmed; crop-age badge on the Crop cell.
            try:
                if (getattr(bean, 'weight_left', 0.0) or 0.0) <= 0:
                    _dim = QColor("#6C7086")  # Catppuccin overlay0
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
        # ## TILAU ## Qt's built-in sort is deliberately left OFF: green_beans (the list)
        # is the single source of truth and every accessor indexes it by visual row.
        # Header clicks reorder the list via sort_by_column() then repopulate, so the
        # visual order and the list order can never diverge. (fix: dual-sort desync)
        self.datatable.setSortingEnabled(False)

        # ## TILAU ## Lot 5: refresh the visible rich list from the same beans
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
            self.set_uuid_in_alog_button.setEnabled(False)
            self.export_csv_button.setEnabled(False)
            self.update_alog_counts_button.setEnabled(False)

        elif len(beans) > 0:
            # Select the first row, which will trigger load_selected_bean_into_form
            self.datatable.selectRow(0)
            # ## TILAU ## Lot 5: datatable stays hidden — the rich list is the view
            self.add_button.setEnabled(True)
            self.clear_button.setEnabled(False) 
            self.generate_label_button.setEnabled(True)
            self.inject_from_ai_button.setEnabled(True)
            self.update_button.setEnabled(False)
            self.generate_qr_button.setEnabled(True)
            self.generate_card_button.setEnabled(True)
            self.roast.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.set_uuid_in_alog_button.setEnabled(True)
            self.export_csv_button.setEnabled(True)
            self.update_alog_counts_button.setEnabled(True)
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
            self._update_crop_age_indicator(int(bean.crop))  ## TILAU ## true value (0 = unset, no colour)
            self.density_input.setValue(bean.density)
            self.last_humidity_input.setValue(bean.last_humidity)
            self.water_activity_input.setValue(bean.water_activity)
            self.volume_input.setValue(bean.volume)
            self.altitude_input.setValue(bean.altitude)
            self.weight_input.setValue(bean.weight)

            self.species_combo.setCurrentText(bean.species if bean.species else "")
            self._update_variety(bean.species)
            self.varieties_combo.setCurrentText(bean.varieties if bean.varieties else "")

            self.weight_left_input.setValue(bean.weight_left)
            self.flavour_notes_input.setText(bean.flavour_notes)
            self.sca_input.setValue(bean.sca)
            self._set_form_sacks(getattr(bean, 'sacks', None) or [])  ## TILAU ##
            
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
                        f"background:rgba(137,180,250,25);border:1px solid rgba(137,180,250,60);"
                        f"border-radius:4px;color:{THEME['ACCENT']};font-size:10px;padding:1px 6px;"
                    )
            # now update roast plan accordingly
            self._update_roast_plan_ui_state()
            self.update_button.setEnabled(True)
            self.generate_qr_button.setEnabled(True)
            self.generate_card_button.setEnabled(True)
            # ## TILAU ## Only allow roasting a bean that is actually in stock.
            in_stock = (getattr(bean, "weight_left", 0.0) or 0.0) > 0
            self.roast.setEnabled(in_stock)
            self.roast.setToolTip(
                QApplication.translate("tilauscope_beancave", "Start a roast with this bean")
                if in_stock else
                QApplication.translate("tilauscope_beancave", "Out of stock — refill this bean before roasting")
            )
            self.remove_button.setEnabled(True)

            # ## TILAU ## Lot 5: refresh the read sheet and return to it
            if hasattr(self, 'bean_sheet'):
                self.bean_sheet.set_bean(bean)
                self._right_stack.setCurrentIndex(0)

        else:
            self.clear_form()

    ## TILAU ##
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

    ## TILAU ## ── sack chips (design v4 §6) ────────────────────────────────
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
                # ## TILAU ## Lot 5: reflect the release on the sheet and the list
                if hasattr(self, 'bean_sheet'):
                    self.bean_sheet.set_bean(bean)
                if hasattr(self, 'catalogue_list') and self.cave is not None:
                    self.catalogue_list.set_beans(self.cave.green_beans)
                _logd.debug(f"Sack {sack_id} released from '{bean.name}' back to the free pool")
        except Exception as e:
            _logd.error(f"Sack release failed for {sack_id}: {e}")

    @pyqtSlot()
    def add_new_row(self) -> None:
        """
        Ask the user whether to seed the new bean from the current form
        fields or start with a blank template, then act accordingly.
        """
        # ── Guard: ensure cave exists ──────────────────────────────────────
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            if self.cave is None:
                self.cave = BeanCaveContainer(green_beans=[], reference_profiles=[])
            else:
                self.cave.green_beans = []

        # ── Detect whether the form carries meaningful data ────────────────
        form_name: str = self.name_input.text().strip()
        form_has_data: bool = bool(
            form_name or
            self.farm_input.text().strip() or
            self.supplier_input.text().strip() or
            self.flavour_notes_input.text().strip() or
            self.weight_left_input.value() > 0.0 or
            self.sca_input.value() > 0.0 or
            self.altitude_input.value() > 0.0 or
            self.density_input.value() > 0.0 or
            self.last_humidity_input.value() > 0.0
        )

        # ── Show the choice dialog only when there is something in the form ─
        new_bean_data: GreenBean | None = None

        if form_has_data:
            dlg = AddBeanChoiceDialog(
                bean_name=form_name or QApplication.translate(
                    "tilauscope_beancave", "untitled"),
                parent=self
            )
            # Centre the dialog over the main window
            dlg.adjustSize()
            parent_geo = self.geometry()
            dlg.move(
                parent_geo.center().x() - dlg.width()  // 2,
                parent_geo.center().y() - dlg.height() // 2,
            )
            result = dlg.exec()

            if result != QDialog.DialogCode.Accepted:
                return  # User cancelled → do nothing

            if dlg.choice() == AddBeanChoiceDialog.CHOICE_FROM_FIELDS:
                # ── Build from form ──────────────────────────────────────
                is_blend = self.type_combo.currentText() == "Blend"
                new_bean_data = GreenBean(
                    name            = form_name or "New Bean",
                    farm            = self.farm_input.text().strip(),
                    country         = self.country_combo.currentText(),
                    supplier        = self.supplier_input.text().strip(),
                    category        = self.category_process_combo.currentText(),
                    process         = self.process_combo.currentText(),
                    crop            = int(self.crop_input.value()),
                    density         = self.density_input.value(),
                    last_humidity   = self.last_humidity_input.value(),
                    water_activity  = self.water_activity_input.value(),
                    volume          = self.volume_input.value(),
                    altitude        = int(self.altitude_input.value()),
                    species         = self.species_combo.currentText(),
                    varieties       = self.varieties_combo.currentText(),
                    weight_left     = self.weight_left_input.value(),
                    flavour_notes   = self.flavour_notes_input.text().strip(),
                    sca             = self.sca_input.value(),
                    count           = 0,
                    weight          = 0,
                    is_blend        = is_blend,
                    bean1_ratio     = self.bean1_ratio_input.value(),
                    bean2_name      = self.bean2_combo.currentText() if is_blend else '',
                    bean2_ratio     = self.bean2_ratio_input.value() if is_blend else 0.0,
                    bean3_name      = self.bean3_combo.currentText() if is_blend else '',
                    bean3_ratio     = self.bean3_ratio_input.value() if is_blend else 0.0,
                    blend_notes     = self.blend_notes_input.text().strip(),
                )
            else:
                # ── Blank template ───────────────────────────────────────
                new_bean_data = GreenBean(
                    name     = "New Bean",
                    crop     = 2024,
                    count    = 0,
                    category = "Traditional Dry",
                    process  = "Natural / Dry Process",
                    species  = "Arabica",
                    varieties= "Typica",
                )
        else:
            # Form is empty → skip the dialog, add a blank bean directly
            new_bean_data = GreenBean(
                name     = "New Bean",
                crop     = 2024,
                count    = 0,
                category = "Traditional Dry",
                process  = "Natural / Dry Process",
                species  = "Arabica",
                varieties= "Typica",
            )

        # ── Append, persist, refresh ───────────────────────────────────────
        self.cave.green_beans.append(new_bean_data)
        self.save_green_beans()
        self.populate_table()

        new_row_index = len(self.cave.green_beans) - 1
        if new_row_index >= 0:
            self.datatable.selectRow(new_row_index)
            self.load_selected_bean_into_form()

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
            current_count = self.cave.green_beans[selected_row_index].count
            ## TILAU ## captured before the record is replaced, to detect the 0 g
            ## transition once the new values are in (design v4 §9.3).
            prev_weight_left = float(getattr(self.cave.green_beans[selected_row_index], 'weight_left', 0.0) or 0.0)
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
                volume=self.volume_input.value(),
                altitude=int(self.altitude_input.value()),
                species=self.species_combo.currentText(),
                varieties=self.varieties_combo.currentText(),
                weight_left=self.weight_left_input.value(),
                flavour_notes=self.flavour_notes_input.text(),
                sca=self.sca_input.value(),
                count=current_count,
                weight=self.cave.green_beans[selected_row_index].weight,  ## TILAU ## preserve roasted total on update
                # --- Blend Fields (Mis à jour) ---
                is_blend=is_blend_selected,
                bean1_ratio=self.bean1_ratio_input.value(),
                bean2_name=self.bean2_combo.currentText() if is_blend_selected else '',
                bean2_ratio=self.bean2_ratio_input.value() if is_blend_selected else 0.0,
                bean3_name=self.bean3_combo.currentText() if is_blend_selected else '',
                bean3_ratio=self.bean3_ratio_input.value() if is_blend_selected else 0.0,
                blend_notes=self.blend_notes_input.text(),
                # unique identifier
                uuid=self.cave.green_beans[selected_row_index].uuid, # preserve uuid
                # tips
                tips=self.cave.green_beans[selected_row_index].tips,
                sacks=list(self._current_sacks),  ## TILAU ## preserve sack labels on update
            )
            self.cave.green_beans[selected_row_index] = new_bean_data
            _logd.debug(f"Green bean updated at {selected_row_index}: {new_bean_data.name}")
            self.save_green_beans()
            ## TILAU ## stock just hit 0 g: offer to reclaim this bean's labels
            ## (design v4 §9.3, shared helper — never duplicate this check).
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

    ## TILAU ##
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
        # ## TILAU ## Lot 5: styled confirmation (same dialog family as the rest)
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
        del self.cave.green_beans[index.row()]
        self.save_green_beans()
        self.populate_table()
        self.clear_form()

    def sort_green_beans(self, key: str) -> None:
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        self.cave.green_beans.sort(key=lambda bean: getattr(bean, key))
        self.populate_table()

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
            10: 'volume',
            11: 'altitude',
            12: 'species',
            13: 'varieties',
            14: 'weight_left',
            15: 'flavour_notes',
            16: 'sca',
            17: 'count',
            18: 'weight',
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
            if key in ['weight', 'stock', 'sca', 'density', 'crop', 'count', 'last_humidity', 'water_activity', 'volume', 'altitude', 'weight_left', 'bean1_ratio', 'bean2_ratio', 'bean3_ratio']:
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

        # ## TILAU ## Sorting reorders the list; rebuild the table so the visual order
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
                # New loop to ensure all beans have a UUID
                updated = False
                for bean in self.green_beans:
                    # Check if uuid is missing or None
                    if not hasattr(bean, 'uuid') or bean.uuid is None or bean.uuid == "":
                        bean.uuid = str(uuid.uuid4())
                        updated = True                    
                # If any UUIDs were generated, save the updated list immediately
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
                beancave_file_path.write_text(self.cave.to_json(), encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8')
            except Exception as e:
                _logd.error(f'Error writing to beancave.json: {e}')
                self._show_message(self, 
                                    QApplication.translate("tilauscope_beancave","Save Error"), 
                                    QApplication.translate("tilauscope_beancave","Unable to save file") + f" '{beancave_file_path}'. " + 
                                    QApplication.translate("tilauscope_beancave","Error")+f": {e}", QMessageBox.Icon.Warning)
        else:
            self.file_management_tab.setFocus() # if nothing has been set before, select the file management tab
            self._show_message(self, 
                                QApplication.translate("tilauscope_beancave","Save Error"), 
                                QApplication.translate("tilauscope_beancave","Please,  go to the file tab, select a directory to store the JSON beancave file and where your alog file are located. Then exit bean cave and relaunch it!"),
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
        self._update_crop_age_indicator(0)  ## TILAU ## cleared form shows no age colour
        self.density_input.setValue(0.0)
        self.last_humidity_input.setValue(0.0)
        self.water_activity_input.setValue(0.0)
        self.volume_input.setValue(0.0)
        self.altitude_input.setValue(0.0)
        self.species_combo.setCurrentIndex(0)
        self.varieties_combo.setCurrentIndex(0)
        self.weight_left_input.setValue(0.0)
        self.flavour_notes_input.clear()
        self.sca_input.setValue(0.0)
        self._set_form_sacks([])  ## TILAU ##
        # --- Blend Fields ---
        self.type_combo.setCurrentText("Single Origin")
        self.bean1_ratio_input.setValue(100.0)
        self.bean2_combo.setCurrentIndex(0)
        self.bean2_ratio_input.setValue(0.0)
        self.bean3_combo.setCurrentIndex(0)
        self.bean3_ratio_input.setValue(0.0)
        self.blend_notes_input.clear()
        # --------------------
        # ## TILAU ## Lot 5: empty selection → empty sheet
        if hasattr(self, 'bean_sheet'):
            self.bean_sheet.clear()

    def createdatatable(self) -> None:
        headers = greencave_headers
        self.datatable.setColumnCount(len(headers))
        self.datatable.setHorizontalHeaderLabels(headers)
        self.datatable.horizontalHeader().setSectionsMovable(True) # type: ignore
        self.datatable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # type: ignore
        self.datatable.itemSelectionChanged.connect(self.load_selected_bean_into_form)
        self.datatable.itemSelectionChanged.connect(self._sync_catalogue_selection)  ## TILAU ## Lot 5
        self.datatable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)  # type: ignore
        self.datatable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows) # type: ignore
        # ## TILAU ## Built-in sort stays OFF — sort_by_column() owns ordering (see populate_table).
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

    def load_settings(self) -> None:
        settings = QSettings()
        self.alog_directory = settings.value('alogDirectory', "", str)
        self.beancave_directory = settings.value('beancaveDirectory', self.alog_directory, str)
        try:
            self.C0_COLOR = float(settings.value(C0_COLOR_KEY, self.C0_COLOR))
            self.C_BT_COLOR = float(settings.value(C_BT_COLOR_KEY, self.C_BT_COLOR))
            self.C_DTR_COLOR = float(settings.value(C_DTR_COLOR_KEY, self.C_DTR_COLOR))
            self.C_WL_COLOR = float(settings.value(C_WL_COLOR_KEY, self.C_WL_COLOR))
            self.duration_rules = settings.value("duration_rules", {
                "drying": (4.0, 8.0),
                "maillard": (3.0, 5.0),
                "development": (1.5, 4.0),
                })
            self.current_roaster_model = settings.value("RoastPlan/RoasterModel", "", str)
        except Exception as e:
            _logd.warning(f"color prediction coefficients loading failed, falling back to defaults: {e}")

        settings.beginGroup("ProbeDeviation")
        self.probe_override = settings.value("ManualProbeSettings", False, bool)
        if not hasattr(self, 'dev_inputs'):
            return
        for key, widgets in self.dev_inputs.items():
            try:
                start_widget, end_widget = widgets
                # Read values, defaulting to 0.0 if not found
                val_start = settings.value(f"{key}_start", 0.0, type=float)
                val_end = settings.value(f"{key}_end", 0.0, type=float)
                
                start_widget.setValue(val_start)
                end_widget.setValue(val_end)
            except Exception as e:
                _logd.error(f"Error loading settings for {key}: {e}")
        settings.endGroup()
        
    @pyqtSlot()      
    def save_settings(self) -> None:
        settings = QSettings()
        settings.setValue('alogDirectory', self.alog_directory)
        settings.setValue('beancaveDirectory', self.beancave_directory)
        settings.setValue(C0_COLOR_KEY, self.C0_COLOR)
        settings.setValue(C_BT_COLOR_KEY, self.C_BT_COLOR)
        settings.setValue(C_DTR_COLOR_KEY, self.C_DTR_COLOR)
        settings.setValue(C_WL_COLOR_KEY, self.C_WL_COLOR)
        settings.setValue("duration_rules",self.duration_rules)
        settings.beginGroup("ProbeDeviation")
        for key, widgets in self.dev_inputs.items():
            try:
                start_widget, end_widget = widgets
                # Ensure we are saving raw floats
                settings.setValue(f"{key}_start", float(start_widget.value()))
                settings.setValue(f"{key}_end", float(end_widget.value()))
            except (AttributeError, ValueError) as e:
                _logd.warning(f"Could not save ProbeDeviation for {key}: {e}")
                continue
            settings.setValue("ManualProbeSettings", self.probe_override)
        settings.endGroup()
    
        settings.sync() # Forces immediate write to disk
        _logd.debug("Settings saved successfully.")
              
    def update_directory_labels(self) -> None:
        self.beancave_directory_label.setText(QApplication.translate("tilauscope_beancave", "Beancave directory: {0}").format(self.beancave_directory))
        self.alog_directory_label.setText(QApplication.translate("tilauscope_beancave","ALog directory: {0}").format(self.alog_directory))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_B and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.close()
        elif event.key() == Qt.Key.Key_Escape:
            # ESC sur un QDialog NonModal appelle reject() → hide() sans closeEvent.
            # On force close() pour déclencher closeEvent et le cleanup complet
            # (notamment _hover_tooltip top-level qui resterait sinon visible).
            self.close()
        else:
            super().keyPressEvent(event)

    # ── Density measurement window ─────────────────────────────────────────  ## TILAU ##
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

    @pyqtSlot('QCloseEvent')
    def closeEvent(self, event: QCloseEvent| None = None) -> None: # type: ignore 
        _log.info("beancave closing")
        # Fermeture en cours : neutralise les slots BLE queued (gardes is_shutting_down).
        with QMutexLocker(self.shutdown_lock):
            self.is_shutting_down = True
        # Stopper le timer de sélection immédiatement pour éviter
        # qu'un chargement ne démarre pendant ou après le cleanup
        if hasattr(self, '_selection_debounce'):
            self._selection_debounce.stop()
            # Déconnecter uniquement le signal connu pour éviter le warning Qt
            # "wildcard call disconnects from destroyed signal"
            try:
                self._selection_debounce.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass
        self._cancel_threads()        
        ## TILAU ## tear down the density window (disconnect scale signals first)
        if self._density_window is not None:
            self._disconnect_density_scale()
            try:
                self._density_window.close()
                self._density_window.deleteLater()
            except (RuntimeError, AttributeError):
                pass
            self._density_window = None
        try:
            self.datatable.selectionModel().selectionChanged.disconnect()
        except TypeError:
            pass # Déjà déconnecté        
        settings = QSettings()
        settings.setValue('BeanCaveGeometry', self.saveGeometry())
        header:QHeaderView = self.datatable.horizontalHeader() #type:ignore
        logical_indices = [header.logicalIndex(visual_index) for visual_index in range(header.count())]
        order_str = ','.join(map(str, logical_indices))
        settings.setValue('BeanCaveColumnOrder', order_str)
        for i in range(header.count()):
            settings.setValue(f'BeanCaveColumnWidth/{i}', header.sectionSize(i))
        if self.aw.beanCaveMenuAction is not None:
            self.aw.beanCaveMenuAction.setChecked(False)
        self.save_green_beans()
        self.save_settings()
        if hasattr(self, '_hover_tooltip'):
            self._hover_tooltip.hide()
            self._hover_tooltip.close()   # force fermeture fenêtre top-level (parent=None)
            self._hover_tooltip.deleteLater()
        from artisanlib.ble_port import bluetooth_enabled
        if bluetooth_enabled():
            # Couper les signaux BLE : aucun évènement queued ne doit tomber dans un widget détruit.
            if self.np is not None:
                for _sig in (self.np.at_connected, self.np.at_disconnected, self.np.error, self.np.status_updated):
                    try:
                        _sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass
            self.stopLebrewAGmanager()
            self.stopTilauAmbientManager()
            if self.np is not None:
                try:
                    self.np.stop()
                    _log.info("Niimbot printer connection and background scan stopped successfully.")
                except Exception as e:
                    _log.error(f"Error during Niimbot printer cleanup: {e}")
            else:
                _log.error("NiimbotPrinter object (self.np) is None.")
        # event may be None when close() is triggered programmatically without an event.
        if event is not None:
            event.accept()
            super().closeEvent(event)



    @override
    def showEvent(self, event):
        super().showEvent(event)
        # niimbot_overlay est un widget inline dans action_bar_layout — pas besoin de show()/move().

    def directory_validity_check(self, directory: str) -> bool:
        path_obj = Path(directory)
        if not path_obj.is_dir():
            self._show_message(self, 
                    QApplication.translate("tilauscope_beancave", "Invalid Directory"),
                    QApplication.translate("tilauscope_beancave", "The selected path is not a valid directory."), 
                    QMessageBox.Icon.Critical)
            self.raise_()
            _log.error(f"selected directory is not a directory: {directory}")
            return False
        if not os.access(directory, os.W_OK):
            # Custom message based on platform for better UX
            platform_msg = ""
            if  _IS_MACOS: # macOS
                platform_msg = "\n\n" + QApplication.translate("tilauscope_beancave", "On macOS, please ensure TilauScope has 'Full Disk Access' in System Settings if this is a protected folder.")
            elif _IS_WINDOWS:
                platform_msg = "\n\n" + QApplication.translate("tilauscope_beancave", "On Windows, ensure the folder is not marked 'Read-only' and your user has modify permissions.")
            self._show_message(self, 
                    QApplication.translate("tilauscope_beancave", "Permission Denied"),
                    QApplication.translate("tilauscope_beancave", "You do not have write permissions for this directory. TilauScope needs to save logs and metadata here.") + platform_msg,
                    QMessageBox.Icon.Warning)
            self.raise_()
            _log.error(f"selected directory has not enough rights to be used: {directory}")
            return False
            
        return True

    @pyqtSlot()
    def select_beancave_directory(self) -> None:
        """
        Opens a dialog to select the Beancave directory.
        Checks for directory validity and write permissions for macOS/Windows compatibility.
        """
        start_dir = str(self.beancave_directory) if self.beancave_directory and Path(self.beancave_directory).exists() else (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if _IS_WINDOWS:
            start_dir = start_dir.rstrip('\\')        

        directory = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_beancave","Select Beancave directory"), start_dir)
        if not directory:
            QTimer.singleShot(50, self._restore_focus)
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","Selection Cancelled"),
                QApplication.translate("tilauscope_beancave","Beancave directory selection was cancelled."),
                QMessageBox.Icon.Information)
            return
        if self.directory_validity_check(directory) and directory != self.beancave_directory:
            self.beancave_directory = directory.rstrip('\\') if _IS_WINDOWS else directory
            self.save_settings()
            self.load_green_beans()
            self.populate_table()
            self.update_directory_labels()
            self.is_directory_defined = str(self.beancave_directory) != "" and str(self.alog_directory) != ""
            self.update_ui_visibility()
            _logd.debug(f"Beancave directory selected: {self.beancave_directory}")
            self._show_message(self, 
            QApplication.translate("tilauscope_beancave","Beancave Directory Selected"),
            QApplication.translate("tilauscope_beancave","The directory") + f" '{self.beancave_directory}' " + 
            QApplication.translate("tilauscope_beancave","has been selected.\nThe beancave.json file is now loaded from this location."))
        if _IS_WINDOWS :
            self.raise_()

    @pyqtSlot()
    def select_alog_directory(self) -> None:
        """
        Opens a dialog to select the ALog directory.
        Checks for directory validity and write permissions for macOS/Windows compatibility.
        """
        start_dir = str(self.alog_directory) if self.alog_directory and Path(self.alog_directory).exists() else (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        if _IS_WINDOWS:
            start_dir = start_dir.rstrip('\\')        

        directory = QFileDialog.getExistingDirectory(self, QApplication.translate("tilauscope_beancave", "Select ALog Directory"),start_dir)
        if not directory:
            QTimer.singleShot(50, self._restore_focus)
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","Selection Cancelled"),
                QApplication.translate("tilauscope_beancave","ALog directory selection was cancelled."),
                QMessageBox.Icon.Information)
            return
        if self.directory_validity_check(directory) and directory != self.alog_directory:
            self.alog_directory = directory.rstrip('\\') if _IS_WINDOWS else directory
            self.save_settings()
            self.update_directory_labels()
            self.list_alog_files()
            _logd.debug(QApplication.translate("tilauscope_beancave","ALog directory selected")+f": {self.alog_directory}")
            self.is_directory_defined = str(self.beancave_directory) != "" and str(self.alog_directory) != ""
            self.update_ui_visibility()
            self._show_message(self,
                QApplication.translate("tilauscope_beancave","ALog Directory Selected"),
                QApplication.translate("tilauscope_beancave","The directory") +  f" '{self.alog_directory}' " + QApplication.translate("tilauscope_beancave","has been selected."),
                QMessageBox.Icon.Warning)
        else:
            if _IS_WINDOWS :
                self.raise_()

    @pyqtSlot()
    def update_alog_counts(self) -> None:
        if not self.alog_directory:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave",
                    "Please, select a valid ALog directory first."),
                QMessageBox.Icon.Warning)
            return
        directory = Path(self.alog_directory)
        if not directory.is_dir():
            return
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return

        progress = TilauProgressDialog(
            QApplication.translate("tilauscope_beancave", "Scanning roast profiles..."),
            self, len(self.cave.green_beans))
        progress.show()

        for bean in self.cave.green_beans:
            bean.count  = 0
            bean.weight = 0.0

        flag_update    = False
        orphaned_count = 0

        # Track which filenames were claimed so we can detect orphans
        claimed: set[str] = set()

        for bi, bean in enumerate(self.cave.green_beans):
            progress.pbar.setValue(bi)
            QApplication.processEvents()

            bean_uuid = getattr(bean, 'uuid', None)

            # ── Primary path: UUID index lookup (O(1), no I/O) ───────────────
            matched_fnames: list[str] = []
            if bean_uuid and bean_uuid in self._alog_uuid_index:
                matched_fnames = self._alog_uuid_index[bean_uuid]

            for fname in matched_fnames:
                claimed.add(fname)
                filepath = directory / fname
                try:
                    data = self.get_alog_data(filepath)
                    if data is None:
                        continue
                    flag_update = True
                    bean.count += 1
                    w_data = data.get('weight')
                    if w_data:
                        w = w_data[0]
                        if isinstance(w, (int, float)) and w > 0:
                            # ## TILAU ## normalise to grams before summing — profiles may be
                            # stored in g/Kg/lb/oz; w_data[2] is the source unit.
                            unit = w_data[2] if len(w_data) > 2 else 'g'
                            try:
                                src_idx = weight_units.index(unit)
                            except ValueError:
                                src_idx = 0  # unknown unit → assume grams
                            bean.weight += convertWeight(float(w), src_idx, 0)
                except OSError as e:
                    _logd.warning(f"update_alog_counts: cannot read {fname}: {e}")

        # Detect orphans: indexed files whose UUID doesn't match any cave bean
        for fname, uuid_val in self._alog_file_uuid.items():
            if fname not in claimed and uuid_val not in self.uuidmap:
                orphaned_count += 1
                _logd.warning(f"Orphaned roast: {fname} references missing UUID {uuid_val}")

        progress.pbar.setValue(len(self.cave.green_beans))
        progress.hide()
        progress.deleteLater()

        if flag_update:
            self.save_green_beans()
            self.populate_table()

        msg = QApplication.translate("tilauscope_beancave",
            "Information has been updated successfully.")
        if orphaned_count:
            msg += " " + QApplication.translate("tilauscope_beancave",
                "Orphaned roasts were detected and logged.")
        self._show_message(self,
            QApplication.translate("tilauscope_beancave", "Update finished"), msg)
    
    @pyqtSlot()
    def on_click_roast_properties(self) -> None:
        selected_row_index = self.datatable.currentRow()
        if selected_row_index == -1:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Error"), QApplication.translate("tilauscope_beancave","Select a line to start a Roast!"), QMessageBox.Icon.Warning)
            return
        if self.cave is None or not hasattr(self.cave, 'green_beans'):
            return
        from tilauscope.roast_properties import RoastSetupDialog
        self.roast_properties_dialog = RoastSetupDialog(self.cave.green_beans[selected_row_index], self)
        self.roast_properties_dialog.exec()

    @pyqtSlot()
    def generate_qr_code(self) -> None:
        """Génère et affiche le QR Code du bean sélectionné dans QRCodeDialog."""
        selected_row_index = self.datatable.currentRow()
        if selected_row_index == -1:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "Select a line to generate a QRCODE!"),
                QMessageBox.Icon.Warning
            )
            return
        if self.cave is None or not hasattr(self.cave, "green_beans"):
            return

        try:
            bean = self.cave.green_beans[selected_row_index]

            # ── Génération du QR ──────────────────────────────────────────────
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,  # type: ignore
                box_size=5,
                border=4,
            )
            qr.add_data(bean.to_json())
            qr.make(fit=True)
            img    = qr.make_image(fill_color="black", back_color="white")
            qimg   = ImageQt(img.convert("RGB"))                      # type: ignore
            pixmap = QPixmap.fromImage(qimg)

            # ── Affichage dans QRCodeDialog (style FlavorSelectorDialog) ──────
            dlg = QRCodeDialog(
                bean_name=bean.name,
                pixmap=pixmap,
                pil_img=img,
                parent=self,
            )
            dlg.exec()

        except Exception as e:
            self._show_message(
                self,
                QApplication.translate("tilauscope_beancave", "Error"),
                QApplication.translate("tilauscope_beancave", "An error happened while generating the QRCode:") + f" {e}",
                QMessageBox.Icon.Critical,
            )
            _logd.error(f"QRCode generation error: {e}")

    def update_regression_coefficients(self, roast_data_list: list[dict[str, Any]]):
        try:
            data_points = []
            
            # 1. Collecte et Nettoyage des points de données valides
            for roast_entry in roast_data_list:
                try:
                    # Target (Y): RoastColor
                    y = float(roast_entry.get('RoastColor', None)) #type:ignore
                    # Feature X1: Drop_BT (°C/°F)
                    bt_str = roast_entry.get('Drop_BT (°C/°F)', 'N/A')
                    bt_str_clean = re.sub(r'[°C°F]', '', bt_str).strip()
                    x1 = float(bt_str_clean) if bt_str_clean.lower() not in ('n/a', '') else None
                    # Feature X2: DTR%
                    x2 = float(roast_entry.get('DTR%', None)) #type:ignore
                    # Feature X3: WeightLoss (%)
                    x3 = float(roast_entry.get('WeightLoss (%)', None)) #type:ignore
                    # Vérification que toutes les valeurs clés sont présentes
                    if None in (x1, x2, x3, y):
                        continue

                    # 1. Perte de Poids (x3) : typiquement entre 10% et 25%
                    if not 10.0 <= x3 <= 25.0:
                        _logd.warning(f"Ignoré: Weight (x3) ({x3:.1f}%)")
                        continue

                    # 2. Température (x1) : Drop BT normal entre 180°C et 230°C
                    if not 180.0 <= x1 <= 230.0: #type:ignore
                        _logd.warning(f"Ignored: Drop BT (x1) ({x1:.1f}°)")
                        continue

                    # 3. Couleur (y)
                    if not 20.0 <= y <= 130.0:
                        _logd.warning(f"Ignored: Color (y) ({y:.1f})")
                        continue
                    
                    # Le point est valide pour la régression
                    data_points.append((y, x1, x2, x3))
                        
                except (ValueError, TypeError, KeyError) as e:
                    # Ignorer les entrées mal formées ou sans les clés nécessaires
                    _logd.debug(f"Ignored: entry incomple or corrupted : {e}")
                    continue

            if len(data_points) < 4:
                _logd.warning(f"Not enough values ({len(data_points)}) to compute regression (min 4).")
                return

            # 2. Calcul de la régression
            Y = numpy.array([p[0] for p in data_points]) # Target (Couleur)
            
            # Matrice X : [X1 (Drop_BT), X2 (DTR%), X3 (WeightLoss), X0 (Constante=1)]
            X = numpy.array([[p[1], p[2], p[3], 1] for p in data_points])

            coefficients, _, _, _ = numpy.linalg.lstsq(X, Y, rcond=None)
            
            # Les coefficients sont dans l'ordre de la Matrice X : [C_BT, C_DTR, C_WL, C0]
            C_BT, C_DTR, C_WL, C0 = coefficients
            
            # 3. Stockage et Sauvegarde
            self.C0_COLOR = C0
            self.C_BT_COLOR = C_BT
            self.C_DTR_COLOR = C_DTR
            self.C_WL_COLOR = C_WL
            
            # 4. Mise à jour du référentiel des profils après la régression
            
            self.construire_profils_referentiels(roast_data_list)            
            self.save_settings() # Sauvegarde des nouveaux coefficients dans QSettings
        except Exception as e:
            _logd.error(f"Fatal error computing regression values: {e}")

    @pyqtSlot()
    def update_alogs_with_uuids(self) -> None:
        """Counts roasts associated with green beans using partial name matching and UUIDs."""
        if not self.cave or not self.cave.green_beans:
            return
        total_count = len(self._metadata_cache.records)
        progress = QProgressDialog(QApplication.translate("tilauscope_beancave", "Scanning roast profiles..."), 
                                   None, 0, len(total_count), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        updated_count = 0

        # Reset counts
        for bean in self.cave.green_beans:
            bean.roasts = 0

        uuid_pattern = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')
        for i,record in enumerate(self._metadata_cache.records.values()):
            filename = record.filename
            progress.setValue(i)
            QApplication.processEvents()

            filepath = Path(self.alog_directory) / filename
            try:
                data = self.get_alog_data(filepath)
                if data is None:
                    continue
                bean_field = data.get("beans", "")
                title_field = data.get("title", "")
                
                matched_bean = None
                # 1. High Precision: UUID Match
                uuid_match = uuid_pattern.search(bean_field)
                if not uuid_match:                        
                    # now we have no uuid in beans field
                    clean_title = title_field.strip().lower() 
                    for bean in self.cave.green_beans:
                        # Check if the bean name is a substring of the roast title
                        if bean.name.lower() in clean_title:
                            matched_bean = bean
                            break
                    if matched_bean:
                        target_uuid = bean.uuid
                        # Append the uuid on a real new line (matches the
                        # canonical "\n".join(...) beans layout). Using "\\n"
                        # here injected a literal backslash that repr then
                        # re-escaped every save. ## TILAU ##
                        data["beans"] = data["beans"].rstrip() + f"\nuuid: {target_uuid}"
                        filepath.write_text(repr(data), encoding='utf-8')
                        # Keep indexes consistent
                        self._alog_uuid_index.setdefault(target_uuid, []).append(filename)
                        self._alog_file_uuid[filename] = target_uuid
                        updated_count += 1                  
            except Exception as e:
                _logd.error(f"Error parsing {filename}: {e}")

        progress.setValue(total_count)
        self.populate_table()
        self._show_message(self,
            QApplication.translate("tilauscope_beancave", "Update Complete"),
            QApplication.translate("tilauscope_beancave", "Finished! Updated {} roast profiles with UUIDs.").format(updated_count))

    def export_pid_analysis_to_csv(self):
        total_count = len(self._metadata_cache.records)

        if total_count ==0 :
            return
        
        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)

        default_path = str(Path(downloads_dir) / "roast_export.csv")

        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave", "Export PID Analysis Data"),
            default_path,
            QApplication.translate("tilauscope_beancave", "CSV Files (*.csv);;All Files (*)")
        )
        if not file_path: return

        progress = QProgressDialog(QApplication.translate("tilauscope_beancave", "Extracting time-series data..."),
                                None, 0, total_count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        uuid_pattern = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')

        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # Header as requested + debugging info
                writer.writerow([
                    'UUID', 'Time_s', 'Phase_Index', 'ET', 'BT', 
                    'Delta_ET', 'Delta_BT', 'Airflow', 'Airwave', 'Burner', 'Drum'
                ])

                _UUID_RE = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')

                for idx, record in enumerate(self._metadata_cache.records.values):
                    filename = record.filename
                    progress.setValue(idx)
                    if progress.wasCanceled(): break
                    
                    filepath = Path(self.alog_directory) / filename
                    data = self.get_alog_data(filepath)
                    if not data: continue

                    # Compute smoothed Deltas using existing Beancave logic
                    deltaet = self.evaldeltas(data, "temp1")
                    deltabt = self.evaldeltas(data, "temp2")
                    
                    timex = data.get('timex', [])
                    temp1 = data.get('temp1', []) # ET
                    temp2 = data.get('temp2', []) # BT
                    t_idx = data.get('timeindex', [])
                    
                    # Machine event data
                    ev_types = data.get('specialeventstype', [])
                    ev_vals = data.get('specialeventsvalue', [])
                    ev_times = data.get('specialevents', []) # Usually rel to charge
                    
                    bean_field = data.get("beans", "")
                    title_field = data.get("title","")
                    #                    first_part = re.split(r"[-/|,:;]", title_field, maxsplit=1)[0].strip()

                    # Inside the per-file loop, replace the UUID block with:
                    target_bean = None

                    # 1. Fast path: reverse index gives UUID directly from filename
                    file_uuid = self._alog_file_uuid.get(filename)
                    if file_uuid:
                        target_bean = self.uuidmap.get(file_uuid)

                    # 2. Fallback: parse beans field for files not in the index
                    if not target_bean:
                        bean_field = data.get("beans", "")
                        m = _UUID_RE.search(bean_field)
                        if m:
                            target_bean = self.uuidmap.get(m.group(1))

                    # 3. Last resort: name-in-title
                    if not target_bean:
                        title_lc = title_field.lower()
                        target_bean = next(
                            (b for b in self.cave.green_beans if b.name.lower() in title_lc), None)
                        
                    roast_uuid = target_bean.uuid if target_bean is not None else filename
                    charge_idx = t_idx[0] if t_idx and t_idx[0] >= 0 else 0
                    
                    # Store last known values for "step" logic
                    last_settings = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}

                    raw_bt = data.get('temp2', [])
                    raw_et = data.get('temp1', [])
                    times = data.get('timex', [])

                    # 2. Use a simple, continuous Delta calculation instead of evaldeltas
                    # This avoids the "phase reset" bug in the recomputeDeltas function
                    def calculate_continuous_ror(temp_list, time_list, window=30):
                        ror = [0.0] * len(temp_list)
                        for i in range(window, len(temp_list)):
                            dt = time_list[i] - time_list[i-window]
                            dy = temp_list[i] - temp_list[i-window]
                            if dt > 0:
                                # Calculate °/min
                                ror[i] = (dy / dt) * 60.0
                        return ror

                    delta_bt_continuous = calculate_continuous_ror(raw_bt, times)
                    delta_et_continuous = calculate_continuous_ror(raw_et, times)

                    for i in range(len(timex)):
                        curr_time_abs = timex[i]
                        curr_time_rel = curr_time_abs - timex[charge_idx]
                        
                        # Identify Phase
                        phase = -1
                        for p_idx, p_start_i in enumerate(t_idx):
                            if p_start_i != -1 and i >= p_start_i:
                                phase = p_idx

                        # Update machine settings logic (mimics findLastValidEvent)
                        for d in range(len(ev_times)):
                            if ev_times[d] <= curr_time_rel:
                                e_type = ev_types[d]
                                if e_type in last_settings:
                                    # Convert internal scale to external %
                                    raw_val = ev_vals[d] if ev_vals[d] is not None else 0.0
                                    last_settings[e_type] = self.aw.qmc.eventsInternal2ExternalValue(raw_val)

                        writer.writerow([
                            roast_uuid,
                            round(curr_time_rel, 1),
                            phase,
                            round(temp1[i], 2) if i < len(temp1) else '',
                            round(temp2[i], 2) if i < len(temp2) else '',
                            round(delta_et_continuous[i], 2) if delta_et_continuous and i < len(delta_et_continuous) and delta_et_continuous[i] is not None else 0.0,
                            round(delta_bt_continuous[i], 2) if delta_bt_continuous and i < len(delta_bt_continuous) and delta_bt_continuous[i] is not None else 0.0,
                            last_settings[1], # Airflow
                            last_settings[3], # Airwave
                            last_settings[0], # Burner
                            last_settings[2]  # Drum
                        ])
            progress.setValue(total_count)
            progress.hide()
            progress.deleteLater()
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Export"),
                QApplication.translate("tilauscope_beancave", "Extended PID analysis data exported."))
        except Exception as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Export Error"),
                QApplication.translate("tilauscope_beancave", "Failed: ") + str(e))
            if progress.isVisible():
                progress.hide()
                progress.deleteLater()

    @pyqtSlot()
    def export_roast_data_to_csv(self):
        """Exports roast data to CSV with extended fields matching the full version."""
        total_count = len(self._metadata_cache.records)
        if total_count == 0:
            return

        from PyQt6.QtCore import QStandardPaths

        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )

        default_path = str(Path(downloads_dir) / "roast_export.csv")

        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave", "Export Roast Data"),
            default_path,
            QApplication.translate("tilauscope_beancave", "CSV Files (*.csv);;All Files (*)")
        )
        if not file_path:
            return

        # Setup Progress Dialog
        progress = QProgressDialog(QApplication.translate("tilauscope_beancave", "Exporting roast data..."), 
                                   None, 0, total_count, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig' if _IS_WINDOWS else 'utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # Extended Headers
                writer.writerow([
                    # ── Identity ──────────────────────────────────────────────
                    'Date', 'Bean Name', 'UUID', 'unit',
                    # ── Weights ───────────────────────────────────────────────
                    'Batch Weight (g)', 'Weight Out (g)', 'Weight Loss (%)',
                    # ── Times ─────────────────────────────────────────────────
                    'Roast Time (s)', 'Dry Time (s)', 'Maillard Time (s)',
                    'Development Time (s)', 'DTR (%)',
                    # ── Turning Point ─────────────────────────────────────────
                    'TP Time (s)', 'TP BT', 'TP ET',
                    # ── Phase temperatures BT (calibration targets) ───────────
                    'Charge BT', 'Dry End BT', 'FC BT', 'Drop BT',
                    # ── Phase temperatures ET (machine fingerprint) ────────────
                    'Charge ET', 'Dry End ET', 'FC ET', 'Drop ET',
                    # ── ET/BT delta at TP (radiant vs drum fingerprint) ────────
                    'TP ET-BT Delta',
                    # ── Color ─────────────────────────────────────────────────
                    'whole color', 'ground color', 'color system',
                    # ── Bean properties ───────────────────────────────────────
                    'density',
                    # ── Ambient conditions ────────────────────────────────────
                    'Ambient Temp', 'Ambient Humidity', 'Ambient Pressure',
                    # ── Energy (RSE/CO2 — on-demand only) ────────────────────
                    'BTU Preheat', 'BTU Roast', 'BTU Cooling',
                    # ── AUC per phase ─────────────────────────────────────────
                    'AUC Dry', 'AUC Maillard', 'AUC Development',
                    # ── RoR per phase ─────────────────────────────────────────
                    'Ror Dry', 'Ror Maillard', 'Ror Development', 'Total Ror',
                    # ── Delta temp per phase ──────────────────────────────────
                    'Delta Temp Dry', 'Delta Temp Maillard', 'Delta Temp Development',
                    # ── Visual defects (boolean) ──────────────────────────────
                    'Heavy FC', 'Low FC', 'Tipping', 'Scorching', 'Divots', 'Uneven',
                    # ── Notes ─────────────────────────────────────────────────
                    'Roasting Notes', 'Cupping Notes',
                    # ── Sensory score (tilau_sensory_score — see RoastResultDialog) ──
                    'Sensory Score',
                ])

                _UUID_RE = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')

                for i, record in enumerate(self._metadata_cache.records.values()):
                    filename = record.filename
                    progress.setValue(i)
                    if progress.wasCanceled(): break
                    QApplication.processEvents()

                    filepath = Path(self.alog_directory) / filename
                    try:
                        data = self.get_alog_data(filepath) # filepath ou alog_file 
                        if data is None:
                            continue
                        computed:ComputedProfileInformation = data.get("computed", {})
                        bean_field = data.get("beans", "")
                        title_field = data.get("title","")
                        first_part = re.split(r"[-/|,:;]", title_field, maxsplit=1)[0].strip()

                        # Inside the per-file loop, replace the UUID block with:
                        target_bean = None

                        # 1. Fast path: reverse index gives UUID directly from filename
                        file_uuid = self._alog_file_uuid.get(filename)
                        if file_uuid:
                            target_bean = self.uuidmap.get(file_uuid)

                        # 2. Fallback: parse beans field for files not in the index
                        if not target_bean:
                            bean_field = data.get("beans", "")
                            m = _UUID_RE.search(bean_field)
                            if m:
                                target_bean = self.uuidmap.get(m.group(1))

                        # 3. Last resort: name-in-title
                        if not target_bean:
                            title_lc = title_field.lower()
                            target_bean = next(
                                (b for b in self.cave.green_beans if b.name.lower() in title_lc), None)
                        # Data Extraction
                        w_in = float(computed.get('weightin', 0))
                        w_out = float(computed.get('weightout', 0))
                        w_loss = float(round(((w_in - w_out) / w_in * 100), 2)) if w_in > 0 else 0.0
                        
                        t_dry = round(float(computed.get("DRY_time", 0.0)), 1)
                        t_fcs = round(float(computed.get("FCs_time", 0.0)), 1)
                        t_drop = round(float(computed.get("DROP_time", 0.0)), 1)
                        dtr = round(100.0*(t_drop-t_fcs)/t_drop,1)
                        name = target_bean.name if target_bean else first_part
                        if name == "":
                            _logd.warning(f"Empty name for roast '{title_field}' in file '{filename}'. Using 'N/A' instead.")
                            continue
                        if w_in==0.0 or w_out==0.0:
                            continue # skip entries with no weight or no drop time, as they are likely incomplete or failed roasts
                        # ── Phase BT temperatures ─────────────────────────────
                        _charge_bt  = computed.get('CHARGE_BT',  0.0) or 0.0
                        _dry_bt     = computed.get('DRY_BT',     0.0) or 0.0
                        _fc_bt      = computed.get('FCs_BT',     0.0) or 0.0
                        _drop_bt    = computed.get('DROP_BT',    0.0) or 0.0
                        # ── Phase ET temperatures ─────────────────────────────
                        _charge_et  = computed.get('CHARGE_ET',  0.0) or 0.0
                        _dry_et     = computed.get('DRY_ET',     0.0) or 0.0
                        _fc_et      = computed.get('FCs_ET',     0.0) or 0.0
                        _drop_et    = computed.get('DROP_ET',    0.0) or 0.0
                        # ── ET/BT delta at TP (machine fingerprint) ───────────
                        # Radiant: ET < BT at TP (negative delta, ~-26°C on SW)
                        # Drum gas: ET > BT at TP (positive delta)
                        _tp_bt      = computed.get('TP_BT',  0.0) or 0.0
                        _tp_et      = computed.get('TP_ET',  0.0) or 0.0
                        _tp_et_bt_delta = round(_tp_et - _tp_bt, 1) if _tp_bt > 0 and _tp_et > 0 else 'N/A'
                        # ── Visual defects ────────────────────────────────────
                        _heavy_fc   = 1 if data.get('heavyFC',   False) else 0
                        _low_fc     = 1 if data.get('lowFC',     False) else 0
                        _tipping    = 1 if data.get('tipping',   False) else 0
                        _scorching  = 1 if data.get('scorching', False) else 0
                        _divots     = 1 if data.get('divots',    False) else 0
                        _uneven     = 1 if data.get('uneven',    False) else 0
                        # ── Notes ─────────────────────────────────────────────
                        _roast_notes  = (data.get('roastingnotes', '') or '').replace('\n', ' ').strip()
                        _cupping_notes = (data.get('cuppingnotes', '') or '').replace('\n', ' ').strip()
                        # ── Sensory score (populated by RoastResultDialog) ────
                        # Field: data['tilau_sensory_score'] — float 0-100
                        # TODO: add tilau_sensory_score field to RoastResultDialog
                        _sensory_score = data.get('tilau_sensory_score', 'N/A')

                        writer.writerow([
                                # ── Identity ──────────────────────────────────
                                data.get('roastisodate', 'N/A'),
                                target_bean.name if target_bean else first_part,
                                getattr(target_bean, 'uuid', 'N/A'),
                                data.get("mode", "C"),
                                # ── Weights ───────────────────────────────────
                                w_in,
                                w_out,
                                w_loss,
                                # ── Times ─────────────────────────────────────
                                t_drop,  # total roast time
                                t_dry,
                                round((t_fcs - t_dry), 1) if t_fcs > t_dry else 0,
                                round((t_drop - t_fcs), 1) if t_drop > t_fcs else 0,
                                dtr,
                                # ── Turning Point ─────────────────────────────
                                computed.get('TP_time', 0.0),
                                _tp_bt,   # TP BT  (fix: was inverted in previous version)
                                _tp_et,   # TP ET
                                # ── Phase BT temperatures ─────────────────────
                                _charge_bt,
                                _dry_bt,
                                _fc_bt,
                                _drop_bt,
                                # ── Phase ET temperatures ─────────────────────
                                _charge_et,
                                _dry_et,
                                _fc_et,
                                _drop_et,
                                # ── ET/BT delta at TP ─────────────────────────
                                _tp_et_bt_delta,
                                # ── Color ─────────────────────────────────────
                                data.get('whole_color', 0),
                                data.get('ground_color', 0),
                                data.get("color_system", 'N/A'),
                                # ── Bean properties ───────────────────────────
                                computed.get('set_density', 'N/A') if target_bean and target_bean.density == 0 else target_bean.density if target_bean else 'N/A',
                                # ── Ambient conditions ────────────────────────
                                computed.get('ambient_temperature', 0),
                                computed.get('ambient_humidity', 0),
                                computed.get('ambient_pressure', 0),
                                # ── Energy ────────────────────────────────────
                                computed.get('BTU_preheat', 'N/A'),
                                computed.get('BTU_roast', 'N/A'),
                                computed.get('BTU_cooling', 'N/A'),
                                # ── AUC ───────────────────────────────────────
                                computed.get('dry_phase_AUC', 'N/A'),
                                computed.get('mid_phase_AUC', 'N/A'),
                                computed.get('finish_phase_AUC', 'N/A'),
                                # ── RoR ───────────────────────────────────────
                                computed.get('dry_phase_ror', 'N/A'),
                                computed.get('mid_phase_ror', 'N/A'),
                                computed.get('finish_phase_ror', 'N/A'),
                                computed.get('total_ror', 'N/A'),
                                # ── Delta temp ────────────────────────────────
                                computed.get('dry_phase_delta_temp', 'N/A'),
                                computed.get('mid_phase_delta_temp', 'N/A'),
                                computed.get('finish_phase_delta_temp', 'N/A'),
                                # ── Visual defects ────────────────────────────
                                _heavy_fc,
                                _low_fc,
                                _tipping,
                                _scorching,
                                _divots,
                                _uneven,
                                # ── Notes ─────────────────────────────────────
                                _roast_notes,
                                _cupping_notes,
                                # ── Sensory score ─────────────────────────────
                                _sensory_score,
                            ])
                    except Exception as e:
                        _logd.error(f"Error exporting {filename}: {e}")

            progress.setValue(total_count)
            progress.hide()
            progress.deleteLater()
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Export"),
                QApplication.translate("tilauscope_beancave", "Extended data exported successfully."))
        except Exception as e:
            if progress.isVisible():
                progress.hide()
                progress.deleteLater()
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Export Error"),
                QApplication.translate("tilauscope_beancave", "Could not save CSV: ") + str(e),
                QMessageBox.Icon.Critical)
        
    @pyqtSlot()
    def load_roast_in_artisan(self) -> None:
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self, 
                                QApplication.translate("tilauscope_beancave","Load in TilauScope"), 
                                QApplication.translate("tilauscope_beancave","Plese, select a roast session first."), QMessageBox.Icon.Warning)
            return
        
        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']
        full_path = Path(self.alog_directory) / alog_filename

        if not full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File error"), 
                                QApplication.translate("tilauscope_beancave", "File not found")+f": {full_path}", QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {full_path}")
            return

        try:
            self.aw.loadFile(str(full_path)) 
            self._show_message(self, 
                                    QApplication.translate("tilauscope_beancave","Load in TilauScope"), 
                                    f"'{alog_filename}' "+QApplication.translate("tilauscope_beancave","has been loaded in TilauScope."))
        except AttributeError:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Configuration error"), 
                                 QApplication.translate("tilauscope_beancave","Error accessing to main TilauScope routine."), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Loading error"), 
                                 QApplication.translate("tilauscope_beancave","An error occurred while loading file")+f": {e}", QMessageBox.Icon.Critical)
            _logd.error(f"Error loading aLog into TilauScope: {e}")

    @pyqtSlot()
    def load_roast_in_artisan_background(self) -> None:

        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self, 
                                QApplication.translate("tilauscope_beancave","TilauScope load"), 
                                QApplication.translate("tilauscope_beancave","Please, select a roast fist from the list."), QMessageBox.Icon.Warning)
            return

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']
        full_path = Path(self.alog_directory) / alog_filename

        if not full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File Error"), 
                                 QApplication.translate("tilauscope_beancave","File not found")+f": {full_path}", QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {full_path}")
            return

        try:
            self.aw.loadAndRedrawBackgroundUUID(str(full_path)) 
            self._show_message(self, QApplication.translate("tilauscope_beancave","TilauScope Load"), 
                                    f"'{alog_filename}'"+QApplication.translate("tilauscope_beancave"," has been loaded in main TilauScope window."))
        except AttributeError:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Confugration error"), 
                                 QApplication.translate("tilauscope_beancave","Error accessing to background TilauScope routine"), QMessageBox.Icon.Critical)
        except Exception as e:
            self._show_message(self, QApplication.translate("tilauscope_beancave","Load error"), 
                                QApplication.translate("tilauscope_beancave", "Une erreur s'est produite lors du chargement")+f": {e}", QMessageBox.Icon.Critical)
            _logd.error(f"Error loading ALog into Artisan: {e}")

    def get_cloud_template_info(self, one_code: str) -> dict[str, Any]|None:
    # 1. URL de l'API Niimbot Cloud
        API_URL = "https://print.niimbot.com/api/template/getCloudTemplateByOneCode"        
        payload = {
            "oneCode": one_code
        }
        headers = {
            "Content-Type": "application/json",
            "niimbot-user-agent": "AppVersionName/999.0.0"
        }
        try:
            response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=10)            
            response.raise_for_status() # Lève une exception pour les codes d'erreur 4xx/5xx
            data = response.json()
            if data.get("code") == 1:
                return data.get("data")
            return None
        except requests.exceptions.RequestException as e:
            _logd.debug(f"Error sending request to Niimbot Cloud {e}")
            return None
        except json.JSONDecodeError:
            _logd.debug("could not find any json answer from cloud api")
            return None
        
    @pyqtSlot()
    def niimbot_connected(self) -> None:
        # Afficher l'overlay dès la connexion (il était masqué au démarrage)
        if hasattr(self, "niimbot_overlay") and self.niimbot_overlay:
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Connecting…"),
                THEME["SUBTEXT"]
            )
        if self.np is not None:
            # BLE établi — le polling peut démarrer immédiatement,
            # même si le papier n'est pas encore détecté.
            self._niimbot_ble_up = True
            self._start_niimbot_poll()
            # Ne pas appeler stop/start_notifications ici : _connect() de ClientBLE
            # appelle déjà start_notifications() juste après on_connect().
            # Un double appel lève "Characteristic notifications already started".
            self.np.initialize()
            time.sleep(0.1)  # Laisser l'imprimante traiter le paquet initial
            hb = self.np.get_heartbeat()  # Pour s'assurer que la connexion est active
            deviceID = self.np.get_serial_number()
            firmwareVersion = self.np.get_software_version()
            rfid = self.np.get_rfid()
            self.np.paperstyle = self.np.get_paper_type()
            if rfid is not None and rfid.valid:
                _logd.debug(f"rfid detected, confirmed paper type={rfid.type} remaining labels={rfid.used_len}/{rfid.total_len}")
                self.np.used_labels = rfid.used_len if rfid.used_len is not None else 0
                self.np.total_labels = rfid.total_len if rfid.total_len is not None else 0
                t = self.get_cloud_template_info(str(rfid.barcode))
                if t is not None:  #swap as we print vertical on B21
                    self.np.paper_height = int(t["width"])
                    self.np.paper_width = int(t["height"])
            _logd.debug(f"Niimbot Device ID: {deviceID}")
            _logd.debug(f"Niimbot Firmware Version: {firmwareVersion}")
            _logd.debug(f"paper type h={self.np.paper_height}xw={self.np.paper_width}")
            # powerlevel = 0-5 (ink) 
            # paperstate = 0-2 (paper) 0=ok, 1=no paper, 2 = printer loader opened
            # closingstate = 0-2 (cover) 0=ok, 1=cover opened, 2=unstable state cannot print
            # rfidreadstate = 0-3 (rfid) 0=ok, 1=no rfid, 2=reading error, 3=no rfid support
            _logd.debug(f"hb received {hb.closingstate} {hb.powerlevel} {hb.paperstate} {hb.rfidreadstate}")
            if hb.powerlevel is not None and hb.powerlevel <= 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Power low"), THEME['WARNING'])
                _logd.warning(f"niimbot printer power is low {hb.powerlevel}/5")
            if hb.rfidreadstate is not None and hb.rfidreadstate != 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: RFID Error"), THEME['CRITICAL'])
                _logd.warning("niimbot rfid cannot be read")
                return
            if hb.paperstate is not None and hb.paperstate == 1 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Cover opened"), THEME['WARNING'])
                _logd.warning("niimbot printer has cover opened, must be closed before printing (1)")
                return
            if hb.paperstate is not None and hb.paperstate == 2 :
                self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Status error"), THEME['WARNING'])
                _logd.warning("niimbot printer status is unstable (2)")
                return
            
            if self.np.paper_height > 0 and self.np.paper_width > 0:
                text, color = self._niimbot_ready_status()
                self.niimbot_overlay.update_status(text, color)
                self._niimbot_connected = True
                self.print_label_button.setEnabled(True)
                _logd.debug("everything is ok")
                return
            self.niimbot_overlay.update_status(QApplication.translate("tilauscope_beancave","Printer: Invalid paper"), THEME['CRITICAL'])
            _logd.debug("paper cannot be used no size detected")
     
    @pyqtSlot()
    def niimbot_disconnected(self) -> None:
        with QMutexLocker(self.shutdown_lock):
            if self.is_shutting_down:
                _logd.debug("the app is closing, ignoring calls.")
                return
        _log.warning("niimbot printer disconnected unexpectedly")
        self._niimbot_connected = False
        self._niimbot_ble_up    = False
        self._stop_niimbot_poll()
        self.niimbot_overlay.update_status(
            QApplication.translate("tilauscope_beancave", "Printer: Disconnected"),
            THEME["CRITICAL"]
        )
        self.print_label_button.setEnabled(False)
        self.print_label_button.repaint()
   
    # À ajouter dans la classe BeancaveDlg
    # À ajouter dans la classe BeancaveDlg
    # ── Polling heartbeat Niimbot (5 s) ──────────────────────────────────────

    def _start_niimbot_poll(self) -> None:
        """Démarre le timer de polling heartbeat/RFID (5 s)."""
        if self._niimbot_poll_timer is not None:
            return  # déjà démarré
        self._niimbot_poll_timer = QTimer(self)
        self._niimbot_poll_timer.setInterval(5000)
        self._niimbot_poll_timer.timeout.connect(self._on_niimbot_poll_tick)
        if self.np is not None:
            self.np.status_updated.connect(self._on_niimbot_status)
            self.np.print_progress.connect(self._on_print_progress)
        self._niimbot_poll_timer.start()
        _logd.debug("Niimbot poll timer started (5 s)")

    def _stop_niimbot_poll(self) -> None:
        """Arrête le timer et déconnecte le signal."""
        if self._niimbot_poll_timer is not None:
            self._niimbot_poll_timer.stop()
            self._niimbot_poll_timer.deleteLater()
            self._niimbot_poll_timer = None
        if self.np is not None:
            try:
                self.np.status_updated.disconnect(self._on_niimbot_status)
            except (TypeError, RuntimeError):
                pass
            try:
                self.np.print_progress.disconnect(self._on_print_progress)
            except (TypeError, RuntimeError):
                pass
        _logd.debug("Niimbot poll timer stopped")

    @pyqtSlot()
    def _on_niimbot_poll_tick(self) -> None:
        """Tick du timer : lance poll_status() dans un QThread dédié.

        Si un thread précédent est encore actif, on skip ce tick pour ne pas
        empiler des requêtes BLE.
        """
        if self.np is None or not self._niimbot_ble_up:
            return
        if self._niimbot_poll_thread is not None and self._niimbot_poll_thread.isRunning():
            _logd.debug("Niimbot poll: thread précédent encore actif, skip.")
            return
        self._niimbot_poll_thread = QThread()
        worker = _NiimbotPollWorker(self.np)
        worker.moveToThread(self._niimbot_poll_thread)
        self._niimbot_poll_thread.started.connect(worker.run)
        worker.finished.connect(self._niimbot_poll_thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._niimbot_poll_thread.finished.connect(self._niimbot_poll_thread.deleteLater)
        self._niimbot_poll_thread.finished.connect(
            lambda: setattr(self, "_niimbot_poll_thread", None)
        )
        self._niimbot_poll_thread.start()

    def _niimbot_ready_status(self) -> tuple[str, str]:
        """Texte + couleur du bandeau quand l'imprimante est prête à imprimer.

        Source unique partagée par le connect et le poll 5 s : garantit que le
        compteur d'étiquettes (« B21S 50×30mm · N labels left ») s'affiche dès
        la connexion et ne soit plus écrasé par un format court « B21S: 50x30 »."""
        remaining = self.np.used_labels  if self.np else 0
        total     = self.np.total_labels if self.np else 0
        w = self.np.paper_width  if self.np else 0
        h = self.np.paper_height if self.np else 0
        labels_word = QApplication.translate("tilauscope_beancave", "labels left")
        count_txt   = f"{remaining}/{total}" if total > 0 else f"{remaining}"
        text  = f"B21S {w}×{h}mm · {count_txt} {labels_word}"
        color = THEME["WARNING"] if total > 0 and remaining / total < 0.1 else THEME["SUCCESS"]
        return text, color

    @pyqtSlot(object, object)
    def _on_niimbot_status(self, hb:NiimbotHeartbeat, rfid:NiimbotRFIDinfo) -> None:
        """Slot main-thread : met à jour l'overlay et paper_height si rouleau changé."""

        if not hb.valid:
            return

        # ── Détection ouverture/fermeture capot ──────────────────────────────
        cs = hb.closingstate
        ps = hb.paperstate
        self._niimbot_prev_closingstate = cs

        cover_open = (
            (cs is not None and cs != 0) or
            (ps is not None and ps != 0)
        )
        if cover_open:
            if ps == 1:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: No paper")
            elif ps == 2:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: Cover open")
            else:
                status_txt = QApplication.translate("tilauscope_beancave", "Printer: Cover open")
            self.niimbot_overlay.update_status(status_txt, THEME["WARNING"])
            self.print_label_button.setEnabled(False)
            return

        # ── Mise à jour RFID si rouleau changé ───────────────────────────────
        if rfid is not None and rfid.valid:
            prev_h = self.np.paper_height if self.np else 0
            self.np.used_labels  = rfid.used_len  if rfid.used_len  is not None else 0
            self.np.total_labels = rfid.total_len if rfid.total_len is not None else 0
            t = self.get_cloud_template_info(str(rfid.barcode))
            if t is not None:
                new_h = int(t["width"])
                new_w = int(t["height"])
                if new_h != prev_h:
                    _logd.debug(f"Niimbot poll: nouveau rouleau détecté {new_w}x{new_h}mm")
                self.np.paper_height = new_h
                self.np.paper_width  = new_w
                self.np.paperstyle   = self.np.get_paper_type()

        # ── Mise à jour overlay ───────────────────────────────────────────────
        if self.np is not None and self.np.paper_height > 0:
            text, color = self._niimbot_ready_status()
            self.niimbot_overlay.update_status(text, color)
            self.print_label_button.setEnabled(True)
        else:
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printer: Invalid paper"),
                THEME["CRITICAL"]
            )

    @pyqtSlot()
    def generate_and_print_label(self) -> None:
        from tilauscope.tilauscope_types import replace_accents  # noqa: F401
        if self.cave is None or not hasattr(self.cave, "green_beans"):
            return

        # ── Résoudre le GreenBean ────────────────────────────────────────────
        bean_field = self.last_plot_data.get("beans", "") if self.last_plot_data is not None else ""
        bean = None
        uuid_match = re.search(r"uuid: \s*([a-fA-F0-9-]{36})", bean_field)
        if uuid_match and self.cave and self.cave.green_beans:
            bean = self.uuidmap.get(uuid_match.group(1))

        if bean is None:
            selected_items = self.roast_list_widget.selectedItems()
            if not selected_items:
                self.roast_plot_label.setText(
                    replace_accents(QApplication.translate("tilauscope_beancave",
                        "Select a roast file to see the curve preview."))
                )
                self.roast_info_text.setText(
                    replace_accents(QApplication.translate("tilauscope_beancave",
                        "Roast Information will appear here."))
                )
                return
            selected_rows = self.datatable.selectionModel().selectedRows()  # type: ignore
            if not selected_rows:
                self._show_message(self,
                    QApplication.translate("tilauscope_beancave", "Print"),
                    QApplication.translate("tilauscope_beancave",
                        "Please, select a green bean first in the first tab, then the roast."),
                    QMessageBox.Icon.Warning)
                return
            bean = self.cave.green_beans[selected_rows[0].row()]

        # ── Vérifications imprimante ─────────────────────────────────────────
        if self.np is not None and (
            self.np.used_labels == 0 or
            (self.np.total_labels > 0 and self.np.used_labels >= self.np.total_labels)
        ):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave",
                    "There is no more labels on the roll, please load a new roll"),
                QMessageBox.Icon.Warning)
            return

        paper_height = 0 if self.np is None else self.np.paper_height
        paper_width  = 0 if self.np is None else self.np.paper_width

        if self.np is not None and (
            self.np.paperstyle == Niimprint_PaperType.UNKNOWN
            or paper_width == 0 or paper_height == 0
        ):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave",
                    "Label size or type of paper was not correctly detected, "
                    "please close and retry to open bean cave"),
                QMessageBox.Icon.Warning)
            return

        if paper_height not in (30, 80):
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Print"),
                QApplication.translate("tilauscope_beancave", "unsupported paper size")
                + f" {paper_width}x{paper_height}",
                QMessageBox.Icon.Warning)
            return

        labeltype = self.np.paperstyle  # type: ignore[union-attr]

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        filepath = Path(self.alog_directory) / meta["raw_fname"]

        try:
            data = self.get_alog_data(filepath)
            if data is None:
                raise ValueError("Failed to load alog data")

            # ── Construction de l'image déléguée à NiimbotLabelBuilder ──────
            from tilauscope.label_printer import NiimbotLabelBuilder
            builder = NiimbotLabelBuilder()
            img = builder.build(bean, data, paper_height)

            # ── Prévisualisation — style TilauScope ──────────────────────────
            WIDTH_PX, HEIGHT_PX = img.size
            from PIL.ImageQt import ImageQt
            qimage = ImageQt(img)
            pixmap = QPixmap.fromImage(qimage)
            pixmap = pixmap.scaled(
                int(WIDTH_PX * 1.0), int(HEIGHT_PX * 1.0),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

            # ── Dialog frameless + card THEME ────────────────────────────────
            preview_dialog = QDialog(self)
            preview_dialog.setWindowTitle(
                QApplication.translate("tilauscope_beancave", "Preview for Niimbot B21S")
            )
            preview_dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            preview_dialog.setWindowFlags(
                Qt.WindowType.Dialog |
                Qt.WindowType.FramelessWindowHint
            )

            outer_layout = QVBoxLayout(preview_dialog)
            outer_layout.setContentsMargins(0, 0, 0, 0)

            card = QFrame()
            card.setObjectName("NiimbotPreviewCard")
            card.setStyleSheet(f"""
                #NiimbotPreviewCard {{
                    background-color : {THEME['BG']};
                    border           : 2px solid {THEME['ACCENT']};
                    border-radius    : 14px;
                }}
            """)
            outer_layout.addWidget(card)

            root = QVBoxLayout(card)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(14)

            # Titre
            title_lbl = QLabel(
                QApplication.translate("tilauscope_beancave", "Preview for Niimbot B21S")
            )
            title_lbl.setStyleSheet(f"""
                color        : {THEME['ACCENT']};
                font-family  : 'JetBrains Mono', monospace;
                font-size    : 13px;
                font-weight  : 800;
                letter-spacing: 1px;
            """)
            root.addWidget(title_lbl)

            # Séparateur
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {THEME.get('BORDER', '#3f3f3f')};")
            root.addWidget(sep)

            # Image de prévisualisation
            img_lbl = QLabel()
            img_lbl.setPixmap(pixmap)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet(f"""
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
                border           : 1px solid {THEME.get('BORDER', '#3f3f3f')};
                border-radius    : 6px;
                padding          : 8px;
            """)
            root.addWidget(img_lbl)

            # Boutons
            btn_print  = QPushButton("🖨  " + QApplication.translate("tilauscope_beancave", "Print now"))
            btn_cancel = QPushButton(QApplication.translate("Button", "Cancel"))

            btn_print.setMinimumHeight(36)
            btn_cancel.setMinimumHeight(36)

            btn_print.setStyleSheet(f"""
                QPushButton {{
                    background-color : {THEME['ACCENT']};
                    color            : {THEME['BG']};
                    border           : none;
                    border-radius    : 6px;
                    padding          : 8px 18px;
                    font-family      : 'JetBrains Mono', monospace;
                    font-size        : 11px;
                    font-weight      : 700;
                }}
                QPushButton:hover {{
                    background-color : {THEME.get('ACCENT_LIGHT', THEME['ACCENT'])};
                }}
                QPushButton:pressed {{
                    background-color : {THEME.get('SURFACE', '#1e1e2e')};
                    color            : {THEME['ACCENT']};
                    border           : 1px solid {THEME['ACCENT']};
                }}
            """)
            btn_cancel.setStyleSheet(f"""
                QPushButton {{
                    background-color : transparent;
                    color            : {THEME.get('MUTED', '#888888')};
                    border           : none;
                    padding          : 6px 12px;
                    font-family      : 'JetBrains Mono', monospace;
                    font-size        : 10px;
                }}
                QPushButton:hover {{
                    color : {THEME['TEXT']};
                }}
            """)

            # Copies counter (default 1) — prints the same label N times.
            copies_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Copies"))
            copies_lbl.setStyleSheet(
                f"color:{THEME['SUBTEXT']};font-family:'JetBrains Mono',monospace;font-size:11px;border:none;")
            copies_spin = QSpinBox()
            copies_spin.setRange(1, 50)
            copies_spin.setValue(1)
            copies_spin.setFixedWidth(70)
            copies_spin.setStyleSheet(f"""
                QSpinBox {{
                    background:{THEME['SURFACE']}; color:{THEME['TEXT']};
                    border:1px solid {THEME['BORDER']}; border-radius:6px;
                    padding:4px 6px; font-family:'JetBrains Mono',monospace; font-size:12px;
                }}
            """)

            btn_row = QHBoxLayout()
            btn_row.addWidget(copies_lbl)
            btn_row.addWidget(copies_spin)
            btn_row.addStretch()
            btn_row.addWidget(btn_print)
            btn_row.addWidget(btn_cancel)
            root.addLayout(btn_row)

            btn_print.clicked.connect(preview_dialog.accept)
            btn_cancel.clicked.connect(preview_dialog.reject)

            if preview_dialog.exec() == QDialog.DialogCode.Accepted:
                # Progression affichée dans le bandeau statut non-modal (pas de
                # fenêtre modale : plus de fond grisé ni de clics bloqués).
                copies = int(copies_spin.value())
                self._roast_print_copies = copies
                self.niimbot_overlay.update_status(
                    QApplication.translate("tilauscope_beancave", "Printing..."), THEME["TEXT"]
                )
                self.niimbot_thread = QThread()
                self._roast_print_copy_i = 1
                self.niimbot_worker = NiimbotWorker(self.np, img, labeltype, copies=copies)
                self.niimbot_worker.copy_progress.connect(self._on_roast_copy_progress)
                self.niimbot_worker.moveToThread(self.niimbot_thread)

                self.niimbot_worker.print_finished.connect(self._on_print_success)
                self.niimbot_worker.print_error.connect(self._on_print_error)
                self.niimbot_thread.started.connect(self.niimbot_worker.run)
                self.niimbot_worker.print_finished.connect(self.niimbot_thread.quit)
                self.niimbot_worker.print_finished.connect(self.niimbot_worker.deleteLater)
                self.niimbot_worker.print_error.connect(self.niimbot_thread.quit)
                self.niimbot_worker.print_error.connect(self.niimbot_worker.deleteLater)
                self.niimbot_thread.finished.connect(self.niimbot_thread.deleteLater)
                self.niimbot_thread.start()

        except ValueError as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Niimbot B21S Print"),
                str(e),
                QMessageBox.Icon.Warning)
        except Exception as e:
            self._show_message(self,
                QApplication.translate("tilauscope_beancave", "Niimbot B21S Print"),
                QApplication.translate("tilauscope_beancave", "Error") + f" : {e}",
                QMessageBox.Icon.Critical)
            _logd.error(f"Label printing error: {e}")

    @pyqtSlot(int, int)
    def _on_print_progress(self, done: int, total: int) -> None:
        """Compteur de progression d'impression (thread worker → GUI).

        Affiché dans le bandeau statut non-modal « Printing… N/total » — pas de
        fenêtre modale qui grise le fond ou capture la souris. Le poll 5 s est
        suspendu pendant l'impression (verrou BLE), donc pas de conflit d'overlay.

        En impression multi-copies, on affiche « Printing copy i/N » plutôt que la
        progression par lignes (qui redémarre à chaque exemplaire).
        """
        if total <= 0:
            return
        if hasattr(self, "niimbot_overlay") and self.niimbot_overlay:
            copies = int(getattr(self, "_roast_print_copies", 1))
            if copies > 1:
                ci = int(getattr(self, "_roast_print_copy_i", 1))
                txt = QApplication.translate("tilauscope_beancave", "Printing copy") + f" {ci}/{copies}…"
            else:
                txt = QApplication.translate("tilauscope_beancave", "Printing...") + f" {done}/{total}"
            self.niimbot_overlay.update_status(txt, THEME["TEXT"])

    @pyqtSlot(int, int)
    def _on_roast_copy_progress(self, i: int, n: int) -> None:
        """Worker signal between copies of a multi-copy roast label run."""
        self._roast_print_copy_i = i
        self._roast_print_copies = n
        if n > 1 and hasattr(self, "niimbot_overlay") and self.niimbot_overlay:
            self.niimbot_overlay.update_status(
                QApplication.translate("tilauscope_beancave", "Printing copy") + f" {i}/{n}…",
                THEME["TEXT"],
            )

    def _on_print_success(self):
        # Décrémenter used_labels localement du nombre d'exemplaires imprimés
        # (le prochain poll RFID confirmera le compteur réel du rouleau).
        copies = int(getattr(self, "_roast_print_copies", 1))
        if self.np is not None and self.np.used_labels > 0:
            self.np.used_labels = max(0, self.np.used_labels - copies)
        self._roast_print_copies = 1
        self._roast_print_copy_i = 1
        # Remettre TOUT DE SUITE le statut imprimante (avec le compteur mis à
        # jour) à la place du « Printing… N/total », sans attendre le poll.
        if (hasattr(self, "niimbot_overlay") and self.niimbot_overlay
                and self.np is not None and self.np.paper_height > 0):
            text, color = self._niimbot_ready_status()
            self.niimbot_overlay.update_status(text, color)
        # Poll RFID différé pour confirmer le compteur réel du rouleau.
        QTimer.singleShot(500, self._on_niimbot_poll_tick)
        if copies > 1:
            m = QApplication.translate("tilauscope_beancave", "{0} labels correctly printed.\n").format(copies)
        else:
            m = QApplication.translate("tilauscope_beancave","Label correctly printed.\n")
        if self.np is not None:
            if self.np.total_labels > 0 and float(self.np.used_labels) <= float(self.np.total_labels) * 0.1:
                m += f"{self.np.used_labels} "+QApplication.translate("tilauscope_beancave","label(s) remaining on the roll, consider changing the roll.")
        self._show_message(self, 
                            QApplication.translate("tilauscope_beancave","Niimbot B21S Print"), 
                            QApplication.translate("tilauscope_beancave","label printed")+f": {m}")

    def _on_print_error(self, message):
        # Forcer un poll pour remettre l'overlay à jour après l'erreur
        self._roast_print_copies = 1
        self._roast_print_copy_i = 1
        QTimer.singleShot(500, self._on_niimbot_poll_tick)
        show_styled_message(self,
                            QApplication.translate("tilauscope_beancave","Niimbot B21S Print"), message,
                            QMessageBox.Icon.Warning)

    def print_niimbot_image_async(self, img, on_finished, on_error) -> None:
        """Print one 1-bit image on the connected Niimbot, no UI popup here.

        For satellite dialogs (Brew Advisor dial-in) that render their own
        in-window status. ``on_finished()`` / ``on_error(str)`` run on the GUI
        thread. BLE access is serialised by NiimbotBLE's internal lock, so this
        coexists safely with the 5 s heartbeat poll. The BeanCave printer
        overlay + remaining-labels counter are refreshed on success."""
        if self.np is None or not self._niimbot_connected:
            on_error(QApplication.translate("tilauscope_beancave", "Printer not ready"))
            return
        if getattr(self, "_sat_niimbot_thread", None) is not None and self._sat_niimbot_thread.isRunning():
            on_error(QApplication.translate("tilauscope_beancave", "A print is already in progress"))
            return
        self._sat_niimbot_thread = QThread()
        self._sat_niimbot_worker = NiimbotWorker(self.np, img, self.np.paperstyle)
        self._sat_niimbot_worker.moveToThread(self._sat_niimbot_thread)
        self._sat_niimbot_thread.started.connect(self._sat_niimbot_worker.run)

        def _post_ok():
            if self.np is not None and self.np.used_labels > 0:
                self.np.used_labels -= 1
            if (hasattr(self, "niimbot_overlay") and self.niimbot_overlay
                    and self.np is not None and self.np.paper_height > 0):
                text, color = self._niimbot_ready_status()
                self.niimbot_overlay.update_status(text, color)
            QTimer.singleShot(500, self._on_niimbot_poll_tick)

        self._sat_niimbot_worker.print_finished.connect(_post_ok)
        self._sat_niimbot_worker.print_finished.connect(on_finished)
        self._sat_niimbot_worker.print_error.connect(on_error)
        for sig in (self._sat_niimbot_worker.print_finished, self._sat_niimbot_worker.print_error):
            sig.connect(self._sat_niimbot_thread.quit)
            sig.connect(self._sat_niimbot_worker.deleteLater)
        self._sat_niimbot_thread.finished.connect(self._sat_niimbot_thread.deleteLater)
        self._sat_niimbot_thread.finished.connect(lambda: setattr(self, "_sat_niimbot_thread", None))
        self._sat_niimbot_thread.start()

    def generate_and_print_pdf_label(self):
        # get roast selected file
        selected_items = self.roast_list_widget.selectedItems()
        if not selected_items:
            self._show_message(self, 
                                QApplication.translate("tilauscope_beancave","TilauScope load"), 
                                QApplication.translate("tilauscope_beancave","Please, select a roast fist from the list."),
                                QMessageBox.Icon.Warning)
            return

        current_item = self.roast_list_widget.currentItem()
        meta = current_item.data(Qt.ItemDataRole.UserRole)
        alog_filename = meta['raw_fname']     
        alog_full_path = Path(self.alog_directory) / alog_filename

        if not alog_full_path.exists():
            self._show_message(self, QApplication.translate("tilauscope_beancave","File Error"), 
                                 QApplication.translate("tilauscope_beancave","File not found")+f": {alog_full_path}",
                                 QMessageBox.Icon.Critical)
            _logd.error(f"aLog file not found for loading: {alog_full_path}")
            return
        if alog_filename and self.last_plot_data is not None: # Fixe 2026/03/06 last plot data can be empty if alog file is malformed or corrupted
            # 'bean' field usually contains something like "Bean Name (uuid: xxxxxxxx-xxxx-...)"
            bean_field = self.last_plot_data.get("beans", "")
            target_bean = None
            # 2. Search for 'uuid: <uuid value>' in the bean field
            uuid_match = re.search(r'uuid: \s*([a-fA-F0-9-]{36})', bean_field)            
            if uuid_match:
                target_uuid = uuid_match.group(1)
                # 3. Load the bean from GreenBean objects
                if self.cave and self.cave.green_beans:
                    target_bean = self.uuidmap.get(target_uuid)
                    if target_bean is None:
                        self._show_message(self, 
                            QApplication.translate("tilauscope_beancave", "Missing Bean"),
                            QApplication.translate("tilauscope_beancave", "This roast is linked to a bean that no longer exists in your cave."),
                            QMessageBox.Icon.Warning)
                        return
            downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if not downloads_dir:
                downloads_dir = str(Path.home() / "Downloads")
            default_name = str(Path(downloads_dir) / f"roast_label_{alog_filename}.pdf")
            file_path = self._open_file_dialog_save( QApplication.translate("tilauscope_beancave", "Save Label PDF"), default_name, QApplication.translate("tilauscope_beancave", "PDF Files (*.pdf)"))            
            if file_path:
                from tilauscope.label_printer import RoastedBeanLabelPrinter
                printer = RoastedBeanLabelPrinter()
                try:
                    # Format natif Artisan : repr(dict) en UTF-8 — pas de unicode_escape
                    # (sinon mojibake sur les accents). literal_eval gère les échappements.
                    decoded_content = alog_full_path.read_text(encoding='utf-8')
                    roast_properties = cast('ProfileData', ast.literal_eval(decoded_content))
                    success = printer.print_to_label(roast_properties, target_bean, file_path)       
                    if success:
                        self._show_message(self, 
                                        QApplication.translate("tilauscope_beancave","Success"), 
                                        QApplication.translate("tilauscope_beancave","Label saved to")+f" {file_path}")
                        self.try_to_open_file(file_path)
                    else:
                        self._show_message(self, 
                                QApplication.translate("tilauscope_beancave","Error"), 
                                QApplication.translate("tilauscope_beancave","PDF file was not generated."),
                                QMessageBox.Icon.Warning)
                except Exception as e:
                    _logd.error(f"error printing to pdf: {e}")

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
        
        # 1. Create and show the non-blocking "Waiting" dialog (frameless/themed,
        # no cancel button so the background thread can't be interrupted mid-flight)
        self.ai_progress = TilauProgressDialog(
            QApplication.translate("tilauscope_beancave","Fetching and analyzing website content..."),
            self)
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
        self.ai_thread.finished.connect(self.ai_thread.deleteLater)

        self.ai_thread.start()

    def _set_wa_label_state(self, connected: bool) -> None:
        ## TILAU ## Reapply the FULL label stylesheet (must mirror the one set at
        ## creation): a bare "color: ..." rule would drop font-size/background/
        ## border/padding. Only the text color toggles between connected (theme
        ## green) and idle (default subtext). unpolish/polish forces Qt to
        ## re-evaluate the stylesheet so the repaint actually happens.
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
    def startLebrewAGmanager(self) -> None:
        from artisanlib.ble_port import bluetooth_enabled
        if bluetooth_enabled():
            _logd.debug('lebrew ag manager starting')
            if self.aw.bleRoastSeeAGDeviceName is not None and self.bleRoastSeeAGDevice is None: # Lebrew Roastsee AG support  
                self.bleRoastSeeAGDevice = LebrewWaterActivityChecker(self.aw.bleRoastSeeAGDeviceName)
                self.bleRoastSeeAGDevice.connected_signal.connect(self.slotStartLebrewAG)
                self.bleRoastSeeAGDevice.disconnected_signal.connect(self.slotStopLebrewAG)
                self.bleRoastSeeAGDevice.wa_changed_signal.connect(self.on_read_water_activity)
                
    @pyqtSlot()
    def stopLebrewAGmanager(self) -> None:
        from artisanlib.ble_port import bluetooth_enabled
        if bluetooth_enabled():
            if self.aw.bleRoastSeeAGDeviceName is not None and self.bleRoastSeeAGDevice is not None:
                try:
                    self.bleRoastSeeAGDevice.disconnect()
                except (TypeError, RuntimeError):
                    pass
                self.bleRoastSeeAGDevice = None
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
        from artisanlib.ble_port import bluetooth_enabled
        if bluetooth_enabled():
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
        # ## TILAU ## Lot 5: forward the reading to an open Characteristics
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
        self.volume_input.setValue(bean.volume)
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

    def load_bean_to_ui(self, bean: GreenBean):

        def update_combo(combo: QComboBox, value:str) -> None:
            if value == '':
                return
            index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            else: # fallback to last value if not found "(usually 'Other')"
                combo.setCurrentIndex(combo.count() - 1)

        # Remplissage des champs texte
        self.name_input.setText(bean.name)
        self.farm_input.setText(bean.farm)
        self.supplier_input.setText(bean.supplier)
        self.flavour_notes_input.setText(bean.flavour_notes)
        self.crop_input.setValue(bean.crop)
        self.density_input.setValue(bean.density)
        self.last_humidity_input.setValue(bean.last_humidity)
        self.water_activity_input.setValue(bean.water_activity)
        self.volume_input.setValue(bean.volume)
        self.altitude_input.setValue(bean.altitude)
        self.sca_input.setValue(bean.sca)
        
        update_combo(self.country_combo, bean.country)

        update_combo(self.category_process_combo, bean.category)
        update_combo(self.species_combo, bean.species)

        # This populates the second-level combos based on the selections above
        if bean.category:
            self._update_methods(bean.category)
        if bean.species:
            self._update_variety(bean.species)

        update_combo(self.process_combo, bean.process)
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
        
    @pyqtSlot()
    def on_print_label_clicked(self):
        # 1. Get selected bean data
        selected_rows = self.datatable.selectionModel().selectedRows()
        if not selected_rows:
            self._show_message(self, 
                                QApplication.translate("Button","Select"), 
                                QApplication.translate("tilauscope_beancave","Please select a bean from the table first."),
                                QMessageBox.Icon.Warning)
            return
            
        row = selected_rows[0].row()
        bean = self.cave.green_beans[row]

#        bean_data = self.helper.get_bean_data_by_index(row) # Using your existing helper

        if bean:
            # 2. Ask where to save
            downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            if not downloads_dir:
                downloads_dir = str(Path.home() / "Downloads")
            default_name = str(Path(downloads_dir) / f"Label_{bean.name}.pdf")
            file_path = self._open_file_dialog_save("Save Label PDF", default_name, "PDF Files (*.pdf)")
            
            if file_path:
                from tilauscope.label_printer import GreenBeanLabelPrinter
                logo_path = Path(getAppPath()) / "tilauscope.png"
                printer = GreenBeanLabelPrinter(logo_path) # set a logo if any
                success = printer.print_to_label(bean, file_path)
                
                if success:
                    self._show_message(self, 
                                            QApplication.translate("tilauscope_beancave","Success"), 
                                            QApplication.translate("tilauscope_beancave","Label saved to")+f" {file_path}")
                self.try_to_open_file(file_path)

    ## TILAU ## Export the selected bean sheet as a shareable landscape JPEG
    def on_export_social_card(self):
        selected_rows = self.datatable.selectionModel().selectedRows()
        if not selected_rows:
            self._show_message(self,
                                QApplication.translate("Button","Select"),
                                QApplication.translate("tilauscope_beancave","Please select a bean from the table first."),
                                QMessageBox.Icon.Warning)
            return

        row = selected_rows[0].row()
        bean = self.cave.green_beans[row]
        if not bean:
            return

        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not downloads_dir:
            downloads_dir = str(Path.home() / "Downloads")
        safe_name = re.sub(r'[^\w\-]+', '-', (bean.name or "bean")).strip('-') or "bean"
        default_name = str(Path(downloads_dir) / f"{safe_name}.jpg")
        file_path = self._open_file_dialog_save(
            QApplication.translate("tilauscope_beancave","Save Bean Card"),
            default_name, "JPEG Images (*.jpg)")
        if not file_path:
            return

        try:
            from tilauscope.beancave_social_card import GreenBeanSocialCard
            ok = GreenBeanSocialCard().save_jpeg(bean, file_path)
        except Exception as e:
            _logd.error(f"Bean card export failed: {e}", exc_info=True)
            ok = False

        if ok:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Success"),
                                QApplication.translate("tilauscope_beancave","Bean card saved to")+f" {file_path}")
            self.try_to_open_file(file_path)
        else:
            self._show_message(self,
                                QApplication.translate("tilauscope_beancave","Error"),
                                QApplication.translate("tilauscope_beancave","The bean card could not be generated."),
                                QMessageBox.Icon.Warning)

    def try_to_open_file(self, file_path: str):
        try:
            if _IS_WINDOWS:
                os.startfile(file_path)
            elif  _IS_MACOS:
                subprocess.Popen(["open", file_path])  # Popen non-bloquant
            else:
                subprocess.Popen(["xdg-open", file_path])  # Popen non-bloquant
        except Exception as e:
            _log.error(f"Failed to open file {file_path}: {e}")

        # Restitue le focus à BeancaveDlg après que l'OS ait traité l'ouverture
        QTimer.singleShot(300, self._restore_focus)

    def _restore_focus(self):
        if self.is_shutting_down:
            return
        if self.isVisible() and not self.isMinimized():
            self.raise_()
            self.activateWindow()        
        
    def _show_message(self, parent, title: str, message: str, icon=QMessageBox.Icon.Information, **kwargs):
        show_styled_message(parent, title, message, icon, **kwargs)
        QTimer.singleShot(100, self._restore_focus)

    def _open_file_dialog_save(self, title: str, default: str, filter_str: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, default, filter_str)
        QTimer.singleShot(50, self._restore_focus)
        return path

# ─────────────────────────────────────────────────────────────────────────────
# DROP-IN REPLACEMENT — paste this block into beancave.py
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. Styled "Add bean" choice dialog ────────────────────────────────────────

class AddBeanChoiceDialog(QDialog):
    """
    Modal dialog that asks the user whether to add a new bean
    pre-filled from the current form fields, or start from a blank slate.

    Styled to match TilauScope's dark THEME (frameless + translucent).
    Works identically on macOS and Windows 10/11.
    """

    # Return codes
    CHOICE_FROM_FIELDS = 1
    CHOICE_BLANK       = 2

    def __init__(self, bean_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._choice: int = 0

        # ── Outer shell (gives the translucent rounded frame) ──────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("AddBeanCard")
        card.setStyleSheet(f"""
            #AddBeanCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
        """)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Icon + title ───────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        icon_lbl = QLabel("🫘")
        icon_lbl.setStyleSheet("font-size: 26px;")
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Add New Bean"))
        title_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 14px;
            font-weight : 800;
            letter-spacing: 1px;
        """)

        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        root.addLayout(title_row)

        # ── Separator ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME.get('BORDER', '#3f3f3f')};")
        root.addWidget(sep)

        # ── Question ───────────────────────────────────────────────────────
        if bean_name:
            q_text = (
                QApplication.translate("tilauscope_beancave",
                    "The form contains data for") +
                f" <b style='color:{THEME['ACCENT']};'>{bean_name}</b>.<br>" +
                QApplication.translate("tilauscope_beancave",
                    "How do you want to create the new entry?")
            )
        else:
            q_text = QApplication.translate("tilauscope_beancave",
                "How do you want to create the new entry?")

        q_lbl = QLabel(q_text)
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(f"""
            color       : {THEME['TEXT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 11px;
        """)
        root.addWidget(q_lbl)

        # ── Buttons ────────────────────────────────────────────────────────
        btn_style_primary = f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
                font-weight      : 700;
            }}
            QPushButton:hover {{
                background-color : {THEME.get('ACCENT_LIGHT', THEME['ACCENT'])};
            }}
            QPushButton:pressed {{
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
        """
        btn_style_secondary = f"""
            QPushButton {{
                background-color : transparent;
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME.get('BORDER', '#3f3f3f')};
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
            }}
            QPushButton:hover {{
                border-color : {THEME['ACCENT']};
                color        : {THEME['ACCENT']};
            }}
            QPushButton:pressed {{
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
            }}
        """
        btn_style_cancel = f"""
            QPushButton {{
                background-color : transparent;
                color            : {THEME.get('MUTED', '#888888')};
                border           : none;
                padding          : 6px 12px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 10px;
            }}
            QPushButton:hover {{
                color : {THEME['TEXT']};
            }}
        """

        btn_from_fields = QPushButton(
            "📋  " + QApplication.translate("tilauscope_beancave",
                                             "From current fields"))
        btn_from_fields.setStyleSheet(btn_style_primary)
        btn_from_fields.setMinimumHeight(36)
        btn_from_fields.clicked.connect(self._choose_from_fields)

        btn_blank = QPushButton(
            "✨  " + QApplication.translate("tilauscope_beancave",
                                            "Blank bean"))
        btn_blank.setStyleSheet(btn_style_secondary)
        btn_blank.setMinimumHeight(36)
        btn_blank.clicked.connect(self._choose_blank)

        btn_cancel = QPushButton(
            QApplication.translate("tilauscope_beancave", "Cancel"))
        btn_cancel.setStyleSheet(btn_style_cancel)
        btn_cancel.clicked.connect(self.reject)

        # ── Hint labels under each main button ────────────────────────────
        hint_fields = QLabel(
            QApplication.translate("tilauscope_beancave",
                "Pre-fill from what you have typed so far"))
        hint_fields.setStyleSheet(
            f"color:{THEME.get('MUTED','#888888')}; font-size:9px;"
            f"font-family:'JetBrains Mono',monospace;")
        hint_fields.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint_blank = QLabel(
            QApplication.translate("tilauscope_beancave",
                "Start fresh with default values"))
        hint_blank.setStyleSheet(
            f"color:{THEME.get('MUTED','#888888')}; font-size:9px;"
            f"font-family:'JetBrains Mono',monospace;")
        hint_blank.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.addWidget(btn_from_fields)
        btn_col.addWidget(hint_fields)
        btn_col.addSpacing(6)
        btn_col.addWidget(btn_blank)
        btn_col.addWidget(hint_blank)
        btn_col.addSpacing(4)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        cancel_row.addWidget(btn_cancel)

        root.addLayout(btn_col)
        root.addLayout(cancel_row)

        self.setMinimumWidth(360)

    # ── Slots ──────────────────────────────────────────────────────────────
    def _choose_from_fields(self) -> None:
        self._choice = self.CHOICE_FROM_FIELDS
        self.accept()

    def _choose_blank(self) -> None:
        self._choice = self.CHOICE_BLANK
        self.accept()

    def choice(self) -> int:
        """Returns CHOICE_FROM_FIELDS, CHOICE_BLANK, or 0 (cancelled)."""
        return self._choice

class NiimbotStatusOverlay(QWidget):
    """
    Statut imprimante Niimbot — widget inline dans l'action_bar_layout du viewer.
    Pas de fenêtre flottante, pas de z-order, pas d'overlay : juste un QWidget
    avec icône + label, inséré directement dans le layout de la barre de boutons.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(5)

        self.icon_label = QLabel("🖨️")
        self.icon_label.setStyleSheet("font-size: 13px; background: transparent; border: none;")

        self.status_label = QLabel(QApplication.translate("tilauscope_beancave", "Printer: Disconnected"))
        self._apply_style(THEME['CRITICAL'])

        lay.addWidget(self.icon_label)
        lay.addWidget(self.status_label)

        self.setStyleSheet(f"""
            NiimbotStatusOverlay {{
                background-color: {THEME['SURFACE']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
            }}
        """)

    def _apply_style(self, color_hex: str):
        self.status_label.setStyleSheet(f"""
            color: {color_hex};
            font-size: 11px;
            font-family: 'JetBrains Mono';
            font-weight: bold;
            background: transparent;
            border: none;
        """)

    def update_status(self, text: str, color_hex: str):
        self.status_label.setText(text)
        self._apply_style(color_hex)

class AwReadingOverlay(QFrame):
    def __init__(self, parent=None):
        # Using WindowStaysOnTopHint and FramelessWindowHint to match Beancave's custom dialog style
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint | 
                                 Qt.WindowType.FramelessWindowHint | 
                                 Qt.WindowType.Tool)
        
        # Match Beancave's transparency and focus behavior
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Import THEME from your types (assuming it's available in scope)
        from tilauscope.tilauscope_types import THEME

        # Main Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 10, 15, 10)

        # Inner container for styling (Matches #MainContainer in beancave.py)
        self.container = QFrame()
        self.container.setObjectName("OverlayContainer")
        self.container.setStyleSheet(f"""
            #OverlayContainer {{
                background-color: {THEME['BG']}; 
                border: 2px solid {THEME['ACCENT']};
                border-radius: 12px;
            }}
        """)
        
        inner_layout = QVBoxLayout(self.container)
        
        # Header text (Accent color, JetBrains Mono)
        self.title_label = QLabel(QApplication.translate("tilauscope_beancave", "WATER ACTIVITY"))
        self.title_label.setStyleSheet(f"""
            color: {THEME['ACCENT']}; 
            font-size: 10px; 
            font-weight: 800; 
            font-family: 'JetBrains Mono';
            letter-spacing: 1px;
        """)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Value display
        self.value_label = QLabel("0.000")
        self.value_label.setStyleSheet(f"""
            color: {THEME['TEXT']}; 
            font-size: 24px; 
            font-weight: bold; 
            font-family: 'JetBrains Mono';
        """)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        inner_layout.addWidget(self.title_label)
        inner_layout.addWidget(self.value_label)
        self.layout.addWidget(self.container)

        # Animation setup
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(300)

    def update_value(self, value):
        """Updates label and triggers a small 'pulse' animation."""
        self.value_label.setText(str(value))
        self.adjustSize()
        
    def show_fancy(self):
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(0.95) # Slightly transparent
            self.fade_anim.start()

    def hide_fancy(self):
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.hide)
        self.fade_anim.start()

class BeanAIWorker(QObject):
    # Signal to return the extracted GreenBean object
    finished = pyqtSignal(GreenBean) 
    error = pyqtSignal(str)

    def __init__(self, ai: TilauAIConfig, url: str, coffee_beans_categories:list[str], coffee_processing_methods:dict[str, list[str]], coffee_producing_countries: list[str], coffee_bean_types:dict[str, list[str]], coffee_beans_species: list[str]):
        super().__init__()
        self.ai = ai
        self.url = url
        self.coffee_beans_categories = coffee_beans_categories
        self.coffee_processing_methods = coffee_processing_methods
        self.coffee_producing_countries = coffee_producing_countries
        self.coffee_bean_types = coffee_bean_types
        self.coffee_beans_species = coffee_beans_species

    def run(self):
        try:
            from tilauscope.bean_extractor import CoffeeAIParser
            parser = CoffeeAIParser(
                                    self.ai, 
                                    self.coffee_beans_categories, 
                                    self.coffee_processing_methods, 
                                    self.coffee_producing_countries,
                                    self.coffee_bean_types, 
                                    self.coffee_beans_species)
            # This is the time-consuming Gemini call
            result = parser.get_bean_from_url(self.url)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class URLInputDialog(QDialog):
    """Frameless, THEME-styled prompt for the supplier URL to AI-parse.

    Styled to match TilauScope's dark THEME (frameless + translucent), same
    pattern as AddBeanChoiceDialog / QRCodeDialog.
    """

    def __init__(self, parent=None):
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(400)

        # ── Outer shell (gives the translucent rounded frame) ──────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("URLInputCard")
        card.setStyleSheet(f"""
            #URLInputCard {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
        """)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Icon + title ─────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        icon_lbl = QLabel("✨")
        icon_lbl.setStyleSheet("font-size: 26px;")
        title_lbl = QLabel(QApplication.translate("tilauscope_beancave", "Search for bean data using AI"))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 14px;
            font-weight : 800;
            letter-spacing: 1px;
        """)
        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl, 1)
        root.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME.get('BORDER', '#3f3f3f')};")
        root.addWidget(sep)

        _input_style = f"""
            QLineEdit {{
                background      : {THEME.get('SURFACE', '#181825')};
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME.get('BORDER', '#3f3f3f')};
                border-radius    : 7px;
                padding          : 7px 10px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
            }}
            QLineEdit:focus {{
                border: 1px solid {THEME['ACCENT']};
            }}
        """
        self.url_input = QLineEdit()
        self.url_input.setStyleSheet(_input_style)
        self.url_input.setPlaceholderText(QApplication.translate("tilauscope_beancave","Enter URL of supplier here..."))
        self.url_input.setMinimumHeight(30)

        btn_style_secondary = f"""
            QPushButton {{
                background-color : transparent;
                color            : {THEME['TEXT']};
                border           : 1px solid {THEME.get('BORDER', '#3f3f3f')};
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
            }}
            QPushButton:hover {{
                border-color : {THEME['ACCENT']};
                color        : {THEME['ACCENT']};
            }}
            QPushButton:pressed {{
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
            }}
            QPushButton:disabled {{
                color : {THEME.get('MUTED', '#888888')};
                border-color : {THEME.get('BORDER', '#3f3f3f')};
            }}
        """
        btn_style_primary = f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
                font-weight      : 700;
            }}
            QPushButton:hover {{
                background-color : {THEME.get('ACCENT_LIGHT', THEME['ACCENT'])};
            }}
            QPushButton:pressed {{
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
        """
        btn_style_cancel = f"""
            QPushButton {{
                background-color : transparent;
                color            : {THEME.get('MUTED', '#888888')};
                border           : none;
                padding          : 6px 12px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 10px;
            }}
            QPushButton:hover {{
                color : {THEME['TEXT']};
            }}
        """

        # Button: Paste URL
        self.btn_paste = QPushButton(QApplication.translate("tilauscope_beancave","Paste URL"))
        self.btn_paste.setStyleSheet(btn_style_secondary)
        self.btn_paste.clicked.connect(self.paste_url)

        # Connection for dynamic update when clipboard changes
        QGuiApplication.clipboard().dataChanged.connect(self.update_paste_button_state)

        # Set initial state
        self.update_paste_button_state()

        # Boutons Validation
        self.btn_ok = QPushButton(QApplication.translate("tilauscope_beancave","Extract data"))
        self.btn_ok.setStyleSheet(btn_style_primary)
        self.btn_ok.setMinimumHeight(34)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton(QApplication.translate("Button","Cancel"))
        self.btn_cancel.setStyleSheet(btn_style_cancel)
        self.btn_cancel.clicked.connect(self.reject)

        root.addWidget(self.url_input)
        root.addWidget(self.btn_paste)

        btns_layout = QHBoxLayout()
        btns_layout.addWidget(self.btn_ok)
        btns_layout.addStretch(1)
        btns_layout.addWidget(self.btn_cancel)
        root.addLayout(btns_layout)

    def update_paste_button_state(self):
        """Checks clipboard content and enables/disables the paste button accordingly."""
        clipboard_text = QGuiApplication.clipboard().text()
        # Enable only if the clipboard contains a URL starting with http
        self.btn_paste.setEnabled(clipboard_text.startswith("http"))

    def paste_url(self):
        self.url_input.setText(QGuiApplication.clipboard().text()) # type: ignore

    def get_url(self):
        return self.url_input.text()

class _NiimbotPollWorker(QObject):
    """Worker off-thread : appelle np.poll_status() sans bloquer l'UI."""
    finished = pyqtSignal()

    def __init__(self, np: "NiimbotBLE"):
        super().__init__()
        self._np = np

    @pyqtSlot()
    def run(self) -> None:
        try:
            self._np.poll_status()
        except Exception as e:
            _logd.warning(f"_NiimbotPollWorker: {e}")
        finally:
            self.finished.emit()


class NiimbotWorker(QObject):
    # Signals for the UI to listen to
    print_finished = pyqtSignal()
    print_error = pyqtSignal(str)
    copy_progress = pyqtSignal(int, int)  # done, total — for multi-copy runs

    def __init__(self, printer_instance:NiimbotBLE, label_image:Image, label_type:Niimprint_PaperType, copies:int=1):
        super().__init__()
        self.printer = printer_instance
        self.image = label_image
        self.type = label_type
        self.copies = max(1, int(copies))

    def run(self):
        try:
            for i in range(self.copies):
                self.copy_progress.emit(i + 1, self.copies)
                if not self.printer.print_image(self.image, 3, self.type):
                    self._on_error("error printing")
                    return
            self._on_success()
        except Exception as e:
            self.print_error.emit(str(e))
            return

    def _on_success(self):
        self.print_finished.emit()

    def _on_error(self,message):
        self.print_error.emit(message)

class _RoasterLoadWorker(QObject):
    finished = pyqtSignal(object)   # emits the populated RoasterManager
    error    = pyqtSignal(str)

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    @pyqtSlot()
    def run(self) -> None:
        try:
            mgr = RoasterManager()
            if self._path.exists():
                mgr.load_json(self._path)
            self.finished.emit(mgr)
        except Exception as e:
            self.error.emit(str(e))

class _AlogLoadWorker(QObject):
    finished = pyqtSignal(object, object, object)  # profiledata, deltaet, deltabt
    error = pyqtSignal(str)

    def __init__(self, parent:BeancaveDlg, filepath: Path, aw: ApplicationWindow):
        super().__init__()
        self._path = filepath
        self.aw = aw
        self.parent = parent

    @pyqtSlot()
    def run(self) -> None:
        try:
            data = self.parent.get_alog_data(self._path)
            if data is not None:
                # evaldeltas is numpy — safe off-thread
                deltaet = self._eval(data, "temp1")
                deltabt = self._eval(data, "temp2")
                self.finished.emit(data, deltaet, deltabt)
            else:
                # Toujours émettre finished ou error — sinon la queue multi se bloque
                _log.warning(f"_AlogLoadWorker: get_alog_data returned None for {self._path}")
                self.error.emit(f"Could not load data from {self._path.name}")
        except Exception as e:
            _log.error(f"_AlogLoadWorker exception: {e}", exc_info=True)
            self.error.emit(str(e))

    def _eval(self, data: dict, deltaname:str):
            tx = numpy.array(data.get("timex", []))
            timeindex = data.get("timeindex", [])
            rd = timeindex[RoastingPhase.CHARGE] if timeindex and timeindex[RoastingPhase.CHARGE] != -1 else 0
            drop = timeindex[RoastingPhase.DROP] if timeindex  else 0
            unit = data.get("temp_unit", "C")
            temp = [convertTemp(t,unit,self.aw.qmc.mode) for t in data.get(deltaname, [])]
                                
            cf = self.aw.qmc.curvefilter #*2 # we smooth twice as heavy for PID/RoR calculation as for normal curve smoothing
            t1 = smooth_list(data.get("timex", []),(fill_gaps(temp) if self.aw.qmc.interpolateDropsflag else temp),window_len=cf,decay_smoothing=not self.aw.qmc.optimalSmoothing)
            if len(t1)>10 and len(tx) > 10:
                # we start RoR computation 10 readings after CHARGE to avoid this initial peak
                RoR_start = min(rd+10,len(tx)-1)
                _, deltas = self.aw.qmc.recomputeDeltas(tx,RoR_start,drop,None,t1,optimalSmoothing=self.aw.qmc.optimalSmoothing)
                return deltas
            return None

class _AlogListWorker(QObject):
    """Scans the alog directory and formats display names off the main thread using cached metadata."""
    finished = pyqtSignal(list)   # list of (raw_filename, display_name)
    error    = pyqtSignal(str)

    def __init__(self, directory: Path, cache_records: dict[str, AlogMetadata]):
        super().__init__()
        self._directory = directory
        self._cache_records = cache_records

    @pyqtSlot()
    def run(self) -> None:
        import re as _re
        from datetime import datetime as _dt

        # Generic Artisan default titles that carry no bean information
        _GENERIC_TITLES = {'roaster scope', 'artisan', ''}

        try:
            fnames = [f.name for f in self._directory.glob('*.alog')
                      if f.suffix.lower() == '.alog']

            # Build intermediate tuples: (fname, sort_epoch, display_name, base_name)
            triples: list[tuple[str, int, str, str]] = []
            for f in fnames:
                f_path_str = str(self._directory / f)
                meta = self._cache_records.get(f_path_str)
                display, base_name, sort_epoch = _AlogListWorker._build_display(
                    fname_stem=f[:-5],
                    meta_title=meta.title if meta else "",
                    batch_prefix=meta.batch_prefix if meta else "",
                    batch_nr=meta.batch_nr if meta else 0,
                    roastepoch=meta.roastepoch if meta else 0,
                    re=_re,
                    dt=_dt,
                    generic_titles=_GENERIC_TITLES,
                )
                triples.append((f, sort_epoch, display, base_name))

            # ## TILAU ## Sort: bean name ASC, then roast date DESC within a bean.
            # This is the intended ordering and it now actually holds: the date
            # half used to be dead whenever the metadata cache had no roastepoch
            # (every file tied at 0, so the list fell back to raw directory order
            # and the roasts of one bean looked shuffled). sort_epoch resolves a
            # date from the filename too, so the tiebreak always has real values.
            triples.sort(key=lambda t: (t[3].lower(), -(t[1])))

            # Deduplicate display names: two roasts of one bean sharing the same
            # displayed date get the original filename stem appended, in parens —
            # the brackets are taken by the date. An explicit "already suffixed"
            # set replaces the old endswith(']') guard, which silently stopped
            # working once every line ended with "[date]" (the first of a pair
            # would then never get disambiguated).
            seen: dict[str, int] = {}        # display_name → first occurrence index
            disambiguated: set[int] = set()  # indices already given a suffix
            pairs: list[tuple[str, str]] = []
            for fname, _epoch, display, _base in triples:
                if display in seen:
                    first_idx = seen[display]
                    if first_idx not in disambiguated:
                        first_fname = pairs[first_idx][0]
                        pairs[first_idx] = (first_fname,
                                            f"{pairs[first_idx][1]} ({first_fname[:-5]})")
                        disambiguated.add(first_idx)
                    new_display = f"{display} ({fname[:-5]})"
                else:
                    seen[display] = len(pairs)
                    new_display = display
                pairs.append((fname, new_display))

            self.finished.emit(pairs)
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _build_display(
        fname_stem: str,
        meta_title: str,
        batch_prefix: str,
        batch_nr: int,
        roastepoch: int,
        re,
        dt,
        generic_titles: set,
    ) -> tuple[str, str, int]:
        """
        Build a human-readable display name for a roast file.

        Returns (display_name, base_name, sort_epoch) where sort_epoch is the
        roast date used to order the list (0 when no date could be resolved).

        Priority:
          date_str  : roastepoch → multi-pattern filename extraction → ""
          base_name : meta.title (if not generic) → cleaned filename stem → ""
          batch_tag : "#N · " prefix when batch_nr > 0  (leading '#' stripped from prefix)
        Result: "{batch_tag}{base_name} ({date_str})"
        """
        # 1. Date from roastepoch (most reliable — immune to filename conventions)
        date_str = ""
        if roastepoch > 0:
            try:
                date_str = dt.fromtimestamp(roastepoch).strftime('%Y/%m/%d %H:%M')
            except (OSError, OverflowError, ValueError):
                pass

        # 2. Fallback: extract date from filename stem
        if not date_str:
            date_str = _AlogListWorker._extract_date_from_stem(fname_stem, re, dt)

        # 2b. ## TILAU ## Sort epoch — the cache has no roastepoch for older /
        # not-yet-scanned files, so recover one from the date read off the
        # filename; without it every such file ties at 0 and the list falls back
        # to raw directory order (which looks random to the user).
        sort_epoch = roastepoch if roastepoch > 0 else 0
        if sort_epoch <= 0 and date_str:
            for _fmt in ('%Y/%m/%d %H:%M', '%Y/%m/%d'):
                try:
                    sort_epoch = int(dt.strptime(date_str, _fmt).timestamp())
                    break
                except (ValueError, OSError, OverflowError):
                    continue

        # 3. Base name: prefer meta.title when it carries real information
        clean_title = meta_title.strip()
        if clean_title.lower() in generic_titles or not clean_title:
            base_name = _AlogListWorker._clean_stem(fname_stem, re)
        else:
            base_name = clean_title

        # 4. Batch tag — strip any leading '#' from prefix to avoid "##N"
        bp_clean = batch_prefix.lstrip('#') if batch_prefix else ""
        batch_tag = f"#{bp_clean}{batch_nr} · " if batch_nr > 0 else ""

        # 5. Assemble: "<bean name incl. crop year> [<date>]" — the name (the
        #    primary sort key) leads the line, the date sits in brackets.
        if date_str:
            if base_name:
                display = f"{batch_tag}{base_name} [{date_str}]"
            elif batch_tag:
                display = f"{batch_tag.rstrip(' · ')} [{date_str}]"
            else:
                display = date_str
        else:
            display = f"{batch_tag}{base_name}" if (batch_tag or base_name) else fname_stem

        return display, (base_name if base_name else fname_stem), sort_epoch

    @staticmethod
    def _extract_date_from_stem(stem: str, re, dt) -> str:
        """
        Try multiple filename date patterns. Returns 'YYYY/MM/DD HH:MM' or 'YYYY/MM/DD' or "".

        Patterns (non-anchored — date may appear anywhere in the stem):
          A: YY-MM-DD_HHMM  (optionally preceded by #N_)  e.g. #1_26-02-24_1858
          B: YYYYMMDD_HHMM                                 e.g. Colombia_20260224_1858
          C: YYYY_MM_DD_HHMM                               e.g. Colombia_2026_02_24_1858
          D: YY-MM-DD  (date only, no time)                e.g. Colombia_26-02-24
        """
        s = stem.replace('\xa0', ' ').strip()

        # A: optional leading #N_, then YY-MM-DD_HHMM (tolerant of trailing suffix like 'b')
        m = re.search(r'(?:^#\d*[_\s])?(\d{2})[-_](\d{2})[-_](\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # B: YYYYMMDD_HHMM
        m = re.search(r'(\d{4})(\d{2})(\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%Y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # C: YYYY_MM_DD_HHMM
        m = re.search(r'(\d{4})[_\-](\d{2})[_\-](\d{2})[_\s-](\d{4})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}", '%Y%m%d%H%M'
                ).strftime('%Y/%m/%d %H:%M')
            except ValueError:
                pass

        # D: YY-MM-DD anywhere (no time)
        m = re.search(r'(\d{2})[-_](\d{2})[-_](\d{2})', s)
        if m:
            try:
                return dt.strptime(
                    f"{m.group(1)}{m.group(2)}{m.group(3)}", '%y%m%d'
                ).strftime('%Y/%m/%d')
            except ValueError:
                pass

        return ""

    @staticmethod
    def _clean_stem(stem: str, re) -> str:
        """Strip date/time noise and batch prefix from a filename stem."""
        s = stem.replace('\xa0', ' ').strip()
        # Remove leading batch marker: #N_ or #_ (N can be empty)
        s = re.sub(r'^#\d*[_\-\s]+', '', s)

        # ## TILAU ## Strip Artisan's trailing date stamp as ONE anchored unit.
        # The loose "date-like block" rules used before mangled names that end
        # with a crop year: in "Yellow Caturra - … - 2024_26-05-13_1847" the
        # YYYY-MM-DD rule matched "2024_26-05" (crop year + YY + MM) and left an
        # orphan "-13" welded to the name → "… Dry Process 13". That stray day
        # number also made every file a unique name, so roasts of the same bean
        # could never be recognised as the same bean.
        date_suffix = (
            r'[\s_\-]+'
            r'(?:\d{2}[-_]\d{2}[-_]\d{2}'      # YY-MM-DD
            r'|\d{4}[-_]\d{2}[-_]\d{2}'        # YYYY-MM-DD
            r'|\d{8})'                          # YYYYMMDD
            r'(?:[\s_\-]+\d{4}\w*)?$'          # optional HHMM (+ suffix like 'b')
        )
        cleaned = re.sub(date_suffix, '', s)
        if cleaned != s:
            s = cleaned
        else:
            # Unknown convention: fall back to the loose rules (date may sit
            # anywhere in the stem). YY-MM-DD first — it is the narrowest match.
            s = re.sub(r'\d{2}[\-_]\d{2}[\-_]\d{2}', '', s)      # YY-MM-DD
            s = re.sub(r'\d{4}[\s_\-]\d{2}[\s_\-]\d{2}', '', s)  # YYYY-MM-DD
            s = re.sub(r'\d{8}', '', s)                            # YYYYMMDD
            # Trailing HHMM block (4 digits, optional non-digit suffix like 'b')
            s = re.sub(r'[\s_\-]\d{4}\w*$', '', s)
        # Normalise separators and trim
        s = re.sub(r'[\s\-_\/]+', ' ', s).strip()
        s = re.sub(r'[.\-\s_]+$', '', s).strip()
        return s  # may be "" — caller handles fallback
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

"""Constants, inline glyphs and small helpers shared across the BeanCave modules.

Nothing here knows about the dialog: it is read by the widgets, the workers and
every mixin, which is why it sits below all of them."""

import logging
import json
import uuid
import sys
import os
import ctypes
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtGui import QIcon  # pylint: disable=unused-import
import re # For sorting alog files
from pathlib import Path

#import matplotlib.pyplot as plt




from PyQt6.QtCore import (Qt, QByteArray, QSize) # @UnusedImport @Reimport  @UnresolvedImport QT_TRANSLATE_NOOP declares strings the extractor must see when translate() is fed a variable
from PyQt6.QtGui import ( QPixmap, QPainter) # @UnusedImport @Reimport  @UnresolvedImport
from PyQt6.QtSvg import QSvgRenderer  # icônes SVG inline pour ZoomToggleButton

# Import QWebEngineView for both PyQt6 and PyQt5

from tilauscope.tilauscope_types import (BeanCaveContainer, THEME, _IS_WINDOWS)

#: The ``tilauscope`` package directory. The JSON and font resources ship beside
#: it, one level ABOVE this package, so a module under ``cave/`` must never
#: resolve them from its own ``__file__`` — it sits one directory too deep.
PKG_DIR: Final[Path] = Path(__file__).resolve().parent.parent

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
_FS_TITLE:  Final[int] = 13   # titre du graphe
_FS_AXIS:   Final[int] = 12   # labels d'axe (x / y)
_FS_TICK:   Final[int] = 11   # graduations
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
            'Humidity', 'Water activity', 'Altitude', 'Specy', 'Variety',
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
_SVG_CONSISTENCY = f"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M1 10.5 C5 7.5 9 4.5 15 1.5 L15 4.5 C9 7.5 5 10.5 1 13.5 Z"
    fill="{THEME['TEXT']}" fill-opacity="0.30"/>
  <path d="M1 12 C5 9 9 6 15 3" stroke="{THEME['TEXT']}" stroke-width="1.4"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>""".encode()

# Glyphe « Aligné » (time-warp) : deux bornes verticales + double-flèche
# horizontale = étirer/compresser le temps pour aligner les jalons.
_SVG_ALIGN = f"""<svg width="16" height="16" viewBox="0 0 16 16" fill="none"
  xmlns="http://www.w3.org/2000/svg">
  <path d="M2.5 2V14M13.5 2V14" stroke="{THEME['TEXT']}" stroke-width="1.5"
    stroke-linecap="round"/>
  <path d="M5 8H11" stroke="{THEME['TEXT']}" stroke-width="1.3" stroke-linecap="round"/>
  <path d="M5 8L7 6M5 8L7 10" stroke="{THEME['TEXT']}" stroke-width="1.3"
    stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M11 8L9 6M11 8L9 10" stroke="{THEME['TEXT']}" stroke-width="1.3"
    stroke-linecap="round" stroke-linejoin="round"/>
</svg>""".encode()


def _safe_filename(text: str, fallback: str) -> str:
    """Build a filesystem-safe base name: no separator runs, no leading/trailing dash."""
    name = re.sub(r'[^\w]+', '-', text or '')
    name = re.sub(r'-{2,}', '-', name).strip('-')
    return name or fallback


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


# Flask icon for the density-measure button (Catppuccin ACCENT)
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

def _atomic_write_text(path: Path, content: str, encoding: str) -> None:
    """Durably replace *path* without ever exposing a partially written file."""
    tmp_path = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with tmp_path.open('x', encoding=encoding, newline='') as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, path)

        # Persist the directory entry too when the platform supports fsync on
        # directories. The replace has already succeeded if this best-effort
        # durability step is unavailable (notably on Windows).
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            _logd.warning('Unable to remove temporary BeanCave file: %s', tmp_path)


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

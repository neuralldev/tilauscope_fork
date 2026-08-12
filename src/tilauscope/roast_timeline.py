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

import re
import threading
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Final
import logging

from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QWheelEvent, QLinearGradient,
                         QPainterPath, QRegion)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTextEdit, QProgressBar,
    QPushButton, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsProxyWidget,
    QDialog, QApplication, QWidget, QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSettings,
    QRunnable, QThreadPool, QObject, pyqtSignal,
)

from tilauscope.tilauscope_types import THEME
from tilauscope.alogmanager import AlogMetadata
from tilauscope.brew_advisor import degassing_band, rest_window, RestStatus, BrewFamily, to_agtron
from tilauscope.theme_qss import apply_tilau_theme, base_qss

_log: Final[logging.Logger] = logging.getLogger(__name__)

# ── constants ──────────────────────────────────────────────────────────────────
DAY_W: Final[int] = 44          # pixels per day
ROW_H: Final[int] = 54          # height of each roast row
ROW_GAP: Final[int] = 8         # vertical gap between rows
HEADER_H: Final[int] = 36       # date axis height
LABEL_H: Final[int] = 18        # roast name label height above bar
BAR_H: Final[int] = 28          # bar height
SCENE_W_DAYS: Final[int] = 730  # total scene width in days (±1 year each side)
ORIGIN_DAY: Final[int] = 365    # index of "today" in the scene (day 0 = today-365)


# ── degassing window ───────────────────────────────────────────────────────────
def _window_geom(agtron: float, family=None) -> tuple[int, int, int, int, str]:
    """Return (ready, peak, peak_end, tail_end, theme_color_key) day-offsets for a
    roast's degassing window, from the shared brew_advisor source of truth. The
    optional brew family applies the pressure rest shift — the timeline passes the
    method chosen in its header selector so the bars match the Brew Advisor."""
    w = rest_window(agtron, 0, family)
    return w.ready_day, w.peak_day, w.peak_end_day, w.tail_end_day, degassing_band(agtron).key


def _get_agtron(filepath: Path) -> float:
    """Fast Agtron extraction — reads only the first 2 KB. Returns the reading on
    the Agtron scale, or 0.0 (unknown) for meters with no valid Agtron mapping
    (e.g. Tonino) — same colour-family policy as brew_advisor.to_agtron."""
    try:
        chunk = filepath.read_text(encoding='utf-8', errors='replace')[:2000]
        scale = re.search(r"['\"]color_system['\"]\s*:\s*['\"]([^'\"]+)['\"]", chunk)
        system = scale.group(1) if scale else ""
        values = re.findall(r"['\"](?:ground|whole)_color['\"]\s*:\s*([\d.]+)", chunk)
        raw = max(float(v) for v in values) if values else 0.0
        return to_agtron(raw, system)
    except Exception:
        return 0.0


def _get_roast_epoch(filepath: Path) -> int:
    """Fast roastepoch extraction — reads only the first 2 KB. 0 if not found."""
    try:
        chunk = filepath.read_text(encoding='utf-8', errors='replace')[:2000]
        m = re.search(r"['\"]roastepoch['\"]\s*:\s*(\d+)", chunk)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


# ── background scan worker ─────────────────────────────────────────────────────
class _ScanSignals(QObject):
    results_ready = pyqtSignal(list)
    error         = pyqtSignal(str)


class _TimelineScanWorker(QRunnable):
    """Reads Agtron from each .alog file off the main thread. Uses cache for
    metadata but falls back to a direct directory scan if the cache is stale."""

    def __init__(
        self,
        alog_directory: str,
        cache: dict[str, AlogMetadata],
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._directory  = Path(alog_directory)
        self._cache      = cache          # filepath_str → AlogMetadata
        self._stop       = stop_event
        self.signals     = _ScanSignals()

    def run(self) -> None:
        try:
            results = self._scan()
            if not self._stop.is_set():
                self.signals.results_ready.emit(results)
        except Exception as exc:
            _log.error("TimelineScanWorker error: %s", exc)
            if not self._stop.is_set():
                self.signals.error.emit(str(exc))

    def _scan(self) -> list[dict]:
        rows: list[dict] = []

        # Ground truth: all .alog files on disk — not limited to cache snapshot
        try:
            all_files = sorted(
                self._directory.glob("*.alog"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            all_files = []

        print("TimelineScanWorker: directory=%s, found %d .alog files", self._directory, len(all_files))

        for fpath in all_files:
            if self._stop.is_set():
                print("TimelineScanWorker: stop requested after %d rows", len(rows))
                break
            try:
                fpath_str  = str(fpath)
                meta       = self._cache.get(fpath_str)
                mtime      = fpath.stat().st_mtime
                # Roast date must come from the .alog roastepoch, NOT the file mtime
                # (mtime shifts on copy/sync and clusters all bars near today).
                epoch      = meta.roastepoch if (meta is not None and meta.roastepoch > 0) else _get_roast_epoch(fpath)
                roast_date = datetime.fromtimestamp(epoch if epoch > 0 else mtime).date()
                agtron     = _get_agtron(fpath)

                if meta is not None:
                    title      = meta.title or meta.filename or fpath.name
                    bean_field = meta.bean_field or ""
                else:
                    # Cache miss — use filename as title, no bean info
                    title      = fpath.stem
                    bean_field = ""

                # Brewable = colour reading (valid Agtron) AND a linked green bean
                # (uuid in the beans field). Non-brewable roasts are drawn dimmed.
                brewable = agtron > 0 and ("uuid" in bean_field.lower())

                # Collapse any run of backslashes-before-n (over-escaped beans field)
                # and real newlines into a single <br>.
                beans = re.sub(r"\\+n", "<br>", bean_field).replace("\n", "<br>")
                rows.append({
                    "name":      title,
                    "filename":  fpath.name,
                    "filepath":  fpath_str,
                    "date":      roast_date,
                    "agtron":    agtron,
                    "brewable":  brewable,
                    "beans":     beans,
                })
                print("TimelineScanWorker: added %s date=%s agtron=%.1f", fpath.name, roast_date, agtron)
            except Exception as exc:
                print("[WARN]", "TimelineScanWorker: skipped %s — %s", fpath.name, exc)
                continue

        print("TimelineScanWorker: scan complete, %d rows", len(rows))
        return rows


# ── tooltip widget (QGraphicsProxyWidget) ─────────────────────────────────────
class _TooltipWidget(QFrame):
    """
    Native Qt tooltip card rendered via QGraphicsProxyWidget.
    No HTML limitations — full control over colors, spacing, fonts.
    """

    # ── color constants (Catppuccin Mocha) ────────────────────────────────────
    _C_TEXT   = THEME['TEXT']   # primary — title, values
    _C_LABEL  = THEME['SUBTEXT']   # secondary — data row labels
    _C_META_K = THEME['OVERLAY2']   # tertiary — meta keys
    _C_BG     = THEME['BG']
    _C_BORDER = THEME['SURFACE1']
    _C_DIV    = THEME['BORDER']

    # status colors
    _C_IN_WIN  = THEME['SUCCESS']   # in window
    _C_NEAR    = THEME['YELLOW']   # near peak · drink soon
    _C_PAST    = THEME['WARNING']   # past window
    _C_NOT_YET = THEME['ACCENT']   # not ready yet
    _C_ACCENT  = THEME['ACCENT']

    # Emitted when the "brew this coffee" CTA is clicked; carries the .alog path.
    prepare_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filepath = ""
        self.setObjectName("TooltipCard")
        self.setStyleSheet(f"""
            QFrame#TooltipCard {{
                background: {self._C_BG};
                border: 1px solid {self._C_BORDER};
                border-radius: 10px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._build_layout()

    def resizeEvent(self, e) -> None:
        # Clip to the rounded shape (corners transparent, body opaque); plain
        # translucency would make the whole card see-through.
        super().resizeEvent(e)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 10.0, 10.0)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _lbl(self, text: str = "", color: str = _C_TEXT,
             size: int = 11, bold: bool = False, italic: bool = False) -> QLabel:
        w = QLabel(text)
        w.setStyleSheet(
            f"color:{color}; font-size:{size}px;"
            + ("font-weight:500;" if bold else "")
            + ("font-style:italic;" if italic else "")
            + "background:transparent; border:none; padding:0;"
        )
        return w

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{self._C_DIV}; border:none;")
        return line

    def _build_layout(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header ────────────────────────────────────────────────────────────
        self._header = QFrame()
        self._header.setObjectName("TtHeader")
        self._header_lbl = self._lbl("", self._C_TEXT, 12, bold=True)
        self._header_lbl.setWordWrap(True)
        hdr_layout = QVBoxLayout(self._header)
        hdr_layout.setContentsMargins(12, 8, 12, 7)
        hdr_layout.addWidget(self._header_lbl)
        outer.addWidget(self._header)

        # ── data rows ─────────────────────────────────────────────────────────
        body = QWidget()
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(12, 7, 12, 0)
        self._body_layout.setSpacing(1)

        self._row_roasted = self._make_data_row("Roasted")
        self._row_agtron  = self._make_data_row("Agtron")
        self._row_peak    = self._make_data_row("Best day")
        self._row_window  = self._make_data_row("Window")
        for row_w in (self._row_roasted, self._row_agtron, self._row_peak, self._row_window):
            self._body_layout.addWidget(row_w)

        # ── divider + status ──────────────────────────────────────────────────
        self._body_layout.addSpacing(4)
        self._body_layout.addWidget(self._divider())
        self._body_layout.addSpacing(3)

        status_row = QWidget()
        self._status_layout = QHBoxLayout(status_row)
        self._status_layout.setContentsMargins(0, 0, 0, 0)
        self._status_layout.setSpacing(6)
        self._dot = QFrame()
        self._dot.setFixedSize(7, 7)
        self._dot.setStyleSheet("border-radius:3px; background:#888;")
        self._status_lbl = self._lbl("", bold=True)
        self._status_layout.addWidget(self._dot)
        self._status_layout.addWidget(self._status_lbl)
        self._status_layout.addStretch()
        self._body_layout.addWidget(status_row)

        # ── divider + meta ────────────────────────────────────────────────────
        self._div_meta   = self._divider()
        self._meta_widget = QWidget()
        self._meta_layout = QVBoxLayout(self._meta_widget)
        self._meta_layout.setContentsMargins(0, 3, 0, 0)
        self._meta_layout.setSpacing(0)

        self._body_layout.addSpacing(3)
        self._body_layout.addWidget(self._div_meta)
        self._body_layout.addWidget(self._meta_widget)

        # ── brew hand-off CTA ─────────────────────────────────────────────────
        self._body_layout.addSpacing(8)
        self._cta = QPushButton("")
        self._cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cta.clicked.connect(lambda: self.prepare_requested.emit(self._filepath))
        self._body_layout.addWidget(self._cta)
        self._body_layout.addSpacing(7)

        outer.addWidget(body)

    def _make_data_row(self, label_text: str) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        lbl = self._lbl(label_text, self._C_LABEL, 11)
        val = self._lbl("", self._C_TEXT, 11, bold=True)
        val.setObjectName(f"val_{label_text.lower()}")
        hl.addWidget(lbl)
        hl.addStretch()
        hl.addWidget(val)
        row._val_lbl = val   # type: ignore[attr-defined]
        return row

    def _set_row_value(self, row: QWidget, text: str, color: str | None = None):
        lbl = row._val_lbl   # type: ignore[attr-defined]
        lbl.setText(text)
        if color:
            lbl.setStyleSheet(
                f"color:{color}; font-size:11px; font-weight:500;"
                "background:transparent; border:none; padding:0;"
            )

    def _clear_meta(self):
        while self._meta_layout.count():
            item = self._meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_meta_pair(self, key: str, value: str):
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        k = self._lbl(f"{key}: ", self._C_META_K, 10, italic=True)
        v = self._lbl(value,       self._C_TEXT,   10, bold=True, italic=True)
        hl.addWidget(k)
        hl.addWidget(v)
        hl.addStretch()
        self._meta_layout.addWidget(row)

    def populate(self, data: dict, accent_color: str) -> None:
        """Fill all fields from a rect data dict."""
        from datetime import date as _date

        # Header
        self._header.setStyleSheet(f"""
            QFrame {{
                background: {accent_color}20;
                border-bottom: 2px solid {accent_color};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
            }}
        """)
        self._header_lbl.setText(data["name"])

        # Data rows
        self._set_row_value(self._row_roasted, data["date"].strftime("%d %b %Y"))
        agtron_txt = f"{data['agtron']:.1f}" if data['agtron'] > 0 else "N/A"
        self._set_row_value(self._row_agtron,  agtron_txt, accent_color)
        self._set_row_value(self._row_peak,    f"d+{data['win_peak']}", accent_color)
        self._set_row_value(self._row_window,  f"d+{data['win_s']} → d+{data['win_e']}")

        # Status — 4 states, from the shared rest window carried in the rect data.
        ws, wp, we, wt = data["win_s"], data["win_peak"], data["win_e"], data["tail_end"]
        today_off = (_date.today() - data["date"]).days
        if today_off < ws:
            txt, col = "Not ready yet", self._C_NOT_YET
        elif today_off <= we:
            days_left = we - today_off
            txt, col  = f"In window · best d+{wp} · {days_left}d left", self._C_IN_WIN
        elif today_off <= wt:
            txt, col  = "Near peak · drink soon", self._C_NEAR
        else:
            txt, col  = "Past window", self._C_PAST
        self._dot.setStyleSheet(f"border-radius:3px; background:{col}; border:none;")
        self._status_lbl.setText(txt)
        self._status_lbl.setStyleSheet(
            f"color:{col}; font-size:11px; font-weight:500;"
            "background:transparent; border:none; padding:0;"
        )

        # Brew hand-off CTA — enabled only when the advisor has what it needs.
        self._filepath = data.get("filepath", "")
        brewable = bool(data.get("brewable", False))
        if brewable:
            self._cta.setText(QApplication.translate("tilauscope_roast_review", "☕ Brew this coffee"))
            self._cta.setEnabled(True)
            self._cta.setStyleSheet(
                f"QPushButton {{ background:{self._C_ACCENT}; color:{self._C_BG};"
                f" border:none; border-radius:7px; padding:7px 10px; font-weight:700; font-size:13px; }}"
                f" QPushButton:hover {{ background:{THEME['LAVENDER']}; }}")
        else:
            self._cta.setText(QApplication.translate("tilauscope_roast_review", "Colour / bean not linked"))
            self._cta.setEnabled(False)
            self._cta.setStyleSheet(
                f"QPushButton {{ background:{self._C_DIV}; color:{self._C_META_K};"
                f" border:none; border-radius:7px; padding:7px 10px; font-size:13px; }}")

        # Meta
        self._clear_meta()
        beans_raw = data.get("beans", "").replace("<br>", "\n").replace("\\n", "\n")
        meta_map: dict[str, str] = {}
        for line in beans_raw.split("\n"):
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                meta_map[k.strip()] = v.strip()
        for key in ("Origin", "Process", "SCA", "Altitude", "Density", "Water activity", "Flavour notes"):
            if key in meta_map and meta_map[key]:
                # Defensive: strip any trailing backslash / pipe / box-drawing
                # noise from over-escaped beans so the compact card stays clean.
                val = re.sub(r"[\s|｜│\\]+$", "", meta_map[key])[:50]
                if val:
                    self._add_meta_pair(key, val)
        has_meta = self._meta_layout.count() > 0
        self._div_meta.setVisible(has_meta)
        self._meta_widget.setVisible(has_meta)

        self.adjustSize()


# ── infinite scrollable timeline view ─────────────────────────────────────────
class _InfiniteTimelineView(QGraphicsView):
    """
    QGraphicsView with:
      - horizontal scroll only (wheel + drag)
      - click on a date label → centre that day
    """
    date_clicked = pyqtSignal(date)   # emitted when user clicks a date label

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setStyleSheet(
            f"background: {THEME['SURFACE']}; border-radius: 15px;"
            f" border: 1px solid {THEME['BORDER']};"
        )
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._drag_start: QPoint | None = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Trackpad swipes map to their axis; a plain vertical-only wheel falls
        # back to horizontal scroll (the timeline reads left-to-right).
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        if dx:
            hbar.setValue(hbar.value() - dx)
        if dy:
            if vbar.maximum() > vbar.minimum():
                vbar.setValue(vbar.value() - dy)
            else:
                hbar.setValue(hbar.value() - dy)
        event.accept()

    def scroll_to_day(self, day_index: int) -> None:
        """Centre the view on *day_index* (0 = today-ORIGIN_DAY)."""
        x_centre = day_index * DAY_W
        vp_half  = self.viewport().width() // 2
        self.horizontalScrollBar().setValue(max(0, x_centre - vp_half))


# ── main dialog ───────────────────────────────────────────────────────────────
class RoastReadyDialog(QDialog):
    """
    Brew Planning timeline dialog.
    Signature unchanged from caller in beancave.py:
        RoastReadyDialog(str(alog_directory), metadata_cache.records, parent)
    """

    # Emitted when the user clicks "brew this coffee" on a roast bar; carries the
    # .alog filepath so BeanCave can select it and open the Brew Advisor.
    brew_requested = pyqtSignal(str)

    def __init__(
        self,
        alog_directory: str,          # kept for API compat, not used (mtime is the truth)
        alog_files: dict[str, AlogMetadata],
        parent: QWidget | None = None,
        aw: QWidget | None = None,    # ApplicationWindow — centering anchor
    ) -> None:
        super().__init__(None)  # No parent — avoids embedding inside BeancaveDlg on macOS
        # ground=False: the grounded base would paint the rectangle opaque and
        # square off the rounded card this window draws inside it.
        apply_tilau_theme(self, ground=False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Unparented → Qt treats this as a "primary" top-level window for
        # lastWindowClosed accounting; disable it so closing this sub-view
        # never fires fileQuit() while BeanCave stays open.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1200, 560)

        self._alog_dir   = alog_directory
        self._cache      = alog_files
        self._aw         = aw
        self._rows: list[dict] = []
        self._stop_event = threading.Event()
        self._old_pos    = QPoint()
        # Targeted brew method (Filter/percolation vs Espresso/pressure) — shifts
        # every window by the pressure rest and persists across sessions.
        self._family     = self._read_family()
        self._hover_key: str | None = None   # filepath of the currently shown tooltip

        # tooltip — native QWidget via QGraphicsProxyWidget (added to scene after build)
        self._tooltip_widget = _TooltipWidget()
        self._tooltip_widget.prepare_requested.connect(self._on_prepare)
        self._tooltip_proxy: QGraphicsProxyWidget | None = None

        self._setup_ui()
        self._start_scan()
        self._center_on_screen()

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def request_stop(self) -> None:
        self._stop_event.set()
        self.close()

    def closeEvent(self, event) -> None:
        self._stop_event.set()
        super().closeEvent(event)

    # ── targeted brew method (persisted) ────────────────────────────────────────
    _FAMILY_KEY = "tilauscope/brew/target_family"

    def _read_family(self) -> BrewFamily:
        try:
            v = QSettings().value(self._FAMILY_KEY, "", str)
        except Exception:
            v = ""
        return BrewFamily.PRESSURE if v == BrewFamily.PRESSURE.value else BrewFamily.PERCOLATION

    def _save_family(self) -> None:
        try:
            QSettings().setValue(self._FAMILY_KEY, self._family.value)
        except Exception:
            pass

    def _set_family(self, family: BrewFamily) -> None:
        if family == self._family:
            return
        self._family = family
        self._save_family()
        self._sync_family_buttons()
        # Rebuild in place — no rescan needed — keeping the scroll position.
        val = self._view.horizontalScrollBar().value()
        self._build_scene()
        self._view.horizontalScrollBar().setValue(val)

    def _sync_family_buttons(self) -> None:
        is_es = self._family == BrewFamily.PRESSURE
        for btn, on in ((self._btn_filter, not is_es), (self._btn_espresso, is_es)):
            btn.setStyleSheet(self._seg_btn_qss(on))

    @staticmethod
    def _seg_btn_qss(on: bool) -> str:
        if on:
            return (f"QPushButton {{ background:{THEME['ACCENT']}; color:{THEME['BG']};"
                    f" border:none; border-radius:6px; padding:5px 13px; font-weight:700;"
                    f" font-size:12px; }}")
        return (f"QPushButton {{ background:transparent; color:{THEME['SUBTEXT']};"
                f" border:none; border-radius:6px; padding:5px 13px;"
                f" font-size:12px; }}")

    # ── brew hand-off ───────────────────────────────────────────────────────────
    def _on_prepare(self, filepath: str) -> None:
        """CTA clicked on a roast bar → ask BeanCave to open the Brew Advisor for
        this roast, then close the timeline so the advisor isn't hidden behind our
        stays-on-top window."""
        if not filepath:
            return
        self.brew_requested.emit(filepath)
        self.close()

    # ── UI construction ────────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        self._container = QFrame()
        self._container.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['BG']};
                border: 3px solid {THEME['BORDER']};
                border-radius: 20px;
            }}
        """)
        content = QVBoxLayout(self._container)
        content.setContentsMargins(25, 25, 25, 25)
        main_layout.addWidget(self._container)

        # ── header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel(
            QApplication.translate("tilauscope_roast_review", "Brew planning - Tilauscope").upper()
        )
        title.setStyleSheet(
            "color:white; font-size:22px; font-weight:900;"
            " "
        )
        today_btn = QPushButton(
            QApplication.translate("tilauscope_roast_review", "◎ Today")
        )
        today_btn.setFixedHeight(30)
        today_btn.clicked.connect(self._scroll_to_today)
        today_btn.setStyleSheet(f"""
            QPushButton {{
                background:{THEME['SURFACE']}; color:{THEME['ACCENT']};
                border:1px solid {THEME['ACCENT']}; border-radius:8px;
                padding:0 12px; font-size:12px;
            }}
            QPushButton:hover {{ background:{THEME['ACCENT']}; color:{THEME['BG']}; }}
        """)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background:{THEME['BORDER']}; color:{THEME['CRITICAL']};
                border-radius:16px; border:1px solid {THEME['CRITICAL']};
                font-weight:bold; font-size:14px;
            }}
            QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}
        """)
        # targeted brew method (Filter / Espresso) — shifts every window & persists
        seg_lbl = QLabel(QApplication.translate("tilauscope_roast_review", "Target"))
        seg_lbl.setProperty('variant', 'eyebrow')
        seg = QFrame()
        seg.setStyleSheet(
            f"QFrame {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:9px; }}")
        seg_l = QHBoxLayout(seg)
        seg_l.setContentsMargins(3, 3, 3, 3)
        seg_l.setSpacing(2)
        self._btn_filter = QPushButton(QApplication.translate("tilauscope_roast_review", "☕ Filter"))
        self._btn_espresso = QPushButton(QApplication.translate("tilauscope_roast_review", "⚙ Espresso"))
        for b in (self._btn_filter, self._btn_espresso):
            b.setFixedHeight(26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_filter.clicked.connect(lambda: self._set_family(BrewFamily.PERCOLATION))
        self._btn_espresso.clicked.connect(lambda: self._set_family(BrewFamily.PRESSURE))
        seg_l.addWidget(self._btn_filter)
        seg_l.addWidget(self._btn_espresso)

        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(seg_lbl)
        hdr.addSpacing(6)
        hdr.addWidget(seg)
        hdr.addSpacing(14)
        hdr.addWidget(today_btn)
        hdr.addSpacing(10)
        hdr.addWidget(close_btn)
        content.addLayout(hdr)
        self._sync_family_buttons()

        # ── legend ────────────────────────────────────────────────────────────
        legend_frame = QFrame()
        legend_frame.setStyleSheet(
            f"background:{THEME['SURFACE']}; border-radius:10px;"
            f" border:1px solid {THEME['BORDER']};"
        )
        leg_layout = QHBoxLayout(legend_frame)
        leg_layout.setContentsMargins(15, 8, 15, 8)
        for col_key, label in [
            ("DARK_ROAST",      "Agtron <45 · d+2→14"),
            ("MED_ROAST",       "Agtron 45-70 · d+3→18"),
            ("LIGHT_ROAST",     "Agtron 70-90 · d+5→25"),
            ("VERY_LIGHT_ROAST","Agtron >90 · d+7→30"),
        ]:
            swatch = QFrame()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background:{THEME.get(col_key,'#888')};"
                " border-radius:3px; border:none;"
            )
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{THEME['SUBTEXT']}; font-size:11px;"
                " border:none; background:transparent;"
            )
            leg_layout.addWidget(swatch)
            leg_layout.addWidget(lbl)
            leg_layout.addSpacing(12)
        leg_layout.addStretch()
        # Today indicator swatch
        swatch_today = QFrame()
        swatch_today.setFixedSize(14, 14)
        swatch_today.setStyleSheet(
            f"background:{THEME['TODAY']};"
            " border-radius:3px; border:none;"
        )
        lbl_today = QLabel(
            QApplication.translate("tilauscope_roast_review", "Today (dashed)")
        )
        lbl_today.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px;"
            " border:none; background:transparent;"
        )
        leg_layout.addWidget(swatch_today)
        leg_layout.addWidget(lbl_today)
        content.addWidget(legend_frame)

        # ── graphics scene + view ─────────────────────────────────────────────
        self._scene = QGraphicsScene()
        self._view  = _InfiniteTimelineView(self._scene, self._container)
        self._view.setMinimumHeight(300)
        self._view.viewport().installEventFilter(self)
        content.addWidget(self._view)

        # loading indicator (hidden once scan completes)
        self._loading_lbl = QLabel(
            QApplication.translate("tilauscope_roast_review", "⏳ Scanning roast logs…")
        )
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:13px;"
            " border:none; background:transparent;"
        )
        content.addWidget(self._loading_lbl)

    # ── scan ──────────────────────────────────────────────────────────────────
    def _start_scan(self) -> None:
        worker = _TimelineScanWorker(self._alog_dir, self._cache, self._stop_event)
        worker.signals.results_ready.connect(self._on_scan_done)
        worker.signals.error.connect(lambda msg: _log.error("Timeline scan: %s", msg))
        QThreadPool.globalInstance().start(worker)

    def _on_scan_done(self, rows: list[dict]) -> None:
        if self._stop_event.is_set():
            return
        self._rows = rows
        self._loading_lbl.hide()
        self._build_scene()
        self._scroll_to_today()

    # ── scene construction ────────────────────────────────────────────────────
    def _build_scene(self) -> None:
        # Detach the tooltip BEFORE clearing so scene.clear() doesn't destroy it;
        # reusing the polished widget avoids a tiny unstyled font on the first card.
        if self._tooltip_proxy is not None:
            self._scene.removeItem(self._tooltip_proxy)
        self._scene.clear()
        self._hover_key = None
        self._date_label_items: list[tuple[QGraphicsTextItem, date]] = []

        today = date.today()

        # Compute origin dynamically: oldest roast date minus 30-day margin
        if self._rows:
            oldest = min(r["date"] for r in self._rows)
            origin = oldest - timedelta(days=30)
        else:
            origin = today - timedelta(days=ORIGIN_DAY)

        # Extend scene to today + 60 days future
        total_days = (today - origin).days + 60
        # ORIGIN_DAY is now dynamic: index of "today" in scene
        today_day_idx = (today - origin).days

        scene_w = total_days * DAY_W

        # ── date axis + vertical grid ─────────────────────────────────────────
        for i in range(total_days + 1):
            curr = origin + timedelta(days=i)
            x    = i * DAY_W

            # vertical grid line
            pen = QPen(QColor(THEME["BORDER"]), 1)
            line = self._scene.addLine(x, HEADER_H, x, 9999, pen)
            line.setZValue(-1)

            # date label — show only on day-1 of each month, or every 7 days for nearby range
            days_from_today = (curr - today).days
            show_label = (curr.day == 1) or (abs(days_from_today) <= 60 and curr.weekday() == 0)
            if show_label or curr == today:
                label_txt = curr.strftime("%-d %b") if curr.day != 1 else curr.strftime("1 %b '%y")
                txt = self._scene.addText(label_txt, QFont("JetBrains Mono", 8))
                txt.setDefaultTextColor(
                    QColor(THEME["TODAY"]) if curr == today else QColor(THEME["SUBTEXT"])
                )
                txt.setPos(x - 18, 4)
                txt.setData(0, curr)          # store date for click detection
                self._date_label_items.append((txt, curr))

        # ── today dashed vertical line ────────────────────────────────────────
        tx = today_day_idx * DAY_W
        t_pen = QPen(QColor(THEME["TODAY"]), 2, Qt.PenStyle.DashLine)
        t_line = self._scene.addLine(tx, 0, tx, 9999, t_pen)
        t_line.setZValue(10)

        # ── roast bars — lane packing (greedy interval) ──────────────────────
        # Assign each roast to the first lane where it doesn't overlap.
        # A lane tracks the rightmost bar_x_end placed so far.
        lane_ends: list[int] = []   # lane_idx → rightmost pixel used

        for rec in self._rows:
            roast_date: date = rec["date"]
            day_offset  = (roast_date - origin).days
            agtron      = rec["agtron"]
            brewable    = bool(rec.get("brewable", False))
            ready, peak, peak_end, tail_end, col_key = _window_geom(agtron, self._family)
            col = THEME.get(col_key, THEME['OVERLAY0'])

            opt_x  = (day_offset + ready) * DAY_W
            opt_w  = max(1, (peak_end - ready) * DAY_W)
            tail_x = (day_offset + peak_end) * DAY_W
            tail_w = max(1, (tail_end - peak_end) * DAY_W)
            bar_x     = opt_x
            bar_x_end = (day_offset + tail_end) * DAY_W   # pack against the tail end

            # Find first free lane (gap of >=4px between bars)
            lane_idx = None
            for i, end in enumerate(lane_ends):
                if bar_x >= end + 4:
                    lane_idx = i
                    break
            if lane_idx is None:
                lane_idx = len(lane_ends)
                lane_ends.append(0)
            lane_ends[lane_idx] = bar_x_end

            bar_y = HEADER_H + lane_idx * ROW_H + LABEL_H
            op = 1.0 if brewable else 0.4   # dim non-brewable roasts (no colour/bean)

            data = {
                "name":     rec["name"],
                "agtron":   agtron,
                "date":     roast_date,
                "beans":    rec["beans"],
                "filepath": rec.get("filepath", ""),
                "brewable": brewable,
                "col_key":  col_key,
                "win_s":    ready,
                "win_peak": peak,
                "win_e":    peak_end,
                "tail_end": tail_end,
            }

            # roast name label (above bar) — greyed when not brewable
            name_txt = rec["name"][:32]
            lbl = self._scene.addText(name_txt, QFont("JetBrains Mono", 8))
            lbl.setDefaultTextColor(QColor("white") if brewable else QColor(THEME["SUBTEXT"]))
            lbl.setPos(opt_x, bar_y - LABEL_H - 2)
            lbl.setOpacity(op)

            # near-peak tail (peak_end → tail_end): hatched, marks the break zone
            tail = QGraphicsRectItem(tail_x, bar_y, tail_w, BAR_H)
            tail.setBrush(QBrush(QColor(col), Qt.BrushStyle.FDiagPattern))
            tail.setPen(QPen(QColor(col), 1))
            tail.setOpacity(op)
            tail.setData(0, data)
            self._scene.addItem(tail)

            # optimal window bar (ready → peak_end): luminance gradient glowing at
            # the theoretical best-drink day, fading toward both edges
            grad = QLinearGradient(opt_x, 0.0, opt_x + opt_w, 0.0)
            grad.setCoordinateMode(QLinearGradient.CoordinateMode.LogicalMode)
            faint = QColor(col); faint.setAlpha(70)
            full  = QColor(col); full.setAlpha(255)
            mid   = QColor(col); mid.setAlpha(150)
            pf = min(0.98, max(0.02, (peak - ready) / (peak_end - ready))) if peak_end > ready else 0.5
            grad.setColorAt(0.0, faint)
            grad.setColorAt(pf, full)
            grad.setColorAt(1.0, mid)
            rect = QGraphicsRectItem(opt_x, bar_y, opt_w, BAR_H)
            rect.setBrush(QBrush(grad))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            rect.setOpacity(op)
            rect.setData(0, data)
            self._scene.addItem(rect)

            # peak marker — bright vertical line at the best-drink day
            peak_x = (day_offset + peak) * DAY_W
            peak_line = self._scene.addLine(peak_x, bar_y - 3, peak_x, bar_y + BAR_H + 3,
                                            QPen(QColor("white"), 2))
            peak_line.setZValue(6)
            peak_line.setOpacity(op)

            # roast day marker (thin dotted tick)
            tick_x = day_offset * DAY_W
            tick = self._scene.addLine(tick_x, bar_y, tick_x, bar_y + BAR_H,
                                       QPen(QColor("white"), 1, Qt.PenStyle.DotLine))
            tick.setZValue(5)
            tick.setOpacity(op)

        self._today_day_idx = today_day_idx
        actual_scene_h = HEADER_H + len(lane_ends) * ROW_H + 60
        self._scene.setSceneRect(0, 0, scene_w, actual_scene_h)

        # Tooltip proxy: create once, re-attach the preserved widget on every rebuild.
        # ensurePolished() applies the stylesheet up front, before the first paint.
        if self._tooltip_proxy is None:
            self._tooltip_widget.ensurePolished()
            self._tooltip_proxy = self._scene.addWidget(self._tooltip_widget)
            self._tooltip_proxy.setZValue(100)
        else:
            self._scene.addItem(self._tooltip_proxy)
        self._tooltip_proxy.hide()

    # ── scroll helpers ────────────────────────────────────────────────────────
    def _scroll_to_today(self) -> None:
        self._view.scroll_to_day(getattr(self, "_today_day_idx", ORIGIN_DAY))

    def _scroll_to_date(self, d: date) -> None:
        # Recompute from stored today index and today date
        today = date.today()
        today_idx = getattr(self, "_today_day_idx", ORIGIN_DAY)
        delta = (d - today).days
        self._view.scroll_to_day(today_idx + delta)

    # ── event filter (hover tooltip + date label click) ───────────────────────
    def eventFilter(self, source, event) -> bool:
        if source is self._view.viewport():
            if event.type() == event.Type.MouseMove:
                item = self._scene.itemAt(self._view.mapToScene(event.pos()), self._view.transform())

                # Over the tooltip itself → freeze panning so its CTA button is
                # clickable, and keep the card shown.
                if self._tooltip_proxy is not None and item is self._tooltip_proxy:
                    self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
                    self._view.viewport().unsetCursor()
                    return False

                self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

                if isinstance(item, QGraphicsRectItem):
                    data = item.data(0)
                    if isinstance(data, dict) and self._tooltip_proxy is not None:
                        key = data.get("filepath") or data.get("name")
                        # Only (re)place the card when moving onto a DIFFERENT roast,
                        # so it stays put while the cursor travels to the CTA.
                        if key != self._hover_key:
                            self._hover_key = key
                            col_hex = THEME.get(data.get("col_key", "MED_ROAST"), THEME['OVERLAY0'])
                            self._tooltip_widget.populate(data, col_hex)
                            cursor_scene = self._view.mapToScene(event.pos())
                            self._tooltip_proxy.setPos(cursor_scene.x() + 16, cursor_scene.y() + 16)
                            self._tooltip_proxy.show()
                        return True

                if isinstance(item, QGraphicsTextItem) and isinstance(item.data(0), date):
                    self._view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    return False

                # Empty space / markers: keep the card (sticky) so the user can reach
                # its button; it is dismissed on a new roast or when leaving the view.
                self._view.viewport().unsetCursor()

            elif event.type() == event.Type.Leave:
                if self._tooltip_proxy:
                    self._tooltip_proxy.hide()
                self._hover_key = None
                self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

            elif event.type() == event.Type.MouseButtonPress:
                item = self._scene.itemAt(self._view.mapToScene(event.pos()), self._view.transform())
                if isinstance(item, QGraphicsTextItem):
                    d_val = item.data(0)
                    if isinstance(d_val, date):
                        self._scroll_to_date(d_val)
                        return True

        return super().eventFilter(source, event)

    # ── drag to move dialog ───────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        self._old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:
        delta = event.globalPosition().toPoint() - self._old_pos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self._old_pos = event.globalPosition().toPoint()

    def _center_on_screen(self) -> None:
        # Priority: aw (Artisan main window) > parent top-level > screen
        anchor = self._aw
        if anchor is None:
            p = self.parentWidget()
            anchor = p.window() if p is not None else None

        if anchor is not None:
            # mapToGlobal is the only reliable way on macOS with native/non-native mixing
            top_left = anchor.mapToGlobal(QPoint(0, 0))
            w, h = anchor.width(), anchor.height()
            self.move(
                top_left.x() + (w - self.width())  // 2,
                top_left.y() + (h - self.height()) // 2,
            )
        else:
            geo = self.screen().availableGeometry()
            self.move(
                geo.x() + (geo.width()  - self.width())  // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )


# ── startup toast (unchanged API) ─────────────────────────────────────────────
class _BrewScanSignals(QObject):
    results_ready = pyqtSignal(list)
    error         = pyqtSignal(str)


class _BrewToastWorker(QRunnable):
    """Scans cache for roasts currently inside their degassing window."""

    def __init__(self, cache: dict[str, AlogMetadata], stop_event: threading.Event) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._cache  = cache
        self._stop   = stop_event
        self.signals = _BrewScanSignals()

    def run(self) -> None:
        try:
            results = self._scan()
            if not self._stop.is_set():
                self.signals.results_ready.emit(results)
        except Exception as exc:
            if not self._stop.is_set():
                self.signals.error.emit(str(exc))

    def _scan(self) -> list[dict]:
        today      = date.today()
        peak       = QApplication.translate("tilauscope_roast_review", "PEAK")
        drink_soon = QApplication.translate("tilauscope_roast_review", "DRINK SOON")
        age_s      = QApplication.translate("tilauscope_roast_review", "Age")
        days_s     = QApplication.translate("tilauscope_roast_review", "days")
        ready: list[dict] = []

        for meta in self._cache.values():
            if self._stop.is_set():
                break
            try:
                epoch      = meta.roastepoch if meta.roastepoch > 0 else meta.mtime
                roast_date = datetime.fromtimestamp(epoch).date()
                days_since = (today - roast_date).days
                if days_since < 0:
                    continue
                agtron = _get_agtron(Path(meta.filepath_str))
                # Method-agnostic (family=None) so the toast agrees with the Brew
                # Advisor: OPTIMAL and near-peak are "recommendations", FRESH/STALE are not.
                win = rest_window(agtron, days_since)
                if win.status == RestStatus.OPTIMAL:
                    status = peak
                elif win.status == RestStatus.NEAR_PEAK:
                    status = drink_soon
                else:
                    continue
                name_part = (meta.title or meta.filename).split('(')[0].strip()
                ready.append({
                    "html": (
                        f"<b>{name_part}</b><br>&nbsp;&nbsp;&nbsp;"
                        f"{age_s}: {days_since} {days_s} ({status})"
                    ),
                    "name":       name_part,
                    "agtron":     agtron,
                    "date":       roast_date,
                    "days_since": days_since,
                    "status":     status,
                })
            except Exception:
                continue
        return ready


class BrewReadyNotification(QDialog):
    """
    Compact startup toast listing roasts currently in their optimal window.
    """

    def __init__(
        self,
        alog_directory: str,               # compat — not used
        alog_files: dict[str, AlogMetadata],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent_widget = parent
        self._cache         = alog_files
        self.remaining_ms   = 15_000
        self._stop_event    = threading.Event()
        self._start_scan()

    def request_stop(self) -> None:
        self._stop_event.set()
        for attr in ('_tick_timer', '_auto_close_timer', '_animation'):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    obj.stop()
                except Exception:
                    pass
        self.close()

    def _start_scan(self) -> None:
        worker = _BrewToastWorker(self._cache, self._stop_event)
        worker.signals.results_ready.connect(self._on_scan_complete)
        worker.signals.error.connect(lambda m: _log.error("BrewToast: %s", m))
        QThreadPool.globalInstance().start(worker)

    def _on_scan_complete(self, results: list[dict]) -> None:
        if self._stop_event.is_set():
            return
        self.ready_items = results
        if self.ready_items:
            self._setup_ui()
            QTimer.singleShot(2000, self.show)
        else:
            self.deleteLater()

    def _setup_ui(self) -> None:
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowOpacity(1.0)
        # Overrides only what base_qss() does not already set.
        self.setStyleSheet(base_qss() + f"""
            QDialog       {{ border: 1px solid {THEME['BORDER']}; }}
            QTextEdit     {{ border: none; background: transparent; font-size: 12px; }}
            QLabel#Header {{ font-weight: bold; font-size: 13px; }}
            QPushButton#CloseBtn {{
                background: transparent; color: {THEME['SUBTEXT']};
                border: none; font-size: 18px; font-weight: bold;
            }}
            QPushButton#CloseBtn:hover {{ color: {THEME['CRITICAL']}; }}
            QProgressBar {{
                border: none; background-color: {THEME['BORDER']};
                height: 4px; text-align: center; border-radius: 2px;
            }}
            QProgressBar::chunk {{ background-color: {THEME['ACCENT']}; border-radius: 2px; }}
        """)
        self.resize(380, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 15)

        title_layout = QHBoxLayout()
        header_lbl   = QLabel(QApplication.translate("tilauscope_roast_review", "☕ Brewing Recommendations"))
        header_lbl.setObjectName("Header")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("CloseBtn")
        close_btn.setFixedSize(24, 24)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.clicked.connect(self._fade_out_and_close)
        title_layout.addWidget(header_lbl)
        title_layout.addStretch()
        title_layout.addWidget(close_btn)
        layout.addLayout(title_layout)

        self.content_area = QTextEdit()
        self.content_area.setReadOnly(True)
        self.content_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_area.installEventFilter(self)
        # #34495e here was a pre-fork light-theme slate, left behind on a card
        # that is now dark — dark blue-grey text on a dark ground.
        html = f"<ul style='margin-left:-15px; color:{THEME['TEXT']};'>"
        for item in self.ready_items:
            html += f"<li style='margin-bottom:6px;'>{item['html']}</li>"
        html += "</ul>"
        self.content_area.setHtml(html)
        layout.addWidget(self.content_area)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.remaining_ms)
        self.progress_bar.setValue(self.remaining_ms)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(100)

        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self._fade_out_and_close)
        self._auto_close_timer.start(self.remaining_ms)

    def showEvent(self, event) -> None:
        if self._parent_widget is not None:
            geo = self._parent_widget.geometry()
            self.move(geo.x() + geo.width() - self.width() - 15,
                      geo.y() + geo.height() - self.height() - 15)
        else:
            screen = self.screen().availableGeometry()
            self.move(screen.width() - self.width() - 20, 20)
        super().showEvent(event)

    def _on_tick(self) -> None:
        self.remaining_ms -= 100
        self.progress_bar.setValue(max(0, self.remaining_ms))
        if self.remaining_ms <= 0:
            self._tick_timer.stop()
            self._fade_out_and_close()

    def _fade_out_and_close(self) -> None:
        if getattr(self, '_animation', None) and \
                self._animation.state() == QPropertyAnimation.State.Running:
            return
        for attr in ('_tick_timer', '_auto_close_timer'):
            obj = getattr(self, attr, None)
            if obj:
                obj.stop()
        self._animation = QPropertyAnimation(self, b"windowOpacity")
        self._animation.setDuration(1000)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self.close)
        self._animation.start()

    def eventFilter(self, source, event) -> bool:
        if event.type() == event.Type.MouseButtonPress:
            self._stop_countdown()
        return super().eventFilter(source, event)

    def mousePressEvent(self, event) -> None:
        self._stop_countdown()
        super().mousePressEvent(event)

    def _stop_countdown(self) -> None:
        for attr in ('_tick_timer', '_auto_close_timer'):
            obj = getattr(self, attr, None)
            if obj:
                obj.stop()
        if hasattr(self, 'progress_bar'):
            self.progress_bar.hide()
        self.setWindowOpacity(1.0)
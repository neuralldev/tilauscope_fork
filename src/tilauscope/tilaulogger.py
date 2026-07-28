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

# this is the internal Artisan with TilauScope addon debugger 
# the top window displays any serial port in real time (do not use it on your roaster 
#       serial while Artisan is roasting, this is designed to monitor peripherial probes)
# the bottom window displays all the debug messages I have added to the software to develop
#       but can also be used to diagnose any issue.
# as this is text area, you can select them and copy/paste content in a text editor.
# warning: do not let the window accumulate too much information and risk a memory crash of the app


# AUTHOR
# TiLau 2025

from pathlib import Path
import re  # ## TILAU ## — regex filter compilation
import serial
import serial.tools.list_ports # Pour la détection des portsimport socketserver
import socket
import socketserver
import pickle
import struct
import threading
import logging
import time
import html  # ## TILAU ## — escape log text before HTML colourisation
import gc  # ## TILAU ## — GC stats for the observability dashboard
import psutil  # ## TILAU ## — process/system metrics (already an Artisan dependency)
from psutil._common import bytes2human  # ## TILAU ## # pyright:ignore[reportPrivateImportUsage]
from collections import deque  # ## TILAU ## — per-zone event buffer
from dataclasses import dataclass, field  # ## TILAU ## — LogEvent
from typing import Final
from datetime import datetime # Added for filename timestamping

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QApplication,
                             QPlainTextEdit, QLabel, QComboBox, QPushButton,
                             QFrame, QSizeGrip, QSizePolicy, QSplitter, QToolButton,
                             QLineEdit, QTextEdit)
from PyQt6.QtCore import pyqtSignal, QObject, QDateTime, QStandardPaths, QTimer, Qt, QSettings, QPointF
from PyQt6.QtGui import (QCursor, QTextCursor, QTextCharFormat, QColor,
                         QKeySequence, QShortcut, QPainter, QPen, QPolygonF)
from artisanlib.main import ApplicationWindow # noqa: F401 # pylint: disable=unused-import
from artisanlib.util import getDataDirectory, debugLogLevelActive, debugLogLevelToggle

from tilauscope.tilauscope_types import _IS_MACOS, _IS_WINDOWS, THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Style helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_style() -> str:
    return f"""
        QWidget {{
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
            font-family: 'JetBrains Mono';
        }}
        QLabel {{ background: transparent; border: none; }}
        QComboBox {{
            background-color: {THEME['SURFACE']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['BORDER']};
            border-radius: 6px;
            padding: 4px 10px;
            combobox-popup: 0;
            font-family: 'JetBrains Mono';
            font-size: 12px;
        }}
        QComboBox:focus {{ border: 1px solid {THEME['ACCENT']}; }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QListView {{
            background-color: #1E1E2E;
            color: {THEME['TEXT']};
            selection-background-color: {THEME['ACCENT']};
            selection-color: #11111B;
        }}
        QScrollBar:vertical {{
            background: {THEME['SURFACE']}; width: 6px; border-radius: 3px;
        }}
        QScrollBar::handle:vertical {{
            background: {THEME['BORDER']}; border-radius: 3px;
        }}
    """


def _log_area_style(text_color: str) -> str:
    return f"""
        QPlainTextEdit {{
            background-color: {THEME['SURFACE']};
            color: {text_color};
            border: 1px solid {THEME['BORDER']};
            border-radius: 8px;
            padding: 8px;
            font-family: 'JetBrains Mono';
            font-size: 12px;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}
    """


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        f"color: {THEME['BORDER']}; background: {THEME['BORDER']}; max-height:1px;"
    )
    return sep

# ─────────────────────────────────────────────────────────────────────────────
# ## TILAU ## — Observability bus: normalised events routed source → zone
# ─────────────────────────────────────────────────────────────────────────────

# Per-level display colour (THEME keys). Drives line colourisation in zones.
_LEVEL_COLOR: Final[dict[str, str]] = {
    "DEBUG":    THEME['SUBTEXT'],
    "INFO":     THEME['TEXT'],
    "WARNING":  THEME['WARNING'],
    "ERROR":    THEME['CRITICAL'],
    "CRITICAL": THEME['CRITICAL'],
}

# Roast keywords that force an immediate file flush (never lose a crack event).
_ROAST_FLUSH_KEYWORDS: Final[tuple[str, ...]] = ("CRACK", "FC", "SC", "ALARM")

# ## TILAU ## — global search highlight colours
_SEARCH_HL: Final[QColor] = QColor(THEME['ACCENT']); _SEARCH_HL.setAlpha(70)
_SEARCH_CUR: Final[QColor] = QColor(THEME['TODAY']); _SEARCH_CUR.setAlpha(190)


def _infer_level(text: str) -> str:
    """Heuristic level for sources without a native level (serial, tail)."""
    t = text.upper()
    if text.startswith("❌") or "CRITICAL" in t:
        return "CRITICAL" if "CRITICAL" in t else "ERROR"
    if "ERROR" in t:
        return "ERROR"
    if text.startswith("⚠") or "WARNING" in t or "WARN" in t:
        return "WARNING"
    return "INFO"


@dataclass(frozen=True, slots=True)
class LogEvent:
    """A single normalised observability record, source-agnostic."""
    source: str                 # "serial" | "tcp" | "tail" | "ble" | "mqtt" | "omniflux"
    text: str
    level: str = "INFO"         # DEBUG / INFO / WARNING / ERROR / CRITICAL
    module: str = ""            # logger namespace (filled by TCP, empty otherwise)
    ts: float = field(default_factory=time.time)


# Level chips: (short label, level name, THEME colour key) in display order.
_LEVEL_CHIPS: Final[tuple[tuple[str, str, str], ...]] = (
    ("D", "DEBUG",    'SUBTEXT'),
    ("I", "INFO",     'ACCENT'),
    ("W", "WARNING",  'WARNING'),
    ("E", "ERROR",    'CRITICAL'),
    ("C", "CRITICAL", 'CRITICAL'),
)
_ALL_LEVELS: Final[frozenset[str]] = frozenset(c[1] for c in _LEVEL_CHIPS)


@dataclass(frozen=True, slots=True)
class FilterState:
    """Per-zone visual filter. Empty query / empty levels == no filtering."""
    query: str = ""
    regex: bool = False
    levels: frozenset = frozenset()   # levels to SHOW; empty == show all


class LogBus(QObject):
    """Central dispatcher. Every source publishes here; consumers subscribe.

    Lives in the UI thread; cross-thread producers emit via queued connection
    (same pattern already used by SerialWorker / TCP handler in this module).
    """
    event = pyqtSignal(object)   # carries a LogEvent

    def emit_line(self, source: str, text: str,
                  level: str = "INFO", module: str = "") -> None:
        """Build and publish a LogEvent from raw fields (thread-safe emit)."""
        self.event.emit(LogEvent(source, text, level, module))


class LogZone:
    """Encapsulates one display area: widget, status label, file logger,
    bounded ring buffer, line counter and per-level colourisation.

    Adding a new observability source is just: build a LogZone and register
    it under its source key — no extra wiring in the window handlers.
    """

    def __init__(self, display: QPlainTextEdit, status: QLabel,
                 file_logger: logging.Logger | None,
                 ring_cap: int, base_color: str) -> None:
        self._display = display
        self._status = status
        self._file_logger = file_logger
        self._base_color = base_color
        self.count: int = 0
        self.last_ts: float = 0.0  # ## TILAU ## — wall-clock ts of last event (freshness)
        self.error_count: int = 0  # ## TILAU ## — ERROR+CRITICAL seen (alerting)
        self.paused: bool = False  # ## TILAU ## — global render freeze
        # Bound the UI buffer to protect against memory growth at high throughput.
        self._display.setMaximumBlockCount(ring_cap)
        # Source-of-truth ring buffer: keeps full (unfiltered) events so the
        # display can be re-rendered when the filter changes.
        self._buffer: deque[LogEvent] = deque(maxlen=ring_cap)
        self._matcher = None              # callable(str)->bool, or None
        self._levels: frozenset = frozenset()  # empty == all levels shown

    # ── filtering ──────────────────────────────────────────────────────────

    def set_filter(self, state: FilterState) -> bool:
        """Apply a filter and re-render. Returns False on invalid regex."""
        valid = True
        if state.query:
            if state.regex:
                try:
                    rx = re.compile(state.query, re.IGNORECASE)
                    self._matcher = rx.search
                except re.error:
                    self._matcher = None  # invalid → neutralise (show all)
                    valid = False
            else:
                needle = state.query.lower()
                self._matcher = lambda t, n=needle: n in t.lower()
        else:
            self._matcher = None
        self._levels = state.levels if state.levels != _ALL_LEVELS else frozenset()
        self._rerender()
        return valid

    def _passes(self, ev: LogEvent) -> bool:
        if self._levels and ev.level not in self._levels:
            return False
        if self._matcher is not None:
            return bool(self._matcher(f"{ev.module} {ev.text}"))
        return True

    def _rerender(self) -> None:
        """Rebuild the display from the buffer under the active filter."""
        self._display.setUpdatesEnabled(False)
        self._display.clear()
        for ev in self._buffer:
            if self._passes(ev):
                self._render(ev)
        self._display.setUpdatesEnabled(True)

    # ── ingestion / rendering ────────────────────────────────────────────────

    def append(self, ev: LogEvent) -> None:
        """Buffer + (file always) + render only if the event passes the filter."""
        self._buffer.append(ev)
        self.count += 1
        self.last_ts = ev.ts
        if ev.level in ("ERROR", "CRITICAL"):
            self.error_count += 1
        if self._file_logger is not None:
            self._file_logger.info(ev.text)
            # Never lose a roast-critical line to buffering.
            if any(k in ev.text for k in _ROAST_FLUSH_KEYWORDS):
                for h in self._file_logger.handlers:
                    h.flush()
        if not self.paused and self._passes(ev):
            self._render(ev)

    def _render(self, ev: LogEvent) -> None:
        """Append one colourised line to the display (no filter check here)."""
        ts = QDateTime.currentDateTime().toString("HH:mm:ss")
        color = _LEVEL_COLOR.get(ev.level, self._base_color)
        prefix = f"({ev.module}) " if ev.module else ""
        safe = html.escape(f"[{ts}] {prefix}{ev.text}")
        weight = "bold" if ev.level in ("ERROR", "CRITICAL") else "normal"
        # appendHtml gives per-line colour that appendPlainText cannot.
        self._display.appendHtml(
            f'<span style="color:{color};font-weight:{weight};white-space:pre">{safe}</span>'
        )
        self._display.verticalScrollBar().setValue(
            self._display.verticalScrollBar().maximum()
        )

    def flush(self) -> None:
        if self._file_logger is not None:
            for h in self._file_logger.handlers:
                h.flush()

    def set_paused(self, paused: bool) -> None:
        """Freeze/unfreeze rendering. Events keep buffering + hitting the file."""
        self.paused = paused
        if not paused:
            self._rerender()

    def recent(self, n: int) -> list:
        """Last n buffered events (for the snapshot export)."""
        return list(self._buffer)[-n:]

    def stats(self) -> tuple[int, int, int, float, int]:
        """(total, buffer used, capacity, last_ts, error_count) for the dashboard."""
        return (self.count, len(self._buffer), self._buffer.maxlen or 0,
                self.last_ts, self.error_count)


# ── Collapsible / focusable zone panel ──────────────────────────────────────
_QWIDGETSIZE_MAX: Final[int] = 16777215   # Qt's QWIDGETSIZE_MAX sentinel


class _ZoneHeader(QFrame):
    """Header strip of a zone; double-click toggles focus mode."""
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class ZonePanel(QWidget):
    """Self-contained log zone: collapsible header + display.

    Packs into a QSplitter so neighbours reclaim space when one collapses.
    Hosts the display consumed by a LogZone; the bus is unaffected.
    """
    focus_requested = pyqtSignal(object)   # emits self
    collapsed_changed = pyqtSignal()       # for layout persistence
    filter_changed = pyqtSignal(object)    # emits FilterState

    def __init__(self, title: str, base_color: str, status_text: str,
                 extra_header: list | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._header = _ZoneHeader()
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(0, 4, 0, 0)
        hl.setSpacing(6)

        # Chevron toggles collapse; carries its own click (no window drag).
        self._chevron = QToolButton()
        self._chevron.setAutoRaise(True)
        self._chevron.setText("▾")
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.setStyleSheet(
            f"QToolButton {{ color: {THEME['ACCENT']}; border: none; "
            f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
        )
        self._chevron.clicked.connect(self.toggle_collapsed)

        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 11px; font-weight: bold; "
            f"letter-spacing: 2px; font-family: 'JetBrains Mono';"
        )
        self._title_lbl = title_lbl  # ## TILAU ## exposed so callers can relabel the zone (see set_title)

        self.status = QLabel(status_text)
        self.status.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 12px; margin-left: 8px;"
        )

        # Permanent cumulative error/exception counter shown on the header.
        self._badge = QLabel("")
        self._badge.setStyleSheet(
            f"color: {THEME['BG']}; background: {THEME['CRITICAL']}; "
            f"border-radius: 8px; padding: 1px 6px; font-size: 9px; "
            f"font-weight: bold; font-family: 'JetBrains Mono';"
        )
        self._badge.setVisible(False)

        # Filter-bar toggle (reveals the per-zone filter row on demand).
        self._filter_btn = QToolButton()
        self._filter_btn.setAutoRaise(True)
        self._filter_btn.setCheckable(True)
        self._filter_btn.setText("🔍")
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setToolTip(
            QApplication.translate("tilauscope_beancave", "Filter this zone")
        )
        self._filter_btn.setStyleSheet(
            f"QToolButton {{ color: {THEME['SUBTEXT']}; border: none; font-size: 12px; }}"
            f"QToolButton:checked {{ color: {THEME['ACCENT']}; }}"
        )
        self._filter_btn.toggled.connect(self._toggle_filter_bar)

        # Dedicated focus/restore button (mirrors the double-click action).
        self._focus_btn = QToolButton()
        self._focus_btn.setAutoRaise(True)
        self._focus_btn.setText("⛶")
        self._focus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._focus_btn.setToolTip(
            QApplication.translate("tilauscope_beancave", "Focus / restore (Esc)")
        )
        self._focus_btn.setStyleSheet(
            f"QToolButton {{ color: {THEME['SUBTEXT']}; border: none; font-size: 13px; }}"
            f"QToolButton:hover {{ color: {THEME['ACCENT']}; }}"
        )
        self._focus_btn.clicked.connect(lambda: self.focus_requested.emit(self))

        hl.addWidget(self._chevron)
        hl.addWidget(title_lbl)
        hl.addWidget(self.status)
        hl.addWidget(self._badge)
        hl.addStretch()
        for w in (extra_header or []):
            hl.addWidget(w)
        hl.addWidget(self._filter_btn)
        hl.addWidget(self._focus_btn)

        self._header.double_clicked.connect(lambda: self.focus_requested.emit(self))

        # ── Filter bar (hidden until 🔍 toggled) ───────────────────────────
        self._filter_open = False
        self._filter_bar = self._build_filter_bar()
        self._filter_bar.setVisible(False)

        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setStyleSheet(_log_area_style(base_color))

        root.addWidget(self._header)
        root.addWidget(self._filter_bar)
        root.addWidget(self.display, 1)

    # ── Filter bar ─────────────────────────────────────────────────────────

    def _build_filter_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(f"background: {THEME['BG']};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 2)
        row.setSpacing(8)

        # Debounce text typing so we re-render at most every 200 ms.
        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(200)
        self._filter_debounce.timeout.connect(self._emit_filter)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(
            QApplication.translate("tilauscope_beancave", "filter…")
        )
        self._filter_edit.setClearButtonEnabled(True)
        self._apply_filter_edit_style(valid=True)
        self._filter_edit.textChanged.connect(lambda: self._filter_debounce.start())

        # Regex toggle (.* ). Text-contains when off.
        self._regex_btn = QToolButton()
        self._regex_btn.setCheckable(True)
        self._regex_btn.setText(".*")
        self._regex_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._regex_btn.setToolTip(
            QApplication.translate("tilauscope_beancave", "Regular expression")
        )
        self._regex_btn.setStyleSheet(
            f"QToolButton {{ color: {THEME['SUBTEXT']}; border: 1px solid {THEME['BORDER']}; "
            f"border-radius: 6px; padding: 2px 7px; font-family: 'JetBrains Mono'; font-size: 11px; }}"
            f"QToolButton:checked {{ color: {THEME['ACCENT']}; border-color: {THEME['ACCENT']}; }}"
        )
        self._regex_btn.toggled.connect(self._emit_filter)

        # Level chips (per-zone). Checked == level shown. All checked by default.
        self._level_chips: dict[str, QToolButton] = {}
        chip_row = QHBoxLayout()
        chip_row.setSpacing(4)
        for label, level, color_key in _LEVEL_CHIPS:
            chip = QToolButton()
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setText(label)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(level.capitalize())
            c = THEME[color_key]
            chip.setStyleSheet(
                f"QToolButton {{ color: {THEME['SUBTEXT']}; background: {THEME['SURFACE']}; "
                f"border: none; border-radius: 5px; padding: 2px 6px; "
                f"font-family: 'JetBrains Mono'; font-size: 10px; }}"
                f"QToolButton:checked {{ color: {c}; background: {THEME['BORDER']}; }}"
            )
            chip.toggled.connect(self._emit_filter)
            self._level_chips[level] = chip
            chip_row.addWidget(chip)

        row.addWidget(self._filter_edit, 1)
        row.addWidget(self._regex_btn)
        row.addLayout(chip_row)
        return bar

    def _apply_filter_edit_style(self, valid: bool) -> None:
        border = THEME['BORDER'] if valid else THEME['CRITICAL']
        self._filter_edit.setStyleSheet(
            f"QLineEdit {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']}; "
            f"border: 1px solid {border}; border-radius: 6px; padding: 3px 8px; "
            f"font-family: 'JetBrains Mono'; font-size: 11px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )

    def _toggle_filter_bar(self, on: bool) -> None:
        self._filter_open = on
        self._filter_bar.setVisible(on and not self._collapsed)
        if on:
            self._filter_edit.setFocus()
        else:
            # Closing the bar clears the filter (show everything again).
            self._filter_edit.clear()
            for chip in self._level_chips.values():
                chip.blockSignals(True)
                chip.setChecked(True)
                chip.blockSignals(False)
            self._regex_btn.setChecked(False)
            self._emit_filter()

    def _build_filter_state(self) -> FilterState:
        shown = frozenset(
            lvl for lvl, chip in self._level_chips.items() if chip.isChecked()
        )
        return FilterState(
            query=self._filter_edit.text(),
            regex=self._regex_btn.isChecked(),
            levels=shown,
        )

    def _emit_filter(self) -> None:
        self.filter_changed.emit(self._build_filter_state())

    def set_filter_valid(self, valid: bool) -> None:
        """Visual feedback on the text field for regex compilation errors."""
        self._apply_filter_edit_style(valid)

    def set_title(self, title: str) -> None:
        """## TILAU ## Relabel the zone header (e.g. serial panel switching
        between "ESP32 FLOW (Serial)" and "TRP FLOW (Serial)" depending on
        which device is actually configured)."""
        self._title_lbl.setText(title.upper())

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
        self.collapsed_changed.emit()

    def set_collapsed(self, collapsed: bool) -> None:
        """Hide the display and shrink the panel to its header (or restore)."""
        self._collapsed = collapsed
        self.display.setVisible(not collapsed)
        self._filter_bar.setVisible(self._filter_open and not collapsed)
        self._chevron.setText("▸" if collapsed else "▾")
        if collapsed:
            # Bound height to the header so the splitter gives space to others.
            self.setMaximumHeight(self._header.sizeHint().height() + 6)
        else:
            self.setMaximumHeight(_QWIDGETSIZE_MAX)

    def set_error_count(self, n: int) -> None:
        """Permanent cumulative error/exception counter on the zone header."""
        if n > 0:
            self._badge.setText(f"⚠ {n}")
            self._badge.setVisible(True)
        else:
            self._badge.setVisible(False)


# ── Application observability dashboard ──────────────────────────────────────
_SOURCE_COLOR: Final[dict[str, str]] = {
    "serial": THEME['SUCCESS'],
    "tcp":    THEME['ACCENT'],
    "tail":   THEME['WARNING'],
}
_SETTINGS_KEY_DASH = "tilaulogger/dashboard_open"   # ## TILAU ##
_DASH_INTERVAL_MS: Final[int] = 1000


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """One sampling of application-internal observability metrics."""
    mem_process: int            # process USS (bytes)
    mem_avail: int              # system available (bytes)
    mem_avail_pct: int          # system available (%)
    cpu_pct: float
    ui_lag_ms: float            # event-loop scheduling drift
    threads: tuple              # ((name, alive, daemon), …)
    thread_count: int
    zones: tuple                # ((source, count, used, cap, rate, fresh_s, err), …)
    serial_on: bool
    serial_label: str
    tcp_on: bool
    tail_on: bool
    gc_counts: tuple            # (gen0, gen1, gen2)
    uptime_s: float
    conn_count: int             # open inet sockets
    fd_count: int               # open file descriptors / handles


class MetricsCollector(QObject):
    """1 Hz sampler. Emits a SystemSnapshot; idle while the panel is collapsed.

    Bus/connection figures are pulled through provider callables so the
    collector stays decoupled from the window internals.
    """
    snapshot_ready = pyqtSignal(object)

    def __init__(self, stats_provider, state_provider,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stats_provider = stats_provider   # () -> [(source, count, used, cap), …]
        self._state_provider = state_provider   # () -> (ser_on, ser_label, tcp_on, tail_on)
        self._proc = psutil.Process()
        self._proc.cpu_percent(None)            # prime non-blocking CPU sampling
        self._start = time.monotonic()
        self._last_tick: float | None = None
        self._prev_counts: dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(_DASH_INTERVAL_MS)
        self._timer.timeout.connect(self._collect)

    def start(self) -> None:
        self._last_tick = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _collect(self) -> None:
        now = time.monotonic()
        # UI responsiveness: drift of this 1 Hz timer vs its nominal interval.
        lag_ms = 0.0
        dt = _DASH_INTERVAL_MS / 1000.0
        if self._last_tick is not None:
            dt = max(1e-3, now - self._last_tick)
            lag_ms = max(0.0, (dt - _DASH_INTERVAL_MS / 1000.0) * 1000.0)
        self._last_tick = now

        try:
            mfi = self._proc.memory_full_info()
            mem_proc = getattr(mfi, "uss", 0) or mfi.rss
        except Exception:
            mem_proc = 0
        vm = psutil.virtual_memory()
        cpu = self._proc.cpu_percent(None)

        threads = tuple(
            (t.name, t.is_alive(), bool(t.daemon)) for t in threading.enumerate()
        )

        wall = time.time()
        zones = []
        for src, count, used, cap, last_ts, err in self._stats_provider():
            rate = round((count - self._prev_counts.get(src, count)) / dt)
            self._prev_counts[src] = count
            fresh = (wall - last_ts) if last_ts else -1.0   # -1 == never
            zones.append((src, count, used, cap, max(0, rate), fresh, err))

        # Open sockets + file descriptors (leak detection). Best-effort.
        try:
            conn_count = len(self._proc.net_connections(kind="inet"))
        except Exception:
            conn_count = -1
        try:
            fd_count = self._proc.num_fds()
        except AttributeError:
            try:
                fd_count = self._proc.num_handles()   # Windows
            except Exception:
                fd_count = -1
        except Exception:
            fd_count = -1

        ser_on, ser_label, tcp_on, tail_on = self._state_provider()

        self.snapshot_ready.emit(SystemSnapshot(
            mem_process=mem_proc,
            mem_avail=vm.available,
            mem_avail_pct=int(round(100 - vm.percent)),
            cpu_pct=cpu,
            ui_lag_ms=lag_ms,
            threads=threads,
            thread_count=len(threads),
            zones=tuple(zones),
            serial_on=ser_on, serial_label=ser_label,
            tcp_on=tcp_on, tail_on=tail_on,
            gc_counts=tuple(gc.get_count()),
            uptime_s=now - self._start,
            conn_count=conn_count,
            fd_count=fd_count,
        ))


class Sparkline(QWidget):
    """Tiny 60-sample trend line, repainted on each push (no dependencies)."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: deque = deque(maxlen=60)
        self._color = QColor(color)
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, value: float) -> None:
        self._data.append(float(value))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, pad = self.width(), self.height(), 2.0
        lo, hi = min(self._data), max(self._data)
        rng = (hi - lo) or 1.0
        n = len(self._data)
        dx = (w - 2 * pad) / max(1, n - 1)
        poly = QPolygonF()
        for i, val in enumerate(self._data):
            x = pad + i * dx
            y = h - pad - ((val - lo) / rng) * (h - 2 * pad)
            poly.append(QPointF(x, y))
        pen = QPen(self._color)
        pen.setWidthF(1.4)
        p.setPen(pen)
        p.drawPolyline(poly)
        p.end()


class SystemDashboard(QWidget):
    """Collapsible observability panel rendered from SystemSnapshot updates."""
    toggled = pyqtSignal(bool)   # True == expanded

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.setSpacing(6)
        self._chevron = QToolButton()
        self._chevron.setAutoRaise(True)
        self._chevron.setText("▸")
        self._chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron.setStyleSheet(
            f"QToolButton {{ color: {THEME['ACCENT']}; border: none; "
            f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
        )
        self._chevron.clicked.connect(self.toggle)
        title = QLabel(
            QApplication.translate("tilauscope_beancave", "SYSTEM · OBSERVABILITY")
        )
        title.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 11px; font-weight: bold; "
            f"letter-spacing: 2px; font-family: 'JetBrains Mono';"
        )
        self._live = QLabel("")
        self._live.setStyleSheet(
            f"color: {THEME['SUCCESS']}; font-size: 10px; margin-left: 6px; "
            f"font-family: 'JetBrains Mono';"
        )
        header.addWidget(self._chevron)
        header.addWidget(title)
        header.addWidget(self._live)
        header.addStretch()
        root.addLayout(header)

        # Body (hidden until expanded)
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 4, 0, 4)
        body.setSpacing(6)

        cards = QHBoxLayout()
        cards.setSpacing(6)
        self._v_mem = self._add_card(cards, QApplication.translate("tilauscope_beancave", "PROC MEM"))
        self._v_free = self._add_card(cards, QApplication.translate("tilauscope_beancave", "FREE MEM"))
        self._v_cpu = self._add_card(cards, QApplication.translate("tilauscope_beancave", "CPU"))
        self._v_thr = self._add_card(cards, QApplication.translate("tilauscope_beancave", "THREADS"))
        self._v_lag = self._add_card(cards, QApplication.translate("tilauscope_beancave", "UI LATENCY"))
        self._v_up = self._add_card(cards, QApplication.translate("tilauscope_beancave", "UPTIME"))
        body.addLayout(cards)

        # Trend sparklines (last 60 samples).
        sparks = QHBoxLayout()
        sparks.setSpacing(10)
        self._spk_cpu = self._add_spark(sparks, QApplication.translate("tilauscope_beancave", "CPU"), THEME['ACCENT'])
        self._spk_mem = self._add_spark(sparks, QApplication.translate("tilauscope_beancave", "MEM"), THEME['SUCCESS'])
        self._spk_bus = self._add_spark(sparks, QApplication.translate("tilauscope_beancave", "BUS/s"), THEME['TODAY'])
        self._spk_lag = self._add_spark(sparks, QApplication.translate("tilauscope_beancave", "LAT"), THEME['WARNING'])
        body.addLayout(sparks)

        self._lbl_tasks = self._add_section(
            body, QApplication.translate("tilauscope_beancave", "RUNNING TASKS"))
        self._lbl_bus = self._add_section(
            body, QApplication.translate("tilauscope_beancave", "BUS · BUFFERS"))
        self._lbl_conn = self._add_section(
            body, QApplication.translate("tilauscope_beancave", "CONNECTIONS · GC · I/O"))

        self._body.setVisible(False)
        root.addWidget(self._body)

    # ── construction helpers ─────────────────────────────────────────────────

    def _add_card(self, parent: QHBoxLayout, title: str) -> QLabel:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {THEME['SURFACE']}; border-radius: 6px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(1)
        cap = QLabel(title)  # title pre-translated at call site (pylupdate6)
        cap.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
        )
        val = QLabel("—")
        val.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 15px; font-family: 'JetBrains Mono';"
        )
        lay.addWidget(cap)
        lay.addWidget(val)
        parent.addWidget(frame, 1)
        return val

    def _add_section(self, parent: QVBoxLayout, title: str) -> QLabel:
        cap = QLabel(title)
        cap.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 9px; letter-spacing: 1px; "
            f"font-family: 'JetBrains Mono';"
        )
        body = QLabel("—")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 10px;")
        parent.addWidget(cap)
        parent.addWidget(body)
        return body

    def _add_spark(self, parent: QHBoxLayout, title: str, color: str) -> Sparkline:
        col = QVBoxLayout()
        col.setSpacing(1)
        cap = QLabel(title)  # title pre-translated at call site (pylupdate6)
        cap.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
        )
        spark = Sparkline(color)
        col.addWidget(cap)
        col.addWidget(spark)
        parent.addLayout(col, 1)
        return spark

    # ── collapse / expand ────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._open

    def toggle(self) -> None:
        self.set_open(not self._open)
        self.toggled.emit(self._open)

    def set_open(self, opened: bool) -> None:
        self._open = opened
        self._body.setVisible(opened)
        self._chevron.setText("▾" if opened else "▸")
        self._live.setText("● 1 Hz" if opened else "")

    # ── live update ──────────────────────────────────────────────────────────

    def update_snapshot(self, s: SystemSnapshot) -> None:
        self._v_mem.setText(bytes2human(s.mem_process))
        self._v_free.setText(f"{bytes2human(s.mem_avail)} {s.mem_avail_pct}%")
        self._v_cpu.setText(f"{s.cpu_pct:.0f}%")
        self._v_thr.setText(str(s.thread_count))
        lag_col = (THEME['SUCCESS'] if s.ui_lag_ms < 25
                   else THEME['WARNING'] if s.ui_lag_ms < 80 else THEME['CRITICAL'])
        self._v_lag.setText(f"{s.ui_lag_ms:.0f} ms")
        self._v_lag.setStyleSheet(
            f"color: {lag_col}; font-size: 15px; font-family: 'JetBrains Mono';"
        )
        self._v_up.setText(self._fmt_uptime(s.uptime_s))

        # Trend sparklines
        self._spk_cpu.push(s.cpu_pct)
        self._spk_mem.push(s.mem_process)
        self._spk_bus.push(sum(z[4] for z in s.zones))
        self._spk_lag.push(s.ui_lag_ms)

        # Threads
        chips = []
        for name, alive, _daemon in s.threads:
            col = THEME['SUCCESS'] if alive else THEME['SUBTEXT']
            dot = "●" if alive else "○"
            chips.append(f'<span style="color:{col};">{dot} {html.escape(name)}</span>')
        self._lbl_tasks.setText(" &nbsp; ".join(chips))

        # Bus / buffers (freshness + error counter per source)
        parts = []
        for src, count, used, cap, rate, fresh, err in s.zones:
            col = _SOURCE_COLOR.get(src, THEME['SUBTEXT'])
            pct = int(100 * used / cap) if cap else 0
            fresh_txt = "—" if fresh < 0 else (f"{fresh:.0f}s" if fresh >= 1 else "now")
            err_txt = (f' · <span style="color:{THEME["CRITICAL"]};">err {err}</span>'
                       if err else "")
            parts.append(
                f'<span style="color:{col};">{src}</span> '
                f'<span style="color:{THEME["SUBTEXT"]};">{count} · {used}/{cap} '
                f'({pct}%) · {rate}/s · ⟳{fresh_txt}</span>{err_txt}'
            )
        self._lbl_bus.setText(" &nbsp;&nbsp; ".join(parts))

        # Connections + GC + I/O
        def _badge(on: bool, label: str) -> str:
            col = THEME['SUCCESS'] if on else THEME['SUBTEXT']
            return f'<span style="color:{col};">{"●" if on else "○"} {html.escape(label)}</span>'

        g0, g1, g2 = s.gc_counts
        conn = " &nbsp; ".join([
            _badge(s.serial_on, f"serial {s.serial_label}".strip()),
            _badge(s.tcp_on, "tcp"),
            _badge(s.tail_on, "tail"),
        ])
        sock = "—" if s.conn_count < 0 else str(s.conn_count)
        fds = "—" if s.fd_count < 0 else str(s.fd_count)
        self._lbl_conn.setText(
            f'{conn} &nbsp;&nbsp; '
            f'<span style="color:{THEME["SUBTEXT"]};">GC {g0}/{g1}/{g2} &nbsp; '
            f'sock {sock} &nbsp; fd {fds}</span>'
        )

    @staticmethod
    def _fmt_uptime(seconds: float) -> str:
        s = int(seconds)
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# --- CLASSES DE TRAVAIL (THREADS) ---
# ## TILAU ##
# Standard baud rates offered in the UI — ordered low to high
BAUD_RATES: Final[list[int]] = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
_DEFAULT_BAUD: Final[int] = 921600

_SETTINGS_KEY_PORT = "tilaulogger/serial_port"
_SETTINGS_KEY_BAUD = "tilaulogger/serial_baud"
_SETTINGS_KEY_SPLITTER = "tilaulogger/splitter_state"   # ## TILAU ##
_SETTINGS_KEY_COLLAPSED = "tilaulogger/collapsed"        # ## TILAU ## — dict source→bool

# ## TILAU ##
_ARTISAN_LOG_NAME: Final[str] = "artisan.log"
_TAIL_MAX_LINES:   Final[int] = 200
_LIVE_MAX_LINES:   Final[int] = 2000   # ## TILAU ## — ring cap for serial/tcp zones
_TAIL_POLL_MS:     Final[int] = 5000   # 5 s — matches existing flush_timer cadence


class ArtisanLogTailWorker(QObject):
    """
    Polls artisan.log from a background QTimer and emits new lines via signal.
    Tracks file position to emit only new content; handles log rotation (inode
    change or size reset) by reopening from the beginning.
    """
    lines_ready = pyqtSignal(list)   # list[str] — batch of new lines
    status_changed = pyqtSignal(str) # human-readable status for the UI label

    def __init__(self, log_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = log_path
        self._pos: int = 0
        self._inode: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(_TAIL_POLL_MS)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        """Seek to end of current file and begin polling (tail -f behaviour)."""
        try:
            stat = self._path.stat()
            self._inode = stat.st_ino
            self._pos = stat.st_size   # start at EOF — only new lines shown
            self.status_changed.emit(
                QApplication.translate("tilauscope_beancave", "🟢 tailing")
            )
        except OSError:
            self._pos = 0
            self._inode = None
            self.status_changed.emit(
                QApplication.translate("tilauscope_beancave", "🟡 waiting for file…")
            )
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.status_changed.emit(
            QApplication.translate("tilauscope_beancave", "⚫ inactive")
        )

    def _poll(self) -> None:
        """Read any new content appended since last poll."""
        try:
            stat = self._path.stat()
        except OSError:
            # File not yet created or temporarily missing
            self.status_changed.emit(
                QApplication.translate("tilauscope_beancave", "🟡 waiting for file…")
            )
            return

        # Detect log rotation: inode changed or file shrank
        if stat.st_ino != self._inode or stat.st_size < self._pos:
            self._pos = 0
            self._inode = stat.st_ino
            self.status_changed.emit(
                QApplication.translate("tilauscope_beancave", "🔄 log rotated")
            )

        if stat.st_size == self._pos:
            return  # nothing new

        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._pos)
                new_lines = fh.readlines()
                self._pos = fh.tell()
        except OSError:
            return

        clean = [ln.rstrip("\n\r") for ln in new_lines if ln.strip()]
        if clean:
            self.lines_ready.emit(clean)
            self.status_changed.emit(
                QApplication.translate("tilauscope_beancave", "🟢 tailing")
            )


class SerialWorker(QObject):
    """Reads a serial port in a background thread; connection is explicit (not automatic)."""
    message_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.port: str | None = None
        self.baud: int = _DEFAULT_BAUD
        self.running: bool = True
        self._serial_lock = threading.Lock()
        self.ser: serial.Serial | None = None
        self.synchronized: bool = False  # gate flag to skip boot noise

    def connect_port(self, port: str, baud: int) -> None:
        """Explicitly open the given port at the given baud rate."""
        with self._serial_lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                self.ser = None
            self.port = port
            self.baud = baud
        # Emit outside the lock — actual open happens in run()
        self.message_received.emit(
            QApplication.translate("tilauscope_beancave", "🔄 Connecting to ")
            + f"{port} @ {baud}..."
        )

    def disconnect_port(self) -> None:
        """Explicitly close the current port."""
        with self._serial_lock:
            self.port = None
            if self.ser and self.ser.is_open:
                self.ser.close()
                self.ser = None
        self.message_received.emit(
            QApplication.translate("tilauscope_beancave", "🔌 Disconnected")
        )

    def send_line(self, text: str) -> bool:
        """## TILAU ## Write one line to the currently open port (LF-terminated,
        spec /TRP/specifications.md Sec2) -- used for the TRP HELLO probe and any
        other ad hoc debug write. Returns False if no port is open."""
        with self._serial_lock:
            ser = self.ser
            if not (ser and ser.is_open):
                return False
            try:
                ser.write((text if text.endswith('\n') else text + '\n').encode('utf-8'))
                return True
            except Exception:  # pylint: disable=broad-except
                return False

    # Inside SerialWorker.run
    def run(self):
        while self.running:
            with self._serial_lock:
                port_target = self.port
                baud_target = self.baud
                ser_open = self.ser and self.ser.is_open

            if port_target and not ser_open:
                try:
                    with self._serial_lock:
                        self.ser = serial.Serial(port_target, baud_target, timeout=0.1)
                        self.ser.dtr = False
                        self.ser.rts = False
                        time.sleep(0.1)
                        self.ser.reset_input_buffer()
                        self.synchronized = True
                    self.message_received.emit(
                        QApplication.translate("tilauscope_beancave", "✅ Connected to ")
                        + f"{port_target} @ {baud_target}"
                    )
                except Exception as e:
                    self.message_received.emit(f"❌ Error opening {port_target}: {str(e)}")
                    with self._serial_lock:
                        self.ser = None

            with self._serial_lock:
                ser = self.ser

            if ser and ser.is_open:
                try:
                    if ser.in_waiting > 0:
                        raw_data = ser.readline()
                        try:
                            line = raw_data.decode('utf-8', errors='ignore').strip()
                        except UnicodeDecodeError:
                            threading.Event().wait(0.05)
                            continue
                        if line:
                            self.message_received.emit(line)
                except Exception:
                    with self._serial_lock:
                        self.ser = None
            threading.Event().wait(0.05)

    def stop(self):
        self.running = False
        with self._serial_lock:
            if self.ser and self.ser.is_open:
                self.ser.close()

class TCPLogHandler(socketserver.StreamRequestHandler):
    """Handler LogRecord via TCP with exit logic."""
    def handle(self):
        # Set a timeout so recv() doesn't block forever
        self.request.settimeout(1.0) 
        
        # Check the server's running flag
        while getattr(self.server, 'running', True):
            try:
                chunk = self.request.recv(4)
                if not chunk: # Connection closed by client
                    break
                if len(chunk) < 4: 
                    continue
                
                slen = struct.unpack('>L', chunk)[0]
                chunk = self.request.recv(slen)
                while len(chunk) < slen:
                    more = self.request.recv(slen - len(chunk))
                    if not more:  # EOF → connexion fermée proprement
                        return
                    chunk += more
                
                obj = pickle.loads(chunk)
                # ## TILAU ## — emit structured fields so the bus keeps level/module
                self.server.ui_signal.emit(obj['name'], obj['levelname'], obj['msg'])
            except (socket.timeout, TimeoutError):
                # This allows the loop to check 'self.server.running'
                continue
            except Exception:
                break

class TCPWorker(socketserver.TCPServer):
    allow_reuse_address = True 

    def __init__(self, host='127.0.0.1', port=9021, signal=None):
        self.ui_signal = signal
        self.running = True  # Flag to signal handlers to stop
        self.request_queue_size = 5
        super().__init__((host, port), TCPLogHandler, bind_and_activate=True)

#--- INTERFACE GRAPHIQUE ---

class TilauscopeLoggerWindow(QWidget):
    serial_signal = pyqtSignal(str)
    tcp_signal = pyqtSignal(str, str, str)   # ## TILAU ## — (name, level, msg)

    def __init__(self, parent:'QWidget', aw:'ApplicationWindow') -> None:
        super().__init__(parent)
        self.aw = aw

        # Frameless + translucent, but a regular top-level Window (not a child /
        # Tool panel) so it can be pushed behind Artisan and other windows.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowModality(Qt.WindowModality.NonModal)
        
        self._drag_pos = None

        self.tcp_server: 'TCPWorker | None' = None
        self.tcp_thread: 'threading.Thread | None' = None

        # Flush timer
        self.flush_timer = QTimer(self)
        self.flush_timer.timeout.connect(self.flush_all_logs)
        self.flush_timer.start(5000)

        # File logging
        self.setup_file_loggers()

        # ## TILAU ## — persistent settings (must exist before _build_ui uses them)
        self._settings = QSettings("TilauScope", "TilauLogger")

        # ## TILAU ## — observability bus + source→zone registry.
        # Bus must exist before _build_ui, which registers the zones.
        # ## TILAU ## — translate recurring status strings once (no per-update translate).
        # Full translate() form (no alias) so pylupdate6 can extract the literals.
        self._tr_ser_connected = QApplication.translate("tilauscope_beancave", "🟢 connected")
        self._tr_ser_error = QApplication.translate("tilauscope_beancave", "🔴 error")
        self._tr_ser_inactive = QApplication.translate("tilauscope_beancave", "⚫ inactive")
        self._tr_ser_connecting = QApplication.translate("tilauscope_beancave", "🟡 connecting...")
        self._tr_tcp_receiving = QApplication.translate("tilauscope_beancave", "🟢 receiving")

        self.bus = LogBus(self)
        self.bus.event.connect(self._on_bus_event)
        self._zones: dict[str, LogZone] = {}
        self._panels: dict[str, 'ZonePanel'] = {}   # ## TILAU ## — source → panel
        self._focused_source: str | None = None
        self._pre_focus: dict[str, bool] = {}        # collapse state before focus

        self.setStyleSheet(_base_style())
        self._build_ui()

        self.resize(1100, 680)

        self.serial_signal.connect(self.handle_serial_msg)
        self.tcp_signal.connect(self.handle_tcp_msg)

        # Serial Worker — starts idle, no port set
        self.ser_worker = SerialWorker()
        self.ser_worker.message_received.connect(self.serial_signal.emit)
        self.ser_thread = threading.Thread(target=self.ser_worker.run, daemon=True, name="TilauSerial")
        self.ser_thread.start()

        # Restore saved port selection (UI only — no auto-connect)
        saved_port = self._settings.value(_SETTINGS_KEY_PORT, "")
        if saved_port:
            idx = self.port_selector.findText(saved_port)
            if idx >= 0:
                self.port_selector.setCurrentIndex(idx)

        # TCP Server
        self.start_tcp_thread()

        # ## TILAU ## — artisan.log tail worker (idle until Start is pressed)
        artisan_log_path = self._log_dir / ".." / _ARTISAN_LOG_NAME
        self._tail_worker = ArtisanLogTailWorker(artisan_log_path, parent=self)
        self._tail_worker.lines_ready.connect(self._on_tail_lines)
        self._tail_worker.status_changed.connect(self._on_tail_status)

        self.aw.tilaudebug.setChecked(True)
        _log.info("debug start")

        # ## TILAU ## — restore splitter sizes + collapsed zones from last session
        self._restore_layout()

        # ## TILAU ## — metrics collector feeding the observability dashboard
        self._collector = MetricsCollector(
            stats_provider=lambda: [(src, *z.stats()) for src, z in self._zones.items()],
            state_provider=self._collect_state,
            parent=self,
        )
        self._collector.snapshot_ready.connect(self.dashboard.update_snapshot)
        # Restore dashboard open state; sampling runs only while expanded.
        if self._settings.value(_SETTINGS_KEY_DASH, False, type=bool):
            self.dashboard.set_open(True)
            self._collector.start()

    def _collect_state(self) -> tuple:
        """Provider: connection/runtime state for the dashboard."""
        ser_label = ""
        if self._connected:
            ser_label = f"{self.port_selector.currentText()}@{self.baud_selector.currentText()}"
        return (self._connected, ser_label,
                self.tcp_server is not None, self._tail_running)

    def _on_dashboard_toggled(self, opened: bool) -> None:
        """Pause sampling while collapsed; persist the choice."""
        if opened:
            self._collector.start()
        else:
            self._collector.stop()
        self._settings.setValue(_SETTINGS_KEY_DASH, opened)

    # ── Drag-to-move ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── Focus mode & layout persistence ───────────────────────────────────────

    def _on_focus_requested(self, panel: 'ZonePanel') -> None:
        """Toggle single-zone focus: collapse all others, or restore."""
        src = next((s for s, p in self._panels.items() if p is panel), None)
        if src is None:
            return
        if self._focused_source == src:
            self._exit_focus()
        else:
            self._enter_focus(src)

    def _enter_focus(self, src: str) -> None:
        # Remember pre-focus collapse state on first entry so Esc restores it.
        if self._focused_source is None:
            self._pre_focus = {s: p.is_collapsed for s, p in self._panels.items()}
        self._focused_source = src
        for s, p in self._panels.items():
            p.set_collapsed(s != src)
        self._save_layout()

    def _exit_focus(self) -> None:
        if self._focused_source is None:
            return
        self._focused_source = None
        for s, p in self._panels.items():
            p.set_collapsed(self._pre_focus.get(s, False))
        self._save_layout()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        # Esc priority: close search bar, else leave focus mode.
        if event.key() == Qt.Key.Key_Escape:
            if getattr(self, '_search_open', False):
                self._close_search()
                event.accept()
                return
            if self._focused_source is not None:
                self._exit_focus()
                event.accept()
                return
        super().keyPressEvent(event)

    def _save_layout(self) -> None:
        """Persist splitter sizes and collapsed zones (source-keyed list)."""
        if not hasattr(self, 'splitter'):
            return
        self._settings.setValue(_SETTINGS_KEY_SPLITTER, self.splitter.saveState())
        self._settings.setValue(
            _SETTINGS_KEY_COLLAPSED,
            [s for s, p in self._panels.items() if p.is_collapsed],
        )

    def _restore_layout(self) -> None:
        """Re-apply last-session collapsed zones, then splitter geometry."""
        saved = self._settings.value(_SETTINGS_KEY_COLLAPSED, []) or []
        for s, p in self._panels.items():
            if s in saved:
                p.set_collapsed(True)
        state = self._settings.value(_SETTINGS_KEY_SPLITTER)
        if state is not None:
            self.splitter.restoreState(state)

    # ── Global search (Ctrl+F) ────────────────────────────────────────────────

    def _build_search_bar(self) -> None:
        self._search_open = False
        self._search_matches: list = []     # [(display, start, end), …] in zone order
        self._search_idx = -1

        self._search_bar = QFrame()
        self._search_bar.setVisible(False)
        row = QHBoxLayout(self._search_bar)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)

        icon = QLabel("🔍")
        icon.setStyleSheet("font-size: 12px;")

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(lambda: self._run_search(reset=True))

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(
            QApplication.translate("tilauscope_beancave", "search all zones…")
        )
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']}; "
            f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 3px 8px; "
            f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        self._search_edit.textChanged.connect(lambda: self._search_debounce.start())
        self._search_edit.returnPressed.connect(self._search_next)

        self._search_count = QLabel("0/0")
        self._search_count.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-family: 'JetBrains Mono'; font-size: 11px;"
        )

        def _nav_btn(glyph: str, slot) -> QToolButton:
            b = QToolButton()
            b.setAutoRaise(True)
            b.setText(glyph)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QToolButton {{ color: {THEME['SUBTEXT']}; border: none; font-size: 14px; }}"
                f"QToolButton:hover {{ color: {THEME['ACCENT']}; }}"
            )
            b.clicked.connect(slot)
            return b

        prev_btn = _nav_btn("‹", self._search_prev)
        next_btn = _nav_btn("›", self._search_next)
        close_btn = _nav_btn("✕", self._close_search)

        row.addWidget(icon)
        row.addWidget(self._search_edit, 1)
        row.addWidget(self._search_count)
        row.addWidget(prev_btn)
        row.addWidget(next_btn)
        row.addWidget(close_btn)

        # Ctrl+F opens the bar from anywhere in the window.
        self._find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self._find_shortcut.activated.connect(self._open_search)

    def _open_search(self) -> None:
        self._search_open = True
        self._search_bar.setVisible(True)
        self._search_edit.setFocus()
        self._search_edit.selectAll()
        if self._search_edit.text():
            self._run_search(reset=True)

    def _close_search(self) -> None:
        self._search_open = False
        self._search_bar.setVisible(False)
        self._clear_search_highlights()
        self._search_matches = []
        self._search_idx = -1

    def _clear_search_highlights(self) -> None:
        for panel in self._panels.values():
            panel.display.setExtraSelections([])

    @staticmethod
    def _collect_matches(display: QPlainTextEdit, text: str) -> list:
        """Return [(start, end), …] of all occurrences in the display."""
        out: list = []
        doc = display.document()
        cur = QTextCursor(doc)
        while True:
            cur = doc.find(text, cur)   # case-insensitive by default
            if cur.isNull():
                break
            out.append((cur.selectionStart(), cur.selectionEnd()))
        return out

    def _run_search(self, advance: int = 0, reset: bool = False) -> None:
        """Re-scan all zones (robust against live drift), highlight, navigate."""
        text = self._search_edit.text()
        self._clear_search_highlights()
        self._search_matches = []
        if text:
            for panel in self._panels.values():
                d = panel.display
                for (s, e) in self._collect_matches(d, text):
                    self._search_matches.append((d, s, e))

        n = len(self._search_matches)
        if n == 0:
            self._search_idx = -1
            self._search_count.setText("0/0")
            return

        if reset or self._search_idx < 0:
            self._search_idx = 0
        else:
            self._search_idx = (self._search_idx + advance) % n

        self._apply_search_highlights()
        self._goto_current_match()
        self._search_count.setText(f"{self._search_idx + 1}/{n}")

    def _apply_search_highlights(self) -> None:
        per: dict = {}
        for idx, (d, s, e) in enumerate(self._search_matches):
            sel = QTextEdit.ExtraSelection()
            c = QTextCursor(d.document())
            c.setPosition(s)
            c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c
            fmt = QTextCharFormat()
            fmt.setBackground(_SEARCH_CUR if idx == self._search_idx else _SEARCH_HL)
            sel.format = fmt
            per.setdefault(d, []).append(sel)
        for panel in self._panels.values():
            panel.display.setExtraSelections(per.get(panel.display, []))

    def _goto_current_match(self) -> None:
        d, s, e = self._search_matches[self._search_idx]
        c = QTextCursor(d.document())
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        d.setTextCursor(c)
        d.ensureCursorVisible()

    def _search_next(self) -> None:
        self._run_search(advance=1)

    def _search_prev(self) -> None:
        self._run_search(advance=-1)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Card shell
        card = QFrame()
        card.setObjectName("loggerCard")
        card.setStyleSheet(f"""
            QFrame#loggerCard {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 20px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 16)
        card_layout.setSpacing(10)
        outer.addWidget(card)

        # ── Title bar ─────────────────────────────────────────────────────
        title_row = QHBoxLayout()

        title_lbl = QLabel(
            QApplication.translate("tilauscope_beancave", "TILAU DEBUG MONITOR")
        )
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: 800; "
            f"font-family: 'JetBrains Mono'; letter-spacing: 3px;"
        )

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #313244;
                color: #f38ba8;
                border-radius: 15px;
                border: 1px solid #f38ba8;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #f38ba8;
                color: #1e1e2e;
            }
        """)
        close_btn.clicked.connect(self.close)

        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        card_layout.addLayout(title_row)
        card_layout.addWidget(_separator())

        # ── Global search bar (Ctrl+F; hidden until invoked) ───────────────
        self._build_search_bar()
        card_layout.addWidget(self._search_bar)

        # ── Controls row ──────────────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        port_lbl = QLabel(
            QApplication.translate("tilauscope_beancave", "Serial port:")
        )
        port_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")

        self.port_selector = QComboBox()
        self.port_selector.setFixedWidth(180)
        # Signal connected later in __init__ after ser_worker is ready
        self.refresh_ports()

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setToolTip(
            QApplication.translate("tilauscope_beancave", "Refresh port list")
        )
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {THEME['ACCENT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{ border-color: {THEME['ACCENT']}; background: {THEME['SURFACE']}; }}
        """)
        refresh_btn.clicked.connect(self.refresh_ports)

        # ## TILAU ## — baud rate selector
        baud_lbl = QLabel(
            QApplication.translate("tilauscope_beancave", "Baud:")
        )
        baud_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")

        self.baud_selector = QComboBox()
        self.baud_selector.setFixedWidth(100)
        for rate in BAUD_RATES:
            self.baud_selector.addItem(str(rate), rate)
        # Restore saved baud or fall back to default
        saved_baud = self._settings.value(_SETTINGS_KEY_BAUD, _DEFAULT_BAUD, type=int)
        idx = self.baud_selector.findData(saved_baud)
        self.baud_selector.setCurrentIndex(idx if idx >= 0 else self.baud_selector.findData(_DEFAULT_BAUD))

        # ## TILAU ## — explicit connect/disconnect button
        self._connected = False
        self.connect_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "Connect")
        )
        self.connect_btn.setFixedHeight(30)
        self.connect_btn.setCheckable(True)
        self.connect_btn.clicked.connect(self._on_connect_toggle)
        self._apply_connect_btn_style(connected=False)

        # ## TILAU ## — manual/repeatable TRP probe (spec /TRP/specifications.md Sec4/Sec19):
        # sends "HELLO TRP/1.0" and, once INFO.../OK come back, the status label
        # switches from the plain "connected" text to the identified TRP device/profile.
        self.trp_hello_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "🤝 HELLO")
        )
        self.trp_hello_btn.setFixedHeight(30)
        self.trp_hello_btn.setToolTip(
            QApplication.translate("tilauscope_beancave",
                "Send the TRP handshake (HELLO TRP/1.0) and detect the connected roaster")
        )
        self.trp_hello_btn.clicked.connect(self._send_trp_hello)
        self._trp_probe_active = False
        self._trp_identity = None
        self._trp_roaster_context = None
        # Initial state — refined on each connect in handle_serial_msg() since
        # the Meter/Extra Device config can change while this window is open.
        self.trp_hello_btn.setEnabled(self._trp_device_configured())

        # ## TILAU ## — serial controls move into the ESP32 zone header (extra_header).
        # The live serial status is the ESP32 panel's own label → no top-bar duplicate.
        self._serial_ctrls = [port_lbl, self.port_selector, refresh_btn,
                              baud_lbl, self.baud_selector, self.connect_btn, self.trp_hello_btn]

        # ## TILAU ## — observability actions (left side of the top bar)
        def _action(glyph: str, tip: str, slot) -> QToolButton:
            b = QToolButton()
            b.setText(glyph)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(QApplication.translate("tilauscope_beancave", tip))
            b.setStyleSheet(
                f"QToolButton {{ color: {THEME['TEXT']}; background: {THEME['SURFACE']}; "
                f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; "
                f"padding: 4px 8px; font-size: 13px; }}"
                f"QToolButton:hover {{ border-color: {THEME['ACCENT']}; }}"
                f"QToolButton:checked {{ color: {THEME['TODAY']}; border-color: {THEME['TODAY']}; }}"
            )
            b.clicked.connect(slot)  # PyQt truncates the emitted 'checked' arg
            ctrl_row.addWidget(b)
            return b

        _action("📌", "Insert marker in all zones", self._insert_marker)
        self._pause_btn = _action("⏸", "Pause / resume rendering", self._toggle_pause)
        self._pause_btn.setCheckable(True)
        _action("💾", "Save snapshot to file", self._take_snapshot)
        _action("♻", "Run garbage collection now", self._gc_now)

        ctrl_row.addStretch()

        # Debug toggle button
        self.debug_btn = QPushButton()
        self.debug_btn.setCheckable(True)
        self.debug_btn.setFixedHeight(30)
        self.debug_btn.clicked.connect(self.toggle_debug_level)

        self.debug_status = QLabel()
        self.debug_status.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")

        ctrl_row.addWidget(self.debug_status)
        ctrl_row.addWidget(self.debug_btn)
        card_layout.addLayout(ctrl_row)
        card_layout.addWidget(_separator())

        self._refresh_debug_ui()

        # ── System observability dashboard (collapsible, top of content) ───
        self.dashboard = SystemDashboard()
        self.dashboard.toggled.connect(self._on_dashboard_toggled)
        card_layout.addWidget(self.dashboard)
        card_layout.addWidget(_separator())

        # ── Log zones (splitter: draggable, collapsible, focusable) ────────
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {THEME['BORDER']}; border-radius: 3px; }}"
        )

        def _register(source: str, panel: 'ZonePanel',
                      file_logger, ring_cap: int, color: str) -> 'ZonePanel':
            panel.focus_requested.connect(self._on_focus_requested)
            panel.collapsed_changed.connect(self._save_layout)
            self.splitter.addWidget(panel)
            self._panels[source] = panel
            zone = LogZone(
                panel.display, panel.status, file_logger, ring_cap, color
            )
            self._zones[source] = zone
            # Filter UI → LogZone re-render; regex validity → field feedback.
            panel.filter_changed.connect(
                lambda state, z=zone, p=panel: p.set_filter_valid(z.set_filter(state))
            )
            return panel

        # Serial flow — serial controls hosted in this zone's header. Title
        # reflects whichever kind of serial device is actually configured
        # (## TILAU ## re-evaluated on each connect, see handle_serial_msg).
        self.serial_panel = _register(
            "serial",
            ZonePanel(self._serial_zone_title(),
                      THEME['SUCCESS'],
                      QApplication.translate("tilauscope_beancave", "⚫ inactive"),
                      extra_header=self._serial_ctrls),
            self.serial_logger, _LIVE_MAX_LINES, THEME['SUCCESS'],
        )
        self.serial_display = self.serial_panel.display
        self.serial_status = self.serial_panel.status

        # Application TCP flow
        self.tcp_panel = _register(
            "tcp",
            ZonePanel(QApplication.translate("tilauscope_beancave", "APPLICATION FLOW  (TCP)"),
                      THEME['ACCENT'],
                      QApplication.translate("tilauscope_beancave", "⚫ inactive")),
            self.tcp_logger, _LIVE_MAX_LINES, THEME['ACCENT'],
        )
        self.tcp_display = self.tcp_panel.display
        self.tcp_status = self.tcp_panel.status

        # Artisan log tail — Start/Stop button hosted in the zone header
        self._tail_running = False
        self.tail_btn = QPushButton(
            QApplication.translate("tilauscope_beancave", "Start")
        )
        self.tail_btn.setFixedHeight(28)
        self.tail_btn.setCheckable(True)
        self.tail_btn.clicked.connect(self._on_tail_toggle)
        self._apply_tail_btn_style(running=False)

        self.tail_panel = _register(
            "tail",
            ZonePanel(QApplication.translate("tilauscope_beancave", "ARTISAN LOG  (tail)"),
                      THEME['WARNING'],
                      QApplication.translate("tilauscope_beancave", "⚫ inactive"),
                      extra_header=[self.tail_btn]),
            None, _TAIL_MAX_LINES, THEME['WARNING'],
        )
        self.artisan_display = self.tail_panel.display
        self.artisan_tail_status = self.tail_panel.status

        card_layout.addWidget(self.splitter, 1)

        # Resize grip
        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        card_layout.addLayout(grip_row)

    def setModal(self, modal: bool) -> None:  # type: ignore[override]
        """No-op — compatibility with main.py (Artisan QDialog pattern). Setup done in __init__."""
        self.setWindowModality(Qt.WindowModality.NonModal)

    def setup_file_loggers(self):
        """Initializes Python loggers to write to the Artisan log directory."""
        # 1. Safely find Artisan's log directory
        if _IS_WINDOWS:
            log_dir = Path(getDataDirectory()) / "tilauscope"
        else:
            log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "tilauscope"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir = log_dir  # ## TILAU ## — shared with tail worker
        ser_path = log_dir / f"tilau_serial_{datetime.now().strftime('%Y%m%d')}.log"
        tcp_path = log_dir / f"tilau_tcp_{datetime.now().strftime('%Y%m%d')}.log"
    
        # 2. Setup Serial File Logger
        self.serial_logger = logging.getLogger("tilau_serial_file")
        self.serial_logger.propagate = False # Prevent double-logging to console
        ser_fh = logging.FileHandler(ser_path, encoding='utf-8')
        ser_fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.serial_logger.addHandler(ser_fh)
        self.serial_logger.setLevel(logging.INFO)

        # 3. Setup TCP File Logger
        self.tcp_logger = logging.getLogger("tilau_tcp_file")
        self.tcp_logger.propagate = False
        tcp_fh = logging.FileHandler(tcp_path, encoding='utf-8')
        tcp_fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.tcp_logger.addHandler(tcp_fh)
        self.tcp_logger.setLevel(logging.INFO)
        
        _log.info(f"Tilau logs initialized as {ser_path} and {tcp_path}")

    # ## TILAU ## — central dispatch: route a normalised event to its zone
    def _on_bus_event(self, ev: 'LogEvent') -> None:
        zone = self._zones.get(ev.source)
        if zone is not None:
            zone.append(ev)
            # Permanent cumulative error/exception counter on the zone header.
            if ev.level in ("ERROR", "CRITICAL"):
                panel = self._panels.get(ev.source)
                if panel is not None:
                    panel.set_error_count(zone.error_count)

    # ── Observability actions ─────────────────────────────────────────────────

    def _insert_marker(self, text: str | None = None) -> None:
        """Inject a timestamped marker line into every zone (bus-independent)."""
        ts_str = QDateTime.currentDateTime().toString("HH:mm:ss")
        label = text or f"─── 📌 marker {ts_str} ───"
        ev = LogEvent(source="marker", text=label, level="INFO")
        for zone in self._zones.values():
            zone.append(ev)

    def _toggle_pause(self) -> None:
        paused = self._pause_btn.isChecked()
        self._pause_btn.setText("▶" if paused else "⏸")
        for zone in self._zones.values():
            zone.set_paused(paused)

    def _gc_now(self) -> None:
        collected = gc.collect()
        self._insert_marker(f"─── ♻ GC collected {collected} objects ───")
        _log.info("manual GC: collected %d objects", collected)

    def _take_snapshot(self) -> None:
        """Dump recent buffers + a quick metrics read to a timestamped file."""
        stamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        out_dir = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"tilau_snapshot_{stamp}.txt"
        try:
            proc = psutil.Process()
            with path.open("w", encoding="utf-8") as fh:
                fh.write(f"TilauScope debug snapshot — {stamp}\n")
                fh.write(f"mem(uss)={bytes2human(getattr(proc.memory_full_info(),'uss',0))} "
                         f"threads={proc.num_threads()} "
                         f"gc={gc.get_count()}\n\n")
                for src, zone in self._zones.items():
                    fh.write(f"===== {src}  (events={zone.count}, errors={zone.error_count}) =====\n")
                    for ev in zone.recent(300):
                        ts_str = QDateTime.fromSecsSinceEpoch(int(ev.ts)).toString("HH:mm:ss")
                        mod = f"({ev.module}) " if ev.module else ""
                        fh.write(f"[{ts_str}] {ev.level} {mod}{ev.text}\n")
                    fh.write("\n")
            self._insert_marker(f"─── 💾 snapshot saved: {path.name} ───")
            _log.info("snapshot written to %s", path)
        except Exception as exc:
            _log.error("snapshot failed: %s", exc)

    def _serial_zone_title(self) -> str:
        """## TILAU ## "TRP FLOW (Serial)" when a TRP device is configured as
        the Meter or an Extra Device, "ESP32 FLOW (Serial)" otherwise (the
        historical default for the non-TRP serial boards this panel was
        built for)."""
        if self._trp_device_configured():
            return QApplication.translate("tilauscope_beancave", "TRP FLOW  (Serial)")
        return QApplication.translate("tilauscope_beancave", "ESP32 FLOW  (Serial)")

    def _trp_device_configured(self) -> bool:
        """## TILAU ## True only if the currently configured Meter (main
        device) or an Extra Device is actually a TRP device (spec Sec19) --
        the HELLO probe only makes sense when TRP is what's actually wired
        up in Artisan's Device config, not for arbitrary serial gear being
        watched through this logger."""
        try:
            trp_ids = {d["id"] for d in self.aw.qmc.tilau_devices.values()
                       if d["label"].startswith("TRP ")}
            return (self.aw.qmc.device in trp_ids
                    or any(d in trp_ids for d in self.aw.qmc.extradevices))
        except Exception:  # pylint: disable=broad-except
            return False

    def handle_serial_msg(self, msg):
        # Status messages drive the connection label/button; data lines flow on.
        if msg.startswith("✅"):
            self.serial_status.setText(self._tr_ser_connected)
            self.serial_status.setStyleSheet(f"color: {THEME['SUCCESS']}; font-size: 12px; margin-left: 8px;")
            trp_configured = self._trp_device_configured()
            self.serial_panel.set_title(self._serial_zone_title())
            self.trp_hello_btn.setEnabled(trp_configured)
            self.trp_hello_btn.setToolTip(
                QApplication.translate("tilauscope_beancave",
                    "Send the TRP handshake (HELLO TRP/1.0) and detect the connected roaster")
                if trp_configured else
                QApplication.translate("tilauscope_beancave",
                    "Set the Meter or an Extra Device to a TRP Roaster device to enable this probe")
            )
            if trp_configured:
                # ## TILAU ## auto-probe: give the port a moment to settle (mirrors
                # SerialWorker's own 0.1s post-open delay) then send HELLO once.
                QTimer.singleShot(300, self._send_trp_hello)
        elif msg.startswith("❌"):
            # Reset button state on open failure
            self._connected = False
            self.connect_btn.setChecked(False)
            self._apply_connect_btn_style(connected=False)
            self.serial_status.setText(self._tr_ser_error)
            self.serial_status.setStyleSheet(f"color: {THEME['CRITICAL']}; font-size: 12px; margin-left: 8px;")
            self._reset_trp_identity()
        elif msg.startswith("🔌"):
            self.serial_status.setText(self._tr_ser_inactive)
            self.serial_status.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; margin-left: 8px;")
            self._reset_trp_identity()
        elif msg.startswith("🔄"):
            self.serial_status.setText(self._tr_ser_connecting)
            self.serial_status.setStyleSheet(f"color: {THEME['TODAY']}; font-size: 12px; margin-left: 8px;")
            self._reset_trp_identity()
        elif self._trp_probe_active:
            self._handle_trp_probe_line(msg)
        # Publish to the bus — zone handles display, colour, file + roast flush.
        self.bus.emit_line("serial", msg, level=_infer_level(msg))

    def _send_trp_hello(self) -> None:
        """## TILAU ## Manual/auto TRP probe (spec Sec4/Sec19): send HELLO and
        arm identity parsing for the INFO/OK lines that should follow."""
        if not self._connected or not self._trp_device_configured():
            return
        self._trp_probe_active = True
        self._trp_identity = None
        self._trp_roaster_context = None
        if self.ser_worker.send_line("HELLO TRP/1.0"):
            self.bus.emit_line("serial", "→ HELLO TRP/1.0", level="INFO")

    def _reset_trp_identity(self) -> None:
        self._trp_probe_active = False
        self._trp_identity = None
        self._trp_roaster_context = None

    def _handle_trp_probe_line(self, line: str) -> None:
        """## TILAU ## Parse INFO/OK/ERR lines following a HELLO probe (spec
        Sec4/Sec19) and, once identified, surface the device/profile on the
        serial zone's status label to make TRP detection visible at a glance."""
        from tilauscope.trp_client import TRPIdentity, resolve_roaster
        tag, _, remainder = line.partition(' ')
        tag = tag.upper()
        if tag == 'INFO':
            if self._trp_identity is None:
                self._trp_identity = TRPIdentity()
            self._trp_identity.update_from_info(remainder)
        elif tag == 'OK' and self._trp_identity is not None:
            self._trp_probe_active = False
            self._trp_roaster_context = resolve_roaster(self._trp_identity)
            profile = self._trp_roaster_context.display_name if self._trp_roaster_context else "generic"
            self.serial_status.setText(
                f"🟢 TRP  {self._trp_identity.device or '?'} — {profile}  "
                f"CAPS={','.join(sorted(self._trp_identity.caps))}"
            )
            self.serial_status.setStyleSheet(f"color: {THEME['SUCCESS']}; font-size: 12px; margin-left: 8px;")
        elif tag == 'ERR':
            # Not a TRP device (or the firmware rejected HELLO) — stop probing
            # and leave the plain "connected" status in place.
            self._trp_probe_active = False
            self._trp_identity = None

    def handle_tcp_msg(self, name: str, level: str, msg: str):
        """Bridge structured TCP record onto the bus (keeps level + module)."""
        self.bus.emit_line("tcp", msg, level=level, module=name)
        if self.tcp_status.toolTip() != "active":
            self.tcp_status.setText(self._tr_tcp_receiving)
            self.tcp_status.setStyleSheet(f"color: {THEME['SUCCESS']}; font-size: 12px; margin-left: 8px;")
            self.tcp_status.setToolTip("active")

    def flush_all_logs(self):
        """Centralized flush triggered by QTimer — iterate registered zones."""
        for zone in self._zones.values():
            zone.flush()

    def start_tcp_thread(self):
        if self.tcp_server is not None:
            return

        self._tcp_ready = threading.Event()

        def run_tcp():
            try:
                server = TCPWorker(signal=self.tcp_signal)
                self.tcp_server = server          # assignation atomique avant serve_forever
                self._tcp_ready.set()             # signal : tcp_server est valide
                server.serve_forever()            # bloque jusqu'a shutdown()
            except Exception as e:
                _log.error(f"Erreur TCP: {e}")
                self._tcp_ready.set()             # debloque closeEvent meme en cas d erreur
            finally:
                if self.tcp_server:
                    try:
                        self.tcp_server.server_close()
                    except Exception:
                        pass
                self.tcp_server = None

        self.tcp_thread = threading.Thread(target=run_tcp, daemon=True, name="TilauTCP")
        self.tcp_thread.start()
        # Attente courte pour que tcp_server soit assigne avant tout acces externe
        self._tcp_ready.wait(timeout=2.0)

    def closeEvent(self, event):
        _log.info("Tilaulogger closing: Shutting down workers...")

        # ## TILAU ## — persist splitter geometry + collapsed zones
        self._save_layout()

        # ## TILAU ## — stop metrics sampling
        if hasattr(self, '_collector'):
            self._collector.stop()

        # 0. Arret du flush timer pour eviter appels post-fermeture
        if hasattr(self, 'flush_timer'):
            self.flush_timer.stop()

        # 1. Flush avant fermeture
        self.flush_all_logs()

        # 2. Stop Serial Worker
        if hasattr(self, 'ser_worker'):
            self.ser_worker.stop()

        # ## TILAU ## — stop tail worker (QTimer-based, no thread join needed)
        if hasattr(self, '_tail_worker'):
            self._tail_worker.stop()

        # 3. Shutdown TCP Server — synchrone, borne a 2s
        #    _tcp_ready garantit que tcp_server est assigne ou None (pas d'etat intermediaire)
        if hasattr(self, '_tcp_ready'):
            self._tcp_ready.wait(timeout=2.0)
        if hasattr(self, 'tcp_server') and self.tcp_server:
            try:
                self.tcp_server.running = False   # signal aux handlers d'arreter leur boucle
                self.tcp_server.shutdown()        # bloque jusqu'a la fin de serve_forever()
                # server_close() est appele dans le finally de run_tcp
            except Exception as e:
                _log.error(f"Error stopping TCP server: {e}")

        # 4. Join des threads avec timeout borne
        try:
            if hasattr(self, 'ser_thread') and self.ser_thread.is_alive():
                self.ser_thread.join(timeout=1.0)
            if hasattr(self, 'tcp_thread') and self.tcp_thread is not None and self.tcp_thread.is_alive():
                self.tcp_thread.join(timeout=2.0)
                if self.tcp_thread.is_alive():
                    _log.warning("TCP thread did not terminate cleanly within timeout")
        except Exception as e:
            _log.error(f"Error joining threads: {e}")

        # uncheck menu item
        self.aw.tilaudebug.setChecked(False)

        event.accept()
        self.deleteLater()
        
    def stop_all_workers(self):
        """Refined stop method to ensure the port is freed."""
        if hasattr(self, 'ser_worker'):
            self.ser_worker.stop()
        if self.tcp_server:
            self.tcp_server.shutdown()
            self.tcp_server.server_close()
            self.tcp_server = None
        _log.info("Tilauscope workers stopped.")   

    def oldcloseEvent(self, event):
        if hasattr(self, 'aw') and hasattr(self.aw, 'qmc'):
            if self.aw.qmc.flagstart or self.aw.qmc.flagon:
                self.hide() 
                event.ignore()
                return
        try:
            self.ser_worker.signal.disconnect()
        except:
            pass

        self.ser_worker.stop()
        self.ser_thread.quit()
        if not self.ser_thread.wait(1000): # Attend 1 sec max
            self.ser_thread.terminate() # Force l'arrêt si bloqué
        
        if hasattr(self, 'tcp_server') and self.tcp_server:
            self.tcp_server.shutdown() # Arrête le serve_forever()
            self.tcp_server.server_close()

        event.accept()
        # Forces Qt to delete this object and release the 'aw' reference
        self.deleteLater()

    def toggle_debug_level(self) -> None:
        debugLogLevelToggle()
        self._refresh_debug_ui()

    def _refresh_debug_ui(self) -> None:
        active = debugLogLevelActive()
        self.debug_btn.setChecked(active)
        if active:
            self.debug_btn.setText(QApplication.translate("tilauscope_beancave", "🔴 DEBUG ON"))
            self.debug_btn.setStyleSheet(
                f"QPushButton {{ background-color: {THEME['CRITICAL']}; color: {THEME['BG']}; "
                f"font-weight: bold; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
            )
            self.debug_status.setText(
                QApplication.translate("tilauscope_beancave", "all modules at DEBUG level")
            )
            self.debug_status.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 12px;"
            )
        else:
            self.debug_btn.setText(QApplication.translate("tilauscope_beancave", "⚪ DEBUG OFF"))
            self.debug_btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {THEME['SUBTEXT']}; "
                f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; color: {THEME['ACCENT']}; }}"
            )
            self.debug_status.setText(
                QApplication.translate("tilauscope_beancave", "INFO level (normal)")
            )
            self.debug_status.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 12px;"
            )

    def _apply_connect_btn_style(self, connected: bool) -> None:
        """Update connect button appearance to reflect current state."""
        if connected:
            self.connect_btn.setText(
                QApplication.translate("tilauscope_beancave", "Disconnect")
            )
            self.connect_btn.setStyleSheet(
                f"QPushButton {{ background-color: {THEME['CRITICAL']}; color: {THEME['BG']}; "
                f"font-weight: bold; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: #ff9999; }}"
            )
        else:
            self.connect_btn.setText(
                QApplication.translate("tilauscope_beancave", "Connect")
            )
            self.connect_btn.setStyleSheet(
                f"QPushButton {{ background-color: {THEME['SUCCESS']}; color: {THEME['BG']}; "
                f"font-weight: bold; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: #aaffaa; }}"
            )

    def _on_connect_toggle(self) -> None:
        """Handle Connect/Disconnect button press."""
        if not self._connected:
            port = self.port_selector.currentText()
            baud = self.baud_selector.currentData()
            if not port:
                return
            # Persist selection before attempting connection
            self._settings.setValue(_SETTINGS_KEY_PORT, port)
            self._settings.setValue(_SETTINGS_KEY_BAUD, baud)
            self._connected = True
            self._apply_connect_btn_style(connected=True)
            self.ser_worker.connect_port(port, baud)
        else:
            self._connected = False
            self._apply_connect_btn_style(connected=False)
            self.ser_worker.disconnect_port()

    # ## TILAU ## — artisan.log tail controls

    def _apply_tail_btn_style(self, running: bool) -> None:
        """Update tail Start/Stop button appearance."""
        if running:
            self.tail_btn.setText(
                QApplication.translate("tilauscope_beancave", "Stop")
            )
            self.tail_btn.setStyleSheet(
                f"QPushButton {{ background-color: {THEME['CRITICAL']}; color: {THEME['BG']}; "
                f"font-weight: bold; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: #ff9999; }}"
            )
        else:
            self.tail_btn.setText(
                QApplication.translate("tilauscope_beancave", "Start")
            )
            self.tail_btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {THEME['SUBTEXT']}; "
                f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 4px 14px; "
                f"font-family: 'JetBrains Mono'; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; color: {THEME['ACCENT']}; }}"
            )

    def _on_tail_toggle(self) -> None:
        """Start or stop the artisan.log tail."""
        if not self._tail_running:
            self._tail_running = True
            self._apply_tail_btn_style(running=True)
            self._tail_worker.start()
        else:
            self._tail_running = False
            self._apply_tail_btn_style(running=False)
            self._tail_worker.stop()

    def _on_tail_lines(self, lines: list) -> None:
        """Publish each new artisan.log line onto the bus."""
        for line in lines:
            self.bus.emit_line("tail", line, level=_infer_level(line))

    def _on_tail_status(self, status: str) -> None:
        """Relay worker status to the UI label."""
        self.artisan_tail_status.setText(status)
        if "🟢" in status:
            self.artisan_tail_status.setStyleSheet(
                f"color: {THEME['SUCCESS']}; font-size: 12px; margin-left: 8px;"
            )
        elif "🔴" in status:
            self.artisan_tail_status.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 12px; margin-left: 8px;"
            )
        else:
            self.artisan_tail_status.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 12px; margin-left: 8px;"
            )

    def refresh_ports(self):
        """Detect the serial ports available on the machine."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_selector.clear()
        self.port_selector.addItems(ports)
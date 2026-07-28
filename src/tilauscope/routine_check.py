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

# routine check — v2 (architecture fixes + redesigned UI)
import json
import logging
import ast
from pathlib import Path
from typing import Final

_ALOG_MAX_BYTES: Final[int] = 2 * 1024 * 1024  # 2 MB safety cap

from PyQt6.QtCore import (
    Qt, QDateTime, QObject, pyqtSignal, QThread,
    pyqtSlot, QSettings, QTimer, QPropertyAnimation,
    QEasingCurve, QEvent,
)
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QApplication, QPushButton,
    QWidget, QProgressBar, QDialog, QSizePolicy,
    QScrollArea,
)

from tilauscope.tilauscope_types import THEME, show_styled_message
## TILAU ## reuse Artisan's canonical weight helpers as single source of truth
from artisanlib.util import weight_units, convertWeight, decodeLocalStrict

_log: Final[logging.Logger] = logging.getLogger(__name__)

def _make_divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {THEME['BORDER']}; border: none;")
    return line

def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Linear interpolation between two #RRGGBB hex colors."""
    def h(c): return (int(c[1:3],16), int(c[3:5],16), int(c[5:7],16))
    r1,g1,b1 = h(c1); r2,g2,b2 = h(c2)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1 + (r2-r1)*t), int(g1 + (g2-g1)*t), int(b1 + (b2-b1)*t)
    )

def _usage_bar_color(ratio: float) -> str:
    """
    0–50 % → ACCENT (blue)
    50–80 % → ACCENT → WARNING (orange)
    80–100 %+ → WARNING → CRITICAL (red)
    """
    if ratio <= 0.5:
        return THEME["ACCENT"]
    elif ratio <= 0.8:
        t = (ratio - 0.5) / 0.3
        return _lerp_color(THEME["ACCENT"], THEME["WARNING"], t)
    else:
        t = min((ratio - 0.8) / 0.2, 1.0)
        return _lerp_color(THEME["WARNING"], THEME["CRITICAL"], t)


class _StatCard(QFrame):
    """Small metric tile: label on top, value below."""

    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 8px; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._label = QLabel(label.upper())
        self._label.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
            " letter-spacing: 1px; border: none;"
        )
        self._value = QLabel(value)
        self._value.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 15px; font-weight: bold;"
            " font-family: 'JetBrains Mono'; border: none;"
        )
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

class _MiniBar(QFrame):
    """Proportional horizontal fill bar that tracks its own width on resize."""

    def __init__(self, ratio: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._ratio = max(0.0, min(ratio, 1.0))
        self.setFixedHeight(4)
        self.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 2px; border: none; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._fill = QFrame(self)
        self._fill.setFixedHeight(4)
        self._fill.setStyleSheet(
            f"QFrame {{ background: {THEME['ACCENT']}; border-radius: 2px; border: none; }}"
        )

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self._fill.setFixedWidth(int(self.width() * self._ratio))
        super().resizeEvent(event)


class _RoastRow(QWidget):
    """One line: date | mini-bar | weight."""

    def __init__(self, date_str: str, weight_kg: float, max_kg: float,
                 parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        date_lbl = QLabel(date_str)
        date_lbl.setFixedWidth(90)
        date_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px;"
            " font-family: 'JetBrains Mono'; border: none;"
        )

        ratio = (weight_kg / max_kg) if max_kg > 0 else 0.0
        bar_bg = _MiniBar(ratio)

        weight_lbl = QLabel(f"{weight_kg:.2f} kg")
        weight_lbl.setFixedWidth(58)
        weight_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        weight_lbl.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 11px; font-weight: bold;"
            " font-family: 'JetBrains Mono'; border: none;"
        )

        layout.addWidget(date_lbl)
        layout.addWidget(bar_bg)
        layout.addWidget(weight_lbl)

class TilauRoutineCheck(QDialog):

    def __init__(self, parent: QWidget, aw=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # ── State ──────────────────────────────
        self.settings = QSettings()
        self.alog_directory: str = self.settings.value("alogDirectory", "", str)
        self.cleaning_threshold: int = 60
        self._countdown_ms: int = 10_000          # 10 s auto-close
        self._countdown_total: int = self._countdown_ms
        self._timer: QTimer | None = None
        self._anim: QPropertyAnimation | None = None
        self._closing: bool = False               # guard double fade-out

        raw = self.settings.value("lastCleaningDate", QDateTime(2000, 1, 1, 0, 0))
        if isinstance(raw, str):
            self.last_clean = QDateTime.fromString(raw, Qt.DateFormat.ISODate)
            if not self.last_clean.isValid():
                self.last_clean = QDateTime(2000, 1, 1, 0, 0)
        else:
            self.last_clean = raw  # type: ignore[assignment]

        # ── Thread placeholders ────────────────
        self._thread: QThread | None = None
        self._worker: "AlogScanner | None" = None

        self._setup_ui()
        self._start_async_scan()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._container = QFrame()
        self._container.setStyleSheet(
            f"QFrame {{ background-color: {THEME['BG']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 20px; }}"
        )
        self._content = QVBoxLayout(self._container)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(0)
        outer.addWidget(self._container)

        self._build_header()
        self._content.addWidget(_make_divider())
        self._build_cycle_section()
        self._content.addWidget(_make_divider())
        self._build_stats_section()
        self._content.addWidget(_make_divider())
        self._build_history_section()
        self._content.addWidget(_make_divider())
        self._build_actions()
        self._build_countdown_strip()

        self.resize(460, 520)

    def _section_padding(self) -> dict:
        return {"left": 20, "top": 14, "right": 20, "bottom": 14}

    def _build_header(self) -> None:
        w = QWidget()
        row = QHBoxLayout(w)
        p = self._section_padding()
        row.setContentsMargins(p["left"], 14, p["right"], 14)

        title = QLabel("🧹 " + QApplication.translate("tilauscope_beancave","ROUTINE CHECK"))
        title.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 14px; font-weight: bold;"
            " font-family: 'JetBrains Mono'; letter-spacing: 1px; border: none;"
        )

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.clicked.connect(self.fade_out_and_close)
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {THEME['SUBTEXT']};"
            f" border-radius: 14px; border: 1px solid {THEME['BORDER']}; font-size: 11px; }}"
            f"QPushButton:hover {{ color: {THEME['TEXT']}; }}"
        )

        row.addWidget(title)
        row.addStretch()
        row.addWidget(self._close_btn)
        self._content.addWidget(w)

    def _build_cycle_section(self) -> None:
        """Jauge de cycle + date du dernier nettoyage."""
        w = QWidget()
        p = self._section_padding()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(p["left"], p["top"], p["right"], p["bottom"])
        layout.setSpacing(8)

        # Top row: label left / counter right
        top = QHBoxLayout()
        cycle_label = QLabel(QApplication.translate("tilauscope_beancave","Cleaning cycle").upper())
        cycle_label.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
            " letter-spacing: 1px; border: none;"
        )

        self._cycle_counter = QLabel(f"— / {self.cleaning_threshold}")
        self._cycle_counter.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 20px; font-weight: bold;"
            " font-family: 'JetBrains Mono'; border: none;"
        )
        self._cycle_counter.setAlignment(Qt.AlignmentFlag.AlignRight)

        top.addWidget(cycle_label, alignment=Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        top.addWidget(self._cycle_counter)
        layout.addLayout(top)

        # Progress bar
        self._usage_bar = QProgressBar()
        self._usage_bar.setMaximum(self.cleaning_threshold)
        self._usage_bar.setValue(0)
        self._usage_bar.setFixedHeight(8)
        self._usage_bar.setTextVisible(False)
        self._usage_bar.setStyleSheet(
            f"QProgressBar {{ background: {THEME['SURFACE']}; border-radius: 4px; border: none; }}"
            f"QProgressBar::chunk {{ background: {THEME['ACCENT']}; border-radius: 4px; }}"
        )
        layout.addWidget(self._usage_bar)

        # Tick marks
        ticks_row = QHBoxLayout()
        ticks_row.setSpacing(0)
        tick_values = [round(self.cleaning_threshold * f / 4) for f in range(5)]
        for i, val in enumerate(tick_values):
            lbl = QLabel(str(val))
            lbl.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
                " border: none;"
            )
            if i == 0:
                lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            elif i == len(tick_values) - 1:
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            else:
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ticks_row.addWidget(lbl, stretch=1)
        layout.addLayout(ticks_row)

        # Last clean date
        last_clean_str = self.last_clean.date().toString(Qt.DateFormat.ISODate)
        self._last_clean_lbl = QLabel(QApplication.translate("tilauscope_beancave","Last cleaning: ") + last_clean_str)
        self._last_clean_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 10px; font-family: 'JetBrains Mono';"
            " border: none;"
        )
        layout.addWidget(self._last_clean_lbl)

        self._content.addWidget(w)

    def _build_stats_section(self) -> None:
        """3 metric tiles: total weight · avg / roast · last roast date."""
        w = QWidget()
        p = self._section_padding()
        layout = QGridLayout(w)
        layout.setContentsMargins(p["left"], p["top"], p["right"], p["bottom"])
        layout.setSpacing(8)

        self._stat_total  = _StatCard(QApplication.translate("tilauscope_beancave","Total"))
        self._stat_avg    = _StatCard(QApplication.translate("tilauscope_beancave","Avg / roast"))
        self._stat_last   = _StatCard(QApplication.translate("tilauscope_beancave","Last roast"))

        layout.addWidget(self._stat_total, 0, 0)
        layout.addWidget(self._stat_avg,   0, 1)
        layout.addWidget(self._stat_last,  0, 2)

        self._content.addWidget(w)

    def _build_history_section(self) -> None:
        """Scrollable list of roast rows (date + proportional bar + weight)."""
        w = QWidget()
        p = self._section_padding()
        outer_layout = QVBoxLayout(w)
        outer_layout.setContentsMargins(p["left"], p["top"], p["right"], p["bottom"])
        outer_layout.setSpacing(6)

        section_lbl = QLabel(QApplication.translate("tilauscope_beancave","Recent roasts").upper())
        section_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 9px; font-family: 'JetBrains Mono';"
            " letter-spacing: 1px; border: none;"
        )
        outer_layout.addWidget(section_lbl)

        # Scroll area containing the rows
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setFixedHeight(150)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()

        self._scroll.setWidget(self._rows_container)
        self._user_scrolled: bool = False
        self._scroll.viewport().installEventFilter(self)
        outer_layout.addWidget(self._scroll)
 
        # Placeholder while scanning
        self._history_placeholder = QLabel(QApplication.translate("tilauscope_beancave","Scanning logs…"))
        self._history_placeholder.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-family: 'JetBrains Mono';"
            " border: none;"
        )
        self._rows_layout.insertWidget(0, self._history_placeholder)

        self._content.addWidget(w)

    def _build_actions(self) -> None:
        w = QWidget()
        p = self._section_padding()
        row = QHBoxLayout(w)
        row.setContentsMargins(p["left"], 12, p["right"], 12)
        row.setSpacing(10)

        self._clean_btn = QPushButton(QApplication.translate("tilauscope_beancave","MARK AS CLEANED"))
        self._clean_btn.setFixedHeight(38)
        self._clean_btn.clicked.connect(self.mark_as_cleaned)
        self._clean_btn.setStyleSheet(
            f"QPushButton {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
            f" border-radius: 8px; font-weight: bold; font-size: 11px;"
            f" font-family: 'JetBrains Mono'; letter-spacing: 1px; border: none; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )

        self._later_btn = QPushButton(QApplication.translate("tilauscope_beancave","Later").upper())
        self._later_btn.setFixedHeight(38)
        self._later_btn.clicked.connect(self.fade_out_and_close)
        self._later_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {THEME['SUBTEXT']};"
            f" border-radius: 8px; font-size: 11px; font-family: 'JetBrains Mono';"
            f" border: 1px solid {THEME['BORDER']}; }}"
            f"QPushButton:hover {{ color: {THEME['TEXT']}; }}"
        )

        row.addWidget(self._clean_btn, stretch=3)
        row.addWidget(self._later_btn, stretch=1)
        self._content.addWidget(w)

    def _build_countdown_strip(self) -> None:
        self._countdown_bar = QProgressBar()
        self._countdown_bar.setRange(0, self._countdown_total)
        self._countdown_bar.setValue(self._countdown_total)
        self._countdown_bar.setFixedHeight(3)
        self._countdown_bar.setTextVisible(False)
        self._countdown_bar.setStyleSheet(
            f"QProgressBar {{ background: transparent; border: none; }}"
            f"QProgressBar::chunk {{ background: {THEME['BORDER']}; }}"
        )
        self._content.addWidget(self._countdown_bar)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if not self._user_scrolled:
                self._freeze_countdown()
        return super().eventFilter(obj, event)

    def _freeze_countdown(self) -> None:
        """Stop auto-close — user is interacting with the scroll list."""
        self._user_scrolled = True
        if self._timer:
            self._timer.stop()
        self._countdown_bar.setValue(0)
        self._countdown_bar.setVisible(False)

    def _start_async_scan(self) -> None:
        self._thread = QThread(self)
        self._worker = AlogScanner(self.alog_directory, self.last_clean)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_scan_finished)
        # Worker and thread cleanup: quit the loop, delete both QObjects, and
        # drop our references so closeEvent never touches a deleted QThread.
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    @pyqtSlot(object, int)
    def _on_scan_finished(self, data_list: list, count: int) -> None:
        if not data_list:
            self.fade_out_and_close()
            return

        # ── Sort by date descending ──
        data_list.sort(key=lambda x: x[0], reverse=True)

        total_weight_kg: float = sum(w * 0.001 for _, w in data_list)
        avg_weight_kg: float = total_weight_kg / count if count else 0.0
        last_dt: QDateTime = data_list[0][0]
        max_w_kg: float = max(w * 0.001 for _, w in data_list)

        # ── Cycle section ──
        self._cycle_counter.setText(f"{count} / {self.cleaning_threshold}")
        fill_val = min(count, self.cleaning_threshold)
        self._usage_bar.setValue(fill_val)

        bar_color = _usage_bar_color(fill_val / self.cleaning_threshold)
        self._usage_bar.setStyleSheet(
            f"QProgressBar {{ background: {THEME['SURFACE']}; border-radius: 4px; border: none; }}"
            f"QProgressBar::chunk {{ background: {bar_color}; border-radius: 4px; }}"
        )

        # ── Stat cards ──
        self._stat_total.set_value(f"{total_weight_kg:.1f} kg")
        self._stat_avg.set_value(f"{avg_weight_kg * 1000:.0f} g")
        self._stat_last.set_value(last_dt.date().toString("dd MMM"))

        # ── History rows ──
        self._history_placeholder.hide()
        capped = data_list[:20]
        insert_idx = 0
        for i, (dt, weight_g) in enumerate(capped):
            date_str = dt.date().toString(Qt.DateFormat.ISODate)
            row = _RoastRow(date_str, weight_g * 0.001, max_w_kg)
            self._rows_layout.insertWidget(insert_idx, row)
            insert_idx += 1
            if i < len(capped) - 1:
                self._rows_layout.insertWidget(insert_idx, _make_divider())
                insert_idx += 1

        # ── Start auto-close countdown ──
        # Don't start it if the user already interacted (scrolled) during the scan.
        if not self._user_scrolled:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_countdown)
            self._timer.start(100)

    def _update_countdown(self) -> None:
        self._countdown_ms -= 100
        self._countdown_bar.setValue(max(0, self._countdown_ms))
        if self._countdown_ms <= 0:
            if self._timer:
                self._timer.stop()
            self.fade_out_and_close()

    def mark_as_cleaned(self) -> None:
        if self._timer:
            self._timer.stop()
        now = QDateTime.currentDateTime()
        self.settings.setValue("lastCleaningDate", now.toString(Qt.DateFormat.ISODate))
        show_styled_message(self, QApplication.translate("tilauscope_beancave","Success"), QApplication.translate("tilauscope_beancave","Cleaning cycle reset!"))
        self.fade_out_and_close()

    def fade_out_and_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._timer:
            self._timer.stop()
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(350)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.close)
        self._anim.start()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._thread and self._thread.isRunning():
            # Disconnect the slot so the destroyed dialog isn't called back
            try:
                self._worker.finished.disconnect(self._on_scan_finished)  # type: ignore[union-attr]
            except (TypeError, RuntimeError):
                pass
            self._thread.quit()
            self._thread.wait(500)
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────────────────────

class AlogScanner(QObject):
    """
    Reads .alog files in a background thread.

    Emits finished(data_list, count) where data_list is a list of
    (QDateTime, weight_grams: int) tuples for all roasts after last_clean.
    """

    finished: pyqtSignal = pyqtSignal(object, int)

    def __init__(self, directory: str, last_clean: QDateTime) -> None:
        super().__init__()
        # Guard against an empty setting: Path("") resolves to the CWD and would
        # otherwise scan the current working directory for stray .alog files.
        self.directory = Path(directory) if directory and directory.strip() else None
        self.last_clean = last_clean

    @pyqtSlot()
    def run(self) -> None:
        dates_with_weight: list[tuple[QDateTime, int]] = []
        try:
            if self.directory is not None and self.directory.is_dir():
                files = sorted(
                    (f for f in self.directory.iterdir() if f.suffix == ".alog"),
                    key=lambda f: f.stat().st_mtime,
                )
                for filepath in files:
                    try:
                        self._parse_file(filepath, dates_with_weight)
                    except Exception as exc:
                        # Per-file error: log and continue with remaining files
                        _log.warning("Skipping %s: %s", filepath.name, exc)
        except Exception as exc:
            _log.error("AlogScanner fatal error: %s", exc)

        self.finished.emit(dates_with_weight, len(dates_with_weight))

    def _parse_file(
        self, filepath: Path, out: list[tuple[QDateTime, int]]
    ) -> None:
        size = filepath.stat().st_size
        if size == 0 or size > _ALOG_MAX_BYTES:
            # Not an error: empty or oversized files are silently ignored.
            _log.debug("Ignoring %s (size=%d)", filepath.name, size)
            return

        # Artisan .alog files are Python-repr dicts (True/False/None, single
        # quotes), read canonically via ast.literal_eval — see
        # artisanlib.util.deserialize(). literal_eval is the working path; JSON
        # is only a defensive fallback for any file that happens to be valid JSON.
        raw = filepath.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        try:
            data = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError("Unparsable (not a Python-repr or JSON dict)") from None

        if not isinstance(data, dict):
            raise ValueError("Expected dict, got " + type(data).__name__)

        iso = data.get("roastisodate", "")
        if not isinstance(iso, str) or not iso:
            raise ValueError(f"Missing roastisodate in {filepath.name}")
        dt = QDateTime.fromString(iso, Qt.DateFormat.ISODate)
        if not dt.isValid():
            raise ValueError(f"Invalid roastisodate: {iso!r}")

        if dt <= self.last_clean:
            return  # older than last cleaning — skip

        out.append((dt, self._weight_grams(data.get("weight", []))))

    @staticmethod
    def _weight_grams(raw_weight: object) -> int:
        """
        Convert the profile's stored input weight to grams.

        Artisan stores ``weight`` as ``[weight_in, weight_out, unit]`` where
        ``unit`` is one of 'g', 'Kg', 'lb', 'oz'. The unit must be honoured —
        a roast recorded in Kg is otherwise read as if it were grams.
        """
        if isinstance(raw_weight, (list, tuple)) and raw_weight:
            try:
                value = float(raw_weight[0])
            except (TypeError, ValueError):
                return 0
            unit = decodeLocalStrict(raw_weight[2], "g") if len(raw_weight) >= 3 else "g"
            try:
                unit_idx = weight_units.index(unit)
            except ValueError:
                unit_idx = 0  # unknown unit → assume grams
            return round(convertWeight(value, unit_idx, 0))  # → index 0 = grams
        if isinstance(raw_weight, (int, float)):
            return round(raw_weight)
        return 0
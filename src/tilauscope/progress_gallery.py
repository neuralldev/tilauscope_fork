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

"""Visual bench for the TilauProgress family: every shape, state and host on one
screen (Configuration -> GENERAL -> Diagnostics). Labels are plain English, not
translated — they name API states, not operator-facing text."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QFrame, QWidget)

from tilauscope.tilauscope_types import (THEME, TilauProgress, TilauProgressRow,
                                         TilauProgressPill, TilauProgressDialog,
                                         set_button_busy, reduce_motion,
                                         print_progress_pill)
from tilauscope.header_icons import (SVG_PROG_SEARCH, SVG_PROG_DOWNLOAD, SVG_PROG_UPLOAD,
                                     SVG_PROG_AI, SVG_PROG_PRINT, SVG_PROG_HEAT)
from tilauscope.theme_qss import base_qss

_log = logging.getLogger(__name__)

_STATES = [
    ("Queued",  TilauProgress.WAITING),
    ("Working", TilauProgress.WORKING),
    ("Filling", TilauProgress.FILLING),
    ("Done",    TilauProgress.DONE),
    ("Failed",  TilauProgress.FAILED),
]

_GLYPHS = [
    ("searching", SVG_PROG_SEARCH),
    ("download",  SVG_PROG_DOWNLOAD),
    ("export",    SVG_PROG_UPLOAD),
    ("AI text",   SVG_PROG_AI),
    ("printing",  SVG_PROG_PRINT),
    ("heating",   SVG_PROG_HEAT),
]


def _caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        f"color:{THEME['SUBTEXT']}; font-size:10px;"
        f" background:transparent; border:none;")
    return lbl


def _heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{THEME['ACCENT']}; font-size:11px; font-weight:bold; letter-spacing:1px;"
        f" background:transparent; border:none;")
    return lbl


def _rule() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color:{THEME['BORDER']}; background:{THEME['BORDER']}; max-height:1px;")
    return line


class ProgressGalleryDlg(QDialog):
    """Every TilauProgress state and host, driveable by hand."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TilauProgress — bench")
        self.setStyleSheet(base_qss() +
            f"QDialog {{ background:{THEME['BG']}; }}"
            f"QLabel {{ color:{THEME['TEXT']}; }}"
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f" border:1px solid {THEME['BORDER']}; border-radius:7px; padding:6px 12px;"
            f" font-size:11px; }}"
            f"QPushButton:hover {{ border:1px solid {THEME['ACCENT']}; }}"
            f"QPushButton:disabled {{ color:{THEME['SUBTEXT']}; }}")

        self._specimens: list[TilauProgress] = []
        self._play_timer: QTimer | None = None
        self._pill: TilauProgressPill | None = None
        self._print_stop = False
        self._row_timer: QTimer | None = None
        self._dlg_timer: QTimer | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("TilauProgress — every state, live")
        title.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:15px; font-weight:bold;"
            f" background:transparent;")
        root.addWidget(title)

        motion = ("reduced motion: ON (the OS asks for it — rings breathe, "
                  "they do not turn)") if reduce_motion() else \
                 "reduced motion: off (rings turn)"
        root.addWidget(_caption(motion))
        root.addWidget(_rule())

        # ── 1. state strip ──────────────────────────────────────────────────
        root.addWidget(_heading("1 · STATES"))
        strip = QHBoxLayout()
        strip.setSpacing(6)
        for label, state in _STATES:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _c=False, s=state: self._apply(s))
            strip.addWidget(btn)
        strip.addStretch(1)
        self.btn_play = QPushButton("▶  Play a full run")
        self.btn_play.clicked.connect(self._play)
        strip.addWidget(self.btn_play)
        root.addLayout(strip)

        # ── 2. specimens ────────────────────────────────────────────────────
        shelf = QHBoxLayout()
        shelf.setSpacing(26)
        for size, cap in ((64, "ring 64\ndialog"), (24, "ring 24\npill"), (16, "ring 16\nbutton")):
            col = QVBoxLayout()
            col.setSpacing(6)
            ring = TilauProgress(TilauProgress.RING, size)
            self._specimens.append(ring)
            holder = QHBoxLayout()
            holder.addStretch(1)
            holder.addWidget(ring)
            holder.addStretch(1)
            col.addLayout(holder)
            col.addWidget(_caption(cap))
            shelf.addLayout(col)

        bar_col = QVBoxLayout()
        bar_col.setSpacing(6)
        self._bar = TilauProgress(TilauProgress.BAR)
        self._specimens.append(self._bar)
        bar_col.addWidget(self._bar)
        bar_col.addWidget(_caption("bar 6px\nlist row / download"))
        shelf.addLayout(bar_col, 1)
        root.addLayout(shelf)

        root.addWidget(_rule())

        # ── 3. glyphs ───────────────────────────────────────────────────────
        root.addWidget(_heading("2 · PROCESS GLYPHS  (always working, 64 px)"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for i, (name, svg) in enumerate(_GLYPHS):
            ring = TilauProgress(TilauProgress.RING, 64, svg)
            ring.set_indeterminate()
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addStretch(1)
            hl.addWidget(ring)
            hl.addStretch(1)
            grid.addWidget(holder, 0, i)
            grid.addWidget(_caption(name), 1, i)
        root.addLayout(grid)

        root.addWidget(_rule())

        # ── 4. the four hosts ───────────────────────────────────────────────
        root.addWidget(_heading("3 · HOSTS"))
        hosts = QHBoxLayout()
        hosts.setSpacing(8)

        b_pill = QPushButton("A · status pill")
        b_pill.clicked.connect(self._demo_pill)
        hosts.addWidget(b_pill)

        b_dlg = QPushButton("B · modal dialog")
        b_dlg.clicked.connect(self._demo_dialog)
        hosts.addWidget(b_dlg)

        b_fail = QPushButton("A · pill that fails")
        b_fail.clicked.connect(self._demo_pill_fail)
        hosts.addWidget(b_fail)

        b_print = QPushButton("A · print run (12 labels)")
        b_print.clicked.connect(self._demo_print)
        hosts.addWidget(b_print)

        self.btn_busy = QPushButton("D · busy button")
        self.btn_busy.clicked.connect(self._demo_busy)
        hosts.addWidget(self.btn_busy)
        hosts.addStretch(1)
        root.addLayout(hosts)

        row_wrap = QHBoxLayout()
        row_wrap.setSpacing(10)
        row_wrap.addWidget(_caption("C · inline row"))
        self._row = TilauProgressRow()
        row_wrap.addWidget(self._row, 1)
        b_row = QPushButton("run")
        b_row.clicked.connect(self._demo_row)
        row_wrap.addWidget(b_row)
        root.addLayout(row_wrap)

        root.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        footer.addWidget(btn_close)
        root.addLayout(footer)

        self.resize(760, 620)
        self._apply(TilauProgress.WORKING)

    # ── specimen driving ────────────────────────────────────────────────────
    def _apply(self, state: str, frac: float | None = None) -> None:
        self._stop_play()
        for w in self._specimens:
            w.set_state(state)
            if state == TilauProgress.FILLING:
                w.set_value(0.62 if frac is None else frac)
            elif state == TilauProgress.FAILED:
                w.set_value(0.42 if frac is None else frac)

    def _stop_play(self) -> None:
        if self._play_timer is not None:
            self._play_timer.stop()
            self._play_timer = None

    def _play(self) -> None:
        """Queued -> working -> filling -> done, the real sequence."""
        self._stop_play()
        for w in self._specimens:
            w.set_state(TilauProgress.WAITING)

        def to_working() -> None:
            for w in self._specimens:
                w.set_state(TilauProgress.WORKING)
            QTimer.singleShot(1500, to_filling)

        def to_filling() -> None:
            for w in self._specimens:
                w.set_state(TilauProgress.FILLING)
                w.set_value(0.0)
            self._tick = 0.0
            self._play_timer = QTimer(self)
            self._play_timer.setInterval(90)
            self._play_timer.timeout.connect(step)
            self._play_timer.start()

        def step() -> None:
            self._tick += 0.045
            if self._tick >= 1.0:
                self._stop_play()
                for w in self._specimens:
                    w.set_state(TilauProgress.DONE)
                return
            for w in self._specimens:
                w.set_value(self._tick)

        QTimer.singleShot(700, to_working)

    # ── host demos ──────────────────────────────────────────────────────────
    def _demo_pill(self) -> None:
        if self._pill is not None:
            self._pill.hide()
            self._pill.deleteLater()
        self._pill = TilauProgressPill(self, "Scanning roast profiles…", SVG_PROG_SEARCH)
        self._pill.cancelled.connect(self._cancel_pill)
        self._pill.show()
        self._pill_i = 0

        def step() -> None:
            if self._pill is None:
                return
            self._pill_i += 11
            if self._pill_i >= 312:
                self._pill.succeed("Done")
                return
            self._pill.set_count(self._pill_i, 312)
            QTimer.singleShot(90, step)

        QTimer.singleShot(600, step)

    def _cancel_pill(self) -> None:
        if self._pill is not None:
            self._pill.fail("Stopped. The profiles already read are kept.")

    def _demo_print(self) -> None:
        """The Niimbot wiring: counted batch, ✕ = stop after the current label."""
        if self._pill is not None:
            self._pill.hide()
            self._pill.deleteLater()
        total = 12
        self._print_stop = False
        self._pill = print_progress_pill(
            self, total, lambda: setattr(self, "_print_stop", True))
        self._pill_i = 0

        def step() -> None:
            if self._pill is None:
                return
            if self._print_stop:
                self._pill.succeed(f"🖨  Stopped after {self._pill_i} of {total} labels")
                return
            self._pill_i += 1
            self._pill.set_count(self._pill_i, total)
            if self._pill_i >= total:
                self._pill.succeed(f"🖨  {total} labels printed")
                return
            QTimer.singleShot(450, step)

        QTimer.singleShot(400, step)

    def _demo_pill_fail(self) -> None:
        if self._pill is not None:
            self._pill.hide()
            self._pill.deleteLater()
        self._pill = TilauProgressPill(self, "Reaching the roaster…", SVG_PROG_SEARCH)
        self._pill.show()
        pill = self._pill

        def boom() -> None:
            if pill is self._pill:
                pill.fail("No reply. Check the USB cable, then try again.")

        QTimer.singleShot(1800, boom)

    def _demo_dialog(self) -> None:
        dlg = TilauProgressDialog("Scanning roast profiles…", self, 312, SVG_PROG_SEARCH)
        dlg.show()
        self._dlg_i = 0

        def step() -> None:
            self._dlg_i += 14
            if self._dlg_i >= 312:
                dlg.pbar.succeed()
                QTimer.singleShot(1200, dlg.close)
                return
            dlg.setValue(self._dlg_i)
            QTimer.singleShot(80, step)

        QTimer.singleShot(300, step)

    def _demo_row(self) -> None:
        if self._row_timer is not None:
            self._row_timer.stop()
        self._row.setRange(0, 24)
        self._row.setValue(0)
        self._row_i = 0

        def step() -> None:
            self._row_i += 1
            self._row.setValue(self._row_i)
            if self._row_i >= 24:
                if self._row_timer is not None:
                    self._row_timer.stop()
                self._row.set_state(TilauProgress.DONE)

        self._row_timer = QTimer(self)
        self._row_timer.setInterval(140)
        self._row_timer.timeout.connect(step)
        self._row_timer.start()

    def _demo_busy(self) -> None:
        set_button_busy(self.btn_busy, True, "working…", SVG_PROG_AI)
        QTimer.singleShot(
            2500, lambda: set_button_busy(self.btn_busy, False))


def open_progress_gallery(parent=None) -> None:
    """Open the bench. Guarded: a diagnostic must never take the app down."""
    try:
        dlg = ProgressGalleryDlg(parent)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.show()
    except Exception:                                    # noqa: BLE001
        _log.exception("progress gallery failed to open")


if __name__ == "__main__":
    # Standalone check: cd src && python -m tilauscope.progress_gallery
    # Org/app names are set to a scratch domain BEFORE the QApplication exists,
    # so this bench never reads or writes the real preferences.
    import sys
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication

    QCoreApplication.setOrganizationName("tilauscope-bench")
    QCoreApplication.setApplicationName("progress-gallery")

    app = QApplication(sys.argv)
    window = ProgressGalleryDlg()
    window.show()
    sys.exit(app.exec())

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

## TILAU ## Roast card — read-only roast summary dialog opened from a QR scan
## (spec: wiki/QR-Scan-Spec.md §3.5, mockup validated 2026-07-16).
## Renders from an already-parsed .alog dict; NEVER loads the profile into
## Artisan (that would overwrite the current device configuration). All work
## happens on user action — nothing here touches the 1 Hz sampling path.

import logging
from typing import Final, Optional, Callable

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame,
)

from tilauscope.tilauscope_types import THEME, format_batch_label

_log: Final[logging.Logger] = logging.getLogger(__name__)

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    _HAS_MPL = True
except Exception as _e:  # pragma: no cover
    _log.warning(f"matplotlib unavailable for roast card: {_e}")
    _HAS_MPL = False

# curve palette (Catppuccin, matches the app theme)
_C_BT = "#89B4FA"      # blue — bean temperature
_C_ET = "#F9E2AF"      # yellow — environment temperature
_C_MARK = "#6C7086"    # event marker lines
_C_PLOT_BG = "#181825"


def _fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


class RoastCardDialog(QDialog):
    """Read-only roast summary card.

    profile:      parsed .alog dict (from BeanCave's cached reader)
    bean_name:    display name of the source green bean ("" if unresolved)
    on_open_bean: callback opening the source bean sheet; the button is
                  hidden when None (bean not resolved in BeancaveDB)
    """

    def __init__(self, profile: dict, parent=None, bean_name: str = "",
                 on_open_bean: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self._drag_pos: Optional[QPoint] = None
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(560)
        self.setStyleSheet(f"""
            QDialog {{
                background: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QPushButton {{
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']}; border-radius: 14px;
                padding: 5px 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {THEME['BORDER']}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        profile = profile or {}
        computed = profile.get("computed") or {}

        # ---- header --------------------------------------------------------
        title_txt = str(profile.get("title") or "").strip()
        display_title = bean_name or title_txt or QApplication.translate(
            "tilauscope_beancave", "Roast")
        batch = format_batch_label(str(profile.get("roastbatchprefix", "") or ""),
                                   int(profile.get("roastbatchnr", 0) or 0))

        head_row = QHBoxLayout()
        head = QLabel("☕  " + display_title.upper() + (f" — {batch}" if batch else ""))
        head.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 16px; font-weight: 800; "
                           f"font-family: 'JetBrains Mono';")
        head.setWordWrap(True)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']}; color: {THEME['CRITICAL']};
                border-radius: 13px; border: 1px solid {THEME['CRITICAL']};
                font-weight: bold; padding: 0;
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """)
        close_btn.clicked.connect(self.accept)
        head_row.addWidget(head, 1)
        head_row.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head_row)

        date_bits = [str(profile.get("roastdate") or "").strip()]
        rt = str(profile.get("roasttime") or "").strip()
        if rt:
            date_bits.append(rt[:5])
        sub = QLabel(QApplication.translate("tilauscope_beancave", "roasted on")
                     + " " + " · ".join(b for b in date_bits if b))
        sub.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px;")
        layout.addWidget(sub)

        layout.addWidget(self._separator())

        # ---- curve ----------------------------------------------------------
        canvas = self._build_curve(profile, computed)
        if canvas is not None:
            layout.addWidget(canvas, 1)

        # ---- weights / loss --------------------------------------------------
        w = profile.get("weight")
        w_line = ""
        if w and len(w) >= 3:
            try:
                w_in, w_out, unit = float(w[0]), float(w[1]), str(w[2])
                if w_in > 0:
                    w_line = f"CHARGE {w_in:g} {unit}"
                    if w_out > 0:
                        loss = (w_in - w_out) / w_in * 100.0
                        w_line += f"   →   DROP {w_out:g} {unit}      " \
                                  + QApplication.translate("tilauscope_beancave", "loss") \
                                  + f" {loss:.1f} %"
            except (TypeError, ValueError):
                w_line = ""
        if w_line:
            wl = QLabel(w_line)
            wl.setStyleSheet(f"font-size: 13px; font-weight: 700; font-family: 'JetBrains Mono';")
            layout.addWidget(wl)

        # ---- agtron / DTR / duration ----------------------------------------
        drop_t = float(computed.get("DROP_time") or 0)
        fcs_t = float(computed.get("FCs_time") or 0)
        stats = []
        try:
            agtron = int(float(profile.get("ground_color") or 0))
            if agtron > 0:
                stats.append(f"Agtron {agtron}")
        except (TypeError, ValueError):
            pass
        if drop_t > 0 and 0 < fcs_t < drop_t:
            stats.append(f"DTR {(drop_t - fcs_t) / drop_t * 100.0:.0f} %")
        if drop_t > 0:
            stats.append(QApplication.translate("tilauscope_beancave", "duration")
                         + f" {_fmt_mmss(drop_t)}")
        if stats:
            sl = QLabel("   ·   ".join(stats))
            sl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; "
                             f"font-family: 'JetBrains Mono';")
            layout.addWidget(sl)

        # ---- key times --------------------------------------------------------
        times = []
        for lbl, key in (("TP", "TP_time"), ("DRYe", "DRY_time"),
                         ("FC", "FCs_time"), ("DROP", "DROP_time")):
            try:
                t = float(computed.get(key) or 0)
            except (TypeError, ValueError):
                t = 0.0
            if t > 0:
                times.append(f"{lbl} {_fmt_mmss(t)}")
        if times:
            tl = QLabel(" · ".join(times))
            tl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; "
                             f"font-family: 'JetBrains Mono';")
            layout.addWidget(tl)

        # ---- cupping notes ------------------------------------------------------
        notes = str(profile.get("cuppingnotes") or "").strip()
        if notes:
            layout.addWidget(self._separator())
            nt = QLabel(QApplication.translate("tilauscope_beancave", "Tasting notes"))
            nt.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 12px; font-weight: 700;")
            layout.addWidget(nt)
            nb = QLabel("« " + notes + " »")
            nb.setWordWrap(True)
            nb.setStyleSheet("font-size: 12px; font-style: italic;")
            layout.addWidget(nb)

        # ---- source bean link ------------------------------------------------
        if on_open_bean is not None:
            layout.addSpacing(4)
            bean_btn = QPushButton("🌱  " + QApplication.translate(
                "tilauscope_beancave", "Open the source bean sheet"))
            bean_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def _open_bean() -> None:
                self.accept()
                on_open_bean()

            bean_btn.clicked.connect(_open_bean)
            layout.addWidget(bean_btn)

    # -------------------------------------------------------------------------

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {THEME['BORDER']}; border: none; "
                           f"min-height: 1px; max-height: 1px;")
        return line

    def _build_curve(self, profile: dict, computed: dict):
        """BT/ET miniature with event markers. Returns a canvas or None."""
        if not _HAS_MPL:
            return None
        try:
            timex = profile.get("timex") or []
            bt = profile.get("temp2") or []
            et = profile.get("temp1") or []
            timeindex = profile.get("timeindex") or []
            if len(timex) < 2 or len(bt) != len(timex):
                return None
            charge_idx = timeindex[0] if timeindex and timeindex[0] > -1 else 0
            t0 = timex[charge_idx]
            xs = [(t - t0) / 60.0 for t in timex]

            fig = Figure(figsize=(5.4, 2.4), facecolor=_C_PLOT_BG)
            ax = fig.add_subplot(111)
            ax.set_facecolor(_C_PLOT_BG)
            if et and len(et) == len(timex):
                ax.plot(xs, et, color=_C_ET, linewidth=1.0, alpha=0.7, label="ET")
            ax.plot(xs, bt, color=_C_BT, linewidth=1.6, label="BT")

            # event markers: CHARGE + sentinel convention (index 0: -1 = unmarked;
            # 1..7: 0 = unmarked, > 0 = marked)
            marks = [("CHARGE", charge_idx if (timeindex and timeindex[0] > -1) else 0)]
            tp_idx = computed.get("TP_idx")
            if tp_idx and 0 < int(tp_idx) < len(timex):
                marks.append(("TP", int(tp_idx)))
            for lbl, ti in (("DRYe", 1), ("FC", 2), ("DROP", 6)):
                if len(timeindex) > ti and timeindex[ti] > 0:
                    marks.append((lbl, timeindex[ti]))
            y_top = max(bt) if bt else 0
            for lbl, idx in marks:
                if 0 <= idx < len(xs):
                    ax.axvline(xs[idx], color=_C_MARK, linewidth=0.7,
                               linestyle="--", alpha=0.8)
                    ax.annotate(lbl, (xs[idx], y_top), fontsize=6.5,
                                color=THEME['SUBTEXT'], ha="center",
                                xytext=(0, 4), textcoords="offset points")

            ax.tick_params(colors=THEME['SUBTEXT'], labelsize=7)
            for spine in ax.spines.values():
                spine.set_color(THEME['BORDER'])
            ax.grid(True, color=THEME['BORDER'], linewidth=0.4, alpha=0.5)
            ax.set_xlim(left=min(0.0, xs[0]))
            ax.margins(y=0.12)
            fig.tight_layout(pad=0.8)

            canvas = FigureCanvas(fig)
            canvas.setMinimumHeight(190)
            canvas.setStyleSheet("background: transparent; border: none;")
            return canvas
        except Exception as e:
            _log.warning(f"Roast card curve rendering failed: {e}", exc_info=True)
            return None

    # frameless drag
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

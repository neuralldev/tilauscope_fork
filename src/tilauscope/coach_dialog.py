#
# ABOUT
# Coach's advice: the coach's reading of the roast under review, in the roasting window.

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

"""The coach's reading, opened from the roast review.

Every word comes from `roast_coach` — the rows BeanCave's Advanced Stats shows
for the same roast — so this file only lays them out. Built on user action,
never in the sampling path.
"""

import logging
from typing import Any, Final, Optional

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from tilauscope import roast_coach as coach
from tilauscope.roast_debrief import display_name
from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Ground and ink per kind of row, the same pairs as BeanCave's report.
_KIND_COLOURS: Final[dict[str, tuple[str, str]]] = {
    "ok": ("#1a3a1a", THEME['SUCCESS']),
    "warn": ("#3a2e00", THEME['WARNING']),
    "bad": ("#3a1a1a", THEME['CRITICAL']),
    "info": ("#0d2a3a", THEME['ACCENT']),
}

_WIDTH: Final[int] = 620                 # px
_MAX_SCREEN_SHARE: Final[float] = 0.85   # tallest the dialog grows; the reading scrolls past it
_MIN_READING_H: Final[int] = 160         # px of reading always left visible


def _mono(size: int, weight: int = 400, color: str = "") -> str:
    col = f" color: {color};" if color else ""
    return (f"font-family: 'JetBrains Mono', monospace; font-size: {size}px;"
            f" font-weight: {weight};{col} background: transparent; border: none;")


def reading_for(aw: Any, profile: dict, *,
                inputs: "tuple[Any, Any] | None" = None) -> coach.CoachReading:
    """The coach's reading of a profile built from the live application.

    Reads the roaster record and the bean file — unless `inputs` carries them
    already — and recomputes the rate of rise, exactly as BeanCave does for a
    stored roast.
    """
    ctx, bean = inputs if inputs is not None else coach.roast_inputs(profile)

    def _ror_bt() -> Any:
        from tilauscope.cave.common import recompute_profile_deltas, ror_span_samples  # noqa: PLC0415
        qmc = aw.qmc
        return recompute_profile_deltas(qmc, profile, "temp2",
                                        ror_span_samples(qmc, profile, "temp2"))

    return coach.read_roast(profile, roast_context=ctx, bean=bean,
                            duration_rules=coach.stored_duration_rules(),
                            evaluate_ror_bt=_ror_bt, ror_mode=str(aw.qmc.mode))


class CoachAdviceDialog(QDialog):
    """Read-only: the level the roast ran at, the advice, and the average rises."""

    def __init__(self, profile: dict, reading: coach.CoachReading, parent=None):
        super().__init__(parent)
        self._drag_pos: Optional[QPoint] = None
        self._fitted = False
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setFixedWidth(_WIDTH)
        self.setStyleSheet(base_qss() + f"""
            QDialog {{
                background: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 10px;
            }}
            QLabel {{ color: {THEME['TEXT']}; background: transparent; border: none; }}
            QScrollArea {{ background: transparent; border: none; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(6)

        # ---- header --------------------------------------------------------
        head_row = QHBoxLayout()
        caption = QLabel(QApplication.translate("tilauscope_beancave", "Coach's Advice 🎯").upper())
        caption.setStyleSheet(_mono(10, 700, THEME['SUBTEXT']) + " letter-spacing: 1px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']}; color: {THEME['CRITICAL']};
                border-radius: 13px; border: 1px solid {THEME['CRITICAL']};
                font-weight: bold; padding: 0;
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """)
        close_btn.clicked.connect(self.accept)
        head_row.addWidget(caption, 1)
        head_row.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head_row)

        name = QLabel((display_name(profile) or QApplication.translate(
            "tilauscope_review", "ROAST")).upper())
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {THEME['ACCENT']};")
        layout.addWidget(name)
        when = " · ".join(b for b in (str(profile.get("roastdate") or "").strip(),
                                      str(profile.get("roasttime") or "").strip()[:5]) if b)
        if when:
            sub = QLabel(when)
            sub.setStyleSheet(_mono(10, 400, THEME['OVERLAY0']))
            layout.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {THEME['BORDER']}; border: none;"
                           f" min-height: 1px; max-height: 1px;")
        layout.addWidget(line)

        # ---- reading -------------------------------------------------------
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 4, 4, 0)
        body_lay.setSpacing(4)

        rows = list(reading.rows)
        if reading.level and rows:
            # The level sentence leads: every row below is measured against it.
            lead = QLabel(rows.pop(0).text)
            lead.setWordWrap(True)
            lead.setTextFormat(Qt.TextFormat.PlainText)
            lead.setStyleSheet("font-size: 12px; padding-bottom: 4px;")
            body_lay.addWidget(lead)
        for row in rows:
            body_lay.addWidget(self._row(row))

        rises = self._rises(profile)
        if rises is not None:
            body_lay.addSpacing(8)
            body_lay.addWidget(rises)

        self._body = body
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(body)
        layout.addWidget(self._scroll)

    # -------------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Sized once shown, not before: the wrapped rows only know their height
        # once the style sheet has given them their font.
        if not self._fitted:
            self._fitted = True
            self._fit_to_content()
            self._center_on_host()

    def _fit_to_content(self) -> None:
        margins = self.layout().contentsMargins()
        natural = self._body.heightForWidth(self.width() - margins.left() - margins.right())
        if natural <= 0:
            natural = self._body.sizeHint().height()
        self._scroll.setFixedHeight(natural)
        self.adjustSize()
        limit = int(self.screen().availableGeometry().height() * _MAX_SCREEN_SHARE)
        if self.height() > limit:
            self._scroll.setFixedHeight(max(_MIN_READING_H, natural - (self.height() - limit)))
            self.adjustSize()

    def _center_on_host(self) -> None:
        """Centre on the roasting window, kept inside the screen."""
        area = self.screen().availableGeometry()
        host = self.parentWidget().window() if self.parentWidget() is not None else None
        frame = self.frameGeometry()
        frame.moveCenter(host.frameGeometry().center() if host is not None else area.center())
        x = min(max(frame.left(), area.left()), area.right() - frame.width())
        y = min(max(frame.top(), area.top()), area.bottom() - frame.height())
        self.move(x, y)

    @staticmethod
    def _row(row: coach.AdviceRow) -> QWidget:
        ground, ink = _KIND_COLOURS.get(row.kind, _KIND_COLOURS["info"])
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background: {ground}; border: none; border-radius: 5px; }}"
                            f"QLabel {{ color: {ink}; background: transparent; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        icon = QLabel(row.icon)
        icon.setFixedWidth(18)
        icon.setStyleSheet("font-size: 13px;")
        text = QLabel(row.text)
        text.setWordWrap(True)
        # Advice is plain text: a "<650 g/l" must never open a tag.
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setStyleSheet("font-size: 11px;")
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(text, 1)
        return frame

    @staticmethod
    def _rises(profile: dict) -> "QWidget | None":
        computed = profile.get("computed") or {}
        cells = (("DRY", coach.average_rise(computed, "TP", "DRY")),
                 ("MAI", coach.average_rise(computed, "DRY", "FCs")),
                 ("DEV", coach.average_rise(computed, "FCs", "DROP")),
                 ("TP → DROP", coach.average_rise(computed, "TP", "DROP")))
        if all(v is None for _, v in cells):
            return None
        unit = "F" if str(profile.get("mode") or "C").upper() == "F" else "C"
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        title = QLabel(QApplication.translate("tilauscope_beancave", "Average rise per phase").upper()
                       + f" · °{unit}/min")
        title.setStyleSheet(_mono(10, 700, THEME['SUBTEXT']) + " letter-spacing: 1px;")
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(6)
        for col, (label, value) in enumerate(cells):
            cell = QFrame()
            cell.setStyleSheet(f"QFrame {{ background: {THEME['SURFACE']};"
                               f" border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}")
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(8, 5, 8, 5)
            cell_lay.setSpacing(0)
            cap = QLabel(label)
            cap.setStyleSheet(_mono(9, 400, THEME['OVERLAY0']))
            val = QLabel("—" if value is None else f"{value:.1f}")
            val.setStyleSheet(_mono(13, 700, THEME['OVERLAY0'] if value is None else THEME['TEXT']))
            cell_lay.addWidget(cap)
            cell_lay.addWidget(val)
            grid.addWidget(cell, 0, col)
        lay.addLayout(grid)
        return box

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

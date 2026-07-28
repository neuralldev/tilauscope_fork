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

## TILAU ##
"""Rich-rows catalogue list for BeanCave (Lot 5, step A — validated mock).

A readable replacement for the 28-column QTableWidget of the Green Beans tab:
each bean is a compact 3-line row — name + badges (BLEND, harvest age),
origin · process · crop, then the stock pill and the attached sack ids —
with a live search field and an "In stock" filter on top.

Architecture note: this widget is a pure VIEW. The legacy datatable stays
alive but hidden and remains the selection model every existing code path
relies on (visual row == green_beans index). Clicking a row here calls
``datatable.selectRow(i)`` through the host hook; programmatic selections
mirror back via ``select_index``. Filtering only hides rows visually — it
never reorders anything, so the row/index invariant holds.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tilauscope.tilauscope_types import THEME

_logd = logging.getLogger('tilaudebug')

_MONO = "'JetBrains Mono', monospace"
_DIM = "#6C7086"



class _BeanRow(QFrame):
    """One catalogue entry: 3 lines, selectable, dimmed when out of stock."""

    clicked = pyqtSignal(int)

    def __init__(self, index: int, bean, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._selected = False
        self._out = (getattr(bean, 'weight_left', 0.0) or 0.0) <= 0
        # lower-cased haystack for the live search filter
        self.haystack = " ".join(str(getattr(bean, a, '') or '') for a in
                                 ('name', 'country', 'farm', 'supplier')).lower()
        self.in_stock = not self._out
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(bean)
        self._restyle()

    def _build(self, bean) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(2)

        text_col = _DIM if self._out else THEME['TEXT']
        sub_col = _DIM if self._out else THEME['SUBTEXT']

        # line 1 — name + badges
        l1 = QHBoxLayout()
        l1.setSpacing(6)
        name = QLabel(bean.name)
        name.setToolTip(bean.name)
        name.setStyleSheet(
            f"color:{text_col};font-size:13px;"
            f"font-weight:{500 if self._out else 600};background:transparent;")
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        l1.addWidget(name, 1)
        if getattr(bean, 'is_blend', False):
            l1.addWidget(self._badge("BLEND", THEME['ACCENT']))
        crop = int(getattr(bean, 'crop', 0) or 0)
        if crop > 0:
            age = datetime.now().astimezone().year - crop
            if age >= 2:
                col = THEME['CRITICAL'] if age >= 3 else THEME['WARNING']
                badge = self._badge(f"⚠ {crop}", col)
                badge.setToolTip(QApplication.translate("tilauscope_beancave", "Harvest is {0} years old").format(age))
                l1.addWidget(badge)
        lay.addLayout(l1)

        # line 2 — origin · process · crop
        parts = [p for p in (bean.country, bean.process, str(crop) if crop > 0 else '') if p]
        l2 = QLabel(" · ".join(parts))
        l2.setStyleSheet(f"color:{sub_col};font-size:11px;background:transparent;")
        l2.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(l2)

        # line 3 — stock pill + sack ids
        l3 = QHBoxLayout()
        l3.setSpacing(8)
        if self._out:
            pill = QLabel(QApplication.translate("tilauscope_beancave", "out of stock"))
            pill_col = _DIM
        else:
            pill = QLabel(f"{bean.weight_left:.0f} g")
            pill_col = THEME['SUCCESS']
        pill.setStyleSheet(
            f"color:{pill_col};font-family:{_MONO};font-size:10px;"
            f"border:1px solid {pill_col};border-radius:8px;"
            f"padding:0px 7px;background:transparent;")
        l3.addWidget(pill)
        sacks = list(getattr(bean, 'sacks', None) or [])
        if sacks:
            sl = QLabel("⬤ " + "  ".join(sacks))
            sl.setToolTip(QApplication.translate("tilauscope_beancave", "Attached sack labels"))
            sl.setStyleSheet(f"color:{_DIM};font-family:{_MONO};font-size:9.5px;background:transparent;")
            sl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            l3.addWidget(sl, 1)
        else:
            l3.addStretch(1)
        lay.addLayout(l3)

    def _badge(self, text: str, color: str) -> QLabel:
        b = QLabel(text)
        b.setStyleSheet(
            f"color:{color};font-family:{_MONO};font-size:9px;font-weight:600;"
            f"border:1px solid {color};border-radius:8px;padding:0px 5px;"
            f"background:transparent;")
        return b

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self._restyle()

    def _restyle(self) -> None:
        if self._selected:
            self.setStyleSheet(
                "_BeanRow { background: rgba(137,180,250,0.10);"
                f"border:none;border-left:3px solid {THEME['ACCENT']};"
                f"border-bottom:1px solid {THEME['BORDER']}; }}")
        else:
            self.setStyleSheet(
                "_BeanRow { background: transparent;"
                "border:none;border-left:3px solid transparent;"
                f"border-bottom:1px solid {THEME['BORDER']}; }}"
                "_BeanRow:hover { background: rgba(137,180,250,0.05); }")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class CatalogueListWidget(QWidget):
    """Search bar + stock filter + scrollable rich rows (row i == green_beans[i])."""

    rowActivated = pyqtSignal(int)  # noqa: N815 — Qt signal naming

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_BeanRow] = []
        self._selected = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── tools bar ────────────────────────────────────────────────────────
        tools = QFrame()
        tools.setStyleSheet(
            f"QFrame {{ background:{THEME['SURFACE']};"
            f"border:none;border-bottom:1px solid {THEME['BORDER']}; }}")
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(QApplication.translate("tilauscope_beancave", "Search name, country, farm…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background:{THEME['BG']};color:{THEME['TEXT']};"
            f"border:1px solid {THEME['BORDER']};border-radius:8px;"
            f"padding:5px 9px;font-size:12px; }}"
            f"QLineEdit:focus {{ border:1px solid {THEME['ACCENT']}; }}")
        self.search_edit.textChanged.connect(self._apply_filter)
        tl.addWidget(self.search_edit, 1)

        self.stock_btn = QPushButton(QApplication.translate("tilauscope_beancave", "In stock"))
        self.stock_btn.setCheckable(True)
        self.stock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Hide out-of-stock beans"))
        self.stock_btn.setStyleSheet(
            f"QPushButton {{ background:{THEME['BG']};color:{_DIM};"
            f"border:1px solid {THEME['BORDER']};border-radius:8px;"
            f"padding:5px 10px;font-size:11px; }}"
            f"QPushButton:checked {{ color:{THEME['SUCCESS']};"
            f"border:1px solid {THEME['SUCCESS']};"
            f"background:rgba(166,227,161,0.08); }}")
        # the filter state survives BeanCave restarts
        self.stock_btn.setChecked(
            QSettings().value("tilauscope/beancave_stock_filter", False, type=bool))
        self.stock_btn.toggled.connect(self._on_stock_toggled)
        tl.addWidget(self.stock_btn)
        root.addWidget(tools)

        # ── rows ─────────────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea {{ background:{THEME['BG']};border:none; }}")

        self._rows_host = QWidget()
        self._rows_host.setStyleSheet(f"background:{THEME['BG']};")
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)

        self._empty_lbl = QLabel(QApplication.translate("tilauscope_beancave", "No bean matches the current filter."))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(f"color:{_DIM};font-size:12px;padding:18px;background:transparent;")
        self._empty_lbl.hide()
        self._rows_lay.addWidget(self._empty_lbl)
        self._rows_lay.addStretch(1)

        self._scroll.setWidget(self._rows_host)
        root.addWidget(self._scroll, 1)

    # ── public API (used by the beancave hooks) ──────────────────────────────
    def set_beans(self, beans: list) -> None:
        """Rebuild the rows, preserving selection and the active filter."""
        for row in self._rows:
            self._rows_lay.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for i, bean in enumerate(beans):
            try:
                row = _BeanRow(i, bean)
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception("catalogue row %s skipped", i)
                continue
            row.clicked.connect(self._on_row_clicked)
            # keep the stretch + empty label at the end
            self._rows_lay.insertWidget(len(self._rows), row)
            self._rows.append(row)
        if not 0 <= self._selected < len(self._rows):
            self._selected = -1
        if self._selected >= 0:
            self._rows[self._selected].set_selected(True)
        self._apply_filter()

    def select_index(self, index: int) -> None:
        """Mirror a programmatic datatable selection — never re-emits."""
        if index == self._selected:
            return
        if 0 <= self._selected < len(self._rows):
            self._rows[self._selected].set_selected(False)
        self._selected = index if 0 <= index < len(self._rows) else -1
        if self._selected >= 0:
            row = self._rows[self._selected]
            row.set_selected(True)
            self._scroll.ensureWidgetVisible(row, 0, 40)

    # ── internals ────────────────────────────────────────────────────────────
    def _on_stock_toggled(self, checked: bool) -> None:
        QSettings().setValue("tilauscope/beancave_stock_filter", bool(checked))
        self._apply_filter()

    def _on_row_clicked(self, index: int) -> None:
        self.select_index(index)
        self.rowActivated.emit(index)

    def _apply_filter(self) -> None:
        needle = self.search_edit.text().strip().lower()
        stock_only = self.stock_btn.isChecked()
        visible = 0
        for row in self._rows:
            show = (not needle or needle in row.haystack) and \
                   (not stock_only or row.in_stock)
            row.setVisible(show)
            visible += int(show)
        self._empty_lbl.setVisible(bool(self._rows) and visible == 0)

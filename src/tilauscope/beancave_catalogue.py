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

"""Rich-rows catalogue list for BeanCave: what there is to roast.

Pure view: the hidden datatable remains the selection model — a row carries its
green_beans index whatever the order it is shown in.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QByteArray, QDate, QLocale, QSettings, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tilauscope.bean_qualifiers import physical_qualifier
from tilauscope.roast_memory import RoastMemory, ready_to_taste
from tilauscope.theme_qss import tint, tint_hex
from tilauscope.tilauscope_types import THEME

_logd = logging.getLogger('tilau')

_MONO = "'JetBrains Mono', monospace"
_DIM = THEME['OVERLAY0']
_PLAIN = "background:transparent;border:none;"

SORT_TO_ROAST = "to_roast"
SORT_NAME = "name"
_SORT_KEY = "tilauscope/beancave_sort"


def svg_pixmap(path_d: str, colour: str, size: int = 15, width: float = 2.0) -> QPixmap:
    """A stroked 24-unit SVG path, rendered at twice its size for HiDPI."""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24">'
           f'<path d="{path_d}" fill="none" stroke="{colour}" stroke-width="{width}" '
           f'stroke-linecap="round" stroke-linejoin="round"/></svg>').encode()
    px = QPixmap(QSize(size * 2, size * 2))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    QSvgRenderer(QByteArray(svg)).render(p)
    p.end()
    px.setDevicePixelRatio(2)
    return px


def svg_icon(path_d: str, colour: str, size: int = 15, width: float = 2.0) -> QIcon:
    """A stroked 24-unit SVG path as an icon."""
    return QIcon(svg_pixmap(path_d, colour, size, width))


_SVG_SEARCH = "M11 5a6 6 0 1 0 0 12a6 6 0 1 0 0-12M20 20l-4.5-4.5"
_SVG_CHEVRON = "M6 9l6 6 6-6"


def _pill_css(checked_accent: bool = True) -> str:
    """The rounded filter pills under the search."""
    css = (f"QPushButton, QToolButton {{ background:transparent;color:{THEME['TEXT']};"
           f"border:1px solid {THEME['SURFACE1']};border-radius:15px;padding:0 12px;font-size:12px; }}"
           f"QPushButton:hover, QToolButton:hover {{ border-color:{THEME['ACCENT']}; }}"
           f"QPushButton::menu-indicator, QToolButton::menu-indicator {{ image:none;width:0; }}")
    if checked_accent:
        css += (f"QPushButton:checked {{ color:{THEME['ACCENT']};border:1px solid {THEME['ACCENT']};"
                f"background:{tint('ACCENT', 0.14)};font-weight:600; }}")
    return css


def _badge(text: str, colour: str, filled: bool = True) -> QLabel:
    b = QLabel(text)
    b.setStyleSheet(
        f"color:{colour};font-size:10px;font-weight:700;letter-spacing:1px;"
        f"border:1px solid {colour};border-radius:7px;padding:1px 7px;"
        f"background:{tint_hex(colour, 0.12) if filled else 'transparent'};")
    return b


def short_date(epoch: int) -> str:
    """'12 Sep' in the interface language."""
    d = datetime.fromtimestamp(epoch).date()
    return QLocale().toString(QDate(d.year, d.month, d.day), "d MMM")


def to_roast_order(bean, memory: RoastMemory | None) -> tuple:
    """Sort key of « To roast first »: what keeps worst comes first.

    In stock before out of stock; then the storage risk the water activity
    reads (free water first); then the oldest harvest; then the coffee left
    longest since its last roast, a never-roasted one before any.
    """
    out = (getattr(bean, 'weight_left', 0.0) or 0.0) <= 0
    aw = float(getattr(bean, 'water_activity', 0.0) or 0.0)
    _, aw_colour = physical_qualifier('aw', aw)
    risk = 0 if aw_colour == THEME['CRITICAL'] else 1 if aw_colour == THEME['WARNING'] else 2
    crop = int(getattr(bean, 'crop', 0) or 0) or 9999
    last = memory.epoch if memory is not None else 0
    return (out, risk, crop, last, (bean.name or '').lower())


class _BeanRow(QFrame):
    """One catalogue entry: 3 lines, selectable, dimmed when out of stock."""

    clicked = pyqtSignal(int)
    double_clicked = pyqtSignal(int)

    def __init__(self, index: int, bean, memory: RoastMemory | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._selected = False
        self._out = (getattr(bean, 'weight_left', 0.0) or 0.0) <= 0
        # lower-cased haystack for the live search filter
        self.haystack = " ".join(str(getattr(bean, a, '') or '') for a in
                                 ('name', 'country', 'farm', 'supplier')).lower()
        self.in_stock = not self._out
        self.order = to_roast_order(bean, memory)
        self.name_key = (bean.name or '').lower()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(QApplication.translate("tilauscope_beancave", "Double-click to see its roasts"))
        self._build(bean, memory)
        self._restyle()

    def _build(self, bean, memory: RoastMemory | None) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        text_col = _DIM if self._out else THEME['TEXT']
        sub_col = _DIM if self._out else THEME['SUBTEXT']

        # line 1 — name + badges
        l1 = QHBoxLayout()
        l1.setSpacing(6)
        name = QLabel(bean.name)
        name.setToolTip(bean.name)
        name.setStyleSheet(f"color:{text_col};font-size:14px;font-weight:{500 if self._out else 600};" + _PLAIN)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        l1.addWidget(name, 1)
        if not self._out and ready_to_taste(memory):
            taste = _badge(QApplication.translate("tilauscope_beancave", "TO TASTE"), THEME['MAUVE'])
            taste.setToolTip(QApplication.translate(
                "tilauscope_beancave", "Its last roast has rested: taste it before roasting it again."))
            l1.addWidget(taste)
        if getattr(bean, 'is_blend', False):
            l1.addWidget(_badge(QApplication.translate("tilauscope_beancave", "BLEND"), THEME['ACCENT'], filled=False))
        crop = int(getattr(bean, 'crop', 0) or 0)
        if crop > 0:
            age = datetime.now().astimezone().year - crop
            if age >= 2:
                badge = _badge(str(crop), THEME['CRITICAL'] if age >= 3 else THEME['WARNING'])
                badge.setToolTip(QApplication.translate("tilauscope_beancave", "Harvest is {0} years old").format(age))
                l1.addWidget(badge)
        lay.addLayout(l1)

        # line 2 — origin · process · crop
        parts = [p for p in (bean.country, bean.process, str(crop) if crop > 0 else '') if p]
        l2 = QLabel(" · ".join(parts))
        l2.setStyleSheet(f"color:{sub_col};font-size:12px;" + _PLAIN)
        l2.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(l2)

        # line 3 — stock, batches left, last roast, water activity
        l3 = QHBoxLayout()
        l3.setSpacing(8)
        if self._out:
            pill = QLabel(QApplication.translate("tilauscope_beancave", "out of stock"))
            pill_col = _DIM
        else:
            pill = QLabel(f"{bean.weight_left:.0f} g")
            pill_col = THEME['SUCCESS']
        pill.setStyleSheet(
            f"color:{pill_col};font-family:{_MONO};font-size:11px;font-weight:600;"
            f"border:1px solid {tint_hex(pill_col, 0.5)};border-radius:4px;"
            f"padding:0px 6px;background:transparent;")
        l3.addWidget(pill)
        stock = float(getattr(bean, 'weight_left', 0.0) or 0.0)
        if not self._out:
            batch = memory.weight_in_g if memory is not None else 0.0
            if batch > 0:
                n = round(stock / batch)
                l3.addWidget(self._small(
                    QApplication.translate("tilauscope_beancave", "≈ 1 batch") if n == 1 else
                    QApplication.translate("tilauscope_beancave", "≈ {0} batches").format(n),
                    THEME['TEXT']))
        when = (QApplication.translate("tilauscope_beancave", "last roast {0}").format(short_date(memory.epoch))
                if memory is not None and memory.epoch > 0 else
                QApplication.translate("tilauscope_beancave", "not roasted yet"))
        l3.addWidget(self._small("·  " + when, _DIM))
        if not self._out:
            aw = float(getattr(bean, 'water_activity', 0.0) or 0.0)
            word, colour = physical_qualifier('aw', aw)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{(colour or THEME['SUCCESS']) if aw > 0 else _DIM};"
                              f"border:none;border-radius:4px;")
            l3.addWidget(dot)
            l3.addWidget(self._small(
                (f"aw {aw:.2f}" + (f" · {word}" if colour else "")) if aw > 0 else
                QApplication.translate("tilauscope_beancave", "aw not measured"), _DIM))
        l3.addStretch(1)
        lay.addLayout(l3)

    @staticmethod
    def _small(text: str, colour: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{colour};font-size:11px;" + _PLAIN)
        return lbl

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self._restyle()

    def _restyle(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"_BeanRow {{ background:{THEME['BORDER']};"
                f"border:none;border-left:3px solid {THEME['ACCENT']};"
                f"border-bottom:1px solid {THEME['BORDER']}; }}")
        else:
            self.setStyleSheet(
                "_BeanRow { background: transparent;"
                "border:none;border-left:3px solid transparent;"
                f"border-bottom:1px solid {THEME['BORDER']}; }}"
                f"_BeanRow:hover {{ background:{tint('ACCENT', 0.05)}; }}")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        # Not passed to the base class: QWidget's default replays it as a
        # second press, which would select the row again behind the Roasts tab.
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._index)
        event.accept()


class CatalogueListWidget(QWidget):
    """Search bar + stock filter + sort + scrollable rich rows (row i == green_beans[i])."""

    rowActivated = pyqtSignal(int)  # noqa: N815 — Qt signal naming
    rowDoubleClicked = pyqtSignal(int)  # noqa: N815

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_BeanRow] = []
        self._selected = -1
        # bean uuid → memory of its last roast; set by the tab before set_beans
        self.memory_for: Callable[[], dict[str, Any]] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── tools: on the list's own ground ──────────────────────────────────
        tools = QWidget()
        tools.setObjectName("catalogueTools")
        tools.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tools.setStyleSheet(f"QWidget#catalogueTools {{ background:{THEME['BG']}; }}")
        tools_lay = QVBoxLayout(tools)
        tools_lay.setContentsMargins(14, 12, 14, 10)
        tools_lay.setSpacing(8)
        # Row 1: whatever the tab puts first (New bean), then the search.
        tl = QHBoxLayout()
        tl.setSpacing(8)
        self.lead_tools = tl
        tools_lay.addLayout(tl)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        tools_lay.addLayout(filters)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(QApplication.translate("tilauscope_beancave", "Search name, country, farm…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.addAction(svg_icon(_SVG_SEARCH, THEME['OVERLAY2']),
                                   QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background:{THEME['SURFACE']};color:{THEME['TEXT']};"
            f"border:1px solid {THEME['SURFACE1']};border-radius:8px;"
            f"padding:0 8px 0 4px;font-size:13px; }}"
            f"QLineEdit:focus {{ border:1px solid {THEME['ACCENT']}; }}")
        self.search_edit.setFixedHeight(38)
        self.search_edit.textChanged.connect(self._apply_filter)
        tl.addWidget(self.search_edit, 1)

        self.stock_btn = QPushButton()
        self.stock_btn.setCheckable(True)
        self.stock_btn.setFixedHeight(30)
        self.stock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_btn.setToolTip(QApplication.translate("tilauscope_beancave", "Hide or show the coffees out of stock"))
        self.stock_btn.setStyleSheet(_pill_css())
        # the filter state survives BeanCave restarts
        self.stock_btn.setChecked(
            QSettings().value("tilauscope/beancave_stock_filter", False, type=bool))
        self.stock_btn.toggled.connect(self._on_stock_toggled)
        self._label_stock()
        filters.addWidget(self.stock_btn)

        self._sort = str(QSettings().value(_SORT_KEY, SORT_TO_ROAST, str) or SORT_TO_ROAST)
        self.sort_btn = QToolButton()
        self.sort_btn.setFixedHeight(30)
        self.sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sort_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sort_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)   # chevron after the text
        self.sort_btn.setIcon(svg_icon(_SVG_CHEVRON, THEME['TEXT'], 12, 2.2))
        self.sort_btn.setIconSize(QSize(12, 12))
        self.sort_btn.setStyleSheet(_pill_css(False))
        from tilauscope.cave.viewer_detail import menu_qss  # noqa: PLC0415
        menu = QMenu(self.sort_btn)
        menu.setStyleSheet(menu_qss())
        for key, text, tip in (
                (SORT_TO_ROAST, QApplication.translate("tilauscope_beancave", "To roast first"),
                 QApplication.translate("tilauscope_beancave",
                                        "Storage risk first (water activity), then the oldest harvest, "
                                        "then the coffee left longest since its last roast.")),
                (SORT_NAME, QApplication.translate("tilauscope_beancave", "Name"), "")):
            act = menu.addAction(text)
            act.setToolTip(tip)
            act.triggered.connect(lambda _=False, k=key: self._set_sort(k))
        menu.setToolTipsVisible(True)
        self.sort_btn.setMenu(menu)
        self._label_sort()
        filters.addWidget(self.sort_btn)
        filters.addStretch(1)
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

        # Out-of-stock coffees, folded away behind one line while « In stock » is on.
        self._out_btn = QPushButton()
        self._out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._out_btn.setIcon(svg_icon("M9 6l6 6-6 6", _DIM, 12, 2.2))
        self._out_btn.setStyleSheet(
            f"QPushButton {{ background:transparent;color:{THEME['OVERLAY0']};text-align:left;"
            f"border:1px dashed {THEME['SURFACE1']};border-radius:8px;padding:7px 12px;font-size:12px; }}"
            f"QPushButton:hover {{ color:{THEME['TEXT']};border-color:{THEME['ACCENT']}; }}")
        self._out_btn.clicked.connect(lambda: self.stock_btn.setChecked(False))
        out_wrap = QHBoxLayout()
        out_wrap.setContentsMargins(14, 8, 14, 8)
        out_wrap.addWidget(self._out_btn)
        self._rows_lay.addLayout(out_wrap)
        self._rows_lay.addStretch(1)

        self._scroll.setWidget(self._rows_host)
        root.addWidget(self._scroll, 1)

    # ── public API (used by the beancave hooks) ──────────────────────────────
    def set_beans(self, beans: list) -> None:
        """Rebuild the rows, preserving selection and the active filter."""
        for row in self._rows:
            self._rows_lay.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows = []
        memories: dict[str, Any] = {}
        if self.memory_for is not None:
            try:
                memories = self.memory_for()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception("catalogue roast facts unavailable")
        for i, bean in enumerate(beans):
            try:
                row = _BeanRow(i, bean, memories.get(getattr(bean, 'uuid', '') or ''))
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                _logd.exception("catalogue row %s skipped", i)
                continue
            row.clicked.connect(self._on_row_clicked)
            row.double_clicked.connect(self.rowDoubleClicked)
            self._rows.append(row)
        self._place_rows()
        row = self._row_for(self._selected)
        if row is None:
            self._selected = -1
        else:
            row.set_selected(True)
        self._apply_filter()

    def _row_for(self, index: int):  # noqa: ANN202
        """The row of bean `index`: a skipped row shifts positions, not bean indices."""
        return next((row for row in self._rows if row._index == index), None)

    def first_visible_index(self) -> int:
        """Return the first matching bean's source index, in the order shown."""
        return next((row._index for row in self._rows if not row.isHidden()), -1)

    def select_index(self, index: int) -> None:
        """Mirror a programmatic datatable selection — never re-emits."""
        if index == self._selected:
            return
        previous = self._row_for(self._selected)
        if previous is not None:
            previous.set_selected(False)
        row = self._row_for(index)
        self._selected = index if row is not None else -1
        if row is not None:
            row.set_selected(True)
            self._scroll.ensureWidgetVisible(row, 0, 40)

    # ── internals ────────────────────────────────────────────────────────────
    def _place_rows(self) -> None:
        """Lay the rows out in the chosen order; out of stock always last."""
        if self._sort == SORT_NAME:
            self._rows.sort(key=lambda r: (not r.in_stock, r.name_key))
        else:
            self._rows.sort(key=lambda r: r.order)
        for position, row in enumerate(self._rows):
            self._rows_lay.removeWidget(row)
            self._rows_lay.insertWidget(position, row)

    def _set_sort(self, key: str) -> None:
        self._sort = key
        QSettings().setValue(_SORT_KEY, key)
        self._label_sort()
        self._place_rows()
        self._apply_filter()

    def _label_sort(self) -> None:
        names = {SORT_TO_ROAST: QApplication.translate("tilauscope_beancave", "To roast first"),
                 SORT_NAME: QApplication.translate("tilauscope_beancave", "Name")}
        self.sort_btn.setText(QApplication.translate("tilauscope_beancave", "Sort: {0}").format(
            names.get(self._sort, names[SORT_TO_ROAST])))

    def _on_stock_toggled(self, checked: bool) -> None:
        QSettings().setValue("tilauscope/beancave_stock_filter", bool(checked))
        self._label_stock()
        self._apply_filter()

    def _label_stock(self) -> None:
        """The filter names what it shows, the way the sort names its order."""
        self.stock_btn.setText(
            QApplication.translate("tilauscope_beancave", "Show: in stock") if self.stock_btn.isChecked()
            else QApplication.translate("tilauscope_beancave", "Show: all coffees"))

    def _on_row_clicked(self, index: int) -> None:
        self.select_index(index)
        self.rowActivated.emit(index)

    def _apply_filter(self) -> None:
        needle = self.search_edit.text().strip().lower()
        stock_only = self.stock_btn.isChecked()
        visible = 0
        folded = 0
        for row in self._rows:
            match = not needle or needle in row.haystack
            show = match and (not stock_only or row.in_stock)
            folded += int(match and stock_only and not row.in_stock)
            row.setVisible(show)
            visible += int(show)
        self._empty_lbl.setVisible(bool(self._rows) and visible == 0 and folded == 0)
        self._out_btn.setText(QApplication.translate("tilauscope_beancave", "Out of stock · {0} coffees").format(folded))
        self._out_btn.setVisible(folded > 0)

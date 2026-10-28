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

"""Frameless rounded card dialog and its building blocks, shared by Backup/Restore and Share coffee."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QStackedWidget, QVBoxLayout, QWidget)

from tilauscope.theme_qss import apply_tilau_theme, tint
from tilauscope.tilauscope_types import THEME

CARD_QSS = f"""
    #TilauCard {{ background:{THEME['BG']}; border:1px solid {THEME['BORDER']}; border-radius:12px; }}
    #TilauCardHeader {{ background:{THEME['SURFACE']}; border-top-left-radius:12px; border-top-right-radius:12px;
                     border-bottom:1px solid {THEME['BORDER']}; }}
    QLabel {{ background:transparent; border:none; }}
    QLabel#body {{ color:{THEME['SUBTEXT']}; font-size:13px; }}
    QLabel#path {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']}; border-radius:8px;
                   padding:9px 12px; font-size:12px; }}
    QFrame#tile {{ background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']}; border-radius:10px; }}
    QFrame#warn {{ background:{tint('WARNING', 0.10)}; border:1px solid {tint('WARNING', 0.45)};
                   border-radius:10px; }}
    QFrame#status {{ background:{THEME['SURFACE']}; border-radius:8px; }}
    QPushButton#restore {{ background:{THEME['WARNING']}; color:{THEME['BG']}; border:none; font-weight:600;
                           border-radius:20px; padding:10px 22px; }}
    QPushButton#restore:hover {{ background:{THEME['YELLOW']}; }}
    QPushButton[variant="primary"] {{ border-radius:20px; padding:10px 22px; }}
    QProgressBar {{ background:{THEME['BORDER']}; border:none; border-radius:4px; max-height:8px; }}
    QProgressBar::chunk {{ background:{THEME['ACCENT']}; border-radius:4px; }}
"""


def card_label(text: str, name: str = "", variant: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    if variant:
        label.setProperty("variant", variant)
    return label


def set_path(label: QLabel, path: str, width: int = 360) -> None:
    """One line, shortened in the middle: the folder name at the end is what tells folders apart."""
    label.setWordWrap(False)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setText(label.fontMetrics().elidedText(path, Qt.TextElideMode.ElideMiddle, width))
    label.setToolTip(path)


def card_separator() -> QFrame:
    line = QFrame()
    line.setProperty("variant", "sep")
    line.setFixedHeight(1)
    return line


def card_button(text: str, variant: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        button.setProperty("variant", variant)
    return button


class CardDialog(QDialog):
    """Frameless rounded card with a draggable title strip and ✕."""

    def __init__(self, parent: QWidget | None, title: str) -> None:
        super().__init__(parent)
        apply_tilau_theme(self, ground=False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setFixedWidth(620)
        self._drag: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("TilauCard")
        card.setStyleSheet(CARD_QSS)
        outer.addWidget(card)
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        header = QFrame()
        header.setObjectName("TilauCardHeader")
        header.setFixedHeight(44)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 8, 0)
        row.addWidget(card_label(title, variant="title"), 1)
        close = card_button("✕")
        close.setFixedSize(28, 28)
        close.setProperty("variant", "icon")
        close.setToolTip(QApplication.translate("Button", "Close"))
        close.clicked.connect(self.close)
        row.addWidget(close)
        column.addWidget(header)

        self.pages = QStackedWidget()
        column.addWidget(self.pages)

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.fit()

    def fit(self) -> None:
        """Size the card to the page shown: wrapped labels do not pass their height through the stack."""
        page = self.pages.currentWidget()
        if page is None or page.layout() is None:
            return
        layout = page.layout()
        width = self.width() - 2
        height = layout.heightForWidth(width) if layout.hasHeightForWidth() else layout.sizeHint().height()
        self.pages.setFixedHeight(max(height, layout.minimumSize().height()))
        self.adjustSize()

    def showEvent(self, a0: Any) -> None:  # noqa: N802
        super().showEvent(a0)
        self.fit()

    def page(self) -> QVBoxLayout:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(14)
        self.pages.addWidget(widget)
        return layout

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is not None and event.button() == Qt.MouseButton.LeftButton and event.position().y() < 44:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # noqa: N802
        if event is not None and self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event: QMouseEvent | None) -> None:  # noqa: N802
        self._drag = None

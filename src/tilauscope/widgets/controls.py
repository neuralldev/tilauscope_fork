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

"""Ways to set a number: pick it from a column, or hold a button down."""

from __future__ import annotations

import time

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QFrame, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from tilauscope.tilauscope_types import THEME


class SmartRoller(QWidget):
    def __init__(self, current_val, color, callback, min_val:int = 0, max_val:int = 100, step:int=1):
        super().__init__(None)
        self.callback = callback
        self.color = color
        self.min_val = min_val
        # 1. Set flags for a popup
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)

        # 2. Re-enable Translucent Background (allows the 'corners' to be invisible)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 3. Ensure we DON'T auto-fill the background (which creates the square box)
        self.setAutoFillBackground(False)

        self.setFixedSize(75, 350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)
        self.container = QFrame()
        self.container.setObjectName("MainContainer") # Ensure ID matches CSS
        self.container.setStyleSheet(f"""
            #MainContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 6px;
            }}
            QScrollBar:horizontal {{
                height: 0px;
                background: transparent;
            }}
            QWidget {{ border: none; }}
        """)
        layout.addWidget(self.container)
        scroll_layout = QVBoxLayout(self.container)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        # One sheet for the whole column, not one per entry. The SV roller spans
        # 0-250 in Celsius and 0-482 in Fahrenheit, so styling each button by
        # itself meant several hundred stylesheet parses between the click and
        # the popup appearing. The selected entry is told apart by a property
        # the selector below reads, which costs nothing to set.
        self.content.setStyleSheet(f"""
            QPushButton {{
                color: {THEME['OVERLAY0']};
                border: none;
                font-size: 14px;
                background: transparent;
            }}
            QPushButton[current="true"] {{
                color: white;
                font-size: 16px;
                font-weight: bold;
                background-color: {color};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                color: white;
                background: {THEME['BORDER']};
                border-radius: 8px;
            }}
        """)
        self._current_btn: QPushButton | None = None
        _closest: int | None = None
        for i in range(min_val, max_val+1, step): # fix 2026/05/02 added step support
            btn = QPushButton(str(i))
            btn.setFixedHeight(38)
            btn.setProperty('current', 'true' if i == current_val else 'false')
            btn.setProperty('roller_value', i)
            # A shared slot rather than one closure per entry: the value travels
            # on the button that was pressed.
            btn.clicked.connect(self._on_entry_clicked)
            self.content_layout.addWidget(btn)
            # Kept for the centring below. Nearest rather than equal, so a value
            # that sits between two steps still opens somewhere sensible.
            gap = abs(i - current_val)
            if _closest is None or gap < _closest:
                _closest, self._current_btn = gap, btn
        self.scroll.setWidget(self.content)
        scroll_layout.addWidget(self.scroll)
        self.current_val = current_val
        # Deferred: the column has no geometry until the layout has run, and the
        # scroll area no viewport height until it has been shown.
        QTimer.singleShot(50, self._centre_on_current)

    def _centre_on_current(self) -> None:
        """Bring the current value to the middle of the visible window.

        Measured off the entry itself. The arithmetic this replaces multiplied
        by a fixed 52 px where an entry occupies 44 (38 tall, 6 of spacing), and
        counted values rather than entries — so a roller stepping by 5 was out
        by a further factor of five, and the value the operator came to change
        opened off screen.
        """
        if self._current_btn is None:
            return
        self.content_layout.activate()
        # setValue clamps, so the first and last entries settle against the ends
        # instead of leaving the column hanging off the edge.
        self.scroll.verticalScrollBar().setValue(
            self._current_btn.y() + self._current_btn.height() // 2
            - self.scroll.viewport().height() // 2
        )

    def _on_entry_clicked(self) -> None:
        """Read the value off the button that was pressed."""
        btn = self.sender()
        if btn is None:
            return
        self.select_value(int(btn.property('roller_value')))

    def select_value(self, val):
                self.callback(val)
                self.close()


class ClickableValue(QLabel):
    # Added release_callback and index to the parameters
    def __init__(self, value, color, slider_ref, unit, index, release_callback, min_val=0, max_val=100, step:int =1):
        super().__init__(f"{value}{unit}")
        self.color = color
        self.slider_ref = slider_ref
        self.min_val = min_val
        self.max_val = max_val
        self.index = index  # Store which slider this is
        self.step = step
        self.release_callback = release_callback  # Store reference to handle_ui_input_released
        self.setFixedWidth(55)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_style()

    def update_style(self, highlight=False):
        style = "font-weight: bold; font-size: 15px; border: none;"
        # QLabel:disabled — the value stays readable but stops claiming a colour
        # it can no longer act on (control out of reach).
        dim = f"QLabel:disabled {{ color: {THEME['SURFACE2']}; background: transparent; }}"
        if highlight: self.setStyleSheet(f"QLabel {{ color: {THEME['CRUST']}; background-color: {self.color}; border-radius: 4px; {style} }} {dim}")
        else: self.setStyleSheet(f"QLabel {{ color: {self.color}; background: transparent; {style} }} {dim}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToGlobal(QPoint(-85, -110))
            self.roller = SmartRoller(self.slider_ref.value(), self.color, self.set_new_value, self.min_val, self.max_val, self.step)
            self.roller.move(pos)
            self.roller.show()

    def set_new_value(self, val):
        self.slider_ref.setValue(val)

        # --- Inform Artisan of the change ---
        if self.release_callback:
            self.release_callback(self.index)

        self.update_style(True)
        QTimer.singleShot(150, lambda: self.update_style(False))


class HoldToFireButton(QPushButton):
    """Header button that fires only once the pointer is held down for
    `hold_ms`. A red sweep fills the button while the press lasts; releasing
    or leaving the button early cancels without firing.

    Used by the emergency heat cut: a stray click must not end a live roast,
    and a confirmation dialog is not an option in the middle of one.
    """

    fired = pyqtSignal()

    def __init__(self, text: str = "", hold_ms: int = 1000, parent=None) -> None:
        super().__init__(text, parent)
        self._hold_ms = max(200, int(hold_ms))
        self._progress = 0.0
        self._t0 = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(30)
        self._tick.timeout.connect(self._advance)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._t0 = time.monotonic()
            self._progress = 0.0
            self._tick.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._abort()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._abort()   # dragged off the button: deliberate way out
        super().leaveEvent(event)

    def _abort(self) -> None:
        self._tick.stop()
        if self._progress:
            self._progress = 0.0
            self.update()

    def _advance(self) -> None:
        self._progress = min(1.0, (time.monotonic() - self._t0) * 1000.0 / self._hold_ms)
        self.update()
        if self._progress >= 1.0:
            self._tick.stop()
            self._progress = 0.0
            self.update()
            self.fired.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._progress <= 0.0:
            return
        rect = self.rect().adjusted(2, 2, -2, -2)
        rect.setWidth(max(1, int(rect.width() * self._progress)))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(243, 139, 168, 120))   # CRITICAL, translucent
        painter.drawRoundedRect(rect, 6, 6)
        painter.end()

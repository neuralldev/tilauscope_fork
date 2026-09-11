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

"""Text that does not fit, and text that answers a click."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget

from tilauscope.theme_qss import mono_family


class TickerLabel(QWidget):
    """
    Widget d'une ligne qui fait défiler son texte horizontalement si le contenu
    dépasse la largeur disponible. Statique si le texte est court.

    Drop-in pour QLabel monoligne — supporte setText(), text(),
    setStyleSheet() et setAlignment().

    Impact temps réel : nul — timer inactif si texte court, 40ms/tick sinon.
    """
    _SPEED_PX   = 1     # pixels par tick
    _PAUSE_TICK = 50    # ticks de pause à chaque extrémité (~2 s à 40 ms)
    _INTERVAL   = 40    # ms entre chaque tick

    def __init__(
        self,
        height: int = 18,
        color: str = "#A6E3A1",
        font_size: int = 11,
        font_weight: int = 700,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        _mono = mono_family()
        self._lbl = QLabel("", self)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._lbl.setStyleSheet(
            f"color: {color}; font-size: {font_size}px; font-weight: {font_weight};"
            f"font-family: '{_mono}', 'JetBrains Mono', monospace;"
            f"border: none; background: transparent;"
        )
        self._lbl.move(0, 0)
        self._lbl.setFixedHeight(height)

        self._offset: int    = 0
        self._direction: int = 1
        self._pause: int     = 0
        self._overflow: int  = 0

        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str) -> None:
        self._lbl.setText(text)
        self._lbl.adjustSize()
        self._offset    = 0
        self._direction = 1
        self._pause     = self._PAUSE_TICK
        self._lbl.move(0, 0)
        self._overflow = max(0, self._lbl.width() - self.width())
        if self._overflow > 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def setStyleSheet(self, style: str) -> None:  # type: ignore[override]
        """Forward stylesheet to internal label (color changes, etc.).

        Callers only ever pass color/weight tweaks; the JetBrains Mono
        font-family set in __init__ must survive those, so it's re-appended
        here rather than relying on every call site to repeat it.
        """
        _mono = mono_family()
        self._lbl.setStyleSheet(f"{style} font-family: '{_mono}', 'JetBrains Mono', monospace;")
        self._lbl.adjustSize()
        self._overflow = max(0, self._lbl.width() - self.width())

    def setAlignment(self, flag) -> None:  # type: ignore[override]
        self._lbl.setAlignment(flag)

    def text(self) -> str:
        return self._lbl.text()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._lbl.setFixedHeight(self.height())
        self._overflow = max(0, self._lbl.width() - self.width())
        if self._overflow <= 0:
            self._timer.stop()
            self._lbl.move(0, 0)

    def _tick(self) -> None:
        if self._pause > 0:
            self._pause -= 1
            return
        self._offset += self._direction * self._SPEED_PX
        if self._offset >= self._overflow:
            self._offset    = self._overflow
            self._direction = -1
            self._pause     = self._PAUSE_TICK
        elif self._offset <= 0:
            self._offset    = 0
            self._direction = 1
            self._pause     = self._PAUSE_TICK
        self._lbl.move(-self._offset, 0)


class ClickableLabel(QLabel):
    clicked = pyqtSignal()  # Define a custom signal

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

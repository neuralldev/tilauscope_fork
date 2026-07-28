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
# -*- coding: utf-8 -*-

"""
tilau_loading_overlay.py
~~~~~~~~~~~~~~~~~~~~~~~~
Animated roaster-drum loading indicator for TilauScope.

Two public classes:
  - TilauRoasterSplash  : QSplashScreen subclass for Artisan startup
                          (before aw is visible)
  - TilauRoasterOverlay : Frameless QWidget overlay on top of aw,
                          used during BeancaveDlg / TilauScope __init__

Both share _RoasterAnimWidget for the actual drum + orbiting bean drawing.
"""

from __future__ import annotations

import math
from typing import Final

from PyQt6.QtCore import (
    Qt, QTimer, QRect, QPointF, QRectF, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QPixmap,
    QRadialGradient, QPainterPath, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QSplashScreen, QLabel, QVBoxLayout,
)

# ── Catppuccin Mocha palette constants ──────────────────────────────────────
_BASE:    Final[str] = "#1E1E2E"
_SURFACE: Final[str] = "#313244"
_OVERLAY: Final[str] = "#6C7086"
_LAVENDER:Final[str] = "#B4BEFE"
_MAUVE:   Final[str] = "#CBA6F7"
_PEACH:   Final[str] = "#FAB387"
_TEXT:    Final[str] = "#CDD6F4"
_SUBTEXT: Final[str] = "#A6ADC8"

# ── Animation constants ──────────────────────────────────────────────────────
_FPS:        Final[int]   = 25          # frames per second (40 ms tick)
_TICK_MS:    Final[int]   = 1000 // _FPS
_DRUM_RPM:   Final[float] = 30.0        # drum rotation speed (visual)
_ORBIT_RPM:  Final[float] = 45.0        # bean orbit speed
_DEG_PER_TICK_DRUM:  Final[float] = _DRUM_RPM  * 360.0 / 60.0 / _FPS
_DEG_PER_TICK_ORBIT: Final[float] = _ORBIT_RPM * 360.0 / 60.0 / _FPS


# ── Core animation widget (shared) ──────────────────────────────────────────

class _RoasterAnimWidget(QWidget):
    """
    Draws a stylised roaster drum with a coffee bean orbiting inside.
    Size-independent — scales to whatever the parent assigns.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drum_angle:  float = 0.0
        self._orbit_angle: float = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._drum_angle  = (self._drum_angle  + _DEG_PER_TICK_DRUM)  % 360.0
        self._orbit_angle = (self._orbit_angle + _DEG_PER_TICK_ORBIT) % 360.0
        self.update()

    # ── Painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        w, h = self.width(), self.height()
        size = min(w, h)
        cx, cy = w / 2.0, h / 2.0

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Outer drum ring ──────────────────────────────────────────────────
        drum_r: float = size * 0.38
        self._draw_drum(p, cx, cy, drum_r)

        # ── Orbiting bean ───────────────────────────────────────────────────
        orbit_rx: float = drum_r * 0.55   # ellipse x radius
        orbit_ry: float = drum_r * 0.32   # ellipse y radius (flattened)
        rad = math.radians(self._orbit_angle)
        bx = cx + orbit_rx * math.cos(rad)
        by = cy + orbit_ry * math.sin(rad)
        bean_r = size * 0.072
        self._draw_bean(p, bx, by, bean_r, self._orbit_angle)

        # ── Centre hub ──────────────────────────────────────────────────────
        hub_r = size * 0.065
        self._draw_hub(p, cx, cy, hub_r)

        p.end()

    # ── Drum ─────────────────────────────────────────────────────────────────

    def _draw_drum(
        self, p: QPainter, cx: float, cy: float, r: float
    ) -> None:
        # Background fill
        grad = QRadialGradient(QPointF(cx, cy), r)
        grad.setColorAt(0.0, QColor(_SURFACE))
        grad.setColorAt(1.0, QColor(_BASE))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Rotating spokes (3 fins inside the drum)
        spoke_pen = QPen(QColor(_OVERLAY), max(1.5, r * 0.03))
        spoke_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(spoke_pen)
        for i in range(3):
            angle = math.radians(self._drum_angle + i * 120.0)
            x1 = cx + (r * 0.18) * math.cos(angle)
            y1 = cy + (r * 0.18) * math.sin(angle)
            x2 = cx + (r * 0.80) * math.cos(angle)
            y2 = cy + (r * 0.80) * math.sin(angle)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Outer ring border
        rim_pen = QPen(QColor(_LAVENDER), max(2.0, r * 0.045))
        rim_pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(rim_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Small vents on the rim (heat vents dots)
        vent_brush = QBrush(QColor(_MAUVE))
        p.setBrush(vent_brush)
        p.setPen(Qt.PenStyle.NoPen)
        vent_r = r * 0.055
        for i in range(8):
            a = math.radians(self._drum_angle * 0.5 + i * 45.0)
            vx = cx + (r + vent_r * 0.3) * math.cos(a)
            vy = cy + (r + vent_r * 0.3) * math.sin(a)
            p.drawEllipse(QPointF(vx, vy), vent_r * 0.5, vent_r * 0.5)

    # ── Bean ─────────────────────────────────────────────────────────────────

    def _draw_bean(
        self, p: QPainter, cx: float, cy: float, r: float, angle: float
    ) -> None:
        # Bean body — oval shape rotated with orbit angle
        bean_grad = QRadialGradient(
            QPointF(cx - r * 0.2, cy - r * 0.2), r * 1.2
        )
        bean_grad.setColorAt(0.0, QColor(_PEACH).lighter(115))
        bean_grad.setColorAt(1.0, QColor(_PEACH).darker(140))
        p.setBrush(QBrush(bean_grad))
        p.setPen(Qt.PenStyle.NoPen)

        p.save()
        p.translate(cx, cy)
        p.rotate(angle + 30.0)   # slight tilt so bean looks natural
        # Draw bean as two overlapping ovals
        p.drawEllipse(QRectF(-r, -r * 0.65, r * 2, r * 1.3))
        # Centre crease line
        crease_pen = QPen(QColor(_PEACH).darker(170), max(1.0, r * 0.12))
        crease_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(crease_pen)
        p.drawLine(QPointF(0.0, -r * 0.55), QPointF(0.0, r * 0.55))
        p.restore()

    # ── Hub ──────────────────────────────────────────────────────────────────

    def _draw_hub(
        self, p: QPainter, cx: float, cy: float, r: float
    ) -> None:
        hub_grad = QRadialGradient(QPointF(cx, cy), r)
        hub_grad.setColorAt(0.0, QColor(_LAVENDER))
        hub_grad.setColorAt(1.0, QColor(_MAUVE).darker(130))
        p.setBrush(QBrush(hub_grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)


# ── Splash screen (Artisan startup) ─────────────────────────────────────────

class TilauRoasterSplash(QSplashScreen):
    """
    Frameless splash shown before aw.show().
    Usage:
        splash = TilauRoasterSplash()
        splash.show()
        app.processEvents()
        # … heavy init …
        splash.finish(aw)
    """

    _SPLASH_SIZE: Final[int] = 380

    def __init__(self) -> None:
        # QSplashScreen needs a QPixmap — we give it a blank one;
        # actual drawing is done in drawContents().
        px = QPixmap(self._SPLASH_SIZE, self._SPLASH_SIZE)
        px.fill(QColor(_BASE))
        super().__init__(px, Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._anim = _RoasterAnimWidget(self)
        self._anim.setGeometry(
            0,
            40,
            self._SPLASH_SIZE,
            self._SPLASH_SIZE - 80,
        )

        # Product label
        self._lbl = QLabel(
            QApplication.translate("tilauscope_beancave", "TilauScope is loading…"),
            self,
        )
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet(
            f"color: {_SUBTEXT}; font-family: 'JetBrains Mono', monospace;"
            f" font-size: 13px; background: transparent;"
        )
        self._lbl.setGeometry(0, self._SPLASH_SIZE - 42, self._SPLASH_SIZE, 32)

    def drawContents(self, painter: QPainter) -> None:  # type: ignore[override]
        # Fill background (called by Qt on repaint)
        painter.fillRect(self.rect(), QColor(_BASE))

    def set_message(self, msg: str) -> None:
        """Update the status label text."""
        self._lbl.setText(msg)
        QApplication.processEvents()

    def close_and_stop(self) -> None:
        self._anim.stop()
        self.close()


# ── Overlay widget (BeancaveDlg / TilauScope init) ──────────────────────────

class TilauRoasterOverlay(QWidget):
    """
    Semi-transparent overlay covering ``aw`` while a heavy init runs.

    Usage (BeancaveDlg example):
        self._loading = TilauRoasterOverlay(aw)
        self._loading.show_over(aw)
        # … heavy __init__ work …
        self._loading.dismiss()    # call from showEvent or after init

    Always call dismiss() even if an exception occurs.
    """

    _OVERLAY_ALPHA: Final[int] = 210   # 0-255

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._anim = _RoasterAnimWidget(self)

        self._lbl = QLabel(
            QApplication.translate("tilauscope_beancave", "Loading…"),
            self,
        )
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet(
            f"color: {_TEXT}; font-family: 'JetBrains Mono', monospace;"
            f" font-size: 14px; background: transparent;"
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def show_over(self, target: QWidget, message: str = "") -> None:
        """
        Position and show the overlay on top of *target*.
        Call processEvents() after to ensure it paints before the heavy work.
        """
        geo = target.geometry()
        self.setGeometry(0, 0, geo.width(), geo.height())
        if message:
            self._lbl.setText(message)
        self._layout_children(geo.width(), geo.height())
        self.show()
        self.raise_()
        QApplication.processEvents()

    def set_message(self, msg: str) -> None:
        self._lbl.setText(msg)
        QApplication.processEvents()

    def dismiss(self) -> None:
        """Stop animation and close (widget is WA_DeleteOnClose)."""
        self._anim.stop()
        self.close()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _layout_children(self, w: int, h: int) -> None:
        anim_size = min(w, h) // 2
        ax = (w - anim_size) // 2
        ay = (h - anim_size) // 2 - 20
        self._anim.setGeometry(ax, ay, anim_size, anim_size)
        self._lbl.setGeometry(0, ay + anim_size + 8, w, 28)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_children(self.width(), self.height())

    # ── Background fill ──────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(_BASE)
        bg.setAlpha(self._OVERLAY_ALPHA)
        p.fillRect(self.rect(), bg)
        p.end()
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
"""Shared painting base for BeanCave's shareable cards.

Both the green bean card (``beancave_social_card``) and the roast card
(``beancave_roast_card``) are 1200x630 landscape JPEGs — the safe open-graph
ratio for X, Facebook and LinkedIn — drawn with QPainter on a QImage and built
from the same parts: the bundled JetBrains Mono faces, a surface identity
column on the left, and the TilauScope signature at its foot.

This module owns what they have in common so the two cards cannot drift apart
visually. Card-specific content lives in the subclasses.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from tilauscope.tilauscope_types import THEME

_logd = logging.getLogger('tilaudebug')

# ── Export geometry, shared by every card ────────────────────────────────────
CARD_W = 1200
CARD_H = 630
JPEG_QUALITY = 92


class CardPainter:
    """QPainter primitives and chrome shared by the BeanCave cards."""

    def __init__(self) -> None:
        self._reg, self._bold = self._load_fonts()

    # ── fonts ────────────────────────────────────────────────────────────────
    @staticmethod
    def _load_fonts() -> tuple[str, str]:
        """Register the bundled JetBrains Mono faces; fall back to a mono default."""
        here = Path(__file__).parent
        families = []
        for fname in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"):
            fam = "Courier New"
            try:
                fid = QFontDatabase.addApplicationFont(str(here / fname))
                if fid != -1:
                    fam = QFontDatabase.applicationFontFamilies(fid)[0]
            except Exception:
                _logd.error("card: failed to load %s", fname)
            families.append(fam)
        return families[0], families[1]

    def _font(self, size: int, bold: bool = False, tracking: float = 0.0) -> QFont:
        f = QFont(self._bold if bold else self._reg, size)
        f.setBold(bold)
        if tracking:
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0 + tracking)
        return f

    # ── low level paint helpers ──────────────────────────────────────────────
    @staticmethod
    def _rrect(p: QPainter, rect: QRectF, radius: float,
               fill: str | None = None, stroke: str | None = None) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if fill:
            p.fillPath(path, QBrush(QColor(fill)))
        if stroke:
            p.strokePath(path, QPen(QColor(stroke), 1))

    def _text(self, p: QPainter, x: int, y: int, text: str, font: QFont,
              color: str) -> int:
        """Draw ``text`` with its top edge at ``y``. Returns the bottom edge."""
        p.setFont(font)
        p.setPen(QColor(color))
        fm = QFontMetrics(font)
        p.drawText(x, y + fm.ascent(), text)
        return y + fm.height()

    @staticmethod
    def _wrap(text: str, font: QFont, max_w: int, max_lines: int = 3) -> list[str]:
        """Word-wrap to at most ``max_lines``.

        Truncation is always signalled: when words are left over the last line
        is elided with an ellipsis, so a long name never loses its tail in
        silence.
        """
        fm = QFontMetrics(font)
        words = text.split()
        lines: list[str] = []
        cur = ""
        i = 0
        while i < len(words):
            probe = f"{cur} {words[i]}".strip()
            if fm.horizontalAdvance(probe) <= max_w or not cur:
                cur = probe
                i += 1
            elif len(lines) + 1 < max_lines:
                lines.append(cur)
                cur = ""
            else:
                break
        if cur:
            lines.append(cur)
        if i < len(words) and lines:
            ## TILAU ## words left over: force the ellipsis onto the last line
            lines[-1] = fm.elidedText(lines[-1] + " " + " ".join(words[i:]),
                                      Qt.TextElideMode.ElideRight, max_w)
        return lines

    def _elided(self, p: QPainter, x: int, y: int, text: str, font: QFont,
                color: str, max_w: int) -> int:
        fm = QFontMetrics(font)
        return self._text(p, x, y, fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w),
                          font, color)

    # ── shared chrome ────────────────────────────────────────────────────────
    def _flow_badges(self, p: QPainter, x: int, y: int, max_w: int,
                     badges: list[tuple[str, str]], size: int = 10,
                     height: int = 26) -> int:
        """Outlined badges flowing onto as many rows as needed."""
        font = self._font(size, tracking=8.0)
        fm = QFontMetrics(font)
        cx, cy = x, y
        for label, colour in badges:
            bw = fm.horizontalAdvance(label) + 22
            if cx + bw > x + max_w and cx > x:
                cx, cy = x, cy + height + 8
            self._rrect(p, QRectF(cx, cy, bw, height), 5, stroke=colour)
            p.setFont(font)
            p.setPen(QColor(THEME['SUBTEXT'] if colour == THEME['BORDER'] else colour))
            p.drawText(QRectF(cx, cy, bw, height), Qt.AlignmentFlag.AlignCenter, label)
            cx += bw + 8
        return cy + height

    def _paint_brand(self, p: QPainter, x: int, tagline: str, size: int = 11) -> None:
        """The TilauScope signature at the foot of the identity column."""
        y = CARD_H - 36 - 14
        p.setBrush(QBrush(QColor(THEME['ACCENT'])))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(x, y + 5, 9, 9)
        p.setBrush(Qt.BrushStyle.NoBrush)
        bold = self._font(size, bold=True)
        p.setFont(bold)
        p.setPen(QColor(THEME['TEXT']))
        fm = QFontMetrics(bold)
        p.drawText(x + 19, y + fm.ascent() + 1, "TilauScope")
        w = fm.horizontalAdvance("TilauScope")
        if tagline:
            self._text(p, x + 19 + w, y + 1, f" · {tagline}", self._font(size),
                       THEME['SUBTEXT'])

    # ── image lifecycle ──────────────────────────────────────────────────────
    @staticmethod
    def _new_image() -> QImage:
        img = QImage(CARD_W, CARD_H, QImage.Format.Format_RGB32)
        img.fill(QColor(THEME['BG']))
        return img

    @staticmethod
    def _begin(img: QImage) -> QPainter:
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        return p

    @staticmethod
    def _save(img: QImage, file_path: str) -> bool:
        try:
            return img.save(file_path, "JPG", JPEG_QUALITY)
        except Exception:
            _logd.error("card: save failed", exc_info=True)
            return False

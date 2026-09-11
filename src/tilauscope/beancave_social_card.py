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

"""Shareable green bean card for BeanCave: renders a bean record as a 1200x630 JPEG.

Layout mirrors the on-screen bean sheet; empty fields are omitted rather than shown as a dash or zero tile.
"""

from __future__ import annotations

import logging
import re

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from tilauscope.beancave_card_base import CARD_H, CARD_W, CardPainter
from tilauscope.tilauscope_types import THEME

_logd = logging.getLogger('tilaudebug')

_LEFT_W = 462          # surface column width
_PAD_L = 40            # left column horizontal padding
_PAD_R = 44            # right column horizontal padding
_PAD_TOP = 48


class GreenBeanSocialCard(CardPainter):
    """Paints a :class:`GreenBean` onto a landscape card image."""

    # ── content extraction ───────────────────────────────────────────────────
    @staticmethod
    def _flavour_chips(bean) -> list[str]:
        raw = (getattr(bean, 'flavour_notes', '') or '').strip()
        if not raw:
            return []
        parts = [c.strip() for c in re.split(r'[,;\n/·]+', raw) if c.strip()]
        return parts[:6]

    def _badges(self, bean) -> list[tuple[str, str]]:
        """(label, colour) badges — process is the one that carries a hue.

        A blend carries no BLEND badge: the origin eyebrow already says it.
        """
        out: list[tuple[str, str]] = []
        if (bean.process or '').strip():
            out.append((bean.process.strip(), THEME['WARNING']))
        if (bean.species or '').strip():
            out.append((bean.species.strip(), THEME['BORDER']))
        crop = int(getattr(bean, 'crop', 0) or 0)
        if crop > 0:
            crop_label = QApplication.translate("tilauscope_roast_review", "Crop")
            out.append((f"{crop_label} {crop}", THEME['BORDER']))
        return out[:4]

    @staticmethod
    def _stats(bean) -> list[tuple[str, str, str, bool]]:
        """(key, value, unit, highlight) — zero/empty metrics are dropped."""
        out: list[tuple[str, str, str, bool]] = []
        sca = float(getattr(bean, 'sca', 0) or 0)
        if sca > 0:
            out.append((QApplication.translate("tilauscope_roast_review", "SCA score"), f"{sca:.1f}".rstrip('0').rstrip('.'), "", True))
        alt = int(getattr(bean, 'altitude', 0) or 0)
        if alt > 0:
            out.append((QApplication.translate("tilauscope_roast_review", "Altitude"), f"{alt:,}".replace(",", " "), "m", False))
        dens = float(getattr(bean, 'density', 0) or 0)
        if dens > 0:
            out.append((QApplication.translate("tilauscope_roast_review", "Density"), f"{dens:g}", "g/l", False))
        hum = float(getattr(bean, 'last_humidity', 0) or 0)
        if hum > 0:
            out.append((QApplication.translate("tilauscope_roast_review", "Humidity"), f"{hum:g}", "%", False))
        return out[:4]

    @staticmethod
    def _provenance(bean) -> list[tuple[str, str]]:
        rows = [(QApplication.translate("tilauscope_roast_review", "Farm"), bean.farm), (QApplication.translate("tilauscope_roast_review", "Country"), bean.country),
                (QApplication.translate("tilauscope_roast_review", "Supplier"), bean.supplier)]
        return [(k, str(v).strip()) for k, v in rows if str(v or '').strip()]

    @staticmethod
    def _characteristics(bean) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        if (bean.species or '').strip():
            rows.append((QApplication.translate("tilauscope_roast_review", "Species"), bean.species.strip()))
        # a blend shows its composition where a single origin shows varieties.
        # Same semantics as the on-screen sheet: component 1 is the record itself
        # (labelled by its varieties), and a 0 ratio means "unknown", not "absent".
        if getattr(bean, 'is_blend', False):
            comps = [((bean.varieties or bean.name or "?").strip(),
                      float(getattr(bean, 'bean1_ratio', 0) or 0))]
            for name, ratio in ((bean.bean2_name, getattr(bean, 'bean2_ratio', 0)),
                                (bean.bean3_name, getattr(bean, 'bean3_ratio', 0))):
                name, ratio = str(name or '').strip(), float(ratio or 0)
                if name or ratio > 0:
                    comps.append((name or "?", ratio))
            rows.append((QApplication.translate("tilauscope_roast_review", "Composition"), " · ".join(
                f"{n} {r:g}%" if r > 0 else n for n, r in comps)))
        elif (bean.varieties or '').strip():
            rows.append((QApplication.translate("tilauscope_roast_review", "Varieties"), bean.varieties.strip()))
        if (bean.category or '').strip():
            rows.append((QApplication.translate("tilauscope_roast_review", "Category"), bean.category.strip()))
        aw = float(getattr(bean, 'water_activity', 0) or 0)
        if aw > 0:
            rows.append((QApplication.translate("tilauscope_roast_review", "Water activity"), f"{aw:g} aw"))
        return rows[:4]

    # ── columns ──────────────────────────────────────────────────────────────
    def _paint_left(self, p: QPainter, bean) -> None:
        x, w = _PAD_L, _LEFT_W - 2 * _PAD_L
        p.fillRect(QRect(0, 0, _LEFT_W, CARD_H), QColor(THEME['SURFACE']))
        p.setPen(QPen(QColor(THEME['BORDER']), 1))
        p.drawLine(_LEFT_W, 0, _LEFT_W, CARD_H)

        y = _PAD_TOP
        origin = (QApplication.translate("tilauscope_roast_review", "Blend") if getattr(bean, 'is_blend', False)
                  else (bean.country or '').strip())
        if origin:
            y = self._text(p, x, y, origin.upper(), self._font(12, tracking=22.0),
                           THEME['ACCENT']) + 14

        name_font = self._font(38, bold=True)
        for line in self._wrap(bean.name or QApplication.translate("tilauscope_roast_review", "Unnamed bean"), name_font, w, 3):
            y = self._text(p, x, y, line, name_font, THEME['TEXT']) + 2

        badges = self._badges(bean)
        if badges:
            y += 18
            y = self._flow_badges(p, x, y, w, badges)

        chips = self._flavour_chips(bean)
        if chips:
            y += 28
            p.setPen(QPen(QColor(THEME['BORDER']), 1))
            p.drawLine(x, y, x + w, y)
            y += 26
            y = self._text(p, x, y, QApplication.translate("tilauscope_roast_review", "Flavour notes").upper(),
                           self._font(10, tracking=16.0), THEME['SUBTEXT']) + 12
            self._flow_chips(p, x, y, w, chips)

        self._paint_brand(p, x, QApplication.translate(
            "tilauscope_roast_review", "green bean sheet"))

    def _flow_chips(self, p: QPainter, x: int, y: int, max_w: int,
                    chips: list[str]) -> int:
        font = self._font(12)
        fm = QFontMetrics(font)
        cx, cy, h = x, y, 30
        for chip in chips:
            cw = fm.horizontalAdvance(chip) + 26
            if cx + cw > x + max_w and cx > x:
                cx, cy = x, cy + h + 8
            self._rrect(p, QRectF(cx, cy, cw, h), h / 2,
                        fill=THEME['BG'], stroke=THEME['BORDER'])
            p.setFont(font)
            p.setPen(QColor(THEME['TEXT']))
            p.drawText(QRectF(cx, cy, cw, h), Qt.AlignmentFlag.AlignCenter, chip)
            cx += cw + 8
        return cy + h

    _KEY_W = 172   # key column — must clear the longest label ("Water activity")

    def _paint_right(self, p: QPainter, bean, y0: int) -> int:
        """Paint the data column from ``y0``; returns the bottom edge reached."""
        x = _LEFT_W + _PAD_R
        w = CARD_W - _LEFT_W - 2 * _PAD_R
        y = y0

        stats = self._stats(bean)
        if stats:
            y = self._paint_stats(p, x, y, w, stats) + 32

        for title, rows in ((QApplication.translate("tilauscope_roast_review", "Provenance"), self._provenance(bean)),
                            (QApplication.translate("tilauscope_roast_review", "Characteristics"), self._characteristics(bean))):
            if not rows:
                continue
            y = self._text(p, x, y, title.upper(), self._font(10, tracking=16.0),
                           THEME['ACCENT']) + 9
            p.setPen(QPen(QColor(THEME['BORDER']), 1))
            p.drawLine(x, y, x + w, y)
            y += 14
            vfont = self._font(13)
            fm = QFontMetrics(vfont)
            for key, value in rows:
                self._text(p, x, y, key, self._font(13), THEME['SUBTEXT'])
                # long values (a blend composition) wrap rather than elide
                vy = y
                for line in self._wrap(value, vfont, w - self._KEY_W, 2):
                    p.setFont(vfont)
                    p.setPen(QColor(THEME['TEXT']))
                    p.drawText(x + self._KEY_W, vy + fm.ascent(), line)
                    vy += fm.height()
                y = vy + 7
            y += 22
        return y

    def _paint_stats(self, p: QPainter, x: int, y: int, w: int,
                     stats: list[tuple[str, str, str, bool]]) -> int:
        h, n = 84, len(stats)
        # cells keep a sane width when the bean has few metrics —
        # a lone SCA tile stretched over 650 px reads as a rendering bug
        cell_w = min(w / n, 176.0)
        w = cell_w * n
        self._rrect(p, QRectF(x, y, w, h), 8, fill=THEME['BG'], stroke=THEME['BORDER'])
        for i, (key, value, unit, highlight) in enumerate(stats):
            cx = x + i * cell_w
            if i:
                p.setPen(QPen(QColor(THEME['BORDER']), 1))
                p.drawLine(int(cx), y + 1, int(cx), y + h - 1)
            self._text(p, int(cx) + 15, y + 16, key.upper(),
                       self._font(9, tracking=14.0), THEME['SUBTEXT'])
            vfont = self._font(21, bold=True)
            fm = QFontMetrics(vfont)
            p.setFont(vfont)
            p.setPen(QColor(THEME['SUCCESS'] if highlight else THEME['TEXT']))
            p.drawText(int(cx) + 15, y + 40 + fm.ascent(), value)
            if unit:
                self._text(p, int(cx) + 15 + fm.horizontalAdvance(value) + 5,
                           y + 40 + fm.ascent() - QFontMetrics(self._font(11)).ascent(),
                           unit, self._font(11), THEME['SUBTEXT'])
        return y + h

    # ── public API ───────────────────────────────────────────────────────────
    def render(self, bean) -> QImage:
        img = self._new_image()
        p = self._begin(img)
        try:
            self._paint_left(p, bean)
            self._paint_right(p, bean, self._right_y0(bean))
        finally:
            p.end()
        return img

    def _right_y0(self, bean) -> int:
        """Top edge that vertically centres the data column.

        Measured by painting onto a throwaway image through the same code path, so it never drifts from the render.
        """
        scratch = QImage(1, 1, QImage.Format.Format_RGB32)
        mp = QPainter(scratch)
        try:
            height = self._paint_right(mp, bean, 0) - 22   # trailing zone gap
        finally:
            mp.end()
        if height >= CARD_H - 2 * _PAD_TOP:
            return _PAD_TOP
        return max(_PAD_TOP, int((CARD_H - height) / 2))

    def save_jpeg(self, bean, file_path: str) -> bool:
        try:
            return self._save(self.render(bean), file_path)
        except Exception:
            _logd.error("social card: render failed", exc_info=True)
            return False

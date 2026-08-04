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
"""Shareable roast card for BeanCave's roast tab (validated mock v3).

Renders a finished roast as a 1200x630 landscape JPEG, sized for social
networks and built as a sibling of the green bean card
(``beancave_social_card``): identity column on the surface at the left, data
at the right.

    LEFT  — origin + date eyebrow, bean name, process/species badges,
            a GREEN BEAN block resolved from the live BeanCave record, then a
            ROAST block opened by the roast level and closed by four figures
            (duration, DTR, charge, weight loss)
    RIGHT — the BT curve with ET behind it and RoR BT on its own right axis,
            milestones marked by a dashed line, a dot on the bean curve and
            their time under the axis

The curve is drawn from CHARGE to DROP only: the .alog also holds the whole
cooling tail, which would flatten the roast into a corner of the plot.

RoR is *not* stored in the .alog (``delta2`` is None) — only phase averages
are. The caller passes the app's own ``evaldeltas(data, "temp2")`` result so
the card shows exactly the RoR the roast viewer draws; without it the RoR
curve is simply left out.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from tilauscope.beancave_card_base import CARD_H, CARD_W, CardPainter
from tilauscope.tilauscope_types import AGTRON_SCALES, THEME

_logd = logging.getLogger('tilaudebug')

_LEFT_W = 448
_PAD_L = 36
_PAD_TOP = 40

# curve panel, in card coordinates
_PLOT_L, _PLOT_R = 506, 1140
_PLOT_T, _PLOT_B = 100, 540

# curve colours follow roast_card.py (the existing roast card dialog), where
# blue is the bean temperature; RoR takes peach and the dashed stroke that
# _PLOT_PALETTE gives to delta curves.
_C_BT = "#89B4FA"
_C_ET = "#F9E2AF"
_C_ROR = "#FAB387"
_C_MARK = "#7F849C"


def _mmss(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class RoastSocialCard(CardPainter):
    """Paints a roast profile onto a landscape card image."""

    # ── content extraction ───────────────────────────────────────────────────
    @staticmethod
    def roast_level(agtron: float):
        """The app's own Agtron table entry for this colour, or None."""
        for scale in AGTRON_SCALES:
            if scale.agtron_range.min_value <= agtron <= scale.agtron_range.max_value:
                return scale
        return None

    @staticmethod
    def agtron_of(profile: dict) -> int:
        """Ground colour, falling back to whole colour.

        Roasts measured on the whole bean only carry ``whole_color``; reading
        ``ground_color`` alone would show nothing at all for them.
        """
        return int(_f(profile.get("ground_color")) or _f(profile.get("whole_color")))

    @staticmethod
    def _date_label(profile: dict) -> str:
        from PyQt6.QtCore import QDateTime, QLocale
        epoch = _f(profile.get("roastepoch"))
        if epoch > 0:
            return QLocale().toString(
                QDateTime.fromSecsSinceEpoch(int(epoch)).date(), "d MMM yyyy")
        return str(profile.get("roastdate") or "").strip()

    def _marks(self, profile: dict, computed: dict) -> list[tuple[str, int]]:
        """(label, index into timex) — Artisan's sentinel convention applies:
        timeindex[0] uses -1 for unmarked, indices 1..7 use 0."""
        timex = profile.get("timex") or []
        timeindex = profile.get("timeindex") or []
        if not timeindex:
            return []
        charge = timeindex[0] if timeindex[0] > -1 else 0
        marks = [("CHARGE", charge)]
        tp = computed.get("TP_idx")
        if tp and 0 < int(tp) < len(timex):
            marks.append(("TP", int(tp)))
        for label, ti in (("DRYe", 1), ("FC", 2), ("DROP", 6)):
            if len(timeindex) > ti and timeindex[ti] > 0:
                marks.append((label, timeindex[ti]))
        return marks

    # ── left column ──────────────────────────────────────────────────────────
    def _paint_left(self, p: QPainter, profile: dict, computed: dict, bean) -> None:
        x, w = _PAD_L, _LEFT_W - 2 * _PAD_L
        p.fillRect(QRect(0, 0, _LEFT_W, CARD_H), QColor(THEME['SURFACE']))
        p.setPen(QPen(QColor(THEME['BORDER']), 1))
        p.drawLine(_LEFT_W, 0, _LEFT_W, CARD_H)

        y = _PAD_TOP
        country = (getattr(bean, 'country', '') or '').strip()
        date = self._date_label(profile)
        eyebrow = " · ".join(b for b in (country, date) if b)
        if eyebrow:
            y = self._text(p, x, y, eyebrow.upper(), self._font(8, tracking=20.0),
                           THEME['ACCENT']) + 12

        name = (getattr(bean, 'name', '') or '').strip() or \
            str(profile.get("title") or "").strip()
        name_font = self._font(26, bold=True)
        for line in self._wrap(name, name_font, w, 2):
            y = self._text(p, x, y, line, name_font, THEME['TEXT']) + 1

        badges: list[tuple[str, str]] = []
        for value, colour in (((getattr(bean, 'process', '') or '').strip(), THEME['WARNING']),
                              ((getattr(bean, 'species', '') or '').strip(), THEME['BORDER'])):
            if value:
                badges.append((value, colour))
        if badges:
            y = self._flow_badges(p, x, y + 14, w, badges, size=8, height=22)

        rows = self._green_rows(bean)
        if rows:
            y = self._section(p, x, y + 22, w,
                              QApplication.translate("tilauscope_roast_review", "Green bean"))
            y = self._kv_rows(p, x, y, w, rows)

        y = self._section(p, x, y + 16, w,
                          QApplication.translate("tilauscope_roast_review", "Roast"))
        agtron = self.agtron_of(profile)
        if agtron > 0:
            y = self._paint_level(p, x, y, w, agtron) + 14
        self._paint_metrics(p, x, y, w, profile, computed)

        self._paint_brand(p, x, str(profile.get("roastertype") or "").strip(), size=9)

    @staticmethod
    def _green_rows(bean) -> list[tuple[str, str]]:
        """The green bean facts worth repeating here.

        Density, humidity, water activity and flavour notes are deliberately
        absent: they belong to the green bean card and would only crowd this
        column.
        """
        if bean is None:
            return []
        rows: list[tuple[str, str]] = []
        farm = (getattr(bean, 'farm', '') or '').strip()
        if farm:
            rows.append((QApplication.translate("tilauscope_roast_review", "Farm"),
                         " ".join(farm.split())))
        varieties = (getattr(bean, 'varieties', '') or '').strip()
        if varieties:
            rows.append((QApplication.translate("tilauscope_roast_review", "Varieties"),
                         varieties))
        altitude = int(_f(getattr(bean, 'altitude', 0)))
        if altitude > 0:
            rows.append((QApplication.translate("tilauscope_roast_review", "Altitude"),
                         f"{altitude:,}".replace(",", " ") + " m"))
        sca = _f(getattr(bean, 'sca', 0))
        if sca > 0:
            crop = int(_f(getattr(bean, 'crop', 0)))
            label = f"{sca:g}"
            if crop > 0:
                label += " · " + QApplication.translate("tilauscope_roast_review", "crop") \
                    + f" {crop}"
            rows.append((QApplication.translate("tilauscope_roast_review", "SCA"), label))
        supplier = (getattr(bean, 'supplier', '') or '').strip()
        if supplier:
            rows.append((QApplication.translate("tilauscope_roast_review", "Supplier"),
                         supplier))
        return rows[:5]

    def _section(self, p: QPainter, x: int, y: int, w: int, title: str) -> int:
        y = self._text(p, x, y, title.upper(), self._font(7, tracking=18.0),
                       THEME['ACCENT']) + 7
        p.setPen(QPen(QColor(THEME['BORDER']), 1))
        p.drawLine(x, y, x + w, y)
        return y + 11

    def _kv_rows(self, p: QPainter, x: int, y: int, w: int,
                 rows: list[tuple[str, str]]) -> int:
        kfont, vfont = self._font(9), self._font(9)
        fm = QFontMetrics(vfont)
        for key, value in rows:
            self._text(p, x, y, key, kfont, THEME['SUBTEXT'])
            self._elided(p, x + 92, y, value, vfont, THEME['TEXT'], w - 92)
            y += fm.height() + 6
        return y

    def _paint_level(self, p: QPainter, x: int, y: int, w: int, agtron: int) -> int:
        """The roast level chip — the one warm thing in the column."""
        h = 52
        self._rrect(p, QRectF(x, y, w, h), 8, fill=THEME['BG'], stroke=THEME['BORDER'])
        level = self.roast_level(agtron)
        if level is not None:
            self._rrect(p, QRectF(x + 12, y + 11, 30, 30), 6, fill=level.color_map,
                        stroke="#4A4A5A")
            self._text(p, x + 52, y + 11, level.name, self._font(11, bold=True),
                       THEME['TEXT'])
            self._text(p, x + 52, y + 29, level.description, self._font(8),
                       THEME['SUBTEXT'])
        vfont = self._font(15, bold=True)
        fm = QFontMetrics(vfont)
        vw = fm.horizontalAdvance(str(agtron))
        p.setFont(vfont)
        p.setPen(QColor(THEME['TEXT']))
        p.drawText(x + w - 12 - vw, y + 12 + fm.ascent(), str(agtron))
        lfont = self._font(7, tracking=14.0)
        lfm = QFontMetrics(lfont)
        label = QApplication.translate("tilauscope_roast_review", "Agtron").upper()
        self._text(p, x + w - 12 - lfm.horizontalAdvance(label), y + 33, label,
                   lfont, THEME['SUBTEXT'])
        return y + h

    def _paint_metrics(self, p: QPainter, x: int, y: int, w: int,
                       profile: dict, computed: dict) -> None:
        drop_t = _f(computed.get("DROP_time"))
        fcs_t = _f(computed.get("FCs_time"))
        tiles: list[tuple[str, str, str, bool]] = []
        if drop_t > 0:
            tiles.append((QApplication.translate("tilauscope_roast_review", "Duration"),
                          _mmss(drop_t), "", False))
        if drop_t > 0 and 0 < fcs_t < drop_t:
            tiles.append(("DTR", f"{(drop_t - fcs_t) / drop_t * 100:.0f}", "%", True))
        weight = profile.get("weight") or []
        if len(weight) >= 3:
            w_in, w_out, unit = _f(weight[0]), _f(weight[1]), str(weight[2])
            if w_in > 0:
                tiles.append((QApplication.translate("tilauscope_roast_review", "Charge"),
                              f"{w_in:g}", unit, False))
                if w_out > 0:
                    tiles.append((QApplication.translate("tilauscope_roast_review", "Loss"),
                                  f"{(w_in - w_out) / w_in * 100:.1f}", "%", False))
        col_w = w / 2
        for i, (key, value, unit, highlight) in enumerate(tiles[:4]):
            cx = int(x + (i % 2) * col_w)
            cy = y + (i // 2) * 58
            self._text(p, cx, cy, key.upper(), self._font(7, tracking=14.0),
                       THEME['SUBTEXT'])
            vfont = self._font(17, bold=True)
            fm = QFontMetrics(vfont)
            p.setFont(vfont)
            p.setPen(QColor(THEME['SUCCESS'] if highlight else THEME['TEXT']))
            p.drawText(cx, cy + 16 + fm.ascent(), value)
            if unit:
                self._text(p, cx + fm.horizontalAdvance(value) + 5,
                           cy + 16 + fm.ascent() - QFontMetrics(self._font(8)).ascent(),
                           unit, self._font(8), THEME['SUBTEXT'])

    # ── curve ────────────────────────────────────────────────────────────────
    def _paint_curve(self, p: QPainter, profile: dict, computed: dict,
                     deltabt) -> None:
        timex = profile.get("timex") or []
        bt = profile.get("temp2") or []
        et = profile.get("temp1") or []
        timeindex = profile.get("timeindex") or []
        if len(timex) < 2 or len(bt) != len(timex) or len(timeindex) < 7:
            return

        charge = timeindex[0] if timeindex[0] > -1 else 0
        drop = timeindex[6] if timeindex[6] > 0 else len(timex) - 1
        if drop <= charge:
            return
        t0 = timex[charge]
        span = range(charge, drop + 1)
        x_max = (timex[drop] - t0) / 60.0
        if x_max <= 0:
            return

        temps = [v for v in (list(bt[charge:drop + 1]) + list(et[charge:drop + 1]))
                 if isinstance(v, (int, float))]
        if not temps:
            return
        y_min = (min(temps) - 15) // 20 * 20
        y_max = -(-(max(temps) + 15) // 20) * 20

        ## TILAU ## RoR window: between CHARGE and TP the bean temperature falls
        ## hard, so RoR dives to -60..-100 there. Scaling the axis to that dip
        ## would squash the whole roasting range into a thin band at the top, so
        ## the axis is fixed to the useful positive range and the dive is clipped
        ## to the plot frame — the curve simply enters from the bottom left.
        rors = [deltabt[i] for i in span
                if deltabt is not None and i < len(deltabt)
                and isinstance(deltabt[i], (int, float)) and deltabt[i] > 0] \
            if deltabt is not None else []
        r_min = 0.0
        r_max = max(30.0, -(-max(rors) // 10) * 10) if rors else 30.0

        def X(t):
            return _PLOT_L + ((t - t0) / 60.0 / x_max) * (_PLOT_R - _PLOT_L)

        def Y(v):
            return _PLOT_T + (1 - (v - y_min) / (y_max - y_min)) * (_PLOT_B - _PLOT_T)

        def YR(v):
            return _PLOT_T + (1 - (v - r_min) / (r_max - r_min)) * (_PLOT_B - _PLOT_T)

        has_ror = bool(rors)
        self._paint_grid(p, y_min, y_max, r_min, r_max, Y, YR, has_ror)

        ## TILAU ## curves are clipped to the frame; only the axes and the
        ## milestone labels are allowed to live outside it
        p.save()
        p.setClipRect(QRect(_PLOT_L, _PLOT_T, _PLOT_R - _PLOT_L, _PLOT_B - _PLOT_T))
        self._polyline(p, [(X(timex[i]), Y(et[i])) for i in span
                           if i < len(et) and isinstance(et[i], (int, float))],
                       _C_ET, 1.4, alpha=128)
        if deltabt is not None:
            ## TILAU ## RoR only exists from ~10 readings after CHARGE; the gaps
            ## are broken segments, never zeros dragged along the axis
            segment: list[tuple[float, float]] = []
            for i in span:
                v = deltabt[i] if i < len(deltabt) else None
                if isinstance(v, (int, float)):
                    segment.append((X(timex[i]), YR(v)))
                elif segment:
                    self._polyline(p, segment, _C_ROR, 1.7, dashed=True)
                    segment = []
            self._polyline(p, segment, _C_ROR, 1.7, dashed=True)
        self._polyline(p, [(X(timex[i]), Y(bt[i])) for i in span
                           if isinstance(bt[i], (int, float))], _C_BT, 2.2)
        p.restore()

        self._paint_marks(p, profile, computed, timex, bt, X, Y)
        self._paint_legend(p, has_ror)

    def _paint_grid(self, p: QPainter, y_min, y_max, r_min, r_max, Y, YR,
                    has_ror: bool) -> None:
        step = 50 if (y_max - y_min) > 150 else 25
        font = self._font(7)
        t = y_min + step
        while t < y_max:
            p.setPen(QPen(QColor(THEME['BORDER']), 1))
            p.drawLine(_PLOT_L, int(Y(t)), _PLOT_R, int(Y(t)))
            fm = QFontMetrics(font)
            self._text(p, _PLOT_L - 8 - fm.horizontalAdvance(str(int(t))),
                       int(Y(t)) - fm.height() // 2, str(int(t)), font, THEME['SUBTEXT'])
            t += step
        ## TILAU ## no RoR curve, no RoR axis: an empty scale would promise a
        ## curve the card never draws
        if not has_ror:
            return
        r = r_min
        while r <= r_max:
            self._text(p, _PLOT_R + 8, int(YR(r)) - QFontMetrics(font).height() // 2,
                       f"{int(r)}", font, _C_ROR)
            r += 10

    def _paint_marks(self, p: QPainter, profile, computed, timex, bt, X, Y) -> None:
        label_font = self._font(9, bold=True)
        time_font = self._font(7)
        for label, idx in self._marks(profile, computed):
            if not 0 <= idx < len(timex):
                continue
            x = X(timex[idx])
            pen = QPen(QColor(_C_MARK), 1.4)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawLine(int(x), _PLOT_T, int(x), _PLOT_B)
            if isinstance(bt[idx], (int, float)):
                ## TILAU ## dark halo first so the dot reads on top of the curve
                y = Y(bt[idx])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(THEME['BG'])))
                p.drawEllipse(QPointF(x, y), 5.4, 5.4)
                p.setBrush(QBrush(QColor(_C_BT)))
                p.drawEllipse(QPointF(x, y), 3.6, 3.6)
                p.setBrush(Qt.BrushStyle.NoBrush)
            charge_t = timex[self._marks(profile, computed)[0][1]]
            self._centred(p, x, _PLOT_T - 22, label, label_font, THEME['TEXT'])
            self._centred(p, x, _PLOT_B + 6, _mmss(timex[idx] - charge_t),
                          time_font, _C_MARK)

    def _centred(self, p: QPainter, cx: float, y: int, text: str, font, colour) -> None:
        """Centre on ``cx`` but never let the first or last label leave the plot."""
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(text)
        x = min(max(int(cx - w / 2), _PLOT_L), _PLOT_R - w)
        self._text(p, x, y, text, font, colour)

    def _paint_legend(self, p: QPainter, has_ror: bool) -> None:
        font = self._font(8, tracking=10.0)
        fm = QFontMetrics(font)
        x, y = _PLOT_L, 44
        entries = [("BT", _C_BT, 255), ("ET", _C_ET, 128)]
        if has_ror:
            entries.append(("RoR BT", _C_ROR, 255))
        for label, colour, alpha in entries:
            c = QColor(colour)
            c.setAlpha(alpha)
            p.setPen(QPen(c, 2))
            p.drawLine(x, y + fm.height() // 2, x + 13, y + fm.height() // 2)
            self._text(p, x + 19, y, label, font, THEME['SUBTEXT'])
            x += 19 + fm.horizontalAdvance(label) + 18
        unit = "°C · °C/min" if has_ror else "°C"
        self._text(p, _PLOT_R - fm.horizontalAdvance(unit), y, unit, font,
                   THEME['SUBTEXT'])

    @staticmethod
    def _polyline(p: QPainter, pts: list[tuple[float, float]], colour: str,
                  width: float, dashed: bool = False, alpha: int = 255) -> None:
        if len(pts) < 2:
            return
        c = QColor(colour)
        c.setAlpha(alpha)
        pen = QPen(c, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pen.setDashPattern([4, 2])
        p.setPen(pen)
        p.drawPolyline([QPointF(x, y) for x, y in pts])

    # ── public API ───────────────────────────────────────────────────────────
    def render(self, profile: dict, bean=None, deltabt=None) -> QImage:
        computed = profile.get("computed") or {}
        img = self._new_image()
        p = self._begin(img)
        try:
            self._paint_left(p, profile, computed, bean)
            self._paint_curve(p, profile, computed, deltabt)
        finally:
            p.end()
        return img

    def save_jpeg(self, profile: dict, file_path: str, bean=None,
                  deltabt=None) -> bool:
        try:
            return self._save(self.render(profile, bean, deltabt), file_path)
        except Exception:
            _logd.error("roast card: render failed", exc_info=True)
            return False

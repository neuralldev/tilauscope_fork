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

"""Landscape roast card: key figures, the curve with the settings played under it, key moments.

What it shows comes from tilaucore.roast_card, shared with the tablet's card; this paints it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, Qt, QDateTime, QLocale
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication

from tilauscope.beancave_card_base import CardPainter
from tilaucore import roast_card as rc
from tilaucore.roast_colour import agtron_text
from tilauscope.roasters import canonical_roaster_name
from tilauscope.tilauscope_types import (COLOR_AIR, COLOR_GRAIN, PHASE_COLORS, THEME,
                                         dimmed, get_agtron_color)

_logd = logging.getLogger('tilau')
_W, _H, _SCALE = rc.WIDTH, rc.HEIGHT, rc.SCALE
_BG, _SURFACE, _BORDER, _RAISED = THEME['BG'], THEME['SURFACE'], THEME['BORDER'], THEME['SURFACE1']
_TEXT, _MUTED, _FAINT = THEME['TEXT'], THEME['SUBTEXT'], THEME['OVERLAY0']
# The probe hues of the roasting window; the rate wears the bean's hue one step back.
_BLUE, _PEACH = COLOR_GRAIN, COLOR_AIR
_RISE = dimmed(_BLUE, _BLUE)
_PHASE_COLORS = PHASE_COLORS   # drying, Maillard, development
# Settings lanes wear the operator's event colours, as on the curve; these stand in for a missing one.
_LANE_COLORS = {3: THEME['CRITICAL'], 0: THEME['TEAL'], 2: THEME['MAUVE'], 1: THEME['LAVENDER']}
# Plot frame
_X0, _X1, _Y0 = 150, 1730, 300
_LANE_H, _LANE_GAP = 52, 14
_mmss = rc.mmss


class RoastSocialCard(CardPainter):
    """Use logical pixel sizes, rendering independently of screen DPI."""

    def _font(self, size: int, bold: bool = False, tracking: float = 0.0) -> QFont:
        font = QFont(QApplication.font())
        font.setPixelSize(size)
        font.setBold(bold)
        if tracking:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + tracking)
        return font

    def _mono(self, size: int, bold: bool = False) -> QFont:
        font = QFont(self._bold if bold else self._reg)
        font.setPixelSize(size)
        font.setBold(bold)
        return font

    @staticmethod
    def agtron_of(profile: dict) -> int:
        return rc.colour(profile)[0]

    @staticmethod
    def _date_label(profile: dict) -> str:
        epoch = rc.number(profile.get('roastepoch'))
        if epoch is not None and epoch > 0:
            when = QDateTime.fromSecsSinceEpoch(int(epoch))
            return QLocale().toString(when, 'd MMM yyyy · HH:mm')
        return str(profile.get('roastdate') or '').strip()

    @staticmethod
    def _lane_colours(colors: list | None) -> dict[int, str]:
        """The operator's event colour of each setting, by event type; ours where it has none."""
        result = {}
        for kind, fallback in _LANE_COLORS.items():
            colour = QColor(colors[kind]) if colors and kind < len(colors) else QColor()
            result[kind] = colour.name() if colour.isValid() else fallback
        return result

    # ── painting helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _draw(p: QPainter, x: float, baseline: float, text: str, font: QFont, color: str,
              align: str = 'left', max_w: int = 0) -> float:
        """Draw on a baseline; returns the drawn width."""
        fm = QFontMetrics(font)
        if max_w:
            text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w)
        width = fm.horizontalAdvance(text)
        if align == 'right':
            x -= width
        elif align == 'center':
            x -= width / 2
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(QPointF(x, baseline), text)
        return width

    @staticmethod
    def _polyline(p: QPainter, points: list[QPointF | None], color: str, width: float) -> None:
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        segment: list[QPointF] = []
        for point in [*points, None]:
            if point is None:
                if len(segment) > 1:
                    p.drawPolyline(segment)
                segment = []
            else:
                segment.append(point)

    # ── header ───────────────────────────────────────────────────────────────
    def _header(self, p: QPainter, profile: dict, bean, marks: dict[str, int], energy: str) -> None:
        country = str(getattr(bean, 'country', '') or '').strip()
        process = str(getattr(bean, 'process', '') or '').strip()
        self._draw(p, 64, 82, ' · '.join(v for v in (country, process) if v).upper(),
                   self._font(24, tracking=8), _MUTED, max_w=560)
        name = str(getattr(bean, 'name', '') or profile.get('title') or '').strip()
        size = 62   # a long name shrinks before it is cut
        while size > 40 and QFontMetrics(self._font(size, True)).horizontalAdvance(name) > 560:
            size -= 2
        self._draw(p, 64, 150, name, self._font(size, True), _TEXT, max_w=560)
        self._draw(p, 64, 198, ' · '.join(v for v in (self._date_label(profile),
                   canonical_roaster_name(str(profile.get('roastertype') or ''))) if v),
                   self._font(26), _MUTED, max_w=560)
        p.setPen(QPen(QColor(_BORDER), 2))
        p.drawLine(QPointF(640, 56), QPointF(640, 210))

        dash = rc.DASH
        shown = rc.figures(profile, marks)
        agtron, basis = rc.colour(profile)
        colour_label = (QApplication.translate('tilauscope_common', 'Colour') if not agtron else
                        {'ground': QApplication.translate('tilauscope_roast_review', 'Colour · ground'),
                         'estimated': QApplication.translate('tilauscope_roast_review', 'Colour · ground (est.)'),
                         }.get(basis, QApplication.translate('tilauscope_roast_review', 'Colour · whole bean')))
        ambient = shown['ambient']
        dev = _PHASE_COLORS[2]
        columns = [
            [(QApplication.translate('tilauscope_roast_review', 'Total duration'), shown['duration'], _TEXT),
             (QApplication.translate('Label', 'Development'), shown['development'], dev),
             (QApplication.translate('tilauscope_roast_review', 'Development rise'), shown['rise'], dev)],
            [(QApplication.translate('tilauscope_common', 'Green weight'), shown['green'], _TEXT),
             (QApplication.translate('tilauscope_common', 'Roasted weight'), shown['roasted'], _TEXT),
             (QApplication.translate('tilauscope_common', 'Weight loss'), shown['loss'], _TEXT)],
            [(colour_label, QApplication.translate('tilauscope_roast_review', 'Agtron')
              + f" {agtron_text(agtron, basis)}"
              if agtron else dash, _TEXT),
             (QApplication.translate('Tab', 'Energy'), energy or dash, _TEXT)]
            + ([(QApplication.translate('Tab', 'Ambient'), ' · '.join(ambient), _TEXT)] if ambient else []),
        ]
        for ci, column in enumerate(columns):
            for ri, (label, value, colour) in enumerate(column):
                x, y = 690 + ci * 560, 90 + ri * 54
                vfont = self._mono(28 if len(value) <= 16 else 22, True)
                width = self._draw(p, x + 500, y, value, vfont, colour, 'right')
                self._draw(p, x, y, label, self._font(26), _MUTED, max_w=max(80, 480 - int(width)))
                if ci == 2 and ri == 0 and agtron:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(get_agtron_color(agtron)))
                    p.drawEllipse(QPointF(x + 500 - width - 22, y - 9), 9, 9)
                    p.setBrush(Qt.BrushStyle.NoBrush)

    # ── curve, phases, lanes ─────────────────────────────────────────────────
    def _chart(self, p: QPainter, profile: dict, marks: dict[str, int], ror: list[float | None],
               lanes: list[rc.Lane]) -> None:
        self._rrect(p, QRectF(32, 248, 1790, 1040), 18, fill=_SURFACE, stroke=_BORDER)
        times = profile.get('timex') or []
        bt, et = profile.get('temp2') or [], profile.get('temp1') or []
        unit = '°F' if profile.get('mode') == 'F' else '°C'
        charge, drop = marks['charge'], marks['drop']
        t0, total = times[charge], times[drop] - times[charge]
        lanes_h = len(lanes) * (_LANE_H + _LANE_GAP) - (_LANE_GAP if lanes else 0)
        y1 = 1262 - 42 - 34 - lanes_h - (90 if lanes else 70)
        def X(t):
            return _X0 + (t - t0) / total * (_X1 - _X0)

        span = range(charge, drop + 1)
        axes = rc.scales(profile, marks, ror)
        low, high, step, rhigh, rstep = axes.low, axes.high, axes.step, axes.rhigh, axes.rstep
        def Y(v):
            return y1 - (v - low) / (high - low) * (y1 - _Y0)
        def R(v):
            return y1 - v / rhigh * (y1 - _Y0)

        # phase grounds, grid, axes
        bounds = [charge, marks.get('dry'), marks.get('fc'), drop]
        for (a, b), colour in zip(zip(bounds, bounds[1:]), _PHASE_COLORS, strict=True):
            if a is not None and b is not None:
                tint = QColor(colour)
                tint.setAlpha(18)
                p.fillRect(QRectF(X(times[a]), _Y0, X(times[b]) - X(times[a]), y1 - _Y0), tint)
        mono = self._mono(22)
        for v in range(low, high + 1, step):
            p.setPen(QPen(QColor(_BORDER), 1))
            p.drawLine(QPointF(_X0, Y(v)), QPointF(_X1, Y(v)))
            self._draw(p, _X0 - 14, Y(v) + 8, f'{v}', mono, _FAINT, 'right')
        for v in range(0, rhigh + 1, rstep):
            self._draw(p, _X1 + 14, R(v) + 8, f'{v}', mono, _RISE)
        self._draw(p, _X0 - 14, _Y0 - 24, unit, self._font(22), _FAINT, 'right')
        self._draw(p, _X1 + 14, _Y0 - 24, f'{unit}/min', self._font(22), _RISE)

        tp = rc.turning_point(profile, marks)
        moments = [('charge', charge, QApplication.translate('Tooltip', 'Charge'))]
        if tp is not None:
            moments.append(('tp', tp, QApplication.translate('Label', 'TP')))
        moments += [(k, marks[k], label) for k, label in (
            ('dry', QApplication.translate('tilauscope_common', 'Dry end')),
            ('fc', QApplication.translate('tilauscope_common', 'First crack'))) if k in marks]
        moments.append(('drop', drop, QApplication.translate('Tooltip', 'Drop')))
        dashed = QPen(QColor(_RAISED), 1.5, Qt.PenStyle.DashLine)
        for _key, idx, _label in moments[1:-1]:
            p.setPen(dashed)
            p.drawLine(QPointF(X(times[idx]), _Y0), QPointF(X(times[idx]), y1))

        # curves, clipped to the plot
        p.save()
        p.setClipRect(QRectF(_X0 - 8, _Y0 - 8, _X1 - _X0 + 16, y1 - _Y0 + 8))
        start = rc.rise_start(profile, marks)
        self._polyline(p, [QPointF(X(times[i]), R(ror[i])) if i >= start and ror[i] is not None else None
                           for i in span], _RISE, 2.7)
        self._polyline(p, [QPointF(X(times[i]), Y(v)) if (v := rc.reading(et, i)) is not None else None
                           for i in span], _PEACH, 2.4)
        self._polyline(p, [QPointF(X(times[i]), Y(v)) if (v := rc.reading(bt, i)) is not None else None
                           for i in span], _BLUE, 3.4)
        p.restore()

        # peak rate of rise after the turning point
        peak = rc.peak_rise(profile, marks, ror)
        if peak:
            r, i = peak
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(_RISE))
            p.drawEllipse(QPointF(X(times[i]), R(r)), 5, 5)
            self._draw(p, X(times[i]), R(r) - 18, f'{r:.1f} {unit}/min', self._mono(22, True), _RISE, 'center')

        # milestones: dot on the bean curve and a callout on two alternating rows
        for n, (key, idx, label) in enumerate(moments):
            v = rc.reading(bt, idx)
            if v is None:
                continue
            x, y = X(times[idx]), Y(v)
            row = _Y0 + (26 if n % 2 == 0 else 79)
            name_font, figure_font = self._font(22, True), self._mono(22)
            figures = f'{_mmss(times[idx] - t0)} · {v:.0f} {unit}'
            width = (QFontMetrics(name_font).horizontalAdvance(label.upper()) + 10
                     + QFontMetrics(figure_font).horizontalAdvance(figures))
            left = x + 8 if key == 'charge' else x - width - 8 if key == 'drop' else x - width / 2
            left = min(max(left, _X0 + 4), _X1 - width - 4)
            lead = QColor(_MUTED)
            lead.setAlpha(128)
            p.setPen(QPen(lead, 1))
            p.drawLine(QPointF(x, row + 12), QPointF(x, y - 9))
            drawn = self._draw(p, left, row, label.upper(), name_font, _TEXT)
            self._draw(p, left + drawn + 10, row, figures, figure_font, _MUTED)
            p.setPen(QPen(QColor(_BLUE), 3))
            p.setBrush(QColor(_BG))
            p.drawEllipse(QPointF(x, y), 6.5, 6.5)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # phase strip
        phases = rc.phase_durations(profile, marks)
        names = (QApplication.translate('Label', 'Drying'), QApplication.translate('Label', 'Maillard'),
                 QApplication.translate('Label', 'Development'))
        sy = y1 + 20
        if all(v is not None for v in phases):
            for (a, b), colour, label, length in zip(zip(bounds, bounds[1:]), _PHASE_COLORS, names, phases,
                                                     strict=True):
                left, width = X(times[a]), X(times[b]) - X(times[a]) - 3
                tint = QColor(colour)
                tint.setAlpha(56)
                path = QPainterPath()
                path.addRoundedRect(QRectF(left, sy, width, 46), 4, 4)
                p.fillPath(path, tint)
                p.fillRect(QRectF(left, sy, width, 4), QColor(colour))
                figures = f'{_mmss(length)} · {length / total * 100:.1f} %'
                if width >= 360:
                    drawn = self._draw(p, left + 12, sy + 31, label, self._font(22, True), colour)
                    self._draw(p, left + 22 + drawn, sy + 31, figures, self._mono(22), _TEXT)
                else:
                    self._draw(p, left + 12, sy + 31, figures, self._mono(22, True), colour, max_w=int(width) - 16)
        else:
            p.fillRect(QRectF(_X0, sy, _X1 - _X0, 10), QColor(_BORDER))

        # settings lanes
        ly = sy + 70
        for lane in lanes:
            colour, bottom = lane.color, ly + _LANE_H
            self._draw(p, _X0 - 14, ly + _LANE_H / 2 + 8, lane.name, self._font(22, True), colour, 'right', 130)
            p.setPen(QPen(QColor(_BORDER), 1))
            p.drawLine(QPointF(_X0, bottom), QPointF(_X1, bottom))
            def LY(v, bottom=bottom):
                return bottom - max(0, min(100, v)) / 100 * _LANE_H
            path = QPainterPath(QPointF(_X0 + lane.steps[0][0] / total * (_X1 - _X0), LY(lane.steps[0][1])))
            for (_t, v), (t_next, v_next) in zip(lane.steps, lane.steps[1:]):
                xn = _X0 + t_next / total * (_X1 - _X0)
                path.lineTo(xn, LY(v))
                path.lineTo(xn, LY(v_next))
            path.lineTo(_X1, LY(lane.steps[-1][1]))
            area = QPainterPath(path)
            area.lineTo(_X1, bottom)
            area.lineTo(path.elementAt(0).x, bottom)
            area.closeSubpath()
            fill = QColor(colour)
            fill.setAlpha(30)
            p.fillPath(area, fill)
            p.setPen(QPen(QColor(colour), 2.5))
            p.drawPath(path)
            last_x, last_v = -1e9, None
            for t, v in lane.steps:
                x = _X0 + t / total * (_X1 - _X0)
                if x - last_x < 70 or v == last_v:
                    continue
                last_x, last_v = x, v
                self._draw(p, x + 4, LY(v) - 6, f'{v}', self._mono(19), colour)
            ly += _LANE_H + _LANE_GAP

        # time axis and legend
        ty = (ly - _LANE_GAP if lanes else sy + 46) + 34
        tick = 60 if total <= 900 else 120
        for t in range(0, int(total) + 1, tick):
            self._draw(p, X(t0 + t), ty, _mmss(t), mono, _FAINT, 'center')
        lx = _X0
        for label, colour in ((QApplication.translate('tilauscope_roast_review', 'Bean temperature'), _BLUE),
                              (QApplication.translate('tilauscope_common', 'Air temperature'), _PEACH),
                              (QApplication.translate('tilauscope_common', 'Rate of rise'), _RISE)):
            p.fillRect(QRectF(lx, 1251, 26, 5), QColor(colour))
            lx += 36 + self._draw(p, lx + 36, 1262, label, self._font(22), _MUTED) + 30

    # ── key moments ──────────────────────────────────────────────────────────
    def _moments(self, p: QPainter, profile: dict, marks: dict[str, int], ror: list[float | None],
                 lanes: list[rc.Lane]) -> None:
        self._rrect(p, QRectF(1846, 248, 522, 1040), 18, fill=_SURFACE, stroke=_BORDER)
        bt = profile.get('temp2') or []
        self._draw(p, 1874, 300, QApplication.translate('tilauscope_roast_review', 'Key moments'),
                   self._font(26, True), _TEXT)
        for label, x, align in ((QApplication.translate('Label', 'Time'), 1874, 'left'),
                                (QApplication.translate('tilauscope_common', 'Bean'), 2036, 'right'),
                                (QApplication.translate('tilauscope_common', 'Rise'), 2136, 'right'),
                                (QApplication.translate('Label', 'Event'), 2168, 'left')):
            self._draw(p, x, 344, label, self._font(20), _FAINT, align)

        named = {'charge': (QApplication.translate('Tooltip', 'Charge'), _TEXT),
                 'tp': (QApplication.translate('Label', 'TP'), _MUTED),
                 'dry': (QApplication.translate('tilauscope_common', 'Dry end'), _PHASE_COLORS[0]),
                 'fc': (QApplication.translate('tilauscope_common', 'First crack'), _PHASE_COLORS[1]),
                 'drop': (QApplication.translate('Tooltip', 'Drop'), _PHASE_COLORS[2])}
        start = rc.rise_start(profile, marks)
        figures = self._mono(22)
        for n, row in enumerate(rc.key_moments(profile, marks, lanes)):
            y = rc.ROW_Y0 + n * rc.ROW_STEP
            i = rc.sample_at(profile, marks, row.t)
            text, colour = named[row.key] if row.milestone else (row.text, row.color)
            if row.milestone:
                shade = QColor(_BORDER)
                shade.setAlpha(140)
                path = QPainterPath()
                path.addRoundedRect(QRectF(1860, y - 27, 494, 36), 6, 6)
                p.fillPath(path, shade)
            temp = rc.number(bt[i]) if i < len(bt) else None
            self._draw(p, 1874, y, _mmss(row.t), figures, _MUTED)
            self._draw(p, 2036, y, f'{temp:.1f}' if temp is not None and temp != -1 else '—', figures, _BLUE, 'right')
            rise = ror[i] if i >= start else None
            self._draw(p, 2136, y, f'{rise:.1f}' if rise is not None else '—', figures, _RISE, 'right')
            self._draw(p, 2168, y, text, self._font(22, row.milestone), colour, max_w=190)

    # ── entry points ─────────────────────────────────────────────────────────
    def render(self, profile: dict, bean=None, deltabt=None, ror_unit: str | None = None,
               energy: str = '', lane_colors: list | None = None) -> QImage:
        marks = rc.milestones(profile)
        times = profile.get('timex') or []
        # RoR supplied by the viewer uses the current display unit, unlike stored BT.
        factor = 1.0
        if ror_unit and ror_unit != profile.get('mode', 'C'):
            factor = 1 / 1.8 if ror_unit == 'F' else 1.8
        ror = [v * factor if (v := rc.number(raw)) is not None else None for raw in (deltabt or [])]
        ror += [None] * (len(times) - len(ror))
        img = QImage(round(_W * _SCALE), round(_H * _SCALE), QImage.Format.Format_RGB32)
        img.fill(QColor(_BG))
        p = self._begin(img)
        p.scale(_SCALE, _SCALE)
        try:
            self._header(p, profile, bean, marks, energy)
            if rc.has_frame(profile, marks):
                lanes = rc.lanes(profile, marks, self._lane_colours(lane_colors))
                self._chart(p, profile, marks, ror, lanes)
                self._moments(p, profile, marks, ror, lanes)
            else:
                self._rrect(p, QRectF(32, 248, 2336, 1040), 18, fill=_SURFACE, stroke=_BORDER)
                self._draw(p, _W / 2, 780, QApplication.translate('tilauscope_roast_review', 'Charge or drop not marked'),
                           self._font(30), _MUTED, 'center')
            self._draw(p, 64, 1328, 'TilauScope', self._font(22, True), _FAINT)
        finally:
            p.end()
        return img

    def save_png(self, profile: dict, file_path: str, bean=None, deltabt=None,
                 ror_unit: str | None = None, energy: str = '', lane_colors: list | None = None) -> bool:
        try:
            return self.render(profile, bean, deltabt, ror_unit, energy, lane_colors).save(file_path, 'PNG')
        except Exception:
            _logd.error('roast card: render failed', exc_info=True)
            return False

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

"""Landscape roast card: key figures, the curve with the settings played under it, key moments."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from numbers import Real

from PyQt6.QtCore import QPointF, QRectF, Qt, QDateTime, QLocale
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication

from artisanlib.util import decodeLocalStrict, events_internal_to_external_value
from tilauscope.beancave_card_base import CardPainter
from tilauscope.roasters import canonical_roaster_name
from tilauscope.tilauscope_types import (COLOR_AIR, COLOR_GRAIN, PHASE_COLORS, THEME,
                                         dimmed, get_agtron_color)

_logd = logging.getLogger('tilau')
# Drawn on a 2400 × 1350 layout, saved at 3200 × 1800.
_W, _H, _SCALE = 2400, 1350, 4 / 3
_BG, _SURFACE, _BORDER, _RAISED = THEME['BG'], THEME['SURFACE'], THEME['BORDER'], THEME['SURFACE1']
_TEXT, _MUTED, _FAINT = THEME['TEXT'], THEME['SUBTEXT'], THEME['OVERLAY0']
# The probe hues of the roasting window; the rate wears the bean's hue one step back.
_BLUE, _PEACH = COLOR_GRAIN, COLOR_AIR
_RISE = dimmed(_BLUE, _BLUE)
_PHASE_COLORS = PHASE_COLORS   # drying, Maillard, development
# Settings lanes by Artisan event type (0 air, 1 drum, 2 damper, 3 burner), burner first.
# They wear the operator's event colours, as on the curve; these stand in for a missing one.
_LANE_ORDER = (3, 0, 2, 1)
_LANE_COLORS = {3: THEME['CRITICAL'], 0: THEME['TEAL'], 2: THEME['MAUVE'], 1: THEME['LAVENDER']}
# Plot frame, key moments column
_X0, _X1, _Y0 = 150, 1730, 300
_LANE_H, _LANE_GAP = 52, 14
_ROW_Y0, _ROW_STEP, _ROW_LAST = 392, 39, 1270
# Changes on one setting closer than this collapse into the last one in the key moments.
_SETTLE_S = 10.0


def _number(value) -> float | None:
    if isinstance(value, Real) and math.isfinite(value):
        return float(value)
    return None


def _mmss(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


@dataclass
class _Lane:
    kind: int
    name: str
    color: str
    steps: list[tuple[float, int]]   # (seconds from CHARGE, value), in order


@dataclass
class _Moment:
    t: float
    text: str
    color: str
    milestone: bool = False
    kind: int = -1   # the setting a gesture moved


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
        for key in ('ground_color', 'whole_color'):
            try:
                value = float(profile.get(key) or 0)
                if math.isfinite(value) and value > 0:
                    return round(value)
            except (TypeError, ValueError):
                pass
        return 0

    @staticmethod
    def _date_label(profile: dict) -> str:
        epoch = _number(profile.get('roastepoch'))
        if epoch is not None and epoch > 0:
            when = QDateTime.fromSecsSinceEpoch(int(epoch))
            return QLocale().toString(when, 'd MMM yyyy · HH:mm')
        return str(profile.get('roastdate') or '').strip()

    @staticmethod
    def _milestones(profile: dict) -> dict[str, int]:
        times = profile.get('timex') or []
        indices = profile.get('timeindex') or []
        marks = {}
        for key, slot in (('charge', 0), ('dry', 1), ('fc', 2), ('drop', 6)):
            if slot >= len(indices):
                continue
            index = indices[slot]
            if (isinstance(index, int) and (index >= 0 if slot == 0 else index > 0)
                    and index < len(times) and _number(times[index]) is not None):
                marks[key] = index
        # Never turn an absent CHARGE or DROP into a made-up milestone.
        if 'charge' in marks:
            for key in ('dry', 'fc', 'drop'):
                if key in marks and times[marks[key]] <= times[marks['charge']]:
                    del marks[key]
        if 'drop' in marks:
            for key in ('dry', 'fc'):
                if key in marks and times[marks[key]] >= times[marks['drop']]:
                    del marks[key]
        return marks

    @staticmethod
    def _phase_durations(profile: dict, marks: dict[str, int]) -> list[float | None]:
        times = profile.get('timex') or []
        result = []
        for start, end in (('charge', 'dry'), ('dry', 'fc'), ('fc', 'drop')):
            duration = times[marks[end]] - times[marks[start]] if start in marks and end in marks else 0
            result.append(duration if duration > 0 else None)
        return result

    @staticmethod
    def _turning_point(profile: dict, marks: dict[str, int]) -> int | None:
        tp = (profile.get('computed') or {}).get('TP_idx')
        if isinstance(tp, int) and marks['charge'] < tp < marks['drop']:
            return tp
        return None

    @staticmethod
    def _lanes(profile: dict, marks: dict[str, int], colors: list | None = None) -> list[_Lane]:
        """Each setting played between CHARGE and DROP, with the value it had at CHARGE."""
        times = profile.get('timex') or []
        names = profile.get('etypes') or []
        charge, drop = marks['charge'], marks['drop']
        t0 = times[charge]
        steps: dict[int, list[tuple[float, int]]] = {}
        before: dict[int, int] = {}
        for idx, kind, value in zip(profile.get('specialevents') or [],
                                    profile.get('specialeventstype') or [],
                                    profile.get('specialeventsvalue') or [], strict=False):
            if kind not in _LANE_COLORS or not isinstance(idx, int) or not 0 <= idx < len(times):
                continue
            pct = events_internal_to_external_value(_number(value))
            if idx <= charge:
                before[kind] = pct
            elif idx <= drop:
                steps.setdefault(kind, []).append((times[idx] - t0, pct))
        lanes = []
        for kind in _LANE_ORDER:
            played = ([(0.0, before[kind])] if kind in before else []) + steps.get(kind, [])
            name = decodeLocalStrict(names[kind]).strip() if kind < len(names) else ''
            colour = QColor(colors[kind]) if colors and kind < len(colors) else QColor()
            if played and name:
                lanes.append(_Lane(kind, name, colour.name() if colour.isValid() else _LANE_COLORS[kind], played))
        return lanes

    @staticmethod
    def _gestures(lanes: list[_Lane]) -> list[_Moment]:
        """Settings changes after CHARGE; a setting moved again within a few seconds keeps its last value."""
        moments = []
        for lane in lanes:
            changes = [s for s in lane.steps if s[0] > 0]
            # a value equal to the one held at CHARGE is no gesture
            previous = lane.steps[0][1] if lane.steps[0][0] == 0 else None
            kept: list[tuple[float, int]] = []
            for i, (t, value) in enumerate(changes):
                if i + 1 < len(changes) and changes[i + 1][0] - t < _SETTLE_S:
                    continue
                if t <= _SETTLE_S:   # set with the charge: the opening value, not a gesture
                    previous = value
                elif value != previous:
                    kept.append((t, value))
                    previous = value
            moments.extend(_Moment(t, f'{lane.name} {value} %', lane.color, kind=lane.kind) for t, value in kept)
        return moments

    @staticmethod
    def _fit_moments(milestones: list[_Moment], gestures: list[_Moment], lanes: list[_Lane],
                     capacity: int) -> list[_Moment]:
        """Every gesture when the column holds them; otherwise the least decisive settings go first."""
        room = capacity - len(milestones)
        order = [lane.kind for lane in lanes]
        while len(gestures) > room and len(order) > 1:
            dropped = order.pop()
            gestures = [g for g in gestures if g.kind != dropped]
        if len(gestures) > room:
            gestures = sorted(gestures, key=lambda g: g.t)[:max(0, room)]
        return sorted(milestones + gestures, key=lambda m: (m.t, not m.milestone))

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
    def _header(self, p: QPainter, profile: dict, bean, marks: dict[str, int],
                duration: float | None, energy: str) -> None:
        bt = profile.get('temp2') or []
        unit = '°F' if profile.get('mode') == 'F' else '°C'
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

        dash = '—'
        phases = self._phase_durations(profile, marks)
        development = dash
        if phases[2] is not None and duration:
            development = f'{_mmss(phases[2])} · {phases[2] / duration * 100:.1f} %'
        rise = dash
        if 'fc' in marks and 'drop' in marks:
            fc_bt, drop_bt = _number(bt[marks['fc']]), _number(bt[marks['drop']])
            if fc_bt is not None and drop_bt is not None and fc_bt > 0 and drop_bt > 0:
                rise = f'{drop_bt - fc_bt:+.1f} {unit}'
        weight = profile.get('weight') or []
        incoming = _number(weight[0]) if len(weight) >= 3 else None
        outgoing = _number(weight[1]) if len(weight) >= 3 else None
        wunit = decodeLocalStrict(weight[2], 'g') if len(weight) >= 3 else 'g'
        loss = dash
        if incoming and outgoing and incoming > 0 and outgoing > 0:
            loss = f'{(incoming - outgoing) / incoming * 100:.1f} %'
        agtron = self.agtron_of(profile)
        ground = _number(profile.get('ground_color'))
        colour_label = (QApplication.translate('tilauscope_common', 'Colour') if not agtron else
                        QApplication.translate('tilauscope_roast_review', 'Colour · ground')
                        if ground is not None and ground > 0 else
                        QApplication.translate('tilauscope_roast_review', 'Colour · whole bean'))
        ambient = []
        for key, fmt in (('ambientTemp', '{:.0f} ' + unit), ('ambient_humidity', '{:.0f} %'),
                         ('ambient_pressure', '{:.0f} hPa')):
            value = _number(profile.get(key))
            if value:
                ambient.append(fmt.format(value))
        dev = _PHASE_COLORS[2]
        columns = [
            [(QApplication.translate('tilauscope_roast_review', 'Total duration'),
              _mmss(duration) if duration else dash, _TEXT),
             (QApplication.translate('Label', 'Development'), development, dev),
             (QApplication.translate('tilauscope_roast_review', 'Development rise'), rise, dev)],
            [(QApplication.translate('tilauscope_common', 'Green weight'),
              f'{incoming:g} {wunit}' if incoming else dash, _TEXT),
             (QApplication.translate('tilauscope_common', 'Roasted weight'),
              f'{outgoing:g} {wunit}' if outgoing else dash, _TEXT),
             (QApplication.translate('tilauscope_common', 'Weight loss'), loss, _TEXT)],
            [(colour_label, QApplication.translate('tilauscope_roast_review', 'Agtron') + f' {agtron}'
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
               lanes: list[_Lane]) -> None:
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

        def valid(series, i):
            v = _number(series[i]) if i < len(series) else None
            return v if v is not None and v != -1 else None

        span = range(charge, drop + 1)
        temps = [v for s in (bt, et) for i in span if (v := valid(s, i)) is not None]
        low = math.floor((min(temps) - 10) / 20) * 20 if temps else 0
        top = max(temps) if temps else 100
        step = 20 if top - low <= 180 else 40
        high = math.ceil((top + 0.2 * (top - low)) / step) * step
        def Y(v):
            return y1 - (v - low) / (high - low) * (y1 - _Y0)
        rvalues = [r for r in ror[charge:drop + 1] if r is not None]
        rstep = 4 if not rvalues or max(rvalues) <= 20 else 8
        rhigh = max(2 * rstep, math.ceil(max(rvalues, default=0) * 1.6 / rstep) * rstep)
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

        tp = self._turning_point(profile, marks)
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
        start = tp if tp is not None else charge
        self._polyline(p, [QPointF(X(times[i]), R(ror[i])) if i >= start and ror[i] is not None else None
                           for i in span], _RISE, 2.7)
        self._polyline(p, [QPointF(X(times[i]), Y(v)) if (v := valid(et, i)) is not None else None
                           for i in span], _PEACH, 2.4)
        self._polyline(p, [QPointF(X(times[i]), Y(v)) if (v := valid(bt, i)) is not None else None
                           for i in span], _BLUE, 3.4)
        p.restore()

        # peak rate of rise after the turning point
        after = [(r, i) for i in range(start, drop + 1) if (r := ror[i]) is not None]
        if after:
            r, i = max(after)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(_RISE))
            p.drawEllipse(QPointF(X(times[i]), R(r)), 5, 5)
            self._draw(p, X(times[i]), R(r) - 18, f'{r:.1f} {unit}/min', self._mono(22, True), _RISE, 'center')

        # milestones: dot on the bean curve and a callout on two alternating rows
        for n, (key, idx, label) in enumerate(moments):
            v = valid(bt, idx)
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
        phases = self._phase_durations(profile, marks)
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
                 lanes: list[_Lane]) -> None:
        self._rrect(p, QRectF(1846, 248, 522, 1040), 18, fill=_SURFACE, stroke=_BORDER)
        times, bt = profile.get('timex') or [], profile.get('temp2') or []
        charge = marks['charge']
        t0 = times[charge]
        self._draw(p, 1874, 300, QApplication.translate('tilauscope_roast_review', 'Key moments'),
                   self._font(26, True), _TEXT)
        for label, x, align in ((QApplication.translate('Label', 'Time'), 1874, 'left'),
                                (QApplication.translate('tilauscope_common', 'Bean'), 2036, 'right'),
                                (QApplication.translate('tilauscope_common', 'Rise'), 2136, 'right'),
                                (QApplication.translate('Label', 'Event'), 2168, 'left')):
            self._draw(p, x, 344, label, self._font(20), _FAINT, align)

        milestones = [_Moment(0.0, QApplication.translate('Tooltip', 'Charge'), _TEXT, True)]
        tp = self._turning_point(profile, marks)
        if tp is not None:
            milestones.append(_Moment(times[tp] - t0, QApplication.translate('Label', 'TP'), _MUTED, True))
        for key, label, colour in (('dry', QApplication.translate('tilauscope_common', 'Dry end'), _PHASE_COLORS[0]),
                                   ('fc', QApplication.translate('tilauscope_common', 'First crack'), _PHASE_COLORS[1]),
                                   ('drop', QApplication.translate('Tooltip', 'Drop'), _PHASE_COLORS[2])):
            if key in marks:
                milestones.append(_Moment(times[marks[key]] - t0, label, colour, True))
        # the rise is only meaningful from the turning point on, as on the curve
        start = tp if tp is not None else charge
        capacity = (_ROW_LAST - _ROW_Y0) // _ROW_STEP + 1
        rows = self._fit_moments(milestones, self._gestures(lanes), lanes, capacity)

        figures = self._mono(22)
        for n, row in enumerate(rows):
            y = _ROW_Y0 + n * _ROW_STEP
            # sample at that moment
            i = min(range(charge, marks['drop'] + 1), key=lambda k: abs(times[k] - t0 - row.t))
            if row.milestone:
                shade = QColor(_BORDER)
                shade.setAlpha(140)
                path = QPainterPath()
                path.addRoundedRect(QRectF(1860, y - 27, 494, 36), 6, 6)
                p.fillPath(path, shade)
            temp = _number(bt[i]) if i < len(bt) else None
            self._draw(p, 1874, y, _mmss(row.t), figures, _MUTED)
            self._draw(p, 2036, y, f'{temp:.1f}' if temp is not None and temp != -1 else '—', figures, _BLUE, 'right')
            rise = ror[i] if i >= start else None
            self._draw(p, 2136, y, f'{rise:.1f}' if rise is not None else '—', figures, _RISE, 'right')
            self._draw(p, 2168, y, row.text, self._font(22, row.milestone), row.color, max_w=190)

    # ── entry points ─────────────────────────────────────────────────────────
    def render(self, profile: dict, bean=None, deltabt=None, ror_unit: str | None = None,
               energy: str = '', lane_colors: list | None = None) -> QImage:
        marks = self._milestones(profile)
        times = profile.get('timex') or []
        has_frame = 'charge' in marks and 'drop' in marks and times[marks['drop']] > times[marks['charge']]
        duration = times[marks['drop']] - times[marks['charge']] if has_frame else None
        # RoR supplied by the viewer uses the current display unit, unlike stored BT.
        factor = 1.0
        if ror_unit and ror_unit != profile.get('mode', 'C'):
            factor = 1 / 1.8 if ror_unit == 'F' else 1.8
        ror = [v * factor if (v := _number(raw)) is not None else None for raw in (deltabt or [])]
        ror += [None] * (len(times) - len(ror))
        img = QImage(round(_W * _SCALE), round(_H * _SCALE), QImage.Format.Format_RGB32)
        img.fill(QColor(_BG))
        p = self._begin(img)
        p.scale(_SCALE, _SCALE)
        try:
            self._header(p, profile, bean, marks, duration, energy)
            if has_frame:
                lanes = self._lanes(profile, marks, lane_colors)
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

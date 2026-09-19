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

"""High-resolution portrait roast export, with aligned temperature and RoR panels."""

from __future__ import annotations

import logging
import math
from numbers import Real

from PyQt6.QtCore import QPointF, QRectF, Qt, QDateTime, QLocale
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from tilauscope.beancave_card_base import CardPainter
from tilauscope.tilauscope_types import (COLOR_AIR, COLOR_GRAIN, CRACK_TICK_ALPHA,
                                         PHASE_COLORS, dimmed, profile_crack_times)

_logd = logging.getLogger('tilaudebug')
_W, _H = 1080, 1620
_BG, _SURFACE, _BORDER = '#1E1E2E', '#181825', '#313244'
_TEXT, _MUTED = '#CDD6F4', '#BAC2DE'
# The probe hues the roasting window draws with: the card is the same picture
# as the screen the roast was driven on. The rate wears the bean's hue one step
# back — it belongs to the bean, and is never the line the roast is read from.
_BLUE, _PEACH = COLOR_GRAIN, COLOR_AIR
_RISE = dimmed(_BLUE, _BLUE)
_PHASE_COLORS = PHASE_COLORS   # drying, Maillard, development
_LEFT, _RIGHT = 112, 998
#: One crack tick at the foot of the rate-of-rise graph, scaled to the card's strokes.
_CRACK_TICK_H, _CRACK_TICK_W = 14, 2.0


def _number(value) -> float | None:
    if isinstance(value, Real) and math.isfinite(value):
        return float(value)
    return None


def _mmss(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


class RoastSocialCard(CardPainter):
    """Use logical pixel sizes, rendering at 2× independently of screen DPI."""

    def _font(self, size: int, bold: bool = False, tracking: float = 0.0) -> QFont:
        font = QFont(QApplication.font())
        font.setPixelSize(size)
        font.setBold(bold)
        if tracking:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + tracking)
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
            return QLocale().toString(QDateTime.fromSecsSinceEpoch(int(epoch)).date(), 'd MMM yyyy')
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

    def _label(self, p: QPainter, x: int, y: int, text: str,
               size: int = 26, width: int = 980, color: str = _TEXT, bold: bool = False) -> None:
        self._elided(p, x, y, text, self._font(size, bold), color, width)

    def _panel(self, p: QPainter, y: int, height: int) -> None:
        self._rrect(p, QRectF(30, y, 1020, height), 18, fill=_SURFACE, stroke=_BORDER)

    def _header(self, p: QPainter, profile: dict, bean, duration: float | None) -> None:
        country = str(getattr(bean, 'country', '') or '').strip()
        process = str(getattr(bean, 'process', '') or '').strip()
        self._label(p, 48, 30, ' · '.join(v for v in (country, process) if v), 25, color=_MUTED)
        name = str(getattr(bean, 'name', '') or profile.get('title') or '').strip()
        for i, line in enumerate(self._wrap(name, self._font(49, True), 980, 2)):
            self._label(p, 48, 67 + i * 56, line, 49, bold=True)
        self._label(p, 48, 185, ' · '.join(v for v in (self._date_label(profile),
                    str(profile.get('roastertype') or '').strip()) if v), 24, color=_MUTED)
        for x in (30, 552):
            self._rrect(p, QRectF(x, 238, 498, 130), 18, fill=_SURFACE, stroke=_BORDER)
        self._label(p, 52, 254, QApplication.translate('tilauscope_roast_review', 'Total duration'), 25, 450, _MUTED)
        self._label(p, 52, 291, _mmss(duration) if duration is not None else '—', 53, 450, bold=True)
        ground = _number(profile.get('ground_color'))
        color_label = (QApplication.translate('tilauscope_roast_review', 'Colour · ground')
                       if ground is not None and ground > 0 else
                       QApplication.translate('tilauscope_roast_review', 'Colour · whole bean'))
        agtron = self.agtron_of(profile)
        if not agtron:
            color_label = QApplication.translate('tilauscope_roast_review', 'Colour')
        self._label(p, 574, 254, color_label, 25, 450, _MUTED)
        self._label(p, 574, 291,
                    QApplication.translate('tilauscope_roast_review', 'Agtron') + f' {agtron}'
                    if agtron else '—', 49, 450, bold=True)

    @staticmethod
    def _series(p: QPainter, times, values, start: int, end: int, X, Y,
                color: str, valid_temperature: bool = False) -> None:
        pen = QPen(QColor(color), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        segment = []
        for i in range(start, end + 1):
            value = _number(values[i]) if i < len(values) else None
            t = _number(times[i])
            # Artisan stores missing temperatures as -1. Missing data breaks the line.
            if value is None or t is None or (valid_temperature and value == -1):
                if len(segment) > 1:
                    p.drawPolyline(segment)
                segment = []
            else:
                segment.append(QPointF(X(t), Y(value)))
        if len(segment) > 1:
            p.drawPolyline(segment)

    def _charts(self, p: QPainter, profile: dict, marks: dict[str, int], deltabt, ror_unit) -> None:
        self._panel(p, 390, 412)
        self._panel(p, 820, 294)
        unit = '°F' if profile.get('mode') == 'F' else '°C'
        self._label(p, 52, 407, QApplication.translate('tilauscope_roast_review', 'Bean temperature') + f' · {unit}', 31, bold=True)
        self._label(p, 52, 839, QApplication.translate('tilauscope_roast_review', 'Rate of rise') + f' · {unit}/min', 30, color=_RISE, bold=True)
        times = profile.get('timex') or []
        bt = profile.get('temp2') or []
        if 'charge' not in marks or 'drop' not in marks:
            self._label(p, 90, 590, QApplication.translate('tilauscope_roast_review', 'Charge or drop not marked'), 30, 890, _MUTED)
            return
        start, end = marks['charge'], marks['drop']
        t0, duration = times[start], times[end] - times[start]
        if duration <= 0 or end <= start:
            return
        def X(t):
            return _LEFT + (t - t0) / duration * (_RIGHT - _LEFT)
        temps = [v for i in range(start, min(end + 1, len(bt)))
                 if (v := _number(bt[i])) is not None and v != -1]
        low = math.floor((min(temps) - 10) / 25) * 25 if temps else 0
        high = math.ceil((max(temps) + 10) / 25) * 25 if temps else 100
        def Y(value):
            return 754 - (value - low) / (high - low) * 284
        # RoR supplied by the viewer uses the current display unit, unlike stored BT.
        factor = 1.0
        if ror_unit and ror_unit != profile.get('mode', 'C'):
            factor = 1 / 1.8 if ror_unit == 'F' else 1.8
        ror = [v * factor if (v := _number(raw)) is not None else None
               for raw in deltabt] if deltabt is not None else []
        tp = (profile.get('computed') or {}).get('TP_idx')
        if not isinstance(tp, int) or not start <= tp <= end:
            # No inferred turning point: keep the supplied signed RoR if TP is unknown.
            tp = start
        rvalues = [v for v in ror[tp:end + 1] if v is not None]
        rlow = min(0, math.floor(min(rvalues) / 10) * 10) if rvalues else 0
        rhigh = max(10, math.ceil(max(rvalues) / 10) * 10) if rvalues else 30
        def YR(value):
            return 1040 - (value - rlow) / (rhigh - rlow) * 142
        rstep = max(10, math.ceil((rhigh - rlow) / 30) * 10)
        for lo, hi, step, ymap in ((low, high, 50, Y), (rlow, rhigh, rstep, YR)):
            for value in range(math.ceil(lo / step) * step, hi + 1, step):
                yy = ymap(value)
                p.setPen(QPen(QColor(_BORDER), 1))
                p.drawLine(QPointF(_LEFT, yy), QPointF(_RIGHT, yy))
                self._label(p, 40, int(yy) - 14, f'{value:.0f}', 23, 64, _MUTED)
        # Fixed time positions shared by both panels; reserve room for the final tick.
        step = max(60, math.ceil(duration / 5 / 60) * 60)
        ticks = [float(t) for t in range(0, math.ceil(duration), step) if duration - t > duration * .09]
        ticks.append(duration)
        for elapsed in ticks:
            xx = X(t0 + elapsed)
            p.setPen(QPen(QColor(_BORDER), 1))
            for top, bottom in ((470, 754), (898, 1040)):
                p.drawLine(QPointF(xx, top), QPointF(xx, bottom))
            label = _mmss(elapsed)
            width = QFontMetrics(self._font(24)).horizontalAdvance(label)
            self._label(p, int(xx - width / 2), 1064, label, 24, width + 4, _MUTED)
        # One tick per pop heard, as the roasting window draws it: overlapping
        # ticks build the density, under the milestones and the curve.
        tick = QColor(_PEACH)
        tick.setAlpha(CRACK_TICK_ALPHA)
        p.setPen(QPen(tick, _CRACK_TICK_W))
        for t in profile_crack_times(profile):
            if t0 <= t <= times[end]:
                xx = X(t)
                p.drawLine(QPointF(xx, 1038 - _CRACK_TICK_H), QPointF(xx, 1038))
        for key, color in zip(('dry', 'fc', 'drop'), _PHASE_COLORS, strict=True):
            if key not in marks:
                continue
            xx = X(times[marks[key]])
            pen = QPen(QColor(color), 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            for top, bottom in ((470, 754), (898, 1040)):
                p.drawLine(QPointF(xx, top), QPointF(xx, bottom))
        p.save()
        p.setClipRect(QRectF(_LEFT - 3, 468, _RIGHT - _LEFT + 6, 289))
        self._series(p, times, bt, start, end, X, Y, _BLUE, True)
        p.restore()
        if rvalues:
            p.save()
            p.setClipRect(QRectF(_LEFT - 3, 896, _RIGHT - _LEFT + 6, 148))
            self._series(p, times, ror, tp, end, X, YR, _RISE)
            p.restore()
            for key in ('fc', 'drop'):
                idx = marks.get(key)
                value = ror[idx] if idx is not None and tp <= idx < len(ror) else None
                if value is not None:
                    xx, yy = X(times[idx]), YR(value)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(_RISE))
                    p.drawEllipse(QPointF(xx, yy), 5, 5)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    self._label(p, min(int(xx) - 18, _RIGHT - 48), int(yy) - 32,
                                f'{value:.1f}', 23, 64, _RISE, True)
        else:
            self._label(p, 220, 954, QApplication.translate('tilauscope_roast_review', 'Rate of rise unavailable'), 28, 760, _MUTED)
        for key, color in zip(('dry', 'fc', 'drop'), _PHASE_COLORS, strict=True):
            idx = marks.get(key)
            value = _number(bt[idx]) if idx is not None and idx < len(bt) else None
            if value is not None and value != -1:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QPointF(X(times[idx]), Y(value)), 6, 6)
                p.setBrush(Qt.BrushStyle.NoBrush)

    def _summary(self, p: QPainter, profile: dict, marks, duration) -> None:
        times, bt = profile.get('timex') or [], profile.get('temp2') or []
        unit = '°F' if profile.get('mode') == 'F' else '°C'
        labels = (QApplication.translate('tilauscope_roast_review', 'Dry end'),
                  QApplication.translate('tilauscope_roast_review', 'First crack'),
                  QApplication.translate('tilauscope_roast_review', 'Drop'))
        missing = QApplication.translate('tilauscope_roast_review', 'Not marked')
        for i, (key, label, color) in enumerate(zip(('dry', 'fc', 'drop'), labels, _PHASE_COLORS, strict=True)):
            x = 48 + 342 * i
            self._label(p, x, 1140, label, 26, 312, color, True)
            idx = marks.get(key)
            if idx is None or 'charge' not in marks:
                value = missing
            else:
                value = _mmss(times[idx] - times[marks['charge']])
                temp = _number(bt[idx]) if idx < len(bt) else None
                if temp is not None and temp != -1:
                    value += f' · {temp:.0f} {unit}'
            self._label(p, x, 1182, value, 32, 312, bold=True)
        phases = self._phase_durations(profile, marks)
        phase_labels = (QApplication.translate('tilauscope_roast_review', 'Drying'),
                        QApplication.translate('tilauscope_roast_review', 'Maillard'),
                        QApplication.translate('tilauscope_roast_review', 'Development'))
        if duration and all(v is not None for v in phases):
            x = 30.0
            for length, color in zip(phases, _PHASE_COLORS, strict=True):
                width = 1020 * length / duration
                p.fillRect(QRectF(x, 1250, width, 22), QColor(color))
                x += width
        else:
            p.fillRect(QRectF(30, 1250, 1020, 22), QColor(_BORDER))
        for i, (label, length, color) in enumerate(zip(phase_labels, phases, _PHASE_COLORS, strict=True)):
            x = 48 + 342 * i
            self._label(p, x, 1300, label, 26, 312, color, True)
            value = _mmss(length) if length is not None else '—'
            if length is not None and duration:
                value += f' · {length / duration * 100:.1f} %'
            self._label(p, x, 1342, value, 36, 312, color, True)
        self._panel(p, 1430, 100)
        weight = profile.get('weight') or []
        incoming = _number(weight[0]) if len(weight) >= 3 else None
        outgoing = _number(weight[1]) if len(weight) >= 3 else None
        mass = '—'
        loss = '—'
        if incoming is not None and incoming > 0:
            mass = f'{incoming:g} {weight[2]}'
            if outgoing is not None and outgoing > 0:
                mass += f' → {outgoing:g} {weight[2]}'
                loss = f'{(incoming - outgoing) / incoming * 100:.1f} %'
        self._label(p, 52, 1458, mass, 34, 500, bold=True)
        self._label(p, 580, 1443, QApplication.translate('tilauscope_roast_review', 'Weight loss'), 23, 440, _MUTED)
        self._label(p, 580, 1475, loss, 32, 440, bold=True)
        self._label(p, 48, 1561, 'TilauScope', 26, 400, _MUTED, True)

    def render(self, profile: dict, bean=None, deltabt=None, ror_unit: str | None = None) -> QImage:
        marks = self._milestones(profile)
        times = profile.get('timex') or []
        duration = (times[marks['drop']] - times[marks['charge']]
                    if 'drop' in marks and 'charge' in marks else None)
        img = QImage(_W * 2, _H * 2, QImage.Format.Format_RGB32)
        img.fill(QColor(_BG))
        p = self._begin(img)
        p.scale(2, 2)
        try:
            self._header(p, profile, bean, duration)
            self._charts(p, profile, marks, deltabt, ror_unit)
            self._summary(p, profile, marks, duration)
        finally:
            p.end()
        return img

    def save_png(self, profile: dict, file_path: str, bean=None, deltabt=None,
                 ror_unit: str | None = None) -> bool:
        try:
            return self.render(profile, bean, deltabt, ror_unit).save(file_path, 'PNG')
        except Exception:
            _logd.error('roast card: render failed', exc_info=True)
            return False

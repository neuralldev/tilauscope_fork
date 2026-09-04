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

"""Fixed-axis roast curve widget — TilauScope's own curve engine.

Draws grain temperature and rate-of-rise as Artisan-smoothed polylines over
fixed axes. Deliberately just the socle: no milestones, no plan envelope, no
fixed axes. Deliberately just the socle: no milestones, no plan envelope, no
phase bands, and no projection cone. Those are later layers; the curve menu
keeps only display preferences and is not part of the roast data.
render shape and cost before investing further.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Final

from PyQt6.QtCore import QPointF, QSettings, QRectF, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from artisanlib.util import convertRoRstrict, convertTemp, findTPint
from tilauscope.graph import smoothing as smooth
from tilauscope.graph.annotation import AnnotationLayer
from tilauscope.graph.crackbar import CrackBar
from tilauscope.graph.common import (
    COLOR_AIR as _COLOR_AIR,
    COLOR_GRAIN as _COLOR_GRAIN,
    ROR_MIN as _ROR_MIN,
    channel_order,
    fmt_clock,
    fmt_temp,
    marked,
    menu_qss,
    report_once,
    dimmed,
    rise_series,
    ror_axis_c as _ror_axis_c,
    temp_axis_c as _temp_axis_c,
)
from tilauscope.graph.preheat import reading as preheat_reading
from tilauscope.theme_qss import tooltip_qss
from tilauscope.tilauscope_types import THEME, resolve_crack_channel

# ── fixed axis extents — never autoscaled, never recomputed from data ──────
_TIME_MAX: Final[float] = 840.0   # 14:00 in seconds — the FULL-SCALE window
_TIME_STEP: Final[float] = 60.0
#: One gridline for this many labelled minutes. Every minute is named; a line
#: every minute would be a picket fence behind the curve.
_TIME_LINE_EVERY: Final[int] = 2
#: How far past its own span a preheat axis may open to show the arrival.
_ARRIVAL_MAX_SHARE: Final[float] = 1.5
#: Replay speeds offered in the simulator, in the order they are shown.
_SPEEDS: Final[tuple[int, ...]] = (1, 2, 8)
#: How far the arrival tick hangs below the target line.
_ARRIVAL_TICK: Final[float] = 14.0
#: Chart kept clear to the right of the projected arrival, so its marker is
#: never drawn on the frame itself.
_ARRIVAL_PAD: Final[float] = 20.0
#: The preheat frame, and the roast's own full scale. A preheat is a long
#: climb; a frame sized to what has been climbed so far rescales under the
#: curve and says the drum will be ready in two minutes.
_PREHEAT_SPAN: Final[float] = _TIME_MAX
_LEAD_IN: Final[float] = 60.0     # the minute before charge, kept in view
_TAIL_OUT: Final[float] = 60.0    # ...and ends one minute after drop
# The scales come from `graph.common`: the phone is told the same table, and a
# chart that changes bounds between the two screens is read wrong on one of them.

# ── layout ───────────────────────────────────────────────────────────────────
_MARGIN_LEFT: Final[int] = 68      # room for temp axis labels, and for the lane names
_MARGIN_RIGHT: Final[int] = 68     # room for RoR axis labels
_MARGIN_TOP: Final[int] = 36       # unit captions, and the view selector above the plot
_MARGIN_BOTTOM: Final[int] = 62    # time axis labels, then the legend row beneath them

_GRAIN_PEN_WIDTH: Final[float] = 3.0
_ROR_PEN_WIDTH: Final[float] = 2.0
_MACHINE_ROR_PEN_WIDTH: Final[float] = 1.6
#: Reference traces keep the probe hues, but sit far enough behind the live
#: roast that the operator never has to ask which line is the one being driven.
_REFERENCE_ALPHA: Final[int] = 72

# Curve colours come from Artisan's own palette — the same source the readouts
# beside the chart are painted from, so the two can never disagree about which
# colour means which probe. One hue per PROBE, not per quantity: the bean and
# its rate are one family, the air and its rate another. Within a family the
# temperature is the solid line and the rate the quieter one, so a rate is never
# mistaken for the line the roast is read from.
#
# The hues and their fallbacks live in `graph.common`, which the phone reads too.
_AIR_PEN_WIDTH: Final[float] = 1.8

# Axis figures and lane names are read at a glance from a step back, not
# studied: both were a size that had to be squinted at.
_AXIS_FONT_PT: Final[int] = 11
_TITLE_FONT_PT: Final[int] = 12
#: Room the coach toggle takes in the top margin, so the title clears it.
_TOGGLE_CLEARANCE: Final[float] = 36.0
#: The crack band: a thin strip at the foot of the plot, and how dark one
#: pop is drawn — light enough that density has somewhere to build.
_CRACK_BAND_HEIGHT: Final[float] = 9.0
_CRACK_TICK_ALPHA: Final[int] = 90
_MARK_FONT_PT: Final[int] = 11     # a milestone is read across the room, not squinted at

# Phase grounds. Blue then yellow then red: peach and red sat one step apart on
# the wheel and the Maillard and development stretches read as one block. The
# alpha also climbs, so the roast visibly intensifies as it advances.
_PHASE_DRYING: Final[tuple[str, int]] = ('SKY', 16)
_PHASE_MAILLARD: Final[tuple[str, int]] = ('YELLOW', 22)
_PHASE_DEVELOPMENT: Final[tuple[str, int]] = ('CRITICAL', 32)
_MARK_LABEL_ROWS: Final[int] = 3      # stagger depth before labels are allowed to touch
_MARK_ROW_HEIGHT: Final[float] = 23.0
_MARK_CHIP_PAD: Final[float] = 7.0
_MARK_DOT_RADIUS: Final[float] = 4.0

# The settings lanes: what was played on the machine, on the same time axis as
# the roast above. Their whole point is reading a change against the curve it
# caused, so they share every gridline.
#
# One lane per channel, each with its own baseline. A burner at 60% and an
# airflow at 30% do not measure the same physical thing; stacking them on a
# single axis makes them cross constantly and asks the eye to untangle
# comparisons that mean nothing. Separate baselines make crossing impossible,
# and each channel is named beside its own lane instead of in a legend.
_LANE_ROW_HEIGHT: Final[float] = 26.0
_LANE_ROW_GAP: Final[float] = 4.0
_LANE_MAX_SHARE: Final[float] = 0.34
_LANE_GAP: Final[float] = 12.0
_LEGEND_FONT_PT: Final[int] = 10
_LANE_MAX: Final[float] = 100.0
_LANE_PEN_WIDTH: Final[float] = 1.6
_LANE_FILL_ALPHA: Final[int] = 70
_LANE_MARK_HEIGHT: Final[float] = 28.0
# Keep the traced channel at its established amplitude. Only gesture lanes need
# extra height for their second value row.
_LANE_AREA_HEIGHT: Final[float] = 19.0 * 2.4
_BURNER_INDEX: Final[int] = 3            # Air=0, Drum=1, Damper=2, Burner=3
_LANE_LABEL_ROWS: Final[int] = 2
_LANE_LABEL_GAP: Final[float] = 1.0

# Two ways to read what was played. 'lanes' gives every channel its own baseline
# and its own shape; 'burner' traces the one lever that writes the roast and
# reduces the others to the gestures they actually are.
_LANE_MODE_LANES: Final[str] = 'lanes'
_LANE_MODE_BURNER: Final[str] = 'burner'
_HOVER_FONT_PT: Final[int] = 10

# Curve display choices are application preferences, not roast data. Read them
# once when the widget is created and write them only when the menu changes.
_SHOW_AIR_KEY: Final[str] = 'tilauscope/curve_show_air_temperature'
_SHOW_MACHINE_RESPONSE_KEY: Final[str] = 'tilauscope/curve_show_machine_response'
_LANE_MODE_KEY: Final[str] = 'tilauscope/curve_lane_mode'


_background_rise_cache: dict[str, Any] = {}


def _background_origin(timex: Any, charge: Any) -> float | None:
    """The instant the reference is anchored on, or None if it has no trace.

    A reference marked at CHARGE is anchored there, which is the comparison
    that means something. Not every reference carries one: a curve built by
    the plotter, fitted by the analyzer, or recorded without the milestone has
    no charge index at all, and dropping it would leave a loaded reference
    drawn nowhere. Those are anchored on their own first sample, which is
    where Artisan itself starts them.
    """
    try:
        if len(timex) < 2:
            return None
        index = int(charge)
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(timex):
        return float(timex[index])
    return float(timex[0])


def _lane_label_layout(
    markers: list[tuple[float, float]], left: float, right: float,
) -> list[tuple[float, int]]:
    """Place every lane value directly above or below its own event dot.

    ``markers`` contains ``(dot_x, label_width)`` in chronological order. A
    value entered a few seconds after the previous one can share almost the
    same pixel column on the fourteen-minute view. Values alternate between two
    compact rows and never create a taller lane. They remain centred on their
    marker; clipping at a frame edge is the sole case where exact centring is
    geometrically impossible.
    """
    if not markers or right <= left:
        return []

    row_right = [float('-inf')] * _LANE_LABEL_ROWS
    placed: list[tuple[float, int]] = []

    for dot_x, raw_width in markers:
        width = min(max(1.0, raw_width), right - left)
        x = max(left, min(dot_x - width / 2.0, right - width))
        free = [i for i, end in enumerate(row_right)
                if x >= end + _LANE_LABEL_GAP]
        # If both rows are saturated, keep the point/value association exact.
        # A local overlap is less misleading than moving the value toward a
        # neighbouring marker, and the compact chip makes this case uncommon.
        row = free[0] if free else min(range(_LANE_LABEL_ROWS),
                                       key=lambda i: row_right[i])
        row_right[row] = max(row_right[row], x + width)

        placed.append((x, row))

    return placed


def _reference_colour(colour: str) -> QColor:
    """The live trace's hue at reference strength."""
    result = QColor(colour)
    result.setAlpha(_REFERENCE_ALPHA)
    return result


def _background_rise_series(qmc: Any, *, machine: bool = False) -> list[Any]:
    """Once recompute one background rate-of-rise series.

    Artisan's held ``delta1B``/``delta2B`` may still belong to the previous
    background until its own canvas redraws. TilauScope can paint first,
    especially while a profile is loaded during monitoring, so it computes
    from the current temperature arrays instead. The cache follows profile and
    array identity: loading another background invalidates it without adding
    recurring work to the paint path.
    """
    try:
        timex = qmc.timeB
        stemp1 = qmc.stemp1B if len(qmc.stemp1B) == len(timex) else qmc.temp1B
        stemp2 = qmc.stemp2B if len(qmc.stemp2B) == len(timex) else qmc.temp2B
        timeindex = qmc.timeindexB
        charge = int(timeindex[0])
        drop = int(timeindex[6])
    except (AttributeError, IndexError, TypeError, ValueError):
        return []
    if not timex:
        return []
    # An unmarked reference is still a rise worth computing: run it over the
    # whole recording rather than returning nothing.
    if not 0 <= charge < len(timex):
        charge = 0
    if not 0 < drop < len(timex):
        drop = len(timex) - 1

    key = (id(qmc.backgroundprofile), id(timex), id(stemp1), id(stemp2),
           len(timex), float(timex[0]),
           float(timex[-1]), charge, drop,
           getattr(qmc, 'background_profile_sampling_interval', None))
    if (_background_rise_cache.get('owner') is not qmc
            or _background_rise_cache.get('key') != key):
        _background_rise_cache.clear()
        _background_rise_cache['owner'] = qmc
        _background_rise_cache['key'] = key
        try:
            kwargs: dict[str, Any] = {}
            interval = getattr(qmc, 'background_profile_sampling_interval', None)
            if interval is not None and float(interval) > 0.0:
                kwargs['deltaETsamples'] = max(
                    1, int(round(float(qmc.deltaETspan) / float(interval))))
                kwargs['deltaBTsamples'] = max(
                    1, int(round(float(qmc.deltaBTspan) / float(interval))))
            start = min(charge + 10, len(timex) - 1)
            kwargs['optimalSmoothing'] = bool(
                getattr(qmc, 'optimalSmoothing', False))
            d1, d2 = qmc.recomputeDeltas(
                timex, start, drop, stemp1, stemp2, **kwargs)
            _background_rise_cache['delta1'] = list(d1 or [])
            _background_rise_cache['delta2'] = list(d2 or [])
        except Exception:
            report_once('RoastCurveWidget: background rise recompute failed')
            _background_rise_cache['delta1'] = []
            _background_rise_cache['delta2'] = []
    return list(_background_rise_cache.get(
        'delta1' if machine else 'delta2', []))


def _background_roast(qmc: Any, *, show_air: bool,
                      show_machine: bool) -> tuple[
                          list[float], list[Any], list[Any],
                          list[Any], list[Any], str] | None:
    """A loaded reference, anchored on its own charge when it has one.

    Artisan mutates ``timeB`` when its background is aligned on DRY, FC or
    DROP, and mutates the temperatures when the background is nudged vertically.
    Those are canvas adjustments, not roast data. Removing both offsets here
    gives TilauScope one invariant comparison: CHARGE on CHARGE, at the recorded
    temperatures, regardless of how Artisan's separate canvas was arranged.
    """
    # ``background`` is only the visibility flag of Artisan's own canvas. It
    # is commonly reset to False when a foreground profile is opened, while
    # the reference itself remains fully loaded in the B arrays. DisplayScope
    # owns its comparison visibility: only emptying the B arrays removes the
    # reference here. A profile is not what makes one: the plotter, the
    # analyzer's curve fit and a background equation all fill those arrays
    # with no profile behind them, and each is a reference the operator asked
    # for and expects to see.
    try:
        raw_time = list(qmc.timeB)
        raw_bt = list(qmc.temp2B)
        raw_air = list(qmc.temp1B) if show_air else []
        timeindex = list(qmc.timeindexB)
        mode = str(qmc.mode)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    origin = _background_origin(raw_time, timeindex[0] if timeindex else -1)
    if origin is None:
        return None

    timex = [float(t) - origin for t in raw_time]
    try:
        y_offset = float(getattr(qmc, 'backgroundprofile_moved_y', 0.0) or 0.0)
    except (TypeError, ValueError):
        y_offset = 0.0
    temp2 = [float(v) - y_offset if v not in (None, -1) else v for v in raw_bt]
    temp1 = [float(v) - y_offset if v not in (None, -1) else v for v in raw_air]
    delta2 = _background_rise_series(qmc)
    delta1 = _background_rise_series(qmc, machine=True) if show_machine else []
    return timex, temp1, temp2, delta2, delta1, mode


def _crisp(x: float) -> float:
    """The middle of a pixel column, where a hairline paints solid."""
    return math.floor(x) + 0.5


def _milestone_label(i: int) -> str:
    """Translated milestone name. One literal per case — a table built in a
    loop would be invisible to the string extractor."""
    if i == 0:
        return QApplication.translate('tilauscope', 'CHARGE')
    if i == 1:
        return QApplication.translate('tilauscope', 'DRY END')
    if i == 2:
        return QApplication.translate('tilauscope', 'FIRST CRACK')
    if i == 3:
        return QApplication.translate('tilauscope', 'FC END')
    if i == 4:
        return QApplication.translate('tilauscope', 'SECOND CRACK')
    if i == 5:
        return QApplication.translate('tilauscope', 'SC END')
    if i == 6:
        return QApplication.translate('tilauscope', 'DROP')
    return QApplication.translate('tilauscope', 'COOL END')


def _sample_temp_c(raw: Any, mode: str) -> float | None:
    """Convert one raw qmc.temp2 sample to °C, or None if it is not a point.

    None and the Artisan -1 sentinel both mean "no reading here" — the
    polyline must break, not interpolate through them.
    """
    if raw is None or raw == -1:
        return None
    return convertTemp(float(raw), mode, 'C')


def _readings(temp2: list[Any], wanted: int = 2) -> bool:
    """True once `wanted` samples carry an actual reading.

    A probe answering nothing fills the arrays with the -1 sentinel, and a
    frame built on those says "the drum is climbing" over a chart with no line
    on it. The empty state has a sentence for that case; this is what leaves it
    the room to say it.
    """
    seen = 0
    for raw in temp2:
        if raw is None or raw == -1:
            continue
        seen += 1
        if seen >= wanted:
            return True
    return False


def _sample_ror_c(raw: Any, mode: str) -> float | None:
    """Convert one raw qmc.delta1/delta2 sample to °C/min, or None.

    Uses convertRoRstrict (scale-only) rather than convertTemp — a rate
    conversion must not carry the ±32 Fahrenheit offset.
    """
    if raw is None or raw == -1:
        return None
    return convertRoRstrict(float(raw), mode, 'C')


def readout_parts(t: float, temp_c: float | None, air_c: float | None,
                  ror_c: float | None, machine_c: float | None,
                  grain: str, air: str, rise: str, machine_rise: str,
                  ) -> list[tuple[str, str, str]]:
    """The crosshair row: (name, figure, colour) for every reading under it.

    Each figure is named, in the same words the legend gives its trace. Two
    readings both ending in °/min sit side by side here and the row reads as a
    row of numbers: with colour as the only thing telling them apart, the
    machine's rate was taken for the bean's — the one figure on this screen
    that must never be misread, since it is what the panel shows in large type.
    """
    parts: list[tuple[str, str, str]] = [('', fmt_clock(t), THEME['TEXT'])]
    if temp_c is not None:
        parts.append((QApplication.translate('tilauscope', 'Bean'),
                      f'{int(round(temp_c))}°', grain))
    if air_c is not None:
        parts.append((QApplication.translate('tilauscope', 'Air'),
                      f'{int(round(air_c))}°', air))
    if ror_c is not None:
        parts.append((QApplication.translate('tilauscope', 'Rise'),
                      f'{ror_c:.1f}°/min', rise))
    if machine_c is not None:
        parts.append((QApplication.translate('tilauscope', 'Machine response'),
                      f'{machine_c:.1f}°/min', machine_rise))
    return parts


class RoastCurveWidget(QWidget):
    """Fixed-axis strip chart: grain temperature plus rate-of-rise.

    Axes are constant — no autoscale, no rescale on data growth. The frame
    (background, grid, tick labels, units) is cached to a QPixmap rebuilt
    only on `resizeEvent`. Live data is read and turned into polylines fresh
    on every `paintEvent`, since that is the only place Qt guarantees the
    widget's own geometry is current and paints are coalesced for free —
    `tick()` itself does no work at all, so the 1 Hz sampling loop never
    pays for chart cost.
    """

    def __init__(self, aw: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._aw = aw
        # Created first: it owns child widgets, and the layout runs during
        # construction — a card that does not exist yet cannot be placed.
        self.annotations = AnnotationLayer(self, aw)
        # The air, and the air's rate. Both are off by default; the choices are
        # restored between sessions so the curve remains shaped to the user's
        # preferred reading without adding any work to the sample path.
        settings = QSettings()
        self.show_machine_response: bool = settings.value(
            _SHOW_MACHINE_RESPONSE_KEY, False, type=bool)
        self.show_air_temperature: bool = settings.value(
            _SHOW_AIR_KEY, False, type=bool)

        self._plot_rect = QRectF()
        # The axes are fixed for a roast and only for a roast. A preheat is a
        # different climb over a different span, and squeezing it into the
        # roast's box would draw a flat line along the bottom for twenty
        # minutes — so the bounds are state, not constants.
        self._temp_lo, self._temp_hi, self._temp_step = _temp_axis_c('C')
        self._ror_max, self._ror_step = _ror_axis_c('C')
        self._time_step: float = _TIME_STEP
        #: The unit the axes are LABELLED in. The values behind them stay °C.
        self._mode: str = 'C'
        #: The live preheat, when one is running before the charge.
        self._preheat: Any = None
        #: Whether the pre-charge climb owns the frame this pass. True for a
        #: controller-driven preheat AND for a drum taken up by hand: both are
        #: the same rise, read on the same axis.
        self._climb_frame: bool = False
        #: Whether the right-hand rate scale is drawn. There is no rate before
        #: the charge — the drum is climbing, not roasting — and a scale with
        #: nothing on it invites reading the drum against the wrong numbers.
        self._rate_axis: bool = True
        saved_lane_mode = settings.value(_LANE_MODE_KEY, _LANE_MODE_LANES, type=str)
        self._lane_mode: str = (
            saved_lane_mode if saved_lane_mode in (_LANE_MODE_LANES, _LANE_MODE_BURNER)
            else _LANE_MODE_LANES)
        self._lane_rows: list[tuple[int, QRectF, str]] = []
        #: Pop times, rebuilt only when the recorded counter grows.
        self._crack_key: tuple[int, ...] | None = None
        self._crack_cache: list[float] = []
        self._frame: QPixmap | None = None
        self._frame_key: tuple[Any, ...] | None = None

        # Time window. While the roast runs it is charge -1:00 .. 14:00, the
        # fixed scale the spec settles on with a minute of lead-in; 'closeup'
        # trims to charge -1:00 .. drop +1:00 once the roast is over, and 'full'
        # then opens out to the whole session. Temperature and rise axes never
        # move in any view — only the time axis does.
        self._closeup: bool = True
        self._t_min: float = -_LEAD_IN
        self._t_max: float = _TIME_MAX

        # Hovered instant, in charge-relative seconds. Held as a time rather than
        # a sample index so it survives the data growing under the cursor.
        self._hover_t: float | None = None
        self.setMouseTracking(True)

        # A two-segment selector, not a single toggling label: a lone button saying
        # "Charge to drop" reads either as the view you are in or the view a click
        # would give, and both readings are reasonable. Showing both options with
        # the active one lit removes the question.
        self._view_btn = QWidget(self)
        _row = QHBoxLayout(self._view_btn)
        _row.setContentsMargins(0, 0, 0, 0)
        _row.setSpacing(0)
        self._seg_full = QPushButton(QApplication.translate('tilauscope', 'Full scale'))
        self._seg_closeup = QPushButton(QApplication.translate('tilauscope', 'Charge to drop'))
        for _b in (self._seg_full, self._seg_closeup):
            _b.setCheckable(True)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _row.addWidget(_b)
        self._seg_full.setStyleSheet(self._segment_qss(left=True, right=False))
        self._seg_closeup.setStyleSheet(self._segment_qss(left=False, right=True))
        self._seg_full.clicked.connect(lambda: self._set_closeup(False))
        self._seg_closeup.clicked.connect(lambda: self._set_closeup(True))
        self._view_btn.setVisible(False)   # appears only once a roast has a drop

        # Replay speed, simulator only. Changing it used to mean clicking the
        # clock with the right modifier held, which is neither discoverable nor
        # usable with one hand on the machine — and in a simulated roast the
        # speed is changed more often than anything else on the screen.
        self._speed_btn = QWidget(self)
        _srow = QHBoxLayout(self._speed_btn)
        _srow.setContentsMargins(0, 0, 0, 0)
        _srow.setSpacing(0)
        self._seg_speed: list[QPushButton] = []
        for _i, _mult in enumerate(_SPEEDS):
            _b = QPushButton(f'x{_mult}')
            _b.setCheckable(True)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _b.setStyleSheet(self._segment_qss(left=_i == 0,
                                               right=_i == len(_SPEEDS) - 1))
            _b.clicked.connect(lambda _c, m=_mult: self._set_speed(m))
            _srow.addWidget(_b)
            self._seg_speed.append(_b)
        self._speed_btn.setVisible(False)

        # TilauPID is an operator control only between START and CHARGE. Keep
        # it in the same top control band as the view and replay selectors.
        self._pid_btn = QWidget(self)
        _prow = QHBoxLayout(self._pid_btn)
        _prow.setContentsMargins(0, 0, 0, 0)
        _prow.setSpacing(0)
        self._pid_on = QPushButton(QApplication.translate('tilauscope', 'PID ON'))
        self._pid_off = QPushButton(QApplication.translate('tilauscope', 'PID OFF'))
        for _b in (self._pid_on, self._pid_off):
            _b.setCheckable(True)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            _prow.addWidget(_b)
        self._pid_on.setStyleSheet(self._segment_qss(left=True, right=False))
        self._pid_off.setStyleSheet(self._segment_qss(left=False, right=True))
        self._pid_on.clicked.connect(lambda: self._toggle_pid(True))
        self._pid_off.clicked.connect(lambda: self._toggle_pid(False))
        self._pid_btn.setVisible(False)

        # Swaps foreground and background (Artisan's own "Switch Profiles"),
        # right by the title since that is exactly what it renames. Like the
        # native action, it is locked while Artisan is sampling: switch()
        # mutates the live roast arrays and has no defensive guard of its own.
        self._switch_btn = QToolButton(self)
        self._switch_btn.setText('⇄')
        self._switch_btn.setFixedSize(22, 22)
        self._switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._switch_btn.setToolTip(QApplication.translate(
            'tilauscope', 'Swap the foreground roast and the background curve'))
        self._switch_btn.setStyleSheet(f"""
            QToolButton {{
                background-color: {THEME['SURFACE']};
                border: 1px solid {THEME['SURFACE1']};
                border-radius: 5px;
                font-size: 12px;
                color: {THEME['SUBTEXT']};
            }}
            QToolButton:hover {{ border: 1px solid {THEME['ACCENT']}; color: {THEME['TEXT']}; }}
            QToolButton:disabled {{
                background-color: {THEME['BG']};
                border: 1px solid {THEME['BORDER']};
                color: {THEME['OVERLAY0']};
            }}
            {tooltip_qss()}
        """)
        self._switch_btn.clicked.connect(self._on_switch_clicked)

        # The acoustic counter, read as a phase. It sits in the middle of this
        # same strip: the two ends are taken, the middle is empty on every
        # roast, and a readout there covers none of the trace it comments on.
        self._crack_bar = CrackBar(aw, self)
        self._crack_bar.set_operator_level(
            settings.value('tilauscope/operator_level', 'guided', type=str))

        self._sync_pid_button()
        self._sync_view_button()
        self._sync_switch_button()

        # Avoids a flash of the platform-default background before the first
        # resizeEvent has had a chance to build the cached frame.
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(THEME['BG']))
        self.setPalette(pal)

        self.setMinimumSize(420, 240)
        # Lay out once here rather than wait for a resize. The plot rectangle
        # used to be filled by a side effect — the first tick found the lane
        # list out of date and relaid out — which held only while the lanes
        # were always there. A widget whose geometry depends on something else
        # happening first paints an empty frame when that something stops.
        self._layout()

    # ── public API ───────────────────────────────────────────────────────
    def set_operator_level(self, level: str) -> None:
        """Propagate the level to the overlays that read it."""
        self._crack_bar.set_operator_level(level)
        self._place_crack_bar()

    @staticmethod
    def _segment_qss(left: bool, right: bool = True) -> str:
        radius = ''
        if left:
            radius += 'border-top-left-radius:4px;border-bottom-left-radius:4px;'
        if right:
            radius += 'border-top-right-radius:4px;border-bottom-right-radius:4px;'
        return (f"QPushButton {{ color:{THEME['OVERLAY0']}; background:transparent;"
                f" border:1px solid {THEME['BORDER']}; border-radius:0px; {radius}"
                f" padding:2px 9px; font-size:11px; }}"
                f"QPushButton:hover {{ color:{THEME['TEXT']}; }}"
                f"QPushButton:checked {{ color:{THEME['TEXT']};"
                f" background:{THEME['BORDER']}; }}")

    def _set_closeup(self, closeup: bool) -> None:
        if closeup != self._closeup:
            self._closeup = closeup
        self._sync_view_button()
        self.update()

    def _sync_view_button(self) -> None:
        self._seg_full.setChecked(not self._closeup)
        self._seg_closeup.setChecked(self._closeup)
        self._view_btn.adjustSize()
        self._place_view_button()
        self._place_speed_button()

    def _set_speed(self, speed: int) -> None:
        try:
            self._aw.tilau_set_simulator_speed(speed)
        except AttributeError:
            report_once('RoastCurveWidget: no simulator speed control')
        self._sync_speed_button()

    def _speed_now(self) -> int:
        """The replay speed the clock is actually running at."""
        try:
            return int(round(self._aw.qmc.timeclock.getBase() / 1000))
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return 1

    def _sync_speed_button(self) -> None:
        speed = self._speed_now()
        for button, mult in zip(self._seg_speed, _SPEEDS, strict=True):
            button.setChecked(mult == speed)
        self._speed_btn.adjustSize()
        self._place_speed_button()

    def _preheating_window(self) -> bool:
        qmc = getattr(self._aw, 'qmc', None)
        if qmc is None or not getattr(qmc, 'flagstart', False):
            return False
        try:
            return not marked(qmc.timeindex, 0)
        except (AttributeError, IndexError, TypeError):
            return False

    def _sync_pid_button(self) -> None:
        pid = getattr(self._aw, 'tilauPreheatingPid', None)
        preheating = self._preheating_window()
        active = bool(pid is not None and getattr(pid, 'active', False))
        if not preheating and active:
            try:
                pid.stop(reason='charge')
            except (AttributeError, TypeError):
                report_once('RoastCurveWidget: PID stop after charge failed')
            active = False
        if getattr(self._aw, '_tilaupid_user_disabled', False):
            active = False
        self._pid_on.setChecked(active)
        self._pid_off.setChecked(not active)
        if active:
            tip = QApplication.translate('tilauscope', 'Disable TilauPID preheating')
        else:
            tip = QApplication.translate('tilauscope', 'Enable TilauPID preheating')
        self._pid_on.setToolTip(tip)
        self._pid_off.setToolTip(tip)
        if self._pid_btn.isVisible() != preheating:
            self._pid_btn.setVisible(preheating)
        self._pid_btn.adjustSize()
        self._place_pid_button()

    def _toggle_pid(self, enabled: bool) -> None:
        if not self._preheating_window():
            self._sync_pid_button()
            return
        pid = getattr(self._aw, 'tilauPreheatingPid', None)
        if pid is None:
            self._sync_pid_button()
            return
        try:
            if enabled:
                self._aw._tilaupid_user_disabled = False
                slider_sv = getattr(self._aw, 'sliderSV', None)
                sv = int(slider_sv.value()) if slider_sv is not None else None
                pid.start(sv)
            else:
                self._aw._tilaupid_user_disabled = True
                pid.stop(reason='operator_toggle')
        except (AttributeError, TypeError, ValueError):
            report_once('RoastCurveWidget: PID toggle failed')
        self._sync_pid_button()
        scope = getattr(self._aw, 'tilauscope_main', None)
        if scope is not None:
            scope.refresh_preheat_status()

    def _place_speed_button(self) -> None:
        # Left of the view selector and on its row, so the top strip reads as
        # one set of controls rather than two floating boxes.
        r = self._plot_rect
        if r.width() <= 1:
            return
        right = (self._view_btn.x() - 8 if self._view_btn.isVisible()
                 else int(r.right()))
        self._speed_btn.move(right - self._speed_btn.width(),
                             max(0, int(r.top()) - self._speed_btn.height() - 5))

    def _place_pid_button(self) -> None:
        r = self._plot_rect
        if r.width() <= 1:
            return
        right = (self._speed_btn.x() - 8 if self._speed_btn.isVisible()
                 else self._view_btn.x() - 8 if self._view_btn.isVisible()
                 else int(r.right()))
        self._pid_btn.move(right - self._pid_btn.width(),
                           max(0, int(r.top()) - self._pid_btn.height() - 5))

    def _place_crack_bar(self) -> None:
        # Centred in what the two ends of the strip leave free. Clamped rather
        # than overlapped: on a narrow window the controls keep their places and
        # the bar gives way, because they can be clicked and it cannot.
        if not self._crack_bar.isVisible():
            return
        r = self._plot_rect
        if r.width() <= 1:
            return
        left = int(r.left())
        if not self.annotations.view_toggle.isHidden():
            left += int(_TOGGLE_CLEARANCE)
        if self._switch_btn.isVisible():
            left = max(left, self._switch_btn.x() + self._switch_btn.width() + 8)
        right = int(r.right())
        for btn in (self._pid_btn, self._speed_btn, self._view_btn):
            if btn.isVisible():
                right = min(right, btn.x() - 8)
        width = self._crack_bar.width()
        x = left + max(0, (right - left - width) // 2)
        self._crack_bar.move(
            x, max(0, int(r.top()) - self._crack_bar.height() - 5))
        self._crack_bar.setVisible(right - left >= width)

    def _place_switch_button(self) -> None:
        # Fallback position, used before the title has ever painted (or
        # once it draws with no text at all): right after the coach
        # toggle's own slot, which is reserved only when that toggle is
        # actually shown (Expert level has no coach toggle at all —
        # reserving its space anyway just pushes this button needlessly
        # far right). Once there is a title, _draw_title repositions the
        # button right after the text itself, since only the paint pass
        # knows how wide that text is.
        r = self._plot_rect
        if r.width() <= 1:
            return
        left = r.left()
        if not self.annotations.view_toggle.isHidden():
            left += _TOGGLE_CLEARANCE
        self._switch_btn.move(int(left),
                              max(0, int(r.top()) - self._switch_btn.height() - 5))

    def _on_switch_clicked(self) -> None:
        # A disabled Qt button cannot emit clicked, but keep the same lock here
        # as a safety net for shortcuts, tests and future programmatic callers.
        if self._switch_locked() or not self._switch_has_profile():
            self._sync_switch_button()
            return
        try:
            self._aw.switch()
        except AttributeError:
            report_once('RoastCurveWidget: no switch() on aw')
            return
        # switch() does not go through loadFile() in the common case (one
        # side empty), so it never fires the "profile loaded" signal chain
        # that would otherwise re-evaluate the review panel on its own — do
        # it here instead. hide first: the swap may have moved the operator
        # out of a state that qualified for review just as easily as into one.
        scope = getattr(self._aw, 'tilauscope_main', None)
        if scope is not None:
            try:
                scope.hide_roast_review()
                scope.show_roast_review()
            except Exception:  # pylint: disable=broad-except
                report_once('RoastCurveWidget: review panel refresh failed')
        _background_rise_cache.clear()
        self._reconcile_view()
        self.update()

    def _switch_locked(self) -> bool:
        qmc = getattr(self._aw, 'qmc', None)
        return bool(qmc is not None and (
            getattr(qmc, 'flagon', False)
            or getattr(qmc, 'flagstart', False)))

    def _switch_has_profile(self) -> bool:
        """Whether Artisan has a foreground or background profile to swap."""
        qmc = getattr(self._aw, 'qmc', None)
        if qmc is None:
            return False
        foreground = bool(getattr(self._aw, 'curFile', None))
        background = (
            getattr(qmc, 'backgroundprofile', None) is not None
            or bool(getattr(qmc, 'backgroundpath', None))
        )
        if not background:
            try:
                # Plotter/analyzer backgrounds have arrays but no profile path.
                background = (len(qmc.temp1B) > 2 or len(qmc.temp2B) > 2)
            except (AttributeError, TypeError):
                pass
        return foreground or background

    def _sync_switch_button(self) -> None:
        locked = self._switch_locked()
        has_profile = self._switch_has_profile()
        enabled = has_profile and not locked
        if self._switch_btn.isEnabled() != enabled:
            self._switch_btn.setEnabled(enabled)
        if locked:
            tooltip = QApplication.translate(
                'tilauscope', 'Profile swap is locked while monitoring or roasting')
        elif not has_profile:
            tooltip = QApplication.translate(
                'tilauscope', 'Profile swap — load a roast profile first')
        else:
            tooltip = QApplication.translate(
                'tilauscope', 'Swap the foreground roast and the background curve')
        if self._switch_btn.toolTip() != tooltip:
            self._switch_btn.setToolTip(tooltip)

    def _place_view_button(self) -> None:
        # Above the plot, never inside it. Floating over the tracing area put it
        # on top of the curves and the milestone chips in the close-up view —
        # a control has no business hiding the thing it controls.
        r = self._plot_rect
        if r.width() > 1:
            self._view_btn.move(int(r.right()) - self._view_btn.width(),
                                max(0, int(r.top()) - self._view_btn.height() - 5))

    def _window_for(self, timex: list[Any], charge: int, drop: int,
                    *, closeup: bool | None = None) -> tuple[float, float]:
        """Time window in charge-relative seconds.

        While a roast is running the scale never moves: the minute before charge
        plus the fixed 0-14:00 roast window. That lead-in is what stops the first
        seconds being crushed against the axis, and it carries the approach to
        the charge and the plunge that follows it. Both other views are reading
        aids and need a finished roast, since each is bounded by the drop.
        """
        if not 0 < drop < len(timex) or not timex:
            # The scale is fixed while the roast runs, and only ever extends —
            # for a roast that outlasts it. A curve that stops growing at 14:00
            # while the clock runs on is worse than a scale that moves, and the
            # extension lands on whole gridline steps so the grid stays read-
            # able at a glance.
            if timex and 0 <= charge < len(timex):
                elapsed = float(timex[-1]) - float(timex[charge])
                if elapsed > _TIME_MAX:
                    return -_LEAD_IN, math.ceil(elapsed / _TIME_STEP) * _TIME_STEP
            return -_LEAD_IN, _TIME_MAX
        t_charge = timex[charge]
        use_closeup = self._closeup if closeup is None else closeup
        if use_closeup:
            return -_LEAD_IN, (timex[drop] - t_charge) + _TAIL_OUT
        # "Full" has to mean the whole session, preheat included — that is what the
        # operator sees in Artisan and what the word promises. Rounded out to whole
        # minutes so gridlines land on them, and so the cooling tail growing after
        # the drop only rebuilds the frame once a minute.
        first = timex[0] - t_charge
        last = timex[-1] - t_charge
        return math.floor(first / 60.0) * 60.0, max(math.ceil(last / 60.0) * 60.0, 60.0)

    def tick(self) -> None:
        """Signal-driven refresh hook. Two O(1) reads and a repaint request —
        see class docstring. No curve data is touched here."""
        self._reconcile_view()
        # Read here, not in the paint: the paint runs on Qt's schedule and must
        # not go asking the controller anything.
        qmc = getattr(self._aw, 'qmc', None)
        self._preheat = (None if (qmc is not None and marked(getattr(qmc, 'timeindex', ()), 0))
                         else preheat_reading(self._aw))
        # The preheat axis is derived from the climb and moves with it, and the
        # card is placed against a line ON that axis. Left to the paint pass it
        # would be settled after the card was placed, so every card would sit
        # against the previous frame's axis — and the very first one against no
        # axis at all.
        if self._preheat is not None and qmc is not None:
            try:
                # The ends, not the series: the axes are settled from the first
                # and last instants and the last reading, and copying two whole
                # sample runs once a second to read three numbers is the one
                # thing this method promises not to do.
                timex, temp2 = qmc.timex, qmc.temp2
                ends = (list(timex[:1]) + list(timex[-1:])
                        if len(timex) > 1 else list(timex[:1]))
                self._set_preheat_axes(ends, list(temp2[-1:]), qmc.mode,
                                       self._preheat)
            except Exception:
                report_once('RoastCurveWidget: preheat axes')
        if [n for n, _r, _k in self._lane_rows] != self._visible_channels():
            # Slider visibility is Artisan's setting and can change while this
            # window is open; the lanes are laid out from it.
            self._layout()
        self.annotations.tick()
        self._crack_bar.refresh()
        self._place_crack_bar()
        self.update()

    def _reconcile_view(self) -> None:
        """Show the view selector when a finished foreground or reference exists.

        The close-up only means something once the roast is closed. The drop is
        not that moment: the beans are still in the cooling tray, the recording
        is still running and the frame is still growing under the curve, so a
        window that claims to end at the drop would keep being wrong. No
        button until then — a control that cannot act is noise on a screen read
        at arm's length. This belongs on the tick and not in the paint — showing
        a child widget from inside its parent's paintEvent re-enters the paint
        pipeline.
        """
        self._sync_switch_button()
        qmc = getattr(self._aw, 'qmc', None)
        if qmc is None:
            return
        try:
            charge = int(qmc.timeindex[0])
            drop = int(qmc.timeindex[6])
            foreground = 0 <= charge < len(qmc.timex)
            readable = (foreground and 0 < drop < len(qmc.timex)
                        and not getattr(qmc, 'flagstart', False))
        except (AttributeError, IndexError, TypeError, ValueError):
            foreground = False
            readable = False
        if not foreground and not getattr(qmc, 'flagstart', False):
            try:
                background_charge = int(qmc.timeindexB[0])
                background_drop = int(qmc.timeindexB[6])
                background = qmc.backgroundprofile is not None
                readable = (background
                            and 0 <= background_charge < len(qmc.timeB)
                            and 0 < background_drop < len(qmc.timeB))
            except (AttributeError, IndexError, TypeError, ValueError):
                pass
        if self._view_btn.isVisible() != readable:
            self._view_btn.setVisible(readable)

        # The speed selector only exists in a simulated roast, and only while
        # one is running: a replay speed with nothing replaying is a control
        # that cannot act.
        replaying = bool(getattr(self._aw, 'simulator', None)
                         and getattr(qmc, 'flagstart', False))
        if self._speed_btn.isVisible() != replaying:
            self._speed_btn.setVisible(replaying)
        if replaying:
            self._sync_speed_button()
        self._place_speed_button()
        self._sync_pid_button()

    # ── geometry (resize-time only) ─────────────────────────────────────
    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._layout()
        # The cards are placed against the tracing area, which just moved. Left
        # to the next tick they would sit a second's worth of geometry behind.
        self.annotations.tick()

    def _layout(self) -> None:
        w, h = self.width(), self.height()
        width = float(max(1, w - _MARGIN_LEFT - _MARGIN_RIGHT))
        available = float(max(2, h - _MARGIN_TOP - _MARGIN_BOTTOM))

        channels = self._visible_channels()
        # Each row asks for a number of "units"; the block is then scaled to fit
        # the share the lanes are allowed, so switching modes never steals the
        # roast plot's height.
        traced = self._traced_channel(channels)
        if self._lane_mode == _LANE_MODE_BURNER and traced is not None:
            plan = [(n, 'area' if n == traced else 'marks') for n in channels]
        else:
            plan = [(n, 'area') for n in channels]

        if self._lane_mode == _LANE_MODE_LANES:
            heights = [_LANE_ROW_HEIGHT for _row in plan]
        else:
            heights = [_LANE_AREA_HEIGHT if kind == 'area'
                       else _LANE_MARK_HEIGHT for _n, kind in plan]
        count = len(plan)
        if count:
            ideal = sum(heights) + (count - 1) * _LANE_ROW_GAP
            allowed = available * _LANE_MAX_SHARE
            scale = min(1.0, allowed / ideal) if ideal > 0 else 1.0
            heights = [max(9.0, hh * scale) for hh in heights]
            block = sum(heights) + (count - 1) * _LANE_ROW_GAP
        else:
            block = 0.0

        main_h = max(1.0, available - block - (_LANE_GAP if block else 0.0))
        self._plot_rect = QRectF(float(_MARGIN_LEFT), float(_MARGIN_TOP), width, main_h)

        self._lane_rows = []
        y = float(_MARGIN_TOP) + main_h + _LANE_GAP
        for (n, kind), row_h in zip(plan, heights, strict=True):
            self._lane_rows.append((n, QRectF(float(_MARGIN_LEFT), y, width, row_h), kind))
            y += row_h + _LANE_ROW_GAP
        self._frame_key = None   # paintEvent rebuilds with the current window
        self._place_view_button()
        self._place_switch_button()
        self._place_crack_bar()

    def _ensure_frame(self, w: int, h: int) -> None:
        """Rebuild the cached frame only when something painted into it changed.

        Everything the frame bakes in has to be in the key, channel names and
        colours included: they come from Artisan's own event configuration and
        change when a profile is loaded. The screen ratio belongs here too, so
        moving the window to a display of a different density rebuilds it.
        """
        key = (w, h, self._t_min, self._t_max, self._lane_mode, self._mode,
               self._temp_lo, self._temp_hi, self._temp_step, self._time_step,
               self._ror_max, self._ror_step,
               self._climb_frame, self._rate_axis,
               tuple(n for n, _r, _k in self._lane_rows),
               self.devicePixelRatioF(), self._channel_labels())
        if key != self._frame_key:
            self._frame = self._build_frame(w, h)
            self._frame_key = key

    def _set_preheat_axes(self, timex: list[Any], temp2: list[Any], mode: str,
                          preheat: Any | None) -> None:
        """An axis that contains the climb, on both sides.

        Time runs from the moment the probes started, not from a charge that has
        not happened. The frame is the same fourteen minutes the roast uses:
        no preheat is over in three, and an axis that grew with the climb kept
        rescaling under the curve — the operator lost their calibration every
        thirty seconds, and the first frames claimed a climb would be done in a
        couple of minutes. It only opens further for a preheat that outruns it.

        Temperature reaches above the target, because the number the operator is
        waiting for has to be on the chart before it is reached.
        """
        elapsed = (float(timex[-1]) - float(timex[0])) if len(timex) > 1 else 0.0
        self._time_step = _TIME_STEP if elapsed <= _PREHEAT_SPAN else _TIME_STEP * 2
        grain = 60.0
        self._t_min = 0.0
        grown = math.ceil((elapsed * 1.05) / grain) * grain
        if grown <= _PREHEAT_SPAN:
            # Inside the frame, the frame does not move. An arrival further out
            # than fourteen minutes simply stays off the chart, and the card
            # carries the countdown until it comes into view — stretching the
            # axis to meet it is what made the frame rescale every half minute.
            span = _PREHEAT_SPAN
        else:
            span = grown
            eta = getattr(preheat, 'eta', None)
            if eta is not None and elapsed + eta <= span * _ARRIVAL_MAX_SHARE:
                # Clear of the arrival, never onto it: a marker drawn on the
                # right border coincides with the frame and cannot be seen.
                span = max(span,
                           math.ceil((elapsed + eta + _ARRIVAL_PAD) / grain) * grain)
        self._t_max = span

        target_c = float(getattr(preheat, 'target_c', 0.0) or 0.0)
        seen = [c for c in (_sample_temp_c(v, mode) for v in temp2[-1:]) if c is not None]
        top = max([target_c, *seen]) if (target_c or seen) else _temp_axis_c(mode)[1]
        if not target_c:
            # No controller, so no number to wait for: the ceiling would then be
            # the reading of the moment, and a climb re-scales its own frame
            # every forty degrees. The roast's ceiling holds it still, and the
            # climb still opens it further if it goes above.
            top = max(top, _temp_axis_c(mode)[1])
        # The climb sets its own ceiling, but the ladder is still the operator's:
        # the rounding is done on round figures in the display unit, then the
        # three numbers are handed back to the °C frame the engine draws in.
        scale = 1.8 if mode == 'F' else 1.0
        lo_n, step_n = (40.0, 60.0) if mode == 'F' else (0.0, 40.0)
        top_n = convertTemp(top, 'C', mode) + 20.0 * scale
        hi_n = max(lo_n + step_n * 2,
                   lo_n + math.ceil((top_n - lo_n) / step_n) * step_n)
        self._temp_step = step_n / scale
        self._temp_lo = convertTemp(lo_n, mode, 'C')
        self._temp_hi = convertTemp(hi_n, mode, 'C')

    def _draw_preheat(self, painter: QPainter, timex: list[Any], temp2: list[Any],
                      mode: str, preheat: Any | None) -> None:
        """The drum climbing towards its target, with the target drawn on it.

        Nothing of the roast belongs here: no milestones, no phase bands, no
        rate axis. A preheat has one question and this answers it — how far up
        the drum is, and how far there is left.

        `preheat` is None when no controller is driving the climb. The line is
        the same line; what falls away is what only a controller knows — the
        target, the arrival and the ready badge.
        """
        r = self._plot_rect
        base = float(timex[0]) if timex else 0.0
        target_c = float(getattr(preheat, 'target_c', 0.0) or 0.0)

        ready = bool(getattr(preheat, 'ready', False))
        # One colour for the whole preheat: the card and the line it comments on
        # are the same message, and painting them differently made the chart
        # argue with the card sitting on top of it.
        state = QColor(getattr(preheat, 'colour', None) or THEME['ACCENT'])
        if target_c:
            # Dashed while the drum is still climbing, solid once it is there:
            # the line stops being a thing to reach and becomes a thing to hold.
            pen = QPen(state)
            pen.setWidthF(2.0 if ready else 1.2)
            if not ready:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            y = self._y_temp(target_c)
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            f = QFont()
            f.setPointSize(_AXIS_FONT_PT)
            f.setBold(ready)
            painter.setFont(f)
            painter.setPen(QPen(state))
            painter.drawText(QRectF(r.left() + 6.0, y - 18.0, 220.0, 16.0),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                             QApplication.translate('tilauscope', 'target {0}°').format(
                                 fmt_temp(getattr(preheat, 'target', target_c))))

        points = QPolygonF()
        for t, raw in zip(timex, temp2, strict=False):
            temp_c = _sample_temp_c(raw, mode)
            if temp_c is None:
                continue
            points.append(QPointF(self._x(float(t) - base), self._y_temp(temp_c)))
        if points.count() < 2:
            return
        grain = QColor(self._grain_colour())
        pen = QPen(grain)
        pen.setWidthF(_GRAIN_PEN_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(points)

        last = points.at(points.count() - 1)
        painter.setBrush(grain)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(last, 3.5, 3.5)

        if ready:
            # The one instruction of the whole preheat, put where the operator
            # is already looking. It rides the head of the curve rather than a
            # corner of the frame: the drum drifts on past target if this is
            # found late.
            self._draw_ready_badge(painter, last)

        # Where the law expects the drum to be once its lag has played out. It
        # sits above the reading whenever the drum is still climbing, and that
        # gap is the whole reason a burner tapers short of target.
        # The projected reading used to be drawn here as a grey ring above the
        # head of the climb. It said the same thing as the gap already written
        # on the card, and once the drum settled it converged onto the head and
        # read as an artefact around it. Removed rather than conditioned: a mark
        # that only sometimes means something is a mark nobody trusts.
        self._draw_arrival(painter, float(timex[-1]) - base if timex else 0.0,
                           target_c, preheat, state)

    def _draw_arrival(self, painter: QPainter, elapsed: float, target_c: float,
                      preheat: Any | None, colour: QColor) -> None:
        """Where the climb is due to meet the target, drawn on the chart.

        The countdown is already written on the card. This puts the same figure
        where the operator is looking — on the target line, at the moment the
        curve is expected to touch it — so the gap left to close is a distance
        on screen rather than a number to picture.
        """
        eta = getattr(preheat, 'eta', None)
        if eta is None or not target_c or getattr(preheat, 'ready', False):
            return
        arrival = elapsed + float(eta)
        if not self._t_min <= arrival <= self._t_max:
            return
        x, y = _crisp(self._x(arrival)), self._y_temp(target_c)
        # A short tick hanging off the target line, not a second dashed rule
        # crossing the whole plot: two dashed lines meeting at right angles read
        # as a grid, and the one that mattered was already the horizontal one.
        pen = QPen(colour)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, y), QPointF(x, y + _ARRIVAL_TICK))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_title(self, painter: QPainter, qmc: Any) -> None:
        """What is being roasted, above the plot.

        The batch prefix and number are composed here, from the raw fields
        Artisan always keeps current — not read from qmc.title_text, Artisan's
        own composed cache, which is only refreshed inside setProfileTitle()
        and can still hold a previous roast's composed title after a plain
        File > Open.
        """
        # qmc.title can outlive a reset(): clearMeasurements() always empties
        # qmc.timex, but the title itself is only cleared when the operator's
        # "Delete Properties on Reset" preference (roastpropertiesflag) is on
        # — Switch Profiles resets with that preference as found, so the old
        # title routinely survives with no curve behind it any more. Whether
        # there is a live title to show is decided by qmc.timex, never by the
        # title text alone; title_text (Artisan's own composed cache with
        # batch prefix/number) only supplies the nicer display text once a
        # live curve is confirmed present.
        has_foreground_curve = bool(getattr(qmc, 'timex', None))
        title_raw = str(getattr(qmc, 'title', '') or '').strip() if has_foreground_curve else ''
        title_b = str(getattr(qmc, 'titleB', '') or '').strip()
        # The placeholder Artisan sets when there is nothing to name is the
        # application's own name, which on this screen says nothing at all.
        if title_raw == QApplication.translate('Scope Title', 'TilauScope'):
            title_raw = ''
        # qmc.title_text (Artisan's own composed cache) is only refreshed
        # inside setProfileTitle() — a plain File > Open sets qmc.title
        # straight from the loaded profile without going through it, so the
        # cache can still hold a *previous* roast's composed title. Compose
        # the batch prefix ourselves instead, from the raw fields setProfile()
        # always keeps current, so this never lags behind the loaded file.
        if title_raw:
            bnr = getattr(qmc, 'roastbatchnr', 0) or 0
            bprefix = str(getattr(qmc, 'roastbatchprefix', '') or '')
            if bnr:
                text = f'{bprefix}{bnr} {title_raw}'
            elif bprefix:
                text = f'{bprefix} {title_raw}'
            else:
                text = title_raw
        else:
            text = ''
        # Parentheses always mean "background reference", whether it is the
        # only thing loaded or sits alongside a live roast — never let a
        # background-only view read like a live title with nothing around it.
        if not text:
            text = f"({title_b})" if title_b else ''
        elif title_b and title_b != text:
            text = f"{text} ({title_b})"
        if not text:
            return
        r = self._plot_rect
        # After the coach toggle when it is actually shown — mirrors
        # _place_switch_button's fallback. The swap button itself sits to
        # the *right* of the title text, not before it, so it is moved here
        # once the text's actual width is known.
        left = r.left()
        if not self.annotations.view_toggle.isHidden():
            left += _TOGGLE_CLEARANCE
        f = QFont()
        f.setPointSize(_TITLE_FONT_PT)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor(THEME['TEXT'])))
        # The crack bar shares this strip when the probe is counting, so the
        # title stops at it rather than running underneath it.
        limit = float(self._view_btn.x())
        if self._crack_bar.isVisible():
            limit = min(limit, float(self._crack_bar.x()))
        avail_width = max(40.0, limit - left - 10.0)
        painter.drawText(
            QRectF(left, 2.0, avail_width, r.top() - 4.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        text_width = min(QFontMetricsF(f).horizontalAdvance(text), avail_width)
        self._switch_btn.move(int(left + text_width + 6),
                              max(0, int(r.top()) - self._switch_btn.height() - 5))

    def _draw_forecast(self, painter: QPainter) -> None:
        """Where the bean is due to reach the target of the phase it is in.

        Dashed and dimmed on purpose: it is the only thing on the chart that has
        not happened yet, and it must not be mistaken for a milestone that has.
        The card next to it names the milestone and counts it down; this says
        where on the curve that countdown lands.
        """
        t = self.annotations.forecast_t
        temp_c = self.annotations.forecast_temp_c
        if t is None or temp_c is None:
            return
        if not self._t_min <= t <= self._t_max:
            return
        if not self._temp_lo <= temp_c <= self._temp_hi:
            return
        r = self._plot_rect
        # Snapped to the middle of a pixel column: a one-pixel vertical line on
        # an integer coordinate is antialiased across two columns at half
        # coverage each, and a dashed one then has no solid pixel anywhere.
        x, y = _crisp(self._x(t)), self._y_temp(temp_c)
        colour = QColor(THEME['YELLOW'])
        pen = QPen(colour)
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_ready_badge(self, painter: QPainter, head: QPointF) -> None:
        text = QApplication.translate('tilauscope', 'CHARGE NOW')
        f = QFont()
        f.setPointSize(_LEGEND_FONT_PT + 2)
        f.setBold(True)
        painter.setFont(f)
        w = painter.fontMetrics().horizontalAdvance(text) + 20.0
        h = float(painter.fontMetrics().height()) + 10.0
        # Kept inside the plot: at the right edge the head of the curve is the
        # frame, and a badge hanging off it would be clipped.
        r = self._plot_rect
        x = min(head.x() + 12.0, r.right() - w - 4.0)
        y = max(r.top() + 4.0, head.y() - h - 10.0)
        box = QRectF(x, y, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME['SUCCESS']))
        painter.drawRoundedRect(box, 4.0, 4.0)
        painter.setPen(QPen(QColor(THEME['CRUST'])))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

    # ── the four curve colours, read from the palette the readouts use ──
    def _palette(self, key: str, fallback: str) -> str:
        try:
            value = self._aw.qmc.palette[key]
        except (AttributeError, KeyError, TypeError):
            return fallback
        colour = QColor(value)
        return colour.name() if colour.isValid() else fallback

    def _grain_colour(self) -> str:
        return self._palette('bt', _COLOR_GRAIN)

    def _air_colour(self) -> str:
        return self._palette('et', _COLOR_AIR)

    def _rise_colour(self) -> str:
        return dimmed(self._grain_colour(), _COLOR_GRAIN)

    def _machine_rise_colour(self) -> str:
        return dimmed(self._air_colour(), _COLOR_AIR)

    def _channel_labels(self) -> tuple[tuple[str, str], ...]:
        """(name, colour) for each lane, as the frame paints them."""
        return tuple((self._channel_name(n), self._channel_colour(n).name())
                     for n, _r, _k in self._lane_rows)

    # ── projection: all an overlay needs to know about this widget ──────
    def plot_rect(self) -> QRectF:
        """The tracing area, in this widget's own coordinates."""
        return QRectF(self._plot_rect)

    def charge_offset(self) -> float | None:
        """Seconds from the start of monitoring to the charge, or None while
        the charge is unmarked. Callers holding absolute `timex` values need it
        to reach the charge-relative time this widget draws in."""
        qmc = getattr(self._aw, 'qmc', None)
        timex = getattr(qmc, 'timex', None) if qmc is not None else None
        timeindex = getattr(qmc, 'timeindex', ()) if qmc is not None else ()
        if not timex or not marked(timeindex, 0):
            return None
        idx = int(timeindex[0])
        if not 0 <= idx < len(timex):
            return None
        return float(timex[idx])

    def preheat_target_point(self) -> QPointF | None:
        """The left end of the preheat target line, in widget coordinates.

        The card that comments on a preheat belongs against the number the
        operator is waiting for, not against the head of the climb: the head
        moves up and to the right all preheat long, dragging the card across
        the very things it comments on — the target and the projected arrival.
        The stretch under the target line on the left is empty for the whole
        climb, by the shape of a climb.
        """
        preheat = self._preheat
        if preheat is None:
            return None
        target_c = float(getattr(preheat, 'target_c', 0.0) or 0.0)
        r = self._plot_rect
        if not target_c or r.width() <= 1 or r.height() <= 1:
            return None
        if not self._temp_lo <= target_c <= self._temp_hi:
            return None
        return QPointF(r.left(), self._y_temp(target_c))

    def forecast_x(self) -> float | None:
        """Where the forecast line stands, in widget coordinates.

        For the card that counts that forecast down: floating beside the bean,
        it walks onto the line as the milestone comes near, and hides the mark
        it exists to explain.
        """
        t = self.annotations.forecast_t
        if t is None or not self._t_min <= t <= self._t_max:
            return None
        r = self._plot_rect
        if r.width() <= 1:
            return None
        return self._x(t)

    def project(self, t: float, temp_c: float) -> QPointF | None:
        """A reading placed in widget coordinates, or None when it falls outside
        the drawn time window.

        Time is rejected rather than clamped: an overlay pinned to the edge of
        the window claims the reading is there, and nothing tells the operator
        otherwise. Temperature is clamped, because a card whose anchor drifts a
        few degrees off the axis is still pointing at the right moment.
        """
        r = self._plot_rect
        if r.width() <= 1 or r.height() <= 1:
            return None
        if not self._t_min <= t <= self._t_max:
            return None
        return QPointF(self._x(t), self._y_temp(temp_c))

    def _x(self, t: float) -> float:
        r = self._plot_rect
        clipped = max(self._t_min, min(t, self._t_max))
        span = max(1.0, self._t_max - self._t_min)
        return r.left() + ((clipped - self._t_min) / span) * r.width()

    def _y_temp(self, temp_c: float) -> float:
        r = self._plot_rect
        clipped = max(self._temp_lo, min(temp_c, self._temp_hi))
        span = max(1.0, self._temp_hi - self._temp_lo)
        return r.bottom() - ((clipped - self._temp_lo) / span) * r.height()

    def _y_ror(self, ror_c: float) -> float:
        r = self._plot_rect
        clipped = max(_ROR_MIN, min(ror_c, self._ror_max))
        return r.bottom() - (clipped / self._ror_max) * r.height()

    def _visible_channels(self) -> list[int]:
        """The lanes, live and afterwards alike.

        Reading a gesture against the curve it caused is the point of these
        strips, and that reading is worth most while the roast is running —
        Artisan's own graph drew the events live and there is no case for
        showing less. Before the first gesture a lane still says something: the
        level the channel is being held at, which is where the roast started.
        """
        return channel_order(getattr(self._aw, 'eventslidervisibilities', None))

    @staticmethod
    def _y_in(rect: QRectF, pct: float) -> float:
        clipped = max(0.0, min(pct, _LANE_MAX))
        return rect.bottom() - (clipped / _LANE_MAX) * rect.height()

    def _traced_channel(self, channels: list[int]) -> int | None:
        """The lever that writes the roast. Artisan's own event-type order puts
        the burner last, and that is the index the rest of TilauScope uses."""
        if not channels:
            return None
        return _BURNER_INDEX if _BURNER_INDEX in channels else channels[-1]

    def _lanes_bottom(self) -> float:
        return self._lane_rows[-1][1].bottom() if self._lane_rows else self._plot_rect.bottom()

    def _full_rect(self) -> QRectF:
        """Roast plot and every settings lane as one box — what a mark in time spans."""
        return QRectF(self._plot_rect.left(), self._plot_rect.top(),
                      self._plot_rect.width(),
                      self._lanes_bottom() - self._plot_rect.top())

    # ── frame cache: background, grid, ticks, units ─────────────────────
    def _build_frame(self, w: int, h: int) -> QPixmap:
        # Built at device resolution, not in points: a pixmap left at ratio 1 is
        # stretched to fill the same box on a Retina screen, so the grid and
        # every axis label come out soft while the live curves stay sharp.
        dpr = max(1.0, self.devicePixelRatioF())
        pm = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(THEME['BG']))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect

        p.fillRect(r, QColor(THEME['SURFACE']))

        font = QFont()
        font.setPointSize(_AXIS_FONT_PT)
        p.setFont(font)

        grid_pen = QPen(QColor(THEME['BORDER']))
        grid_pen.setWidthF(1.0)
        text_pen = QPen(QColor(THEME['OVERLAY0']))

        # time grid + labels — ticks stay anchored on charge (0:00) whatever the
        # window, so the same gridline means the same moment in both views. They
        # run through both plots: reading a step against the curve it caused is
        # the whole reason the lane exists.
        # A minute is the unit a roast is read in, so every minute is named. A
        # line every minute would be a picket fence behind the curve, so only
        # every other one is drawn: the figures give the resolution, the lines
        # give the structure.
        label_step = self._time_step
        line_step = label_step * _TIME_LINE_EVERY
        t = math.ceil(self._t_min / label_step) * label_step
        while t <= self._t_max + 1e-6:
            x = self._x(t)
            if abs(t / line_step - round(t / line_step)) < 1e-6:
                p.setPen(grid_pen)
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                for _n, lane, _kind in self._lane_rows:
                    p.drawLine(QPointF(x, lane.top()), QPointF(x, lane.bottom()))
            p.setPen(text_pen)
            label_rect = QRectF(x - 30.0, self._lanes_bottom() + 4.0, 60.0, 18.0)
            p.drawText(label_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                       fmt_clock(t))
            t += label_step

        # temperature grid + left axis labels. The bounds are °C — the frame the
        # engine draws in — and the figure beside each line is that same height
        # said in the operator's unit: the single conversion of this axis.
        temp = self._temp_lo
        while temp <= self._temp_hi + 1e-6:
            y = self._y_temp(temp)
            p.setPen(grid_pen)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(text_pen)
            label_rect = QRectF(0.0, y - 9.0, float(_MARGIN_LEFT) - 8.0, 18.0)
            p.drawText(label_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       str(round(convertTemp(temp, 'C', self._mode))))
            temp += self._temp_step

        # RoR right axis labels (shares the horizontal grid drawn above). None
        # before the charge: no rate is drawn there, and a scale with nothing on
        # it invites reading the drum temperature against the wrong numbers.
        _rise_scale = 1.8 if self._mode == 'F' else 1.0
        ror = _ROR_MIN if self._rate_axis else self._ror_max + 1.0
        while ror <= self._ror_max + 1e-6:
            y = self._y_ror(ror)
            p.setPen(text_pen)
            label_rect = QRectF(r.right() + 8.0, y - 9.0, float(_MARGIN_RIGHT) - 10.0, 18.0)
            p.drawText(label_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       str(round(ror * _rise_scale)))
            ror += self._ror_step

        # One ground per channel, and its name written beside it: a lane that
        # carries its own label needs no legend entry.
        lane_font = QFont()
        lane_font.setPointSize(_LEGEND_FONT_PT)
        lane_font.setBold(True)
        for n, lane, _kind in self._lane_rows:
            p.fillRect(lane, QColor(THEME['SURFACE']))
            p.setFont(lane_font)
            colour = self._channel_colour(n)
            p.setPen(QPen(colour))
            p.drawText(QRectF(0.0, lane.top(), float(_MARGIN_LEFT) - 8.0, lane.height()),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       self._channel_name(n).upper())
        p.setFont(font)

        # plot borders
        border_pen = QPen(QColor(THEME['OVERLAY0']))
        border_pen.setWidthF(1.0)
        p.setPen(border_pen)
        p.drawRect(r)
        for _n, lane, _kind in self._lane_rows:
            p.drawRect(lane)

        # unit captions
        p.setPen(text_pen)
        p.drawText(QRectF(0.0, 2.0, float(_MARGIN_LEFT) - 4.0, 16.0),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   QApplication.translate('tilauscope', '°F') if self._mode == 'F'
                   else QApplication.translate('tilauscope', '°C'))
        if self._rate_axis:
            p.drawText(QRectF(r.right() + 8.0, 2.0, float(_MARGIN_RIGHT) - 10.0, 16.0),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QApplication.translate('tilauscope', '°F/min') if self._mode == 'F'
                       else QApplication.translate('tilauscope', '°C/min'))

        p.end()
        return pm

    # ── live polylines (paint-time only) ────────────────────────────────
    def _build_temp_segments(self, timex: list[Any], raw: list[Any], mode: str) -> list[QPolygonF]:
        """Grain temperature polyline(s), broken at any not-a-point sample."""
        segments: list[QPolygonF] = []
        current = QPolygonF()
        # strict=False, deliberately: the sampling thread appends temperature
        # and time one statement apart, so a frame read between the two sees one
        # array a single sample longer. Both are front-aligned, so dropping the
        # newest point is right — the pairing is never wrong.
        for t, v in zip(timex, raw, strict=False):
            if float(t) < self._t_min:
                continue       # before the window opens
            if float(t) > self._t_max:
                break          # past the window: stop, never pile points on the edge
            temp_c = _sample_temp_c(v, mode)
            # Off the fixed axis, the line stops. Pinning it to the edge draws a
            # flat run at 40 °C that the probe never reported, and there is no
            # way for the operator to tell that apart from a real reading.
            if temp_c is None or not self._temp_lo <= temp_c <= self._temp_hi:
                if len(current) > 1:
                    segments.append(current)
                current = QPolygonF()
                continue
            current.append(QPointF(self._x(float(t)), self._y_temp(temp_c)))
        if len(current) > 1:
            segments.append(current)
        return segments

    def _build_ror_segments(self, timex: list[Any], raw: list[Any], mode: str) -> list[QPolygonF]:
        """RoR polyline(s), from the charge on, broken wherever the rate leaves
        the fixed 0-24 axis.

        That includes the whole stretch before the turning point, where the rate
        is negative by definition, and any later crash below zero. Both are real
        readings the axis cannot show — so the line stops, rather than lying
        flat on the zero baseline where a crash would look like a steady 0.
        """
        segments: list[QPolygonF] = []
        current = QPolygonF()
        for t, v in zip(timex, raw, strict=False):   # see _build_temp_segments
            if float(t) < 0.0:
                # The lead-in minute is there to show the drum the beans met,
                # and a temperature reads as that. A rate does not: before the
                # charge it is the warm-up climbing, drawn under a legend that
                # says the bean is rising.
                continue
            if float(t) < self._t_min:
                continue       # before the window opens
            if float(t) > self._t_max:
                break          # past the window: stop, never pile points on the edge
            ror_c = _sample_ror_c(v, mode)
            if ror_c is None or not _ROR_MIN <= ror_c <= self._ror_max:
                if len(current) > 1:
                    segments.append(current)
                current = QPolygonF()
                continue
            current.append(QPointF(self._x(float(t)), self._y_ror(ror_c)))
        if len(current) > 1:
            segments.append(current)
        return segments

    def _draw_reference(self, painter: QPainter, timex: list[Any], temp1: list[Any],
                        temp2: list[Any], delta2: list[Any], delta1: list[Any],
                        mode: str) -> None:
        """Paint the loaded roast with the exact live trace vocabulary, dimmed."""
        if self.show_machine_response and len(delta1) >= len(timex) - 2 and delta1:
            pen = QPen(_reference_colour(self._machine_rise_colour()))
            pen.setWidthF(_MACHINE_ROR_PEN_WIDTH)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            for poly in self._build_ror_segments(timex, delta1, mode):
                painter.drawPolyline(poly)

        if len(delta2) >= len(timex) - 2 and delta2:
            pen = QPen(_reference_colour(self._rise_colour()))
            pen.setWidthF(_ROR_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_ror_segments(timex, delta2, mode):
                painter.drawPolyline(poly)

        if temp1:
            pen = QPen(_reference_colour(self._air_colour()))
            pen.setWidthF(_AIR_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_temp_segments(timex, temp1, mode):
                painter.drawPolyline(poly)

        if temp2:
            pen = QPen(_reference_colour(self._grain_colour()))
            pen.setWidthF(_GRAIN_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_temp_segments(timex, temp2, mode):
                painter.drawPolyline(poly)

    # ── phases and milestones (paint-time, on top of the cached frame) ──
    def _phase_spans(self, timex: list[Any],
                     timeindex: list[Any]) -> list[tuple[float, float, tuple[str, int]]]:
        """Charge-relative (start, end, colour) for each phase begun so far.

        A phase that has not ended yet runs to the latest sample, so the ground
        grows with the roast instead of appearing all at once at its close.
        """
        if not timex or not timeindex:
            return []
        # The last sample is not the end of the roast — the arrays run on into
        # the cooling tray. With a milestone left unmarked the preceding ground
        # would otherwise be painted straight through the drop.
        now = float(timex[-1])
        if marked(timeindex, 6) and 0 <= int(timeindex[6]) < len(timex):
            now = float(timex[int(timeindex[6])])
        spans: list[tuple[float, float, str]] = []

        def _in_range(i: int) -> bool:
            return marked(timeindex, i) and int(timeindex[i]) < len(timex)

        def _t(i: int) -> float:
            return float(timex[int(timeindex[i])])

        # A milestone index can outrun timex for one frame while the sampling
        # thread is mid-append; treat that as not yet marked rather than raising
        # out of paintEvent.
        dry = _in_range(1)
        fcs = _in_range(2)
        dropped = _in_range(6)

        spans.append((0.0, _t(1) if dry else now, _PHASE_DRYING))
        if dry:
            spans.append((_t(1), _t(2) if fcs else now, _PHASE_MAILLARD))
        if fcs:
            spans.append((_t(2), _t(6) if dropped else now, _PHASE_DEVELOPMENT))
        return spans

    def _draw_phase_bands(self, painter: QPainter, timex: list[Any],
                          timeindex: list[Any]) -> None:
        r = self._plot_rect
        for start, end, (token, alpha) in self._phase_spans(timex, timeindex):
            lo = max(start, self._t_min)
            hi = min(end, self._t_max)
            if hi <= lo:
                continue
            color = QColor(THEME[token])
            color.setAlpha(alpha)
            painter.fillRect(QRectF(self._x(lo), r.top(), self._x(hi) - self._x(lo), r.height()),
                             color)

    def _crack_times(self, timex: list[Any]) -> list[float]:
        """When each pop was heard, in charge-relative seconds.

        Read off the recorded counter rather than accumulated live, so a roast
        reopened from a file draws exactly what the roast that ran drew. The
        probe writes -1 on any tick it does not answer — most of them — and a
        saved profile carries the series interpolated to floats, so only the
        integer part is the count: 0.0, 0.33, 0.67, 1.0 is one pop, not three.
        """
        qmc = getattr(self._aw, 'qmc', None)
        if qmc is None:
            return []
        det = getattr(qmc, 'fc_detector', None)
        channel = det.crack_channel() if det is not None else None
        if channel is None:
            # Discovery runs on monitor-on and at CHARGE; a roast merely opened
            # from a file goes through neither, so resolve it from the names.
            try:
                channel = resolve_crack_channel(qmc.extraname1, qmc.extraname2,
                                                qmc.extratemp1, qmc.extratemp2)
            except (AttributeError, TypeError):
                channel = None
        if channel is None:
            return []
        idx, ch = channel
        try:
            series = qmc.extratemp1[idx] if ch == 1 else qmc.extratemp2[idx]
        except (AttributeError, IndexError, TypeError):
            return []
        if not series:
            return []
        key = (idx, ch, len(series), len(timex))
        if key == self._crack_key:
            return self._crack_cache
        times: list[float] = []
        previous: int | None = None
        for i, value in enumerate(series):
            if value is None or value < 0 or i >= len(timex):
                continue
            count = int(value)
            if previous is not None and count > previous:
                times.extend([float(timex[i])] * min(count - previous, 16))
            previous = count
        self._crack_key = key
        self._crack_cache = times
        return times

    def _draw_crack_band(self, painter: QPainter, timex: list[Any]) -> None:
        """One tick per pop heard, along the foot of the plot.

        No smoothing and no gradient: overlapping ticks build the density on
        their own, which is the honest picture — a crack is a count of events,
        not a continuous quantity. Drawn under everything else, because it is a
        ground the roast is read against, not a mark on the roast.
        """
        times = self._crack_times(timex)
        if not times:
            return
        r = self._plot_rect
        top = r.bottom() - _CRACK_BAND_HEIGHT - 2.0
        colour = QColor(THEME['WARNING'])
        colour.setAlpha(_CRACK_TICK_ALPHA)
        pen = QPen(colour)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        for t in times:
            if not self._t_min <= t <= self._t_max:
                continue
            x = self._x(t)
            painter.drawLine(QPointF(x, top), QPointF(x, top + _CRACK_BAND_HEIGHT))

    def _draw_planned_fc(self, painter: QPainter) -> None:
        """The first crack the plan expected, beside the one that was heard.

        The gap between the two rules is the whole point: it is what says the
        batch ran early or late while there is still a drop to place.
        """
        planned = getattr(self._aw, 'tilau_plan_fc_sec', None)
        if planned is None or not self._t_min <= planned <= self._t_max:
            return
        r = self._plot_rect
        x = self._x(float(planned))
        pen = QPen(QColor(THEME['OVERLAY0']))
        pen.setWidthF(1.2)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        f = QFont()
        f.setPointSize(_AXIS_FONT_PT)
        painter.setFont(f)
        painter.setPen(QPen(QColor(THEME['OVERLAY0'])))
        painter.drawText(QRectF(x + 4.0, r.top() + 2.0, 90.0, 14.0),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         QApplication.translate('tilauscope', 'FC planned'))

    def _draw_milestones(self, painter: QPainter, timex: list[Any], temp2: list[Any],
                         mode: str, timeindex: list[Any], tp_index: int) -> None:
        """Vertical rules plus a chip naming each milestone and its bean reading.

        The turning point is drawn dotted rather than dashed: it is computed
        from the readings, not marked, and the difference should be visible.
        """
        if not timex:
            return
        r = self._plot_rect

        marks: list[tuple[float, str, float | None, bool]] = []
        for i in range(8):
            if not marked(timeindex, i):
                continue
            idx = int(timeindex[i])
            if not 0 <= int(idx) < len(timex):
                continue
            t = float(timex[idx])
            if not self._t_min <= t <= self._t_max:
                continue
            raw = temp2[idx] if idx < len(temp2) else None
            marks.append((t, _milestone_label(i), _sample_temp_c(raw, mode), False))

        if 0 < tp_index < len(timex):
            t = float(timex[tp_index])
            if self._t_min <= t <= self._t_max:
                raw = temp2[tp_index] if tp_index < len(temp2) else None
                marks.append((t, QApplication.translate('tilauscope', 'TP'),
                              _sample_temp_c(raw, mode), True))

        if not marks:
            return
        marks.sort(key=lambda m: m[0])

        rule = QPen(QColor(THEME['OVERLAY1']))
        rule.setWidthF(1.0)
        rule.setStyle(Qt.PenStyle.DashLine)
        # Bright enough to survive a phase ground behind it: at OVERLAY0 the
        # dotted rule simply disappeared into the drying band.
        tp_rule = QPen(QColor(THEME['SUBTEXT']))
        tp_rule.setWidthF(1.4)
        tp_rule.setStyle(Qt.PenStyle.DotLine)
        full = self._full_rect()
        for t, _label, _temp, is_tp in marks:
            painter.setPen(tp_rule if is_tp else rule)
            x = self._x(t)
            painter.drawLine(QPointF(x, full.top()), QPointF(x, full.bottom()))

        # The chip names the milestone, the dot says where it happened. Without
        # it the eye has to guess which point of the curve the label belongs to.
        for t, _label, temp_c, is_tp in marks:
            # Same rule as the curve: a milestone off the axis gets no dot,
            # rather than one parked on the edge away from its own reading.
            if temp_c is None or not self._temp_lo <= temp_c <= self._temp_hi:
                continue
            centre = QPointF(self._x(t), self._y_temp(temp_c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['BG']))
            painter.drawEllipse(centre, _MARK_DOT_RADIUS + 2.0, _MARK_DOT_RADIUS + 2.0)
            painter.setBrush(QColor(THEME['SUBTEXT'] if is_tp else self._grain_colour()))
            painter.drawEllipse(centre, _MARK_DOT_RADIUS, _MARK_DOT_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        font = QFont()
        font.setPointSize(_MARK_FONT_PT)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        # Milestones cluster — first crack and the drop can be a minute apart, and
        # their chips would overlap on the same line. Staggering keeps both
        # readable without moving either away from the instant it marks.
        row_right = [r.left() - 1.0] * _MARK_LABEL_ROWS

        for t, label, temp_c, is_tp in marks:
            # On a dark roast FC END, SECOND CRACK and SC END fall within a
            # minute of each other and eight chips do not fit three rows. So a
            # crowded chip gives up its reading and keeps its name: a milestone
            # nobody can name is worth less than one without its temperature.
            candidates = [label] if temp_c is None else [
                f'{label}  {int(round(temp_c))}°', label]
            placed: tuple[str, float, float, int] | None = None
            for text in candidates:
                width = metrics.horizontalAdvance(text) + 2 * _MARK_CHIP_PAD
                x = self._x(t) + 3.0
                if x + width > r.right():
                    x = self._x(t) - 3.0 - width   # near the right edge, hang the chip left
                for candidate in range(_MARK_LABEL_ROWS):
                    if x > row_right[candidate] + 3.0:
                        placed = (text, width, x, candidate)
                        break
                if placed is not None:
                    break
            if placed is None:
                # Nothing fits anywhere: the least crowded row, name only.
                text = label
                width = metrics.horizontalAdvance(text) + 2 * _MARK_CHIP_PAD
                x = self._x(t) + 3.0
                if x + width > r.right():
                    x = self._x(t) - 3.0 - width
                placed = (text, width, x,
                          min(range(_MARK_LABEL_ROWS), key=lambda c: row_right[c]))
            text, width, x, row = placed
            # A chip hanging left (near the right edge) can end before the
            # chip already on this row does; never let that pull the row's
            # recorded edge backwards.
            row_right[row] = max(row_right[row], x + width)
            top = r.top() + 4.0 + row * _MARK_ROW_HEIGHT
            chip = QRectF(x, top, width, _MARK_ROW_HEIGHT - 4.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['CRUST'] if is_tp else THEME['BORDER']))
            painter.drawRoundedRect(chip, 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(THEME['OVERLAY2'] if is_tp else THEME['SUBTEXT1'])))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)

    # ── settings lanes: what was played on the machine ──────────────────
    def _channel_points(self, timex: list[Any], events: list[Any], types: list[Any],
                        pcts: list[Any], n: int) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for k, idx in enumerate(events):
            try:
                if int(types[k]) != n or not 0 <= int(idx) < len(timex):
                    continue
                points.append((float(timex[int(idx)]), float(pcts[k])))
            except (IndexError, TypeError, ValueError):
                continue
        points.sort(key=lambda q: q[0])
        # Two gestures on one second — a slider clicked twice in the same tick —
        # are one setting as far as the roast is concerned: the last one is what
        # held. Keeping both would draw a riser of no width and hand the label
        # to the value that never applied.
        collapsed: list[tuple[float, float]] = []
        for pt in points:
            if collapsed and collapsed[len(collapsed) - 1][0] == pt[0]:
                collapsed[len(collapsed) - 1] = pt
            else:
                collapsed.append(pt)
        return collapsed

    def _draw_settings(self, painter: QPainter, timex: list[Any], events: list[Any],
                       types: list[Any], pcts: list[Any], colors: list[Any]) -> None:
        if not self._lane_rows:
            return
        # No samples to bound it: a held level runs to the edge of the window,
        # because that is how long it has been held for.
        end = min(self._t_max, float(timex[-1])) if timex else self._t_max
        for n, lane, kind in self._lane_rows:
            try:
                colour = QColor(colors[n])
            except (IndexError, TypeError):
                continue
            points = self._channel_points(timex, events, types, pcts, n)
            if not points:
                # Nothing recorded on this channel yet — which is every channel
                # during a preheat. The lever is still set to something, and an
                # empty strip says the opposite.
                held = self._held_now(n)
                if held is None:
                    continue
                points = [(self._t_min, held)]
            painter.setClipRect(lane)
            if kind == 'area':
                self._draw_channel_area(painter, lane, colour, points, end)
            else:
                self._draw_channel_marks(painter, lane, colour, points)

    def _draw_channel_area(self, painter: QPainter, lane: QRectF, colour: QColor,
                           points: list[tuple[float, float]], end: float) -> None:
        """Filled staircase. A setting holds until the next one, so the outline
        steps — drawing it sloped would invent a ramp nobody made."""
        poly = QPolygonF()
        held: float | None = None
        for t, v in points:
            if t < self._t_min:
                held = v          # set before the window opened: it still holds
                continue
            if t > self._t_max:
                break
            if not len(poly) and held is not None:
                poly.append(QPointF(self._x(self._t_min), self._y_in(lane, held)))
            if held is not None:
                poly.append(QPointF(self._x(t), self._y_in(lane, held)))
            poly.append(QPointF(self._x(t), self._y_in(lane, v)))
            held = v
        if held is not None and len(poly):
            poly.append(QPointF(self._x(end), self._y_in(lane, held)))
        if len(poly) < 2:
            return

        filled = QPolygonF(poly)
        filled.append(QPointF(poly[len(poly) - 1].x(), lane.bottom()))
        filled.append(QPointF(poly[0].x(), lane.bottom()))
        fill = QColor(colour)
        fill.setAlpha(_LANE_FILL_ALPHA)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(filled)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        pen = QPen(colour)
        pen.setWidthF(_LANE_PEN_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.drawPolyline(poly)

        # The level, in figures, at the end of the trace. A channel held at zero
        # draws a line along the floor of its lane and is otherwise
        # indistinguishable from a lane with nothing in it — which is the one
        # reading the operator must never have to guess at.
        self._draw_lane_value(painter, lane, colour, held)

    def _draw_lane_value(self, painter: QPainter, lane: QRectF, colour: QColor,
                         value: float | None) -> None:
        if value is None:
            return
        font = QFont()
        font.setPointSize(_LEGEND_FONT_PT)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text = f'{int(round(value))}'
        width = metrics.horizontalAdvance(text) + 2 * _MARK_CHIP_PAD
        height = min(lane.height() - 2.0, 16.0)
        chip = QRectF(lane.right() - width - 3.0, lane.center().y() - height / 2.0,
                      width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME['CRUST']))
        painter.drawRoundedRect(chip, 3.0, 3.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(colour))
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_channel_marks(self, painter: QPainter, lane: QRectF, colour: QColor,
                            points: list[tuple[float, float]]) -> None:
        """One dot per gesture, with the value written beside it. For a channel
        that is set two or three times in a roast, the moment and the number are
        the whole story — a shape would only add a line to follow."""
        cy = lane.center().y()
        rail = QColor(colour)
        rail.setAlpha(60)
        pen = QPen(rail)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(lane.left(), cy), QPointF(lane.right(), cy))

        font = QFont()
        font.setPointSize(_LEGEND_FONT_PT - 1)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        marks: list[tuple[float, str, float]] = []
        for t, v in points:
            if self._t_min <= t <= self._t_max:
                text = f'{int(round(v))}'
                marks.append((self._x(t), text,
                              metrics.horizontalAdvance(text) + 2.0))

        placements = _lane_label_layout(
            [(x, width) for x, _text, width in marks], lane.left(), lane.right())
        row_height = lane.height() / _LANE_LABEL_ROWS
        for (_x, text, width), (label_x, row) in zip(marks, placements, strict=True):
            chip = QRectF(
                label_x,
                lane.top() + row * row_height + 1.0,
                width,
                max(8.0, row_height - 2.0),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['CRUST']))
            painter.drawRoundedRect(chip, 2.0, 2.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)

        # Markers are painted last. Even under pathological label density the
        # point remains visible and cannot be mistaken for part of a number.
        for x, _text, _width in marks:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['BG']))
            painter.drawEllipse(QPointF(x, cy), 4.5, 4.5)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(x, cy), 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    def _held_now(self, n: int) -> float | None:
        """What the operator has this lever set to, right now.

        Only while something is being measured: on a roast read back from disk
        the sliders carry the current session's values, and drawing those as if
        they were played would invent a gesture that never happened.
        """
        qmc = getattr(self._aw, 'qmc', None)
        if not getattr(qmc, 'flagon', False):
            return None
        try:
            return float(self._aw.eventslidervalues[n])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _channel_colour(self, n: int) -> QColor:
        try:
            return QColor(self._aw.qmc.EvalueColor[n])
        except (AttributeError, IndexError, TypeError):
            return QColor(THEME['OVERLAY1'])    # channel not configured

    def _channel_name(self, n: int) -> str:
        try:
            return str(self._aw.qmc.etypes[n])
        except (AttributeError, IndexError, TypeError):
            return ''       # channel not configured

    # ── legends ──────────────────────────────────────────────────────────
    @staticmethod
    def _draw_legend(painter: QPainter, entries: list[tuple[str, str, str]],
                     left: float, top: float) -> None:
        """A row of swatch + name. Without it the screen shows four traces and
        names none of them."""
        if not entries:
            return
        font = QFont()
        font.setPointSize(_LEGEND_FONT_PT)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        x = left
        for color, label, style in entries:
            if style == 'block':
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
                painter.drawRect(QRectF(x, top + 2.0, 11.0, 8.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                pen = QPen(QColor(color))
                pen.setWidthF(2.0)
                if style == 'dash':
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, top + 6.0), QPointF(x + 11.0, top + 6.0))
            painter.setPen(QPen(QColor(THEME['OVERLAY1'])))
            width = metrics.horizontalAdvance(label)
            painter.drawText(QRectF(x + 15.0, top, width + 4.0, 13.0),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             label)
            x += 15.0 + width + 13.0

    def _draw_curve_legend(self, painter: QPainter, *, phases: bool = True) -> None:
        """The trace legend, with phase grounds only when they were painted."""
        painter.setClipping(False)
        legend: list[tuple[str, str, str]] = [
            (self._grain_colour(), QApplication.translate('tilauscope', 'Bean'), 'line'),
            (self._rise_colour(), QApplication.translate('tilauscope', 'Rise'), 'line'),
        ]
        if self.show_air_temperature:
            legend.insert(1, (self._air_colour(),
                              QApplication.translate('tilauscope', 'Air'), 'line'))
        if self.show_machine_response:
            legend.append((self._machine_rise_colour(),
                           QApplication.translate('tilauscope', 'Machine response'), 'dash'))
        if phases:
            legend.extend((
                (THEME[_PHASE_DRYING[0]],
                 QApplication.translate('tilauscope', 'Drying'), 'block'),
                (THEME[_PHASE_MAILLARD[0]],
                 QApplication.translate('tilauscope', 'Maillard'), 'block'),
                (THEME[_PHASE_DEVELOPMENT[0]],
                 QApplication.translate('tilauscope', 'Development'), 'block'),
            ))
        self._draw_legend(painter, legend, self._plot_rect.left(),
                          self._lanes_bottom() + 30.0)

    # ── hover readout ────────────────────────────────────────────────────
    def _t_for_x(self, x: float) -> float:
        r = self._plot_rect
        span = max(1.0, self._t_max - self._t_min)
        return self._t_min + ((x - r.left()) / max(1.0, r.width())) * span

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        pos = event.position()
        # The whole chart, not just the roast plot: the crosshair already spans
        # the lanes, so hovering one has to answer like anywhere else.
        if not self._full_rect().contains(pos):
            if self._hover_t is not None:
                self._hover_t = None
                self.update()
            return
        t = self._t_for_x(pos.x())
        # Repaint only when the cursor has moved to another second: at mouse-move
        # rates a repaint per pixel would redraw two 1400-point polylines dozens
        # of times a second for no visible gain.
        if self._hover_t is None or int(round(t)) != int(round(self._hover_t)):
            self._hover_t = t
            self.update()

    def leaveEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        if self._hover_t is not None:
            self._hover_t = None
            self.update()
        super().leaveEvent(event)

    def _draw_hover(self, painter: QPainter, timex: list[Any], temp2: list[Any],
                    temp1: list[Any], delta2: list[Any], delta1: list[Any], mode: str,
                    events: list[Any], types: list[Any], pcts: list[Any],
                    colors: list[Any]) -> None:
        """Crosshair on the hovered instant, with the two readings under it."""
        if self._hover_t is None or not timex:
            return
        t_hover = max(self._t_min, min(self._hover_t, self._t_max))
        idx = bisect.bisect_left(timex, t_hover)
        if idx >= len(timex):
            idx = len(timex) - 1
        elif idx > 0 and abs(timex[idx - 1] - t_hover) < abs(timex[idx] - t_hover):
            idx -= 1
        t = float(timex[idx])
        if not self._t_min <= t <= self._t_max:
            return

        r = self._plot_rect
        x = self._x(t)
        full = self._full_rect()
        pen = QPen(QColor(THEME['SUBTEXT1']))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, full.top()), QPointF(x, full.bottom()))

        temp_c = _sample_temp_c(temp2[idx], mode) if idx < len(temp2) else None
        air_c = _sample_temp_c(temp1[idx], mode) if idx < len(temp1) else None
        ror_c = _sample_ror_c(delta2[idx], mode) if idx < len(delta2) else None
        machine_c = (_sample_ror_c(delta1[idx], mode)
                     if self.show_machine_response and idx < len(delta1) else None)

        grain, air = self._grain_colour(), self._air_colour()
        rise, machine_rise = self._rise_colour(), self._machine_rise_colour()
        painter.setPen(Qt.PenStyle.NoPen)
        # A dot is only drawn where the axis can honestly carry it. Off-scale the
        # mapping clamps, which would pin the marker to an edge it never touched —
        # the figure still appears in the readout, where it cannot mislead.
        for reading, colour, to_y, lo, hi in (
                (temp_c, grain, self._y_temp, self._temp_lo, self._temp_hi),
                (air_c, air, self._y_temp, self._temp_lo, self._temp_hi),
                (ror_c, rise, self._y_ror, _ROR_MIN, self._ror_max),
                (machine_c, machine_rise, self._y_ror, _ROR_MIN, self._ror_max)):
            if reading is None or not lo <= reading <= hi:
                continue
            centre = QPointF(x, to_y(reading))
            painter.setBrush(QColor(THEME['BG']))
            painter.drawEllipse(centre, _MARK_DOT_RADIUS + 2.0, _MARK_DOT_RADIUS + 2.0)
            painter.setBrush(QColor(colour))
            painter.drawEllipse(centre, _MARK_DOT_RADIUS - 0.5, _MARK_DOT_RADIUS - 0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Every lane answers too: the setting that was holding at that instant,
        # marked on its own baseline and written beside it.
        lane_font = QFont()
        lane_font.setPointSize(_HOVER_FONT_PT)
        lane_font.setBold(True)
        lane_metrics = QFontMetricsF(lane_font)
        painter.setFont(lane_font)
        for n, lane, _kind in self._lane_rows:
            points = self._channel_points(timex, events, types, pcts, n)
            held: float | None = None
            for pt_t, pt_v in points:
                if pt_t > t:
                    break
                held = pt_v
            if held is None:
                continue
            try:
                colour = QColor(colors[n])
            except (IndexError, TypeError):
                continue
            cy = lane.center().y() if _kind == 'marks' else self._y_in(lane, held)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['BG']))
            painter.drawEllipse(QPointF(x, cy), 4.5, 4.5)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(x, cy), 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            text = f'{int(round(held))}'
            width = lane_metrics.horizontalAdvance(text) + 2 * _MARK_CHIP_PAD
            # On its own dark chip, never straight onto the lane: the fill under
            # the figure is the channel's own colour, so coloured text there has
            # no contrast left to work with.
            height = min(lane.height() - 2.0, 16.0)
            # Flip to the left of the crosshair near the right edge, so the chip
            # never falls outside the lane it belongs to.
            tx = x + 7.0 if x + 7.0 + width < lane.right() else x - 7.0 - width
            chip = QRectF(tx, lane.center().y() - height / 2.0, width, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(THEME['CRUST']))
            painter.drawRoundedRect(chip, 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colour))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), text)

        parts = readout_parts(t, temp_c, air_c, ror_c, machine_c,
                              grain, air, rise, machine_rise)

        font = QFont()
        font.setPointSize(_HOVER_FONT_PT)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        gap = 12.0
        label_gap = 4.0
        cells = [(metrics.horizontalAdvance(label) + label_gap if label else 0.0,
                  metrics.horizontalAdvance(value))
                 for label, value, _c in parts]
        width = sum(lw + vw for lw, vw in cells) + gap * (len(parts) - 1) + 2 * _MARK_CHIP_PAD
        # Along the bottom edge, clear of the milestone chips at the top.
        left = min(max(x + 8.0, r.left() + 2.0), r.right() - width - 2.0)
        chip = QRectF(left, r.bottom() - _MARK_ROW_HEIGHT - 2.0, width, _MARK_ROW_HEIGHT - 4.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME['CRUST']))
        painter.drawRoundedRect(chip, 3.0, 3.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cursor = left + _MARK_CHIP_PAD
        for (label, value, colour), (lw, vw) in zip(parts, cells, strict=True):
            if label:
                painter.setPen(QPen(QColor(THEME['OVERLAY1'])))
                painter.drawText(QRectF(cursor, chip.top(), lw - label_gap, chip.height()),
                                 int(Qt.AlignmentFlag.AlignCenter), label)
                cursor += lw
            painter.setPen(QPen(QColor(colour)))
            painter.drawText(QRectF(cursor, chip.top(), vw, chip.height()),
                             int(Qt.AlignmentFlag.AlignCenter), value)
            cursor += vw + gap

    # ── right-click: the place the spec reserves for curve settings ─────
    def _clear_background(self) -> None:
        """Remove the loaded reference through Artisan's own cleanup path."""
        try:
            self._aw.clearbackgroundRedraw()
        except Exception:
            report_once('RoastCurveWidget: clearing background failed')
            return
        # Do not retain either the computed rate or a selector that belonged to
        # the reference-only state until the next one-second screen tick.
        _background_rise_cache.clear()
        self._reconcile_view()
        self.update()

    def _add_background_menu_action(self, menu: QMenu) -> QAction | None:
        qmc = getattr(self._aw, 'qmc', None)
        # Offered for whatever is actually drawn, profile-backed or not: a
        # reference the operator can see is one they must be able to remove.
        if qmc is None or _background_roast(
                qmc, show_air=False, show_machine=False) is None:
            return None
        menu.addSeparator()
        action = QAction(
            QApplication.translate('tilauscope', 'Remove reference curve'), menu)
        action.triggered.connect(self._clear_background)
        menu.addAction(action)
        return action

    def contextMenuEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss())
        air = QAction(QApplication.translate('tilauscope', 'Air temperature'), menu)
        air.setCheckable(True)
        air.setChecked(self.show_air_temperature)
        # A roast recorded with the air probe off has nothing to trace, and an
        # option that silently does nothing is worse than one that is not there:
        # the operator clicks it, sees no change, and doubts the whole menu.
        if not self._has_air_readings():
            air.setEnabled(False)
            air.setToolTip(QApplication.translate(
                'tilauscope', 'This roast carries no air temperature'))
        # Above the rate it belongs to, because that is the order they are read
        # in: what the air IS, then how fast it is moving.
        air.toggled.connect(self._set_air_temperature)
        menu.addAction(air)

        act = QAction(QApplication.translate('tilauscope', 'Machine response'), menu)
        act.setCheckable(True)
        act.setChecked(self.show_machine_response)
        # It moves before the bean does: the only trace that says a burner change
        # is working during the 15-30 s the bean has not registered it yet. Off by
        # default, and for this session only — where the preference belongs
            # (machine or global) is still open.
            # default, and restored from the user's curve display preferences.
        act.toggled.connect(self._set_machine_response)
        menu.addAction(act)

        menu.addSeparator()
        lanes = QAction(QApplication.translate('tilauscope', 'One lane per channel'), menu)
        lanes.setCheckable(True)
        lanes.setChecked(self._lane_mode == _LANE_MODE_LANES)
        lanes.triggered.connect(lambda: self._set_lane_mode(_LANE_MODE_LANES))
        menu.addAction(lanes)

        burner = QAction(
            QApplication.translate('tilauscope', 'Burner traced, others as gestures'), menu)
        burner.setCheckable(True)
        burner.setChecked(self._lane_mode == _LANE_MODE_BURNER)
        burner.triggered.connect(lambda: self._set_lane_mode(_LANE_MODE_BURNER))
        menu.addAction(burner)

        menu.addSeparator()
        # The rate of rise is derived, never stored, so this is not a display
        # option: it decides what the rate IS, on this roast and on every one
        # reopened afterwards. Three levels rather than the four numbers
        # Artisan exposes — see `smoothing` for what bounds them.
        smoothing = menu.addMenu(QApplication.translate('tilauscope', 'Rate of rise'))
        smoothing.setStyleSheet(menu_qss())
        qmc = getattr(self._aw, 'qmc', None)
        chosen = smooth.current(qmc) if qmc is not None else ''
        for level in smooth.LEVELS:
            act_level = QAction(smooth.label(level), smoothing)
            act_level.setCheckable(True)
            act_level.setChecked(level.key == chosen)
            act_level.triggered.connect(
                lambda _c, key=level.key: self._set_smoothing(key))
            smoothing.addAction(act_level)

        self._add_background_menu_action(menu)

        menu.exec(event.globalPos())

    def _set_smoothing(self, key: str) -> None:
        qmc = getattr(self._aw, 'qmc', None)
        if qmc is None or not smooth.apply_level(qmc, key):
            return
        # The frame holds axes and grid, which this does not touch; only the
        # rate polyline is redrawn, and that lives in the paint pass.
        self.update()

    def _set_lane_mode(self, mode: str) -> None:
        if mode == self._lane_mode:
            return
        self._lane_mode = mode
        QSettings().setValue(_LANE_MODE_KEY, mode)
        self._layout()          # the lanes change height, so the frame changes too
        self._place_view_button()
        self.update()

    def _set_machine_response(self, on: bool) -> None:
        self.show_machine_response = on
        QSettings().setValue(_SHOW_MACHINE_RESPONSE_KEY, on)
        self.update()

    def _has_air_readings(self) -> bool:
        """Whether the air probe answered anything on this roast.

        Silence is only meaningful once there is something to be silent about:
        a roast that has not sampled yet gets the benefit of the doubt.
        """
        qmc = getattr(self._aw, 'qmc', None)
        try:
            series = list(qmc.temp1)
        except (AttributeError, TypeError):
            return True
        if not series:
            return True
        mode = getattr(qmc, 'mode', 'C')
        return any(_sample_temp_c(v, mode) is not None for v in series)

    def _set_air_temperature(self, on: bool) -> None:
        self.show_air_temperature = on
        QSettings().setValue(_SHOW_AIR_KEY, on)
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802, ARG002 (Qt override)
        """Paint, and never let anything out.

        An exception escaping a reimplemented Qt virtual reaches the process
        excepthook, and this application's excepthook ends in sys.exit — so a
        single bad sample here does not blank a chart, it closes the roast
        window mid-roast. The painter is ended in every case: leaving one
        active on the widget poisons every frame after it.
        """
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception:
            report_once('RoastCurveWidget.paintEvent')
        finally:
            if painter.isActive():
                painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        qmc = getattr(self._aw, 'qmc', None)
        timex: list[Any] = []
        temp1: list[Any] = []
        temp2: list[Any] = []
        delta2: list[Any] = []
        delta1: list[Any] = []
        mode = 'C'
        timeindex: list[Any] = []
        events: list[Any] = []
        ev_types: list[Any] = []
        ev_pcts: list[Any] = []
        ev_colors: list[Any] = []
        charge = -1
        drop = -1
        monitoring = False
        no_meter = False
        if qmc is not None:
            try:
                timex = list(qmc.timex)
                temp2 = list(qmc.temp2)
                temp1 = list(qmc.temp1) if self.show_air_temperature else []
                delta2 = rise_series(qmc)
                delta1 = rise_series(qmc, machine=True) if self.show_machine_response else []
                mode = qmc.mode
                timeindex = list(qmc.timeindex)
                charge = timeindex[0]
                drop = timeindex[6]
                events = list(qmc.specialevents)
                ev_types = list(qmc.specialeventstype)
                ev_pcts = [qmc.eventsInternal2ExternalValue(v)
                           for v in qmc.specialeventsvalue]
                ev_colors = list(qmc.EvalueColor)
                monitoring = bool(qmc.flagon)
                # Artisan's "NONE" device: no meter is configured at all, so no
                # reading is coming until one is chosen. A different nothing from
                # a cable out, and a different fix.
                no_meter = (int(getattr(qmc, 'device', 0)) == 18
                            and getattr(self._aw, 'simulator', None) is None)
            except Exception:
                # Live data can be mid-mutation on the sampling thread's cadence;
                # skip this frame rather than risk a half-read list. Keeping the
                # previous frame is the honest choice: clearing timex here would
                # print "no roast recorded" over a roast that is running.
                report_once('RoastCurveWidget: live read failed')
                return

        # Time is measured from CHARGE, not from the start of monitoring: qmc.timex
        # covers the preheat too, which would paint the drum warm-up and the charge
        # plunge inside the roast window. Before the foreground CHARGE is marked
        # (sentinel -1), only a loaded reference can define a roast frame.
        drawable = 0 <= charge < len(timex)
        preheat = None if drawable else self._preheat
        # The climb up to the charge owns a time frame of its own, and it owns
        # it whether or not a controller is driving it. A drum taken up by hand
        # is the same rise, played with the same levers, and it used to be given
        # the empty "waiting for charge" chart for the whole preheat: nothing
        # advanced, and every gesture of that preheat was drawn nowhere, because
        # the only frame on offer was measured from a charge that had not
        # happened. The controller adds a target and a countdown to this frame;
        # it is not what creates it.
        climb_frame = preheat is not None or (
            not drawable and monitoring and len(timex) > 1 and _readings(temp2))
        # Outside that frame, a loaded reference is a perfectly drawable roast
        # even when there is no foreground yet.
        reference = (None if climb_frame else _background_roast(
            qmc, show_air=self.show_air_temperature,
            show_machine=self.show_machine_response))
        reference_only = not drawable and reference is not None
        self._rate_axis = drawable or reference_only
        self._climb_frame = climb_frame
        # The unit the axes are labelled in, and the rise scale that goes with
        # it. Both are in the frame key, so a unit switched mid-session rebuilds
        # the frame instead of leaving °C figures on a °F chart.
        self._mode = mode
        self._ror_max, self._ror_step = _ror_axis_c(mode)
        if drawable:
            # DROP does not close a live roast: cooling is still being recorded.
            # Keep the fixed live scale without throwing away the operator's
            # preferred view, which becomes active as soon as recording stops.
            self._t_min, self._t_max = self._window_for(
                timex, charge, drop,
                closeup=self._closeup and not getattr(qmc, 'flagstart', False))
            self._temp_lo, self._temp_hi, self._temp_step = _temp_axis_c(mode)
            self._time_step = _TIME_STEP
        elif climb_frame:
            self._set_preheat_axes(timex, temp2, mode, preheat)
        elif reference is not None:
            ref_timex = reference[0]
            try:
                ref_index = list(qmc.timeindexB)
                ref_charge = int(ref_index[0])
                ref_drop = int(ref_index[6])
            except (AttributeError, IndexError, TypeError, ValueError):
                ref_charge, ref_drop = -1, -1
            self._t_min, self._t_max = self._window_for(
                ref_timex, ref_charge, ref_drop, closeup=self._closeup)
            self._temp_lo, self._temp_hi, self._temp_step = _temp_axis_c(mode)
            self._time_step = _TIME_STEP
        else:
            self._t_min, self._t_max = -_LEAD_IN, _TIME_MAX
            self._temp_lo, self._temp_hi, self._temp_step = _temp_axis_c(mode)
            self._time_step = _TIME_STEP

        # The frame carries the time labels, so it must be current for this window
        # before it is blitted. _ensure_frame is a no-op unless the window moved.
        self._ensure_frame(self.width(), self.height())
        if self._frame is not None:
            painter.drawPixmap(0, 0, self._frame)
        self._draw_title(painter, qmc)
        if climb_frame:
            self._draw_preheat(painter, timex, temp2, mode, preheat)
            # The lanes were laid out but never reached: a preheat used to leave
            # four empty strips under the climb, which is where the operator
            # looks for what the levers are set to.
            base = float(timex[0]) if timex else 0.0
            self._draw_settings(painter, [float(t) - base for t in timex],
                                events, ev_types, ev_pcts, ev_colors)
            return
        if not drawable:
            if reference is not None:
                painter.setClipRect(self._plot_rect)
                self._draw_reference(painter, *reference)
                # There is no foreground time in which to place gestures. Keep
                # the lane behaviour of the genuinely empty state, but do not
                # cover the valid reference with an empty-state message.
                self._draw_settings(painter, [], [], [], [], ev_colors)
                self._draw_curve_legend(painter, phases=False)
                return
            # An empty plot must say why it is empty, and the reasons are not
            # interchangeable. Monitoring off: nothing is coming, and saying
            # "waiting" would be a lie. Monitoring on with nothing measured: the
            # wait is on the machine, not on the operator — announcing a charge
            # here told someone with an unplugged roaster that the application
            # was ready for their beans. Monitoring on with a reading: the climb
            # takes the frame a sample later, so this is genuinely the charge
            # being waited for. The fix for a silent machine is not repeated
            # here: the phase box beside this one carries it in full, and a
            # warning said three ways is a warning read none.
            if not monitoring:
                headline = QApplication.translate('tilauscope', 'No roast recorded')
                detail = QApplication.translate('tilauscope', 'The curve starts when the charge is marked.')
            elif no_meter:
                headline = QApplication.translate('tilauscope', 'No meter connected')
                detail = QApplication.translate('tilauscope', 'Configure a device in Machine > Device.')
            elif not _readings(temp2, 1):
                headline = QApplication.translate('tilauscope', 'Waiting for the machine')
                detail = QApplication.translate('tilauscope', 'The curve starts with the first temperature reading.')
            else:
                headline = QApplication.translate('tilauscope', 'Waiting for charge')
                detail = ''
            r = self._plot_rect
            f = QFont()
            f.setPointSize(_AXIS_FONT_PT + 2)
            painter.setFont(f)
            painter.setPen(QPen(QColor(THEME['OVERLAY0'])))
            painter.drawText(
                QRectF(r.left(), r.top(), r.width(), r.height() - (22.0 if detail else 0.0)),
                int(Qt.AlignmentFlag.AlignCenter), headline)
            # The levers, even with no roast to place them against. Their own
            # times are deliberately not used here: the axis is charge-relative
            # and there is no charge, so a gesture drawn on it would claim a
            # moment in a roast that has not started.
            self._draw_settings(painter, [], [], [], [], ev_colors)
            if detail:
                f.setPointSize(_AXIS_FONT_PT)
                painter.setFont(f)
                painter.drawText(
                    QRectF(r.left(), r.center().y() + 8.0, r.width(), 22.0),
                    int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop), detail)
            return

        # The turning point is not in timeindex — it is the coldest bean reading
        # between charge and first crack, so it has to be searched for. Early in
        # the roast the minimum is simply the latest sample and keeps sliding;
        # it is only a turning point once the bean has been climbing away from it
        # for a few samples, which is what the tail margin below tests.
        tp_index = -1
        if timeindex:
            try:
                found = findTPint(timeindex, timex, temp2)
                if charge < found < len(timex) - 5:
                    tp_index = found
            except Exception:
                tp_index = -1
                report_once('RoastCurveWidget: turning point search failed')

        t_charge = timex[charge]
        timex = [t - t_charge for t in timex]
        painter.setClipRect(self._plot_rect)

        # Phases sit under everything: they are a ground, not a mark.
        self._draw_phase_bands(painter, timex, timeindex)
        self._draw_crack_band(painter, timex)

        # The reference lives in the same CHARGE-relative frame as this roast.
        # It is painted first, so every live trace remains the visual authority
        # even where the two roasts follow one another exactly.
        if reference is not None:
            self._draw_reference(painter, *reference)

        # A short delta1 is not a mid-append transient but a profile recorded
        # with Artisan's ET rate switched off: tracing the fragment would show a
        # machine response that stops in the middle of the roast for no visible
        # reason. Better to draw none.
        if self.show_machine_response and len(delta1) >= len(timex) - 2 and delta1:
            pen = QPen(QColor(self._machine_rise_colour()))
            pen.setWidthF(_MACHINE_ROR_PEN_WIDTH)
            pen.setStyle(Qt.PenStyle.DashLine)
            color = QColor(self._machine_rise_colour())
            color.setAlpha(140)
            pen.setColor(color)
            painter.setPen(pen)
            for poly in self._build_ror_segments(timex, delta1, mode):
                painter.drawPolyline(poly)

        if delta2:
            pen = QPen(QColor(self._rise_colour()))
            pen.setWidthF(_ROR_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_ror_segments(timex, delta2, mode):
                painter.drawPolyline(poly)

        # Under the bean, and thinner: the air is context for the bean's climb,
        # never the line the roast is read from.
        if temp1:
            pen = QPen(QColor(self._air_colour()))
            pen.setWidthF(_AIR_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_temp_segments(timex, temp1, mode):
                painter.drawPolyline(poly)

        if temp2:
            pen = QPen(QColor(self._grain_colour()))
            pen.setWidthF(_GRAIN_PEN_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for poly in self._build_temp_segments(timex, temp2, mode):
                painter.drawPolyline(poly)

        self._draw_forecast(painter)

        self._draw_settings(painter, timex, events, ev_types, ev_pcts, ev_colors)

        # Milestones last, and their labels last of all: a label that a curve
        # can cross is a label that cannot be read. Their rules cross both plots,
        # which is what ties a setting to the moment it was played.
        painter.setClipRect(self._full_rect())
        # Before the marked milestones, so the crack that was HEARD keeps the
        # stronger rule and the plan stays the fainter of the two.
        self._draw_planned_fc(painter)
        self._draw_milestones(painter, timex, temp2, mode, timeindex, tp_index)
        self._draw_hover(painter, timex, temp2, temp1, delta2, delta1, mode,
                         events, ev_types, ev_pcts, ev_colors)

        # One legend for the whole chart, on its own row under the time axis.
        # Anywhere inside a plot it either covers a trace or gets covered by one.
        self._draw_curve_legend(painter)

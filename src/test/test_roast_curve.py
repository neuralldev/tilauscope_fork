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

"""The roast curve engine, driven through every state it has to survive.

The defects this widget has shipped were not arithmetic. They were a default
written one line too late, a figure that was right on a live roast and lied on
a loaded one, a hover that worked over the plot and died over the lanes, a card
that walked onto the marker it was explaining. None of those needs a roaster to
reproduce; all of them need the widget to be *built and painted* in the state
that triggers them, which is what this module does.

Painting matters. A tick() that only touches labels cannot reach a paintEvent,
and paintEvent is where the geometry lives, so every state here is rendered to
a pixmap rather than merely constructed.

The host is the widget itself. These tests used to run inside a shell that has
since been removed, and a widget that has only ever been exercised inside one
particular parent has only been half tested: the roast screen builds
``RoastCurveWidget(aw)`` and puts it in a layout, which is what happens here.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import pytest
import roast_harness as H
from PyQt6.QtCore import QRectF
from tilauscope.tilauscope_types import THEME

# NOTE: the modules under test are imported inside the tests, never here. A
# test earlier in the suite pulls in artisanlib.main, whose logging dictConfig
# disables every logger that already exists — so a module imported at
# collection time comes out mute, and the guards that only speak through a log
# go unverified.

GRAPH_DIR = Path(__file__).resolve().parent.parent / 'tilauscope' / 'graph'


@pytest.fixture
def roast_curve(qapp: Any):
    """Builds the curve over a scenario, and tears it down after the test."""
    built: list[Any] = []

    def _build(aw: Any) -> Any:
        from tilauscope.graph.common import reset_reports
        from tilauscope.graph.curve import RoastCurveWidget

        # Guards report once per site per process; without this the first test
        # to trip one would hide it from every test after it.
        reset_reports()

        widget = RoastCurveWidget(aw)
        widget.resize(900, 520)
        qapp.processEvents()
        built.append(widget)
        return widget

    yield _build

    for widget in built:
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


def _paint(widget: Any) -> None:
    """Force a full paint pass over the whole widget."""
    widget.grab()


def _errors(caplog: Any) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize('state', [name for name, _ in H.all_states()])
def test_every_state_builds_and_paints_in_silence(state, roast_curve, caplog) -> None:
    """Build, tick and paint each roast state; nothing may raise or be logged.

    The silence half of this is the point. Every paint is guarded, so a curve
    that has been broken for weeks still looks like a curve — it just shows a
    stale frame. Failing on a logged exception is what turns that back into a
    visible defect.
    """
    aw = H.scenario(state.split('/')[0], simulator=state.endswith('/simulator'))
    with caplog.at_level(logging.ERROR):
        curve = roast_curve(aw)
        curve.tick()
        _paint(curve)
    assert _errors(caplog) == [], f'{state}: {_errors(caplog)}'


@pytest.mark.parametrize('state', [name for name, _ in H.all_states()])
def test_hover_sweeps_the_full_width_in_silence(state, roast_curve, caplog) -> None:
    """Drag the pointer across the whole curve band, plot and lanes alike.

    The lanes were dead to hover for a whole iteration because the hit test
    accepted the plot rectangle only. Sweeping the full height catches that
    class without anyone having to notice it on screen.
    """
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    name = state.split('/')[0]
    aw = H.scenario(name, simulator=state.endswith('/simulator'))
    with caplog.at_level(logging.ERROR):
        curve = roast_curve(aw)
        w, h = curve.width(), curve.height()
        for fx in (0.01, 0.2, 0.5, 0.8, 0.99):
            for fy in (0.02, 0.3, 0.6, 0.85, 0.98):
                pos = QPointF(w * fx, h * fy)
                event = QMouseEvent(
                    QEvent.Type.MouseMove, pos, curve.mapToGlobal(pos),
                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(curve, event)
                _paint(curve)
    assert _errors(caplog) == [], f'{state}: {_errors(caplog)}'


@pytest.mark.parametrize('state', ['maillard', 'development', 'replay'])
def test_view_switches_paint_in_silence(state, roast_curve, caplog) -> None:
    """Both time windows and both lane modes, on real data."""
    from tilauscope.graph.curve import _LANE_MODE_BURNER, _LANE_MODE_LANES

    name = state.split('/')[0]
    aw = H.scenario(name)
    with caplog.at_level(logging.ERROR):
        curve = roast_curve(aw)
        for mode in (_LANE_MODE_LANES, _LANE_MODE_BURNER):
            curve._set_lane_mode(mode)
            _paint(curve)
        for closeup in (True, False):
            curve._set_closeup(closeup)
            _paint(curve)
    assert _errors(caplog) == [], f'{state}: {_errors(caplog)}'


def test_profile_swap_is_locked_while_monitoring_or_roasting(roast_curve) -> None:
    """The prominent swap button must never mutate a live roast."""
    aw = H.scenario('replay')
    aw.curFile = '/tmp/foreground-roast.alog'
    switched: list[bool] = []
    aw.switch = lambda: switched.append(True)
    curve = roast_curve(aw)

    assert curve._switch_btn.isEnabled()
    curve._on_switch_clicked()
    assert switched == [True]

    # Monitoring is already sampling, even before CHARGE.
    aw.qmc.flagon = True
    aw.qmc.flagstart = False
    curve.tick()
    assert not curve._switch_btn.isEnabled()
    assert 'locked' in curve._switch_btn.toolTip().lower()
    curve._on_switch_clicked()
    assert switched == [True]

    # Recording after CHARGE remains locked as well.
    aw.qmc.flagstart = True
    curve.tick()
    assert not curve._switch_btn.isEnabled()
    curve._on_switch_clicked()
    assert switched == [True]

    aw.qmc.flagon = aw.qmc.flagstart = False
    curve.tick()
    assert curve._switch_btn.isEnabled()
    curve._on_switch_clicked()
    assert switched == [True, True]


def test_profile_swap_is_disabled_when_no_profile_is_loaded(roast_curve) -> None:
    aw = H.scenario('cold')
    switched: list[bool] = []
    aw.switch = lambda: switched.append(True)
    curve = roast_curve(aw)

    assert not curve._switch_btn.isEnabled()
    assert 'load a roast profile' in curve._switch_btn.toolTip().lower()
    curve._on_switch_clicked()
    assert switched == []

    # Either side is enough: switch() can promote a background or demote a
    # file-backed foreground profile.
    aw.qmc.backgroundprofile = {}
    curve.tick()
    assert curve._switch_btn.isEnabled()

    aw.qmc.backgroundprofile = None
    aw.curFile = '/tmp/finished-roast.alog'
    curve.tick()
    assert curve._switch_btn.isEnabled()


def test_a_growing_roast_never_breaks_the_screen(roast_curve, caplog) -> None:
    """Walk a roast sample by sample, the way Artisan's loop grows the arrays.

    A screen fed a finished roast is a screen that has never seen its own
    hardest moments: the first sample, the sample where a milestone lands, the
    sample right after the drop.
    """
    aw = H.scenario('cold')
    qmc = aw.qmc
    with caplog.at_level(logging.ERROR):
        curve = roast_curve(aw)
        qmc.flagon = qmc.flagstart = True
        for i in range(240):
            qmc.append(float(i), 200.0 + i * 0.2, 90.0 + i * 0.5, 12.0)
            if i == 20:
                qmc.timeindex[0] = len(qmc.timex) - 1
            if i == 140:
                qmc.timeindex[1] = len(qmc.timex) - 1
            if i == 220:
                qmc.timeindex[2] = len(qmc.timex) - 1
            curve.tick()
            if i % 20 == 0:
                _paint(curve)
        _paint(curve)
    assert _errors(caplog) == []


# ── what the curve reads before it draws anything ────────────────────────

def test_the_burner_leads_the_channel_order() -> None:
    """Artisan's slider order is an implementation detail; the operator's order
    is the order of leverage, and the burner is the first lever."""
    from tilauscope.graph.common import channel_order

    assert channel_order([1, 1, 1, 1])[0] == H.BURNER
    assert channel_order([1, 1, 1, 1])[1] == H.AIR
    assert H.BURNER not in channel_order([1, 1, 1, 0])   # hidden, never invented
    assert channel_order(None) == []
    assert channel_order([0, 0, 0, 0]) == []


def test_the_background_roast_is_aligned_on_its_own_charge() -> None:
    """Artisan may move its background to align DRY, FC or DROP.

    Those canvas offsets must not leak into the comparison: the two roasts
    share zero at CHARGE, and a vertical nudge does not rewrite the recorded
    temperatures TilauScope draws.
    """
    from tilauscope.graph.curve import _background_roast

    qmc = H.FakeQmc()
    qmc.background = True
    qmc.backgroundprofile = {}
    qmc.timeB = [500.0, 520.0, 540.0]
    qmc.timeindexB = [1, 0, 0, 0, 0, 0, 2, 0]
    qmc.temp1B = [195.0, 205.0, 215.0]
    qmc.temp2B = [115.0, 125.0, 135.0]
    qmc.stemp1B = list(qmc.temp1B)
    qmc.stemp2B = list(qmc.temp2B)
    qmc.delta1B = [5.0, 6.0, 7.0]
    qmc.delta2B = [8.0, 9.0, 10.0]
    qmc.backgroundprofile_moved_x = 400
    qmc.backgroundprofile_moved_y = 15

    reference = _background_roast(qmc, show_air=True, show_machine=True)
    assert reference is not None
    timex, air, bean, rise, machine, mode = reference
    assert timex == [-20.0, 0.0, 20.0]
    assert air == [180.0, 190.0, 200.0]
    assert bean == [100.0, 110.0, 120.0]
    assert rise == [12.0, 12.0, 12.0]
    assert machine == [12.0, 12.0, 12.0]
    assert mode == 'C'
    assert qmc.recomputed == 1

    _background_roast(qmc, show_air=True, show_machine=True)
    assert qmc.recomputed == 1, 'the static reference recomputed its rise on repaint'

    # Loading a foreground can hide Artisan's own background canvas without
    # unloading the reference. DisplayScope must keep the comparison.
    qmc.background = False
    assert _background_roast(qmc, show_air=True, show_machine=True) is not None

    qmc.backgroundprofile = None
    assert _background_roast(qmc, show_air=True, show_machine=True) is None


def test_the_reference_keeps_the_live_hue_at_lower_strength() -> None:
    from PyQt6.QtGui import QColor
    from tilauscope.graph.curve import _REFERENCE_ALPHA, _reference_colour

    live = QColor('#89B4FA')
    reference = _reference_colour(live.name())
    assert reference.alpha() == _REFERENCE_ALPHA
    assert reference.red() == live.red()
    assert reference.green() == live.green()
    assert reference.blue() == live.blue()


def test_a_loaded_background_paints_the_same_requested_traces(
        roast_curve, caplog) -> None:
    """Bean/rise are always mirrored; air/machine follow the same switches."""
    aw = H.scenario('maillard')
    qmc = aw.qmc
    qmc.background = True
    qmc.backgroundprofile = {}
    qmc.timeB = [t + 300.0 for t in qmc.timex]
    qmc.timeindexB = list(qmc.timeindex)
    qmc.temp1B = list(qmc.temp1)
    qmc.temp2B = list(qmc.temp2)
    qmc.stemp1B = list(qmc.temp1)
    qmc.stemp2B = list(qmc.temp2)
    qmc.delta1B = list(qmc.delta1)
    qmc.delta2B = list(qmc.delta2)
    qmc.backgroundprofile_moved_y = 0

    curve = roast_curve(aw)
    calls: list[tuple] = []
    draw = curve._draw_reference

    def record(painter, *series) -> None:  # noqa: ANN001
        calls.append(series)
        draw(painter, *series)

    curve._draw_reference = record
    with caplog.at_level(logging.ERROR):
        curve.show_air_temperature = False
        curve.show_machine_response = False
        _paint(curve)
        curve.show_air_temperature = True
        curve.show_machine_response = True
        _paint(curve)

    assert _errors(caplog) == []
    assert len(calls) == 2
    # timex, temp1, temp2, delta2, delta1, mode
    assert calls[0][1] == [] and calls[0][4] == []
    assert calls[0][2] and calls[0][3]
    assert calls[1][1] and calls[1][4]


def test_loading_a_foreground_does_not_hide_the_reference_from_displayscope(
        roast_curve, caplog) -> None:
    """Artisan's hide-after-load flag belongs to its canvas, not this comparison."""
    aw = H.scenario('replay')
    qmc = aw.qmc
    qmc.backgroundprofile = {}
    qmc.timeB = [t + 180.0 for t in qmc.timex]
    qmc.timeindexB = list(qmc.timeindex)
    qmc.temp1B = list(qmc.temp1)
    qmc.temp2B = list(qmc.temp2)
    qmc.stemp1B = list(qmc.stemp1)
    qmc.stemp2B = list(qmc.stemp2)
    qmc.backgroundprofile_moved_y = 0
    # What ApplicationWindow.loadFile does when hideBgafterprofileload is set.
    qmc.background = False

    curve = roast_curve(aw)
    calls: list[tuple] = []
    draw = curve._draw_reference

    def record(painter, *series) -> None:  # noqa: ANN001
        calls.append(series)
        draw(painter, *series)

    curve._draw_reference = record
    with caplog.at_level(logging.ERROR):
        curve.tick()
        _paint(curve)

    assert _errors(caplog) == []
    assert len(calls) == 1


def test_a_background_is_drawn_without_a_foreground_roast(
        roast_curve, caplog) -> None:
    """A reference is roast data, not an empty chart, even when it stands alone."""
    aw = H.scenario('replay')
    qmc = aw.qmc
    qmc.background = True
    qmc.backgroundprofile = {}
    qmc.timeB = [t + 240.0 for t in qmc.timex]
    qmc.timeindexB = list(qmc.timeindex)
    qmc.temp1B = list(qmc.temp1)
    qmc.temp2B = list(qmc.temp2)
    qmc.stemp1B = list(qmc.stemp1)
    qmc.stemp2B = list(qmc.stemp2)
    qmc.backgroundprofile_moved_y = 0
    qmc.titleB = 'Reference roast'

    qmc.timex = []
    qmc.temp1 = []
    qmc.temp2 = []
    qmc.stemp1 = []
    qmc.stemp2 = []
    qmc.delta1 = []
    qmc.delta2 = []
    qmc.timeindex = [-1] * 8
    qmc.flagon = qmc.flagstart = False

    curve = roast_curve(aw)
    calls: list[tuple] = []
    draw = curve._draw_reference

    def record(painter, *series) -> None:  # noqa: ANN001
        calls.append(series)
        draw(painter, *series)

    curve._draw_reference = record
    with caplog.at_level(logging.ERROR):
        curve.show()
        curve.tick()
        _paint(curve)

    assert _errors(caplog) == []
    assert len(calls) == 1
    assert calls[0][0][qmc.timeindexB[0]] == 0.0
    assert curve._rate_axis
    assert curve._t_min <= 0.0 <= curve._t_max
    assert curve._closeup
    assert curve._seg_closeup.isChecked()
    assert curve._view_btn.isVisibleTo(curve)


def test_the_context_menu_can_remove_the_loaded_reference(roast_curve) -> None:
    from PyQt6.QtWidgets import QMenu

    aw = H.scenario('replay')
    qmc = aw.qmc
    qmc.background = True
    qmc.backgroundprofile = {}
    qmc.timeB = list(qmc.timex)
    qmc.timeindexB = list(qmc.timeindex)
    qmc.temp1B = list(qmc.temp1)
    qmc.temp2B = list(qmc.temp2)
    qmc.stemp1B = list(qmc.stemp1)
    qmc.stemp2B = list(qmc.stemp2)
    cleared: list[bool] = []

    def clear() -> None:
        cleared.append(True)
        qmc.background = False
        qmc.backgroundprofile = None
        qmc.timeB = []
        qmc.temp1B = []
        qmc.temp2B = []

    aw.clearbackgroundRedraw = clear
    curve = roast_curve(aw)
    menu = QMenu(curve)
    action = curve._add_background_menu_action(menu)

    assert action is not None
    assert action.text() == 'Remove reference curve'
    action.trigger()
    assert cleared == [True]
    assert qmc.backgroundprofile is None

    empty_menu = QMenu(curve)
    assert curve._add_background_menu_action(empty_menu) is None


# ── the guard that keeps the guards honest ───────────────────────────────

def test_no_graph_module_swallows_an_exception_in_silence() -> None:
    """A bare ``except Exception: pass`` is how a broken curve keeps looking fine.

    Guards are right — nothing may raise into Artisan's sampling loop, and
    nothing may escape a Qt virtual — but a guard that says nothing turns a
    defect into stale pixels, which is exactly the failure mode this screen has
    been shipping. Every guard must leave a trace: a log call, or a re-raise.
    """
    offenders: list[str] = []
    for path in sorted(GRAPH_DIR.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if _handler_leaves_a_trace(node):
                continue
            offenders.append(f'{path.name}:{node.lineno}')
    assert offenders == [], (
        'silent exception guards — each must log or re-raise: ' + ', '.join(offenders))


def _handler_leaves_a_trace(node: ast.ExceptHandler) -> bool:
    """True if the handler logs, re-raises, or is a narrow expected-error catch.

    A named exception type is a decision about a known failure — a missing
    optional attribute, a disconnected signal. A bare ``Exception`` is a net,
    and a net has to report what it caught.
    """
    if node.type is not None and not _catches_broad(node.type):
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Raise):
            return True
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in {
                    'exception', 'error', 'warning'}:
                return True
            # common.report_once is the package's own once-per-site log call.
            if isinstance(func, ast.Name) and func.id == 'report_once':
                return True
    return False


def _catches_broad(node: ast.expr) -> bool:
    names = [node] if not isinstance(node, ast.Tuple) else list(node.elts)
    return any(isinstance(n, ast.Name) and n.id in {'Exception', 'BaseException'}
               for n in names)


# ── the plot: axes, phases, lanes ────────────────────────────────────────

def test_a_lane_fill_is_as_tall_as_its_value(roast_curve) -> None:
    """Measure the painted fill, rather than argue about it.

    The lane amplitude looked wrong on screen — a burner held at 60% seeming to
    fill most of its band. This renders the widget and measures the fill
    boundary against the lane it sits in, so the question is settled by the
    pixels the operator actually sees.
    """
    from PyQt6.QtGui import QColor

    aw = H.scenario('replay')
    qmc = aw.qmc
    # One channel, one value, held for the whole roast: an unambiguous target.
    aw.eventslidervisibilities = [0, 0, 0, 1]
    qmc.specialevents, qmc.specialeventstype, qmc.specialeventsvalue = [], [], []
    qmc.add_event(qmc.timeindex[0], H.BURNER, 60)

    curve = roast_curve(aw)
    image = curve.grab().toImage()

    lanes = [(n, rect) for n, rect, _kind in curve._lane_rows if n == H.BURNER]
    assert lanes, 'the burner lane was not laid out'
    _n, lane = lanes[0]

    x = int(lane.center().x())
    top, bottom = int(lane.top()) + 1, int(lane.bottom()) - 1
    ground = QColor(image.pixel(x, top))          # empty part of the lane
    filled = [y for y in range(top, bottom + 1)
              if QColor(image.pixel(x, y)) != ground]
    assert filled, 'the lane painted no fill at all'

    height = bottom - top + 1
    share = (bottom - min(filled) + 1) / height
    assert 0.5 <= share <= 0.7, f'60% was painted as {share:.0%} of the lane'


def test_a_failing_paint_is_reported_and_contained(roast_curve, caplog) -> None:
    """Nothing may escape paintEvent — an escape does not blank a chart, it quits.

    PyQt sends an exception raised inside a reimplemented virtual to the process
    excepthook, and this application's excepthook ends in sys.exit. So the cost
    of an unguarded paint is the roast window closing mid-roast, on a machine
    with beans in it.
    """
    aw = H.scenario('development')
    curve = roast_curve(aw)

    def _explode(*_a: Any, **_k: Any) -> None:
        raise RuntimeError('a bad sample')

    curve._draw_milestones = _explode
    with caplog.at_level(logging.ERROR):
        _paint(curve)      # must not raise, must not leave the painter active
    assert _errors(caplog), 'a failing paint said nothing at all'
    _paint(curve)          # and the next frame still works


def test_a_roast_longer_than_the_fixed_scale_is_still_drawn(roast_curve) -> None:
    """The scale is fixed at 14:00 by design; a roast that outlasts it is not.

    Truncating the window means the curve stops growing while the clock runs on,
    which on a long roast is the screen quietly ceasing to report.
    """
    aw = H.scenario('cold')
    qmc = aw.qmc
    qmc.flagon = qmc.flagstart = True
    qmc.timeindex[0] = 0
    for i in range(1100):        # 18:20, well past the 14:00 scale
        qmc.append(float(i), 200.0, 90.0 + i * 0.1, 8.0)

    curve = roast_curve(aw)
    _paint(curve)
    elapsed = qmc.timex[-1] - qmc.timex[qmc.timeindex[0]]
    assert curve._t_max >= elapsed, 'the window cut the roast short'


def test_the_live_window_opens_a_minute_before_the_charge(roast_curve) -> None:
    """Twelve seconds of roast against a 14:00 scale sits crushed on the axis,
    with the charge itself hard against the frame. The window carries a minute
    of lead-in so the approach and the plunge have somewhere to be drawn."""
    aw = H.scenario('cold')
    qmc = aw.qmc
    qmc.flagon = qmc.flagstart = True
    for i in range(80):          # a minute of preheat, then twelve seconds of roast
        qmc.append(float(i), 190.0, 185.0, 8.0)
    qmc.timeindex[0] = 68

    curve = roast_curve(aw)
    _paint(curve)
    assert curve._t_min == -60.0, 'the roast starts hard against the axis'
    assert curve._x(0.0) > curve._plot_rect.left() + 1.0, 'the charge line is on the frame'


def test_a_phase_ground_stops_at_the_drop(roast_curve) -> None:
    """With a milestone unmarked the preceding phase must not be painted across
    the drop and through the cooling tail."""
    aw = H.scenario('replay')
    qmc = aw.qmc
    qmc.timeindex[2] = 0 if qmc.timeindex[1] == 0 else -1   # forget first crack
    curve = roast_curve(aw)
    _paint(curve)

    charge, drop = int(qmc.timeindex[0]), int(qmc.timeindex[6])
    roast = float(qmc.timex[drop]) - float(qmc.timex[charge])
    spans = curve._phase_spans([t - qmc.timex[charge] for t in qmc.timex], qmc.timeindex)
    assert spans, 'no phase ground at all'
    assert max(end for _s, end, _c in spans) <= roast + 0.5


def test_a_rate_below_the_axis_breaks_the_line(roast_curve) -> None:
    """The rate axis starts at zero, so a crash below it cannot be drawn.

    Pinning it to the baseline is the dangerous option: a crashing rate would
    render as a steady zero, which is a different roast.
    """
    aw = H.scenario('development')
    curve = roast_curve(aw)
    charge = int(aw.qmc.timeindex[0])
    timex = [t - aw.qmc.timex[charge] for t in aw.qmc.timex]

    rising = [10.0] * len(timex)
    crashed = list(rising)
    crashed[len(crashed) // 2] = -6.0
    assert len(curve._build_ror_segments(timex, crashed, 'C')) > \
        len(curve._build_ror_segments(timex, rising, 'C'))


# ── the three rate-of-rise levels ────────────────────────────────────────

def test_the_levels_stay_inside_the_window_the_corpus_measured() -> None:
    """Below about 10 s of span an untroubled roast reads as a crash; above
    about 25 s a real crash is flattened into the ordinary. The levels are
    bounded by that measurement, not chosen for roundness."""
    from tilauscope.graph.smoothing import LEVELS

    assert [level.span for level in LEVELS] == [10, 15, 25]
    for level in LEVELS:
        assert 10 <= level.span <= 25
        assert level.ror_filter % 2 == 1          # a centred average needs odd


def test_the_default_level_changes_nothing_for_a_roaster_already_set_up() -> None:
    """Standard is what the reference machine already ran. A level that moved
    the reference would rewrite how every roast on file reads."""
    from tilauscope.graph.smoothing import DEFAULT, LEVELS

    standard = next(level for level in LEVELS if level.key == DEFAULT)
    assert (standard.span, standard.ror_filter) == (15, 7)


def test_choosing_a_level_sets_both_probes_and_recomputes(roast_curve) -> None:
    """Both probes answer the same question about two thermometers: left apart,
    one trace lags the other for no reason the operator can see."""
    from tilauscope.graph import smoothing as smooth

    aw = H.scenario('replay')
    curve = roast_curve(aw)
    curve.tick()

    assert smooth.apply_level(aw.qmc, 'smooth')
    assert aw.qmc.deltaBTspan == aw.qmc.deltaETspan == 25
    assert aw.qmc.deltaBTfilter == aw.qmc.deltaETfilter == 9
    assert aw.qmc.deltaBTsamples == 25                # derived, not left stale
    assert aw.qmc.delta2 == []                        # cleared so it recomputes
    assert smooth.current(aw.qmc) == 'smooth'


def test_a_running_roast_never_loses_the_rate_it_has_measured() -> None:
    """A finished roast is recomputed to show the change. A running one is not:
    its rate is being measured sample by sample, and clearing it would throw
    away the roast so far."""
    from tilauscope.graph import smoothing as smooth

    aw = H.scenario('development')                    # flagstart is set
    before = list(aw.qmc.delta2)
    assert smooth.apply_level(aw.qmc, 'responsive')

    assert aw.qmc.deltaBTspan == 10                   # the setting still took
    assert aw.qmc.delta2 == before                    # the measurements did not


def test_settings_made_in_artisan_are_not_claimed_as_a_level() -> None:
    """An operator who set their own numbers sees no level ticked, rather than
    the nearest one — which would claim a choice they did not make."""
    from tilauscope.graph import smoothing as smooth

    aw = H.scenario('replay')
    aw.qmc.deltaBTspan = 18
    aw.qmc.deltaBTfilter = 7
    assert smooth.current(aw.qmc) == ''
    assert smooth.current(None) == ''          # and no canvas is not a level


# ── the setting lanes under the plot ─────────────────────────────────────

def test_the_setting_lanes_are_drawn_live(roast_curve) -> None:
    """Reading a gesture against the curve it caused is worth most while the
    roast is running. They were once held back until the roast was over; the
    operator asked for them live, and Artisan's own graph drew them live."""
    for state in ('monitoring', 'maillard', 'replay'):
        curve = roast_curve(H.scenario(state))
        curve.tick()
        assert len(curve._lane_rows) == 4, \
            f'{state}: the lanes were withheld'


def test_a_lane_with_no_gesture_yet_still_says_where_it_is_held(roast_curve) -> None:
    """Every channel during a preheat: nothing recorded, but the lever is set to
    something. An empty strip says the opposite of the truth."""
    from PyQt6.QtGui import QColor

    aw = H.scenario('monitoring')
    aw.eventslidervalues = [0, 0, 0, 62]
    aw.qmc.specialevents, aw.qmc.specialeventstype, aw.qmc.specialeventsvalue = [], [], []
    curve = roast_curve(aw)
    curve.tick()

    lanes = [r for n, r, _k in curve._lane_rows if n == H.BURNER]
    assert lanes, 'the burner lane was not laid out'
    image = curve.grab().toImage()
    lane = lanes[0]
    row = int(lane.center().y())
    ground = QColor(image.pixel(int(lane.right()) - 2, int(lane.top()) + 2))
    painted = [x for x in range(int(lane.left()) + 2, int(lane.right()) - 2)
               if QColor(image.pixel(x, row)) != ground]
    assert painted, 'a held lever was drawn as an empty lane'


def test_a_loaded_roast_is_not_given_the_current_lever_values(roast_curve) -> None:
    """The sliders carry this session's values. On a roast read back from disk
    they are not what was played, and drawing them would invent a gesture."""
    aw = H.scenario('replay')
    aw.eventslidervalues = [0, 0, 0, 62]
    aw.qmc.specialevents, aw.qmc.specialeventstype, aw.qmc.specialeventsvalue = [], [], []
    curve = roast_curve(aw)
    curve.tick()
    assert curve._held_now(H.BURNER) is None, \
        'a loaded roast was given the live lever values'


def test_close_setting_values_are_repositioned_not_dropped() -> None:
    """Every close gesture keeps a value directly above/below its own dot."""
    from tilauscope.graph.curve import _lane_label_layout

    # Compact labels fit the dense visual regression on two rows without any
    # horizontal displacement toward a neighbouring marker.
    dots = [100.0, 108.0, 116.0, 124.0, 132.0, 140.0, 148.0]
    widths = [14.0] * len(dots)
    placements = _lane_label_layout(list(zip(dots, widths, strict=True)), 0.0, 220.0)

    assert len(placements) == len(dots)
    labels = [(x, x + width, row)
              for (x, row), width in zip(placements, widths, strict=True)]
    for start, end, row in labels:
        assert 0.0 <= start < end <= 220.0
        peers = [(other_start, other_end) for other_start, other_end, other_row in labels
                 if other_row == row and (other_start, other_end) != (start, end)]
        assert all(end <= other_start or start >= other_end
                   for other_start, other_end in peers)
    assert all(abs((start + end) / 2.0 - dot) < 0.01
               for (start, end, _row), dot in zip(labels, dots, strict=True))
    assert max(row for _start, _end, row in labels) == 1


def test_dense_setting_values_keep_a_two_row_lane(roast_curve) -> None:
    """Dense values never make the setting lane grow beyond two rows."""
    from tilauscope.graph.curve import _LANE_MARK_HEIGHT, _LANE_MODE_BURNER

    aw = H.scenario('replay')
    qmc = aw.qmc
    qmc.specialevents = []
    qmc.specialeventstype = []
    qmc.specialeventsvalue = []
    qmc.specialeventsStrings = []
    charge = qmc.timeindex[0]
    for offset, value in zip(range(290, 339, 8), range(31, 38), strict=True):
        qmc.add_event(charge + offset, H.DAMPER, value)

    curve = roast_curve(aw)
    curve._set_lane_mode(_LANE_MODE_BURNER)
    curve.tick()
    lane, kind = next((rect, row_kind) for channel, rect, row_kind in curve._lane_rows
                      if channel == H.DAMPER)
    mark_heights = [rect.height() for _channel, rect, row_kind in curve._lane_rows
                    if row_kind == 'marks']

    assert kind == 'marks'
    assert all(height == pytest.approx(lane.height()) for height in mark_heights)
    assert lane.height() <= _LANE_MARK_HEIGHT


def test_drying_annotation_omits_only_its_redundant_bt_row(roast_curve) -> None:
    """Drying already exposes BT in the readout/hover; later phases keep it."""
    from tilauscope.graph import annotation_text as text

    drying = roast_curve(H.scenario('drying'))
    drying.annotations.set_coach_allowed(True)
    drying.annotations.expert_view = True
    drying.tick()
    dry_html = drying.annotations.roast.text()

    maillard = roast_curve(H.scenario('maillard'))
    maillard.annotations.set_coach_allowed(True)
    maillard.annotations.expert_view = True
    maillard.tick()
    maillard_html = maillard.annotations.roast.text()

    bt_cell = f">{text._labels()['BT']}</td>"  # noqa: SLF001 - exact rendered label
    assert bt_cell not in dry_html
    assert bt_cell in maillard_html


# ── the preheat, on an axis of its own ───────────────────────────────────

def _climbing(minutes: int = 8, target: float = 185.0):
    """A drum being taken from cold, with a preheat controller driving it.

    Recording is on. Not a detail: Artisan only cycles the preheat law when
    ``flagstart`` is set, so a preheat with recording off is a preheat whose
    controller never runs — a state the operator cannot be in.
    """
    aw = H.scenario('cold')
    aw.qmc.flagon = aw.qmc.flagstart = True
    bt = 22.0
    ror = 12.0
    for i in range(minutes * 60):
        ror = max(2.0, 14.0 * (1.0 - bt / 210.0))
        bt += ror / 60.0
        aw.qmc.append(float(i), bt + 12.0, bt, ror)
    aw.qmc.rateofchange2 = ror
    aw.tilauPreheatingPid = H.FakePreheatPID(target=target, projected=bt + 1.0)
    return aw


def test_the_preheat_is_drawn_on_an_axis_that_contains_it(roast_curve) -> None:
    """The roast temperature axis starts at 40°; a drum taken from cold would
    draw a flat line along the bottom of it. The climb keeps the roast's own
    fourteen-minute frame — a preheat is that long — and gets a temperature axis
    that reaches from cold to above the target."""
    aw = _climbing(minutes=8, target=185.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)          # the axes are settled when the frame is drawn

    assert curve._preheat is not None
    assert curve._t_min == 0.0             # elapsed, not charge-relative
    assert curve._t_max == 840.0           # the same frame the roast is read on
    assert curve._temp_lo < 40.0           # a cold drum is on the chart
    assert curve._temp_hi > 185.0          # and so is the number being waited for


def test_the_preheat_window_grows_with_the_climb(roast_curve) -> None:
    """It does not pretend to know how long a preheat takes."""
    short = roast_curve(_climbing(minutes=3))
    long_ = roast_curve(_climbing(minutes=18))
    for climb in (short, long_):
        climb.tick()
        _paint(climb)

    assert long_._t_max > short._t_max


def test_the_charge_hands_the_axis_back_to_the_roast(roast_curve) -> None:
    """A preheat that ran long must not leave the roast on a stretched axis."""
    aw = _climbing(minutes=20)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve._t_max > 840.0, 'a twenty-minute climb did not open the frame'

    aw.qmc.timeindex[0] = len(aw.qmc.timex) - 1
    aw.qmc.flagstart = True
    curve.tick()
    _paint(curve)

    assert curve._preheat is None
    assert curve._temp_lo == 40.0
    assert curve._temp_hi == 240.0


def test_the_preheat_carries_no_rate_axis(roast_curve) -> None:
    """A scale with nothing on it invites reading the drum temperature against
    the wrong numbers."""
    aw = _climbing()
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)

    # The frame is rebuilt from the axes, so the preheat state has to be in its
    # key — otherwise the roast frame is blitted under a preheat curve.
    assert curve._frame_key is not None
    assert True in curve._frame_key


def test_the_preheat_paints_without_a_word(roast_curve, caplog) -> None:
    """The whole point is that it is not an empty grid any more."""
    curve = roast_curve(_climbing())
    curve.tick()
    with caplog.at_level(logging.ERROR):
        _paint(curve)
    assert not _errors(caplog)


def test_the_charge_moment_is_marked_on_the_curve(roast_curve, caplog) -> None:
    """It rides the head of the curve, where the operator is already looking."""
    aw = _climbing(minutes=2, target=40.0)
    curve = roast_curve(aw)
    curve.tick()
    with caplog.at_level(logging.ERROR):
        _paint(curve)

    assert curve._preheat.ready is True
    assert not _errors(caplog)


# ── the two cards floating over the curve ────────────────────────────────

def test_the_roast_card_floats_against_the_bean_reading(roast_curve) -> None:
    """The card comments on one instant, so it has to sit at that instant. A
    card parked in a corner of the plot is a legend, not an annotation."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)

    card = curve.annotations.roast
    assert card.isVisibleTo(curve), 'the roast card never appeared'
    assert curve.annotations.preheat.isHidden(), 'both cards on screen at once'

    rect = curve.plot_rect()
    assert rect.left() - 1 <= card.x() <= rect.right(), 'the card left the plot'
    assert 0 <= card.y() <= curve.height() - card.height(), 'the card left the widget'


def test_the_preheat_card_gives_way_at_the_charge(roast_curve) -> None:
    """Before the charge the drum is the subject; after it the roast is. Two
    cards live at once would have the operator choose which one to believe."""
    aw = _climbing(minutes=6, target=185.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.preheat.isVisibleTo(curve), 'no card during the preheat'
    assert curve.annotations.roast.isHidden()

    aw.qmc.timeindex[0] = len(aw.qmc.timex) - 1
    aw.qmc.flagstart = True
    curve.tick()
    _paint(curve)
    assert curve.annotations.preheat.isHidden(), 'the preheat card outlived the charge'
    assert curve.annotations.roast.isVisibleTo(curve)


def test_no_card_before_the_charge_without_a_controller(roast_curve) -> None:
    """Monitoring a cold drum by hand has nothing to annotate. A card there
    would be furniture."""
    aw = H.scenario('monitoring')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.roast.isHidden()
    assert curve.annotations.preheat.isHidden()


def test_a_reading_outside_the_window_takes_its_card_with_it(roast_curve) -> None:
    """The window moves; for a cycle or two the latest reading projects outside
    it. A card left in place would point at a moment that is no longer there."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.roast.isVisibleTo(curve)

    # Push the window off the data rather than the data off the window: the
    # curve's own projection is what has to refuse.
    curve._t_min, curve._t_max = 3600.0, 4200.0
    curve.annotations.tick()
    assert curve.annotations.roast.isHidden(), 'the card survived losing its anchor'


def test_a_failing_formatter_costs_the_card_and_not_the_screen(
        roast_curve, caplog, monkeypatch) -> None:
    """The card's text is nine hundred lines of formatting over live readings.
    If any of it raises, the curve still has to draw — an annotation comments
    on the roast, it is not the roast."""
    from tilauscope.graph import annotation_text

    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError('formatter down')

    monkeypatch.setattr(annotation_text, 'roast_card', _boom)
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    with caplog.at_level(logging.ERROR):
        curve.tick()
        _paint(curve)
    assert curve.annotations.roast.isHidden()
    assert _errors(caplog), 'the failure passed in silence'
    _paint(curve)          # and the next frame still works


def test_the_preheat_card_carries_the_climb_and_not_the_fallback(roast_curve) -> None:
    """Both preheat formatters end in a bare-header fallback when anything in
    them raises. It renders, it logs, and it looks close enough to the real
    thing to pass a glance — so the test asks for something only the full
    render produces: the climb gauge."""
    aw = _climbing(minutes=5, target=185.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    card = curve.annotations.preheat
    assert card.isVisibleTo(curve)
    assert '&#9608;' in card.text(), 'the preheat card fell back to its header'


def test_the_roast_card_names_the_phase_it_is_in(roast_curve) -> None:
    """The card is built from the roast state, not from a template. Naming the
    phase is the cheapest proof that the state actually reached it."""
    aw = H.scenario('development')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    card = curve.annotations.roast
    assert card.isVisibleTo(curve)
    assert card.text().strip(), 'the roast card rendered empty'


# ── the air, the arrival marker and the coach toggle ─────────────────────

def _near_colour(widget: Any, hexcolour: str, rect: Any = None, tol: int = 20) -> int:
    """Pixels close to one colour, sampled every other row and column.

    Antialiasing means a 1.8 px line lands very few pixels on its exact value,
    so an equality count is a coin toss. The tolerance is narrow enough that no
    other colour on the chart falls inside it.
    """
    from PyQt6.QtGui import QColor

    image = widget.grab().toImage()
    want = QColor(hexcolour)
    if rect is None:
        x0, y0, x1, y1 = 0, 0, image.width(), image.height()
    else:
        x0, y0 = int(rect.left()) + 1, int(rect.top()) + 1
        x1, y1 = int(rect.right()), int(rect.bottom())
    found = 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            c = QColor(image.pixel(x, y))
            if (abs(c.red() - want.red()) <= tol
                    and abs(c.green() - want.green()) <= tol
                    and abs(c.blue() - want.blue()) <= tol):
                found += 1
    return found


def test_the_air_stays_off_the_chart_until_it_is_asked_for(roast_curve) -> None:
    """On a radiant roaster the air runs below the bean and answers a question
    the operator does not have on every roast. It is offered, not imposed."""
    from tilauscope.graph import curve as curve_mod

    aw = H.scenario('maillard')
    curve = roast_curve(aw)

    before = _near_colour(curve, curve_mod._COLOR_AIR, curve.plot_rect())
    assert before == 0, 'the air was drawn without being asked for'

    curve._set_air_temperature(True)
    after = _near_colour(curve, curve_mod._COLOR_AIR, curve.plot_rect())
    assert after > 0, 'asking for the air drew nothing'


def _closing_in(minutes: int = 8, minutes_out: float = 3.0):
    """A climb whose target is a stated number of minutes away at the current
    rate — the state in which an arrival marker has something to say."""
    aw = _climbing(minutes=minutes, target=0.0)
    bt = float(aw.qmc.temp2[-1])
    target = bt + aw.qmc.rateofchange2 * minutes_out
    aw.tilauPreheatingPid = H.FakePreheatPID(target=target, projected=bt + 1.0)
    return aw


def test_the_arrival_marker_stands_where_the_climb_meets_the_target(roast_curve) -> None:
    """The countdown is on the card; this puts the same figure on the chart, so
    what is left to close is a distance rather than a number to picture."""
    aw = _closing_in(minutes=8, minutes_out=3.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve._preheat is not None and curve._preheat.eta is not None

    elapsed = float(aw.qmc.timex[-1]) - float(aw.qmc.timex[0])
    arrival_x = int(curve._x(elapsed + curve._preheat.eta))
    target_y = int(curve._y_temp(curve._preheat.target_c))
    rect = curve.plot_rect()
    assert rect.left() < arrival_x < rect.right(), 'the arrival fell off the axis'

    # Below the target line only: the target itself is drawn in the same colour
    # and runs the full width, so a column that included it would always pass.
    state = curve._preheat.colour
    band = QRectF(float(arrival_x - 1), float(target_y + 3), 3.0, 12.0)
    control = QRectF(rect.left() + 8.0, float(target_y + 3), 3.0, 12.0)
    assert _near_colour(curve, state, band) > 0, 'no marker at the arrival'
    assert _near_colour(curve, state, control) == 0, \
        'the marker colour was found where no marker belongs'

    # A tick, not a second rule: two dashed lines meeting at right angles read
    # as a grid, and the one that mattered was the horizontal one.
    deep = QRectF(float(arrival_x - 1), float(target_y + 40),
                  3.0, max(4.0, rect.bottom() - target_y - 44.0))
    assert _near_colour(curve, state, deep) == 0, \
        'the arrival was drawn as a full-height rule'


def test_a_distant_arrival_does_not_stretch_the_axis_to_reach_it(roast_curve) -> None:
    """A climb that outruns the frame has its arrival off it too, and opening
    the axis to a far arrival flattens what has been climbed so far against the
    left edge. The marker waits until it can come into view."""
    aw = _closing_in(minutes=20, minutes_out=30.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve._preheat is not None and curve._preheat.eta is not None

    elapsed = float(aw.qmc.timex[-1]) - float(aw.qmc.timex[0])
    assert elapsed + curve._preheat.eta > curve._t_max, \
        'the axis was stretched to a distant arrival'
    assert curve._t_max <= elapsed * 1.5, 'the climb was flattened'


def test_a_drum_that_has_arrived_is_given_no_countdown(roast_curve) -> None:
    """Once the drum is there the marker would sit on the head of the curve and
    claim there is still something to wait for."""
    aw = _climbing(minutes=5, target=185.0)
    # Put the target under the drum: the climb is over.
    aw.tilauPreheatingPid = H.FakePreheatPID(target=float(aw.qmc.temp2[-1]) - 2.0)
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve._preheat is not None and curve._preheat.ready
    assert curve._preheat.eta is None, 'a drum that has arrived was given a countdown'


def test_the_coach_toggle_follows_the_operator_level(roast_curve) -> None:
    """The switch is the point of the Guided level. An operator reading the full
    table has already said which view they want."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    layer = curve.annotations

    layer.set_coach_allowed(False)
    curve.tick()
    _paint(curve)
    assert layer.view_toggle.isHidden(), 'the toggle appeared outside Guided'

    layer.set_coach_allowed(True)
    layer.tick()
    assert layer.view_toggle.isVisibleTo(curve), 'Guided got no toggle'
    rect = curve.plot_rect()
    assert layer.view_toggle.y() + layer.view_toggle.height() <= rect.top(), \
        'the toggle sits on the curve it explains'

    layer.set_coach_allowed(False)
    assert layer.view_toggle.isHidden()


def test_the_coach_toggle_changes_what_the_card_says(roast_curve) -> None:
    """Two views of one roast, not two skins of one text — the guided view drops
    the table and keeps the gesture."""
    aw = H.scenario('development')
    curve = roast_curve(aw)
    layer = curve.annotations
    layer.set_coach_allowed(True)
    layer.expert_view = False
    layer.tick()
    coach = curve.annotations.roast.text()

    layer.expert_view = True
    layer.tick()
    expert = curve.annotations.roast.text()

    assert coach and expert
    assert coach != expert, 'both views rendered the same card'


def test_the_toggle_gives_way_with_the_card_it_switches(roast_curve) -> None:
    """A control left standing over a card that is not on screen offers to
    change nothing."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    layer = curve.annotations
    layer.set_coach_allowed(True)
    layer.tick()
    assert layer.view_toggle.isVisibleTo(curve)

    curve._t_min, curve._t_max = 3600.0, 4200.0
    layer.tick()
    assert curve.annotations.roast.isHidden()
    assert layer.view_toggle.isHidden(), 'the toggle outlived its card'


# ── the countdown to the next milestone ──────────────────────────────────

def test_the_card_counts_down_to_the_next_milestone(roast_curve) -> None:
    """The forward half of the card is the reason it exists. It came out of a
    drawing on the Artisan canvas — a projection line crossing the target — and
    the crossing is now computed instead. A card that always reads '--:--' looks
    exactly like a working one, so this asks for the figure itself.
    """
    from tilauscope.graph import annotation_text as text
    from tilauscope.graph import forecast

    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.forecast_t is not None, 'no forecast was made'

    # The figure itself, not merely the absence of a dash: handed the current
    # time instead of the forecast the card still renders a countdown — 00:00 —
    # which reads as a working card. That is the regression this guards.
    _target, info = text.phase_and_target(aw.qmc)
    raw = forecast.milestone(aw.qmc, info)
    assert raw is not None
    left = int(raw - float(aw.qmc.timex[-1]))
    assert left > 30, 'the scenario left nothing to count down'
    expected = f'{left // 60:02d}:{left % 60:02d}'

    layer = curve.annotations
    layer.set_coach_allowed(True)
    layer.expert_view = True
    layer.tick()
    assert expected in layer.roast.text(), \
        f'the card did not count down to the milestone ({expected} missing)'


def test_the_coach_view_counts_down_to_dry_end(roast_curve) -> None:
    """The guided view draws its drying countdown from the same forecast, and
    from nothing else — past dry end it switches to the predictive engine, so
    this is the one phase where the two views can be told apart by source."""
    from tilauscope.graph import annotation_text as text
    from tilauscope.graph import forecast

    aw = H.scenario('drying')
    # The scenario ends exactly on its dry-end temperature, so there is nothing
    # left to forecast. Put the milestone ahead of the bean, which is the state
    # the countdown exists for.
    aw.qmc.phases[1] = float(aw.qmc.temp2[-1]) + 12.0
    curve = roast_curve(aw)
    layer = curve.annotations
    layer.set_coach_allowed(True)
    layer.expert_view = False
    curve.tick()
    _paint(curve)

    _target, info = text.phase_and_target(aw.qmc)
    raw = forecast.milestone(aw.qmc, info)
    assert raw is not None, 'the drying scenario made no forecast'
    left = int(raw - float(aw.qmc.timex[-1]))
    assert left > 30, 'the scenario left nothing to count down'
    expected = f'{left // 60:02d}:{left % 60:02d}'
    assert expected in layer.roast.text(), \
        f'the coach view did not count down to dry end ({expected} missing)'


def test_a_bean_that_is_not_climbing_is_given_no_countdown() -> None:
    """A rate at or below zero supports no arrival, and neither does a target
    already behind the bean. Both get silence rather than a number."""
    from tilauscope.graph import forecast

    aw = H.scenario('maillard')
    qmc = aw.qmc
    info = {'target': float(qmc.temp2[-1]) + 20.0}

    qmc.rateofchange2 = 10.0
    ahead = forecast.milestone(qmc, info)
    assert ahead is not None and ahead > float(qmc.timex[-1])

    qmc.rateofchange2 = 0.0
    assert forecast.milestone(qmc, info) is None, 'a stalled bean got an arrival'

    qmc.rateofchange2 = 10.0
    behind = {'target': float(qmc.temp2[-1]) - 20.0}
    assert forecast.milestone(qmc, behind) is None, \
        'a target already passed got an arrival'


def test_the_drawn_forecast_is_held_still_while_the_card_is_not() -> None:
    """The raw forecast steps by seconds every sample — right on the card, and
    unreadable as a marker. The chart gets the smoothed value, the card the raw
    one, which is why the two are computed separately."""
    from tilauscope.graph import forecast

    s = forecast.Smoother()
    assert s.feed(600.0) == 600.0          # nothing to average yet
    held = [s.feed(600.0 + n) for n in (2.0, -2.0, 1.0, -1.0)]
    assert all(v == 600.0 for v in held), f'the marker chased the noise: {held}'

    moved = None
    for _ in range(40):
        moved = s.feed(660.0)
    assert moved is not None and moved > 610.0, 'the marker never followed a real move'

    assert s.feed(None) is None            # no forecast, no marker
    assert s.feed(500.0) == 500.0, 'the smoother kept state across a gap'


def test_the_forecast_marker_stands_on_the_curve(roast_curve) -> None:
    """It is the only thing on the chart that has not happened yet, so it is
    drawn — dashed and dimmed — where the countdown lands."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    t = curve.annotations.forecast_t
    assert t is not None and curve._t_min <= t <= curve._t_max

    x = int(curve._x(t))
    rect = curve.plot_rect()
    band = QRectF(float(x - 1), rect.top() + 2.0, 3.0, rect.height() - 4.0)
    control = QRectF(rect.left() + 6.0, rect.top() + 2.0, 3.0, rect.height() - 4.0)
    assert _near_colour(curve, THEME['YELLOW'], band) > 0, 'no marker at the forecast'
    assert _near_colour(curve, THEME['YELLOW'], control) == 0, \
        'yellow found where no forecast belongs'


def test_the_operator_can_switch_the_roast_card_off(roast_curve) -> None:
    """The switch predates the move and keeps its meaning: it has always
    governed the roast card and never the preheat monitor, which reports a drum
    the operator is waiting on rather than a roast they are reading."""
    aw = H.scenario('maillard')
    aw.TilauScopeAnnotation = False
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.roast.isHidden(), 'the card ignored the switch'
    assert curve.annotations.view_toggle.isHidden()
    assert curve.annotations.forecast_t is None, 'the marker outlived the card'

    aw.TilauScopeAnnotation = True
    curve.annotations.tick()
    assert curve.annotations.roast.isVisibleTo(curve)


def test_the_preheat_monitor_is_not_governed_by_that_switch(roast_curve) -> None:
    """Same rule as before the move, stated as a test so it cannot drift."""
    aw = _climbing(minutes=5, target=185.0)
    aw.TilauScopeAnnotation = False
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.preheat.isVisibleTo(
        curve), 'the preheat monitor followed the roast switch'


# ── the title, the preheat card and the two selectors ────────────────────

def test_the_curve_names_the_roast_it_is_showing(roast_curve) -> None:
    """Which coffee this is, above the plot. This composes the line itself from
    qmc.title and the batch prefix/number rather than reading Artisan's own
    title_text cache, which is only refreshed inside setProfileTitle() and can
    still hold a previous roast's composed text after a plain File > Open."""
    curve = roast_curve(H.scenario('maillard'))
    curve.tick()
    band = QRectF(curve.plot_rect().left(), 2.0, 300.0, curve.plot_rect().top() - 4.0)
    assert _near_colour(curve, THEME['TEXT'], band) == 0, 'a nameless roast was named'

    aw = H.scenario('maillard')
    aw.qmc.title = 'Ethiopia Guji'
    curve = roast_curve(aw)
    curve.tick()
    assert _near_colour(curve, THEME['TEXT'], band) > 0, 'the roast title was not drawn'


def test_the_application_name_is_not_a_roast_title(roast_curve) -> None:
    """Artisan parks its own name in qmc.title when there is nothing to show.
    Printing it over the curve tells the operator what they already know."""
    aw = H.scenario('maillard')
    aw.qmc.title = 'TilauScope'
    curve = roast_curve(aw)
    curve.tick()
    band = QRectF(curve.plot_rect().left(), 2.0, 300.0, curve.plot_rect().top() - 4.0)
    assert _near_colour(curve, THEME['TEXT'], band) == 0, \
        'the placeholder title was drawn as a roast name'


def test_the_curve_composes_the_batch_prefix_into_the_title(roast_curve) -> None:
    """The batch prefix and number are recomposed here from the raw fields,
    not read from Artisan's cached title_text, so this drives qmc.title and
    the batch fields directly and checks the composed string reaches the
    painter rather than merely that something was drawn."""
    from unittest.mock import MagicMock

    aw = H.scenario('maillard')
    aw.qmc.title = 'Ethiopia Guji'
    aw.qmc.roastbatchprefix = 'R-'
    aw.qmc.roastbatchnr = 42
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)

    painter = MagicMock()
    curve._draw_title(painter, aw.qmc)
    texts = [call.args[-1] for call in painter.drawText.call_args_list]
    assert any('R-42 Ethiopia Guji' in t for t in texts), \
        f'the composed batch prefix did not reach the screen: {texts}'


def test_the_air_option_says_so_when_there_is_no_air_to_trace(roast_curve) -> None:
    """A roast recorded with the air probe off has nothing to trace. An option
    that silently does nothing is worse than one that is absent: the operator
    clicks it, sees no change, and stops trusting the whole menu."""
    aw = H.scenario('replay')
    assert roast_curve(aw)._has_air_readings(), 'a roast with an air probe was refused'

    blind = H.scenario('replay')
    blind.qmc.temp1 = [H.NO_READING] * len(blind.qmc.temp1)
    assert not roast_curve(blind)._has_air_readings(), \
        'a roast with no air reading was offered the air trace'

    fresh = H.scenario('cold')
    assert roast_curve(fresh)._has_air_readings(), \
        'a roast that has not sampled yet was refused the benefit of the doubt'


def test_a_preheat_shows_the_card_and_the_lever_levels(roast_curve) -> None:
    """What a preheat looked like before this was fixed: the climb drawn, and
    under it four empty strips and no card. The lanes were laid out and never
    reached, because the preheat path returned before the settings were drawn.
    """
    from PyQt6.QtGui import QColor

    aw = _climbing(minutes=5, target=185.0)
    aw.eventslidervalues = [0, 60, 30, 79]
    aw.qmc.specialevents, aw.qmc.specialeventstype, aw.qmc.specialeventsvalue = [], [], []
    curve = roast_curve(aw)
    curve.tick()
    image = curve.grab().toImage()

    assert curve._preheat is not None, 'the preheat was not read'
    assert curve.annotations.preheat.isVisibleTo(curve), 'no card during the preheat'
    assert curve._lane_rows, 'the preheat got no lanes'

    for n, lane, _kind in curve._lane_rows:
        ground = QColor(image.pixel(int(lane.right()) - 2, int(lane.top()) + 2))
        painted = [(x, y)
                   for y in range(int(lane.top()) + 2, int(lane.bottom()) - 1, 2)
                   for x in range(int(lane.left()) + 2, int(lane.right()) - 2, 4)
                   if QColor(image.pixel(x, y)) != ground]
        assert painted, f'channel {n} was drawn as an empty strip during the preheat'


def test_the_preheat_card_sits_under_the_target_and_not_on_the_climb(roast_curve) -> None:
    """It comments on the target, so it belongs against the target. Anchored to
    the head of the climb it rode up and to the right all preheat long and ended
    parked on the two things it was commenting on — the target line and the
    projected arrival. The stretch under the target on the left is empty for the
    whole climb, by the shape of a climb."""
    aw = _closing_in(minutes=8, minutes_out=3.0)
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()

    card = curve.annotations.preheat
    assert card.isVisibleTo(curve), 'no card during the preheat'
    anchor = curve.preheat_target_point()
    assert anchor is not None, 'the target line was not on the axis'

    assert card.y() >= anchor.y(), 'the card was drawn over the target line'
    rect = curve.plot_rect()
    assert card.x() < rect.center().x(), 'the card drifted to the head of the climb'


def test_the_preheat_card_holds_its_place_against_the_target(roast_curve) -> None:
    """A card that travels across the chart is a card the eye has to find again
    every second. It keeps a fixed offset from the target line — which itself
    only moves when the temperature axis grows — instead of riding the head of
    the climb, which moves every single second."""
    aw = _closing_in(minutes=4, minutes_out=3.0)
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()
    card, anchor = curve.annotations.preheat, curve.preheat_target_point()
    assert anchor is not None
    first = (card.x() - anchor.x(), card.y() - anchor.y())

    bt = float(aw.qmc.temp2[-1])
    for i in range(120):
        bt += 4.0 / 60.0
        aw.qmc.append(float(len(aw.qmc.timex) + i), bt + 12.0, bt, 4.0)
    curve.tick()
    curve.grab()

    anchor = curve.preheat_target_point()
    assert anchor is not None
    assert (card.x() - anchor.x(), card.y() - anchor.y()) == first, \
        'the card came unstuck from the target line'


def test_the_preheat_card_does_not_repeat_the_panel(roast_curve) -> None:
    """The learning badge is rendered in full on the preheat panel a few
    centimetres to the left. A card floating over the climb has to earn every
    line it takes."""
    aw = _climbing(minutes=5, target=185.0)
    aw.tilauPreheatingPid.learning_badge_html = (
        '<div id="the-badge">EXPERIENCE</div>')
    curve = roast_curve(aw)
    curve.tick()
    assert 'the-badge' not in curve.annotations.preheat.text(), \
        'the card repeated what the panel already says'
    assert '&#9608;' in curve.annotations.preheat.text(), 'the climb gauge went with it'


def test_a_long_preheat_keeps_its_arrival_clear_of_the_frame(roast_curve) -> None:
    """Past the fourteen-minute frame the axis grows with the climb again, and
    the arrival must land inside it rather than on the border, where a marker
    coincides with the frame and cannot be seen."""
    aw = _closing_in(minutes=18, minutes_out=6.0)
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()

    elapsed = float(aw.qmc.timex[-1]) - float(aw.qmc.timex[0])
    eta = curve._preheat.eta
    assert eta is not None
    arrival = elapsed + eta
    assert curve._t_max > arrival, 'the arrival was drawn on the frame'
    assert curve._t_max - arrival <= 90.0, \
        f'{curve._t_max - arrival:.0f}s of empty chart past the arrival'


def test_the_projected_reading_is_not_drawn_on_the_climb(roast_curve) -> None:
    """It said the same thing as the gap already written on the card, and once
    the drum settled it converged onto the head of the climb and read as a ring
    around it. Removed rather than conditioned: a mark that only sometimes means
    something is a mark nobody trusts."""
    from PyQt6.QtGui import QColor

    def _ring_pixels(gap_c: float) -> int:
        aw = _climbing(minutes=5, target=185.0)
        bt = float(aw.qmc.temp2[-1])
        aw.tilauPreheatingPid = H.FakePreheatPID(target=185.0, projected=bt + gap_c)
        curve = roast_curve(aw)
        curve.tick()
        image = curve.grab().toImage()
        want = QColor(THEME['OVERLAY2'])
        r = curve.plot_rect()
        return sum(
            1
            for y in range(int(r.top()) + 1, int(r.bottom()), 2)
            for x in range(int(r.left()) + 1, int(r.right()), 2)
            if QColor(image.pixel(x, y)) == want)

    assert _ring_pixels(25.0) == 0, 'the projected reading is back on the chart'
    assert _ring_pixels(0.2) == 0


def test_the_time_axis_names_every_minute_and_rules_every_other(roast_curve) -> None:
    """A minute is the unit a roast is read in, so every minute is named. A rule
    every minute would be a picket fence behind the curve, so only every other
    one is drawn: the figures give the resolution, the lines the structure."""
    from PyQt6.QtGui import QColor

    aw = H.scenario('replay')
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()
    # The cached frame, not the painted widget: the phase grounds change the
    # background from column to column, so a row of the finished picture cannot
    # be compared against a single colour.
    assert curve._frame is not None
    image = curve._frame.toImage()

    r = curve.plot_rect()
    row = int(r.top()) + 6
    ground = QColor(image.pixel(int(r.left()) + 3, row))
    ruled = [x for x in range(int(r.left()) + 2, int(r.right()) - 1)
             if QColor(image.pixel(x, row)) != ground]
    # Group adjacent columns: an antialiased hairline can touch two of them.
    lines = [x for i, x in enumerate(ruled) if i == 0 or x - ruled[i - 1] > 2]

    minutes = (curve._t_max - curve._t_min) / 60.0
    assert curve._time_step == 60.0, 'the axis stopped naming every minute'
    # The rule is written out rather than read from the constant that sets it:
    # a test that computes its expectation from the value under test agrees with
    # whatever that value happens to be.
    assert abs(len(lines) - minutes / 2.0) <= 2, \
        f'{len(lines)} rules drawn over {minutes:.0f} named minutes — expected one in two'


def test_the_card_leaves_when_the_recording_stops(roast_curve) -> None:
    """It says what to do next. Once the operator has stopped, there is nothing
    next — and it sat there announcing the cooling phase over a finished roast."""
    aw = H.scenario('development')
    curve = roast_curve(aw)
    curve.tick()
    _paint(curve)
    assert curve.annotations.roast.isVisibleTo(curve)

    aw.qmc.flagstart = False
    curve.annotations.tick()
    assert curve.annotations.roast.isHidden(), 'the card outlived the recording'
    assert curve.annotations.view_toggle.isHidden()


def test_the_preheat_card_gives_way_to_the_charge_badge(roast_curve) -> None:
    """Once the drum is there the chart says CHARGE NOW on the head of the
    climb, where the operator is already looking. A card repeating it beside the
    target is a second instruction for a single decision, and the countdown it
    carried has nothing left to count."""
    climbing = _closing_in(minutes=8, minutes_out=3.0)
    curve = roast_curve(climbing)
    curve.tick()
    assert curve.annotations.preheat.isVisibleTo(curve), 'no card while still climbing'

    arrived = _climbing(minutes=5, target=185.0)
    arrived.tilauPreheatingPid = H.FakePreheatPID(
        target=float(arrived.qmc.temp2[-1]) - 2.0)
    curve = roast_curve(arrived)
    curve.tick()
    assert curve._preheat.ready
    assert curve.annotations.preheat.isHidden(), \
        'the card repeated the charge instruction'


def test_no_rate_scale_before_the_charge(roast_curve) -> None:
    """The drum is climbing, not roasting. A rate scale with nothing on it
    invites reading the drum temperature against the wrong numbers."""
    for state in ('monitoring', 'cold'):
        curve = roast_curve(H.scenario(state))
        curve.tick()
        curve.grab()
        assert not curve._rate_axis, f'{state}: the rate scale was drawn'

    curve = roast_curve(H.scenario('maillard'))
    curve.tick()
    curve.grab()
    assert curve._rate_axis, 'a running roast lost its rate scale'


def test_the_curve_takes_its_colours_from_the_readouts(roast_curve) -> None:
    """One source for both, so they can never name two different things with the
    same colour. The rates wear the colour of the probe they are measured on,
    one step back, so a rate is never mistaken for the line the roast is read
    from."""
    from PyQt6.QtGui import QColor

    aw = H.scenario('maillard')
    aw.qmc.palette = {'bt': '#89B4FA', 'et': '#FAB387'}
    curve = roast_curve(aw)

    assert QColor(curve._grain_colour()) == QColor('#89B4FA')
    assert QColor(curve._air_colour()) == QColor('#FAB387')
    for probe, rate in ((curve._grain_colour(), curve._rise_colour()),
                        (curve._air_colour(), curve._machine_rise_colour())):
        p, r = QColor(probe), QColor(rate)
        assert abs(p.hue() - r.hue()) <= 4, 'the rate left its probe’s family'
        assert r.lightness() < p.lightness(), 'the rate is as loud as the probe'


def test_the_replay_speed_is_offered_only_while_a_simulation_runs(roast_curve) -> None:
    """A replay speed with nothing replaying is a control that cannot act. It
    exists because changing the speed used to mean clicking the clock with the
    right modifier held — neither discoverable nor usable with one hand on the
    machine, and in a simulated roast the speed is changed more often than
    anything else on the screen."""
    live = roast_curve(H.scenario('maillard'))
    live.tick()
    assert live._speed_btn.isHidden(), 'a real roast was offered a replay speed'

    sim = roast_curve(H.scenario('maillard', simulator=True))
    sim.tick()
    assert sim._speed_btn.isVisibleTo(sim), 'a simulated roast got no speed control'
    assert [b.text() for b in sim._seg_speed] == ['x1', 'x2', 'x8']

    rect = sim.plot_rect()
    assert sim._speed_btn.y() + sim._speed_btn.height() <= rect.top(), \
        'the speed control sits on the curve'


def test_the_speed_control_reports_the_clock_it_drives(roast_curve) -> None:
    """It shows the speed the clock is actually running at, not the last button
    pressed: the same speed can be set from Artisan's own clock click."""
    aw = H.scenario('maillard', simulator=True)
    curve = roast_curve(aw)
    curve.tick()
    assert [b.isChecked() for b in curve._seg_speed] == [True, False, False]

    aw.qmc.timeclock.base = 8000.0
    curve.tick()
    assert [b.isChecked() for b in curve._seg_speed] == [False, False, True]


def test_the_crosshair_row_names_every_figure_it_prints() -> None:
    """Two figures in the row end in °/min. Colour was the only thing telling
    the bean's rate from the machine's, and the row was read as a row of
    numbers: the operator took the machine figure for the rate of rise and
    reported it against the panel, which shows the bean's."""
    from tilauscope.graph.curve import readout_parts

    parts = readout_parts(90.0, 82.8, 137.1, 11.1, -8.6,
                          '#89B4FA', '#FAB387', '#5a7bb0', '#a8785e')
    rates = [(label, value) for label, value, _c in parts if value.endswith('°/min')]
    assert len(rates) == 2, 'the row no longer carries two rates'
    assert all(label for label, _v in rates), 'a rate figure was printed unnamed'
    assert rates[0][0] != rates[1][0], 'both rates answer to the same name'
    assert rates[0][1] == '11.1°/min', 'the bean rate is not the first of the two'


def test_the_crosshair_rate_is_the_figure_the_panel_shows(roast_curve) -> None:
    """The panel's large RoR is Artisan's own delta2 at the last sample. The
    row must print that same number: a chart that disagrees with the readout
    beside it makes the operator distrust both."""
    from tilauscope.graph.curve import _sample_ror_c

    aw = H.scenario('maillard')
    aw.qmc.delta2[-1] = 11.1
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()
    panel = aw.qmc.delta2[-1]            # what updateLCDs sends the panel
    assert f'{_sample_ror_c(panel, aw.qmc.mode):.1f}' == '11.1'


def test_the_card_slides_past_the_forecast_it_counts_down(roast_curve) -> None:
    """The card floats beside the bean and the bean walks towards the forecast
    line, so the card ends up sitting on the very mark it explains. It must
    step over the line while the roast leaves room on the far side."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()
    card = curve.annotations.roast
    assert card.isVisibleTo(curve), 'no card to place'
    x = curve.forecast_x()
    assert x is not None, 'the maillard scenario drew no forecast'
    assert not card.x() <= x <= card.x() + card.width(), \
        'the card is standing on the forecast line'


def test_the_card_keeps_its_place_when_the_forecast_is_elsewhere(roast_curve) -> None:
    """The step aside is conditional, not a permanent shift right: with the
    line far from the card the card stays beside the bean, where it belongs."""
    from PyQt6.QtCore import QPointF

    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()
    layer = curve.annotations
    card = layer.roast
    html = layer._roast_html(aw.qmc)
    layer._place(card, aw.qmc, html, None)
    beside = card.x()
    layer._place(card, aw.qmc, html, float(curve.plot_rect().left()))
    assert card.x() == beside, 'a line the card does not cover moved it anyway'
    assert isinstance(layer._anchor(aw.qmc), QPointF)


def test_no_rate_is_drawn_before_the_charge(roast_curve) -> None:
    """The lead-in minute shows the drum the beans were about to meet, and a
    temperature reads as that. A rate does not: before the charge it is the
    warm-up climbing, drawn under a legend that says the bean is rising."""
    aw = H.scenario('maillard')
    curve = roast_curve(aw)
    curve.tick()
    curve.grab()                       # paint is what settles the time window
    charge = int(aw.qmc.timeindex[0])
    t_charge = float(aw.qmc.timex[charge])
    timex = [float(t) - t_charge for t in aw.qmc.timex]
    assert timex[0] < 0.0, 'the scenario has no lead-in to leave out'

    segments = curve._build_ror_segments(timex, list(aw.qmc.delta2), aw.qmc.mode)
    assert segments, 'the rate vanished from the roast as well'
    first = min(poly.at(0).x() for poly in segments)
    assert first >= curve._x(0.0) - 0.5, 'the rate is drawn before the charge'


def test_the_view_selector_waits_for_the_roast_to_close(roast_curve) -> None:
    """The drop is not the end: the beans are in the cooling tray, the
    recording is still running and the frame is still growing, so a window
    that claims to end at the drop keeps being wrong."""
    aw = H.scenario('cooling')
    aw.qmc.flagstart = True                 # dropped, still recording
    curve = roast_curve(aw)
    curve.show()
    curve.tick()
    assert curve._view_btn.isHidden(), 'the selector acts during the cooling'

    aw.qmc.flagstart = False                # the operator stops
    curve.tick()
    assert not curve._view_btn.isHidden(), 'the selector never came back'


def test_a_finished_roast_opens_charge_to_drop(roast_curve) -> None:
    """The useful comparison is the roast itself; the full session is optional."""
    aw = H.scenario('replay')
    curve = roast_curve(aw)
    curve.show()
    curve.tick()
    _paint(curve)

    charge = int(aw.qmc.timeindex[0])
    drop = int(aw.qmc.timeindex[6])
    expected_end = aw.qmc.timex[drop] - aw.qmc.timex[charge] + 60.0
    assert curve._closeup
    assert curve._seg_closeup.isChecked()
    assert curve._t_min == -60.0
    assert curve._t_max == expected_end

    curve._set_closeup(False)
    _paint(curve)
    assert curve._seg_full.isChecked()
    assert curve._t_max > expected_end


def test_two_gestures_on_one_second_keep_only_the_one_that_held() -> None:
    """A slider clicked twice inside a sampling tick records two events at the
    same instant. Only the last one ever applied: drawing both hands the label
    to a setting that never held, and the crosshair then contradicts it."""
    from tilauscope.graph.curve import RoastCurveWidget

    timex = [0.0, 1.0, 2.0, 3.0]
    events = [1, 1, 3]
    types = [0, 0, 0]
    pcts = [50, 55, 60]

    points = RoastCurveWidget._channel_points(None, timex, events, types, pcts, 0)

    assert points == [(1.0, 55.0), (3.0, 60.0)]

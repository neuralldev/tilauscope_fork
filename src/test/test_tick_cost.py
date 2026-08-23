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

"""What one sample costs now that TilauScope draws the roast itself.

Artisan samples at 1 Hz and does everything it does inside that beat: read the
probes, update the readouts, fire the alarms, run the preheat PID. Whatever the
screen takes, it takes out of that. The substitution was justified on this
ground — the matplotlib figure was the expensive part of the beat and it is no
longer drawn — so the claim has to be measured rather than asserted.

Three separate questions, and they are not interchangeable:

*What the sampling thread pays.* ``tick()`` is what the 1 Hz signal calls. It
must stay flat in the length of the roast: a cost that grows with the arrays is
a screen that gets slower as the roast goes on, which is precisely backwards.

*What the paint pass costs.* Qt coalesces paints, so this is not paid once per
sample — but it is real work, and it is where the polylines are built.

*What was there before.* Artisan drew its figure on every one of those beats.
The reference below is matplotlib drawing the same roast at the same size: not
Artisan's canvas itself, which cannot be built without its application window,
but the same library doing the same job, which is what the figure was. It is
measured both ways, because Artisan uses both — a blit per sample, a full
redraw whenever the axes move — and quoting only the full redraw would flatter
the comparison.

That comparison is not symmetric and must not be read as a score. The blitted
reference re-renders four traces onto a restored background. This chart
re-renders everything above its cached frame: the phase grounds, the four
setting lanes, the milestone rules and chips, the legend, the crosshair. More
ink, drawn every frame, against four lines drawn over a photograph.

Timings are wall clock on a loaded developer machine. They are reported rather
than pinned: the assertions are on shape — flatness in the roast length, and a
budget loose enough that only a change of order trips it.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest
import roast_harness as H


def _median_ms(fn: Any, *, runs: int, warmup: int = 3) -> float:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def _roast(samples: int) -> Any:
    """A roast of `samples` seconds, charged, with the usual gestures on it.

    The bean has to end *inside* the temperature axis. Off it the card finds no
    anchor and is never placed — and a tick measured with no card on screen is
    a tick that measures the wrong thing. :func:`_card_is_up` is what stops that
    from passing unnoticed a second time.
    """
    aw = H.scenario('cold')
    qmc = aw.qmc
    qmc.flagon = qmc.flagstart = True
    for i in range(20):                       # pre-charge monitoring
        qmc.append(float(i), 205.0, 185.0, 0.0)
    qmc.timeindex[0] = len(qmc.timex)
    bt = 90.0
    step = (205.0 - 90.0) / max(1, samples)
    for i in range(samples):
        bt += step
        qmc.append(20.0 + i, bt + 25.0, bt, 12.0 - i * (8.0 / samples))
    qmc.timeindex[1] = qmc.timeindex[0] + int(samples * 0.45)
    if samples > 500:
        qmc.timeindex[2] = qmc.timeindex[0] + int(samples * 0.85)
    for n, at, value in ((H.BURNER, 0, 80), (H.AIR, 30, 40),
                         (H.BURNER, int(samples * 0.5), 62),
                         (H.AIR, int(samples * 0.7), 55)):
        qmc.add_event(qmc.timeindex[0] + at, n, value)
    return aw


def _preheating(samples: int) -> Any:
    """A drum climbing to target — the state whose tick does read the arrays."""
    aw = H.scenario('cold')
    aw.qmc.flagon = aw.qmc.flagstart = True   # see _climbing in test_roast_curve
    bt = 22.0
    ror = 12.0
    for i in range(samples):
        ror = max(2.0, 14.0 * (1.0 - bt / 210.0))
        bt += ror / 60.0
        aw.qmc.append(float(i), bt + 12.0, bt, ror)
    aw.qmc.rateofchange2 = ror
    aw.tilauPreheatingPid = H.FakePreheatPID(target=185.0, projected=bt + 1.0)
    return aw


def _repaint(widget: Any) -> Any:
    """Render the widget into one reusable image, and return the callable.

    ``grab()`` allocates a fresh QPixmap per call; a real paint goes to a
    backing store that is already there. Timing the allocation as if it were
    drawing would make the chart look more expensive than it is.
    """
    from PyQt6.QtGui import QImage, QPainter

    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)

    def _once() -> None:
        painter = QPainter(image)
        widget.render(painter)
        painter.end()

    return _once


def _card_is_up(widget: Any) -> bool:
    """True when the roast card is actually on screen with text in it."""
    card = widget.annotations.roast
    return bool(card.isVisibleTo(widget) and len(card.text()) > 200)


@pytest.fixture
def curve(qapp: Any):
    built: list[Any] = []

    def _build(aw: Any) -> Any:
        from tilauscope.graph.common import reset_reports
        from tilauscope.graph.curve import RoastCurveWidget

        reset_reports()
        widget = RoastCurveWidget(aw)
        widget.resize(1180, 620)          # the size the roast screen gives it
        qapp.processEvents()
        built.append(widget)
        return widget

    yield _build

    for widget in built:
        widget.close()
        widget.deleteLater()
    qapp.processEvents()


def test_the_tick_does_not_grow_with_the_roast(curve) -> None:
    """The 1 Hz path must cost the same at the drop as at the charge.

    This is the one property that cannot be traded away. A tick that walks the
    arrays is a screen whose cost rises as the roast goes on — slowest exactly
    where the operator is busiest, and invisible until the machine is loaded.
    """
    short = curve(_roast(120))
    long_ = curve(_roast(1200))
    # Twice: the card is placed against the axis the previous paint settled,
    # so a window that has just opened costs one frame before the card lands.
    for widget in (short, long_):
        for _ in range(2):
            widget.tick()
            widget.grab()
    assert _card_is_up(short) and _card_is_up(long_), \
        'no card on screen — the tick being timed is not the one that runs'

    t_short = _median_ms(short.tick, runs=200)
    t_long = _median_ms(long_.tick, runs=200)
    print(f'\n  tick   120 samples : {t_short:6.3f} ms'
          f'\n  tick  1200 samples : {t_long:6.3f} ms')

    # Ten times the roast, and the cost must not follow. The margin is wide on
    # purpose: what is being refused is proportionality, not a few microseconds.
    assert t_long < max(t_short * 3.0, 0.5), (
        f'the tick grows with the roast: {t_short:.3f} ms at 120 samples, '
        f'{t_long:.3f} ms at 1200')


@pytest.mark.slow
def test_the_cost_of_one_sample_is_reported(curve) -> None:
    """What one sample costs, and what the figure it replaced cost.

    The budget is the beat: Artisan samples once a second, and everything the
    screen does has to fit inside that with room for the probes, the alarms and
    the preheat law. The assertions are that budget, not a race against
    matplotlib — see the module docstring for why that race would not be fair.
    """
    roast = curve(_roast(700))                       # a 12-minute roast
    for _ in range(2):
        roast.tick()
        roast.grab()
    assert _card_is_up(roast), \
        'no card on screen — the tick being timed is not the one that runs'

    tick_ms = _median_ms(roast.tick, runs=200)
    paint_ms = _median_ms(_repaint(roast), runs=40)
    grab_ms = _median_ms(roast.grab, runs=40)
    cards_ms = _median_ms(roast.annotations.tick, runs=200)

    preheat = curve(_preheating(1080))
    for _ in range(2):
        preheat.tick()
        preheat.grab()
    pre_tick_ms = _median_ms(preheat.tick, runs=200)

    full_ms, blit_ms = _matplotlib_reference_ms()

    print('\n'
          f'\n  a 12-minute roast, 700 samples, 1180x620'
          f'\n    tick()            {tick_ms:7.3f} ms   (called once per sample)'
          f'\n      of which cards  {cards_ms:7.3f} ms'
          f'\n    paint             {paint_ms:7.3f} ms   (coalesced by Qt)'
          f'\n      via grab()      {grab_ms:7.3f} ms   (with the pixmap allocation)'
          f'\n  a preheat climbing, 1080 samples'
          f'\n    tick()            {pre_tick_ms:7.3f} ms'
          f'\n  the figure this replaced, same data and same size'
          f'\n    full redraw       {full_ms:7.3f} ms   (axes, ticks, labels)'
          f'\n    blitted traces    {blit_ms:7.3f} ms   (the live path)'
          f'\n')

    # The 1 Hz path: two orders of magnitude under the beat, so that a machine
    # ten times slower than this one is still nowhere near it.
    assert tick_ms < 5.0, f'the 1 Hz path costs {tick_ms:.3f} ms'
    assert pre_tick_ms < 5.0, f'the preheat tick costs {pre_tick_ms:.3f} ms'
    # The paint is coalesced, so it is paid about once per sample too.
    assert paint_ms < 50.0, f'a frame costs {paint_ms:.1f} ms of a 1000 ms beat'
    assert blit_ms > 0.0 and full_ms > 0.0


def _matplotlib_reference_ms() -> tuple[float, float]:
    """What one redraw of the same roast costs matplotlib, both ways.

    Not Artisan's canvas — that needs its application window, which the suite
    must never build. This is the same library drawing the same four traces at
    the same pixel size, which is what the figure Artisan redrew per sample was.

    Two figures, because Artisan uses two paths and quoting only one would
    flatter the comparison. Per sample it blits: the background is restored
    from a cached region and only the traces are re-rendered. It falls back to
    the full redraw whenever the axes move — which, on a roast that outgrows
    its window, is regularly.
    """
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    n = 1200
    xs = list(range(n))
    bt = [90.0 + i * 0.14 for i in range(n)]
    et = [t + 25.0 for t in bt]
    d_bt = [12.0 - i * 0.004 for i in range(n)]
    d_et = [10.0 - i * 0.003 for i in range(n)]

    fig = Figure(figsize=(11.8, 6.2), dpi=100)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.grid(True)
    ax.plot(xs, bt)
    ax.plot(xs, et)
    twin = ax.twinx()
    twin.plot(xs, d_bt)
    twin.plot(xs, d_et)

    def _full() -> None:
        canvas.draw()

    full = _median_ms(_full, runs=15, warmup=2)

    canvas.draw()
    background = canvas.copy_from_bbox(ax.bbox)
    artists = [*ax.get_lines(), *twin.get_lines()]

    def _blit() -> None:
        canvas.restore_region(background)
        for artist in artists:
            ax.draw_artist(artist)
        canvas.blit(ax.bbox)

    return full, _median_ms(_blit, runs=30, warmup=2)

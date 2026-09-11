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

"""What the preheat controller knows, in the four numbers a band can hold.

While TilauPID ramps the drum, the two forward-looking slots of the second
band answer a different pair of questions from the ones a roast asks. Not
which phase and which milestone — there is no roast yet — but what the drum is
being taken to, and when it will be there.

The projected temperature is the one that matters: it is the quantity the
control law actually steers on, and reading it is what explains a burner that
tapers while the drum is still short of target. It is read from the PID rather
than recomputed here, so the screen can never show a projection the law did
not use.

The full account of the preheat — where the learned hold power and the lead
come from, how much history is behind them — belongs to the Roasting screen's
own face. This is the live pair, on the screen the operator is already on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from artisanlib.util import convertTemp
from tilauscope.graph.common import delta_scale, within_share
from tilauscope.tilauscope_types import THEME

#: Past this a projection has stopped meaning anything — the rate is near zero
#: and the arithmetic runs away. It is deliberately generous: a drum taken from
#: cold to 200° is a twenty-minute climb, and refusing to count it down leaves
#: the operator watching a screen that says 'still settling' for half a preheat.
#: The figure is honest about being drawn from the rate of the moment; early on
#: that rate is still building, so the estimate starts long and comes in.
_ETA_CAP_S: Final[float] = 45 * 60.0

#: Inside this share of the target the drum counts as arrived. Every other
#: approach band in TilauScope uses the same share, and the four must not
#: disagree — hence the shared `within_share`, which judges it in °C.
_CLOSE_SHARE: Final[float] = 0.05

#: Below this the approach has started; above it the drum is still far out.
#: A gap in °C, scaled to what the operator reads.
_NEAR_DEGREES_C: Final[float] = 15.0


@dataclass(frozen=True)
class PreheatReading:
    """One glance at the ramp. `eta` is None whenever no honest one exists."""

    target: float
    projected: float | None
    eta: float | None
    ready: bool
    colour: str
    #: The same two figures in °C, for the axis — which is drawn in °C
    #: whatever the operator reads in.
    target_c: float = 0.0
    projected_c: float | None = None


def reading(aw: Any) -> PreheatReading | None:
    """The live preheat pair, or None when no preheat is running."""
    pid = getattr(aw, 'tilauPreheatingPid', None)
    if pid is None or not getattr(pid, 'active', False):
        return None
    try:
        target = float(pid.sv_native())
    except (AttributeError, TypeError, ValueError):
        return None
    if target <= 0:
        return None

    qmc = getattr(aw, 'qmc', None)
    mode = getattr(qmc, 'mode', 'C')
    target_c = convertTemp(target, mode, 'C')
    actual = _probe_reading(aw, qmc)
    if actual is None:
        return PreheatReading(target, None, None, False, THEME['ACCENT'],
                              target_c=target_c)

    delta = target - actual
    ready = delta <= 0 or within_share(delta, target, _CLOSE_SHARE, mode)
    if ready:
        colour = THEME['SUCCESS']
    elif abs(delta) < _NEAR_DEGREES_C * delta_scale(mode):
        colour = THEME['YELLOW']
    else:
        colour = THEME['ACCENT']

    projected = _projected(pid, qmc, actual)
    return PreheatReading(
        target, projected, None if ready else _eta(delta, rate(aw, qmc)), ready, colour,
        target_c=target_c,
        projected_c=None if projected is None else convertTemp(projected, mode, 'C'))


def _on_bean(aw: Any) -> bool:
    """Which probe the law is fed with — the same choice `sample()` makes."""
    try:
        return aw.pidcontrol.pidSource in (0, 1)
    except (AttributeError, TypeError):
        return True


def _probe_reading(aw: Any, qmc: Any) -> float | None:
    try:
        series = qmc.temp2 if _on_bean(aw) else qmc.temp1
        last = float(series[-1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    return None if last <= -1 else last


def rate(aw: Any, qmc: Any = None) -> float | None:
    """The rate the countdown is drawn from, and the one the band shows with it.

    `rateofchange1/2` and not `delta1/2`: the displayed rise is clipped to None
    outside a band sized for a roast, which an aggressive ramp leaves routinely.
    """
    if qmc is None:
        qmc = getattr(aw, 'qmc', None)
    try:
        held = qmc.rateofchange2 if _on_bean(aw) else qmc.rateofchange1
        return None if held is None else float(held)
    except (AttributeError, TypeError, ValueError):
        return None


def _projected(pid: Any, qmc: Any, actual: float) -> float | None:
    """Where the law expects the drum to be once its own lag has played out.

    Read from the controller in its own unit, never recomputed here: the
    projection is what explains a burner tapering short of target, and a
    second implementation would eventually show one the law did not use.
    """
    held = getattr(pid, 't_proj_c', None)
    if held is None:
        return None
    try:
        # The law works in °C throughout; this is the single conversion to
        # whatever unit the screen is reading in.
        projected = convertTemp(float(held), 'C', getattr(qmc, 'mode', 'C'))
    except (TypeError, ValueError):
        return None
    # A projection more than a probe-length away from the reading is a stale
    # one — the law has not run since the drum moved.
    unit_span = 90.0 if getattr(qmc, 'mode', 'C') == 'F' else 50.0
    return projected if abs(projected - actual) <= unit_span else None


def _eta(delta: float, rate: float | None) -> float | None:
    """Seconds to the target, or None when the climb does not support one.

    A tapering burner lets the rate sag well before the close band is reached;
    that is the anticipation working, not a stall, so it gets no number rather
    than a frozen one.
    """
    if rate is None or rate <= 0 or delta <= 0:
        return None
    seconds = delta / rate * 60.0
    return seconds if seconds <= _ETA_CAP_S else None

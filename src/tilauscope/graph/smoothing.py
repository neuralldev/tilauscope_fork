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

"""Three rate-of-rise smoothing levels, in place of five separate numbers.

Artisan exposes the span, two filter widths and a curve filter, each on its own
scale, none of them saying what it costs. What the operator actually chooses is
one thing: how much lag to accept in exchange for how steady a reading.

The three levels were bounded by measurement on the reference corpus rather
than picked for roundness. Two facts set the window:

*Below about 10 seconds of span the ordinary roast reads as a crash.* The
steepest fall an untroubled roast shows over 15 s rises to 3.9 °C/min at a 5 s
span — above the 2.5–3 °C/min that defines a crash. Every roast would look like
it was collapsing.

*Above about 25 seconds a real crash is flattened into the ordinary.* The same
measure falls to 1.45 at 30 s, so a genuine collapse no longer stands out from
the noise of a roast that is behaving.

The peak rate of rise barely moves across the whole range (16.6 to 15.5), which
is what makes this safe to expose: changing level does not rewrite what the
plan has learned from past roasts.

The bean curve's own smoothing is deliberately left alone. It is a different
question — how the temperature reads, not how its rate reads — and folding it
in here would change the curve while the operator thought they were changing
the rate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from PyQt6.QtWidgets import QApplication

from tilauscope.graph.common import report_once, reset_rise_cache

_log: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True)
class Level:
    """One smoothing choice. `span` is the seconds a single rate value is
    measured over; `ror_filter` the width of the average run over the result."""

    key: str
    span: int
    ror_filter: int

    @property
    def lag(self) -> float:
        """Seconds the reading trails the bean by: half the span, plus half the
        filter. Immaterial for steering — a burner gesture cannot be judged
        before 60 to 90 seconds — but it is what the choice actually costs."""
        return self.span / 2 + (self.ror_filter - 1) / 2


LEVELS: Final[tuple[Level, ...]] = (
    Level('responsive', 10, 5),
    Level('standard', 15, 7),
    Level('smooth', 25, 9),
)

#: The level a roaster who has chosen nothing gets. It is also what the
#: reference machine already ran, so adopting these levels changes nothing for
#: the roasts already on file.
DEFAULT: Final[str] = 'standard'


def label(level: Level) -> str:
    """Menu text: the name, then the span, because the span is the choice.

    One literal per level — the extractor only sees literal arguments, so a
    table walked in a loop would ship three untranslatable names.
    """
    if level.key == 'responsive':
        name = QApplication.translate('tilauscope', 'Responsive')
    elif level.key == 'standard':
        name = QApplication.translate('tilauscope', 'Standard')
    else:
        name = QApplication.translate('tilauscope', 'Smooth')
    return f'{name}  ·  {level.span} s'


def current(qmc: Any) -> str:
    """Which level the canvas is set to, or '' for anything else.

    An operator who set their own numbers in Artisan's own dialog sees no level
    ticked, rather than the nearest one — which would claim a choice they did
    not make.
    """
    try:
        span = int(qmc.deltaBTspan)
        width = int(qmc.deltaBTfilter)
    except (AttributeError, TypeError, ValueError):
        return ''
    for level in LEVELS:
        if level.span == span and level.ror_filter == width:
            return level.key
    return ''


def apply_level(qmc: Any, key: str) -> bool:
    """Set the canvas to a level. True when it took.

    Both probes get the same span. They answer the same question about two
    thermometers, and leaving them apart is how one trace ends up lagging the
    other for no reason the operator can see.
    """
    level = next((one for one in LEVELS if one.key == key), None)
    if level is None:
        return False
    try:
        qmc.deltaBTspan = level.span
        qmc.deltaETspan = level.span
        qmc.deltaBTfilter = level.ror_filter
        qmc.deltaETfilter = level.ror_filter
        # The span is in seconds; the number of samples it covers depends on the
        # sampling interval, and Artisan derives one from the other.
        qmc.updateDeltaSamples()
    except (AttributeError, TypeError, ValueError):
        report_once('smoothing: could not apply the level')
        return False

    reset_rise_cache()
    # A finished roast has to be recomputed to show the change; a running one
    # must not be touched — its rate is being measured sample by sample, and
    # clearing it would throw away the roast so far.
    if not getattr(qmc, 'flagstart', False):
        try:
            qmc.delta1 = []
            qmc.delta2 = []
        except AttributeError:
            report_once('smoothing: could not clear the rate arrays')
    return True

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

"""What the curve engine needs that is not drawing.

Reading Artisan's arrays, ordering the machine channels, formatting a clock or
a temperature, reporting a guard once rather than every frame. Kept apart from
the widget so a rule about *what a roast is* — an unmarked milestone, a rate
Artisan already holds, a missing reading — is stated once and read the same way
by the chart, the cards and their text.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

from PyQt6.QtGui import QColor

from tilauscope.tilauscope_types import THEME

_log: Final[logging.Logger] = logging.getLogger(__name__)

# An unknown value is written, never blanked: an empty slot reads as a broken
# screen, a dash reads as "not known yet". Same glyph everywhere.
DASH: Final[str] = '—'


# Artisan numbers its event sliders Air=0, Drum=1, Damper=2, Burner=3 — a device
# ordering, not a roasting one. On screen the channels are ranked by how much
# each lever writes the roast: the burner decides it, the air supports it, the
# rest are set once and left alone.
_LEVER_PRIORITY: Final[tuple[int, ...]] = (3, 0)


def channel_order(visible: object) -> list[int]:
    """Visible machine channels, most decisive lever first.

    One definition for the whole screen: the settings lanes and the control
    band must not disagree about where a channel sits.
    """
    if visible is None:
        return []
    try:
        present = [n for n in range(4) if visible[n]]      # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        # Not a four-slot sequence: no channels rather than a wrong guess.
        return []
    ranked = [n for n in _LEVER_PRIORITY if n in present]
    return ranked + [n for n in present if n not in ranked]


# ── reading the roast ────────────────────────────────────────────────────
#
# The functions below are the only place in this package that decides what the
# roast state *is*. They were four copies once, one per screen element, and four
# copies of the sentinel rule below is four chances to fix it in three places
# and ship the fourth.

#: Index of the DROP entry in Artisan's `timeindex`.
DROP: Final[int] = 6


#: A share of an ABSOLUTE reading is not a physical band unless it is judged in
#: °C: the two scales share no origin, so 5 % of 392 °F is 10.9 °C where 5 % of
#: 200 °C is 10. Every approach band in TilauScope goes through `within_share`.
def delta_scale(mode: str) -> float:
    """Factor turning a °C difference or rate into the display unit."""
    return 1.8 if mode == 'F' else 1.0


def within_share(delta: float, target: float, share: float, mode: str = 'C') -> bool:
    """True when `delta` is inside `share` of `target`, both in display unit.

    The judgement is made in the °C frame so an operator reading °F gets the
    same physical band, not a wider one.
    """
    try:
        if target <= 0.0:
            return False
        target_c = (target - 32.0) / 1.8 if mode == 'F' else target
        return abs(delta) / delta_scale(mode) <= share * target_c
    except (TypeError, ValueError):
        return False


def marked(timeindex: Any, i: int) -> bool:
    """True if milestone `i` has been placed.

    The "unmarked" sentinel is mode-dependent and this is the trap the whole
    package walks past: index 0 reads -1 when unset in every mode, but indices
    1..7 read -1 in a real roast and 0 in the simulator. One test, used
    everywhere, keeps the two modes from disagreeing about what marked means.
    """
    try:
        if i == 0:
            return int(timeindex[0]) > -1
        return int(timeindex[i]) > 0
    except (TypeError, IndexError, ValueError):
        return False


def _is_alarm(text: str) -> bool:
    """Artisan writes 'A<n> (S<k>)' for a slider moved by alarm <n>."""
    return (len(text) > 1 and text[0] == 'A' and text[1].isdigit()
            and text.endswith(')') and '(S' in text)


def _is_preheat_command(text: str) -> bool:
    """The preheat controller writes 'S<n>:<power>%', where a gesture on the
    same channel writes Artisan's plain value and unit."""
    return text.startswith('S') and ':' in text and text.endswith('%')


# ── guards that stay honest ──────────────────────────────────────────────

_reported: set[str] = set()


def report_once(where: str) -> None:
    """Log the exception currently being handled, the first time `where` sees one.

    Every band guards its tick so nothing can raise into Artisan's sampling
    loop — right, and also how a band stays broken for a week while still
    looking like a band. Logging makes the defect visible; logging *once* keeps
    a 1 Hz loop from burying the log in a minute.
    """
    if where in _reported:
        return
    _reported.add(where)
    _log.exception('%s', where)


def reset_reports() -> None:
    """Forget which sites have already reported. For tests: without it the
    first case to trip a guard would hide that guard from every later one."""
    _reported.clear()


def menu_qss() -> str:
    """Popup-menu style. The shared theme has no QMenu rule, so a context menu
    opened from the curve would come up in the platform's own colours —
    a white rectangle in the middle of a dark screen."""
    return (
        f"QMenu {{ background-color: {THEME['SURFACE']}; color: {THEME['TEXT']};"
        f" border: 1px solid {THEME['BORDER']}; border-radius: 4px; padding: 4px; }}"
        f"QMenu::item {{ padding: 5px 24px 5px 22px; border-radius: 3px; }}"
        f"QMenu::item:selected {{ background-color: {THEME['BORDER']}; }}"
        f"QMenu::item:disabled {{ color: {THEME['OVERLAY0']}; }}"
        f"QMenu::separator {{ height: 1px; background-color: {THEME['BORDER']};"
        f" margin: 4px 6px; }}"
        f"QMenu::indicator {{ width: 14px; height: 14px; left: 5px; }}")


def fmt_clock(seconds: float | None) -> str:
    """m:ss, negative-safe. None -> dash."""
    if seconds is None:
        return DASH
    total = int(round(seconds))
    sign = '-' if total < 0 else ''
    total = abs(total)
    return f'{sign}{total // 60}:{total % 60:02d}'


def fmt_temp(temp: float | None) -> str:
    """Whole degrees, no decimal — a tenth of a degree is noise at arm's length."""
    if temp is None:
        return DASH
    return f'{int(round(temp))}'


# ── the two measured figures ─────────────────────────────────────────────
#
# Colour and weight are the only numbers on this screen nobody computes: an
# instrument reads them, or they are simply absent. Both bands that show them
# read them through here, so the account and the measurement bar can never
# disagree about what was measured.


#: Artisan keeps the bean record's identity inside the free-text `beans` field.
#: Same shape BeanCave writes and reads.
_UUID_IN_BEANS: Final[re.Pattern[str]] = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')


# ── the rise, when Artisan has not computed it ───────────────────────────
#
# No profile on file carries the rate of rise: Artisan saves temperatures and
# recomputes the rest on load. That recompute is gated on ITS OWN display
# flags — with both DeltaET and DeltaBT unticked, a loaded roast comes back
# with empty delta arrays and perfectly good temperatures.
#
# TilauScope draws its own pixels, so a setting belonging to Artisan's figure
# must not decide whether the curve has a rise trace. Artisan's own function is used rather
# than a second implementation: a rise computed differently here would not be
# the one the corpus was built from. Nothing is written back into qmc — the
# parallel route stays additive.

_rise_cache: dict[str, Any] = {}


def _rise_key(qmc: Any) -> tuple[Any, ...] | None:
    try:
        timex = qmc.timex
        if not timex:
            return None
        # Array identity is deliberately part of the key. Profiles can have the
        # same length, time bounds and milestones while carrying entirely
        # different temperatures; Artisan replaces these arrays when loading a
        # profile. Identity keeps the paint-path lookup O(1), unlike hashing
        # thousands of samples on every frame.
        return (id(timex), id(qmc.stemp1), id(qmc.stemp2),
                len(timex), float(timex[0]), float(timex[-1]),
                int(qmc.timeindex[0]), int(qmc.timeindex[DROP]))
    except (AttributeError, TypeError, IndexError, ValueError):
        return None


def rise_series(qmc: Any, *, machine: bool = False) -> list[Any]:
    """Rate of rise for the bean, or for the machine when `machine` is set.

    Returns whatever Artisan already holds. Only a loaded roast whose deltas
    were never computed reaches the recompute, and the result is cached: this
    is read from a paint path.
    """
    try:
        held = qmc.delta1 if machine else qmc.delta2
    except AttributeError:
        return []
    if held:
        return list(held)

    key = _rise_key(qmc)
    if key is None:
        return []
    cached = _rise_cache.get('key')
    # The structural key alone cannot distinguish two qmc instances holding
    # profiles with identical time geometry. Keep the owner itself (not only
    # id(qmc), which Python may reuse after collection) as part of the match.
    if _rise_cache.get('owner') is not qmc or cached != key:
        _rise_cache.clear()
        _rise_cache['owner'] = qmc
        _rise_cache['key'] = key
        try:
            d1, d2 = qmc.recomputeDeltas(
                qmc.timex,
                int(qmc.timeindex[0]) if marked(qmc.timeindex, 0) else -1,
                int(qmc.timeindex[DROP]) if marked(qmc.timeindex, DROP) else 0,
                qmc.stemp1, qmc.stemp2)
            _rise_cache['delta1'] = list(d1 or [])
            _rise_cache['delta2'] = list(d2 or [])
        except Exception:
            report_once('common.rise_series: recompute failed')
            _rise_cache['delta1'] = []
            _rise_cache['delta2'] = []
    return list(_rise_cache.get('delta1' if machine else 'delta2', []))


def reset_rise_cache() -> None:
    """Forget the recomputed rise. For tests, and for a change of roast that
    somehow keeps the same shape."""
    _rise_cache.clear()

def dimmed(colour: str, fallback: str) -> str:
    """The same hue, one step back.

    A rate belongs to the probe it is measured on, so it wears that probe's
    colour rather than one of its own — but it must never be mistaken for the
    temperature itself, which is the line the roast is read from. Darker and a
    little less saturated does both: same family at a glance, clearly the
    quieter member of it.
    """
    c = QColor(colour)
    if not c.isValid():
        c = QColor(fallback)
    h, sat, light, alpha = c.getHsl()
    return QColor.fromHsl(h, int(sat * 0.72), int(light * 0.74), alpha).name()

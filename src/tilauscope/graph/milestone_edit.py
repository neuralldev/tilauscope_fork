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

"""Correcting a milestone on a roast that is no longer running.

Where a milestone may go, the one transaction that writes it into Artisan's
profile, and the dialog for typing its instant. Nothing here acts while Artisan
monitors or records: a correction rewrites a roast's history, it never marks a
roast in progress — no machine command, alarm, assistant, batch number or
upload follows from it.

The rules are an order of placement, not a list of prerequisites:
CHARGE < DRY END < FC START < FC END < SC START < SC END < DROP < COOL END.
Only milestones actually present bound one another, and no temperature, rate or
duration decides what the operator observed.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass
from typing import Any, Final

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QVBoxLayout, QWidget)

from artisanlib.util import is_proper_temp
from tilauscope.graph.common import fmt_clock, marked, normalize_timeindex, report_once
from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import THEME

#: Artisan's timeindex slots used by name here.
CHARGE: Final[int] = 0
DRY_END: Final[int] = 1
FC_START: Final[int] = 2
DROP: Final[int] = 6
SLOTS: Final[int] = 8
#: Artisan's label-position cache key for the turning point.
_TP_KEY: Final[int] = -1

_CLOCK: Final[re.Pattern[str]] = re.compile(r'^\s*([+-]?)\s*(\d{1,3})\s*:\s*(\d{1,2})\s*$')


@dataclass(frozen=True)
class Profile:
    """The foreground profile as it stood when a gesture began."""

    timex: tuple[float, ...]
    timeindex: tuple[int, ...]
    #: Artisan's own time list, held so the same profile is recognised later.
    source: Any
    cur_file: Any


@dataclass(frozen=True)
class Proposal:
    """Where a dragged milestone would land."""

    index: int
    #: The neighbouring milestone holding it back, when one is.
    limit: int | None = None


# ── reading ──────────────────────────────────────────────────────────────

def idle(qmc: Any) -> bool:
    """True when Artisan neither monitors nor records."""
    return not getattr(qmc, 'flagon', False) and not getattr(qmc, 'flagstart', False)


def read_profile(aw: Any) -> Profile | None:
    """The foreground profile, or None when its time axis cannot carry a mark."""
    qmc = getattr(aw, 'qmc', None)
    try:
        source = qmc.timex
        times = tuple(float(t) for t in source)
        timeindex = tuple(normalize_timeindex(qmc.timeindex))
    except (AttributeError, TypeError, ValueError):
        return None
    if not times or not all(map(math.isfinite, times)):
        return None
    if any(later < earlier for earlier, later in zip(times, times[1:], strict=False)):
        return None
    return Profile(times, timeindex, source, getattr(aw, 'curFile', None))


def still_current(aw: Any, profile: Profile) -> bool:
    """Whether Artisan still holds, idle and unchanged, the profile a gesture began on.

    The instants themselves are compared, last and in full: Artisan rewrites its
    time list in place, keeping both its identity and its length.
    """
    qmc = getattr(aw, 'qmc', None)
    try:
        return bool(qmc is not None and idle(qmc)
                    and qmc.timex is profile.source
                    and len(qmc.timex) == len(profile.timex)
                    and tuple(normalize_timeindex(qmc.timeindex)) == profile.timeindex
                    and getattr(aw, 'curFile', None) == profile.cur_file
                    and tuple(float(t) for t in qmc.timex) == profile.timex)
    except (AttributeError, TypeError, ValueError):
        return False


def present(profile: Profile) -> dict[int, int]:
    """Sample index of every milestone the profile carries."""
    return {m: profile.timeindex[m] for m in range(SLOTS) if marked(profile.timeindex, m)}


def usable(profile: Profile) -> bool:
    """Whether every milestone present lies inside the recording, in roast order."""
    previous: float | None = None
    for _milestone, index in sorted(present(profile).items()):
        if index >= len(profile.timex):
            return False
        t = profile.timex[index]
        if previous is not None and t <= previous:
            return False
        previous = t
    return True


def origin(profile: Profile) -> float:
    """The instant the curve measures from: CHARGE, or the first sample without one."""
    charge = profile.timeindex[CHARGE]
    if marked(profile.timeindex, CHARGE) and charge < len(profile.timex):
        return profile.timex[charge]
    return profile.timex[0]


# ── the rules ────────────────────────────────────────────────────────────

def _floor(milestone: int) -> int:
    """Lowest sample a milestone may take: after CHARGE, Artisan reads 0 as unmarked."""
    return 0 if milestone == CHARGE else 1


def neighbours(profile: Profile, milestone: int) -> tuple[int | None, int | None]:
    """The closest milestones present below and above `milestone` in roast order."""
    marks = [m for m in present(profile) if m != milestone]
    before = max((m for m in marks if m < milestone), default=None)
    after = min((m for m in marks if m > milestone), default=None)
    return before, after


def _span(profile: Profile, before: int | None, after: int | None,
          floor: int) -> tuple[int, int] | None:
    times = profile.timex
    lo, hi = floor, len(times) - 1
    if before is not None:
        lo = max(lo, bisect.bisect_right(times, times[profile.timeindex[before]]))
    if after is not None:
        hi = min(hi, bisect.bisect_left(times, times[profile.timeindex[after]]) - 1)
    return (lo, hi) if lo <= hi else None


def interval(profile: Profile, milestone: int) -> tuple[int, int] | None:
    """First and last sample `milestone` may occupy, strictly between its neighbours' instants."""
    before, after = neighbours(profile, milestone)
    return _span(profile, before, after, _floor(milestone))


def nearest(times: tuple[float, ...], t: float, lo: int, hi: int) -> int:
    """The sample of [lo, hi] closest to `t`; the earliest one on a tie."""
    i = bisect.bisect_left(times, t, lo, hi + 1)
    if i > hi:
        best = hi
    elif i == lo:
        best = lo
    else:
        best = i if times[i] - t < t - times[i - 1] else i - 1
    return bisect.bisect_left(times, times[best], lo, best + 1)


def _occupied(profile: Profile, index: int, milestone: int | None) -> bool:
    return any(i == index for m, i in present(profile).items() if m != milestone)


def propose_move(profile: Profile, milestone: int, t: float) -> Proposal | None:
    """The sample a milestone dragged to raw instant `t` lands on, stopped at its neighbours."""
    if not usable(profile) or not marked(profile.timeindex, milestone):
        return None
    span = interval(profile, milestone)
    if span is None:
        return None
    lo, hi = span
    times = profile.timex
    index = nearest(times, t, lo, hi)
    if _occupied(profile, index, milestone):
        return None
    wanted = nearest(times, t, 0, len(times) - 1)
    before, after = neighbours(profile, milestone)
    limit = before if wanted < lo else after if wanted > hi else None
    return Proposal(index, limit)


def propose_add(profile: Profile, t: float) -> tuple[int, tuple[int, ...]] | None:
    """The sample a right-click at raw instant `t` adds on, with the milestones allowed there.

    The click itself has to fall between the candidates' neighbours: nothing is
    offered somewhere other than where the operator pointed, and a click outside
    the recording is not pulled back onto its ends.
    """
    if not usable(profile):
        return None
    times = profile.timex
    if not times[0] <= t <= times[-1]:
        return None
    marks = present(profile)
    candidates: list[int] = []
    for m in range(SLOTS):
        if m in marks:
            continue
        before, after = neighbours(profile, m)
        if before is not None and t <= times[marks[before]]:
            continue
        if after is not None and t >= times[marks[after]]:
            continue
        candidates.append(m)
    if not candidates:
        return None
    # Every candidate shares one gap between present milestones, hence one span.
    before, after = neighbours(profile, candidates[0])
    span = _span(profile, before, after, min(_floor(m) for m in candidates))
    if span is None:
        return None
    index = nearest(times, t, *span)
    if _occupied(profile, index, None):
        return None
    allowed = tuple(m for m in candidates if index >= _floor(m))
    return (index, allowed) if allowed else None


def admissible(profile: Profile, milestone: int, index: int) -> bool:
    """Whether `milestone` may be written at sample `index` of this profile."""
    if not 0 <= milestone < SLOTS or not usable(profile):
        return False
    span = interval(profile, milestone)
    return (span is not None and span[0] <= index <= span[1]
            and not _occupied(profile, index, milestone))


# ── the transaction ──────────────────────────────────────────────────────

def commit(aw: Any, profile: Profile, milestone: int, index: int) -> bool:
    """Write one correction into Artisan's profile; True when the profile changed.

    Revalidated against Artisan's live state first, so a menu, drag or dialog
    left open while monitoring started or another profile was loaded writes
    nothing. The follow-ups are those of Artisan's own right-click marking on a
    profile that is not recording, without its first-DROP upload and its
    ambient readings.
    """
    if not still_current(aw, profile) or not admissible(profile, milestone, index):
        return False
    was = profile.timeindex[milestone] if marked(profile.timeindex, milestone) else None
    if was == index:
        return False
    qmc = aw.qmc
    try:
        qmc.timeindex[milestone] = int(index)
    except (IndexError, TypeError):
        report_once('milestone_edit: timeindex refused the correction')
        return False
    _forget_label_positions(qmc, milestone)
    _realign(aw, qmc, milestone, was, index)
    try:
        qmc.fileDirtySignal.emit()
    except AttributeError:
        report_once('milestone_edit: the profile could not be marked modified')
    try:
        qmc.redraw_keep_view(recomputeAllDeltas=milestone in (CHARGE, DROP))
    except Exception:
        report_once('milestone_edit: Artisan redraw after a correction')
    return True


def _forget_label_positions(qmc: Any, milestone: int) -> None:
    """Drop the label placements Artisan remembers for what the correction moved."""
    keys = {milestone}
    if milestone in (CHARGE, FC_START, DROP):
        keys.add(_TP_KEY)   # the turning point is searched between these marks
    for name in ('l_annotations_dict', 'l_annotations_pos_dict'):
        cache = getattr(qmc, name, None)
        if isinstance(cache, dict):
            for key in keys:
                cache.pop(key, None)


def _realign(aw: Any, qmc: Any, milestone: int, was: int | None, index: int) -> None:
    """Artisan's axis, background and phase follow-ups to a placed mark."""
    try:
        if milestone == CHARGE:
            timex = qmc.timex
            qmc.startofx += timex[index] - (timex[was] if was is not None else 0.0)
            aw.autoAdjustAxis(deltas=False)
            qmc.timealign(redraw=False)
        elif milestone == DROP:
            aw.autoAdjustAxis(deltas=False)
        elif milestone in (DRY_END, FC_START) and getattr(qmc, 'phasesbuttonflag', False):
            reading = qmc.temp2[index]
            if is_proper_temp(reading):
                qmc.phases[milestone] = int(round(reading))
    except Exception:
        report_once('milestone_edit: Artisan realignment after a correction')


# ── typing an instant ────────────────────────────────────────────────────

def parse_clock(text: str) -> float | None:
    """Signed m:ss as seconds, or None when the text is not a time."""
    match = _CLOCK.match(text)
    if match is None:
        return None
    sign, minutes, seconds = match.groups()
    if int(seconds) > 59:
        return None
    value = float(int(minutes) * 60 + int(seconds))
    return -value if sign == '-' else value


class MilestoneTimeDialog(QDialog):
    """Sets one milestone's instant from the keyboard.

    Times are read from the CHARGE as it stood when the dialog opened, or from
    the first sample when there is none, and land on the nearest sample the
    rules allow. The retained time is shown before anything is applied.
    """

    def __init__(self, parent: QWidget | None, profile: Profile, milestone: int,
                 label: str) -> None:
        super().__init__(parent)
        self._profile = profile
        self._milestone = milestone
        self._origin = origin(profile)
        self._span = interval(profile, milestone)
        self._current = profile.timeindex[milestone]
        self._chosen: int | None = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setStyleSheet(base_qss() + (
            f"QDialog {{ border: 2px solid {THEME['ACCENT']}; }}"))

        times = profile.timex
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        title = QLabel(QApplication.translate('tilauscope', 'Change the time of {0}').format(label))
        title.setProperty('variant', 'title')
        lay.addWidget(title)

        now = fmt_clock(times[self._current] - self._origin)
        if self._span is not None:
            lo, hi = self._span
            bounds = QApplication.translate(
                'tilauscope', 'Now at {0}. Allowed from {1} to {2}.').format(
                    now, fmt_clock(times[lo] - self._origin), fmt_clock(times[hi] - self._origin))
        else:
            bounds = QApplication.translate('tilauscope', 'Now at {0}. There is no room to move it.').format(now)
        caption = QLabel(bounds)
        caption.setProperty('variant', 'secondary')
        lay.addWidget(caption)

        row = QHBoxLayout()
        row.setSpacing(10)
        if marked(profile.timeindex, CHARGE):
            field_name = QApplication.translate('tilauscope', 'Time from the charge')
        else:
            field_name = QApplication.translate('tilauscope', 'Time from the start of the recording')
        row.addWidget(QLabel(field_name))
        self.field = QLineEdit(now)
        self.field.setPlaceholderText(QApplication.translate('tilauscope', 'm:ss'))
        self.field.setMaxLength(9)
        self.field.setFixedWidth(96)
        row.addWidget(self.field)
        row.addStretch(1)
        lay.addLayout(row)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        lay.addWidget(self.feedback)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(QApplication.translate('tilauscope', 'Cancel'))
        cancel.setProperty('variant', 'outline')
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton(QApplication.translate('tilauscope', 'Apply'))
        self.apply_button.setProperty('variant', 'primary')
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_button)
        lay.addLayout(buttons)

        self.setMinimumWidth(420)
        self.field.textChanged.connect(self._evaluate)
        self._evaluate()

    def chosen_index(self) -> int | None:
        """The sample the typed time lands on, or None when nothing may be applied."""
        return self._chosen

    def showEvent(self, event: Any) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        # A frameless dialog on macOS takes the keyboard only once it is active.
        QTimer.singleShot(0, self._take_focus)

    def _take_focus(self) -> None:
        try:
            self.raise_()
            self.activateWindow()
            self.field.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            self.field.selectAll()
        except RuntimeError:
            report_once('MilestoneTimeDialog: closed before it took the focus')

    def _evaluate(self) -> None:
        self._chosen = None
        warning = True
        value = parse_clock(self.field.text())
        times = self._profile.timex
        if self._span is None:
            message = QApplication.translate('tilauscope', 'There is no room to move it.')
        elif value is None:
            message = QApplication.translate('tilauscope', 'Type the time as minutes:seconds, for example 5:24.')
        else:
            lo, hi = self._span
            # The bounds are compared as they are shown, in whole seconds.
            first = round(times[lo] - self._origin)
            last = round(times[hi] - self._origin)
            if not first <= value <= last:
                message = QApplication.translate('tilauscope', 'Outside the allowed range.')
            else:
                index = nearest(times, self._origin + value, lo, hi)
                shown = fmt_clock(times[index] - self._origin)
                if index == self._current:
                    message = QApplication.translate('tilauscope', 'Already at {0}: nothing to change.').format(shown)
                else:
                    self._chosen = index
                    warning = False
                    message = QApplication.translate('tilauscope', 'Will be set to {0}.').format(shown)
        self.feedback.setText(message)
        colour = THEME['YELLOW'] if warning else THEME['SUCCESS']
        self.feedback.setStyleSheet(f"QLabel {{ color: {colour}; }}")
        self.apply_button.setEnabled(self._chosen is not None)

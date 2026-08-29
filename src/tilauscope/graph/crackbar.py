"""Crack bar — the acoustic counter read as a phase, in the strip above the plot.

The probe returns a cumulative count, which nobody roasts by. What the operator
needs is the rate and the phase it implies, so the bar names the phase and the
meter only says which way it is moving. The gesture is not spoken here: it stays
on the assistant's coach line, the one place guidance lives.

The counter is read straight from the detector's own channels rather than from
its sliding window: that window is only fed while first crack is still unmarked,
and the bar has to keep reading through development.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Final

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QWidget

from tilauscope.tilauscope_types import THEME
from tilauscope.graph.common import marked, report_once

#: Phase keys. Display only — none of this can move the first-crack milestone.
QUIET: Final[str] = 'quiet'
FIRST: Final[str] = 'first'
ROLLING: Final[str] = 'rolling'
SETTLING: Final[str] = 'settling'

#: How long the rate has to stay under the threshold before the crack is called
#: over. Long enough not to blink on the gap between two pops, short enough to
#: still serve the drop decision.
_LULL_S: Final[float] = 20.0

#: Segments in the meter, and the rate that fills it. Three times the firing
#: threshold reaches the end of the scale — a rolling crack sits around the
#: middle, which leaves the meter somewhere to go.
_SEGMENTS: Final[int] = 10
_FULL_SCALE: Final[float] = 3.0

_COLOUR: Final[dict[str, str]] = {
    QUIET:    THEME['OVERLAY0'],
    FIRST:    THEME['YELLOW'],
    ROLLING:  THEME['WARNING'],
    SETTLING: THEME['ACCENT'],
}


def _phase_word(phase: str) -> str:
    if phase == FIRST:
        return QApplication.translate('tilauscope', 'FIRST POPS')
    if phase == ROLLING:
        return QApplication.translate('tilauscope', 'ROLLING')
    if phase == SETTLING:
        return QApplication.translate('tilauscope', 'SETTLING')
    return QApplication.translate('tilauscope', 'QUIET')


class CrackBar(QFrame):
    """One line: label, phase word, meter, rate.

    A child of the curve widget, placed by it in the strip above the plot. It
    exists only while the probe is counting — a greyed widget in the middle of a
    roast says less than no widget at all.
    """

    def __init__(self, aw: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._aw = aw
        self._level: str = 'guided'

        # Pop timestamps in roast seconds, over the detection window.
        self._pops: deque[float] = deque()
        self._last_total: int | None = None
        self._lull_since: float | None = None
        self._phase: str = QUIET

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            f"background-color: {THEME['SURFACE']};"
            f" border: 1px solid {THEME['SURFACE1']};"
            f" border-radius: 5px;"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(8)

        self._lbl = QLabel(QApplication.translate('tilauscope', 'CRACK'))
        self._lbl.setStyleSheet(
            f"border: none; color: {THEME['OVERLAY0']};"
            " font-family: 'JetBrains Mono'; font-size: 9px; letter-spacing: 1px;")
        row.addWidget(self._lbl)

        self._word = QLabel(_phase_word(QUIET))
        self._word.setStyleSheet(
            f"border: none; color: {_COLOUR[QUIET]};"
            " font-size: 12px; font-weight: bold;")
        # Fixed to the widest word so the bar never resizes under the eye: the
        # phase changes at the one moment the operator is looking at it.
        _fm = QFontMetrics(self._word.font())
        self._word.setFixedWidth(max(
            _fm.horizontalAdvance(_phase_word(p))
            for p in (QUIET, FIRST, ROLLING, SETTLING)) + 4)
        row.addWidget(self._word)

        self._meter = QWidget(self)
        _mrow = QHBoxLayout(self._meter)
        _mrow.setContentsMargins(0, 0, 0, 0)
        _mrow.setSpacing(2)
        self._segs: list[QFrame] = []
        for _i in range(_SEGMENTS):
            seg = QFrame(self._meter)
            seg.setFixedSize(8, 8)
            self._segs.append(seg)
            _mrow.addWidget(seg)
        self._paint_meter(QUIET, 0)
        row.addWidget(self._meter)

        self._rate = QLabel('')
        self._rate.setMinimumWidth(58)
        self._rate.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._rate.setStyleSheet(
            f"border: none; color: {THEME['SUBTEXT']};"
            " font-family: 'JetBrains Mono'; font-size: 9px;")
        row.addWidget(self._rate)

        self.setVisible(False)
        self.adjustSize()

    # ── level ────────────────────────────────────────────────────────────
    def set_operator_level(self, level: str) -> None:
        """Guided reads the word alone; the meter and the figures are what the
        further levels add. Nothing is removed — the word says the same thing."""
        self._level = level
        self._meter.setVisible(level != 'guided')
        self._rate.setVisible(level != 'guided')
        self.adjustSize()

    # ── state ────────────────────────────────────────────────────────────
    def reset(self) -> None:
        self._pops.clear()
        self._last_total = None
        self._lull_since = None
        self._phase = QUIET

    def _detector(self) -> Any | None:
        return getattr(getattr(self._aw, 'qmc', None), 'fc_detector', None)

    @staticmethod
    def _roast_seconds(qmc: Any) -> float:
        """Elapsed since charge, in seconds. Before the charge, since the start
        of the recording — the lull timer only needs a clock that advances at
        the roast's own pace, which under the simulator is not the wall's."""
        timex = qmc.timex
        if not timex:
            return 0.0
        now = float(timex[-1])
        ti = qmc.timeindex
        if marked(ti, 0) and int(ti[0]) < len(timex):
            return now - float(timex[int(ti[0])])
        return now

    def refresh(self) -> None:
        """Read the counter, resolve the phase, repaint. Called on the curve's
        own tick: two array reads, a subtraction and a deque purge."""
        try:
            self._refresh()
        except Exception:
            report_once('CrackBar.refresh')
            self.setVisible(False)

    def _refresh(self) -> None:
        det = self._detector()
        qmc = getattr(self._aw, 'qmc', None)
        # A detector too old to answer is one that is not counting: the bar
        # has nothing to show, which is exactly the no-probe case.
        read = getattr(det, 'read_total', None)
        total = read() if callable(read) else None
        if qmc is None or total is None:
            # Nothing is counting: the bar does not exist.
            self.setVisible(False)
            self.reset()
            self._aw.tilau_crack_phase = None
            return

        window = float(getattr(self._aw, 'TilauScopeFCWindow', 35.0)) or 35.0
        threshold = int(getattr(self._aw, 'TilauScopeFCTreshold', 4)) or 4
        t_now = self._roast_seconds(qmc)

        # A counter that went backwards is a probe that restarted; re-baseline
        # rather than bank a negative delta as pops. Where each pop LANDED is
        # not tracked here: the curve reads that off the recorded channel, so a
        # reopened roast draws the same band as the one that ran.
        if self._last_total is None or total < self._last_total:
            self._last_total = total
        elif total > self._last_total:
            for _ in range(min(total - self._last_total, 64)):
                self._pops.append(t_now)
            self._last_total = total
        while self._pops and (t_now - self._pops[0]) > window:
            self._pops.popleft()

        n = len(self._pops)
        fc_marked = marked(qmc.timeindex, 2)
        phase = self._resolve(n, threshold, fc_marked, t_now)

        if phase != self._phase:
            self._phase = phase
            self._word.setText(_phase_word(phase))
            self._word.setStyleSheet(
                f"border: none; color: {_COLOUR[phase]};"
                " font-size: 12px; font-weight: bold;")
        self._paint_meter(phase, n if phase != QUIET else 0)

        if self._level != 'guided':
            text = f'{n} · {int(window)} s'
            if self._level == 'expert':
                text = f'{text} · {total}'
            self._rate.setText(text)
        self.setToolTip(
            QApplication.translate('tilauscope', '{0} pops in the last {1} s').format(n, int(window)))
        self.setVisible(True)
        # Published for the assistant's coach line, which speaks the gesture:
        # the bar is the readout, and guidance keeps its one place on screen.
        self._aw.tilau_crack_phase = phase

    def _resolve(self, n: int, threshold: int, fc_marked: bool, t_now: float) -> str:
        """Phase from the rate. Display only: the first-crack milestone is the
        detector's to mark, and this never disagrees with it."""
        if fc_marked:
            if n >= threshold:
                self._lull_since = None
                return ROLLING
            if self._lull_since is None:
                self._lull_since = t_now
            return SETTLING if (t_now - self._lull_since) >= _LULL_S else ROLLING
        self._lull_since = None
        return FIRST if n >= 1 else QUIET

    def _paint_meter(self, phase: str, n: int) -> None:
        colour = _COLOUR[phase]
        full = max(1.0, _FULL_SCALE * float(
            int(getattr(self._aw, 'TilauScopeFCTreshold', 4)) or 4))
        filled = max(0, min(_SEGMENTS, int(round(_SEGMENTS * n / full))))
        for i, seg in enumerate(self._segs):
            fill = colour if i < filled else THEME['BORDER']
            seg.setStyleSheet(f'background-color: {fill}; border-radius: 1px;')

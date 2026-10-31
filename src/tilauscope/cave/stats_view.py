# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Statistics at a glance: the one point of a roast, the next change, its phases, three checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from tilauscope.tilauscope_types import THEME

_KIND_COLOURS = {'ok': 'SUCCESS', 'warn': 'WARNING', 'bad': 'CRITICAL', 'neutral': 'SUBTEXT1'}


@dataclass
class PhaseFigures:
    name: str
    share_pct: float
    duration: str
    rise: str           # average °/min, as the sheet states it
    status: str         # '' when the phase could not be judged
    flagged: bool
    colour: str         # THEME key


@dataclass
class StatsSummary:
    kind: str           # 'ok' | 'warn' | 'bad'
    title: str
    effect: str
    next_text: str      # '' when nothing is asked
    phases: list[PhaseFigures] = field(default_factory=list)
    cards: list[tuple[str, str, str, str]] = field(default_factory=list)    # label, value, word, kind


def _label(text: str, size: int, colour: str = 'TEXT', bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    weight = 'font-weight: 600;' if bold else ''
    label.setStyleSheet(f"color: {THEME[colour]}; font-size: {size}px; background: transparent; {weight}")
    return label


class RoastStatsSummary(QScrollArea):
    """Read only; its one way on is the full sheet."""

    figures_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.has_data = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"QScrollArea {{ border: none; background: {THEME['BG']}; }}")
        self._body = QWidget()
        self._body.setStyleSheet(f"background: {THEME['BG']};")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(16)
        self.setWidget(self._body)

    def clear(self) -> None:
        self.has_data = False
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def show_summary(self, summary: StatsSummary) -> None:
        self.clear()
        self.has_data = True
        self._layout.addWidget(self._hero(summary))
        if summary.phases:
            self._layout.addWidget(self._phases(summary.phases))
        self._layout.addLayout(self._cards(summary.cards))
        more = QPushButton(QApplication.translate("tilauscope_beancave", "All figures and advice ›"))
        more.setFlat(True)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 14px; font-weight: 600; border: none; text-align: left;")
        more.clicked.connect(lambda: self.figures_requested.emit())
        self._layout.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
        self._layout.addStretch(1)

    @staticmethod
    def _hero(summary: StatsSummary) -> QFrame:
        hero = QFrame()
        hero.setObjectName('statsHero')
        hero.setStyleSheet(f"QFrame#statsHero {{ background: {THEME['SURFACE']}; border-radius: 12px; }}")
        row = QHBoxLayout(hero)
        row.setContentsMargins(22, 18, 22, 18)
        row.setSpacing(22)
        left = QVBoxLayout()
        left.setSpacing(6)
        if summary.kind != 'ok':
            left.addWidget(_label(QApplication.translate("tilauscope_beancave", "One thing to look at"), 13,
                                  _KIND_COLOURS[summary.kind], True))
        left.addWidget(_label(summary.title, 25, 'TEXT', True))
        left.addWidget(_label(summary.effect, 14, 'SUBTEXT1'))
        left.addStretch(1)
        row.addLayout(left, 1)
        if summary.next_text:
            line = QFrame()
            line.setFixedWidth(1)
            line.setStyleSheet(f"background: {THEME['SURFACE1']};")
            row.addWidget(line)
            right = QVBoxLayout()
            right.setSpacing(8)
            right.addWidget(_label(QApplication.translate("tilauscope_beancave", "Next time"), 13, 'ACCENT', True))
            right.addWidget(_label(summary.next_text, 18, 'TEXT', True))
            right.addStretch(1)
            row.addLayout(right, 1)
        return hero

    @staticmethod
    def _phases(phases: list[PhaseFigures]) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(3)
        for phase in phases:
            part = QFrame()
            part.setFixedHeight(12)
            part.setStyleSheet(f"background: {THEME[phase.colour]}; border-radius: 3px;")
            bar.addWidget(part, max(1, round(phase.share_pct * 10)))
        column.addLayout(bar)
        figures = QHBoxLayout()
        figures.setSpacing(20)
        for phase in phases:
            cell = QVBoxLayout()
            cell.setSpacing(3)
            cell.addWidget(_label(f"{phase.name} · {phase.share_pct:.0f} %", 13, 'SUBTEXT1'))
            cell.addWidget(_label(phase.duration, 23, 'WARNING' if phase.flagged else 'TEXT', True))
            words = " · ".join(w for w in (f"{phase.rise} °/min", phase.status) if w)
            cell.addWidget(_label(words, 13, 'SUBTEXT1'))
            cell.addStretch(1)
            figures.addLayout(cell, 1)
        column.addLayout(figures)
        return host

    @staticmethod
    def _cards(cards: list[tuple[str, str, str, str]]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for label, value, word, kind in cards:
            card = QFrame()
            card.setObjectName('statsCard')
            card.setStyleSheet(f"QFrame#statsCard {{ background: {THEME['SURFACE']}; border-radius: 10px; }}")
            cell = QVBoxLayout(card)
            cell.setContentsMargins(14, 11, 14, 11)
            cell.setSpacing(3)
            cell.addWidget(_label(label, 13, 'SUBTEXT1'))
            cell.addWidget(_label(value, 18, 'TEXT', True))
            if word:
                cell.addWidget(_label(word, 13, _KIND_COLOURS.get(kind, 'SUBTEXT1')))
            cell.addStretch(1)
            row.addWidget(card, 1)
        return row

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The Journal page of the Roasts tab: a coffee's roasts, what each tried, how it tasted."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from tilaucore import tasting_log
from tilaucore.roast_journal import JournalRow, next_step
from tilaucore.roast_plan_view import tasting_change_values
from tilauscope.beancave_catalogue import short_date
from tilauscope.cave.tasting_dialog import change_text, defect_labels, verdict_labels
from tilauscope.tilauscope_types import THEME

_VERDICT_COLOURS = {'yes': 'SUCCESS', 'almost': 'YELLOW', 'no': 'CRITICAL'}


def _label(text: str, size: int, colour: str = 'TEXT', bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    weight = 'font-weight: 600;' if bold else ''
    label.setStyleSheet(f"color: {THEME[colour]}; font-size: {size}px; background: transparent; {weight}")
    return label


def _taste_button(signal: pyqtSignal) -> QPushButton:  # type: ignore[valid-type]
    button = QPushButton(QApplication.translate("tilauscope_beancave", "Taste ›"))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background: {THEME['SURFACE1']}; color: {THEME['ACCENT']}; border: none;"
        f" border-radius: 8px; padding: 8px 16px; font-size: 14px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: {THEME['SURFACE2']}; }}")
    button.clicked.connect(lambda: signal.emit())
    return button


class RoastJournalView(QScrollArea):
    """Read only; its one action is to taste the latest roast."""

    taste_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"QScrollArea {{ border: none; background: {THEME['BG']}; }}")
        self._body = QWidget()
        self._body.setStyleSheet(f"background: {THEME['BG']};")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(10)
        self.setWidget(self._body)

    def _clear(self) -> None:
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def show_message(self, text: str) -> None:
        self._clear()
        self._layout.addStretch(1)
        message = _label(text, 15, 'SUBTEXT1')
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(message)
        self._layout.addStretch(1)

    def show_rows(self, rows: list[JournalRow], selected_uuid: str, mode: str) -> None:
        """`selected_uuid` is the roast on screen: the form opens on it, so Taste stands for it alone."""
        self._clear()
        can_taste = bool(rows) and rows[0].roast_uuid == selected_uuid
        if len(rows) == 1 and rows[0].tasting is None:
            self._show_first_roast(can_taste)
            return
        self._layout.addWidget(self._next_block(rows, can_taste, mode))
        for row in rows:
            self._layout.addWidget(self._row(row, row.roast_uuid == selected_uuid, mode))
        self._layout.addStretch(1)

    def _show_first_roast(self, can_taste: bool) -> None:
        self._layout.addStretch(1)
        for text, size, colour, bold in (
                (QApplication.translate("tilauscope_beancave", "First roast of this coffee"), 22, 'TEXT', True),
                (QApplication.translate("tilauscope_beancave", "Taste it once rested. The next roast starts from there."),
                 15, 'SUBTEXT1', False)):
            label = _label(text, size, colour, bold)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(label)
        if can_taste:
            self._layout.addWidget(_taste_button(self.taste_requested), 0, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addStretch(1)

    def _next_block(self, rows: list[JournalRow], can_taste: bool, mode: str) -> QFrame:
        kind, defect = next_step(rows)
        if kind == 'change':
            text = change_text(defect, mode)[0]
        elif kind == 'taste':
            text = (QApplication.translate("tilauscope_beancave", "Taste this roast to choose the next change")
                    if can_taste else
                    QApplication.translate("tilauscope_beancave", "Taste your latest roast to choose the next change"))
        else:
            text = QApplication.translate(*(tasting_log.NEXT_SAME if kind == 'same' else tasting_log.NEXT_TICK)[0])
        block = QFrame()
        block.setObjectName('journalNext')
        block.setStyleSheet(f"QFrame#journalNext {{ background: {THEME['SURFACE']}; border-radius: 10px; }}")
        layout = QHBoxLayout(block)
        layout.setContentsMargins(18, 14, 18, 14)
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addWidget(_label(QApplication.translate("tilauscope_beancave", "Next roast"), 12, 'ACCENT', True))
        words.addWidget(_label(text, 19, 'TEXT', True))
        layout.addLayout(words, 1)
        if kind == 'taste' and can_taste:
            layout.addWidget(_taste_button(self.taste_requested))
        return block

    @staticmethod
    def _tried_cell(row: JournalRow, mode: str) -> QVBoxLayout:
        cell = QVBoxLayout()
        cell.setSpacing(3)
        heading = QApplication.translate("tilauscope_beancave", "Tried")
        if row.tried:
            cell.addWidget(_label(heading, 12, 'SUBTEXT1', True))
            cell.addWidget(_label(change_text(row.tried['defect'], mode)[0], 15, 'TEXT', True))
            cell.addWidget(_label(tasting_change_values(row.tried, row.tried.get('unit', 'C')), 13, 'SUBTEXT1'))
        elif row.suggested:
            cell.addWidget(_label(QApplication.translate("tilauscope_beancave", "Suggested"), 12, 'SUBTEXT1', True))
            cell.addWidget(_label(change_text(row.suggested, mode)[0], 14, 'SUBTEXT1'))
        elif row.first:
            cell.addWidget(_label(heading, 12, 'SUBTEXT1', True))
            cell.addWidget(_label(QApplication.translate("tilauscope_beancave", "First roast"), 15, 'SUBTEXT1', True))
        return cell

    @staticmethod
    def _cup_cell(row: JournalRow) -> QVBoxLayout:
        cell = QVBoxLayout()
        cell.setSpacing(3)
        cell.addWidget(_label(QApplication.translate("tilauscope_beancave", "In the cup"), 12, 'SUBTEXT1', True))
        if row.tasting is None:
            cell.addWidget(_label(QApplication.translate("tilauscope_beancave", "Not tasted yet"), 14, 'SUBTEXT1'))
            return cell
        verdict = verdict_labels().get(row.tasting.verdict, '')
        if verdict:
            cell.addWidget(_label(verdict, 15, _VERDICT_COLOURS.get(row.tasting.verdict, 'TEXT'), True))
        labels = defect_labels()
        defects = ", ".join(labels[d] for d in row.tasting.defects if d in labels)
        if defects:
            cell.addWidget(_label(defects, 13, 'SUBTEXT1'))
        return cell

    def _row(self, row: JournalRow, selected: bool, mode: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName('journalRow')
        border = THEME['ACCENT'] if selected else THEME['BORDER']
        frame.setStyleSheet(f"QFrame#journalRow {{ border: 1px solid {border}; border-radius: 10px; }}")
        grid = QGridLayout(frame)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(20)
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        when = QVBoxLayout()
        when.setSpacing(3)
        when.addWidget(_label(short_date(row.epoch), 14, 'TEXT', True))
        if row.weight_in_g > 0:
            when.addWidget(_label(f"{row.weight_in_g:.0f} g", 13, 'SUBTEXT1'))
        grid.addLayout(when, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addLayout(self._tried_cell(row, mode), 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.addLayout(self._cup_cell(row), 0, 2, Qt.AlignmentFlag.AlignTop)
        return frame

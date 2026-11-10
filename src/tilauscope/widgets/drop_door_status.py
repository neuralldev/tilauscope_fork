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

"""The drop door contact's live state, in TilauScope Config (Sensors and Detection).

Reads DropDoorWatch.status() once a second while shown: a cached value, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tilauscope.drop_door_watch import DoorStatus
from tilauscope.theme_qss import tint
from tilauscope.tilauscope_types import THEME

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # pylint: disable=unused-import

_TOKEN = {DoorStatus.READY: 'SUCCESS', DoorStatus.OPEN: 'YELLOW', DoorStatus.NOT_WIRED: 'SUBTEXT',
          DoorStatus.OFFLINE: 'SUBTEXT', DoorStatus.UPDATE: 'WARNING'}


def _chip_text(status: DoorStatus) -> str:
    return {
        DoorStatus.READY: QApplication.translate('tilauscope_devices', 'Closed'),
        DoorStatus.OPEN: QApplication.translate('tilauscope_devices', 'Open'),
        DoorStatus.NOT_WIRED: QApplication.translate('tilauscope_devices', 'Not wired'),
        DoorStatus.OFFLINE: QApplication.translate('tilauscope_devices', 'Offline'),
        DoorStatus.UPDATE: QApplication.translate('tilauscope_devices', 'Update'),
    }[status]


def _sensors_text(status: DoorStatus, dropped_at: str | None) -> str:
    if status is DoorStatus.READY:
        return QApplication.translate('tilauscope_devices', 'Door closed. DROP is marked the moment it opens.')
    if status is DoorStatus.OPEN:
        if dropped_at:
            return QApplication.translate('tilauscope_devices', 'Door open. DROP marked from the door at {0}.').format(dropped_at)
        return QApplication.translate('tilauscope_devices', 'Door open.')
    if status is DoorStatus.NOT_WIRED:
        return QApplication.translate('tilauscope_devices',
                                      'No door contact seen. DROP is found from the curve, about 15 s after the beans leave.')
    if status is DoorStatus.OFFLINE:
        return QApplication.translate('tilauscope_devices',
                                      'Probe not connected. DROP is found from the curve until it reconnects.')
    return QApplication.translate('tilauscope_devices',
                                  'This probe firmware cannot read a door contact. Update the probe to use one.')


def _detection_text(status: DoorStatus) -> str:
    if status in (DoorStatus.READY, DoorStatus.OPEN):
        return QApplication.translate('tilauscope_devices',
                                      'Drop door contact: marks DROP the moment the door opens, even with this box unchecked.')
    if status is DoorStatus.OFFLINE:
        return QApplication.translate('tilauscope_devices', 'Probe not connected. DROP comes only from the box above.')
    return QApplication.translate('tilauscope_devices', 'No drop door contact. DROP comes only from the box above.')


class _DoorGlyph(QWidget):
    """The door drawn in the state's colour: closed, ajar, dashed (no contact), or a warning mark."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.status = DoorStatus.OFFLINE

    def paintEvent(self, _event) -> None:  # noqa: ANN001, N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(THEME[_TOKEN[self.status]] if self.status is not DoorStatus.OFFLINE else THEME['OVERLAY0'])
        pen = QPen(colour, 1.6)
        if self.status is DoorStatus.NOT_WIRED:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(4, 4, 20, 20), 3.5, 3.5)
        p.setPen(Qt.PenStyle.NoPen)
        if self.status in (DoorStatus.READY, DoorStatus.OFFLINE):
            p.setBrush(colour if self.status is DoorStatus.READY else QColor(THEME['SURFACE1']))
            p.drawRoundedRect(QRectF(8, 11, 12, 6), 1.5, 1.5)
        elif self.status is DoorStatus.OPEN:
            leaf = QPainterPath()
            leaf.moveTo(8, 21)
            leaf.lineTo(8, 11)
            leaf.lineTo(18, 7.5)
            leaf.lineTo(18, 17.5)
            leaf.closeSubpath()
            p.setBrush(colour)
            p.drawPath(leaf)
        elif self.status is DoorStatus.UPDATE:
            p.setPen(QPen(colour, 2.2, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(14, 9, 14, 16)
            p.drawPoint(14, 19)
        p.end()


class _Chip(QLabel):
    def show_status(self, status: DoorStatus) -> None:
        token = _TOKEN[status]
        ground = tint(token, 0.15) if status not in (DoorStatus.NOT_WIRED, DoorStatus.OFFLINE) else THEME['BORDER']
        self.setText(_chip_text(status))
        self.setStyleSheet(f"QLabel {{ background: {ground}; color: {THEME[token]}; border-radius: 9px;"
                           f" padding: 2px 9px; font-size: 11px; font-weight: 600; }}")


class DropDoorStatus(QFrame):
    """`detection=False`: the Sensors line (glyph, title, sentence, chip).
    `detection=True`: the line under the auto DROP box (chip, sentence)."""

    def __init__(self, aw: ApplicationWindow, detection: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._aw = aw
        self._detection = detection
        self._shown: tuple[DoorStatus, str | None] | None = None
        self.setObjectName('dropDoorStatus')
        self.setStyleSheet(f"QFrame#dropDoorStatus {{ background: {THEME['BG']}; border-radius: 8px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        self._chip = _Chip()
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; background: transparent;")
        self._glyph: _DoorGlyph | None = None
        if detection:
            row.addWidget(self._chip, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(self._text, 1)
        else:
            self._glyph = _DoorGlyph()
            title = QLabel(QApplication.translate('tilauscope_devices', 'Drop door'))
            title.setStyleSheet(f"color: {THEME['TEXT']}; font-weight: 600; font-size: 13px; background: transparent;")
            words = QVBoxLayout()
            words.setSpacing(1)
            words.addWidget(title)
            words.addWidget(self._text)
            row.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(words, 1)
            row.addWidget(self._chip, 0, Qt.AlignmentFlag.AlignVCenter)
            self.setMinimumHeight(60)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        watch = getattr(self._aw, '_tilau_drop_door', None)
        status = watch.status(self._aw) if watch is not None else DoorStatus.OFFLINE
        dropped_at = watch.dropped_at if watch is not None else None
        if (status, dropped_at) == self._shown:
            return
        self._shown = (status, dropped_at)
        self._chip.show_status(status)
        self._text.setText(_detection_text(status) if self._detection else _sensors_text(status, dropped_at))
        if self._glyph is not None:
            self._glyph.status = status
            self._glyph.update()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: ANN001, N802
        self._timer.stop()
        super().hideEvent(event)

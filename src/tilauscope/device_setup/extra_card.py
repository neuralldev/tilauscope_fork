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

"""One extra device in the Devices window: its channels, their names, their counters.

A card behaves like a row of the alarm editor: a press selects it (the commands
in the bar above act on the selection) and the grip drags it to another place.
It edits its draft row in place. The name of a channel is also what TilauScope
recognises it by (the crack counter, the colour reading), so the card says when
a name carries such a role and warns when an edit makes it lose one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PyQt6.QtCore import QEvent, QMimeData, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QVBoxLayout, QWidget)

from tilauscope.device_setup.draft import ExtraRow
from tilauscope.tilauscope_types import THEME, classify_extra_channel
from tilauscope.widgets.controls import GripHandle

#: What a dragged card carries: the uid of its draft row.
EXTRA_DEVICE_MIME: Final[str] = 'application/x-tilau-extra-device-uid'
_CHANNEL_INDENT: Final[int] = 23   # channel lines start under the title, past the grip


def _role_text(category: str) -> str:
    if category == 'fc':
        return QApplication.translate('tilauscope_devices', 'Used for first crack detection')
    if category == 'sc':
        return QApplication.translate('tilauscope_devices', 'Used for second crack detection')
    if category == 'color':
        return QApplication.translate('tilauscope_devices', 'Used as roast colour')
    return QApplication.translate('tilauscope_devices', 'Used as rate of colour change')


def _lost_role_text(category: str) -> str:
    if category == 'fc':
        return QApplication.translate('tilauscope_devices',
                                      'Renamed — no longer used for first crack detection.')
    if category == 'sc':
        return QApplication.translate('tilauscope_devices',
                                      'Renamed — no longer used for second crack detection.')
    if category == 'color':
        return QApplication.translate('tilauscope_devices',
                                      'Renamed — no longer used as roast colour.')
    return QApplication.translate('tilauscope_devices',
                                  'Renamed — no longer used as rate of colour change.')


class ExtraDeviceCard(QFrame):
    """Grip, title, and one line per channel the device uses."""

    clicked = pyqtSignal(int)   # uid of the row

    def __init__(self, row: ExtraRow, title: str, used: tuple[bool, bool], warning: str,
                 name_subst: Callable[[str], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self._name_subst = name_subst
        self._selected = False
        self.setObjectName('extraDeviceCard')
        self._apply_frame_style()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 12, 10)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(7)
        header.addWidget(GripHandle(self._start_drag,
                                    QApplication.translate('tilauscope_devices', 'Drag to reorder')))
        title_lbl = QLabel(title)
        title_lbl.setProperty('variant', 'title')
        header.addWidget(title_lbl)
        header.addStretch()
        outer.addLayout(header)

        if warning:
            note = QLabel(warning)
            note.setWordWrap(True)
            note.setContentsMargins(_CHANNEL_INDENT, 0, 0, 0)
            note.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 11px; background: transparent;")
            outer.addWidget(note)

        for channel in (0, 1):
            if used[channel]:
                self._add_channel(outer, channel)

    # ── selection ─────────────────────────────────────────────────────────────

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._apply_frame_style()

    def _apply_frame_style(self) -> None:
        border = THEME['ACCENT'] if self._selected else THEME['BORDER']
        background = THEME['BG'] if self._selected else THEME['SURFACE']
        self.setStyleSheet(
            f'#extraDeviceCard {{ background: {background}; border: 1px solid {border};'
            f' border-radius: 8px; }}')

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        # a press on a card selects it; it never starts moving the window
        self.clicked.emit(self._row.uid)
        event.accept()

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        if event is not None and event.type() == QEvent.Type.FocusIn:
            self.clicked.emit(self._row.uid)   # editing a channel selects its card too
        return super().eventFilter(watched, event)

    def _start_drag(self) -> None:
        self.clicked.emit(self._row.uid)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(EXTRA_DEVICE_MIME, str(self._row.uid).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    # ── channels ──────────────────────────────────────────────────────────────

    def _add_channel(self, outer: QVBoxLayout, channel: int) -> None:
        # a {n} placeholder reads as its event name; it is kept unless retyped
        shown = self._name_subst(self._row.names[channel])
        line = QHBoxLayout()
        line.setContentsMargins(_CHANNEL_INDENT, 0, 0, 0)
        edit = QLineEdit(shown)
        edit.setMinimumWidth(220)
        edit.installEventFilter(self)
        show = QCheckBox(QApplication.translate('tilauscope_devices', 'Show counter'))
        show.setChecked(self._row.show[channel])
        show.installEventFilter(self)
        line.addWidget(edit, 1)
        line.addSpacing(16)
        line.addWidget(show)
        outer.addLayout(line)

        role = QLabel()
        role.setWordWrap(True)
        role.setContentsMargins(_CHANNEL_INDENT, 0, 0, 0)
        outer.addWidget(role)
        initial = classify_extra_channel(shown)
        self._show_role(role, initial, initial)

        def renamed(text: str) -> None:
            self._row.names[channel] = text
            self._show_role(role, initial, classify_extra_channel(text))

        def toggled(checked: bool) -> None:
            self._row.show[channel] = checked

        edit.textEdited.connect(renamed)
        show.toggled.connect(toggled)

    @staticmethod
    def _show_role(label: QLabel, initial: str | None, now: str | None) -> None:
        if now is not None:
            label.setText('✓ ' + _role_text(now))
            color = THEME['SUCCESS']
        elif initial is not None:
            label.setText(_lost_role_text(initial))
            color = THEME['WARNING']
        else:
            label.setVisible(False)
            return
        label.setStyleSheet(f'color: {color}; font-size: 11px; background: transparent;')
        label.setVisible(True)

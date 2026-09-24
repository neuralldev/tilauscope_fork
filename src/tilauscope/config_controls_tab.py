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

"""TilauScope Config's CONTROLS tab: the control names and the commands the
milestone and monitoring buttons send — what Artisan's Events › Config tab held
that TilauScope uses. Nothing is written before Save (apply())."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)
from PyQt6 import sip

from tilauscope.theme_qss import style_combo_popup
from tilauscope.tilauscope_types import THEME
from tilauscope.widgets.config_parts import (QCollapsibleWidget, scrollable, section_label,
                                             styled_combo_view, trash_button_qss)

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_log = logging.getLogger(__name__)

#: Artisan's action type for an IO Command, as stored in the button action lists.
_IO_COMMAND: Final[int] = 5


def _action_types() -> list[str]:
    """Artisan's button action types, in the order their index is stored
    (artisanlib/events.py buttonActionTypes); index 0 is no action."""
    return [
        QApplication.translate('ComboBox', 'None'),
        QApplication.translate('ComboBox', 'Serial Command'),
        QApplication.translate('ComboBox', 'Call Program'),
        QApplication.translate('ComboBox', 'Modbus Command'),
        QApplication.translate('ComboBox', 'DTA Command'),
        QApplication.translate('ComboBox', 'IO Command'),
        QApplication.translate('ComboBox', 'Hottop Heater'),
        QApplication.translate('ComboBox', 'Hottop Fan'),
        QApplication.translate('ComboBox', 'Hottop Command'),
        QApplication.translate('ComboBox', 'p-i-d'),
        QApplication.translate('ComboBox', 'Fuji Command'),
        QApplication.translate('ComboBox', 'PWM Command'),
        QApplication.translate('ComboBox', 'VOUT Command'),
        QApplication.translate('ComboBox', 'S7 Command'),
        QApplication.translate('ComboBox', 'Aillio R1 Heater'),
        QApplication.translate('ComboBox', 'Aillio R1 Fan'),
        QApplication.translate('ComboBox', 'Aillio R1 Drum'),
        QApplication.translate('ComboBox', 'Aillio R1 Command'),
        QApplication.translate('ComboBox', 'Artisan Command'),
        QApplication.translate('ComboBox', 'RC Command'),
        QApplication.translate('ComboBox', 'Multiple Event'),
        QApplication.translate('ComboBox', 'WebSocket Command'),
        QApplication.translate('ComboBox', 'Difluid Airwave Command'),
        QApplication.translate('ComboBox', 'TilauScope Ambient Command'),
    ]


class _CommandCard(QFrame):
    """One button's command: action type, command text and, for a milestone, ✕."""

    changed = pyqtSignal()
    cleared = pyqtSignal()

    def __init__(self, title: str, actions_attr: str, strings_attr: str, index: int,
                 aw: ApplicationWindow, removable: bool) -> None:
        super().__init__()
        self._actions_attr = actions_attr
        self._strings_attr = strings_attr
        self._index = index
        self.setObjectName('cmdCard')
        self.setStyleSheet(
            f"QFrame#cmdCard {{ background: {THEME['SURFACE']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(6)
        head = QLabel(title)
        head.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px; font-weight: bold;"
                           f"letter-spacing: 1.5px; border: none;")
        lay.addWidget(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        types = _action_types()
        # None first, then Artisan's alphabetical order; the item data is the stored index
        self.type_combo = QComboBox()
        self.type_combo.setView(styled_combo_view())
        style_combo_popup(self.type_combo)
        self.type_combo.addItem(types[0], 0)
        for i in sorted(range(1, len(types)), key=lambda k: types[k]):
            self.type_combo.addItem(types[i], i)
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText(
            QApplication.translate('tilauscope_devices', 'Command sent to the roaster'))
        row.addWidget(self.type_combo)
        row.addWidget(self.command_edit, 1)
        if removable:
            clear_btn = QPushButton('✕')
            clear_btn.setStyleSheet(trash_button_qss())
            clear_btn.setToolTip(QApplication.translate('tilauscope_devices', 'Remove this command'))
            clear_btn.clicked.connect(self._clear)
            row.addWidget(clear_btn)
        lay.addLayout(row)

        qmc = aw.qmc
        actions = getattr(qmc, actions_attr)
        strings = getattr(qmc, strings_attr)
        action = actions[index] if index < len(actions) else 0
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(action)))
        self.command_edit.setText(strings[index] if index < len(strings) else '')
        self.type_combo.currentIndexChanged.connect(self.changed)
        self.command_edit.textChanged.connect(self.changed)

    def has_command(self) -> bool:
        """A command is its text: a type alone sends nothing."""
        return bool(self.command_edit.text().strip())

    def _clear(self) -> None:
        self.type_combo.setCurrentIndex(0)
        self.command_edit.clear()
        self.cleared.emit()

    def apply(self, aw: ApplicationWindow) -> None:
        qmc = aw.qmc
        actions = list(getattr(qmc, self._actions_attr))
        strings = list(getattr(qmc, self._strings_attr))
        command = self.command_edit.text().strip()
        actions[self._index] = int(self.type_combo.currentData()) if command else 0
        strings[self._index] = command
        setattr(qmc, self._actions_attr, actions)
        setattr(qmc, self._strings_attr, strings)


class _MilestoneRail(QWidget):
    """The roast milestones on one line; a filled dot has a command. Click picks one."""

    picked = pyqtSignal(int)

    _MARGIN: Final[int] = 34
    _DOT_Y: Final[int] = 12
    _RADIUS: Final[float] = 6.0

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self._names = names
        self._filled = [False] * len(names)
        self.setMinimumHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_filled(self, index: int, filled: bool) -> None:
        if self._filled[index] != filled:
            self._filled[index] = filled
            self.update()

    def _x(self, index: int) -> float:
        span = self.width() - 2 * self._MARGIN
        return self._MARGIN + index * span / (len(self._names) - 1)

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: N802
        del a0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(THEME['BORDER']), 2))
        p.drawLine(QPointF(self._x(0), self._DOT_Y), QPointF(self._x(len(self._names) - 1), self._DOT_Y))
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        for i, name in enumerate(self._names):
            x = self._x(i)
            filled = self._filled[i]
            p.setPen(QPen(QColor(THEME['ACCENT'] if filled else THEME['SUBTEXT']), 2))
            p.setBrush(QColor(THEME['ACCENT'] if filled else THEME['BG']))
            p.drawEllipse(QPointF(x, self._DOT_Y), self._RADIUS, self._RADIUS)
            p.setPen(QColor(THEME['TEXT'] if filled else THEME['SUBTEXT']))
            p.drawText(QRectF(x - 40, self._DOT_Y + 10, 80, 18), Qt.AlignmentFlag.AlignCenter, name)
        p.end()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is None or a0.button() != Qt.MouseButton.LeftButton:
            return
        x = a0.position().x()
        nearest = min(range(len(self._names)), key=lambda i: abs(self._x(i) - x))
        self.picked.emit(nearest)


class ControlsTab:
    """Builds the CONTROLS tab into `tab` and writes it back on apply()."""

    def __init__(self, tab: QWidget, aw: ApplicationWindow) -> None:
        self._aw = aw
        layout = scrollable(tab).widget().layout()

        # ── Control names ────────────────────────────────────────────────
        layout.addWidget(section_label(QApplication.translate('tilauscope_devices', 'Control names')))
        layout.addWidget(self._hint(QApplication.translate(
            'tilauscope_devices', 'Names shown on sliders, buttons, alarms and the phone.')))
        names_row = QHBoxLayout()
        names_row.setSpacing(10)
        self._name_edits: list[QLineEdit] = []
        for i in range(4):
            number = QLabel('①②③④'[i])
            number.setStyleSheet(f"color: {THEME['ACCENT']}; font-size: 15px;")
            edit = QLineEdit(aw.qmc.etypes[i])
            names_row.addWidget(number)
            names_row.addWidget(edit, 1)
            self._name_edits.append(edit)
        layout.addLayout(names_row)

        # ── Milestone commands ───────────────────────────────────────────
        layout.addWidget(section_label(QApplication.translate('tilauscope_devices', 'Milestone commands')))
        layout.addWidget(self._hint(QApplication.translate(
            'tilauscope_devices',
            'Sent to the roaster when the milestone is marked, from TilauScope, Artisan or the phone.')))
        milestones = [
            QApplication.translate('Button', 'CHARGE'),
            QApplication.translate('Button', 'DRY END'),
            QApplication.translate('Button', 'FC START'),
            QApplication.translate('Button', 'FC END'),
            QApplication.translate('Button', 'SC START'),
            QApplication.translate('Button', 'SC END'),
            QApplication.translate('Button', 'DROP'),
            QApplication.translate('Button', 'COOL END'),
        ]
        self._rail = _MilestoneRail(milestones)
        self._rail.picked.connect(self._open_milestone)
        layout.addWidget(self._rail)

        self._milestone_cards: list[_CommandCard] = []
        for i, name in enumerate(milestones):
            card = _CommandCard(name, 'buttonactions', 'buttonactionstrings', i, aw, removable=True)
            card.changed.connect(lambda i=i: self._refresh_milestone(i))
            card.cleared.connect(lambda i=i: self._close_milestone(i))
            card.setVisible(card.has_command())
            layout.addWidget(card)
            self._milestone_cards.append(card)
        self._add_hint = self._hint(QApplication.translate(
            'tilauscope_devices', '＋ Click an empty milestone to add a command.'))
        layout.addWidget(self._add_hint)
        for i in range(len(milestones)):
            self._refresh_milestone(i)

        # ── Monitoring buttons ───────────────────────────────────────────
        monitoring = QCollapsibleWidget(
            QApplication.translate('tilauscope_devices', 'Monitoring buttons'), collapsed=True)
        self._monitoring_cards = [
            _CommandCard(QApplication.translate('Button', 'RESET'),
                         'xextrabuttonactions', 'xextrabuttonactionstrings', 0, aw, removable=False),
            _CommandCard(QApplication.translate('Button', 'ON'),
                         'extrabuttonactions', 'extrabuttonactionstrings', 0, aw, removable=False),
            _CommandCard(QApplication.translate('Button', 'OFF'),
                         'extrabuttonactions', 'extrabuttonactionstrings', 1, aw, removable=False),
        ]
        for card in self._monitoring_cards:
            monitoring.content_layout.addWidget(card)
        monitoring.content_layout.addWidget(self._start_card())
        layout.addWidget(monitoring)
        layout.addStretch()

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 11px;")
        return lbl

    def _start_card(self) -> QFrame:
        """START is owned by Roast Setup (preheat): shown, never edited here."""
        qmc = self._aw.qmc
        action = qmc.xextrabuttonactions[1]
        command = qmc.xextrabuttonactionstrings[1].strip()
        if action == _IO_COMMAND and command.lower().startswith('tilaupid(start,'):
            setpoint = command.split(',', 1)[1].rstrip(')').strip()
            body = QApplication.translate('tilauscope_devices', 'Preheat to {0} °{1}').format(setpoint, qmc.mode)
        elif action == 0 and not command:
            body = QApplication.translate('tilauscope_devices', 'No preheat')
        else:
            body = f'{_action_types()[action]}: {command}'
        card = QFrame()
        card.setObjectName('cmdCard')
        card.setStyleSheet(
            f"QFrame#cmdCard {{ background: {THEME['SURFACE']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 8px; }}"
            f"QLabel {{ border: none; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel(QApplication.translate('Button', 'START'))
        title.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")
        owner = QLabel(QApplication.translate('tilauscope_devices', '🔒 set by Roast Setup'))
        owner.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px;")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(owner)
        lay.addLayout(head)
        text = QLabel(body)
        text.setStyleSheet(f"color: {THEME['TEXT']};")
        lay.addWidget(text)
        return card

    def _refresh_milestone(self, index: int) -> None:
        self._rail.set_filled(index, self._milestone_cards[index].has_command())
        self._add_hint.setVisible(any(c.isHidden() for c in self._milestone_cards))

    def _open_milestone(self, index: int) -> None:
        card = self._milestone_cards[index]
        if card.type_combo.currentData() == 0:
            # a command left on None would never be sent
            card.type_combo.setCurrentIndex(card.type_combo.findData(_IO_COMMAND))
        card.setVisible(True)
        card.command_edit.setFocus()
        self._refresh_milestone(index)

    def _close_milestone(self, index: int) -> None:
        self._milestone_cards[index].setVisible(False)
        self._refresh_milestone(index)

    def apply(self) -> None:
        """Write the tab back into Artisan's settings (Save)."""
        aw = self._aw
        qmc = aw.qmc
        names = [edit.text().strip() or qmc.etypes[i] for i, edit in enumerate(self._name_edits)]
        names_changed = names != list(qmc.etypes[:4])
        for i, name in enumerate(names):
            qmc.etypes[i] = name
        for card in (*self._milestone_cards, *self._monitoring_cards):
            card.apply(aw)
        if not names_changed:
            return
        # the refreshes Artisan's Events dialog runs after renaming
        try:
            aw.updateSlidersProperties()
            aw.establish_etypes()
            qmc.redraw(recomputeAllDeltas=False)
            main = getattr(aw, 'tilauscope_main', None)
            if main is not None and not sip.isdeleted(main):
                main.refresh_slider_names()  # before the rebuild: the event panel reads them
                main.update_events_from_artisan()
        except Exception:  # pylint: disable=broad-except
            _log.exception('refreshing the renamed controls failed')

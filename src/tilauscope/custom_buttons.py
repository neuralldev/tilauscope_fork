"""TilauScope custom event-button editor.

This is a dedicated, theme-native replacement for the dense ``EventsDlg``
Buttons table.  It deliberately writes the same nine parallel arrays, keeping
the roasting engine and the Artisan settings format unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from tilauscope.theme_qss import apply_tilau_theme
from tilauscope.tilauscope_types import THEME

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow


_ACTION_IDS: Final[list[int]] = list(range(7)) + list(range(8, 26))
_ACTION_LABELS: Final[list[str]] = [
    '—', 'Serial Command', 'Call Program', 'Multiple Event', 'Modbus Command',
    'DTA Command', 'IO Command', 'Hottop Heater', 'Hottop Fan',
    'Hottop Command', 'p-i-d', 'Fuji Command', 'PWM Command', 'VOUT Command',
    'S7 Command', 'Aillio R1 Heater', 'Aillio R1 Fan', 'Aillio R1 Drum',
    'Aillio R1 Command', 'Artisan Command', 'RC Command', 'WebSocket Command',
    'Stepper Command', 'Difluid Airwave Command', 'TilauScope Ambient Command',
]


@dataclass
class ButtonSpec:
    label: str = 'E'
    description: str = ''
    event_type: int = 4
    value: float = 0.0
    action: int = 0
    command: str = ''
    visible: bool = True
    background: str = '#808080'
    foreground: str = '#ffffff'


class CustomButtonManager(QDialog):
    """Master-detail editor backed by Artisan's existing custom-button model."""

    def __init__(self, parent: QWidget, aw: ApplicationWindow) -> None:
        super().__init__(parent)
        apply_tilau_theme(self, ground=False)
        self.aw = aw
        self._loading = False
        self._rows = self._read_rows()
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(self.tr('Custom button management'))
        self._build_ui()
        settings = QSettings()
        if settings.contains('TilauCustomButtonsGeometry'):
            self.restoreGeometry(settings.value('TilauCustomButtonsGeometry'))
        else:
            self.resize(900, 600)
        self._refresh_list(0)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {THEME['BG']}; border: 1px solid {THEME['BORDER']};"
            ' border-radius: 16px; }')
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(self.tr('CUSTOM BUTTON MANAGEMENT'))
        title.setStyleSheet(
            f"color:{THEME['ACCENT']}; font-size:16px; font-weight:900;"
            ' letter-spacing:2px; border:none;')
        close = QPushButton('✕')
        close.setFixedSize(28, 28)
        close.setProperty('variant', 'icon')
        close.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        root.addLayout(header)

        subtitle = QLabel(self.tr(
            'Arrange the buttons shown during roasting, then configure the selected button.'))
        subtitle.setProperty('variant', 'secondary')
        root.addWidget(subtitle)

        splitter = QSplitter()
        splitter.addWidget(self._build_master())
        splitter.addWidget(self._build_detail())
        splitter.setSizes([330, 560])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.max_per_row = QSpinBox()
        self.max_per_row.setRange(self.aw.buttonpalettemaxlen_min,
                                  self.aw.buttonpalettemaxlen_max)
        self.max_per_row.setValue(int(self.aw.buttonlistmaxlen))
        footer.addWidget(QLabel(self.tr('Buttons per row')))
        footer.addWidget(self.max_per_row)
        footer.addStretch()
        cancel = QPushButton(self.tr('Cancel'))
        cancel.clicked.connect(self.reject)
        save = QPushButton(self.tr('Apply'))
        save.setProperty('variant', 'primary')
        save.clicked.connect(self._apply)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    def _build_master(self) -> QWidget:
        panel = QFrame()
        panel.setProperty('variant', 'card')
        lay = QVBoxLayout(panel)
        heading = QLabel(self.tr('BUTTONS'))
        heading.setProperty('variant', 'eyebrow')
        lay.addWidget(heading)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._load_row)
        lay.addWidget(self.list, 1)
        bar = QHBoxLayout()
        for text, slot in ((self.tr('+ Add'), self._add),
                           (self.tr('Duplicate'), self._duplicate),
                           (self.tr('Delete'), self._delete)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            if text == self.tr('Delete'):
                button.setProperty('variant', 'danger-outline')
            bar.addWidget(button)
        lay.addLayout(bar)
        move = QHBoxLayout()
        up = QPushButton(self.tr('Move up'))
        down = QPushButton(self.tr('Move down'))
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        move.addWidget(up)
        move.addWidget(down)
        lay.addLayout(move)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QFrame()
        panel.setProperty('variant', 'card')
        lay = QVBoxLayout(panel)
        heading = QLabel(self.tr('SELECTED BUTTON'))
        heading.setProperty('variant', 'eyebrow')
        lay.addWidget(heading)

        self.preview = QPushButton(self.tr('Preview'))
        self.preview.setMinimumHeight(48)
        self.preview.setEnabled(False)
        lay.addWidget(self.preview)

        form = QFormLayout()
        self.label = QLineEdit()
        self.description = QLineEdit()
        self.event_type = QComboBox()
        self.event_type.addItems(['—', 'E1', 'E2', 'E3', 'E4', '±E1', '±E2',
                                  '±E3', '±E4', '±E1%', '±E2%', '±E3%', '±E4%'])
        self.value = QLineEdit()
        self.value.setPlaceholderText(self.tr('Numeric value, -999 to 999'))
        self.action = QComboBox()
        self.action.addItems([self.tr(x) for x in _ACTION_LABELS])
        self.command = QLineEdit()
        self.command.setPlaceholderText(self.tr('Command or action parameters'))
        self.visible = QCheckBox(self.tr('Visible on the roasting screen'))
        self.bg = QPushButton()
        self.fg = QPushButton()
        self.bg.clicked.connect(lambda: self._pick_color(False))
        self.fg.clicked.connect(lambda: self._pick_color(True))
        form.addRow(self.tr('Label'), self.label)
        form.addRow(self.tr('Description / tooltip'), self.description)
        form.addRow(self.tr('Event type'), self.event_type)
        form.addRow(self.tr('Event value'), self.value)
        form.addRow(self.tr('Action'), self.action)
        form.addRow(self.tr('Command / documentation'), self.command)
        form.addRow(self.tr('Visibility'), self.visible)
        colors = QHBoxLayout()
        colors.addWidget(self.bg)
        colors.addWidget(self.fg)
        form.addRow(self.tr('Button / text color'), colors)
        lay.addLayout(form)
        lay.addStretch()

        for widget in (self.label, self.description, self.value, self.command):
            widget.textChanged.connect(self._store_form)
        self.event_type.currentIndexChanged.connect(self._store_form)
        self.action.currentIndexChanged.connect(self._store_form)
        self.visible.toggled.connect(self._store_form)
        return panel

    def _read_rows(self) -> list[ButtonSpec]:
        lengths = [len(getattr(self.aw, name, [])) for name in (
            'extraeventslabels', 'extraeventsdescriptions', 'extraeventstypes',
            'extraeventsvalues', 'extraeventsactions', 'extraeventsactionstrings',
            'extraeventsvisibility', 'extraeventbuttoncolor',
            'extraeventbuttontextcolor')]
        count = min(lengths) if lengths else 0
        return [ButtonSpec(
            self.aw.extraeventslabels[i], self.aw.extraeventsdescriptions[i],
            self.aw.extraeventstypes[i], self.aw.extraeventsvalues[i],
            self.aw.extraeventsactions[i], self.aw.extraeventsactionstrings[i],
            bool(self.aw.extraeventsvisibility[i]), self.aw.extraeventbuttoncolor[i],
            self.aw.extraeventbuttontextcolor[i]) for i in range(count)]

    def _refresh_list(self, selected: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for i, row in enumerate(self._rows):
            item = QListWidgetItem(f'{i + 1:02d}   {row.label or self.tr("Untitled")}')
            item.setToolTip(row.description)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self._rows:
            self.list.setCurrentRow(min(selected or 0, len(self._rows) - 1))
        else:
            self._set_form_enabled(False)

    def _load_row(self, index: int) -> None:
        if not 0 <= index < len(self._rows):
            self._set_form_enabled(False)
            return
        self._loading = True
        row = self._rows[index]
        self._set_form_enabled(True)
        self.label.setText(row.label.replace('\n', '\\n'))
        self.description.setText(row.description)
        self.event_type.setCurrentIndex(self._event_to_combo(row.event_type))
        self.value.setText(f'{row.value:g}')
        self.action.setCurrentIndex(_ACTION_IDS.index(row.action) if row.action in _ACTION_IDS else 0)
        self.command.setText(row.command)
        self.visible.setChecked(row.visible)
        self._loading = False
        self._update_preview(row)

    def _store_form(self, *_args: object) -> None:
        if self._loading:
            return
        index = self.list.currentRow()
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        row.label = self.label.text().replace('\\n', '\n')
        row.description = self.description.text()
        row.event_type = self._combo_to_event(self.event_type.currentIndex())
        try:
            row.value = max(-999.0, min(999.0, float(self.value.text().replace(',', '.'))))
        except ValueError:
            pass
        row.action = _ACTION_IDS[self.action.currentIndex()]
        row.command = self.command.text()
        row.visible = self.visible.isChecked()
        self.list.currentItem().setText(f'{index + 1:02d}   {row.label or self.tr("Untitled")}')
        self._update_preview(row)

    def _update_preview(self, row: ButtonSpec) -> None:
        text = row.label.replace('\n', ' / ') or self.tr('Untitled')
        self.preview.setText(text)
        self.preview.setStyleSheet(
            f'background:{row.background}; color:{row.foreground};'
            f' border:1px solid {THEME["BORDER"]}; border-radius:8px; font-weight:bold;')
        self.bg.setText(row.background)
        self.fg.setText(row.foreground)

    def _pick_color(self, foreground: bool) -> None:
        index = self.list.currentRow()
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        current = row.foreground if foreground else row.background
        color = QColorDialog.getColor(QColor(current), self)
        if color.isValid():
            if foreground:
                row.foreground = color.name()
            else:
                row.background = color.name()
            self._update_preview(row)

    def _add(self) -> None:
        limit = self.aw.buttonlistmaxlen * self.aw.max_palettes
        if len(self._rows) < limit:
            self._rows.append(ButtonSpec())
            self._refresh_list(len(self._rows) - 1)

    def _duplicate(self) -> None:
        index = self.list.currentRow()
        if 0 <= index < len(self._rows):
            row = self._rows[index]
            self._rows.insert(index + 1, ButtonSpec(**vars(row)))
            self._refresh_list(index + 1)

    def _delete(self) -> None:
        index = self.list.currentRow()
        if 0 <= index < len(self._rows):
            self._rows.pop(index)
            self._refresh_list(index)

    def _move(self, delta: int) -> None:
        index = self.list.currentRow()
        target = index + delta
        if 0 <= index < len(self._rows) and 0 <= target < len(self._rows):
            self._rows[index], self._rows[target] = self._rows[target], self._rows[index]
            self._refresh_list(target)

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (self.preview, self.label, self.description, self.event_type,
                       self.value, self.action, self.command, self.visible,
                       self.bg, self.fg):
            widget.setEnabled(enabled)

    @staticmethod
    def _event_to_combo(event_type: int) -> int:
        if event_type == 4:
            return 0
        if 0 <= event_type <= 3:
            return event_type + 1
        if 5 <= event_type <= 12:
            return event_type
        return 0

    @staticmethod
    def _combo_to_event(index: int) -> int:
        if index == 0:
            return 4
        if 1 <= index <= 4:
            return index - 1
        return index

    def _apply(self) -> None:
        self._store_form()
        self.aw.extraeventslabels = [r.label for r in self._rows]
        self.aw.extraeventsdescriptions = [r.description for r in self._rows]
        self.aw.extraeventstypes = [r.event_type for r in self._rows]
        self.aw.extraeventsvalues = [r.value for r in self._rows]
        self.aw.extraeventsactions = [r.action for r in self._rows]
        self.aw.extraeventsactionstrings = [r.command for r in self._rows]
        self.aw.extraeventsvisibility = [int(r.visible) for r in self._rows]
        self.aw.extraeventbuttoncolor = [r.background for r in self._rows]
        self.aw.extraeventbuttontextcolor = [r.foreground for r in self._rows]
        self.aw.buttonlistmaxlen = self.max_per_row.value()
        self.aw.update_extraeventbuttons_visibility()
        self.accept()

    def done(self, result: int) -> None:
        QSettings().setValue('TilauCustomButtonsGeometry', self.saveGeometry())
        super().done(result)


def open_custom_button_manager(aw: ApplicationWindow) -> None:
    """Menu entry point."""
    CustomButtonManager(aw, aw).exec()

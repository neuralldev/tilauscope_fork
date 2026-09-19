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

"""The Devices window: ROASTER, EXTRA DEVICES and AMBIENT.

Every widget edits the draft; Save hands it to ``draft.apply`` and Cancel drops
it. What the window does not cover stays one click away in Artisan's own device
and port dialogs. EXTRA DEVICES is laid out like the alarm editor: a command bar
acting on the selected card, and cards dragged into order by their grip.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMenu, QMessageBox, QPushButton, QScrollArea,
                             QSizeGrip, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from tilauscope.device_setup import catalogue, draft
from tilauscope.device_setup.extra_card import EXTRA_DEVICE_MIME, ExtraDeviceCard
from tilauscope.theme_qss import base_qss, style_combo_popup, tooltip_qss
from tilauscope.tilauscope_types import THEME, no_enter_default, show_styled_message
from tilauscope.widgets.config_parts import (QCollapsibleWidget, close_button, config_card,
                                             config_dialog_qss, config_tabs_qss, dialog_title,
                                             field_label, scrollable, separator,
                                             styled_combo_view, toolbar_button)
from tilauscope.widgets.controls import ReorderDropBody, SegmentedControl

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401

_log: Final[logging.Logger] = logging.getLogger(__name__)

_METER: Final[int] = 0
_TC4: Final[int] = 1
_TAB_EXTRAS: Final[int] = 1
_TAB_AMBIENT: Final[int] = 2
_TC4_CHANNELS: Final[tuple[str, ...]] = ('None', '1', '2', '3', '4')
_TC4_AMBIENT: Final[tuple[str, ...]] = ('None', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6')
_LABEL_W: Final[int] = 190


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty('variant', 'caption')
    label.setWordWrap(True)
    return label


def _frameless(dialog: QDialog) -> None:
    # A plain Dialog, not a Tool window: on macOS a Tool window never becomes
    # key, and the first click on Save would only activate it.
    dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.WindowStaysOnTopHint
                          | Qt.WindowType.Dialog)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setModal(True)
    dialog.setStyleSheet(base_qss(ground=False) + config_dialog_qss())


def _footer_button(text: str, variant: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName('footerBtn')
    button.setProperty('variant', variant)
    return button


class _DragToMove:
    """Frameless windows move by their card."""

    _drag_pos: Any = None

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)  # type: ignore[misc]

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)  # type: ignore[attr-defined]
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)  # type: ignore[misc]

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)  # type: ignore[misc]


class _OtherDevicePicker(_DragToMove, QDialog):
    """Any extra device Artisan knows, filtered as you type."""

    def __init__(self, parent: QWidget, title: str, confirm: str) -> None:
        super().__init__(parent)
        _frameless(self)
        self.selected: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card, layout = config_card()
        outer.addWidget(card)
        layout.addWidget(dialog_title(title))

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(QApplication.translate('tilauscope_devices', 'Search devices'))
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = QListWidget()
        self._list.addItems(list(catalogue.artisan_extra_names()))
        self._list.setStyleSheet(
            f"QListWidget {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f" border: 1px solid {THEME['BORDER']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 4px 8px; }}"
            f"QListWidget::item:selected {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}")
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        cancel = _footer_button(QApplication.translate('tilauscope_devices', 'Cancel'), 'outline')
        cancel.clicked.connect(self.reject)
        ok = _footer_button(confirm, 'primary')
        ok.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self.resize(420, 480)
        no_enter_default(self)

    @pyqtSlot(str)
    def _apply_filter(self, text: str) -> None:
        wanted = text.casefold()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is not None:
                item.setHidden(wanted not in item.text().casefold())

    def accept(self) -> None:
        item = self._list.currentItem()
        if item is None or item.isHidden():
            return
        self.selected = item.text()
        super().accept()


class DeviceSetupDialog(_DragToMove, QDialog):
    """What reads the roaster, the extra devices behind the counters, the room readings."""

    def __init__(self, parent: QWidget, aw: 'ApplicationWindow') -> None:
        super().__init__(parent)
        self.aw = aw
        self._capacity = int(aw.nLCDS)
        self._original = draft.snapshot(aw)
        self._draft = copy.deepcopy(self._original)
        self._ambient_items: dict[str, list[tuple[str, draft.Source]]] = {}
        self._selected_uid: int | None = None
        self._cards_by_uid: dict[int, ExtraDeviceCard] = {}
        _frameless(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)   # each opening builds a new window
        self._build_ui()
        self.setMinimumSize(660, 540)
        self.resize(740, 640)
        no_enter_default(self)

    # ── shell ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card, layout = config_card()
        outer.addWidget(card)

        title_row = QHBoxLayout()
        title_row.addWidget(dialog_title(QApplication.translate('tilauscope_devices', 'DEVICES')))
        title_row.addStretch()
        close = close_button()
        close.clicked.connect(self.reject)
        title_row.addWidget(close)
        layout.addLayout(title_row)
        layout.addWidget(separator())

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(config_tabs_qss())
        tab_qss = 'QWidget { background: transparent; }' + tooltip_qss()
        pages = []
        for title in (QApplication.translate('tilauscope_devices', 'ROASTER'),
                      QApplication.translate('tilauscope_devices', 'EXTRA DEVICES'),
                      QApplication.translate('tilauscope_devices', 'AMBIENT')):
            page = QWidget()
            page.setStyleSheet(tab_qss)
            self._tabs.addTab(page, title)
            pages.append(page)
        self._build_roaster_tab(pages[0])
        self._build_extras_tab(pages[1])
        self._build_ambient_tab(pages[2])
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        layout.addWidget(separator())
        footer = QHBoxLayout()
        footer.setSpacing(12)
        cancel = _footer_button(QApplication.translate('tilauscope_devices', 'Cancel'), 'outline')
        cancel.clicked.connect(self.reject)
        save = _footer_button(QApplication.translate('tilauscope_devices', 'Save'), 'primary')
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)

        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip_row.addWidget(QSizeGrip(self), 0,
                           Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(grip_row)

    @pyqtSlot(int)
    def _on_tab_changed(self, index: int) -> None:
        if index == _TAB_AMBIENT:
            self._refresh_ambient()   # names edited on the cards show up here

    # ── ROASTER ──────────────────────────────────────────────────────────────

    def _build_roaster_tab(self, page: QWidget) -> None:
        layout = scrollable(page).widget().layout()
        layout.addWidget(_caption(QApplication.translate(
            'tilauscope_devices', 'Choose how TilauScope reads bean and environment temperatures.')))

        self._mode = SegmentedControl([QApplication.translate('tilauscope_devices', 'Meter'),
                                       QApplication.translate('tilauscope_devices', 'TC4 board')])
        self._mode.set_current({'meter': _METER, 'tc4': _TC4}.get(self._draft.mode, -1))
        self._mode.changed.connect(self._on_mode_changed)
        layout.addWidget(self._mode)

        self._other_note = _caption(QApplication.translate(
            'tilauscope_devices',
            "The current connection is set in Artisan's device settings. "
            "Choose Meter or TC4 board to replace it."))
        layout.addWidget(self._other_note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self._meter_label = field_label(QApplication.translate('tilauscope_devices', 'Meter'), _LABEL_W)
        self._meter_combo = self._build_meter_combo()
        grid.addWidget(self._meter_label, 0, 0)
        grid.addWidget(self._meter_combo, 0, 1)
        self._meter_hint = _caption(QApplication.translate(
            'tilauscope_devices', 'Bluetooth link chosen in TilauScope Config › Sensors.'))
        grid.addWidget(self._meter_hint, 1, 1)

        self._connection_label = field_label(
            QApplication.translate('tilauscope_devices', 'Connection settings'), _LABEL_W)
        self._connection_btn = QPushButton(
            QApplication.translate('tilauscope_devices', 'Open Artisan port settings'))
        self._connection_btn.setProperty('variant', 'outline')
        self._connection_btn.clicked.connect(lambda _checked=False: self._leave_for_artisan(self.aw.setcommport))
        grid.addWidget(self._connection_label, 2, 0)
        grid.addWidget(self._connection_btn, 2, 1, Qt.AlignmentFlag.AlignLeft)

        from artisanlib.dialogs import PortComboBox  # Artisan's own port list: same filters, same names
        self._port_label = field_label(QApplication.translate('tilauscope_devices', 'USB port'), _LABEL_W)
        self._port_combo = PortComboBox(selection=self._draft.comport or None)
        self._port_combo.setView(styled_combo_view())
        style_combo_popup(self._port_combo)
        grid.addWidget(self._port_label, 3, 0)
        grid.addWidget(self._port_combo, 3, 1)
        layout.addLayout(grid)

        self._tc4_box = QWidget()
        tc4 = QGridLayout(self._tc4_box)
        tc4.setContentsMargins(0, 0, 0, 0)
        tc4.setHorizontalSpacing(12)
        tc4.setVerticalSpacing(10)
        tc4.setColumnStretch(2, 1)
        et, bt, at = self._draft.tc4_channels
        self._tc4_bt = self._channel_combo(_TC4_CHANNELS, bt)
        self._tc4_et = self._channel_combo(_TC4_CHANNELS, et)
        self._tc4_at = self._channel_combo(_TC4_AMBIENT, at)
        for r, (label, combo) in enumerate((
                (QApplication.translate('tilauscope_devices', 'Bean temperature (BT)'), self._tc4_bt),
                (QApplication.translate('tilauscope_devices', 'Environment temperature (ET)'), self._tc4_et),
                (QApplication.translate('tilauscope_devices', 'Board ambient (AT)'), self._tc4_at))):
            tc4.addWidget(field_label(label, _LABEL_W), r, 0)
            tc4.addWidget(combo, r, 1)
        self._pid_firmware = QCheckBox(QApplication.translate('tilauscope_devices', 'Board runs PID firmware'))
        self._pid_firmware.setChecked(self._draft.pid_firmware)
        tc4.addWidget(self._pid_firmware, 3, 0, 1, 3)

        smoothing = QCollapsibleWidget(QApplication.translate('tilauscope_devices', 'Signal smoothing'),
                                       collapsed=True)
        spins_row = QHBoxLayout()
        self._tc4_filter: list[QSpinBox] = []
        for i, value in enumerate(self._draft.tc4_filter):
            spins_row.addWidget(QLabel(QApplication.translate('tilauscope_devices', 'Channel {0}').format(i + 1)))
            spin = QSpinBox()
            spin.setRange(0, 99)
            spin.setSingleStep(5)
            spin.setSuffix(' %')
            spin.setValue(value)
            self._tc4_filter.append(spin)
            spins_row.addWidget(spin)
            spins_row.addSpacing(10)
        spins_row.addStretch()
        smoothing.content_layout.addLayout(spins_row)
        tc4.addWidget(smoothing, 4, 0, 1, 3)
        layout.addWidget(self._tc4_box)

        layout.addStretch(1)
        link = QHBoxLayout()
        link.addWidget(_caption(QApplication.translate(
            'tilauscope_devices', 'Need network, Modbus or Phidget options?')), 1)
        artisan = QPushButton(QApplication.translate('tilauscope_devices', 'Open Artisan device settings'))
        artisan.setProperty('variant', 'outline')
        artisan.clicked.connect(lambda _checked=False: self._leave_for_artisan(self.aw.deviceassigment))
        link.addWidget(artisan)
        layout.addLayout(link)

        self._sync_roaster()

    @staticmethod
    def _channel_combo(values: tuple[str, ...], current: str) -> QComboBox:
        combo = QComboBox()
        combo.setView(styled_combo_view())
        style_combo_popup(combo)
        for value in values:
            text = QApplication.translate('tilauscope_devices', 'None') if value == 'None' else value
            combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _build_meter_combo(self) -> QComboBox:
        names = catalogue.meter_names()
        combo = QComboBox()
        combo.setPlaceholderText(QApplication.translate('tilauscope_devices', 'Choose a meter'))
        model = QStandardItemModel(combo)

        def heading(text: str) -> QStandardItem:
            item = QStandardItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(THEME['SUBTEXT']))
            return item

        model.appendRow(heading(QApplication.translate('tilauscope_devices', 'TilauScope meters')))
        for name in catalogue.PINNED_METERS:
            if name in names:
                model.appendRow(QStandardItem(name))
        model.appendRow(heading(QApplication.translate('tilauscope_devices', 'All meters')))
        for name in names:
            model.appendRow(QStandardItem(name))
        combo.setModel(model)
        combo.setView(styled_combo_view())
        style_combo_popup(combo)
        combo.activated.connect(self._on_meter_activated)
        self._show_meter(combo, self._draft.meter)
        return combo

    @staticmethod
    def _show_meter(combo: QComboBox, name: str | None) -> None:
        model = combo.model()
        combo.blockSignals(True)
        row = -1
        if name and isinstance(model, QStandardItemModel):
            row = next((i for i in range(model.rowCount())
                        if model.item(i).isEnabled() and model.item(i).text() == name), -1)
        combo.setCurrentIndex(row)   # -1 shows the placeholder
        combo.blockSignals(False)

    def _choose_meter(self, name: str) -> None:
        if name not in catalogue.meter_names():
            return
        self._draft.meter = name
        self._show_meter(self._meter_combo, name)
        self._sync_roaster()

    @pyqtSlot(int)
    def _on_meter_activated(self, index: int) -> None:
        self._choose_meter(self._meter_combo.itemText(index))

    @pyqtSlot(int)
    def _on_mode_changed(self, index: int) -> None:
        self._draft.mode = 'meter' if index == _METER else 'tc4'
        self._sync_roaster()
        if self._draft.mode == 'meter' and not self._draft.meter:
            self._meter_combo.setFocus()

    def _sync_roaster(self) -> None:
        mode, meter = self._draft.mode, self._draft.meter
        in_meter = mode == 'meter'
        self._other_note.setVisible(mode == 'other')
        self._meter_label.setVisible(in_meter)
        self._meter_combo.setVisible(in_meter)
        self._meter_hint.setVisible(in_meter and meter in catalogue.BLUETOOTH_METERS)
        via_port_dialog = in_meter and meter in catalogue.PORT_DIALOG_METERS
        self._connection_label.setVisible(via_port_dialog)
        self._connection_btn.setVisible(via_port_dialog)
        usb = draft.uses_usb_port(self._draft)
        self._port_label.setVisible(usb)
        self._port_combo.setVisible(usb)
        self._tc4_box.setVisible(mode == 'tc4')

    # ── EXTRA DEVICES ────────────────────────────────────────────────────────

    def _build_extras_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 8)
        layout.setSpacing(10)
        layout.addWidget(_caption(QApplication.translate(
            'tilauscope_devices',
            'Extra devices add counters under the roast curve — airflow, room conditions, crack counts.')))

        # the alarm editor's command bar: each command acts on the selected card
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._btn_add = toolbar_button(QApplication.translate('tilauscope_devices', 'Add') + '  ▾',
                                       accent=THEME['SUCCESS'])
        self._btn_add.clicked.connect(
            lambda _checked=False: self._show_device_menu(self._btn_add, self._add_kind, self._add_other))
        self._btn_change = toolbar_button(QApplication.translate('tilauscope_devices', 'Change device') + '  ▾')
        self._btn_change.clicked.connect(
            lambda _checked=False: self._show_device_menu(self._btn_change, self._change_to_kind,
                                                          self._change_to_other))
        self._btn_delete = toolbar_button(QApplication.translate('tilauscope_devices', 'Delete'))
        self._btn_delete.clicked.connect(lambda _checked=False: self._on_delete())
        for button in (self._btn_add, self._btn_change, self._btn_delete):
            bar.addWidget(button)
        bar.addStretch()
        self._slots = QLabel()
        self._slots.setProperty('variant', 'caption')
        bar.addWidget(self._slots)
        layout.addLayout(bar)

        self._empty_extras = QWidget()
        empty = QVBoxLayout(self._empty_extras)
        empty.setContentsMargins(0, 8, 0, 8)
        heading = QLabel(QApplication.translate('tilauscope_devices', 'No extra devices yet.'))
        heading.setProperty('variant', 'title')
        empty.addWidget(heading)
        empty.addWidget(_caption(QApplication.translate(
            'tilauscope_devices',
            'Add one to see airflow, room conditions or crack counts under your roast curve.')))
        layout.addWidget(self._empty_extras)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        self._cards_body = ReorderDropBody(EXTRA_DEVICE_MIME, self._on_card_dropped)
        self._cards = QVBoxLayout(self._cards_body)
        self._cards.setContentsMargins(0, 0, 4, 0)
        self._cards.setSpacing(6)
        scroll.setWidget(self._cards_body)
        layout.addWidget(scroll, 1)

        self._full = _caption(QApplication.translate(
            'tilauscope_devices', 'All {0} slots are used — remove a device to add another.'
        ).format(self._capacity))
        self._full.setStyleSheet(f"color: {THEME['WARNING']};")
        layout.addWidget(self._full)
        layout.addWidget(_caption(QApplication.translate(
            'tilauscope_devices', "Phidget formulas and curve colours are in Artisan's device settings.")))
        self._rebuild_cards()

    def _show_device_menu(self, anchor: QPushButton, on_kind: Callable[[str], None],
                          on_other: Callable[[], None]) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f" border: 1px solid {THEME['BORDER']}; padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 18px; }}"
            f"QMenu::item:selected {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}"
            f"QMenu::item:disabled {{ color: {THEME['SUBTEXT']}; font-weight: bold; }}"
            f"QMenu::separator {{ height: 1px; background: {THEME['BORDER']}; margin: 4px 8px; }}")
        for group in catalogue.GROUPS:
            menu.addAction(catalogue.group_title(group)).setEnabled(False)
            for kind in catalogue.EXTRA_KINDS:
                if kind.group == group:
                    action = menu.addAction('    ' + catalogue.kind_title(kind))
                    action.triggered.connect(lambda _checked=False, key=kind.key: on_kind(key))
            menu.addSeparator()
        other = menu.addAction(QApplication.translate('tilauscope_devices', 'Other Artisan device…'))
        other.triggered.connect(lambda _checked=False: on_other())
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _pick_other_device(self, title: str, confirm: str) -> int | None:
        picker = _OtherDevicePicker(self, title, confirm)
        if not picker.exec() or picker.selected is None:
            return None
        return catalogue.extra_device_id(picker.selected)

    def _row_title(self, row: draft.ExtraRow) -> str:
        kind = catalogue.kind_of(row.device_id)
        return catalogue.kind_title(kind) if kind is not None else catalogue.device_title(row.device_id)

    def _reader_title(self, reader: draft.ExtraRow | str) -> str:
        """A card's title, or ET / BT for Artisan's own formulas, rate of rise included."""
        if isinstance(reader, str):
            return self.aw.qmc.device_name_subst(self.aw.BTname if 'BT' in reader else self.aw.ETname)
        return self._row_title(reader)

    def _selected_row(self) -> draft.ExtraRow | None:
        return next((row for row in self._draft.rows if row.uid == self._selected_uid), None)

    @pyqtSlot(int)
    def _select(self, uid: int) -> None:
        self._selected_uid = uid
        for card_uid, card in self._cards_by_uid.items():
            card.set_selected(card_uid == uid)
        self._sync_extras_bar()

    def _sync_extras_bar(self) -> None:
        count = len(self._draft.rows)
        selected = self._selected_row() is not None
        self._btn_add.setEnabled(count < self._capacity)
        self._btn_change.setEnabled(selected)
        self._btn_delete.setEnabled(selected)
        self._slots.setText(QApplication.translate('tilauscope_devices', '{0} of {1} used')
                            .format(count, self._capacity))
        self._full.setVisible(count >= self._capacity)
        self._empty_extras.setVisible(count == 0)

    def _rebuild_cards(self) -> None:
        # hiding a card hands a name field's focus to the next card, which would select itself
        for card in self._cards_by_uid.values():
            card.blockSignals(True)
        while self._cards.count():
            item = self._cards.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._cards_by_uid = {}
        if self._selected_row() is None:
            self._selected_uid = None
        misordered = QApplication.translate(
            'tilauscope_devices',
            'Reads nothing — temperature & humidity must come before it. '
            'Drag it below temperature & humidity.')
        for row in self._draft.rows:
            kind = catalogue.kind_of(row.device_id)
            used = (bool(kind.names[0]), bool(kind.names[1])) if kind is not None else (True, True)
            warning = misordered if draft.is_misordered(self._draft, row) else ''
            below = draft.calculated_reading_below(self._draft, row)
            if not warning and below is not None:
                warning = QApplication.translate(
                    'tilauscope_devices',
                    'Reads {0} before its formula — {0} must come before it. Drag it below {0}.'
                ).format(self._row_title(below))
            card = ExtraDeviceCard(row, self._row_title(row), used, warning,
                                   self.aw.qmc.device_name_subst)
            card.set_selected(row.uid == self._selected_uid)
            card.clicked.connect(self._select)
            self._cards.addWidget(card)
            self._cards_by_uid[row.uid] = card
        self._cards.addStretch(1)
        self._sync_extras_bar()

    def _no_room(self) -> None:
        show_styled_message(
            self, QApplication.translate('tilauscope_devices', 'Devices'),
            QApplication.translate('tilauscope_devices',
                                   'All {0} slots are used — remove a device to add another.'
                                   ).format(self._capacity),
            QMessageBox.Icon.Information)

    def _add_kind(self, key: str) -> None:
        added = draft.add_kind(self._draft, key, self._capacity)
        if not added:
            self._no_room()
            return
        self._selected_uid = added[-1].uid
        self._devices_changed()

    def _add_other(self) -> None:
        device_id = self._pick_other_device(
            QApplication.translate('tilauscope_devices', 'ADD A DEVICE'),
            QApplication.translate('tilauscope_devices', 'Add'))
        if device_id is None:
            return
        row = draft.add_device(self._draft, device_id, self._capacity)
        if row is None:
            self._no_room()
            return
        self._selected_uid = row.uid
        self._devices_changed()

    def _change_to_kind(self, key: str) -> None:
        row = self._selected_row()
        if row is not None:
            draft.change_device(self._draft, row, catalogue.kind_by_key(key).device_id())
            self._devices_changed()

    def _change_to_other(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        device_id = self._pick_other_device(
            QApplication.translate('tilauscope_devices', 'CHANGE DEVICE'),
            QApplication.translate('tilauscope_devices', 'Change'))
        if device_id is not None:
            draft.change_device(self._draft, row, device_id)
            self._devices_changed()

    def _on_delete(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        readers = draft.formula_readers(self._draft, row)
        if readers:
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Delete device'),
                QApplication.translate('tilauscope_devices',
                                       "Used in the formula of {0}. Change that formula in Artisan's "
                                       'device settings first, then delete this device.'
                                       ).format(', '.join(dict.fromkeys(self._reader_title(r) for r in readers))),
                QMessageBox.Icon.Information)
            return
        if draft.is_pid_input(self._draft, row):
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Delete device'),
                QApplication.translate('tilauscope_devices',
                                       'Used as the PID input. Choose another PID input in the PID settings '
                                       'first, then delete this device.'),
                QMessageBox.Icon.Information)
            return
        dependents = draft.dependents(self._draft, row)
        if dependents:
            reply = show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Delete device'),
                QApplication.translate('tilauscope_devices',
                                       '{0} is read through this device and will be deleted too.'
                                       ).format(', '.join(self._row_title(d) for d in dependents)),
                QMessageBox.Icon.Question,
                buttons=[QApplication.translate('tilauscope_devices', 'Delete both'),
                         QApplication.translate('tilauscope_devices', 'Cancel')])
            if reply != 0:
                return
        index = draft.row_index(self._draft, row.uid) or 0
        draft.remove_row(self._draft, row)
        rows = self._draft.rows
        self._selected_uid = rows[min(index, len(rows) - 1)].uid if rows else None
        self._devices_changed()

    def _on_card_dropped(self, uid: int, global_y: int) -> None:
        """Insert the dragged card before the first card whose middle is below the drop."""
        others = [row for row in self._draft.rows if row.uid != uid]
        index = len(others)
        for i, row in enumerate(others):
            card = self._cards_by_uid.get(row.uid)
            if card is not None and card.mapToGlobal(QPoint(0, card.height() // 2)).y() > global_y:
                index = i
                break
        self._selected_uid = uid
        if draft.move_row(self._draft, uid, index):
            self._devices_changed()

    def _devices_changed(self) -> None:
        # a drop is delivered while the dragged card is still on the stack: rebuild after it
        QTimer.singleShot(0, self._rebuild_cards)
        self._refresh_ambient()

    # ── AMBIENT ──────────────────────────────────────────────────────────────

    def _build_ambient_tab(self, page: QWidget) -> None:
        layout = scrollable(page).widget().layout()
        layout.addWidget(_caption(QApplication.translate(
            'tilauscope_devices',
            'Room conditions are saved with every roast so roasts from different seasons can be compared.')))

        self._probe_banner = QFrame()
        self._probe_banner.setProperty('variant', 'card')
        banner = QVBoxLayout(self._probe_banner)
        banner.setContentsMargins(14, 10, 14, 12)
        found = QLabel(QApplication.translate('tilauscope_devices', 'TilauAmbient probe found.'))
        found.setProperty('variant', 'title')
        use = QPushButton(QApplication.translate('tilauscope_devices',
                                                 'Use it for temperature, humidity and pressure'))
        use.setProperty('variant', 'primary')
        use.clicked.connect(lambda _checked=False: self._use_tilauambient())
        banner.addWidget(found)
        banner.addWidget(use, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._probe_banner)

        self._ambient_empty = QWidget()
        empty = QHBoxLayout(self._ambient_empty)
        empty.setContentsMargins(0, 0, 0, 0)
        empty.addWidget(_caption(QApplication.translate(
            'tilauscope_devices', 'No extra device provides room readings yet.')), 1)
        go = QPushButton(QApplication.translate('tilauscope_devices', 'Go to Extra devices'))
        go.setProperty('variant', 'outline')
        go.clicked.connect(lambda _checked=False: self._tabs.setCurrentIndex(_TAB_EXTRAS))
        empty.addWidget(go)
        layout.addWidget(self._ambient_empty)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        qmc = self.aw.qmc
        sensors = {'temperature': qmc.temperaturedevicefunctionlist,
                   'humidity': qmc.humiditydevicefunctionlist,
                   'pressure': qmc.pressuredevicefunctionlist}
        self._ambient_widgets: dict[str, QWidget] = {}
        for r, (key, label) in enumerate((
                ('temperature', QApplication.translate('tilauscope_devices', 'Temperature')),
                ('humidity', QApplication.translate('tilauscope_devices', 'Humidity')),
                ('pressure', QApplication.translate('tilauscope_devices', 'Pressure')))):
            grid.addWidget(field_label(label, 120), r, 0)
            hardware = self._draft.ambient_hardware[key]
            if hardware:
                names = sensors[key]
                widget: QWidget = _caption(QApplication.translate(
                    'tilauscope_devices', "{0} — set in Artisan's device settings."
                ).format(names[hardware] if hardware < len(names) else ''))
            else:
                combo = QComboBox()
                combo.setView(styled_combo_view())
                style_combo_popup(combo)
                combo.currentIndexChanged.connect(self._ambient_slot(key))
                widget = combo
            grid.addWidget(widget, r, 1)
            self._ambient_widgets[key] = widget
        layout.addLayout(grid)
        layout.addStretch(1)
        self._refresh_ambient()

    def _ambient_slot(self, key: str) -> Callable[[int], None]:
        def changed(index: int) -> None:
            items = self._ambient_items.get(key, [])
            if 0 <= index < len(items):
                self._draft.ambient[key] = items[index][1]
            self._sync_probe_banner()
        return changed

    def _refresh_ambient(self) -> None:
        subst = self.aw.qmc.device_name_subst
        choices: list[tuple[str, draft.Source]] = [
            (QApplication.translate('tilauscope_devices', 'None'), 0)]
        for row in self._draft.rows:
            kind = catalogue.kind_of(row.device_id)
            for channel in (1, 2):
                if kind is not None and not kind.names[channel - 1]:
                    continue
                choices.append((f'{catalogue.device_title(row.device_id)} · {subst(row.names[channel - 1])}',
                                (row.uid, channel)))
        for key, widget in self._ambient_widgets.items():
            if not isinstance(widget, QComboBox):
                continue
            current = self._draft.ambient[key]
            items = list(choices)
            if current in (1, 2):   # ET or BT, set in Artisan: shown so it is never dropped unseen
                items.insert(1, (subst(self.aw.ETname if current == 1 else self.aw.BTname), current))
            index = next((i for i, (_text, source) in enumerate(items) if source == current), 0)
            self._draft.ambient[key] = items[index][1]
            self._ambient_items[key] = items
            widget.blockSignals(True)
            widget.clear()
            for text, _source in items:
                widget.addItem(text)
            widget.setCurrentIndex(index)
            widget.blockSignals(False)
        self._ambient_empty.setVisible(not self._draft.rows and not self._probe_paired())
        self._sync_probe_banner()

    def _probe_paired(self) -> bool:
        return bool(getattr(self.aw, 'bleTilauScopeDeviceName', None))

    def _sync_probe_banner(self) -> None:
        self._probe_banner.setVisible(self._probe_paired() and not draft.tilauambient_in_use(self._draft))

    def _use_tilauambient(self) -> None:
        if not draft.use_tilauambient(self._draft, self._capacity):
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'TilauAmbient needs free slots. Remove an extra device first.'),
                QMessageBox.Icon.Information)
            return
        self._devices_changed()

    # ── leaving ──────────────────────────────────────────────────────────────

    def _read_widgets(self) -> None:
        """The ROASTER fields the draft does not follow live."""
        d = self._draft
        d.tc4_channels = [self._tc4_et.currentData(), self._tc4_bt.currentData(), self._tc4_at.currentData()]
        d.tc4_filter = [spin.value() for spin in self._tc4_filter]
        d.pid_firmware = self._pid_firmware.isChecked()
        if draft.uses_usb_port(d):
            d.comport = self._port_combo.getSelection() or d.comport

    def _leave_for_artisan(self, opener: Callable[[], Any]) -> None:
        self._read_widgets()
        if self._draft != self._original:
            reply = show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'The changes made in this window will be discarded.'),
                QMessageBox.Icon.Question,
                buttons=[QApplication.translate('tilauscope_devices', 'Discard and open'),
                         QApplication.translate('tilauscope_devices', 'Cancel')])
            if reply != 0:
                return
        self.reject()
        QTimer.singleShot(0, opener)

    @pyqtSlot()
    def _on_save(self) -> None:
        aw = self.aw
        if aw.qmc.flagon:
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'Devices cannot be changed while the roaster is being read. '
                                       'Turn monitoring off first.'),
                QMessageBox.Icon.Warning)
            return
        if draft.is_stale(aw, self._original):
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'The devices changed while this window was open, usually because '
                                       'a roast file was loaded. Nothing was saved — open Devices again.'),
                QMessageBox.Icon.Warning)
            self.reject()
            return
        self._read_widgets()
        d = self._draft
        if d.mode == 'meter' and not d.meter:
            self._tabs.setCurrentIndex(0)
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices', 'Choose a meter, or switch to TC4 board.'),
                QMessageBox.Icon.Information)
            return
        kept = {row.origin for row in d.rows if row.origin is not None}
        removed = [row for row in self._original.rows if row.origin not in kept]
        if removed and len(aw.qmc.timex) > 0:
            reply = show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'Removing {0} also removes its readings from the roast that is '
                                       'open. Save anyway?').format(', '.join(self._row_title(r) for r in removed)),
                QMessageBox.Icon.Question,
                buttons=[QApplication.translate('tilauscope_devices', 'Save'),
                         QApplication.translate('tilauscope_devices', 'Cancel')])
            if reply != 0:
                return
        try:
            draft.apply(aw, d, self._original, parent=self)
        except Exception:  # pylint: disable=broad-except
            _log.exception('saving the Devices window failed')
            show_styled_message(
                self, QApplication.translate('tilauscope_devices', 'Devices'),
                QApplication.translate('tilauscope_devices',
                                       'Saving the devices failed. The log has the details.'),
                QMessageBox.Icon.Critical)
        self.accept()

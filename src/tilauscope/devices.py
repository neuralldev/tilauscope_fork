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
# -*- coding: utf-8 -*-


import os
import re
import logging
from pathlib import Path
from typing import Final, TYPE_CHECKING

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow  # noqa: F401
    from tilauscope.tilauscope_types import MQTTSensorConfig  # noqa: F401
    from tilauscope.mqttbridge import MQTTConfig  # noqa: F401

_log:  Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")

from PyQt6.QtCore    import (Qt, pyqtSlot, QPropertyAnimation, QEasingCurve,
                            QSettings, QStandardPaths)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QCheckBox, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QFormLayout, QPushButton, QSpinBox, QTabWidget,
    QComboBox, QGridLayout, QDialog, QGroupBox,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView, QDoubleSpinBox,
    QFrame, QSizeGrip, QScrollArea, QListView, QSizePolicy, QStyledItemDelegate,
    QFileDialog,
)
from PyQt6.QtGui import QCursor, QPalette, QColor

from tilauscope.theme_qss import base_qss
from tilauscope.tilauscope_types import THEME, show_styled_message, TilauProgress


# ─────────────────────────────────────────────────────────────────────────────
# Stylesheet helpers  (local — mirrors roast_properties pattern)
# ─────────────────────────────────────────────────────────────────────────────

# What this dialog needs on top of theme_qss.base_qss(): only rules that
# differ from the base, each with its own reason. See wiki/Theme-QSS-Spec.md.
def _local_style() -> str:
    return f"""
        /* combobox-popup is behaviour, not decoration: without it Qt shows a
           native popup menu on macOS that no stylesheet can reach. */
        QComboBox {{ combobox-popup: 1; }}
        QComboBox::drop-down {{ border: none; }}

        /* Inline cell editor: Qt paints it over the cell without clearing it,
           so an unstyled (transparent) editor shows the old text underneath. */
        QTableWidget QLineEdit, QTableWidget QAbstractItemView QLineEdit {{
            background: {THEME['BG']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['ACCENT']};
            border-radius: 3px;
            padding: 1px 3px;
            margin: 0px;
            font-size: 12px;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}

        /* Section headings are set as spaced small caps throughout this
           dialog — the tab bar and the group boxes have to agree. */
        QGroupBox {{
            color: {THEME['SUBTEXT']};
            font-size: 11px;
            font-weight: bold;
            letter-spacing: 1.5px;
            padding-top: 6px;
        }}
        QGroupBox::title {{ subcontrol-position: top left; padding: 0 6px; }}

        /* Save / Cancel close the window — deliberately larger than the
           inline action buttons inside the tabs. */
        QPushButton#footerBtn {{
            border-radius: 8px;
            font-size: 13px;
            padding: 9px 24px;
        }}

        /* A dense settings window: the 12px base scrollbar eats the width the
           sensor rows need. */
        QScrollBar:vertical {{
            background: {THEME['SURFACE']};
            width: 6px;
            border-radius: 3px;
        }}
        QScrollBar::handle:vertical {{
            background: {THEME['BORDER']};
            border-radius: 3px;
        }}
    """


def _tabs_style() -> str:
    return f"""
        QTabWidget {{ background: transparent; }}
        QTabWidget::pane {{
            border: none;
            background: transparent;
            margin-top: 0px;
        }}
        QTabWidget > QWidget {{ background: transparent; }}
        QTabBar {{ background: {THEME['BG']}; border: none; }}
        QTabBar::tab {{
            background: {THEME['BG']};
            color: {THEME['SUBTEXT']};
            font-size: 11px;
            font-weight: bold;
            letter-spacing: 1px;
            padding: 8px 18px;
            border: none;
            border-bottom: 2px solid transparent;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {THEME['BG']};
            color: {THEME['ACCENT']};
            border-bottom: 2px solid {THEME['ACCENT']};
        }}
        QTabBar::tab:hover:!selected {{
            background: {THEME['BG']};
            color: {THEME['TEXT']};
            border-bottom: 2px solid {THEME['BORDER']};
        }}
    """


_SCAN_BTN_W: Final[int] = 90   # fixed width — status pill column
_SCAN_BTN_H: Final[int] = 34   # fixed height — aligns with QComboBox / trash button


def _styled_combo_view() -> QListView:
    """Fresh Mocha-styled popup view for a sensor QComboBox. macOS shows the
    popup as a separate top-level window that does not inherit the dialog's
    descendant QSS, so each combo needs its own styled view. """
    view = QListView()
    # the combo can shrink (Ignored policy), but the popup must stay
    # wide enough to show the full BLE UUID/MAC of each detected device.
    view.setMinimumWidth(360)
    view.setStyleSheet(
        f"""
        QListView {{
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['ACCENT']};
            border-radius: 4px;
            outline: none;
            padding: 2px;
        }}
        QListView::item {{
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
            padding: 4px 6px;
        }}
        QListView::item:selected {{
            background-color: {THEME['ACCENT']};
            color: {THEME['CRUST']};
        }}
        """
    )
    return view


def _btn_trash() -> str:
    """Fixed square icon button — forgets (unassigns) the sensor. """
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {THEME['SUBTEXT']};
            border: 1px solid {THEME['BORDER']};
            border-radius: 6px;
            font-size: 13px;
            padding: 0px;
            min-width: {_SCAN_BTN_H}px;
            max-width: {_SCAN_BTN_H}px;
            min-height: {_SCAN_BTN_H}px;
            max-height: {_SCAN_BTN_H}px;
        }}
        QPushButton:hover {{
            border-color: {THEME['CRITICAL']};
            color: {THEME['CRITICAL']};
        }}
    """


def _table_spinbox_style() -> str:
    """Explicit style for QDoubleSpinBox/QSpinBox used as QTableWidget cell widgets.
    Overrides Qt's platform selection highlight that makes text unreadable on focus."""
    return f"""
        QDoubleSpinBox, QSpinBox {{
            background-color: {THEME['SURFACE']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['BORDER']};
            border-radius: 4px;
            padding: 3px 6px;
            font-family: 'JetBrains Mono';
            font-size: 12px;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}
        QDoubleSpinBox:focus, QSpinBox:focus {{
            border: 1px solid {THEME['ACCENT']};
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
        }}
        QDoubleSpinBox::up-button, QSpinBox::up-button,
        QDoubleSpinBox::down-button, QSpinBox::down-button {{
            width: 16px;
            border: none;
            background: transparent;
        }}
    """


# Standard broker ports; the TLS switch moves between the two as long as the
# user has not typed a port of their own.
_MQTT_PORT_PLAIN: Final[int] = 1883
_MQTT_PORT_TLS: Final[int] = 8883

# Width of the broker spin boxes: enough for five digits, a unit suffix and the
# arrows with the dialog padding — the rest of the row belongs to its label.
_MQTT_SPIN_W: Final[int] = 96

# Indicator (16 px) plus its spacing (8 px) plus a margin, added to the measured
# text width to give a check box the room its label needs.
_CHECKBOX_EXTRA_W: Final[int] = 34


# MQTT sensor units: stored code -> label shown in the table. "" means the
# reading is not a temperature and is recorded exactly as published.
_MQTT_SENSOR_UNITS: Final[tuple[tuple[str, str], ...]] = (
    ("",  "—"),
    ("C", "°C"),
    ("F", "°F"),
)


def _cell_editor_style() -> str:
    """Explicit style for the inline cell editor of an editable QTableWidget."""
    return f"""
        QLineEdit {{
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['ACCENT']};
            border-radius: 3px;
            padding: 1px 3px;
            font-size: 12px;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}
    """


class OpaqueCellDelegate(QStyledItemDelegate):
    """Editable table cells with an editor that actually hides the cell.

    Qt builds its own QLineEdit subclass for the default editor and leaves it
    translucent under our dialog stylesheet, so the cell text stayed visible
    through the editor while typing. Building the editor here lets us make it
    opaque (autoFillBackground + its own stylesheet), which a descendant rule
    in the dialog stylesheet does not reliably achieve.
    """

    def createEditor(self, parent, option, index):  # noqa: N802,ARG002
        editor = QLineEdit(parent)
        editor.setAutoFillBackground(True)
        editor.setFrame(True)
        pal = editor.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(THEME['BG']))
        pal.setColor(QPalette.ColorRole.Text, QColor(THEME['TEXT']))
        editor.setPalette(pal)
        editor.setStyleSheet(_cell_editor_style())
        return editor

    def updateEditorGeometry(self, editor, option, index):  # noqa: N802,ARG002
        # cover the whole cell: a smaller editor leaves a rim of the cell behind
        editor.setGeometry(option.rect)


def _table_combobox_style() -> str:
    """Explicit style for QComboBox used as QTableWidget cell widget."""
    return f"""
        QComboBox {{
            background-color: {THEME['SURFACE']};
            color: {THEME['TEXT']};
            border: 1px solid {THEME['BORDER']};
            border-radius: 4px;
            padding: 3px 6px;
            font-size: 12px;
            combobox-popup: 0;
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}
        QComboBox:focus {{
            border: 1px solid {THEME['ACCENT']};
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QListView {{
            background-color: {THEME['BG']};
            color: {THEME['TEXT']};
            selection-background-color: {THEME['ACCENT']};
            selection-color: {THEME['BG']};
        }}
    """


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(
        f"color: {THEME['BORDER']}; background: {THEME['BORDER']}; max-height:1px;"
    )
    return sep


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {THEME['ACCENT']}; font-size: 11px; font-weight: bold;"
        f"letter-spacing: 2px; margin-top: 4px;"
    )
    return lbl


def _field_label(text: str, width: int = 150) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty('variant', 'secondary')
    lbl.setMinimumWidth(width)
    return lbl


# ─────────────────────────────────────────────────────────────────────────────
# QCollapsibleWidget
# ─────────────────────────────────────────────────────────────────────────────

class QCollapsibleWidget(QWidget):
    """
    A titled section that can be collapsed/expanded via a toggle button.
    Content is placed in self.content_widget (QWidget with a QVBoxLayout).

    Usage:
        section = QCollapsibleWidget("AirWave PID", collapsed=True)
        section.content_layout.addWidget(some_table)
        parent_layout.addWidget(section)
    """

    def __init__(self, title: str, collapsed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = collapsed

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toggle button ────────────────────────────────────────────────
        self._toggle_btn = QPushButton()
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(not collapsed)
        self._toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['SURFACE']};
                color: {THEME['SUBTEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {THEME['ACCENT']};
                color: {THEME['ACCENT']};
            }}
            QPushButton:checked {{
                color: {THEME['ACCENT']};
                border-color: {THEME['ACCENT']};
            }}
        """)
        self._set_toggle_label(title)
        self._title = title
        self._toggle_btn.toggled.connect(self._on_toggle)
        root.addWidget(self._toggle_btn)

        # ── Content area ─────────────────────────────────────────────────
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 8, 0, 4)
        self.content_layout.setSpacing(8)

        # Animated max-height
        self._anim = QPropertyAnimation(self.content_widget, b"maximumHeight")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.content_widget.setMaximumHeight(0 if collapsed else 16_777_215)
        self.content_widget.setVisible(not collapsed)
        root.addWidget(self.content_widget)

    def _set_toggle_label(self, title: str) -> None:
        arrow = "▶" if self._collapsed else "▼"
        self._toggle_btn.setText(f" {arrow}  {title.upper()}")

    @pyqtSlot(bool)
    def _on_toggle(self, checked: bool) -> None:
        self._collapsed = not checked
        self._set_toggle_label(self._title)

        # Disconnect stale finished callbacks before configuring new ones
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass

        if checked:
            # Expand: make visible at height 0, animate to natural height
            self.content_widget.setVisible(True)
            self.content_widget.setMaximumHeight(0)
            natural = self.content_widget.sizeHint().height()
            self._anim.setStartValue(0)
            self._anim.setEndValue(max(natural, 20))
            self._anim.finished.connect(
                lambda: self.content_widget.setMaximumHeight(16_777_215)
            )
        else:
            # Collapse: animate to 0, then hide
            current = self.content_widget.height()
            self._anim.setStartValue(current)
            self._anim.setEndValue(0)
            self._anim.finished.connect(
                lambda: self.content_widget.setVisible(False)
            )
        self._anim.start()


# ─────────────────────────────────────────────────────────────────────────────
# Sensor group descriptor  (background-detection model)
# ─────────────────────────────────────────────────────────────────────────────

class _SensorGroup:
    """One BLE sensor row in the SENSORS tab. Detection is passive: the central
    TilauBLEScanner streams advertisements, each group matches them by BLE name
    prefix and drives its own combo + status pill. The persisted assignment
    (aw.<name_attr>) is never cleared by the scanner — only an explicit trash
    click unassigns it."""

    __slots__ = (
        "label", "prefix", "combo", "status", "spinner", "name_attr", "list_attr",
        "seen", "cleared", "user_touched", "auto_done", "was_assigned",
    )

    def __init__(self, label: str, prefix: str, combo: QComboBox,
                 name_attr: str, list_attr: str) -> None:
        self.label        = label       # fixed combo/label display (e.g. "Skywalker v2")
        self.prefix       = prefix      # BLE advertised-name prefix to match
        self.combo        = combo
        self.status: QLabel | None = None
        self.spinner      = None        # TilauProgress ring, alive only while scanning
        self.name_attr    = name_attr   # aw attribute holding the assigned id
        self.list_attr    = list_attr   # aw attribute holding the candidate id list
        self.seen: set[str] = set()     # addresses seen live this dialog session
        self.cleared      = False       # user pressed 🗑 → suppress auto-select
        self.user_touched = False       # user picked in the combo → stop auto-select
        self.auto_done    = False       # single detected device already auto-selected
        self.was_assigned = False       # an id was persisted when the tab opened


# ─────────────────────────────────────────────────────────────────────────────
# TilauscopeConfigDlg
# ─────────────────────────────────────────────────────────────────────────────

class TilauscopeConfigDlg(QDialog):
    """
    TilauScope configuration dialog — frameless Catppuccin Mocha.

    Tabs
    ────
    ⚙  GENERAL       Roaster model, UI features
    📡  SENSORS       All coupled devices grouped by role (BLE scan per device)
    🔬  DETECTION     FC / DE algorithm parameters & per-phase thresholds
    🌐  INTEGRATIONS  MQTT broker + AI provider
    """

    def __init__(self, parent: QWidget, aw: 'ApplicationWindow') -> None:
        super().__init__(parent)
        self.aw = aw

        # Frameless + translucent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        # Background sensor detection, populated in _setup_sensors_tab and
        # driven by the central TilauBLEScanner while the SENSORS tab is active. See _hook_scanner().
        self._sensor_groups: list[_SensorGroup] = []
        self._scanner = None            # scanner we are currently listening to
        self._own_scanner = None        # private scanner (only when no BeanCave shell)
        self._scanner_hooked = False
        self._bt_available = False      # cached at hook time (bluetooth_enabled)
        self._hook_attempted = False    # True once we entered the SENSORS tab

        # "Other hardware detected nearby" section (bottom of SENSORS
        # tab) — mirrors the onboarding wizard: surfaces every recognisable BLE
        # device that is NOT currently wired up, both known third-party brands
        # (Santoker / IKAWA / …) and our own sensors seen but left unassigned.
        self._other_seen: dict[str, tuple[str, str, bool]] = {}  # addr -> (label, sig, is_own)
        self._other_rows: dict[str, QWidget] = {}                # addr -> row widget
        self._other_host: QWidget | None = None
        self._other_layout: QVBoxLayout | None = None
        self._other_empty: QLabel | None = None

        # Drag state
        self._drag_pos = None

        # Snapshot for cancel
        self._snapshot()

        # Pilot window for the shared base stylesheet (theme_qss).
        # The base is laid down first and what this window still needs on top
        # of it second: at equal specificity the later rule wins.
        # See wiki/Theme-QSS-Spec.md.
        self.setStyleSheet(base_qss(ground=False) + _local_style())
        self._build_ui()

        # release the BLE scanner on any close path (Esc/reject too)
        self.finished.connect(lambda _=0: self._unhook_scanner())

        self.setMinimumSize(720, 560)
        self.resize(780, 620)

    # ── Drag-to-move ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── Settings snapshot / restore ──────────────────────────────────────────

    def _snapshot(self) -> None:
        aw = self.aw
        self._org = {
            "tilau_roaster":              aw.tilau_roaster,
            "TilauScopeAnnotation":       aw.TilauScopeAnnotation,
            "TilauScopeNotification":     aw.TilauScopeNotification,
            "bleTilauScopeDeviceName":    aw.bleTilauScopeDeviceName,
            "bleTilauScopeautomarkFC":    aw.bleTilauScopeautomarkFC,
            "bleTilauScopeFCTreshold":    aw.bleTilauScopeFCTreshold,
            "TilauScopeFCMarkFlag":       aw.TilauScopeFCMarkFlag,
            "TilauScopeFCWindow":         aw.TilauScopeFCWindow,
            "TilauScopeFCTreshold":       aw.TilauScopeFCTreshold,
            "TilauScopeCrackParams":      aw.TilauScopeCrackParams.copy(),
            "TilauScopeDEMarkFlag":       aw.TilauScopeDEMarkFlag,
            "bleRoastSeeDeviceName":      aw.bleRoastSeeDeviceName,
            "bleRoastSeeAGDeviceName":    aw.bleRoastSeeAGDeviceName,
            "bleNiimbotDeviceName":       aw.bleNiimbotDeviceName,
            "bleAirwaveDeviceName":       aw.bleAirwaveDeviceName,
            "bleSkywalkerDeviceName":     aw.bleSkywalkerDeviceName,
            "bleAirwavepidOnET":          aw.bleAirwavepidOnET,
            "bleAirwavepidRamp":          aw.bleAirwavepidRamp,
            "bleAirwaveEmulateOmniflux":  aw.bleAirwaveEmulateOmniflux,
            "bleAirwavepidparms":         aw.bleAirwavepidparms.copy(),
            "mqttConfig":                 aw.mqttConfig,
            "tilau_aiConfig":             aw.tilau_aiConfig,
        }

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Card shell ────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("configCard")
        card.setStyleSheet(f"""
            QFrame#configCard {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 20px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 22, 28, 20)
        card_layout.setSpacing(12)
        outer.addWidget(card)

        # ── Title bar ─────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel(
            QApplication.translate("tilauscope_devices", "TILAU CONFIGURATION")
        )
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: 800;"
            f"letter-spacing: 3px;"
        )
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty('variant', 'icon')   # fixed size: no base padding
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BORDER']};
                color: {THEME['CRITICAL']};
                border-radius: 15px;
                border: 1px solid {THEME['CRITICAL']};
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {THEME['CRITICAL']};
                color: {THEME['BG']};
            }}
        """)
        close_btn.clicked.connect(self._on_cancel)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        card_layout.addLayout(title_row)
        card_layout.addWidget(_separator())

        # ── Tabs ──────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_tabs_style())

        self._general_tab    = QWidget(); self._general_tab.setStyleSheet("background: transparent;")
        self._sensors_tab    = QWidget(); self._sensors_tab.setStyleSheet("background: transparent;")
        self._detection_tab  = QWidget(); self._detection_tab.setStyleSheet("background: transparent;")
        self._integrations_tab = QWidget(); self._integrations_tab.setStyleSheet("background: transparent;")
        self._printing_tab   = QWidget(); self._printing_tab.setStyleSheet("background: transparent;")
        self._beancave_tab   = QWidget(); self._beancave_tab.setStyleSheet("background: transparent;")

        self._tabs.addTab(self._general_tab,     QApplication.translate("tilauscope_devices", "⚙  GENERAL"))
        self._tabs.addTab(self._sensors_tab,     QApplication.translate("tilauscope_devices", "📡  SENSORS"))
        self._tabs.addTab(self._detection_tab,   QApplication.translate("tilauscope_devices", "🔬  DETECTION"))
        self._tabs.addTab(self._integrations_tab, QApplication.translate("tilauscope_devices", "🌐  INTEGRATIONS"))
        self._tabs.addTab(self._printing_tab,    QApplication.translate("tilauscope_devices", "🖨  PRINTING"))
        self._tabs.addTab(self._beancave_tab,    QApplication.translate("tilauscope_devices", "☕  BEANCAVE"))

        self._setup_general_tab()
        self._setup_sensors_tab()
        self._setup_detection_tab()
        self._setup_integrations_tab()
        self._setup_printing_tab()
        self._setup_beancave_tab()

        # background sensor scan is scoped to the SENSORS tab: hook the
        # central BLE scanner on enter, release it on leave (and on close).
        self._tabs.currentChanged.connect(self._on_tab_changed)

        card_layout.addWidget(self._tabs, 1)

        # ── Footer buttons ─────────────────────────────────────────────────
        card_layout.addWidget(_separator())
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = QPushButton(QApplication.translate("tilauscope_devices", "Cancel"))
        cancel_btn.setObjectName("footerBtn")
        cancel_btn.setProperty('variant', 'outline')
        cancel_btn.clicked.connect(self._on_cancel)

        ok_btn = QPushButton(QApplication.translate("tilauscope_devices", "⬥  Save"))
        ok_btn.setObjectName("footerBtn")
        ok_btn.setProperty('variant', 'primary')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        card_layout.addLayout(btn_row)

        # Resize grip (bottom-right)
        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip_row.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        card_layout.addLayout(grip_row)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — GENERAL
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_general_tab(self) -> None:
        scroll = _scrollable(self._general_tab)
        layout = scroll.widget().layout()

        # Roaster model
        layout.addWidget(_section_label(QApplication.translate("tilauscope_devices", "Roaster")))
        roaster_group = QGroupBox(QApplication.translate("tilauscope_devices", "Machine Profile"))
        rg = QFormLayout(roaster_group)
        self.tilauRoaster = QComboBox()
        # macOS: the popup is a separate top-level window that does not reliably
        # inherit the dialog's descendant QSS — style the view object directly so
        # the dropdown gets the Mocha background instead of the white system one.
        _roaster_view = QListView()
        _roaster_view.setStyleSheet(
            f"""
            QListView {{
                background-color: {THEME['BG']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['ACCENT']};
                border-radius: 4px;
                outline: none;
                padding: 2px;
            }}
            QListView::item {{
                background-color: {THEME['BG']};
                color: {THEME['TEXT']};
                padding: 4px 6px;
            }}
            QListView::item:selected {{
                background-color: {THEME['ACCENT']};
                color: {THEME['CRUST']};
            }}
            """
        )
        self.tilauRoaster.setView(_roaster_view)
        self.tilauRoaster.setToolTip(
            QApplication.translate("tilauscope_devices", "Select the active roaster machine profile")
        )
        from tilauscope.roasters import RoasterManager
        rm = RoasterManager()
        items = [QApplication.translate("tilauscope_devices", "— select a roaster model —")]
        items.extend(rm.get_roaster_list())
        self.tilauRoaster.addItems(items)
        if self.aw.tilau_roaster:
            idx = self.tilauRoaster.findText(self.aw.tilau_roaster)
            if idx >= 0:
                self.tilauRoaster.setCurrentIndex(idx)
        rg.addRow(QApplication.translate("tilauscope_devices", "Model:"), self.tilauRoaster)
        # read-only roaster: monitoring only, Artisan sends no commands
        self.tilauRoasterReadonly = QCheckBox(
            QApplication.translate("tilauscope_devices",
                "Read-only (monitoring only — Artisan does not control the machine)")
        )
        self.tilauRoasterReadonly.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Tick for a roaster you drive by hand (Artisan only records ET/BT): "
                "the control sliders are hidden here and in Artisan. Untick to restore "
                "your previous slider configuration.")
        )
        self.tilauRoasterReadonly.setChecked(
            bool(getattr(self.aw, "tilau_roaster_readonly", False))
        )
        rg.addRow("", self.tilauRoasterReadonly)
        layout.addWidget(roaster_group)

        # UI features
        layout.addWidget(_section_label(QApplication.translate("tilauscope_devices", "UI Features")))
        feat_group = QGroupBox(QApplication.translate("tilauscope_devices", "Overlay & Notifications"))
        fg = QVBoxLayout(feat_group)
        fg.setContentsMargins(12, 14, 12, 14)
        fg.setSpacing(18)
        self.tilauScopeAnnotationCheckBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "Enable floating annotations")
        )
        self.tilauScopeAnnotationCheckBox.setToolTip(
            QApplication.translate("tilauscope_devices", "Show phase-event annotations on the roast graph overlay")
        )
        if self.aw.TilauScopeAnnotation is not None:
            self.tilauScopeAnnotationCheckBox.setChecked(self.aw.TilauScopeAnnotation)

        self.tilauScopeNotificationCheckBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "Enable BeanCave startup notifications")
        )
        self.tilauScopeNotificationCheckBox.setToolTip(
            QApplication.translate("tilauscope_devices", "Show inventory alerts and reminders when BeanCave opens")
        )
        if self.aw.TilauScopeNotification is not None:
            self.tilauScopeNotificationCheckBox.setChecked(self.aw.TilauScopeNotification)

        # Headless "BeanCave home" mode — persisted in QSettings and read
        # at boot (main.py). Boot-time only, so it takes effect after a restart.
        self.headlessModeCheckBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "BeanCave home mode (hide the Artisan window)")
        )
        self.headlessModeCheckBox.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Start in the BeanCave shell with the Artisan window hidden. Takes effect after a restart.")
        )
        self.headlessModeCheckBox.setChecked(
            QSettings().value('tilauscope/headless_mode', False, type=bool)
        )

        fg.addWidget(self.tilauScopeAnnotationCheckBox)
        fg.addWidget(self.tilauScopeNotificationCheckBox)
        fg.addWidget(self.headlessModeCheckBox)
        layout.addWidget(feat_group)

        # QR scan / mobile record server (spec wiki/QR-Scan-Spec.md §2.1) —
        # the port is baked into printed label QR codes, so change it knowingly.
        layout.addWidget(_section_label(QApplication.translate("tilauscope_devices", "Remote access")))
        web_group = QGroupBox(QApplication.translate("tilauscope_devices", "Record web server (phone QR scan)"))
        wg = QFormLayout(web_group)
        self.webPortSpin = QSpinBox()
        self.webPortSpin.setRange(1024, 65535)
        self.webPortSpin.setValue(QSettings().value('tilauscope/web_port', 8123, type=int))
        self.webPortSpin.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Port of the read-only record server used when scanning a label QR code "
                "with a phone (http://tilauscope.local:port). It is encoded in printed "
                "labels — change it only if it conflicts with another service. "
                "Takes effect after a restart. Default: 8123.")
        )
        wg.addRow(QApplication.translate("tilauscope_devices", "Port:"), self.webPortSpin)
        layout.addWidget(web_group)

        # remote control (phone piloting) — opt-in, boot-time (main.py
        # start_tilau_web_host). Off by default; takes effect after a restart.
        remote_group = QGroupBox(QApplication.translate("tilauscope_devices", "Remote control (phone piloting)"))
        rgl = QFormLayout(remote_group)
        self.remoteControlCheckBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "Enable remote control from a phone")
        )
        self.remoteControlCheckBox.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Run the control server so a phone on the same wifi can follow the roast "
                "(and, later, pilot it). Off by default. Takes effect after a restart.")
        )
        self.remoteControlCheckBox.setChecked(
            QSettings().value('tilauscope/remote_enabled', False, type=bool)
        )
        self.remotePortSpin = QSpinBox()
        self.remotePortSpin.setRange(1024, 65535)
        self.remotePortSpin.setValue(QSettings().value('tilauscope/remote_port', 8765, type=int))
        self.remotePortSpin.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Port of the remote-control server. Takes effect after a restart. Default: 8765.")
        )
        rgl.addRow(self.remoteControlCheckBox)
        rgl.addRow(QApplication.translate("tilauscope_devices", "Port:"), self.remotePortSpin)
        self.pairPhoneBtn = QPushButton(QApplication.translate("tilauscope_devices", "Pair a phone…"))
        self.pairPhoneBtn.clicked.connect(self._pair_phone)
        rgl.addRow(self.pairPhoneBtn)
        layout.addWidget(remote_group)

        # visual bench for the shared progress indicators
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Diagnostics")))
        diag_group = QGroupBox(QApplication.translate("tilauscope_devices", "Display check"))
        dgl = QFormLayout(diag_group)
        self.progressGalleryBtn = QPushButton(
            QApplication.translate("tilauscope_devices", "Check progress indicators…"))
        self.progressGalleryBtn.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Open a window showing every progress indicator the application uses, "
                "so their appearance and animation can be checked on this machine."))
        self.progressGalleryBtn.clicked.connect(self._open_progress_gallery)
        dgl.addRow(self.progressGalleryBtn)
        layout.addWidget(diag_group)

        layout.addStretch()

    def _open_progress_gallery(self) -> None:
        from tilauscope.progress_gallery import open_progress_gallery  # noqa: PLC0415
        open_progress_gallery(self)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 — SENSORS
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_sensors_tab(self) -> None:
        scroll = _scrollable(self._sensors_tab)
        layout = scroll.widget().layout()

        # BLE name prefixes for passive detection (fall back to
        # literals if a device module can't be imported). Same set the
        # onboarding wizard matches against the central scanner stream.
        self._prefixes = self._resolve_prefixes()

        # ── Ambient — TilauAmbient BLE ────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Ambient")
        ))
        ambient_group = QGroupBox("TilauAmbient  (BME280 / BLE)")
        ambient_group.setContentsMargins(12, 18, 12, 12)
        ag = QGridLayout(ambient_group)
        ag.setVerticalSpacing(10)
        ag.setHorizontalSpacing(10)

        self.tilauscopeProbeComboBoxcList = QComboBox()
        self.tilauscopeProbeComboBoxcList.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ambient_cell = self._sensor_cell(
            "TilauAmbient", self._prefixes["ambient"],
            self.tilauscopeProbeComboBoxcList,
            "bleTilauScopeDeviceName", "bleTilauAmbientDeviceslist",
        )

        # Crack audio threshold — parameter of THIS device's microphone analysis
        self.tilauAmbientCrackThresholdSpin = QSpinBox()
        self.tilauAmbientCrackThresholdSpin.setRange(1, 10)
        self.tilauAmbientCrackThresholdSpin.setValue(
            self.aw.bleTilauScopeFCTreshold if self.aw.bleTilauScopeFCTreshold is not None else 3
        )
        self.tilauAmbientCrackThresholdSpin.setToolTip(
            QApplication.translate(
                "tilauscope_devices",
                "Acoustic sensitivity threshold for crack detection via TilauAmbient microphone.\n"
                "Lower = more sensitive. Independent from the global algorithm threshold."
            )
        )

        ag.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        ag.addWidget(self.tilauscopeProbeComboBoxcList, 0, 1)
        ag.addWidget(ambient_cell, 0, 2)
        ag.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Crack audio sensitivity:")), 1, 0)
        ag.addWidget(self.tilauAmbientCrackThresholdSpin, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(ambient_group)

        # ── Color & Airflow — AirWave BLE ─────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Color & Airflow")
        ))
        airwave_group = QGroupBox("Difluid AirWave  (BLE)")
        airwave_group.setContentsMargins(12, 18, 12, 12)
        aw_g = QGridLayout(airwave_group)
        aw_g.setVerticalSpacing(10)
        aw_g.setHorizontalSpacing(10)

        self.AirwaveComboBox = QComboBox()
        self.AirwaveComboBox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        airwave_cell = self._sensor_cell(
            "AirWave", self._prefixes["airwave"], self.AirwaveComboBox,
            "bleAirwaveDeviceName", "bleAirwaveDeviceslist",
        )

        self.AirwavePidOnETCheckVBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "PID target on ET (instead of BT)")
        )
        self.AirwavePidOnETCheckVBox.setChecked(self.aw.bleAirwavepidOnET)

        self.AirwavePidRampSpinBox = QSpinBox()
        self.AirwavePidRampSpinBox.setRange(1, 10)
        self.AirwavePidRampSpinBox.setValue(self.aw.bleAirwavepidRamp)
        self.AirwavePidRampSpinBox.setToolTip(
            QApplication.translate("tilauscope_devices", "PID correction ramp speed (1=slow … 10=fast)")
        )

        self.AirwaveEmulateOmnifluxCheckVBox = QCheckBox(
            QApplication.translate("tilauscope_devices", "Emulate Omniflux output (Agtron channel)")
        )
        self.AirwaveEmulateOmnifluxCheckVBox.setChecked(self.aw.bleAirwaveEmulateOmniflux)

        aw_g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        aw_g.addWidget(self.AirwaveComboBox, 0, 1)
        aw_g.addWidget(airwave_cell, 0, 2)
        aw_g.addWidget(self.AirwavePidOnETCheckVBox, 1, 0, 1, 3)
        aw_g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Ramp speed:")), 2, 0)
        aw_g.addWidget(self.AirwavePidRampSpinBox, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        aw_g.addWidget(self.AirwaveEmulateOmnifluxCheckVBox, 3, 0, 1, 3)
        layout.addWidget(airwave_group)

        # ── AirWave PID — collapsible ──────────────────────────────────────
        self._airwave_pid_section = QCollapsibleWidget(
            QApplication.translate("tilauscope_devices", "AirWave PID parameters"),
            collapsed=True,
        )
        self.pid_table = QTableWidget()
        pid_headers = [
            "Kp", "Ki",
            QApplication.translate("tilauscope_devices", "Min fan %"),
            QApplication.translate("tilauscope_devices", "Inlet target"),
            QApplication.translate("tilauscope_devices", "Inlet limit"),
            QApplication.translate("tilauscope_devices", "Mode"),
            QApplication.translate("tilauscope_devices", "Ramp %/s"),
        ]
        self.pid_table.setColumnCount(len(pid_headers))
        self.pid_table.setHorizontalHeaderLabels(pid_headers)
        self.pid_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pid_table.setMinimumHeight(160)
        self._populate_airwave_pid_table()
        self._airwave_pid_section.content_layout.addWidget(self.pid_table)
        layout.addWidget(self._airwave_pid_section)

        # ── SKyWALKER BLE ───────────────────────────────────────
        layout.addWidget(_section_label(
             QApplication.translate("tilauscope_devices", "Roaster Link")
        ))
        skywalker_group = QGroupBox("Skywalker v2  (TC4-BLE)")
        skywalker_group.setContentsMargins(12, 18, 12, 12)
        sw_g = QGridLayout(skywalker_group)
        sw_g.setVerticalSpacing(10); sw_g.setHorizontalSpacing(10)
        self.SkywalkerComboBox = QComboBox()
        self.SkywalkerComboBox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        skywalker_cell = self._sensor_cell(
            "Skywalker v2", self._prefixes["skywalker"], self.SkywalkerComboBox,
            "bleSkywalkerDeviceName", "bleSkywalkerDeviceslist",
        )
        sw_g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        sw_g.addWidget(self.SkywalkerComboBox, 0, 1)
        sw_g.addWidget(skywalker_cell, 0, 2)
        layout.addWidget(skywalker_group)

        # ── Color Meter — Lebrew C1 ───────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Color Meter")
        ))
        c1_group = QGroupBox("Lebrew RoastSee C1  (BLE)")
        c1_group.setContentsMargins(12, 18, 12, 12)
        c1g = QGridLayout(c1_group)
        c1g.setVerticalSpacing(10)
        c1g.setHorizontalSpacing(10)

        self.lebrewRoastSeeC1ComboBox = QComboBox()
        self.lebrewRoastSeeC1ComboBox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        c1_cell = self._sensor_cell(
            "C1", self._prefixes["c1"], self.lebrewRoastSeeC1ComboBox,
            "bleRoastSeeDeviceName", "bleRoastSeeDeviceslist",
        )

        c1g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        c1g.addWidget(self.lebrewRoastSeeC1ComboBox, 0, 1)
        c1g.addWidget(c1_cell, 0, 2)
        layout.addWidget(c1_group)

        # ── Water — AquaGauge ─────────────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Water Quality")
        ))
        ag_group = QGroupBox("Lebrew AquaGauge  (BLE)")
        ag_group.setContentsMargins(12, 18, 12, 12)
        agg = QGridLayout(ag_group)
        agg.setVerticalSpacing(10)
        agg.setHorizontalSpacing(10)

        self.lebrewRoastSeeAGComboBox = QComboBox()
        self.lebrewRoastSeeAGComboBox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ag_cell = self._sensor_cell(
            "AquaGauge", self._prefixes["aquagauge"], self.lebrewRoastSeeAGComboBox,
            "bleRoastSeeAGDeviceName", "bleRoastSeeAGDeviceslist",
        )

        agg.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        agg.addWidget(self.lebrewRoastSeeAGComboBox, 0, 1)
        agg.addWidget(ag_cell, 0, 2)
        layout.addWidget(ag_group)

        # ── Printer — Niimbot B21S ─────────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Label Printer")
        ))
        niimbot_group = QGroupBox("Niimbot B21S  (BLE)")
        niimbot_group.setContentsMargins(12, 18, 12, 12)
        ng = QGridLayout(niimbot_group)
        ng.setVerticalSpacing(10)
        ng.setHorizontalSpacing(10)

        self.niimbotComboBox = QComboBox()
        self.niimbotComboBox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        niimbot_cell = self._sensor_cell(
            "B21S", self._prefixes["niimbot"], self.niimbotComboBox,
            "bleNiimbotDeviceName", "bleNiimbotDeviceslist",
        )

        ng.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Device:")), 0, 0)
        ng.addWidget(self.niimbotComboBox, 0, 1)
        ng.addWidget(niimbot_cell, 0, 2)
        layout.addWidget(niimbot_group)

        # other hardware detected nearby (identification only)
        self._build_other_section(layout)

        layout.addStretch()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 — DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_detection_tab(self) -> None:
        scroll = _scrollable(self._detection_tab)
        layout = scroll.widget().layout()

        # ── First Crack ───────────────────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "First Crack (FC)")
        ))

        # Source info
        src_lbl = QLabel(
            QApplication.translate(
                "tilauscope_devices",
                "Signal sources: TilauAmbient (acoustic) · Omniflux (color/RoC) — fused in tilau_intelligence"
            )
        )
        src_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic;"
        )
        src_lbl.setWordWrap(True)
        layout.addWidget(src_lbl)

        fc_group = QGroupBox(QApplication.translate("tilauscope_devices", "FC Algorithm"))
        fc_g = QGridLayout(fc_group)

        self.fcMarking = QCheckBox(
            QApplication.translate("tilauscope_devices", "Enable automatic FC detection & marking")
        )
        self.fcMarking.setChecked(self.aw.TilauScopeFCMarkFlag)
        self.fcMarking.setToolTip(
            QApplication.translate(
                "tilauscope_devices",
                "Activates the TilauScope multi-signal FC detection algorithm "
                "(crack count density, color RoC, BT threshold)."
            )
        )

        self.fcWindowSpin = QSpinBox()
        self.fcWindowSpin.setRange(5, 120)
        self.fcWindowSpin.setSuffix(" s")
        self.fcWindowSpin.setValue(self.aw.TilauScopeFCWindow)
        self.fcWindowSpin.setToolTip(
            QApplication.translate("tilauscope_devices", "Sliding time window for crack density analysis (seconds).")
        )

        self.fcThresholdSpin = QSpinBox()
        self.fcThresholdSpin.setRange(1, 20)
        self.fcThresholdSpin.setValue(self.aw.TilauScopeFCTreshold)
        self.fcThresholdSpin.setToolTip(
            QApplication.translate(
                "tilauscope_devices",
                "Minimum number of acoustic events within the window to confirm FC. "
                "Independent from the TilauAmbient device sensitivity setting."
            )
        )

        # Enable/disable window+threshold with the main toggle
        self.fcMarking.toggled.connect(self.fcWindowSpin.setEnabled)
        self.fcMarking.toggled.connect(self.fcThresholdSpin.setEnabled)
        self.fcWindowSpin.setEnabled(self.fcMarking.isChecked())
        self.fcThresholdSpin.setEnabled(self.fcMarking.isChecked())

        fc_g.addWidget(self.fcMarking, 0, 0, 1, 2)
        fc_g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Detection window:")), 1, 0)
        fc_g.addWidget(self.fcWindowSpin, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        fc_g.addWidget(_field_label(QApplication.translate("tilauscope_devices", "Global event threshold:")), 2, 0)
        fc_g.addWidget(self.fcThresholdSpin, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(fc_group)

        # ── Dry End ───────────────────────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Dry End (DE)")
        ))
        de_group = QGroupBox(QApplication.translate("tilauscope_devices", "DE Algorithm"))
        de_g = QGridLayout(de_group)

        self.deMarking = QCheckBox(
            QApplication.translate("tilauscope_devices", "Enable automatic Dry End detection & marking")
        )
        self.deMarking.setChecked(self.aw.TilauScopeDEMarkFlag)
        self.deMarking.setToolTip(
            QApplication.translate(
                "tilauscope_devices",
                "Thermodynamic multi-signal detection: RoR_BT/RoR_ET ratio convergence, "
                "Δgap slope, BT progress toward Dry End target set in Phases. "
                "Agtron is used as a bonus signal when a color device is configured."
            )
        )
        de_g.addWidget(self.deMarking, 0, 0, 1, 2)
        layout.addWidget(de_group)

        # ── Per-phase thresholds ──────────────────────────────────────────
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Per-Phase Thresholds")
        ))
        param_group = QGroupBox(
            QApplication.translate("tilauscope_devices", "Detection parameters by crack event")
        )
        param_layout = QVBoxLayout(param_group)

        self.crack_table = QTableWidget()
        crack_headers = [
            QApplication.translate("tilauscope_devices", "Threshold"),
            QApplication.translate("tilauscope_devices", "Agtron max"),
            QApplication.translate("tilauscope_devices", "RoC min"),
            QApplication.translate("tilauscope_devices", "BT margin"),
        ]
        self.crack_table.setColumnCount(len(crack_headers))
        self.crack_table.setHorizontalHeaderLabels(crack_headers)
        self.crack_table.setRowCount(2)
        self.crack_table.setVerticalHeaderLabels([
            QApplication.translate("tilauscope_devices", "First Crack"),
            QApplication.translate("tilauscope_devices", "Second Crack"),
        ])
        self.crack_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.crack_table.setFixedHeight(100)
        self._populate_crack_table()
        param_layout.addWidget(self.crack_table)
        layout.addWidget(param_group)

        layout.addStretch()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4 — INTEGRATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_integrations_tab(self) -> None:
        scroll = _scrollable(self._integrations_tab)
        layout = scroll.widget().layout()

        # ── MQTT ──────────────────────────────────────────────────────────
        layout.addWidget(_section_label("MQTT"))
        mqtt_group = QGroupBox(QApplication.translate("tilauscope_devices", "MQTT Broker"))
        mqtt_layout = QFormLayout(mqtt_group)

        self.mqttBrokerEdit  = QLineEdit(self.aw.mqttConfig.broker_url)
        self.mqttPortSpin    = QSpinBox()
        self.mqttPortSpin.setRange(1, 65535)
        self.mqttPortSpin.setValue(self.aw.mqttConfig.port)
        # A spin box expands horizontally by default and would take the whole row,
        # leaving the label next to it clipped: five digits is all it ever needs.
        self.mqttPortSpin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mqttPortSpin.setMinimumWidth(_MQTT_SPIN_W)
        # TLS and protocol version are handled by the underlying transport; the
        # certificate is checked against the system CA bundle, so a self-signed
        # broker certificate is rejected — there is no "accept anyway" here.
        self.mqttTlsCheck = QCheckBox(
            QApplication.translate("tilauscope_devices", "TLS (encrypted)")
        )
        self.mqttTlsCheck.setChecked(self.aw.mqttConfig.tls)
        self.mqttTlsCheck.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "Encrypts the link to the broker. The broker certificate must be issued "
            "by a recognised authority; a self-signed certificate is refused."
        ))
        self.mqttTlsCheck.toggled.connect(self._mqtt_tls_toggled)
        # A squeezed check box clips its own text rather than refusing to shrink,
        # so the width its label needs is claimed explicitly — measured, because a
        # translated label is not the same length as the English one.
        self.mqttTlsCheck.setMinimumWidth(
            self.mqttTlsCheck.fontMetrics().horizontalAdvance(self.mqttTlsCheck.text())
            + _CHECKBOX_EXTRA_W
        )
        self.mqttTlsCheck.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.addWidget(self.mqttPortSpin)
        port_row.addWidget(self.mqttTlsCheck)
        port_row.addStretch()
        self._mqtt_port_row = QWidget()
        self._mqtt_port_row.setLayout(port_row)

        self.mqttProtocolCombo = QComboBox()
        for label in ("MQTT v3.1", "MQTT v3.1.1", "MQTT v5"):
            self.mqttProtocolCombo.addItem(label)
        self.mqttProtocolCombo.setCurrentIndex(
            min(max(self.aw.mqttConfig.protocol_version, 0), 2)
        )
        # macOS draws the popup as a top-level window that ignores the dialog QSS
        self.mqttProtocolCombo.setView(_styled_combo_view())
        self.mqttProtocolCombo.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "Version spoken to the broker. Leave on v3.1.1 unless the broker "
            "requires otherwise."
        ))

        self.mqttTopicEdit   = QLineEdit(self.aw.mqttConfig.topic)
        self.mqttUsernameEdit = QLineEdit(self.aw.mqttConfig.username)
        self.mqttPasswordEdit = QLineEdit(self.aw.mqttConfig.password)
        self.mqttPasswordEdit.setEchoMode(QLineEdit.EchoMode.Password)

        self.mqttTimeoutSpin = QDoubleSpinBox()
        self.mqttTimeoutSpin.setRange(0.5, 30.0)
        self.mqttTimeoutSpin.setSingleStep(0.5)
        self.mqttTimeoutSpin.setDecimals(1)
        self.mqttTimeoutSpin.setValue(self.aw.mqttConfig.connect_timeout)
        self.mqttTimeoutSpin.setSuffix(QApplication.translate("tilauscope_devices", " s"))
        self.mqttTimeoutSpin.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "How long the broker is given to accept the connection before it is "
            "declared unreachable. A distant or encrypted broker needs more."
        ))
        self.mqttKeepaliveSpin = QSpinBox()
        self.mqttKeepaliveSpin.setRange(5, 600)
        self.mqttKeepaliveSpin.setValue(self.aw.mqttConfig.keepalive)
        self.mqttKeepaliveSpin.setSuffix(QApplication.translate("tilauscope_devices", " s"))
        self.mqttKeepaliveSpin.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "Idle time after which the connection is checked. A short value detects "
            "a lost broker sooner but talks to it more often."
        ))
        _keepalive_label = QLabel(QApplication.translate("tilauscope_devices", "Keepalive:"))
        conn_row = QHBoxLayout()
        conn_row.setContentsMargins(0, 0, 0, 0)
        for _spin in (self.mqttTimeoutSpin, self.mqttKeepaliveSpin):
            _spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            _spin.setMinimumWidth(_MQTT_SPIN_W)
        conn_row.addWidget(self.mqttTimeoutSpin)
        conn_row.addSpacing(12)
        conn_row.addWidget(_keepalive_label)
        conn_row.addWidget(self.mqttKeepaliveSpin)
        conn_row.addStretch()
        self._mqtt_conn_row = QWidget()
        self._mqtt_conn_row.setLayout(conn_row)

        # Polling: some gateways publish a value only when asked, or far too
        # slowly for a roast. Left empty, nothing is ever requested.
        self.mqttPollTopicEdit = QLineEdit(self.aw.mqttConfig.poll_topic)
        self.mqttPollTopicEdit.setPlaceholderText(
            "zwave/_CLIENTS/ZWAVE_GATEWAY-<name>/api/pollValue/set"
        )
        self.mqttPollIntervalSpin = QSpinBox()
        self.mqttPollIntervalSpin.setRange(0, 600)
        self.mqttPollIntervalSpin.setValue(self.aw.mqttConfig.poll_interval)
        self.mqttPollIntervalSpin.setSuffix(
            QApplication.translate("tilauscope_devices", " s")
        )
        self.mqttPollIntervalSpin.setSpecialValueText(
            QApplication.translate("tilauscope_devices", "off")
        )
        self.mqttPollIntervalSpin.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "How often a reading is requested from the gateway. Below 10 seconds "
            "the network cannot keep up, so 10 seconds is used instead."
        ))

        self.mqttTestButton  = QPushButton(
            QApplication.translate("tilauscope_devices", "Test Connection")
        )
        self.mqttTestButton.setProperty('variant', 'outline')
        self.mqttTestButton.clicked.connect(self._test_mqtt_connection)

        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Broker URL:"), self.mqttBrokerEdit)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Port:"),       self._mqtt_port_row)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Protocol:"),   self.mqttProtocolCombo)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Topic:"),      self.mqttTopicEdit)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Username:"),   self.mqttUsernameEdit)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Password:"),   self.mqttPasswordEdit)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Timeout:"),    self._mqtt_conn_row)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Poll request topic:"), self.mqttPollTopicEdit)
        mqtt_layout.addRow(QApplication.translate("tilauscope_devices", "Poll every:"), self.mqttPollIntervalSpin)
        mqtt_layout.addRow("", self.mqttTestButton)

        # ── MQTT sensors ──────────────────────────────────────────────────
        # Sensor list lives with the broker it depends on. Editable in place and
        # without a live broker: the connection is only needed to probe a sensor.
        self._setup_mqtt_sensors(mqtt_layout)

        layout.addWidget(mqtt_group)

        # ── AI Provider ───────────────────────────────────────────────────
        layout.addWidget(_section_label(QApplication.translate("tilauscope_devices", "AI Provider")))
        ai_group = QGroupBox(QApplication.translate("tilauscope_devices", "AI Configuration"))
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.setSpacing(8)

        self._ai_status_lbl = QLabel()
        self._ai_status_lbl.setWordWrap(True)
        self._ai_update_status_label()
        ai_layout.addWidget(self._ai_status_lbl)

        self._ai_configure_btn = QPushButton(
            QApplication.translate("tilauscope_devices", "Configure AI Provider…")
        )
        self._ai_configure_btn.setProperty('variant', 'outline')
        self._ai_configure_btn.clicked.connect(self._open_ai_provider_picker)
        ai_layout.addWidget(self._ai_configure_btn)
        layout.addWidget(ai_group)

        layout.addStretch()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 5 — PRINTING
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_printing_tab(self) -> None:
        scroll = _scrollable(self._printing_tab)
        layout = scroll.widget().layout()

        layout.addWidget(_section_label(QApplication.translate("tilauscope_devices", "Labels")))
        label_group = QGroupBox(QApplication.translate("tilauscope_devices", "Green bean & roasted bean labels"))
        lg = QFormLayout(label_group)

        self.labelSizeCombo = QComboBox()
        _label_size_view = QListView()
        _label_size_view.setStyleSheet(
            f"""
            QListView {{
                background-color: {THEME['BG']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['ACCENT']};
                border-radius: 4px;
                outline: none;
                padding: 2px;
            }}
            QListView::item {{
                background-color: {THEME['BG']};
                color: {THEME['TEXT']};
                padding: 4px 6px;
            }}
            QListView::item:selected {{
                background-color: {THEME['ACCENT']};
                color: {THEME['CRUST']};
            }}
            """
        )
        self.labelSizeCombo.setView(_label_size_view)
        self.labelSizeCombo.setToolTip(
            QApplication.translate("tilauscope_devices",
                "Physical size the label PDF is generated at. Print at 100% (no "
                "\"fit to page\") so it comes out the printer at this exact size.")
        )
        # value is the "WxH" string persisted to QSettings and read
        # back by label_printer's _FontMixin._load_label_size(); 100x150 is the
        # reference size the whole label layout is authored against, so it's the
        # only choice that needs no geometric scaling.
        label_size_choices = [
            ("100x150", QApplication.translate("tilauscope_devices", "10 × 15 cm (standard pochette)")),
            ("70x90",   QApplication.translate("tilauscope_devices", "7 × 9 cm (compact pochette)")),
        ]
        for value, text in label_size_choices:
            self.labelSizeCombo.addItem(text, value)
        current = QSettings().value("tilauscope/label_size_mm", "100x150", type=str)
        idx = self.labelSizeCombo.findData(current)
        self.labelSizeCombo.setCurrentIndex(idx if idx >= 0 else 0)
        lg.addRow(QApplication.translate("tilauscope_devices", "Label size:"), self.labelSizeCombo)
        layout.addWidget(label_group)

        layout.addStretch()

    # ─────────────────────────────────────────────────────────────────────────
    # Table helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _populate_crack_table(self) -> None:
        data = self.aw.TilauScopeCrackParams
        _ss = _table_spinbox_style()
        for row, key in enumerate(["FC", "SC"]):
            params = data.get(key, [4, 90.0, 2.0, 25.0])
            for col in range(4):
                sb = QDoubleSpinBox()
                sb.setRange(0, 300)
                sb.setDecimals(1 if col > 0 else 0)
                sb.setValue(float(params[col]))
                sb.setStyleSheet(_ss)
                self.crack_table.setCellWidget(row, col, sb)

    def _get_crack_table_data(self) -> dict:
        data = {}
        for row, key in enumerate(["FC", "SC"]):
            data[key] = [
                self.crack_table.cellWidget(row, col).value()  # type: ignore[union-attr]
                for col in range(4)
            ]
        return data

    def _populate_airwave_pid_table(self) -> None:
        keys = list(self.aw.bleAirwavepidparms.keys())
        self.pid_table.setRowCount(len(keys))
        self.pid_table.setVerticalHeaderLabels(keys)
        mode_options = ["FAN", "STD", "EXT"]
        _ss  = _table_spinbox_style()
        _css = _table_combobox_style()
        for row, key in enumerate(keys):
            params = self.aw.bleAirwavepidparms[key]
            for col in range(5):
                sb = QDoubleSpinBox()
                sb.setRange(0, 500)
                sb.setDecimals(1 if col == 0 else (2 if col == 1 else 0))
                sb.setValue(float(params[col]))
                sb.setStyleSheet(_ss)
                self.pid_table.setCellWidget(row, col, sb)
            cb = QComboBox()
            cb.addItems(mode_options)
            cb.setCurrentText(str(params[5]))
            cb.setStyleSheet(_css)
            self.pid_table.setCellWidget(row, 5, cb)
            ramp_sb = QDoubleSpinBox()
            ramp_sb.setRange(0.05, 2.0)
            ramp_sb.setDecimals(2)
            ramp_sb.setSingleStep(0.05)
            ramp_sb.setStyleSheet(_ss)
            ramp_sb.setToolTip(
                QApplication.translate(
                    "tilauscope_devices",
                    "Ramp speed toward target fan speed (% per cycle ~1 s). "
                    "0.20 = gentle (~75 s for 15% change). "
                    "0.50 = fast (~30 s for 15% change).",
                )
            )
            ramp_val = float(params[6]) if len(params) > 6 else 0.25
            ramp_sb.setValue(ramp_val)
            self.pid_table.setCellWidget(row, 6, ramp_sb)

    def _get_airwave_pid_data(self) -> dict:
        new_params = {}
        keys = list(self.aw.bleAirwavepidparms.keys())
        for row, key in enumerate(keys):
            widgets = [self.pid_table.cellWidget(row, c) for c in range(7)]
            if all(w is not None for w in widgets):
                new_params[key] = (
                    float(widgets[0].value()),   # type: ignore[union-attr]
                    float(widgets[1].value()),   # type: ignore[union-attr]
                    float(widgets[2].value()),   # type: ignore[union-attr]
                    int(widgets[3].value()),     # type: ignore[union-attr]
                    int(widgets[4].value()),     # type: ignore[union-attr]
                    widgets[5].currentText(),    # type: ignore[union-attr]
                    float(widgets[6].value()),   # type: ignore[union-attr]
                )
        return new_params

    # ─────────────────────────────────────────────────────────────────────────
    # Background sensor detection
    #
    # While the SENSORS tab is active, the central TilauBLEScanner streams
    # advertisements; each group matches them by BLE name prefix and drives its
    # own combo + status pill. An assigned-but-absent device is never cleared —
    # only the 🗑 button unassigns it (written as None on Save, reversible via Cancel).
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_prefixes() -> "dict[str, str]":
        """BLE advertised-name prefixes per sensor, with literal fallbacks."""
        prefixes = {
            "ambient":   "TLSCAM",
            "airwave":   "AirWave ",
            "skywalker": "TD5325A",
            "c1":        "RoastSee C1",
            "aquagauge": "RoastSee AquaGauge",
            "niimbot":   "B21",
        }
        try:
            from tilauscope.tilauambient import TILAUAMBIENT_PREFIX
            prefixes["ambient"] = TILAUAMBIENT_PREFIX
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            from tilauscope.difluid import AIRWAVE_PREFIX
            prefixes["airwave"] = AIRWAVE_PREFIX
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            from tilauscope.tc4ble import SKYWALKER_PREFIX
            prefixes["skywalker"] = SKYWALKER_PREFIX
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            from tilauscope.lebrewroastsee import C1_PREFIX, AG_PREFIX
            prefixes["c1"] = C1_PREFIX
            prefixes["aquagauge"] = AG_PREFIX
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            from tilauscope.niimprint import NIIMBOT_PREFIX
            prefixes["niimbot"] = NIIMBOT_PREFIX
        except Exception:  # pylint: disable=broad-except
            pass
        return prefixes

    def _no_device_text(self) -> str:
        return QApplication.translate("tilauscope_devices", "— no device —")

    def _sensor_cell(self, label: str, prefix: str, combo: QComboBox,
                     name_attr: str, list_attr: str) -> QWidget:
        """Build the right-hand cell (status pill + 🗑 button) for one sensor
        row, register the group for background detection, and seed the combo
        from the persisted assignment."""
        g = _SensorGroup(label, prefix, combo, name_attr, list_attr)

        # Mocha-style the popup (macOS top-level popup ignores dialog QSS)
        combo.setView(_styled_combo_view())
        # let the combo shrink to the available width (the long UUID no
        # longer forces the row wider than the dialog → no horizontal scrollbar);
        # the current text elides and the full id stays visible in the popup.
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(140)

        status = QLabel()
        status.setMinimumWidth(_SCAN_BTN_W)
        g.status = status

        # A static "scanning…" says nothing about being alive. The ring does,
        # and it is the same one every long operation in the app uses.
        spinner = TilauProgress(TilauProgress.RING, 12)
        spinner.setVisible(False)
        g.spinner = spinner

        trash = QPushButton("🗑")
        trash.setStyleSheet(_btn_trash())
        trash.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        trash.setToolTip(
            QApplication.translate("tilauscope_devices", "Forget this device (unassign)")
        )
        trash.clicked.connect(lambda _=False, gg=g: self._on_trash(gg))
        combo.activated.connect(lambda _=0, gg=g: self._on_user_selected(gg))

        self._seed_sensor_combo(g)
        self._sensor_groups.append(g)
        self._update_status(g)

        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(spinner)
        h.addWidget(status)
        h.addWidget(trash)
        return cell

    def _seed_sensor_combo(self, g: "_SensorGroup") -> None:
        """Seed a combo from the persisted assignment. A configured-but-offline
        device stays shown and selected so it is never lost."""
        combo = g.combo
        combo.blockSignals(True)
        combo.clear()
        assigned = getattr(self.aw, g.name_attr, None)
        if assigned:
            combo.addItem(f"{g.label} ({assigned})")
            g.was_assigned = True
        else:
            combo.addItem(self._no_device_text())
            g.was_assigned = False
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    @staticmethod
    def _combo_item_ids(combo: QComboBox) -> set:
        ids: set = set()
        for i in range(combo.count()):
            m = re.search(r'\(([^)]+)\)', combo.itemText(i))
            if m:
                ids.add(m.group(1).strip())
        return ids

    def _set_pill(self, status: "QLabel | None", text: str, color: str,
                  spinner=None, busy: bool = False) -> None:
        """Single place that writes a sensor status. Text and ring move
        together, so 'searching' never reads as 'stalled'."""
        if status is not None:
            status.setText(text)
            status.setStyleSheet(
                f"color:{color}; font-size:11px; font-weight:bold;"
                f" background:transparent;"
            )
        if spinner is not None:
            if busy:
                spinner.set_indeterminate()
            spinner.setVisible(busy)

    def _update_status(self, g: "_SensorGroup") -> None:
        """Refresh the status pill from the current selection + live sightings."""
        if self._hook_attempted and not self._bt_available:
            self._set_pill(
                g.status,
                QApplication.translate("tilauscope_devices", "⚠ bluetooth off"),
                THEME['WARNING'], g.spinner, False)
            return
        txt = g.combo.currentText()
        sel_id = None
        if txt != self._no_device_text():
            m = re.search(r'\(([^)]+)\)', txt)
            if m:
                sel_id = m.group(1).strip()
        if sel_id:
            if sel_id in g.seen:
                self._set_pill(
                    g.status,
                    QApplication.translate("tilauscope_devices", "detected ✓"),
                    THEME['SUCCESS'], g.spinner, False)
            else:
                # Configured but not seen: the device may simply be off, so no
                # ring — a spinner that never stops reads as a stuck app.
                self._set_pill(
                    g.status,
                    QApplication.translate("tilauscope_devices", "assigned"),
                    THEME['ACCENT'], g.spinner, False)
        elif g.seen:
            self._set_pill(
                g.status,
                f"{len(g.seen)} " + QApplication.translate("tilauscope_devices", "found ✓"),
                THEME['SUCCESS'], g.spinner, False)
        else:
            self._set_pill(
                g.status,
                QApplication.translate("tilauscope_devices", "scanning…"),
                THEME['SUBTEXT'], g.spinner, True)

    # ── scanner wiring (SENSORS tab lifetime) ──────────────────────────────

    @pyqtSlot(int)
    def _on_tab_changed(self, index: int) -> None:
        if self._tabs.widget(index) is self._sensors_tab:
            self._hook_scanner()
        else:
            self._unhook_scanner()

    def _hook_scanner(self) -> None:
        """Subscribe to the central BLE scanner. Reuse the BeanCave shell's
        scanner when present (single CBCentralManager on macOS); otherwise spin
        up a private one for the SENSORS tab's lifetime."""
        if self._scanner_hooked:
            return
        self._hook_attempted = True

        scanner = None
        bc = getattr(self.aw, "beancaveWindow", None)
        if bc is not None:
            scanner = getattr(bc, "_ble_scanner", None)

        if scanner is not None:
            # A running BeanCave scanner implies Bluetooth is available; do not
            # probe CoreBluetooth again (avoids CBCentralManager contention).
            self._bt_available = True
        else:
            try:
                from artisanlib.ble_port import bluetooth_enabled
                self._bt_available = bluetooth_enabled()
            except Exception:  # pylint: disable=broad-except
                self._bt_available = False
            if self._bt_available:
                try:
                    from tilauscope.tilau_ble_scanner import TilauBLEScanner
                    scanner = TilauBLEScanner(self)
                    scanner.start()
                    self._own_scanner = scanner
                except Exception as e:  # pylint: disable=broad-except
                    _log.exception("TilauScope config: private scanner start failed: %s", e)
                    scanner = None

        self._scanner = scanner
        if scanner is not None and hasattr(scanner, "devices_found"):
            try:
                scanner.devices_found.connect(self._on_devices_found)
                self._scanner_hooked = True
            except Exception as e:  # pylint: disable=broad-except
                _log.exception("TilauScope config: scanner hook failed: %s", e)

        for g in self._sensor_groups:
            self._update_status(g)

    def _unhook_scanner(self) -> None:
        if self._scanner is not None and self._scanner_hooked:
            try:
                self._scanner.devices_found.disconnect(self._on_devices_found)
            except Exception:  # pylint: disable=broad-except
                pass
        self._scanner_hooked = False
        if self._own_scanner is not None:
            try:
                self._own_scanner.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            self._own_scanner = None
        self._scanner = None

    @pyqtSlot(list)
    def _on_devices_found(self, devices: list) -> None:
        """Slot on TilauBLEScanner.devices_found — match advertisements to rows
        by BLE name prefix and update each combo + status pill live."""
        try:
            for g in self._sensor_groups:
                for bd, _ad in devices:
                    name = getattr(bd, "name", None)
                    addr = getattr(bd, "address", None)
                    if name and addr and g.prefix and name.startswith(g.prefix):
                        g.seen.add(addr)
                        self._add_detected(g, addr)
                if g.seen:
                    # mirror the candidate id list for the picker widget
                    try:
                        setattr(self.aw, g.list_attr, sorted(g.seen))
                    except Exception:  # pylint: disable=broad-except
                        pass
                self._maybe_autoselect(g)
                self._update_status(g)
            # surface everything else recognisable but not wired up
            self._scan_other_hardware(devices)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception("TilauScope config: _on_devices_found failed: %s", e)

    def _add_detected(self, g: "_SensorGroup", address: str) -> None:
        """Add a newly seen device to the combo (dedup by address). Never
        removes the assigned item — the keep-assignment invariant holds."""
        if address in self._combo_item_ids(g.combo):
            return
        g.combo.blockSignals(True)
        g.combo.addItem(f"{g.label} ({address})")
        g.combo.blockSignals(False)

    def _maybe_autoselect(self, g: "_SensorGroup") -> None:
        """Auto-select a single detected device when nothing was assigned and the
        user has not intervened. Multiple detected → leave the choice open."""
        if g.cleared or g.user_touched or g.auto_done or g.was_assigned:
            return
        real = [i for i in range(g.combo.count())
                if g.combo.itemText(i) != self._no_device_text()]
        if len(real) == 1:
            g.combo.blockSignals(True)
            g.combo.setCurrentIndex(real[0])
            g.combo.blockSignals(False)
            g.auto_done = True

    def _on_trash(self, g: "_SensorGroup") -> None:
        """Explicit unassign: deselect the device and suppress auto-select for
        this group. Detected/assigned items are kept in the list so they stay
        re-selectable immediately (no wait for the next scan cycle). The None
        write happens on Save (reversible via Cancel)."""
        g.cleared = True
        g.user_touched = True
        g.was_assigned = False
        g.auto_done = True
        combo = g.combo
        no_dev = self._no_device_text()
        combo.blockSignals(True)
        if combo.itemText(0) != no_dev:
            combo.insertItem(0, no_dev)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._update_status(g)

    def _on_user_selected(self, g: "_SensorGroup") -> None:
        g.user_touched = True
        if g.combo.currentText() != self._no_device_text():
            g.cleared = False
        self._update_status(g)

    # ── other hardware detected nearby (identify only, no linking) ─────────

    def _build_other_section(self, layout: QVBoxLayout) -> None:
        """Section at the bottom of the SENSORS tab that lists every nearby BLE
        device that is recognisable but not wired up — known third-party brands
        AND our own sensors seen but left unassigned. Fed live by the scanner;
        identification only, nothing is paired, linked or persisted."""
        layout.addSpacing(6)
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "Other hardware detected nearby")
        ))
        host = QWidget()
        vl = QVBoxLayout(host)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)
        empty = QLabel(QApplication.translate(
            "tilauscope_devices",
            "nothing else recognised nearby — these are identified, not configured"))
        empty.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px; font-style:italic;"
            f" background:transparent; padding:2px 0;"
        )
        vl.addWidget(empty)
        layout.addWidget(host)
        self._other_host = host
        self._other_layout = vl
        self._other_empty = empty

    def _assigned_ids(self) -> set:
        """BLE ids currently selected in the sensor combos (i.e. wired up)."""
        ids: set = set()
        no_dev = self._no_device_text()
        for g in self._sensor_groups:
            txt = g.combo.currentText()
            if txt and txt != no_dev:
                m = re.search(r'\(([^)]+)\)', txt)
                if m:
                    ids.add(m.group(1).strip())
        return ids

    def _classify_other(self, bd, ad) -> "tuple[str, str, bool] | None":
        """Return (label, signature, is_own) for a nearby device, or None if it
        is not recognisable. is_own=True → one of our sensors left unassigned."""
        name = getattr(bd, "name", None) or getattr(ad, "local_name", None) or ""
        # 1. one of our own sensors, matched by advertised-name prefix
        for g in self._sensor_groups:
            if g.prefix and name.startswith(g.prefix):
                return (g.label, name or "—", True)
        # 2. a known third-party Artisan BLE device (shared onboarding catalog)
        try:
            from tilauscope.onboarding import (
                _KNOWN_BLE_SIGNATURES, _ble_signature_match,
            )
        except Exception:  # pylint: disable=broad-except
            return None
        for label, prefix, service_uuid in _KNOWN_BLE_SIGNATURES:
            if _ble_signature_match(bd, ad, prefix, service_uuid):
                return (label, name or "—", False)
        return None

    def _scan_other_hardware(self, devices: list) -> None:
        """Accumulate recognisable nearby devices, then refresh the rows so only
        the ones not currently wired up are shown."""
        if self._other_layout is None:
            return
        for bd, ad in devices:
            addr = getattr(bd, "address", None) or getattr(bd, "name", None)
            if not addr or addr in self._other_seen:
                continue
            info = self._classify_other(bd, ad)
            if info is not None:
                self._other_seen[addr] = info
        self._refresh_other_rows()

    def _refresh_other_rows(self) -> None:
        """Show one row per recognisable device that is NOT currently assigned;
        drop rows for devices that just got wired up. Toggles the empty state."""
        if self._other_layout is None:
            return
        assigned = self._assigned_ids()
        visible = {a: info for a, info in self._other_seen.items() if a not in assigned}
        # remove rows that no longer belong (now assigned)
        for addr in list(self._other_rows.keys()):
            if addr not in visible:
                row = self._other_rows.pop(addr)
                row.setParent(None)
                row.deleteLater()
        # add rows for newly visible devices
        for addr, (label, sig, is_own) in visible.items():
            if addr not in self._other_rows:
                self._other_rows[addr] = self._add_other_row(label, sig, is_own)
        if self._other_empty is not None:
            self._other_empty.setVisible(not self._other_rows)

    def _add_other_row(self, label: str, signature: str, is_own: bool) -> QWidget:
        """Build a single identify-only row (dot · name · signature · tag)."""
        accent = THEME['WARNING'] if is_own else THEME['MAUVE']  # mauve for third-party
        tag_txt = (QApplication.translate("tilauscope_devices", "detected · not linked")
                   if is_own else
                   QApplication.translate("tilauscope_devices", "recognised · not configured"))
        row = QFrame()
        row.setStyleSheet(
            f"background:{THEME['SURFACE']}; border:1px solid {THEME['BORDER']};"
            f" border-radius:9px;"
        )
        hl = QHBoxLayout(row)
        hl.setContentsMargins(12, 8, 12, 8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{accent}; font-size:11px; background:transparent;")
        nl = QLabel(label)
        nl.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:13px; font-weight:600; background:transparent;")
        sig = QLabel(signature)
        sig.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px;"
            f" background:transparent;")
        tag = QLabel(tag_txt)
        tag.setStyleSheet(
            f"color:{accent}; font-size:11px;"
            f" background:transparent;")
        hl.addWidget(dot)
        hl.addWidget(nl)
        hl.addSpacing(8)
        hl.addWidget(sig)
        hl.addStretch()
        hl.addWidget(tag)
        self._other_layout.addWidget(row)
        return row

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT sensors
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_mqtt_sensors(self, form_layout: QFormLayout) -> None:
        """Sensor table under the broker fields. Cells are edited in place; the
        stored list is rebuilt from the table when the dialog is applied."""
        from tilauscope.mqttbridge import TilauMqttPorts
        self._mqtt_ports = TilauMqttPorts(None)  # persistence only, no broker needed
        self._mqtt_sensors = self._mqtt_ports.load_mqtt_sensors()

        form_layout.addRow(_section_label(
            QApplication.translate("tilauscope_devices", "Sensors")
        ))

        self.mqtt_sensor_table = QTableWidget()
        self._mqtt_sensor_headers = [
            QApplication.translate("tilauscope_devices", "ID"),
            QApplication.translate("tilauscope_devices", "Topic"),
            QApplication.translate("tilauscope_devices", "Command"),
            QApplication.translate("tilauscope_devices", "Multiplier"),
            QApplication.translate("tilauscope_devices", "Divider"),
            QApplication.translate("tilauscope_devices", "Unit"),
        ]
        self.mqtt_sensor_table.setColumnCount(len(self._mqtt_sensor_headers))
        self.mqtt_sensor_table.setHorizontalHeaderLabels(self._mqtt_sensor_headers)
        header = self.mqtt_sensor_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._mqtt_cell_delegate = OpaqueCellDelegate(self.mqtt_sensor_table)
        self.mqtt_sensor_table.setItemDelegate(self._mqtt_cell_delegate)
        self.mqtt_sensor_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.mqtt_sensor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mqtt_sensor_table.setMinimumHeight(140)
        self._populate_mqtt_sensor_table()
        form_layout.addRow(self.mqtt_sensor_table)

        buttons = QWidget()
        btn_layout = QHBoxLayout(buttons)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.mqttAddSensorButton = QPushButton(
            QApplication.translate("tilauscope_devices", "Add sensor")
        )
        self.mqttAddSensorButton.setProperty('variant', 'outline')
        self.mqttAddSensorButton.clicked.connect(self._mqtt_add_sensor_row)
        self.mqttDeleteSensorButton = QPushButton(
            QApplication.translate("tilauscope_devices", "Delete")
        )
        self.mqttDeleteSensorButton.setProperty('variant', 'outline')
        self.mqttDeleteSensorButton.clicked.connect(self._mqtt_delete_sensor_row)
        self.mqttCheckSensorButton = QPushButton(
            QApplication.translate("tilauscope_devices", "Check sensor")
        )
        self.mqttCheckSensorButton.setProperty('variant', 'outline')
        self.mqttCheckSensorButton.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "Connect to the broker with the settings above and read the selected sensor once."
        ))
        self.mqttCheckSensorButton.clicked.connect(self._mqtt_check_sensor)
        btn_layout.addWidget(self.mqttAddSensorButton)
        btn_layout.addWidget(self.mqttDeleteSensorButton)
        btn_layout.addStretch()
        btn_layout.addWidget(self.mqttCheckSensorButton)
        form_layout.addRow(buttons)

    def _set_mqtt_row_widgets(self, row: int, multiplier: float | None,
                              divider: float | None, unit: str) -> None:
        """Cell widgets of one sensor row: the two scaling factors and the unit."""
        _ss = _table_spinbox_style()
        for col, value in ((3, multiplier), (4, divider)):
            sb = QDoubleSpinBox()
            sb.setRange(0, 10000)
            sb.setDecimals(1)
            sb.setValue(1.0 if value is None else float(value))
            sb.setStyleSheet(_ss)
            self.mqtt_sensor_table.setCellWidget(row, col, sb)
        cb = QComboBox()
        for code, label in _MQTT_SENSOR_UNITS:
            cb.addItem(label, code)
        index = cb.findData(unit if unit in ("C", "F") else "")
        cb.setCurrentIndex(max(index, 0))
        cb.setStyleSheet(_table_combobox_style())
        cb.setToolTip(QApplication.translate(
            "tilauscope_devices",
            "Unit the sensor publishes in. A temperature is converted to the unit "
            "the application works in; leave empty for anything that is not a temperature."
        ))
        self.mqtt_sensor_table.setCellWidget(row, 5, cb)

    def _populate_mqtt_sensor_table(self) -> None:
        sensors = self._mqtt_sensors.sensors
        self.mqtt_sensor_table.setRowCount(len(sensors))
        for row, sensor in enumerate(sensors):
            for col, value in enumerate((sensor.id, sensor.topic, sensor.command)):
                self.mqtt_sensor_table.setItem(row, col, QTableWidgetItem(value or ""))
            self._set_mqtt_row_widgets(row, sensor.multiplier, sensor.divider, sensor.unit)

    def _get_mqtt_sensor_data(self) -> 'MQTTSensorConfig':
        """Rebuild the sensor list from the table. Rows without an id or a topic
        are dropped: they are half-typed rows, not sensors."""
        from tilauscope.tilauscope_types import MQTTSensor, MQTTSensorConfig
        sensors: list[MQTTSensor] = []
        for row in range(self.mqtt_sensor_table.rowCount()):
            def _text(col: int, row: int = row) -> str:
                item = self.mqtt_sensor_table.item(row, col)
                return item.text().strip() if item is not None else ""
            def _num(col: int, row: int = row) -> float:
                w = self.mqtt_sensor_table.cellWidget(row, col)
                return float(w.value()) if isinstance(w, QDoubleSpinBox) else 1.0
            def _unit(row: int = row) -> str:
                w = self.mqtt_sensor_table.cellWidget(row, 5)
                return str(w.currentData() or "") if isinstance(w, QComboBox) else ""
            sensor_id, topic = _text(0), _text(1)
            if not sensor_id or not topic:
                continue
            sensors.append(MQTTSensor(
                id=sensor_id,
                topic=topic,
                command=_text(2),
                multiplier=_num(3),
                divider=_num(4),
                unit=_unit(),
            ))
        return MQTTSensorConfig(sensors=sensors)

    @pyqtSlot()
    def _mqtt_add_sensor_row(self) -> None:
        row = self.mqtt_sensor_table.rowCount()
        self.mqtt_sensor_table.insertRow(row)
        for col in range(3):
            self.mqtt_sensor_table.setItem(row, col, QTableWidgetItem(""))
        self._set_mqtt_row_widgets(row, 1.0, 1.0, "")
        self.mqtt_sensor_table.selectRow(row)
        self.mqtt_sensor_table.editItem(self.mqtt_sensor_table.item(row, 0))

    @pyqtSlot()
    def _mqtt_delete_sensor_row(self) -> None:
        row = self.mqtt_sensor_table.currentRow()
        if row < 0:
            return
        self.mqtt_sensor_table.removeRow(row)

    @pyqtSlot()
    def _mqtt_check_sensor(self) -> None:
        """Probe the selected row against a short-lived connection built from the
        broker fields as currently typed, so a sensor can be verified before the
        settings have ever been saved."""
        from tilauscope.mqttbridge import TilauscopeMQTTClient, TilauMqttPorts
        row = self.mqtt_sensor_table.currentRow()
        if row < 0:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Check sensor"),
                QApplication.translate("tilauscope_devices", "Select a sensor row first."),
                QMessageBox.Icon.Warning,
            )
            return
        candidates = self._get_mqtt_sensor_data().sensors
        item = self.mqtt_sensor_table.item(row, 0)
        sensor_id = item.text().strip() if item is not None else ""
        sensor = next((s for s in candidates if s.id == sensor_id), None)
        if sensor is None:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Check sensor"),
                QApplication.translate("tilauscope_devices", "This row needs an ID and a topic before it can be checked."),
                QMessageBox.Icon.Warning,
            )
            return

        client = TilauscopeMQTTClient(self._mqtt_config_from_form(), self.aw)
        result = None
        try:
            if client.start():
                # same conversion the sampling loop applies, so the reported
                # figure is the one that will be recorded
                result = TilauMqttPorts(client).check_sensor(sensor, mode=self.aw.qmc.mode)
        except Exception as e:  # noqa: BLE001
            _log.error("MQTT sensor check failed: %s", e)
        finally:
            client.stop()

        if result is not None and result.ok:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "MQTT Sensor OK"),
                QApplication.translate("tilauscope_devices", "Value read for {0}: {1} {2}").format(
                    sensor.id, result.value,
                    f"°{self.aw.qmc.mode}" if sensor.unit else "").strip(),
            )
        else:
            detail = "" if result is None else f"{result.error.name} — {result.message or ''}"
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "MQTT Sensor Check Failed"),
                QApplication.translate(
                    "tilauscope_devices",
                    "No value could be read for {0}.\n{1}\n\nThe sensor is kept: a topic that is silent right now may still be valid."
                ).format(sensor.id, detail),
                QMessageBox.Icon.Warning,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT test
    # ─────────────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _mqtt_config_from_form(self) -> 'MQTTConfig':
        """Broker settings exactly as typed, without waiting for OK — both the
        connection test and the sensor check work on what is on screen."""
        from tilauscope.mqttbridge import MQTTConfig
        config = MQTTConfig(
            broker_url=self.mqttBrokerEdit.text(),
            port=self.mqttPortSpin.value(),
            topic=self.mqttTopicEdit.text(),
            tls=self.mqttTlsCheck.isChecked(),
            protocol_version=self.mqttProtocolCombo.currentIndex(),
            connect_timeout=self.mqttTimeoutSpin.value(),
            keepalive=self.mqttKeepaliveSpin.value(),
        )
        config.username = self.mqttUsernameEdit.text()
        config.password = self.mqttPasswordEdit.text()
        return config

    def _mqtt_tls_toggled(self, checked: bool) -> None:
        """Follow the standard port pair when TLS is switched, but only while the
        port still holds the default of the other mode — a port typed by hand is
        never overwritten."""
        if checked and self.mqttPortSpin.value() == _MQTT_PORT_PLAIN:
            self.mqttPortSpin.setValue(_MQTT_PORT_TLS)
        elif not checked and self.mqttPortSpin.value() == _MQTT_PORT_TLS:
            self.mqttPortSpin.setValue(_MQTT_PORT_PLAIN)

    def _test_mqtt_connection(self) -> None:
        from tilauscope.mqttbridge import TilauscopeMQTTClient
        mqtt_client = TilauscopeMQTTClient(self._mqtt_config_from_form(), self.aw)
        connected = mqtt_client.start()
        mqtt_client.stop()
        if connected:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "MQTT Connection Test"),
                QApplication.translate("tilauscope_devices", "Connection to MQTT broker successful!"),
            )
        else:
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "MQTT Connection Test"),
                QApplication.translate("tilauscope_devices", "Failed to connect to MQTT broker."),
                QMessageBox.Icon.Warning,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # AI helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _ai_update_status_label(self) -> None:
        cfg = self.aw.tilau_aiConfig
        if cfg.is_configured:
            key_hint = "●●●●●●" + cfg.apikey[-4:] if len(cfg.apikey) > 4 else "●●●●●●"
            text = (
                f"<b>{cfg.provider_name}</b> — {cfg.engine}<br>"
                f"<span style='color:grey;font-size:10px;'>Key: {key_hint}</span>"
            )
        else:
            text = (
                f"<span style='color:{THEME['WARNING']};'>"
                + QApplication.translate("tilauscope_devices", "Not configured — AI features disabled")
                + "</span>"
            )
        self._ai_status_lbl.setText(text)
        self._ai_status_lbl.setTextFormat(Qt.TextFormat.RichText)

    @pyqtSlot()
    def _open_ai_provider_picker(self) -> None:
        from tilauscope.ai_support import AIProviderPickerDialog
        dlg = AIProviderPickerDialog(self.aw.tilau_aiConfig, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.aw.tilau_aiConfig = dlg.result_config
            if hasattr(self.aw, "tilau_ai_service"):
                self.aw.tilau_ai_service.ai_config = self.aw.tilau_aiConfig
            self._ai_update_status_label()

    # ─────────────────────────────────────────────────────────────────────────
    # Ok / Cancel
    # ─────────────────────────────────────────────────────────────────────────

    _SLIDER_VIS_BACKUP_KEY = "tilauscope/slider_vis_backup"

    def _apply_roaster_slider_visibilities(self) -> None:
        """Apply the explicit read-only flag (devices.py checkbox →
        aw.tilau_roaster_readonly) to Artisan's slider visibilities:
          - read-only ticked  → snapshot the current config once, then disable
            all control sliders ([0,0,0,0]) (monitoring only);
          - read-only unticked → restore the snapshot taken when it was ticked
            (no clobber of the operator's manual slider setup); if there is no
            snapshot, leave the configuration untouched.
        The AirWave / Damper (idx 2) is governed separately by
        _apply_airwave_damper_mapping(), which re-claims it after this runs.
        Refreshes the Artisan slider dock and the TilauScope panel (if open)."""
        aw = self.aw
        try:
            n = len(aw.eventslidervisibilities)
            readonly = bool(getattr(aw, "tilau_roaster_readonly", False))
            s = QSettings()
            key = self._SLIDER_VIS_BACKUP_KEY
            if readonly:
                if s.value(key, None) is None:  # snapshot once, on entering read-only
                    s.setValue(key, ",".join(str(int(v)) for v in aw.eventslidervisibilities))
                aw.eventslidervisibilities = [0] * n
            else:
                backup = s.value(key, None)
                if backup:
                    try:
                        vals = [int(x) for x in str(backup).split(",") if x != ""]
                    except ValueError:
                        vals = [1] * n
                    if len(vals) < n:
                        vals = vals + [1] * (n - len(vals))
                    aw.eventslidervisibilities = vals[:n]
                    s.remove(key)
                # no snapshot → leave the config exactly as the operator set it

            # Apply per-slider visibility WITHOUT forcing the Artisan slider
            # dock open or closed: that overall shown/hidden state is the user's
            # own choice (Artisan View menu) and must be preserved.
            aw.updateSlidersProperties()

            # Mirror onto the TilauScope panel if it is currently open
            tsm = getattr(aw, "tilauscope_main", None)
            if tsm is not None and hasattr(tsm, "_apply_slider_visibility_mirror"):
                tsm._apply_slider_visibility_mirror()
        except Exception:
            _logd.exception("TilauScope: _apply_roaster_slider_visibilities failed")

    def _apply_airwave_damper_mapping(self) -> None:
        """When an AirWave is configured, map the Damper slider
        (idx 2) to the DiFluid AirWave: action 'Difluid Airwave Command'
        (stored id 20), command 'FAN {}', range 30-100, step 1, renamed
        'Airwave', and kept visible even on a read-only roaster (the AirWave is
        a separate BLE extractor). POWER ON/OFF and MODE FAN/STD/EXT stay
        alarm-driven (expert tool). Only (re)writes the mapping when it is not
        already in place; always ensures the slider stays visible."""
        aw = self.aw
        DAMPER = 2
        try:
            if not getattr(aw, "bleAirwaveDeviceName", None):
                return  # no AirWave configured → nothing to map
            already = (aw.eventslideractions[DAMPER] == 20
                       and aw.eventslidervisibilities[DAMPER] == 1)
            if not already:
                aw.eventslideractions[DAMPER]  = 20          # Difluid Airwave Command
                aw.eventslidercommands[DAMPER] = "FAN {}"
                aw.eventslidermin[DAMPER]      = 30
                aw.eventslidermax[DAMPER]      = 100
                aw.eventsliderfactors[DAMPER]  = 1.0
                aw.eventslideroffsets[DAMPER]  = 0.0
                aw.eventslidercoarse[DAMPER]   = 0           # step of 1
                try:
                    aw.qmc.etypes[DAMPER] = "Airwave"
                except Exception:
                    pass
            # AirWave present → damper slider stays available even read-only
            aw.eventslidervisibilities[DAMPER] = 1

            # Apply per-slider visibility only; never force the Artisan dock
            # open/closed (user's own choice).
            aw.updateSlidersProperties()
            tsm = getattr(aw, "tilauscope_main", None)
            if tsm is not None and hasattr(tsm, "_apply_slider_visibility_mirror"):
                tsm._apply_slider_visibility_mirror()
        except Exception:
            _logd.exception("TilauScope: _apply_airwave_damper_mapping failed")

    @pyqtSlot()
    def _pair_phone(self) -> None:
        # open the desktop pairing modal (QR + device list + revoke)
        host = getattr(self.aw, 'tilau_web_host', None)
        if host is None or not host.control_active():
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Remote control is off"),
                QApplication.translate("tilauscope_devices",
                    "Enable remote control, click OK, restart TilauScope, then pair a phone."),
            )
            return
        from tilauscope.pairing_dialog import PairingDialog
        port = QSettings().value('tilauscope/remote_port', 8765, type=int)
        PairingDialog(host, port, self).exec()

    def _setup_beancave_tab(self) -> None:
        """Directories used by BeanCave and by the roast-history tools."""
        scroll = _scrollable(self._beancave_tab)
        layout = scroll.widget().layout()
        layout.addWidget(_section_label(
            QApplication.translate("tilauscope_devices", "BeanCave files")
        ))

        explanation = QLabel(QApplication.translate(
            "tilauscope_devices",
            "Choose where the green-bean database and the Artisan roast logs (.alog) are stored."
        ))
        explanation.setWordWrap(True)
        explanation.setProperty('variant', 'secondary')
        layout.addWidget(explanation)

        group = QGroupBox(QApplication.translate("tilauscope_devices", "Directories"))
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        settings = QSettings()
        alog_dir = settings.value("alogDirectory", "", str) or ""
        beancave_dir = settings.value("beancaveDirectory", alog_dir, str) or ""

        self.beancaveDirectoryEdit = self._directory_row(
            form,
            QApplication.translate("tilauscope_devices", "BeanCave database:"),
            beancave_dir,
            "beancave",
        )
        self.alogDirectoryEdit = self._directory_row(
            form,
            QApplication.translate("tilauscope_devices", "Roast logs (.alog):"),
            alog_dir,
            "alog",
        )
        layout.addWidget(group)
        layout.addStretch()

    def _directory_row(self, form: QFormLayout, label: str, value: str,
                       kind: str) -> QLineEdit:
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        edit.setReadOnly(True)
        edit.setPlaceholderText(QApplication.translate("tilauscope_devices", "Not configured"))
        button = QPushButton(QApplication.translate("tilauscope_devices", "Choose…"))
        button.setProperty('variant', 'outline')
        button.clicked.connect(lambda _checked=False: self._choose_beancave_directory(kind, edit))
        row_layout.addWidget(edit, 1)
        row_layout.addWidget(button)
        form.addRow(_field_label(label), row)
        return edit

    def _choose_beancave_directory(self, kind: str, edit: QLineEdit) -> None:
        start = edit.text().strip()
        if not start or not Path(start).is_dir():
            start = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation)
        title = (QApplication.translate("tilauscope_devices", "Select BeanCave directory")
                 if kind == "beancave" else
                 QApplication.translate("tilauscope_devices", "Select ALog directory"))
        directory = QFileDialog.getExistingDirectory(self, title, start)
        if not directory:
            return
        path = Path(directory)
        if not path.is_dir() or not os.access(directory, os.W_OK):
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Invalid directory"),
                QApplication.translate(
                    "tilauscope_devices",
                    "Choose an existing directory where TilauScope has write permission."
                ),
                QMessageBox.Icon.Warning,
            )
            return
        edit.setText(directory)

    def _on_ok(self) -> None:
        aw = self.aw
        self._unhook_scanner()  # stop background sensor detection
        _no_dev = self._no_device_text()  # explicit-unassign placeholder

        # ── BeanCave ──────────────────────────────────────────────────────
        settings = QSettings()
        settings.setValue("beancaveDirectory", self.beancaveDirectoryEdit.text().strip())
        settings.setValue("alogDirectory", self.alogDirectoryEdit.text().strip())

        # ── General ───────────────────────────────────────────────────────
        aw.tilau_roaster = (
            self.tilauRoaster.currentText()
            if self.tilauRoaster.currentIndex() > 0
            else "")
        aw.tilau_roaster_readonly = self.tilauRoasterReadonly.isChecked()
        from tilauscope.roasters import sync_roaster_to_qmc
        sync_roaster_to_qmc(aw, aw.tilau_roaster) # mirror onto the canvas machine label
        self._apply_roaster_slider_visibilities()
        aw.TilauScopeAnnotation  = self.tilauScopeAnnotationCheckBox.isChecked()
        aw.TilauScopeNotification = self.tilauScopeNotificationCheckBox.isChecked()

        # ── Sensors — Ambient ─────────────────────────────────────────────
        t = self.tilauscopeProbeComboBoxcList.currentText()
        if t and t != _no_dev:
            m = re.search(r'\((.*?)\)', t)
            aw.bleTilauScopeDeviceName = m.group(1) if m else t
        else:
            aw.bleTilauScopeDeviceName = None  # unassigned via 🗑
        # Acoustic crack sensitivity (device-level)
        aw.bleTilauScopeFCTreshold = self.tilauAmbientCrackThresholdSpin.value()

        # ── Sensors — AirWave ─────────────────────────────────────────────
        t = self.AirwaveComboBox.currentText()
        if t and t != _no_dev:
            m = re.search(r'\((.*?)\)', t)
            aw.bleAirwaveDeviceName = m.group(1) if m else t
        else:
            aw.bleAirwaveDeviceName = None  # unassigned via 🗑
        aw.bleAirwavepidOnET         = self.AirwavePidOnETCheckVBox.isChecked()
        aw.bleAirwavepidRamp         = self.AirwavePidRampSpinBox.value()
        aw.bleAirwaveEmulateOmniflux = self.AirwaveEmulateOmnifluxCheckVBox.isChecked()
        aw.bleAirwavepidparms        = self._get_airwave_pid_data()
        # AirWave configured → map the Damper slider onto it (runs
        # after the roaster visibilities so it re-claims idx 2 even read-only)
        self._apply_airwave_damper_mapping()

        # Only accept a real BLE identifier from the combos: an empty scan leaves
        # "No X found" as the combo text, which must not overwrite the stored UUID.
        # macOS: Core Bluetooth UUID — Windows: MAC address
        _ble_uuid_pat = re.compile(
            r'^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
            r'|([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})$')

        def _combo_ble_id(text: str) -> str | None:
            m = re.search(r'\(([^)]+)\)', text) if text else None
            if m and _ble_uuid_pat.match(m.group(1).strip()):
                return m.group(1).strip()
            return None

        # ── Roaster — Skywalker (TC4-BLE) ──
        # An explicit 🗑 (placeholder) unassigns; otherwise only a valid id writes,
        # so an assigned-but-absent device keeps its assignment.
        _sw_txt = self.SkywalkerComboBox.currentText()
        if _sw_txt == _no_dev:
            aw.bleSkywalkerDeviceName = None
        else:
            _bid = _combo_ble_id(_sw_txt)
            if _bid is not None:
                aw.bleSkywalkerDeviceName = _bid

        # ── Sensors — Lebrew C1 ───────────────────────────────────────────
        _c1_txt = self.lebrewRoastSeeC1ComboBox.currentText()
        if _c1_txt == _no_dev:
            aw.bleRoastSeeDeviceName = None
        else:
            _bid = _combo_ble_id(_c1_txt)
            if _bid is not None:
                aw.bleRoastSeeDeviceName = _bid

        # ── Sensors — AquaGauge ───────────────────────────────────────────
        _ag_txt = self.lebrewRoastSeeAGComboBox.currentText()
        if _ag_txt == _no_dev:
            aw.bleRoastSeeAGDeviceName = None
        else:
            _bid = _combo_ble_id(_ag_txt)
            if _bid is not None:
                aw.bleRoastSeeAGDeviceName = _bid

        # ── Sensors — Niimbot ─────────────────────────────────────────────
        t = self.niimbotComboBox.currentText()
        if t and t != _no_dev:
            m = re.search(r'\(([^)]+)\)', t)
            uuid_candidate = m.group(1) if m else t
            _uuid_pat = re.compile(
                r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            )
            aw.bleNiimbotDeviceName = uuid_candidate if _uuid_pat.match(uuid_candidate) else None
        else:
            aw.bleNiimbotDeviceName = None

        # ── Detection ─────────────────────────────────────────────────────
        aw.TilauScopeFCMarkFlag  = self.fcMarking.isChecked()
        aw.TilauScopeFCWindow    = self.fcWindowSpin.value()
        aw.TilauScopeFCTreshold  = self.fcThresholdSpin.value()
        aw.TilauScopeDEMarkFlag  = self.deMarking.isChecked()
        aw.TilauScopeCrackParams = self._get_crack_table_data()

        # FC automark flag is kept in sync: algorithm is active ↔ FC marking on
        aw.bleTilauScopeautomarkFC = self.fcMarking.isChecked()

        # ── Integrations — MQTT ───────────────────────────────────────────
        aw.mqttConfig.broker_url = self.mqttBrokerEdit.text()
        aw.mqttConfig.port       = self.mqttPortSpin.value()
        aw.mqttConfig.tls        = self.mqttTlsCheck.isChecked()
        aw.mqttConfig.protocol_version = self.mqttProtocolCombo.currentIndex()
        aw.mqttConfig.connect_timeout  = self.mqttTimeoutSpin.value()
        aw.mqttConfig.keepalive        = self.mqttKeepaliveSpin.value()
        aw.mqttConfig.topic      = self.mqttTopicEdit.text()
        aw.mqttConfig.username   = self.mqttUsernameEdit.text()
        aw.mqttConfig.password   = self.mqttPasswordEdit.text()
        aw.mqttConfig.poll_topic    = self.mqttPollTopicEdit.text().strip()
        aw.mqttConfig.poll_interval = self.mqttPollIntervalSpin.value()

        # sensor list is rebuilt from the table and persisted to QSettings
        self._mqtt_sensors = self._get_mqtt_sensor_data()
        self._mqtt_ports.save_mqtt_sensors(self._mqtt_sensors)

        # headless "BeanCave home" mode -> QSettings (boot-time; restart)
        _h_prev = QSettings().value('tilauscope/headless_mode', False, type=bool)
        _h_new  = self.headlessModeCheckBox.isChecked()
        if _h_new != _h_prev:
            QSettings().setValue('tilauscope/headless_mode', _h_new)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Restart required"),
                QApplication.translate("tilauscope_devices",
                    "BeanCave home mode will take effect the next time you start TilauScope."),
            )

        # record web server port -> QSettings (spec wiki/QR-Scan-Spec.md §2.1)
        _p_prev = QSettings().value('tilauscope/web_port', 8123, type=int)
        _p_new  = self.webPortSpin.value()
        if _p_new != _p_prev:
            QSettings().setValue('tilauscope/web_port', _p_new)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Restart required"),
                QApplication.translate("tilauscope_devices",
                    "The record web server port will take effect the next time you "
                    "start TilauScope. Labels printed from now on will encode the new port."),
            )

        # remote control (phone piloting) -> QSettings (boot-time; restart)
        _r_prev  = QSettings().value('tilauscope/remote_enabled', False, type=bool)
        _r_new   = self.remoteControlCheckBox.isChecked()
        _rp_prev = QSettings().value('tilauscope/remote_port', 8765, type=int)
        _rp_new  = self.remotePortSpin.value()
        if _r_new != _r_prev or _rp_new != _rp_prev:
            QSettings().setValue('tilauscope/remote_enabled', _r_new)
            QSettings().setValue('tilauscope/remote_port', _rp_new)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_devices", "Restart required"),
                QApplication.translate("tilauscope_devices",
                    "Remote control will take effect the next time you start TilauScope."),
            )

        # label size — takes effect on the next print, no restart needed
        QSettings().setValue("tilauscope/label_size_mm", self.labelSizeCombo.currentData())

        # AI config saved immediately in _open_ai_provider_picker
        self.accept()

    @pyqtSlot()
    def _on_cancel(self) -> None:
        self._unhook_scanner()  # stop background sensor detection
        aw = self.aw
        for key, val in self._org.items():
            if isinstance(val, dict):
                setattr(aw, key, val.copy())
            else:
                setattr(aw, key, val)
        self.reject()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _scrollable(parent: QWidget) -> QScrollArea:
    """Wrap a tab widget's root in a scrollable area with a QVBoxLayout content."""
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    # content only scrolls vertically — never show a horizontal bar
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 12, 0, 12)
    lay.setSpacing(12)
    scroll.setWidget(content)

    tab_layout = QVBoxLayout(parent)
    tab_layout.setContentsMargins(0, 0, 0, 0)
    tab_layout.addWidget(scroll)

    return scroll

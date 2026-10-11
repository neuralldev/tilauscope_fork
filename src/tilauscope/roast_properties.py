#
# ABOUT
# Beancave – Roast Properties (pre-roast setup dialog)
#
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

"""RoastSetupDialog (shown before a roast, sets up Artisan qmc fields from a
GreenBean) and RoastResultDialog (shown after a roast to record weight/colour/notes)."""

from __future__ import annotations
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Final
from datetime import datetime

from tilauscope.roast_insights import build_insights
from tilauscope.guidance_phase import milestone_marked
from tilauscope.roast_debrief import roast_colour_agtron
from tilauscope.theme_qss import base_qss, apply_tilau_theme, tooltip_qss, tint, mono_family
from tilauscope.roasters import RoasterManager, canonical_roaster_name
from tilauscope.probe_visibility import et_available_for, et_available_in_profile
from tilauscope.sack_manager import prompt_release_if_emptied
from PyQt6.QtCore    import Qt, QPropertyAnimation, pyqtSlot, QTimer, QSettings, QSize
from PyQt6.QtCore import QThread, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QWidget, QCheckBox, QComboBox,
    QButtonGroup,
    QSizePolicy, QMessageBox, QApplication,
    QTabWidget, QSpinBox,
)
from PyQt6.QtWidgets import QGridLayout, QStackedWidget, QScrollArea, QProgressBar
from PyQt6.QtWidgets import (
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizeGrip, QSplitter, QAbstractItemView, QFileDialog,
)
from PyQt6.QtGui import QColor, QKeyEvent, QFontMetrics, QIcon

from artisanlib.util import fromCtoFstrict, convertWeight, weight_units, events_internal_to_external_value
from tilauscope.tilauscope_types import (
    GreenBean, THEME, show_styled_message, AGTRON_SCALES, format_batch_label, roast_batch_tag,
    open_in_os_viewer, ensure_color_system, resolve_color_system, call_later,
    get_agtron_color, decode_alog_text, SCREEN_SIZE_RANGES, operator_level,
    park_until_finished,
)

# AI modules are optional — guard against ImportError if not yet deployed
try:
    from tilauscope.ai_service import AITask
    from tilauscope.ai_float_panel import AIFloatPanel
    _AI_AVAILABLE = True
except ImportError:
    AITask = None        # type: ignore[assignment]
    AIFloatPanel = None  # type: ignore[assignment]
    _AI_AVAILABLE = False

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow
    from tilauscope.beancave import BeancaveDlg
    from tilauscope.ai_float_panel import AIFloatPanel  # noqa: F811  # type: ignore[assignment]
    from tilauscope.ai_service import AITask            # noqa: F811  # type: ignore[assignment]

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")


def _weight_unit_index(unit: object) -> int:
    """Artisan's index for a weight unit; an unknown unit reads as grams."""
    try:
        return weight_units.index(str(unit))
    except ValueError:
        return 0


def _to_grams(value: object, unit: object) -> float:
    """A weight Artisan keeps in `unit`, in grams (0.0 when unreadable)."""
    try:
        return convertWeight(float(value), _weight_unit_index(unit), 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _from_grams(grams: float, unit: object) -> float:
    """Grams typed in a form, in the unit Artisan keeps the profile in."""
    return convertWeight(float(grams), 0, _weight_unit_index(unit))


# ─────────────────────────────────────────────────────────────────────────────
# Tiny stylesheet helpers
# ─────────────────────────────────────────────────────────────────────────────

# What these dialogs still have to say on top of
# theme_qss.base_qss(). Everything the base already expresses — window ground,
# labels, text fields, checkboxes, scrollbars — has been removed; what is left
# is only what this file needs differently. See wiki/Theme-QSS-Spec.md.
def _local_style() -> str:
    return f"""
        /* combobox-popup 0 keeps the native popup here, unlike the
           configuration dialog: these combos are short and the native list
           positions itself better over a scrolled form. */
        QComboBox {{ combobox-popup: 0; }}
        QComboBox::drop-down {{ border: none; }}

        /* macOS shows a combo popup as its own top-level window, which does
           not inherit a descendant sheet; these rules only bite on Windows,
           and _ScaleFloatWindow-style combos style their view directly. */
        QComboBox QAbstractItemView {{ background: {THEME['BG']}; }}
        QComboBox QAbstractScrollArea QWidget {{ background-color: {THEME['BG']}; }}

        /* Save / Cancel close the window — larger than inline buttons. */
        QPushButton#footerBtn {{
            border-radius: 8px;
            font-size: 13px;
            padding: 10px 28px;
        }}

        /* A dense setup form: the 12px base scrollbar eats the width the
           weight and colour rows need. */
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


def _btn_warning() -> str:
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {THEME['WARNING']};
            border: 1px solid {THEME['WARNING']};
            border-radius: 8px;
            font-size: 12px;
            padding: 8px 16px;
        }}
        QPushButton:hover {{ background-color: {THEME['WARNING']}; color: {THEME['BG']}; }}
    """


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {THEME['ACCENT']}; font-size: 12px; font-weight: bold;"
        f"letter-spacing: 2px; margin-top: 6px;"
    )
    return lbl


class _ElidedLabel(QLabel):
    """Single-line label that trims its text to the width it is given, full
    text kept in the tooltip. A free-length string in a fixed-width card must
    never widen its parent."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._apply_elide()

    def _apply_elide(self) -> None:
        fm = QFontMetrics(self.font())
        super().setText(
            fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        )

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._apply_elide()


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {THEME['BORDER']}; background: {THEME['BORDER']}; max-height:1px;")
    return sep


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty('variant', 'secondary')
    lbl.setMinimumWidth(130)
    return lbl


def _value_label(text: str, accent: bool = False) -> QLabel:
    color = THEME['ACCENT'] if accent else THEME['TEXT']
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; font-size: 13px; font-weight: {'bold' if accent else 'normal'};"
    )
    return lbl


def _input_row(label_text: str, widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(_field_label(label_text))
    row.addWidget(widget, 1)
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Batch block — shared by RoastSetupDialog (preview) and RoastResultDialog (edit)
#
# Artisan batch model:
#   global  : qmc.batchcounter (-1 = system off), qmc.batchsequence, qmc.batchprefix
#   profile : qmc.roastbatchnr (0 = unassigned), qmc.roastbatchprefix, qmc.roastbatchpos
# The number is assigned by Artisan at DROP (incBatchCounter). This widget never
# advances the counter: SETUP previews it, RESULT edits the already-assigned value.
# ─────────────────────────────────────────────────────────────────────────────

class _BatchBlock(QFrame):
    """Compact batch widget with two rendering modes.

    MODE_PREVIEW (setup, pre-CHARGE)
        Shows the *forecast* identity ``{batchprefix}{batchcounter+1}`` plus an
        "track batches" toggle that delegates activation of the batch system
        (so the user never has to open Artisan's batch dialog). The counter is
        never mutated here — Artisan assigns the real number at DROP.

    MODE_EDIT (result, post-DROP)
        Shows the assigned identity ``{roastbatchprefix}{roastbatchnr} (pos)``.
        Prefix / number / position are locked by default; a padlock toggle
        unlocks them for an explicit, deliberate correction.
    """

    MODE_PREVIEW: Final[int] = 0
    MODE_EDIT:    Final[int] = 1

    def __init__(self, aw: 'ApplicationWindow', mode: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._aw   = aw
        self._mode = mode
        self.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 10px; }} QLabel {{ border: none; background: transparent; }}"
        )
        qmc = aw.qmc

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(14)

        # ── Big identity badge (left) ─────────────────────────────────────
        self._badge = QLabel()
        self._badge.setProperty('variant', 'readout')
        self._badge.setStyleSheet(f"color: {THEME['TEXT']};")
        root.addWidget(self._badge)

        # status pill + hint
        tag_col = QVBoxLayout()
        tag_col.setSpacing(3)
        self._pill = QLabel()
        self._pill.setStyleSheet(self._pill_style(self._mode == self.MODE_EDIT))
        self._pill.setAlignment(Qt.AlignmentFlag.AlignLeft)
        tag_col.addWidget(self._pill, 0, Qt.AlignmentFlag.AlignLeft)
        self._hint = QLabel()
        self._hint.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px;")
        tag_col.addWidget(self._hint)
        root.addLayout(tag_col)
        root.addStretch(1)

        # ── Editors (right) ───────────────────────────────────────────────
        self._prefix_edit = QLineEdit(qmc.roastbatchprefix or qmc.batchprefix or "#")
        self._prefix_edit.setFixedWidth(46)
        self._prefix_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prefix_edit.setStyleSheet(self._edit_style())

        if mode == self.MODE_PREVIEW:
            # only the prefix is editable in preview; the number is auto
            self._track_cb = QCheckBox(QApplication.translate("tilauscope_roast_setup", "track batches"))
            self._track_cb.setChecked(qmc.batchcounter > -1)
            self._track_cb.setStyleSheet(
                f"QCheckBox {{ color: {THEME['SUCCESS']}; font-size: 11px;"
                f"spacing: 6px; }}"
            )
            self._track_cb.toggled.connect(self._refresh)
            self._prefix_edit.textChanged.connect(lambda _=None: self._refresh())
            root.addWidget(_field_label_compact(QApplication.translate("tilauscope_roast_setup", "prefix")))
            root.addWidget(self._prefix_edit)
            root.addWidget(self._track_cb)
        else:
            # MODE_EDIT — prefix + number + position, locked behind a padlock
            self._nr_spin = QSpinBox()
            self._nr_spin.setRange(0, 65534)
            self._nr_spin.setValue(int(qmc.roastbatchnr or 0))
            self._nr_spin.setFixedWidth(78)
            self._nr_spin.setStyleSheet(self._spin_style())
            self._pos_spin = QSpinBox()
            self._pos_spin.setRange(1, 99)
            self._pos_spin.setValue(int(qmc.roastbatchpos or 1))
            self._pos_spin.setFixedWidth(58)
            self._pos_spin.setStyleSheet(self._spin_style())

            self._lock_btn = QPushButton("\U0001F512")  # 🔒
            self._lock_btn.setCheckable(True)
            self._lock_btn.setFixedSize(34, 30)
            self._lock_btn.setProperty('variant', 'icon')   # fixed size: no base padding
            self._lock_btn.setToolTip(QApplication.translate(
                "tilauscope_roast_setup", "Unlock to correct the assigned batch number"))
            self._lock_btn.toggled.connect(self._set_unlocked)
            self._lock_btn.setStyleSheet(self._lock_style())

            root.addWidget(_field_label_compact(QApplication.translate("tilauscope_roast_setup", "n°")))
            root.addWidget(self._prefix_edit)
            root.addWidget(self._nr_spin)
            root.addWidget(_field_label_compact(QApplication.translate("tilauscope_roast_setup", "pos")))
            root.addWidget(self._pos_spin)
            root.addWidget(self._lock_btn)
            self._set_unlocked(False)  # locked by default

        self._refresh()

    # ── styling helpers ───────────────────────────────────────────────────
    @staticmethod
    def _pill_style(assigned: bool) -> str:
        color = THEME['SUCCESS'] if assigned else THEME['TODAY']
        return (f"color: {color}; font-size: 10px; font-weight: bold;"
                f"padding: 1px 0px;")

    @staticmethod
    def _edit_style() -> str:
        return (f"QLineEdit {{ background: {THEME['BG']}; color: {THEME['TEXT']};"
                f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 5px;"
                f"font-size: 13px; }} "
                f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }} "
                f"QLineEdit:disabled {{ color: {THEME['SUBTEXT']}; }}")

    @staticmethod
    def _spin_style() -> str:
        return (f"QSpinBox {{ background: {THEME['BG']}; color: {THEME['TEXT']};"
                f"border: 1px solid {THEME['BORDER']}; border-radius: 6px; padding: 4px;"
                f"font-family: 'JetBrains Mono'; font-size: 13px; }} "
                f"QSpinBox:focus {{ border-color: {THEME['ACCENT']}; }} "
                f"QSpinBox:disabled {{ color: {THEME['SUBTEXT']}; }}")

    @staticmethod
    def _lock_style() -> str:
        return (f"QPushButton {{ background: {THEME['BG']}; border: 1px solid {THEME['BORDER']};"
                f"border-radius: 6px; font-size: 14px; }} "
                f"QPushButton:hover {{ border-color: {THEME['ACCENT']}; }} "
                f"QPushButton:checked {{ border-color: {THEME['SUCCESS']}; }}")

    # ── behaviour ─────────────────────────────────────────────────────────
    def _set_unlocked(self, unlocked: bool) -> None:
        for w in (self._prefix_edit, self._nr_spin, self._pos_spin):
            w.setEnabled(unlocked)
        self._lock_btn.setText("\U0001F513" if unlocked else "\U0001F512")  # 🔓 / 🔒

    def _refresh(self) -> None:
        qmc = self._aw.qmc
        if self._mode == self.MODE_PREVIEW:
            track = self._track_cb.isChecked()
            self._prefix_edit.setEnabled(track)
            if track:
                nr = max(int(qmc.batchcounter), 0) + 1  # forecast — never mutates the counter
                self._badge.setText(f"{self._prefix_edit.text()}{nr}")
                self._pill.setText(QApplication.translate("tilauscope_roast_setup", "forecast"))
                self._hint.setText(QApplication.translate(
                    "tilauscope_roast_setup", "assigned at DROP"))
            else:
                self._badge.setText("—")
                self._pill.setText(QApplication.translate("tilauscope_roast_setup", "off"))
                self._hint.setText(QApplication.translate(
                    "tilauscope_roast_setup", "batch tracking disabled"))
        else:
            label = format_batch_label(qmc.roastbatchprefix, qmc.roastbatchnr, qmc.roastbatchpos)
            self._badge.setText(label or "—")
            self._pill.setText(
                QApplication.translate("tilauscope_common", "assigned")
                if label else QApplication.translate("tilauscope_roast_setup", "unassigned"))
            self._hint.setText("" if label else QApplication.translate(
                "tilauscope_roast_setup", "no batch number for this roast"))

    # ── persistence ───────────────────────────────────────────────────────
    def apply_to_qmc(self) -> None:
        """Write the user's choices back to qmc. Never advances batchcounter."""
        qmc = self._aw.qmc
        if self._mode == self.MODE_PREVIEW:
            track = self._track_cb.isChecked()
            qmc.batchprefix = self._prefix_edit.text() or "#"
            if track and qmc.batchcounter < 0:
                qmc.batchcounter = 0          # delegate activation (next DROP → #1)
            elif not track:
                qmc.batchcounter = -1         # delegate deactivation
            # keep an existing positive counter untouched
        else:
            qmc.roastbatchprefix = self._prefix_edit.text() or "#"
            qmc.roastbatchnr     = int(self._nr_spin.value())
            qmc.roastbatchpos    = int(self._pos_spin.value())


def _field_label_compact(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {THEME['SUBTEXT']}; font-size: 10px; "
    )
    return lbl


# ─────────────────────────────────────────────────────────────────────────────
# Floating scale weight window  (mirrors the LebrewWaterActivity approach)
# ─────────────────────────────────────────────────────────────────────────────

class _ScaleFloatWindow(QDialog):
    """
    Small always-on-top window showing live scale reading.
    Click on the weight value → transfers it to the green-weight field.
    """

    def __init__(self, parent: 'RoastSetupDialog') -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._parent_dialog = parent
        self._weight: float | None = None
        # a reconnect releases the dead link first, and that release reports a
        # disconnect: while we are connecting, it is not news to show
        self._connecting = False
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("scaleCard")
        self._card.setStyleSheet(f"""
            QFrame#scaleCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
        """)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 14, 20, 14)
        card_layout.setSpacing(4)

        header = QLabel(QApplication.translate("tilauscope_roast_setup", "⚖  SCALE"))
        header.setProperty('variant', 'eyebrow')
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._weight_lbl = QLabel("–– g")
        self._weight_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._weight_lbl.setProperty('variant', 'readout')
        self._weight_lbl.setStyleSheet(f"color: {THEME['ACCENT']};")
        self._weight_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._weight_lbl.setToolTip(f"<span style='font-size: 10px;'>{QApplication.translate('tilauscope_roast_setup', 'Click to transfer weight<br>Double-click to TARE')}</span>")
        self._weight_lbl.mousePressEvent = self._on_weight_clicked  # type: ignore[method-assign]
        self._weight_lbl.mouseDoubleClickEvent = self._on_weight_double_clicked  # type: ignore[method-assign]

        self._hint_lbl = QLabel(QApplication.translate("tilauscope_common", "tap to use"))
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_lbl.setProperty('variant', 'caption')

        card_layout.addWidget(header)
        card_layout.addWidget(self._weight_lbl)
        card_layout.addWidget(self._hint_lbl)
        outer.addWidget(self._card)
        self.adjustSize()

    # ── Public slots ─────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def update_weight(self, weight: int) -> None:
        self._connecting = False
        self._weight = weight
        self._weight_lbl.setText(f"{weight} g")

    @pyqtSlot()
    def scale_disconnected(self) -> None:
        if self._connecting:
            return
        self._weight = None
        self._weight_lbl.setText("–– g")
        self._hint_lbl.setText(QApplication.translate("tilauscope_roast_setup", "disconnected"))

    # connection feedback: without it the card sat on "–– g" with no
    # clue that the scale had gone idle during the roast.
    def set_status(self, text: str) -> None:
        self._hint_lbl.setText(text)

    def scale_connecting(self) -> None:
        self._connecting = True
        self._weight = None
        self._weight_lbl.setText("–– g")
        self.set_status(QApplication.translate("tilauscope_roast_setup", "connecting…"))

    def scale_ready(self) -> None:
        self._connecting = False
        self.set_status(QApplication.translate("tilauscope_common", "tap to use"))

    # ── Interaction ──────────────────────────────────────────────────────────

    def _on_weight_clicked(self, _event) -> None:  # noqa: ANN001
        if self._weight is None:
            # no reading yet → the click is a manual reconnect request
            retry = getattr(self._parent_dialog, 'request_scale_connect', None)
            if callable(retry):
                retry()
            return
        self._parent_dialog.receive_scale_weight(self._weight)

    def _on_weight_double_clicked(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                # Emit the tare signal to scale 1 via the scale manager
                self._parent_dialog._aw.scale_manager.tare_scale1_signal.emit()
                _logd.debug("Scale tare triggered via double-click in pre-roast setup")
            except Exception as e:
                _log.error(f"Failed to tare scale: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Floating ambient conditions window  (mirrors _ScaleFloatWindow)
# ─────────────────────────────────────────────────────────────────────────────

# Inline SVG icons — 20×20, path-only, rendered via QLabel pixmap
_SVG_TEMP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<rect x="8" y="2" width="4" height="10" rx="2" fill="{color}"/>'
    '<circle cx="10" cy="14" r="4" fill="{color}"/>'
    '<rect x="9" y="4" width="2" height="8" rx="1" fill="#1e1e2e"/>'
    '</svg>'
)
_SVG_HUM = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<path d="M10 2 C10 2 4 10 4 14 a6 6 0 0 0 12 0 C16 10 10 2 10 2z" fill="{color}"/>'
    '<path d="M10 6 C10 6 6 12 6 14 a4 4 0 0 0 8 0 C14 12 10 6 10 6z" fill="#1e1e2e" opacity="0.4"/>'
    '</svg>'
)
_SVG_PRESSURE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<circle cx="10" cy="10" r="8" fill="none" stroke="{color}" stroke-width="2"/>'
    '<line x1="10" y1="10" x2="10" y2="4" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
    '<line x1="10" y1="10" x2="14" y2="12" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>'
    '<circle cx="10" cy="10" r="1.5" fill="{color}"/>'
    '</svg>'
)


def _svg_pixmap(svg_template: str, color: str, size: int = 20):
    """Render an SVG template string to a QPixmap."""
    from PyQt6.QtSvg  import QSvgRenderer
    from PyQt6.QtGui  import QPixmap, QPainter
    from PyQt6.QtCore import QByteArray
    svg_bytes = QByteArray(svg_template.format(color=color).encode())
    renderer  = QSvgRenderer(svg_bytes)
    pix       = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter   = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return pix


def _temp_color(temp: float, _is_fahrenheit: bool = False) -> str:
    """Colour that reflects temperature comfort level."""
    if (temp < 59 if _is_fahrenheit else temp < 15):  return "#89b4fa"
    if (temp < 77 if _is_fahrenheit else temp < 22):  return "#a6e3a1"
    if (temp < 85 if _is_fahrenheit else temp < 28):  return "#fab387"
    return "#f38ba8"                   # hot – red


def _hum_color(hum: float) -> str:
    if hum < 30:    return THEME['CRITICAL']   # too dry – red
    if hum < 60:    return "#a6e3a1"   # ideal – green
    return THEME['ACCENT']                   # humid – blue


def _plan_uses_text(card) -> str:  # noqa: ANN001
    """What the plan is built on while a room card has no reading of its own."""
    unit = "°F" if card._aw.qmc.mode == "F" else "°C"
    reading = card.temperature
    default = 20.0 if unit == "°C" else 68.0
    temp = f"{reading if reading is not None else default:.0f}\u00a0{unit}"
    alt = card.altitude
    if alt is None:
        alt = card._parent_dialog._artisan_elevation()
    if alt > 0:
        return QApplication.translate("tilauscope_roast_setup", "Plan now uses {0}, {1} m").format(
            temp, f"{alt:.0f}")
    return QApplication.translate("tilauscope_roast_setup", "Plan now uses {0}, sea level").format(temp)


def _age_text(epoch: float) -> str:
    """How long ago a reading was taken, in words."""
    secs = max(0.0, time.time() - epoch)
    if secs < 120:
        return QApplication.translate("tilauscope_common", "just now")
    if secs < 3600:
        return QApplication.translate("tilauscope_roast_setup", "{0} min ago").format(int(secs // 60))
    if secs < 2 * 86400:
        return QApplication.translate("tilauscope_roast_setup", "{0} h ago").format(int(secs // 3600))
    return QApplication.translate("tilauscope_roast_setup", "{0} days ago").format(int(secs // 86400))


class _AmbientFloatWindow(QDialog):
    """
    Small always-on-top card displaying live ambient temperature, humidity
    and pressure from the TilauScope probe.

    The probe is managed externally: by BeanCave (bleTilauAmbientDevice)
    during pre-roast setup, or by Artisan (aw.bleTilauScopeDevice, via
    startTilauAmbientManager / stopTilauAmbientManager) once monitoring has
    started. This card simply observes:

    · It connects to the device's connected_signal / disconnected_signal at
      show-time, then detaches at close.
    · While the probe is connected it polls get_ambient() every
      POLL_INTERVAL_MS via a QTimer (main-thread, no extra thread needed –
      get_ambient() returns the probe's last cached reading).
    · If no device is available when the card opens it waits, showing
      "waiting for probe", and wires up as soon as one appears (checked on
      each timer tick).
    · Every valid reading is remembered. While the probe is silent (a plan
      prepared away from the roaster) the card shows the last one, greyed and
      dated, and the plan is built on it.
    """

    POLL_INTERVAL_MS: Final[int] = 4_000
    LAST_READING_KEY: Final[str] = "tilauscope/ambient_last_reading"
    CARD_WIDTH:       Final[int] = 140   # same width as scale card

    def __init__(self, parent: 'RoastSetupDialog') -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._parent_dialog = parent
        self._aw            = parent._aw
        self._probe_live    = False      # True while connected_signal has been received
        self._device_ref    = None       # the bleTilauScopeDevice we are wired to

        # values to keep for parent
        self._temperature:float|None = None
        self._humidity:float|None = None
        self._pressure:float|None = None
        self._altitude:float|None = None
        self._reading_time: float | None = None   # epoch of the values above
        self._showing_last = False                # values on screen are a past reading

        self._build_ui()
        self._load_last_reading()

        # ── Polling timer (main-thread, safe to update widgets directly) ──────
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        # Wire to whatever device currently exists (may be None → retried each
        # tick, so a probe that connects after the dialog opened is picked up).
        self._attach_device()
        self._timer.start()

    # properties
    @property
    def temperature(self) -> float | None:
        """Last good reading in the DISPLAY unit — that is what qmc.ambientTemp
        holds (Artisan converts on sampling). Use temperature_c for the plan."""
        if self._temperature is None:
            return None
        return self._temperature if self._aw.qmc.mode == "C" else fromCtoFstrict(self._temperature)

    @property
    def temperature_c(self) -> float | None:
        """Last good reading in °C — internal unit of the whole plan chain."""
        return self._temperature

    @property
    def humidity(self) -> float | None:
        return self._humidity

    @property
    def pressure(self) -> float | None:
        return self._pressure

    @property
    def altitude(self) -> float | None:
        """Altitude the probe derives from its pressure reading (m), None until one arrives."""
        return self._altitude

    # ── Device wiring ─────────────────────────────────────────────────────────

    def _attach_device(self) -> None:
        """Wire to the LIVE probe. During pre-roast setup the probe is managed by
        BeanCave (self._parent_widget.bleTilauAmbientDevice), not by Artisan's
        aw.bleTilauScopeDevice — the latter stays None until roast monitoring
        starts via ToggleMonitor. Falls back to aw.bleTilauScopeDevice in case
        the dialog is ever reused outside BeanCave.

        Never instantiate a private TilauAmbient here: BeanCave already owns
        the one BLE client for this probe UUID; a second client here would
        just fight it for the connection.
        """
        beancave = getattr(self._parent_dialog, '_parent_widget', None)
        device = getattr(beancave, 'bleTilauAmbientDevice', None) \
            or getattr(self._aw, 'bleTilauScopeDevice', None)
        if device is None or device is self._device_ref:
            return
        self._detach_device()
        try:
            device.connected_signal.connect(self._on_probe_connected)
            device.disconnected_signal.connect(self._on_probe_disconnected)
            self._device_ref = device
            _logd.debug("AmbientCard: attached to ambient probe device")
            # If the device is already connected, reflect that immediately
            if getattr(device, 'is_connected', False):
                self._on_probe_connected()
        except Exception as exc:  # noqa: BLE001
            _log.warning("AmbientCard: could not attach to device: %s", exc)

    def _detach_device(self) -> None:
        """Unwire only — the probe belongs to Artisan and must stay connected."""
        if self._device_ref is None:
            return
        try:
            self._device_ref.connected_signal.disconnect(self._on_probe_connected)
            self._device_ref.disconnected_signal.disconnect(self._on_probe_disconnected)
        except Exception:  # noqa: BLE001
            pass
        self._device_ref = None

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("ambientCard")
        self._card.setFixedWidth(self.CARD_WIDTH)
        self._card.setStyleSheet(f"""
            QFrame#ambientCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
        """)
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(8)

        # Header
        header = QLabel(QApplication.translate("tilauscope_roast_setup", "🌡  AMBIENT"))
        header.setProperty('variant', 'eyebrow')
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(header)

        # Metric rows
        self._temp_row,  self._temp_val  = self._make_row(_SVG_TEMP,     THEME['ACCENT'])
        self._hum_row,   self._hum_val   = self._make_row(_SVG_HUM,      THEME['ACCENT'])
        self._press_row, self._press_val = self._make_row(_SVG_PRESSURE, THEME['SUBTEXT'])
        cl.addLayout(self._temp_row)
        cl.addLayout(self._hum_row)
        cl.addLayout(self._press_row)

        # Status hint
        self._status_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "waiting for probe"))
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setProperty('variant', 'caption')
        cl.addWidget(self._status_lbl)

        # What the plan is built on while the probe is silent
        self._note_lbl = QLabel()
        self._note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._note_lbl.setWordWrap(True)
        self._note_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 9px;")
        self._note_lbl.setVisible(False)
        cl.addWidget(self._note_lbl)

        outer.addWidget(self._card)
        self.adjustSize()

    @staticmethod
    def _make_row(svg_template: str, icon_color: str):
        """Return (QHBoxLayout, value_QLabel) for one metric row."""
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(18, 18)
        icon_lbl.setPixmap(_svg_pixmap(svg_template, icon_color, 18))

        val_lbl = QLabel("––")
        val_lbl.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 12px; font-weight: bold;"
        )
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(icon_lbl)
        row.addWidget(val_lbl, 1)
        return row, val_lbl

    # ── Probe signal slots ────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_probe_connected(self) -> None:
        self._probe_live = True
        # A remembered reading stays on screen, dated, until the first live one.
        if not self._showing_last:
            self._show_live_frame()
        self._timer.start()
        _logd.debug("AmbientCard: probe connected – polling started")

    @pyqtSlot()
    def _on_probe_disconnected(self) -> None:
        # The timer keeps running: it is also the re-attach watchdog.
        self._probe_live = False
        if self._reading_time is not None:
            self._show_last_reading()
        else:
            self._set_border(THEME['BORDER'])
            self._status_lbl.setText(QApplication.translate("tilauscope_roast_setup", "offline"))
            self._status_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 9px;")
            self._note_lbl.setText(_plan_uses_text(self))
            self._note_lbl.setVisible(True)
            self._temp_val.setText("––")
            self._hum_val.setText("––")
            self._press_val.setText("––")
            self.adjustSize()
        _logd.debug("AmbientCard: probe disconnected")

    # ── Card states ───────────────────────────────────────────────────────────

    def _set_border(self, colour: str) -> None:
        self._card.setStyleSheet(f"""
            QFrame#ambientCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {colour};
                border-radius: 16px;
            }}
        """)

    def _show_live_frame(self) -> None:
        self._showing_last = False
        self._set_border(THEME['ACCENT'])
        self._status_lbl.setText(QApplication.translate("tilauscope_roast_setup", "live"))
        self._status_lbl.setStyleSheet(
            f"color: {THEME['SUCCESS']}; font-size: 9px; "
        )
        self._note_lbl.setVisible(False)
        self._press_val.setStyleSheet(f"color: {THEME['TEXT']}; font-size: 12px; font-weight: bold;")
        self.adjustSize()

    def _show_last_reading(self) -> None:
        """The remembered reading, greyed and dated so it never reads as live."""
        if self._temperature is None or self._reading_time is None:
            return
        self._showing_last = True
        dim = THEME['SUBTEXT']
        self._set_border(THEME['BORDER'])
        temp = self._temperature if self._aw.qmc.mode == "C" else fromCtoFstrict(self._temperature)
        unit = "°F" if self._aw.qmc.mode == "F" else "°C"
        self._temp_row.itemAt(0).widget().setPixmap(_svg_pixmap(_SVG_TEMP, dim, 18))
        self._hum_row.itemAt(0).widget().setPixmap(_svg_pixmap(_SVG_HUM, dim, 18))
        self._temp_val.setText(f"{temp:.1f} {unit}")
        self._hum_val.setText(f"{self._humidity:.0f} %" if self._humidity is not None else "––")
        self._press_val.setText(f"{self._pressure:.0f} hPa" if self._pressure is not None else "––")
        for val in (self._temp_val, self._hum_val, self._press_val):
            val.setStyleSheet(f"color: {dim}; font-size: 12px; font-weight: bold;")
        self._status_lbl.setText(
            QApplication.translate("tilauscope_roast_setup", "last reading") + "\n" + _age_text(self._reading_time))
        self._status_lbl.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 9px;")
        self._note_lbl.setText(QApplication.translate("tilauscope_roast_setup", "Plan uses it until the probe answers"))
        self._note_lbl.setVisible(True)
        self.adjustSize()

    def _load_last_reading(self) -> None:
        """Start from the remembered reading, or say what the plan uses without one."""
        try:
            last = json.loads(str(QSettings().value(self.LAST_READING_KEY, "") or ""))
            self._temperature = float(last["t"])
            self._humidity = float(last["h"]) if last.get("h") is not None else None
            self._pressure = float(last["p"]) if last.get("p") is not None else None
            self._altitude = float(last["a"]) if last.get("a") is not None else None
            self._reading_time = float(last["at"])
        except (ValueError, TypeError, KeyError, AttributeError):
            self._temperature = self._humidity = self._pressure = self._altitude = None
            self._reading_time = None
        if self._reading_time is not None:
            self._show_last_reading()
        else:
            self._set_border(THEME['BORDER'])
            self._status_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 9px;")
            self._note_lbl.setText(_plan_uses_text(self))
            self._note_lbl.setVisible(True)
            self.adjustSize()

    def _remember_reading(self) -> None:
        if self._temperature is None or self._reading_time is None:
            return
        QSettings().setValue(self.LAST_READING_KEY, json.dumps({
            "t": self._temperature, "h": self._humidity, "p": self._pressure,
            "a": self._altitude, "at": self._reading_time}))

    # ── Polling tick ──────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_tick(self) -> None:
        # If the probe appeared (or was replaced) after the card opened, wire now
        if self._device_ref is None:
            self._attach_device()
            return

        if not self._probe_live:
            # connected_signal may have fired before we were wired
            if getattr(self._device_ref, 'is_connected', False):
                self._on_probe_connected()
            else:
                return

        try:
            # go through get_ambient(): it holds the command-idle guard shared
            # with Artisan's sampling loop.
            data = self._device_ref.get_ambient("AMBIENT")
        except Exception as exc:  # noqa: BLE001
            _log.warning("AmbientCard: read error: %s", exc)
            return

        if not getattr(data, 'valid', False):
            return   # stale/invalid packet – keep showing last good values

        temp  = data.temperature * 1.0 if self._aw.qmc.mode =="C" else fromCtoFstrict(data.temperature)
        hum   = data.humidity
        press = data.pressure
        # keep the last good reading: the dialog injects these into
        # qmc (ambientTemp / ambient_humidity / ambient_pressure) on OK and
        # feeds the roast plan. Stored in °C — converted at the boundary only.
        self._temperature = data.temperature
        self._humidity    = hum
        self._pressure    = press
        alt = getattr(data, 'altitude', None)
        self._altitude    = float(alt) if alt is not None and -500.0 <= float(alt) <= 6000.0 else None
        self._reading_time = time.time()   # persisted once, on close
        if self._showing_last or not self._note_lbl.isHidden():
            self._show_live_frame()
        tc    = _temp_color(temp)
        hc    = _hum_color(hum)

        # Update icons to reflect current value range
        self._temp_row.itemAt(0).widget().setPixmap(_svg_pixmap(_SVG_TEMP, tc, 18))
        self._hum_row.itemAt(0).widget().setPixmap(_svg_pixmap(_SVG_HUM,  hc, 18))

        unit = "°F" if self._aw.qmc.mode == "F" else "°C"
        self._temp_val.setText(f"{temp:.1f} {unit}")
        self._temp_val.setStyleSheet(
            f"color: {tc}; font-size: 12px; font-weight: bold; "
        )
        self._hum_val.setText(f"{hum:.0f} %")
        self._hum_val.setStyleSheet(
            f"color: {hc}; font-size: 12px; font-weight: bold; "
        )
        self._press_val.setText(f"{press:.0f} hPa")
        on_reading = getattr(self._parent_dialog, "_on_ambient_reading", None)
        if callable(on_reading):
            on_reading()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._timer.stop()
        self._detach_device()
        self._remember_reading()
        super().closeEvent(event)

_SVG_ALTITUDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
    '<path d="M2 16 L7.5 7 L11 12 L13 9 L18 16 Z" fill="none" stroke="{color}" stroke-width="1.8"'
    ' stroke-linejoin="round"/>'
    '</svg>'
)


class _WeatherWorker(QObject):
    """Runs the online weather lookup off the GUI thread; only its dict crosses back."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    @pyqtSlot()
    def run(self) -> None:
        from tilauscope.online_weather import fetch_online_weather  # noqa: PLC0415
        try:
            self.finished.emit(fetch_online_weather())
        except Exception as exc:  # noqa: BLE001
            _log.warning("Weather lookup failed: %s", exc)
            self.error.emit(str(exc))


class _WeatherFloatWindow(QDialog):
    """
    The room, for a setup with no ambient probe: the online weather on a tap,
    or values typed by hand. It stands where the AMBIENT card would.

    Nothing leaves the computer before a tap, and the first tap asks for
    consent (tilau_privacy_ui). A typed altitude is remembered — it does not
    change between roasts; the temperature and humidity do.

    Exposes the same readings as _AmbientFloatWindow (temperature in the
    display unit, temperature_c, humidity, pressure, altitude), so the dialog
    reads either card the same way.
    """

    CARD_WIDTH: Final[int] = 180
    ALTITUDE_KEY: Final[str] = "tilauscope/room_altitude_m"

    def __init__(self, parent: 'RoastSetupDialog') -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._parent_dialog = parent
        self._aw = parent._aw
        self._temperature: float | None = None   # °C
        self._humidity: float | None = None
        self._pressure: float | None = None
        self._altitude: float | None = None
        self._thread: QThread | None = None
        self._worker: _WeatherWorker | None = None
        try:
            stored = QSettings().value(self.ALTITUDE_KEY, None)
            self._remembered_altitude: float | None = float(stored) if stored not in (None, "") else None
        except (TypeError, ValueError):
            self._remembered_altitude = None
        self._build_ui()
        self._show_idle()

    # ── readings, same contract as the AMBIENT card ─────────────────────────────

    @property
    def temperature(self) -> float | None:
        if self._temperature is None:
            return None
        return self._temperature if self._aw.qmc.mode == "C" else fromCtoFstrict(self._temperature)

    @property
    def temperature_c(self) -> float | None:
        return self._temperature

    @property
    def humidity(self) -> float | None:
        return self._humidity

    @property
    def pressure(self) -> float | None:
        return self._pressure

    @property
    def altitude(self) -> float | None:
        return self._altitude if self._altitude is not None else self._remembered_altitude

    # ── UI ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame()
        self._card.setObjectName("weatherCard")
        self._card.setFixedWidth(self.CARD_WIDTH)
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(7)
        header = QLabel("☂  " + QApplication.translate("tilauscope_roast_setup", "WEATHER"))
        header.setProperty('variant', 'eyebrow')
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(header)

        link_css = self._link_css = (f"QPushButton {{ border: none; background: transparent; color: {THEME['ACCENT']};"
                    f"font-size: 12px; font-weight: bold; padding: 2px; }}"
                    f"QPushButton:disabled {{ color: {THEME['SUBTEXT']}; }}")
        caption_css = f"color: {THEME['SUBTEXT']}; font-size: 10px;"

        # Idle / locating / unavailable
        self._idle = QWidget()
        il = QVBoxLayout(self._idle)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(4)
        self._idle_btn = QPushButton()
        self._idle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._idle_btn.setStyleSheet(link_css)
        self._idle_btn.clicked.connect(self._request_weather)
        self._idle_note = QLabel()
        self._idle_note.setWordWrap(True)
        self._idle_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_note.setStyleSheet(caption_css)
        il.addWidget(self._idle_btn)
        il.addWidget(self._idle_note)
        cl.addWidget(self._idle)

        # Reading from the weather service
        self._reading = QWidget()
        rl = QVBoxLayout(self._reading)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self._temp_row, self._temp_val = _AmbientFloatWindow._make_row(_SVG_TEMP, THEME['ACCENT'])
        self._hum_row, self._hum_val = _AmbientFloatWindow._make_row(_SVG_HUM, THEME['ACCENT'])
        self._alt_row, self._alt_val = _AmbientFloatWindow._make_row(_SVG_ALTITUDE, THEME['SUBTEXT'])
        for row in (self._temp_row, self._hum_row, self._alt_row):
            rl.addLayout(row)
        self._place_lbl = QLabel()
        self._place_lbl.setWordWrap(True)
        self._place_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._place_lbl.setStyleSheet(caption_css)
        rl.addWidget(self._place_lbl)
        self._reading_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "Refresh"))
        self._reading_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reading_btn.setStyleSheet(link_css.replace("font-size: 12px", "font-size: 10px"))
        self._reading_btn.clicked.connect(self._request_weather)
        rl.addWidget(self._reading_btn)
        cl.addWidget(self._reading)

        # Typed by hand
        self._typed = QWidget()
        tl = QVBoxLayout(self._typed)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(5)
        unit = "°F" if self._aw.qmc.mode == "F" else "°C"
        self._t_edit = self._typed_row(tl, _SVG_TEMP, unit,
                                       QApplication.translate("tilauscope_roast_setup", "Room temperature"))
        self._h_edit = self._typed_row(tl, _SVG_HUM, "%",
                                       QApplication.translate("tilauscope_roast_setup", "Room humidity"))
        self._a_edit = self._typed_row(tl, _SVG_ALTITUDE, "m",
                                       QApplication.translate("tilauscope_common", "Altitude"))
        typed_note = QLabel(QApplication.translate("tilauscope_roast_setup", "typed · altitude remembered"))
        typed_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        typed_note.setStyleSheet(caption_css)
        tl.addWidget(typed_note)
        online_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "Use online weather"))
        online_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        online_btn.setStyleSheet(link_css.replace("font-size: 12px", "font-size: 10px"))
        online_btn.clicked.connect(self._request_weather)
        tl.addWidget(online_btn)
        cl.addWidget(self._typed)

        outer.addWidget(self._card)

    def _typed_row(self, layout: QVBoxLayout, svg: str, unit: str, name: str) -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(5)
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(_svg_pixmap(svg, THEME['SUBTEXT'], 16))
        edit = QLineEdit()
        edit.setAccessibleName(name)
        edit.setToolTip(name)
        edit.setFixedWidth(58)
        edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        edit.textEdited.connect(self._on_typed)
        unit_lbl = QLabel(unit)
        unit_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px;")
        unit_lbl.setFixedWidth(18)
        row.addWidget(icon)
        row.addStretch()
        row.addWidget(edit)
        row.addWidget(unit_lbl)
        layout.addLayout(row)
        return edit

    def _set_border(self, live: bool) -> None:
        self._card.setStyleSheet(
            f"QFrame#weatherCard {{ background-color: {THEME['SURFACE']};"
            f"border: 2px solid {THEME['ACCENT'] if live else THEME['BORDER']}; border-radius: 16px; }}")

    def _show_page(self, page: QWidget) -> None:
        for p in (self._idle, self._reading, self._typed):
            p.setVisible(p is page)
        self._set_border(page is not self._idle)
        self._card.adjustSize()
        self.adjustSize()

    def _plan_uses(self) -> str:
        """What the plan is built on while the card has no reading."""
        return _plan_uses_text(self)

    def _show_idle(self, note: str | None = None) -> None:
        self._idle_btn.setEnabled(True)
        self._idle_btn.setText(QApplication.translate("tilauscope_roast_setup", "Tap for local weather"))
        self._idle_btn.setStyleSheet(self._link_css)
        self._idle_btn.setToolTip("")
        self._idle_note.setText(note or self._plan_uses())
        self._show_page(self._idle)

    # ── actions ─────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _request_weather(self) -> None:
        """A tap: ask once, then look the weather up off the GUI thread."""
        if self._thread is not None:
            return
        from tilauscope.tilau_privacy_ui import ensure_geo_consent, hand_over_to_manual_entry  # noqa: PLC0415
        if not ensure_geo_consent(self._parent_dialog):
            # "I'll type it" — the other way of giving the same values.
            self._fill_typed()
            self._show_page(self._typed)
            hand_over_to_manual_entry(self._t_edit)
            return
        self._idle_btn.setEnabled(False)
        self._idle_btn.setText(QApplication.translate("tilauscope_roast_setup", "locating…"))
        self._idle_note.setText(self._plan_uses())
        self._show_page(self._idle)
        # Unparented thread: a card closed mid-lookup parks it until it ends.
        self._thread = QThread()
        self._worker = _WeatherWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_weather)
        self._worker.error.connect(self._on_weather_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_done)
        self._thread.start()

    @pyqtSlot()
    def _on_thread_done(self) -> None:
        if self._thread is not None:
            self._thread.wait(1000)   # finished fires just before the thread really exits
        self._thread = None
        self._worker = None

    @pyqtSlot(object)
    def _on_weather(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("temperature") is None:
            self._on_weather_error("")
            return
        from datetime import datetime  # noqa: PLC0415
        self._temperature = float(payload["temperature"])
        self._humidity = float(payload["humidity"]) if payload.get("humidity") is not None else None
        self._pressure = float(payload["pressure"]) if payload.get("pressure") is not None else None
        try:
            elevation = float(payload.get("elevation"))
            self._altitude = elevation if -500.0 <= elevation <= 6000.0 else None
        except (TypeError, ValueError):
            self._altitude = None
        unit = "°F" if self._aw.qmc.mode == "F" else "°C"
        temp = self.temperature or 0.0
        self._temp_val.setText(f"{temp:.1f} {unit}")
        self._temp_val.setStyleSheet(f"color: {_temp_color(temp, unit == '°F')}; font-size: 12px; font-weight: bold;")
        self._hum_val.setText(f"{self._humidity:.0f} %" if self._humidity is not None else "––")
        self._alt_val.setText(f"{self._altitude:.0f} m" if self._altitude is not None else "––")
        place = str(payload.get("city") or "")
        self._place_lbl.setText(" · ".join(p for p in (place, datetime.now().strftime("%H:%M")) if p))
        self._show_page(self._reading)
        self._notify()

    @pyqtSlot(str)
    def _on_weather_error(self, message: str) -> None:
        self._show_idle(self._plan_uses() + " · " + QApplication.translate("tilauscope_roast_setup", "tap to retry"))
        self._idle_btn.setText(QApplication.translate("tilauscope_roast_setup", "Weather unavailable"))
        self._idle_btn.setStyleSheet(self._link_css.replace(THEME['ACCENT'], THEME['WARNING'], 1))
        from tilauscope.online_weather import weather_error_text  # noqa: PLC0415
        self._idle_btn.setToolTip(weather_error_text(message))

    def _fill_typed(self) -> None:
        if self._temperature is not None and not self._t_edit.text():
            self._t_edit.setText(f"{self.temperature:.1f}")
        if self._humidity is not None and not self._h_edit.text():
            self._h_edit.setText(f"{self._humidity:.0f}")
        if self.altitude is not None and not self._a_edit.text():
            self._a_edit.setText(f"{self.altitude:.0f}")

    @pyqtSlot(str)
    def _on_typed(self, _text: str) -> None:
        def _num(edit: QLineEdit) -> float | None:
            try:
                return float(edit.text().replace(',', '.'))
            except ValueError:
                return None
        t = _num(self._t_edit)
        if t is not None and self._aw.qmc.mode == "F":
            t = (t - 32.0) / 1.8
        self._temperature = t if t is not None and -20.0 <= t <= 50.0 else None
        h = _num(self._h_edit)
        self._humidity = h if h is not None and 0.0 <= h <= 100.0 else None
        a = _num(self._a_edit)
        self._altitude = a if a is not None and -500.0 <= a <= 6000.0 else None
        self._pressure = None
        if self._altitude is not None:
            self._remembered_altitude = self._altitude
            QSettings().setValue(self.ALTITUDE_KEY, self._altitude)
        elif not self._a_edit.text().strip():   # an emptied field forgets the altitude
            self._remembered_altitude = None
            QSettings().remove(self.ALTITUDE_KEY)
        self._notify()

    def _notify(self) -> None:
        on_reading = getattr(self._parent_dialog, "_on_ambient_reading", None)
        if callable(on_reading):
            on_reading()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: ANN001
        thread, worker = self._thread, self._worker
        if thread is not None and worker is not None:
            for sig, slot in ((worker.finished, self._on_weather), (worker.error, self._on_weather_error),
                              (thread.finished, self._on_thread_done)):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            park_until_finished(thread, worker)   # dropping it while it runs aborts Qt
        self._thread = self._worker = None
        super().closeEvent(event)


# ════════════════════════════════════════════════════════════════════════════
# Roast Insights — non-blocking educational panel
# ════════════════════════════════════════════════════════════════════════════

# Runs synchronously on the GUI thread inside _RoastInsightsPanel._launch(),
# guarded by a 250 ms debounce. Do NOT run this off-thread: build_insights() and
# the roast-plan engine call QApplication.translate() and reach into the live
# shared qmc, which corrupts Qt/Artisan state off the GUI thread.


def _tasting_change_text(change: dict, unit: str) -> str:
    """'💡 Last time: <defect> — <change> (<before → after>)' for a plan's "Tasting Change"."""
    from tilauscope.cave.tasting_dialog import change_text, defect_labels  # noqa: PLC0415
    mode = 'F' if unit == 'F' else 'C'
    before, after = float(change["before"]), float(change["after"])
    lever = change["lever"]
    if lever.startswith("burner_"):
        values = f"{before:.0f} → {after:.0f} %"
    elif lever == "development_s":
        values = f"{int(before) // 60}:{int(before) % 60:02d} → {int(after) // 60}:{int(after) % 60:02d}"
    else:
        values = f"{before:.0f} → {after:.0f} °{mode}"
    return QApplication.translate(
        "tilauscope_roast_setup", "💡 Last time: {0} — {1} ({2})").format(
            defect_labels().get(change["defect"], ""), change_text(change["defect"], mode)[0], values)


class _RoastInsightsPanel(QWidget):
    """
    Renders the educational pre-roast insights. Owns no domain logic: it calls
    the pure engine (and the roast-plan generator) on a worker thread and paints
    the returned data.

    Heuristics render immediately; the plan fills the reserved targets when ready.
    The target roast level is taken from the OPTIONS tab profile selection and is
    shown here as a read-only reminder. Lifecycle is macOS-safe: parented QThread,
    a generation token discards stale results, ``shutdown()`` tears down cleanly.
    """

    def __init__(self, aw, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._aw = aw
        self._gen = 0
        self._destroyed = False
        self._pending: dict | None = None
        self._last_setup: dict | None = None
        self._target_scale = None          # AgtronScale | None (from OPTIONS)

        self._engine = None                # TilauScopeRoastPlan, built on demand
        self._engine_ctx = None            # roaster context the engine was built for
        self._plan: dict | None = None    # latest plan, used by RoastSetupDialog
        self._plan_result: tuple | None = None  # (plan, graph, crashes, flicks) — what the PDF needs
        self._plan_failed = False
        self._pinned: dict | None = None   # {"plan", "label"} — column A of a comparison
        self._load_alarms = False          # Expert: load the plan's alarms at Start
        self._roadmap_host: QWidget | None = None
        self._pin_btn: QPushButton | None = None
        self._pdf_btn: QPushButton | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        # 500 ms: a plan generation is not free even off the corpus scan, and
        # typing a three-digit weight must not fire three of them.
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._launch)

        self._build_ui()

    # ── UI scaffold ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(10)

        self._stack = QStackedWidget()
        self._computing = QLabel("⟳  " + QApplication.translate("tilauscope_roast_setup", "Computing…"))
        self._computing.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._computing.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 13px;")
        self._stack.addWidget(self._computing)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        # The content wraps to the width it is given; it never scrolls sideways.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(QWidget())
        self._stack.addWidget(self._scroll)

        lay.addWidget(self._stack, 1)
        self._stack.setCurrentIndex(0)

    # ── Public API ───────────────────────────────────────────────────────────

    def request(self, *, bean, density, moisture, green_weight, bean_temp,
                ctx, mode, ambient_temp, ambient_humidity, altitude,
                plan_parent, target_scale=None, run_plan=True) -> None:  # noqa: ANN001
        """Queue a (debounced) recompute with the current setup values."""
        if self._destroyed:
            return
        self._target_scale = target_scale
        self._last_setup = dict(
            bean=bean, density=density, moisture=moisture,
            green_weight=green_weight, bean_temp=bean_temp, ctx=ctx, mode=mode,
            ambient_temp=ambient_temp, ambient_humidity=ambient_humidity,
            altitude=altitude, plan_parent=plan_parent,
            target_scale=target_scale, run_plan=run_plan,
        )
        self._pending = self._last_setup
        if not green_weight or green_weight <= 0:
            # Whole tab waits for a green weight before computing anything.
            self._computing.setText(
                "⚖  " + QApplication.translate(
                    "tilauscope_roast_setup", "Enter a green weight to generate insights")
            )
            self._stack.setCurrentIndex(0)
            return
        self._computing.setText(
            "⟳  " + QApplication.translate("tilauscope_roast_setup", "Computing…")
        )
        self._stack.setCurrentIndex(0)
        self._debounce.start()

    def shutdown(self) -> None:
        self._destroyed = True
        self._plan = None
        self._engine = None
        self._engine_ctx = None
        try:
            self._debounce.stop()
        except RuntimeError:
            pass

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.shutdown()
        super().closeEvent(event)

    # ── Compute (synchronous, GUI thread) ───────────────────────────────────────

    def _engine_for(self, parent, ctx):  # noqa: ANN001
        """The dialog's roast-plan engine, rebuilt only if the roaster changes."""
        from tilauscope.roast_plan_model import TilauScopeRoastPlan
        if self._engine is None or self._engine_ctx is not ctx:
            self._engine = TilauScopeRoastPlan(parent=parent, roaster_ctx=ctx)
            self._engine_ctx = ctx
        return self._engine

    def _launch(self) -> None:
        if self._destroyed or self._pending is None:
            return
        s = self._pending
        self._gen += 1
        gen = self._gen

        insight_params = dict(
            bean=s["bean"], density=s["density"], moisture=s["moisture"],
            green_weight=s["green_weight"], bean_temp=s["bean_temp"],
            ctx=s["ctx"], mode=s["mode"],
        )
        plan_params = None
        if s["run_plan"] and s["ctx"] is not None and s["target_scale"] is not None \
                and s["green_weight"] and s["green_weight"] > 0:
            plan_params = dict(
                parent=s["plan_parent"], ctx=s["ctx"], bean=s["bean"],
                agtron_target=s["target_scale"],
                ambient_temp=s["ambient_temp"], ambient_humidity=s["ambient_humidity"],
                charge_weight=s["green_weight"], altitude=s["altitude"],
                # Same reading as the assistant: a paired AirWave puts the
                # extraction path into the plan, its PDF and its alarms.
                airwave_present=getattr(s["plan_parent"], "bleAirwaveDevice", None) is not None,
            )

        # Computed synchronously on the GUI thread: build_insights() and the
        # roast-plan engine call QApplication.translate() and reach into the
        # shared, live qmc, neither of which is safe off the main thread. The
        # 500 ms debounce already absorbs keystroke thrash.
        try:
            res = build_insights(**insight_params)
        except Exception:  # noqa: BLE001
            res = None
        self._on_ready(gen, res)

        plan = None
        full = None
        if plan_params is not None:
            try:
                # One engine for the whole dialog: a fresh instance drops the
                # corpus index snapshot and the per-bean history cache, so every
                # keystroke paid the historical scan again. The history cache is
                # keyed by (bean, colour target, weight), so reusing it cannot
                # serve a plan computed for other inputs.
                engine = self._engine_for(plan_params["parent"], plan_params["ctx"])
                result = engine.generate_roast_plan(
                    bean=plan_params["bean"],
                    agtron_target=plan_params["agtron_target"],
                    ambient_temp=plan_params["ambient_temp"],
                    ambient_humidity=plan_params["ambient_humidity"],
                    charge_weight=plan_params["charge_weight"],
                    roast_altitude=plan_params["altitude"],
                    bt_deviation=None,
                    airwave_present=plan_params.get("airwave_present", False),
                )
                # generate_roast_plan returns (plan_dict, graph, crashes, flicks)
                full = result if isinstance(result, tuple) else (result, {}, [], [])
                plan = full[0]
            except Exception:  # noqa: BLE001
                _log.exception("RoastInsights: roast plan generation failed")
                plan = None
                full = None
        _log.info("INSIGHTS computed gen=%s plan=%s", gen, "ok" if plan else "None")
        self._on_plan_ready(gen, plan, full)

    @pyqtSlot(int, object)
    def _on_ready(self, gen: int, result: object) -> None:
        if self._destroyed or gen != self._gen:
            return  # stale result — discard
        if result is None:
            self._computing.setText(
                "⚠  " + QApplication.translate("tilauscope_roast_setup", "Insights unavailable")
            )
            self._stack.setCurrentIndex(0)
            return
        self._render(result)
        self._stack.setCurrentIndex(1)

    @pyqtSlot(int, object, object)
    def _on_plan_ready(self, gen: int, plan: object, full: object = None) -> None:
        _log.info("INSIGHTS on_plan_ready gen=%s cur=%s plan=%s", gen, self._gen, type(plan).__name__)
        if self._destroyed or gen != self._gen:
            return
        if plan is None:
            self._plan = None
            self._plan_result = None
            self._plan_failed = self._target_scale is not None
            self._render_roadmap()
            return
        self._plan = plan if isinstance(plan, dict) else None
        self._plan_result = full if isinstance(full, tuple) and self._plan is not None else None
        self._plan_failed = False
        charge_temp = self.charge_temperature()
        # The INSIGHTS tab page is the parent once laid out; the dialog is the window.
        owner = self.window()
        if charge_temp is not None and owner is not None:
            update_target = getattr(owner, "_on_plan_charge_temperature", None)
            if callable(update_target):
                update_target(charge_temp)
        if owner is not None and self._plan is not None:
            # What the cultivar family did to the charge, stated on the intent card.
            show_family = getattr(owner, "_set_family_readout", None)
            if callable(show_family):
                try:
                    _delta = float(self._plan.get("Charge Family Delta") or 0.0)
                except (TypeError, ValueError):
                    _delta = 0.0
                show_family(str(self._plan.get("Charge Family") or ""), _delta)
            show_tasting = getattr(owner, "_set_tasting_readout", None)
            if callable(show_tasting):
                show_tasting(self._plan.get("Tasting Change"))
        self._render_roadmap()

    def charge_temperature(self) -> float | None:
        """Return the generated plan's charge temperature in display units."""
        if self._plan is None:
            return None
        try:
            value = float(self._plan["Charge Temp"])
            return value if value > 0 else None
        except (KeyError, TypeError, ValueError):
            return None

    def ensure_plan(self) -> None:
        """Finish a queued computation before a setup dialog is accepted.

        A recompute still waiting on the debounce runs even when a plan exists:
        that plan belongs to the setup before the last change.
        """
        if self._pending is not None and (
                self._debounce.isActive() or self.charge_temperature() is None):
            self._debounce.stop()
            self._launch()

    # ── Rendering ──────────────────────────────────────────────────────────────

    @staticmethod
    def _sev_color(sev: str) -> str:
        return {
            "ok":   THEME["SUCCESS"],
            "warn": THEME["WARNING"],
            "crit": THEME["CRITICAL"],
            "info": THEME["ACCENT"],
        }.get(sev, THEME["SUBTEXT"])

    @staticmethod
    def _clear_layout(layout) -> None:  # noqa: ANN001
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _chip(self, sig) -> QFrame:  # noqa: ANN001
        color = self._sev_color(sig.severity)
        f = QFrame()
        # By name: a bare QFrame rule reaches the QLabels inside (a QLabel is a
        # QFrame) and draws the accent bar again before every line of text.
        f.setObjectName("insightChip")
        f.setStyleSheet(
            f"QFrame#insightChip {{ background: {THEME['SURFACE']}; border-radius: 8px;"
            f"border-left: 3px solid {color}; }}"
        )
        v = QVBoxLayout(f)
        v.setContentsMargins(11, 9, 11, 9)
        v.setSpacing(3)
        top = QHBoxLayout()
        name = QLabel(sig.label)
        val = QLabel(sig.value_text)
        val.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; border: none;")
        top.addWidget(name)
        top.addStretch()
        top.addWidget(val)
        v.addLayout(top)
        impl = QLabel(sig.implication)
        impl.setWordWrap(True)
        impl.setProperty('variant', 'caption')
        v.addWidget(impl)
        return f

    def _band_card(self, band) -> QFrame:  # noqa: ANN001
        f = QFrame()
        f.setStyleSheet(f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 8px; }}")
        v = QVBoxLayout(f)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(1)
        for text, css in (
            (band.name, f"color: {THEME['SUBTEXT']}; font-size: 11px; border: none;"),
            (f"{band.lo:.0f}–{band.hi:.0f}", f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: bold; border: none;"),
            (band.unit, f"color: {THEME['BORDER']}; font-size: 10px; border: none;"),
        ):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(css)
            v.addWidget(lbl)
        return f

    def _render(self, ins) -> None:  # noqa: ANN001
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(2, 0, 8, 8)
        v.setSpacing(14)

        # The roadmap leads: it is what the operator reads before the drum turns.
        v.addLayout(self._roadmap_header())
        self._roadmap_host = QWidget()
        rh = QVBoxLayout(self._roadmap_host)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(8)
        v.addWidget(self._roadmap_host)

        if ins.signals:
            v.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Green signals")))
            grid = QGridLayout()
            grid.setSpacing(8)
            for i, sig in enumerate(ins.signals):
                grid.addWidget(self._chip(sig), i // 2, i % 2)
            v.addLayout(grid)

        if ins.load is not None:
            v.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Load & setup")))
            card = QFrame()
            card.setStyleSheet(f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 8px; }}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 10, 12, 10)
            cv.setSpacing(6)
            head = QHBoxLayout()
            ll = QLabel(ins.load.text)
            head.addWidget(ll)
            head.addStretch()
            if ins.load.pct is not None:
                pl = QLabel(f"{ins.load.pct:.0f} %")
                pl.setStyleSheet(
                    f"color: {self._sev_color(ins.load.severity)}; font-size: 12px;"
                    f"font-weight: bold; border: none;"
                )
                head.addWidget(pl)
            cv.addLayout(head)
            if ins.load.pct is not None:
                color = self._sev_color(ins.load.severity)
                bar = QProgressBar()
                bar.setRange(0, 100)                       # 100% fills the track
                bar.setValue(int(min(ins.load.pct, 100)))  # overload clamps full; colour flags it
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                bar.setStyleSheet(
                    f"QProgressBar {{ background: {THEME['BORDER']}; border: none; border-radius: 3px; }}"
                    f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
                )
                cv.addWidget(bar)
            note = QLabel(ins.load.note)
            note.setWordWrap(True)
            note.setProperty('variant', 'caption')
            cv.addWidget(note)
            v.addWidget(card)

        if ins.bands:
            v.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Phase cheat-sheet (RoR)")))
            grid = QGridLayout()
            grid.setSpacing(8)
            for i, band in enumerate(ins.bands):
                grid.addWidget(self._band_card(band), 0, i)
            v.addLayout(grid)

        if ins.strategy:
            box = QFrame()
            box.setObjectName("strategyBox")
            box.setStyleSheet(
                f"QFrame#strategyBox {{ background: {THEME['SURFACE']}; border: 1px solid {THEME['ACCENT']};"
                f"border-radius: 8px; }}"
            )
            bv = QVBoxLayout(box)
            bv.setContentsMargins(13, 11, 13, 11)
            bv.setSpacing(4)
            t = QLabel(QApplication.translate("tilauscope_roast_setup", "STRATEGY"))
            t.setProperty('variant', 'eyebrow')
            t.setStyleSheet(f"color: {THEME['ACCENT']};")
            bv.addWidget(t)
            slbl = QLabel(ins.strategy)
            slbl.setWordWrap(True)
            bv.addWidget(slbl)
            v.addWidget(box)

        v.addStretch()
        self._scroll.setWidget(host)   # takes ownership; old host is destroyed
        self._render_roadmap()

    # ── Roadmap (PLAN tab) ───────────────────────────────────────────────────

    def _roadmap_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Roadmap")))
        row.addStretch()
        self._pin_btn = QPushButton()
        self._pin_btn.setProperty('variant', 'outline')
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setToolTip(QApplication.translate(
            "tilauscope_roast_setup",
            "Keep this plan aside, then change the weight, the use or the level to compare."))
        self._pin_btn.clicked.connect(self._toggle_pin)
        row.addWidget(self._pin_btn)
        self._pdf_btn = QPushButton("📄  " + QApplication.translate("tilauscope_roast_setup", "PDF"))
        self._pdf_btn.setProperty('variant', 'outline')
        self._pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pdf_btn.setToolTip(QApplication.translate(
            "tilauscope_roast_setup",
            "Save the plan as a PDF to keep at hand — with a comparison page when a plan is pinned."))
        self._pdf_btn.clicked.connect(self._export_pdf)
        row.addWidget(self._pdf_btn)
        return row

    @staticmethod
    def _hint_label(text: str, color: str | None = None) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color or THEME['SUBTEXT']}; font-size: 12px; border: none;")
        return lbl

    @staticmethod
    def _mmss(text: Any) -> str:
        """'04:44' → '4:44'; anything else unchanged."""
        m = re.fullmatch(r"\s*(\d+):(\d\d)\s*", str(text or ""))
        return f"{int(m.group(1))}:{m.group(2)}" if m else str(text or "")

    def _mode(self) -> str:
        return (self._last_setup or {}).get("mode", "C")

    def _plan_label(self, plan: dict) -> str:
        """'Filter · 250 g · Medium Light' — names a plan in a comparison."""
        from tilauscope.roast_plan_model import BuildPRoastPlanPDF  # noqa: PLC0415
        parts = [BuildPRoastPlanPDF._destination_label(plan.get("Roast Destination"))]  # pylint: disable=protected-access
        try:
            parts.append(f"{float(plan.get('Weight') or 0):.0f} g")
        except (TypeError, ValueError):
            pass
        if self._target_scale is not None:
            parts.append(str(getattr(self._target_scale, 'name', '')))
        return " · ".join(p for p in parts if p)

    def _reference_line(self, plan: dict) -> "tuple[str, bool] | None":
        """The reference roast the plan stands on, or why it does not — (text, used); None without one."""
        from tilauscope.beancave_catalogue import roast_name  # noqa: PLC0415

        def _name(ref: dict) -> str:
            return roast_name(int(ref.get("epoch") or 0), str(ref.get("batch") or ""), in_sentence=True)

        ref = plan.get("Reference Roast") or {}
        status = ref.get("status")
        if not status:
            # Only the calendar is inherited: the burner follows the new lot.
            prev_ref = (plan.get("Previous Harvest") or {}).get("reference_roast") or {}
            if prev_ref.get("status") == "used":
                return QApplication.translate(
                    "tilauscope_roast_setup",
                    "Timings and temperatures from the {0} crop's reference roast ({1}), "
                    "until this crop has roasts of its own.").format(
                        plan["Previous Harvest"].get("crop", ""), _name(prev_ref)), True
            return None
        name = _name(ref)
        if status == "used":
            if ref.get("tasting_change_skipped"):
                return (QApplication.translate("tilauscope_roast_setup",
                                               "Based on your reference roast of {0}.").format(name) + " "
                        + QApplication.translate(
                            "tilauscope_roast_setup",
                            "The change asked by the last tasting is not applied: "
                            "going back to the reference is the correction.")), True
            if ref.get("tasting_change_applied"):
                return QApplication.translate(
                    "tilauscope_roast_setup",
                    "Based on your reference roast of {0}, with the change asked by the last tasting.").format(
                        name), True
            return QApplication.translate(
                "tilauscope_roast_setup", "Based on your reference roast of {0}.").format(name), True
        reason = ref.get("reason")
        if reason == "missing":
            text = QApplication.translate(
                "tilauscope_roast_setup", "Your reference roast is not used: its roast file was not found.")
        elif status == "no_tasting":
            text = QApplication.translate(
                "tilauscope_roast_setup", "Your reference roast ({0}) is not used: its tasting was not found.").format(name)
        elif reason == "excluded":
            text = QApplication.translate(
                "tilauscope_roast_setup", "Your reference roast ({0}) is not used: it is excluded from learning.").format(
                    name)
        elif status == "not_tasted_yes":
            text = QApplication.translate(
                "tilauscope_roast_setup", "Your reference roast ({0}) is not used: it was not tasted Yes.").format(name)
        elif reason == "weight":
            text = QApplication.translate(
                "tilauscope_roast_setup",
                "Your reference roast ({0}) is not used: it was {1} g and this batch is {2} g.").format(
                    name, f"{float(ref.get('weight_g') or 0):.0f}", f"{float(plan.get('Weight') or 0):.0f}")
        elif reason == "level" and ref.get("level") and self._target_scale is not None:
            text = QApplication.translate(
                "tilauscope_roast_setup",
                "Your reference roast ({0}) is not used: it was roasted {1} and this roast is {2}.").format(
                    name, ref["level"], getattr(self._target_scale, 'name', ''))
        else:
            text = QApplication.translate(
                "tilauscope_roast_setup", "Your reference roast ({0}) is not used for this batch.").format(name)
        return text, False

    @staticmethod
    def _star_line(text: str, used: bool) -> QFrame:
        """A ★ line in the reference's yellow, or a ☆ line in grey when the reference is not used."""
        box = QFrame()
        box.setObjectName("referenceLine")
        colour = THEME['YELLOW'] if used else THEME['OVERLAY1']
        box.setStyleSheet(
            f"QFrame#referenceLine {{ border: 1px {'solid' if used else 'dashed'} {colour};"
            f" border-radius: 8px; background: {'rgba(249,226,175,0.08)' if used else 'transparent'}; }}"
            f" QLabel {{ border: none; background: transparent; }}")
        row = QHBoxLayout(box)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        glyph = QLabel('★' if used else '☆')
        glyph.setStyleSheet(f"color: {colour}; font-size: 15px;")
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {THEME['TEXT'] if used else THEME['SUBTEXT']}; font-size: 12px;")
        row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        return box

    def _confidence(self, plan: dict) -> tuple[str, bool]:
        """What the plan rests on, in words — and whether it is guessing."""
        prev = plan.get("Previous Harvest") or {}
        if prev.get("crop"):
            return QApplication.translate(
                "tilauscope_roast_setup", "Built on the {0} harvest ({1} roasts)").format(
                    prev["crop"], prev.get("roasts", 0)), False
        try:
            n = int(plan.get("History Roasts") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 1:   # a single roast is shown as reference only; the plan starts from the grid
            return QApplication.translate(
                "tilauscope_roast_setup", "Based on {0} roasts of this coffee").format(n), False
        bean = (self._last_setup or {}).get("bean")
        if int(getattr(bean, 'count', 0) or 0) == 0:
            return QApplication.translate(
                "tilauscope_roast_setup",
                "First roast of this coffee — the plan starts from its characteristics; "
                "expect to adjust after tasting."), True
        return QApplication.translate(
            "tilauscope_roast_setup",
            "No earlier roast of this coffee could be used — the plan starts from its characteristics."), True

    def _render_roadmap(self) -> None:
        host = self._roadmap_host
        if host is None:
            return
        try:
            lay = host.layout()
        except RuntimeError:
            return
        if lay is None:
            return
        self._clear_layout(lay)
        plan = self._plan
        ready = plan is not None and self._target_scale is not None
        try:
            if self._pin_btn is not None:
                self._pin_btn.setEnabled(ready)
                self._pin_btn.setText("📌  " + (
                    QApplication.translate("tilauscope_roast_setup", "Unpin") if self._pinned is not None
                    else QApplication.translate("tilauscope_roast_setup", "Pin")))
            if self._pdf_btn is not None:
                self._pdf_btn.setEnabled(ready)
        except RuntimeError:
            pass
        if self._target_scale is None:
            lay.addWidget(self._hint_label(QApplication.translate(
                "tilauscope_roast_setup", "Choose a roast level above to see the roadmap.")))
            return
        if plan is None:
            lay.addWidget(self._hint_label(
                QApplication.translate("tilauscope_roast_setup", "Plan unavailable — see log for details.")
                if self._plan_failed else
                "⟳  " + QApplication.translate("tilauscope_roast_setup", "Building the roadmap…")))
            return
        mode = self._mode()
        try:
            if self._pinned is not None:
                lay.addWidget(self._comparison_card(self._pinned, plan, mode))
            else:
                lay.addWidget(self._roadmap_card(plan, mode))
        except Exception:  # noqa: BLE001
            _log.exception("RoastInsights: roadmap render failed")
        change = plan.get("Tasting Change")
        if change:
            try:
                lay.addWidget(self._hint_label(_tasting_change_text(change, mode), THEME['TODAY']))
            except Exception:  # noqa: BLE001
                _log.exception("RoastInsights: tasting line failed")
        reference = self._reference_line(plan)
        if reference is not None and reference[1]:
            lay.addWidget(self._star_line(reference[0], True))
        else:
            text, guessing = self._confidence(plan)
            if reference is not None:
                lay.addWidget(self._star_line(reference[0] + " " + text, False))
            else:
                lay.addWidget(self._hint_label(text, THEME['WARNING'] if guessing else None))
        if operator_level(self._aw) == "expert":
            cb = QCheckBox(QApplication.translate(
                "tilauscope_roast_setup", "Load the plan's alarms at start — replaces your current alarms"))
            cb.setChecked(self._load_alarms)
            cb.toggled.connect(self._on_load_alarms_toggled)
            lay.addWidget(cb)

    def _roadmap_card(self, plan: dict, mode: str) -> QFrame:
        from tilauscope.roast_plan_model import BuildPRoastPlanPDF, plan_cooled_weight  # noqa: PLC0415
        unit = f"°{mode}"
        mono = mono_family()
        levels = BuildPRoastPlanPDF.entry_levels(plan)

        def _levers(i: int, drum: bool) -> str:
            parts = []
            for key, text in (
                    ("heater", QApplication.translate("tilauscope_roast_setup", "Burner {0} %")),
                    ("airflow", QApplication.translate("tilauscope_roast_setup", "Air {0} %"))):
                values = levels.get(key) or []
                if i < len(values) and values[i] is not None:
                    parts.append(text.format(f"{values[i]:.0f}"))
            drum_values = levels.get("drum") or []
            if drum and drum_values and drum_values[0] is not None:
                parts.append(QApplication.translate("tilauscope_roast_setup", "Drum {0} %").format(
                    f"{drum_values[0]:.0f}"))
            return "  ·  ".join(parts)

        try:
            dev_pct = f"{float(plan.get('Development Phase %')):.0f}"
        except (TypeError, ValueError):
            dev_pct = "—"
        rows = (
            (QApplication.translate("Button", "CHARGE"), THEME['ACCENT'],
             plan.get("Charge Temp"), "", _levers(0, True)),
            (QApplication.translate("Button", "DRY END"), THEME['WARNING'],
             plan.get("End of Dry Temp"), "~" + self._mmss(plan.get("Dry Phase")), _levers(1, False)),
            (QApplication.translate("Button", "FC START"), THEME['TODAY'],
             plan.get("First Crack Temp"), "~" + self._mmss(plan.get("FC Time")), _levers(2, False)),
            (QApplication.translate("Button", "DROP"), THEME['CRITICAL'],
             plan.get("Drop Temp"), "~" + self._mmss(plan.get("Total Time")),
             QApplication.translate("tilauscope_roast_setup", "Development {0} ({1} %)").format(
                 self._mmss(plan.get("Development Phase")), dev_pct)),
        )

        card = QFrame()
        card.setObjectName("roadmapCard")
        card.setStyleSheet(
            f"QFrame#roadmapCard {{ background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 10px; }}")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        for i, (name, colour, temp, when, levers) in enumerate(rows):
            row = QFrame()
            row.setObjectName("roadmapRow")
            row.setStyleSheet(
                "QFrame#roadmapRow { border: none; "
                + ("" if i == 0 else f"border-top: 1px solid {THEME['BORDER']}; ") + "}")
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 9, 14, 9)
            h.setSpacing(10)
            name_lbl = QLabel(f"<span style='color:{colour};'>●</span>&nbsp;&nbsp;{name}")
            name_lbl.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 11px; font-weight: bold; letter-spacing: 1px; border: none;")
            name_lbl.setFixedWidth(104)
            temp_lbl = QLabel(f"{temp} {unit}")
            temp_lbl.setStyleSheet(
                f"color: {THEME['TEXT']}; font-family: '{mono}'; font-size: 16px; font-weight: bold; border: none;")
            temp_lbl.setFixedWidth(76)
            when_lbl = QLabel(when)
            when_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-family: '{mono}'; font-size: 13px; border: none;")
            when_lbl.setFixedWidth(54)
            lever_lbl = QLabel(levers)
            lever_lbl.setWordWrap(True)
            lever_lbl.setStyleSheet(f"color: {THEME['TEXT']}; font-size: 12px; border: none;")
            h.addWidget(name_lbl)
            h.addWidget(temp_lbl)
            h.addWidget(when_lbl)
            h.addWidget(lever_lbl, 1)
            cv.addWidget(row)

        cooled = plan_cooled_weight(plan)
        loss = plan.get("Target Weight Loss")
        if cooled is not None:
            foot = QFrame()
            foot.setObjectName("roadmapFoot")
            foot.setStyleSheet(
                f"QFrame#roadmapFoot {{ background: {tint('ACCENT', 10)}; border: none;"
                f"border-top: 1px solid {THEME['BORDER']}; border-bottom-left-radius: 10px;"
                f"border-bottom-right-radius: 10px; }}")
            fh = QHBoxLayout(foot)
            fh.setContentsMargins(14, 9, 14, 9)
            lbl = QLabel(QApplication.translate(
                "tilauscope_roast_setup", "After cooling, aim for {0}  ·  ≈ {1} g on the scale").format(
                    f"<b style='color:{THEME['ACCENT']}; font-family:\"{mono}\";'>−{loss} %</b>", f"{cooled:.0f}"))
            lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; border: none;")
            fh.addWidget(lbl)
            cv.addWidget(foot)
        return card

    def _comparison_card(self, pinned: dict, plan: dict, mode: str) -> QFrame:
        from tilauscope.roast_plan_model import plan_comparison_rows  # noqa: PLC0415
        mono = mono_family()
        rows = plan_comparison_rows(pinned["plan"], plan, f"°{mode}")
        card = QFrame()
        card.setObjectName("roadmapCard")
        card.setStyleSheet(
            f"QFrame#roadmapCard {{ background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 10px; }}")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        def _cell(text: str, css: str, align=Qt.AlignmentFlag.AlignLeft) -> QLabel:  # noqa: ANN001
            lbl = QLabel(text)
            lbl.setStyleSheet(css + "border: none;")
            lbl.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        def _two_lines(label: str) -> str:
            # The level goes under use and weight: one line is wider than the sheet.
            return "\n".join(label.rsplit(" · ", 1))

        head = f"color: {THEME['SUBTEXT']}; font-size: 11px; font-weight: bold;"
        grid.addWidget(_cell("📌  " + _two_lines(pinned["label"]), head), 0, 1)
        grid.addWidget(_cell(_two_lines(self._plan_label(plan)),
                             f"color: {THEME['TEXT']}; font-size: 11px; font-weight: bold;"), 0, 2)
        grid.addWidget(_cell(QApplication.translate("tilauscope_roast_setup", "Change"), head,
                             Qt.AlignmentFlag.AlignRight), 0, 3)
        moved = False
        for r, (label, a, b, delta) in enumerate(rows, start=1):
            changed = a != b
            moved = moved or changed
            grid.addWidget(_cell(label, f"color: {THEME['SUBTEXT']}; font-size: 12px;"), r, 0)
            grid.addWidget(_cell(a, f"color: {THEME['SUBTEXT']}; font-family: '{mono}'; font-size: 12px;"), r, 1)
            grid.addWidget(_cell(b, f"color: {THEME['TODAY'] if changed else THEME['TEXT']}; font-family: '{mono}';"
                                    f"font-size: 12px; font-weight: {'bold' if changed else 'normal'};"), r, 2)
            grid.addWidget(_cell(delta or "—", f"color: {THEME['TODAY'] if delta else THEME['BORDER']};"
                                                f"font-family: '{mono}'; font-size: 12px; font-weight: bold;",
                                 Qt.AlignmentFlag.AlignRight), r, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        if not moved:
            grid.addWidget(_cell(QApplication.translate(
                "tilauscope_roast_setup", "Change the weight, the use or the level to see what moves."),
                f"color: {THEME['WARNING']}; font-size: 12px;"), len(rows) + 1, 0, 1, 4)
        return card

    @pyqtSlot()
    def _toggle_pin(self) -> None:
        if self._pinned is not None:
            self._pinned = None
        elif self._plan is not None and self._target_scale is not None:
            self._pinned = {"plan": {"Target Roast Level": self._target_scale.name} | self._plan,
                            "label": self._plan_label(self._plan)}
        self._render_roadmap()

    @pyqtSlot(bool)
    def _on_load_alarms_toggled(self, checked: bool) -> None:
        self._load_alarms = checked

    def load_alarms_requested(self) -> bool:
        """Expert asked for the plan's alarms to replace theirs at Start."""
        return (self._load_alarms and self._plan is not None
                and operator_level(self._aw) == "expert")

    def write_plan_alarms(self) -> str | None:
        """Export the current plan's alarm set; returns the file, or None."""
        if self._plan is None or self._target_scale is None:
            return None
        from pathlib import Path  # noqa: PLC0415
        from PyQt6.QtCore import QStandardPaths  # noqa: PLC0415
        from tilauscope.roast_plan_model import TilauscopeAlarmFactory  # noqa: PLC0415
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        folder.mkdir(parents=True, exist_ok=True)
        path = str(folder / "roast_plan_alarms.alrm")
        TilauscopeAlarmFactory({"Target Roast Level": self._target_scale.name} | self._plan).export(path)
        return path

    @pyqtSlot()
    def _export_pdf(self) -> None:
        """Save the plan as a PDF, its alarm set beside it, and open it."""
        if self._plan_result is None or self._target_scale is None:
            return
        from tilauscope.roast_plan_model import BuildPRoastPlanPDF, TilauscopeAlarmFactory  # noqa: PLC0415
        from tilauscope.label_printer import get_downloads_dir  # noqa: PLC0415
        plan, graph, crashes, flicks = self._plan_result
        scale = self._target_scale
        data = {"Target Roast Level": scale.name} | plan
        owner = self.window()
        bean_name = str(plan.get("Bean Name") or "roast_plan").replace(" ", "_").replace("/", "-")
        rng = getattr(scale, "agtron_range", None)
        suffix = f"_{rng.min_value}-{rng.max_value}Ag" if rng is not None else ""
        default = str(get_downloads_dir() / f"Roast_Plan_{bean_name}_{scale.name}{suffix}.pdf")
        path, _ = QFileDialog.getSaveFileName(
            owner, QApplication.translate("tilauscope_roast_setup", "Save the roast plan"), default,
            QApplication.translate("tilauscope_common", "PDF Files (*.pdf)"))
        if not path:
            return
        try:
            pdf = BuildPRoastPlanPDF(orientation='P', unit='mm', format='A4', temp_unit=self._mode(),
                                     roaster_ctx=(self._last_setup or {}).get("ctx"))
            if self._pinned is not None:
                pdf.create_comparison_page(self._pinned["plan"], self._pinned["label"],
                                           data, self._plan_label(plan))
            pdf.create_pdf_report(data, graph, crashes, flicks)
            pdf.output(path)
            stem = path[:-4] if path.lower().endswith(".pdf") else path
            TilauscopeAlarmFactory(data).export(stem + ".alrm")
        except Exception as exc:  # noqa: BLE001
            _log.exception("RoastInsights: plan PDF failed")
            show_styled_message(
                owner, QApplication.translate("Error Message", "Error"),
                QApplication.translate("tilauscope_roast_setup",
                                       "Could not generate the roast plan:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)
            return
        helpers = [w for w in (getattr(owner, "_scale_window", None), getattr(owner, "_ambient_window", None),
                               getattr(owner, "_weather_window", None)) if w is not None]
        open_in_os_viewer(path, owner, helpers=helpers)

# ─────────────────────────────────────────────────────────────────────────────

def _replay_reaction_time_s(ctx: Any) -> float:
    """The burner lag a Roast Replay leads by: the machine's bench value, else 10 s."""
    bench_value = getattr(ctx, "burner_reaction_time_s", None)
    return float(bench_value) if bench_value is not None else 10.0


def _default_autosave_prefix(qmc: Any) -> str:
    """The save-filename template, set to batch + title + date/time when empty.

    A template the user configured is kept. A malformed one that wraps tokens in
    a TRAILING '~' too (e.g. '~title~_~yy~-~mm~-~dd~_~hour~~minute~') is
    replaced: Artisan tokens use a single LEADING '~' only, and the trailing
    ones leave stray '~' in the filename. Signature: a double tilde '~~' (never
    present in a valid template — adjacent tokens like '~hour~minute' have a
    single '~').
    """
    _bad_exact = (
        '~title~_~yy~-~mm~-~dd~_~hour~~minute~',
        '~batch~_~title~_~yy~-~mm~-~dd~_~hour~~minute~',
    )
    prefix = qmc.autosaveprefix
    if prefix != '' and '~~' not in prefix and prefix not in _bad_exact:
        return prefix
    ## Valid, clean template: ~date = yy-MM-dd, ~time = hhmm.
    ## See generateFilename/parseAutosaveprefix (fields list) in main.py.
    ## Artisan's batch counter, -1 when off; the number itself lands at DROP.
    if qmc.batchcounter > -1:
        return '~batch_~title_~date_~time'
    return '~title_~date_~time'


class RoastSetupDialog(QDialog):
    """
    Pre-roast setup dialog.

    Parameters
    ----------
    bean : GreenBean
        The bean selected from BeanCave.
    aw : ApplicationWindow
        The Artisan main window (for qmc injection, scale signals, title combo).

    """

    def __init__(
        self,
        bean: GreenBean,
        parent: 'BeancaveDlg',
        open_tab: str = "roast",
    ) -> None:
        super().__init__(parent)  # no parent → independent window
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._bean       = bean
        self._aw         = parent.aw
        self._parent_widget = parent

        # Preheat setpoint ownership: the plan fills the field until the operator
        # types in it, then the field is theirs and the plan only advises.
        self._plan_charge_temperature: float | None = None
        self._pid_charge_temp_user_set: bool = False

        # A weight pre-filled from the last batch is a proposal: Start waits
        # until it is weighed or typed. Source: "scale" | "typed" | "" (none yet).
        self._weight_confirmed: bool = False
        self._weight_source: str = ""

        # scale management
        self._scale_window: _ScaleFloatWindow | None = None
        # scale1_was_connected is set by _connect_scale() and read by the close
        # path to decide whether the scale connection must be dropped.
        self.scale1_was_connected: bool = False
        self._connect_scale()

        # get roaster name if defined
        self._roaster =  self._aw.tilau_roaster
        # roaster context (single JSON load) — None when unconfigured/unknown
        try:
            self._roaster_ctx = RoasterManager(self._roaster).get_roast_context()
        except Exception:  # noqa: BLE001
            self._roaster_ctx = None

        # ambient probe — show card if probe device name is configured
        # the unconfigured marker is 'none' (main.py default), not ""
        self._is_tilau_probe = self._aw.bleTilauScopeDeviceName not in (None, "", "none")
        self._ambient_window: _AmbientFloatWindow | None = None
        self._weather_window: _WeatherFloatWindow | None = None
        if self._is_tilau_probe:
            self._ambient_window = _AmbientFloatWindow(self)
        else:
            # No probe: the room comes from the weather, on a tap, or is typed.
            self._weather_window = _WeatherFloatWindow(self)

        self.setStyleSheet(base_qss(ground=False) + _local_style())
        self._build_ui()
        self._populate_fields()
        if open_tab == "plan":
            self._tabs.setCurrentWidget(self._plan_tab)
        self.setMinimumWidth(580)
        # No explicit minimum height: the layout's own minimum keeps the tallest
        # tab from being squeezed below its widgets' sizes.
        # Wide enough for the PLAN tab's A/B comparison without squeezing it.
        self.resize(720, 640)
        # drag support state
        self._drag_pos: object = None

    # ── Drag-to-move (frameless window) ──────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    # mouseMoveEvent is defined later in this class (it also repositions the
    # scale/ambient float windows); the earlier duplicate has been removed.

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── Scale integration ────────────────────────────────────────────────────

    def _connect_scale(self) -> None:
        try:
            sm = self._aw.scale_manager
            self.scale1_was_connected = sm.is_scale1_connected()
            if sm.is_scale1_configured():
                self._scale_window = _ScaleFloatWindow(self)
                sm.scale1_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.connect(self._scale_window.scale_disconnected)
                sm.scale1_connected_signal.connect(self._on_scale_connected)
                if self.scale1_was_connected:
                    # already connected: seed the float window with the last reading
                    scale1_last_weight = sm.get_scale1_last_weight()
                    if scale1_last_weight is not None:
                        self._scale_window.update_weight(scale1_last_weight)
                else:
                    # not connected yet: request a connection
                    self.request_scale_connect()
        except Exception as exc:  # noqa: BLE001
            _log.warning("Scale not available: %s", exc)

    def request_scale_connect(self) -> None:
        """(Re)connect scale 1 — also the manual retry when the card is tapped."""
        if self._scale_window is None:
            return
        try:
            sm = self._aw.scale_manager
            if not sm.is_scale1_configured() or sm.is_scale1_connected():
                return
            self._scale_window.scale_connecting()
            sm.connect_scale1_signal.emit(False)
        except Exception as exc:  # noqa: BLE001
            _log.warning("Scale connect request failed: %s", exc)

    @pyqtSlot()
    def _on_scale_connected(self) -> None:
        if self._scale_window is None:
            return
        self._scale_window.scale_ready()
        try:
            last = self._aw.scale_manager.get_scale1_last_weight()
            if last is not None:
                self._scale_window.update_weight(last)
        except Exception:  # noqa: BLE001
            pass

    def _disconnect_scale(self) -> None:
        if self._scale_window is None:
            return
        if self._aw.scale_manager.is_scale1_configured():
            # disconnect from scale_manager signals
            try:
                self._aw.scale_manager.scale1_weight_changed_signal.disconnect(self._scale_window.update_weight)
                self._aw.scale_manager.scale1_stable_weight_changed_signal.disconnect(self._scale_window.update_weight)
                self._aw.scale_manager.scale1_disconnected_signal.disconnect(self._scale_window.scale_disconnected)
                self._aw.scale_manager.scale1_connected_signal.disconnect(self._on_scale_connected)
            except Exception as e: # pylint: disable=broad-except
                _log.error(e)
            # the scale is deliberately left connected when the setup
            # dialog closes: the roast that follows ends on RoastResultDialog,
            # which needs the very same link to weigh the roasted batch.

    def _show_scale_window(self) -> None:
        """Float the scale card, then the room card below it, right of the sheet."""
        geo = self.geometry()
        x, y = geo.right() + 12, geo.top() + 40
        if self._scale_window is not None:
            self._scale_window.move(x, y)
            self._scale_window.show()
            y = self._scale_window.geometry().bottom() + 8
        room = self._room_window()
        if room is not None:
            room.move(x, y)
            room.show()

    def _room_window(self):  # noqa: ANN202
        """The card the room is read from: the ambient probe, else the weather card."""
        return self._ambient_window or getattr(self, "_weather_window", None)

    def _artisan_elevation(self) -> float:
        """The altitude set in Artisan's own settings, 0 when none."""
        try:
            elevation = float(self._aw.qmc.elevation or 0.0)
        except (AttributeError, TypeError, ValueError):
            return 0.0
        return elevation if elevation > 0 else 0.0

    def _room_values(self) -> tuple[float, float, float]:
        """(temperature in the display unit, humidity %, altitude m) the plan is built on.

        Probe or weather card first; the altitude then falls back to Artisan's
        own setting, then to sea level.
        """
        t = 20.0 if self._temp_unit() != 'F' else fromCtoFstrict(20.0)
        h = 50.0
        a: float | None = None
        room = self._room_window()
        if room is not None:
            try:
                if room.temperature is not None:
                    t = float(room.temperature)
                if room.humidity is not None:
                    h = float(room.humidity)
                if room.altitude is not None:
                    a = float(room.altitude)
            except Exception:  # noqa: BLE001
                pass
        return t, h, (a if a is not None else self._artisan_elevation())

    @pyqtSlot(float)
    def receive_scale_weight(self, weight: float) -> None:
        """Called when user clicks the floating scale value."""
        current = self._green_weight_edit.text().strip()
        if current in ('', '0', '0.0') or not self._weight_confirmed:
            self._set_confirmed_weight(f"{weight:.0f}", "scale")
        else:
            reply = show_styled_message(
                self,
                QApplication.translate("tilauscope_roast_setup", "Replace Weight?"),
                QApplication.translate("tilauscope_roast_setup", "Current weight is <b>{0} g</b>.<br>Replace with scale reading <b>{1} g</b>?").format(current, weight),
                QMessageBox.Icon.Question,
                rich=True,
                width=400,
            )
            if reply == QMessageBox.StandardButton.Ok:
                self._set_confirmed_weight(f"{weight:.0f}", "scale")

    def _set_confirmed_weight(self, text: str, source: str) -> None:
        self._weight_confirmed = True
        self._weight_source = source
        self._green_weight_edit.setText(text)
        self._update_ok_button_state()

    @pyqtSlot(str)
    def _on_weight_typed(self, _text: str) -> None:
        self._weight_confirmed = True
        self._weight_source = "typed"
        self._update_ok_button_state()

    def _last_batch_weight(self) -> float | None:
        """Green weight of the most recent roast of this coffee, from BeanCave's roast index."""
        cache = getattr(self._parent_widget, "_metadata_cache", None)
        uuid = (getattr(self._bean, "uuid", "") or "").lower()
        if cache is None or not uuid:
            return None
        latest = None
        try:
            for rec in cache.records.values():
                if (rec.uuid or "").lower() == uuid and not rec.simulated and rec.weight_in_g > 0 and (
                        latest is None or rec.roastepoch > latest.roastepoch):
                    latest = rec
        except Exception:  # noqa: BLE001
            return None
        return latest.weight_in_g if latest is not None else None

    # ── UI construction ──────────────────────────────────────────────────────

    def _tooltip_style(self):
        return tooltip_qss()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Card shell ────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("setupCard")
        card.setStyleSheet(f"""
            QFrame#setupCard {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 20px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 24)
        card_layout.setSpacing(14)
        outer.addWidget(card)

        # ── Header row ────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "ROAST SETUP"))
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 16px; font-weight: 800;"
            f"letter-spacing: 3px;"
        )
        header_row.addWidget(title_lbl)

        # Roaster name – shown next to title when configured
        if self._roaster:
            roaster_lbl = QLabel(
               self._roaster.upper()
            )
            roaster_lbl.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 9px; font-weight: bold;"
                f"letter-spacing: 1px; margin-left: 84px;"
            )
            header_row.addWidget(roaster_lbl)

        header_row.addStretch()
        self._date_lbl = QLabel()
        self._date_lbl.setProperty('variant', 'caption')
        from datetime import datetime
        self._date_lbl.setText(datetime.now().strftime("%a %d %b %Y  %H:%M"))
        header_row.addWidget(self._date_lbl)
        card_layout.addLayout(header_row)
        card_layout.addWidget(_separator())

        # ── Tab widget ────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(False)
        self._tabs.setStyleSheet(f"""
            QTabWidget {{
                background: transparent;
            }}
            QTabWidget::pane {{
                border: none;
                background: transparent;
                margin-top: 0px;
            }}
            QTabWidget > QWidget {{
                background: transparent;
            }}
            QTabBar {{
                background: {THEME['BG']};
                border: none;
            }}
            QTabBar::tab {{
                background: {THEME['BG']};
                color: {THEME['SUBTEXT']};
                font-size: 12px;
                font-weight: bold;
                letter-spacing: 1.5px;
                padding: 9px 24px;
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
            QTabBar::tab:!selected {{
                background: {THEME['BG']};
            }}
        """)
        card_layout.addWidget(self._tabs, 1)

        # ── TAB 1: Roast fields ───────────────────────────────────────────
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        t1.setContentsMargins(0, 16, 0, 0)
        t1.setSpacing(14)
        self._tabs.addTab(tab1, QApplication.translate("tilauscope_roast_setup", "⬥  ROAST"))

        # Bean
        t1.addWidget(_section_label(QApplication.translate("tilauscope_common", "Bean")))
        self._bean_info_frame = QFrame()
        self._bean_info_frame.setStyleSheet(" border: none;")
        bean_info_layout = QVBoxLayout(self._bean_info_frame)
        bean_info_layout.setContentsMargins(5, 5, 5, 5)
        bean_info_layout.setSpacing(2)
        # fixed 3-line layout (title / reduced summary / notes), no wrap
        self._bean_info_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._bean_name_lbl = QLabel("---------------------------")
        self._bean_name_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 12px; font-weight: bold; border: none;"
            + self._tooltip_style()
        )
        self._bean_name_lbl.setWordWrap(False)

        self._bean_meta_lbl = QLabel("---------------------------")
        self._bean_meta_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; border: none;"
            + self._tooltip_style()
        )
        self._bean_meta_lbl.setWordWrap(False)

        self._bean_flavour_lbl = QLabel("---------------------------")
        self._bean_flavour_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; border: none; font-style: italic;"
            + self._tooltip_style()
        )
        self._bean_flavour_lbl.setWordWrap(False)

        bean_info_layout.addWidget(self._bean_name_lbl)
        bean_info_layout.addWidget(self._bean_meta_lbl)
        bean_info_layout.addWidget(self._bean_flavour_lbl)
        t1.addWidget(self._bean_info_frame)

        # Roast title
        t1.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Roast title")))
        self._title_combo = QComboBox()
        self._title_combo.setEditable(True)
        self._title_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._title_combo.setMinimumHeight(38)
        t1.addWidget(self._title_combo)

        # Batch (forecast — never advances the counter; toggle delegates activation)
        t1.addWidget(_section_label(QApplication.translate("Label", "Batch")))
        self._batch_block = _BatchBlock(self._aw, _BatchBlock.MODE_PREVIEW)
        # guard against vertical compression on short screens
        self._batch_block.setMinimumHeight(56)
        self._batch_block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        t1.addWidget(self._batch_block)

        # Green weight
        t1.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Green weight")))
        weight_row = QHBoxLayout()
        self._green_weight_edit = QLineEdit()
        self._green_weight_edit.setPlaceholderText("0")
        self._green_weight_edit.setMinimumHeight(42)
        self._green_weight_edit.setMaximumWidth(140)
        self._green_weight_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._green_weight_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 22px; font-weight: bold; color: {THEME['TEXT']};"
            f"background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 8px; padding: 6px 12px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        g_unit = QLabel(QApplication.translate("Label", "g"))
        g_unit.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 18px; margin-left: 4px;")
        self._stock_lbl = QLabel()
        self._stock_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 12px; margin-left: 16px;"
        )
        weight_row.addWidget(self._green_weight_edit)
        weight_row.addWidget(g_unit)
        weight_row.addWidget(self._stock_lbl)
        weight_row.addStretch()
        t1.addLayout(weight_row)
        self._weight_prefill_lbl = QLabel(QApplication.translate(
            "tilauscope_roast_setup", "Last batch of this coffee — weigh it or type it to confirm."))
        self._weight_prefill_lbl.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 11px;")
        self._weight_prefill_lbl.hide()
        t1.addWidget(self._weight_prefill_lbl)

        self._decrease_stock_cb = QCheckBox(QApplication.translate("tilauscope_roast_setup", "Decrease bean stock by this weight after OK"))
        self._decrease_stock_cb.setChecked(True)
        t1.addWidget(self._decrease_stock_cb)

        # Physical properties moved to ⚙ OPTIONS tab (see _build_optional_tab2)

        # Artisan beans field
        self._beans_field_edit = QLineEdit()
        self._beans_field_edit.setPlaceholderText(QApplication.translate("tilauscope_roast_setup", "Bean info injected into Artisan …"))
        self._beans_field_edit.setMinimumHeight(60)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        refresh_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "↺  Rebuild from bean"))
        refresh_btn.setProperty('variant', 'outline')
        refresh_btn.clicked.connect(self._rebuild_beans_field)
        refresh_row.addWidget(refresh_btn)
        #t1.addLayout(refresh_row)
        t1.addStretch()

        # ── TAB 2: Optional settings ──────────────────────────────────────
        tab2 = QWidget()
        self._tabs.addTab(tab2, QApplication.translate("tilauscope_roast_setup", "⚙  OPTIONS"))
        self._build_optional_tab2(tab2)

        # ── TAB 3: Optional settings ──────────────────────────────────────
        tab3 = QWidget()
        self._tabs.addTab(tab3, QApplication.translate("tilauscope_roast_setup", "⚙  MORE OPTIONS"))
        self._build_optional_tab3(tab3)

        # ── TAB 4: the plan — choices stay put, the roadmap scrolls ───────
        tab4 = QWidget()
        self._plan_tab = tab4
        self._tabs.addTab(tab4, QApplication.translate("tilauscope_roast_setup", "ⓘ  PLAN"))
        t4 = QVBoxLayout(tab4)
        t4.setContentsMargins(0, 14, 0, 0)
        t4.setSpacing(10)
        t4.addWidget(self._build_plan_choices())
        self._insights_panel = _RoastInsightsPanel(self._aw, self)
        t4.addWidget(self._insights_panel, 1)

        # ── Buttons (always visible, outside tabs) ────────────────────────
        card_layout.addWidget(_separator())
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        cancel_btn = QPushButton(QApplication.translate("Button", "Cancel"))
        cancel_btn.setObjectName('footerBtn')
        cancel_btn.setProperty('variant', 'outline')
        cancel_btn.clicked.connect(self._on_cancel)

        self._ok_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "⬥  Start Roast"))
        self._ok_btn.setObjectName('footerBtn')
        self._ok_btn.setProperty('variant', 'primary')
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok)

        self._weigh_hint_lbl = QLabel("⚖  " + QApplication.translate(
            "tilauscope_roast_setup", "Weigh the batch to start the roast"))
        self._weigh_hint_lbl.setStyleSheet(f"color: {THEME['WARNING']}; font-size: 12px;")
        btn_row.addWidget(self._weigh_hint_lbl)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._ok_btn)
        card_layout.addLayout(btn_row)

        self._green_weight_edit.textChanged.connect(self._update_ok_button_state)
        self._green_weight_edit.textEdited.connect(self._on_weight_typed)
        # Recompute insights when any physical / setup input changes (debounced)
        for _w in (self._green_weight_edit, self._density_edit,
                   self._moisture_edit, self._bean_temp_edit):
            _w.textChanged.connect(self._refresh_insights)
        # Populate from current Artisan state
        self._populate_optional_tab()
        self._fill_plan_level_combo()
        self._profile_combo.currentIndexChanged.connect(self._sync_plan_level)


    # ── Helpers ──────────────────────────────────────────────────────────────

    def _temp_unit(self) -> str:
        try:
            return self._aw.qmc.mode
        except Exception:  # noqa: BLE001
            return "C"

    def _build_beans_field(self) -> str:
        """Mimics the beans text that Artisan/BeanCave historically injects."""
        b = self._bean
        parts: list[str] = []
        if b.name:
            parts.append(b.name)
        if b.country:
            parts.append(b.country)
        if b.farm:
            parts.append("{0} {1}".format(QApplication.translate("tilauscope_common", "Farm:"), b.farm))
        if b.process:
            parts.append("{0} {1}".format(QApplication.translate("tilauscope_common", "Process"), b.process))
        if b.varieties:
            parts.append("{0} {1}".format(QApplication.translate("tilauscope_common", "Variety"), b.varieties))
        if b.altitude:
            parts.append("{0} {1}m".format(QApplication.translate("tilauscope_common", "Altitude:"), b.altitude))
        if b.sca:
            parts.append(QApplication.translate("tilauscope_common", "SCA: {0}").format(f"{b.sca:.1f}"))
        if b.uuid:
            # Machine key, not a label: the assistant reads it back to find the
            # bean. Translated, French returned "uuid : : {0}" and the roast lost
            # its link to the record it names.
            parts.append(f"uuid: {b.uuid}")
        return "\n".join(parts)

    def _populate_fields(self) -> None:
        b = self._bean

        # Bean name
        self._bean_name_lbl.setText(b.name or QApplication.translate("tilauscope_roast_setup", "(no name)"))
        self._bean_name_lbl.setToolTip(b.name or "")

        # Meta line — full detail kept in tooltip, label shows a reduced 1-line summary
        full_parts: list[str] = []
        if b.country:
            full_parts.append(b.country)
        if b.farm:
            full_parts.append(b.farm)
        if b.process:
            full_parts.append(b.process)
        if b.varieties:
            full_parts.append(b.varieties)
        if b.altitude:
            full_parts.append("{0} {1} m".format(QApplication.translate("tilauscope_common", "Altitude:"), b.altitude))
        if b.crop:
            full_parts.append("{0} {1}".format(QApplication.translate("tilauscope_common", "Crop"), b.crop))
        if b.sca:
            full_parts.append(QApplication.translate("tilauscope_roast_setup", "SCA {0}").format(f"{b.sca:.1f}"))

        summary_parts: list[str] = []
        if b.country:
            summary_parts.append(b.country)
        if b.process:
            summary_parts.append(b.process)
        if b.varieties:
            summary_parts.append(b.varieties)
        if b.sca:
            summary_parts.append(QApplication.translate("tilauscope_roast_setup", "SCA {0}").format(f"{b.sca:.1f}"))

        self._bean_meta_lbl.setText("  ·  ".join(summary_parts) if summary_parts else "")
        self._bean_meta_lbl.setToolTip("  ·  ".join(full_parts) if full_parts else "")

        # Flavour
        self._bean_flavour_lbl.setText(b.flavour_notes or "")
        self._bean_flavour_lbl.setToolTip(b.flavour_notes or "")
        self._bean_flavour_lbl.setVisible(bool(b.flavour_notes))

        # Stock
        stock = getattr(b, 'weight_left', 0.0)
        self._stock_lbl.setText(QApplication.translate("tilauscope_roast_setup", "Stock: {0} g").format(f"{stock:.0f}"))
        if stock < 1:
            self._stock_lbl.setStyleSheet(
                f"color: {THEME['CRITICAL']}; font-size: 12px; margin-left: 16px;"
            )

        # Batch weight: the last one of this coffee, proposed until confirmed
        if not self._green_weight_edit.text().strip():
            last_batch = self._last_batch_weight()
            if last_batch:
                self._green_weight_edit.setText(f"{last_batch:.0f}")

        # Physical
        self._density_edit.setText(f"{b.density:.1f}" if b.density else "")
        self._moisture_edit.setText(f"{b.last_humidity:.1f}" if b.last_humidity else "")
        self._update_ok_button_state()

        # Title suggestion
        try:
            if self._title_combo.count() == 0 or self._title_combo.currentText() == "":
                crop = str(b.crop) if b.crop else 'N/A'
                self._title_combo.setCurrentText(f"{b.name} - {b.process} - {crop}")
        except Exception:  # noqa: BLE001
            pass

        # Beans field
        self._beans_field_edit.setText(self._build_beans_field())

        self._refresh_insights()

    @pyqtSlot()
    def _rebuild_beans_field(self) -> None:
        self._beans_field_edit.setText(self._build_beans_field())

    @pyqtSlot()
    def _update_ok_button_state(self) -> None:
        """Start needs a weight that was weighed or typed — a pre-filled one is only a proposal."""
        try:
            txt = self._green_weight_edit.text().replace(',', '.')
            val = float(txt) if txt else 0.0
        except ValueError:
            val = 0.0
        ready = val > 0 and self._weight_confirmed
        self._ok_btn.setEnabled(ready)
        self._weigh_hint_lbl.setVisible(not ready)
        self._weight_prefill_lbl.setVisible(val > 0 and not self._weight_confirmed)
        self._refresh_plan_weight(val)

    # ── PLAN tab choices: the same three settings as ROAST and OPTIONS ────────

    def _build_plan_choices(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        def _column(caption: str, widget: QWidget, stretch: int = 0) -> None:
            col = QVBoxLayout()
            col.setSpacing(5)
            cap = QLabel(caption.upper())
            cap.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px; letter-spacing: 1.5px;")
            col.addWidget(cap)
            col.addWidget(widget)
            row.addLayout(col, stretch)

        # Weight: the field of the ROAST tab, read here; a tap weighs.
        self._plan_weight_btn = QPushButton()
        self._plan_weight_btn.setObjectName("planWeightChip")
        self._plan_weight_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plan_weight_btn.setMinimumSize(180, 54)
        wl = QVBoxLayout(self._plan_weight_btn)
        wl.setContentsMargins(12, 5, 12, 5)
        wl.setSpacing(0)
        self._plan_weight_val = QLabel()
        self._plan_weight_val.setStyleSheet(
            f"color: {THEME['TEXT']}; font-family: '{mono_family()}'; font-size: 17px; font-weight: bold;"
            f"background: transparent;")
        self._plan_weight_sub = QLabel()
        for lbl in (self._plan_weight_val, self._plan_weight_sub):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            wl.addWidget(lbl)
        self._plan_weight_btn.clicked.connect(self._on_plan_weight_clicked)
        _column(QApplication.translate("tilauscope_roast_setup", "Green weight"), self._plan_weight_btn)

        # Use: a second face of the OPTIONS segmented control.
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self._plan_dest_group = QButtonGroup(self)
        self._plan_dest_group.setExclusive(True)
        self._plan_dest_buttons: dict[str, QPushButton] = {}
        for i, key in enumerate(self._DEST_KEYS):
            b = QPushButton(self._dest_buttons[key].text())
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(54)
            b.setStyleSheet(self._dest_buttons[key].styleSheet())
            self._plan_dest_group.addButton(b, i)
            self._plan_dest_buttons[key] = b
            sl.addWidget(b, 1)
        for key, b in self._dest_buttons.items():
            self._plan_dest_buttons[key].setChecked(b.isChecked())
        self._plan_dest_group.idClicked.connect(self._on_plan_destination_clicked)
        _column(QApplication.translate("tilauscope_roast_setup", "What is this coffee for?"), seg, 1)

        # Level: the OPTIONS profile, by name only.
        self._plan_level_combo = QComboBox()
        self._plan_level_combo.setMinimumHeight(54)
        self._plan_level_combo.setMinimumWidth(150)
        self._plan_level_combo.currentIndexChanged.connect(self._on_plan_level_changed)
        _column(QApplication.translate("tilauscope_common", "Roast level"), self._plan_level_combo)
        return host

    def _refresh_plan_weight(self, val: float) -> None:
        if not hasattr(self, "_plan_weight_btn"):
            return
        self._plan_weight_val.setText(f"{val:.0f} g" if val > 0 else "— g")
        if val <= 0:
            sub, colour, border = (QApplication.translate("tilauscope_roast_setup", "tap to weigh"),
                                   THEME['SUBTEXT'], f"1.5px dashed {THEME['BORDER']}")
        elif not self._weight_confirmed:
            sub, colour, border = (QApplication.translate("tilauscope_roast_setup", "last batch — tap to weigh"),
                                   THEME['WARNING'], f"1.5px dashed {THEME['WARNING']}")
        elif self._weight_source == "scale":
            sub, colour, border = (QApplication.translate("tilauscope_roast_setup", "weighed on the scale"),
                                   THEME['SUCCESS'], f"1px solid {THEME['BORDER']}")
        else:
            sub, colour, border = (QApplication.translate("tilauscope_roast_setup", "entered by hand"),
                                   THEME['SUBTEXT'], f"1px solid {THEME['BORDER']}")
        self._plan_weight_sub.setText(sub)
        self._plan_weight_sub.setStyleSheet(f"color: {colour}; font-size: 10px; background: transparent;")
        self._plan_weight_btn.setStyleSheet(
            f"QPushButton#planWeightChip {{ background: {THEME['SURFACE']}; border: {border};"
            f"border-radius: 8px; text-align: left; }}"
            f"QPushButton#planWeightChip:hover {{ border-color: {THEME['ACCENT']}; }}")

    @pyqtSlot()
    def _on_plan_weight_clicked(self) -> None:
        """Take the scale's reading when there is one, else hand over to the weight field."""
        try:
            sm = self._aw.scale_manager
            if sm.is_scale1_configured() and sm.is_scale1_connected():
                last = sm.get_scale1_last_weight()
                if last is not None and float(last) > 0:
                    self.receive_scale_weight(float(last))
                    return
        except Exception:  # noqa: BLE001
            pass
        self._tabs.setCurrentIndex(0)
        self._green_weight_edit.setFocus()
        self._green_weight_edit.selectAll()

    def _on_plan_destination_clicked(self, index: int) -> None:
        if 0 <= index < len(self._DEST_KEYS):
            self._dest_buttons[self._DEST_KEYS[index]].setChecked(True)
        self._on_destination_changed(index)

    def _fill_plan_level_combo(self) -> None:
        combo = self._plan_level_combo
        combo.blockSignals(True)
        combo.clear()
        for i in range(self._profile_combo.count()):
            data = self._profile_combo.itemData(i)
            profile = data.get('profile') if isinstance(data, dict) else None
            combo.addItem(str(getattr(profile, 'name', '')) if profile is not None
                          else QApplication.translate("tilauscope_common", "Choose…"))
        combo.setCurrentIndex(self._profile_combo.currentIndex())
        combo.blockSignals(False)

    @pyqtSlot(int)
    def _on_plan_level_changed(self, index: int) -> None:
        if 0 <= index < self._profile_combo.count() and index != self._profile_combo.currentIndex():
            self._profile_combo.setCurrentIndex(index)

    @pyqtSlot(int)
    def _sync_plan_level(self, index: int) -> None:
        if self._plan_level_combo.currentIndex() != index:
            self._plan_level_combo.blockSignals(True)
            self._plan_level_combo.setCurrentIndex(index)
            self._plan_level_combo.blockSignals(False)

    _DEST_KEYS: tuple[str, ...] = ("filter", "omni", "espresso")

    def _restore_destination(self) -> None:
        """Select the destination remembered from the last roast (default omni)."""
        from PyQt6.QtCore import QSettings
        key = str(QSettings().value("tilauscope/roast_destination", "omni", str) or "omni")
        if key not in self._dest_buttons:
            key = "omni"
        self._dest_buttons[key].setChecked(True)

    def _on_destination_changed(self, index: int) -> None:
        """Persist the destination and recompute the plan with it.

        The engine re-reads the setting at each run, so the refresh below is
        enough — the cached engine object does not have to be rebuilt.
        """
        from PyQt6.QtCore import QSettings
        if not 0 <= index < len(self._DEST_KEYS):
            return
        QSettings().setValue("tilauscope/roast_destination", self._DEST_KEYS[index])
        plan_button = getattr(self, "_plan_dest_buttons", {}).get(self._DEST_KEYS[index])
        if plan_button is not None:
            plan_button.setChecked(True)
        self._refresh_insights()

    def _set_family_readout(self, family: str, delta_c: float) -> None:
        """State what the coffee's variety did to the charge, or that it did nothing.

        A prior the operator cannot see is a prior they cannot argue with, and
        half of the variety vocabulary is deliberately silent — saying so is what
        keeps the silence readable instead of looking like a failure.
        """
        if not family:
            self._family_lbl.setText(QApplication.translate(
                "tilauscope_roast_setup", "Bean family: not known — using the standard pace"))
            return
        if delta_c > 0:
            pace = QApplication.translate("tilauscope_common", "wants a faster roast")
        elif delta_c < 0:
            pace = QApplication.translate("tilauscope_common", "takes a slower roast")
        else:
            pace = QApplication.translate("tilauscope_common", "keeps the standard pace")
        self._family_lbl.setText(QApplication.translate(
            "tilauscope_roast_setup", "Bean family: {0} — {1} ({2} °{3} on the charge)").format(
                family, pace, f"{delta_c:+.0f}", self._temp_unit()))

    def _set_tasting_readout(self, change: dict | None) -> None:
        """Recall what the last tasting of this coffee changed in this plan, with the numbers."""
        if not change:
            self._tasting_lbl.hide()
            return
        self._tasting_lbl.setText(_tasting_change_text(change, self._temp_unit()))
        self._tasting_lbl.show()

    @pyqtSlot()
    def _refresh_insights(self) -> None:
        panel = getattr(self, "_insights_panel", None)
        if panel is None:
            return

        def _f(edit, default: float = 0.0) -> float:
            try:
                return float(edit.text().replace(',', '.'))
            except (ValueError, AttributeError):
                return default

        # The room from the probe or the weather card. The engine takes the
        # temperature in the DISPLAY unit and normalises it itself, exactly as
        # the assistant passes it — °C here was read as °F in °F mode.
        amb_t, amb_h, altitude = self._room_values()
        self._planned_ambient = (amb_t, amb_h, altitude)

        # Target roast level comes from the OPTIONS profile selection
        data = self._profile_combo.itemData(self._profile_combo.currentIndex())
        target_scale = data.get('profile') if isinstance(data, dict) else None

        bt_txt = self._bean_temp_edit.text().strip()
        panel.request(
            bean=self._bean,
            density=_f(self._density_edit, self._bean.density),
            moisture=_f(self._moisture_edit, self._bean.last_humidity),
            green_weight=_f(self._green_weight_edit, 0.0),
            bean_temp=_f(self._bean_temp_edit) if bt_txt else None,
            ctx=self._roaster_ctx,
            mode=self._temp_unit(),
            ambient_temp=amb_t,
            ambient_humidity=amb_h,
            altitude=altitude,
            plan_parent=self._aw,
            target_scale=target_scale,
            run_plan=True,
        )

    def _on_ambient_reading(self) -> None:
        """Re-plan when the room differs from the one the plan was built on.

        The probe answers a few seconds after the sheet opens, the weather on a
        tap: without this the plan stayed on the 20 °C / sea-level defaults.
        """
        last = getattr(self, "_planned_ambient", None)
        t, h, a = self._room_values()
        if (last is None or abs(t - last[0]) >= 0.5
                or abs(h - last[1]) >= 2.0 or abs(a - last[2]) >= 10.0):
            self._refresh_insights()

    @pyqtSlot(float)
    def _on_plan_charge_temperature(self, temperature: float) -> None:
        """Offer the plan's charge temperature to the preheat PID.

        Fills the field only while it still belongs to the plan. Once the
        operator has typed their own setpoint the field is theirs, and the plan
        states its figure beside it instead of replacing it.
        """
        self._plan_charge_temperature = temperature
        if not self._pid_charge_temp_user_set:
            self._pid_value_edit.setText(f"{temperature:.0f}")
            self._set_pid_recommendation_visible(False)
            return
        self._refresh_pid_recommendation()

    def _on_pid_value_typed(self, _text: str) -> None:
        """The field becomes the operator's the moment they type in it."""
        self._pid_charge_temp_user_set = True
        self._refresh_pid_recommendation()

    def _adopt_plan_charge_temperature(self) -> None:
        """`use`: hand the field back to the plan."""
        if self._plan_charge_temperature is None:
            return
        self._pid_charge_temp_user_set = False
        self._pid_value_edit.setText(f"{self._plan_charge_temperature:.0f}")
        self._set_pid_recommendation_visible(False)

    def _refresh_pid_recommendation(self) -> None:
        """Show the plan's figure only when it differs from what is typed."""
        planned = self._plan_charge_temperature
        if planned is None:
            self._set_pid_recommendation_visible(False)
            return
        try:
            typed = float(self._pid_value_edit.text())
        except (TypeError, ValueError):
            typed = None
        if typed is not None and abs(typed - planned) < 0.5:
            self._set_pid_recommendation_visible(False)
            return
        self._pid_reco_lbl.setText(QApplication.translate(
            "tilauscope_roast_setup", "Plan recommends {0} °{1}").format(
                f"{planned:.0f}", self._temp_unit()))
        self._set_pid_recommendation_visible(True)

    def _set_pid_recommendation_visible(self, visible: bool) -> None:
        self._pid_reco_lbl.setVisible(visible)
        self._pid_reco_btn.setVisible(visible)

    # ── Optional settings tab ─────────────────────────────────────────────────

    def _build_optional_tab2(self, tab: QWidget) -> None:
        """Builds the ⚙ OPTIONS tab content."""
        t = QVBoxLayout(tab)
        t.setContentsMargins(0, 16, 0, 0)
        t.setSpacing(20)

        # ── 0. Roast intent ───────────────────────────────────────────────────
        # Above the target profile because it decides what that profile serves.
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Roast intent")))
        intent_card = QFrame()
        intent_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        ic = QVBoxLayout(intent_card)
        ic.setContentsMargins(16, 14, 16, 14)
        ic.setSpacing(10)

        dest_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "What is this coffee for?"))
        dest_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic; border: none;")
        ic.addWidget(dest_lbl)

        # Segmented control, not a toggle: three options that name themselves,
        # so nothing has to be read as the inverse of a state.
        _dest_seg = (
            f"QPushButton:checked {{ color: {THEME['BG']}; background: {THEME['ACCENT']};"
            f"border: 1px solid {THEME['ACCENT']}; }}"
        )
        dest_row = QHBoxLayout()
        dest_row.setSpacing(0)
        self._dest_group = QButtonGroup(self)
        self._dest_group.setExclusive(True)
        _dest_defs = (
            ("filter",   QApplication.translate("tilauscope_roast_setup", "Filter")),
            ("omni",     QApplication.translate("tilauscope_roast_setup", "Omni")),
            ("espresso", QApplication.translate("tilauscope_common", "Espresso")),
        )
        self._dest_buttons: dict[str, QPushButton] = {}
        for _i, (_key, _label) in enumerate(_dest_defs):
            _b = QPushButton(_label)
            _b.setCheckable(True)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _radius = ("border-top-left-radius: 6px; border-bottom-left-radius: 6px;" if _i == 0
                       else "border-top-right-radius: 6px; border-bottom-right-radius: 6px;"
                       if _i == len(_dest_defs) - 1 else "")
            _b.setStyleSheet(
                f"QPushButton {{ color: {THEME['SUBTEXT']}; background: {THEME['BG']};"
                f"border: 1px solid {THEME['BORDER']};"
                f"{'border-left: none;' if _i else ''} padding: 6px 18px;"
                f"font-size: 13px; font-weight: bold; {_radius} }}" + _dest_seg)
            self._dest_group.addButton(_b, _i)
            self._dest_buttons[_key] = _b
            dest_row.addWidget(_b)
        dest_row.addStretch()
        ic.addLayout(dest_row)

        # Bean family — read, never asked: it comes from the coffee's record.
        self._family_lbl = QLabel("")
        self._family_lbl.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 12px; border: none;")
        ic.addWidget(self._family_lbl)
        # What the last tasting of this coffee changed in the plan — hidden when nothing.
        self._tasting_lbl = QLabel("")
        self._tasting_lbl.setWordWrap(True)
        self._tasting_lbl.setStyleSheet(
            f"color: {THEME['TODAY']}; font-size: 12px; border: none;")
        self._tasting_lbl.hide()
        ic.addWidget(self._tasting_lbl)
        t.addWidget(intent_card)

        self._restore_destination()
        self._set_family_readout("", 0.0)
        self._dest_group.idClicked.connect(self._on_destination_changed)

        # ── 1. Target roast profile ───────────────────────────────────────────
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Target roast profile")))

        profile_card = QFrame()
        profile_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        pc = QVBoxLayout(profile_card)
        pc.setContentsMargins(16, 14, 16, 14)
        pc.setSpacing(10)

        profile_hint = QLabel(QApplication.translate("tilauscope_roast_setup", "Link a roast plan profile to guide this session."))
        profile_hint.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic; border: none;"
        )
        pc.addWidget(profile_hint)

        profile_row = QHBoxLayout()
        self._profile_combo = QComboBox()
        self._profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._profile_combo.setMinimumHeight(36)
        self._profile_combo.setToolTip(
            QApplication.translate("tilauscope_roast_setup", "Select a roast plan profile.\nPhase injection will be available in a future version.")
        )
        self._profile_combo.setStyleSheet(self.styleSheet() + self._tooltip_style())

        self._profile_color_dot = QLabel("●")
        self._profile_color_dot.setStyleSheet(
            f"color: {THEME['BORDER']}; font-size: 20px; margin-left: 6px; border: none;"
        )
        self._profile_color_dot.setVisible(False)
        profile_row.addWidget(self._profile_combo, 1)
        profile_row.addWidget(self._profile_color_dot)
        pc.addLayout(profile_row)

        self._profile_future_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "⟳  Phase injection will be available in the next version"))
        self._profile_future_lbl.setStyleSheet(
            f"color: {THEME['BORDER']}; font-size: 10px; font-style: italic; border: none;"
        )
#        self._profile_future_lbl.setVisible(False)
        pc.addWidget(self._profile_future_lbl)
        t.addWidget(profile_card)

        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self._profile_combo.currentIndexChanged.connect(self._refresh_insights)

        # ── 2. Physical properties (moved from ROAST tab) ─────────────────────
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Physical properties")))
        props_row = QHBoxLayout()
        props_row.setSpacing(16)

        density_col = QVBoxLayout()
        density_col.setSpacing(4)
        density_col.addWidget(_field_label(QApplication.translate("tilauscope_common", "Density:")))
        self._density_edit = QLineEdit()
        self._density_edit.setPlaceholderText("0.0")
        self._density_edit.setMinimumHeight(34)
        self._density_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        density_col.addWidget(self._density_edit)
        props_row.addLayout(density_col)

        moisture_col = QVBoxLayout()
        moisture_col.setSpacing(4)
        moisture_col.addWidget(_field_label(QApplication.translate("Label", "Moisture")))
        self._moisture_edit = QLineEdit()
        self._moisture_edit.setPlaceholderText("0.0")
        self._moisture_edit.setMinimumHeight(34)
        self._moisture_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        moisture_col.addWidget(self._moisture_edit)
        props_row.addLayout(moisture_col)

        temp_col = QVBoxLayout()
        temp_col.setSpacing(4)
        temp_col.addWidget(_field_label(QApplication.translate("tilauscope_roast_setup", "Bean temp (°{0})").format(self._temp_unit())))
        self._bean_temp_edit = QLineEdit()
        self._bean_temp_edit.setPlaceholderText("0")
        self._bean_temp_edit.setMinimumHeight(34)
        self._bean_temp_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        temp_col.addWidget(self._bean_temp_edit)
        props_row.addLayout(temp_col)

        t.addLayout(props_row)

        t.addStretch()

    def _build_optional_tab3(self, tab: QWidget) -> None:
        """Builds the ⚙ MORE OPTIONS tab content."""
        t = QVBoxLayout(tab)
        t.setContentsMargins(0, 16, 0, 0)
        t.setSpacing(14)

        # ── 2. TilauPID ───────────────────────────────────────────────────────
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "TilauPID on START")))

        pid_card = QFrame()
        pid_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        pid_c = QVBoxLayout(pid_card)
        pid_c.setContentsMargins(16, 14, 16, 14)
        pid_c.setSpacing(12)

        pid_hint = QLabel(
            QApplication.translate("tilauscope_roast_setup", "Activates TilauPID automatically at roast start by injecting\nan IOCommand on the START event.")
        )
        pid_hint.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic; border: none;"
        )
        pid_c.addWidget(pid_hint)

        self._pid_enable_cb = QCheckBox(QApplication.translate("tilauscope_roast_setup", "Enable TilauPID at start of roast"))
        self._pid_enable_cb.setStyleSheet(
            f"QCheckBox {{ color: {THEME['TEXT']}; font-size: 13px; border: none; }}"
            f"QCheckBox::indicator {{ width:17px; height:17px; border-radius:4px;"
            f"border:1px solid {THEME['BORDER']}; background:{THEME['BG']}; }}"
            f"QCheckBox::indicator:checked {{ background:{THEME['ACCENT']};"
            f"border:1px solid {THEME['ACCENT']}; }}"
        )
        pid_c.addWidget(self._pid_enable_cb)

        # PID value row — always shown, greyed when disabled
        pid_val_row = QHBoxLayout()
        pid_val_row.setSpacing(10)
        pid_val_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "Target temp"))
        pid_val_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; border: none;")
        self._pid_value_edit = QLineEdit()
        self._pid_value_edit.setPlaceholderText(QApplication.translate("tilauscope_roast_setup", "e.g. 200"))
        self._pid_value_edit.setMinimumHeight(38)
        self._pid_value_edit.setMaximumWidth(110)
        self._pid_value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._pid_value_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 16px; font-weight: bold; color: {THEME['ACCENT']};"
            f"background: {THEME['BG']}; border: 1px solid {THEME['ACCENT']};"
            f"border-radius: 6px; padding: 4px 10px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['LAVENDER']}; }}"
            f"QLineEdit:disabled {{ color: {THEME['BORDER']}; border-color: {THEME['BORDER']}; }}"
        )
        pid_unit = QLabel(QApplication.translate("tilauscope_roast_setup", "°{0}").format(self._temp_unit()))
        pid_unit.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 14px; border: none;")
        pid_val_row.addWidget(pid_val_lbl)
        pid_val_row.addWidget(self._pid_value_edit)
        pid_val_row.addWidget(pid_unit)

        # ── PID input source toggle (BT vs ET) — segmented, inline on the Target row.
        # Maps to aw.pidcontrol.pidSource (1 = BT, 2 = ET); the preheat PID and Artisan
        # share this setting, so the choice here drives which channel the PID follows.
        pid_val_row.addSpacing(18)
        pid_input_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "Input"))
        pid_input_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 12px; border: none;")
        pid_val_row.addWidget(pid_input_lbl)

        _seg_checked = (
            f"QPushButton:checked {{ color: {THEME['BG']}; background: {THEME['ACCENT']};"
            f"border: 1px solid {THEME['ACCENT']}; }}"
            f"QPushButton:disabled {{ color: {THEME['BORDER']}; border-color: {THEME['BORDER']};"
            f"background: {THEME['BG']}; }}"
        )
        self._pid_input_bt_btn = QPushButton(QApplication.translate("Button", "BT"))
        self._pid_input_bt_btn.setStyleSheet(
            f"QPushButton {{ color: {THEME['SUBTEXT']}; background: {THEME['BG']};"
            f"border: 1px solid {THEME['BORDER']}; padding: 6px 16px; font-size: 13px; font-weight: bold;"
            f"border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}" + _seg_checked
        )
        self._pid_input_et_btn = QPushButton(QApplication.translate("Button", "ET"))
        self._pid_input_et_btn.setStyleSheet(
            f"QPushButton {{ color: {THEME['SUBTEXT']}; background: {THEME['BG']};"
            f"border: 1px solid {THEME['BORDER']}; border-left: none; padding: 6px 16px; font-size: 13px; font-weight: bold;"
            f"border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}" + _seg_checked
        )
        self._pid_input_group = QButtonGroup(self)
        self._pid_input_group.setExclusive(True)
        seg_wrap = QHBoxLayout()
        seg_wrap.setSpacing(0)
        for _src_id, _btn in ((1, self._pid_input_bt_btn), (2, self._pid_input_et_btn)):  # id == pidSource value
            _btn.setCheckable(True)
            _btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._pid_input_group.addButton(_btn, _src_id)
            seg_wrap.addWidget(_btn)
        self._pid_input_bt_btn.setChecked(True)   # default BT; overridden on load from pidSource
        pid_val_row.addLayout(seg_wrap)
        # Without an ET probe there is nothing to choose: the PID follows BT.
        if not et_available_for(self._aw):
            for _w in (pid_input_lbl, self._pid_input_bt_btn, self._pid_input_et_btn):
                _w.setVisible(False)

        pid_val_row.addStretch()
        pid_c.addLayout(pid_val_row)

        # Plan recommendation, shown only once it differs from what is typed.
        # The plan used to overwrite the field on every recomputation, losing a
        # manual entry without a word; it now states its figure and offers it.
        reco_row = QHBoxLayout()
        reco_row.setSpacing(8)
        self._pid_reco_lbl = QLabel("")
        self._pid_reco_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic; border: none;")
        self._pid_reco_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "use"))
        self._pid_reco_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pid_reco_btn.setStyleSheet(
            f"QPushButton {{ color: {THEME['ACCENT']}; background: transparent;"
            f"border: 1px solid {THEME['ACCENT']}; border-radius: 5px;"
            f"padding: 2px 10px; font-size: 11px; font-weight: bold; }}")
        self._pid_reco_btn.clicked.connect(self._adopt_plan_charge_temperature)
        reco_row.addWidget(self._pid_reco_lbl)
        reco_row.addWidget(self._pid_reco_btn)
        reco_row.addStretch()
        self._set_pid_recommendation_visible(False)
        pid_c.addLayout(reco_row)
        t.addWidget(pid_card)

        ## Une saisie de l'opérateur gèle le champ : `textEdited` ne part qu'à la
        ## frappe, jamais sur `setText`, donc le plan peut continuer à remplir un
        ## champ vierge sans jamais recouvrir une valeur voulue.
        self._pid_value_edit.textEdited.connect(self._on_pid_value_typed)

        # Link enabled state
        def _sync_pid(checked: bool) -> None:
            self._pid_value_edit.setEnabled(checked)
            self._pid_input_bt_btn.setEnabled(checked)
            self._pid_input_et_btn.setEnabled(checked)
        self._pid_enable_cb.toggled.connect(_sync_pid)

        # ── 3. Roast automation ───────────────────────────────────────────────
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Roast automation")))

        auto_card = QFrame()
        auto_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        auto_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        auto_c = QVBoxLayout(auto_card)
        auto_c.setContentsMargins(16, 10, 16, 10)
        auto_c.setSpacing(6)

        # Hint moved to each checkbox's tooltip — "Roast automation" section
        # label above already says what the card is for; a static line here
        # only ate space that 4 checkboxes don't need.

        def _make_auto_cb(label: str, sublabel: str, enabled: bool = True) -> QCheckBox:
            cb = QCheckBox(label)
            cb.setEnabled(enabled)
            cb.setToolTip(sublabel)
            cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cb.setMinimumHeight(22)
            cb.setStyleSheet(self.styleSheet() + self._tooltip_style())
            return cb

        # Row 1: CHARGE / DROP
        self._auto_charge_cb = _make_auto_cb(
            QApplication.translate("tilauscope_roast_setup", "Auto Charge"),
            QApplication.translate("tilauscope_roast_setup", "Automatically detect and mark the CHARGE event"),
            enabled=True,
        )
        self._auto_drop_cb = _make_auto_cb(
            QApplication.translate("tilauscope_roast_setup", "Auto Drop"),
            QApplication.translate("tilauscope_roast_setup", "Automatically detect and mark the DROP event"),
            enabled=True,
        )
        active_row = QHBoxLayout()
        active_row.setSpacing(24)
        active_row.addWidget(self._auto_charge_cb)
        active_row.addWidget(self._auto_drop_cb)
        active_row.addStretch()
        auto_c.addLayout(active_row)

        # Row 2: DRY END / FIRST CRACK (TilauScope detectors)
        self._auto_dry_end_cb = _make_auto_cb(
            QApplication.translate("tilauscope_roast_setup", "Auto Dry End"),
            QApplication.translate("tilauscope_roast_setup", "Detect DRY END from the thermodynamic model (requires a Dry phase BT target in Artisan Phases)"),
            enabled=True,
        )
        self._auto_fc_cb = _make_auto_cb(
            QApplication.translate("tilauscope_roast_setup", "Auto First Crack"),
            QApplication.translate("tilauscope_roast_setup", "Detect FIRST CRACK from the crack counter"),
            enabled=True,
        )
        detect_row = QHBoxLayout()
        detect_row.setSpacing(24)
        detect_row.addWidget(self._auto_dry_end_cb)
        detect_row.addWidget(self._auto_fc_cb)
        detect_row.addStretch()
        auto_c.addLayout(detect_row)
        t.addWidget(auto_card)

        # ── 4. Roast Replay ─────────────────────────────────────────────────
        # Single row, tooltip carries the explanation — tab3 has no scroll area,
        # a full card here overflows the dialog's fixed height (see _on_ok note).
        t.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Roast Replay")))

        replay_card = QFrame()
        replay_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        replay_c = QHBoxLayout(replay_card)
        replay_c.setContentsMargins(16, 10, 16, 10)
        replay_c.setSpacing(14)

        self._replay_enable_cb = QCheckBox(QApplication.translate("tilauscope_roast_setup", "Enable roast replay"))
        self._replay_enable_cb.setStyleSheet(
            f"QCheckBox {{ color: {THEME['TEXT']}; font-size: 13px; border: none; }}"
            f"QCheckBox::indicator {{ width:17px; height:17px; border-radius:4px;"
            f"border:1px solid {THEME['BORDER']}; background:{THEME['BG']}; }}"
            f"QCheckBox::indicator:checked {{ background:{THEME['ACCENT']};"
            f"border:1px solid {THEME['ACCENT']}; }}"
            f"QCheckBox:disabled {{ color: {THEME['SUBTEXT']}; }}"
            + self._tooltip_style()
        )
        replay_c.addWidget(self._replay_enable_cb)
        replay_c.addStretch()

        # Named the background the replay will follow, once the reference is loaded.
        self._replay_reference_chip = QLabel()
        self._replay_reference_chip.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 12px; background: {THEME['BG']};"
            f"border: 1px solid {THEME['SURFACE1']}; border-radius: 10px; padding: 2px 10px;")
        self._replay_reference_chip.hide()
        replay_c.insertWidget(1, self._replay_reference_chip)

        # Why replay is unavailable (no background curve loaded, or roaster does
        # not support it) — a disabled checkbox's own tooltip is too easy to miss.
        self._replay_status_lbl = QLabel()
        self._replay_status_lbl.setWordWrap(False)
        self._replay_status_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; font-style: italic; border: none;"
        )
        replay_c.addWidget(self._replay_status_lbl)

        # Expert only, in place of that reason: load the coffee's reference roast
        # as the background. Nothing is replayed until the box is ticked.
        self._replay_reference_btn = QPushButton()
        self._replay_reference_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._replay_reference_btn.setToolTip(QApplication.translate(
            "tilauscope_roast_setup", "Loads your reference roast as the background curve, so it can be replayed."))
        self._replay_reference_btn.setStyleSheet(
            f"QPushButton {{ color: {THEME['TEXT']}; background: {THEME['BORDER']};"
            f"border: 1px solid {THEME['SURFACE1']}; border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {THEME['YELLOW']}; }}" + self._tooltip_style())
        self._replay_reference_btn.clicked.connect(self._load_reference_background)
        self._replay_reference_btn.hide()
        replay_c.addWidget(self._replay_reference_btn)
        t.addWidget(replay_card)

        t.addStretch()

    def _populate_optional_tab(self) -> None:
        """Read current Artisan state to initialise optional-settings widgets."""

        # Roast profiles from bean's roast plan
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItem(QApplication.translate("tilauscope_roast_setup", "— No profile —"), userData=None)
        try:
            for p in reversed(AGTRON_SCALES):
                name  = getattr(p, 'name',  None) or str(p)
                color_range = getattr(p, 'agtron_range', None)
                color = getattr(p, 'color_map', None)
                description = getattr(p, 'description', None)
                label = f"{name} - {description}"
                self._profile_combo.addItem(label, userData={'profile': p, 'description': description, 'color_range': color_range, 'color': color})
        except Exception as exc:
            _log.debug("Could not load roast profiles: %s", exc)
        self._profile_combo.blockSignals(False)

        # Restore last selection
        settings = QSettings()
        last_idx = settings.value("RoastSetup/LastProfileIndex", 0, type=int)
        if 0 <= last_idx < self._profile_combo.count():
            self._profile_combo.setCurrentIndex(last_idx)

        # TilauPID – detect existing START IOCommand
        pid_active = False
        pid_value  = ""
        try:
            actions = self._aw.qmc.xextrabuttonactions
            strings = self._aw.qmc.xextrabuttonactionstrings
            if len(actions) > 1 and actions[1] == 5:
                cmd = strings[1] if len(strings) > 1 else ""
                if cmd.lower().startswith("tilaupid(start,"):
                    pid_active = True
                    try:
                        pid_value = cmd.split(",", 1)[1].rstrip(")").strip()
                    except IndexError:
                        pass
        except Exception as exc:
            _log.debug("Could not read PID state: %s", exc)

        self._pid_enable_cb.setChecked(pid_active)
        self._pid_value_edit.setText(pid_value)
        self._pid_value_edit.setEnabled(pid_active)
        # The reloaded value belongs to the previous roast (another coffee, another
        # weight): the plan owns the field until the operator types in it.
        self._pid_charge_temp_user_set = False
        self._refresh_pid_recommendation()
        # Preselect PID input source from Artisan (pidSource: 2 = ET, else BT) + sync enabled state
        self._pid_input_bt_btn.setEnabled(pid_active)
        self._pid_input_et_btn.setEnabled(pid_active)
        try:
            is_et = self._aw.pidcontrol.pidSource == 2 and et_available_for(self._aw)
        except Exception:  # pylint: disable=broad-except
            is_et = False
        (self._pid_input_et_btn if is_et else self._pid_input_bt_btn).setChecked(True)

        # Automation flags
        try:
            qmc = self._aw.qmc
            self._auto_charge_cb.setChecked(bool(qmc.autoChargeFlag))
            self._auto_drop_cb.setChecked(bool(qmc.autoDropFlag))
            self._auto_dry_end_cb.setChecked(bool(getattr(self._aw, "TilauScopeDEMarkFlag", False)))
            self._auto_fc_cb.setChecked(bool(getattr(self._aw, "TilauScopeFCMarkFlag", False)))
        except Exception as exc:
            _log.debug("Could not read auto flags: %s", exc)

        # Roast Replay — only meaningful if this roaster supports it AND a
        # background curve is loaded.
        try:
            self._replay_enable_cb.setChecked(False)
            self._replay_loaded_reference = ""
            self._refresh_replay_card()
        except Exception as exc:
            _log.debug("Could not initialise Roast Replay controls: %s", exc)

    def _refresh_replay_card(self) -> None:
        """Whether replay is available, why not, and — for an Expert — the reference to load."""
        supports_replay = bool(getattr(self._roaster_ctx, "supports_profile_replay", False))
        has_background = self._aw.qmc.backgroundprofile is not None
        available = supports_replay and has_background
        self._replay_enable_cb.setEnabled(available)
        if not supports_replay:
            _replay_status = QApplication.translate(
                "tilauscope_roast_setup", "Not supported by this roaster")
        elif not has_background:
            _replay_status = QApplication.translate(
                "tilauscope_roast_setup", "Load a background curve first (Roast > Background)")
        else:
            _replay_status = ""
        _replay_tip = (_replay_status if _replay_status else QApplication.translate(
            "tilauscope_roast_setup",
            "Replays the loaded background curve during this roast — disables Guided."))
        self._replay_enable_cb.setToolTip(_replay_tip)
        reference = (self._reference_record()
                     if supports_replay and not has_background and operator_level(self._aw) == "expert"
                     else None)
        if reference is not None:
            self._replay_reference_btn.setText(
                "★  " + QApplication.translate("tilauscope_roast_setup", "Load {0}").format(
                    self._record_name(reference)))
        self._replay_reference_btn.setVisible(reference is not None)
        self._replay_status_lbl.setText(_replay_status)
        self._replay_status_lbl.setVisible(not available and reference is None)
        self._replay_reference_chip.setText("★  " + self._replay_loaded_reference)
        self._replay_reference_chip.setVisible(available and bool(self._replay_loaded_reference))

    def _reference_record(self):  # noqa: ANN202
        """The roast index record of this coffee's reference roast while it is tasted Yes, else None."""
        from pathlib import Path  # noqa: PLC0415
        ref = str(getattr(self._bean, "reference_roast_uuid", "") or "")
        cache = getattr(self._parent_widget, "_metadata_cache", None)
        if not ref or cache is None:
            return None
        record = next((m for m in cache.records.values() if m.roast_uuid == ref), None)
        if (record is None or record.exclude_learning or record.simulated
                or not Path(record.filepath_str).exists()):
            return None
        from tilauscope import tasting_log  # noqa: PLC0415
        tasting = tasting_log.load(QSettings().value('beancaveDirectory', '', str)).entries.get(ref)
        return record if tasting is not None and tasting.verdict == "yes" else None

    @staticmethod
    def _record_name(record) -> str:  # noqa: ANN001
        from tilauscope.beancave_catalogue import roast_name  # noqa: PLC0415
        return roast_name(int(record.roastepoch or record.mtime), roast_batch_tag(record.batch_prefix, record.batch_nr))

    @pyqtSlot()
    def _load_reference_background(self) -> None:
        """The Expert's explicit ask: the reference roast becomes the background curve."""
        # Reached from a click slot: an escape here would close the application.
        try:
            record = self._reference_record()
            if record is None:
                return
            self._aw.loadAndRedrawBackgroundUUID(record.filepath_str)
            if self._aw.qmc.backgroundprofile is None:
                # Artisan refused it (Designer mode, unreadable file…): say so, or the click looks ignored.
                show_styled_message(
                    self, QApplication.translate("tilauscope_roast_setup", "Roast Replay"),
                    QApplication.translate("tilauscope_roast_setup",
                                           "The reference roast could not be loaded as the background curve."),
                    QMessageBox.Icon.Warning)
                return
            self._replay_loaded_reference = self._record_name(record)
            self._refresh_replay_card()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            _log.exception("the reference roast could not be loaded as background")

    @pyqtSlot(int)
    def _on_profile_changed(self, index: int) -> None:
        data = self._profile_combo.itemData(index)
        if data and data.get('color'):
            color_str = data['color']
            self._profile_color_dot.setStyleSheet(
                f"color: {color_str}; font-size: 20px; margin-left: 6px; border: none;"
            )
            self._profile_color_dot.setVisible(True)
        else:
            self._profile_color_dot.setVisible(False)

    # ── showEvent – position scale window and mouse mmove────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        QTimer.singleShot(100, self._show_scale_window)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            new_pos = self.pos() + delta
            self.move(new_pos)

            # Compute helper positions from new_pos + known dialog size —
            # never read self.geometry() back after move() to avoid a recursive
            # moveEvent feedback loop that freezes the UI on some platforms.
            helper_x = new_pos.x() + self.width() + 12
            helper_y = new_pos.y() + 40

            if self._scale_window and self._scale_window.isVisible():
                self._scale_window.move(helper_x, helper_y)
                helper_y = self._scale_window.y() + self._scale_window.height() + 8

            room = self._room_window()
            if room is not None and room.isVisible():
                room.move(helper_x, helper_y)

            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    # ── OK / Cancel ──────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_ok(self) -> None:
        # Roast Replay needs the loaded background curve to survive into the
        # live roast — read the checkbox before reset() clears anything.
        replay_wanted = self._replay_enable_cb.isEnabled() and self._replay_enable_cb.isChecked()

        # Reset Artisan first. False means the save prompt for the roast on
        # screen was cancelled: that roast stays, and nothing is written over it.
        if not self._aw.qmc.reset():
            return
        if not replay_wanted:
            self._aw.clearBackgroundSignal.emit()

        # now store values
        title  = self._title_combo.currentText().strip()
        beans  = self._beans_field_edit.text().strip()

        # Weight
        try:
            green_weight = float(self._green_weight_edit.text().replace(',', '.'))
        except ValueError:
            green_weight = 0.0

        # Density
        try:
            density = float(self._density_edit.text().replace(',', '.'))
        except ValueError:
            density = 0.0

        # Moisture
        try:
            moisture = float(self._moisture_edit.text().replace(',', '.'))
        except ValueError:
            moisture = 0.0

        # Bean temp
        try:
            bean_temp = float(self._bean_temp_edit.text().replace(',', '.'))
        except ValueError:
            bean_temp = 0.0

        # ── Inject into Artisan qmc ────────────────────────────────────────
        try:
            qmc = self._aw.qmc

            # Title
            qmc.title            = title
            qmc.title_show_always = True
            qmc.autosaveprefix = _default_autosave_prefix(qmc)

            # Beans text
            qmc.beans            = beans
            # stash on aw so reset() (ON/RESET) can't lose them;
            # restored at DROP in displayscope._open_roast_result_dialog.
            self._aw._tilau_live_title = title
            self._aw._tilau_live_beans = beans
            # stash la CIBLE live (profil OPTIONS) pour que le combo cible
            ## de l'assistant se cale dessus, au lieu de rester collé sur une
            ## valeur périmée / du background (bug : Light devenait Medium Dark).
            try:
                _pd = self._profile_combo.itemData(self._profile_combo.currentIndex())
                self._aw._tilau_live_target = _pd.get('profile') if isinstance(_pd, dict) else None
            except Exception:  # noqa: BLE001
                self._aw._tilau_live_target = None

            # update display of text
            self._aw.qmc.setProfileTitle(title)
            if self._aw.qmc.background and self._aw.qmc.title != '':
                if self._aw.qmc.roastbatchnrB == 0:
                    titleB = self._aw.qmc.titleB
                else:
                    titleB = self._aw.qmc.roastbatchprefixB + str(self._aw.qmc.roastbatchnrB) + ' ' + self._aw.qmc.titleB
                self._aw.qmc.setProfileBackgroundTitle(titleB)
            self._aw.qmc.fig.canvas.draw()

            # Green weight  (weight = (in_g, out_g, unit_str))
            w2 = qmc.weight[2] if qmc.weight[2] else 'g'
            from artisanlib.util import convertWeight, weight_units  # type: ignore[attr-defined]
            try:
                unit_idx = weight_units.index(w2)
                w0 = convertWeight(green_weight, 0, unit_idx)  # g → target unit
            except Exception:  # noqa: BLE001
                w0 = green_weight
                w2 = 'g'
            qmc.weight           = (w0, 0.0, w2)

            # Density
            qmc.density          = (density, 'g', 1, 'l')

            # Moisture
            qmc.moisture_greens  = moisture

            # Screen size — always written, so a previous bean's size never carries over
            qmc.beansize_min, qmc.beansize_max = SCREEN_SIZE_RANGES.get(
                getattr(self._bean, 'screen_size', '') or '', (0, 0))

            # Bean temperature
            qmc.greens_temp      = bean_temp

            # Batch — write prefix and (de)activation only; never touch the counter value
            try:
                self._batch_block.apply_to_qmc()
            except Exception as exc:  # noqa: BLE001
                _log.warning("RoastSetupDialog: batch apply failed: %s", exc)

            # if ambient values are detectable and window exists
            room = self._room_window()
            # A remembered probe reading is not this roast's ambient: it is not recorded.
            if room is not None and not getattr(room, "_showing_last", False):
                if room.humidity is not None:
                    qmc.ambient_humidity = room.humidity
                if room.pressure is not None:
                    qmc.ambient_pressure = room.pressure
                if room.temperature is not None:
                    qmc.ambientTemp = room.temperature
            # The assistant plans on the room this sheet planned with, a remembered reading included.
            self._aw._tilau_planned_room = getattr(self, "_planned_ambient", None)

            # Trigger redraw / dirty flag if a profile is loaded
            if len(qmc.timex):
                qmc.fileDirty()

            _log.info(
                "RoastSetupDialog: injected title=%r beans=%r weight=%.1f density=%.1f moisture=%.1f",
                title, beans, green_weight, density, moisture,
            )
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to inject roast properties into Artisan: %s", exc)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_roast_setup", "Injection Error"),
                QApplication.translate("tilauscope_roast_setup", "Could not update Artisan properties:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True,
            )
            return

        # ── Optional settings ──────────────────────────────────────────────

        # Save profile combo selection
        settings = QSettings()
        settings.setValue("RoastSetup/LastProfileIndex", self._profile_combo.currentIndex())

        # TilauPID – set or clear the preheat IOCommand on the START button.
        # START maps to xextrabuttonactions[1] / xextrabuttonactionstrings[1]
        # (RESET is index 0). IO Command action type == 5.
        try:
            xactions = list(self._aw.qmc.xextrabuttonactions)
            xstrings = list(self._aw.qmc.xextrabuttonactionstrings)

            # Ensure lists are long enough (RESET=0, START=1)
            while len(xactions) < 2:
                xactions.append(0)
            while len(xstrings) < 2:
                xstrings.append("")

            # Migrate away the legacy mistake where the command was written to
            # the ON (extrabuttonactions[0]) or OFF (extrabuttonactions[1])
            # buttons — clear it if it holds a tilaupid command.
            try:
                eactions = list(self._aw.qmc.extrabuttonactions)
                estrings = list(self._aw.qmc.extrabuttonactionstrings)
                migrated = False
                for i in range(min(len(eactions), len(estrings))):
                    if estrings[i].lower().startswith("tilaupid(start,"):
                        eactions[i] = 0
                        estrings[i] = ""
                        migrated = True
                if migrated:
                    self._aw.qmc.extrabuttonactions       = eactions
                    self._aw.qmc.extrabuttonactionstrings = estrings
                    _log.info("RoastSetupDialog: cleared legacy TilauPID command on ON/OFF button")
            except Exception as exc:  # pylint: disable=broad-except
                _log.warning("Could not migrate legacy TilauPID command: %s", exc)

            raw = self._pid_value_edit.text().strip()
            self._insights_panel.ensure_plan()
            try:
                pid_val = float(raw.replace(',', '.'))
            except ValueError:
                pid_val = 0.0

            # The plan owns the charge setpoint only while the operator has not
            # claimed it. Overriding a typed value here discarded a deliberate
            # entry at the last moment, after the field had shown it all along.
            if self._pid_enable_cb.isChecked() and not self._pid_charge_temp_user_set:
                plan_charge_temp = self._insights_panel.charge_temperature()
                if plan_charge_temp is not None:
                    pid_val = plan_charge_temp
                    self._pid_value_edit.setText(f"{pid_val:.0f}")

            if self._pid_enable_cb.isChecked() and pid_val > 0.0:
                # Case cochée ET SV donné → on remplit le START.
                # SV envoyée en ENTIER : régler un préchauffage au dixième de degré
                # n'a aucun sens, et le récepteur (float(value)/setSV(int(sv))) l'accepte.
                pid_sv = int(round(pid_val))
                xactions[1] = 5  # IO Command
                xstrings[1] = f"tilaupid(START,{pid_sv})"
                _log.info("RoastSetupDialog: TilauPID START command set → %s", xstrings[1])
                # Point Artisan's PID input source at the chosen channel (1 = BT, 2 = ET),
                # mirroring how SV is pushed through pidcontrol. The preheat PID reads
                # pidcontrol.pidSource every cycle (st2 if pidSource in [0,1] else st1).
                try:
                    self._aw.pidcontrol.pidSource = 2 if self._pid_input_et_btn.isChecked() else 1
                    self._aw.pidcontrol.setSV(pid_sv)
                    slider_sv = getattr(self._aw, "sliderSV", None)
                    if slider_sv is not None and slider_sv.value() != pid_sv:
                        slider_sv.blockSignals(True)
                        slider_sv.setValue(pid_sv)
                        slider_sv.blockSignals(False)
                    _log.info("RoastSetupDialog: PID input source → %s",
                              "ET" if self._pid_input_et_btn.isChecked() else "BT")
                except Exception as exc:  # pylint: disable=broad-except
                    _log.warning("Could not set PID input source: %s", exc)
            else:
                # Sinon (décochée, ou cochée sans SV) → on ne remplit pas : vider tout
                # tilaupid start résiduel pour ne pas lancer le PID.
                if xstrings[1].lower().startswith("tilaupid(start,"):
                    xactions[1] = 0
                    xstrings[1] = ""
                    _log.info("RoastSetupDialog: TilauPID START command cleared")

            self._aw.qmc.xextrabuttonactions       = xactions
            self._aw.qmc.xextrabuttonactionstrings = xstrings
        except Exception as exc:
            _log.warning("Could not set TilauPID command: %s", exc)

        # Automation flags. Own block: indented into the handler above, they only
        # ever ran when setting the preheat command had failed, so a checkbox
        # changed on the normal path kept its previous setting.
        self._aw.qmc.autoChargeFlag = self._auto_charge_cb.isChecked()
        self._aw.qmc.autoDropFlag   = self._auto_drop_cb.isChecked()

        # Auto Dry End requires a configured Dry-phase BT target (phases[1]);
        # without it the detector cannot fire, so the flag is not activated.
        de_checked = self._auto_dry_end_cb.isChecked()
        if de_checked:
            try:
                de_target = float(self._aw.qmc.phases[1])
            except (IndexError, TypeError, ValueError):
                de_target = 0.0
            if de_target <= 0.0:
                show_styled_message(
                    self,
                    QApplication.translate("tilauscope_roast_setup", "Auto Dry End"),
                    QApplication.translate("tilauscope_roast_setup", "Set a Dry-phase BT target in Artisan Phases first.<br>Auto Dry End was left disabled."),
                    QMessageBox.Icon.Information, rich=True,
                )
                de_checked = False
                self._auto_dry_end_cb.setChecked(False)
        self._aw.TilauScopeDEMarkFlag = de_checked
        self._aw.TilauScopeFCMarkFlag = self._auto_fc_cb.isChecked()

        # Expert: the plan's alarms replace the operator's own — written only now
        # that the roast is confirmed, never while the plan is merely looked at.
        if self._insights_panel.load_alarms_requested():
            try:
                alarms_path = self._insights_panel.write_plan_alarms()
                if alarms_path:
                    self._aw.loadAlarms(alarms_path)
            except Exception as exc:  # noqa: BLE001
                _log.warning("RoastSetupDialog: plan alarms not loaded: %s", exc)

        # Roast profile – reserved for next version (phase injection)
        # selected_data = self._profile_combo.currentData()
        # if selected_data:  # TODO: inject phases in next version

        # ── Decrease stock ─────────────────────────────────────────────────
        if self._decrease_stock_cb.isChecked() and green_weight > 0 and self._bean.uuid:
            try:
                self._decrease_bean_stock(green_weight)
                _log.info(
                    "RoastSetupDialog: stock decreased by %.1f g for %s",
                    green_weight, self._bean.name,
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("Could not decrease stock: %s", exc)

        self._close_helpers()
        lets_start_a_new_roast_message = QApplication.translate(
            "tilauscope_roast_setup",
            "Your '%s' green bean is ready for a new roast. Switch Tilauscope monitor ON, then press on START when you are ready to begin the magic!"
        ) % self._bean.name
        if self._aw.tilauscope_main is None:
            # open tilauscope to be ready to roast if it was not opened.
            # Do NOT pass the message here: TilauScope would show it via
            # showMessage() AND we already show it once via show_styled_message()
            # below — that produced two identical message boxes.
            self._aw.tilauscopeCall(False)
        # Roast Replay: arm now (locks Expert) so the launch_guided_assistant()
        # call right below becomes a no-op — a replay session has no plan to guide.
        if replay_wanted and self._aw.tilauscope_main is not None:
            self._aw.tilauscope_main.arm_roast_replay(_replay_reaction_time_s(self._roaster_ctx))
        # Workflow guidé : ancre et démarre l'assistant automatiquement.
        # QTimer(0) diffère au prochain tick pour laisser Qt traiter show/raise.
        _aw = self._aw
        QTimer.singleShot(0, lambda: _aw.tilauscope_main and _aw.tilauscope_main.launch_guided_assistant())
        # headless: BeanCave is the persistent home shell — hide it (keep
        # the single instance and its threads alive) instead of closing/destroying.
        if getattr(self._aw, '_tilau_headless', False):
            self._parent_widget.hide()
        else:
            self._parent_widget.close()
        self.accept()
        # Owned by the main window, not by this dialog: the dialog has just
        # closed, and the invitation has to outlive it.
        call_later(self._aw, 500, lambda: show_styled_message(
            parent=self._aw.tilauscope_main,
            title=QApplication.translate("tilauscope_roast_setup", "Start a new roast"),
            text=lets_start_a_new_roast_message,
            icon=QMessageBox.Icon.Information, rich=False
        ))

    @pyqtSlot()
    def _on_cancel(self) -> None:
        self._close_helpers()
        self._start_fade_out()

    def _decrease_bean_stock(self, green_weight: float) -> None:
        """Take the roast's green weight off the stored record's stock, and nothing else.

        Saving the BeanCave form back instead rewrote every field the form
        cannot show (free-text variety, density above its range).
        """
        host = self._parent_widget
        bean = getattr(host, 'uuidmap', {}).get(self._bean.uuid)
        if bean is None:
            return
        previous = float(bean.weight_left or 0.0)
        bean.weight_left = max(0.0, previous - green_weight)
        if not host.save_green_beans():
            bean.weight_left = previous   # the file still holds it; the operator was told why
            return
        prompt_release_if_emptied(host, bean, previous, host.save_green_beans)
        host.populate_table()   # reselects the row, so the form reloads the new stock

    def _close_helpers(self) -> None:
        # unwire first — the scale manager outlives this dialog.
        self._disconnect_scale()
        if self._scale_window is not None:
            self._scale_window.close()
            self._scale_window = None
        if self._ambient_window is not None:
            self._ambient_window.close()
            self._ambient_window = None
        if self._weather_window is not None:
            self._weather_window.close()
            self._weather_window = None
        panel = getattr(self, "_insights_panel", None)
        if panel is not None:
            panel.shutdown()

    def _start_fade_out(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(300)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.reject)
        self._fade.start()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._close_helpers()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            # ESC on a non-modal QDialog calls reject() → hide() without closeEvent.
            # Force close() to trigger closeEvent and the full cleanup
            # (otherwise _scale_window/_ambient_window stay visible as orphan windows).
            self.close()
        else:
            super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience factory kept for backward compatibility with BeanCave
# ─────────────────────────────────────────────────────────────────────────────

class RoastProperties(RoastSetupDialog):
    """Thin compat alias for RoastSetupDialog."""

    def __init__(self, bean: GreenBean, parent, aw: 'ApplicationWindow' = None) -> None:
        super().__init__(bean, parent)


# ─────────────────────────────────────────────────────────────────────────────
# Inline SVG icons for RoastResultDialog
# ─────────────────────────────────────────────────────────────────────────────

_SVG_BEAN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<ellipse cx="12" cy="12" rx="9" ry="6" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<path d="M12 6 Q16 12 12 18" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
    '</svg>'
)

_SVG_DEFECT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<line x1="8" y1="8" x2="16" y2="16" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
    '<line x1="16" y1="8" x2="8" y2="16" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
    '</svg>'
)

_SVG_COLOR_LENS = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<circle cx="12" cy="12" r="5" fill="{color}" opacity="0.35"/>'
    '<circle cx="12" cy="12" r="2" fill="{color}"/>'
    '</svg>'
)

_SVG_SCALE_RESULT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<line x1="4" y1="6" x2="20" y2="6" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>'
    '<line x1="12" y1="6" x2="12" y2="10" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>'
    '<path d="M6 10 Q6 16 12 16 Q18 16 18 10 Z" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<line x1="8" y1="19" x2="16" y2="19" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>'
    '<line x1="12" y1="16" x2="12" y2="19" stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
    '</svg>'
)


_SVG_CLOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="9" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<line x1="12" y1="7" x2="12" y2="12" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
    '<line x1="12" y1="12" x2="16" y2="14" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>'
    '<circle cx="12" cy="12" r="1.2" fill="{color}"/>'
    '</svg>'
)

_SVG_THERMOMETER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<rect x="10" y="3" width="4" height="12" rx="2" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<circle cx="12" cy="17" r="4" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<line x1="12" y1="9" x2="12" y2="15" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
    '</svg>'
)

_SVG_DEVELOPMENT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<polyline points="3,18 8,10 13,14 20,5" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="20" cy="5" r="2" fill="{color}"/>'
    '</svg>'
)


# Tipping: both ends of the bean burnt. Scorching: burnt patches on its face.
_SVG_TIPPING = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<ellipse cx="12" cy="12" rx="9" ry="6" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<path d="M12 6 Q16 12 12 18" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
    '<path d="M7 17 C1.67 14.61 1.67 9.39 7 7 Z" fill="{color}"/>'
    '<path d="M17 17 C22.33 14.61 22.33 9.39 17 7 Z" fill="{color}"/>'
    '</svg>'
)

_SVG_SCORCHING = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<ellipse cx="12" cy="12" rx="9" ry="6" fill="none" stroke="{color}" stroke-width="1.8"/>'
    '<path d="M12 6 Q16 12 12 18" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
    '<path d="M6.2 10.2 Q7.8 8 10 9.4 Q11.2 11.8 9.6 14 Q7.4 15.2 6.3 13.2 Q5.4 11.6 6.2 10.2 Z" fill="{color}"/>'
    '<circle cx="16.6" cy="11" r="1.3" fill="{color}"/>'
    '</svg>'
)


def _svg_icon_label(svg_template: str, color: str, size: int = 22) -> QLabel:
    """Return a QLabel bearing a rendered SVG icon."""
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(_svg_pixmap(svg_template, color, size))
    lbl.setStyleSheet("background: transparent; border: none;")
    return lbl


def _defect_mark_chip(svg_template: str, text: str, tooltip: str, marked: bool) -> QPushButton:
    """Checkable chip marking a defect seen on the roasted beans; lit with ✓ when marked."""
    chip = QPushButton()
    chip.setCheckable(True)
    chip.setCursor(Qt.CursorShape.PointingHandCursor)
    chip.setToolTip(tooltip)
    icon = QIcon()
    for color, state in ((THEME['SUBTEXT'], QIcon.State.Off), (THEME['WARNING'], QIcon.State.On)):
        pix = _svg_pixmap(svg_template, color, 32)
        pix.setDevicePixelRatio(2.0)
        icon.addPixmap(pix, QIcon.Mode.Normal, state)
    chip.setIcon(icon)
    chip.setIconSize(QSize(16, 16))
    chip.setStyleSheet(
        f"QPushButton {{ color: {THEME['SUBTEXT']}; background: transparent;"
        f"border: 1px solid {THEME['BORDER']}; border-radius: 13px;"
        f"padding: 4px 12px; font-size: 12px; }}"
        f"QPushButton:hover {{ background: {THEME['BORDER']}; }}"
        f"QPushButton:checked {{ color: {THEME['WARNING']};"
        f"background: {tint('WARNING', 0.15)}; border-color: {THEME['WARNING']}; }}"
        f"QPushButton:checked:hover {{ background: {tint('WARNING', 0.25)}; }}"
    )
    marked_text = f"{text}  ✓"
    # Reserve the marked width so marking one chip never shifts its neighbour.
    chip.setText(marked_text)
    chip.ensurePolished()
    chip.setMinimumWidth(chip.sizeHint().width())
    chip.setText(marked_text if marked else text)
    chip.setChecked(marked)
    chip.toggled.connect(lambda on: chip.setText(marked_text if on else text))
    return chip


# ─────────────────────────────────────────────────────────────────────────────
# _ColorFloatWindow – floating colour meter card for RoastResultDialog
# ─────────────────────────────────────────────────────────────────────────────

class _ColorFloatWindow(QDialog):
    """
    Small always-on-top card that shows the live Agtron reading from the
    paired colour meter.

    When the user clicks the live value the parent dialog fills the whole or
    ground field: the one the meter names, else the one picked in a small popup.

    The colour meter is created here and torn down on close, mirroring
    how _AmbientFloatWindow manages TilauAmbient.
    """

    CARD_WIDTH: Final[int] = 150

    def __init__(self, parent: 'RoastResultDialog') -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        apply_tilau_theme(self, ground=False)  # frameless translucent: no ground rule
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._parent_dialog = parent
        self._aw            = parent._aw
        self._color_value: float | None = None
        self._color_basis: str | None = None   # 'whole' / 'ground' when the meter tells, else None
        self._device: object | None = None   # ColorMeter of the configured model

        self._build_ui()
        self._attach_device()

    # ── Device wiring ─────────────────────────────────────────────────────────

    def _attach_device(self) -> None:
        """Create the configured colour meter, if any."""
        device_name = getattr(self._aw, 'bleRoastSeeDeviceName', None) or ""
        if not device_name:
            self._set_status(
                QApplication.translate("tilauscope_roast_setup", "no device configured"),
                THEME['SUBTEXT'],
            )
            return
        try:
            from tilauscope.colormeters import configured_model_key, create_color_meter
            model_key = configured_model_key()
            self._device = create_color_meter(model_key, device_name)
            if self._device is None:
                raise RuntimeError(f"unknown colour meter model {model_key}")
            self._device.connected_signal.connect(self._on_connected)
            self._device.disconnected_signal.connect(self._on_disconnected)
            self._device.reading_signal.connect(self._on_reading)
            _logd.debug("ColorCard: attached to %s device %s", model_key, device_name)
        except Exception as exc:
            _log.warning("ColorCard: could not attach colour meter: %s", exc)
            self._set_status(
                QApplication.translate("tilauscope_roast_setup", "device error"),
                THEME['WARNING'],
            )

    def _detach_device(self) -> None:
        if self._device is None:
            return
        try:
            self._device.reading_signal.disconnect(self._on_reading)
            self._device.connected_signal.disconnect(self._on_connected)
            self._device.disconnected_signal.disconnect(self._on_disconnected)
            self._device.stop()
        except Exception:  # noqa: BLE001
            pass
        self._device = None

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("colorCard")
        self._card.setFixedWidth(self.CARD_WIDTH)
        self._card.setStyleSheet(f"""
            QFrame#colorCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 16px;
            }}
        """)
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)

        header = QLabel(QApplication.translate("tilauscope_roast_setup", "◉  COLOR"))
        header.setProperty('variant', 'eyebrow')
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(header)

        # Live colour swatch bar
        self._swatch = QFrame()
        self._swatch.setFixedHeight(8)
        self._swatch.setStyleSheet(f"background: {THEME['BORDER']}; border-radius: 4px;")
        cl.addWidget(self._swatch)

        self._color_lbl = QLabel("–– ")
        self._color_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._color_lbl.setProperty('variant', 'readout')
        self._color_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']};")
        self._color_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_lbl.setToolTip(
            QApplication.translate("tilauscope_roast_setup", "Click to assign this reading")
        )
        self._color_lbl.mousePressEvent = self._on_value_clicked  # type: ignore[method-assign]
        cl.addWidget(self._color_lbl)

        tap_hint = QLabel(QApplication.translate("tilauscope_roast_setup", "tap to capture"))
        tap_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_hint.setProperty('variant', 'caption')
        cl.addWidget(tap_hint)

        self._status_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "connecting…"))
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setProperty('variant', 'caption')
        cl.addWidget(self._status_lbl)

        outer.addWidget(self._card)
        self.adjustSize()

    # ── Slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_connected(self) -> None:
        self._card.setStyleSheet(f"""
            QFrame#colorCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['ACCENT']};
                border-radius: 16px;
            }}
        """)
        self._set_status(
            QApplication.translate("tilauscope_roast_setup", "live"),
            THEME['SUCCESS'],
        )

    @pyqtSlot()
    def _on_disconnected(self) -> None:
        self._card.setStyleSheet(f"""
            QFrame#colorCard {{
                background-color: {THEME['SURFACE']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 16px;
            }}
        """)
        self._color_lbl.setText("––")
        self._color_lbl.setProperty('variant', 'readout')
        self._color_lbl.setStyleSheet(f"color: {THEME['SUBTEXT']};")
        self._swatch.setStyleSheet(f"background: {THEME['BORDER']}; border-radius: 4px;")
        self._set_status(
            QApplication.translate("tilauscope_roast_setup", "offline"),
            THEME['SUBTEXT'],
        )

    @pyqtSlot(object)
    def _on_reading(self, reading) -> None:  # noqa: ANN001
        self._color_basis = reading.basis
        self._on_color_changed(reading.value)

    def _on_color_changed(self, value: float) -> None:
        self._color_value = value
        # Colour the number to reflect Agtron range
        hue_color = self._agtron_hue(value)
        self._color_lbl.setText(f"{value:.1f}")
        self._color_lbl.setProperty('variant', 'readout')
        self._color_lbl.setStyleSheet(f"color: {hue_color};")
        self._swatch.setStyleSheet(
            f"background: {hue_color}; border-radius: 4px;"
        )

    def _on_value_clicked(self, _event) -> None:  # noqa: ANN001
        if self._color_value is None:
            return
        self._parent_dialog.receive_color_reading(self._color_value, self._color_basis)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _agtron_hue(agtron: float) -> str:
        """The colour of that Agtron number, from the application's roast scale."""
        return get_agtron_color(agtron)

    def _set_status(self, text: str, color: str) -> None:
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 9px; "
        )

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._detach_device()
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# RoastResultDialog – post-roast recording
# ─────────────────────────────────────────────────────────────────────────────

class RoastResultDialog(QDialog):
    """
    Post-roast dialog – records roasted weight, defects, colour (Agtron),
    and roasting notes.  Supports live scale readout and optional colour
    meter, both as floating helper windows that move with the dialog.
    """

    def __init__(
        self,
        bean: GreenBean | None,
        aw: ApplicationWindow,
        green_weight: float = 0.0,
        *,
        bean_description: str | None = None,
    ) -> None:
        super().__init__(parent=None)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._bean         = bean
        self._aw           = aw
        self._green_weight = green_weight
        # A review passes the beans field frozen with the displayed roast.
        # None means the normal live path and therefore reads qmc.beans.
        self._bean_description = bean_description
        # bean may arrive None (DROP path) or empty (no BeanCave row): resolve
        # from the frozen/live description, uuid first and text as a net.
        if self._bean is None or not getattr(self._bean, 'name', ''):
            resolved = self._resolve_bean()
            if resolved is not None:
                self._bean = resolved
        if self._bean is None:
            self._bean = GreenBean()

        # helper windows
        self._scale_window: _ScaleFloatWindow | None = None
        self._color_window: _ColorFloatWindow | None = None
        self._cleaned = False  # done() has unwired the form

        self._drag_pos: object = None
        # drives the "print the label before closing?" reminder on save
        self._label_printed = False

        self.setStyleSheet(base_qss(ground=False) + _local_style())
        self._connect_scale()
        self._build_ui()
        # Frameless modal: clamp to the screen or the footer becomes unreachable.
        self.setMinimumWidth(920)
        # Push the body's own minimum width through the scroll area, which does
        # not propagate it: without this the window can be narrower than what it
        # holds, and the content is cut rather than the window widened.
        self._body_scroll.setMinimumWidth(self._body.minimumSizeHint().width())
        avail = self.screen().availableGeometry()
        max_h = avail.height() - 40
        self.setMaximumHeight(max_h)
        # Height of the body plus the chrome around it, not the scroll area's
        # own hint, which is a fixed default and would open the window short.
        chrome = self.sizeHint().height() - self._body_scroll.sizeHint().height()
        wanted = chrome + self._body.sizeHint().height()
        self.resize(min(940, avail.width() - 40), min(wanted, max_h))

        # AI floating panel – optional, only when AI is fully configured.
        # All access is guarded: ai_service, tilau_aiConfig and is_configured may not
        # exist if the user has not yet deployed all new modules.
        self._ai_panel: AIFloatPanel | None = None
        try:
            ai_svc = getattr(self._aw, "tilau_ai_service", None)
            ai_cfg = getattr(self._aw, "tilau_aiConfig", None)
            configured = getattr(ai_cfg, "is_configured", False) if ai_cfg else False
            if _AI_AVAILABLE and ai_svc is not None and configured:
                self._ai_panel = AIFloatPanel(
                    task_type  = AITask.ROAST_SUMMARY,
                    ai_service = ai_svc,
                    title      = QApplication.translate("tilauscope_roast_setup", "Roast Summary"),
                    owner      = self,
                    aw         = self._aw,
                )
                self._ai_panel.set_payload_fn(self._build_roast_summary_payload)
        except Exception as exc:  # noqa: BLE001
            _log.warning("RoastResultDialog: AI panel init failed: %s", exc)
            self._ai_panel = None

    def _resolve_bean(self) -> 'GreenBean | None':
        """Resolve the roasted bean when the caller could not supply one.

        Priority 1: uuid embedded in the reviewed/live roast description →
        BeanCave uuidmap (full bean). Priority 2 (net): parse that description
        into a minimal GreenBean. Returns None if it is empty/unusable.
        """
        if self._bean_description is None:
            try:
                beans_txt = (getattr(self._aw.qmc, 'beans', '') or '').strip()
            except Exception:  # noqa: BLE001
                beans_txt = ''
        else:
            beans_txt = str(self._bean_description or '').strip()
        if not beans_txt:
            return None

        # Priority 1 — uuid lookup against the loaded cave
        uuid = ''
        m = re.search(r'uuid:\s*([a-fA-F0-9-]{36})', beans_txt)
        if m:
            uuid = m.group(1)
            try:
                bc = getattr(self._aw, 'beancaveWindow', None)
                uuidmap = getattr(bc, 'uuidmap', None) if bc is not None else None
                if uuidmap:
                    hit = uuidmap.get(uuid)
                    if hit is not None:
                        return hit
            except Exception as exc:  # noqa: BLE001
                _log.warning("RoastResultDialog: uuid lookup failed: %s", exc)

        # Priority 2 (net) — best-effort parse of the free-text beans field
        try:
            lines = [ln.strip() for ln in beans_txt.splitlines() if ln.strip()]
            name = lines[0] if lines else ''
            country = process = varieties = ''
            for ln in lines[1:]:
                low = ln.lower()
                if low.startswith('uuid:') or low.startswith('farm:') or low.startswith('altitude:'):
                    continue
                if low.startswith('process'):
                    parts = ln.split(None, 1)
                    process = parts[1].strip() if len(parts) > 1 else ''
                elif low.startswith('variety') or low.startswith('varieties'):
                    parts = ln.split(None, 1)
                    varieties = parts[1].strip() if len(parts) > 1 else ''
                elif not country:
                    country = ln  # first plain line after name ≈ origin
            if name:
                return GreenBean(name=name, country=country, process=process,
                                 varieties=varieties, uuid=uuid)
        except Exception as exc:  # noqa: BLE001
            _log.warning("RoastResultDialog: beans text parse failed: %s", exc)
        return None

    def _green_grams(self) -> float:
        """Green weight in grams: the profile's own, else the one handed in.

        qmc.weight is in the profile's unit, and not every caller converts it.
        """
        try:
            green = _to_grams(self._aw.qmc.weight[0], self._aw.qmc.weight[2])
        except (AttributeError, IndexError, TypeError):
            green = 0.0
        return green if green > 0 else float(self._green_weight or 0.0)

    # An Acaia left alone for the length of a roast drops its BLE link
    # (or goes to sleep). A single connect request at dialog open then silently
    # failed and the card stayed on "–– g" forever. We now report the state and
    # keep retrying for a while, and the card is clickable to force a retry.
    _SCALE_RETRY_MS:      Final[int] = 6_000
    _SCALE_RETRY_MAX:     Final[int] = 10

    def _connect_scale(self) -> None:
        self._scale_was_connected = False
        self._scale_retries = 0
        self._scale_retry_timer: QTimer | None = None
        try:
            sm = self._aw.scale_manager
            self._scale_was_connected = sm.is_scale1_connected()
            if sm.is_scale1_configured():
                self._scale_window = _ScaleFloatWindow(self)
                sm.scale1_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.connect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.connect(self._scale_window.scale_disconnected)
                sm.scale1_connected_signal.connect(self._on_scale_connected)
                if self._scale_was_connected:
                    last = sm.get_scale1_last_weight()
                    if last is not None:
                        self._scale_window.update_weight(last)
                else:
                    self.request_scale_connect()
        except Exception as exc:
            _log.warning("RoastResultDialog: scale not available: %s", exc)

    def request_scale_connect(self) -> None:
        """Ask the scale manager to (re)connect scale 1 and start the retry loop.

        Reached on opening with the scale down, and on a tap on a card that is
        showing no reading. A scale the manager still calls connected but that
        sends nothing is exactly what the operator is tapping about, so the link
        is recycled rather than the request refused.
        """
        if self._scale_window is None:
            return
        try:
            sm = self._aw.scale_manager
            if not sm.is_scale1_configured():
                return
            self._scale_retries = 0
            self._scale_window.scale_connecting()
            # The scale's BLE client refuses every start() while it still
            # believes it is running, and only a disconnect clears that. A link
            # the roast left half-open therefore swallowed every reconnect for
            # the rest of the session. Release it first: it is already down, so
            # nothing working is being cut. Both signals are queued, so the
            # release is processed before the connect.
            sm.disconnect_scale1_signal.emit()
            sm.connect_scale1_signal.emit(False)
            if self._scale_retry_timer is None:
                self._scale_retry_timer = QTimer(self)
                self._scale_retry_timer.setInterval(self._SCALE_RETRY_MS)
                self._scale_retry_timer.timeout.connect(self._retry_scale_connect)
            self._scale_retry_timer.start()
        except Exception as exc:  # noqa: BLE001
            _log.warning("RoastResultDialog: scale connect request failed: %s", exc)

    @pyqtSlot()
    def _retry_scale_connect(self) -> None:
        if self._scale_window is None:
            self._stop_scale_retry()
            return
        try:
            sm = self._aw.scale_manager
            if sm.is_scale1_connected():
                self._on_scale_connected()
                return
            self._scale_retries += 1
            if self._scale_retries > self._SCALE_RETRY_MAX:
                self._stop_scale_retry()
                self._scale_window.set_status(QApplication.translate(
                    "tilauscope_roast_setup", "no scale — tap to retry"))
                return
            sm.connect_scale1_signal.emit(False)
        except Exception as exc:  # noqa: BLE001
            _log.warning("RoastResultDialog: scale retry failed: %s", exc)
            self._stop_scale_retry()

    @pyqtSlot()
    def _on_scale_connected(self) -> None:
        self._stop_scale_retry()
        if self._scale_window is None:
            return
        self._scale_window.scale_ready()
        try:
            last = self._aw.scale_manager.get_scale1_last_weight()
            if last is not None:
                self._scale_window.update_weight(last)
        except Exception:  # noqa: BLE001
            pass

    def _stop_scale_retry(self) -> None:
        if self._scale_retry_timer is not None:
            self._scale_retry_timer.stop()

    def _disconnect_scale(self) -> None:
        self._stop_scale_retry()
        if self._scale_window is None:
            return
        try:
            sm = self._aw.scale_manager
            if sm.is_scale1_configured():
                sm.scale1_weight_changed_signal.disconnect(self._scale_window.update_weight)
                sm.scale1_stable_weight_changed_signal.disconnect(self._scale_window.update_weight)
                sm.scale1_disconnected_signal.disconnect(self._scale_window.scale_disconnected)
                try:
                    sm.scale1_connected_signal.disconnect(self._on_scale_connected)
                except Exception:  # noqa: BLE001
                    pass
                # the physical scale is deliberately left connected:
                # disconnecting it here is what made the next dialog blind.
        except Exception as exc:
            _log.warning("RoastResultDialog: scale disconnect error: %s", exc)

    @pyqtSlot(float)
    def receive_scale_weight(self, weight: float) -> None:
        """Called when user taps the floating scale value."""
        current = self._roasted_weight_edit.text().strip()
        if current in ('', '0', '0.0'):
            self._roasted_weight_edit.setText(f"{weight:.0f}")
            self._update_loss_label()
        else:
            reply = show_styled_message(
                self,
                QApplication.translate("tilauscope_roast_setup", "Replace Weight?"),
                QApplication.translate("tilauscope_roast_setup",
                    "Current weight is <b>{0} g</b>.<br>Replace with scale reading <b>{1} g</b>?").format(
                    current, f"{weight:.0f}"),
                QMessageBox.Icon.Question,
                rich=True,
                width=400,
            )
            if reply == QMessageBox.StandardButton.Ok:
                self._roasted_weight_edit.setText(f"{weight:.0f}")
                self._update_loss_label()

    def receive_color_reading(self, value: float, basis: str | None = None) -> None:
        """
        Called when the user taps the floating colour card.
        Populates the whole-bean or ground field: the one the meter names in
        *basis*, else the one picked in a small context dialog.
        """
        if basis in ("whole", "ground"):
            edit = self._colour_whole_edit if basis == "whole" else self._colour_ground_edit
            edit.setText(f"{value:.1f}")
            self._update_color_diff()
            return
        reply = show_styled_message(
            self,
            QApplication.translate("tilauscope_roast_setup", "Which sample?"),
            QApplication.translate("tilauscope_roast_setup",
                "Reading: <b>{0}</b><br><br>"
                "Is this a <b>Whole bean</b> or <b>Ground</b> measurement?"
            ).format(f"{value:.1f}"),
            QMessageBox.Icon.Question,
            rich=True,
            width=380,
            buttons=[
                QApplication.translate("tilauscope_common", "Whole bean"),
                QApplication.translate("Label", "Ground"),
                QApplication.translate("Button", "Cancel"),
            ],
        )
        # show_styled_message returns a StandardButton; map text via index
        # We rely on the button index: 0=Whole, 1=Ground, 2=Cancel
        # Since show_styled_message may return Ok/Cancel, we handle both styles
        if reply in (QMessageBox.StandardButton.Ok, 0):
            self._colour_whole_edit.setText(f"{value:.1f}")
            self._update_color_diff()
        elif reply in (QMessageBox.StandardButton.Save, 1):
            self._colour_ground_edit.setText(f"{value:.1f}")
            self._update_color_diff()

    # ── Drag support ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            new_pos = self.pos() + delta
            self.move(new_pos)
            self._drag_pos = event.globalPosition().toPoint()
            self._reposition_helpers(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _helper_x(self, base_pos, helper_w: int) -> int:
        """Dock x for the scale / colour cards: right of the dialog, left when
        the screen has no room. They are frameless and always-on-top, so a card
        pushed off-screen cannot be dragged back."""
        scr = self.screen().availableGeometry()
        right = base_pos.x() + self.width() + 12
        if right + helper_w <= scr.right():
            return right
        return max(scr.left(), base_pos.x() - helper_w - 12)

    def _reposition_helpers(self, base_pos=None) -> None:
        # Accept an explicit base_pos so we never read self.geometry() back
        # immediately after a move() call — that re-entrancy freezes the UI.
        if base_pos is None:
            base_pos = self.pos()
        y = base_pos.y() + 40
        if self._scale_window and self._scale_window.isVisible():
            self._scale_window.move(
                self._helper_x(base_pos, self._scale_window.width()), y)
            y = self._scale_window.y() + self._scale_window.height() + 8
        if self._color_window and self._color_window.isVisible():
            self._color_window.move(
                self._helper_x(base_pos, self._color_window.width()), y)
        # ai_panel is a top-level window — reposition() uses owner.mapToGlobal
        if self._ai_panel is not None and self._ai_panel.isVisible():
            self._ai_panel.reposition()

    def _show_helpers(self) -> None:
        base_pos = self.pos()
        y = self.y() + 40
        if self._scale_window is not None:
            self._scale_window.show()
            self._scale_window.adjustSize()
            self._scale_window.move(
                self._helper_x(base_pos, self._scale_window.width()), y)
            y += self._scale_window.height() + 8
        if self._color_window is not None:
            self._color_window.show()
            self._color_window.adjustSize()
            self._color_window.move(
                self._helper_x(base_pos, self._color_window.width()), y)

    def _close_helpers(self) -> None:
        # unwire before destroying the card, otherwise the scale
        # manager keeps emitting into a dead window for the whole session.
        self._disconnect_scale()
        if self._scale_window is not None:
            self._scale_window.close()
            self._scale_window = None
        if self._color_window is not None:
            self._color_window.close()
            self._color_window = None
        if self._ai_panel is not None:
            # Cancel any running AI job before closing the panel so the
            # worker QThread is stopped cleanly (avoids "Destroyed while
            # thread is still running" fatal Qt message).
            try:
                from tilauscope.ai_service import AITask  # noqa: PLC0415
                self._ai_panel._ai_service.cancel(AITask.ROAST_SUMMARY)
            except Exception:
                pass
            self._ai_panel.close()   # unwires signals via closeEvent
            self._ai_panel = None

    # ── showEvent ─────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        QTimer.singleShot(120, self._show_helpers)

    # ── Roast metrics (read-only, computed from loaded profile) ──────────────

    def _build_metrics_strip(self) -> QFrame:
        """
        Read-only strip showing the key numbers from the just-finished roast:
        total time, charge BT, drop BT, development time, and DTR%.

        All values come from qmc attributes on the already-loaded profile.
        Every field degrades gracefully to '––' if the data is absent or
        the profile has no timeindex yet (e.g. manual entry without recording).
        """
        qmc = self._aw.qmc

        def _fmt_time(seconds) -> str:
            try:
                s = int(round(float(seconds)))
                return f"{s // 60}:{s % 60:02d}"
            except (TypeError, ValueError):
                return "––"

        def _fmt_temp(val) -> str:
            try:
                v = float(val)
                if v <= 0:
                    return "––"
                unit = getattr(qmc, 'mode', 'C')
                return f"{v:.0f} °{unit}"
            except (TypeError, ValueError):
                return "––"

        def _fmt_dtr(dev_s, total_s) -> str:
            try:
                d, t = float(dev_s), float(total_s)
                if t <= 0:
                    return "––"
                return f"{d / t * 100:.1f} %"
            except (TypeError, ValueError):
                return "––"

        try:
            timeindex = qmc.timeindex          # [CHARGE, DRYe, FCs, FCe, SCs, SCe, DROP, +1]
            timex     = qmc.timex
            temp2     = qmc.temp2              # BT array
            stats     = qmc.statisticstimes    # [0, drying, maillard, finish, 0, ...]

            charge_i = timeindex[0] if milestone_marked(timeindex, 0) else -1
            fc_i     = timeindex[2] if milestone_marked(timeindex, 2) else -1
            drop_i   = timeindex[6] if milestone_marked(timeindex, 6) else -1

            total_s      = (timex[drop_i] - timex[charge_i]) if (charge_i >= 0 and drop_i >= 0) else None
            charge_bt    = temp2[charge_i] if charge_i >= 0 and charge_i < len(temp2) else None
            drop_bt      = temp2[drop_i]   if drop_i   >= 0 and drop_i   < len(temp2) else None

            dev_s        = stats[3] if stats and len(stats) > 3 and stats[3] > 0 else None
            total_s_stat = sum(stats[1:4]) if stats and len(stats) >= 4 and stats[3] > 0 else None

            # Fallback: statisticstimes not yet computed (pre-STOP).
            # Development runs from FIRST CRACK to DROP, never from DRY END.
            if dev_s is None and fc_i >= 0 and drop_i >= 0:
                dev_s = timex[drop_i] - timex[fc_i]
                total_s_stat = total_s
        except Exception:  # noqa: BLE001
            total_s = charge_bt = drop_bt = dev_s = total_s_stat = None

        strip = QFrame()
        strip.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        row = QHBoxLayout(strip)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(0)

        metrics = [
            (_SVG_CLOCK,       THEME['SUBTEXT'], QApplication.translate("tilauscope_roast_setup", "Total"),     _fmt_time(total_s),               THEME['TEXT']),
            (_SVG_THERMOMETER, THEME['ACCENT'],        QApplication.translate("Tooltip", "Charge"),    _fmt_temp(charge_bt),              THEME['ACCENT']),
            (_SVG_THERMOMETER, "#fab387",        QApplication.translate("Tooltip", "Drop"),      _fmt_temp(drop_bt),                "#fab387"),
            (_SVG_CLOCK,       THEME['ACCENT'],  QApplication.translate("tilauscope_common", "Dev"),       _fmt_time(dev_s),                  THEME['ACCENT']),
            (_SVG_DEVELOPMENT, THEME['ACCENT'],  QApplication.translate("tilauscope_common", "DTR"),       _fmt_dtr(dev_s, total_s_stat),     THEME['ACCENT']),
        ]

        for i, (svg, icon_color, label, value, val_color) in enumerate(metrics):
            if i > 0:
                div = QFrame()
                div.setFixedWidth(1)
                div.setStyleSheet(f"background: {THEME['BORDER']}; border: none; margin: 4px 0;")
                row.addWidget(div)

            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.setContentsMargins(12, 0, 12, 0)

            icon_row = QHBoxLayout()
            icon_row.setSpacing(5)
            icon_row.setContentsMargins(0, 0, 0, 0)
            icon_row.addWidget(_svg_icon_label(svg, icon_color, 14))
            lbl = QLabel(label)
            lbl.setProperty('variant', 'eyebrow')
            icon_row.addWidget(lbl)
            icon_row.addStretch()

            val_lbl = QLabel(value)
            val_lbl.setStyleSheet(
                f"color: {val_color}; font-size: 15px; font-weight: bold;"
            )
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)

            cell.addLayout(icon_row)
            cell.addWidget(val_lbl)
            row.addLayout(cell)

        return strip

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        from PyQt6.QtWidgets import QTextEdit, QScrollArea

        qmc = self._aw.qmc

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Card shell ────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("resultCard")
        card.setStyleSheet(f"""
            QFrame#resultCard {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['SUCCESS']};
                border-radius: 20px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 24)
        cl.setSpacing(14)
        outer.addWidget(card)

        # ── Header ────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "POST-ROAST"))
        title_lbl.setStyleSheet(
            f"color: {THEME['SUCCESS']}; font-size: 16px; font-weight: 800;"
            f"letter-spacing: 3px;"
        )
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        date_lbl = QLabel(datetime.now().strftime("%a %d %b  %H:%M"))
        date_lbl.setProperty('variant', 'caption')
        header_row.addWidget(date_lbl)
        cl.addLayout(header_row)
        cl.addWidget(_separator())

        # ── Scrollable body ───────────────────────────────────────────────
        # Header and footer stay outside so they survive a short screen.
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(14)
        body_scroll.setWidget(body)
        cl.addWidget(body_scroll, 1)
        # QScrollArea reports a size hint of its own, unrelated to what it holds.
        # Keep the body's own hints so the window sizes to its content.
        self._body = body
        self._body_scroll = body_scroll

        # ── Identity band — bean left, batch right ────────────────────────
        # Both answer "which roast is this?", so they share one row.
        identity_row = QHBoxLayout()
        identity_row.setSpacing(12)

        bean_card = QFrame()
        bean_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        bc = QHBoxLayout(bean_card)
        bc.setContentsMargins(14, 10, 14, 10)
        bc.setSpacing(16)

        # Bean icon
        bc.addWidget(_svg_icon_label(_SVG_BEAN, THEME['ACCENT'], 28))

        # Bean text stack
        bean_text = QVBoxLayout()
        bean_text.setSpacing(2)
        bean_name = _ElidedLabel(
            self._bean.name or QApplication.translate("tilauscope_roast_setup", "(unknown bean)"))
        bean_name.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 13px; font-weight: bold; border: none;"
        )
        bean_text.addWidget(bean_name)

        meta_parts = []
        if self._bean.country:    meta_parts.append(self._bean.country)
        if self._bean.process:    meta_parts.append(self._bean.process)
        if self._bean.varieties:  meta_parts.append(self._bean.varieties)
        if meta_parts:
            meta_lbl = _ElidedLabel("  ·  ".join(meta_parts))
            meta_lbl.setProperty('variant', 'caption')
            bean_text.addWidget(meta_lbl)
        bc.addLayout(bean_text, 1)

        # Green weight badge
        green_g = self._green_grams()
        if green_g:
            gw_col = QVBoxLayout()
            gw_col.setSpacing(0)
            gw_val = QLabel(f"{green_g:.0f}")
            gw_val.setStyleSheet(
                f"color: {THEME['ACCENT']}; font-size: 16px; font-weight: bold; border: none;"
            )
            gw_val.setAlignment(Qt.AlignmentFlag.AlignRight)
            gw_unit = QLabel(QApplication.translate("tilauscope_roast_setup", "g green"))
            gw_unit.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px; border: none;")
            gw_unit.setAlignment(Qt.AlignmentFlag.AlignRight)
            gw_col.addWidget(gw_val)
            gw_col.addWidget(gw_unit)
            bc.addLayout(gw_col)
        bean_card.setMinimumWidth(360)
        identity_row.addWidget(bean_card, 1)

        # ── Batch (assigned at DROP; locked, unlock via padlock to correct) ───
        batch_card = QFrame()
        batch_card.setStyleSheet(
            f"QFrame {{ background: {THEME['SURFACE']}; border-radius: 10px;"
            f"border: 1px solid {THEME['BORDER']}; }}"
        )
        batch_lay = QVBoxLayout(batch_card)
        batch_lay.setContentsMargins(14, 6, 14, 8)
        batch_lay.setSpacing(2)
        batch_lay.addWidget(_section_label(QApplication.translate("Label", "Batch")))
        self._batch_block = _BatchBlock(self._aw, _BatchBlock.MODE_EDIT)
        batch_lay.addWidget(self._batch_block)
        batch_card.setFixedWidth(270)
        identity_row.addWidget(batch_card)
        bl.addLayout(identity_row)

        # ── Roast metrics strip (read-only) ───────────────────────────────
        bl.addWidget(self._build_metrics_strip())
        bl.addWidget(_separator())

        # ── Two columns — entry fields left, notes right ───────────────────
        columns_row = QHBoxLayout()
        columns_row.setSpacing(28)
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(12)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(12)

        # ── SECTION 1 — Weight ────────────────────────────────────────────
        weight_sec_row = QHBoxLayout()
        weight_sec_row.addWidget(_svg_icon_label(_SVG_SCALE_RESULT, THEME['ACCENT'], 18))
        weight_sec_row.addSpacing(6)
        weight_sec_row.addWidget(_section_label(QApplication.translate("tilauscope_common", "Roasted weight")))
        weight_sec_row.addStretch()
        left_col.addLayout(weight_sec_row)

        weight_row = QHBoxLayout()
        weight_row.setSpacing(10)

        # Whole-bean weight (large field)
        # the loaded profile's weight, in grams: qmc keeps the profile's own unit
        self._roasted_weight_edit = QLineEdit(str(round(_to_grams(qmc.weight[1], qmc.weight[2]), 1)))
        self._roasted_weight_edit.setPlaceholderText("0")
        self._roasted_weight_edit.setMinimumHeight(48)
        self._roasted_weight_edit.setMaximumWidth(150)
        self._roasted_weight_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._roasted_weight_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 26px; font-weight: bold; color: {THEME['TEXT']};"
            f"background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 8px; padding: 6px 12px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        self._roasted_weight_edit.textChanged.connect(self._update_loss_label)
        rw_unit = QLabel("g")
        rw_unit.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 18px;")
        weight_row.addWidget(self._roasted_weight_edit)
        weight_row.addWidget(rw_unit)

        # Weight-loss badge — wraps to two lines in the 470 px entry column
        self._loss_lbl = QLabel("")
        self._loss_lbl.setWordWrap(True)
        self._loss_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 11px; margin-left: 10px;"
        )
        weight_row.addWidget(self._loss_lbl)
        weight_row.addStretch()
        left_col.addLayout(weight_row)

        # Defects field
        defect_row = QHBoxLayout()
        defect_row.setSpacing(10)
        defect_row.addWidget(_svg_icon_label(_SVG_DEFECT, THEME['WARNING'], 16))
        defect_lbl = QLabel(QApplication.translate("Textbox", "Defects"))
        defect_lbl.setProperty('variant', 'secondary')
        defect_row.addWidget(defect_lbl)
        self._defects_edit = QLineEdit(str(round(_to_grams(qmc.roasted_defects_weight, qmc.weight[2]), 1)))
        self._defects_edit.setPlaceholderText("0")
        self._defects_edit.setMinimumHeight(32)
        self._defects_edit.setMaximumWidth(90)
        self._defects_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._defects_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 14px; color: {THEME['WARNING']};"
            f"background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 6px; padding: 4px 10px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['WARNING']}; }}"
        )
        defect_row.addWidget(self._defects_edit)
        defect_row.addWidget(_value_label("g"))  # inline unit
        self.defects_percentage = QLabel()
        self.defects_percentage.setProperty('variant', 'secondary')
        defect_row.addWidget(self.defects_percentage)
        defect_row.addStretch()
        left_col.addLayout(defect_row)
        self._defects_edit.textChanged.connect(self._update_loss_label)
        # the defect share divides by the roasted weight: it follows both fields
        self._defects_edit.textChanged.connect(self._update_defect_percentage)
        self._roasted_weight_edit.textChanged.connect(self._update_defect_percentage)

        # ── SECTION 2 — Colour ────────────────────────────────────────────
        left_col.addWidget(_separator())
        color_sec_row = QHBoxLayout()
        color_sec_row.addWidget(_svg_icon_label(_SVG_COLOR_LENS, THEME['ACCENT'], 18))
        color_sec_row.addSpacing(6)
        color_sec_row.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Colour (Agtron)")))
        color_sec_row.addStretch()

        # C1 device button: shown only when device is configured
        has_c1 = bool(getattr(self._aw, 'bleRoastSeeDeviceName', None))
        if has_c1:
            c1_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "◉  Colour meter"))
            c1_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {THEME['ACCENT']};"
                f"border: 1px solid {THEME['ACCENT']}; border-radius: 6px;"
                f"font-size: 11px; padding: 4px 10px; }}"
                f"QPushButton:hover {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}"
            )
            c1_btn.setToolTip(QApplication.translate("tilauscope_roast_setup",
                "Open the colour meter card"))
            c1_btn.clicked.connect(self._toggle_color_window)
            color_sec_row.addWidget(c1_btn)
            # Create the floating colour window
            self._color_window = _ColorFloatWindow(self)
        left_col.addLayout(color_sec_row)

        colour_fields_row = QHBoxLayout()
        colour_fields_row.setSpacing(20)

        # Whole-bean colour
        whole_col = QVBoxLayout()
        whole_col.setSpacing(4)
        whole_header = QHBoxLayout()
        whole_header.addWidget(_svg_icon_label(_SVG_BEAN, THEME['SUBTEXT'], 14))
        whole_header.addSpacing(4)
        wh_lbl = QLabel(QApplication.translate("tilauscope_common", "Whole bean"))
        wh_lbl.setProperty('variant', 'caption')
        whole_header.addWidget(wh_lbl)
        whole_header.addStretch()
        whole_col.addLayout(whole_header)
        self._colour_whole_edit = QLineEdit(str(qmc.whole_color))
        self._colour_whole_edit.setPlaceholderText("—")
        self._colour_whole_edit.setMinimumHeight(38)
        self._colour_whole_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._colour_whole_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 18px; font-weight: bold; color: {THEME['TEXT']};"
            f"background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 6px; padding: 4px 10px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        self._colour_whole_edit.setToolTip(
            QApplication.translate("tilauscope_roast_setup",
                "Agtron reading on whole roasted beans.\n"
                "You can tap the colour meter card to populate this field automatically.")
        )
        self._colour_whole_edit.textChanged.connect(self._update_color_diff)
        whole_col.addWidget(self._colour_whole_edit)
        colour_fields_row.addLayout(whole_col, 1)
        # Ground colour
        ground_col = QVBoxLayout()
        ground_col.setSpacing(4)
        ground_header = QHBoxLayout()
        ground_header.addWidget(_svg_icon_label(_SVG_DEFECT, THEME['SUBTEXT'], 14))
        ground_header.addSpacing(4)
        gr_lbl = QLabel(QApplication.translate("Label", "Ground"))
        gr_lbl.setProperty('variant', 'caption')
        ground_header.addWidget(gr_lbl)
        ground_header.addStretch()
        ground_col.addLayout(ground_header)
        self._colour_ground_edit = QLineEdit(str(qmc.ground_color))
        self._colour_ground_edit.setPlaceholderText("—")
        self._colour_ground_edit.setMinimumHeight(38)
        self._colour_ground_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._colour_ground_edit.setStyleSheet(
            f"QLineEdit {{ font-size: 18px; font-weight: bold; color: {THEME['TEXT']};"
            f"background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 6px; padding: 4px 10px; }}"
            f"QLineEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        self._colour_ground_edit.setToolTip(
            QApplication.translate("tilauscope_roast_setup",
                "Agtron reading on ground beans.\n"
                "You can tap the colour meter card to populate this field automatically.")
        )
        self._colour_ground_edit.textChanged.connect(self._update_color_diff)
        ground_col.addWidget(self._colour_ground_edit)
        colour_fields_row.addLayout(ground_col, 1)

        # Delta badge
        delta_col = QVBoxLayout()
        delta_col.setSpacing(4)
        delta_col.addWidget(QLabel(""))   # spacer to align with field header height
        self._color_delta_lbl = QLabel("Δ ––")
        self._color_delta_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._color_delta_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 13px; font-weight: bold;"
            f"min-width: 60px;"
        )
        self._color_delta_lbl.setToolTip(
            QApplication.translate("tilauscope_roast_setup", "Difference: whole − ground")
        )
        delta_col.addWidget(self._color_delta_lbl)
        colour_fields_row.addLayout(delta_col)

        left_col.addLayout(colour_fields_row)

        # Agtron range hint
        self._agtron_hint_lbl = QLabel("")
        self._agtron_hint_lbl.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-size: 10px; font-style: italic;"
        )
        left_col.addWidget(self._agtron_hint_lbl)
        left_col.addStretch()

        # ── SECTION 3 — How did the roast go? ────────────────────────────
        notes_sec_row = QHBoxLayout()
        notes_sec_row.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "How did it go?")))
        notes_sec_row.addStretch()
        right_col.addLayout(notes_sec_row)

        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText(
            QApplication.translate("tilauscope_roast_setup",
                "How was the development? Any surprises with this bean? "
                "Cracking point, smell, colour progression…")
        )
        # Unbounded: this box absorbs the height of the entry column beside it.
        self._notes_edit.setMinimumHeight(140)
        self._notes_edit.setStyleSheet(
            f"QTextEdit {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 8px;"
            f"font-size: 12px; padding: 8px; }}"
            f"QTextEdit:focus {{ border-color: {THEME['ACCENT']}; }}"
        )
        right_col.addWidget(self._notes_edit, 1)

        # Burns seen on the beans — Artisan's own roast flags, written on Save.
        # Caption above the chips: translated defect names outgrow a single row.
        marks_col = QVBoxLayout()
        marks_col.setSpacing(4)
        marks_lbl = QLabel(QApplication.translate("tilauscope_roast_setup", "Seen on the beans"))
        marks_lbl.setProperty('variant', 'secondary')
        marks_col.addWidget(marks_lbl)
        marks_row = QHBoxLayout()
        marks_row.setSpacing(8)
        self._tipping_chip = _defect_mark_chip(
            _SVG_TIPPING,
            QApplication.translate("tilauscope_roast_setup", "Tipping"),
            QApplication.translate("tilauscope_roast_setup",
                "Tipping — the ends of the beans are burnt dark. "
                "Usually too much heat early in the roast."),
            bool(getattr(qmc, 'tipping_flag', False)))
        marks_row.addWidget(self._tipping_chip)
        self._scorching_chip = _defect_mark_chip(
            _SVG_SCORCHING,
            QApplication.translate("tilauscope_roast_setup", "Scorching"),
            QApplication.translate("tilauscope_roast_setup",
                "Scorching — dark burnt patches on the flat side of the beans. "
                "Usually a charge that was too hot for this batch."),
            bool(getattr(qmc, 'scorching_flag', False)))
        marks_row.addWidget(self._scorching_chip)
        marks_row.addStretch()
        marks_col.addLayout(marks_row)
        right_col.addLayout(marks_col)

        mood_hint = QLabel(QApplication.translate("tilauscope_roast_setup", "free notes → roast log"))
        mood_hint.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px; font-style: italic;")
        right_col.addWidget(mood_hint)

        # Declared widths, none inferred: the entry column holds the widest row
        # (weight field + loss badge), the notes box takes what is left.
        left_host = QWidget()
        left_host.setLayout(left_col)
        left_host.setFixedWidth(470)
        right_host = QWidget()
        right_host.setLayout(right_col)
        right_host.setMinimumWidth(340)
        columns_row.addWidget(left_host)
        columns_row.addWidget(right_host, 1)
        bl.addLayout(columns_row)

        # ── Buttons ───────────────────────────────────────────────────────
        cl.addWidget(_separator())
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        cancel_btn = QPushButton(QApplication.translate("Button", "Cancel"))
        cancel_btn.setObjectName('footerBtn')
        cancel_btn.setProperty('variant', 'outline')
        cancel_btn.clicked.connect(self._on_cancel)
        ok_btn = QPushButton(QApplication.translate("tilauscope_roast_setup", "⬥  Save roast"))
        ok_btn.setObjectName('footerBtn')
        ok_btn.setProperty('variant', 'primary')
        ok_btn.clicked.connect(self._on_ok)
        # AI Summary button – only shown when AI is configured
        try:
            ai_cfg = getattr(self._aw, "tilau_aiConfig", None)
            if getattr(ai_cfg, "is_configured", False):
                ai_btn = QPushButton(
                    QApplication.translate("tilauscope_roast_setup", "✦  AI Summary")
                )
                ai_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {THEME['ACCENT']};
                        border: 1px solid {THEME['ACCENT']};
                        border-radius: 8px;
                        padding: 8px 16px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background: {THEME['ACCENT']};
                        color: {THEME['BG']};
                    }}
                """)
                ai_btn.clicked.connect(self._toggle_ai_panel)
                btn_row.addWidget(ai_btn)
        except Exception as exc:  # noqa: BLE001
            _log.warning("RoastResultDialog: AI button init failed: %s", exc)
        # Roast label — printable straight from the values typed above, without
        # waiting for the profile to reach the disk (see _label_profile_snapshot)
        label_btn = QPushButton(
            QApplication.translate("tilauscope_roast_setup", "🏷  Label PDF")
        )
        label_btn.setProperty('variant', 'outline')
        label_btn.setToolTip(QApplication.translate(
            "tilauscope_roast_setup",
            "Generate the roast label as a PDF from the values entered above"))
        label_btn.clicked.connect(self._on_print_label)
        btn_row.addWidget(label_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        cl.addLayout(btn_row)

        # wen creation is finished, update computed fields
        self._update_loss_label()
        self._update_defect_percentage()
        self._update_color_diff()

    # ── Live label updates ────────────────────────────────────────────────────

    @pyqtSlot()
    def _update_defect_percentage(self) -> None:
        """Recompute and display the defect % whenever either weight/defectchanges."""
        roasted:float = 0.0
        defects:float = 0.0
        percent:float = 0.0
        try:
            roasted = float(self._roasted_weight_edit.text().replace(',', '.') or '0')
        except ValueError:
            pass
        try:
            defects = float(self._defects_edit.text().replace(',', '.') or '0')
        except ValueError:
            pass
        hint=""
        if roasted > 0.0 and defects > 0.0:
            percent = (defects/roasted)*100.0
            if percent > 0.0:
                hint = f"{percent:.1f}%"

        color = THEME['SUCCESS'] if 0 <= percent <= 5 else THEME['WARNING']

        self.defects_percentage.setText(hint)
        self.defects_percentage.setStyleSheet(f"color: {color}; font-size: 11px; margin-left: 10px;")

    def _loss_aim(self) -> tuple[float, float, float] | None:
        """(aim, low, high) weight loss of this roast, as the debrief judges it;
        None without a level read from the roast. Resolved once: it reads files."""
        if not hasattr(self, '_loss_aim_cache'):
            self._loss_aim_cache = None
            try:
                from tilauscope import roast_coach  # noqa: PLC0415
                from tilauscope.roast_debrief import profile_from_qmc  # noqa: PLC0415
                profile = profile_from_qmc(self._aw)
                ctx, bean = roast_coach.roast_inputs(profile)
                bands = roast_coach.roast_bands(profile, roast_context=ctx, bean=bean)
                if bands.level:
                    self._loss_aim_cache = (bands.thresholds['wl_target'], *bands.wl_window)
            except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
                _log.debug("weight-loss aim unavailable: %s", exc)
        return self._loss_aim_cache

    @pyqtSlot()
    def _update_loss_label(self) -> None:
        """Recompute and display the weight-loss % whenever either weight/defect changes."""
        green = self._green_grams()
        if not green:
            self._loss_lbl.setText("")
            return
        try:
            roasted = float(self._roasted_weight_edit.text().replace(',', '.') or '0')
        except ValueError:
            roasted = 0.0
        try:
            defects = float(self._defects_edit.text().replace(',', '.') or '0')
        except ValueError:
            defects = 0.0

        if (roasted-defects) > 0 and green > 0:
            loss_pct = (1.0 - ((roasted - defects) / green)) * 100.0
            aim = self._loss_aim()
            if aim is None:
                color = THEME['SUBTEXT']
                hint = QApplication.translate("tilauscope_roast_setup",
                    "{0:.1f} % loss  (green: {1:.0f} g)").format(loss_pct, green)
            else:
                target, lo, hi = aim
                color = THEME['SUCCESS'] if lo <= loss_pct <= hi else THEME['WARNING']
                hint = QApplication.translate("tilauscope_roast_setup",
                    "{0:.1f} % loss · aim {1:.1f} % ({2:.1f}–{3:.1f} %)  (green: {4:.0f} g)").format(
                    loss_pct, target, lo, hi, green)
            self._loss_lbl.setText(hint)
            self._loss_lbl.setStyleSheet(f"color: {color}; font-size: 11px; margin-left: 10px;")
        else:
            self._loss_lbl.setText(
                QApplication.translate("tilauscope_roast_setup", "green: {0:.0f} g").format(green)
            )

    @pyqtSlot()
    def _update_color_diff(self) -> None:
        """Show delta between whole-bean and ground Agtron readings."""
        try:
            w = float(self._colour_whole_edit.text().replace(',', '.'))
        except ValueError:
            w = None
        try:
            g = float(self._colour_ground_edit.text().replace(',', '.'))
        except ValueError:
            g = None

        if w is not None and g is not None and w >0 and g > 0 :
            delta = w - g
            sign  = "+" if delta >= 0 else ""
            self._color_delta_lbl.setText(f"Δ {sign}{delta:.1f}")
            color = THEME['ACCENT'] if abs(delta) < 10 else THEME['WARNING']
            self._color_delta_lbl.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold;"
                f"min-width: 60px;"
            )
        else:
            self._color_delta_lbl.setText("")
            self._color_delta_lbl.setStyleSheet(
                f"color: {THEME['SUBTEXT']}; font-size: 13px; font-weight: bold;"
                f"min-width: 60px;"
            )

        # The roast's colour: ground when measured, else whole — never whichever
        # field merely holds a number.
        ref = roast_colour_agtron({'ground_color': g or 0.0, 'whole_color': w or 0.0})
        self._agtron_hint_lbl.setText(self._agtron_range_label(ref) if ref is not None else "")

    @staticmethod
    def _agtron_range_label(value: float) -> str:
        if value >= 85:   return QApplication.translate("tilauscope_roast_setup", "Very light roast")
        if value >= 70:   return QApplication.translate("tilauscope_roast_setup", "Light roast")
        if value >= 55:   return QApplication.translate("tilauscope_roast_setup", "Medium-light roast")
        if value >= 40:   return QApplication.translate("tilauscope_roast_setup", "Medium roast")
        if value >= 25:   return QApplication.translate("tilauscope_roast_setup", "Medium-dark roast")
        return QApplication.translate("tilauscope_roast_setup", "Dark roast")

    # ── AI panel ──────────────────────────────────────────────────────────────

    def _toggle_ai_panel(self) -> None:
        if self._ai_panel is None:
            return
        self._ai_panel.toggle()

    def _build_roast_summary_payload(self) -> tuple[str, str]:
        """
        Assembles system + user messages for the AI roast summary.
        Returns (system_prompt, user_content).
        """
        qmc  = self._aw.qmc
        bean = self._bean

        def _fmt_time(s) -> str:
            try:
                s = int(round(float(s)))
                return f"{s // 60}:{s % 60:02d}"
            except Exception:
                return "n/a"

        def _fmt_temp(v) -> str:
            try:
                v = float(v)
                return f"{v:.1f} °{getattr(qmc, 'mode', 'C')}" if v > 0 else "n/a"
            except Exception:
                return "n/a"

        # ── Bean info ─────────────────────────────────────────────────────────
        lines: list[str] = ["## Bean"]
        lines.append(f"- Name: {bean.name or '(unknown)'}")
        if bean.country:       lines.append(f"- Origin: {bean.country}")
        if bean.process:       lines.append(f"- Process: {bean.process}")
        if bean.varieties:     lines.append(f"- Varieties: {bean.varieties}")
        if bean.sca:           lines.append(f"- SCA score: {bean.sca}")
        if bean.density:       lines.append(f"- Density: {bean.density} g/L")
        if bean.last_humidity: lines.append(f"- Moisture: {bean.last_humidity}%")
        if bean.water_activity:lines.append(f"- Water activity: {bean.water_activity}")
        if bean.altitude:      lines.append(f"- Altitude: {bean.altitude} m")
        if bean.flavour_notes: lines.append(f"- Expected flavours: {bean.flavour_notes}")
        if bean.tips:          lines.append(f"- Supplier roasting tips: {bean.tips}")
        lines.append("")

        # ── Roast metrics ─────────────────────────────────────────────────────
        try:
            ti    = qmc.timeindex
            timex = qmc.timex
            temp2 = qmc.temp2
            stats = qmc.statisticstimes

            charge_i = ti[0] if milestone_marked(ti, 0) else -1
            dry_i    = ti[1] if milestone_marked(ti, 1) else -1
            fc_i     = ti[2] if milestone_marked(ti, 2) else -1
            drop_i   = ti[6] if milestone_marked(ti, 6) else -1

            total_s    = (timex[drop_i] - timex[charge_i]) if (charge_i >= 0 and drop_i >= 0) else None
            drying_s   = (timex[dry_i]  - timex[charge_i]) if (charge_i >= 0 and dry_i  >= 0) else None
            maillard_s = (timex[fc_i]   - timex[dry_i])    if (dry_i   >= 0 and fc_i    >= 0) else None
            dev_s      = stats[3]            if stats and len(stats) > 3 else None
            total_stat = sum(stats[1:4])     if stats and len(stats) >= 4 else None
            dtr        = f"{dev_s / total_stat * 100:.1f}%" if (dev_s and total_stat) else "n/a"

            # Drying % and Maillard % of total
            drying_pct   = f"{drying_s   / total_s * 100:.0f}%" if (drying_s   and total_s) else "n/a"
            maillard_pct = f"{maillard_s / total_s * 100:.0f}%" if (maillard_s and total_s) else "n/a"
            dev_pct      = f"{dev_s      / total_s * 100:.0f}%" if (dev_s      and total_s) else "n/a"

            # RoR at drop (last 30 s average if data available)
            ror_at_drop = "n/a"
            try:
                if drop_i >= 0 and len(timex) > drop_i and len(temp2) > drop_i:
                    window = 30  # seconds
                    # Find index ~30s before drop
                    idx_before = drop_i
                    for i in range(drop_i, 0, -1):
                        if timex[drop_i] - timex[i] >= window:
                            idx_before = i
                            break
                    dt = timex[drop_i] - timex[idx_before]
                    dT = temp2[drop_i] - temp2[idx_before]
                    if dt > 0:
                        ror_at_drop = f"{dT / dt * 60:.1f} °/min"
            except Exception:
                pass

            lines += [
                "## Roast Metrics",
                f"- Total time: {_fmt_time(total_s)}",
                f"- Charge BT: {_fmt_temp(temp2[charge_i]) if charge_i >= 0 and charge_i < len(temp2) else 'n/a'}",
                f"- Dry-end BT: {_fmt_temp(temp2[dry_i]) if dry_i >= 0 and dry_i < len(temp2) else 'n/a'}",
                f"- FC BT: {_fmt_temp(temp2[fc_i]) if fc_i >= 0 and fc_i < len(temp2) else 'n/a'}",
                f"- Drop BT: {_fmt_temp(temp2[drop_i]) if drop_i >= 0 and drop_i < len(temp2) else 'n/a'}",
                f"- Drying phase: {_fmt_time(drying_s)} ({drying_pct} of total)",
                f"- Maillard phase: {_fmt_time(maillard_s)} ({maillard_pct} of total)",
                f"- Development time: {_fmt_time(dev_s)} ({dev_pct} of total)",
                f"- DTR: {dtr}",
                f"- RoR at drop: {ror_at_drop}",
                "",
            ]
        except Exception:
            lines.append("*(metrics unavailable)*\n")

        # ── Colour ────────────────────────────────────────────────────────────
        try:
            wh = self._colour_whole_edit.text().strip()
            gr = self._colour_ground_edit.text().strip()
            if wh or gr:
                lines += [
                    "## Colour (Agtron)",
                    f"- Whole bean: {wh or 'n/a'}",
                    f"- Ground: {gr or 'n/a'}",
                    "",
                ]
        except Exception:
            pass

        # ── Visible defects ───────────────────────────────────────────────────
        try:
            seen = [name for name, chip in (("tipping", self._tipping_chip),
                                            ("scorching", self._scorching_chip))
                    if chip.isChecked()]
            if seen:
                lines += ["## Visible Defects",
                          f"- Seen on the roasted beans: {', '.join(seen)}", ""]
        except Exception:
            pass

        # ── Roaster notes ─────────────────────────────────────────────────────
        try:
            notes = self._notes_edit.toPlainText().strip()
            if notes:
                lines += ["## Roaster Notes", notes, ""]
        except Exception:
            pass

        if self._aw.qmc.roastertype:
            roaster_name = self._aw.qmc.roastertype+"  with all its capacity for control and precision"
        else:
            roaster_name = "drum roaster with independent control of burner, air damper, and drum speed"

        system = (
            "You are an expert coffee roasting consultant. you need to asses about the quality of a roast based on the data provided by the roaster and the roaster's notes. "
            f"The roaster device used is a {roaster_name}.\n"
            "Analyse the roast session data below and produce a report with these exact sections:\n"
            "1. **Verdict** – one sentence: was this a good roast for this bean?\n"
            "2. **Phase analysis** – evaluate drying %, Maillard %, DTR, and RoR at drop against best-practice ranges. "
            "Flag anything outside normal ranges.\n"
            "3. **Temperature profile** – comment on charge temp, turning point, development curve.\n"
            "4. **Colour** – interpret Agtron values if provided (whole bean vs ground delta).\n"
            "5. **Flavour match** – assess whether the roast profile suits the expected flavour notes.\n"
            "6. **Next roast suggestions** – 2-3 concrete actionable changes if warranted; "
            "skip this section if the roast was well-executed.\n"
            f"Be direct and concise. Avoid technical jargon. Use Markdown. Write in language from locale code {self._aw.qmc.locale_str}.."
        )
        user = "\n".join(lines)
        return (system, user)

    # ── Color window toggle ───────────────────────────────────────────────────

    def _toggle_color_window(self) -> None:
        if self._color_window is None:
            return
        if self._color_window.isVisible():
            self._color_window.hide()
        else:
            geo = self.geometry()
            x   = geo.right() + 12
            y_base = geo.top() + 40
            if self._scale_window and self._scale_window.isVisible():
                y_base = self._scale_window.geometry().bottom() + 8
            self._color_window.move(x, y_base)
            self._color_window.show()

    # ── Roast label (PDF) ────────────────────────────────────────────────────

    def _label_profile_snapshot(self) -> dict:
        """Profile dict feeding the label renderer.

        The label printer only needs a profile dictionary — on the live path the
        roast has not been written to disk yet, so it cannot be read back from an
        .alog like BeanCave does: getProfile() returns the very same structure
        from memory, 'computed' block included.

        The values typed in this dialog are overridden on the snapshot only —
        qmc stays untouched so that printing has no side effect and a later
        Cancel really cancels.
        """
        profile = dict(self._aw.getProfile())

        try:
            roasted = float(self._roasted_weight_edit.text().replace(',', '.') or '0')
        except ValueError:
            roasted = 0.0
        try:
            whole_color = float(self._colour_whole_edit.text().replace(',', '.') or '0')
        except ValueError:
            whole_color = 0.0
        try:
            ground_color = float(self._colour_ground_edit.text().replace(',', '.') or '0')
        except ValueError:
            ground_color = 0.0

        weight = list(profile.get('weight') or [0.0, 0.0, 'g'])
        while len(weight) < 3:
            weight.append('g')
        try:
            green = float(weight[0])
        except (TypeError, ValueError):
            green = 0.0
        # The form's figures are grams; the profile keeps its own unit.
        if green <= 0:
            green = _from_grams(self._green_grams(), weight[2])
        roasted = _from_grams(roasted, weight[2])
        profile['weight'] = [green, roasted, weight[2]]

        profile['whole_color']  = whole_color
        profile['ground_color'] = ground_color
        # The scale travels with the reading: a snapshot taken before OK would
        # otherwise carry the unset scale of the profile it was copied from.
        profile['color_system'] = resolve_color_system(
            str(profile.get('color_system') or ''), ground_color, whole_color)

        computed = dict(profile.get('computed') or {})
        if green > 0 and roasted > 0:
            computed['total_loss'] = round((1.0 - (roasted / green)) * 100.0, 1)
        profile['computed'] = computed

        return profile

    @pyqtSlot()
    def _on_print_label(self) -> None:
        try:
            from tilauscope.label_printer import RoastedBeanLabelPrinter, get_downloads_dir

            profile = self._label_profile_snapshot()

            bean_name = (self._bean.name if self._bean and self._bean.name else "roast")
            safe_name = bean_name.replace(" ", "_").replace("/", "-")
            date_str  = str(profile.get('roastisodate') or profile.get('roastdate') or "").replace(" ", "_")
            default   = str(get_downloads_dir() / f"roast_label_{safe_name}_{date_str}.pdf".replace("__", "_"))

            file_path, _ = QFileDialog.getSaveFileName(
                self,
                QApplication.translate("tilauscope_common", "Save Label PDF"),
                default,
                QApplication.translate("tilauscope_common", "PDF Files (*.pdf)"))
            if not file_path:
                return

            ok = RoastedBeanLabelPrinter().print_to_label(profile, self._bean, file_path)
            if not ok:
                show_styled_message(
                    self,
                    QApplication.translate("Error Message", "Error"),
                    QApplication.translate("tilauscope_common", "PDF file was not generated."),
                    QMessageBox.Icon.Warning)
                return

            self._label_printed = True
            self._open_file(file_path)
            _log.info("RoastResultDialog: roast label written to %s", file_path)
        except Exception as exc:  # noqa: BLE001
            _log.error("RoastResultDialog: label printing failed: %s", exc)
            show_styled_message(
                self,
                QApplication.translate("Error Message", "Error"),
                QApplication.translate("tilauscope_roast_setup",
                    "Could not generate the roast label:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True)

    def _open_file(self, file_path: str) -> None:
        """Hand the generated PDF to the OS viewer, in front of this dialog.

        This dialog is created WindowStaysOnTopHint and its helper windows float
        on their own, so the viewer would open underneath all of them — that is
        what open_in_os_viewer takes care of. The dialog stays modal meanwhile,
        so nothing behind it becomes reachable.
        """
        open_in_os_viewer(
            file_path, self,
            helpers=[w for w in (self._scale_window, self._color_window) if w is not None])

    # ── OK / Cancel ──────────────────────────────────────────────────────────

    #: What saving the form writes into qmc — put back when the save fails.
    _QMC_FIELDS: Final[tuple[str, ...]] = (
        'beans', 'weight', 'roasted_defects_weight', 'whole_color', 'ground_color',
        'color_system_idx', 'tipping_flag', 'scorching_flag', 'roastingnotes',
        'roastbatchprefix', 'roastbatchnr', 'roastbatchpos',
    )

    @pyqtSlot()
    def _on_ok(self) -> None:
        # Last chance to print the label: once this dialog closes the
        # batch is done and the label has to be re-generated from BeanCave.
        if not self._label_printed:
            choice = show_styled_message(
                self,
                QApplication.translate("tilauscope_roast_setup", "Roast label"),
                QApplication.translate("tilauscope_roast_setup",
                    "You have not generated the label for this roast yet.<br>"
                    "Do you want to print it before closing?"),
                QMessageBox.Icon.Question, rich=True,
                buttons=[
                    QApplication.translate("tilauscope_roast_setup", "🏷  Label PDF"),
                    QApplication.translate("tilauscope_roast_setup", "Save without label"),
                ])
            if choice == 0:
                self._on_print_label()
                # file dialog cancelled or generation failed → stay open
                if not self._label_printed:
                    return
            elif choice != 1:
                return  # dialog dismissed — do not close behind the user's back

        try:
            roasted_w = float(self._roasted_weight_edit.text().replace(',', '.') or '0')
        except ValueError:
            roasted_w = 0.0
        try:
            defects_w = float(self._defects_edit.text().replace(',', '.') or '0')
        except ValueError:
            defects_w = 0.0
        try:
            whole_color = float(self._colour_whole_edit.text().replace(',', '.') or '0')
        except ValueError:
            whole_color = 0.0
        try:
            ground_color = float(self._colour_ground_edit.text().replace(',', '.') or '0')
        except ValueError:
            ground_color = 0.0

        # Inject into Artisan. A failed save puts qmc back as it was: the form
        # keeps the values for a retry, and a later Cancel must change nothing.
        qmc = self._aw.qmc
        before = {name: getattr(qmc, name) for name in self._QMC_FIELDS if hasattr(qmc, name)}

        def restore() -> None:
            for name, value in before.items():
                setattr(qmc, name, value)

        try:
            # A review owns the identity frozen with the displayed roast.  Set
            # it only on Save so Cancel remains side-effect free, including for
            # legacy unlinked roasts whose correct description is empty.
            if self._bean_description is not None:
                qmc.beans = self._bean_description
            # qmc.weight is a typed tuple (in, out, unit) at runtime — rebuild as
            # tuple; the form's grams go back in the profile's own unit.
            w0, _, w2 = qmc.weight
            qmc.weight        = (w0, _from_grams(roasted_w, w2), w2)
            qmc.whole_color   = whole_color
            qmc.ground_color  = ground_color
            # These fields are Agtron — name the scale so the saved profile
            # does not read back as "no colour measured".
            ensure_color_system(qmc)
            qmc.roasted_defects_weight = _from_grams(defects_w, w2)
            qmc.tipping_flag   = self._tipping_chip.isChecked()
            qmc.scorching_flag = self._scorching_chip.isChecked()

            # Batch — persist a deliberate correction of the assigned identity
            try:
                self._batch_block.apply_to_qmc()
            except Exception as exc:  # noqa: BLE001
                _log.warning("RoastResultDialog: batch apply failed: %s", exc)

            notes = self._notes_edit.toPlainText().strip()
            if notes:
                existing = getattr(qmc, 'roastingnotes', '') or ''
                qmc.roastingnotes = (existing + "\n" + notes).strip() if existing else notes
            _log.info(
                "RoastResultDialog: injected roasted=%.1f defects=%.1f "
                "whole_color=%.1f ground_color=%.1f",
                roasted_w, defects_w, whole_color, ground_color,
            )
        except Exception as exc:  # noqa: BLE001
            restore()
            _log.error("RoastResultDialog injection error: %s", exc)
            show_styled_message(
                self,
                QApplication.translate("tilauscope_common", "Save Error"),
                QApplication.translate("tilauscope_roast_setup",
                    "Could not save roast result:<br><b>{0}</b>").format(exc),
                QMessageBox.Icon.Warning, rich=True,
            )
            return

        # OffRecorder's autosave runs before this post-roast dialog opens.  The
        # values above therefore only existed in memory and pressing "Save
        # roast" used to close the dialog without updating the .alog file.
        # Rewrite the autosaved/current profile, or ask for a destination when
        # autosave is disabled.  Never close the dialog after a failed or
        # cancelled save: the operator must retain a chance to retry.
        try:
            saved = bool(self._aw.fileSave(getattr(self._aw, 'curFile', None)))
        except Exception as exc:  # noqa: BLE001
            _log.error("RoastResultDialog profile save failed: %s", exc)
            saved = False
        if not saved:
            restore()
            show_styled_message(
                self,
                QApplication.translate("tilauscope_common", "Save Error"),
                QApplication.translate("tilauscope_roast_setup",
                    "The roast could not be saved. Your data is still in this window; "
                    "choose Save roast to try again."),
                QMessageBox.Icon.Warning,
            )
            return

        self.accept()

    @pyqtSlot()
    def _on_cancel(self) -> None:
        # Cards go now rather than after the fade; done() finds nothing left.
        self._close_helpers()
        self._disconnect_scale()
        self._start_fade_out()

    def _start_fade_out(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(300)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.reject)
        self._fade.start()

    def done(self, result: int) -> None:  # noqa: N802 (Qt override)
        """Unwire the form on every way out: Save, Cancel, Escape, window close.

        On done(), not closeEvent: Escape and accept()/reject() raise no close
        event, and a window close falls back to reject(). Guarded, because an
        exception escaping a Qt virtual aborts the application.
        """
        if not self._cleaned:
            self._cleaned = True
            try:
                self._close_helpers()
                self._disconnect_scale()
            except Exception as exc:  # noqa: BLE001
                _log.warning("RoastResultDialog: cleanup on close failed: %s", exc)
        super().done(result)


# ─────────────────────────────────────────────────────────────────────────────
# Roast Data Reader — readable, navigable view of a recorded roast.
#
# A frameless Mocha window opened from the BeanCave "Roast Viewer" tab. It reads
# a ProfileData dict (decoded .alog) and renders side by side:
#   • left  : a "Parcours" navigator (milestones + special events + phase
#             metrics) — click an entry, or use ↑/↓, to jump the table to it.
#   • right : the full sample table. Time is shown absolute from the start of the
#             recording so the preheat phase BEFORE charge is explorable too.
# Read-only: it never mutates the profile, qmc or the .alog file.
# ─────────────────────────────────────────────────────────────────────────────

# (label, icon, accent colour) per Artisan timeindex slot.
_MILESTONE_SLOTS: Final = (
    ("CHARGE",   "⬤", THEME['WARNING']),   # 0  ⬤ major
    ("DRY END",  "◆", THEME['ACCENT']),    # 1  ◆
    ("FC START", "◆", THEME['SUCCESS']),   # 2  ◆
    ("FC END",   "◆", THEME['SUCCESS']),   # 3  ◆
    ("SC START", "◆", THEME['TEXT']),      # 4  ◆
    ("SC END",   "◆", THEME['TEXT']),      # 5  ◆
    ("DROP",     "⬤", THEME['WARNING']),   # 6  ⬤ major
    ("COOL END", "◆", THEME['SUBTEXT']),   # 7  ◆
)

_ROW_MILESTONE_BG: Final = QColor(THEME['BORDER'])   # overlay
_ROW_EVENT_BG: Final     = QColor('#262637')
_NAV_LABEL_ROLE: Final   = Qt.ItemDataRole.UserRole + 1   # journey entry label


class RoastDataReaderDialog(QDialog):
    """Readable, navigable reader for a recorded roast's sample data.

    Parameters
    ----------
    profile : ProfileData
        Decoded .alog dict (as returned by ``BeancaveDlg.get_alog_data``).
    title : str
        Human label shown in the header (bean / roast name).
    parent : QWidget | None
    """

    def __init__(self, profile: dict, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._drag_pos: object = None
        self._filter_kind: str = 'all'
        self._load_profile(profile, title)

        self.setStyleSheet(base_qss() + _local_style())
        self._build_ui()
        self.resize(940, 620)

    def set_profile(self, profile: dict, title: str = "") -> None:
        """Show another roast in the open reader.

        The filter and the journey entry in focus carry over, so the same
        milestone can be read across roasts.
        """
        focus = self._nav_focus_label()
        self._load_profile(profile, title)
        self._fill()
        self._restore_nav_focus(focus)

    def _load_profile(self, profile: dict, title: str) -> None:
        self._p = profile or {}
        self._roast_title = decode_alog_text(title or self._p.get('title', ''))

        # raw series (defensive copies, never mutated)
        self._timex: list[float] = list(self._p.get('timex', []) or [])
        self._t1: list[float]    = list(self._p.get('temp1', []) or [])   # ET
        self._t2: list[float]    = list(self._p.get('temp2', []) or [])   # BT
        self._ti: list[int]      = list(self._p.get('timeindex', []) or [])
        self._sev: list[int]     = list(self._p.get('specialevents', []) or [])
        self._sevtype: list[int] = list(self._p.get('specialeventstype', []) or [])
        self._sevval: list[float]= list(self._p.get('specialeventsvalue', []) or [])
        # Artisan escapes every text field when it saves a profile, so an event
        # read straight from the file says "Br\\xfbleur" until it is decoded.
        self._sevstr: list[str]  = [decode_alog_text(x) for x in (self._p.get('specialeventsStrings', []) or [])]
        self._etypes: list[str]  = [decode_alog_text(x) for x in (self._p.get('etypes', []) or [])]
        self._extraname1: list[str] = [decode_alog_text(x) for x in (self._p.get('extraname1', []) or [])]
        self._extraname2: list[str] = [decode_alog_text(x) for x in (self._p.get('extraname2', []) or [])]
        self._extratemp1: list[list[float]] = list(self._p.get('extratemp1', []) or [])
        self._extratemp2: list[list[float]] = list(self._p.get('extratemp2', []) or [])
        self._unit: str = str(self._p.get('mode', 'C') or 'C')

        self._ndata: int = min(len(self._timex), len(self._t1), len(self._t2))
        self._origin: float = self._timex[0] if self._ndata else 0.0
        # row -> kinds for filtering: one sample can carry a milestone and events
        self._row_kinds: list[set[str]] = [set() for _ in range(self._ndata)]
        # row -> every special-event position on that sample, in recorded order
        self._sev_at: dict[int, list[int]] = {}
        for k, r in enumerate(self._sev):
            if 0 <= r < self._ndata:
                self._sev_at.setdefault(r, []).append(k)

    # ── small helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _mmss(sec: float) -> str:
        s = int(round(sec))
        sign = '-' if s < 0 else ''
        s = abs(s)
        return f"{sign}{s // 60:02d}:{s % 60:02d}"

    def _fmt_temp(self, v: float) -> str:
        try:
            if v is None or v == -1:
                return "--"
            return f"{v:.1f}"
        except Exception:  # noqa: BLE001
            return "--"

    def _charge_idx(self) -> int:
        return self._ti[0] if (self._ti and self._ti[0] > -1) else -1

    def _slot_idx(self, slot: int) -> int:
        """Marked row for a timeindex slot, or -1 when unmarked/out of range."""
        if slot >= len(self._ti):
            return -1
        idx = self._ti[slot]
        marked = (idx > -1) if slot == 0 else (idx > 0)
        return idx if (marked and 0 <= idx < self._ndata) else -1

    def _tp_idx(self) -> int:
        """Turning point = BT minimum between CHARGE and DRY END (or end)."""
        c = self._charge_idx()
        if c < 0:
            return -1
        end = self._slot_idx(1)
        if end <= c:
            end = self._slot_idx(6)
        if end <= c:
            end = self._ndata - 1
        best_i, best_v = -1, None
        for i in range(c, min(end, self._ndata - 1) + 1):
            v = self._t2[i]
            if v == -1:
                continue
            if best_v is None or v < best_v:
                best_v, best_i = v, i
        # ignore if TP coincides with CHARGE (no real dip captured)
        return best_i if best_i > c else -1

    def _event_text(self, k: int) -> str:
        """Display label for special event #k (e.g. 'Air 50' or a free string)."""
        try:
            etype = self._sevtype[k] if k < len(self._sevtype) else -1
            name = self._etypes[etype] if 0 <= etype < len(self._etypes) else ""
            val = self._sevval[k] if k < len(self._sevval) else 0.0
            valstr = str(events_internal_to_external_value(val))
            label = (name + " " + valstr).strip()
            sstr = self._sevstr[k].strip() if k < len(self._sevstr) else ""
            if sstr and sstr not in ("0", ""):
                label = f"{label} · {sstr}" if label else sstr
            return label or QApplication.translate("tilauscope_roast_setup", "event")
        except Exception:  # noqa: BLE001
            return QApplication.translate("tilauscope_roast_setup", "event")

    # ── phase metrics ────────────────────────────────────────────────────────
    def _phase_pct(self, start_slot: int, end_slot: int) -> str:
        """Percentage of total roast (CHARGE→DROP) spanned start→end, as 'NN%'."""
        c, d = self._charge_idx(), self._slot_idx(6)
        a = self._slot_idx(start_slot) if start_slot >= 0 else c
        b = self._slot_idx(end_slot)
        if c < 0 or d < 0 or a < 0 or b < 0:
            return ""
        total = self._timex[d] - self._timex[c]
        if total <= 0:
            return ""
        return f"{(self._timex[b] - self._timex[a]) / total * 100:.0f}%"

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("readerCard")
        card.setStyleSheet(
            f"QFrame#readerCard {{ background-color: {THEME['BG']};"
            f"border: 2px solid {THEME['ACCENT']}; border-radius: 16px; }}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 10)
        cl.setSpacing(10)
        outer.addWidget(card)

        cl.addLayout(self._build_header())
        cl.addLayout(self._build_toolbar())
        cl.addWidget(_separator())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_navigator())
        splitter.addWidget(self._build_table())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 670])
        cl.addWidget(splitter, 1)

        # bottom row: hint + size grip
        bottom = QHBoxLayout()
        hint = QLabel(QApplication.translate(
            "tilauscope_roast_setup",
            "↑/↓ milestone  ·  click to jump  ·  double-click = center row"))
        hint.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px;")
        bottom.addWidget(hint)
        bottom.addStretch()
        grip = QSizeGrip(self)
        bottom.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        cl.addLayout(bottom)

        self._fill()

    def _fill(self) -> None:
        """Write the loaded profile into the widgets, replacing what they showed."""
        self._subtitle.setText(self._subtitle_text())
        self._summary.setText(self._summary_line())
        self._table.setUpdatesEnabled(False)
        try:
            self._populate_table()
        finally:
            self._table.setUpdatesEnabled(True)
        self._nav.clear()
        self._populate_navigator()
        self._apply_filter(self._filter_kind)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel(QApplication.translate("tilauscope_roast_setup", "DATA READER"))
        title.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: 800;"
            f"letter-spacing: 3px;")
        row.addWidget(title)

        self._subtitle = QLabel()
        self._subtitle.setProperty('variant', 'caption')
        row.addWidget(self._subtitle)
        row.addStretch()

        close = QPushButton("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(22, 22)
        close.setToolTip(QApplication.translate("Button", "Close"))
        close.setStyleSheet(
            f"QPushButton {{ background: {THEME['CRITICAL']}; color: {THEME['BG']};"
            f"border: none; border-radius: 11px; font-size: 12px; font-weight: bold; }} "
            f"QPushButton:hover {{ background: #FF6E8A; }}")
        close.clicked.connect(self.close)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _subtitle_text(self) -> str:
        bits = []
        if self._roast_title:
            bits.append(self._roast_title)
        rtype = canonical_roaster_name(str(self._p.get('roastertype', '') or ''))
        if rtype:
            bits.append(rtype)
        rdate = str(self._p.get('roastdate', '') or '')
        if rdate:
            bits.append(rdate)
        return "   " + "  ·  ".join(bits) if bits else ""

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self._summary = QLabel()
        self._summary.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 11px; ")
        row.addWidget(self._summary)
        row.addStretch()

        lbl = QLabel(QApplication.translate("Label", "Show"))
        lbl.setProperty('variant', 'caption')
        row.addWidget(lbl)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for key, text in (
            ('all',       QApplication.translate("tilauscope_common", "All")),
            ('milestone', QApplication.translate("tilauscope_roast_setup", "Milestones")),
            ('event',     QApplication.translate("Tab", "Events")),
        ):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty('filter_key', key)
            btn.setStyleSheet(
                f"QPushButton {{ background: {THEME['SURFACE']}; color: {THEME['SUBTEXT']};"
                f"border: 1px solid {THEME['BORDER']}; border-radius: 8px; padding: 3px 12px;"
                f"font-size: 11px; }} "
                f"QPushButton:checked {{ background: {THEME['ACCENT']}; color: {THEME['BG']};"
                f"border-color: {THEME['ACCENT']}; font-weight: bold; }}")
            if key == 'all':
                btn.setChecked(True)
            btn.clicked.connect(lambda _c, k=key: self._apply_filter(k))
            self._filter_group.addButton(btn)
            row.addWidget(btn)
        return row

    def _summary_line(self) -> str:
        parts = []
        c = self._charge_idx()
        if c >= 0:
            parts.append(QApplication.translate("tilauscope_roast_setup", "Charge {0}°").format(
                self._fmt_temp(self._t2[c])))
        d = self._slot_idx(6)
        if d >= 0:
            parts.append(QApplication.translate("tilauscope_roast_setup", "Drop {0}").format(
                self._mmss(self._timex[d] - self._origin)))
        dtr = self._phase_pct(2, 6)   # FC START → DROP
        if dtr:
            parts.append("DTR " + dtr)
        return "   ".join(parts)

    def _build_navigator(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(_section_label(QApplication.translate("tilauscope_roast_setup", "Journey")))
        self._nav = QListWidget()
        self._nav.setStyleSheet(
            f"QListWidget {{ background: {THEME['SURFACE']}; border: 1px solid {THEME['BORDER']};"
            f"border-radius: 8px; padding: 4px; }} "
            f"QListWidget::item {{ padding: 4px 6px; border-radius: 6px; }} "
            f"QListWidget::item:selected {{ background: {THEME['BORDER']}; }}")
        self._nav.currentItemChanged.connect(self._on_nav_changed)
        lay.addWidget(self._nav)
        return wrap

    def _build_table(self) -> QWidget:
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {THEME['SURFACE']}; color: {THEME['TEXT']};"
            f"border: 1px solid {THEME['BORDER']}; border-radius: 8px; gridline-color: {THEME['BORDER']};"
            f"alternate-background-color: #1b1b29; font-size: 11px; }} "
            f"QHeaderView::section {{ background: {THEME['BG']}; color: {THEME['SUBTEXT']};"
            f"border: none; border-bottom: 1px solid {THEME['BORDER']}; padding: 4px; }} "
            f"QTableWidget::item:selected {{ background: {THEME['ACCENT']}; color: {THEME['BG']}; }}")
        vh = self._table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        return self._table

    def _setup_columns(self) -> None:
        """Columns follow the profile: each roast brings its own extra devices."""
        cols = [QApplication.translate("Table", "Time"),
                "ET", "BT", "ΔET", "ΔBT",
                QApplication.translate("Label", "Marker")]
        self._extra_cols: list[tuple[int, int]] = []   # (extra_device_k, 1 or 2)
        for k in range(len(self._extratemp1)):
            n1 = self._extraname1[k] if k < len(self._extraname1) else ""
            n2 = self._extraname2[k] if k < len(self._extraname2) else ""
            if k < len(self._extratemp1):
                cols.insert(len(cols) - 1, n1 or f"x1-{k}")
                self._extra_cols.append((k, 1))
            if k < len(self._extratemp2):
                cols.insert(len(cols) - 1, n2 or f"x2-{k}")
                self._extra_cols.append((k, 2))

        self._marker_col = len(cols) - 1
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)

    def _populate_table(self) -> None:
        n = self._ndata
        # Emptied first so no item or hidden row of the previous roast survives.
        self._table.setRowCount(0)
        self._setup_columns()
        self._table.setRowCount(n)
        has_et = et_available_in_profile(self._p)
        self._table.setColumnHidden(1, not has_et)   # ET
        self._table.setColumnHidden(3, not has_et)   # ΔET
        # milestone row -> every (label, colour) marked on that sample
        ms_rows: dict[int, list[tuple[str, str]]] = {}
        for slot, (label, _icon, color) in enumerate(_MILESTONE_SLOTS):
            idx = self._slot_idx(slot)
            if idx >= 0:
                ms_rows.setdefault(idx, []).append((label, color))

        for i in range(n):
            rtime = QTableWidgetItem(self._mmss(self._timex[i] - self._origin))
            rtime.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            et = QTableWidgetItem(self._fmt_temp(self._t1[i]))
            bt = QTableWidgetItem(self._fmt_temp(self._t2[i]))
            det = QTableWidgetItem(self._ror(self._t1, i))
            dbt = QTableWidgetItem(self._ror(self._t2, i))
            for it in (et, bt, det, dbt):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._table.setItem(i, 0, rtime)
            self._table.setItem(i, 1, et)
            self._table.setItem(i, 2, bt)
            self._table.setItem(i, 3, det)
            self._table.setItem(i, 4, dbt)

            col = 5
            for (k, which) in self._extra_cols:
                series = self._extratemp1[k] if which == 1 else self._extratemp2[k]
                val = series[i] if i < len(series) else -1
                xi = QTableWidgetItem(self._fmt_temp(val))
                xi.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(i, col, xi)
                col += 1

            # A sample can carry several milestones and events: name them all.
            milestones = ms_rows.get(i, [])
            events = self._sev_at.get(i, [])
            parts = ["◆ " + label for label, _color in milestones]
            parts += ["▣ " + self._event_text(k) for k in events]
            mk = QTableWidgetItem("   ".join(parts))
            row_bg = None
            if milestones:
                self._row_kinds[i].add('milestone')
                row_bg = _ROW_MILESTONE_BG
                mk.setForeground(QColor(milestones[0][1]))
                font = mk.font(); font.setBold(True); mk.setFont(font)
            elif events:
                row_bg = _ROW_EVENT_BG
                mk.setForeground(QColor(THEME['WARNING']))
            if events:
                self._row_kinds[i].add('event')
            self._table.setItem(i, self._marker_col, mk)

            if row_bg is not None:
                for c in range(self._table.columnCount()):
                    it = self._table.item(i, c)
                    if it is not None:
                        it.setBackground(row_bg)

        header = self._table.horizontalHeader()
        if header is not None:
            self._table.resizeColumnsToContents()
            header.setStretchLastSection(True)

    def _ror(self, series: list[float], i: int) -> str:
        try:
            if i <= 0:
                return "--"
            dt = self._timex[i] - self._timex[i - 1]
            if not dt or series[i] == -1 or series[i - 1] == -1:
                return "--"
            return f"{60 * (series[i] - series[i - 1]) / dt:.1f}"
        except Exception:  # noqa: BLE001
            return "--"

    def _populate_navigator(self) -> None:
        entries: list[tuple[int, str, str, str, str]] = []   # row, icon, colour, label, sub

        if self._ndata:
            entries.append((0, "▸", THEME['SUBTEXT'],
                            QApplication.translate("tilauscope_roast_setup", "START"),
                            self._mmss(0) + "  ·  " +
                            QApplication.translate("tilauscope_roast_setup", "preheat")))

        tp = self._tp_idx()
        if tp >= 0:
            entries.append((tp, "▽", THEME['ACCENT'],
                            QApplication.translate("tilauscope_roast_setup", "TURNING POINT"),
                            self._mmss(self._timex[tp] - self._origin) +
                            "  ·  " + self._fmt_temp(self._t2[tp]) + "°"))

        # metric per milestone slot, prefixed with a short phase tag
        metric_for = {1: ("dry", self._phase_pct(-1, 1)),  # drying   (CHARGE→DRY END)
                      2: ("mai", self._phase_pct(1, 2)),    # maillard (DRY END→FC START)
                      6: ("dtr", self._phase_pct(2, 6))}    # dev/DTR  (FC START→DROP)
        for slot, (label, icon, color) in enumerate(_MILESTONE_SLOTS):
            idx = self._slot_idx(slot)
            if idx < 0:
                continue
            sub = self._mmss(self._timex[idx] - self._origin) + "  ·  " + \
                self._fmt_temp(self._t2[idx]) + "°"
            tag, m = metric_for.get(slot, ("", ""))
            if m:
                sub += "  ·  " + tag + " " + m
            entries.append((idx, icon, color, label, sub))

        entries.sort(key=lambda e: e[0])
        for row, icon, color, label, sub in entries:
            self._add_nav_item(row, icon, color, label, sub)

        # events section
        evs = sorted((r, k) for r, ks in self._sev_at.items() for k in ks)
        if evs:
            sep = QListWidgetItem(QApplication.translate(
                "tilauscope_roast_setup", "EVENTS ({0})").format(len(evs)))
            sep.setFlags(Qt.ItemFlag.NoItemFlags)
            sep.setForeground(QColor(THEME['SUBTEXT']))
            f = sep.font(); f.setBold(True); f.setPointSize(max(8, f.pointSize() - 1)); sep.setFont(f)
            self._nav.addItem(sep)
            for r, k in evs:
                self._add_nav_item(
                    r, "▣", THEME['WARNING'], self._event_text(k),
                    self._mmss(self._timex[r] - self._origin))

    def _add_nav_item(self, row: int, icon: str, color: str, label: str, sub: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, row)
        item.setData(_NAV_LABEL_ROLE, label)
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(8)
        ic = QLabel(icon)
        ic.setStyleSheet(f"color: {color}; font-size: 13px;")
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel(label)
        title.setStyleSheet(
            f"color: {THEME['TEXT']}; font-size: 12px; font-weight: bold;")
        col.addWidget(title)
        if sub:
            s = QLabel(sub)
            s.setStyleSheet(f"color: {THEME['SUBTEXT']}; font-size: 10px;")
            col.addWidget(s)
        lay.addLayout(col, 1)
        item.setSizeHint(w.sizeHint())
        self._nav.addItem(item)
        self._nav.setItemWidget(item, w)

    # ── interaction ──────────────────────────────────────────────────────────
    def _on_nav_changed(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        row = current.data(Qt.ItemDataRole.UserRole)
        if row is None or not (0 <= row < self._ndata):
            return
        self._table.selectRow(row)
        it = self._table.item(row, 0)
        if it is not None:
            self._table.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _nav_focus_label(self) -> str | None:
        item = self._nav.currentItem()
        return item.data(_NAV_LABEL_ROLE) if item is not None else None

    def _restore_nav_focus(self, label: str | None) -> None:
        if not label:
            return
        for i in range(self._nav.count()):
            item = self._nav.item(i)
            if item is not None and item.data(_NAV_LABEL_ROLE) == label:
                self._nav.setCurrentItem(item)
                return

    def _apply_filter(self, kind: str) -> None:
        self._filter_kind = kind
        for r in range(self._ndata):
            vis = (kind == 'all') or (kind in self._row_kinds[r])
            self._table.setRowHidden(r, not vis)

    # ── frameless drag ───────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self._drag_pos = None
        super().mouseReleaseEvent(event)

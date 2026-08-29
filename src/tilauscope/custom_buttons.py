"""TilauScope custom event-button editor.

A theme-native replacement for the dense ``EventsDlg`` Buttons table.  It writes
the same nine parallel arrays, so the roasting engine and the Artisan settings
format stay unchanged.

The canvas mirrors Artisan's own layout rules (``realignbuttons``): buttons fill
rows of ``buttonlistmaxlen``; a hidden button placed before the first visible one
takes no slot and is only reachable from an alarm; a hidden button placed among
the visible ones takes a slot, renders as a gap and splits the rounded group.
Those two roles get two different shapes here — a tray and a gap tile — so the
grouping is something the operator drags rather than something they discover.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import (
    QMimeData, QPoint, QSettings, QT_TRANSLATE_NOOP, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from tilauscope.button_labels import (
    MODE_OFFSET, MODE_PERCENT, MODE_SET, NO_EVENT, SEQUENCES,
    join_event_type, split_event_type, subst_button_label,
)
from tilauscope.button_layout import first_visible, round_codes, tray_and_rows
from tilauscope.theme_qss import apply_tilau_theme, tint, tooltip_qss
from tilauscope.tilauscope_types import THEME, no_enter_default, show_styled_message

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

_log: Final[logging.Logger] = logging.getLogger(__name__)


_MIME: Final[str] = 'application/x-tilau-button'
_DRAG_THRESHOLD: Final[int] = 6   # px, same feel as the alarm editor grip
_TILE_W: Final[int] = 96
_TILE_H: Final[int] = 44
#: A gap is drawn as the breathing space it produces on the bar, not as the
#: button-wide slot Artisan's own bar gives it.
_GAP_W: Final[int] = 24

# Action ids as Artisan stores them; 7 is unused. Labels are marked for
# extraction here and translated at display time — translate() only sees
# literals, never a loop variable.
_ACTION_IDS: Final[list[int]] = list(range(7)) + list(range(8, 26))
_ACTION_LABELS: Final[list[str]] = [
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'None'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Serial Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Call Program'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Multiple Event'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Modbus Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'DTA Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'IO Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Hottop Heater'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Hottop Fan'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Hottop Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'p-i-d'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Fuji Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'PWM Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'VOUT Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'S7 Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Aillio R1 Heater'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Aillio R1 Fan'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Aillio R1 Drum'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Aillio R1 Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Artisan Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'RC Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'WebSocket Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Stepper Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'Difluid Airwave Command'),
    QT_TRANSLATE_NOOP('tilauscope_buttons', 'TilauScope Ambient Command'),
]

# Fill colours offered as one click, paired with a text colour that stays legible.
_SWATCHES: Final[list[tuple[str, str]]] = [
    (THEME['BORDER'], THEME['TEXT']),
    (THEME['ACCENT'], THEME['BG']),
    (THEME['SUCCESS'], THEME['BG']),
    (THEME['WARNING'], THEME['BG']),
    (THEME['CRITICAL'], THEME['BG']),
    (THEME['MAUVE'], THEME['BG']),
    (THEME['TEAL'], THEME['BG']),
]


@dataclass
class ButtonSpec:
    label: str = ''
    description: str = ''
    event_type: int = NO_EVENT
    value: float = 0.0
    action: int = 0
    command: str = ''
    visible: bool = True
    background: str = '#808080'
    foreground: str = '#ffffff'


def _is_spacer(spec: ButtonSpec) -> bool:
    """A hidden button carrying nothing at all — it exists only to break a row.

    A hidden button that has a label, a command or an event is something else:
    a button someone configured and then took off the screen. Drawing the two
    the same way hides the second one behind the width of the first.
    """
    return not (spec.label or spec.command or spec.action
                or spec.event_type != NO_EVENT)


# ───────────────────────────────────────────────────────────────────────────
# _ButtonTile — one button as it will look on the roast screen
# ───────────────────────────────────────────────────────────────────────────

class _ButtonTile(QFrame):
    """A draggable preview of one button. Below the drag threshold a press is
    a selection; past it, the tile leaves for a new position."""

    clicked = pyqtSignal(int)

    def __init__(self, index: int, spec: ButtonSpec, face: str, caption: str,
                 round_code: int, selected: bool, gap: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.is_gap = gap
        self._press: QPoint | None = None
        self.setFixedWidth(_GAP_W if gap else _TILE_W)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        left = 10 if round_code in (1, 3) else 3
        right = 10 if round_code in (2, 3) else 3
        self.face = QLabel(face)
        self.face.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.face.setFixedHeight(_TILE_H)
        self.face.setWordWrap(False)
        if spec.visible:
            ring = f"2px solid {THEME['ACCENT']}" if selected else f"1px solid {THEME['BORDER']}"
            self.face.setStyleSheet(
                f"background:{spec.background}; color:{spec.foreground};"
                f"border:{ring};"
                f"border-top-left-radius:{left}px; border-bottom-left-radius:{left}px;"
                f"border-top-right-radius:{right}px; border-bottom-right-radius:{right}px;"
                f"font-size:12px; font-weight:bold;")
        else:
            ring = THEME['ACCENT'] if selected else THEME['SURFACE1']
            self.face.setStyleSheet(
                f"background:transparent; color:{THEME['OVERLAY0']};"
                f"border:1px dashed {ring}; border-radius:8px; font-size:11px;")
        lay.addWidget(self.face)

        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet(
            f"color:{THEME['OVERLAY1']}; font-size:10px; border:none; background:transparent;")
        self.set_caption('' if gap else caption)
        lay.addWidget(self.caption)

    def set_caption(self, text: str) -> None:
        """Fit the caption to the tile; an unelided one runs into its neighbour."""
        self.caption.setToolTip(text)
        metrics = QFontMetrics(self.caption.font())
        self.caption.setText(metrics.elidedText(
            text, Qt.TextElideMode.ElideRight, self.width() - 4))

    def mousePressEvent(self, a0) -> None:  # type: ignore[override]
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._press = a0.position().toPoint()
            a0.accept()

    def mouseMoveEvent(self, a0) -> None:  # type: ignore[override]
        if (a0 is not None and self._press is not None
                and (a0.position().toPoint() - self._press).manhattanLength() > _DRAG_THRESHOLD):
            self._press = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(_MIME, str(self.index).encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, a0) -> None:  # type: ignore[override]
        if self._press is not None:
            self._press = None
            self.clicked.emit(self.index)
        if a0 is not None:
            a0.accept()


# ───────────────────────────────────────────────────────────────────────────
# _Canvas — the scroll body: rows, tray, and the insertion caret
# ───────────────────────────────────────────────────────────────────────────

class _Canvas(QWidget):
    """Holds the row blocks and reports drops as a target index.

    Bands are the drop geometry, in canvas coordinates: one per row plus one
    for the tray. They are published after the layout has run, because a
    widget has no real geometry before that.
    """

    dropRequested = pyqtSignal(int, int, bool)   # source index, target index, into tray

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        # (top, bottom, slots as (x, width), start index, is tray)
        self._bands: list[tuple[int, int, list[tuple[int, int]], int, bool]] = []
        self._caret = QFrame(self)
        self._caret.setFixedWidth(2)
        self._caret.setStyleSheet(f"background:{THEME['ACCENT']}; border:none;")
        self._caret.hide()

    def set_bands(self, bands: list[tuple[int, int, list[tuple[int, int]], int, bool]]) -> None:
        self._bands = bands

    def _resolve(self, pos: QPoint) -> tuple[int, bool, int, int, int]:
        """Return (target index, into tray, caret x, caret y, caret height)."""
        if not self._bands:
            return 0, False, 0, 0, 0
        band = min(self._bands, key=lambda b: 0 if b[0] <= pos.y() <= b[1]
                   else min(abs(pos.y() - b[0]), abs(pos.y() - b[1])))
        top, bottom, slots, start, is_tray = band
        height = max(8, bottom - top)
        if not slots:
            return start, is_tray, 8, top, height
        for offset, (x, width) in enumerate(slots):
            if pos.x() < x + width // 2:
                return start + offset, is_tray, max(0, x - 2), top, height
        last_x, last_w = slots[-1]
        return start + len(slots), is_tray, last_x + last_w, top, height

    def dragEnterEvent(self, a0) -> None:  # type: ignore[override]
        if a0 is not None and a0.mimeData() is not None and a0.mimeData().hasFormat(_MIME):
            a0.acceptProposedAction()

    def dragMoveEvent(self, a0) -> None:  # type: ignore[override]
        if a0 is None or a0.mimeData() is None or not a0.mimeData().hasFormat(_MIME):
            return
        _, _, x, y, height = self._resolve(a0.position().toPoint())
        self._caret.setGeometry(x, y, 2, height)
        self._caret.show()
        self._caret.raise_()
        a0.acceptProposedAction()

    def dragLeaveEvent(self, a0) -> None:  # type: ignore[override]
        del a0
        self._caret.hide()

    def dropEvent(self, a0) -> None:  # type: ignore[override]
        self._caret.hide()
        if a0 is None or a0.mimeData() is None or not a0.mimeData().hasFormat(_MIME):
            return
        try:
            src = int(bytes(a0.mimeData().data(_MIME)).decode())
        except (ValueError, TypeError):
            return
        target, to_tray, _, _, _ = self._resolve(a0.position().toPoint())
        self.dropRequested.emit(src, target, to_tray)
        a0.acceptProposedAction()


# ───────────────────────────────────────────────────────────────────────────
# CustomButtonManager
# ───────────────────────────────────────────────────────────────────────────

class CustomButtonManager(QDialog):
    """Canvas-and-inspector editor over Artisan's custom-button model."""

    def __init__(self, parent: QWidget, aw: ApplicationWindow) -> None:
        super().__init__(parent)
        apply_tilau_theme(self, ground=False)
        self.aw = aw
        self._loading = False
        self._selected = -1
        self._tiles: dict[int, _ButtonTile] = {}
        self._preview_pressed = False
        self._rows = self._read_rows()
        self.oldPos: QPoint | None = None
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(QApplication.translate('tilauscope_buttons', 'Custom buttons'))
        self._expert = QSettings().value(
            'tilauscope/operator_level', 'guided', type=str) == 'expert'
        self._build_ui()
        settings = QSettings()
        if settings.contains('TilauCustomButtonsGeometry'):
            self.restoreGeometry(settings.value('TilauCustomButtonsGeometry'))
        else:
            self.resize(880, 680)
        self._select(0 if self._rows else -1)

        # Return must not reach the ✕ / Cancel this dialog builds first
        # (tilauscope_types.no_enter_default).
        no_enter_default(self)

    # ── construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{THEME['BG']}; border:1px solid {THEME['BORDER']};"
            ' border-radius:16px; }' + tooltip_qss())
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(QApplication.translate('tilauscope_buttons', 'Custom buttons').upper())
        title.setStyleSheet(
            f"color:{THEME['ACCENT']}; font-size:16px; font-weight:900;"
            ' letter-spacing:2px; border:none;')
        close = QPushButton('✕')
        close.setFixedSize(28, 28)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.reject)
        close.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:14px; }}"
            f"QPushButton:hover {{ background:{THEME['CRITICAL']}; color:{THEME['BG']}; }}")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        root.addLayout(header)

        subtitle = QLabel(QApplication.translate(
            'tilauscope_buttons', 'The buttons you press during a roast. Drag one to move it.'))
        subtitle.setStyleSheet(
            f"color:{THEME['SUBTEXT']}; font-size:11px; border:none;")
        root.addWidget(subtitle)

        root.addLayout(self._build_toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet('QScrollArea { background: transparent; border: none; }')
        self.canvas = _Canvas()
        self.canvas_lay = QVBoxLayout(self.canvas)
        self.canvas_lay.setContentsMargins(0, 0, 6, 0)
        self.canvas_lay.setSpacing(10)
        self.canvas.dropRequested.connect(self._on_drop)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        root.addWidget(self._build_inspector())

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton(QApplication.translate('tilauscope_buttons', 'Cancel'))
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.setMinimumWidth(100)
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:8px; padding:7px 16px;"
            ' font-size:12px; }')
        save = QPushButton(QApplication.translate('tilauscope_buttons', 'Apply'))
        save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        save.setMinimumWidth(110)
        save.clicked.connect(self._apply)
        save.setStyleSheet(
            f"QPushButton {{ background:{THEME['ACCENT']}; color:{THEME['BG']};"
            'border:none; border-radius:8px; padding:7px 16px;'
            ' font-size:12px; font-weight:bold; }')
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

        self._rebuild_canvas()

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._btn_add = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Add button'), self._add, THEME['SUCCESS'])
        self._btn_dup = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Duplicate'), self._duplicate)
        self._btn_gap = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Add gap'), self._add_gap)
        self._btn_gap.setToolTip(QApplication.translate(
            'tilauscope_buttons', 'Leaves an empty slot that splits the row into two groups.'))
        self._btn_del = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Delete'), self._delete, THEME['CRITICAL'])
        for b in (self._btn_add, self._btn_dup, self._btn_gap, self._btn_del):
            bar.addWidget(b)
        bar.addStretch()

        caption = QLabel(QApplication.translate('tilauscope_buttons', 'Buttons per row'))
        caption.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px; border:none;")
        bar.addWidget(caption)
        self.max_per_row = QSpinBox()
        self.max_per_row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.max_per_row.setRange(self.aw.buttonpalettemaxlen_min,
                                  self.aw.buttonpalettemaxlen_max)
        self.max_per_row.setValue(int(self.aw.buttonlistmaxlen))
        self.max_per_row.setStyleSheet(
            f"QSpinBox {{ background:{THEME['BG']}; color:{THEME['TEXT']};"
            f"border:1px solid {THEME['SURFACE1']}; border-radius:6px; padding:2px 6px;"
            ' font-size:11px; }')
        self.max_per_row.valueChanged.connect(lambda _v: self._rebuild_canvas())
        bar.addWidget(self.max_per_row)
        return bar

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame#inspector {{ background:{THEME['SURFACE']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:12px; }}")
        panel.setObjectName('inspector')
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        heading = QLabel(QApplication.translate('tilauscope_buttons', 'Selected button').upper())
        heading.setStyleSheet(
            f"color:{THEME['OVERLAY2']}; font-size:10px; font-weight:bold;"
            ' letter-spacing:1.5px; border:none;')
        lay.addWidget(heading)

        # line 1 — the text and what it renders as
        line1 = QHBoxLayout()
        line1.setSpacing(8)
        line1.addWidget(self._caption(QApplication.translate('tilauscope_buttons', 'Button text')))
        self.label = QLineEdit()
        self.label.setStyleSheet(self._edit_qss())
        line1.addWidget(self.label, 1)
        self._btn_insert = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Insert') + '  ▾', self._show_insert_menu)
        line1.addWidget(self._btn_insert)
        lay.addLayout(line1)

        line2 = QHBoxLayout()
        line2.setSpacing(8)
        line2.addWidget(self._caption(QApplication.translate('tilauscope_buttons', 'Shows as')))
        self.rendered = QLabel()
        self.rendered.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:12px; font-weight:bold; border:none;")
        line2.addWidget(self.rendered, 1)
        self._state_released = self._state_btn(
            QApplication.translate('tilauscope_buttons', 'released'), False)
        self._state_pressed = self._state_btn(
            QApplication.translate('tilauscope_buttons', 'pressed'), True)
        line2.addWidget(self._state_released)
        line2.addWidget(self._state_pressed)
        lay.addLayout(line2)

        line3 = QHBoxLayout()
        line3.setSpacing(8)
        line3.addWidget(self._caption(QApplication.translate('tilauscope_buttons', 'Hover hint')))
        self.description = QLineEdit()
        self.description.setStyleSheet(self._edit_qss())
        self.description.setPlaceholderText(QApplication.translate(
            'tilauscope_buttons', 'What this button does, shown when the operator hovers it'))
        line3.addWidget(self.description, 1)
        lay.addLayout(line3)

        # line 4 — colours
        line4 = QHBoxLayout()
        line4.setSpacing(8)
        line4.addWidget(self._caption(QApplication.translate('tilauscope_buttons', 'Colours')))
        self.bg = QPushButton(QApplication.translate('tilauscope_buttons', 'fill'))
        self.fg = QPushButton(QApplication.translate('tilauscope_buttons', 'text'))
        self.bg.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fg.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bg.setFixedWidth(76)
        self.fg.setFixedWidth(76)
        self.bg.clicked.connect(lambda: self._pick_color(False))
        self.fg.clicked.connect(lambda: self._pick_color(True))
        line4.addWidget(self.bg)
        line4.addWidget(self.fg)
        for fill, text in _SWATCHES:
            sw = QPushButton()
            sw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            sw.setFixedSize(20, 20)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setStyleSheet(
                f"QPushButton {{ background:{fill}; border:1px solid {THEME['BORDER']};"
                'border-radius:5px; }'
                f"QPushButton:hover {{ border:1px solid {THEME['TEXT']}; }}")
            sw.clicked.connect(lambda _c=False, f=fill, t=text: self._set_colors(f, t))
            line4.addWidget(sw)
        line4.addStretch()
        lay.addLayout(line4)

        # line 5 — what the press records
        line5 = QHBoxLayout()
        line5.setSpacing(8)
        line5.addWidget(self._caption(QApplication.translate('tilauscope_buttons', 'Records')))
        self.event_name = QComboBox()
        self.event_name.setStyleSheet(self._combo_qss())
        self.event_name.addItem(QApplication.translate('tilauscope_buttons', 'Nothing'))
        for name in self.aw.qmc.etypes[:4]:
            self.event_name.addItem(name)
        self.event_mode = QComboBox()
        self.event_mode.setStyleSheet(self._combo_qss())
        self.event_mode.addItem(QApplication.translate('tilauscope_buttons', 'set to'))
        self.event_mode.addItem(QApplication.translate('tilauscope_buttons', 'change by'))
        self.event_mode.addItem(QApplication.translate('tilauscope_buttons', 'change by % of'))
        self.value = QLineEdit()
        self.value.setStyleSheet(self._edit_qss())
        self.value.setFixedWidth(70)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        line5.addWidget(self.event_name)
        line5.addWidget(self.event_mode)
        line5.addWidget(self.value)
        line5.addStretch()
        self.visible = QCheckBox(QApplication.translate('tilauscope_buttons', 'Show on roast screen'))
        self.visible.setStyleSheet(f"color:{THEME['TEXT']}; font-size:11px; border:none;")
        line5.addWidget(self.visible)
        lay.addLayout(line5)

        # line 6 — the machine command, folded away unless the operator is Expert
        self._advanced_toggle = QPushButton()
        self._advanced_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._advanced_toggle.setStyleSheet(
            f"QPushButton {{ color:{THEME['SUBTEXT']}; background:transparent; border:none;"
            ' font-size:11px; text-align:left; padding:0; }'
            f"QPushButton:hover {{ color:{THEME['TEXT']}; }}")
        self._advanced_toggle.clicked.connect(self._toggle_advanced)
        lay.addWidget(self._advanced_toggle)

        self._advanced = QWidget()
        adv = QHBoxLayout(self._advanced)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(8)
        self.action = QComboBox()
        self.action.setStyleSheet(self._combo_qss())
        self.action.addItems([QApplication.translate('tilauscope_buttons', x) for x in _ACTION_LABELS])
        self.command = QLineEdit()
        self.command.setStyleSheet(self._edit_qss())
        self.command.setPlaceholderText(QApplication.translate(
            'tilauscope_buttons', 'Command sent to the machine — {} is replaced by the event value'))
        adv.addWidget(self.action)
        adv.addWidget(self.command, 1)
        lay.addWidget(self._advanced)
        self._advanced.setVisible(self._expert)
        self._sync_advanced_toggle()

        for widget in (self.label, self.description, self.value, self.command):
            widget.textChanged.connect(self._store_form)
        self.event_name.currentIndexChanged.connect(self._store_form)
        self.event_mode.currentIndexChanged.connect(self._store_form)
        self.action.currentIndexChanged.connect(self._store_form)
        self.visible.toggled.connect(self._on_visibility_toggled)
        return panel

    # ── small styled parts ────────────────────────────────────────────────

    @staticmethod
    def _edit_qss() -> str:
        return (f"QLineEdit {{ background:{THEME['BG']}; color:{THEME['TEXT']};"
                f"border:1px solid {THEME['SURFACE1']}; border-radius:6px;"
                ' padding:4px 8px; font-size:12px; }'
                f"QLineEdit:focus {{ border:1px solid {THEME['ACCENT']}; }}")

    @staticmethod
    def _combo_qss() -> str:
        return (f"QComboBox {{ background:{THEME['BG']}; color:{THEME['TEXT']};"
                f"border:1px solid {THEME['SURFACE1']}; border-radius:6px;"
                ' padding:3px 8px; font-size:12px; }'
                f"QComboBox QAbstractItemView {{ background:{THEME['SURFACE']};"
                f"color:{THEME['TEXT']}; selection-background-color:{THEME['ACCENT']};"
                f"selection-color:{THEME['BG']}; border:1px solid {THEME['BORDER']}; }}")

    @staticmethod
    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedWidth(96)
        lbl.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px; border:none;")
        return lbl

    def _tool_btn(self, text: str, slot, accent: str | None = None) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(slot)
        col = accent or THEME['TEXT']
        btn.setStyleSheet(
            f"QPushButton {{ background:{THEME['SURFACE']}; color:{col};"
            f"border:1px solid {THEME['BORDER']}; border-radius:7px;"
            ' padding:5px 11px; font-size:11px; }'
            f"QPushButton:hover {{ border-color:{col}; }}"
            f"QPushButton:disabled {{ color:{THEME['OVERLAY0']}; }}")
        return btn

    def _state_btn(self, text: str, pressed_state: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, s=pressed_state: self._set_preview_state(s))
        btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{THEME['OVERLAY1']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:6px;"
            ' padding:2px 8px; font-size:10px; }'
            f"QPushButton:checked {{ background:{tint('ACCENT', 0.14)};"
            f"color:{THEME['ACCENT']}; border-color:{THEME['ACCENT']}; }}")
        btn.setChecked(pressed_state == self._preview_pressed)
        return btn

    # ── canvas ────────────────────────────────────────────────────────────

    def _face_text(self, spec: ButtonSpec, state: int = 0) -> str:
        text = subst_button_label(spec.label, spec.event_type, self.aw.qmc.etypes,
                                  spec.value, self.aw.qmc.mode, state)
        return text or QApplication.translate('tilauscope_buttons', 'Untitled')

    def _caption_text(self, spec: ButtonSpec) -> str:
        etype, mode = split_event_type(spec.event_type)
        parts: list[str] = []
        if etype < 0:
            parts.append(QApplication.translate('tilauscope_buttons', 'no event'))
        else:
            name = self.aw.qmc.etypes[etype] if etype < len(self.aw.qmc.etypes) else ''
            value = self.aw.qmc.eventsInternal2ExternalValue(spec.value)
            if mode == MODE_SET:
                parts.append(f'{name} → {value}')
            elif mode == MODE_OFFSET:
                parts.append(f'{name} {value:+}')
            else:
                parts.append(f'{name} {value:+} %')
        if spec.action:
            index = _ACTION_IDS.index(spec.action) if spec.action in _ACTION_IDS else 0
            parts.append(QApplication.translate('tilauscope_buttons', _ACTION_LABELS[index]))
        return ' · '.join(parts)

    def _clear_canvas(self) -> None:
        while self.canvas_lay.count():
            item = self.canvas_lay.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_canvas(self) -> None:
        self._clear_canvas()
        self._tiles = {}
        if not self._rows:
            self.canvas_lay.addWidget(self._build_empty_state())
            self.canvas.set_bands([])
            self._sync_toolbar()
            return

        per_row = self.max_per_row.value()
        first = first_visible(self._rows)
        codes = round_codes(self._rows, per_row, first)
        tray_specs, chunks = tray_and_rows(self._rows, per_row)
        blocks: list[tuple[QWidget, list[_ButtonTile], int, bool]] = []

        for chunk_no, indices in enumerate(chunks):
            block, tiles = self._build_row_block(
                QApplication.translate('tilauscope_buttons', 'Row {0}').format(chunk_no + 1),
                per_row - len(indices), indices, codes)
            blocks.append((block, tiles, indices[0] if indices else first, False))

        if tray_specs:
            block, tiles = self._build_tray_block(tray_specs, codes)
            blocks.append((block, tiles, 0, True))

        for block, _tiles, _start, _tray in blocks:
            self.canvas_lay.addWidget(block)
        self.canvas_lay.addStretch(1)

        def _publish() -> None:
            bands = []
            try:
                for block, tiles, start, is_tray in blocks:
                    top = block.mapTo(self.canvas, QPoint(0, 0)).y()
                    slots = [(t.mapTo(self.canvas, QPoint(0, 0)).x(), t.width())
                             for t in tiles]
                    bands.append((top, top + block.height(), slots, start, is_tray))
            except RuntimeError:
                return  # a newer rebuild already dropped these widgets
            self.canvas.set_bands(bands)

        self.canvas.set_bands([])
        # a widget has no real geometry until the layout has run
        QTimer.singleShot(0, _publish)
        self._sync_toolbar()

    def _build_empty_state(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background:{THEME['SURFACE']}; border:1px dashed {THEME['BORDER']};"
            ' border-radius:12px; }')
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 28, 20, 28)
        lay.setSpacing(8)
        title = QLabel(QApplication.translate('tilauscope_buttons', 'No custom buttons yet.'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:{THEME['TEXT']}; font-size:13px; font-weight:bold; border:none;")
        body = QLabel(QApplication.translate(
            'tilauscope_buttons', 'Custom buttons record an event or drive the machine '
                  'with one press during the roast.'))
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{THEME['SUBTEXT']}; font-size:11px; border:none;")
        action = self._tool_btn(
            QApplication.translate('tilauscope_buttons', 'Add your first button'), self._add,
            THEME['ACCENT'])
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(action)
        row.addStretch()
        lay.addWidget(title)
        lay.addWidget(body)
        lay.addLayout(row)
        return panel

    def _build_row_block(self, heading: str, free: int, indices: list[int],
                         codes: list[int]) -> tuple[QWidget, list[_ButtonTile]]:
        block = QFrame()
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.addWidget(self._eyebrow(heading))
        head.addStretch()
        head.addWidget(self._eyebrow(
            QApplication.translate('tilauscope_buttons', '{0} slots free').format(free)
            if free else QApplication.translate('tilauscope_buttons', 'row full')))
        lay.addLayout(head)

        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        tiles = self._make_tiles(indices, codes, strip)
        strip.addStretch(1)
        lay.addLayout(strip)
        return block, tiles

    def _build_tray_block(self, indices: list[int],
                          codes: list[int]) -> tuple[QWidget, list[_ButtonTile]]:
        block = QFrame()
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._eyebrow(QApplication.translate(
            'tilauscope_buttons', 'Not on the roast screen — triggered by alarms only')))
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(6)
        tiles = self._make_tiles(indices, codes, strip)
        strip.addStretch(1)
        lay.addLayout(strip)
        return block, tiles

    def _make_tiles(self, indices: list[int], codes: list[int],
                    strip: QHBoxLayout) -> list[_ButtonTile]:
        tiles: list[_ButtonTile] = []
        for i in indices:
            spec = self._rows[i]
            gap = self._is_gap(i)
            face = '' if gap else (self._face_text(spec) if spec.visible
                                   else spec.label or QApplication.translate(
                                       'tilauscope_buttons', 'hidden'))
            tile = _ButtonTile(i, spec, face, self._caption_text(spec),
                               codes[i], i == self._selected, gap=gap)
            tile.clicked.connect(self._select)
            tile.setToolTip(spec.description or (
                QApplication.translate('tilauscope_buttons',
                                       'Gap — splits the row into two groups')
                if gap else ''))
            self._tiles[i] = tile
            tiles.append(tile)
            strip.addWidget(tile)
        return tiles

    @staticmethod
    def _eyebrow(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{THEME['OVERLAY2']}; font-size:10px; font-weight:bold;"
            ' letter-spacing:1.2px; border:none; background:transparent;')
        return lbl

    # ── model ─────────────────────────────────────────────────────────────

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

    def _select(self, index: int) -> None:
        self._selected = index if 0 <= index < len(self._rows) else -1
        self._load_form()
        self._rebuild_canvas()

    def _load_form(self) -> None:
        index = self._selected
        enabled = 0 <= index < len(self._rows)
        self._set_form_enabled(enabled)
        if not enabled:
            self.rendered.setText('')
            return
        self._loading = True
        row = self._rows[index]
        self.label.setText(row.label.replace('\n', '\\n'))
        self.description.setText(row.description)
        etype, mode = split_event_type(row.event_type)
        self.event_name.setCurrentIndex(etype + 1 if etype >= 0 else 0)
        self.event_mode.setCurrentIndex(
            {MODE_SET: 0, MODE_OFFSET: 1, MODE_PERCENT: 2}[mode])
        self.event_mode.setEnabled(etype >= 0)
        self.value.setEnabled(etype >= 0)
        self.value.setText(self.aw.qmc.eventsvalues(row.value))
        self.action.setCurrentIndex(
            _ACTION_IDS.index(row.action) if row.action in _ACTION_IDS else 0)
        self.command.setText(row.command)
        self.visible.setChecked(row.visible)
        self.bg.setStyleSheet(self._swatch_qss(row.background))
        self.fg.setStyleSheet(self._swatch_qss(row.foreground))
        self._loading = False
        self._refresh_rendered()
        self._sync_advanced_toggle()

    def _store_form(self, *_args: object) -> None:
        if self._loading or not 0 <= self._selected < len(self._rows):
            return
        row = self._rows[self._selected]
        row.label = self.label.text().replace('\\n', '\n')
        row.description = self.description.text()
        etype = self.event_name.currentIndex() - 1
        mode = [MODE_SET, MODE_OFFSET, MODE_PERCENT][self.event_mode.currentIndex()]
        row.event_type = join_event_type(etype, mode)
        self.event_mode.setEnabled(etype >= 0)
        self.value.setEnabled(etype >= 0)
        try:
            row.value = self.aw.qmc.str2eventsvalue(self.value.text().strip())
        except (ValueError, TypeError):
            pass
        row.action = _ACTION_IDS[self.action.currentIndex()]
        row.command = self.command.text()
        self._refresh_rendered()
        self._sync_advanced_toggle()
        # keystrokes only change the selected tile: repainting the whole canvas
        # on every one would rebuild every widget under the cursor
        self._refresh_selected_tile()

    def _on_visibility_toggled(self, checked: bool) -> None:
        if self._loading or not 0 <= self._selected < len(self._rows):
            return
        self._rows[self._selected].visible = checked
        self._rebuild_canvas()

    def _is_gap(self, index: int) -> bool:
        """True when the tile at ``index`` is drawn as a bare separator.

        Only inside the rows: in the tray a hidden button is a real button.
        """
        spec = self._rows[index]
        return (not spec.visible and index >= first_visible(self._rows)
                and _is_spacer(spec))

    def _refresh_selected_tile(self) -> None:
        tile = self._tiles.get(self._selected)
        if tile is None:
            return
        if tile.is_gap != self._is_gap(self._selected):
            # The first character typed into a separator turns it into a
            # button; it has to grow on the spot rather than at the next
            # structural change, which is when the confusion would have set in.
            self._rebuild_canvas()
            return
        if tile.is_gap:
            return
        spec = self._rows[self._selected]
        tile.face.setText(self._face_text(spec) if spec.visible else spec.label)
        tile.set_caption(self._caption_text(spec))
        tile.setToolTip(spec.description)

    def _refresh_rendered(self) -> None:
        if not 0 <= self._selected < len(self._rows):
            self.rendered.setText('')
            return
        row = self._rows[self._selected]
        text = self._face_text(row, 1 if self._preview_pressed else 0)
        self.rendered.setText(text.replace('\n', ' ⏎ '))

    def _set_preview_state(self, pressed: bool) -> None:
        self._preview_pressed = pressed
        self._state_released.setChecked(not pressed)
        self._state_pressed.setChecked(pressed)
        self._refresh_rendered()

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (self.label, self.description, self.event_name, self.event_mode,
                       self.value, self.action, self.command, self.visible,
                       self.bg, self.fg, self._btn_insert, self._advanced_toggle,
                       self._state_released, self._state_pressed):
            widget.setEnabled(enabled)

    def _sync_toolbar(self) -> None:
        has_selection = 0 <= self._selected < len(self._rows)
        self._btn_dup.setEnabled(has_selection)
        self._btn_del.setEnabled(has_selection)
        self._btn_add.setEnabled(len(self._rows) < self._limit())
        self._btn_gap.setEnabled(len(self._rows) < self._limit() and any(
            r.visible for r in self._rows))

    def _limit(self) -> int:
        rows = getattr(self.aw, 'NUMBER_OF_EXTRABUTTON_ROWS', 10)
        return int(rows) * int(self.max_per_row.value())

    # ── colours ───────────────────────────────────────────────────────────

    @staticmethod
    def _swatch_qss(colour: str) -> str:
        return (f"QPushButton {{ background:{colour}; color:{THEME['BG']};"
                f"border:1px solid {THEME['BORDER']}; border-radius:6px;"
                ' padding:4px 8px; font-size:10px; font-weight:bold; }'
                f"QPushButton:hover {{ border-color:{THEME['TEXT']}; }}")

    def _set_colors(self, fill: str, text: str) -> None:
        if not 0 <= self._selected < len(self._rows):
            return
        row = self._rows[self._selected]
        row.background, row.foreground = fill, text
        self.bg.setStyleSheet(self._swatch_qss(fill))
        self.fg.setStyleSheet(self._swatch_qss(text))
        self._rebuild_canvas()

    def _pick_color(self, foreground: bool) -> None:
        if not 0 <= self._selected < len(self._rows):
            return
        row = self._rows[self._selected]
        current = row.foreground if foreground else row.background
        colour = QColorDialog.getColor(QColor(current), self)
        if colour.isValid():
            if foreground:
                self._set_colors(row.background, colour.name())
            else:
                self._set_colors(colour.name(), row.foreground)

    # ── the Insert menu ───────────────────────────────────────────────────

    def _show_insert_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{THEME['SURFACE']}; color:{THEME['TEXT']};"
            f"border:1px solid {THEME['BORDER']}; border-radius:8px; padding:4px; }}"
            'QMenu::item { padding:4px 22px 4px 12px; border-radius:5px; font-size:11px; }'
            f"QMenu::item:selected {{ background:{THEME['ACCENT']}; color:{THEME['BG']}; }}"
            f"QMenu::separator {{ height:1px; background:{THEME['BORDER']}; margin:4px 8px; }}")
        current = ''
        for seq in SEQUENCES:
            group = QApplication.translate('tilauscope_buttons', seq.group)
            if group != current:
                if current:
                    menu.addSeparator()
                current = group
                heading = menu.addAction(group)
                if heading is not None:
                    heading.setEnabled(False)
            act = menu.addAction(QApplication.translate('tilauscope_buttons', seq.name))
            if act is not None:
                act.triggered.connect(lambda _c=False, code=seq.code: self._insert(code))
        menu.exec(self._btn_insert.mapToGlobal(
            QPoint(0, self._btn_insert.height())))

    def _insert(self, code: str) -> None:
        self.label.insert(code)
        self.label.setFocus()

    def _toggle_advanced(self) -> None:
        self._advanced.setVisible(not self._advanced.isVisible())
        self._sync_advanced_toggle()

    def _sync_advanced_toggle(self) -> None:
        arrow = '▾' if self._advanced.isVisible() else '▸'
        title = QApplication.translate('tilauscope_buttons', 'Machine command')
        if self._advanced.isVisible():
            self._advanced_toggle.setText(f'{arrow}  {title}')
            return
        index = 0
        if 0 <= self._selected < len(self._rows):
            action = self._rows[self._selected].action
            index = _ACTION_IDS.index(action) if action in _ACTION_IDS else 0
        summary = (QApplication.translate('tilauscope_buttons', 'none') if index == 0
                   else QApplication.translate('tilauscope_buttons', _ACTION_LABELS[index]))
        self._advanced_toggle.setText(f'{arrow}  {title} — {summary}')

    # ── structural edits ──────────────────────────────────────────────────

    def _add(self) -> None:
        if len(self._rows) >= self._limit():
            return
        self._rows.append(ButtonSpec(label='E'))
        self._select(len(self._rows) - 1)

    def _add_gap(self) -> None:
        if len(self._rows) >= self._limit():
            return
        first = first_visible(self._rows)
        at = self._selected + 1 if self._selected >= 0 else len(self._rows)
        at = max(at, first + 1)
        self._rows.insert(min(at, len(self._rows)), ButtonSpec(visible=False))
        self._select(min(at, len(self._rows) - 1))

    def _duplicate(self) -> None:
        if not 0 <= self._selected < len(self._rows):
            return
        self._rows.insert(self._selected + 1, ButtonSpec(**vars(self._rows[self._selected])))
        self._select(self._selected + 1)

    def _delete(self) -> None:
        if not 0 <= self._selected < len(self._rows):
            return
        answer = show_styled_message(
            self, QApplication.translate('tilauscope_buttons', 'Delete this button?'),
            QApplication.translate(
                'tilauscope_buttons', 'It is removed from the roast screen right away.'),
            buttons=[QApplication.translate('tilauscope_buttons', 'Cancel'),
                     QApplication.translate('tilauscope_buttons', 'Delete')])
        if answer != 1:
            return
        self._rows.pop(self._selected)
        self._select(min(self._selected, len(self._rows) - 1))

    def _on_drop(self, src: int, target: int, to_tray: bool) -> None:
        if not 0 <= src < len(self._rows):
            return
        was_tray = src < first_visible(self._rows)
        spec = self._rows.pop(src)
        if target > src:
            target -= 1
        target = max(0, min(target, len(self._rows)))
        # Visibility only flips when the button crosses between the tray and the
        # rows; a gap dragged inside the rows stays a gap.
        if to_tray and not was_tray:
            spec.visible = False
        elif was_tray and not to_tray:
            spec.visible = True
        self._rows.insert(target, spec)
        self._select(target)

    # ── save ──────────────────────────────────────────────────────────────

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
        # realignbuttons rebuilds the bar from the arrays; settooltip must follow
        # it because it reads aw.buttonlist, which realignbuttons repopulates.
        self.aw.realignbuttons()
        self.aw.settooltip()
        self.aw.update_extraeventbuttons_visibility()
        # realignbuttons only rebuilds Artisan's own bar. TilauScope's floating
        # bar is a separate set of widgets built once from the same arrays, so
        # it stays on the previous buttons until it is told to rebuild — which
        # Artisan's Events dialog does on OK and this one has to do as well.
        tilau = getattr(self.aw, 'tilauscope_main', None)
        if tilau is not None:
            try:
                tilau.update_events_from_artisan()
            except Exception:  # pylint: disable=broad-except
                # An apply that reached here has already written every array;
                # a bar that failed to redraw must not take the dialog with it.
                _log.exception('could not rebuild the TilauScope button bar')
        self.accept()

    # ── frameless window ──────────────────────────────────────────────────

    def mousePressEvent(self, a0) -> None:  # type: ignore[override]
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.oldPos = a0.globalPosition().toPoint()

    def mouseMoveEvent(self, a0) -> None:  # type: ignore[override]
        if a0 is not None and self.oldPos is not None:
            delta = a0.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = a0.globalPosition().toPoint()

    def mouseReleaseEvent(self, a0) -> None:  # type: ignore[override]
        del a0
        self.oldPos = None

    def done(self, result: int) -> None:
        QSettings().setValue('TilauCustomButtonsGeometry', self.saveGeometry())
        super().done(result)


def open_custom_button_manager(aw: ApplicationWindow) -> None:
    """Menu entry point."""
    CustomButtonManager(aw, aw).exec()

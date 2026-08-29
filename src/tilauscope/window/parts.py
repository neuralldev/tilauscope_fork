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

"""The window's own parts: widgets that do know about Artisan.

Unlike tilauscope.widgets, these read the running session — the event
buttons Artisan is configured with, the extra devices it is sampling, the
sliders it publishes. They belong to the window, not to a widget library.
"""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)
from artisanlib.main import ApplicationWindow
from artisanlib.util import (
    events_internal_to_external_value,
    rgba_colorname2argb_colorname,
)
from dataclasses import dataclass, field
from mashumaro import DataClassDictMixin
from tilauscope.button_labels import subst_button_label
from tilauscope.button_layout import corner_radii, split_groups, tray_and_rows
from tilauscope.graph.common import dimmed
from tilauscope.theme_qss import tint, tooltip_qss, with_tooltip
from tilauscope.tilauscope_types import THEME
from tilauscope.widgets.flow_layout import FlowLayout
from tilauscope.widgets.readouts import ExtraCounterWidget, LCDReadout


_log: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass
class ExtraEventButton(DataClassDictMixin):
    label: str
    action_type: int  # extraeventsactions
    command: str      # extraeventsactionstrings
    description: str  # extraeventsdescriptions
    color: str        # extraeventbuttoncolor
    text_color: str   # extraeventbuttontextcolor
    ui_type: int      # extraeventstypes
    value: float      # extraeventsvalues
    visible: bool     # extraeventsvisibility
    index: int = 0
    # decorated offset labels for the button tooltip (type name with +/- and % markers, signed offset value)
    type_label: str = ''   # e.g. "±Air%", "Air"
    value_label: str = ''  # e.g. "+5%", "-3", "120"

    def get_action_name(self) -> str:
        """Returns the human-readable action type name."""
        actions = [
            '', 'Serial Command', 'Call Program', 'Multiple Event',
            'Modbus Command', 'DTA Command', 'IO Command', 'Hottop Heater',
            'Hottop Fan', 'Hottop Command', 'p-i-d', 'Fuji Command',
            'PWM Command', 'VOUT Command', 'S7 Command', 'Aillio R1 Heater',
            'Aillio R1 Fan', 'Aillio R1 Drum', 'Aillio R1 Command', 'Artisan Command',
            'RC Command', 'WebSocket Command', 'Stepper Command',
            'Difluid Airwave Command', 'TilauScope Ambient Command'
        ]
        try:
            # Artisan stores action codes with a +1 offset above the historical gap at 8; mirror events.py (act>7 -> -1)
            act = self.action_type
            if act > 7:
                act -= 1
            return actions[act]
        except IndexError:
            return "Unknown"


@dataclass
class ButtonManager(DataClassDictMixin):
    buttons: list[ExtraEventButton] = field(default_factory=list)
    artisan_conf: 'ArtisanSettings' = None # per-instance Artisan bridge

    def _onclick(self, i: int):
        """Triggers the actual Artisan event."""
        if self.artisan_conf and self.artisan_conf.aw and self.artisan_conf.aw.qmc.flagon:
            # Artisan uses 1-based indexing for extra events
            self.artisan_conf.aw.recordextraevent(i , parallel=False, updateButtons=False)

    @classmethod
    def from_artisan_settings(cls, artisan_conf, temp_mode:str):
        """Factory to create the manager from QSettings."""
        conf = artisan_conf

        # Helper to parse Artisan's CSV format in .aset / QSettings

        labels = conf.aw.extraeventslabels
        actions = conf.aw.extraeventsactions
        cmds = conf.aw.extraeventsactionstrings
        descs = conf.aw.extraeventsdescriptions
        colors = conf.aw.extraeventbuttoncolor
        text_colors = conf.aw.extraeventbuttontextcolor
        types = conf.aw.extraeventstypes
        values = conf.aw.extraeventsvalues
        vis = conf.aw.extraeventsvisibility

        btn_list = []
        # Zip based on the length of labels or the max defined in Artisan
        for i in range(len(labels)):
            try:

                # build decorated offset labels (same +/- and % rules as substButtonLabel \V / etype name)
                _t = int(types[i])
                _ext = events_internal_to_external_value(values[i])
                _prefix = '\u00B1' if _t != 9 and 4 < _t < 14 else ''  # relative type -> show +/- marker
                _percent = '%' if 9 < _t < 14 else ''                  # relative-percent type
                _sign = '+' if (_t != 9 and 4 < _t < 14 and _ext > 0) else ''
                _type_label = f'{_prefix}{conf.aw.qmc.etypesf(_t)}{_percent}'
                _value_label = f'{_sign}{_ext}{_percent}'

                btn_list.append(ExtraEventButton(
                    label=subst_button_label(labels[i].replace('\\n', chr(10)), types[i],
                                             conf.slider_names, values[i], temp_mode),
                    action_type=int(actions[i]),
                    command=cmds[i],
                    description=descs[i],
                    color=colors[i],
                    text_color=text_colors[i],
                    ui_type=_t,
                    value=float(values[i]),
                    visible=bool(int(vis[i])),
                    index = i,
                    type_label=_type_label,
                    value_label=_value_label
                ))

            except (IndexError, ValueError):
                continue

        return cls(buttons=btn_list, artisan_conf=conf)


class ArtisanSettings:
    def __init__(self, aw: ApplicationWindow):
        self.aw = aw
        self.mode = aw.qmc.mode
        self.ETname = aw.ETname
        self.BTname = aw.BTname
        self.palette = aw.qmc.palette
        self.slider_names = [s.upper() for s in aw.qmc.etypes]

        # Load Buttons as Objects
        self.button_manager = ButtonManager.from_artisan_settings(self, self.mode)

    def get_visible_buttons(self) -> list[ExtraEventButton]:
        return [b for b in self.button_manager.buttons if b.visible]

    def get_setting_color(self, key, default="#FFFFFF"):
        """ Récupère et convertit une couleur Artisan en format compatible Qt/CSS """
        try:
            val = self.palette.get(key, default)
            # Convertit le format RGBA/Nom d'Artisan en ARGB compatible Qt
            color_hex = rgba_colorname2argb_colorname(val)

            # Pour le CSS (setStyleSheet), on a besoin de #RRGGBB ou #AARRGGBB
            # rgba_colorname2argb_colorname renvoie souvent du #AARRGGBB
            return color_hex
        except Exception:
            return default

    def get_lightened_color(self, hex_color, factor=120):
        """
        Récupère une couleur et l'éclaircit.
        factor > 100 : éclaircit (ex: 120 = +20%)
        factor < 100 : assombrit
        """
        color = QColor(hex_color)
        # .lighter(factor) renvoie une nouvelle instance QColor plus claire
        return color.lighter(factor).name()

    def get_theme_colors(self):
        """
        Récupère les couleurs des sondes définies dans Artisan
        BT = Beans Temperature, ET = Environment Temperature
        """
        return {
            "BT": self.get_setting_color("bt", "#FAB387"), # Orange par défaut
            "ET": self.get_setting_color("et", THEME['CRITICAL']), # Rouge par défaut
            "ROR": self.get_setting_color("deltabt", "#A6E3A1"), # Vert par défaut
            "BG": self.get_setting_color("background", "#0F0F12"), # Fond
            "AIR": THEME['CRITICAL'],
            "DRUM": THEME['ACCENT'],
            "DAMPER": THEME['TEAL'],
            "BURNER": "#FAB387",
            "SV": "#4C4C4C",
        }


#: Space left between two welded groups — this is the gap the operator placed.
_GROUP_SPACING: Final[int] = 20
#: One row of buttons plus the container's own padding.
_MIN_PANEL_H: Final[int] = 75
#: Width of a button's identity stripe, matching the milestone strip's own.
_STRIPE_W: Final[int] = 5


class EventPanel(QWidget):

    # signal émis après chaque action : (label, commande, timestamp, couleur_hex)
    event_fired = pyqtSignal(str, str, str, str)

     # ── QSettings keys ────────────────────────────────────────────────────────
    _SETTINGS_W = "tilauscope/event_panel_width"
    _SETTINGS_H = "tilauscope/event_panel_height"
    _SETTINGS_X = "tilauscope/event_panel_x"
    _SETTINGS_Y = "tilauscope/event_panel_y"

    def __init__(self, button_manager: ButtonManager, theme, parent=None):
        super().__init__(parent)

        self.main_window = parent

        self.settings = QSettings()
        self.oldPos = QPoint()

        self.setStyleSheet(tooltip_qss())

        # Allow resizing for this panel
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # This is a satellite of the roasting window, never a destination. Shown
        # at monitoring ON, it used to take activation with it: macOS delivers
        # pointer movement to the active window only, so the whole header went
        # numb — no hover, no tooltip — until the next click brought it back.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.bm = button_manager
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        self.container = QFrame()
        self.container.setObjectName("MainOuterContainer") # Give it a unique ID

        self.container.setStyleSheet(f"""
            #MainOuterContainer {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['BORDER']};
                border-radius: 8px;
            }}
            QLabel, QFrame {{
                border: none;
                background: transparent;
            }}
        """)


        # The FlowLayout carries welded groups, not single buttons: a group is
        # the run of buttons between two gaps, and it must never be split by a
        # wrap. Rows the operator chose survive as hard breaks.
        self.flow_layout = FlowLayout(
            self.container, margin=10, spacing=_GROUP_SPACING, centered=True)

        buttons = button_manager.buttons
        per_row = max(1, int(getattr(
            getattr(button_manager.artisan_conf, 'aw', None), 'buttonlistmaxlen', 14)))
        _tray, rows = tray_and_rows(buttons, per_row)

        for row_no, chunk in enumerate(rows):
            groups = split_groups(chunk, buttons)
            for group in groups:
                self.flow_layout.addWidget(self._build_group(group, buttons))
            if groups and row_no < len(rows) - 1:
                self.flow_layout.addBreak()

        self.layout.addWidget(self.container)

        self.oldPos = QPoint()

        # --- INITIAL SIZE ---
        # Ask the layout rather than counting buttons: what wraps is a group of
        # unequal width, and a row can end before the width runs out, so no
        # arithmetic over a button count describes the result any more.
        parent_w = self.parent().width() if self.parent() else 800
        self.setFixedHeight(max(_MIN_PANEL_H, self.layout.heightForWidth(parent_w) + 10))

    def _build_group(self, group, buttons) -> QFrame:
        """One welded run of buttons: no spacing inside, rounded at the ends."""
        frame = QFrame()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for position, index in enumerate(group):
            lay.addWidget(self._build_button(buttons[index], position, len(group)))
        return frame

    def _build_button(self, btn_obj: ExtraEventButton, position: int,
                      size: int) -> QPushButton:
        btn = QPushButton(btn_obj.label)
        # IMPORTANT: Fixed size prevents the layout from stretching them.
        # Keep BOTH dimensions fixed here. This panel is a free
        # floating bar on a FlowLayout, not the 330px milestone grid — the
        # width was dropped once by mistake, carrying over that grid's fix,
        # and the row became a ragged run of content-sized buttons.
        btn.setFixedSize(90, 45)
        # tooltip now exposes the event type and the signed/percent offset value, not just the command
        tip = f"<b>{btn_obj.get_action_name()}</b><br>"
        tip += QApplication.translate('Tooltip', '<b>Type </b>= ') + btn_obj.type_label + '<br>'
        if btn_obj.ui_type != 4:  # type 4 = no event assigned -> no offset value to show
            tip += QApplication.translate('Tooltip', '<b>Value </b>= ') + btn_obj.value_label + '<br>'
        if btn_obj.command:
            tip += QApplication.translate('Tooltip', '<b>Documentation </b>= ') + btn_obj.command
        btn.setToolTip(tip)
        left, right = corner_radii(position, size)
        # The edge between two welded buttons has to outweigh the block's own
        # outline, or a welded pair reads as one button carrying two lines of
        # text — the corner rounding that says otherwise sits a button away.
        edge = THEME['SURFACE1'] if position < size - 1 else THEME['BORDER']
        btn.setStyleSheet(with_tooltip(f"""
            QPushButton {{
                background: {THEME['BG']}; color: {THEME['TEXT']};
                border-top-left-radius: {left}px; border-bottom-left-radius: {left}px;
                border-top-right-radius: {right}px; border-bottom-right-radius: {right}px;
                border-left: {_STRIPE_W}px solid {btn_obj.color};
                border-top: 1px solid {THEME['BORDER']};
                border-bottom: 1px solid {THEME['BORDER']}; border-right: 1px solid {edge};
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #28283D; }}
            QPushButton:pressed {{ background: {btn_obj.color}; color: {btn_obj.text_color}; }}
        """))
        btn.clicked.connect(
            lambda checked, b_w=btn, b_o=btn_obj: self.execute_action(b_o.index, b_w, b_o))
        return btn

    def update_panel_height(self):
        # Get the height required for the current width
        # 45 (button) + 10 (margins) = 55 approx for 1 row
        width = self.width() if self.width() > 0 else 800
        needed_height = self.layout.heightForWidth(width) + 10
        self.setFixedHeight(needed_height)

    def execute_action(self, i, btn_widget:QPushButton, btn_obj:ExtraEventButton):

        # 1. Capture original style once if not already stored
        if not hasattr(btn_widget, '_original_style'):
            btn_widget._original_style = btn_widget.styleSheet()

        # 2. Apply flash style
        btn_widget.setStyleSheet(f"""
            QPushButton {{
                background: {btn_obj.color};
                color: {btn_obj.text_color};
                border: 2px solid white;
                font-weight: bold;
            }}
        """)

        # 3. Managed Timer Cleanup: Ensure only one timer is active per button
        if not hasattr(btn_widget, '_flash_timer'):
            btn_widget._flash_timer = QTimer(btn_widget)
            btn_widget._flash_timer.setSingleShot(True)
            # Revert style on timeout
            btn_widget._flash_timer.timeout.connect(
                lambda: btn_widget.setStyleSheet(btn_widget._original_style)
            )

        # 4. Restarting an existing timer is much cheaper than creating a new singleShot
        btn_widget._flash_timer.start(150)

        # 5. execute the Artisan action
        self.bm._onclick(btn_obj.index) # Use the button's index to trigger the correct Artisan event

        # 6. Notifier la sidebar — timestamp relatif au CHARGE si flagon, sinon horloge
        try:
            aw = self.main_window.aw if hasattr(self.main_window, 'aw') else None
            if aw and aw.qmc.flagon and aw.qmc.timeindex[0] > -1:
                charge_t = aw.qmc.timex[aw.qmc.timeindex[0]]
                elapsed  = aw.qmc.timeclock.elapsed() / 1000.0 - charge_t
                mm, ss   = int(elapsed) // 60, int(elapsed) % 60
                ts       = f"{mm}:{ss:02d}"
            else:
                from datetime import datetime as _dt
                ts = _dt.now().strftime("%H:%M:%S")
            cmd = btn_obj.command if hasattr(btn_obj, 'command') and btn_obj.command else ""
            self.event_fired.emit(btn_obj.label, cmd, ts, btn_obj.color)
        except Exception:
            pass


    # --- Capture Clavier (Redirection vers TilauScope) ---
    def keyPressEvent(self, event):
        # On renvoie l'événement vers le handler principal de Tilauscope
        self.main_window.keyPressEvent(event)

    def mousePressEvent(self, event):
        self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        # Ensure we are subtracting two QPoints
        current_pos = event.globalPosition().toPoint()
        delta = current_pos - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = current_pos

    def toggle_visibility(self, visible:bool|None=None):
        if visible is None:
            visible = not self.isVisible()
        self.setVisible(visible)

    def restore_or_align(self, fallback_pos: QPoint) -> None:
        """
        Restaure la géométrie sauvegardée.
        Si aucune sauvegarde n'existe, utilise fallback_pos (résultat d'align_panels).
        Doit être appelée APRÈS setFixedWidth() + update_panel_height().
        """
        pos_x = self.settings.value(self._SETTINGS_X, None)
        pos_y = self.settings.value(self._SETTINGS_Y, None)
        if pos_x is not None and pos_y is not None:
            self.move(int(pos_x), int(pos_y))
        else:
            self.move(fallback_pos)

    def save_geometry(self) -> None:
        self.settings.setValue(self._SETTINGS_W, self.width())
        self.settings.setValue(self._SETTINGS_H, self.height())
        self.settings.setValue(self._SETTINGS_X, self.x())
        self.settings.setValue(self._SETTINGS_Y, self.y())

    # ── Persistance sur drag-to-move ─────────────────────────────────────────
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = QPoint()
            self.save_geometry()

    def close(self):
        self.save_geometry()
        self.settings.sync()
        return super().close()


class TilauscopeSlider(QSlider):
    def __init__(self, accent_color="#4CAF50", parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.accent_color = accent_color
        self.setMinimumHeight(30)

        self.setStyleSheet(f"""
        QSlider {{
            border: none;
            background: transparent;
            height: 30px;
        }}
        QSlider::groove:horizontal {{
            background: #333; /* Un fond sombre pour voir la glissière */
            height: 6px;
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {self.accent_color};
            width: 18px;
            height: 18px;
            margin: -6px 0; /* Centre le handle verticalement sur le groove */
            border-radius: 9px;
        }}
        QSlider::sub-page:horizontal {{
            background: {self.accent_color};
            border-radius: 3px;
        }}
        """)

    def wheelEvent(self, event) -> None:
        """Molette/trackpad : ±singleStep() par cran. Ignoré si flagon actif."""
        # Remonter la hiérarchie pour trouver .aw.qmc.flagon
        p = self.parent()
        while p is not None:
            if hasattr(p, 'aw') and hasattr(p.aw, 'qmc'):
                if p.aw.qmc.flagon:
                    event.ignore()
                    return
                break
            p = p.parent()
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        step = self.singleStep() if delta > 0 else -self.singleStep()
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + step)))
        event.accept()

    # Standard QSlider requires dragging; this makes it snap to mouse click
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            sr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)

            if not sr.contains(event.pos()):
                new_val = self.minimum() + ((self.maximum() - self.minimum()) * event.position().x()) / self.width()
                self.setValue(int(new_val))
                event.accept()
        super().mousePressEvent(event)


class SegmentedControlSlider(TilauscopeSlider):
    """Segmented slider that keeps TilauscopeSlider's interaction contract."""

    _SEGMENT_COUNT: Final[int] = 20

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_rect = self.rect().adjusted(0, 7, 0, -7)
        track_rect.setHeight(min(24, track_rect.height()))
        track_rect.moveTop(self.height() // 2 - track_rect.height() // 2)
        segment_gap = 2
        segment_width = (track_rect.width() - segment_gap * (self._SEGMENT_COUNT - 1)) / self._SEGMENT_COUNT
        filled = 0.0
        if self.maximum() > self.minimum():
            filled = (self.value() - self.minimum()) / (self.maximum() - self.minimum())
        filled_count = round(filled * self._SEGMENT_COUNT)

        # Disabled = out of reach: the value still reads, in grey.
        active = QColor(self.accent_color if self.isEnabled() else THEME['SURFACE2'])
        inactive = QColor(THEME['BORDER'])
        for index in range(self._SEGMENT_COUNT):
            left = track_rect.left() + index * (segment_width + segment_gap)
            segment = QRect(round(left), track_rect.top(), max(1, round(segment_width)), track_rect.height())
            painter.setBrush(active if index < filled_count else inactive)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(segment, 8, 8)
        painter.end()


class ExtraCountersPanel(QWidget):
    """
    Floating panel that shows extra-device readings.

    Improvements over the original single-row HBox version
    ───────────────────────────────────────────────────────
    • Uses FlowLayout so counters wrap onto multiple lines when the panel
      is narrower than the total widget width.
    • Exposes a resize grip in the bottom-right corner: the user can drag it
      to widen/narrow the panel and the rows reflow automatically.
    • Size is persisted in QSettings so it survives a rebuild
      (update_extradevicelist).
    • Mouse-drag on the title bar still moves the panel; the resize grip
      is the only area that triggers a resize.

    Layout skeleton
    ───────────────
        ┌─ outer QVBoxLayout (self) ──────────────────────────────────────┐
        │  ┌─ container QFrame (rounded, dark) ───────────────────────┐  │
        │  │  ┌─ inner QVBoxLayout ───────────────────────────────┐   │  │
        │  │  │  [title bar: drag handle ···  + grip icon ···]    │   │  │
        │  │  │  [FlowLayout: ExtraCounterWidget …  wrap …]       │   │  │
        │  │  └──────────────────────────────────────────────────-┘   │  │
        │  └──────────────────────────────────────────────────────────┘  │
        └─────────────────────────────────────────────────────────────────┘

    The resize grip is painted manually in the bottom-right corner of the
    container; it reacts to left-button press+move.
    """

    # QSettings keys
    _SETTINGS_W = "tilauscope/extra_panel_width"
    _SETTINGS_H = "tilauscope/extra_panel_height"
    _SETTINGS_X = "tilauscope/extra_panel_x"
    _SETTINGS_Y = "tilauscope/extra_panel_y"

    # Grip zone size (px)
    _GRIP_SIZE = 14

    def __init__(self, artisan_conf, theme, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.main_window    = parent
        self.artisan_conf   = artisan_conf
        self.theme          = theme
        self.active_counters: list[tuple] = []   # (widget, source_id, index)

        # ── interaction state ────────────────────────────────────────────────
        self.oldPos          = QPoint()   # drag-to-move
        self._resize_origin  = QPoint()   # drag-to-resize start pos
        self._resize_origin_size = QSize()
        self._resizing       = False

        # ── restore saved size (fall back to a sensible default) ────────────
        self.settings  = QSettings()

        # ── outer layout (just holds the container) ──────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── container frame ──────────────────────────────────────────────────
        self.container = QFrame()
        self.container.setObjectName("ExtraContainer")
        self.container.setStyleSheet(f"""
            #ExtraContainer {{
                background-color: {tint('SURFACE', 230)};
                border: 2px solid {THEME['SURFACE1']};
                border-radius: 12px;
            }}
        """)
        outer.addWidget(self.container)

        inner = QVBoxLayout(self.container)
        inner.setContentsMargins(4, 4, 4, self._GRIP_SIZE)
        inner.setSpacing(4)

        # ── title / drag bar ─────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(18)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(4, 0, 4, 0)
        title_layout.setSpacing(0)

        dots_lbl = QLabel("⋯")
        dots_lbl.setStyleSheet(
            f"color: {THEME['SURFACE1']}; font-size: 12px; font-weight: bold; border: none;"
        )
        dots_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_layout.addStretch()
        title_layout.addWidget(dots_lbl)
        title_layout.addStretch()
        inner.addWidget(title_bar)

        # ── flow layout for counters ─────────────────────────────────────────
        self.flow_container = QWidget()
        self.flow_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.inner_layout = FlowLayout(self.flow_container, margin=2, spacing=4)
        inner.addWidget(self.flow_container)

        # ── populate ─────────────────────────────────────────────────────────
        self.init_counters()

        # ── apply saved / auto size ───────────────────────────────────────────
        self.adjustSize()
        self.container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.restore_geometry() # read first values


    # ── counter management ────────────────────────────────────────────────────

    def init_counters(self):
        """Populate FlowLayout from Artisan extra-device configuration."""
        qmc  = self.artisan_conf.aw.qmc
        n1   = qmc.extraname1
        n2   = qmc.extraname2
        vis1 = self.artisan_conf.aw.extraLCDvisibility1
        vis2 = self.artisan_conf.aw.extraLCDvisibility2
        for i in range(max(len(n1), len(n2))):
            if i < len(n1) and n1[i].strip() and vis1[i] == 1:
                self._add_item(qmc.device_name_subst(n1[i]), source_id=1, idx=i)
            if i < len(n2) and n2[i].strip() and vis2[i] == 1:
                self._add_item(qmc.device_name_subst(n2[i]), source_id=2, idx=i)

    def _add_item(self, name: str, source_id: int, idx: int):
        color = THEME['ACCENT'] if source_id == 1 else "#E5E54F"
        w = ExtraCounterWidget(name, color)
        self.inner_layout.addWidget(w)
        self.active_counters.append((w, source_id, idx))

    def reset_counters(self):
        """Reset all counter displays to dashes (used at power-off / start)."""
        qmc = self.artisan_conf.aw.qmc
        for widget, src, idx in self.active_counters:
            is_int = qmc.intChannel(idx, 1 if src == 1 else 2)
            dash = "--" if (not qmc.LCDdecimalplaces or is_int) else "-.-"
            widget.update_value(dash)

    def update_values(self):
        """Pull latest readings from Artisan and refresh every counter.

        Data routing (from canvas.py sample_processing analysis):
          - flagstart=True  (recording) : extratemp1/2[idx]   <- profil permanent
          - flagstart=False (ON seul)   : RTextratemp1/2[idx] <- buffer RT du dernier cycle,
                                          toujours a jour quelle que soit la phase
            NOTE: on_extratemp1/2 existent mais ne sont jamais alimentes par Artisan
                  (les sous-listes ne sont pas creees au demarrage ON).
        """
        qmc = self.artisan_conf.aw.qmc
        for widget, src, idx in self.active_counters:
            try:
                is_int = qmc.intChannel(idx, 1 if src == 1 else 2)
                dash   = "--" if (not qmc.LCDdecimalplaces or is_int) else "-.-"

                if qmc.flagstart:
                    # Recording: lire le dernier element de la sous-liste permanente
                    arr = qmc.extratemp1[idx] if src == 1 else qmc.extratemp2[idx]
                    if not arr or arr[-1] == -1.0:
                        widget.update_value(dash)
                    else:
                        widget.update_value(f"{int(arr[-1])}" if is_int else f"{arr[-1]:.1f}")

                elif qmc.flagon:
                    # ON sans recording: lire depuis le buffer RT (alimente a chaque cycle)
                    rt = qmc.RTextratemp1 if src == 1 else qmc.RTextratemp2
                    if idx >= len(rt) or rt[idx] == -1.0:
                        widget.update_value(dash)
                    else:
                        widget.update_value(f"{int(rt[idx])}" if is_int else f"{rt[idx]:.1f}")

                else:
                    # OFF: afficher tirets
                    widget.update_value(dash)

            except (IndexError, TypeError):
                continue

    # ── resize grip painting ──────────────────────────────────────────────────

    def paintEvent(self, event):
        """Draw a subtle resize grip in the bottom-right corner."""
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        grip_color = QColor(THEME['OVERLAY0'])
        p.setPen(grip_color)
        r = self.rect()
        # Draw three diagonal dotted lines (standard resize-grip look)
        for offset in (4, 8, 12):
            x = r.right()  - offset
            y = r.bottom() - 2
            x2 = r.right() - 2
            y2 = r.bottom() - offset
            if x >= 0 and y2 >= 0:
                p.drawLine(x, y, x2, y2)
        p.end()

    # ── resize grip hit-test ──────────────────────────────────────────────────

    def _in_resize_grip(self, pos: QPoint) -> bool:
        r = self.rect()
        return (pos.x() >= r.right()  - self._GRIP_SIZE and
                pos.y() >= r.bottom() - self._GRIP_SIZE)

    # ── mouse events: move vs resize ─────────────────────────────────────────

    def restore_geometry(self):
            """Restores size and position from settings."""
            saved_w = self.settings.value(self._SETTINGS_W, 400, type=int)
            saved_h = self.settings.value(self._SETTINGS_H, 100, type=int)
            pos_x   = self.settings.value(self._SETTINGS_X, 100, type=int)
            pos_y   = self.settings.value(self._SETTINGS_Y, 100, type=int)
            self.resize(saved_w, saved_h)
            self.move(pos_x, pos_y)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        gpos = event.globalPosition().toPoint()
        if self._in_resize_grip(event.pos()):
            self._resizing        = True
            self._resize_origin   = gpos
            self._resize_origin_size = self.size()
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self._resizing = False
            self.oldPos    = gpos

    def mouseMoveEvent(self, event):
        gpos = event.globalPosition().toPoint()
        if self._resizing:
            delta = gpos - self._resize_origin
            new_w = max(self.minimumWidth(),  self._resize_origin_size.width()  + delta.x())
            new_h = max(self.minimumHeight(), self._resize_origin_size.height() + delta.y())
            self.resize(new_w, new_h)
            # Force the FlowLayout to recompute immediately
            self.flow_container.updateGeometry()
            self.update()
        elif not self.oldPos.isNull():
            delta = gpos - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = gpos

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing:
                self._resizing = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.settings.setValue(self._SETTINGS_W, self.width())
            self.settings.setValue(self._SETTINGS_H, self.height())
            self.settings.setValue(self._SETTINGS_X, self.x())
            self.settings.setValue(self._SETTINGS_Y, self.y())

    def close(self):
        self.settings.setValue(self._SETTINGS_W, self.width())
        self.settings.setValue(self._SETTINGS_H, self.height())
        self.settings.setValue(self._SETTINGS_X, self.x())
        self.settings.setValue(self._SETTINGS_Y, self.y())
        self.settings.sync()
        return super().close()


    # Qt calls this automatically for hover — we override it here:
    def event(self, e):
        if e.type() == QEvent.Type.HoverMove:
            pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
            if self._in_resize_grip(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        return super().event(e)

    # ── key forwarding ───────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        self.main_window.keyPressEvent(event)

    # ── visibility toggle ─────────────────────────────────────────────────────

    def toggle_visibility(self, visible: bool | None = None):
        if visible is None:
            visible = not self.isVisible()
        if visible:
            self.restore_geometry()
        self.setVisible(visible)


class TilauscopePanel(QWidget):
    def __init__(self, artisan_conf:ArtisanSettings):
        self.artisan_conf = artisan_conf
        super().__init__()
        self.init_ui()

    def init_ui(self):
        # Main Layout for the metrics row
        self.metrics_layout = QHBoxLayout(self)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_layout.setSpacing(8)

        # Seuils de danger selon le mode de température (Celsius / Fahrenheit)
        # BT/ET : 230 °C ≈ 446 °F — température dangereuse de grains
        # RoR   : 20 °C/m ≈ 36 °F/m — montée en chaleur excessive
        _danger_temp = 230.0 if self.artisan_conf.mode == 'C' else 446.0
        _danger_ror  = 20.0  if self.artisan_conf.mode == 'C' else 36.0
        # Plage d'approche : 30 °C / 54 °F avant la cible pour BT/ET, 10 pour RoR
        _range_temp  = 30.0  if self.artisan_conf.mode == 'C' else 54.0
        _range_ror   = 10.0  if self.artisan_conf.mode == 'C' else 18.0

        # 1. Grain Temp (BT) - Smaller
        self.tg_lcd = LCDReadout(
            QApplication.translate("Label", self.artisan_conf.BTname) + f" °{self.artisan_conf.mode}",
            self.artisan_conf.get_setting_color('bt'),
            alert_target=_danger_temp,
            alert_range=_range_temp,
        )

        # 2. Exhaust Temp (ET) - Smaller
        self.te_lcd = LCDReadout(
            QApplication.translate("Label", self.artisan_conf.ETname) + f" °{self.artisan_conf.mode}",
            self.artisan_conf.get_setting_color('et'),
            alert_target=_danger_temp,
            alert_range=_range_temp,
        )

        # 3. Rate of Rise (RoR) - LARGER HIERARCHY
        # The bean's colour, one step back — the same rule the curve draws its
        # rate with. A rate belongs to the probe it is measured on; giving it a
        # hue of its own made the readout and the curve name two different
        # things with the same word.
        self.ror_lcd = LCDReadout(
            QApplication.translate("Label", "RoR") + f" °{self.artisan_conf.mode}/m",
            dimmed(self.artisan_conf.get_setting_color('bt'), '#89B4FA'),
            is_main=True,
            alert_target=_danger_ror,
            alert_range=_range_ror,
        )

        # Adding to layout with Stretch Factors:
        # BT/ET widened: at 320px/stretch(2,2,3) the "NNN.N" reading
        # (3 integer digits) didn't fit the BT/ET box and got clipped on the
        # right. Restoring the panel to 360px and giving BT/ET a bigger share
        # fixes it without shrinking RoR below its previous width.
        self.metrics_layout.addWidget(self.tg_lcd, stretch=3)
        self.metrics_layout.addWidget(self.te_lcd, stretch=3)
        self.metrics_layout.addWidget(self.ror_lcd, stretch=4)

        self.setStyleSheet("background-color: #0b0b0b;")
        self.setFixedWidth(360)   # widened back from 320 to stop BT/ET readouts truncating

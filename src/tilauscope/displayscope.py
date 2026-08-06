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
# TiLau 2025

from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsOpacityEffect,
                             QLabel, QFrame, QSlider, QProgressBar, QGridLayout, QMenu, QStyle, QStyleOptionSlider,
                             QPushButton, QScrollArea, QLayout, QDialog, QStackedWidget)
from PyQt6.QtCore import Qt, QPoint, QTimer, QTime, QRect, QSize, pyqtSlot, QEvent, QSettings
from PyQt6.QtGui import QColor, QCloseEvent, QKeyEvent, QPalette, QCursor, QPixmap, QIcon, QImage, QKeySequence, QPainter, QFont, QFontMetrics, QFontDatabase, QShortcut
from PyQt6.QtCore import QPropertyAnimation, pyqtProperty, pyqtSignal, QEasingCurve

# get settings
import logging
import os
import time
from pathlib import Path

from dataclasses import dataclass, field
from typing import Final, override
from mashumaro import DataClassDictMixin

from artisanlib.main import ApplicationWindow 
from artisanlib.util import events_internal_to_external_value, fromFtoCstrict, fromCtoFstrict, rgba_colorname2argb_colorname, toDim
from artisanlib.util import deltaLabelUTF8

from tilauscope.beancave import BeancaveDlg
from tilauscope.tilauscope_types import THEME, _IS_WINDOWS, _IS_MACOS, TilauMessageBox
from tilauscope.whats_new import maybe_show_whats_new
from tilauscope.header_icons import (
    SVG_MENU, SVG_POWER, SVG_PLAY, SVG_STOP,
    SVG_RESET, SVG_BEANCAVE, SVG_ASSISTANT, SVG_SWAP,
    BTN_ICON_SIZE,
    COL_MENU, COL_IDLE, COL_DISABLED, COL_PRESSED,
    COL_POWER_IDLE, COL_POWER_ACTIVE,
    COL_START_IDLE, COL_START_ACTIVE,
    COL_RESET_IDLE, COL_RESET_ACTIVE,
    COL_BEANCAVE_IDLE, COL_BEANCAVE_ACTIVE,
    COL_ASSISTANT_IDLE, COL_ASSISTANT_ACTIVE,
    COL_SWAP_IDLE, COL_SWAP_ACTIVE,
    COL_DOCK_IDLE, COL_DOCK_ACTIVE,
    make_icon, apply_icon,
    QSS_MENU, QSS_POWER, QSS_START_STOP, QSS_RESET,
    QSS_BEANCAVE, QSS_ASSISTANT, QSS_SWAP, QSS_DOCK,
    SVG_DOCK,
)
from tilauscope.visualalarm import AlarmData
from tilauscope.artisan_message_ticker import ArtisanMessageTicker, ArtisanMessageHook
from tilauscope.main_window_style import take_body, give_body

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")


_MONO_FAMILY: str = ""  # resolved once by _mono_font_family()

## TILAU ## Coalescing window for slider commits: a burst of +/- clicks within
## this delay sends a single hardware command with the final value instead of
## one command (and one recorded event) per click.
_SLIDER_COMMIT_DEBOUNCE_MS: Final[int] = 300

## TILAU ## Horizontal room the ToggleBar (10 px) + its layout spacing (6 px) take
## on the right of the slider rows. The SV row sits outside that zone and must
## reserve the same width to stay aligned with the rows above.
_CTRL_TOGGLE_RESERVE_PX: Final[int] = 16

## TILAU ## Explicit insets for every slider row (the 4 event sliders + SV), so the
## rows line up regardless of platform: a layout installed on a widget inherits the
## style's default margin (~12 px on macOS, 9 on Windows) while a nested layout gets
## 0 — which is exactly what left the SV row out of line. Vertical is kept small: the
## inherited default put ~11 px above AND below each row, spreading them far apart.
_SLIDER_ROW_MARGINS: Final[tuple[int, int, int, int]] = (11, 2, 11, 2)


def _mono_font_family() -> str:
    """Register the bundled JetBrains Mono once and return its real family name.

    Falls back to a system monospace ('Menlo' on macOS) if the embedded file
    cannot be loaded. Bundling the font makes the timer rendering independent
    of what is installed on the machine.
    """
    global _MONO_FAMILY
    if _MONO_FAMILY:
        return _MONO_FAMILY
    try:
        import os
        _path = os.path.join(os.path.dirname(__file__), "JetBrainsMono-Bold.ttf")
        fid = QFontDatabase.addApplicationFont(_path)
        families = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
        _MONO_FAMILY = families[0] if families else "Menlo"
    except Exception:  # noqa: BLE001
        _MONO_FAMILY = "Menlo"
    return _MONO_FAMILY


SIDEBAR_W   = 220   # px — must match AlarmSidebar content needs
GRIP_W      = 16    # px — always-visible strip

# Catppuccin Mocha palette references
_COL_SURFACE0  = "#313244"
_COL_SURFACE1  = "#45475A"
_COL_LAVENDER  = "#b4befe"
_COL_TEXT      = "#CDD6F4"
_COL_BASE      = "#1e1e2e"

# Style à appliquer au parent pour la cohérence visuelle
PARENT_TILAUSTYLE = """
    /* On cible uniquement le widget avec cet ID précis */
    QWidget#CentralWidget {
        background-color: #0F0F12;
        border: 1px solid #313244;
        border-radius: 10px; /* Vos coins arrondis ici */
    }

    /* On réinitialise explicitement les bordures pour les enfants directs ou indirects */
    #CentralWidget QWidget {
        border-radius: 0px;
        border: none;
    }
"""
 
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
    ## TILAU ## decorated offset labels for the button tooltip (type name with +/- and % markers, signed offset value)
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
            ## TILAU ## Artisan stores action codes with a +1 offset above the historical gap at 8; mirror events.py (act>7 -> -1)
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

        def substButtonLabel(label:str, eventtype:int, etypes, eventvalue:float, mode:str) -> str:
            et:int = eventtype
            res:str = label
            value = events_internal_to_external_value(eventvalue)
            tempvalueF = (value if mode == 'F' else int(round(fromFtoCstrict(value))))
            tempvalueC = (value if mode == 'C' else int(round(fromCtoFstrict(value))))
            sign = ''
            percent = ''
            evType = eventtype
            if et < len(etypes):
                if evType == -1:
                    evType = 4 # and map the first entry to 4
                elif evType == 4:
                    evType = 9 # and map the entry 4 to 9
                elif evType > 8:
                    evType += 1
            if et != 9 and 4 < et < 14 and value > 0:
                sign = '+'
            if 9 < et < 14:
                percent = '%'
            if et > 8:
                et = et - 10
            if et > 4:
                et = et - 5
            if et < 4 and et != 9:
                i = etypes[evType]-1
                map_source = conf.slider_names[et]
                res = res.replace('\\t',map_source)
            for var,subst in [
                    ('\\0', QApplication.translate('Label','OFF')),
                    ('\\1', QApplication.translate('Label','ON')),
                    ('\\2', (QApplication.translate('Label','ON'))),
                    ('\\3', (QApplication.translate('Label','OFF'))),
                    ('\\a', QApplication.translate('Label','AUTO')),
                    ('\\A', (QApplication.translate('Label','MANUAL'))),
                    ('\\b', QApplication.translate('Label','FLAP')),
                    ('\\c', QApplication.translate('Label','CLOSE')),
                    ('\\C', (QApplication.translate('Label','OPEN'))),
                    ('\\d', QApplication.translate('Label','CONTROL')),
                    ('\\D', QApplication.translate('Label','DISCHARGE')),
                    ('\\e', etypes[2]),
                    ('\\h', QApplication.translate('Label','HEATING')),
                    ('\\i', QApplication.translate('Label','STIRRER')),
                    ('\\f', QApplication.translate('Label','FILL')),
                    ('\\F', f'{tempvalueF}{mode}'),
                    ('\\l', QApplication.translate('Label','COOLING')),
                    ('\\m', QApplication.translate('Label','MANUAL')),
                    ('\\M', (QApplication.translate('Label','AUTO'))),
                    ('\\o', QApplication.translate('Label','OPEN')),
                    ('\\O', (QApplication.translate('Label','CLOSE'))),
                    ('\\p', QApplication.translate('Label','STOP')),
                    ('\\P', (QApplication.translate('Label','START'))),
                    ('\\q', etypes[0]),
                    ('\\r', etypes[3]),
                    ('\\R', QApplication.translate('Label','RELEASE')),
                    ('\\s', QApplication.translate('Label','START')),
                    ('\\S', (QApplication.translate('Label','STOP'))),
                    ('\\T', f'{tempvalueC}{mode}'),
                    ('\\V', f'{sign}{value}{percent}'),
                    ('\\w', etypes[1])
                    ]:
                res = res.replace(var,str(subst))
            return res

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
                
                ## TILAU ## build decorated offset labels (same +/- and % rules as substButtonLabel \V / etype name)
                _t = int(types[i])
                _ext = events_internal_to_external_value(values[i])
                _prefix = '\u00B1' if _t != 9 and 4 < _t < 14 else ''  # relative type -> show +/- marker
                _percent = '%' if 9 < _t < 14 else ''                  # relative-percent type
                _sign = '+' if (_t != 9 and 4 < _t < 14 and _ext > 0) else ''
                _type_label = f'{_prefix}{conf.aw.qmc.etypesf(_t)}{_percent}'
                _value_label = f'{_sign}{_ext}{_percent}'

                btn_list.append(ExtraEventButton(
                    label=substButtonLabel(labels[i].replace('\\n', chr(10)), types[i], types, values[i], temp_mode),
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
            "ET": self.get_setting_color("et", "#F38BA8"), # Rouge par défaut
            "ROR": self.get_setting_color("deltabt", "#A6E3A1"), # Vert par défaut
            "BG": self.get_setting_color("background", "#0F0F12"), # Fond
            "AIR": "#F38BA8",
            "DRUM": "#89B4FA",
            "DAMPER": "#94E2D5",
            "BURNER": "#FAB387",
            "SV": "#4C4C4C",
        }

class SmartRoller(QWidget):
    def __init__(self, current_val, color, callback, min_val:int = 0, max_val:int = 100, step:int=1):
        super().__init__(None)
        self.callback = callback
        self.color = color
        self.min_val = min_val
        # 1. Set flags for a popup
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        
        # 2. Re-enable Translucent Background (allows the 'corners' to be invisible)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 3. Ensure we DON'T auto-fill the background (which creates the square box)
        self.setAutoFillBackground(False)

        self.setFixedSize(75, 350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)
        self.container = QFrame()
        self.container.setObjectName("MainContainer") # Ensure ID matches CSS
        self.container.setStyleSheet("""
            #MainContainer {
                background-color: #1E1E2E; 
                border: 2px solid #313244; 
                border-radius: 6px;
            }
            QScrollBar:horizontal {
                height: 0px;
                background: transparent;
            }
            QWidget { border: none; }
        """)
        layout.addWidget(self.container)
        scroll_layout = QVBoxLayout(self.container)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        for i in range(min_val, max_val+1, step): # fix 2026/05/02 added step support 
            btn = QPushButton(str(i))
            btn.setFixedHeight(38)
            is_curr = (i == current_val)
            style = f"color: {'white' if is_curr else '#6c7086'}; border: none; font-family: 'JetBrains Mono'; font-size: {'16px' if is_curr else '14px'};"
            if is_curr: style += f"background-color: {color}; border-radius: 8px; font-weight: bold;"
            else: style += "background: transparent;"
            btn.setStyleSheet(f"QPushButton {{ {style} }} QPushButton:hover {{ color: white; background: #313244; border-radius: 8px; }}")
            btn.clicked.connect(lambda checked, v=i: self.select_value(v))
            self.content_layout.addWidget(btn)
        self.scroll.setWidget(self.content)
        scroll_layout.addWidget(self.scroll)
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue((current_val-self.min_val) * 52 - 90))
        self.current_val = current_val

    def select_value(self, val):
                self.callback(val)
                self.close()

class TickerLabel(QWidget):
    """
    Widget d'une ligne qui fait défiler son texte horizontalement si le contenu
    dépasse la largeur disponible. Statique si le texte est court.

    Drop-in pour QLabel monoligne — supporte setText(), text(),
    setStyleSheet() et setAlignment().

    Impact temps réel : nul — timer inactif si texte court, 40ms/tick sinon.
    """
    _SPEED_PX   = 1     # pixels par tick
    _PAUSE_TICK = 50    # ticks de pause à chaque extrémité (~2 s à 40 ms)
    _INTERVAL   = 40    # ms entre chaque tick

    def __init__(
        self,
        height: int = 18,
        color: str = "#A6E3A1",
        font_size: int = 11,
        font_weight: int = 700,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)

        self._lbl = QLabel("", self)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._lbl.setStyleSheet(
            f"color: {color}; font-size: {font_size}px; font-weight: {font_weight}; "
            f"border: none; background: transparent;"
        )
        self._lbl.move(0, 0)
        self._lbl.setFixedHeight(height)

        self._offset: int    = 0
        self._direction: int = 1
        self._pause: int     = 0
        self._overflow: int  = 0

        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL)
        self._timer.timeout.connect(self._tick)

    def setText(self, text: str) -> None:
        self._lbl.setText(text)
        self._lbl.adjustSize()
        self._offset    = 0
        self._direction = 1
        self._pause     = self._PAUSE_TICK
        self._lbl.move(0, 0)
        self._overflow = max(0, self._lbl.width() - self.width())
        if self._overflow > 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def setStyleSheet(self, style: str) -> None:  # type: ignore[override]
        """Forward stylesheet to internal label (color changes, etc.)."""
        self._lbl.setStyleSheet(style)
        self._lbl.adjustSize()
        self._overflow = max(0, self._lbl.width() - self.width())

    def setAlignment(self, flag) -> None:  # type: ignore[override]
        self._lbl.setAlignment(flag)

    def text(self) -> str:
        return self._lbl.text()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._lbl.setFixedHeight(self.height())
        self._overflow = max(0, self._lbl.width() - self.width())
        if self._overflow <= 0:
            self._timer.stop()
            self._lbl.move(0, 0)

    def _tick(self) -> None:
        if self._pause > 0:
            self._pause -= 1
            return
        self._offset += self._direction * self._SPEED_PX
        if self._offset >= self._overflow:
            self._offset    = self._overflow
            self._direction = -1
            self._pause     = self._PAUSE_TICK
        elif self._offset <= 0:
            self._offset    = 0
            self._direction = 1
            self._pause     = self._PAUSE_TICK
        self._lbl.move(-self._offset, 0)

class ClickableValue(QLabel):
    # Added release_callback and index to the parameters
    def __init__(self, value, color, slider_ref, unit, index, release_callback, min_val=0, max_val=100, step:int =1):
        super().__init__(f"{value}{unit}")
        self.color = color
        self.slider_ref = slider_ref
        self.min_val = min_val
        self.max_val = max_val
        self.index = index  # Store which slider this is
        self.step = step
        self.release_callback = release_callback  # Store reference to handle_ui_input_released
        self.setFixedWidth(55)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_style()

    def update_style(self, highlight=False):
        style = "font-weight: bold; font-family: 'JetBrains Mono'; font-size: 15px; border: none;"
        if highlight: self.setStyleSheet(f"color: #11111B; background-color: {self.color}; border-radius: 4px; {style}")
        else: self.setStyleSheet(f"color: {self.color}; background: transparent; {style}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToGlobal(QPoint(-85, -110))
            self.roller = SmartRoller(self.slider_ref.value(), self.color, self.set_new_value, self.min_val, self.max_val, self.step)
            self.roller.move(pos)
            self.roller.show()

    def set_new_value(self, val):
        self.slider_ref.setValue(val)
        
        # --- Inform Artisan of the change ---
        if self.release_callback:
            self.release_callback(self.index)
            
        self.update_style(True)
        QTimer.singleShot(150, lambda: self.update_style(False))

# --- WIDGETS DE PHASES ---

class PhaseWidget(QFrame):
    def __init__(self, alias, name, color, theme, subtitle=None):
        super().__init__()
        self.theme = theme
        self.name = name
        self.alias = alias
        self.phase_color = color  # Store the specific phase color (blue, yellow, or pink)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(0)
        if subtitle is not None:
            name += "<br>"+subtitle
        self.lbl = QLabel(name)
        self.lbl.setWordWrap(True)
        self.lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter) # Align to bottom
        self.lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 800; border: none;")
        self.lbl.setAutoFillBackground(True)

        self.stats = QLabel("00:00 (0%)")
        self.stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats.setStyleSheet("color: #64748B; font-size: 13px; font-family: 'JetBrains Mono'; border: none;")

        self.bar = QProgressBar()
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"QProgressBar {{ background: #1E1E2E; border: none; border-radius: 3px; }} QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}")

        self.layout.addWidget(self.lbl)
        self.layout.addWidget(self.stats) 
        self.layout.addSpacing(10)
        self.layout.addWidget(self.bar)
        self.setStyleSheet("border: none; background: transparent;")
        self.set_progress(0)

    def update_subtitle(self, subtitle):
        name = self.name +f"<br>{subtitle}" if subtitle is not None else ""
        self.lbl.setText(name)

    def set_active(self, active=True):
        if active:
            # ACTIVE: Highlight with the specific phase color border (Yellow for Maillard, etc.)
            self.lbl.setStyleSheet("color: white; font-size: 12px; font-weight: 900; border: none;")
            self.stats.setStyleSheet("color: white; font-size: 13px; font-family: 'JetBrains Mono'; font-weight: bold; border: none;")
            self.setStyleSheet(f"""
                PhaseWidget {{ 
                    background: {self.theme['BG']}; 
                    border-radius: 10px; 
                    border: 2px solid {self.phase_color}; 
                }}
            """)
        else:
            # INACTIVE: Normal gray/white style, no border
            self.lbl.setStyleSheet("color: #64748B; font-size: 12px; border: none;")
            self.stats.setStyleSheet("color: #475569; font-size: 13px; border: none;font-size: 13px; font-family: 'JetBrains Mono'; ")
            self.setStyleSheet("PhaseWidget { background: transparent; border: none; }")

    def update_stats(self, seconds, total_seconds):
            """Updates the timer and percentage label."""
            m, s = divmod(int(seconds), 60)
            percent = min(100, max(0, int((seconds / total_seconds * 100)))) if total_seconds > 0 else 0
#            percent = int((seconds / total_seconds * 100)) if total_seconds > 0 else 0
            new_text = f"{m:02d}:{s:02d} ({percent}%)"
            if self.stats.text() != new_text: # Only update if string changed
                self.stats.setText(new_text)
    
    def set_progress(self, percent):
        """Sets the progress bar value (0-100)."""
        self.bar.setValue(min(100, max(0, int(percent))))

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        # Initialize attributes BEFORE setting margins or adding items
        self._height_cache = {} 
        self._cached_min_size = None
        self.items = []
        
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def invalidate(self):
        """Clear layout caches with safety checks."""
        # Use hasattr to prevent the AttributeError during early initialization
        if hasattr(self, '_height_cache'):
            self._height_cache.clear()
        if hasattr(self, '_cached_min_size'):
            self._cached_min_size = None
        super().invalidate()

    def __del__(self):
        while self.items:
            self.takeAt(0)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate() # Clear caches when items are added

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        if 0 <= index < len(self.items):
            self.invalidate()
            return self.items.pop(index)
        return None
    
    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True
    
    def heightForWidth(self, width):
        # Optimization: Return cached height if we already calculated it for this width
        if width in self._height_cache:
            return self._height_cache[width]
        
        h = self._do_layout(QRect(0, 0, width, 0), True)
        self._height_cache[width] = h
        return h

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()
    
    def minimumSize(self):
        if self._cached_min_size:
            return self._cached_min_size
            
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        
        margin = self.contentsMargins().left()
        size += QSize(2 * margin, 2 * margin)
        self._cached_min_size = size
        return size
    
    def _do_layout(self, rect, test_only):
        """Perform the actual layout logic."""
        m_left, m_top, m_right, m_bottom = self.getContentsMargins()
        x = rect.x() + m_left
        y = rect.y() + m_top
        line_height = 0
        spacing = self.spacing()
        right_limit = rect.right() - m_right

        for item in self.items:
            # OPTIMIZATION: Call sizeHint() exactly ONCE per item.
            s_hint = item.sizeHint()
            item_w = s_hint.width()
            item_h = s_hint.height()

            next_x = x + item_w + spacing
            
            # If we exceed the width, wrap to the next line
            if next_x - spacing > right_limit and line_height > 0:
                x = rect.x() + m_left
                y = y + line_height + spacing
                next_x = x + item_w + spacing
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), s_hint))

            x = next_x
            line_height = max(line_height, item_h)

        return y + line_height + m_bottom - rect.y()
    
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

        self.setStyleSheet("QToolTip { color: #ffffff; background-color: #2D2D35; border: 1px solid #585B70; }")
        
        # Allow resizing for this panel
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.bm = button_manager
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)        
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        self.container = QFrame()
        self.container.setObjectName("MainOuterContainer") # Give it a unique ID

        self.container.setStyleSheet("""
            #MainOuterContainer {
                background-color: #1E1E2E; 
                border: 2px solid #313244; 
                border-radius: 8px;
            }
            QLabel, QFrame { 
                border: none; 
                background: transparent; 
            }
        """)

        
        # Use the custom FlowLayout instead of QGridLayout
        self.flow_layout = FlowLayout(self.container, margin=10, spacing=8)
        
        visible_buttons = [b for b in button_manager.buttons if b.visible]

        for i, btn_obj in enumerate(visible_buttons):
            btn = QPushButton(btn_obj.label)
            # IMPORTANT: Fixed size prevents the layout from stretching them
            btn.setFixedSize(90, 45)
            ## TILAU ## tooltip now exposes the event type and the signed/percent offset value, not just the command
            tip = f"<b>{btn_obj.get_action_name()}</b><br>"
            tip += QApplication.translate('Tooltip', '<b>Type </b>= ') + btn_obj.type_label + '<br>'
            if btn_obj.ui_type != 4:  # type 4 = no event assigned -> no offset value to show
                tip += QApplication.translate('Tooltip', '<b>Value </b>= ') + btn_obj.value_label + '<br>'
            if btn_obj.command:
                tip += QApplication.translate('Tooltip', '<b>Documentation </b>= ') + btn_obj.command
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton {{ 
                    background: #1E1E2E; color: #CDD6F4; border-radius: 6px;
                    border-left: 4px solid {btn_obj.color}; border-top: 1px solid #313244;
                    border-bottom: 1px solid #313244; border-right: 1px solid #313244;
                    font-family: 'JetBrains Mono';
                    font-size: 11px; 
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: #28283D; }}
                QPushButton:pressed {{ background: {btn_obj.color}; color: {btn_obj.text_color}; }}
            """)
            btn.clicked.connect(lambda checked, i=i, b_w=btn, b_o=btn_obj: self.execute_action(i, b_w, b_o))
            self.flow_layout.addWidget(btn)
            
        self.layout.addWidget(self.container)
        
        self.oldPos = QPoint()

        # --- SMART DYNAMIC INITIAL SIZE ---
        
        # 1. Configuration matching your button/layout settings
        btn_h = 45      # From btn.setFixedHeight(45)
        spacing = 8     # From FlowLayout(..., spacing=8)
        v_margins = 30  # Space for container padding and borders

        num_buttons = len(visible_buttons)

        # 2. Calculate rows based on the actual parent width
        # We use the parent's width to estimate how many buttons fit per row
        parent_w = self.parent().width() if self.parent() else 800
        btns_per_row = max(1, (parent_w - 20) // (90 + spacing)) # 90 is btn fixed width
        num_rows = (num_buttons + btns_per_row - 1) // btns_per_row if num_buttons > 0 else 1

        # 3. Final height calculation
        calculated_height = (num_rows * btn_h) + (max(0, num_rows - 1) * spacing) + v_margins
        self.setFixedHeight(calculated_height)

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

        # 5. enable buttons based on current press, disable previous buttons
        #visible_buttons:list[ExtraEventButton] = [b for b in self.bm.buttons if b.visible]
        #for n, btn_obj in enumerate(visible_buttons): # fixed 2026/03/29: was iterating over wrong object before
        #    enabled = i >= n
        #    btn_obj.setEnabled(enabled)

        # Revert the style after 150ms to simulate a physical click
        #QTimer.singleShot(150, lambda: btn_widget.setStyleSheet(original_style))    

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

# --- WIDGETS DE CONTROLE ALTERNATIVE SLIDER ---

class BigControlCard(QFrame):
    """
    Card-style alternative to a horizontal slider row.

    Layout (top→bottom inside a rounded QFrame):
        ┌───────────────┐
        │       ▲       │  ← btn_up   (transparent bg, body dark shows)
        ├───────────────┤
        │    70%        │  ← val_frame (mid-tone bg, clickable → SmartRoller)
        ├───────────────┤
        │       ▼       │  ← btn_down
        └───────────────┘
          HEATER          ← name_lbl (below card)

    Arrows increment/decrement by `step`.
    Clicking the value zone opens the existing SmartRoller popup.
    The hidden TilauscopeSlider `slider_ref` remains the source of truth so
    all Artisan signal chains (handle_ui_input_released / move) still fire.
    """

    def __init__(
        self,
        name: str,
        color: str,
        slider_ref,          # TilauscopeSlider — hidden, still connected to Artisan
        index: int,
        release_callback,    # TilauScope.handle_ui_input_released
        unit: str = "%",
        min_val: int = 0,
        max_val: int = 100,
        step: int = 1,
    ):
        super().__init__()
        self.name = name
        self.color = color
        self.slider_ref = slider_ref
        self.index = index
        self.release_callback = release_callback
        self.unit = unit
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self._roller = None  # keep reference so GC doesn't eat it

        # Derive card-section colours from the accent colour
        base = QColor(color)
        self._col_body = base.darker(160).name()   # arrow zone (darker)
        self._col_mid  = base.darker(120).name()   # value zone (less dark)
        self._col_border = base.darker(220).name() # card outline

        self._build_ui()

        # Stay in sync with external slider changes (e.g. playback / Artisan automation)
        self.slider_ref.valueChanged.connect(
            lambda v: self.val_lbl.setText(f"{v}{self.unit}")
        )

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setFixedWidth(100)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Card itself is transparent; all painting is on card_body. The QToolTip
        # rule themes the card tooltips (else they render in the default white
        # OS style). ## TILAU ##
        self.setStyleSheet(
            "BigControlCard { background: transparent; border: none; }"
            "QToolTip { background-color: #2D2F3F; color: #CDD6F4;"
            " border: 1px solid #585B70; padding: 4px; border-radius: 4px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 0, 3, 4)
        outer.setSpacing(4)

        # ── Card body frame ───────────────────────────────────────────────────
        # border-radius gives the overall pill shape.
        # Child widgets use transparent backgrounds so the dark body colour
        # is visible at the rounded top/bottom corners.
        card_body = QFrame()
        card_body.setObjectName(f"CardBody_{self.name}")
        card_body.setStyleSheet(f"""
            QFrame#CardBody_{self.name} {{
                background: {self._col_body};
                border-radius: 12px;
                border: 1px solid {self._col_border};
            }}
        """)
        body_layout = QVBoxLayout(card_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── Up arrow ─────────────────────────────────────────────────────────
        self.btn_up = self._make_arrow("▲", top=True)
        self.btn_up.clicked.connect(self._increment)

        # ── Value display (clickable) ─────────────────────────────────────────
        val_frame = QFrame()
        val_frame.setObjectName(f"ValFrame_{self.name}")
        val_frame.setStyleSheet(f"""
            QFrame#ValFrame_{self.name} {{
                background: {self._col_mid};
                border: none;
                border-top:    1px solid {self._col_border};
                border-bottom: 1px solid {self._col_border};
                border-radius: 0px;
            }}
        """)
        val_frame.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        val_frame.setToolTip(QApplication.translate("tilauscope_window", "Click to open roller — right-click for context menu"))
        # Monkey-patch mousePressEvent on the frame so the full zone is hot
        val_frame.mousePressEvent = self._open_roller

        val_inner = QVBoxLayout(val_frame)
        val_inner.setContentsMargins(4, 10, 4, 10)

        self.val_lbl = QLabel(f"{self.slider_ref.value()}{self.unit}")
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.val_lbl.setStyleSheet("""
            color: white;
            font-family: 'JetBrains Mono';
            font-size: 19px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)
        val_inner.addWidget(self.val_lbl)

        # ── Down arrow ────────────────────────────────────────────────────────
        self.btn_down = self._make_arrow("▼", top=False)
        self.btn_down.clicked.connect(self._decrement)

        body_layout.addWidget(self.btn_up)
        body_layout.addWidget(val_frame, 1)
        body_layout.addWidget(self.btn_down)

        # ── Name label (below the card body) ─────────────────────────────────
        name_lbl = QLabel(self.name)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("""
            color: #585B70;
            font-family: 'JetBrains Mono';
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.5px;
            border: none;
            background: transparent;
        """)

        outer.addWidget(card_body, 1)
        outer.addWidget(name_lbl)

    def _make_arrow(self, glyph: str, top: bool) -> QPushButton:
        """Creates a styled arrow QPushButton."""
        btn = QPushButton(glyph)
        btn.setFixedHeight(30)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Rounded corners only on the exposed side of the card
        radius = "10px 10px 0px 0px" if top else "0px 0px 10px 10px"
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: rgba(255, 255, 255, 0.70);
                font-size: 13px;
                border: none;
                border-radius: {radius};
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.13);
                color: white;
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 0.26);
                color: white;
            }}
        """)
        return btn

    # ── Interaction ───────────────────────────────────────────────────────────

    def _increment(self):
        self._apply_value(min(self.max_val, self.slider_ref.value() + self.step))

    def _decrement(self):
        self._apply_value(max(self.min_val, self.slider_ref.value() - self.step))

    def _apply_value(self, val: int):
        """Set slider value and fire Artisan callbacks, with visual flash."""
        self.slider_ref.setValue(val)
        if self.release_callback:
            self.release_callback(self.index)
        # Brief colour flash so the user sees the change registered
        self.val_lbl.setStyleSheet(f"""
            color: #11111B;
            font-family: 'JetBrains Mono';
            font-size: 19px;
            font-weight: bold;
            border: none;
            background: {self.color};
            border-radius: 4px;
        """)
        QTimer.singleShot(130, self._reset_val_style)

    def _reset_val_style(self):
        self.val_lbl.setStyleSheet("""
            color: white;
            font-family: 'JetBrains Mono';
            font-size: 19px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)

    def _open_roller(self, event):
        """Open the SmartRoller popup (reuses existing class — no duplication)."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Position the roller slightly above and to the left of the card
            gpos = self.mapToGlobal(QPoint(50, 0))
            gpos.setX(gpos.x() - 90)
            gpos.setY(gpos.y() - 120)
            self._roller = SmartRoller(
                self.slider_ref.value(),
                self.color,
                self._from_roller,
                self.min_val,
                self.max_val,
                self.step
            )
            self._roller.move(gpos)
            self._roller.show()

    def _from_roller(self, val: int):
        """Callback from SmartRoller selection."""
        self.slider_ref.setValue(val)
        if self.release_callback:
            self.release_callback(self.index)

class ToggleBar(QFrame):
    """
    Slim vertical bar (≈10 px wide) placed at the right edge of the control zone.
    Clicking it emits `toggled` to switch between slider view and card view.
    Visible in both modes — it's always the rightmost element of the zone.
    """
    toggled = pyqtSignal()

    # macOS: dark scrim that blends with the window chrome
    # Windows: same colour works fine; both render border-radius identically in Qt 6
    _COL_REST  = "#111118"
    _COL_HOVER = "#2D2D45"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setFixedWidth(10)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(QApplication.translate("tilauscope_window", "Toggle: horizontal sliders  ↔  card controls"))
        self._hovered = False
        self._refresh()

    def _refresh(self):
        bg = self._COL_HOVER if self._hovered else self._COL_REST
        self.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border-radius: 5px;
                border: 1px solid #2A2A3C;
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit()

    def enterEvent(self, event):
        self._hovered = True
        self._refresh()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._refresh()
        super().leaveEvent(event)

class BigControlsRow(QWidget):
    """
    Horizontal row of 4 BigControlCard widgets (sliders 0-3).
    Replaces the 4 QHBoxLayout slider rows when the ToggleBar is clicked.

    card_configs is a list of tuples:
        (name, color, slider_ref, index, release_callback, unit, min_val, max_val, step)
    """

    def __init__(self, card_configs: list, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(5)

        self.cards: list[BigControlCard] = []
        for name, color, slider_ref, index, release_cb, unit, min_val, max_val, step in card_configs:
            card = BigControlCard(
                name, color, slider_ref, index, release_cb, unit, min_val, max_val, step
            )
            self.cards.append(card)
            layout.addWidget(card)

        layout.addStretch(1)   # keeps cards left-aligned; spare space fills right

# --- SLIDERS ---

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

class ClickableLabel(QLabel):
    clicked = pyqtSignal()  # Define a custom signal

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

# --- EXTRA DEVICES ---

class ExtraCounterWidget(QFrame):
    def __init__(self, name, color="#89B4FA"):
        super().__init__()

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(2)

        self.name_lbl = QLabel(name.upper())
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_lbl.setStyleSheet("color: #64748B; font-family: 'JetBrains Mono'; font-size: 10px; font-weight: 800; border: none;")

        self.val_lbl = QLabel("0.0")
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.val_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-family: 'JetBrains Mono'; font-weight: bold; border: none;")

        self.layout.addWidget(self.name_lbl)
        self.layout.addWidget(self.val_lbl)
        self.setMinimumWidth(75)

    def update_value(self, value):
        self.val_lbl.setText(f"{value}")

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
        self.container.setStyleSheet("""
            #ExtraContainer {
                background-color: rgba(24, 24, 37, 230);
                border: 2px solid #45475A;
                border-radius: 12px;
            }
        """)
        outer.addWidget(self.container)

        inner = QVBoxLayout(self.container)
        inner.setContentsMargins(4, 4, 4, self._GRIP_SIZE)
        inner.setSpacing(4)

        # ── title / drag bar ─────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(18)
        title_bar.setStyleSheet("background: transparent;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(4, 0, 4, 0)
        title_layout.setSpacing(0)

        dots_lbl = QLabel("⋯")
        dots_lbl.setStyleSheet(
            "color: #45475A; font-size: 12px; font-weight: bold; border: none;"
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

        # stretch so the flow area takes all available vertical space
        #inner.addStretch(1)

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
        color = "#89B4FA" if source_id == 1 else "#E5E54F"
        w = ExtraCounterWidget(name, color)
        self.inner_layout.addWidget(w)
        self.active_counters.append((w, source_id, idx))

    def reset_counters(self):
        """Reset all counter displays to dashes (used at power-off / start)."""
        qmc = self.artisan_conf.aw.qmc
        for widget, src, idx in self.active_counters:
            if qmc.LCDdecimalplaces:
                if qmc.intChannel(idx, 1 if src == 1 else 2):
                    widget.update_value("--")
                else:
                    widget.update_value("-.-")

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
        grip_color = QColor("#6c7086")
        p.setPen(grip_color)
        r = self.rect()
        # Draw three diagonal dotted lines (standard resize-grip look)
        gs = self._GRIP_SIZE
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
            #_log.info(f"restore position of extracounter panel w={saved_w} h={saved_h} x={pos_x} y={pos_y}")
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

    def mouseMoveEventCursor(self, event):
        """Update cursor shape when hovering near the resize grip."""
        if self._in_resize_grip(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        
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

# --- LCD READOUT ---

class LCDReadout(QFrame):
    """Custom LCD-style widget for Roaster Metrics.

    Alert background system
    -----------------------
    Lorsque alert_target est défini, le fond du compteur évolue progressivement
    au fur et à mesure que la valeur courante s'approche de la cible :

      - En dehors de la plage (valeur < target - range) : fond neutre #1a1a1a
      - Dans la plage d'approche [target-range … target] :
          0 %  → jaune foncé (#2a2200)  — « attention »
          50 % → orange foncé (#2a1000)
          100% → rouge intense (#3a0000)  — « danger »
      - Au-delà de la cible (dépassement) : rouge pulsant via QPropertyAnimation

    Appeler set_alert_value(float) à chaque rafraîchissement de mesure.
    Appeler reset_alert() pour revenir à l'état neutre (fin de rôtissage, OFF, etc.).
    """

    # Couleur de fond neutre (repos)
    _BG_NEUTRAL   = QColor("#1a1a1a")
    # Palier intermédiaires de l'alerte (approche)
    _BG_WARN      = QColor("#2a2200")   # jaune très sombre
    _BG_HOT       = QColor("#2a1000")   # orange sombre
    _BG_DANGER    = QColor("#3a0000")   # rouge sombre
    # Couleur de pulsation (dépassement total)
    _BG_OVERSHOT  = QColor("#5a0000")   # rouge vif

    def __init__(self, label: str, color: str, is_main: bool = False,
                 alert_target: float | None = None,
                 alert_range: float = 30.0):
        """
        Parameters
        ----------
        label        : texte du titre (ex. "BT °C")
        color        : couleur du texte / titre
        is_main      : True pour le compteur RoR (plus grand)
        alert_target : valeur seuil déclenchant l'alerte (ex. 230 pour BT/ET, 20 pour RoR)
                       None = pas d'alerte
        alert_range  : plage (en unité de la valeur) en-deçà de la cible où débute l'alerte
                       ex. 30 → alerte commence à target-30 (200°C si target=230°C)
        """
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._value_color   = color
        self._alert_target  = alert_target
        self._alert_range   = alert_range
        self._last_ratio    = -1.0   # Ratio précédent : évite les repaints inutiles
        self._last_ror_color = None  # Couleur RoR précédente : évite un reparse de style à chaque échantillon

        # Define hierarchy: Main (RoR) is larger, others are smaller
        fixed_width = 100 if is_main else 80  
        font_size_val = 24 if not is_main else 28 # On réduit un peu la police
        font_size_lab = 11
        min_height    = 80 if is_main else 70
    
        self.setMinimumWidth(80) # Sécurité minimale
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)        
        #self.setFixedWidth(fixed_width)  # <--- FORCE la largeur du bloc complet
        #self.setMinimumHeight(min_height)
        self._apply_bg(self._BG_NEUTRAL)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8) # Marges internes
        layout.setSpacing(2)                  # Espace réduit entre titre et valeur
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Label (Title)
        self.lbl_title = QLabel(label.upper()) # Upper pour le look pro
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet(
            f"color: {color}; "
            f"font-family: 'JetBrains Mono'; "
            f"font-weight: bold; "
            f"font-size: {font_size_lab}px; "
            "background: transparent;"
        )

        # Value (Data)
        self.lbl_value = QLabel("--")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # On utilise une largeur de ligne fixe (ex: 3 chiffres + point + 1 décimale)
        self.lbl_value.setStyleSheet(
            f"color: {color}; "
            f"font-family: 'JetBrains Mono'; "
            f"font-size: {font_size_val}px; "
            f"font-weight: 800; " # Plus épais pour la lisibilité
            "background: transparent;"
        )

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

        # --- Animation de pulsation pour le dépassement ---
        self._pulse_anim = QPropertyAnimation(self, b"_bg_color_prop", self)
        self._pulse_anim.setDuration(800)
        self._pulse_anim.setLoopCount(-1)   # boucle infinie
        self._pulse_anim.setKeyValueAt(0.0, self._BG_DANGER)
        self._pulse_anim.setKeyValueAt(0.5, self._BG_OVERSHOT)
        self._pulse_anim.setKeyValueAt(1.0, self._BG_DANGER)
        self._pulsing = False

    # ------------------------------------------------------------------
    # Propriété Qt animable pour la couleur de fond
    # ------------------------------------------------------------------

    def _get_bg_color(self) -> QColor:
        return self._current_bg

    def _set_bg_color(self, color: QColor) -> None:
        self._current_bg = color
        self._apply_bg(color)

    # pyqtProperty doit être déclaré après les accesseurs
    _bg_color_prop = pyqtProperty(QColor, fget=_get_bg_color, fset=_set_bg_color)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _apply_bg(self, color: QColor) -> None:
        """Met à jour le stylesheet du QFrame avec la couleur de fond donnée."""
        self._current_bg = color
        hex_bg = color.name()
        # Bord légèrement plus clair que le fond pour rester lisible
        border_color = color.lighter(140).name()
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {hex_bg};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QLabel {{ font-family: 'JetBrains Mono'; border: none; background: transparent; }}
        """)

    @staticmethod
    def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
        """Interpolation linéaire entre deux QColor (t ∈ [0, 1])."""
        t = max(0.0, min(1.0, t))
        r = int(c1.red()   + (c2.red()   - c1.red())   * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue()  + (c2.blue()  - c1.blue())  * t)
        return QColor(r, g, b)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def set_alert_value(self, value: float) -> None:
        """Mettre à jour la couleur de fond en fonction de la proximité de la cible.

        À appeler à chaque rafraîchissement de la valeur courante.
        Sans alert_target configuré, la méthode ne fait rien.
        """
        if self._alert_target is None:
            return

        delta = self._alert_target - value   # positif = on n'a pas encore atteint la cible

        # --- Dépassement : démarrer la pulsation ---
        if delta <= 0:
            if not self._pulsing:
                self._pulsing = True
                self._pulse_anim.start()
            return

        # --- Hors plage d'alerte : fond neutre ---
        if delta >= self._alert_range:
            ratio = 0.0
        else:
            # ratio 0.0 (début de la plage) → 1.0 (juste avant la cible)
            ratio = 1.0 - (delta / self._alert_range)

        # Optimisation : ne repeindre que si le ratio a significativement changé
        if abs(ratio - self._last_ratio) < 0.01:
            return
        self._last_ratio = ratio

        # Arrêter la pulsation si on redescend sous la cible
        if self._pulsing:
            self._pulsing = False
            self._pulse_anim.stop()

        # Interpolation en deux segments pour une transition douce
        #   0.0 → 0.5 : neutre → jaune-avertissement
        #   0.5 → 0.8 : jaune → orange
        #   0.8 → 1.0 : orange → rouge-danger
        if ratio < 0.5:
            bg = self._lerp_color(self._BG_NEUTRAL, self._BG_WARN, ratio / 0.5)
        elif ratio < 0.8:
            bg = self._lerp_color(self._BG_WARN, self._BG_HOT, (ratio - 0.5) / 0.3)
        else:
            bg = self._lerp_color(self._BG_HOT, self._BG_DANGER, (ratio - 0.8) / 0.2)

        self._apply_bg(bg)

    def reset_alert(self) -> None:
        """Revenir au fond neutre (appeler en fin de rôtissage ou lors du passage OFF)."""
        if self._pulsing:
            self._pulsing = False
            self._pulse_anim.stop()
        self._last_ratio = -1.0
        self._apply_bg(self._BG_NEUTRAL)

    # Paliers de couleur RoR (seuils en °C, adaptés si mode F)
    _ROR_PALETTE = [
        (0,   "#4FC3F7"),  # bleu  — négatif / nul
        (5,   "#6C7086"),  # gris  — 0–5
        (10,  "#A6E3A1"),  # vert  — 5–10  (idéal)
        (15,  "#F9E2AF"),  # jaune — 10–15
        (20,  "#FAB387"),  # orange — 15–20
    ]
    _ROR_RED = "#F38BA8"   # rouge — ≥ 20°C/min

    def set_ror_color(self, ror_value: float, mode: str = 'C') -> None:
        """Colorise lbl_value selon la valeur du RoR.
        Seuils en °C — multipliés par 1.8 si mode == 'F'.
        """
        factor = 1.8 if mode == 'F' else 1.0
        color = self._ROR_RED
        for threshold, col in reversed(self._ROR_PALETTE):
            if ror_value < threshold * factor:
                color = col
        # Fires on every RoR sample (even while only monitoring); the band —
        # hence the colour — changes rarely. Skip the stylesheet reparse when
        # the colour is unchanged.
        if color == self._last_ror_color:
            return
        self._last_ror_color = color
        self.lbl_value.setStyleSheet(
            f"color: {color}; font-family: 'JetBrains Mono'; "
            f"font-size: {24 if not hasattr(self,'_is_main') else 28}px; "
            "font-weight: 800; background: transparent;"
        )

    def init_minmax(self) -> None:
        """Réinitialise les trackers min/max — appeler au CHARGE."""
        self._mm_min: float | None = None
        self._mm_max: float | None = None
        # Restaurer le texte de base du titre (sans la ligne min/max)
        base = self.lbl_title.property("_base_text")
        if base:
            self.lbl_title.setText(base)
        self.lbl_title.setTextFormat(Qt.TextFormat.RichText)

    def update_minmax(self, value: float) -> None:
        """Met à jour min/max. Affiche en sous-titre discret dans lbl_title."""
        if not hasattr(self, '_mm_min') or self._mm_min is None:
            self._mm_min = value
            self._mm_max = value
        else:
            new_min = min(self._mm_min, value)
            new_max = max(self._mm_max, value)
            # Appelé à chaque échantillon BT/ET ; les extrêmes bougent rarement.
            # Sauter la reconstruction du rich-text quand aucune borne ne change.
            if new_min == self._mm_min and new_max == self._mm_max:
                return
            self._mm_min = new_min
            self._mm_max = new_max
        # Afficher ↓min / ↑max en petite ligne sous le label titre
        base_text = self.lbl_title.property("_base_text") or self.lbl_title.text()
        if not self.lbl_title.property("_base_text"):
            self.lbl_title.setProperty("_base_text", base_text)
        self.lbl_title.setText(
            f'{base_text}<br>'
            f'<span style="font-size:9px;color:#585B70;font-weight:400;">'
            f'↓{self._mm_min:.1f}  ↑{self._mm_max:.1f}</span>'
        )
        self.lbl_title.setTextFormat(Qt.TextFormat.RichText)

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
        self.ror_lcd = LCDReadout(
            QApplication.translate("Label", "RoR") + f" °{self.artisan_conf.mode}/m",
            self.artisan_conf.get_setting_color('deltabt'),
            is_main=True,
            alert_target=_danger_ror,
            alert_range=_range_ror,
        )

        # Adding to layout with Stretch Factors:
        # TG=1, TE=1, RoR=1.5 (RoR takes up 50% more width than the others)
        self.metrics_layout.addWidget(self.tg_lcd, stretch=2)
        self.metrics_layout.addWidget(self.te_lcd, stretch=2)
        self.metrics_layout.addWidget(self.ror_lcd, stretch=3)

        self.setStyleSheet("background-color: #0b0b0b;")
        self.setFixedWidth(360)

# --- ALARM SIDEBAR ---

class TriggeredAlarmBadge(QFrame):

    # Static mappings — built once at class definition, shared across all instances
    EVENT_NAMES: dict[int, str] = {
        9: "ON", -1: "START", 0: "CHARGE", 8: "TP", 1: "DRY END",
        2: "FC START", 3: "FC END", 4: "SC START", 5: "SC END", 6: "DROP",
        7: "COOL END", 10: "IF ALARM",
    }
    CAT_COLORS: dict[str, QColor] = {
        "PID": QColor("#448AFF"), "AIR": QColor("#69F0AE"),
        "DRUM": QColor("#00BFA5"), "BURNER": QColor("#FFD740"),
        "EXTERNAL": QColor("#FF5252"), "DEFAULT": QColor("#CFD8DC"),
    }
    ALARM_CONDS: list[str] = ['<', '>', '=', '\u2260']
    event_positions: dict[int, int] = {9: 100, -1: 250, 0: 400, 8: 550, 1: 700, 2: 850, 6: 1050}

    def __init__(self, alarm_data: AlarmData, aw: ApplicationWindow, action_list: dict, parent=None):
        super().__init__(parent)
        self.data = alarm_data
        self.aw = aw
        self.color = "#9DB09E"
        self.background_color = "#192A34"

        # action_list built once by AlarmSidebar and shared — avoids 28 translate() calls per badge
        self.ACTION_LIST = action_list

        # alarm_source offset +3 : [-3→idx0=None, -2→idx1=ΔET, -1→idx2=ΔBT, 0→idx3=ET, 1→idx4=BT, 2+→extra]
        _delta = QApplication.translate('Label', 'Delta')
        self.alarm_source_list: list[str] = [
            QApplication.translate('Label', 'None'),         # -3
            f"{_delta}ET",                                   # -2
            f"{_delta}BT",                                   # -1
            QApplication.translate('Label', 'ET'),           #  0
            QApplication.translate('Label', 'BT'),           #  1
        ]
        # Appendre les extra devices (même convention que le dialog Artisan)
        for i, name in enumerate(aw.qmc.extraname1):
            self.alarm_source_list.append(f"{name} ({QApplication.translate('Label','Extra')} {i+1}T1)")
        for i, name in enumerate(aw.qmc.extraname2):
            self.alarm_source_list.append(f"{name} ({QApplication.translate('Label','Extra')} {i+1}T2)")

        self.setFixedWidth(200)
        self.setMinimumHeight(60)
        
        # Style basé sur le style VisualAlarm de tilauscope
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {self.background_color}33; /* 20% Alpha */
                border: 2px solid {self.color};
                border-radius: 10px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(2)
        
        # Header: ID et Source
        header = QLabel(QApplication.translate("Label","Alarm")+f" #{self.data.index + 1}")
        header.setStyleSheet(f"color: {self.color}; font-weight: 900; font-size: 9px; border: none;")
        
        # Message / Action
        msg = QLabel(self.define_text(alarm_data))
        msg.setStyleSheet("color: white; font-weight: normal; font-size: 9px; border: none;")
        msg.setWordWrap(True)
        
        layout.addWidget(header)
        layout.addWidget(msg)

        # Animation d'entrée (Fade + Slide)
        self.setWindowOpacity(0)
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(500)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def define_text(self, alarm:AlarmData)->str:
        if alarm.event_code == 10:
            if alarm.previous_alarm > 0:
                header = f"#{alarm.index+1} | "+QApplication.translate("tilauscope_window","IF ALARM")+f" #{alarm.previous_alarm}, "+QApplication.translate("tilauscope_window","at")+f" +{alarm.offset}s "+QApplication.translate("tilauscope_window","do")
            elif alarm.not_alarm > 0:
                header = f"#{alarm.index+1} | "+QApplication.translate("tilauscope_window","IF NOT ALARM")+f" #{alarm.not_alarm}, "+QApplication.translate("tilauscope_window","at")+f" +{alarm.offset}s "+QApplication.translate("tilauscope_window","do")
        else:
            header = f"{self.EVENT_NAMES.get(alarm.event_code, 'ALARM')} +{alarm.offset}s"
        # Annotation Box
        if alarm.action == 25 or alarm.action >= 8 and alarm.action <= 25:
            body =  f"{self.ACTION_LIST.get(alarm.action, 'Action')}"
            body += f" ({alarm.msg})\n" if alarm.msg else ""    
        else:
            body = f"{self.ACTION_LIST.get(alarm.action, 'Action')}={alarm.msg}"
        if alarm.alarm_source != -3:
            if alarm.alarm_source +3 < len(self.alarm_source_list):
                source_txt = self.alarm_source_list[alarm.alarm_source+3]
            else:
                source_txt = self.alarm_source_list[3]
            body += f"\nIF {source_txt} {self.ALARM_CONDS[alarm.alarm_cond]} {alarm.alarm_temperature}"
        return f"{header}\n{body}"

class EventFiredBadge(QFrame):
    """Carte affichée dans AlarmSidebar lors d'un appui sur un bouton EventPanel.

    Style : fond #1E1E2E, bordure gauche 4 px couleur Artisan, tag EVT,
    fade-in 400 ms identique à TriggeredAlarmBadge.
    """

    def __init__(self, label: str, command: str, timestamp: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setMinimumHeight(60)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #1E1E2E;
                border: 1px solid {color}33;
                border-left: 4px solid {color};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        # Ligne header : tag EVT + timestamp
        header_row = QHBoxLayout()
        tag = QLabel("EVT")
        tag.setStyleSheet(f"color: {color}; font-weight: 900; font-size: 9px; border: none; letter-spacing: 1px;")
        ts_lbl = QLabel(timestamp)
        ts_lbl.setStyleSheet("color: #585B70; font-size: 9px; border: none;")
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(tag)
        header_row.addStretch(1)
        header_row.addWidget(ts_lbl)
        layout.addLayout(header_row)

        # Label du bouton
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11px; border: none;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        # Commande (si disponible)
        if command:
            cmd_lbl = QLabel(command)
            cmd_lbl.setStyleSheet("color: #6C7086; font-size: 9px; border: none;")
            cmd_lbl.setWordWrap(True)
            layout.addWidget(cmd_lbl)

        # Fade-in 400 ms
        self.setWindowOpacity(0.0)
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(400)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

class AlarmSidebar(QWidget):
    def __init__(self, aw : ApplicationWindow, parent=None):
        super().__init__(parent)
        self.aw = aw
        self.setMinimumWidth(0)   # let parent drive width
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(5)
        
        # ── Barre de titre : LIVE EVENTS | compteur | bouton clear ────────
        title_row = QHBoxLayout()
        title_row.setContentsMargins(2, 0, 2, 0)
        title_row.setSpacing(4)

        lbl = QLabel(QApplication.translate("tilauscope_window", "LIVE EVENTS"))
        lbl.setStyleSheet(f"color: {THEME['ACCENT']}; font-weight: bold; font-family: 'JetBrains Mono';")
        title_row.addWidget(lbl, 1)

        # Compteur de cartes
        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; background: #313244; font-size: 9px; font-weight: 700;"
            "border-radius: 8px; padding: 1px 6px; font-family: 'JetBrains Mono';"
        )
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setFixedHeight(16)
        title_row.addWidget(self._count_lbl)

        # Bouton clear
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(18, 18)
        clear_btn.setToolTip(QApplication.translate("tilauscope_window", "Clear all events"))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #313244; color: #6C7086;
                border-radius: 4px; border: none;
                font-size: 9px; font-weight: bold;
            }
            QPushButton:hover { background: #45475A; color: #F38BA8; }
            QPushButton:pressed { background: #F38BA8; color: #1E1E2E; }
        """)
        clear_btn.clicked.connect(self._clear_all_badges)
        title_row.addWidget(clear_btn)

        self.layout.addLayout(title_row)

        # Zone scrollable pour les badges
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: #1E1E2E; width: 6px; margin: 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #45475A; min-height: 20px; border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover { background: #585B70; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._badges_widget = QWidget()
        self._badges_widget.setStyleSheet("background: transparent;")
        self._badges_layout = QVBoxLayout(self._badges_widget)
        self._badges_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._badges_layout.setSpacing(5)
        self._badges_layout.setContentsMargins(6, 4, 6, 4)
        self._scroll.setWidget(self._badges_widget)
        self.layout.addWidget(self._scroll, 1)

        self.badges = []

        # Build ACTION_LIST once — etypesf() values are stable for the session lifetime
        qmc = self.aw.qmc
        self._action_list: dict[int, str] = {
            0:  QApplication.translate('ComboBox', 'Pop Up'),
            1:  QApplication.translate('ComboBox', 'Call Program'),
            2:  QApplication.translate('ComboBox', 'Event Button'),
            3:  QApplication.translate('ComboBox', 'Slider') + ' ' + qmc.etypesf(0),
            4:  QApplication.translate('ComboBox', 'Slider') + ' ' + qmc.etypesf(1),
            5:  QApplication.translate('ComboBox', 'Slider') + ' ' + qmc.etypesf(2),
            6:  QApplication.translate('ComboBox', 'Slider') + ' ' + qmc.etypesf(3),
            7:  QApplication.translate('ComboBox', 'START'),
            8:  QApplication.translate('Label',    'DRY END'),
            9:  QApplication.translate('Label',    'FC START'),
            10: QApplication.translate('Label',    'FC END'),
            11: QApplication.translate('Label',    'SC START'),
            12: QApplication.translate('Label',    'SC END'),
            13: QApplication.translate('Label',    'DROP'),
            14: QApplication.translate('ComboBox', 'COOL END'),
            15: QApplication.translate('ComboBox', 'OFF'),
            16: QApplication.translate('Label',    'CHARGE'),
            17: QApplication.translate('ComboBox', 'RampSoak ON'),
            18: QApplication.translate('ComboBox', 'RampSoak OFF'),
            19: QApplication.translate('ComboBox', 'PID ON'),
            20: QApplication.translate('ComboBox', 'PID OFF'),
            21: QApplication.translate('ComboBox', 'SV'),
            22: QApplication.translate('ComboBox', 'Playback ON'),
            23: QApplication.translate('ComboBox', 'Playback OFF'),
            24: QApplication.translate('ComboBox', 'Set Canvas Color'),
            25: QApplication.translate('ComboBox', 'Reset Canvas Color'),
            26: QApplication.translate('Combobox', 'Airwave'),
            27: QApplication.translate('Combobox', 'TilauScope Ambient'),
            28: QApplication.translate('Combobox', 'TilauScope kernel'),
        }

        # get alarms from artisan
        raw_alarms = self.get_current_alarms_data()
        self.current_alarms:list[AlarmData] = []
        # convert alarms structure to class data object
        self._load_alarms(raw_alarms)

    def get_current_alarms_data(self):    
        alarms:dict[str, list[int]|list[float]|list[str]] = {}
        alarms['alarmflags'] = self.aw.qmc.alarmflag
        alarms['alarmguards'] = self.aw.qmc.alarmguard
        alarms['alarmnegguards'] = self.aw.qmc.alarmnegguard
        alarms['alarmtimes'] = self.aw.qmc.alarmtime
        alarms['alarmoffsets'] = self.aw.qmc.alarmoffset
        alarms['alarmconds'] = self.aw.qmc.alarmcond
        alarms['alarmsources'] = self.aw.qmc.alarmsource
        alarms['alarmtemperatures'] = self.aw.qmc.alarmtemperature
        alarms['alarmactions'] = self.aw.qmc.alarmaction
        alarms['alarmbeep'] = self.aw.qmc.alarmbeep
        alarms['alarmstrings'] = self.aw.qmc.alarmstrings
        return alarms

    def buildAlarmSourceList(self) -> list[str]:
            extra_names = []
            for i in range(len(self.aw.qmc.extradevices)):
                extra_names.append(self.aw.qmc.device_name_subst(self.aw.qmc.extraname1[i]))
                extra_names.append(self.aw.qmc.device_name_subst(self.aw.qmc.extraname2[i]))
            et_name = self.aw.qmc.device_name_subst(self.aw.ETname)
            bt_name = self.aw.qmc.device_name_subst(self.aw.BTname)
            return ['',
                deltaLabelUTF8 + et_name,
                deltaLabelUTF8 + bt_name,
                et_name,
                bt_name] + extra_names

    def _get_info(self, action_id):
        mapping = {19: ("PID", -220), 20: ("PID", -220), 3: ("AIR", 100), 4: ("DRUM", 180), 6: ("BURNER", 260), 27: ("EXTERNAL", 340)}
        return mapping.get(action_id, ("DEFAULT", -120))

    def _load_alarms(self, data):
        self.alarm_objects = []
        for i in range(len(data.get("alarmflags", []))):
            if data["alarmflags"][i] == 1:
                action = data["alarmactions"][i]
                cat, _ = self._get_info(action)
                alarm_raw = AlarmData(index=i, event_code=data["alarmtimes"][i], offset=data["alarmoffsets"][i], action=action, msg=data["alarmstrings"][i], previous_alarm=data["alarmguards"][i], not_alarm=data["alarmnegguards"][i], alarm_source=data["alarmsources"][i], alarm_cond=data["alarmconds"][i], alarm_temperature=data["alarmtemperatures"][i], is_active=True)
                self.current_alarms.append(alarm_raw)

    def get_alarm_info(self, alarm_index:int)->AlarmData:
        return next((a for a in self.current_alarms if a.index == alarm_index), None)

    def _update_count(self) -> None:
        """Met à jour le label compteur."""
        n = len(self.badges)
        self._count_lbl.setText(str(n))
        self._count_lbl.setVisible(n > 0)

    def _clear_all_badges(self) -> None:
        """Vide toutes les cartes de la sidebar."""
        for badge in self.badges:
            self._badges_layout.removeWidget(badge)
            badge.deleteLater()
        self.badges.clear()
        self._update_count()

    def _trim_badges(self, max_count: int = 20) -> None:
        """Supprime les badges les plus anciens au-delà de max_count."""
        while len(self.badges) > max_count:
            old = self.badges.pop()
            self._badges_layout.removeWidget(old)
            old.deleteLater()
        self._update_count()

    def add_triggered_alarm(self, alarm_data: AlarmData) -> None:
        badge = TriggeredAlarmBadge(alarm_data, self.aw, self._action_list)
        self._badges_layout.insertWidget(0, badge)
        self.badges.insert(0, badge)
        self._trim_badges()

    def add_event_badge(self, label: str, command: str, timestamp: str, color: str) -> None:
        """Ajoute une carte EVT (bouton event panel) dans la sidebar."""
        badge = EventFiredBadge(label, command, timestamp, color)
        self._badges_layout.insertWidget(0, badge)
        self.badges.insert(0, badge)
        self._trim_badges()

# ─── Grip tab (always visible, 16 px wide) ──────────────────────────────────

class _GripTab(QWidget):
    """
    A slim vertical strip that acts as the sole toggle control.

    Visual design:
      • Collapsed state : lavender background, "›" chevron, tooltip "Show events"
      • Expanded state  : dark background, "‹" chevron, tooltip "Hide events"
      • Three dots in the middle act as a drag/grip hint (purely cosmetic).

    Works identically on macOS and Windows because it uses solid colours only
    (no WA_TranslucentBackground, no blur — those are unreliable on Windows).
    """

    clicked = pyqtSignal()   # emitted on left-click anywhere on the strip

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True   # tracks sidebar state
        self.setFixedWidth(GRIP_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_tooltip()

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Background
        if self._expanded:
            bg = QColor(_COL_SURFACE0)
        else:
            bg = QColor(_COL_LAVENDER)
        p.fillRect(0, 0, w, h, bg)

        # Three grip dots (cosmetic only)
        dot_color = QColor(_COL_TEXT if self._expanded else _COL_BASE)
        dot_color.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_color)
        cx = w // 2
        for dy in (-8, 0, 8):
            p.drawEllipse(cx - 2, h // 2 + dy - 2, 4, 4)

        p.end()

    # ── Interaction ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ── State update (called by CollapsibleLiveEvents) ────────────────────────

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._update_tooltip()
        self.update()   # repaint

    def _update_tooltip(self):
        if self._expanded:
            self.setToolTip(QApplication.translate("tilauscope_window","Hide live events  ‹"))
        else:
            self.setToolTip(QApplication.translate("tilauscope_window","Show live events  ›"))

# ─── Sidebar wrapper (thin layer around AlarmSidebar) ───────────────────────

class _SidebarWrapper(QWidget):
    """
    Wraps AlarmSidebar and owns a header label (LIVE EVENTS title).
    Width is hard-fixed to SIDEBAR_W; show/hide is managed externally.

    An opacity fade of 150 ms plays on show/hide for a polished feel
    without touching geometry (safe inside a stretch layout).
    """

    def __init__(self, aw, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar (matches grip tab height visually)
#        header = QWidget()
#        header.setFixedHeight(28)
#        header.setStyleSheet(f"background: {_COL_SURFACE0};")
#        h_lyt = QHBoxLayout(header)
#        h_lyt.setContentsMargins(8, 0, 8, 0)
#        lbl = QLabel("LIVE EVENTS")
#        lbl.setStyleSheet(
#            f"color: {_COL_LAVENDER}; font-size: 10px; font-weight: 800; "
#            "font-family: 'JetBrains Mono'; letter-spacing: 1px; border: none;"
#        )
#        h_lyt.addWidget(lbl)
#        h_lyt.addStretch()

        # Alarm sidebar (imported from same module — AlarmSidebar is defined
        # in displayscope.py above this class)
        self.alarm_sidebar = AlarmSidebar(aw, self)   # noqa: F821
        # AlarmSidebar sets setFixedWidth(200) internally — we need to remove
        # that or it fights our own fixed width. Override with setSizePolicy.
        self.alarm_sidebar.setMinimumWidth(0)
        self.alarm_sidebar.setMaximumWidth(SIDEBAR_W)
        self.alarm_sidebar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        #layout.addWidget(header)
        layout.addWidget(self.alarm_sidebar, stretch=1)

        # ── Ticker messages Artisan (sous les badges alarmes/events) ──────────
        self.msg_ticker = ArtisanMessageTicker(self)
        layout.addWidget(self.msg_ticker, stretch=0)   # hauteur fixe, pas de stretch

        self.setStyleSheet(f"background: {_COL_BASE}; border-left: 1px solid {_COL_SURFACE0};")

        # Opacity effect for the fade animation
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_fx)

        self._fade_anim = QPropertyAnimation(self._opacity_fx, b"opacity")
        self._fade_anim.setDuration(150)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def fade_in(self):
        self._fade_anim.stop()
        self.setVisible(True)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def fade_out(self):
        self._fade_anim.stop()
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._hide_after_fade)
        self._fade_anim.start()

    def _hide_after_fade(self):
        self._fade_anim.finished.disconnect(self._hide_after_fade)
        self.setVisible(False)

# ─── Public façade ───────────────────────────────────────────────────────────

class CollapsibleLiveEvents:
    """
    NOT a QWidget itself — it is a controller that owns two widgets:

        .grip    → _GripTab    (always in the layout, 16 px wide)
        .sidebar → _SidebarWrapper  (shown/hidden, 200 px wide)

    Usage in displayscope.py  (replace the two old lines):
    ───────────────────────────────────────────────────────
        self.collapsible_events = CollapsibleLiveEvents(self.aw, parent_widget)
        content_layout.addWidget(self.collapsible_events.grip,    stretch=0)
        content_layout.addWidget(self.collapsible_events.sidebar, stretch=0)

    Public API
    ----------
        .is_expanded          → bool
        .toggle()             → toggle sidebar visibility
        .expand()  / .collapse()
        .alarm_sidebar        → direct reference to AlarmSidebar instance
    """

    def __init__(self, aw, parent=None):
        self.aw          = aw
        self.settings = QSettings()
        # Par défaut True si la clé n'existe pas encore
        self._is_expanded = self.settings.value("tilauscope/show_live_events", True, type=bool)

        self.grip = _GripTab(parent)
        self.sidebar = _SidebarWrapper(aw, parent)

        self.grip.clicked.connect(self.toggle)
        self.apply_initial_state()


    def apply_initial_state(self):
        """Applique l'état sans transition au démarrage."""
        self.grip.set_expanded(self._is_expanded)
        self.sidebar.setVisible(self._is_expanded)
        if self._is_expanded:
            self.sidebar._opacity_fx.setOpacity(1.0)
        else:
            self.sidebar._opacity_fx.setOpacity(0.0)

    # ── Public API ────────────────────────────────────────────────────────────

    def toggle(self):
        if self._is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self):
        self.is_expanded = True
        self.grip.set_expanded(True)
        self.sidebar.fade_in()

    def collapse(self):
        self.is_expanded = False
        self.grip.set_expanded(False)
        self.sidebar.fade_out()

    @property
    def alarm_sidebar(self):
        return self.sidebar.alarm_sidebar

    @property
    def is_expanded(self):
        """Lecture seule pour les composants externes."""
        return self._is_expanded

    @is_expanded.setter
    def is_expanded(self, value:bool):
        if self._is_expanded != value:
            self._is_expanded = value
            self.settings.setValue("tilauscope/show_live_events", value)
            self.settings.sync() # Force l'écriture immédiate sur le disque

# --- SURCHARGE DES MENUS ---

ARROW = "url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNDREQ2RjQiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cG9seWxpbmUgcG9pbnRzPSI5IDE4IDE1IDEyIDkgNiI+PC9wb2x5bGluZT48L3N2Zz4=)"     

# Use Python 3.14 f-strings for cleaner theme integration
MENU_STYLE = """
    QMenu {
        background-color: #1E1E2E; /* Background of the menu */
        border: 1px solid #313244;
        color: #CDD6F4;
        padding: 4px;
    }

    QMenu::item {
        padding: 6px 24px 6px 24px;
        border-radius: 4px;
        min-width: 150px;
    }

    /* Distinctive color for hovered/selected items */
    QMenu::item:selected {
        background-color: #313244;
        color: #F5E0DC;
    }

    /* 1. Handling Disabled Lines: Lower opacity or specific muted color */
    QMenu::item:disabled {
        color: #585B70; /* Muted gray for disabled inputs */
        background-color: transparent;
    }

    /* 2. Handling Checked Inputs: Highlight checked state */
    QMenu::item:checked {
        font-weight: bold;
        color: #A6E3A1; /* Distinctive green for checked items */
    }

    /* Styling the check indicator itself */
    QMenu::indicator:checked {
        image: url(check_icon.png); /* Optional: path to an icon */
        width: 12px;
        height: 12px;
        margin-left: 5px;
    }

    /* Distinctive styling for separators */
    QMenu::separator {
        height: 1px;
        background: #313244;
        margin: 4px 10px;
    }

    QMenu::icon {
        left: 5px;
        /* Ce filtre inverse les couleurs de l'icône (Noir -> Blanc) */
        /* Note: 'invert' est supporté par certains moteurs de rendu Qt6 
           Sinon, on joue sur l'opacité ou le remplacement via QProxyStyle */
    }
"""

# --- PLAYBACK CHECK BEFORE ROASTING --- 

class PlaybackWarningDlg(QDialog):
    """
    Boîte de dialogue de sécurité pour TilauScope.
    Prévient l'utilisateur si des automatismes de playback sont actifs au départ.
    """
    # Constantes de retour pour identifier le choix
    CONTINUE: Final = 1
    CANCEL: Final = 0
    DISABLE_AND_START: Final = 2

    def __init__(self, parent: QWidget, active_modes: list[str]) -> None:
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            QDialog       { background-color: #ffffff; border: 1px solid #2c3e50; }
            QTextEdit     { border: none; background: transparent; color: #2c3e50; font-size: 12px; }
            QLabel#Header { font-weight: bold; font-size: 13px; color: #2c3e50; }
        """)
        # ── Outer shell (gives the translucent rounded frame) ──────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("PlaybackWarning")
        card.setStyleSheet(f"""
            #PlaybackWarning {{
                background-color : {THEME['BG']};
                border           : 2px solid {THEME['ACCENT']};
                border-radius    : 14px;
            }}
        """)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ── Icon + title ───────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        icon_lbl = QLabel("🫘")
        icon_lbl.setStyleSheet("font-size: 26px;")
        title_lbl = QLabel(QApplication.translate("tilauscope_window", "TilauScope Security"))
        title_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 14px;
            font-weight : 800;
            letter-spacing: 1px;
        """)

        title_row.addWidget(icon_lbl)
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        root.addLayout(title_row)
        # ── Separator ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {THEME.get('BORDER', '#3f3f3f')};")
        root.addWidget(sep)

        q_lbl = QLabel()
        q_lbl.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(48, 48))
        q_lbl.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 11px;
        """)
        root.addWidget(q_lbl)
    
        modes_str = ", ".join(active_modes)
        text = (f"<b>{QApplication.translate('Message', 'WARNING REPLAY AUTOMATISM ARE ACTIVE')}</b><br><br>"
                f"the following Features are activated on your background profile to replay events:<br><br>"
                f"<span style='color: #e74c3c;'><b>{modes_str}</b></span><br><br>"
                f"Do you really want to start the roast or review your configuration?")
        
        label = QLabel(text)
        label.setStyleSheet(f"""
            color       : {THEME['ACCENT']};
            font-family : 'JetBrains Mono', monospace;
            font-size   : 11px;
        """)
        label.setWordWrap(True)
        root.addWidget(label)

        self.result_code = self.CANCEL
        # ── Buttons ────────────────────────────────────────────────────────
        btn_style_primary = f"""
            QPushButton {{
                background-color : {THEME['ACCENT']};
                color            : {THEME['BG']};
                border           : none;
                border-radius    : 6px;
                padding          : 8px 18px;
                font-family      : 'JetBrains Mono', monospace;
                font-size        : 11px;
                font-weight      : 700;
            }}
            QPushButton:hover {{
                background-color : {THEME.get('HOVER', THEME['ACCENT'])};
            }}
            QPushButton:pressed {{
                background-color : {THEME.get('SURFACE', '#1e1e2e')};
                color            : {THEME['ACCENT']};
                border           : 1px solid {THEME['ACCENT']};
            }}
        """
        
        # Boutons
        btn_layout = QHBoxLayout()
        
        self.btn_cancel = QPushButton(QApplication.translate('Button', 'Cancel Roasting'))
        self.btn_cancel.setStyleSheet(btn_style_primary)       
        self.btn_disable = QPushButton(QApplication.translate('Button', 'Deactivate all and Roast'))
        self.btn_disable.setStyleSheet(btn_style_primary)       
        self.btn_continue = QPushButton(QApplication.translate('Button', 'Continue as is'))
        self.btn_continue.setStyleSheet(btn_style_primary)       
 
        # Style pour le bouton principal de désactivation
#        self.btn_disable.setStyleSheet("font-weight: bold; padding: 5px;")

        # Gestion de l'ordre des boutons (Native Look)
        if _IS_MACOS: # macOS
            btn_layout.addWidget(self.btn_cancel)
            btn_layout.addStretch()
            btn_layout.addWidget(self.btn_continue)
            btn_layout.addWidget(self.btn_disable)
        else: # Windows / Linux
            btn_layout.addStretch()
            btn_layout.addWidget(self.btn_disable)
            btn_layout.addWidget(self.btn_continue)
            btn_layout.addWidget(self.btn_cancel)

        root.addLayout(btn_layout)

        # Connexions
        self.btn_cancel.clicked.connect(self.do_cancel)
        self.btn_continue.clicked.connect(self.do_continue)
        self.btn_disable.clicked.connect(self.do_disable)

    def do_cancel(self):
        self.result_code = self.CANCEL
        self.reject()

    def do_continue(self):
        self.result_code = self.CONTINUE
        self.accept()

    def do_disable(self):
        self.result_code = self.DISABLE_AND_START
        self.accept()

# --- APPLICATION PRINCIPALE ---

# Catppuccin Mocha mapping for Artisan qmc.palette keys
_CATPPUCCIN_QMC: dict[str, str] = {
    'canvas':           '#1E1E2E',  # Base
    'background':       '#181825',  # Mantle
    'grid':             '#313244',  # Surface0
    'et':               '#FAB387',  # Peach  — ET curve
    'bt':               '#89B4FA',  # Blue   — BT curve
    'deltaet':          '#F9E2AF',  # Yellow — RoR ET
    'deltabt':          '#A6E3A1',  # Green  — RoR BT
    'title':            '#CDD6F4',  # Text
    'xlabel':           '#94A3B8',  # Subtext1
    'ylabel':           '#94A3B8',
    'text':             '#CDD6F4',
    'messages':         '#CDD6F4',
    'markers':          '#CDD6F4',
    'timeguide':        '#585B70',  # Surface2
    'aucguide':         '#89DCEB',  # Sky
    'aucarea':          '#313244',  # Surface0
    'watermarks':       '#45475A',  # Surface1
    'legendbg':         '#181825',  # Mantle
    'legendborder':     '#313244',  # Surface0
    'rect1':            '#45475A',  # CHARGE→DRY    Surface1
    'rect2':            '#585B70',  # DRY→FCs       Surface2
    'rect3':            '#6C7086',  # FCs→FCe       Overlay0
    'rect4':            '#7F849C',  # FCe→SCs       Overlay1
    'rect5':            '#9399B2',  # SCs→DROP      Overlay2
    'mettext':          '#FAB387',  # Peach — MET annotation
    'metbox':           '#181825',
    'specialeventtext': '#CDD6F4',
    'specialeventbox':  '#313244',
    'bgeventtext':      '#94A3B8',
    'bgeventmarker':    '#45475A',
    'xt':               '#CBA6F7',  # Mauve — extra curves bg tint
    'yt':               '#F5C2E7',  # Pink
}

# Catppuccin Mocha LCD foreground per channel
_CATPPUCCIN_LCD_FG: dict[str, str] = {
    'timer':           '#CDD6F4',  # Text
    'et':              '#FAB387',  # Peach
    'bt':              '#89B4FA',  # Blue
    'deltaet':         '#F9E2AF',  # Yellow
    'deltabt':         '#A6E3A1',  # Green
    'sv':              '#CBA6F7',  # Mauve
    'rstimer':         '#94A3B8',  # Subtext1
    'slowcoolingtimer':'#94A3B8',
}

# All LCD backgrounds → Mantle
_CATPPUCCIN_LCD_BG: dict[str, str] = {k: '#181825' for k in _CATPPUCCIN_LCD_FG}

class TilauScope(QWidget):

    alarm_fired_signal = pyqtSignal(int)

    # Phase progress mapping — hot BT path (per sample). Class constants so the
    # per-sample handler never re-allocates these lists.
    _PHASE_KEYS   = ("DRY", "MAI", "DEV")          # ordered
    _PHASE_BOUNDS = ((0, 1), (1, 2), (2, 3))       # indices dans qmc.phases

    def __init__(self, aw: ApplicationWindow, message:str = ""):
        super().__init__(None)

        #_logd.info("tilauscope started")
        self.aw = aw

        # Initialisation du pont Artisan
        self.artisan_conf = ArtisanSettings(aw)
        self.theme = self.artisan_conf.get_theme_colors()

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        if _IS_MACOS: 
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        if _IS_WINDOWS:
            # Empêche TilauScope de voler le focus au retour des dialogues
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
            # Déclare TilauScope comme fenêtre "tool" pour Windows
            self.setWindowFlag(Qt.WindowType.Tool, False)   
                
        self.setObjectName("TilauScopeWindow")
        self.setStyleSheet("#TilauScopeWindow { background-color: #1E1E2E; border-radius: 12px; }")

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1E1E2E"))
        self.setPalette(palette)
        
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # list of objects in artisan that are hidden/shown to enter tilauscope mode
        self.show_controls:list[int] = []
        self.show_lcds:list[int] = []
        self.show_minieventline:list[int] = []
        self.show_extrabuttons:list[int] = []
        self.show_sliders:list[int] = []
        self.transformArtisan_ui()

        # Initialisation cruciale pour éviter le Traceback
        self.is_roasting = self.artisan_conf.aw.qmc.flagstart
        self.start_time = None  # <--- On commence à None
        
        self.last_update_second = -1
        self._last_extra_update = 0.0   ## TILAU ## throttle horodaté du panneau extra (≤ 1 Hz)

        self.root_menu:QMenu|None = None
        self.init = True
        ## TILAU ## re-entrancy guard: True while mirroring Artisan slider values
        ## into our sliders, so their valueChanged does not push back to Artisan.
        self._syncing_from_artisan = False
        ## TILAU ## one debounce timer per slider index (see handle_ui_input_released)
        self._slider_commit_timers: dict[int, QTimer] = {}
        ## TILAU ## SV row widgets + lock state (read-only while TilauPID preheats)
        self._sv_widgets: tuple = ()
        self._sv_locked: bool = False

        ## TILAU ## Main store: this used to be QSettings("Artisan","TilauScope"), a
        ## separate file written under Artisan's name. Key is namespaced, so it
        ## folds in without collision; the old value is carried by settings_migration.
        self.is_swapped = QSettings().value("interface/swap_events_control", False, type=bool) # shall we swap content?

        self.init_ui()
        
        if self.aw:
            parent_geo = self.aw.geometry()        
            self.setGeometry(parent_geo)
            
            # 1. Match the width
            self.event_panel.setFixedWidth(parent_geo.width())
            # 2. Tell the panel to recalculate height for this new width
            self.event_panel.update_panel_height()
            # 3. Position it
            self.event_panel.move(parent_geo.x(), parent_geo.y() + parent_geo.height())

        # Initialize Pulse Timer with an efficient interval
        self.p_timer = QTimer(self)
        self.p_timer.timeout.connect(self.pulse)
        self.p_timer.setInterval(600)  # Optimized: 600ms is a natural "breathing" rhythm
        self.p_state = True
        # Add Opacity Effect to the timer label (GPU accelerated)
        self._timer_state = "idle"
        self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
        self.timer_lbl.setGraphicsEffect(self.timer_opacity)
        self.p_timer.start()

        # counters for phase shift, last_phase holds the phase from the last cycle to compare to current_phase during processing
        self.phase_starts = {"DRY": None, "MAI": None, "DEV": None}
        self.current_phase = None
        self.last_phase = None
        self.current_event = None

        # ── Détection automatique du refroidissement post-DROP ────────────────
        # On surveille temp2 (BT) : si chute > 10°C en < 30s → handle_cooling()
        self._drop_done: bool = False               # True dès que DROP est validé
        self._cooling_detected: bool = False        # True dès que la chute est détectée
        self._bt_at_drop: float | None = None       # BT au moment du DROP
        self._bt_drop_timestamp: float | None = None  # temps (timex) au DROP

        # mouse move tracking
        self.oldPos:QPoint | None = None
        self._drag_origin:QPoint | None = None  # drag handle origin
        self._drag_self_origin:QPoint = QPoint() # TilauScope pos at drag start
        self._dragging:bool = False              # inhibe _safe_raise pendant drag

        # track if we are preheating
        self.preheating = False

        self._is_simulator = bool(self.artisan_conf.aw.simulator)

        QTimer.singleShot(500, self.focusOn)

        self.aw.tilauscopeMain.setChecked(True)

        ## TILAU ## Shift+T view-toggle from within TilauScope. The act_main
        ## QAction/shortcut lives on the Artisan window, which is hidden (and thus
        ## receives no key events) in headless mode — so we register a window-local
        ## shortcut here so Shift+T reaches tilauscopeCall() while TilauScope has
        ## focus. Harmless in normal mode (Artisan stays visible on toggle).
        self._view_toggle_sc = QShortcut(QKeySequence("Shift+T"), self)
        self._view_toggle_sc.activated.connect(self.aw.tilauscopeCall)

        # static strings 
        self.str_preheating  =  QApplication.translate("tilauscope_window","PREHEATING ")  
        self.str_autocharge =  QApplication.translate("tilauscope_window","AUTO-CHARGE ENGAGED")
        self.str_autodry    =  QApplication.translate("tilauscope_window","AUTO-DRY ENGAGED")
        self.str_autofc     =  QApplication.translate("tilauscope_window","AUTO-FC ENGAGED")
        self.str_autodrop   =  QApplication.translate("tilauscope_window","AUTO-DROP ENGAGED")
        self.str_roastsession =  QApplication.translate("tilauscope_window","roast session started")
        self.str_simulator =  QApplication.translate("tilauscope_window","SIMULATOR")
        self.str_paused =  QApplication.translate("tilauscope_window","PAUSED")
        self.str_nopid = QApplication.translate("tilauscope_window","with no PID")
        self.str_artisanpid = QApplication.translate("tilauscope_window","with ArtisanPID to")
        self.str_tilaupid= QApplication.translate("tilauscope_window","with Tilauscope PID to")
        self.str_tilaupid_close = QApplication.translate("tilauscope_window", "<br><br>PREPARE YOURSELF TO <b>CHARGE</b> THE BEANS!")
        self.str_tilaupidinit = QApplication.translate("tilauscope_window", "TilauPID is initializing, please wait...")

        # _update_automation_banner() runs once/sec from the TIMER path — these
        # must be pre-translated here, never re-translated inside the 1Hz tick.
        self.str_automation_pid           = QApplication.translate("tilauscope_window", "PID")
        self.str_automation_replay_events = QApplication.translate("tilauscope_window", "Replay Events")
        self.str_automation_auto_drop     = QApplication.translate("tilauscope_window", "Auto-DROP")
        self.str_automation_playback_aid  = QApplication.translate("tilauscope_window", "Playback Aid")
        self.str_automation_prefix        = QApplication.translate("tilauscope_window", "⚠ AUTOMATED ROAST")

        self.is_pid_active:bool = False
        self.aw.pidcontrol.activateSVSlider(True)
        self.curr_bt:float = None

        if self.artisan_conf.aw.TilauScopeNotification:
            self.check_daily_brew_status()
            from tilauscope.routine_check import TilauRoutineCheck
            self.trc = TilauRoutineCheck(self, self)
            self.trc.setWindowModality(Qt.WindowModality.NonModal)
            # Ensure the object is deleted from memory when closed manually
            self.trc.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)    
            QTimer.singleShot(100, self.trc.show)    
        
        # now build the collection of existing buttons in an array to be able to trigger them from the routine check
        self.artisan_buttons_collection: dict[str, QPushButton] = {
            "fcs": self.aw.buttonFCs,
            "fce": self.aw.buttonFCe,
            "scs": self.aw.buttonSCs,
            "sce": self.aw.buttonSCe,
            "reset": self.aw.buttonRESET,
            "charge": self.aw.buttonCHARGE,
            "drop": self.aw.buttonDROP,
            "dry": self.aw.buttonDRY,
            "cool": self.aw.buttonCOOL,
            "event": self.aw.buttonEVENT,
        }

        self.aw.messagelabel.setStyleSheet(PARENT_TILAUSTYLE)
        self.aw.setStyleSheet(PARENT_TILAUSTYLE)

        # ── Hook messages Artisan → ticker ────────────────────────────────────
        # Installé ici, retiré dans closeEvent.  Aucune modification de main.py.
        self._msg_hook = ArtisanMessageHook(
            self.aw,
            self.collapsible_events.sidebar.msg_ticker,
        )
        self._msg_hook.install()

        # Masquer messagelabel si TilauScope s'ouvre pendant une torréfaction déjà active
        self.aw.messagelabel.setVisible(False)

         # What's New splash — shown once per build
        self.alarm_fired_signal.connect(self.handle_alarm_trigger)
        # Live data from qmc, decoupled via signal (slot is exception-guarded).
        self.aw.qmc.tilauUpdateSignal.connect(self.update_ui_from_artisan)
        if message != "":
            QTimer.singleShot(500, lambda: self.showMessage(message))
        else:
            QTimer.singleShot(1200, lambda: maybe_show_whats_new(self, self))

    def check_daily_brew_status(self):
        alog_directory = "" # Pour stocker le chemin du répertoire ALog
        beancave_directory = "" # Nouvelle variable pour le répertoire de beancave.json
        settings = QSettings()
        alog_directory = settings.value('alogDirectory', "", str)
        beancave_directory = settings.value('beancaveDirectory', alog_directory, str)
        if beancave_directory != "" and alog_directory != "":
            from tilauscope.roast_timeline import BrewReadyNotification
            # ## TILAU ## BrewReadyNotification wants the alog metadata cache
            # (dict[str, AlogMetadata]), not the TilauScope widget. Reuse BeanCave's
            # already-indexed cache when available; empty dict → no toast, no crash.
            alog_files = {}
            bc = getattr(self.aw, 'beancaveWindow', None)
            if bc is not None and hasattr(bc, '_metadata_cache'):
                try:
                    alog_files = dict(bc._metadata_cache.records)
                except Exception:  # noqa: BLE001
                    alog_files = {}
            self._brew_notif = BrewReadyNotification(alog_directory, alog_files, self)

        _logd.info("tilauscope init finished")  

    @pyqtSlot()
    def focusOn(self):
        self.setFocus()

    ## TILAU ##
    # ─────────────────────────────────────────────────────────────────────────────
    # Catppuccin Mocha palette helpers — apply on TilauScope open, restore on close
    # ─────────────────────────────────────────────────────────────────────────────

    ## TILAU ##

    def _refresh_artisan_colors(self) -> None:
        """Push palette changes to Artisan LCD widgets and trigger canvas redraw."""
        aw = self.aw
        qmc = aw.qmc

        # Invalidate cached light_background_p so it recomputes from new palette
        aw.__dict__.pop('light_background_p', None)

        # Refresh LCD stylesheets — mirrors Artisan setLCDsBW pattern
        r = rgba_colorname2argb_colorname
        aw.lcd1.setStyleSheet(
            f"QLCDNumber {{ border-radius:4; color:{r(aw.lcdpaletteF['timer'])};"
            f" background-color:{r(aw.lcdpaletteB['timer'])};  }}"
        )
        for lcd, key in (
            (aw.lcd2, 'et'), (aw.lcd3, 'bt'),
            (aw.lcd4, 'deltaet'), (aw.lcd5, 'deltabt'), (aw.lcd6, 'sv'),
        ):
            lcd.setStyleSheet(
                f"QLCDNumber {{ border-radius:4; color:{r(aw.lcdpaletteF[key])};"
                f" background-color:{r(aw.lcdpaletteB[key])};  }}"
            )

        # Refresh curve labels
        aw.setLabelColor(aw.label2, qmc.palette['et'],      qmc.ETcurve)
        aw.setLabelColor(aw.label3, qmc.palette['bt'],      qmc.BTcurve)
        aw.setLabelColor(aw.label4, qmc.palette['deltaet'], qmc.DeltaETflag)
        aw.setLabelColor(aw.label5, qmc.palette['deltabt'], qmc.DeltaBTflag)

        # Messages label
        aw.setLabelColor(aw.messagelabel, qmc.palette.get('messages', '#CDD6F4'))

        # Canvas background + nav bar colors
        aw.updateCanvasColors(checkColors=False)

        # Full redraw — skipped during live sampling to avoid latency
        if not qmc.flagon:
            qmc.redraw(recomputeAllDeltas=False)
        else:
            qmc.canvas.draw_idle()

    def _apply_catppuccin_palette(self) -> None:
        """Snapshot Artisan palette, apply Catppuccin Mocha, trigger redraw."""
        aw = self.aw
        qmc = aw.qmc

        # --- snapshot current state ---
        self._snap_qmc_palette: dict[str, str]   = dict(qmc.palette)
        self._snap_lcd_fg:       dict[str, str]   = dict(aw.lcdpaletteF)
        self._snap_lcd_bg:       dict[str, str]   = dict(aw.lcdpaletteB)
        self._snap_bg_met:  str = qmc.backgroundmetcolor
        self._snap_bg_bt:   str = qmc.backgroundbtcolor
        self._snap_bg_det:  str = qmc.backgrounddeltaetcolor
        self._snap_bg_dbt:  str = qmc.backgrounddeltabtcolor

        # --- apply Catppuccin qmc.palette (only known keys, preserve unknowns) ---
        for k, v in _CATPPUCCIN_QMC.items():
            if k in qmc.palette:
                qmc.palette[k] = v

        # --- background profile curves inherit main curve tint ---
        qmc.backgroundmetcolor      = '#7F6147'  # dimmed Peach
        qmc.backgroundbtcolor       = '#4A6FA5'  # dimmed Blue
        qmc.backgrounddeltaetcolor  = '#8B7A32'  # dimmed Yellow
        qmc.backgrounddeltabtcolor  = '#4E7A54'  # dimmed Green

        # --- apply Catppuccin LCD colors ---
        for k, v in _CATPPUCCIN_LCD_FG.items():
            if k in aw.lcdpaletteF:
                aw.lcdpaletteF[k] = v
        for k, v in _CATPPUCCIN_LCD_BG.items():
            if k in aw.lcdpaletteB:
                aw.lcdpaletteB[k] = v

        self._palette_applied = True
        self._refresh_artisan_colors()

    def _restore_artisan_palette_dicts(self) -> None:
        """Restore palette dicts only — no redraw (deferred redraw handles it)."""
        if not getattr(self, '_palette_applied', False):
            return
        aw = self.aw
        qmc = aw.qmc
        qmc.palette.update(self._snap_qmc_palette)
        aw.lcdpaletteF.update(self._snap_lcd_fg)
        aw.lcdpaletteB.update(self._snap_lcd_bg)
        qmc.backgroundmetcolor     = self._snap_bg_met
        qmc.backgroundbtcolor      = self._snap_bg_bt
        qmc.backgrounddeltaetcolor = self._snap_bg_det
        qmc.backgrounddeltabtcolor = self._snap_bg_dbt
        self._palette_applied = False
        # Invalidate cached property so it recomputes after palette change
        aw.__dict__.pop('light_background_p', None)

    def _finish_palette_restore(self) -> None:
        """Push restored palette to LCD widgets — called inside _deferred_restore."""
        aw = self.aw
        qmc = aw.qmc
        r = rgba_colorname2argb_colorname
        aw.lcd1.setStyleSheet(
            f"QLCDNumber {{ border-radius:4; color:{r(aw.lcdpaletteF['timer'])};"
            f" background-color:{r(aw.lcdpaletteB['timer'])};  }}"
        )
        for lcd, key in (
            (aw.lcd2, 'et'), (aw.lcd3, 'bt'),
            (aw.lcd4, 'deltaet'), (aw.lcd5, 'deltabt'), (aw.lcd6, 'sv'),
        ):
            lcd.setStyleSheet(
                f"QLCDNumber {{ border-radius:4; color:{r(aw.lcdpaletteF[key])};"
                f" background-color:{r(aw.lcdpaletteB[key])};  }}"
            )
        aw.setLabelColor(aw.label2, qmc.palette['et'],      qmc.ETcurve)
        aw.setLabelColor(aw.label3, qmc.palette['bt'],      qmc.BTcurve)
        aw.setLabelColor(aw.label4, qmc.palette['deltaet'], qmc.DeltaETflag)
        aw.setLabelColor(aw.label5, qmc.palette['deltabt'], qmc.DeltaBTflag)
        aw.setLabelColor(aw.messagelabel, qmc.palette.get('messages', '#CDD6F4'))
        aw.updateCanvasColors(checkColors=False)

    def transformArtisan_ui(self, store =True):
        aw = self.aw
        aw.setWindowOpacity(0.01)
 
        # 1. Sauvegarde des flags de fenêtre
        self.aw_flags = self.aw.windowFlags
 
        # 3. Mapping des ressources : (Attribut cible, Liste de flags, Méthode de masquage)
        ui_elements = [
            ('show_controls',      'controlsflags',            aw.hideControls),
            ('show_lcds',          'readingslcdsflags',        aw.hideLCDs),
            ('show_minieventline', 'minieventsflags',          aw.hide_minieventline),
            ('show_extrabuttons',  'extraeventsbuttonsflags',  aw.hideExtraButtons),
            ('show_sliders',       'eventslidersflags',        aw.hideSliders),
        ]
 
        # 4. Application de la logique en boucle
        for attr, flag_name, hide_method in ui_elements:
            if store :
                flags = getattr(aw, flag_name)
                setattr(self, attr, flags)
            hide_method()

        ## TILAU ##
        # Apply Catppuccin Mocha palette to Artisan canvas on TilauScope open
        self._apply_catppuccin_palette()
 
    @override
    def closeEvent(self, a0: 'QCloseEvent|None') -> None:
        aw = self.aw
        qmc = aw.qmc

        ## TILAU ## block exit while sampling is active
        if qmc.flagon and a0 is not None:
            a0.ignore()
            return
        
        ## TILAU ## don't lose a slider change still inside its coalescing window
        self.flush_pending_slider_commits()

        # 1. Stopper les timers avant toute manipulation de widgets
        if hasattr(self, 'p_timer') and self.p_timer.isActive():
            self.p_timer.stop()

        # 2. Restaurer le stylesheet de main_widget AVANT de le reparenter
        #    (effacer celui qu'on a injecté pendant le transfert)
        if hasattr(self, 'artisan_graph'):
            self.artisan_graph.setStyleSheet("")

        # 3. Retirer explicitement main_widget du layout de TilauScope
        #    AVANT setCentralWidget, pour que Qt ne tente pas de le gérer deux fois
        if hasattr(self, 'artisan_graph'):
            # Le retirer proprement du content_layout de TilauScope
            content_layout = self.container.layout()
            if content_layout is not None:
                # Remove sidebar widgets first so their fixed widths don't
                # linger as size hints on artisan_graph after reparenting
                if hasattr(self, 'collapsible_events'):
                    content_layout.removeWidget(self.collapsible_events.grip)
                    content_layout.removeWidget(self.collapsible_events.sidebar)
                content_layout.removeWidget(self.artisan_graph)

        # 4. Restaurer le graph sous la barre de titre custom (jamais via
        #    setCentralWidget directement, sinon on perdrait le wrapper de
        #    main_window_style.py et donc la barre de titre)
        if hasattr(self, 'artisan_graph'):
            give_body(aw, self.artisan_graph)

        # 5. Restaurer l'opacité
        aw.setWindowOpacity(1.0)

        # 6. Kick Qt layout engine — deferred redraw ensures canvas has its final
        #    geometry before matplotlib tight_layout recalculates
        aw.main_widget.updateGeometry()
        aw.resize(aw.size())

        def _deferred_restore() -> None:
            try:
                canvas = aw.qmc.canvas
                sz = canvas.size()
                from PyQt6.QtGui import QResizeEvent
                canvas.resizeEvent(QResizeEvent(sz, sz))
                ## TILAU ## push restored palette to LCDs, then redraw with correct colors
                self._finish_palette_restore()
                qmc.redraw(recomputeAllDeltas=True)
                canvas.draw_idle()
                aw.update()
            except Exception as e:
                _log.error('deferred restore after TilauScope close: %s', e)

        QTimer.singleShot(150, _deferred_restore)

        # 9. Restaurer la visibilité des éléments UI Artisan
        idx = 2 if qmc.flagstart else (1 if qmc.flagon else 0)
        try:
            if self.show_controls[idx] == 1:     aw.showControls()
            if self.show_lcds[idx] == 1:         aw.showLCDs()
            if self.show_minieventline[idx] == 1: aw.show_minieventline()
            if self.show_extrabuttons[idx] == 1: aw.showExtraButtons()
            if self.show_sliders[idx] == 1:      aw.showSliders()
        except (IndexError, AttributeError) as e:
            _log.error('restore UI elements: %s', e)

        # 10. Fermer le panel flottant
        if hasattr(self, 'event_panel'):
            self.event_panel.close()
        # 10bis. Fermer le panel flottant extradevices
        if hasattr(self, 'extra_panel'):
            self.extra_panel.close()

        ## TILAU ##
        # Close roast assistant panel if open (floating or anchored)
        if hasattr(self, 'roast_assistant') and (
                self.roast_assistant.isVisible() or getattr(self, '_assistant_anchored', False)):
            if getattr(self, '_body_in_host', False):
                # Return the body to the shell before closing to avoid orphaning it.
                self._anchor_host.takeWidget()
                self.roast_assistant.give_body()
                self._body_in_host = False
            self.roast_assistant.close()

        # 11. Remove event filter from main window
        if self.aw:
            self.aw.removeEventFilter(self)

        # 12. Restore focus to main window
        aw.activateWindow()
        aw.raise_()

        self.aw.tilauscopeMain.setChecked(False)

        if hasattr(self,'_brew_notif'):
            if self._brew_notif:
                try:
                    self._brew_notif.request_stop()
                except RuntimeError:
                    # underlying C++ widget already deleted (auto-closed) — nothing to stop
                    pass
                self._brew_notif = None

        if _IS_WINDOWS:
            self.clearFocus()

        # Détacher le flux de données live qmc -> TilauScope
        try:
            self.aw.qmc.tilauUpdateSignal.disconnect(self.update_ui_from_artisan)
        except (TypeError, RuntimeError):
            pass

        # 13. Retirer le hook messages Artisan et restaurer messagelabel
        if hasattr(self, '_msg_hook'):
            self._msg_hook.remove()
        self.aw.messagelabel.setVisible(True)

        ## TILAU ##
        # Restore palette dicts before deferred redraw picks them up
        self._restore_artisan_palette_dicts()
        super().closeEvent(a0)

    def _update_phase_subtitle(self,phase:str)->str:
        # check if there are phases defined on artisan
        if self.aw.qmc.phasesbuttonflag:
            if phase == "DRY": 
                return QApplication.translate("tilauscope_window", "Auto")
            if phase == "MAI" : 
                return QApplication.translate("tilauscope_window", "Auto")
            if phase == "DEV" :
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[3]) + "°" + self.aw.qmc.mode
            return ""
        else:
            if phase == "DRY": 
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[1]) + "°" + self.aw.qmc.mode
            if phase == "MAI": 
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[2]) + "°" + self.aw.qmc.mode
            if phase == "DEV": 
                return QApplication.translate("tilauscope_window", "Aims ") + str(self.aw.qmc.phases[3]) + "°" + self.aw.qmc.mode            
            return ""

    def init_ui(self):
         
        self.init = True
        main_layout = QVBoxLayout(self)
        bg_color = self.theme["BG"]
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.setStyleSheet("""
                            QToolTip {
                                background-color: #2D2F3F; /* Gris foncé pour le fond */
                                color: white;              /* Texte blanc */
                                border: 1px solid #585B70; /* Bordure discrète */
                                padding: 5px;
                                border-radius: 3px;
                                font-size: 11px;
                            }
                        """)
        # Main Styled Frame
        self.container = QFrame()
        self.container.setStyleSheet(f"background-color: {bg_color}; border: 2px solid #2D2D35; border-radius: 8px;")

        # Horizontal Layout: Controls on Left, Graph on Right
        content_layout = QHBoxLayout(self.container)
        # Increase margins slightly so internal widgets don't "touch" the border
        content_layout.setContentsMargins(10,10,10,10) 
        content_layout.setSpacing(10) 

        # --- LEFT PANE: ROASTER CONTROLS ---
        left_widget = QWidget()
        left_pane = QVBoxLayout(left_widget)
        left_pane.setContentsMargins(15, 15, 15, 15)
        left_pane.setSpacing(15) # Tightened spacing to ensure full display
        left_widget.setFixedWidth(440)

        # values for counters
        self.bt_label =f"0.0"
        self.et_label =f"0.0"
        self.deltabt_label=f"0"

        self.time_charge = 0.0
        self.time_dryend = 0.0
        self.time_fcs = 0.0

        self.prev_pidtext:str = ""

        # 1. HEADER (Timer + Préchauffage)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.setContentsMargins(0, 0, 5, 0) # Add a small right margin to protect the border
        # Group controls and status on the left
        left_header_group = QHBoxLayout()

        # Create and add the Artisan Menu Button
        self.btn_main_menu = QPushButton()
        self.btn_main_menu.setFixedSize(26, 30)
        self.btn_main_menu.setIconSize(BTN_ICON_SIZE)
        self.btn_main_menu.setStyleSheet(QSS_MENU)
        apply_icon(self.btn_main_menu, SVG_MENU, COL_MENU)
        self.btn_main_menu.clicked.connect(self.open_main_menu)

        self.btn_power = QPushButton()
        self.btn_power.setFixedSize(32, 30)
        self.btn_power.setCheckable(True)
        self.btn_power.setIconSize(BTN_ICON_SIZE)
        self.btn_power.setToolTip(QApplication.translate('Tooltip', 'Start monitoring'))
        self.btn_power.setStyleSheet(QSS_POWER)
        apply_icon(self.btn_power, SVG_POWER, COL_POWER_IDLE)
        self.update_button_style(self.btn_power, True)
        self.btn_power.clicked.connect(self.toggle_power)
        
        self.btn_start_stop = QPushButton()
        self.btn_start_stop.setFixedSize(32, 30)
        self.btn_start_stop.setCheckable(False)
        self.btn_start_stop.setIconSize(BTN_ICON_SIZE)
        self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Start recording'))
        self.btn_start_stop.clicked.connect(self.toggle_start_stop)
        self.btn_start_stop.setStyleSheet(QSS_START_STOP)
        apply_icon(self.btn_start_stop, SVG_PLAY, COL_START_IDLE)
        self.update_button_style(self.btn_start_stop, False)

        self.btn_reset = QPushButton()
        self.btn_reset.setFixedSize(32, 30)
        self.btn_reset.setCheckable(False)
        self.btn_reset.setIconSize(BTN_ICON_SIZE)
        self.btn_reset.setToolTip(QApplication.translate('Tooltip', 'Reset'))
        self.btn_reset.clicked.connect(self.handle_reset)
        self.btn_reset.setStyleSheet(QSS_RESET)
        apply_icon(self.btn_reset, SVG_RESET, COL_RESET_IDLE)
        self.update_button_style(self.btn_reset, True)

        self.btn_beancave = QPushButton()
        self.btn_beancave.setFixedSize(32, 30)
        self.btn_beancave.setCheckable(True)
        self.btn_beancave.setIconSize(BTN_ICON_SIZE)
        self.btn_beancave.setToolTip(QApplication.translate('tilauscope_window', 'Access to Bean Cave'))
        self.btn_beancave.clicked.connect(self.toggle_beancave)
        self.btn_beancave.setStyleSheet(QSS_BEANCAVE)
        apply_icon(self.btn_beancave, SVG_BEANCAVE, COL_BEANCAVE_IDLE)
        self.btn_beancave.setChecked(False)
        self.update_button_style(self.btn_beancave, True)

        self.btn_assistant = QPushButton()
        self.btn_assistant.setFixedSize(32, 30)
        self.btn_assistant.setCheckable(False)
        self.btn_assistant.setIconSize(BTN_ICON_SIZE)
        self.btn_assistant.setToolTip(QApplication.translate('tilauscope_window', 'Engage Roast Assistant'))
        self.btn_assistant.clicked.connect(self.toggle_roast_assistant)
        self.btn_assistant.setStyleSheet(QSS_ASSISTANT)
        apply_icon(self.btn_assistant, SVG_ASSISTANT, COL_ASSISTANT_IDLE)
        self.update_button_style(self.btn_assistant, False)

        # ── Float ↔ anchor toggle for the roast assistant ## TILAU ## ─────────
        self.btn_dock = QPushButton()
        self.btn_dock.setFixedSize(26, 30)
        self.btn_dock.setCheckable(False)
        self.btn_dock.setToolTip(QApplication.translate(
            'tilauscope_window',
            'Anchor the assistant in place of the main panel (toggle floating)'))
        self.btn_dock.setStyleSheet(QSS_DOCK)
        apply_icon(self.btn_dock, SVG_DOCK, COL_DOCK_IDLE)
        self.btn_dock.clicked.connect(self.toggle_assistant_anchor)
        self.update_button_style(self.btn_dock, False)

        self.swap_button = QPushButton()
        self.swap_button.setFixedSize(26, 30)
        self.swap_button.setCheckable(False)
        self.swap_button.setIconSize(BTN_ICON_SIZE)
        self.swap_button.clicked.connect(lambda: self.toggle_panels(left_widget, content_layout, True))
        self.swap_button.setStyleSheet(QSS_SWAP)
        apply_icon(self.swap_button, SVG_SWAP, COL_SWAP_IDLE)
        self.update_button_style(self.swap_button, True)

        # ── Assemblage du header ─────────────────────────────────────────────
        left_header_group.addWidget(self.btn_main_menu)
        left_header_group.addWidget(self.btn_power)
        left_header_group.addWidget(self.btn_start_stop)
        left_header_group.addWidget(self.btn_reset)
        left_header_group.addWidget(self.btn_beancave)
        # Assistant engage + anchor buttons no longer live in the main button
        # bar. In Guided the assistant is anchored by default and floated via
        # the GREEN BEAN header control; in Expert there is no assistant.
        # Objects kept (hidden) so existing style/state references stay valid.
        self.btn_assistant.hide()
        self.btn_dock.hide()
        left_header_group.addWidget(self.swap_button)
        left_header_group.setSpacing(8)
        header.addLayout(left_header_group)

        # ── Operator level selector (single cycling button) ## TILAU ## ──────
        # One ~32px button in the icon row. Letter = level, colour = level.
        # One click cycles G→S→E→G. No popup (real-time friendly).
        _lvl_sep = QFrame()
        _lvl_sep.setFrameShape(QFrame.Shape.VLine)
        _lvl_sep.setFixedHeight(22)
        _lvl_sep.setStyleSheet("color: #313244; background: #313244; border: none; max-width: 1px;")
        header.addSpacing(4)
        header.addWidget(_lvl_sep)
        header.addSpacing(4)

        self.btn_level = QPushButton()
        self.btn_level.setFixedSize(32, 30)
        self.btn_level.clicked.connect(self._cycle_operator_level)
        header.addWidget(self.btn_level)

        # Drag handle — zone de déplacement explicite entre boutons et timer
        # Cursor SizeAllCursor signale visuellement la zone draggable
        self.drag_handle = QLabel("⠿")  # braille pattern = grab icon léger
        self.drag_handle.setFixedHeight(32)
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drag_handle.setStyleSheet("""
            QLabel { color: #45475A; font-size: 18px; border: none;
                     background: transparent; padding: 0 8px; }
            QToolTip { background-color: #2D2F3F; color: white;
                       border: 1px solid #585B70; padding: 5px;
                       border-radius: 3px; font-size: 11px; }
        """)
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setToolTip(QApplication.translate("tilauscope_window", "Drag to move"))
        # Installer les événements souris sur le handle
        self.drag_handle.mousePressEvent   = self._handle_drag_press
        self.drag_handle.mouseMoveEvent    = self._handle_drag_move
        self.drag_handle.mouseReleaseEvent = self._handle_drag_release
        header.addWidget(self.drag_handle)

        header.addStretch(1) # Pushes the timer to the far right
        header.setSpacing(6)

        # Adjust Timer Font Size
        self.timer_lbl = ClickableLabel("00:00")
        # Reduced from 80px to 68px to ensure it fits the 400px pane width
        # Use the bundled JetBrains Mono (monospaced — every digit same width)
        # so the timer never reflows the header as the value changes.
        _mono = _mono_font_family()
        self.timer_lbl.setStyleSheet(f"font-size: 28px; font-weight: 700; color: #313244; font-family: '{_mono}', 'Menlo', monospace; border: none; background: transparent;")
        self.timer_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.timer_lbl.clicked.connect(self.timer_clicked)
        # Belt-and-suspenders: pin the box to the widest reading so the timer
        # zone never resizes regardless of the resolved font.
        _timer_font = QFont(_mono)
        _timer_font.setPixelSize(28)
        _timer_font.setWeight(QFont.Weight.Bold)
        _fm = QFontMetrics(_timer_font)
        self.timer_lbl.setFixedWidth(_fm.horizontalAdvance("-88:88") + 6)

        header.addWidget(self.timer_lbl)
        left_pane.addLayout(header)

        # Status label — affiche l'état de la session (monitoring, recording, emergency)
        # Status label — TickerLabel : défile si le texte dépasse la largeur
        self.status_lbl = TickerLabel(height=18, color="#A6E3A1", font_size=11, font_weight=700)
        left_pane.addWidget(self.status_lbl, 0)

        ## TILAU ## Automation banner — red text on amber, shown only while the
        ## roast is driven by Artisan automations (PID from CHARGE, or any
        ## background playback mode). Hidden the rest of the time.
        self.automation_lbl = QLabel("")
        self.automation_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.automation_lbl.setWordWrap(True)
        self.automation_lbl.setStyleSheet(
            "color: #B00710; background: #FAB387; border-radius: 6px;"
            " padding: 2px 8px; font-size: 11px; font-weight: 900;"
            " font-family: 'JetBrains Mono'; border: 1px solid #F38BA8;"
        )
        self.automation_lbl.hide()
        self._automation_prev = None   # cache to avoid redundant setText/show
        left_pane.addWidget(self.automation_lbl, 0)

        # 2. METRICS
        self.et_val_label = QLabel("0.0")
        self.bt_val_label = QLabel("0.0")
        self.ror_val_label = QLabel("0.0")
        
        self.lcds = TilauscopePanel(self.artisan_conf)
        left_pane.addWidget(self.lcds) 

        # ── Anchorable main-panel container ## TILAU ## ──────────────────────
        # Everything below the counters lives here, so the whole block can be
        # swapped for the anchored roast-assistant body via a QStackedWidget.
        self._main_controls = QWidget()
        self._main_controls.setStyleSheet("background: transparent; border: none;")
        mc_lay = QVBoxLayout(self._main_controls)
        mc_lay.setContentsMargins(0, 0, 0, 0)
        mc_lay.setSpacing(15)

        # 3. PHASES & OVERLAY MESSAGE
        self.phase_container = QFrame()
        self.phase_container.setMinimumHeight(130) # Force une zone de respiration
        self.phase_container.setStyleSheet(f"background: {self.theme["BG"]}; border-radius: 10px; border: 1px solid #313244; margin-top: 10px;")
        self.phase_stack = QGridLayout(self.phase_container)
        
        self.msg_lbl = QLabel("") # Message Drop/Cool
        self.msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ## TILAU ## long status lines used to run past both edges of the window:
        ## the grid item was centred at its full single-line size hint. Let it take
        ## the cell width (see below) and wrap inside the box instead.
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setStyleSheet("color: #94E2D5; font-size: 16px; font-weight: 800; font-family: 'JetBrains Mono'; border: none")
        self.msg_lbl.hide()
        
        self.phase_box = QHBoxLayout()
        self.phase_box.setContentsMargins(0, 0, 0, 0)
        self.phase_box.setSpacing(2) # Small gap between phase blocks

        self.phases = {
            "DRY": PhaseWidget("DRY", QApplication.translate("tilauscope_window","Drying Phase").upper(), "#89B4FA", self.theme, self._update_phase_subtitle("DRY")), 
            "MAI": PhaseWidget("MAI", QApplication.translate("tilauscope_window","Maillard Phase").upper(), "#F9E2AF", self.theme, self._update_phase_subtitle("MAI")), 
            "DEV": PhaseWidget("DEV", QApplication.translate("tilauscope_window","Finishing Phase").upper(), "#F38BA8", self.theme, self._update_phase_subtitle("DEV"))}
        _PHASE_IDX = {"DRY": 1, "MAI": 2, "DEV": 3}
        for key, p in self.phases.items():
            self.phase_box.addWidget(p)
            p.setFocusPolicy(Qt.FocusPolicy.WheelFocus)  # macOS trackpad delivery
            p.installEventFilter(self)
            p._phase_key = key
            p._phase_idx = _PHASE_IDX[key]

        self.phase_stack.addLayout(self.phase_box, 0, 0)
        self.phase_stack.addWidget(self.msg_lbl, 0, 0)
        ## TILAU ## no item alignment here: an aligned grid item keeps its size hint,
        ## which for a one-line label is the full text width — that is what made long
        ## messages overflow the panel. Filling the cell lets setWordWrap do its job;
        ## the text stays centred through the label's own alignment.
        mc_lay.addWidget(self.phase_container,1)   ## TILAU ##

        # 4. PILOTAGE MACHINE
        mc_lay.addSpacing(10)   ## TILAU ##
        self.sld_list: list[TilauscopeSlider] = []

        # ── Slider configurations (unchanged from your original loop) ──────────
        slider_defs = [
            (self.artisan_conf.slider_names[0], self.aw.qmc.EvalueColor[0],
             self.aw.eventslidermin[0], self.aw.eventslidermax[0], "%",
             self.aw.eventSliderStepSize(0)),
            (self.artisan_conf.slider_names[1], self.aw.qmc.EvalueColor[1],
             self.aw.eventslidermin[1], self.aw.eventslidermax[1], "%",
             self.aw.eventSliderStepSize(1)),
            (self.artisan_conf.slider_names[2], self.aw.qmc.EvalueColor[2],
             self.aw.eventslidermin[2], self.aw.eventslidermax[2], "%",
             self.aw.eventSliderStepSize(2)),
            (self.artisan_conf.slider_names[3], self.aw.qmc.EvalueColor[3],
             self.aw.eventslidermin[3], self.aw.eventslidermax[3], "%",
             self.aw.eventSliderStepSize(3)),
            (QApplication.translate("Tab", "SV"), self.theme["SV"],
             0, 250 if self.artisan_conf.mode == 'C' else fromCtoFstrict(250),
             f"°{self.artisan_conf.mode}", 1),
        ]

        # Initial slider values (Artisan sources)
        _initial_vals = [
            self.aw.slider1.value(),
            self.aw.slider2.value(),
            self.aw.slider3.value(),
            self.aw.slider4.value(),
            self.aw.sliderSV.value(),
        ]

        # ── Slider rows container (classic view, sliders 0-3 only) ───────────
        
        self.slider_rows_widget = QWidget()
        self.slider_rows_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider_rows_widget.setObjectName("SliderRows") # ID Unique
        if _IS_MACOS:
            self.slider_rows_widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.slider_rows_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.slider_rows_widget.setStyleSheet("""
                #SliderRows { 
                    border: none; 
                    background: transparent; 
                }
                QWidget { border: none; } 
            """)
        slider_rows_layout = QVBoxLayout(self.slider_rows_widget)
        slider_rows_layout.setContentsMargins(0, 0, 0, 0)
        slider_rows_layout.setSpacing(4)

        _card_configs = []   # accumulate tuples for BigControlsRow
        self._slider_row_widgets: list[QWidget] = []  ## TILAU ## per-slider row widgets (idx 0-3), for visibility mirror

        for i, (name, color, min_val, max_val, unit, step) in enumerate(slider_defs):
            row = QHBoxLayout()
            row.setContentsMargins(*_SLIDER_ROW_MARGINS)   ## TILAU ## same inset for all 5 rows
            lbl = QLabel(name)
            lbl.setFixedWidth(55)
            lbl.setStyleSheet(
                "font-size: 11px; font-weight: 800; color: #585B70; border: none;"
            )
            sld = TilauscopeSlider(accent_color=color)
            self.sld_list.append(sld)
            sld.setRange(int(min_val), int(max_val))
            sld.setSingleStep(step)
            sld.setValue(_initial_vals[i])

            val_pct = ClickableValue(
                _initial_vals[i], color, sld, unit, i,
                self.handle_ui_input_released, int(min_val), int(max_val), int(step)
            )
            sld.valueChanged.connect(lambda v, l=val_pct, u=unit: l.setText(f"{v}{u}"))
            sld.valueChanged.connect(lambda v, n=i: self.handle_ui_input_move(n, v))
            ## TILAU ## drag release: no burst to coalesce → commit without delay
            sld.sliderReleased.connect(lambda n=i: self.handle_ui_input_released(n, immediate=True))

            def _sync_artisan(v, n=i):
                if getattr(self.aw, 'tilauscope_main', None) is not None:
                    try:
                        self.aw.tilauscope_main.sld_list[n].setValue(v)
                    except (IndexError, AttributeError):
                        pass
            sld.valueChanged.connect(_sync_artisan)

            btn_minus = QPushButton("-")
            btn_minus.setFixedSize(24, 24)
            btn_minus.setStyleSheet(self._get_stepper_style(color))
            btn_minus.clicked.connect(lambda _, s=sld, n=i: [
                s.setValue(max(s.minimum(), s.value() - s.singleStep())),
                s.valueChanged.emit(s.value()),
                self.handle_ui_input_released(n),
            ])

            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(24, 24)
            btn_plus.setStyleSheet(self._get_stepper_style(color))
            btn_plus.clicked.connect(lambda _, s=sld, n=i: [
                s.setValue(min(s.maximum(), s.value() + s.singleStep())),
                s.valueChanged.emit(s.value()),
                self.handle_ui_input_released(n),
            ])

            row.addWidget(lbl)
            row.addWidget(sld)
            row.addWidget(btn_minus)
            row.addWidget(val_pct)
            row.addWidget(btn_plus)

            if i < 4:
                # Classic slider row → goes into the toggleable container.
                # Wrapped in a QWidget so each row can be shown/hidden on its own
                # to mirror Artisan's eventslidervisibilities. ## TILAU ##
                row_w = QWidget()
                row_w.setStyleSheet("border: none; background: transparent;")
                row_w.setLayout(row)
                # Fixed height so a hidden→shown cycle can't let the rows stretch
                # to fill the (taller) locked control zone. ## TILAU ##
                row_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                self._slider_row_widgets.append(row_w)
                slider_rows_layout.addWidget(row_w)
                # Also register for the card view
                _card_configs.append((
                    name, color, sld, i, self.handle_ui_input_released,
                    unit, int(min_val), int(max_val), step,
                ))
            else:
                # SV slider — always visible, not part of the toggle
                self._sv_row_widget = QWidget()
                sv_inner = QVBoxLayout(self._sv_row_widget)
                ## TILAU ## Right inset = ToggleBar width + ctrl_zone spacing: the 4 rows
                ## above sit left of the toggle bar, the SV row spans the full panel, so
                ## without it the SV steppers hang past the column they should line up with.
                sv_inner.setContentsMargins(0, 0, _CTRL_TOGGLE_RESERVE_PX, 0)
                sv_inner.setSpacing(0)
                self._sv_row_widget.setObjectName("SVRow")
                self._sv_row_widget.setStyleSheet("#SVRow { border: none; background: transparent; }")
                ## TILAU ## Same wrapper as the rows above: the row carries the explicit
                ## _SLIDER_ROW_MARGINS either way, but keeping the construction identical
                ## means the SV row can never drift out of line with them again.
                sv_row_w = QWidget()
                sv_row_w.setStyleSheet("border: none; background: transparent;")
                sv_row_w.setLayout(row)
                sv_inner.addWidget(sv_row_w)
                ## TILAU ## kept for _apply_sv_lock (read-only while TilauPID preheats)
                self._sv_widgets = (sld, btn_minus, btn_plus, val_pct)

        # Trailing stretch: any spare height in the (card-sized) locked control
        # zone collects at the bottom, keeping the classic rows packed at top
        # instead of spreading out. ## TILAU ##
        slider_rows_layout.addStretch(1)

        if _IS_MACOS: # macOS
            # Force la suppression des bordures de focus natives Aqua
            self.slider_rows_widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            self._sv_row_widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        else: # Windows
            # Supprime le rectangle de focus pointillé typique de Windows
            self.slider_rows_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._sv_row_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)


        # ── Card view (alternative to slider rows) ────────────────────────────
        self.big_controls_row = BigControlsRow(_card_configs, self)
        self.big_controls_row.hide()   # hidden by default

        # Mirror Artisan's per-slider visibilities onto both views ## TILAU ##
        self._apply_slider_visibility_mirror()

        # ── Toggle bar (always visible on the right of the control zone) ──────
        self._toggle_bar = ToggleBar(self)
        self._toggle_bar.toggled.connect(self._toggle_control_view)
        self._show_cards: bool = False   # persisted state flag

        # ── Assemble the control zone: [stacked slider/card area | toggle bar]
        ctrl_zone = QHBoxLayout()
        ctrl_zone.setContentsMargins(0, 0, 0, 0)
        ctrl_zone.setSpacing(6)

        # A plain QWidget hosts both views; only one is visible at a time
        self._ctrl_stack = QWidget()
        self._ctrl_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._ctrl_stack.setStyleSheet("border: none; background: transparent;")
        stack_layout = QVBoxLayout(self._ctrl_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)
        stack_layout.addWidget(self.slider_rows_widget)
        stack_layout.addWidget(self.big_controls_row)
        ctrl_zone.addWidget(self._ctrl_stack, 1)
        ctrl_zone.addWidget(self._toggle_bar)

        mc_lay.addLayout(ctrl_zone)   ## TILAU ##
        # Freeze the control-zone height to the taller of the two views so the
        # sliders ↔ cards toggle never changes the window size. The phase
        # container has stretch=1 and would otherwise absorb the slack, growing
        # the window when switching back to sliders. ## TILAU ##
        QTimer.singleShot(0, self._lock_control_zone_height)

        # SV slider row — beneath the toggle zone, always shown
        mc_lay.addWidget(self._sv_row_widget)   ## TILAU ##

        # 5. ÉVÉNEMENTS
        mc_lay.addSpacing(15)   ## TILAU ##
        grid = QGridLayout()
        self.event_buttons:dict[str,QPushButton] = {}  # Dictionary to store button references
        self.events = [
            (QApplication.translate("Button","CHARGE"), "#A6E3A1"), 
            (QApplication.translate("Button","DRY END"), "#89B4FA"), 
            (QApplication.translate("Button","FC START"), "#FAB387"), 
            (QApplication.translate("Button","FC END"), "#F38BA8"), 
            (QApplication.translate("Button","SC START"), "#F38BA8"), 
            (QApplication.translate("Button","SC END"), "#F38BA8"), 
            (QApplication.translate("Button","DROP"), "#F38BA8"),
            (QApplication.translate("Button","COOL END"), "#94E2D5")]
        for i, (n, c) in enumerate(self.events):
            btn = QPushButton(n)
            btn.setFixedHeight(45)
            btn.setEnabled(False)
            if i == 0: btn.clicked.connect(lambda: self.aw.qmc.markChargeSignal.emit(False))
            elif i == 1: btn.clicked.connect(lambda: self.aw.qmc.markDRYSignal.emit(False))
            elif i == 2: btn.clicked.connect(lambda: self.aw.qmc.markFCsSignal.emit(False))
            elif i == 3: btn.clicked.connect(lambda: self.aw.qmc.markFCeSignal.emit(False))
            elif i == 4: btn.clicked.connect(lambda: self.aw.qmc.markSCsSignal.emit(False))
            elif i == 5: btn.clicked.connect(lambda: self.aw.qmc.markSCeSignal.emit(False))
            elif i == 6: btn.clicked.connect(lambda: self.handle_drop())
            elif i == 7: btn.clicked.connect(lambda: self.handle_cool())
            self.event_buttons[n] = btn
            self.set_button_style(i, True)
            grid.addWidget(btn, i // 4, i % 4)
        mc_lay.addLayout(grid)   ## TILAU ##

        # ── Panel stack: page 0 = manual controls, page 1 = anchored assistant ## TILAU ##
        # The hidden page is not painted, so anchoring adds no per-cycle CPU cost.
        self._panel_stack = QStackedWidget()
        self._panel_stack.addWidget(self._main_controls)            # index 0
        self._anchor_host = QScrollArea()
        self._anchor_host.setWidgetResizable(True)
        self._anchor_host.setFrameShape(QFrame.Shape.NoFrame)
        self._anchor_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  ## TILAU ##
        self._anchor_host.setStyleSheet("background: transparent; border: none;")
        self._panel_stack.addWidget(self._anchor_host)              # index 1
        self._panel_stack.setCurrentIndex(0)
        left_pane.addWidget(self._panel_stack, 1)

        # --- RIGHT PANE: ARTISAN GRAPH ---
        # centralWidget() is the frameless-style wrapper (custom title bar + graph,
        # see main_window_style.py), not the graph itself — take_body() detaches
        # just the graph so we don't embed our own title bar in the panel.
        self.artisan_graph = take_body(self.aw)
        self.old_parent = self.artisan_graph.parent()
        self.artisan_graph.setParent(self.container)
        self.artisan_graph.setStyleSheet("background: transparent; border-radius: 15px;")
        # Graph takes all remaining space (stretch=1)
    
        main_layout.addWidget(self.container)
        
        # --- add the sidebar ---
        self.collapsible_events = CollapsibleLiveEvents(self.aw, self)

        self.toggle_panels(left_widget, content_layout, False) # no swap just display current parameter value

        #6 buttons      
        # Initialize the managed buttons
        self.btn_manager = ButtonManager.from_artisan_settings(self.artisan_conf, self.artisan_conf.mode)
        
        # Initialize floating panel and slider values
        self.event_panel = EventPanel(self.btn_manager, self.theme, self)
        self.event_panel.update_panel_height() # Ensure correct height based on content
        self.event_panel.hide()
        self.event_panel.event_fired.connect(self.handle_event_fired)

        # extracoutner panel
        self.extra_panel = ExtraCountersPanel(self.artisan_conf, self.theme, self)
        self;self.extra_panel.reset_counters() # Initialize counters 
        self.extra_panel.hide() # Caché par défaut

        # Position it horizontally centered relative to main window
        QTimer.singleShot(100, self.align_panels)
        QTimer.singleShot(100, self.align_extra_panel)

        # now set the sliders value
        self.sld_list[0].setValue(self.aw.slider1.value())
        self.sld_list[1].setValue(self.aw.slider2.value())
        self.sld_list[2].setValue(self.aw.slider3.value())
        self.sld_list[3].setValue(self.aw.slider4.value())
        self.sld_list[4].setValue(self.aw.sliderSV.value())
        # Pre-compute Artisan slider refs — stable after build, avoids per-cycle list allocation
        self._artisan_sliders = (self.aw.slider1, self.aw.slider2, self.aw.slider3, self.aw.slider4)
        self.update_status_text() # first initialization of status
        if self.aw:
            self.aw.installEventFilter(self)
        from tilauscope.roast_asssistant import RoastAssistantPanel
        from tilauscope.roast_bridge import RoastDataBridge
        self.roast_assistant = RoastAssistantPanel(self.aw, self)
        self.roast_bridge    = RoastDataBridge(self.aw, parent=self)
        self.roast_assistant.connect_bridge(self.roast_bridge)
        self.roast_assistant.closed.connect(self._on_assistant_closed)   ## TILAU ##
        self.roast_assistant.anchor_requested.connect(self.toggle_assistant_anchor)   ## TILAU ##
        self.roast_assistant.hide()

        # ── Assistant placement state ## TILAU ## ────────────────────────────
        self._assistant_open: bool   = False
        self._body_in_host: bool     = False
        self._assistant_anchored: bool = QSettings().value(
            "tilauscope/assistant_anchored", False, type=bool)
        self.btn_dock.setEnabled(False)
        self.roast_assistant.populate_bean_list()   ## TILAU ## always identify bean on open
        if self._assistant_anchored:
            # Restoring the anchored mode implies re-opening the assistant.
            self._assistant_open = True
            self.update_button_style(self.btn_assistant, True, False, False, True)
        self._place_assistant()
        if self._assistant_anchored:
            # Re-evaluate once geometry has settled to avoid a transient scrollbar.
            QTimer.singleShot(150, self._place_assistant)   ## TILAU ##

        # ── Operator level init ## TILAU ## ──────────────────────────────────
        # Two levels only: Guided (default) and Expert. Legacy "standard" and
        # new installs both fall back to Guided.
        _saved_level = QSettings().value("tilauscope/operator_level")
        if _saved_level not in ("guided", "expert"):
            _saved_level = "guided"
            QSettings().setValue("tilauscope/operator_level", _saved_level)
        self._operator_level: str = _saved_level
        self._apply_operator_level(_saved_level, from_init=True)

        self.init = False

    @override
    def eventFilter(self, obj, event):
        # ── Wheel sur PhaseWidget → ajuster la consigne de phase ─────────
        if (event.type() == QEvent.Type.Wheel
                and hasattr(obj, '_phase_key')):
            self._phase_wheel(obj, event)
            return True   # événement consommé — ne remonte pas
        if obj == self.aw and event.type() == QEvent.Type.WindowActivate:
            # Vérifie qu'aucune fenêtre modale/dialogue fils n'est active
            # (QFileDialog, QMessageBox, etc. ferment et rendent focus à aw)
            active = QApplication.activeWindow()
            if active is None or active is self.aw:
                # Ne pas interférer si Beancave est visible — il a la priorité
                beancave_visible = False
                try:
                    from tilauscope.beancave import BeancaveDlg
                    beancave_visible = any(
                        isinstance(w, BeancaveDlg) and w.isVisible()
                        for w in QApplication.topLevelWidgets()
                    )
                except ImportError:
                    pass
                if not beancave_visible:
                    QTimer.singleShot(0, self._safe_raise)
        return super().eventFilter(obj, event)

    def _safe_raise(self):
        """Ramène TilauScope au premier plan seulement si aucun dialogue fils n'est ouvert
        et si Beancave n'est pas visible (il a la priorité de premier plan)."""
        # Ne pas interférer pendant un drag — évite boucle WindowActivate ↔ raise_()
        if getattr(self, "_dragging", False):
            return
        active = QApplication.activeWindow()
        if (active is not None and active is not self.aw) or active is self:
            return
        # Vérifie qu'aucun QDialog fils n'est visible — remonte toute la chaîne de parenté
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                p = widget.parent()
                while p is not None:
                    if p in (self, self.aw):
                        return
                    p = p.parent()
        # Cède la priorité à Beancave s'il est ouvert et visible
        try:
            from tilauscope.beancave import BeancaveDlg
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, BeancaveDlg) and widget.isVisible():
                    return
        except ImportError:
            pass
        self.raise_()
        self.activateWindow()

    def _lock_control_zone_height(self) -> None:
        """Freeze the control zone to the taller of the slider/card views so the
        sliders ↔ cards toggle is size-neutral and never grows the window.
        Run once, deferred, after the first layout pass. ## TILAU ##"""
        try:
            h = max(self.slider_rows_widget.sizeHint().height(),
                    self.big_controls_row.sizeHint().height())
            if h > 0:
                self._ctrl_stack.setFixedHeight(h)
        except (AttributeError, RuntimeError):
            pass

    def _toggle_control_view(self):
        """
        Switch between classic horizontal sliders (0-3) and BigControlCard view.
        The SV slider (index 4) and the ToggleBar itself are unaffected.
        State is held in self._show_cards (bool).
        """
        self._show_cards = not self._show_cards
        self.slider_rows_widget.setVisible(not self._show_cards)
        self.big_controls_row.setVisible(self._show_cards)

        # Animate the toggle bar colour to give a mode hint
        col = "#89B4FA" if self._show_cards else "#111118"   # blue accent when cards active
        self._toggle_bar.setStyleSheet(f"""
            QFrame {{
                background: {col};
                border-radius: 5px;
                border: 1px solid #2A2A3C;
            }}
        """)

    def _apply_slider_visibility_mirror(self) -> None:
        """Mirror Artisan's per-slider visibilities (eventslidervisibilities,
        idx 0-3) onto both the classic slider rows and the card view: a slider
        disabled on the Artisan side is hidden here too. Called at build time
        and re-callable from the config dialog when the roaster changes. The SV
        slider (idx 4) is never touched. ## TILAU ##"""
        try:
            vis = self.aw.eventslidervisibilities
            cards = getattr(self.big_controls_row, "cards", [])
            for i, row_w in enumerate(getattr(self, "_slider_row_widgets", [])):
                show = bool(vis[i]) if i < len(vis) else True
                row_w.setVisible(show)
                if i < len(cards):
                    cards[i].setVisible(show)
        except Exception:
            _logd.exception("TilauScope: _apply_slider_visibility_mirror failed")

    @override
    def keyPressEvent(self, a0: 'QKeyEvent|None') -> None:
        if a0 is None:
            return
        key = a0.key()
        modifiers = a0.modifiers()
        shift_modifier = modifiers == Qt.KeyboardModifier.ShiftModifier # SHIFT
        no_modifier = modifiers == Qt.KeyboardModifier.NoModifier
        
        ## TILAU ## PID L/R shortcuts removed — PID piloting is delegated to
        ## Artisan's own key cascade (handled by self.aw.keyPressEvent below).
        if key == Qt.Key.Key_B and shift_modifier:
            # call Beancave
            self.btn_beancave.setChecked(not self.btn_beancave.isChecked()) # fix 2026/04/25
            self.toggle_beancave()
        elif key == Qt.Key.Key_X and no_modifier:
            # Call the extra counters logic
            if len(self.extra_panel.active_counters) > 0:
                self.extra_panel.toggle_visibility()
            return
        elif key == Qt.Key.Key_B and no_modifier:
            # Call the extra counters logic
            self.event_panel.toggle_visibility()
            return
        elif key == Qt.Key.Key_A and shift_modifier:
            self.toggle_roast_assistant()   ## TILAU ## placement handled inside
            return
        ## TILAU ## F1-F8 milestone shortcuts gated on current_event (last marked
        ## event code: None=nothing, 0=CHARGE, 1=DRY END, 2=FC START, 3=FC END,
        ## 4=SC START, 5=SC END, 6=DROP, 7=COOL END). The inner timeindex checks
        ## enforce the actual ordering; the outer guard just blocks gross misfires.
        elif key==Qt.Key.Key_F1 and no_modifier and (self.current_event is None or self.current_event == 0): # charge can be marked at any time before dry end is marked, but not after
            if self.is_roasting:
                self.aw.qmc.markChargeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F2 and no_modifier and self.current_event in [0,1]: # dry end can be marked any time after charge is marked, but not after 1C start is marked
            if self.is_roasting and self.aw.qmc.timeindex[0] > -1:
                self.aw.qmc.markDRYSignal.emit(False)
                return
        elif key==Qt.Key.Key_F3 and no_modifier and self.current_event in [1,2]: # 1C start can be marked any time after dry end is marked, but not after 1C end is marked
            if self.is_roasting and self.aw.qmc.timeindex[1] > -1:
                self.aw.qmc.markFCsSignal.emit(False)
                return
        elif key==Qt.Key.Key_F4 and no_modifier and self.current_event in [2,3]: # 1C end can be marked any time after 1C start is marked, but not after 2C start is marked
            if self.is_roasting and self.aw.qmc.timeindex[2] > -1:
                self.aw.qmc.markFCeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F5 and no_modifier and self.current_event in [3,4]: # 2C start can be marked any time after 1C end is marked, but not after 2C end is marked
            if self.is_roasting and self.aw.qmc.timeindex[3] > -1:
                self.aw.qmc.markSCsSignal.emit(False)
                return
        elif key==Qt.Key.Key_F6 and no_modifier and self.current_event in [4,5]: # 2C end can be marked any time after 2C start is marked, but not after drop is marked
            if self.is_roasting and self.aw.qmc.timeindex[4] > -1:
                self.aw.qmc.markSCeSignal.emit(False)
                return
        elif key==Qt.Key.Key_F7 and no_modifier and self.current_event in [5,6]: # drop can be marked any time after CHARGE is marked, but not after cool end is marked (except if it's a mispress before charge)
            if self.is_roasting and self.aw.qmc.timeindex[1] > -1: # just check that charge is marked to avoid mispresses before charge
                self.handle_drop()
                return
        elif key==Qt.Key.Key_F8 and no_modifier and self.current_event in [6,7]: # cool end can be marked any time after drop is marked, but not after another event is marked (except if it's a mispress before charge)
            if self.is_roasting and self.aw.qmc.timeindex[6] > -1:
                self.handle_cool()
                return
        # Pass other keys to the standard handler (important for ESC, etc.)
        self.aw.keyPressEvent(a0)
        super().keyPressEvent(a0)

    def _get_stepper_style(self, color):
        return f"""
            QPushButton {{
                background-color: #313244;
                color: {color};
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
                border: 1px solid transparent;
            }}
            QPushButton:hover {{
                background-color: #45475a;
                border: 1px solid {color}44;
            }}
            QPushButton:pressed {{
                background-color: {color};
                color: #11111b;
            }}
        """

    def align_panels(self):
        # Position the panel 10px below the main window
        self.event_panel.move(self.x(), self.y() + self.height() + 10)

    def align_extra_panel(self):
        """
        Place the extra-counters panel centered horizontally above the main window.
        Respects the panel's current size (user-resized or saved via QSettings)
        instead of forcing adjustSize(), which would break multi-line layouts.
        """
        geo = self.geometry()
        p_w = self.extra_panel.width()
        # Centre horizontally over TilauScope; 10 px below its top edge
        x = geo.x() + (geo.width() - p_w) // 2
        y = geo.y() + 10
        self.extra_panel.move(x, y)

    @pyqtSlot(int)
    def handle_alarm_trigger(self, alarm_index):
        """Méthode appelée quand Artisan détecte le déclenchement"""
        # Récupérer l'objet AlarmData correspondant à l'index
        # self.current_alarms est la liste chargée via _load_alarms[cite: 4]
        target_alarm = self.collapsible_events.alarm_sidebar.get_alarm_info(alarm_index)
        #_logd.info(f"alarm fired {alarm_index}")
        #_log.error(f"alarm fired {alarm_index}")
        if target_alarm:
            # On envoie les données et la couleur au widget de droite
            self.collapsible_events.alarm_sidebar.add_triggered_alarm(target_alarm)

    # ── Timer visual state machine ────────────────────────────────────────────
    # Three states:
    #   "idle"    : pre-charge, grey + slow opacity pulse (waiting / preheating)
    #   "roasting": charge → drop, white solid (no effect)
    #   "paused"  : simulator paused, orange + fast colour blink
    #
    # Call _update_timer_style(state) from any code path that changes the state.
    # ──────────────────────────────────────────────────────────────────────────

    def _update_timer_style(self, state: str) -> None:
        """ 
        Updates the timer look based on state: "roasting", "idle", or "paused" 
        """
        self._timer_state = state
        
        # Ensure the opacity effect attribute exists
        if not hasattr(self, "timer_opacity"):
            self.timer_opacity = None

        if  state == "roasting" or state == "engaged":
            # ROASTING: Lighter color, NO blinking
            if self.timer_lbl.graphicsEffect() is not None:
                self.timer_lbl.setGraphicsEffect(None)
            self.timer_opacity = None
            self.timer_lbl.setStyleSheet(
                "font-size: 36px; font-weight: 900; color: #CDD6F4; " # Lighter gray/white
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )
            
        elif state == "paused":
            # PAUSED (Simulation): Orange color, Blinking enabled
            if self.timer_opacity is None:
                self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
            self.timer_lbl.setGraphicsEffect(self.timer_opacity)
            self.timer_lbl.setStyleSheet(
                "font-size: 36px; font-weight: 900; color: #FAB387; " # Orange
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )
            
        else: # "idle"
            # IDLE: Dark gray, slow pulse
            if self.timer_opacity is None:
                self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
            self.timer_lbl.setGraphicsEffect(self.timer_opacity)
            self.timer_lbl.setStyleSheet(
                "font-size: 36px; font-weight: 900; color: #313244; " # Dark gray
                "border: none; background: transparent; font-family: 'JetBrains Mono';"
            )

    def pulse(self):
        """ 
        Handles the blinking/pulsing animation. 
        Called by p_timer (e.g., every 600ms).
        """
        state = getattr(self, "_timer_state", "idle")
        
        # 1. If roasting, ensure no effect is active and stop
        if state == "roasting":
            if self.timer_lbl.graphicsEffect() is not None:
                self.timer_lbl.setGraphicsEffect(None)
            return

        # 2. Manage the opacity for "paused" (blink) or "idle" (slow pulse)
        if self.timer_opacity is not None:
            if state == "paused":
                # Hard toggle for blinking
                new_opacity = 0.0 if self.timer_opacity.opacity() > 0.5 else 1.0
                self.timer_opacity.setOpacity(new_opacity)
            else: # "idle"
                # Soft pulse logic
                current = self.timer_opacity.opacity()
                # Toggle between 0.3 and 1.0 for idle visibility
                self.timer_opacity.setOpacity(1.0 if current < 1.0 else 0.4)
        
    # button CHARGE was pressed in the displayscope, update display and inform Artisan
    def start_roast(self, auto=False):
        if not self.aw.qmc.flagstart: # do not allow to press CHARGE before roast is really recorded
            return
        self.start_time = QTime.currentTime()
        self._update_timer_style("roasting")
        for btn in self.event_buttons.values():
            btn.setEnabled(True)
        # Réinitialiser les trackers min/max au CHARGE
        for lcd in (self.lcds.tg_lcd, self.lcds.te_lcd, self.lcds.ror_lcd):
            lcd.init_minmax()

    # updates phase_start structure with current timer value for given phase (key) and highlight the current phase using set_active
    def set_phase(self, key, artisan_secs: int = 0):
        self.current_phase = key
        for k, widget in self.phases.items():
            widget.set_active(k == key)
        self.last_phase = key
        # Store Artisan timer seconds at phase transition — same source as data==10
        self.phase_starts[key] = artisan_secs
    # get target pid value depending on pid usage (tilau or artisan) to display it in the preheating message
   
    def _get_pid_target(self)->str:
        # pidcontrol.sv est mis à jour par processcommand("sv") ET processcommand("start")
        # via setSV() — c'est le signal que l'alarme a été traitée pour cette session.
        # Tant qu'il ne correspond pas au slider, l'alarme n'est pas encore passée
        # → on retourne "" pour ne rien afficher plutôt qu'une valeur obsolète.
        try:
            ## TILAU ## When TilauPID drives the preheat, ITS target is the truth and
            ## needs no confirmation from Artisan: aw.pidcontrol.sv is only ever set
            ## by branches that require Artisan's own PID path (external PID / Control
            ## flag), so on a slider-driven roaster it stays None forever and the
            ## status message was stuck on "TilauPID is initializing" for the whole
            ## preheat.
            pid = self.aw.tilauPreheatingPid
            if pid is not None and pid.active:
                sv_native = int(round(pid.sv_native()))
                return str(sv_native) if sv_native > 0 else ""
            sv_pid = self.aw.pidcontrol.sv       # None ou valeur native
            sv_slider = self.sld_list[4].value() # toujours un int, valeur native
            if sv_pid is not None and sv_slider > 0 and int(sv_pid) == sv_slider:
                # alarme traitée — valeur confirmée pour cette session (> 0 évite "0" à l'init)
                return str(sv_slider)
            # alarme pas encore traitée → rien à afficher
            return ""
        except Exception:
            return ""

# build a string defining if we are close to target 
    def _is_pid_target_close(self, bt:float)->str:
        pid = self.aw.tilauPreheatingPid
        if pid and pid.active:
            sv = pid.sv_native()   # cfg.target_sv est °C interne ; bt est natif
            delta = sv - float(bt)
            #_logd.info(f"tilaupid target={sv} delta={delta} bt={bt}")
            return self.str_tilaupid_close if (delta <= 0) or abs(delta) <= (0.05 * sv) else "" # reduced from 10% to 5%
        return ""

    # build a string with the current pid status depending on artisan or tilaupid usage
    def get_pid_status(self):
            # Aucun PID configuré du tout → "with no PID"
            # Ne pas tester .active ici : TilauPID peut être en cours de démarrage
            # via signal queued non encore traité au moment où handle_preheat() est appelé
            if self.aw.tilauPreheatingPid is None and not self.is_pid_active:
                return self.str_nopid
            # Si TilauPID est configuré mais la cible n'est pas encore confirmée → message init
            if self.aw.tilauPreheatingPid is not None and not self.is_pid_active:
                target = self._get_pid_target()
                if not target:
                    return self.str_tilaupidinit
                ## TILAU ## NBSP (not a plain space) between value and unit: the label
                ## word-wraps and used to drop "°C" alone on the next line. A literal
                ##   survives .upper() where an &nbsp; entity would not.
                return (self.str_tilaupid + f" {target} °{self.aw.qmc.mode}").upper()
            pid_text = self.str_artisanpid if self.is_pid_active else ""
            target = self._get_pid_target()
            pid_target = f" {target} °{self.aw.qmc.mode}" if target else ""
            return pid_text.upper() + pid_target

    def _phase_wheel(self, widget, event) -> None:
        """Ajuste qmc.phases[idx] de ±1° par cran de molette/trackpad.

        Bornes absolues : 60-250°C / 140-482°F (converties selon qmc.mode).
        Bornes relatives adaptatives :
          - premier éditable (DRY, idx=first) : lo=abs_lo,      hi=phases[idx+1]-1
          - milieu (MAI)                       : lo=phases[idx-1]+1, hi=phases[idx+1]-1
          - dernier éditable (DEV, idx=last)   : lo=phases[idx-1]+1, hi=abs_hi
        first/last calculés dynamiquement depuis len(phases).
        Guards : flagon, phasesbuttonflag+DRY/MAI.
        """
        qmc = self.aw.qmc
        if qmc.flagon:
            return
        idx = widget._phase_idx          # 1=DRY, 2=MAI, 3=DEV
        key = widget._phase_key
        if qmc.phasesbuttonflag and key in ("DRY", "MAI"):
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        # Accumuler le delta pour normaliser souris (±120/cran) et trackpad (flux continu)
        # Un step ne se déclenche que quand l'accumulation atteint ±120
        attr = f"_wheel_acc_{widget._phase_key}"
        acc = getattr(self, attr, 0) + delta
        if abs(acc) < 120:
            setattr(self, attr, acc)
            return
        step = 1 if acc > 0 else -1
        setattr(self, attr, 0)  # reset après déclenchement

        phases = qmc.phases              # liste mutable [below_dry, dry, mai, dev, ...]
        n = len(phases)
        first_editable = 1              # DRY
        last_editable  = n - 1         # DEV (dernier index valide)

        # Bornes absolues en fonction de l'unité Artisan
        if qmc.mode == 'F':
            abs_lo, abs_hi = 140, 482   # ≈ 60°C / 250°C en Fahrenheit
        else:
            abs_lo, abs_hi = 60, 250

        # Bornes relatives adaptatives
        if idx == first_editable:
            lo = abs_lo
            hi = phases[idx + 1] - 1 if idx + 1 < n else abs_hi
        elif idx == last_editable:
            lo = phases[idx - 1] + 1 if idx > 0 else abs_lo
            hi = abs_hi
        else:
            lo = phases[idx - 1] + 1 if idx > 0 else abs_lo
            hi = phases[idx + 1] - 1 if idx + 1 < n else abs_hi

        new_val = max(lo, min(hi, phases[idx] + step))
        if new_val == phases[idx]:
            return
        phases[idx] = new_val
        widget.update_subtitle(self._update_phase_subtitle(key))
        # Flash bordure 150 ms dans la couleur de la phase
        flash = (f"PhaseWidget {{ background: {self.theme['BG']}; border-radius: 10px;"
                 f" border: 2px solid {widget.phase_color}; }}")
        idle  = "PhaseWidget { background: transparent; border: none; }"
        widget.setStyleSheet(flash)
        QTimer.singleShot(150, lambda w=widget, s=idle: w.setStyleSheet(s))

    @pyqtSlot(str, str, str, str)
    def handle_event_fired(self, label: str, command: str, timestamp: str, color: str) -> None:
        """Délègue l'event badge à la sidebar sans logique métier."""
        try:
            self.collapsible_events.alarm_sidebar.add_event_badge(label, command, timestamp, color)
        except Exception:
            pass

    # Enter preheating stage, 
    # engaged when start/stop button is pressed or Artisan STARTS
    def handle_preheat(self, show:bool = True):
        self.preheating = show
        # show or hide the individual phase widgets to make room for the message
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                if show :
                    widget.hide()
                else:
                    widget.show()   
        if show:     
            # Update and show the message
            status = self.get_pid_status()
            self.msg_lbl.setText(self.str_preheating + status)
            self.msg_lbl.show()
            self.msg_lbl.raise_()  # Force the label to the top of the stack
            # Style the container to highlight preheating mode
            self.phase_container.setStyleSheet("background: #0F0F12; border-radius: 15px; border: 1px solid #F38BA866;")
        else:
            self.phase_container.setStyleSheet("background: #0F0F12; border-radius: 15px; border: none;")
            # hide messag and show roasting phases zones
            self.msg_lbl.hide()
        if hasattr(self, 'roast_bridge'):
            self.roast_bridge.notify_preheat(show)
        self._update_timer_style("engaged")

    # update display on DROP, then inform artisan     
    def handle_drop(self):
        for i in range(self.phase_box.count()): 
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate("tilauscope_window","▼ DROPPING ROASTED COFFEE..."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()  # Force the label to the top of the stack
        self.phase_container.setStyleSheet("background: #0F0F12; border-radius: 15px; border: 1px solid #F38BA866;")
        self.aw.qmc.markDropSignal.emit(False)
        # Armer la détection de refroidissement
        self._arm_cooling_detection()

    ## TILAU ## arm/disarm shared by the UI/keyboard path (handle_drop) and the
    ## Artisan milestone path (_handle_milestone_events, data==6) so the auto
    ## cooling detection works regardless of how DROP was marked.
    def _arm_cooling_detection(self) -> None:
        self._drop_done = True
        self._cooling_detected = False
        try:
            self._bt_at_drop = float(self.aw.qmc.temp2[-1]) if self.aw.qmc.temp2 else None
            self._bt_drop_timestamp = self.aw.qmc.timex[-1] if self.aw.qmc.timex else None
        except (IndexError, TypeError):
            self._bt_at_drop = None
            self._bt_drop_timestamp = None

    def _disarm_cooling_detection(self) -> None:
        self._drop_done = False
        self._cooling_detected = False
        self._bt_at_drop = None
        self._bt_drop_timestamp = None

    def handle_cooling(self):
        """Déclenché automatiquement quand BT chute de >10°C en <30s après DROP."""
        self._cooling_detected = True
        for i in range(self.phase_box.count()):
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate(
            "tilauscope_window",
            "❄ COOLING IN PROGRESS\nSet drum & airflow high — or prepare for back-to-back roast."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()
        self.phase_container.setStyleSheet(
            "background: #0F0F12; border-radius: 15px; border: 1px solid #89DCEB66;")

    # update display on COOL END, then inform artisan
    def handle_cool(self):
        """Compatibilité — redirige vers handle_cool_end."""
        self.handle_cool_end()

    def handle_cool_end(self):
        for i in range(self.phase_box.count()): 
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText(QApplication.translate(
            "tilauscope_window",
            "✅ ROASTER IS NOW COOLED\nSafe to switch off."))
        self.msg_lbl.show()
        self.msg_lbl.raise_()
        self.phase_container.setStyleSheet(
            "background: #0F0F12; border-radius: 15px; border: 1px solid #A6E3A166;")
        self.aw.qmc.markCoolSignal.emit(False)
        # Réinitialiser les flags de refroidissement
        self._disarm_cooling_detection()
            
    def check_pid_status(self):
        ## TILAU ## tracks Artisan PID active state for the preheating status
        ## message only — the PID button/piloting was removed (handled by Artisan).
        if self.aw.pidcontrol.pidActive != self.is_pid_active:
            self.is_pid_active = self.aw.pidcontrol.pidActive

    ## TILAU ## ──────────────────────────────────────────────────────────────
    def _update_automation_banner(self) -> None:
        """Surface, in the status zone, any Artisan automation that drives the
        roast: PID active (from CHARGE) and the background playback modes.

        Called once per second from the TIMER path (data==10). Cheap: builds a
        short token list and only touches the widget when the set changes.
        """
        qmc = self.aw.qmc
        tokens: list[str] = []

        # Artisan PID piloting the heat — only meaningful once CHARGE is marked
        if self.is_pid_active and qmc.timeindex and qmc.timeindex[0] > -1:
            tokens.append(self.str_automation_pid)

        # Background playback modes — same flags as check_playback_before_start()
        # so the START warning and this in-roast banner stay consistent.
        if qmc.backgroundPlaybackEvents:
            tokens.append(self.str_automation_replay_events)
        if qmc.backgroundPlaybackDROP:
            tokens.append(self.str_automation_auto_drop)
        if qmc.backgroundReproduce:
            tokens.append(self.str_automation_playback_aid)

        key = tuple(tokens)
        if key == self._automation_prev:
            return
        self._automation_prev = key

        if not tokens:
            self.automation_lbl.hide()
            return
        self.automation_lbl.setText(f"{self.str_automation_prefix} — {' · '.join(tokens)}")
        self.automation_lbl.show()

    def _hide_automation_banner(self) -> None:
        """Hide the automation banner and reset its cache (roast end / OFF)."""
        self._automation_prev = None
        self.automation_lbl.hide()

    def _cycle_operator_level(self) -> None:
        """Toggle the operator level Guided ↔ Expert on button click. ## TILAU ##"""
        nxt = "expert" if getattr(self, "_operator_level", "guided") == "guided" else "guided"
        self._apply_operator_level(nxt)

    def _apply_operator_level(self, level: str, from_init: bool = False) -> None:
        """Apply the operator level and update UI accordingly.

        At init (from_init=True) only updates button states and visibility —
        anchor state has already been restored from QSettings above.
        At runtime, also adjusts the assistant anchor to match the new level.
        Never called in the hot update path — zero performance impact.
        """
        self._operator_level = level
        if not from_init:
            QSettings().setValue("tilauscope/operator_level", level)

        # Reflect the level on the cycling button (letter + colour + tooltip).
        _meta = {
            "guided": ("G", "#A6E3A1", QApplication.translate("tilauscope_window", "Guided")),
            "expert": ("E", "#FAB387", QApplication.translate("tilauscope_window", "Expert")),
        }
        _letter, _col, _name = _meta.get(level, _meta["guided"])
        _next_name = _meta["expert" if level == "guided" else "guided"][2]
        self.btn_level.setText(_letter)
        self.btn_level.setStyleSheet(
            f"QPushButton {{ background: #181825; color: {_col};"
            f" border: 1px solid {_col}; border-radius: 6px;"
            f" font-size: 13px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: #1E1E2E; }}"
            f"QToolTip {{ background-color: #2D2F3F; color: white;"
            f" border: 1px solid #585B70; padding: 5px;"
            f" border-radius: 3px; font-size: 11px; }}"
        )
        self.btn_level.setToolTip(
            QApplication.translate("tilauscope_window", "Operator level: {0} — click for {1}")
            .format(_name, _next_name))

        is_guided = level == "guided"
        # Panel-side anchor control (GREEN BEAN header of the advice zone):
        # Guided only. In Guided the assistant is anchored by default and the
        # ⤢ button floats it for a two-panel layout; Expert is main panel only.
        self.roast_assistant.set_panel_anchor_visible(is_guided)
        self.roast_assistant.set_operator_level(level)  ## TILAU ## propagate level (controls btn_toggle visibility)

        # Guided-only coach view toggle on the roast graph. ## TILAU ##
        try:
            self.aw.qmc.set_coach_toggle_allowed(is_guided)
        except Exception:  # pylint: disable=broad-except
            pass

        # ## TILAU ## Alarm control follows the operator level: Guided suppresses
        # all alarm actions (re-asserted each status refresh); Expert hands control
        # back to the user immediately. Applied at INIT too (below the from_init
        # guard would leave a fresh Expert start with alarms wrongly suppressed —
        # the startup update_status_text() runs before _operator_level exists and
        # defaults to Guided, setting silent_alarms=True).
        try:
            self.aw.qmc.silent_alarms = is_guided
        except Exception:  # pylint: disable=broad-except
            pass

        # ## TILAU ## Refresh the status line now — for the initial render as well
        # as later toggles — so the alarm-set suffix (🔕 …SUSPENDED in Guided,
        # plain ALARM-SET in Expert) matches the level from the very first paint;
        # while OFFLINE nothing else repaints it.
        self.update_status_text()

        if from_init:
            # Init keeps the QSettings-restored anchor untouched — only the
            # runtime toggle re-places the assistant below.
            return

        if not is_guided and self._assistant_anchored:
            # Expert: detach the assistant, back to the main control panel.
            self._assistant_anchored = False
            self._assistant_open = False
            QSettings().setValue("tilauscope/assistant_anchored", False)
            self._place_assistant()
        elif is_guided and not self._assistant_anchored:
            # Guided: anchor the assistant in place of the main panel.
            self.roast_assistant.populate_bean_list()
            self._assistant_anchored = True
            self._assistant_open = True
            QSettings().setValue("tilauscope/assistant_anchored", True)
            self.update_button_style(self.btn_assistant, True, False, False, True)
            self._place_assistant()

    def launch_guided_assistant(self) -> None:
        """Démarre et ancre l'assistant depuis le workflow Beancave → RoastSetup.

        Appelé automatiquement par RoastSetupDialog._on_ok() via QTimer.singleShot(0).
        Rafraîchit populate_bean_list() pour couvrir le cas où TilauScope était déjà
        ouvert avant que RoastSetup injecte qmc.beans.
        """
        if getattr(self, '_operator_level', 'guided') == 'expert':
            return
        self.roast_assistant.populate_bean_list()
        if not self._assistant_anchored:
            self.toggle_assistant_anchor()
        elif not self._assistant_open:
            self._assistant_open = True
            self.update_button_style(self.btn_assistant, True, False, False, True)
            self._place_assistant()
        self.roast_assistant.auto_start_from_workflow()

    def toggle_roast_assistant(self):
        """Toggle the roast assistant open/closed (placement is centralised)."""
        self._assistant_open = not getattr(self, '_assistant_open', False)   ## TILAU ##
        self.update_button_style(self.btn_assistant, self._assistant_open, False, False, True)
        if self._assistant_open:
            self.roast_assistant.populate_bean_list()   ## TILAU ## refresh bean identification on open
        self._place_assistant()                                              ## TILAU ##

    def refresh_assistant_beans(self) -> None:
        """## TILAU ## Rebuild the assistant's green-bean dropdown to match the
        current simulator state — all beans in simulator mode (any past roast is
        replayable regardless of stock), in-stock only otherwise. Appelé quand le
        simulateur est activé/arrêté pendant que TilauScope est ouvert. No-op si
        un roast est actif (la liste n'est alors plus en cours d'utilisation)."""
        try:
            ra = getattr(self, "roast_assistant", None)
            if ra is not None and not getattr(ra, "is_active", False):
                ra.populate_bean_list()
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("refresh_assistant_beans failed: %s", e)

    # ── Assistant anchoring ## TILAU ## ────────────────────────────────────────

    def toggle_assistant_anchor(self):
        """Toggle the assistant between floating and anchored display."""
        was_open = getattr(self, '_assistant_open', False)
        self._assistant_anchored = not getattr(self, '_assistant_anchored', False)
        if self._assistant_anchored:
            # Anchoring implies the assistant is open.
            self._assistant_open = True
            self.update_button_style(self.btn_assistant, True, False, False, True)
            if not was_open:
                self.roast_assistant.populate_bean_list()   ## TILAU ## refresh bean identification
        QSettings().setValue("tilauscope/assistant_anchored", self._assistant_anchored)
        self._place_assistant()

    def _place_assistant(self) -> None:
        """Single source of truth for assistant placement.

        Stack page 1 (anchored body) is shown iff the assistant is open AND
        anchored. The body is one widget reparented between the floating shell
        and the anchor host, so roast state and bridge signals survive every
        transition. The hidden stack page is not painted (no extra CPU).
        """
        open_    = getattr(self, '_assistant_open', False)
        anchored = getattr(self, '_assistant_anchored', False)
        want_host = open_ and anchored

        if want_host and not self._body_in_host:
            self._anchor_host.setWidget(self.roast_assistant.take_body())
            self._body_in_host = True
        elif not want_host and self._body_in_host:
            self._anchor_host.takeWidget()          # release without deleting
            self.roast_assistant.give_body()
            self._body_in_host = False

        self._panel_stack.setCurrentIndex(1 if want_host else 0)

        if open_ and not anchored:
            self.roast_assistant.show()
            self.roast_assistant.raise_()
        else:
            self.roast_assistant.hide()

        self.btn_dock.setEnabled(open_)
        self.update_button_style(self.btn_dock, anchored, False, False, True)  ## TILAU ## icon/state via pipeline

    def _on_assistant_closed(self) -> None:
        """Re-sync open/close state when the floating ✕ closes the assistant. ## TILAU ##"""
        if not getattr(self, '_assistant_open', False):
            return
        self._assistant_open = False
        self.update_button_style(self.btn_assistant, False, False, False, True)
        self._place_assistant()

    def toggle_beancave(self):
        """Toggles the visibility of the Bean Cave panel."""
        ## TILAU ## headless: BeanCave is the home view — leaving TilauScope means
        ## switching to BeanCave (close TilauScope, keep Artisan hidden). Delegated
        ## to aw.handleBeancave() so the button and the Shift+B/menu path converge.
        ## Deferred: handleBeancave closes this very TilauScope, so let the button
        ## click handler unwind first before we tear the window down.
        if getattr(self.aw, '_tilau_headless', False):
            QTimer.singleShot(0, lambda: self.aw.handleBeancave())
            return
        if hasattr(self.aw, 'beancaveWindow') and self.aw.beancaveWindow is not None and self.aw.beancaveWindow.isVisible():
            self.aw.beancaveWindow.close()
            self.update_button_style(self.btn_beancave, True, False, False)
        else:
            self.update_button_style(self.btn_beancave, False, False, True)
            self.aw.beancaveWindow = BeancaveDlg(self.aw)
            self.aw.beancaveWindow.setWindowModality(Qt.WindowModality.NonModal)
            self.aw.beancaveWindow.finished.connect(self._on_beancave_closed)
            self.aw.beancaveWindow.show()
    
    def _on_beancave_closed(self): # fix 2026/04/25: this is needed to uncheck the button if Beancave is closed by other means than the button (e.g. by Artisan or by the user with the window close button)
        """Called when BeancaveDlg is closed to unmark the button."""
        self.update_button_style(self.btn_beancave, True)

    def update_button_style(self, button:QPushButton, active:bool, emergency:bool=False, checked:bool=False, updateonly:bool=False):
        if not updateonly:
            button.setEnabled(active)
            if button.isCheckable():
                button.setChecked(checked)
        button.setProperty("active", "true" if active else "false")

        # ── icon refresh — lazy map (certains boutons peuvent ne pas encore exister) ──
        disabled = not button.isEnabled()
        _ICON_SPECS = [
            ('btn_power',     SVG_POWER,    COL_POWER_ACTIVE,    SVG_POWER,    COL_POWER_IDLE),
            ('btn_start_stop',SVG_STOP,     COL_START_ACTIVE,    SVG_PLAY,     COL_START_IDLE),
            ('btn_reset',     SVG_RESET,    COL_RESET_ACTIVE,    SVG_RESET,    COL_RESET_IDLE),
            ('btn_beancave',  SVG_BEANCAVE, COL_BEANCAVE_ACTIVE, SVG_BEANCAVE, COL_BEANCAVE_IDLE),
            ('btn_assistant', SVG_ASSISTANT,COL_ASSISTANT_ACTIVE,SVG_ASSISTANT,COL_ASSISTANT_IDLE),
            ('swap_button',   SVG_SWAP,     COL_SWAP_ACTIVE,     SVG_SWAP,     COL_SWAP_IDLE),
            ('btn_dock',      SVG_DOCK,     COL_DOCK_ACTIVE,     SVG_DOCK,     COL_DOCK_IDLE),   ## TILAU ##
        ]
        for attr, svg_a, col_a, svg_i, col_i in _ICON_SPECS:
            btn = getattr(self, attr, None)
            if btn is not None and btn is button:
                if disabled:
                    apply_icon(button, svg_i, COL_DISABLED)
                elif active:
                    apply_icon(button, svg_a, col_a)
                else:
                    apply_icon(button, svg_i, col_i)
                break

        # emergency override for btn_power
        if button is self.btn_power:
            button.setProperty("emergency", "true" if emergency else "false")
            if emergency:
                apply_icon(button, SVG_POWER, "#F38BA8")

        button.style().unpolish(button)
        button.style().polish(button)

    def open_main_menu(self):
        def get_inverted_icon(icon: QIcon) -> QIcon:
            if icon.isNull():
                return icon
            
            # Optimization: Use native Qt pixel inversion instead of Python loops.
            # This is significantly faster, especially on Windows.
            pixmap = icon.pixmap(QSize(16, 16))
            image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            if image.isNull():
                return icon
            
            # Invert RGB but preserve Alpha channel
            image.invertPixels(QImage.InvertMode.InvertRgb)
            return QIcon(QPixmap.fromImage(image))

        # ── Non-destructive mirror of Artisan's menu tree ## TILAU ## ──────────
        # Re-hosting live submenu objects via addMenu(menu) detaches them from
        # the native macOS menubar, so any later rebuild of root_menu loses
        # entries. Instead we create NEW QMenu containers and re-add the ORIGINAL
        # QActions (addAction shares the action → Artisan slot connections kept,
        # aw.menuBar() left intact). Recurses to preserve nested submenus.
        def clone_into(dst: QMenu, src: QMenu) -> None:
            for sub_action in src.actions():
                child = sub_action.menu()
                if child is not None:
                    branch = dst.addMenu(sub_action.text())
                    branch.setStyleSheet(MENU_STYLE)
                    if not sub_action.icon().isNull():
                        branch.setIcon(get_inverted_icon(sub_action.icon()))
                    clone_into(branch, child)
                    continue
                if sub_action.isSeparator():
                    dst.addSeparator()
                    continue
                if not sub_action.icon().isNull():
                    sub_action.setIcon(get_inverted_icon(sub_action.icon()))
                shortcut = sub_action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                if shortcut:
                    original_text = sub_action.text()
                    # On évite de doubler le raccourci si Artisan l'a déjà mis
                    if "\t" not in original_text:
                        # Le \t pousse tout ce qui suit à l'extrémité droite du menu
                        sub_action.setText(f"{original_text}\t{shortcut}")
                dst.addAction(sub_action)

        if self.root_menu is not None:
            self.root_menu.exec(QCursor.pos())
            return

        artisan_menubar = self.aw.menuBar()   
        self.root_menu = QMenu(self)
        self.root_menu.setStyleSheet(MENU_STYLE)
        for action in artisan_menubar.actions():
            menu_artisan = action.menu()
            if menu_artisan:
                top = self.root_menu.addMenu(action.text())
                top.setStyleSheet(MENU_STYLE)
                if not action.icon().isNull():
                    top.setIcon(get_inverted_icon(action.icon()))
                clone_into(top, menu_artisan)
        self.root_menu.exec(QCursor.pos())

    # ON / OFF BUTTON + Artisan instruction
    def toggle_power(self):
        if self.btn_power.isChecked():
            #power button
            self.update_button_style(self.btn_power, True, False, True)
            self.update_button_style(self. btn_start_stop, True)
            self.btn_power.setToolTip(QApplication.translate('Tooltip', 'Stop monitoring'))
            # reset button
            self.update_button_style(self.btn_reset, True)
            self.update_button_style(self.btn_assistant, True)
            # event buttons
            for btn in self.event_buttons.values():
                btn.setEnabled(True) 
            self.event_panel.show()
            self.aw.qmc.ToggleMonitor()
            self.update_status_text() # immediately update status to avoid waiting for first data from Artisan
            self._update_timer_style("engaged") # Update timer style based on power state
            self.update_button_style(self.swap_button, False)
        else:
            if self.is_roasting: # if stop is pressed during a roast, we first stop recording.
                self.toggle_start_stop(pressed=False, force=True)
            self.msg_lbl.setText(self.build_end_of_roast())
            # power button
            self.update_button_style(self.btn_power, False, False, False, True)
            self.update_button_style(self.btn_start_stop,False)
            self.btn_power.setToolTip(QApplication.translate('Tooltip', 'Start monitoring'))
            # reset button
            self.update_button_style(self.btn_reset, True)
            # roast assistant button
            self.update_button_style(self.btn_assistant, False)
            # event buttons
            for btn in self.event_buttons.values():
                btn.setEnabled(False) 
            self.event_panel.hide()
            self.update_button_style(self.swap_button, True)
            self.aw.qmc.ToggleMonitor()
            # reset roasting flag if OFF is called directly without STOP
            self.is_roasting = False
            self.extra_panel.reset_counters() # reset extra counters on power off
            self._update_timer_style("idle") # Update timer style based on power state
            self.update_status_text() # immediately update status to avoid waiting for first data from Artisan
            # Restaurer messagelabel Artisan au retour en mode OFF
            self.aw.messagelabel.setVisible(True)

    def handle_emergency(self):
        self.is_roasting = False
        self.m_timer.stop()
        self.p_timer.stop()
        self.update_button_style(self.btn_power, False, True)

        # Kill the heater and max out the fan via WebSocket
        self.bridge.send_to_artisan({"set": {"heater": 0, "fan": 100}}) 
        
        # Interface visuelle d'urgence
        self.timer_lbl.setStyleSheet("font-size: 80px; font-weight: 900; color: #F38BA8; border: none;")
        self.status_lbl.setText("EMERGENCY EXIT")
        self.status_lbl.setStyleSheet("color: #F38BA8; font-size: 11px; font-weight: 900;border: none; background: transparent;")
        
        # Overlay Message
        for i in range(self.phase_box.count()): 
            widget = self.phase_box.itemAt(i).widget()
            if widget:
                widget.hide()
        self.msg_lbl.setText("⚠️ EMERGENCY STOP\nSYSTEM SECURED")
        self.msg_lbl.setStyleSheet("color: #F38BA8; font-size: 22px; font-weight: 900; font-family: 'JetBrains Mono'; border: none; min-height:100px")
        self.msg_lbl.show()
        self.phase_container.setStyleSheet("background: #181825; border-radius: 15px; border: 2px solid #F38BA8;")

    def handle_reset(self):
        self.aw.qmc.resetButtonAction()

    # ── Relance back-to-back (bouton « Restart batch » de la page cooling) ─────

    def relaunch_batch(self) -> None:
        """Relance back-to-back « mode batch » (design validé) : STOP SANS
        formulaire de résultat, sauvegarde SILENCIEUSE de l'alog courant —
        incomplet, poids/couleur à compléter dans Repair ALogs pendant le
        batch suivant (fenêtre non-modale) — puis RESET, ré-injection de la
        session et START preheat."""
        if self.is_roasting:
            self._relaunch_pending = True   # court-circuite le formulaire de résultat
            self.toggle_start_stop(False, force=True)
            # laisser Artisan terminer sa fin de roast (mêmes 800 ms que le
            # formulaire) avant la sauvegarde + reset
            QTimer.singleShot(900, self._relaunch_continue)
        else:
            self._relaunch_continue()

    def _save_current_roast_silently(self) -> bool:
        """Sauvegarde l'alog courant sans dialogue : autosave Artisan si
        configuré, sinon écriture directe dans le répertoire alog TilauScope
        (même nomenclature generateFilename). Marque le profil « propre » pour
        que le RESET qui suit ne déclenche pas l'invite de sauvegarde.
        False si aucune destination n'existe — la relance est alors abandonnée
        plutôt que de risquer le roast."""
        try:
            qmc = self.aw.qmc
            if qmc.autosaveflag and qmc.autosavepath:
                return self.aw.automaticsave(interactive=False) is not None
            from artisanlib.util import serialize
            directory = qmc.autosavepath or QSettings().value('alogDirectory', '', str)
            if not directory or not Path(str(directory)).is_dir():
                _log.warning("relaunch: no save directory (autosavepath/alogDirectory) — aborted")
                return False
            prefix = qmc.autosaveprefix or (
                (qmc.batchprefix + str(qmc.roastbatchnr)) if qmc.roastbatchnr > 0
                else qmc.batchprefix)
            filename = self.aw.generateFilename(prefix=prefix)
            path = os.path.join(str(directory), filename)
            pf = self.aw.getProfile()
            if pf is None:
                return False
            serialize(path, pf)
            self.aw.setCurrentFile(path, False)
            qmc.fileCleanSignal.emit()
            self.aw.sendmessage(QApplication.translate(
                'Message', 'Profile {0} saved in: {1}').format(filename, str(directory)))
            _log.info("relaunch: silent save %s", path)
            return True
        except Exception as e:  # pylint: disable=broad-except
            _log.warning(f"relaunch silent save failed: {e}")
            return False

    def _relaunch_continue(self) -> None:
        """Phase 2 de la relance : sauvegarde silencieuse, capture de la
        session, RESET, ré-injection, START (preheat). L'assistant redémarre
        avec le même grain et un plan neuf incluant la correction heat-soak."""
        self._relaunch_pending = False
        qmc = self.aw.qmc
        # capture AVANT le reset qui efface title/beans/weight
        title = getattr(self.aw, '_tilau_live_title', '') or (qmc.title or '')
        beans = getattr(self.aw, '_tilau_live_beans', '') or (getattr(qmc, 'beans', '') or '')
        try:
            w = qmc.weight
            green_w, w_unit = float(w[0]), w[2]
        except (TypeError, IndexError, ValueError):
            green_w, w_unit = 0.0, 'g'
        # sauvegarde silencieuse de l'alog courant (incomplet) — sans elle,
        # pas de relance : on ne reset jamais par-dessus un roast non sauvé
        if not self._save_current_roast_silently():
            return
        if not qmc.reset():
            return   # l'utilisateur a annulé l'invite résiduelle
        if title:
            qmc.title = title
            qmc.title_show_always = True
        if beans:
            qmc.beans = beans
        if green_w > 0:
            # qmc.weight est un tuple au runtime : réassigner, jamais muter
            qmc.weight = (green_w, 0.0, w_unit)
        self.toggle_start_stop(False)   # équivalent clic START (branche sur is_roasting)

    # ── Drag handle handlers ────────────────────────────────────────────────────
    # Le drag passe uniquement par la handle — plus de détection childAt() fragile.
    # On déplace TilauScope en premier, puis on synchronise aw dessus.
    # Cela évite la boucle moveEvent(aw) → setGeometry(aw) → delta corrompu.

    def _handle_drag_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_self_origin = self.pos()
            self._dragging = True          # inhibe eventFilter/_safe_raise
        event.accept()

    def _handle_drag_move(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, "_drag_origin") or self._drag_origin is None:
            return
        delta = event.globalPosition().toPoint() - self._drag_origin
        dist = abs(delta.x()) + abs(delta.y())
        if dist < 2 or dist > 1200:
            return
        new_pos = self._drag_self_origin + delta
        self.move(new_pos)
        if self.aw:
            self.aw.move(new_pos)
        event.accept()

    def _handle_drag_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._dragging = False
        event.accept()

    # mousePressEvent principal : déléguer uniquement le fond nu (container)
    # La drag handle a ses propres handlers — pas besoin de la logique childAt ici
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is None or child == self.container:
                # Clic sur fond nu — activer drag de secours (même logique que handle)
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_self_origin = self.pos()
            else:
                event.ignore()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not hasattr(self, "_drag_origin") or self._drag_origin is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._drag_origin = None
            return
        delta = event.globalPosition().toPoint() - self._drag_origin
        dist = abs(delta.x()) + abs(delta.y())
        if dist < 2 or dist > 1200:
            return
        new_pos = self._drag_self_origin + delta
        self.move(new_pos)
        if self.aw:
            self.aw.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
        super().mouseReleaseEvent(event)

    def moveEvent(self, event):
        # This keeps the Button Panel (event_panel) attached 
        # whenever the TilauScope moves (triggered by the parent moving)
        if hasattr(self, 'event_panel'):
            self.align_panels()
        super().moveEvent(event)

    def resizeEvent(self, event):
        """Allow the window to keep its new size."""
        # Only perform layout updates here, do NOT call self.resize() 
        # or it will create an infinite loop/snap-back effect.
        super().resizeEvent(event)
        if hasattr(self, 'aw') and self.aw:
            # Sync the parent window's geometry to match this window
            self.aw.setGeometry(self.geometry())
            # If the event panel exists, we need to update its width and reposition it
            if hasattr(self, 'event_panel') and self.event_panel:
                self.event_panel.setFixedWidth(self.width())
                self.event_panel.update_panel_height()
                self.event_panel.move(self.x(), self.y() + self.height())

    def set_button_state(self, event:int, state:bool):
        button_key,button_color = self.events[event]
        btn = self.event_buttons[button_key]
        btn.setEnabled(state)  

    def set_button_style(self, event:int,state:bool):
        button_key,button_color = self.events[event]
        btn = self.event_buttons[button_key]
        if state:
            btn.setStyleSheet(f"""
            QPushButton {{ 
                background: #1E1E2E; 
                color: #CDD6F4; 
                border-radius: 8px; 
                border: 1px solid transparent; 
                border-left: 5px solid {button_color}; 
                font-size: 11px; 
                font-weight: bold; 
                text-align: left; 
                padding-left: 15px; 
            }}
            
            /* Bordure grise transparente au survol */
            QPushButton:hover {{
                background: #28283D;
                border: 1px solid rgba(148, 163, 184, 0.2); 
                border-left: 5px solid {button_color};
            }}

            /* Flash de couleur et effet d'enfoncement au clic */
            QPushButton:pressed {{
                background: {button_color}; 
                color: #11111B;
                padding-left: 18px;
                padding-top: 2px;
            }}
            """)
        else:
            btn.setStyleSheet("""
                QPushButton { 
                    background: #313244; 
                    color: #585B70; 
                    border-radius: 8px; 
                    border: 1px solid #45475a; 
                    border-left: 5px solid #585B70; 
                    font-size: 11px; 
                    font-weight: bold; 
                    text-align: left; 
                    padding-left: 15px; 
                }
            """)

    def _apply_sv_lock(self, locked: bool) -> None:
        """Enable/disable the whole SV row. No-op unless the state actually flips,
        so this stays O(1) on the pulse path. ## TILAU ##"""
        if locked == self._sv_locked or not self._sv_widgets:
            return
        self._sv_locked = locked
        tip = QApplication.translate(
            "tilauscope_window",
            "Set point driven by TilauPID while preheating"
        ) if locked else ""
        for w in self._sv_widgets:
            w.setEnabled(not locked)
            w.setToolTip(tip)

    def check_sliders_update(self):
        aw = self.aw
        ## TILAU ## mirror-only: copying Artisan values into our sliders must not
        ## re-fire the move/release handlers back toward Artisan. The visible
        ## value labels still refresh (their valueChanged lambda is not guarded).
        self._syncing_from_artisan = True
        try:
            # 1. Handle the first 4 sliders — use pre-computed tuple (no per-call allocation)
            for i, art_slider in enumerate(self._artisan_sliders):
                ## TILAU ## a click not yet committed (debounce window) has not
                ## reached Artisan yet: mirroring here would snap the slider back
                ## to the pre-click value mid-burst.
                if self._has_pending_commit(i):
                    continue
                new_val = art_slider.value()
                if self.sld_list[i].value() != new_val:
                    self.sld_list[i].setValue(new_val)
            # 2. Handle the SV slider logic (index 4)
            pid = aw.tilauPreheatingPid
            ## TILAU ## while the guided preheat runs, the SV displayed IS TilauPID's
            ## target — it is overwritten on every pulse, so editing it can only look
            ## broken. Lock the row instead of letting the operator fight the PID.
            self._apply_sv_lock(pid is not None and pid.active)
            if not self._has_pending_commit(4):
                if pid is not None and pid.active:
                    target_val = int(pid.sv_native())  # slider SV est en unité native
                    if target_val != self.sld_list[4].value():
                        self.sld_list[4].setValue(target_val)
                else:
                    sv_val = aw.sliderSV.value()
                    if self.sld_list[4].value() != sv_val:
                        self.sld_list[4].setValue(sv_val)
        finally:
            self._syncing_from_artisan = False

    # visual indication that a button event is triggered
    def mark_button_active(self, event:int, state:bool=False, disable_button:bool=False):
        """Visually disables a button when its event is triggered."""
        button_key,button_color = self.events[event]
        button_color_todim = toDim(self.artisan_conf.get_lightened_color(button_color))
        btn = self.event_buttons[button_key]
        btn.setEnabled(not disable_button)
        #_logd.info(f"mark_button_active event={event} state={state} button={button_key} btn_exists={btn is not None}")
        if btn:
            if disable_button:
                btn.setToolTip(QApplication.translate("tilauscope_window", "This event is already recorded"))
                btn.setStyleSheet(f"""
                    QPushButton:disabled {{ 
                        background: #2D2D35; 
                        color: {button_color}; 
                        border-radius: 8px; 
                        border: 1px solid #45475a; 
                        border-left: 5px solid #585B70; 
                        font-size: 11px; 
                        font-weight: bold; 
                        text-align: left; 
                        padding-left: 15px; 
                    }}
                """)
                return
            if not state: # button flat
                btn.setToolTip(QApplication.translate("tilauscope_window", "Click to cancel marking of this event"))
                btn.setStyleSheet(f"""
                    QPushButton {{ 
                        background: #313244; 
                        color: #585B70; 
                        border-radius: 8px; 
                        border: 1px solid #45475a; 
                        border-left: 5px solid #585B70; 
                        font-size: 11px; 
                        font-weight: bold; 
                        text-align: left; 
                        padding-left: 15px; 
                    }}
                    /* Bordure grise transparente au survol */
                    QPushButton:hover {{
                        background: {button_color_todim};
                        border: 1px solid rgba(148, 163, 184, 0.2); 
                        border-left: 5px solid {button_color};
                    }}
                    /* Flash de couleur et effet d'enfoncement au clic */
                    QPushButton:pressed {{
                        background: {button_color}; 
                        color: #11111B;
                        padding-left: 18px;
                        padding-top: 2px;
                    }}
                """)
            else: # not flat button
                btn.setToolTip(QApplication.translate("tilauscope_window", "Click to mark this event"))
                btn.setStyleSheet(f"""
                QPushButton {{ 
                    background: #1E1E2E; 
                    color: #CDD6F4; 
                    border-radius: 8px; 
                    border: 1px solid transparent; 
                    border-left: 5px solid {button_color}; 
                    font-size: 11px; 
                    font-weight: bold; 
                    text-align: left; 
                    padding-left: 15px; 
                }}
                
                /* Bordure grise transparente au survol */
                QPushButton:hover {{
                    background: #28283D;
                    border: 1px solid rgba(148, 163, 184, 0.2); 
                    border-left: 5px solid {button_color};
                }}

                /* Flash de couleur et effet d'enfoncement au clic */
                QPushButton:pressed {{
                    background: {button_color}; 
                    color: #11111B;
                    padding-left: 18px;
                    padding-top: 2px;
                }}
                """)

    def update_extradevices_from_artisan(self):
        # if extradevicesdisplay strategy have been changed, we must rebuild ExtraCounterPanel to update the display
        _logd.debug("Updating extra devices display from Artisan changes...")
                # Initialize the managed buttons
        visible:bool = False
        if self.extra_panel is not None:
            # extracoutner panel
            visible = self.extra_panel.isVisible()
            self.extra_panel.hide()
            self.extra_panel.deleteLater() # Clear the old panel to avoid duplicates
            self.extra_panel = None
        self.extra_panel = ExtraCountersPanel(self.artisan_conf, self.theme, self)
        self.extra_panel.reset_counters() # Initialize counters 
        self.align_extra_panel() # Align the panel based on current window geometry
        if visible:
            self.extra_panel.show()
        else:
            self.extra_panel.hide() # Caché 

    def update_events_from_artisan(self):
        # if buttons have changed, we must rebuild event buttons to update the button bar
        _logd.debug("Updating events display from Artisan changes...")
        # 1. Capturer géométrie AVANT destruction
        old_geo: QRect | None = None
        visible = False
        if self.event_panel is not None:
            visible = self.event_panel.isVisible()
            old_geo = self.event_panel.geometry()   # ← snapshot avant deleteLater
            self.event_panel.hide()
            self.event_panel.deleteLater()
            self.event_panel = None
            self.btn_manager = None

        # 2. Rebuild
        self.btn_manager = ButtonManager.from_artisan_settings(
            self.artisan_conf, self.artisan_conf.mode
        )
        self.event_panel = EventPanel(self.btn_manager, self.theme, self)

        # 3. Fixer la largeur EN PREMIER (critique pour heightForWidth)
        self.event_panel.setFixedWidth(self.width())

        # 4. Recalculer la hauteur avec une largeur connue
        self.event_panel.update_panel_height()

        # 5. Restaurer position : ancienne géométrie > QSettings > fallback align_panels
        if old_geo is not None:
            # Réutiliser directement la position avant rebuild
            self.event_panel.move(old_geo.topLeft())
        else:
            # Première fois : fallback sur align_panels
            self.align_panels()

        # 6. Visibilité
        if visible:
            self.event_panel.show()
        else:
            self.event_panel.hide()
          
    def update_pid_from_artisan(self,sv:int, move:bool = True, init:bool = False):
        #_log.info(f"update pid received from artisan sv={sv} move={move} init={init}")
        if self._has_pending_commit(4):
            return  ## TILAU ## uncommitted SV click wins over the echo from Artisan
        slider_sv = self.sld_list[4].value()
        if slider_sv != int(sv) :
            self.sld_list[4].setValue(int(sv))

    @pyqtSlot(int, object, object, bool)
    def update_ui_from_artisan(self, data, value=None, raw=None, buttonState=True):
        """Signal slot for qmc.tilauUpdateSignal. Guarded so no exception can
        propagate back into Artisan's sample loop (updateLCDs)."""
        try:
            self._apply_artisan_update(data, value, raw, buttonState)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception('tilau update failed (data=%s): %s', data, e)

    def _apply_artisan_update(self, data, value=None, raw=None, buttonState=True):
        # buttonState is used to know if we need to update button style (on event trigger) or not (on event reset)
        """Update labels with live data from Artisan."""
        # data values
        # extra devices values are collected every cycle
        # roasting events
        # 0 = CHARGE
        # 1 = DRY END
        # 2 = FIRST CRACK START
        # 3 = END OF FC
        # 4 = SECOND CRACK START
        # 5 = SC END
        # 6 = DROP
        # 7 = COOLING
        # main values to mirror from Artisan
        # 12 = BT
        # 11 = ET
        # 13 = Delta BT
        # 10 = Timer
        qmc = self.aw.qmc  # Cache reference
        val_str = str(value) if value is not None else ""

        # 1. Idle Timer
        if not self.is_roasting and data == "TIMER":
            self.timer_lbl.setText(val_str)

        # 2. Extra Panel Update — throttled to ≤ 1 Hz. This slot fires on every
        # channel (BT/ET/RoR/TIMER…, ~4×/sample) and BT/ET/RoR keep firing while
        # only monitoring — where data==10 does NOT (updateLCDtime guards on
        # flagstart). So a time throttle, not a data==10 gate, caps the cost
        # without freezing the panel during monitoring. First call after the
        # panel is shown runs immediately (timestamp stays stale while hidden).
        if self.extra_panel.isVisible():
            _now = time.monotonic()
            if _now - self._last_extra_update >= 0.9:
                self._last_extra_update = _now
                self.extra_panel.update_values()

        # 3. Handle Events
        if data == 12:  # BT event
            if self.lcds.tg_lcd.lbl_value.text() != val_str:
                self.lcds.tg_lcd.lbl_value.setText(val_str)
            fv = raw if isinstance(raw, (int, float)) else None

            if fv is not None:
                self.lcds.tg_lcd.set_alert_value(fv)
                if self.is_roasting and qmc.timeindex[0] > -1:
                    self.lcds.tg_lcd.update_minmax(fv)

                self.curr_bt = fv
                try:
                    p = qmc.phases
                    # phase_defs: (key, phase_index 0-based in self.phases, p start idx, p end idx)
                    # Phases passées → 100%, phase active → calcul, phases futures → 0%
                    phase_keys = self._PHASE_KEYS       # ordered (class constant)
                    phase_bounds = self._PHASE_BOUNDS   # indices dans qmc.phases
                    active_idx = phase_keys.index(self.current_phase) if self.current_phase in phase_keys else -1
                    for i, (key, (si, ei)) in enumerate(zip(phase_keys, phase_bounds)):
                        if i < active_idx:
                            self.phases[key].set_progress(100)
                        elif i == active_idx:
                            span = p[ei] - p[si]
                            prog = ((fv - p[si]) / span * 100) if span > 0 else 0
                            self.phases[key].set_progress(max(0, min(100, prog)))
                        else:
                            self.phases[key].set_progress(0)
                except (IndexError, ValueError):
                    pass

                # ── Détection automatique du refroidissement post-DROP ────────────
                # Seuil : chute BT > 10°C en moins de 30s après DROP
                if (self._drop_done
                        and not self._cooling_detected
                        and self._bt_at_drop is not None
                        and self._bt_drop_timestamp is not None):
                    try:
                        current_time = qmc.timex[-1] if qmc.timex else None
                        if current_time is not None:
                            elapsed = current_time - self._bt_drop_timestamp
                            if 0 < elapsed <= 30 and (self._bt_at_drop - fv) >= 10:
                                self.handle_cooling()
                    except (IndexError, TypeError):
                        pass

        elif data == 11:  # ET event
            if self.lcds.te_lcd.lbl_value.text() != val_str:
                self.lcds.te_lcd.lbl_value.setText(val_str)
            fv = raw if isinstance(raw, (int, float)) else None
            if fv is not None:
                self.lcds.te_lcd.set_alert_value(fv)
                if self.is_roasting and qmc.timeindex[0] > -1:
                    self.lcds.te_lcd.update_minmax(fv)

        elif data == 13:  # DELTABT (RoR) event
            if self.lcds.ror_lcd.lbl_value.text() != val_str:
                self.lcds.ror_lcd.lbl_value.setText(val_str)
            fv = raw if isinstance(raw, (int, float)) else None
            if fv is not None:
                self.lcds.ror_lcd.set_alert_value(fv)
                self.lcds.ror_lcd.set_ror_color(fv, qmc.mode)
                if self.is_roasting and qmc.timeindex[0] > -1:
                    self.lcds.ror_lcd.update_minmax(fv)

        elif data == 10:  # TIMER event
            self.timer_lbl.setText(val_str)

            if not qmc.flagon or not self.is_roasting:
                return

            # Parse Artisan's own timer value (format "MM:SS") — the single source of truth.
            # This eliminates any drift between our wall-clock and Artisan's internal clock.
            try:
                parts = val_str.split(":")
                total_secs = int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                return

            # Frequency Capping (1Hz)
            if total_secs <= self.last_update_second:
                return
            self.last_update_second = total_secs

            # SV sync — checked once per second max (SV changes rarely)
            sv = int(self.aw.pidcontrol.sv if self.aw.pidcontrol.sv is not None else 0)
            if sv != int(self.aw.sliderSV.value()):
                ## TILAU ## reflect the PID setpoint on Artisan's SV slider without
                ## re-triggering Artisan's own slider action (programmatic mirror).
                self.aw.sliderSV.blockSignals(True)
                self.aw.sliderSV.setValue(sv)
                self.aw.sliderSV.blockSignals(False)

            # Update Phase Stats — phase_starts now stores Artisan timer seconds at phase start
            if self.current_phase and self.phase_starts.get(self.current_phase) is not None:
                elapsed = total_secs - self.phase_starts[self.current_phase]
                self.phases[self.current_phase].update_stats(elapsed, max(total_secs, 1))

                if self.current_phase in ("MAI", "DEV") and self.phase_starts.get("DRY") is not None and self.phase_starts.get("MAI") is not None:
                    dry_dur = self.phase_starts["MAI"] - self.phase_starts["DRY"]
                    self.phases["DRY"].update_stats(dry_dur, max(total_secs, 1))
                    if self.current_phase == "DEV" and self.phase_starts.get("DEV") is not None:
                        mai_dur = self.phase_starts["DEV"] - self.phase_starts["MAI"]
                        self.phases["MAI"].update_stats(mai_dur, max(total_secs, 1))

            # Simulator pause/resume detection — update timer colour in real time
            if self._is_simulator:
                sim_paused = not self.aw.sample_loop_running
                current_timer_state = getattr(self, "_timer_state", "idle")
                if sim_paused and current_timer_state != "paused":
                    self._update_timer_style("paused")
                    self.p_timer.setInterval(300)   # faster blink when paused
                elif not sim_paused and current_timer_state == "paused":
                    # Resume: go back to roasting (white) if charge was already done
                    if self.aw.qmc.timeindex[0] > -1:
                        self._update_timer_style("roasting")
                    else:
                        self._update_timer_style("idle")
                    self.p_timer.setInterval(600)   # restore normal pulse rate

            # Build Status Text
            status_parts = []
            if qmc.flagstart:
                status_parts.append(self.str_roastsession.upper())
                
            if self._is_simulator:
                sim_text = self.str_simulator
                if not self.aw.sample_loop_running:
                    sim_text += f" {self.str_paused}"
                else:
                    speed = int(qmc.timeclock.getBase() / 1000)
                    if speed > 1: sim_text += f" x{speed}"
                status_parts.append(sim_text)

            # Auto-flags
            self.check_pid_status()
            self._update_automation_banner()   ## TILAU ## red-on-amber automation notice
            ti = qmc.timeindex
            if ti:
                if ti[0] == -1:  # Pre-charge
                    # get_pid_status() ne dépend pas de BT — toujours calculé
                    # _is_pid_target_close() nécessite BT — optionnel
                    p_text = self.get_pid_status()
                    if self.curr_bt is not None:
                        p_text += self._is_pid_target_close(self.curr_bt)
                    if getattr(self, "prev_pidtext", None) != p_text:
                        self.prev_pidtext = p_text
                        ## TILAU ## separator must be <br>, not \n: msg_lbl is in AutoText
                        ## mode and Qt's rich-text sniffing stops at the first newline, so
                        ## a leading "\n" made it render the whole message as plain text —
                        ## the <br>/<b> of the "ready to charge" line showed up literally.
                        self.msg_lbl.setText(f"{self.str_preheating}<br>{p_text}")
                    if qmc.autoChargeFlag: status_parts.append(self.str_autocharge)
                elif ti[1] == -1 and (qmc.autoDRYenabled or self.aw.TilauScopeDEMarkFlag):
                    status_parts.append(self.str_autodry)
                elif ti[2] == -1 and (qmc.autoFCsenabled or self.aw.bleTilauScopeautomarkFC or self.aw.TilauScopeFCMarkFlag):
                    status_parts.append(self.str_autofc)
                elif ti[2] > 0 and ti[6] == -1 and qmc.autoDROPenabled:
                    status_parts.append(self.str_autodrop)

            new_status = " - ".join(status_parts)
            if getattr(self, '_last_simulator_status', None) != new_status:
                self._last_simulator_status = new_status
                self.status_lbl.setText(new_status)

            self.check_sliders_update()

            if (self.roast_assistant.isVisible() or getattr(self, '_assistant_anchored', False)) and self.roast_assistant.is_active:   ## TILAU ##
                self.roast_bridge.tick(data)

        elif 0 <= data <= 7:  # Shared logic for Charge through Cool
            self._handle_milestone_events(data, buttonState)

    def _handle_milestone_events(self, data, buttonState: bool):
        """Extracted helper for standard roast events to keep main func clean."""
        self.current_event = data
        # Use the last Artisan timer value we received — same source as data==10,
        # so phase_starts and total_secs are always in the same unit with no drift.
        artisan_secs = self.last_update_second if self.last_update_second >= 0 else 0

        if data == 0:  # CHARGE
            if buttonState:
                self.last_update_second = -1
                self.handle_preheat(False)
                self.start_roast(auto=True)
                self.set_phase("DRY", 0)
                self.mark_button_active(0)
                self.roast_bridge.notify_phase("DRY")
            else:
                self.current_phase = None
                self.phase_starts = {"DRY": None, "MAI": None, "DEV": None}
                self.phases["DRY"].update_stats(0, 1)
                self.phases["MAI"].update_stats(0, 1)
                self.phases["DEV"].update_stats(0, 1)
                for p in self.phases.values():
                    p.set_active(False)
                self.handle_preheat(True)
                self.mark_button_active(0, state=True)
                self.roast_bridge.notify_phase("PREHEAT")
        elif data == 1:  # DRY END
            if buttonState:
                dry_elapsed = artisan_secs - (self.phase_starts["DRY"] or 0)
                self._set_phase_completed("DRY", dry_elapsed, "MAI", 1)
                self.phase_starts["MAI"] = artisan_secs
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, disable_button=False)
                self.roast_bridge.notify_phase("MAI")
            else:
                self.phase_starts["MAI"] = None
                self.phases["MAI"].update_stats(0, 1)
                self.phases["MAI"].set_active(False)
                self.set_phase("DRY", self.phase_starts["DRY"] or 0)
                self.mark_button_active(1, state=True)
                self.mark_button_active(0, state=True)
                self.roast_bridge.notify_phase("DRY")
        elif data == 2:  # FC START
            if buttonState:
                mai_elapsed = artisan_secs - (self.phase_starts["MAI"] or 0)
                self._set_phase_completed("MAI", mai_elapsed, "DEV", 2)
                self.phase_starts["DEV"] = artisan_secs
                self.roast_bridge.notify_phase("DEV")
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, disable_button=True)
                self.mark_button_active(2)
            else:
                self.phase_starts["DEV"] = None
                self.phases["DEV"].update_stats(0, 1)
                self.phases["DEV"].set_active(False)
                self.set_phase("MAI", self.phase_starts["MAI"] or 0)
                self.mark_button_active(0, disable_button=True)
                self.mark_button_active(1, state=True)
                self.mark_button_active(2, state=True)
                self.roast_bridge.notify_phase("MAI")
        elif data in (3, 4, 5):  # FC END, SC START, SC END
            self.mark_button_active(data, state=not buttonState)
        elif data == 6:  # DROP
            if buttonState:
                # Horodatage wall-clock du DROP : survit au RESET d'Artisan,
                # consommé par la correction heat-soak du prochain plan
                # (minutes_since_last_drop) et la reco d'attente back-to-back.
                self.aw._tilau_last_drop_wall = time.time()
                for n in range(1, 7):
                    self.mark_button_active(n, disable_button=True)
                self.roast_bridge.notify_phase("COOL")
                self.roast_assistant.update_batch()   # rafraîchit le badge batch (DROP + UNDO DROP)
                self._arm_cooling_detection()   ## TILAU ## arm even when DROP is marked from Artisan
            else:
                self.set_phase("DEV")
                self.mark_button_active(6, state=True)
                self.roast_bridge.notify_phase("DEV")
                self._disarm_cooling_detection()   ## TILAU ## DROP undone
        elif data == 7:  # COOL END
            if buttonState:
                self.roast_bridge.notify_phase("COOL")
                self.mark_button_active(7)
                self._disarm_cooling_detection()   ## TILAU ##
            else:
                self.set_phase("DEV", self.phase_starts.get("DEV") or 0)
                self.mark_button_active(7, state=True)
                self.mark_button_active(6)
                self.roast_bridge.notify_phase("COOL")

    def _set_phase_completed(self, phase_key, duration, next_phase, btn_idx):
        m, s = divmod(int(duration), 60)
        self.phases[phase_key].stats.setText(f"{m:02d}:{s:02d}")
        self.phases[phase_key].bar.setValue(100)
        self.set_phase(next_phase)
        self.mark_button_active(btn_idx)

    # called to refresh screen at start and when paused/resumed
    def update_status_text(self):
        try:
            if not hasattr(self, 'aw') or not self.aw or not hasattr(self.aw, 'qmc') or not self.aw.qmc: # artisan is not correctly initialized yet
                return
            if hasattr(self, 'menu_btn'):
                self.menu_btn.raise_()  # Pulls the button to the very front
                self.menu_btn.activateWindow() # Ensures it captures mouse events                
                _log.info("raise button")
            status_text = f"ARTISAN "+QApplication.translate("tilauscope_window","CONNECTED") if self.aw.qmc.flagon else QApplication.translate("tilauscope_window","OFFLINE")
            # if there is an alarm set selected
    
            # ## TILAU ## Guided mode is the sole control authority: suppress all
            # alarm ACTIONS via the native lever (conditions still evaluated,
            # nothing fired). Re-asserted here so it survives the reset that clears
            # silent_alarms (canvas ~15151); this method is the single point where
            # alarm-suppression state and its banner display stay in sync.
            if getattr(self, "_operator_level", "guided") == "guided":
                self.aw.qmc.silent_alarms = True
                alarm_set = QApplication.translate("tilauscope_window", " 🔕 ALARM-SET='<b>{0}</b>' SUSPENDED").format(self.aw.qmc.alarmsetlabel.upper()) if self.aw.qmc.alarmsetlabel != "" else ""
            else:
                alarm_set = QApplication.translate("tilauscope_window", " ALARM-SET='<b>{0}</b>'").format(self.aw.qmc.alarmsetlabel.upper()) if self.aw.qmc.alarmsetlabel != "" else ""
            status_text += alarm_set
            # if roast started
            # ## TILAU ## ground truth is Artisan's flagstart, NOT is_roasting: our
            # own flag drifts whenever recording is toggled outside our button (the
            # Artisan STOP, a remote command, the simulator), which left the banner
            # announcing a roast session well after it had ended. This method is the
            # sync point, so resync here rather than patch each caller.
            self.is_roasting = bool(self.aw.qmc.flagstart)
            # ## TILAU ## the guided assistant is started/stopped by the recording
            # state, but only our own START/STOP button used to announce it. A roast
            # started from Artisan (or the simulator, a remote command, an alarm)
            # therefore left the assistant on its idle page — bean identified in the
            # dropdown, never adopted, no plan. Same reasoning as the resync above:
            # this method is the single sync point, so the edge is emitted here.
            _prev_roasting = getattr(self, '_last_flagstart', None)
            if _prev_roasting is not None and _prev_roasting != self.is_roasting:
                try:
                    self.roast_bridge.notify_roast_state(self.is_roasting)
                except Exception as e:  # pylint: disable=broad-except
                    _log.debug("roast state notify: %s", e)
                # ## TILAU ## Artisan re-shows its own milestone bar at every
                # OnRecorder (applyStandardButtonVisibility) — TilauScope has its
                # own milestone row, so that bar must go back down whatever
                # started the recording, not only our own button.
                if self.is_roasting:
                    self._hide_artisan_standard_buttons()
            self._last_flagstart = self.is_roasting
            if self.is_roasting: # replace text with roast information
                status_text = self.str_roastsession.upper()
            # now check for simulation mode
            simulator_text =""
            self._is_simulator = bool(self.aw.simulator)
            if self._is_simulator:
                simulator_text = " - "+self.str_simulator if hasattr(self, "str_simulator") else "" # Fix 2026/04/15
                # "paused" only means something while the scope is still ON: with
                # monitoring off the loop is stopped, not paused, and the status
                # already says OFFLINE — claiming a pause on top of it is wrong.
                if not self.aw.sample_loop_running and self.aw.qmc.flagon:
                    simulator_text += " "+ self.str_paused
                else:
                    b= self.aw.qmc.timeclock.elapsedMilli()
                    try:
                        b_val = float(b)
                        if b_val > 1000.0:
                            simulator_text += f" x{round(b_val * 0.001, 0)}"
                    except (TypeError, ValueError):
                        pass
#                    if isinstance(b, float): # Fix 2026-09-29: Ensure b is a float before formatting
#                        simulator_text += " x"+str(round(b*0.001, 0)) if b > 1000 else ""
            # store concatened text
            self.status_lbl.setText(f"{status_text}{simulator_text}")
            self.status_lbl.setStyleSheet(f"color: {'#A6E3A1' if self.aw.qmc.flagon else '#F38BA8'}; border: none; background:transparent;")
            self.update_button_style(self.btn_power, self.aw.qmc.flagon, False, False, True)
            self.update_button_style(self.btn_start_stop, self.aw.qmc.flagstart, False, False, True)
            # ## TILAU ## remote clients live off Artisan's sampling ticks, which
            # stop with the sampling itself — a STOP that also takes monitoring down
            # (simulator) would never reach the phone. This method already runs at
            # every point where the desktop state changed, so it is the natural
            # place to push it. Guarded: the status bar must never break for it.
            try:
                tap = getattr(self.aw, 'tilau_telemetry_tap', None)
                if tap is not None:
                    tap.sync_state()
            except Exception as e:  # pylint: disable=broad-except
                _log.debug("remote sync_state: %s", e)
        except Exception as e:
            _log.error(e)

    ## TILAU ## Single choke point for every slider commit path (big control
    ## cards, +/- steppers, SmartRoller, assistant quick-adjust, slider drag).
    ## Repeated clicks restart the timer, so only the last value is pushed to
    ## Artisan: one hardware command and one recorded event per burst.
    ## `immediate=True` bypasses the delay (drag release — no repeat to coalesce).
    def handle_ui_input_released(self, n, immediate: bool = False):
        if self.init or self._syncing_from_artisan:
            return
        timer = self._slider_commit_timers.get(n)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(_SLIDER_COMMIT_DEBOUNCE_MS)
            timer.timeout.connect(lambda idx=n: self._commit_slider_value(idx))
            self._slider_commit_timers[n] = timer
        if immediate:
            timer.stop()
            self._commit_slider_value(n)
        else:
            timer.start()   # restart: the window slides on every new click

    def _has_pending_commit(self, n) -> bool:
        """True while slider `n` holds a click that has not reached Artisan yet."""
        timer = self._slider_commit_timers.get(n)
        return timer is not None and timer.isActive()

    def flush_pending_slider_commits(self):
        """Fire any debounced slider commit still pending (window close, etc.)."""
        for n, timer in self._slider_commit_timers.items():
            if timer.isActive():
                timer.stop()
                try:
                    self._commit_slider_value(n)
                except Exception as e:      # never let a flush break the caller
                    _log.error(e)

    def _commit_slider_value(self, n):
        """Push the current slider value to Artisan (hardware + event record)."""
        if self.init or self._syncing_from_artisan:
            return
        if n in [0,1,2,3]:
            slidervalue = self.sld_list[n].value()
            self.aw.moveslider(n,slidervalue)
            self.aw.extraeventsactionslastvalue[n] = int(round(slidervalue))
            value:float = (float(slidervalue)+10.0)*0.1
            self.aw.qmc.EventRecordAction(1,n,value,f'S{n:d}', False)
            self.aw.fireslideraction(n)
        else:
            slidervalue = self.sld_list[n].value()
            self.aw.pidcontrol.setSV(slidervalue,True)
            ## TILAU ## setSV only reaches Artisan's own SV slider when Artisan's PID
            ## path is configured (external PID, ArduinoTC4, Kaleido or the Control
            ## flag). On a slider-driven roaster none of those branches run, so
            ## aw.sliderSV kept its old value and check_sliders_update snapped our
            ## slider right back. Mirror it ourselves; signals stay blocked so this
            ## cannot re-enter Artisan's SV chain.
            if self.aw.sliderSV.value() != slidervalue:
                self.aw.sliderSV.blockSignals(True)
                self.aw.sliderSV.setValue(slidervalue)
                self.aw.sliderSV.blockSignals(False)

    def handle_ui_input_move(self, n, value):
        if self.init or self._syncing_from_artisan:
            return
        # add action to slider
        if n in [0,1,2,3]:
            slider_lcd:dict[int, callable[int]] = {
                0:self.aw.updateSlider1LCD, 
                1:self.aw.updateSlider2LCD, 
                2:self.aw.updateSlider3LCD, 
                3:self.aw.updateSlider4LCD
                }
            slider_lcd[n](value)
        else:
            ## TILAU ## SV now behaves like sliders 0-3: moving it only refreshes
            ## the LCD. The set-point reaches the PID at commit (release) only —
            ## it used to be pushed on every intermediate value, so a drag or a
            ## burst of +/- clicks retargeted the PID at each step.
            self.aw.updateSVSliderLCD(int(round(value)))
        
    #build end of roast message
    def build_end_of_roast(self)->str:
        try:
            # total time of roast from charge to drop
            total_sec = self.aw.qmc.timex[self.aw.qmc.timeindex[6]]-self.aw.qmc.timex[self.aw.qmc.timeindex[0]]+1
            m, s = divmod(int(total_sec), 60)
            str_total_time = f"{m:02d}:{s:02d}"
            # build DTR
            dtr = (self.aw.qmc.timex[self.aw.qmc.timeindex[6]]-self.aw.qmc.timex[self.aw.qmc.timeindex[2]]) * 100.0/ total_sec
            str_dtr = f"{dtr:.0f}%"
            # delta T
            temp_at_fc = self.aw.qmc.temp2[self.aw.qmc.timeindex[2]]
            temp_at_drop = self.aw.qmc.temp2[self.aw.qmc.timeindex[6]]
            delta_temp  = temp_at_drop - temp_at_fc
            str_delta_t =  f"{delta_temp:.1f}°{self.aw.qmc.mode}"
        except Exception:
            str_total_time = "--:--"
            str_dtr = "--"
            str_delta_t="--.-"
        return f"Total time: {str_total_time} - DTR {str_dtr} - Dev ΔT {str_delta_t}"
    
    def check_playback_before_start(self):
        """
        Méthode à appeler juste après le clic sur 'START'
        """
        active_modes = []
        # Accès aux flags via le Quality Management Controller (qmc) d'Artisan
        if self.aw.qmc.backgroundReproduce:
            active_modes.append(QApplication.translate("CheckBox", "Playback Aid"))
        if self.aw.qmc.backgroundPlaybackEvents:
            active_modes.append(QApplication.translate("CheckBox","Playback Events"))
        if self.aw.qmc.backgroundPlaybackDROP:
            active_modes.append(QApplication.translate("CheckBox","Playback DROP"))

        if active_modes:
            dlg = PlaybackWarningDlg(self.aw, active_modes)
            dlg.exec()
            
            if dlg.result_code == PlaybackWarningDlg.CANCEL:
                return False # On stoppe le processus de démarrage
                
            elif dlg.result_code == PlaybackWarningDlg.DISABLE_AND_START:
                # Désactivation propre via les méthodes d'Artisan pour mettre à jour l'UI
                self.aw.qmc.backgroundReproduce = False
                self.aw.qmc.turn_playback_event_OFF()
                self.aw.qmc.backgroundPlaybackDROP = False
                
#                # Mise à jour des indicateurs visuels (couleurs de boutons, etc.)
#                self.aw.updatePlaybackIndicator() 
#                self.aw.sendmessage("Automations désactivées pour ce roast.")
                
        return True # On autorise le démarrage
    
    ## TILAU ## single place hiding Artisan's own milestone/event button bar:
    ## TilauScope displays its own CHARGE/DRY/FC…/DROP row, so the Artisan one
    ## is redundant inside the canvas. Artisan re-shows it on every OnRecorder,
    ## hence more than one caller — never duplicate the loop.
    def _hide_artisan_standard_buttons(self) -> None:
        try:
            for b in self.artisan_buttons_collection.values():
                b.setVisible(False)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("hide artisan buttons: %s", e)

    # Handle START/STOP button action
    def toggle_start_stop(self, pressed, force=False):
        if force :
            pressed = False

        if not self.is_roasting and self.aw.qmc.device == 18 and self.aw.simulator is None:
            self.msg_lbl.setText(QApplication.translate(
                "tilauscope_window",
                "⚠ No meter connected — configure a device in Machine > Device."))
            self.msg_lbl.show()
            self.msg_lbl.raise_()
            return

        ## TILAU ## only warn about active automations when STARTING a roast;
        ## the dialog must never pop up on STOP (is_roasting already True).
        if not self.is_roasting and not self.check_playback_before_start():
            return
        ## TILAU ## snapshot BEFORE ToggleRecorder: Artisan calls back into
        ## update_status_text() synchronously, which resyncs self.is_roasting on
        ## flagstart. Reading the flag after the call therefore reports the NEW
        ## state, and a START was taken for a STOP — post-roast result dialog
        ## popping up 800 ms after pressing START.
        was_roasting = self.is_roasting
        self.aw.qmc.ToggleRecorder(pressed)
        if not was_roasting :
            # update roasting flag
            self.is_roasting = True
            # Reset timing state so phase counters start fresh
            self.last_update_second = -1
            self.phase_starts = {"DRY": None, "MAI": None, "DEV": None}
            self.current_phase = None
            # Switch timer to idle/preheating style while waiting for CHARGE
            self._update_timer_style("idle")
            self._hide_artisan_standard_buttons()
            # start preheating
            self.handle_preheat(True)
            #. disable reset button
            self.update_button_style(self.btn_reset, False)
            self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Stop recording'))
            # Masquer messagelabel Artisan : le flux est redirigé vers le ticker
            self.aw.messagelabel.setVisible(False)
            self.roast_bridge.notify_roast_state(True)   ## TILAU ##
        else:
            # update roasting flag
            self.is_roasting = False
            self._update_timer_style("idle")   # back to grey pulse
            self.roast_bridge.notify_roast_state(False)   ## TILAU ## stops the assistant
            self._hide_automation_banner()   ## TILAU ## clear automation notice at roast end
            if self.preheating:
                self.handle_preheat(False) 
                self.preheating = False
            self.update_status_text()
            # at end of roast enable reset button to clear the screen
            self.update_button_style(self.btn_reset, True)
            ## TILAU ## only the TilauScope preheating PID is piloted here;
            ## Artisan's own PID is left untouched (no longer driven by TilauScope).
            if self.aw.tilauPreheatingPid is not None and self.aw.tilauPreheatingPid.active:
                self.aw.tilauPreheatingPid.stop()
            self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Start recording'))
            # Ouvrir roast properties 800ms après la fin pour laisser Artisan terminer.
            # Mode batch (relance back-to-back) : PAS de formulaire — la saisie
            # poids/couleur est différée dans Repair ALogs (design validé), le
            # roast est sauvegardé incomplet silencieusement par la relance.
            if not self.aw.simulator and not getattr(self, '_relaunch_pending', False):
                QTimer.singleShot(800, self._open_roast_result_dialog)
            # reset phases display to normal
            for p in self.phases.values(): 
                p.set_active(False) 
            for n in range (0,8): # reset buttons styles
                self.set_button_style(n, True)
                self.set_button_state(n, False)
            # now update the current message label to display main info on roast session
            self.msg_lbl.setText("roasting has ended, press OFF button to display stats")
            # Restaurer messagelabel Artisan : fin de torréfaction
            self.aw.messagelabel.setVisible(True)
            # Réinitialiser les alertes de fond et tooltips min/max
            for lcd in (self.lcds.tg_lcd, self.lcds.te_lcd, self.lcds.ror_lcd):
                lcd.reset_alert()
                lcd.init_minmax()
            # finally call powxer off
            #QTimer.singleShot(250, self.toggle_power)

    def _open_roast_result_dialog(self) -> None:
        """Ouvre RoastResultDialog en fin de roast — même pattern que
        BeancaveDlg.on_roast_finished_clicked."""
        try:
            from tilauscope.roast_properties import RoastResultDialog
            from tilauscope.tilauscope_types import GreenBean

            ## TILAU ## reset() (ON/RESET) may have wiped qmc.title/qmc.beans.
            ## Restore the live values stashed at setup so the save filename
            ## and the .alog bean linkage are correct. Live DROP path only.
            qmc = self.aw.qmc
            default_title = QApplication.translate('Scope Title', 'TilauScope') ## TILAU ##
            stash_title = getattr(self.aw, '_tilau_live_title', '')
            stash_beans = getattr(self.aw, '_tilau_live_beans', '')
            if stash_title and (not qmc.title or qmc.title == default_title):
                qmc.title = stash_title
                qmc.title_show_always = True
            if stash_beans and not getattr(qmc, 'beans', ''):
                qmc.beans = stash_beans

            bean = None
            bc = getattr(self.aw, 'beancaveWindow', None)

            # Priorité 1 — BeancaveDlg ouvert et cave disponible
            if bc is not None and bc.cave is not None:
                row = bc.datatable.currentRow()
                if 0 <= row < len(bc.cave.green_beans):
                    bean = bc.cave.green_beans[row]

            # Priorité 2 — cave en mémoire → recherche par nom
            if bean is None and bc is not None and bc.cave is not None:
                name = getattr(bc, 'current_bean_name', None)
                if name:
                    bean = next(
                        (b for b in bc.cave.green_beans if b.name == name), None)

            # Fallback — bean vide
            if bean is None:
                bean = GreenBean()

            # green_weight depuis qmc.weight
            green_weight = 0.0
            try:
                green_weight = float(self.aw.qmc.weight[0])
            except (ValueError, TypeError, IndexError):
                pass

            dlg = RoastResultDialog(bean, self.aw, green_weight=green_weight)
            dlg.exec()
        except Exception as e:
            _log.warning(f"_open_roast_result_dialog: {e}")

    def timer_clicked(self):
        # only call superior routine if simulator is engaged and roast ON
        if self._is_simulator and self.aw.qmc.flagon:
            self.aw.superusermodeLeftClicked()
            # refresh our screen
            self.update_status_text()

    def clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    @pyqtSlot(QWidget, QLayout, bool)
    def toggle_panels(self, left_widget:QWidget, content_layout:QLayout, swap:bool):
        # 1. Prevent the UI from repainting until we are done (saves CPU)
        self.setUpdatesEnabled(False)
        try:
            # 2. Use the cached boolean (Point 2)
            if swap:
                self.is_swapped = not self.is_swapped
                settings = QSettings()
                settings.setValue("interface/swap_events_control", self.is_swapped)

            widgets = []
            while content_layout.count() > 0:
                item = content_layout.takeAt(0)
                if item.widget():
                    widgets.append(item.widget())

            if self.is_swapped:
                content_layout.addWidget(self.collapsible_events.sidebar, stretch=0)
                content_layout.addWidget(self.collapsible_events.grip,    stretch=0)
                content_layout.addWidget(self.artisan_graph, stretch=1)
                content_layout.addWidget(left_widget, stretch=0)
                self.swap_button.setToolTip(QApplication.translate('tilauscope_window', 'Swap panel position from right to left'))
            else:
                content_layout.addWidget(left_widget, stretch=0)
                content_layout.addWidget(self.artisan_graph, stretch=1)
                content_layout.addWidget(self.collapsible_events.grip,    stretch=0)
                content_layout.addWidget(self.collapsible_events.sidebar, stretch=0)
                self.swap_button.setToolTip(QApplication.translate('tilauscope_window', 'Swap panel position from left to right'))
        finally:
            # 3. Re-enable updates and trigger one single clean repaint
            self.setUpdatesEnabled(True)

    def showMessage(self, message:str):
        mb = TilauMessageBox(None, QApplication.translate("tilauscope_window","Roasting"), message, None, True, 500)
        mb.exec()
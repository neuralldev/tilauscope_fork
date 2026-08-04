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

# courtesy to Difluid team which provided the API structure of packets exchanged through BLE
# and V005 firmware update though the app (this is mandatory for this coupling to work)

# AUTHOR
# TiLau 2025

import logging
from typing import Final, TYPE_CHECKING

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QWidget, QApplication, QHBoxLayout, QFrame, QScrollArea
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QPainterPath, QBrush
from PyQt6.QtCore import Qt, QRectF, QPointF, QRect, QPoint, QSize, QPropertyAnimation, QTimer

from dataclasses import dataclass
from mashumaro.mixins.dict import DataClassDictMixin
from tilauscope.tilauscope_types import THEME, show_styled_message
from tilauscope.ai_service import AITask
from tilauscope.ai_float_panel import AIFloatPanel

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow # noqa: F401 # pylint: disable=unused-import

_log: Final[logging.Logger] = logging.getLogger(__name__)

class AlarmTimelineDialog(QDialog):
    def __init__(self, parent:QWidget, alarm_source_list:list[str], aw:'ApplicationWindow') -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        

        self.aw = aw
        self.alarm_source_list = alarm_source_list
        self.oldPos = None # Initialisation pour éviter les erreurs de déplacement

        # Fetch current data
        self.current_data = {
            'alarmflags': self.aw.qmc.alarmflag,
            'alarmtimes': self.aw.qmc.alarmtime,
            'alarmoffsets': self.aw.qmc.alarmoffset,
            'alarmactions': self.aw.qmc.alarmaction,
            'alarmstrings': self.aw.qmc.alarmstrings,
            'alarmguards': self.aw.qmc.alarmguard,
            'alarmnegguards': self.aw.qmc.alarmnegguard,
            'alarmsources': self.aw.qmc.alarmsource,
            'alarmconds': self.aw.qmc.alarmcond,
            'alarmtemperatures': self.aw.qmc.alarmtemperature
        }

        self.setup_ui()
        self.resize(1200, 800)

        # AI floating panel – top-level window owned by this dialog
        self._ai_panel = AIFloatPanel(
            task_type  = AITask.ALARM_NARRATIVE,
            ai_service = self.aw.tilau_ai_service,
            title      = QApplication.translate("tilauscope_alarms", "Alarm Narrative"),
            owner      = self,
            aw         = self.aw,
        )
        self._ai_panel.set_payload_fn(self._build_alarm_payload)

    def setup_ui(self):

       # Main layout with margins for the shadow effect/container
        self.main_layout = QVBoxLayout(self)
        
        # Main Container (Matches TilauScope style)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{ 
                background-color: {THEME['BG']}; 
                border: 1px solid {THEME['BORDER']}; 
                border-radius: 20px; 
            }}
        """)
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(25, 25, 25, 25)
        self.main_layout.addWidget(self.container)

        # 1. HEADER
        header = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate('Label', 'Visual Alarm Timeline').upper())
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 18px; font-weight: 900; "
            f"font-family: 'JetBrains Mono'; border: none; letter-spacing: 2px;"
        )
    
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.clicked.connect(self.fade_out_and_close)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{ 
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border-radius: 16px; border: 1px solid {THEME['BORDER']}; font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """)
        header.addWidget(title_lbl)
        header.addStretch()
        header.addWidget(self.close_btn)
        self.content_layout.addLayout(header)

        self.visualalarm_scroll = QScrollArea()
        self.visualalarm_scroll.setWidgetResizable(False)  # manual size via sizeHint

        self.timeline_widget = AlarmTimelineWidget(self.current_data, self.alarm_source_list, self, self.aw)
        self.timeline_widget.zoom_changed.connect(self._on_zoom_changed)

        self.visualalarm_scroll.setWidget(self.timeline_widget)
        self.content_layout.addWidget(self.visualalarm_scroll)
        self.content_layout.setStretchFactor(self.visualalarm_scroll, 1)
        
         # Actions
        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        ai_configured = self.aw.tilau_aiConfig.is_configured
        text = QApplication.translate('Button','Generate explanation (AI)').upper()
        self.AI_button = QPushButton("✦  " + text)
        self.AI_button.setFixedHeight(36)
        self.AI_button.clicked.connect(self._toggle_ai_panel)
        self.AI_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {THEME['ACCENT']};
                border: 1px solid {THEME['ACCENT']};
                border-radius: 8px;
                padding: 0 16px;
                font-family: 'JetBrains Mono';
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {THEME['ACCENT']};
                color: {THEME['BG']};
            }}
            QPushButton:disabled {{
                border-color: {THEME['BORDER']};
                color: {THEME['SUBTEXT']};
            }}
        """)
        self.AI_button.setVisible(ai_configured)
        width = self.AI_button.fontMetrics().horizontalAdvance("✦  " + text) + 40
        self.AI_button.setFixedWidth(width)
        buttons.addWidget(self.AI_button)

        text = QApplication.translate('Button','Auto-center timeline').upper()
        self.Autocenter_button = QPushButton(text)
        self.Autocenter_button.setFixedHeight(36)
        self.Autocenter_button.clicked.connect(self.autocenter_timeline)
        self.Autocenter_button.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
                padding: 0 16px;
                font-family: 'JetBrains Mono';
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                border-color: {THEME['ACCENT']};
                color: {THEME['ACCENT']};
            }}
        """)
        self.Autocenter_button.setEnabled(True)
        self.Autocenter_button.setToolTip(QApplication.translate('Tooltip','Automatically center the timeline in the visualization window.'))
        width = self.Autocenter_button.fontMetrics().horizontalAdvance(text) + 40
        self.Autocenter_button.setFixedWidth(width)
        buttons.addWidget(self.Autocenter_button)

        # Zoom controls
        _zoom_btn_ss = f"""
            QPushButton {{
                background: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ border-color: {THEME['ACCENT']}; color: {THEME['ACCENT']}; }}
        """
        self._btn_zoom_out = QPushButton("⊖")
        self._btn_zoom_out.setFixedSize(36, 36)
        self._btn_zoom_out.setToolTip(QApplication.translate('Tooltip', 'Zoom out (Ctrl+scroll down / pinch)'))
        self._btn_zoom_out.setStyleSheet(_zoom_btn_ss)
        self._btn_zoom_out.clicked.connect(lambda: self.timeline_widget.apply_zoom_step(-0.1))

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet(
            f"color: {THEME['SUBTEXT']}; font-family: 'JetBrains Mono'; font-size: 11px; border: none;")

        self._btn_zoom_in = QPushButton("⊕")
        self._btn_zoom_in.setFixedSize(36, 36)
        self._btn_zoom_in.setToolTip(QApplication.translate('Tooltip', 'Zoom in (Ctrl+scroll up / pinch)'))
        self._btn_zoom_in.setStyleSheet(_zoom_btn_ss)
        self._btn_zoom_in.clicked.connect(lambda: self.timeline_widget.apply_zoom_step(+0.1))

        buttons.addSpacing(12)
        buttons.addWidget(self._btn_zoom_out)
        buttons.addWidget(self._zoom_label)
        buttons.addWidget(self._btn_zoom_in)

        buttons.addStretch()
        
        # 4 Trigger a layout recalculation without showing the window
        self.content_layout.addLayout(buttons)

        self.content_layout.layout().activate()
        self.show()
        QTimer.singleShot(100, self.autocenter_timeline)
        QTimer.singleShot(150, self._center_on_screen)

    def _center_on_screen(self) -> None:
        """Centre la fenêtre sur l'écran après que Qt ait finalisé la géométrie."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )
        # Sur macOS avec FramelessWindowHint, move() est asynchrone.
        # On diffère le repositionnement du panel IA pour qu'il lise
        # la position effective après que le WM ait déplacé la fenêtre.
        QTimer.singleShot(50, self._reposition_ai_panel)

    def _reposition_ai_panel(self) -> None:
        """Repositionne le panel IA après que le move() soit effectif."""
        if hasattr(self, "_ai_panel") and self._ai_panel is not None:
            self._ai_panel.reposition()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # On vérifie si on clique sur un widget interactif
            widget = self.childAt(event.position().toPoint())
            if isinstance(widget, (QPushButton, QTextEdit, QScrollArea)):
                event.ignore() # On laisse le bouton gérer son clic
                return
            
            self.oldPos = event.globalPosition().toPoint()

    def closeEvent(self, event) -> None:
        if hasattr(self, "_ai_panel") and self._ai_panel is not None:
            try:
                from tilauscope.ai_service import AITask  # noqa: PLC0415
                self._ai_panel._ai_service.cancel(AITask.ALARM_NARRATIVE)
            except Exception:
                pass
            self._ai_panel.hide()
            self._ai_panel.close()
            self._ai_panel = None
        super().closeEvent(event)

    def mouseMoveEvent(self, event):
        if self.oldPos is not None:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.oldPos = None
 
    def _on_zoom_changed(self, factor: float) -> None:
        """Update zoom label and resize timeline widget after zoom change."""
        pct = int(round(factor * 100))
        self._zoom_label.setText(f"{pct}%")
        hint = self.timeline_widget.sizeHint()
        self.timeline_widget.resize(hint)

    def autocenter_timeline(self) -> None:
        if hasattr(self, 'visualalarm_scroll') and self.visualalarm_scroll is not None:
            v_bar = self.visualalarm_scroll.verticalScrollBar()
            h_bar = self.visualalarm_scroll.horizontalScrollBar()

            # Reset horizontal to start
            h_bar.setValue(0)

            # To center the content vertically:
            # The maximum value of the scrollbar represents the bottom-most scroll position.
            # Setting it to half of the maximum effectively centers the scrollable content.
            v_center = v_bar.maximum() // 2
            v_bar.setValue(v_center)

    def fade_out_and_close(self):
        if hasattr(self, "_ai_panel") and self._ai_panel is not None:
            self._ai_panel.hide()
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0); self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.close)
        self.anim.start()

    def _toggle_ai_panel(self) -> None:
        self._ai_panel.toggle()

    def moveEvent(self, event) -> None:  # noqa: ANN001
        super().moveEvent(event)
        if hasattr(self, "_ai_panel") and self._ai_panel.isVisible():
            self._ai_panel.reposition()

    def _build_alarm_payload(self) -> tuple[str, str]:
        """Build system + user messages for the AI alarm narrative."""
        alarm_objects = self.timeline_widget.alarm_objects
        if not alarm_objects:
            return ("", "")

        EVENT_NAMES  = self.timeline_widget.EVENT_NAMES
        ACTION_LIST  = self.timeline_widget.ACTION_LIST
        ALARM_CONDS  = self.timeline_widget.ALARM_CONDS

        lines: list[str] = []
        for alarm in sorted(alarm_objects, key=lambda a: a.data.index):
            d = alarm.data

            # Timing
            if d.event_code == 10:
                if d.previous_alarm > 0:
                    timing = f"IF Alarm #{d.previous_alarm} triggered, at +{d.offset}s"
                elif d.not_alarm > 0:
                    timing = f"IF Alarm #{d.not_alarm} NOT triggered, at +{d.offset}s"
                else:
                    timing = f"Conditional trigger at +{d.offset}s"
            else:
                event  = EVENT_NAMES.get(d.event_code, "Event")
                timing = f"At {event} +{d.offset}s"

            # Action
            action = ACTION_LIST.get(d.action, "Action")
            value  = f" → {d.msg}" if d.msg else ""

            # Trigger condition (sensor threshold)
            condition = ""
            if d.alarm_source != -3:
                try:
                    src = self.timeline_widget.alarm_source_list[d.alarm_source + 3]
                except (IndexError, AttributeError):
                    src = f"source#{d.alarm_source}"
                try:
                    cond_sym = ALARM_CONDS[d.alarm_cond]
                except (IndexError, TypeError):
                    cond_sym = "?"
                if d.alarm_temperature > 0:
                    condition = f" [trigger: {src} {cond_sym} {d.alarm_temperature:.0f}°]"

            lines.append(
                f"- #{d.index + 1}: {timing} → {action}{value}{condition}"
            )
        if self.aw.tilau_roaster:
            roaster_text = f" such as from a {self.aw.tilau_roaster}"
        else:
            roaster_text = ""
        _locale_map = {"fr": "French", "en": "English", "de": "German", "es": "Spanish",
                       "it": "Italian", "ja": "Japanese", "zh": "Chinese", "pt": "Portuguese",
                       "nl": "Dutch", "ko": "Korean", "ru": "Russian", "pl": "Polish"}
        _lang = _locale_map.get(self.aw.qmc.locale_str, self.aw.qmc.locale_str)
        system = (
            "You are an expert coffee roasting consultant specializing in roasting. "
            "You need to assess the alarm sequence programmed into the roaster, along with any notes from the roaster. "
            f"The roaster device used is{roaster_text}, commonly used in specialty coffee roasting; "
            "it brings a high level of control and precision to the roasting process, "
            "allowing roasters to fine-tune their profiles with great detail "
            "based on independent air, drum, speed, and burner controls.\n"
            "Analyse the alarm sequence below and produce a structured report with these exact sections:\n"
            "1. **Overview** – one paragraph summarising the automation strategy.\n"
            "2. **Phase-by-phase breakdown** – for each roast phase (Charge, Drying, Maillard, Development, Drop), "
            "describe the alarms that fire and their purpose.\n"
            "3. **Conditional logic** – explain all IF-ALARM dependencies clearly.\n"
            "4. **Assessment** – rate the overall strategy (coherent / has gaps / over-automated) with brief justification.\n"
            "5. **Suggestions** – list only genuine improvements; skip this section entirely if none exist.\n"
            f"Be concise and direct. Avoid technical jargon. Use Markdown. "
            f"Your entire response MUST be written in {_lang}. Do not translate or summarise this prompt."
        )
        user = "Alarm sequence:\n\n" + "\n".join(lines)
        return (system, user)

@dataclass
class AlarmData(DataClassDictMixin):
    index: int
    event_code: int
    offset: int
    action: int
    msg: str
    previous_alarm: int
    not_alarm: int
    alarm_cond : int
    alarm_source: int
    alarm_temperature: float
    is_active: bool

class AlarmItem:
    def __init__(self, data: AlarmData, color: QColor):
        self.data = data
        self.color = color
        self.visual_pos = QPointF(0, 0) 
        self.rect = QRectF()
        self.initialized = False

class AlarmTimelineWidget(QWidget):
    from PyQt6.QtCore import pyqtSignal
    zoom_changed = pyqtSignal(float)

    # Base X positions (at zoom=1.0) for each event code, in logical pixels
    _BASE_EVENT_X: dict[int, int] = {
        9: 100,    # ON
        -1: 280,   # START
        0: 460,    # CHARGE
        8: 640,    # TP
        1: 820,    # DRY END
        2: 1000,   # FC START
        3: 1130,   # FC END
        4: 1260,   # SC START
        5: 1390,   # SC END
        6: 1520,   # DROP
        7: 1700,   # COOL END
    }
    # Base height at zoom=1.0 per alarm slot
    _BASE_SLOT_H: int = 45
    _BASE_MIN_H:  int = 800
    _ZOOM_MIN:    float = 0.3
    _ZOOM_MAX:    float = 2.0
    _ZOOM_STEP:   float = 0.1

    def __init__(self, data: dict, alarm_souce_list: list[str], parent: QWidget, aw: 'ApplicationWindow') -> None:
        super().__init__(aw)
        self.parent = parent
        self.aw = aw
        self.alarm_source_list = alarm_souce_list
        self.dragging_alarm = None
        self.drag_offset = QPointF()
        self.active_tick = None
        self._zoom_factor: float = 1.0
        self._pinch_start_factor: float = 1.0  # accumulator for native pinch gesture

        self.alarm_objects: list[AlarmItem] = []
        self.EVENT_NAMES = {
            9: "ON", -1: "START", 0: "CHARGE", 8: "TP", 1: "DRY END",
            2: "FC START", 3: "FC END", 4: "SC START", 5: "SC END",
            6: "DROP", 7: "COOL END", 10: "IF ALARM"
        }

        self.ACTION_LIST = {
            0: QApplication.translate('ComboBox','Pop Up'),
            1 : QApplication.translate('ComboBox','Call Program'),
            2 : QApplication.translate('ComboBox','Event Button'),
            3: QApplication.translate('ComboBox','Slider') + ' ' + self.aw.qmc.etypesf(0),
            4: QApplication.translate('ComboBox','Slider') + ' ' + self.aw.qmc.etypesf(1),
            5: QApplication.translate('ComboBox','Slider') + ' ' + self.aw.qmc.etypesf(2),
            6: QApplication.translate('ComboBox','Slider') + ' ' + self.aw.qmc.etypesf(3),
            7: QApplication.translate('ComboBox','START'),
            8:QApplication.translate('Label','DRY END'),
            9:QApplication.translate('Label','FC START'),
            10:QApplication.translate('Label','FC END'),
            11:QApplication.translate('Label','SC START'),
            12:QApplication.translate('Label','SC END'),
            13:QApplication.translate('Label','DROP'),
            14:QApplication.translate('ComboBox','COOL END'),
            15:QApplication.translate('ComboBox','OFF'),
            16:QApplication.translate('Label','CHARGE'),
            17:QApplication.translate('ComboBox','RampSoak ON'),
            18:QApplication.translate('ComboBox','RampSoak OFF'),
            19:QApplication.translate('ComboBox','PID ON'),
            20:QApplication.translate('ComboBox','PID OFF'),
            21:QApplication.translate('ComboBox','SV'),
            22:QApplication.translate('ComboBox','Playback ON'),
            23:QApplication.translate('ComboBox','Playback OFF'),
            24:QApplication.translate('ComboBox','Set Canvas Color'),
            25:QApplication.translate('ComboBox','Reset Canvas Color'),
            26:QApplication.translate('Combobox','Airwave'),
            27:QApplication.translate('Combobox','TilauScope Ambient'),
            28:QApplication.translate('Combobox','TilauScope kernel'),
        }
        self.CAT_COLORS = {
            "PID": QColor("#448AFF"), "AIR": QColor("#69F0AE"),
            "DRUM": QColor("#00BFA5"), "BURNER": QColor("#FFD740"),
            "EXTERNAL": QColor("#FF5252"), "DEFAULT": QColor("#CFD8DC"),
        }
        self.ALARM_CONDS = ['<', '>', '=', '\u2260']
        self._load_alarms(data)
        self.setMouseTracking(True)
        # Enable native gesture (pinch) on macOS
        self.grabGesture(Qt.GestureType.PinchGesture)

    # ── Zoom helpers ──────────────────────────────────────────────────────────

    @property
    def event_positions(self) -> dict[int, int]:
        """Scaled event X positions for current zoom level."""
        z = self._zoom_factor
        return {code: int(x * z) for code, x in self._BASE_EVENT_X.items()}

    def sizeHint(self) -> QSize:
        z = self._zoom_factor
        n = len(self.alarm_objects) if self.alarm_objects else 1
        w = int(max(self._BASE_EVENT_X[7], max(self._BASE_EVENT_X.values())) * z) + 300
        h = int(max(self._BASE_MIN_H, n * self._BASE_SLOT_H + 200) * z)
        return QSize(w, h)

    def apply_zoom_step(self, delta: float) -> None:
        """Adjust zoom by delta, clamp, preserve viewport centre."""
        new_z = round(max(self._ZOOM_MIN, min(self._ZOOM_MAX, self._zoom_factor + delta)), 2)
        if new_z == self._zoom_factor:
            return
        self._apply_zoom(new_z)

    def _apply_zoom(self, new_z: float) -> None:
        """Apply new zoom factor, keep scroll centred on viewport centre."""
        scroll = self._scroll_area()
        if scroll is None:
            self._zoom_factor = new_z
            self._after_zoom()
            return

        h_bar = scroll.horizontalScrollBar()
        v_bar = scroll.verticalScrollBar()
        # Fractional position of centre in the current content
        old_z = self._zoom_factor
        vp = scroll.viewport()
        cx_frac = (h_bar.value() + vp.width()  / 2) / max(1, self.width())
        cy_frac = (v_bar.value() + vp.height() / 2) / max(1, self.height())

        self._zoom_factor = new_z
        self._after_zoom()

        # Restore centre
        hint = self.sizeHint()
        h_bar.setValue(int(cx_frac * hint.width()  - vp.width()  / 2))
        v_bar.setValue(int(cy_frac * hint.height() - vp.height() / 2))

    def _after_zoom(self) -> None:
        hint = self.sizeHint()
        self.setMinimumSize(hint)
        self.resize(hint)
        self._resolve_collisions()
        self.update()
        self.zoom_changed.emit(self._zoom_factor)

    def _scroll_area(self):
        from PyQt6.QtWidgets import QScrollArea as _SA  # noqa: PLC0415
        p = self.parent
        while p is not None:
            if isinstance(p, _SA):
                return p
            p = p.parent() if callable(getattr(p, 'parent', None)) else None
        return None

    # ── Input events ──────────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = self._ZOOM_STEP if event.angleDelta().y() > 0 else -self._ZOOM_STEP
            self._apply_zoom(round(max(self._ZOOM_MIN, min(self._ZOOM_MAX,
                                       self._zoom_factor + delta)), 2))
            event.accept()
        else:
            event.ignore()

    def event(self, e) -> bool:  # type: ignore[override]
        """Handle native pinch gesture (macOS trackpad)."""
        from PyQt6.QtCore import QEvent  # noqa: PLC0415
        if e.type() == QEvent.Type.Gesture:
            from PyQt6.QtWidgets import QGestureEvent  # noqa: PLC0415
            ge = e  # type: ignore[assignment]
            pinch = ge.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                from PyQt6.QtWidgets import QPinchGesture  # noqa: PLC0415
                sf = pinch.scaleFactor()  # type: ignore[attr-defined]
                new_z = round(max(self._ZOOM_MIN, min(self._ZOOM_MAX,
                                   self._zoom_factor * sf)), 2)
                self._apply_zoom(new_z)
                return True
        return super().event(e)

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
                self.alarm_objects.append(AlarmItem(alarm_raw, self.CAT_COLORS[cat]))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if we clicked an annotation box (check top-most first)
            for alarm in reversed(self.alarm_objects):
                if alarm.rect.contains(event.position()):
                    self.dragging_alarm = alarm
                    self.drag_offset = alarm.visual_pos - event.position()
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    break

    def mouseMoveEvent(self, event):
        pos = event.position()
        self.active_tick = None
        
        # 1. Update Hover State
        for alarm in reversed(self.alarm_objects):
            if alarm.rect.contains(pos):
                self.active_tick = alarm
                break
        
        # 2. Handle Dragging
        if self.dragging_alarm:
            self.dragging_alarm.visual_pos = pos + self.drag_offset
        
        self.update()

    def mouseReleaseEvent(self, event):
        self.dragging_alarm = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#121212"))
            baseline_y = self.height() // 2
            z = self._zoom_factor
            ev_pos = self.event_positions  # scaled dict

            # Scaled font
            base_pt = max(6, int(9 * z))
            scaled_font = QFont(self.font())
            scaled_font.setPointSize(base_pt)
            painter.setFont(scaled_font)
            metrics = QFontMetrics(scaled_font)

            # 1. Timeline & Milestones
            painter.setPen(QPen(QColor("#444444"), 2))
            painter.drawLine(0, baseline_y, self.width(), baseline_y)

            for code, x in ev_pos.items():
                if code == 10:
                    continue  # IF ALARM has no milestone column
                painter.setPen(QPen(QColor("#2A2A2A"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(x, 50, x, self.height() - 50)
                painter.setPen(QColor("#777777"))
                painter.drawText(x + 5, baseline_y - 10, self.EVENT_NAMES.get(code, ""))

            # 2. Draw Alarms
            card_w = int(170 * z)
            for alarm in self.alarm_objects:
                is_active = (alarm == self.active_tick or alarm == self.dragging_alarm)

                if alarm.data.event_code == 10:
                    parent = alarm
                    visited = set()
                    while (parent.data.previous_alarm > 0 or parent.data.not_alarm > 0) \
                            and id(parent) not in visited:
                        visited.add(id(parent))
                        nxt = next(
                            (a for a in self.alarm_objects
                             if a.data.index == parent.data.previous_alarm
                             or a.data.index == parent.data.not_alarm),
                            None)
                        if nxt is None:
                            break
                        parent = nxt
                    x_anchor = ev_pos.get(parent.data.event_code, 0) + int(alarm.data.offset * 2 * z)
                else:
                    x_anchor = ev_pos.get(alarm.data.event_code, 0) + int(alarm.data.offset * 2 * z)

                anchor_point = QPointF(x_anchor, baseline_y)

                # --- CONNECTOR LINE ---
                painter.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                path.moveTo(anchor_point)
                ctrl_y = (anchor_point.y() + alarm.visual_pos.y()) / 2
                path.cubicTo(QPointF(x_anchor, ctrl_y), QPointF(alarm.visual_pos.x(), ctrl_y), alarm.visual_pos)

                line_color = alarm.color.lighter(150) if is_active else alarm.color
                painter.setPen(QPen(line_color, 2 if is_active else 1.2))
                painter.drawPath(path)

                # --- FLOATING TIME MARKER ---
                if is_active and alarm.data.offset != 0:
                    time_str = f" +{alarm.data.offset}s "
                    tw = metrics.horizontalAdvance(time_str)
                    th = int(20 * z)
                    tick_rect = QRectF(x_anchor - tw / 2, baseline_y - int(30 * z), tw, th)
                    painter.setBrush(QColor("#1B1B1B"))
                    painter.setPen(QPen(line_color, 1))
                    painter.drawRoundedRect(tick_rect, 3, 3)
                    painter.setPen(Qt.GlobalColor.white)
                    bold_font = QFont(scaled_font)
                    bold_font.setBold(True)
                    painter.setFont(bold_font)
                    painter.drawText(tick_rect, Qt.AlignmentFlag.AlignCenter, time_str)
                    painter.setFont(scaled_font)

                # Card text
                if alarm.data.event_code == 10:
                    if alarm.data.previous_alarm > 0:
                        header = (f"#{alarm.data.index+1} | "
                                  + QApplication.translate("tilauscope_alarms", "IF ALARM")
                                  + f" #{alarm.data.previous_alarm}, "
                                  + QApplication.translate("tilauscope_alarms", "at")
                                  + f" +{alarm.data.offset}s "
                                  + QApplication.translate("tilauscope_alarms", "do"))
                    elif alarm.data.not_alarm > 0:
                        header = (f"#{alarm.data.index+1} | "
                                  + QApplication.translate("tilauscope_alarms", "IF NOT ALARM")
                                  + f" #{alarm.data.not_alarm}, "
                                  + QApplication.translate("tilauscope_alarms", "at")
                                  + f" +{alarm.data.offset}s "
                                  + QApplication.translate("tilauscope_alarms", "do"))
                else:
                    header = f"#{alarm.data.index+1} | {self.EVENT_NAMES.get(alarm.data.event_code, 'ALARM')} +{alarm.data.offset}s"

                if alarm.data.action == 25 or (8 <= alarm.data.action <= 25):
                    body = f"{self.ACTION_LIST.get(alarm.data.action, 'Action')}"
                    body += f" ({alarm.data.msg})\n" if alarm.data.msg else ""
                else:
                    body = f"{self.ACTION_LIST.get(alarm.data.action, 'Action')}={alarm.data.msg}"
                if alarm.data.alarm_source != -3:
                    if alarm.data.alarm_source + 3 < len(self.alarm_source_list):
                        source_txt = self.alarm_source_list[alarm.data.alarm_source + 3]
                    else:
                        source_txt = self.alarm_source_list[3]
                    body += f"\nIF {source_txt} {self.ALARM_CONDS[alarm.data.alarm_cond]} {alarm.data.alarm_temperature}"
                full_text = f"{header}\n{body}"

                text_rect = metrics.boundingRect(
                    QRect(0, 0, card_w - 20, 500),
                    Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                    full_text)
                rect_h = text_rect.height() + int(20 * z)
                alarm.rect = QRectF(
                    alarm.visual_pos.x() - card_w / 2,
                    alarm.visual_pos.y() - rect_h / 2,
                    card_w, rect_h)

                bg_color = alarm.color.lighter(140) if is_active else alarm.color
                painter.setBrush(QBrush(bg_color))
                painter.setPen(QPen(alarm.color.lighter(200), 2) if is_active else Qt.PenStyle.NoPen)
                painter.drawRoundedRect(alarm.rect, 5, 5)

                painter.setPen(Qt.GlobalColor.black)
                painter.drawText(
                    alarm.rect.adjusted(int(10 * z), int(5 * z), -int(10 * z), -int(5 * z)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                    full_text)
                
    def _resolve_collisions(self):
        baseline_y = self.sizeHint().height() // 2
        ev_pos = self.event_positions  # scaled by zoom
        z = self._zoom_factor
        slot_h = int(self._BASE_SLOT_H * z)
        box_w  = int(175 * z)
        occupied_slots: dict[int, list[tuple[int, int]]] = {}

        # Sort to process parent alarms before their IF-ALARM children
        sorted_alarms = sorted(self.alarm_objects, key=lambda a: a.data.index)

        for alarm in sorted_alarms:
            if alarm.data.event_code == 10:
                parent = alarm
                visited = set()
                while (parent.data.previous_alarm > 0 or parent.data.not_alarm > 0) \
                        and id(parent) not in visited:
                    visited.add(id(parent))
                    nxt = next(
                        (a for a in self.alarm_objects
                         if a.data.index == parent.data.previous_alarm
                         or a.data.index == parent.data.not_alarm),
                        None)
                    if nxt is None:
                        break
                    parent = nxt
                x_anchor = ev_pos.get(parent.data.event_code, 0) + int(alarm.data.offset * 2 * z)
            else:
                x_anchor = ev_pos.get(alarm.data.event_code, 0) + int(alarm.data.offset * 2 * z)

            _, y_offset = self._get_info(alarm.data.action)
            y_offset_scaled = int(y_offset * z)
            y_pos = baseline_y + y_offset_scaled

            if y_pos not in occupied_slots:
                occupied_slots[y_pos] = []

            current_x = x_anchor
            collision = True
            while collision:
                collision = False
                for start, end in occupied_slots[y_pos]:
                    if not (current_x + box_w / 2 < start or current_x - box_w / 2 > end):
                        current_x += int(30 * z)
                        collision = True
                        break

            occupied_slots[y_pos].append((current_x - box_w // 2, current_x + box_w // 2))
            alarm.visual_pos = QPointF(current_x, y_pos)

    def showEvent(self, event):
        hint = self.sizeHint()
        self.setMinimumSize(hint)
        self.resize(hint)
        self._resolve_collisions()
        self.update()

    def leaveEvent(self, event):
        self.hover_pos = QPointF(-1, -1)
        self.active_tick = None
        self.update()

class RoastNarrativeDialog(QDialog):
    def __init__(self, narrative_text: str, parent:AlarmTimelineWidget|None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        self.setWindowTitle(QApplication.translate("tilauscope_alarms","Roast Profile Narrative").upper())
        
        # 1. Augmenter la taille par défaut pour les longs rapports
        self.resize(700, 800) 
        self.setMinimumSize(500, 500)
          
        # Style pour le texte (Markdown)
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setMarkdown(narrative_text)
        
        # 2. Appliquer le style Catppuccin au QTextEdit
        self.text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME['SURFACE']};
                color: {THEME['TEXT']};
                border: 1px solid {THEME['BORDER']};
                border-radius: 8px;
                padding: 15px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
                line-height: 1.5;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {THEME['BG']};
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['ACCENT']};
                min-height: 20px;
                border-radius: 5px;
            }}
        """)
        
        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{ 
                background-color: {THEME['BG']}; 
                border: 1px solid {THEME['BORDER']}; 
                border-radius: 20px; 
            }}
        """)
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.addWidget(self.container)

         # Header
        header = QHBoxLayout()
        title_lbl = QLabel(QApplication.translate("tilauscope_alarms","Generated Roast Strategy:").upper())
        title_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; font-size: 15px; font-weight: 900; "
            f"border: none; font-family: 'JetBrains Mono'; letter-spacing: 2px;"
        )
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(self.fade_out_and_close)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['SURFACE']}; color: {THEME['TEXT']};
                border-radius: 15px; border: 1px solid {THEME['BORDER']};
            }}
            QPushButton:hover {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """)
        header.addWidget(title_lbl); header.addStretch(); header.addWidget(self.close_btn)
        self.content_layout.addLayout(header)
        self.content_layout.addWidget(self.text_area)

    def mousePressEvent(self, event): 
        self.oldPos = event.globalPosition().toPoint()
        
    def mouseMoveEvent(self, event):
        delta = QPoint(event.globalPosition().toPoint() - self.oldPos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = event.globalPosition().toPoint()

    def fade_out_and_close(self):
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0); self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.close)
        self.anim.start()
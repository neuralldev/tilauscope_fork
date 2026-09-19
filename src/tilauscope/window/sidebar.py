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

"""The collapsible live-events sidebar and the badges that fill it.

Alarms and event-button presses land here as cards that fade in, behind a
grip tab the operator can pull out from the right edge of the window.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from tilauscope.artisan_message_ticker import ArtisanMessageTicker
from tilauscope.theme_qss import with_tooltip
from tilauscope.tilauscope_types import THEME
from tilauscope.visualalarm import AlarmData
from tilauscope.widgets.badges import EventFiredBadge


if TYPE_CHECKING:
    # Annotation only — importing artisanlib.main at runtime executes a
    # settings migration against the real preferences and drags the whole
    # application into any process that only wanted this widget.
    from artisanlib.canvas import tgraphcanvas
    from artisanlib.main import ApplicationWindow

_log: Final[logging.Logger] = logging.getLogger(__name__)


def live_event_timestamp(qmc: tgraphcanvas) -> str:
    """Stamp used by every card in the LIVE EVENTS column.

    Roast time since CHARGE once the batch is on, wall clock otherwise. The
    leading '+' is the only thing telling the two apart on a 200 px card, so
    both card kinds have to go through here rather than format their own.
    """
    try:
        if qmc.flagon and qmc.timeindex[0] > -1:
            elapsed = qmc.timeclock.elapsed() / 1000.0 - qmc.timex[qmc.timeindex[0]]
            return f"+{int(elapsed) // 60}:{int(elapsed) % 60:02d}"
    except Exception:  # pylint: disable=broad-except - a card without a stamp beats no card
        pass
    return datetime.now().strftime("%H:%M:%S")


SIDEBAR_W   = 220   # px — must match AlarmSidebar content needs


GRIP_W      = 16    # px — always-visible strip


# Catppuccin Mocha palette references
_COL_SURFACE0  = THEME['BORDER']


_COL_LAVENDER  = THEME['LAVENDER']


_COL_TEXT      = THEME['TEXT']


_COL_BASE      = THEME['BG']


class TriggeredAlarmBadge(QFrame):

    # Static mappings — built once at class definition, shared across all instances
    EVENT_NAMES: dict[int, str] = {
        9: "ON", -1: "START", 0: "CHARGE", 8: "TP", 1: "DRY END",
        2: "FC START", 3: "FC END", 4: "SC START", 5: "SC END", 6: "DROP",
        7: "COOL END", 10: "IF ALARM",
    }
    ALARM_CONDS: list[str] = ['<', '>', '=', '\u2260']

    def __init__(self, alarm_data: AlarmData, aw: ApplicationWindow, action_list: dict,
                 timestamp: str = '', parent=None):
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
        # Artisan assigns source IDs per device, interleaving its two channels:
        # device 1 T1, device 1 T2, device 2 T1, device 2 T2, ... .  Building
        # all T1 names before all T2 names shifts every label from the second
        # source onward as soon as more than one extra device is configured.
        extra_label = QApplication.translate('Label', 'Extra')
        for i in range(len(aw.qmc.extradevices)):
            name_t1 = aw.qmc.device_name_subst(aw.qmc.extraname1[i])
            name_t2 = aw.qmc.device_name_subst(aw.qmc.extraname2[i])
            self.alarm_source_list.append(f"{name_t1} ({extra_label} {i + 1}T1)")
            self.alarm_source_list.append(f"{name_t2} ({extra_label} {i + 1}T2)")

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

        # Header: ID et Source, horodatage à droite comme sur la carte EVT
        header = QLabel(QApplication.translate("Label","Alarm")+f" #{self.data.index + 1}")
        header.setStyleSheet(f"color: {self.color}; font-weight: 900; font-size: 9px; border: none;")
        header_row = QHBoxLayout()
        header_row.addWidget(header)
        header_row.addStretch(1)
        ts_lbl = QLabel(timestamp)
        ts_lbl.setStyleSheet(f"color: {THEME['SURFACE2']}; font-size: 9px; border: none;")
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(ts_lbl)

        # Message / Action
        msg = QLabel(self.define_text(alarm_data))
        msg.setStyleSheet("color: white; font-weight: normal; font-size: 9px; border: none;")
        msg.setWordWrap(True)

        layout.addLayout(header_row)
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
            # Alarm guards are stored as zero-based indices; -1 means that no
            # guard is configured.  Therefore alarm #1 is represented by 0 and
            # must not be rejected by a ``> 0`` check.
            if alarm.previous_alarm >= 0:
                condition = QApplication.translate("tilauscope_window", "IF ALARM")
                referenced_alarm = alarm.previous_alarm
            elif alarm.not_alarm >= 0:
                condition = QApplication.translate("tilauscope_window", "IF NOT ALARM")
                referenced_alarm = alarm.not_alarm
            else:
                # Defensive fallback for an invalid/incomplete IF ALARM entry:
                # keep the live-events sidebar operational instead of using an
                # uninitialised ``header`` variable.
                condition = QApplication.translate("tilauscope_window", "IF ALARM")
                referenced_alarm = None

            reference = f" #{referenced_alarm + 1}," if referenced_alarm is not None else ""
            header = (
                f"#{alarm.index + 1} | {condition}{reference} "
                f"{QApplication.translate('tilauscope_window', 'at')} +{alarm.offset}s "
                f"{QApplication.translate('tilauscope_window', 'do')}"
            )
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
        lbl.setStyleSheet(f"color: {THEME['ACCENT']}; font-weight: bold; ")
        title_row.addWidget(lbl, 1)

        # Compteur de cartes
        self._count_lbl = QLabel("0")
        self._count_lbl.setStyleSheet(
            f"color: {THEME['ACCENT']}; background: {THEME['BORDER']}; font-size: 9px; font-weight: 700;"
            "border-radius: 8px; padding: 1px 6px; font-family: 'JetBrains Mono';"
        )
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setFixedHeight(16)
        title_row.addWidget(self._count_lbl)

        # Bouton clear
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(18, 18)
        clear_btn.setProperty('variant', 'icon')   # fixed square: no base padding
        clear_btn.setToolTip(QApplication.translate("tilauscope_window", "Clear all events"))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(with_tooltip(f"""
            QPushButton {{
                background: {THEME['BORDER']}; color: {THEME['OVERLAY0']};
                border-radius: 4px; border: none;
                font-size: 9px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['SURFACE1']}; color: {THEME['CRITICAL']}; }}
            QPushButton:pressed {{ background: {THEME['CRITICAL']}; color: {THEME['BG']}; }}
        """))
        clear_btn.clicked.connect(self.clear)
        title_row.addWidget(clear_btn)

        self.layout.addLayout(title_row)

        # Zone scrollable pour les badges
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {THEME['BG']}; width: 6px; margin: 0;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['SURFACE1']}; min-height: 20px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {THEME['SURFACE2']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._badges_widget = QWidget()
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

    def get_alarm_info(self, alarm_index:int) -> AlarmData | None:
        """Build the fired alarm's description from qmc, at fire time.

        Never from a snapshot: the alarm editor rewrites the whole qmc.alarm*
        set on save, so every index shifts as soon as one alarm is added or
        removed. A copy taken when this window opened described the wrong
        alarm — or no alarm at all, and the card silently never appeared.
        """
        qmc = self.aw.qmc
        if not 0 <= alarm_index < len(qmc.alarmtime):
            return None
        return AlarmData(
            index=alarm_index,
            event_code=qmc.alarmtime[alarm_index],
            offset=qmc.alarmoffset[alarm_index],
            action=qmc.alarmaction[alarm_index],
            msg=qmc.alarmstrings[alarm_index],
            previous_alarm=qmc.alarmguard[alarm_index],
            not_alarm=qmc.alarmnegguard[alarm_index],
            alarm_source=qmc.alarmsource[alarm_index],
            alarm_cond=qmc.alarmcond[alarm_index],
            alarm_temperature=qmc.alarmtemperature[alarm_index],
            is_active=True,
        )

    def _update_count(self) -> None:
        """Met à jour le label compteur."""
        n = len(self.badges)
        self._count_lbl.setText(str(n))
        self._count_lbl.setVisible(n > 0)

    def clear(self) -> None:
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
        badge = TriggeredAlarmBadge(alarm_data, self.aw, self._action_list,
                                    live_event_timestamp(self.aw.qmc))
        self._badges_layout.insertWidget(0, badge)
        self.badges.insert(0, badge)
        self._trim_badges()

    def add_event_badge(self, label: str, command: str, timestamp: str, color: str,
                        recorded: bool = True) -> None:
        """Ajoute une carte EVT (bouton event panel) dans la sidebar."""
        badge = EventFiredBadge(label, command, timestamp, color, recorded)
        self._badges_layout.insertWidget(0, badge)
        self.badges.insert(0, badge)
        self._trim_badges()


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

        # Alarm sidebar (AlarmSidebar is defined in displayscope.py above this class)
        self.alarm_sidebar = AlarmSidebar(aw, self)   # noqa: F821
        # AlarmSidebar sets setFixedWidth(200) internally; override with setSizePolicy so it doesn't fight our fixed width.
        self.alarm_sidebar.setMinimumWidth(0)
        self.alarm_sidebar.setMaximumWidth(SIDEBAR_W)
        self.alarm_sidebar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

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

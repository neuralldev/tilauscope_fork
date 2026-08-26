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

"""Putting the window together, and nothing else.

State is declared first, whole; then the six sections are built in order;
then what needs the widgets to exist is wired up. Declarations used to sit
on both sides of the build, and which side one landed on decided whether
its default won or lost. There is no side to get wrong here.
"""

from __future__ import annotations

import logging
from typing import Final

from PyQt6.QtCore import QPoint, QSettings, QSize, QTimer, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from artisanlib.util import fromCtoFstrict
from tilauscope.artisan_message_ticker import ArtisanMessageHook
from tilauscope.axes_config import AxesConfigHook
from tilauscope.canvas_style import CanvasStyleHook
from tilauscope.graph.curve import RoastCurveWidget
from tilauscope.header_icons import (
    BTN_ICON_SIZE,
    COL_ASSISTANT_IDLE,
    COL_BEANCAVE_IDLE,
    COL_DOCK_IDLE,
    COL_ESTOP,
    COL_MENU,
    COL_ON_LIGHT_FILL,
    COL_POWER_IDLE,
    COL_RESET_IDLE,
    COL_SWAP_IDLE,
    QSS_ASSISTANT,
    QSS_COMPACT_BEANCAVE,
    QSS_COMPACT_ESTOP,
    QSS_COMPACT_POWER,
    QSS_COMPACT_RESET,
    QSS_COMPACT_START,
    QSS_COMPACT_SWAP,
    QSS_DOCK,
    QSS_MENU,
    SVG_ASSISTANT,
    SVG_BEANCAVE,
    SVG_DOCK,
    SVG_HEATCUT,
    SVG_MENU,
    SVG_PLAY,
    SVG_POWER,
    SVG_RESET,
    SVG_SWAP,
    apply_icon,
)
from tilauscope.roast_review_panel import RoastReviewPanel
from tilauscope.theme_qss import apply_tilau_theme, tooltip_qss
from tilauscope.tilauscope_types import THEME, _IS_MACOS
from tilauscope.whats_new import maybe_show_whats_new
from tilauscope.widgets.controls import ClickableValue, HoldToFireButton
from tilauscope.widgets.labels import ClickableLabel, TickerLabel
from tilauscope.widgets.phase import PhaseWidget
from tilauscope.window.parts import (
    ButtonManager,
    EventPanel,
    ExtraCountersPanel,
    SegmentedControlSlider,
    TilauscopePanel,
    TilauscopeSlider,
)
from tilauscope.window.sidebar import CollapsibleLiveEvents
from tilauscope.window.layout import PARENT_TILAUSTYLE, _HDR2_BEANCAVE, _HDR2_DRAG_W, _HDR2_ESTOP, _HDR2_GAP, _HDR2_LEVEL, _HDR2_MARGINS, _HDR2_MENU, _HDR2_POWER, _HDR2_RESET, _HDR2_START, _HDR2_SWAP, _SLIDER_ROW_MARGINS, _SV_ROW_GAP_CORRECTION_PX, _TIMER_FONT_PX, _USE_SEGMENTED_SLIDER


_log: Final[logging.Logger] = logging.getLogger(__name__)


def _mono_font_family() -> str:
    """Return the bundled JetBrains Mono family name.

    Delegates to theme_qss, the single place that registers both faces.
    """
    from tilauscope.theme_qss import mono_family  # noqa: PLC0415
    return mono_family()


class BuildMixin:
    """Construction of the roasting window: state, then widgets, then wiring.

    A plain mixin, deliberately not a QWidget subclass. Qt registers the slots
    a class declares in that class's own metaobject, and a window built from
    several QWidget-derived bases only ever gets the first one's — so a
    @pyqtSlot living in any later slice became unconnectable, with Qt reporting
    a slot that takes no arguments at all. Inheriting nothing keeps every slot
    on the window itself.
    """

    def _declare_state(self) -> None:
        """Every attribute this window owns, set to its resting value.

        One block, and it runs before anything is built. That order is the
        point: init_ui() reads this state and writes some of it back, so while
        declarations sat on both sides of the build, whether a default won or
        lost depended on which side of the call it had been written on. Four
        comments in the constructor used to say so, one per attribute that had
        been caught by it. Nothing is declared after the build any more, so
        there is no side to get wrong.
        """
        # list of objects in artisan that are hidden/shown to enter tilauscope mode
        self.show_controls:list[int] = []
        self.show_lcds:list[int] = []
        self.show_minieventline:list[int] = []
        self.show_extrabuttons:list[int] = []
        self.show_sliders:list[int] = []

        # Initialisation cruciale pour éviter le Traceback
        self.is_roasting = self.artisan_conf.aw.qmc.flagstart
        self.start_time = None  # <--- On commence à None

        self.last_update_second = -1
        self._last_extra_update = 0.0   # throttle horodaté du panneau extra (≤ 1 Hz)

        self.root_menu:QMenu|None = None
        self.init = True
        # re-entrancy guard: True while mirroring Artisan slider values
        # into our sliders, so their valueChanged does not push back to Artisan.
        self._syncing_from_artisan = False
        # one debounce timer per slider index (see handle_ui_input_released)
        self._slider_commit_timers: dict[int, QTimer] = {}
        # SV row widgets + lock state (read-only while TilauPID preheats)
        self._sv_widgets: tuple = ()
        self._sv_locked: bool = False

        # Main store, namespaced key; migration from the legacy Artisan-named file
        # is handled by settings_migration.
        self.is_swapped = QSettings().value("interface/swap_events_control", False, type=bool) # shall we swap content?

        # Declared before the UI is built, never after: init_ui() runs from here
        # and assigns it, so a default written below this call would overwrite
        # the widget with None and silence every tick without a word.
        self.curve: RoastCurveWidget | None = None
        # Same rule: init_ui() reads the emergency latch when it decides whether
        # the heat cut is visible.
        self._emergency_latched: bool = False
        # Probe silence: a device can be configured, opened and still return
        # nothing at all (cable out). Counted per sample, painted at the two
        # transitions only.
        self._no_reading_samples: int = 0
        self._no_reading_shown: bool = False
        self._saved_face: tuple | None = None
        # Opening on an already-running Artisan session is a first-show concern,
        # not a construction concern.  The one-shot flag also prevents a return
        # from BeanCave from rebuilding phase state a second time.
        self._live_state_adoption_queued: bool = False
        # Same rule once more: init_ui() ends on _refresh_replay_button(), and
        # the header button reads both of these. Declared after the build, the
        # first refresh died on an AttributeError.
        self.replay_enabled: bool = False
        self.replay_reaction_time_s: float = 10.0
        # static strings — same rule again: init_ui() ends on update_status_text(),
        # which reads str_roastsession. Declared after the build, that first call
        # died on an AttributeError swallowed by its own guard, leaving MONITOR and
        # START unstyled whenever the window opened on a live session.
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
        self.str_tilaupidinit = QApplication.translate("tilauscope_window", "TilauPID is initializing, please wait...")

        # _update_automation_banner() runs once/sec from the TIMER path — these
        # must be pre-translated here, never re-translated inside the 1Hz tick.
        self.str_automation_pid           = QApplication.translate("tilauscope_window", "PID")
        self.str_automation_replay_events = QApplication.translate("tilauscope_window", "Replay Events")
        self.str_automation_auto_drop     = QApplication.translate("tilauscope_window", "Auto-DROP")
        self.str_automation_playback_aid  = QApplication.translate("tilauscope_window", "Playback Aid")
        self.str_automation_prefix        = QApplication.translate("tilauscope_window", "⚠ AUTOMATED ROAST")

        # Probe silence — pre-translated, never re-translated in the sample path
        self.str_no_reading_title = QApplication.translate(
            "tilauscope_window", "⚠ NO TEMPERATURE FROM THE MACHINE")
        self.str_no_reading_body = QApplication.translate(
            "tilauscope_window",
            "Check the roaster is switched on and its cable connected.\n"
            "Nothing can be measured or guided until a reading arrives.")

        self.str_no_reading_stopped = QApplication.translate(
            "tilauscope_window", "Recording has been stopped.")

        # Emergency heat cut — lever names double as the report of what was cut
        self.str_emergency_burner      = QApplication.translate("tilauscope_window", "burner off")
        self.str_emergency_air         = QApplication.translate("tilauscope_window", "airflow open")
        self.str_emergency_extraction  = QApplication.translate("tilauscope_window", "extraction full")
        self.str_emergency_status      = QApplication.translate("tilauscope_window", "⚠ HEAT CUT")
        self.str_emergency_nothing     = QApplication.translate("tilauscope_window", "no lever could be commanded")
        self.str_emergency_title       = QApplication.translate("tilauscope_window", "⚠️ HEAT CUT")
        self.str_emergency_empty_drum  = QApplication.translate("tilauscope_window", "Empty the drum into the cooling tray now")
        self.str_emergency_manual_burner = QApplication.translate("tilauscope_window", "Turn the burner off on the machine, then empty the drum")
        # The glyph carries no words, so the tip has to name the control, the
        # gesture and what it leaves the operator to do — not just the effect.
        self.str_emergency_tip = QApplication.translate(
            "tilauscope_window",
            "EMERGENCY HEAT CUT — hold one second.\n"
            "Stops everything driving the heat, sets the burner to zero and opens "
            "airflow and extraction.\n"
            "The drum keeps turning: empty it into the cooling tray yourself.")

        # Declared here rather than after the build, where they used to sit.
        # None of them is read while the widgets are going up; keeping them
        # with the rest is what makes the rule above checkable at a glance.
        self.p_state = True
        self._timer_state = "idle"
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

        self.is_pid_active:bool = False
        self.curr_bt:float = None

    def _wire_after_build(self, message: str) -> None:
        """Everything that needs the widgets to exist: geometry, effects, hooks.

        Actions only — no attribute here holds a resting value that anything
        reads during the build. New state belongs in _declare_state().
        """
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
        # Add Opacity Effect to the timer label (GPU accelerated)
        self.timer_opacity = QGraphicsOpacityEffect(self.timer_lbl)
        self.timer_lbl.setGraphicsEffect(self.timer_opacity)
        self.p_timer.start()

        QTimer.singleShot(500, self.focusOn)

        self.aw.tilauscopeMain.setChecked(True)

        # Shift+T view-toggle from within TilauScope. The act_main
        # QAction/shortcut lives on the Artisan window, which is hidden (and thus
        # receives no key events) in headless mode — so we register a window-local
        # shortcut here so Shift+T reaches tilauscopeCall() while TilauScope has
        # focus. Harmless in normal mode (Artisan stays visible on toggle).
        self._view_toggle_sc = QShortcut(QKeySequence("Shift+T"), self)
        self._view_toggle_sc.activated.connect(self.aw.tilauscopeCall)

        self.aw.pidcontrol.activateSVSlider(True)

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

        # ── Réglages menu Axes Artisan (fenêtre temps, grille, légende, delta…) ─
        # Appliqués une première fois ici, puis ré-appliqués à chaque chargement
        # de profil (.alog) via patch de aw.loadFile. Aucune modification de main.py.
        self._axes_hook = AxesConfigHook(self.aw)
        self._axes_hook.install()
        self._axes_hook.apply_now()

        # ── Typo du titre du roast sur le canvas Artisan (taille + JetBrains Mono) ─
        self._canvas_style_hook = CanvasStyleHook(self.aw)
        self._canvas_style_hook.install()
        self._canvas_style_hook.apply_now()

        # Masquer messagelabel si TilauScope s'ouvre pendant une torréfaction déjà active
        self.aw.messagelabel.setVisible(False)

        # What's New splash — shown once per build
        self.alarm_fired_signal.connect(self.handle_alarm_trigger)
        # Live data from qmc, decoupled via signal (slot is exception-guarded).
        self.aw.qmc.tilauUpdateSignal.connect(self.update_ui_from_artisan)
        # A background curve can be loaded/cleared from Artisan's own menu at
        # any time (not just through RoastSetupDialog) — keep the header
        # REPLAY button's eligibility in sync with that, not just at init.
        # Both slots are kept on the instance and dropped in closeEvent: aw
        # outlives this window, and a connection surviving the close keeps the
        # closed instance alive and still reacting on the next session's qmc.
        self._on_background_changed = lambda *_: self._refresh_replay_button()
        self.aw.loadBackgroundSignal.connect(self._on_background_changed)
        self.aw.clearBackgroundSignal.connect(self._on_background_changed)
        if message != "":
            QTimer.singleShot(500, lambda: self.showMessage(message))
        else:
            QTimer.singleShot(1200, lambda: maybe_show_whats_new(self, self))

    def init_ui(self):

        self.init = True
        self._main_layout = QVBoxLayout(self)
        bg_color = self.theme["BG"]
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self.setStyleSheet(f"""
                            {tooltip_qss()}
                        """)
        # Main Styled Frame
        self.container = QFrame()
        self.container.setStyleSheet(f"background-color: {bg_color}; border: 2px solid #2D2D35; border-radius: 8px;")

        # Horizontal Layout: Controls on Left, Graph on Right
        self._content_layout = QHBoxLayout(self.container)
        # Increase margins slightly so internal widgets don't "touch" the border
        self._content_layout.setContentsMargins(10,10,10,10)
        self._content_layout.setSpacing(10)

        # --- LEFT PANE: ROASTER CONTROLS ---
        self._left_widget = QWidget()
        self._left_pane = QVBoxLayout(self._left_widget)
        self._left_pane.setContentsMargins(10, 10, 10, 10)   # compaction scenario A
        self._left_pane.setSpacing(10) # Tightened spacing to ensure full display
        self._left_widget.setFixedWidth(390)   # compaction scenario B (was 440)
        # The base sheet goes on the left pane, not on the window:
        # this window reparents Artisan's own main_widget into itself
        # so a sheet on the root would cascade into the roast curve. self._left_widget
        # is the whole control side — header, controls, panel stack — and stops
        # where the curve begins. ground=False because the panel composes with
        # transparency. See wiki/Theme-QSS-Spec.md.
        apply_tilau_theme(self._left_widget, ground=False)

        # values for counters
        self.bt_label ="0.0"
        self.et_label ="0.0"
        self.deltabt_label="0"

        self.time_charge = 0.0
        self.time_dryend = 0.0
        self.time_fcs = 0.0

        self.prev_pidtext:str = ""


        self._build_header()
        self._build_readouts()
        self._build_phases()
        self._build_controls()
        self._build_events()
        self._build_panels()

        # ── Operator level init ──────────────────────────────────
        # Two levels only: Guided (default) and Expert. Legacy "standard" and
        # new installs both fall back to Guided.
        _saved_level = QSettings().value("tilauscope/operator_level")
        if _saved_level not in ("guided", "expert"):
            _saved_level = "guided"
            QSettings().setValue("tilauscope/operator_level", _saved_level)
        self._operator_level: str = _saved_level
        self._apply_operator_level(_saved_level, from_init=True)
        self._refresh_replay_button()

        self.init = False

    def _build_header(self) -> None:
        """Title bar: timer, milestone shortcuts, menu and the header buttons.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # 1. HEADER (Timer + Préchauffage)
        header = QHBoxLayout()
        header.setSpacing(_HDR2_GAP)
        # The primary row is width-bound: menu, monitoring, recording and timer
        # must fit the pane without placing the edge controls against its border.
        header.setContentsMargins(*_HDR2_MARGINS)
        # Group controls and status on the left
        left_header_group = QHBoxLayout()

        # Create and add the Artisan Menu Button
        self.btn_main_menu = QPushButton()
        self.btn_main_menu.setFixedSize(*_HDR2_MENU)
        self.btn_main_menu.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_main_menu.setIconSize(QSize(22, 22))
        self.btn_main_menu.setStyleSheet(QSS_MENU)
        apply_icon(self.btn_main_menu, SVG_MENU, COL_MENU)
        self.btn_main_menu.clicked.connect(self.open_main_menu)

        self.btn_power = QPushButton()
        self.btn_power.setFixedSize(*_HDR2_POWER)
        self.btn_power.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_power.setCheckable(True)
        self.btn_power.setIconSize(QSize(18, 18))
        self.btn_power.setText(QApplication.translate('Button', 'MONITOR'))
        self.btn_power.setToolTip(QApplication.translate('Tooltip', 'Start monitoring'))
        self.btn_power.setStyleSheet(QSS_COMPACT_POWER)
        apply_icon(self.btn_power, SVG_POWER, COL_POWER_IDLE)
        self.update_button_style(self.btn_power, True)
        self.btn_power.clicked.connect(self.toggle_power)

        self.btn_start_stop = QPushButton()
        self.btn_start_stop.setFixedSize(*_HDR2_START)
        self.btn_start_stop.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_start_stop.setCheckable(False)
        self.btn_start_stop.setIconSize(QSize(18, 18))
        self.btn_start_stop.setText(QApplication.translate('Button', 'START'))
        self.btn_start_stop.setToolTip(QApplication.translate('Tooltip', 'Start recording'))
        self.btn_start_stop.clicked.connect(self.toggle_start_stop)
        self.btn_start_stop.setStyleSheet(QSS_COMPACT_START)
        apply_icon(self.btn_start_stop, SVG_PLAY, COL_ON_LIGHT_FILL)
        self.update_button_style(self.btn_start_stop, False)

        self.btn_reset = QPushButton()
        self.btn_reset.setFixedSize(*_HDR2_RESET)
        self.btn_reset.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_reset.setCheckable(False)
        self.btn_reset.setIconSize(QSize(22, 22))
        self.btn_reset.setText(QApplication.translate('Button', 'RESET'))
        self.btn_reset.setToolTip(QApplication.translate('Tooltip', 'Reset'))
        self.btn_reset.clicked.connect(self.handle_reset)
        self.btn_reset.setStyleSheet(QSS_COMPACT_RESET)
        apply_icon(self.btn_reset, SVG_RESET, COL_RESET_IDLE)
        self.update_button_style(self.btn_reset, True)

        self.btn_beancave = QPushButton()
        self.btn_beancave.setFixedSize(*_HDR2_BEANCAVE)
        self.btn_beancave.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_beancave.setCheckable(True)
        self.btn_beancave.setIconSize(QSize(22, 22))
        self.btn_beancave.setText(QApplication.translate('Button', 'BEAN CAVE'))
        self.btn_beancave.setToolTip(QApplication.translate('tilauscope_window', 'Access to Bean Cave'))
        self.btn_beancave.clicked.connect(self.toggle_beancave)
        self.btn_beancave.setStyleSheet(QSS_COMPACT_BEANCAVE)
        apply_icon(self.btn_beancave, SVG_BEANCAVE, COL_BEANCAVE_IDLE)
        self.btn_beancave.setChecked(False)
        self.update_button_style(self.btn_beancave, True)

        self.btn_assistant = QPushButton()
        self.btn_assistant.setFixedSize(32, 30)
        self.btn_assistant.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_assistant.setCheckable(False)
        self.btn_assistant.setIconSize(BTN_ICON_SIZE)
        self.btn_assistant.setToolTip(QApplication.translate('tilauscope_window', 'Engage Roast Assistant'))
        self.btn_assistant.clicked.connect(self.toggle_roast_assistant)
        self.btn_assistant.setStyleSheet(QSS_ASSISTANT)
        apply_icon(self.btn_assistant, SVG_ASSISTANT, COL_ASSISTANT_IDLE)
        self.update_button_style(self.btn_assistant, False)

        # ── Float ↔ anchor toggle for the roast assistant ─────────
        self.btn_dock = QPushButton()
        self.btn_dock.setFixedSize(26, 30)
        self.btn_dock.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_dock.setCheckable(False)
        self.btn_dock.setToolTip(QApplication.translate(
            'tilauscope_window',
            'Anchor the assistant in place of the main panel (toggle floating)'))
        self.btn_dock.setStyleSheet(QSS_DOCK)
        apply_icon(self.btn_dock, SVG_DOCK, COL_DOCK_IDLE)
        self.btn_dock.clicked.connect(self.toggle_assistant_anchor)
        self.update_button_style(self.btn_dock, False)

        self.swap_button = QPushButton()
        self.swap_button.setFixedSize(*_HDR2_SWAP)
        self.swap_button.setProperty('variant', 'icon')   # fixed square: no base padding
        self.swap_button.setCheckable(False)
        self.swap_button.setIconSize(QSize(22, 22))
        self.swap_button.clicked.connect(lambda: self.toggle_panels(self._left_widget, self._content_layout, True))
        self.swap_button.setStyleSheet(QSS_COMPACT_SWAP)
        apply_icon(self.swap_button, SVG_SWAP, COL_SWAP_IDLE)
        self.update_button_style(self.swap_button, True)

        # ── Emergency heat cut ───────────────────────────────────────
        # Hold to fire: a stray click must not end a live roast, and a modal
        # confirmation is not allowed while one is running. Hidden until
        # something can actually be hot (see _refresh_emergency_visibility).
        self.btn_estop = HoldToFireButton("", 1000)
        self.btn_estop.setFixedSize(*_HDR2_ESTOP)
        self.btn_estop.setStyleSheet(QSS_COMPACT_ESTOP)
        apply_icon(self.btn_estop, SVG_HEATCUT, COL_ESTOP)
        self.btn_estop.setToolTip(self.str_emergency_tip)
        self.btn_estop.fired.connect(self.handle_emergency)
        self.btn_estop.hide()

        # ── Assemblage du header ─────────────────────────────────────────────
        left_header_group.addWidget(self.btn_main_menu)
        left_header_group.addWidget(self.btn_power)
        left_header_group.addWidget(self.btn_start_stop)
        # Assistant engage/anchor buttons: in Guided the assistant is anchored
        # by default and floated via the GREEN BEAN header control; in Expert
        # there is no assistant. Kept hidden so existing style/state references stay valid.
        self.btn_assistant.hide()
        self.btn_dock.hide()
        left_header_group.setSpacing(_HDR2_GAP)
        header.addLayout(left_header_group)

        # ── Operator level selector (single cycling button) ──────
        # One ~32px button in the icon row. Letter = level, colour = level.
        # One click cycles G→S→E→G. No popup (real-time friendly).
        _lvl_sep = QFrame()
        _lvl_sep.setFrameShape(QFrame.Shape.VLine)
        _lvl_sep.setFixedHeight(22)
        _lvl_sep.setStyleSheet(f"color: {THEME['BORDER']}; background: {THEME['BORDER']}; border: none; max-width: 1px;")
        self.btn_level = QPushButton()
        self.btn_level.setFixedSize(*_HDR2_LEVEL)
        self.btn_level.setProperty('variant', 'icon')   # fixed square: no base padding
        self.btn_level.clicked.connect(self._cycle_operator_level)

        # Roast Replay: visible at all times so it can be killed on the spot
        # (too much delta, emergency, ...) — but it can only ARM before CHARGE;
        # see _toggle_replay_button / _refresh_replay_button.
        self.btn_replay = QPushButton("↻")
        self.btn_replay.setFixedSize(*_HDR2_LEVEL)
        self.btn_replay.setProperty('variant', 'icon')
        self.btn_replay.setCheckable(True)
        self.btn_replay.clicked.connect(self._toggle_replay_button)

        secondary_header = QHBoxLayout()
        secondary_header.setContentsMargins(*_HDR2_MARGINS)
        secondary_header.setSpacing(_HDR2_GAP)
        secondary_header.addWidget(self.btn_reset)
        secondary_header.addWidget(self.btn_beancave)
        secondary_header.addWidget(_lvl_sep)
        secondary_header.addWidget(self.btn_level)
        secondary_header.addWidget(self.btn_replay)
        secondary_header.addWidget(self.swap_button)
        header_column = QVBoxLayout()
        header_column.setContentsMargins(0, 0, 0, 0)
        header_column.setSpacing(4)   # visual break between primary and secondary rows
        header_column.addLayout(header)
        header_column.addLayout(secondary_header)

        # Drag handle — zone de déplacement explicite, première ligne juste à
        # gauche du compteur. SizeAllCursor signale visuellement la zone.
        self.drag_handle = QLabel("⠿")  # braille pattern = grab icon léger
        self.drag_handle.setFixedSize(_HDR2_DRAG_W, _HDR2_START[1])
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drag_handle.setStyleSheet(f"""
            QLabel {{ color: {THEME['SURFACE1']}; font-size: 18px; border: none;
                     background: transparent; padding: 0 2px; }}   /* TILAU: header budget (was 0 8px, then 0 4px) */
            {tooltip_qss()}
        """)
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setToolTip(QApplication.translate("tilauscope_window", "Drag to move"))
        # Installer les événements souris sur le handle
        self.drag_handle.mousePressEvent   = self._handle_drag_press
        self.drag_handle.mouseMoveEvent    = self._handle_drag_move
        self.drag_handle.mouseReleaseEvent = self._handle_drag_release
        self.drag_handle.setSizePolicy(QSizePolicy.Policy.Fixed,
                                       QSizePolicy.Policy.Fixed)
        secondary_header.addStretch(1)
        # Far right of the secondary row, under the timer: reachable in
        # every panel mode (the header sits outside the panel stack).
        secondary_header.addWidget(self.btn_estop)

        # Adjust Timer Font Size
        self.timer_lbl = ClickableLabel("00:00")
        # Bundled JetBrains Mono (monospaced — every digit same width) so the
        # timer never reflows the header as the value changes.
        _mono = _mono_font_family()
        self.timer_lbl.setStyleSheet(f"font-size: {_TIMER_FONT_PX}px; font-weight: 700; color: {THEME['BORDER']}; font-family: '{_mono}', 'Menlo', monospace; border: none; background: transparent;")
        self.timer_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.timer_lbl.clicked.connect(self.timer_clicked)
        # Belt-and-suspenders: pin the box to the widest reading so the timer
        # zone never resizes regardless of the resolved font.
        _timer_font = QFont(_mono)
        _timer_font.setPixelSize(_TIMER_FONT_PX)   # compaction scenario B (was 28, then 24)
        # Measured at the heaviest weight any timer state uses (900), so a
        # fallback family that is not truly monospaced still fits the box.
        _timer_font.setWeight(QFont.Weight.Black)
        _fm = QFontMetrics(_timer_font)
        _timer_w = _fm.horizontalAdvance("-88:88") + 4
        # The timer is the row's only elastic item — it eats the leftover
        # pixels instead of a spacer, which would be charged the row gap
        # twice. Right-aligned, so the digits stay pinned to the edge.
        self.timer_lbl.setMinimumWidth(_timer_w)
        self.timer_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Preferred)

        # Keep the handle visually attached to the counter without charging a
        # second top-level layout gap to the already exact primary-row budget.
        counter_group = QHBoxLayout()
        counter_group.setContentsMargins(0, 0, 0, 0)
        counter_group.setSpacing(0)
        counter_group.addWidget(self.drag_handle)
        counter_group.addWidget(self.timer_lbl)
        header.addLayout(counter_group)
        self._left_pane.addLayout(header_column)

        # Status label — affiche l'état de la session (monitoring, recording, emergency)
        # Status label — TickerLabel : défile si le texte dépasse la largeur
        self.status_lbl = TickerLabel(height=18, color="#A6E3A1", font_size=9, font_weight=700)
        self._left_pane.addWidget(self.status_lbl, 0)
        self._left_pane.setStretchFactor(self.status_lbl, 1)

        # Automation banner — red text on amber, shown only while the
        # roast is driven by Artisan automations (PID from CHARGE, or any
        # background playback mode). Hidden the rest of the time.
        self.automation_lbl = QLabel("")
        self.automation_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.automation_lbl.setWordWrap(True)
        self.automation_lbl.setStyleSheet(
            "color: #B00710; background: #FAB387; border-radius: 6px;"
            " padding: 2px 8px; font-size: 11px; font-weight: 900;"
            f" border: 1px solid {THEME['CRITICAL']};"
        )
        self.automation_lbl.hide()
        self._automation_prev = None   # cache to avoid redundant setText/show
        self._left_pane.addWidget(self.automation_lbl, 0)

    def _build_readouts(self) -> None:
        """The BT / ET / rate-of-rise readouts.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # 2. METRICS
        self.et_val_label = QLabel("0.0")
        self.bt_val_label = QLabel("0.0")
        self.ror_val_label = QLabel("0.0")

        self.lcds = TilauscopePanel(self.artisan_conf)
        self._left_pane.addWidget(self.lcds)

        # ── Anchorable main-panel container ──────────────────────
        # Everything below the counters lives here, so the whole block can be
        # swapped for the anchored roast-assistant body via a QStackedWidget.
        self._main_controls = QWidget()
        self._main_controls.setStyleSheet("background: transparent; border: none;")
        self._mc_lay = QVBoxLayout(self._main_controls)
        self._mc_lay.setContentsMargins(0, 0, 0, 0)
        self._mc_lay.setSpacing(15)

    def _build_phases(self) -> None:
        """The three phase blocks and the message line that overlays them.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # 3. PHASES & OVERLAY MESSAGE
        self.phase_container = QFrame()
        self.phase_container.setMinimumHeight(110) # Force une zone de respiration compaction scenario A
        self.phase_container.setStyleSheet(f"background: {self.theme["BG"]}; border-radius: 10px; border: 1px solid {THEME['BORDER']}; margin-top: 10px;")
        self.phase_stack = QGridLayout(self.phase_container)

        self.msg_lbl = QLabel("") # Message Drop/Cool
        self.msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wraps inside the cell width (see below) instead of centring at its
        # full single-line size hint, which would run past both edges of the window.
        self.msg_lbl.setWordWrap(True)
        self.msg_lbl.setStyleSheet(f"color: {THEME['TEAL']}; font-size: 16px; font-weight: 800; border: none")
        self.msg_lbl.hide()

        self.phase_box = QHBoxLayout()
        self.phase_box.setContentsMargins(0, 0, 0, 0)
        self.phase_box.setSpacing(2) # Small gap between phase blocks

        self.phases = {
            "DRY": PhaseWidget("DRY", QApplication.translate("tilauscope_window","Drying Phase").upper(), THEME['ACCENT'], self.theme, self._update_phase_subtitle("DRY")),
            "MAI": PhaseWidget("MAI", QApplication.translate("tilauscope_window","Maillard Phase").upper(), THEME['YELLOW'], self.theme, self._update_phase_subtitle("MAI")),
            "DEV": PhaseWidget("DEV", QApplication.translate("tilauscope_window","Finishing Phase").upper(), THEME['CRITICAL'], self.theme, self._update_phase_subtitle("DEV"))}
        _PHASE_IDX = {"DRY": 1, "MAI": 2, "DEV": 3}
        for key, p in self.phases.items():
            self.phase_box.addWidget(p)
            p.setFocusPolicy(Qt.FocusPolicy.WheelFocus)  # macOS trackpad delivery
            p.installEventFilter(self)
            p._phase_key = key
            p._phase_idx = _PHASE_IDX[key]

        self.phase_stack.addLayout(self.phase_box, 0, 0)
        self.phase_stack.addWidget(self.msg_lbl, 0, 0)
        # no item alignment here: an aligned grid item keeps its size hint,
        # which for a one-line label is the full text width — that is what made long
        # messages overflow the panel. Filling the cell lets setWordWrap do its job;
        # the text stays centred through the label's own alignment.
        self._mc_lay.addWidget(self.phase_container,1)

    def _build_controls(self) -> None:
        """Machine controls: the five slider rows, their cards, and the swap bar.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # 4. PILOTAGE MACHINE
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

        self._slider_row_widgets: list[QWidget] = []  # per-slider row widgets (idx 0-3), for visibility mirror

        for i, (name, color, min_val, max_val, unit, step) in enumerate(slider_defs):
            row = QHBoxLayout()
            row.setContentsMargins(*_SLIDER_ROW_MARGINS)   # same inset for all 5 rows
            lbl = QLabel(name)
            lbl.setFixedWidth(55)
            lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 800; color: {THEME['SURFACE2']}; border: none;"
            )
            slider_class = SegmentedControlSlider if _USE_SEGMENTED_SLIDER else TilauscopeSlider
            sld = slider_class(accent_color=color)
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
            # drag release: no burst to coalesce → commit without delay
            sld.sliderReleased.connect(lambda n=i: self.handle_ui_input_released(n, immediate=True))
            # Nothing else is connected here to push the value outward: aw.slider1..4
            # are written by _commit_slider_value() through Artisan's own
            # moveslider()/recordsliderevent() transaction, on release rather than
            # on every intermediate value.

            btn_minus = QPushButton("-")
            btn_minus.setFixedSize(24, 24)
            btn_minus.setProperty('variant', 'icon')   # fixed square: no base padding
            btn_minus.setAutoRepeat(True)
            btn_minus.setAutoRepeatDelay(350)
            btn_minus.setAutoRepeatInterval(120)
            btn_minus.setStyleSheet(self._get_stepper_style(color))
            btn_minus.clicked.connect(lambda _, s=sld, n=i: [
                s.setValue(max(s.minimum(), s.value() - s.singleStep())),
                self.handle_ui_input_released(n),
            ])

            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(24, 24)
            btn_plus.setProperty('variant', 'icon')   # fixed square: no base padding
            btn_plus.setAutoRepeat(True)
            btn_plus.setAutoRepeatDelay(350)
            btn_plus.setAutoRepeatInterval(120)
            btn_plus.setStyleSheet(self._get_stepper_style(color))
            btn_plus.clicked.connect(lambda _, s=sld, n=i: [
                s.setValue(min(s.maximum(), s.value() + s.singleStep())),
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
                # to mirror Artisan's eventslidervisibilities.
                row_w = QWidget()
                row_w.setStyleSheet("border: none; background: transparent;")
                row_w.setLayout(row)
                # Fixed height so a hidden→shown cycle can't let the rows stretch
                # to fill the (taller) locked control zone.
                row_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                self._slider_row_widgets.append(row_w)
                slider_rows_layout.addWidget(row_w)
            else:
                # SV slider — always visible, not part of the toggle
                self._sv_row_widget = QWidget()
                sv_inner = QVBoxLayout(self._sv_row_widget)
                # SV uses the same row margins as the four controls above.
                sv_inner.setContentsMargins(0, 0, 0, 0)
                sv_inner.setSpacing(0)
                self._sv_row_widget.setObjectName("SVRow")
                self._sv_row_widget.setStyleSheet("#SVRow { border: none; background: transparent; }")
                # Same wrapper as the rows above: the row carries the explicit
                # _SLIDER_ROW_MARGINS either way, but keeping the construction identical
                # means the SV row can never drift out of line with them again.
                sv_row_w = QWidget()
                sv_row_w.setStyleSheet("border: none; background: transparent;")
                sv_row_w.setLayout(row)
                sv_inner.addWidget(sv_row_w)
                # kept for _apply_sv_lock (read-only while TilauPID preheats)
                self._sv_widgets = (sld, btn_minus, btn_plus, val_pct)

        # Trailing stretch: any spare height in the (card-sized) locked control
        # zone collects at the bottom, keeping the classic rows packed at top
        # instead of spreading out.
        slider_rows_layout.addStretch(1)

        if _IS_MACOS: # macOS
            # Force la suppression des bordures de focus natives Aqua
            self.slider_rows_widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            self._sv_row_widget.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        else: # Windows
            # Supprime le rectangle de focus pointillé typique de Windows
            self.slider_rows_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._sv_row_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)


        # Mirror Artisan's per-slider visibilities onto the rows
        self._apply_slider_visibility_mirror()

        # ── Assemble the control zone ─────────────────────────────────────────
        ctrl_zone = QHBoxLayout()
        ctrl_zone.setContentsMargins(0, 0, 0, 0)
        ctrl_zone.setSpacing(6)

        # A plain QWidget hosts the rows, so the zone can be given a fixed height
        self._ctrl_stack = QWidget()
        self._ctrl_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._ctrl_stack.setStyleSheet("border: none; background: transparent;")
        stack_layout = QVBoxLayout(self._ctrl_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)
        stack_layout.addWidget(self.slider_rows_widget)
        ctrl_zone.addWidget(self._ctrl_stack, 1)

        self._mc_lay.addLayout(ctrl_zone)
        # Freeze the control-zone height to the taller of the two views so the
        # sliders ↔ cards toggle never changes the window size. The phase
        # container has stretch=1 and would otherwise absorb the slack, growing
        # the window when switching back to sliders.
        QTimer.singleShot(0, self._lock_control_zone_height)

        # SV slider row — beneath the toggle zone, always shown
        self._mc_lay.addSpacing(_SV_ROW_GAP_CORRECTION_PX)
        self._mc_lay.addWidget(self._sv_row_widget)

    def _build_events(self) -> None:
        """Artisan's event buttons, and the stack that pages them with the assistant.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # 5. ÉVÉNEMENTS
        grid = QGridLayout()
        # Nested layouts inherit no margin, so the milestone buttons ran
        # into both edges of the panel. Same horizontal inset as the slider rows
        # so the two blocks line up, and tighter gaps to buy that inset back —
        # with 4 columns each button gains rather than loses width.
        grid.setContentsMargins(_SLIDER_ROW_MARGINS[0], 4, _SLIDER_ROW_MARGINS[2], 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.event_buttons:dict[str,QPushButton] = {}  # Dictionary to store button references
        self.events = [
            (QApplication.translate("Button","CHARGE"), "#A6E3A1"),
            (QApplication.translate("Button","DRY END"), THEME['ACCENT']),
            (QApplication.translate("Button","FC START"), "#FAB387"),
            (QApplication.translate("Button","FC END"), THEME['CRITICAL']),
            (QApplication.translate("Button","SC START"), THEME['CRITICAL']),
            (QApplication.translate("Button","SC END"), THEME['CRITICAL']),
            (QApplication.translate("Button","DROP"), THEME['CRITICAL']),
            (QApplication.translate("Button","COOL END"), THEME['TEAL'])]
        for i, (n, c) in enumerate(self.events):
            btn = QPushButton(n)
            btn.setFixedHeight(38)   # compaction scenario A
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
        self._mc_lay.addLayout(grid)

    def _build_panels(self) -> None:
        """The roast curve, the alarm sidebar and the floating panels.

        Built in the order init_ui() calls it: the sections of this window
        read each other's widgets, so the sequence is load-bearing.
        """
        # ── Panel stack: page 0 = manual controls, page 1 = anchored assistant
        # The hidden page is not painted, so anchoring adds no per-cycle CPU cost.
        self._panel_stack = QStackedWidget()
        self._panel_stack.addWidget(self._main_controls)            # index 0
        self._anchor_host = QScrollArea()
        self._anchor_host.setWidgetResizable(True)
        self._anchor_host.setFrameShape(QFrame.Shape.NoFrame)
        self._anchor_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._anchor_host.setStyleSheet("background: transparent; border: none;")
        self._panel_stack.addWidget(self._anchor_host)              # index 1
        # Page 2 — roast review. Takes the place of the controls once they are
        # inert: a finished roast, or a profile opened from a file.
        self._review_host = QScrollArea()
        self._review_host.setWidgetResizable(True)
        self._review_host.setFrameShape(QFrame.Shape.NoFrame)
        self._review_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._review_host.setStyleSheet("background: transparent; border: none;")
        self.roast_review = RoastReviewPanel(self.aw, self)
        self.roast_review.card_requested.connect(self._open_roast_card)
        self.roast_review.weight_requested.connect(self._enter_roast_weights)
        self._review_host.setWidget(self.roast_review)
        self._panel_stack.addWidget(self._review_host)              # index 2
        self._review_shown: bool = False
        self._panel_stack.setCurrentIndex(0)
        self._left_pane.addWidget(self._panel_stack, 1)

        # --- RIGHT PANE: THE ROAST CURVE ---
        # Our own drawing, not Artisan's figure. TilauScope used to reparent
        # Artisan's whole body into this pane and hide everything in it that was
        # not the graph; the window and the figure now stay where they belong.
        self.curve = RoastCurveWidget(self.aw, self.container)
        self.curve.setStyleSheet("background: transparent; border-radius: 15px;")
        self.curve.tick()   # whatever is already loaded, before the first sample
        # The curve takes all remaining space (stretch=1)

        self._main_layout.addWidget(self.container)

        # --- add the sidebar ---
        self.collapsible_events = CollapsibleLiveEvents(self.aw, self)
        # CollapsibleLiveEvents is a controller, not a widget — the
        # base sheet goes on the panel it owns. The grip is a 16 px painted
        # tab with nothing for the sheet to style.
        apply_tilau_theme(self.collapsible_events.sidebar, ground=False)

        self.toggle_panels(self._left_widget, self._content_layout, False) # no swap just display current parameter value

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
        self.extra_panel.reset_counters()
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
        self._refresh_emergency_visibility()   # window may open on a live session
        if self.aw:
            self.aw.installEventFilter(self)
        from tilauscope.roast_asssistant import RoastAssistantPanel
        from tilauscope.roast_bridge import RoastDataBridge
        self.roast_assistant = RoastAssistantPanel(self.aw, self)
        self.roast_bridge    = RoastDataBridge(self.aw, parent=self)
        self.roast_assistant.connect_bridge(self.roast_bridge)
        self.roast_assistant.closed.connect(self._on_assistant_closed)
        self.roast_assistant.anchor_requested.connect(self.toggle_assistant_anchor)
        self.roast_assistant.hide()

        # ── Assistant placement state ────────────────────────────
        self._assistant_open: bool   = False
        self._body_in_host: bool     = False
        self._assistant_anchored: bool = QSettings().value(
            "tilauscope/assistant_anchored", False, type=bool)
        self.btn_dock.setEnabled(False)
        self.roast_assistant.populate_bean_list()   # always identify bean on open
        if self._assistant_anchored:
            # Restoring the anchored mode implies re-opening the assistant.
            self._assistant_open = True
            self.update_button_style(self.btn_assistant, True, False, False, True)
        self._place_assistant()
        if self._assistant_anchored:
            # Re-evaluate once geometry has settled to avoid a transient scrollbar.
            QTimer.singleShot(150, self._place_assistant)

        # ── Roast Replay init ──────────────────────────────────────
        # Armed by RoastSetupDialog (pre-CHARGE) or by the header button;
        # only ever engaged at CHARGE (see arm_roast_replay / _engage_replay).
        # Any playback left armed in Artisan's own settings from a previous
        # session is cleared below — we control this, not leftover state.
        try:
            # backgroundPlaybackEvents/backgroundReproduce persist in QSettings
            # across sessions (main.py restoreSettings) — a value left ticked
            # from a previous session must not silently arm anything now.
            # Skipped while a roast is already recording (TilauScope opening
            # mid-roast, e.g. after a restart) so an in-progress automation
            # is never yanked out from under the operator.
            if not self.aw.qmc.flagstart:
                self.aw.qmc.backgroundReproduce = False
                self.aw.qmc.turn_playback_event_OFF()
                self.aw.qmc.backgroundPlaybackDROP = False
        except Exception:  # pylint: disable=broad-except
            pass

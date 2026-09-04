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

from PyQt6.QtWidgets import (QApplication, QWidget, QSizePolicy, QMenu,
                             QPushButton, QLayout)
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSlot, QSettings
from PyQt6.QtGui import QColor, QPalette, QCursor, QPixmap, QIcon, QImage
from PyQt6.QtCore import pyqtSignal
from PyQt6 import sip

# get settings
import logging

from typing import Final

from artisanlib.main import ApplicationWindow

from tilauscope.beancave import BeancaveDlg
from tilauscope.tilauscope_types import THEME, _IS_MACOS, TilauMessageBox
from tilauscope.header_icons import (
    SVG_POWER, SVG_PLAY, SVG_STOP,
    SVG_RESET, SVG_BEANCAVE, SVG_ASSISTANT, SVG_SWAP, COL_DISABLED,
    COL_POWER_IDLE, COL_POWER_ACTIVE, COL_ON_LIGHT_FILL,
    COL_RESET_IDLE, COL_RESET_ACTIVE,
    COL_BEANCAVE_IDLE, COL_BEANCAVE_ACTIVE,
    COL_ASSISTANT_IDLE, COL_ASSISTANT_ACTIVE,
    COL_SWAP_IDLE, COL_SWAP_ACTIVE,
    COL_DOCK_IDLE, COL_DOCK_ACTIVE, apply_icon,
    SVG_DOCK,
)
from tilauscope.window.build import BuildMixin
from tilauscope.window.chrome import ChromeMixin
from tilauscope.window.live import LiveMixin
from tilauscope.window.sliders import SlidersMixin
from tilauscope.window.milestones import MilestonesMixin
from tilauscope.window.lifecycle import LifecycleMixin
from tilauscope.window.emergency import EmergencyMixin
from tilauscope.window.parts import ArtisanSettings
from tilauscope.theme_qss import tooltip_qss
from tilauscope.wake_classes import TilauController

_log: Final[logging.Logger] = logging.getLogger(__name__)
_logd: Final[logging.Logger] = logging.getLogger("tilau")
























# --- WIDGETS DE PHASES ---




# --- WIDGETS DE CONTROLE ALTERNATIVE SLIDER ---




# --- SLIDERS ---








# --- EXTRA DEVICES ---



# --- LCD READOUT ---



# --- ALARM SIDEBAR ---




# ─── Grip tab (always visible, 16 px wide) ──────────────────────────────────


# ─── Sidebar wrapper (thin layer around AlarmSidebar) ───────────────────────


# ─── Public façade ───────────────────────────────────────────────────────────


# --- SURCHARGE DES MENUS ---


# Use Python 3.14 f-strings for cleaner theme integration
MENU_STYLE = f"""
    QMenu {{
        background-color: {THEME['BG']}; /* Background of the menu */
        border: 1px solid {THEME['BORDER']};
        color: {THEME['TEXT']};
        padding: 4px;
    }}

    QMenu::item {{
        padding: 6px 24px 6px 24px;
        border-radius: 4px;
        min-width: 150px;
    }}

    /* Distinctive color for hovered/selected items */
    QMenu::item:selected {{
        background-color: {THEME['BORDER']};
        color: #F5E0DC;
    }}

    /* 1. Handling Disabled Lines: Lower opacity or specific muted color */
    QMenu::item:disabled {{
        color: {THEME['SURFACE2']}; /* Muted gray for disabled inputs */
        background-color: transparent;
    }}

    /* 2. Handling Checked Inputs: Highlight checked state */
    QMenu::item:checked {{
        font-weight: bold;
        color: #A6E3A1; /* Distinctive green for checked items */
    }}

    /* Styling the check indicator itself */
    QMenu::indicator:checked {{
        image: url(check_icon.png); /* Optional: path to an icon */
        width: 12px;
        height: 12px;
        margin-left: 5px;
    }}

    /* Distinctive styling for separators */
    QMenu::separator {{
        height: 1px;
        background: {THEME['BORDER']};
        margin: 4px 10px;
    }}

    QMenu::icon {{
        left: 5px;
        /* Ce filtre inverse les couleurs de l'icône (Noir -> Blanc) */
        /* Note: 'invert' est supporté par certains moteurs de rendu Qt6
           Sinon, on joue sur l'opacité ou le remplacement via QProxyStyle */
    }}
"""

# --- PLAYBACK CHECK BEFORE ROASTING ---


# --- APPLICATION PRINCIPALE ---


# QWidget comes last: each mixin inherits it, so listing it first would make
# the method resolution order impossible to build.
class TilauScope(BuildMixin, ChromeMixin, LiveMixin, SlidersMixin, MilestonesMixin, LifecycleMixin, EmergencyMixin, QWidget):

    alarm_fired_signal = pyqtSignal(int)

    # Phase progress mapping — hot BT path (per sample). Class constants so the
    # per-sample handler never re-allocates these lists.
    _PHASE_KEYS   = ("DRY", "MAI", "DEV")          # ordered
    _PHASE_BOUNDS = ((0, 1), (1, 2), (2, 3))       # indices dans qmc.phases

    def __init__(self, aw: ApplicationWindow, message:str = ""):
        super().__init__(None)

        self.aw = aw
        # DisplayScope owns the keep-awake lifecycle: monitoring can now be
        # operated without relying on Artisan's canvas to hold this service.
        self.tilau_ssbserver = TilauController(self)
        self._wake_monitoring = False
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.tilau_ssbserver.finish)

        # Initialisation du pont Artisan
        self.artisan_conf = ArtisanSettings(aw)
        self.theme = self.artisan_conf.get_theme_colors()

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        if _IS_MACOS:
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # Focus stealing on Windows is handled by WA_ShowWithoutActivating above.
        # Two setWindowFlag(..., False) calls used to sit here claiming to do it:
        # setWindowFlags() never set those flags, so clearing them did nothing.

        self.setObjectName("TilauScopeWindow")
        self.setStyleSheet(f"#TilauScopeWindow {{ background-color: {THEME['BG']}; border-radius: 12px; }}")

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(THEME['BG']))
        self.setPalette(palette)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # State first, then the window, then the wiring that needs the widgets.
        # transformArtisan_ui() reads the show_* lists _declare_state() fills.
        self._declare_state()
        self.transformArtisan_ui()
        self.init_ui()
        self._wire_after_build(message)



    def check_daily_brew_status(self):
        settings = QSettings()
        alog_directory = settings.value('alogDirectory', "", str)
        if alog_directory != "":
            from tilauscope.roast_timeline import BrewReadyNotification
            # BrewReadyNotification wants the alog metadata cache
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


    # ─────────────────────────────────────────────────────────────────────────────
    # Artisan UI handover — hide its panels on open, give them back on close
    # ─────────────────────────────────────────────────────────────────────────────


    def transformArtisan_ui(self, store =True):
        aw = self.aw
        aw.setWindowOpacity(0.01)

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
                # copy, never alias: the hide methods below write 0 into that very
                # list, so a reference is already zeroed by the time closeEvent
                # reads it back and Artisan never gets its layout returned
                setattr(self, attr, list(getattr(aw, flag_name)))
            # changeDefault=False: our hiding is temporary and belongs to the
            # TilauScope session, it must not rewrite Artisan's saved preferences
            hide_method(False)

        # Artisan calls this on ON, including when monitoring is switched on from
        # its own side rather than from our MONITOR button. The heat cut has to
        # be on screen from that instant — waiting for START is too late, since
        # the drum is already heating.
        self._refresh_beancave_availability()
        self._refresh_emergency_visibility()


    def _queue_live_artisan_state_adoption(self) -> None:
        """Adopt an existing live session once the new window fully exists.

        showEvent runs only after tilauscopeCall() has assigned this instance to
        ``aw.tilauscope_main`` and connected its live signals.  One additional
        event-loop turn lets show() finish before the adoption changes controls,
        phase state and bridge notifications.
        """
        if self._live_state_adoption_queued:
            return
        self._live_state_adoption_queued = True
        QTimer.singleShot(0, self._adopt_live_artisan_state)














    def _lock_control_zone_height(self) -> None:
        """Freeze the control zone at the height its rows ask for, so a row
        hidden and shown again cannot grow the window.
        Run once, deferred, after the first layout pass. """
        try:
            h = self.slider_rows_widget.sizeHint().height()
            if h > 0:
                self._ctrl_stack.setFixedHeight(h)
        except (AttributeError, RuntimeError):
            pass

    def _get_stepper_style(self, color):
        return f"""
            QPushButton {{
                background-color: {THEME['BORDER']};
                color: {color};
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
                border: 1px solid transparent;
            }}
            QPushButton:hover {{
                background-color: {THEME['SURFACE1']};
                border: 1px solid {color}44;
            }}
            QPushButton:pressed {{
                background-color: {color};
                color: {THEME['CRUST']};
            }}
            QPushButton:disabled {{
                background-color: {THEME['BORDER']};
                color: {THEME['SURFACE2']};
                border: 1px solid transparent;
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
        if self.extra_panel is None:
            return
        geo = self.geometry()
        p_w = self.extra_panel.width()
        # Centre horizontally over TilauScope; 10 px below its top edge
        x = geo.x() + (geo.width() - p_w) // 2
        y = geo.y() + 10
        self.extra_panel.move(x, y)

    @pyqtSlot(int)
    def handle_alarm_trigger(self, alarm_index):
        """An alarm fired in Artisan: show it in the sidebar.

        Guarded like the sampling slot, and for the same reason: this is the
        other slot Artisan's sampling thread emits into, and an exception
        escaping a slot reaches the excepthook, which ends this application.
        A card that cannot be built is a missing card, not a closed roast.
        """
        try:
            target_alarm = self.collapsible_events.alarm_sidebar.get_alarm_info(alarm_index)
            if target_alarm:
                self.collapsible_events.alarm_sidebar.add_triggered_alarm(target_alarm)
        except Exception as e:  # pylint: disable=broad-except
            _log.exception('alarm %s could not be shown: %s', alarm_index, e)

    # ── Timer visual state machine ────────────────────────────────────────────
    # Visual states:
    #   "idle"    : stopped/off, grey + slow opacity pulse
    #   "preheat" : recording before CHARGE, white solid (no effect)
    #   "roasting": CHARGE → DROP, white solid (no effect)
    #   "paused"  : simulator paused, orange + fast colour blink
    #
    # Call _update_timer_style(state) from any code path that changes the state.
    # ──────────────────────────────────────────────────────────────────────────






    # get target pid value depending on pid usage (tilau or artisan) to display it in the preheating message






    @pyqtSlot(str, str, str, str)
    def handle_event_fired(self, label: str, command: str, timestamp: str, color: str) -> None:
        """Délègue l'event badge à la sidebar sans logique métier."""
        try:
            self.collapsible_events.alarm_sidebar.add_event_badge(label, command, timestamp, color)
        except Exception:
            pass







    def _minmax_open(self) -> bool:
        """The min/max trackers follow the roast, not the cooling: they close at
        DROP even though the recording is still running."""
        return self.is_roasting and self.aw.qmc.timeindex[0] > -1 and not self._drop_done









    def _level_switch_allowed(self) -> bool:
        """False while a recording roast forbids the Expert → Guided switch,
        or while Roast Replay is armed/active — a replay session has no plan
        of its own, Guided has nothing to guide with.

        Guided → Expert stays free: dropping the guidance mid-roast is safe,
        while adopting it on a roast that has no plan is not.
        """
        if self.replay_enabled:
            return False
        if getattr(self, "_operator_level", "guided") != "expert":
            return True
        try:
            return not bool(self.aw.qmc.flagstart)
        except Exception:  # pylint: disable=broad-except
            return True

    def _refresh_level_lock(self) -> None:
        """Enable/disable the level button according to the recording state."""
        try:
            allowed = self._level_switch_allowed()
            self.btn_level.setEnabled(allowed)
            if allowed:
                _tip = getattr(self, "_level_tooltip", "")
            elif self.replay_enabled:
                _tip = QApplication.translate(
                    "tilauscope_window",
                    "Operator level: Expert — locked while Roast Replay is active")
            else:
                _tip = QApplication.translate(
                    "tilauscope_window",
                    "Operator level: Expert — locked until the roast ends")
            self.btn_level.setToolTip(_tip)
        except Exception:  # pylint: disable=broad-except
            pass

    def _cycle_operator_level(self) -> None:
        """Toggle the operator level Guided ↔ Expert on button click. """
        if not self._level_switch_allowed():
            return
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
            f"QPushButton {{ background: {THEME['SURFACE']}; color: {_col};"
            f" border: 1px solid {_col}; border-radius: 6px;"
            f" font-size: 13px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {THEME['BG']}; }}"
            f"QPushButton:disabled {{ color: {THEME['SUBTEXT']};"
            f" border: 1px solid {THEME['BORDER']}; }}"
            + tooltip_qss()
        )
        # Guarded: this runs on the construction path, and a translation shipped
        # without both placeholders would raise out of init_ui() and leave the
        # window unopenable in that language alone
        try:
            self._level_tooltip = (
                QApplication.translate("tilauscope_window", "Operator level: {0} — click for {1}")
                .format(_name, _next_name))
        except Exception:  # pylint: disable=broad-except
            self._level_tooltip = f"{_name} → {_next_name}"
        # Expert taken while recording stays Expert until the roast ends.
        self._refresh_level_lock()

        is_guided = level == "guided"
        # Panel-side anchor control (GREEN BEAN header of the advice zone):
        # Guided only. In Guided the assistant is anchored by default and the
        # ⤢ button floats it for a two-panel layout; Expert is main panel only.
        self.roast_assistant.set_panel_anchor_visible(is_guided)
        self.roast_assistant.set_operator_level(level)  # propagate level (controls btn_toggle visibility)
        # The canvas overlays that read the level too — the crack bar shows the
        # phase word alone in Guided, and adds the meter and the figures above it.
        try:
            self.curve.set_operator_level(level)
        except Exception:
            pass

        # Guided-only coach view toggle on the roast graph. The toggle belongs
        # to our own curve now; the getattr keeps this working before the curve
        # is what TilauScope displays, and after.
        try:
            curve = getattr(self, "curve", None)
            if curve is not None:
                curve.annotations.set_coach_allowed(is_guided)
        except Exception:  # pylint: disable=broad-except
            pass

        # Alarm control follows the operator level: Guided suppresses
        # all alarm actions (re-asserted each status refresh); Expert hands control
        # back to the user immediately. Applied at INIT too (below the from_init
        # guard would leave a fresh Expert start with alarms wrongly suppressed —
        # the startup update_status_text() runs before _operator_level exists and
        # defaults to Guided, setting silent_alarms=True).
        try:
            self.aw.qmc.silent_alarms = is_guided
        except Exception:  # pylint: disable=broad-except
            pass

        # Refresh the status line now — for the initial render as well
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

    # ── Roast Replay ─────────────────────────────────────────────────
    # Replays a loaded background curve during a live roast, driving Artisan's
    # own playback engine (canvas.py playbackevent/playbackdrop). Armed from
    # RoastSetupDialog or the header button; only ever engaged at CHARGE
    # (see _engage_replay) — this is deliberate, not deferred by accident:
    # the automation must never be live before the operator actually commits
    # to CHARGE, and Artisan's own qmc flags stay untouched (and the native
    # Playback Events checkbox unchecked) until that exact moment.









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


    def refresh_assistant_beans(self) -> None:
        """Rebuild the assistant's green-bean dropdown to match the
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

    # ── Assistant anchoring ────────────────────────────────────────

    def toggle_assistant_anchor(self):
        """Toggle the assistant between floating and anchored display."""
        was_open = getattr(self, '_assistant_open', False)
        self._assistant_anchored = not getattr(self, '_assistant_anchored', False)
        if self._assistant_anchored:
            # Anchoring implies the assistant is open.
            self._assistant_open = True
            self.update_button_style(self.btn_assistant, True, False, False, True)
            if not was_open:
                self.roast_assistant.populate_bean_list()   # refresh bean identification
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

        # Page order of precedence: the anchored assistant wins (it is only
        # anchored while the operator asked for it), then the roast review,
        # then the controls.
        self._panel_stack.setCurrentIndex(
            1 if want_host else (2 if getattr(self, '_review_shown', False) else 0))

        if open_ and not anchored:
            self.roast_assistant.show()
            self.roast_assistant.raise_()
        else:
            self.roast_assistant.hide()

        self.btn_dock.setEnabled(open_)
        self.update_button_style(self.btn_dock, anchored, False, False, True)  # icon/state via pipeline

    # ── Milestone marks ────────────────────────────────────────────────



    # ── Roast review ───────────────────────────────────────────────────




    def _set_live_column_visible(self, visible: bool) -> None:
        """Show or hide everything above the panel that only means something live."""
        for widget in (self.lcds, self.status_lbl):
            widget.setVisible(visible)
        if not visible:
            self.automation_lbl.hide()



    def _on_assistant_closed(self) -> None:
        """Re-sync open/close state when the floating ✕ closes the assistant. """
        if not getattr(self, '_assistant_open', False):
            return
        self._assistant_open = False
        self.update_button_style(self.btn_assistant, False, False, False, True)
        self._place_assistant()

    def toggle_beancave(self):
        """Toggles the visibility of the Bean Cave panel."""
        # headless: BeanCave is the home view — leaving TilauScope means
        # switching to BeanCave (close TilauScope, keep Artisan hidden). Delegated
        # to aw.handleBeancave() so the button and the Shift+B/menu path converge.
        # Deferred: handleBeancave closes this very TilauScope, so let the button
        # click handler unwind first before we tear the window down.
        if getattr(self.aw, '_tilau_headless', False):
            QTimer.singleShot(0, lambda: self.aw.handleBeancave())
            return
        if hasattr(self.aw, 'beancaveWindow') and self.aw.beancaveWindow is not None and self.aw.beancaveWindow.isVisible():
            self.aw.beancaveWindow.close()
            self.update_button_style(self.btn_beancave, True, False, False)
        else:
            self.update_button_style(self.btn_beancave, False, False, True)
            # Reuse the live instance: BeancaveDlg has no WA_DeleteOnClose and stays
            # parented to aw, so recreating it on every open piled up dialogs, each
            # keeping its indexer thread and BLE handles alive until quit.
            bc = getattr(self.aw, 'beancaveWindow', None)
            if bc is None or sip.isdeleted(bc):
                bc = BeancaveDlg(self.aw)
                bc.setWindowModality(Qt.WindowModality.NonModal)
                self.aw.beancaveWindow = bc
            elif hasattr(bc, 'refresh_home'):
                # returning to an existing BeanCave: reload stock and roast history
                QTimer.singleShot(0, bc.refresh_home)
            # hooked once per instance — the dialog may also have been created by
            # Artisan's own BeanCave path, which does not connect our handler
            if not bc.property('_tilau_close_hooked'):
                bc.finished.connect(self._on_beancave_closed)
                bc.setProperty('_tilau_close_hooked', True)
            bc.show()

    def _on_beancave_closed(self): # fix 2026/04/25: this is needed to uncheck the button if Beancave is closed by other means than the button (e.g. by Artisan or by the user with the window close button)
        """Called when BeancaveDlg is closed to unmark the button."""
        # Through the helper: monitoring may have been switched on while the
        # database was open, and the button must come back locked, not enabled.
        self.update_button_style(self.btn_beancave, True)
        self._refresh_beancave_availability()

    def update_button_style(self, button:QPushButton, active:bool, emergency:bool=False, checked:bool=False, updateonly:bool=False):
        if not updateonly:
            button.setEnabled(active)
            if button.isCheckable():
                button.setChecked(checked)
        if button is self.btn_power:
            button.setText(QApplication.translate('Button', 'MONITOR'))
        elif button is self.btn_start_stop:
            # one literal per call: a ternary inside translate() is invisible to
            # the extractor, so both labels shipped in English in every language
            button.setText(QApplication.translate('Button', 'STOP') if active
                           else QApplication.translate('Button', 'START'))
        button.setProperty("active", "true" if active else "false")

        # ── icon refresh — lazy map (certains boutons peuvent ne pas encore exister) ──
        disabled = not button.isEnabled()
        _ICON_SPECS = [
            ('btn_power',     SVG_POWER,    COL_POWER_ACTIVE,    SVG_POWER,    COL_POWER_IDLE),
            # START keeps its bright blue fill in both states, so the
            # glyph stays dark like the label instead of following the fill.
            ('btn_start_stop',SVG_STOP, COL_ON_LIGHT_FILL,
             SVG_PLAY, COL_ON_LIGHT_FILL),
            ('btn_reset',     SVG_RESET,    COL_RESET_ACTIVE,    SVG_RESET,    COL_RESET_IDLE),
            ('btn_beancave',  SVG_BEANCAVE, COL_BEANCAVE_ACTIVE, SVG_BEANCAVE, COL_BEANCAVE_IDLE),
            ('btn_assistant', SVG_ASSISTANT,COL_ASSISTANT_ACTIVE,SVG_ASSISTANT,COL_ASSISTANT_IDLE),
            ('swap_button',   SVG_SWAP,     COL_SWAP_ACTIVE,     SVG_SWAP,     COL_SWAP_IDLE),
            ('btn_dock',      SVG_DOCK,     COL_DOCK_ACTIVE,     SVG_DOCK,     COL_DOCK_IDLE),
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
                apply_icon(button, SVG_POWER, THEME['CRITICAL'])

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

        # ── Non-destructive mirror of Artisan's menu tree ──────────
        # Re-hosting live submenu objects via addMenu(menu) detaches them from
        # the native macOS menubar, so any later rebuild of root_menu loses
        # entries. Instead we create NEW QMenu containers and re-add the ORIGINAL
        # QActions (addAction shares the action → Artisan slot connections kept,
        # the application menu bar left intact). Recurses to preserve nested submenus.
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
                # Icon inversion mutates the shared action, so do it at most once
                # ever: re-inverting on every open would flip the icons back, and
                # the text is left untouched — Qt already right-aligns the
                # shortcut itself, and retitling a shared QAction is what trips
                # the macOS menuRole hijack on Artisan's own menubar.
                if not sub_action.icon().isNull() and not sub_action.property('_tilau_icon_inverted'):
                    sub_action.setIcon(get_inverted_icon(sub_action.icon()))
                    sub_action.setProperty('_tilau_icon_inverted', True)
                dst.addAction(sub_action)

        # Rebuilt on every open: the clone re-hosts Artisan's own QAction objects,
        # and Artisan clears and repopulates whole menus at runtime (themes, recent
        # roasts). A cached tree would go stale and, once those actions are
        # deleted, raise out of the click handler.
        if self.root_menu is not None:
            self.root_menu.deleteLater()
            self.root_menu = None

        # tilau_menubar(), not menuBar(): on macOS the menus live on a
        # parentless bar, and menuBar() would build an empty one on the
        # hidden main window instead of returning them.
        artisan_menubar = self.aw.tilau_menubar()
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
            # Ask Artisan first: ToggleMonitor returns without setting flagon when
            # the unsaved-profile prompt is declined. Committing the UI before the
            # call left the window lit with monitoring off, and inverted the
            # button against the real state on the next click.
            self.aw.qmc.ToggleMonitor()
            if not self.aw.qmc.flagon:
                self.update_button_style(self.btn_power, True, False, False)
                self.update_status_text()
                self._refresh_beancave_availability()
                self._refresh_emergency_visibility()
                return
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
            self._apply_controls_enabled(True)
            self.event_panel.show()
            self.update_status_text() # immediately update status to avoid waiting for first data from Artisan
            self._update_timer_style("engaged") # Update timer style based on power state
            self.update_button_style(self.swap_button, False)
            # flagon is already settled here (ToggleMonitor ran above), so a single
            # direct read is enough — no deferred re-read needed
            self._refresh_beancave_availability()
            self._refresh_emergency_visibility()
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
            self._apply_controls_enabled(False)
            self.event_panel.hide()
            self.update_button_style(self.swap_button, True)
            self.aw.qmc.ToggleMonitor()
            # reset roasting flag if OFF is called directly without STOP
            self.is_roasting = False
            if self.extra_panel is not None:
                self.extra_panel.reset_counters() # reset extra counters on power off
            self._update_timer_style("idle") # Update timer style based on power state
            self.update_status_text() # immediately update status to avoid waiting for first data from Artisan
            self._clear_emergency_state()   # nothing is hot any more
            self._clear_no_reading_face()   # nothing is sampling any more
            self._refresh_beancave_availability()
            self._refresh_emergency_visibility()
            # Restaurer messagelabel Artisan au retour en mode OFF
            self.aw.messagelabel.setVisible(True)

    # ── Emergency heat cut ───────────────────────────────────────────────

    def _refresh_beancave_availability(self) -> None:
        """Lock BEAN CAVE while monitoring is on. The database is a between-roasts
        screen: opening it over a live roast puts a second window in front of the
        readouts, and loading a record from it overwrites the device configuration
        the running session depends on."""
        try:
            btn = getattr(self, 'btn_beancave', None)
            if btn is None:
                return
            win = getattr(self.aw, 'beancaveWindow', None)
            if win is not None and win.isVisible():
                return          # already open: leave it its open-state styling
            self.update_button_style(btn, not self.aw.qmc.flagon, False, False)
        except Exception:  # pylint: disable=broad-except
            pass







    # ── Probe silence ────────────────────────────────────────────────────








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









    def set_button_state(self, event:int, state:bool):
        button_key = self.events[event][0]
        btn = self.event_buttons[button_key]
        btn.setEnabled(state)

    def set_button_style(self, event:int,state:bool):
        button_key,button_color = self.events[event]
        btn = self.event_buttons[button_key]
        if state:
            btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['BG']};
                color: {THEME['TEXT']};
                border-radius: 8px;
                border: 1px solid transparent;
                border-left: 5px solid {button_color};
                font-size: 11px;
                font-weight: bold;
                text-align: left;
                padding: 0 4px 0 9px;
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
                color: {THEME['CRUST']};
                padding-left: 18px;
                padding-top: 2px;
            }}

            /* Au repos (hors monitoring) le bouton est inaccessible : il doit
               le montrer. Sans cette regle Qt repeint la forme active. */
            QPushButton:disabled {{
                background: {THEME['BORDER']};
                color: {THEME['SURFACE2']};
                border: 1px solid {THEME['SURFACE1']};
                border-left: 5px solid {THEME['SURFACE2']};
            }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['BORDER']};
                    color: {THEME['SURFACE2']};
                    border-radius: 8px;
                    border: 1px solid {THEME['SURFACE1']};
                    border-left: 5px solid {THEME['SURFACE2']};
                    font-size: 11px;
                    font-weight: bold;
                    text-align: left;
                    padding: 0 4px 0 9px;
                }}
            """)











    # called to refresh screen at start and when paused/resumed
    def _sync_wake_lock(self) -> None:
        """Apply only monitoring ON/OFF edges to DisplayScope's wake lock.

        Reading qmc.flagon here covers state changes initiated by DisplayScope,
        Artisan, the simulator, alarms, or remote control. Merely opening
        DisplayScope does not acquire a lock.
        """
        try:
            monitoring = bool(self.aw.qmc.flagon)
            if monitoring == self._wake_monitoring:
                return
            if monitoring:
                self.tilau_ssbserver.start()
            else:
                self.tilau_ssbserver.finish()
            self._wake_monitoring = monitoring
        except Exception as e:  # the status UI must survive a platform wake error
            _log.warning("wake lock synchronization failed: %s", e)


    # Single choke point for every slider commit path (big control
    # cards, +/- steppers, SmartRoller, assistant quick-adjust, slider drag).
    # Repeated clicks restart the timer, so only the last value is pushed to
    # Artisan: one hardware command and one recorded event per burst.
    # `immediate=True` bypasses the delay (drag release — no repeat to coalesce).
    # ------------------------------------------------------------------
    # Public slider API — how anything outside this window reaches a control
    # ------------------------------------------------------------------
    # Artisan's LCD slots, the assistant's one-tap actions and its quick-adjust
    # tiles each indexed sld_list directly: ten sites, each with its own idea of
    # clamping and of which way the value was travelling. The commit path is
    # documented as having a single choke point, and these methods are how the
    # rest of the application reaches it.














    # single place hiding Artisan's own milestone/event button bar:
    # TilauScope displays its own CHARGE/DRY/FC…/DROP row, so the Artisan one
    # is redundant inside the canvas. Artisan re-shows it on every OnRecorder,
    # hence more than one caller — never duplicate the loop.
    def _hide_artisan_standard_buttons(self) -> None:
        try:
            for b in self.artisan_buttons_collection.values():
                b.setVisible(False)
        except Exception as e:  # pylint: disable=broad-except
            _log.debug("hide artisan buttons: %s", e)




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

            # Drain the layout before re-adding in the new order. The four widgets
            # below are the whole content of this layout: anything else added here
            # would be dropped, so add it to both branches too.
            while content_layout.count() > 0:
                content_layout.takeAt(0)

            if self.is_swapped:
                content_layout.addWidget(self.collapsible_events.sidebar, stretch=0)
                content_layout.addWidget(self.collapsible_events.grip,    stretch=0)
                content_layout.addWidget(self.curve, stretch=1)
                content_layout.addWidget(left_widget, stretch=0)
                self.swap_button.setToolTip(QApplication.translate('tilauscope_window', 'Swap panel position from right to left'))
            else:
                content_layout.addWidget(left_widget, stretch=0)
                content_layout.addWidget(self.curve, stretch=1)
                content_layout.addWidget(self.collapsible_events.grip,    stretch=0)
                content_layout.addWidget(self.collapsible_events.sidebar, stretch=0)
                self.swap_button.setToolTip(QApplication.translate('tilauscope_window', 'Swap panel position from left to right'))
        finally:
            # 3. Re-enable updates and trigger one single clean repaint
            self.setUpdatesEnabled(True)

    def showMessage(self, message:str):
        mb = TilauMessageBox(None, QApplication.translate("tilauscope_window","Roasting"), message, None, True, 500)
        mb.exec()

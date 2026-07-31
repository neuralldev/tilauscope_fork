#
# ABOUT
# MQTT bridge for TilauScope sensors
# Transport delegated to artisanlib.mqttport (Artisan native paho stack).
# Maintains a separate broker connection; feeds MQTTDatabase instead of readings[].

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
# TiLau 2025-2026

# tilauscope/menu_extension.py
#
# Centralizes all TilauScope menu additions and replacements.
# Keeps main.py contact surface to 3 lines (see INTEGRATION below).
#
# INTEGRATION in main.py (3 lines, never change after):
#
#   __slots__  → add  'tilau_menu'
#   __init__   → after all QAction definitions:
#                  from tilauscope.menu_extension import TilauMenuExtension
#                  self.tilau_menu = TilauMenuExtension(self)
#   set_menu() → at end, before closing `if menuBar is not None:`:
#                  self.tilau_menu.apply(menuBar, ui_mode)
#
# ADDING NEW ENTRIES:
#   - New QAction      → declare in _build_actions(), add to _build_tilau_menu()
#                        or _patch_config_menu(), register in shortcut_actions()
#   - Replace action   → use _replace_action() helper
#   - New submenu      → add _build_<name>_menu(), call from _build_tilau_menu()

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication, QMenu, QMenuBar
from PyQt6.QtGui import QAction

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow, UI_MODE

_log = logging.getLogger(__name__)


class TilauMenuExtension:
    """Owns all TilauScope QActions and injects them into Artisan menus."""

    def __init__(self, aw: 'ApplicationWindow') -> None:
        self._aw = aw
        # Top-level menu kept as instance var — prevents GC on macOS
        self.tilau_top_menu: QMenu | None = None
        self._build_actions()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, menu_bar: QMenuBar, ui_mode: 'UI_MODE') -> None:
        """Called at the end of ApplicationWindow.set_menu()."""
        self._sync_checked_states()
        self._patch_config_menu(ui_mode)
        self._insert_tilau_top_menu(menu_bar, ui_mode)

    def shortcut_actions(self) -> list[QAction | None]:
        """Actions with shortcuts managed by MenuShortCutsDisabled."""
        return [
            self.act_main,
            self.act_beancave,
        ]

    # ------------------------------------------------------------------
    # Action construction — add new TilauScope actions here
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        aw = self._aw

        self.act_main = QAction('TilauScope', aw)
        self.act_main.setCheckable(True)
        self.act_main.setShortcut('Shift+T')
        self.act_main.triggered.connect(aw.tilauscopeCall)

        self.act_beancave = QAction(QApplication.translate('Menu', 'BeanCave'), aw)
        self.act_beancave.setCheckable(True)
        self.act_beancave.setShortcut('Shift+B')
        self.act_beancave.triggered.connect(aw.handleBeancave)

        # EXPERT only — injected in Config menu after deviceAction
        self.act_config = QAction(QApplication.translate('Menu', 'TilauScope Config...'), aw)
        self.act_config.triggered.connect(aw.tilauscope_config)

        # Replay the first-run configuration assistant on demand
        self.act_first_config = QAction(
            QApplication.translate('Menu', 'Redo First-Time Setup...'), aw)
        self.act_first_config.triggered.connect(self._run_first_config)

        # EXPERT only — in TilauScope top menu
        self.act_debug = QAction(QApplication.translate('Menu', 'TilauScope Debug'), aw)
        self.act_debug.setCheckable(True)
        self.act_debug.triggered.connect(aw.tilauscopeDebug)

        self.act_pid_autotune = QAction(QApplication.translate('Menu', 'PID Autotune'), aw)
        self.act_pid_autotune.setCheckable(True)
        self.act_pid_autotune.triggered.connect(aw.handlePIDAutotune)

        ## TILAU ## No About entry here on purpose: renaming the application made
        ## Artisan's own About action read "About TilauScope" in the conventional
        ## slot (application menu on macOS, Help menu elsewhere). It opens the
        ## fork's About window — see ApplicationWindow.helpAbout().

        ## TILAU ## macOS menu merging: Qt's default TextHeuristicRole inspects the
        ## action's *translated* text and hijacks anything looking like About /
        ## Preferences / Quit into the application menu. 'About TilauScope' was
        ## silently moved there, and a translated 'Config...' would follow. Artisan
        ## itself pins NoRole on every action it wants to keep in place
        ## (main.py:2219 and below) — same treatment here.
        for _action in (self.act_main, self.act_beancave, self.act_config,
                        self.act_first_config, self.act_debug,
                        self.act_pid_autotune):
            _action.setMenuRole(QAction.MenuRole.NoRole)

    def _run_first_config(self, _checked: bool = False) -> None:
        """Force-replay the first-run configuration assistant."""
        try:
            from tilauscope.onboarding import run_onboarding
            bc = getattr(self._aw, 'beancave', None)
            parent = bc if bc is not None else self._aw
            run_onboarding(parent, self._aw)
        except Exception:  # pylint: disable=broad-except
            import logging
            logging.getLogger(__name__).exception('replay first-config failed')

    def _sync_checked_states(self) -> None:
        aw = self._aw
        self.act_main.setChecked(bool(aw.tilauscope_main))
        self.act_beancave.setChecked(bool(aw.beancave))
        self.act_debug.setChecked(bool(aw.tilauDBG))
        self.act_pid_autotune.setChecked(bool(aw.PIDAutotune))
        self.refresh_main_label(getattr(aw, '_tilau_headless', False), bool(aw.tilauscope_main))

    def refresh_main_label(self, headless: bool, tilau_open: bool) -> None:
        ## TILAU ## In headless mode the Shift+T action is a view-toggle between
        ## the Artisan window and TilauScope; the label states where it goes.
        ## In normal mode it keeps the plain 'TilauScope' label.
        if not headless:
            self.act_main.setText('TilauScope')
        elif tilau_open:
            # TilauScope is the active view -> Shift+T reveals the Artisan window
            self.act_main.setText(QApplication.translate('Menu', 'Switch to Artisan window'))
        else:
            # Artisan is the active view -> Shift+T returns to TilauScope
            self.act_main.setText(QApplication.translate('Menu', 'Switch to TilauScope'))

    # ------------------------------------------------------------------
    # Menu building — add new TilauScope submenus here
    # ------------------------------------------------------------------

    def _build_tilau_menu(self, ui_mode: 'UI_MODE') -> QMenu:
        """Build (or rebuild) the TilauScope top-level menu."""
        from artisanlib.main import UI_MODE as _UI_MODE

        # Parent = aw so Qt doesn't GC it on macOS
        menu = QMenu('&TilauScope', self._aw)
        menu.addAction(self.act_main)
        menu.addAction(self.act_beancave)
        menu.addSeparator()
        menu.addAction(self.act_config)
        menu.addAction(self.act_first_config)
        if ui_mode is _UI_MODE.EXPERT:
            menu.addSeparator()
            menu.addAction(self.act_debug)
            menu.addAction(self.act_pid_autotune)
        return menu

    # ------------------------------------------------------------------
    # Patching helpers
    # ------------------------------------------------------------------

    def _patch_config_menu(self, ui_mode: 'UI_MODE') -> None:
        """No-op — act_config is now in the TilauScope top-level menu."""

    def _insert_tilau_top_menu(self, menu_bar: QMenuBar, ui_mode: 'UI_MODE') -> None:
        """Insert TilauScope menu between Tools/View (or View/Help in PRODUCTION)."""
        # Rebuild each time set_menu() is called (mode switches)
        self.tilau_top_menu = self._build_tilau_menu(ui_mode)

        # Use aw.viewMenu directly — reliable on macOS, no title-search needed
        view_menu: QMenu | None = self._aw.viewMenu
        if view_menu is not None:
            menu_bar.insertMenu(view_menu.menuAction(), self.tilau_top_menu)
        else:
            menu_bar.addMenu(self.tilau_top_menu)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_action_after(menu: QMenu, ref: QAction | None, new_action: QAction) -> None:
        """Insert new_action immediately after ref. Idempotent. Appends if ref absent."""
        if new_action in menu.actions():
            return
        if ref is None or ref not in menu.actions():
            menu.addAction(new_action)
            return
        actions = menu.actions()
        idx = actions.index(ref)
        before = actions[idx + 1] if idx + 1 < len(actions) else None
        if before is not None:
            menu.insertAction(before, new_action)
        else:
            menu.addAction(new_action)

    @staticmethod
    def _replace_action(menu: QMenu, old_action: QAction, new_action: QAction) -> None:
        """Swap old_action for new_action, preserving position."""
        if old_action not in menu.actions():
            return
        menu.insertAction(old_action, new_action)
        menu.removeAction(old_action)
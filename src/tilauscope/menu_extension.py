#
# ABOUT
# Centralizes all TilauScope menu additions and replacements into Artisan's menu bar.

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

# Keeps main.py's contact surface to 3 lines: __slots__ entry, TilauMenuExtension(self)
# in __init__, and self.tilau_menu.apply(menuBar, ui_mode) at the end of set_menu().

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication, QMenu, QMenuBar
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from PyQt6 import sip

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow, UI_MODE

_log = logging.getLogger(__name__)


class TilauMenuExtension:
    """Owns all TilauScope QActions and injects them into Artisan menus."""

    def __init__(self, aw: 'ApplicationWindow') -> None:
        self._aw = aw
        # Top-level menu kept as instance var — prevents GC on macOS
        self.tilau_top_menu: QMenu | None = None
        self._help_menu_rewired = False
        self._build_actions()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, menu_bar: QMenuBar, ui_mode: 'UI_MODE') -> None:
        """Called at the end of ApplicationWindow.set_menu()."""
        self._sync_checked_states()
        self._patch_config_menu(ui_mode)
        self._insert_export_logs_action()
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

        # Free-entry label: for a coffee bought already roasted, so it needs no
        # bean record and no open BeanCave window.
        self.act_custom_label = QAction(
            QApplication.translate('Menu', 'Print a Coffee Label...'), aw)
        self.act_custom_label.triggered.connect(self._open_custom_label)

        self.act_profile_maintenance = QAction(
            QApplication.translate('Menu', 'Roast Profile Maintenance...'), aw)
        self.act_profile_maintenance.triggered.connect(self._open_profile_maintenance)

        self.act_custom_buttons = QAction(
            QApplication.translate('Menu', 'Custom button management...'), aw)
        self.act_custom_buttons.triggered.connect(self._open_custom_buttons)

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

        self.act_pid_autotune = QAction(
            QApplication.translate('Menu', 'Understand and adjust PID...'), aw)
        self.act_pid_autotune.setCheckable(True)
        self.act_pid_autotune.triggered.connect(aw.handlePIDAutotune)

        # Inserted into Artisan's general Help menu — shares report_a_bug() with
        # the About dialog (never drift apart).
        self.act_export_logs = QAction(
            QApplication.translate('Menu', 'Export Logs...'), aw)
        self.act_export_logs.triggered.connect(self._export_logs)

        # No About entry here: Artisan's own About action already reads
        # "About TilauScope" and opens the fork's About window (see helpAbout()).

        # macOS menu merging: Qt's TextHeuristicRole hijacks any action whose
        # translated text looks like About/Preferences/Quit into the application
        # menu. Pin NoRole on every action, matching Artisan's own treatment
        # (main.py:2219 and below).
        for _action in (self.act_main, self.act_beancave,
                        self.act_custom_label,
                        self.act_profile_maintenance, self.act_custom_buttons,
                        self.act_config,
                        self.act_first_config, self.act_debug,
                        self.act_pid_autotune, self.act_export_logs):
            _action.setMenuRole(QAction.MenuRole.NoRole)

    def _open_profile_maintenance(self, _checked: bool = False) -> None:
        """Open profile maintenance directly; BeanCave remains a data provider."""
        try:
            bc = getattr(self._aw, 'beancaveWindow', None)
            if bc is None or sip.isdeleted(bc):
                from tilauscope.beancave import BeancaveDlg
                bc = BeancaveDlg(
                    self._aw, self._aw.qmc.beans if self._aw.qmc.beans else '')
                bc.setWindowModality(Qt.WindowModality.NonModal)
                self._aw.beancaveWindow = bc
            bc.open_profile_maintenance()
        except Exception:  # pylint: disable=broad-except
            _log.exception('opening roast profile maintenance failed')

    def _open_custom_label(self, _checked: bool = False) -> None:
        """Open the hand-typed label window; BeanCave supplies the printer."""
        try:
            from tilauscope.custom_label_dialog import open_custom_label_dialog
            open_custom_label_dialog(self._aw)
        except Exception:  # pylint: disable=broad-except
            _log.exception('opening the custom label dialog failed')

    def _open_custom_buttons(self, _checked: bool = False) -> None:
        """Open the TilauScope master-detail editor for custom event buttons."""
        try:
            from tilauscope.custom_buttons import open_custom_button_manager
            open_custom_button_manager(self._aw)
        except Exception:  # pylint: disable=broad-except
            _log.exception('opening custom button management failed')

    def _export_logs(self, _checked: bool = False) -> None:
        from tilauscope.tilau_exceptions import report_a_bug
        report_a_bug(self._aw)

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
        # The action only exists as a VIEW TOGGLE, and only headless mode has two
        # views to toggle between. In normal mode TilauScope is the application:
        # Artisan's window is hidden at boot and closing TilauScope quits, so the
        # entry could only ever take the operator somewhere they cannot come back
        # from. Hidden rather than removed — set_menu() runs before the boot mode
        # is known, so the decision has to be one this method can revisit.
        self.act_main.setVisible(headless)
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
        menu.addAction(self.act_custom_label)
        menu.addAction(self.act_profile_maintenance)
        menu.addAction(self.act_custom_buttons)
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
        """Hide Artisan menu items not used by TilauScope's guided workflow
        (theme/colors/UI mode, wheel graph, cup profile, core debug tools).
        Re-applied on every set_menu() call (mode switches rebuild the menus).
        """
        aw = self._aw
        for attr, hide in (
            ('colorsAction', lambda a: a.setVisible(False)),
            ('themeMenu', lambda m: m.menuAction().setVisible(False)),
            ('UIModeMenu', lambda m: m.menuAction().setVisible(False)),
            ('wheeleditorAction', lambda a: a.setVisible(False)),
            ('calculatorAction', lambda a: a.setVisible(False)),
            ('scheduleAction', lambda a: a.setVisible(False)),
            ('transformAction', lambda a: a.setVisible(False)),
            ('flavorAction', lambda a: a.setVisible(False)),
            ('errorAction', lambda a: a.setVisible(False)),
            ('messageAction', lambda a: a.setVisible(False)),
            ('serialAction', lambda a: a.setVisible(False)),
            ('platformAction', lambda a: a.setVisible(False)),
            ('resetAction', lambda a: a.setVisible(False)),
        ):
            obj = getattr(aw, attr, None)
            if obj is not None:
                hide(obj)

        self._rewire_help_actions()

    def _rewire_help_actions(self) -> None:
        """Point Help/Documentation and Help/Check for Updates at TilauScope's
        own doc URL and update routine instead of Artisan's. Runs once — the
        QAction objects are created once and persist across set_menu() calls.
        """
        if self._help_menu_rewired:
            return
        aw = self._aw

        doc_action = getattr(aw, 'helpDocumentationAction', None)
        if doc_action is not None and hasattr(aw, 'helpHelp'):
            doc_action.triggered.disconnect(aw.helpHelp)
            doc_action.triggered.connect(self._open_tilau_documentation)

        update_action = getattr(aw, 'checkUpdateAction', None)
        updater = getattr(aw, '_tilau_updater', None)
        if update_action is not None and updater is not None and hasattr(aw, 'checkUpdate'):
            update_action.triggered.disconnect(aw.checkUpdate)
            update_action.triggered.connect(updater.check_now)

        if doc_action is not None or update_action is not None:
            self._help_menu_rewired = True

    def _insert_export_logs_action(self) -> None:
        """Add 'Export Logs...' to Artisan's general Help menu, right after the
        keyboard-shortcuts entry. helpMenu is rebuilt from scratch on every
        set_menu() call, so this re-inserts every time rather than once.
        """
        help_menu = getattr(self._aw, 'helpMenu', None)
        if help_menu is None:
            return
        ref = getattr(self._aw, 'KshortCAction', None) \
            or getattr(self._aw, 'helpDocumentationAction', None)
        self._insert_action_after(help_menu, ref, self.act_export_logs)

    @staticmethod
    def _open_tilau_documentation(_checked: bool = False) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl('https://tilauscope.org'))

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

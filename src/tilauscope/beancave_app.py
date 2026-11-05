# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""BeanCave alone, beside the operator's own Artisan (wiki/BeanCave-Standalone-Spec.md).

    python -m tilauscope.beancave_app

Its own settings (TilauScope / BeanCave), its own single instance, and never
Artisan's application window: BeanCave runs against the stand-in of
cave/standalone.py and hands roasts to Artisan through the files it opens.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path

from PyQt6.QtCore import QLibraryInfo, QLocale, QLockFile, QSettings, QStandardPaths, QTimer, QTranslator
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import QApplication, QMenuBar

from artisanlib.util import getResourcePath

_log = logging.getLogger(__name__)


def interface_language(artisan: QSettings | None) -> str:
    """The language Artisan is set to, else the system's, in the spelling of the .qm files."""
    chosen = str(artisan.value('locale', '') or '') if artisan is not None else ''
    name = chosen if chosen not in {'', 'None'} else QLocale.system().name()
    if name.startswith(('zh_Hans', 'zh_CN')) or name == 'zh':
        return 'zh_CN'
    if name.startswith(('zh_Hant', 'zh_TW')):
        return 'zh_TW'
    if name.startswith('pt_BR'):
        return 'pt_BR'
    return name[:2] or 'en'


def install_translations(app: QApplication, language: str) -> None:
    """Qt's own strings and TilauScope's, from the folders TilauScope ships them in."""
    if language == 'en':
        return
    from artisanlib import translation_paths
    folders = translation_paths.translation_search_paths(
        translation_paths.__file__, QApplication.applicationDirPath(),
        frozen_root=getattr(sys, '_MEIPASS', None), system=platform.system())
    for catalogue, search in ((f'qtbase_{language}',
                               [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath), *folders]),
                              (f'artisan_{language}', folders)):
        translator = QTranslator(app)
        if any(translator.load(catalogue, folder) for folder in search):
            app.installTranslator(translator)
        else:
            _log.info('no %s in %s', catalogue, search)


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName('TilauScope')
    app.setOrganizationDomain('tilauscope.org')
    app.setApplicationName('BeanCave')
    # macOS draws the Dock icon from the bundle and rounds it, as TilauScope's; a
    # window icon would replace it with the square tile as it is.
    if platform.system() != 'Darwin':
        app.setWindowIcon(QIcon(str(Path(getResourcePath()) / 'Icons' / 'beancave.png')))

    # One BeanCave at a time: a second launch leaves the first one alone.
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    data.mkdir(parents=True, exist_ok=True)
    # Without a console (Windows, the Dock), the log file is the only trace; as TilauScope's.
    from logging.handlers import RotatingFileHandler
    log_file = RotatingFileHandler(data / 'beancave.log', maxBytes=800_000, backupCount=2,
                                   encoding='utf-8', delay=True)
    log_file.setFormatter(logging.Formatter(
        '%(asctime)s %(threadName)-10s %(name)-20s %(levelname)-7s: %(message)s', '%m-%d %H:%M:%S'))
    logging.getLogger().addHandler(log_file)
    logging.getLogger().setLevel(logging.INFO)
    _log.info('BeanCave starting (pid %s)', os.getpid())
    # An exception no one catches (a slot, a virtual, a thread) is written down before anything else sees it.
    import threading
    previous_hook = sys.excepthook

    def log_uncaught(kind, value, trace):  # noqa: ANN001
        _log.critical('uncaught exception', exc_info=(kind, value, trace))
        previous_hook(kind, value, trace)
    sys.excepthook = log_uncaught
    threading.excepthook = lambda args: _log.critical(
        'uncaught exception in thread %s', getattr(args.thread, 'name', '?'),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    instance = QLockFile(str(data / 'beancave.instance'))
    if not instance.tryLock(0):
        _log.info('BeanCave is already running')
        return 0
    # A restore chosen in the last session, before anything reads the settings or the library.
    from tilauscope import backup
    backup.apply_pending_restore()

    from tilauscope.cave.artisan_prefs import apply_artisan_settings, artisan_settings, roasts_folder
    from tilauscope.cave.first_run import ROASTER_KEY, FirstRunDialog, needs_first_run
    from tilauscope.roasters import RoasterManager, canonical_roaster_name
    artisan = artisan_settings()
    install_translations(app, interface_language(artisan))
    if needs_first_run(QSettings()):
        artisan_machine = canonical_roaster_name(str(artisan.value('roastertype_setup', '') or '')) if artisan else ''
        first_run = FirstRunDialog(roasts_folder(artisan), list(RoasterManager().get_roaster_list() or []),
                                   artisan_machine)
        if first_run.exec() != FirstRunDialog.DialogCode.Accepted:
            return 0
        # The devices and integrations TilauScope already knows, once (§11).
        from tilauscope.cave.standalone_settings import take_over, tilauscope_settings
        take_over(QSettings(), tilauscope_settings())

    from tilauscope.beancave import BeancaveDlg
    from tilauscope.cave.standalone import StandaloneWindow
    window = StandaloneWindow()
    apply_artisan_settings(window, artisan)
    window.tilau_roaster = canonical_roaster_name(QSettings().value(ROASTER_KEY, '', str))
    cave = BeancaveDlg(window)
    window.beancaveWindow = cave
    from tilauscope import backup_dialog
    # macOS moves this entry to the application menu as Preferences… (⌘,).
    menu_bar = QMenuBar()
    settings_action = QAction(QApplication.translate("tilauscope_beancave", "Settings…"), menu_bar)
    settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
    settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
    settings_action.triggered.connect(cave.open_settings)
    # TilauScope's updater, on BeanCave's own installers in the same releases.
    from tilauscope.tilau_updater import TilauUpdater
    updater = TilauUpdater(cave, product='beancave')
    window._tilau_updater = updater   # a backup from a newer BeanCave offers to update
    update_action = QAction(QApplication.translate("Menu", "Check for Updates"), menu_bar)
    update_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
    update_action.triggered.connect(updater.check_now)
    # Roasts Artisan saved without a coffee are linked here (the Roasts banner opens it too).
    maintenance_action = QAction(QApplication.translate('Menu', 'Roast Profile Maintenance...'), menu_bar)
    maintenance_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
    maintenance_action.triggered.connect(lambda _checked=False: cave.open_profile_maintenance())
    # TilauScope's backup and restore, under BeanCave's name (backup.app_name).
    backup_action = QAction(QApplication.translate("tilauscope_beancave", "Back up BeanCave…"), menu_bar)
    backup_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
    backup_action.triggered.connect(lambda _checked=False: backup_dialog.open_backup(window, cave))
    restore_action = QAction(QApplication.translate("tilauscope_beancave", "Restore BeanCave…"), menu_bar)
    restore_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
    restore_action.triggered.connect(lambda _checked=False: backup_dialog.open_restore(window))
    # ⌘Q closes BeanCave's window, so its own close (saves, threads, printer) runs,
    # and may be refused there; quitting follows from the window closing.
    quit_action = QAction(QApplication.translate("tilauscope_beancave", "Quit"), menu_bar)
    quit_action.setMenuRole(QAction.MenuRole.QuitRole)
    quit_action.setShortcut(QKeySequence.StandardKey.Quit)
    quit_action.triggered.connect(cave.close)
    menu = menu_bar.addMenu('BeanCave')
    if menu is not None:
        menu.addAction(settings_action)
        menu.addAction(maintenance_action)
        menu.addAction(backup_action)
        menu.addAction(restore_action)
        menu.addAction(update_action)
        menu.addAction(quit_action)
    # Its parent is never shown, so Qt does not count it as a window at all: closing it
    # quits. And Qt's own quit on the last window must go, or closing any parentless
    # window (a message, a card) would end BeanCave with its own window still open.
    app.setQuitOnLastWindowClosed(False)
    cave.finished.connect(app.quit)
    cave.show()
    updater.start()
    # What the last session left to say: a restore done or failed, an extra copy not made.
    QTimer.singleShot(1500, lambda: backup_dialog.show_backup_notices(cave, window))
    code = app.exec()
    # Quitting: relaunch for a restore chosen now, else the automatic backup when due.
    try:
        backup_dialog.on_quit()
    except Exception:  # noqa: BLE001
        _log.exception('backup on quit failed')
    window.release_bluetooth()
    # The windows go while the application still exists: one left to Python's exit is
    # destroyed after it, and macOS crashes there (SIGSEGV in QWidget::~QWidget, 2026-11-05).
    from PyQt6 import sip
    for widget in QApplication.topLevelWidgets():
        if not sip.isdeleted(widget):
            sip.delete(widget)
    _log.info('BeanCave ends')
    return code


if __name__ == '__main__':
    sys.exit(main())

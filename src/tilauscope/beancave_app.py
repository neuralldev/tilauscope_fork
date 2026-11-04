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
import platform
import sys
from pathlib import Path

from PyQt6.QtCore import QLibraryInfo, QLocale, QLockFile, QSettings, QStandardPaths, QTranslator
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
    app.setWindowIcon(QIcon(str(Path(getResourcePath()) / 'Icons' / 'beancave.png')))

    # One BeanCave at a time: a second launch leaves the first one alone.
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    data.mkdir(parents=True, exist_ok=True)
    instance = QLockFile(str(data / 'beancave.instance'))
    if not instance.tryLock(0):
        _log.info('BeanCave is already running')
        return 0

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
    # macOS moves this entry to the application menu as Preferences… (⌘,).
    menu_bar = QMenuBar()
    settings_action = QAction(QApplication.translate("tilauscope_beancave", "Settings…"), menu_bar)
    settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
    settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
    settings_action.triggered.connect(cave.open_settings)
    # TilauScope's updater, on BeanCave's own installers in the same releases.
    from tilauscope.tilau_updater import TilauUpdater
    updater = TilauUpdater(cave, product='beancave')
    update_action = QAction(QApplication.translate("Menu", "Check for Updates"), menu_bar)
    update_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
    update_action.triggered.connect(updater.check_now)
    menu = menu_bar.addMenu('BeanCave')
    if menu is not None:
        menu.addAction(settings_action)
        menu.addAction(update_action)
    # Its parent is never shown, so Qt would not count it as the last window: closing it quits.
    cave.finished.connect(app.quit)
    cave.show()
    updater.start()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

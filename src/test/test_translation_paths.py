from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QTranslator

from artisanlib.translation_paths import translation_search_paths


SRC = Path(__file__).resolve().parent.parent
MAIN = SRC / 'artisanlib' / 'main.py'


def test_source_catalog_path_does_not_depend_on_working_directory(tmp_path: Path) -> None:
    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        paths = translation_search_paths(str(MAIN), '/Applications/Python')
    finally:
        os.chdir(previous)

    assert paths[0] == str(SRC / 'translations')
    assert all(Path(path).is_absolute() for path in paths)


def test_macos_bundle_resources_are_searched() -> None:
    paths = translation_search_paths(
        '/Applications/TilauScope.app/Contents/Frameworks/artisanlib/main.py',
        '/Applications/TilauScope.app/Contents/MacOS',
        frozen_root='/Applications/TilauScope.app/Contents/Frameworks',
        system='Darwin',
    )

    assert '/Applications/TilauScope.app/Contents/Resources/translations' in paths


def test_french_catalog_loads_from_source_path() -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    translator = QTranslator(app)
    translation_dir = translation_search_paths(str(MAIN), str(SRC))[0]

    assert translator.load('artisan_fr', translation_dir)
    app.installTranslator(translator)
    try:
        assert QCoreApplication.translate('Menu', 'Language') == 'Langue'
    finally:
        app.removeTranslator(translator)

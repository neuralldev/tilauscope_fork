"""Locate Qt translation catalogs independently of the process CWD."""

from __future__ import annotations

from pathlib import Path


def translation_search_paths(
        module_file: str,
        application_dir: str,
        *,
        frozen_root: str | None = None,
        system: str = '',
) -> list[str]:
    """Return absolute directories in which bundled ``.qm`` files may live.

    TilauScope changes its working directory to the user data directory during
    startup, so translation paths must be anchored to the installation rather
    than to the current directory.  PyInstaller 6 may expose collected data
    through ``sys._MEIPASS`` or move it into a macOS bundle's Resources folder;
    both layouts are covered here.
    """
    module_root = Path(module_file).resolve().parent.parent
    app_dir = Path(application_dir).resolve()

    candidates = [module_root / 'translations']
    if frozen_root:
        candidates.append(Path(frozen_root).resolve() / 'translations')

    if system == 'Darwin':
        contents = app_dir.parent
        candidates.extend((
            contents / 'Resources' / 'translations',
            contents / 'Frameworks' / 'translations',
            contents / 'translations',  # legacy py2app/PyInstaller layout
        ))
    else:
        candidates.extend((
            app_dir / 'translations',
            app_dir / '_internal' / 'translations',
        ))

    # Keep order while removing aliases and duplicates. Do not filter on
    # existence: the list is also useful in startup diagnostics.
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = str(candidate)
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""What makes ``tilauscope.widgets`` a package rather than a folder.

These classes were written inside the roasting window because that is the file
that happened to need them first. Moving them out is only worth something for
as long as they stay ignorant of Artisan: the moment one of them reaches for
``aw`` or imports the window back, the package is a folder again and the next
reader has to read the whole window to understand a label.

The rule is not obvious from the code, so it is stated here.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Final


SRC: Final[Path] = Path(__file__).resolve().parent.parent
PACKAGE: Final[Path] = SRC / 'tilauscope' / 'widgets'
# What a widget in here is allowed to know about.
ALLOWED_ROOTS: Final[frozenset[str]] = frozenset({
    'PyQt6', 'tilauscope.theme_qss', 'tilauscope.tilauscope_types',
    'tilauscope.widgets', '__future__',
})
FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset({
    'aw', 'qmc', 'artisan_conf', 'tilauscope_main', 'ApplicationWindow',
})


def _modules() -> list[Path]:
    found = sorted(PACKAGE.glob('*.py'))
    assert found, f'no package at {PACKAGE}'
    return found


def test_the_package_knows_nothing_but_qt_and_the_theme() -> None:
    """Anything else dragged in here is a dependency the window owns."""
    strays: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                if name.split('.')[0] in {'typing', 'time', 'logging', 'math'}:
                    continue
                if not any(name == root or name.startswith(root + '.')
                           for root in ALLOWED_ROOTS):
                    strays.append(f'{path.name}:{node.lineno} imports {name}')
    assert strays == [], strays


def test_no_widget_reaches_for_artisan_state() -> None:
    """Not by import, and not by walking up a parent chain either."""
    reaches: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            found = None
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
                found = node.attr
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                found = node.id
            elif (isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)
                  and node.func.id in {'getattr', 'hasattr'}
                  and len(node.args) > 1
                  and isinstance(node.args[1], ast.Constant)
                  and node.args[1].value in FORBIDDEN_NAMES):
                found = str(node.args[1].value)
            if found:
                reaches.append(f'{path.name}:{node.lineno} touches {found}')
    assert reaches == [], reaches


def test_the_package_imports_without_artisan(tmp_path: Path) -> None:
    """The claim above, proved by running it rather than by reading it.

    A fresh interpreter imports the package and reports what came with it. If
    anything in here pulled the roasting window in, ``artisanlib`` would appear
    — and importing that writes preferences, which is why this runs in a child
    process rather than in the test session.
    """
    code = (
        'import sys\n'
        'import tilauscope.widgets\n'
        "print([m for m in sys.modules if m.startswith('artisanlib')\n"
        "       or m.endswith('displayscope')])\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, '-c', code], cwd=SRC, capture_output=True, text=True,
        check=False, env={'PATH': '/usr/bin:/bin', 'QT_QPA_PLATFORM': 'offscreen',
                          # its own HOME: nothing this child does may land in the repo
                          'HOME': str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '[]', result.stdout


def test_every_exported_name_is_really_there() -> None:
    """``__all__`` is the package's public face; a typo in it is a broken import."""
    from tilauscope import widgets

    missing = [name for name in widgets.__all__ if not hasattr(widgets, name)]
    assert missing == [], missing
    assert len(widgets.__all__) == len(set(widgets.__all__)), 'duplicated export'

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Where the roasting window's source lives, now that it lives in more than one file.

Many tests compile a single method out of the window without importing it —
importing pulls in ``artisanlib.main``, which writes preferences at module
scope. They used to name ``displayscope.py`` directly. The window is now
assembled from mixins, so the method a test wants may sit in any of its
slices, and every one of those tests would otherwise have to know which.

Ask for the method by name; this finds the slice it currently lives in.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Final


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'
WINDOW_PACKAGE: Final[Path] = SRC / 'tilauscope' / 'window'

#: displayscope first, so a name still defined there wins — which is what the
#: running window does too, the mixins being further along the MRO.
WINDOW_SOURCES: Final[tuple[Path, ...]] = (
    DISPLAY_SCOPE, *sorted(p for p in WINDOW_PACKAGE.glob('*.py')
                           if p.name != '__init__.py'),
)

def _carries_the_window(name: str) -> bool:
    """A rule rather than a list: a new slice should not need editing here."""
    return name == 'TilauScope' or name.endswith('Mixin')


def window_method_node(name: str) -> tuple[Path, ast.FunctionDef]:
    """The definition of window method `name`, and the file holding it."""
    for path in WINDOW_SOURCES:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef)
                    and _carries_the_window(node.name)):
                continue
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return path, child
    raise LookupError(
        f'no method {name!r} on the window; looked in '
        + ', '.join(p.name for p in WINDOW_SOURCES)
    )


def window_method(name: str, namespace: dict[str, Any] | None = None) -> Any:
    """Compile one window method on its own, with no import of the window."""
    path, node = window_method_node(name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    ns: dict[str, Any] = dict(namespace or {})
    exec(compile(module, path, 'exec'), ns)  # noqa: S102
    return ns[name]


def window_source(name: str) -> str:
    """The text of the slice that holds `name` — for tests that grep rather than run."""
    return window_method_node(name)[0].read_text(encoding='utf-8')

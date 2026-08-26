# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""displayscope is a leaf: nothing in the tree imports it back.

Two function-local imports claimed otherwise — one of a name already bound at
module level, on the window-activation path — and a comment said outright that
the assistant imports this module back. It does not, and that sentence would
have sent the next reader looking for a cycle to preserve. The invariant is
cheap to state, so it is stated here rather than in a comment.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'
# Artisan's own entry point owns the window, and imports it lazily.
ALLOWED_IMPORTERS: Final[frozenset[str]] = frozenset({'artisanlib/main.py'})


def _imports_displayscope(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.endswith('displayscope'):
                return True
            if node.module.endswith('tilauscope') and any(
                    alias.name == 'displayscope' for alias in node.names):
                return True
        elif isinstance(node, ast.Import) and any(
                alias.name.endswith('displayscope') for alias in node.names):
            return True
    return False


def test_no_module_imports_displayscope_back() -> None:
    """The premise of every local import inside it. Tests are exempt."""
    culprits = [
        str(path.relative_to(SRC))
        for path in sorted(SRC.rglob('*.py'))
        if path != DISPLAY_SCOPE
        and 'test' not in path.parts
        and _imports_displayscope(ast.parse(path.read_text(encoding='utf-8')))
    ]

    assert set(culprits) <= ALLOWED_IMPORTERS, culprits


def test_beancave_is_imported_once_and_at_module_level() -> None:
    """It was bound at the top, then imported again on every WindowActivate."""
    tree = ast.parse(DISPLAY_SCOPE.read_text(encoding='utf-8'))
    sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == 'BeancaveDlg' for alias in node.names)
    ]

    assert len(sites) == 1, [node.lineno for node in sites]
    assert sites[0] in tree.body, 'the single import belongs at module level'

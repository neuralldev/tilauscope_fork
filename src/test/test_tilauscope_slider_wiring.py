# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Inside TilauScope, ``aw.tilauscope_main`` is this very instance.

Reaching for it from within the class is therefore never a way out to Artisan:
it is a no-op before ``tilauscopeCall()`` has assigned it, and a self-reference
afterwards. Five slider handlers were built that way and pushed each value back
into the slider it came from. The path outward is ``moveslider()``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Final

from _window_source import WINDOW_SOURCES, window_method_node


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'
ARTISAN_MAIN: Final[Path] = SRC / 'artisanlib' / 'main.py'


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def test_tilauscope_never_reaches_for_its_own_global_handle() -> None:
    """Any read of it inside the window is a no-op or a self-assignment.

    Checked across every slice: the window is assembled from mixins, and a
    reach for the global handle is just as pointless in any of them.
    """
    reads = [
        node
        for path in WINDOW_SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
        if isinstance(node, ast.Attribute) and node.attr == 'tilauscope_main'
    ]
    assert reads == [], (
        'use self directly: '
        + ', '.join(f'line {node.lineno}' for node in reads)
    )


def test_the_handle_only_ever_holds_none_or_a_fresh_window() -> None:
    """The premise above: Artisan nulls it on close before building a new one.

    Should it ever be pointed at a second, different instance, the reasoning
    that made those slider handlers dead code stops holding.
    """
    tree = ast.parse(ARTISAN_MAIN.read_text(encoding='utf-8'))
    assigned: list[Any] = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute) and target.attr == 'tilauscope_main'
    ]
    assert assigned, 'expected tilauscopeCall() to own this handle'
    for value in assigned:
        is_none = isinstance(value, ast.Constant) and value.value is None
        is_fresh = (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == 'TilauScope'
        )
        assert is_none or is_fresh, ast.dump(value)


def test_slider_moves_reach_artisan_through_the_commit_path() -> None:
    """The value leaves this window in _commit_slider_value(), nowhere else."""
    commit = window_method_node('_commit_slider_value')[1]
    called = {
        node.func.attr for node in ast.walk(commit)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {'moveslider', 'recordsliderevent'} <= called

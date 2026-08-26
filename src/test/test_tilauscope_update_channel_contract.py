# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""The live update channel is a number, and three statements that said otherwise.

``tilauUpdateSignal`` is declared ``pyqtSignal(int, object, object, bool)``, so
a branch testing the channel against ``"TIMER"`` could never be taken — it read
like the idle timer was handled there, while the real handling sits in the
numeric branch below it. Alongside it, a stray expression statement and a class
docstring written as an f-string, which leaves the class with no docstring at
all. All three are the kind of thing only a parser sees.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'

from _window_source import window_method_node  # noqa: E402
CANVAS: Final[Path] = SRC / 'artisanlib' / 'canvas.py'


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_the_channel_is_never_compared_to_a_string() -> None:
    """Such a branch is unreachable, and hides that the case is handled elsewhere."""
    handler = window_method_node('_apply_artisan_update')[1]
    offenders = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name) and node.left.id == 'data'
        and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                for c in node.comparators)
    ]

    assert offenders == [], f'unreachable channel comparison at {offenders}'


def test_every_emitter_sends_a_numeric_channel() -> None:
    """The premise of the test above, checked on the producing side."""
    offenders: list[int] = []
    for node in ast.walk(_tree(CANVAS)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'emit'
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == 'tilauUpdateSignal'):
            continue
        channel = node.args[0] if node.args else None
        if isinstance(channel, ast.Constant) and not isinstance(channel.value, int):
            offenders.append(node.lineno)

    assert offenders == [], f'non-numeric channel emitted at {offenders}'


def test_no_statement_evaluates_a_name_and_throws_it_away() -> None:
    """`self;self.extra_panel.reset_counters()` — a typo the parser accepts."""
    offenders = [
        node.lineno for node in ast.walk(_tree(window_method_node(
            '_apply_artisan_update')[0]))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Name)
    ]

    assert offenders == [], f'expression statement with no effect at {offenders}'


def test_no_docstring_is_written_as_an_f_string() -> None:
    """An f-string in that position is an expression: __doc__ stays None."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob('*.py')):
        if 'test' in path.parts:
            continue
        tree = _tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.JoinedStr)):
                offenders.append(f'{path.relative_to(SRC)}:{first.lineno}')

    assert offenders == [], offenders

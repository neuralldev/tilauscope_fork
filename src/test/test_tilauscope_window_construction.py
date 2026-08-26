# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""State is declared before the window is built, never after.

The constructor used to set attributes on both sides of its call to init_ui().
Which side an attribute had been written on decided whether its default won or
lost, and four comments in the constructor said so — one per attribute that had
already been caught by it, each with the symptom it produced: a silenced tick, a
heat cut missing from the header, a first refresh dying on an AttributeError
swallowed by its own guard.

There is no side to get wrong any more, and this is the rule that keeps it that
way. Nothing here constructs the window: doing that needs Artisan, whose import
writes preferences.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from _window_source import WINDOW_SOURCES, window_method_node


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'


def _window_class() -> ast.ClassDef:
    tree = ast.parse(DISPLAY_SCOPE.read_text(encoding='utf-8'))
    return next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'TilauScope'
    )


def _self_calls(node: ast.AST) -> list[str]:
    return [
        call.func.attr for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name) and call.func.value.id == 'self'
    ]


def _assigned(node: ast.AST) -> set[str]:
    out = set()
    for st in ast.walk(node):
        targets = (st.targets if isinstance(st, ast.Assign)
                   else [st.target] if isinstance(st, ast.AnnAssign) else [])
        for t in targets:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == 'self'):
                out.add(t.attr)
    return out


def test_the_constructor_declares_then_builds_then_wires() -> None:
    """Three phases, in that order, and nothing else between them."""
    init = next(
        node for node in _window_class().body
        if isinstance(node, ast.FunctionDef) and node.name == '__init__'
    )
    calls = _self_calls(init)
    for name in ('_declare_state', 'init_ui', '_wire_after_build'):
        assert name in calls, f'{name}() is not called by the constructor'
    assert (calls.index('_declare_state') < calls.index('init_ui')
            < calls.index('_wire_after_build')), calls


def test_the_constructor_itself_declares_nothing_the_build_reads() -> None:
    """Attributes belong in _declare_state(), not scattered up the constructor.

    The Qt window setup at the top legitimately sets a few; what matters is
    that nothing the build reads is left to it.
    """
    init = next(
        node for node in _window_class().body
        if isinstance(node, ast.FunctionDef) and node.name == '__init__'
    )
    # only what the constructor writes directly, not what _declare_state does
    direct = _assigned(init)
    assert direct <= {'aw', 'tilau_ssbserver', '_wake_monitoring', 'artisan_conf',
                      'theme'}, sorted(direct)


def _build_scope() -> list[ast.FunctionDef]:
    """init_ui, its builders, and the methods those call — one level down."""
    seen: dict[str, ast.FunctionDef] = {}
    frontier = ['init_ui']
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        try:
            seen[name] = window_method_node(name)[1]
        except LookupError:
            continue
        if name == 'init_ui' or name.startswith('_build_'):
            frontier += _self_calls(seen[name])
    return list(seen.values())


def test_nothing_the_build_reads_is_left_to_be_declared_after_it() -> None:
    """The rule, in the form that catches a new attribute put in the wrong place."""
    wire = window_method_node('_wire_after_build')[1]
    late = _assigned(wire)
    read_during_build = {
        node.attr
        for fn in _build_scope()
        for node in ast.walk(fn)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == 'self' and isinstance(node.ctx, ast.Load)
    }
    trapped = sorted(late & read_during_build)
    assert trapped == [], (
        'declared after the build but read during it: ' + ', '.join(trapped)
    )


def test_the_build_is_split_and_stays_split() -> None:
    """init_ui was 719 lines; the sections it now calls are the seams."""
    init_ui = window_method_node('init_ui')[1]
    builders = [c for c in _self_calls(init_ui) if c.startswith('_build_')]
    assert len(builders) >= 5, builders
    assert len(builders) == len(set(builders)), 'a builder is called twice'
    longest = max((window_method_node(b)[1] for b in builders),
                  key=lambda n: n.end_lineno - n.lineno)
    assert longest.end_lineno - longest.lineno < 400, (
        f'{longest.name} is {longest.end_lineno - longest.lineno} lines'
    )


def test_the_window_can_still_resolve_its_own_bases() -> None:
    """Each slice is a QWidget, so QWidget has to come last.

    Listing it first makes the method resolution order impossible to build and
    the class fails at import, not at construction.
    """
    bases = [b.id for b in _window_class().bases if isinstance(b, ast.Name)]
    assert bases, 'the window has no named bases'
    assert bases[-1] == 'QWidget', bases
    assert all(b.endswith('Mixin') for b in bases[:-1]), bases


def test_no_slice_of_the_window_is_itself_a_widget() -> None:
    """The mixins inherit nothing, and that is not a matter of taste.

    Qt registers the slots a class declares in that class's own metaobject, and
    a window assembled from several QWidget-derived bases only ever receives
    the first one's. A ``@pyqtSlot`` in any later slice then cannot be connected
    at all — Qt reports it as a slot taking no arguments, whatever its real
    signature. Plain mixins keep every slot on the window itself.

    This cost a failed launch once; the runtime half is in
    test_tilauscope_window_slots.py.
    """
    for path in WINDOW_SOURCES:
        if path == DISPLAY_SCOPE:
            continue
        for node in ast.parse(path.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.ClassDef) and node.name.endswith('Mixin'):
                bases = [ast.unparse(b) for b in node.bases]
                assert bases == [], f'{path.name}: {node.name} inherits {bases}'


def test_a_decorated_slot_lives_in_more_than_one_slice() -> None:
    """The premise of the test above: the trap needs a later slice to spring.

    If every decorated slot happened to sit in the first mixin listed, the rule
    would hold by accident and stop protecting anything.
    """
    window = SRC / 'tilauscope' / 'window'
    holders = set()
    for path in WINDOW_SOURCES:
        if window not in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.FunctionDef)
                    and any('pyqtSlot' in ast.unparse(d) for d in node.decorator_list)):
                holders.add(path.name)
    assert len(holders) >= 2, sorted(holders)

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""The unmarked sentinel of qmc.timeindex, and the F-key guards reading it.

Artisan resets timeindex to ``[-1, 0, 0, 0, 0, 0, 0, 0]``: CHARGE is -1 because
0 is a valid sample index, every milestone after it is 0. Reading -1 for the
milestones makes the guards permanently true, which is how they came to enforce
nothing at all.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, Final

from _window_source import window_method, window_method_node, window_source


DISPLAY_SCOPE: Final[Path] = (
    Path(__file__).resolve().parent.parent / 'tilauscope' / 'displayscope.py'
)
UNMARKED: Final[list[int]] = [-1, 0, 0, 0, 0, 0, 0, 0]


def _method_node(name: str) -> ast.FunctionDef:
    return window_method_node(name)[1]


def _method(name: str) -> Any:
    return window_method(name)


def _scope(timeindex: list[int], *, roasting: bool = True) -> Any:
    scope = SimpleNamespace(
        aw=SimpleNamespace(qmc=SimpleNamespace(timeindex=list(timeindex))),
        is_roasting=roasting,
    )
    scope._milestone_marked = MethodType(_method('_milestone_marked'), scope)
    scope._milestone_key_allowed = MethodType(
        _method('_milestone_key_allowed'), scope,
    )
    return scope


def test_artisan_reset_state_has_no_milestone_marked() -> None:
    """The regression itself: on a fresh reset, nothing is marked."""
    scope = _scope(UNMARKED)
    assert [i for i in range(8) if scope._milestone_marked(i)] == []


def test_charge_at_sample_zero_is_marked() -> None:
    """CHARGE uses -1 precisely so that index 0 stays a usable mark."""
    scope = _scope([0, 0, 0, 0, 0, 0, 0, 0])
    assert scope._milestone_marked(0) is True


def test_each_milestone_is_marked_only_by_a_positive_index() -> None:
    for idx in range(1, 8):
        timeindex = list(UNMARKED)
        assert _scope(timeindex)._milestone_marked(idx) is False
        timeindex[idx] = 42
        assert _scope(timeindex)._milestone_marked(idx) is True


def test_out_of_range_or_absent_timeindex_is_not_marked() -> None:
    assert _scope([])._milestone_marked(3) is False
    scope = SimpleNamespace(aw=SimpleNamespace(qmc=SimpleNamespace()))
    assert MethodType(_method('_milestone_marked'), scope)(0) is False


def test_a_key_cannot_mark_a_milestone_whose_prerequisite_is_missing() -> None:
    """FC START (2) needs DRY END (1); on a fresh CHARGE it must refuse."""
    charged = list(UNMARKED)
    charged[0] = 5
    assert _scope(charged)._milestone_key_allowed(2, 1) is False

    dry_marked = list(charged)
    dry_marked[1] = 9
    assert _scope(dry_marked)._milestone_key_allowed(2, 1) is True


def test_a_key_can_always_undo_the_mark_it_owns() -> None:
    """A mark the operator made stays reachable even without its prerequisite."""
    fcs_only = list(UNMARKED)
    fcs_only[2] = 9
    assert _scope(fcs_only)._milestone_marked(1) is False
    assert _scope(fcs_only)._milestone_key_allowed(2, 1) is True


def test_no_key_acts_while_the_roast_is_not_recording() -> None:
    complete = [5, 6, 7, 8, 9, 10, 11, 12]
    assert _scope(complete, roasting=False)._milestone_key_allowed(2, 1) is False


def test_drop_depends_on_charge_not_on_the_crack_before_it() -> None:
    """F7's guard used to read index 1 while its comment named CHARGE."""
    node = _method_node('keyPressEvent')
    source = ast.get_source_segment(window_source('keyPressEvent'), node) or ''
    assert '_milestone_key_allowed(6, 0)' in source


def test_the_shortcut_block_reads_the_sentinel_through_one_helper() -> None:
    """Two conventions coexisted in this file; only the helper may hold one."""
    source = window_source('keyPressEvent')
    node = _method_node('keyPressEvent')
    block = ast.get_source_segment(source, node) or ''
    assert 'timeindex[' not in block
    assert block.count('if self._milestone_key_allowed(') == 7   # F2 through F8

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""A slider being dragged holds a value Artisan has not been told about yet.

Dragging only commits on release, so during the gesture Artisan still holds the
old value — and the once-a-second mirror copied it straight back over the
handle under the operator's finger. Cross a second while dragging the burner
and the drag was simply lost.
"""

from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, Final

from _window_source import window_method


DISPLAY_SCOPE: Final[Path] = (
    Path(__file__).resolve().parent.parent / 'tilauscope' / 'displayscope.py'
)


def _method(name: str) -> Any:
    return window_method(name)


class _Slider:
    """Only what the mirror touches: a value, and whether it is being held."""

    def __init__(self, value: int, held: bool = False) -> None:
        self._value = value
        self._held = held

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - Qt API shape
        self._value = value

    def isSliderDown(self) -> bool:  # noqa: N802 - Qt API shape
        return self._held


def _scope(*, held: set[int] | None = None, pending: set[int] | None = None,
           artisan: int = 40, ours: int = 75, sv: int = 180,
           pid_active: bool = False) -> Any:
    held = held or set()
    pending = pending or set()
    scope = SimpleNamespace(
        _syncing_from_artisan=False,
        sld_list=[_Slider(ours, i in held) for i in range(4)]
        + [_Slider(sv, 4 in held)],
        _artisan_sliders=tuple(_Slider(artisan) for _ in range(4)),
        _has_pending_commit=lambda n: n in pending,
        _apply_sv_lock=lambda _locked: None,
        aw=SimpleNamespace(
            tilauPreheatingPid=SimpleNamespace(
                active=pid_active, sv_native=lambda: 200.0),
            sliderSV=_Slider(sv - 20),
        ),
    )
    scope._slider_holds_user_value = MethodType(
        _method('_slider_holds_user_value'), scope)
    return scope


def _mirror(scope: Any) -> None:
    _method('check_sliders_update')(scope)


def test_the_mirror_leaves_a_slider_the_operator_is_dragging() -> None:
    scope = _scope(held={1}, artisan=40, ours=75)

    _mirror(scope)

    assert scope.sld_list[1].value() == 75, 'the drag was overwritten mid-gesture'


def test_the_other_sliders_still_follow_artisan_during_that_drag() -> None:
    """The fence is per slider: dragging one must not freeze the panel."""
    scope = _scope(held={1}, artisan=40, ours=75)

    _mirror(scope)

    assert [scope.sld_list[i].value() for i in (0, 2, 3)] == [40, 40, 40]


def test_a_debounced_click_is_still_fenced_off() -> None:
    """The release path this replaces: a click inside the commit window."""
    scope = _scope(pending={2}, artisan=40, ours=75)

    _mirror(scope)

    assert scope.sld_list[2].value() == 75


def test_the_set_point_is_fenced_off_while_it_is_dragged() -> None:
    scope = _scope(held={4}, sv=180)

    _mirror(scope)

    assert scope.sld_list[4].value() == 180


def test_the_set_point_is_fenced_off_from_the_preheat_pid_too() -> None:
    """TilauPID rewrites the set point on every pulse — the loudest writer."""
    scope = _scope(held={4}, sv=180, pid_active=True)

    _mirror(scope)

    assert scope.sld_list[4].value() == 180


def test_an_idle_set_point_still_follows_the_preheat_pid() -> None:
    scope = _scope(sv=180, pid_active=True)

    _mirror(scope)

    assert scope.sld_list[4].value() == 200


def test_the_pid_echo_does_not_move_a_set_point_being_dragged() -> None:
    """The second writer into that slider, on Artisan's own SV signal."""
    scope = _scope(held={4}, sv=180)

    _method('update_pid_from_artisan')(scope, 210)

    assert scope.sld_list[4].value() == 180


def test_the_pid_echo_still_reaches_an_idle_set_point() -> None:
    scope = _scope(sv=180)

    _method('update_pid_from_artisan')(scope, 210)

    assert scope.sld_list[4].value() == 210


def test_a_slider_that_cannot_answer_is_not_treated_as_held() -> None:
    """A missing index must not fence the mirror off for good."""
    scope = _scope()
    scope.sld_list = []

    assert scope._slider_holds_user_value(0) is False

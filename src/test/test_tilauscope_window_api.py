# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""A machine control is reached through the window, never past it.

Ten sites outside the roasting window used to index its ``sld_list`` and drive
the control themselves. Each carried its own idea of clamping, and — the part
that made this worth fixing rather than tidying — its own idea of which way the
value was travelling. Artisan's slider LCD slots exist to show a value Artisan
already holds; one of them ended up committing outward instead, pushing the
window's stale value over the one that had just arrived, through a path that
records an event on the roast curve each time round.

Inward is ``mirror_slider_from_artisan``. Outward is ``set_slider_value``.
Keeping them apart is the point.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, Final

from _window_source import window_method


SRC: Final[Path] = Path(__file__).resolve().parent.parent
DISPLAY_SCOPE: Final[Path] = SRC / 'tilauscope' / 'displayscope.py'


def _method(name: str) -> Any:
    return window_method(name)


class _Slider:
    """A control, plus a note of the sync flag each time it is written."""

    def __init__(self, scope: Any, value: int, held: bool = False,
                 low: int = 0, high: int = 100) -> None:
        self._scope, self._value, self._held = scope, value, held
        self._low, self._high = low, high
        self.writes: list[tuple[int, bool]] = []

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - Qt API shape
        self._value = value
        self.writes.append((value, self._scope._syncing_from_artisan))

    def isSliderDown(self) -> bool:  # noqa: N802
        return self._held

    def minimum(self) -> int:
        return self._low

    def maximum(self) -> int:
        return self._high


def _window(*, ours: int = 40, held: bool = False, low: int = 0,
            high: int = 100, controls: int = 4) -> Any:
    commits: list[tuple[int, bool]] = []
    scope = SimpleNamespace(_syncing_from_artisan=False, commits=commits)
    scope.sld_list = [_Slider(scope, ours, held, low, high)
                      for _ in range(controls)]
    scope._slider_holds_user_value = lambda n: scope.sld_list[n].isSliderDown()
    scope.handle_ui_input_released = (
        lambda n, immediate=False: commits.append((n, immediate)))
    for name in ('_slider', 'slider_value', 'set_slider_value',
                 'mirror_slider_from_artisan'):
        setattr(scope, name, MethodType(_method(name), scope))
    return scope


# --- inward -----------------------------------------------------------------

def test_the_mirror_never_travels_back_out() -> None:
    """The defect this pair exists to make impossible."""
    window = _window(ours=40)
    window.mirror_slider_from_artisan(0, 65)
    assert window.sld_list[0].value() == 65
    assert window.commits == [], 'a mirror committed outward'


def test_the_mirror_is_flagged_so_the_move_handler_stays_quiet() -> None:
    """Unflagged, the write re-enters Artisan's own slot it was called from."""
    window = _window()
    window.mirror_slider_from_artisan(2, 55)
    assert window.sld_list[2].writes == [(55, True)]
    assert window._syncing_from_artisan is False, 'the flag was left raised'


def test_the_mirror_yields_to_a_handle_still_held() -> None:
    """Same rule as the once-a-second refresh: the gesture in progress wins."""
    window = _window(ours=40, held=True)
    window.mirror_slider_from_artisan(1, 90)
    assert window.sld_list[1].value() == 40
    assert window.sld_list[1].writes == []


def test_the_flag_comes_down_even_if_the_write_fails() -> None:
    """Left raised, it would mute every later commit from the operator."""
    window = _window()

    def _explode(_value: int) -> None:
        raise RuntimeError('C++ object deleted')

    window.sld_list[3].setValue = _explode
    try:
        window.mirror_slider_from_artisan(3, 10)
    except RuntimeError:
        pass
    assert window._syncing_from_artisan is False


# --- outward ----------------------------------------------------------------

def test_setting_a_value_leaves_through_the_commit_path() -> None:
    window = _window()
    assert window.set_slider_value(1, 62) is True
    assert window.sld_list[1].value() == 62
    assert window.commits == [(1, False)]


def test_setting_a_value_can_skip_the_debounce() -> None:
    window = _window()
    window.set_slider_value(0, 30, True)
    assert window.commits == [(0, True)]


def test_a_value_past_the_end_of_the_control_is_clamped() -> None:
    """Every caller used to clamp for itself, or forget to."""
    window = _window(low=10, high=80)
    window.set_slider_value(0, 500)
    assert window.sld_list[0].value() == 80
    window.set_slider_value(0, -20)
    assert window.sld_list[0].value() == 10


# --- absent controls --------------------------------------------------------

def test_a_control_that_is_not_there_is_reported_not_raised() -> None:
    """Callers run before the window has built its controls, and after it closes."""
    window = _window(controls=2)
    assert window.slider_value(7) is None
    assert window.set_slider_value(7, 50) is False
    window.mirror_slider_from_artisan(7, 50)   # must not raise
    assert window.commits == []


def test_reading_a_control_reports_its_value() -> None:
    window = _window(ours=44)
    assert window.slider_value(3) == 44


# --- the rule itself --------------------------------------------------------

def _sources() -> list[Path]:
    """Everything that is not the window itself.

    The window is assembled from mixins, so it is displayscope.py plus the
    slices under tilauscope/window/ — all of them are inside the front door,
    and indexing sld_list there is the window doing its own work.
    """
    window = SRC / 'tilauscope' / 'window'
    return [
        path for path in sorted(SRC.rglob('*.py'))
        if path != DISPLAY_SCOPE and window not in path.parents
        and 'test' not in path.parts
    ]


def test_nothing_outside_the_window_indexes_its_controls() -> None:
    """``sld_list`` is the window's own business."""
    culprits: list[str] = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == 'sld_list'):
                culprits.append(f'{path.relative_to(SRC)}:{node.lineno}')
    assert culprits == [], culprits


def test_nothing_outside_the_window_calls_into_its_privates() -> None:
    """Reaching past the front door is how the ten sites came about."""
    culprits: list[str] = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Attribute)
                    and node.attr.startswith('_')
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == 'tilauscope_main'):
                culprits.append(
                    f'{path.relative_to(SRC)}:{node.lineno} .{node.attr}')
    assert culprits == [], culprits


# Anything that sends a value out to the machine. None of it belongs in a slot
# whose job is to display a value that machine already has.
COMMIT_CALLS: Final[frozenset[str]] = frozenset({
    'handle_ui_input_released', 'set_slider_value', '_commit_slider_value',
})


def test_artisans_slider_slots_only_ever_mirror_inward() -> None:
    """The regression this guards actually happened, which is why it is here.

    ``updateSliderNLCD`` runs when Artisan's own slider has moved. Committing
    from inside it sends the window's current value back over the new one, and
    every trip through the commit records a slider event on the roast curve.
    """
    tree = ast.parse((SRC / 'artisanlib' / 'main.py').read_text(encoding='utf-8'))
    slots = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith('updateSlider') and node.name.endswith('LCD')
    ]
    assert len(slots) >= 4, [slot.name for slot in slots]

    offenders = [
        f'{slot.name}:{node.lineno} calls {node.func.attr}()'
        for slot in slots
        for node in ast.walk(slot)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in COMMIT_CALLS
    ]
    assert offenders == [], offenders

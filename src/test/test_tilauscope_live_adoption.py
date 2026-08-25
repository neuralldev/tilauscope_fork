# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Lifecycle regressions for adopting a session Artisan already runs."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final


DISPLAY_SCOPE: Final[Path] = (
    Path(__file__).resolve().parent.parent / 'tilauscope' / 'displayscope.py'
)


def _method_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(DISPLAY_SCOPE.read_text(encoding='utf-8'))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'TilauScope'
    )
    return next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _method(name: str, globals_: dict[str, Any] | None = None) -> Any:
    node = _method_node(name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace: dict[str, Any] = {} if globals_ is None else dict(globals_)
    exec(compile(module, DISPLAY_SCOPE, 'exec'), namespace)  # noqa: S102
    return namespace[name]


def _calls(node: ast.FunctionDef) -> list[str]:
    return [
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]


def test_live_state_adoption_belongs_to_first_show_not_construction() -> None:
    constructor_calls = _calls(_method_node('__init__'))
    assert '_adopt_live_artisan_state' not in constructor_calls
    assert '_queue_live_artisan_state_adoption' not in constructor_calls
    assert _calls(_method_node('showEvent')).count(
        '_queue_live_artisan_state_adoption'
    ) == 1


def test_live_state_adoption_is_deferred_and_queued_only_once() -> None:
    scheduled: list[tuple[int, Any]] = []

    class FakeTimer:
        @staticmethod
        def singleShot(delay: int, callback: Any) -> None:  # noqa: N802
            scheduled.append((delay, callback))

    queue_adoption = _method(
        '_queue_live_artisan_state_adoption', {'QTimer': FakeTimer},
    )
    owner = SimpleNamespace(tilauscope_main=None)
    observed_owner: list[bool] = []
    scope = SimpleNamespace(
        _live_state_adoption_queued=False,
        _adopt_live_artisan_state=lambda: observed_owner.append(
            owner.tilauscope_main is scope
        ),
    )

    queue_adoption(scope)
    queue_adoption(scope)  # a second show before the callback must not duplicate it
    assert observed_owner == []
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0

    # Mirrors tilauscopeCall(): assignment and show() complete before Qt invokes
    # the zero-delay callback on the following event-loop turn.
    owner.tilauscope_main = scope
    scheduled[0][1]()
    assert observed_owner == [True]

    queue_adoption(scope)  # returning from BeanCave is only a re-display
    assert len(scheduled) == 1


class _Button:
    def __init__(self) -> None:
        self.checked = False
        self.enabled = False
        self.tooltip = ''

    def setChecked(self, value: bool) -> None:  # noqa: N802
        self.checked = value

    def setEnabled(self, value: bool) -> None:  # noqa: N802
        self.enabled = value

    def setToolTip(self, value: str) -> None:  # noqa: N802
        self.tooltip = value


class _Phase:
    def __init__(self) -> None:
        self.stats: list[tuple[int, int]] = []

    def update_stats(self, elapsed: int, total: int) -> None:
        self.stats.append((elapsed, total))


def _live_scope(*, recording: bool) -> tuple[Any, list[Any]]:
    calls: list[Any] = []
    qmc = SimpleNamespace(
        flagon=True,
        flagstart=recording,
        timeindex=[0, -1, -1, -1, -1, -1, -1, -1],
        timex=[100.0, 101.0],
        temp2=[180.0, 181.0],
    )
    scope = SimpleNamespace(
        aw=SimpleNamespace(
            qmc=qmc,
            messagelabel=SimpleNamespace(
                setVisible=lambda visible: calls.append(('message', visible)),
            ),
        ),
        btn_power=_Button(),
        btn_start_stop=_Button(),
        btn_assistant=_Button(),
        swap_button=_Button(),
        btn_reset=_Button(),
        event_buttons={0: _Button(), 1: _Button()},
        event_panel=SimpleNamespace(show=lambda: calls.append('panel')),
        phases={'DRY': _Phase(), 'MAI': _Phase(), 'DEV': _Phase()},
        phase_starts={'DRY': None, 'MAI': None, 'DEV': None},
        roast_bridge=SimpleNamespace(
            notify_roast_state=lambda live: calls.append(('live', live)),
            notify_phase=lambda phase: calls.append(('phase', phase)),
        ),
        is_roasting=False,
        update_button_style=lambda *args: calls.append(('style', args)),
        _update_timer_style=lambda state: calls.append(('timer', state)),
        update_status_text=lambda: calls.append('status'),
        _hide_artisan_standard_buttons=lambda: calls.append('hide-standard'),
        _refresh_level_lock=lambda: calls.append('level-lock'),
        handle_preheat=lambda visible: calls.append(('preheat', visible)),
        start_roast=lambda auto=False: calls.append(('start-roast', auto)),
        set_phase=lambda phase, second: calls.append(('set-phase', phase, second)),
        _freeze_phases_at_drop=lambda: calls.append('freeze'),
        _disarm_cooling_detection=lambda: calls.append('disarm'),
        mark_button_active=lambda index, disable_button: calls.append(
            ('mark', index, disable_button)
        ),
        _drop_done=False,
        _cooling_detected=False,
        _bt_at_drop=None,
        _bt_drop_timestamp=None,
    )
    return scope, calls


def test_deferred_adoption_restores_monitoring_and_recording_states() -> None:
    class FakeApplication:
        @staticmethod
        def translate(_context: str, text: str) -> str:
            return text

    log_errors: list[Any] = []
    adopt = _method(
        '_adopt_live_artisan_state',
        {
            'QApplication': FakeApplication,
            '_log': SimpleNamespace(error=log_errors.append),
        },
    )

    monitoring, monitoring_calls = _live_scope(recording=False)
    adopt(monitoring)
    assert monitoring.btn_power.checked
    assert monitoring.btn_power.tooltip == 'Stop monitoring'
    assert monitoring.is_roasting is False
    assert 'status' in monitoring_calls
    assert not any(call == ('start-roast', True) for call in monitoring_calls)

    recording, recording_calls = _live_scope(recording=True)
    adopt(recording)
    assert recording.btn_power.checked
    assert recording.is_roasting is True
    assert ('preheat', False) in recording_calls
    assert ('start-roast', True) in recording_calls
    assert ('set-phase', 'DRY', 0) in recording_calls
    assert ('live', True) in recording_calls
    assert ('phase', 'DRY') in recording_calls
    assert log_errors == []

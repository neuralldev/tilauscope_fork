# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""What the emergency heat cut actually commands, and on which machine.

Burner to its minimum, airflow and extraction wide open. Airflow is slider 0
across the whole application — the guidance lever map, the assistant tiles —
but this one path resolved it by reading the event name and comparing it to
'Air', a name the operator can change and the translator does change. What
decides is the machine: a roaster with no airflow control has no lever to open
there, and driving its slider 0 to maximum moves something else.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Final

from _window_source import window_method


DISPLAY_SCOPE: Final[Path] = (
    Path(__file__).resolve().parent.parent / 'tilauscope' / 'displayscope.py'
)
BURNER: Final[int] = 3
AIRWAVE_COMMAND: Final[int] = 20


def _method(name: str) -> Any:
    return window_method(name, {'_log': logging.getLogger('test')})


def _stub_assistant_module() -> None:
    """The burner resolver lives there; importing it for real would drag Qt in."""
    if 'tilauscope.roast_asssistant' in sys.modules:
        return
    stub = ModuleType('tilauscope.roast_asssistant')
    stub._burner_slider_idx = lambda _aw: BURNER  # type: ignore[attr-defined]
    sys.modules['tilauscope.roast_asssistant'] = stub


def _scope(*, airflow: bool | None = True, air_name: str = 'Air',
           airwave_on: int | None = None) -> Any:
    """`airflow=None` stands for an unknown roaster (no context loaded)."""
    _stub_assistant_module()
    actions = [1, 1, 1, 1]
    if airwave_on is not None:
        actions[airwave_on] = AIRWAVE_COMMAND
    ctx = None if airflow is None else SimpleNamespace(has_airflow_control=airflow)
    return SimpleNamespace(
        aw=SimpleNamespace(
            eventslideractions=actions,
            eventslidermin=[0, 0, 0, 10],
            eventslidermax=[100, 100, 100, 80],
            _tilau_roast_context=ctx,
            qmc=SimpleNamespace(etypes=[air_name, 'Drum', 'Damper', 'Burner']),
        ),
        str_emergency_burner='burner',
        str_emergency_air='air',
        str_emergency_extraction='extraction',
    )


def _targets(scope: Any) -> list[tuple[int, int, str]]:
    return _method('_emergency_slider_targets')(scope)


def test_the_burner_goes_to_its_minimum_first() -> None:
    targets = _targets(_scope())

    assert targets[0] == (BURNER, 10, 'burner'), 'the burner is cut before anything'


def test_airflow_opens_wide_on_a_machine_that_has_it() -> None:
    assert (0, 100, 'air') in _targets(_scope(airflow=True))


def test_airflow_is_left_alone_on_a_machine_that_has_none() -> None:
    """Slider 0 there is some other lever — moving it is not a safe state."""
    targets = _targets(_scope(airflow=False))

    assert [name for _, _, name in targets] == ['burner']


def test_an_unknown_roaster_still_gets_its_airflow_opened() -> None:
    """No context loaded: stay permissive rather than skip a safety gesture."""
    assert (0, 100, 'air') in _targets(_scope(airflow=None))


def test_a_lever_named_in_another_language_is_still_the_airflow() -> None:
    """The regression the name test carried: 'Air' is a translated string."""
    assert (0, 100, 'air') in _targets(_scope(air_name='Luftstrom'))


def test_a_lever_the_operator_renamed_is_still_the_airflow() -> None:
    assert (0, 100, 'air') in _targets(_scope(air_name='Fan'))


def test_the_extraction_is_found_by_its_action_not_its_position() -> None:
    targets = _targets(_scope(airwave_on=2))

    assert (2, 100, 'extraction') in targets


def test_a_lever_that_is_both_airflow_and_extraction_is_sent_once() -> None:
    targets = _targets(_scope(airwave_on=0))

    assert [name for _, _, name in targets] == ['burner', 'extraction']


def test_no_extraction_configured_commands_no_third_lever() -> None:
    targets = _targets(_scope())

    assert [name for _, _, name in targets] == ['burner', 'air']


# --- the replay session, which the heat cut kills without saying so ---------

def _automation_scope(*, replay_raises: bool = False) -> Any:
    done: list[str] = []

    def _disable_replay() -> None:
        done.append('replay')
        if replay_raises:
            raise RuntimeError('header repaint failed')

    return SimpleNamespace(
        done=done,
        _disable_roast_replay=_disable_replay,
        roast_assistant=SimpleNamespace(
            emergency_disengage=lambda: done.append('assistant')),
        aw=SimpleNamespace(
            tilauPreheatingPid=SimpleNamespace(
                active=True, stop=lambda _r: done.append('preheat')),
            pidcontrol=SimpleNamespace(
                pidActive=True, pidOff=lambda: done.append('pid')),
            qmc=SimpleNamespace(
                backgroundPlaybackEvents=True, backgroundPlaybackDROP=True,
                backgroundReproduce=True, alarmsflag=1),
        ),
    )


def test_the_heat_cut_turns_the_replay_session_off() -> None:
    """It already killed the playback underneath: the flag has to follow."""
    scope = _automation_scope()

    _method('_stop_all_automation')(scope)

    assert 'replay' in scope.done


def test_the_heat_cut_still_disarms_everything_if_the_replay_step_fails() -> None:
    """Each step is isolated on purpose — nothing may re-apply heat after."""
    scope = _automation_scope(replay_raises=True)

    _method('_stop_all_automation')(scope)

    qmc = scope.aw.qmc
    assert scope.done == ['preheat', 'pid', 'replay', 'assistant']
    assert (qmc.backgroundPlaybackEvents, qmc.backgroundReproduce) == (False, False)
    assert qmc.alarmsflag == 0


def test_a_lever_elsewhere_carrying_the_name_air_is_not_opened() -> None:
    """The harm the name test could do: a damper labelled 'Air' by its operator
    was driven to maximum in place of the airflow lever, and the airflow one
    was left where it stood."""
    scope = _scope()
    scope.aw.qmc.etypes = ['Intake', 'Drum', 'Air', 'Burner']

    targets = _targets(scope)

    assert (2, 100, 'air') not in targets
    assert (0, 100, 'air') in targets

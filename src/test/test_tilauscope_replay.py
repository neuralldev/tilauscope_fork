# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Roast Replay integration regressions."""

from __future__ import annotations

import ast
import logging
import os
import subprocess  # noqa: S404 - trusted, fully-constructed argv, no shell
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import _guard
from _window_source import window_method, window_method_node, window_source

from tilauscope import roasters
from tilauscope.roasters import invalidate_roast_context, roast_context_for


TEST_DIR: Final[Path] = Path(__file__).resolve().parent
SRC_DIR: Final[Path] = TEST_DIR.parent
DISPLAY_SCOPE: Final[Path] = SRC_DIR / 'tilauscope' / 'displayscope.py'

#: Real registry entries — the capability path is only worth testing against
#: the roasters.json actually shipped.
REPLAY_ROASTER: Final[str] = 'ITOP Cyberroaster'
NO_REPLAY_ROASTER: Final[str] = 'ITOP Skywalker V1'
UNKNOWN_ROASTER: Final[str] = 'No Such Roaster 9000'

# Importing displayscope pulls in artisanlib.main and its process-wide Qt
# objects.  Letting Python finalise those objects is a known PyQt teardown
# crash on macOS (QGuiApplication::~QGuiApplication), so this integration test
# follows the import portico: assert in an isolated child, flush, then hard-exit
# without running the unsafe interpreter finalisers.
_CHILD: Final[str] = r"""
import os, sys, traceback
from types import SimpleNamespace

try:
    sys.path.insert(0, sys.argv[1])
    import _guard
    sandbox = _guard.install(sys.argv[2])
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import numpy
    from tilauscope.displayscope import TilauScope

    # The capability is read through roasters.roast_context_for(), which also
    # publishes the context on aw for every other reader.
    capability_scope = SimpleNamespace(aw=SimpleNamespace(tilau_roaster='ITOP Cyberroaster'))
    assert TilauScope._roaster_supports_profile_replay(capability_scope) is True
    assert capability_scope.aw._tilau_roast_context.display_name == 'ITOP Cyberroaster'
    capability_scope.aw.tilau_roaster = 'ITOP Skywalker V1'
    assert TilauScope._roaster_supports_profile_replay(capability_scope) is False
    capability_scope.aw.tilau_roaster = 'None'
    assert TilauScope._roaster_supports_profile_replay(capability_scope) is False
    assert capability_scope.aw._tilau_roast_context is None

    for background_bt, expected_replay_type in (
        (numpy.array([180.0, 181.0]), 1),
        (numpy.array([-1.0, numpy.nan]), 0),
    ):
        playback_started = []
        qmc = SimpleNamespace(
            backgroundprofile=object(),
            stemp2B=background_bt,
            backgroundReproduce=False,
            replayType=-1,
            specialeventplayback=[False] * 4,
            specialeventplaybackramp=[False] * 4,
            ramp_lookahead=0,
            turn_playback_event_ON=lambda: playback_started.append(True),
        )
        scope = SimpleNamespace(
            aw=SimpleNamespace(
                qmc=qmc,
                tilau_roaster_readonly=False,
                tilau_roaster='ITOP Cyberroaster',
            ),
            replay_reaction_time_s=28.0,
            _roaster_supports_profile_replay=lambda: True,
            _refresh_replay_button=lambda: None,
        )

        TilauScope._engage_replay(scope)

        assert qmc.backgroundReproduce is True
        assert qmc.replayType == expected_replay_type
        assert qmc.specialeventplayback == [True] * 4
        assert qmc.specialeventplaybackramp == [True] * 4
        assert qmc.ramp_lookahead == 28
        assert playback_started == [True]

    # Every entry point must deny a roaster whose context explicitly says no.
    arm_refreshes = []
    level_changes = []
    unsupported = SimpleNamespace(
        replay_enabled=False,
        replay_reaction_time_s=10.0,
        _roaster_supports_profile_replay=lambda: False,
        _refresh_replay_button=lambda: arm_refreshes.append(True),
        _apply_operator_level=lambda level: level_changes.append(level),
    )
    TilauScope.arm_roast_replay(unsupported, 31.0)
    assert unsupported.replay_enabled is False
    assert unsupported.replay_reaction_time_s == 10.0
    assert arm_refreshes == [True]
    assert level_changes == []

    toggle_arms = []
    toggle_scope = SimpleNamespace(
        replay_enabled=False,
        replay_reaction_time_s=10.0,
        aw=SimpleNamespace(qmc=SimpleNamespace(
            timeindex=[-1] * 8,
            backgroundprofile=object(),
        )),
        _replay_externally_active=lambda: False,
        _roaster_supports_profile_replay=lambda: False,
        arm_roast_replay=lambda seconds: toggle_arms.append(seconds),
        _disable_roast_replay=lambda: None,
        _refresh_replay_button=lambda: None,
    )
    TilauScope._toggle_replay_button(toggle_scope)
    assert toggle_arms == []

    class FakeReplayButton:
        def __init__(self):
            self.enabled = True
            self.checked = False
            self.tooltip = ''

        def blockSignals(self, _blocked):
            pass

        def setChecked(self, checked):
            self.checked = checked

        def setEnabled(self, enabled):
            self.enabled = enabled

        def setStyleSheet(self, _style):
            pass

        def setToolTip(self, tooltip):
            self.tooltip = tooltip

    blocked_button = FakeReplayButton()
    refresh_scope = SimpleNamespace(
        replay_enabled=False,
        btn_replay=blocked_button,
        aw=toggle_scope.aw,
        _replay_externally_active=lambda: False,
        _roaster_supports_profile_replay=lambda: False,
    )
    TilauScope._refresh_replay_button(refresh_scope)
    assert blocked_button.enabled is False
    assert 'not supported' in blocked_button.tooltip.lower()

    stopped = []
    started = []
    blocked_qmc = SimpleNamespace(
        backgroundprofile=object(),
        backgroundReproduce=False,
        backgroundPlaybackEvents=False,
        turn_playback_event_ON=lambda: started.append(True),
        turn_playback_event_OFF=lambda: stopped.append(True),
    )
    blocked_scope = SimpleNamespace(
        aw=SimpleNamespace(qmc=blocked_qmc),
        replay_enabled=True,
        _level_before_replay=None,
        _anchor_before_replay=None,
        _roaster_supports_profile_replay=lambda: False,
        _refresh_level_lock=lambda: None,
        _refresh_replay_button=lambda: None,
    )
    blocked_scope._restore_replay_level = lambda: TilauScope._restore_replay_level(
        blocked_scope)
    blocked_scope._disable_roast_replay = lambda: TilauScope._disable_roast_replay(
        blocked_scope)
    TilauScope._engage_replay(blocked_scope)
    assert blocked_scope.replay_enabled is False
    assert blocked_qmc.backgroundReproduce is False
    assert started == []
    assert stopped == [True]
    _guard.verify(sandbox)
except BaseException:
    traceback.print_exc()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1)
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
"""


def test_charge_engages_replay_with_a_numpy_bt_trace(sandbox: Path) -> None:
    env = dict(os.environ)
    env[_guard.SANDBOX_ENV] = str(sandbox / 'replay')
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = os.pathsep.join([str(SRC_DIR), str(TEST_DIR)])
    proc = subprocess.run(  # noqa: S603 - argv is fully constructed, shell=False
        [sys.executable, '-c', _CHILD, str(TEST_DIR), str(sandbox / 'replay')],
        cwd=str(SRC_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── Roast context resolution (roasters.roast_context_for) ──────────────────
# Pure model layer: no Qt, no widget, only the shipped roasters.json.

def _method(name: str, globals_: dict[str, Any] | None = None) -> Any:
    return window_method(name, globals_)


def test_no_roaster_and_unknown_roaster_both_resolve_to_no_replay() -> None:
    for name in ('', 'None', UNKNOWN_ROASTER):
        aw = SimpleNamespace(tilau_roaster=name)
        assert roast_context_for(aw) is None
        assert aw._tilau_roast_context is None
        # The resolver owns the inlet air path too — no roaster means push.
        assert aw._tilau_inlet_air_mode == 'push'


def test_resolution_is_cached_per_selected_roaster(monkeypatch: Any) -> None:
    lookups: list[str | None] = []
    original = roasters.RoasterManager.get_roast_context

    def counted(self: Any, name: str | None = None) -> Any:
        lookups.append(name if name is not None else self._current_roaster)
        return original(self, name)

    monkeypatch.setattr(roasters.RoasterManager, 'get_roast_context', counted)

    aw = SimpleNamespace(tilau_roaster=REPLAY_ROASTER)
    resolved = roast_context_for(aw)
    assert resolved is not None and resolved.supports_profile_replay is True
    for _ in range(4):
        assert roast_context_for(aw) is resolved     # cached object, not a re-read
    assert lookups == [REPLAY_ROASTER]

    # A None result is cached exactly like any other: an unknown roaster must
    # not re-read roasters.json on every button refresh.
    aw.tilau_roaster = UNKNOWN_ROASTER
    for _ in range(4):
        assert roast_context_for(aw) is None
    assert lookups == [REPLAY_ROASTER, UNKNOWN_ROASTER]

    # 'None' and '' are the same selection — one resolution for both.
    aw.tilau_roaster = 'None'
    assert roast_context_for(aw) is None
    aw.tilau_roaster = ''
    assert roast_context_for(aw) is None
    assert lookups == [REPLAY_ROASTER, UNKNOWN_ROASTER]


def test_a_roaster_change_is_seen_without_an_explicit_invalidation() -> None:
    aw = SimpleNamespace(tilau_roaster=REPLAY_ROASTER)
    assert roast_context_for(aw).supports_profile_replay is True
    aw.tilau_roaster = NO_REPLAY_ROASTER
    assert roast_context_for(aw).supports_profile_replay is False
    assert aw._tilau_roast_context.display_name == NO_REPLAY_ROASTER


def test_invalidate_forces_a_re_resolution_of_the_same_name() -> None:
    aw = SimpleNamespace(tilau_roaster=REPLAY_ROASTER)
    first = roast_context_for(aw)
    assert roast_context_for(aw) is first
    invalidate_roast_context(aw)
    second = roast_context_for(aw)
    assert second is not first
    assert second.display_name == first.display_name


def _refresh_capability() -> Any:
    return _method('refresh_replay_capability', {
        'invalidate_roast_context': invalidate_roast_context,
        '_log': logging.getLogger('test'),
    })


def test_refresh_replay_capability_realigns_button_and_advisor() -> None:
    refresh = _refresh_capability()
    aw = SimpleNamespace(tilau_roaster=REPLAY_ROASTER)
    button_reads: list[Any] = []
    advisor_reads: list[Any] = []
    scope = SimpleNamespace(
        aw=aw,
        _refresh_replay_button=lambda: button_reads.append(roast_context_for(aw)),
        roast_assistant=SimpleNamespace(
            reload_roaster_context=lambda: advisor_reads.append(roast_context_for(aw)),
        ),
    )
    assert roast_context_for(aw).supports_profile_replay is True

    aw.tilau_roaster = NO_REPLAY_ROASTER
    refresh(scope)
    assert button_reads[-1].display_name == NO_REPLAY_ROASTER
    # Button and advisor must land on the same machine, not two.
    assert advisor_reads[-1] is button_reads[-1]
    assert aw._tilau_roast_context is button_reads[-1]

    # The invalidation is what makes it re-resolve even on an unchanged name.
    stale = aw._tilau_roast_context
    refresh(scope)
    assert aw._tilau_roast_context is not stale


def test_refresh_replay_capability_never_raises_into_its_caller() -> None:
    refresh = _refresh_capability()

    def boom() -> None:
        raise RuntimeError('button rebuild failed')

    scope = SimpleNamespace(
        aw=SimpleNamespace(tilau_roaster=REPLAY_ROASTER),
        _refresh_replay_button=boom,
    )
    refresh(scope)   # a settings save must never stop here

    # Missing assistant (Expert level / window built without it) is not a failure.
    quiet = SimpleNamespace(
        aw=SimpleNamespace(tilau_roaster=REPLAY_ROASTER),
        _refresh_replay_button=lambda: None,
        roast_assistant=None,
    )
    refresh(quiet)


# ── Lifecycle: the aw-level signals must not outlive the window ────────────

def test_background_signals_are_disconnected_on_close() -> None:
    # The disconnects live in _detach_live_feed, which closeEvent calls first —
    # before any teardown step that could fail and skip them. Both halves are
    # asserted: a helper nobody calls disconnects nothing.
    assert '_detach_live_feed' in window_source('closeEvent')
    detach = window_method_node('_detach_live_feed')[1]
    disconnected = {
        ast.unparse(call.func.value)
        for call in ast.walk(detach)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and call.func.attr == 'disconnect'
    }
    assert 'self.aw.loadBackgroundSignal' in disconnected
    assert 'self.aw.clearBackgroundSignal' in disconnected
    assert 'self.aw.qmc.tilauUpdateSignal' in disconnected
    # A bare lambda cannot be disconnected — the slot has to be held. It is
    # bound where the window is wired up, which is not where closeEvent lives.
    assert 'self._on_background_changed = lambda' in window_source(
        '_wire_after_build')


def test_replay_attributes_are_declared_before_the_ui_is_built() -> None:
    """They are read by the header button, which the build refreshes on its way out.

    The declarations now live in _declare_state(), which the constructor runs
    before init_ui(); the general form of this rule is checked in
    test_tilauscope_window_construction.py.
    """
    tree = ast.parse(window_source('_declare_state'))
    cls = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in ('TilauScope', 'BuildMixin')
        and any(isinstance(m, ast.FunctionDef) and m.name == '_declare_state'
                for m in node.body)
    )
    declare = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == '_declare_state'
    )
    declared = {
        node.target.attr for node in ast.walk(declare)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute)
    }
    for attr in ('replay_enabled', 'replay_reaction_time_s'):
        assert attr in declared, f'{attr} is not declared in _declare_state()'
    # No defensive getattr() left over now that the attributes always exist.
    assert 'getattr(self, "replay_enabled"' not in window_source(
        '_refresh_replay_button')

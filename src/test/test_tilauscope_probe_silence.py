# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""A configured machine that returns nothing at all.

The device opens, sampling runs, and every reading is Artisan's -1 sentinel —
a cable out of its socket. The panel used to keep announcing a preheat it could
not measure, with a maturity badge to go with it; the only honest trace went to
the log, which no operator reads.
"""

from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, Final

from _window_source import window_method


DISPLAY_SCOPE: Final[Path] = (
    Path(__file__).resolve().parent.parent / 'tilauscope' / 'displayscope.py'
)
THRESHOLD: Final[int] = 5


def _method(name: str, namespace: dict[str, Any] | None = None) -> Any:
    return window_method(name, namespace)


def _scope(*, recording: bool = False, charged: bool = False,
           emergency: bool = False, dropped: bool = False) -> Any:
    calls: list[Any] = []
    scope = SimpleNamespace(
        _no_reading_samples=0,
        _no_reading_shown=False,
        _emergency_latched=emergency,
        _drop_done=dropped,
        is_roasting=recording,
        calls=calls,
        _show_no_reading_face=lambda stopped=False: calls.append(('banner', stopped)),
        _milestone_marked=lambda idx: charged and idx == 0,
    )
    scope._stop_recording_no_reading = lambda: calls.append('stop')

    def _clear() -> None:
        # the real one resets the counter before anything else; a double that
        # forgets that would let the banner fire on a machine reading fine
        scope._no_reading_samples = 0
        calls.append('clear')

    scope._clear_no_reading_face = _clear
    # run the deferred call for real, so the test follows it to its target
    deferred = SimpleNamespace(singleShot=lambda _ms, fn: fn())
    scope._track_probe_silence = MethodType(
        _method('_track_probe_silence',
                {'QTimer': deferred, '_NO_READING_SAMPLES': THRESHOLD}),
        scope,
    )
    return scope


def _go_silent(scope: Any, samples: int) -> None:
    for _ in range(samples):
        scope._track_probe_silence(False)


def test_a_brief_gap_says_nothing() -> None:
    """Devices miss samples on startup; that is not a fault worth shouting."""
    scope = _scope()
    _go_silent(scope, THRESHOLD - 1)
    assert scope.calls == []


def test_sustained_silence_is_announced() -> None:
    scope = _scope()
    _go_silent(scope, THRESHOLD)
    assert scope.calls == [('banner', False)]


def test_it_is_announced_once_not_on_every_sample() -> None:
    """The banner sits in the per-sample path: it may not repaint at 1 Hz."""
    scope = _scope()
    _go_silent(scope, THRESHOLD * 6)
    assert scope.calls == [('banner', False)]


def test_a_recording_that_measured_nothing_is_stopped() -> None:
    scope = _scope(recording=True, charged=False)
    _go_silent(scope, THRESHOLD)
    assert scope.calls == ['stop']


def test_a_charged_roast_is_never_stopped() -> None:
    """Beans are in the drum: stopping would not cool them, only lose the trace.

    A dropout after CHARGE can be a passing loss of communication, and the
    recording is worth more than the tidiness of ending it.
    """
    scope = _scope(recording=True, charged=True)
    _go_silent(scope, THRESHOLD * 3)
    assert scope.calls == [('banner', False)]
    assert 'stop' not in scope.calls


def test_a_reading_coming_back_clears_it() -> None:
    scope = _scope()
    _go_silent(scope, THRESHOLD)
    scope._track_probe_silence(True)
    assert scope.calls == [('banner', False), 'clear']


def test_the_counter_restarts_after_every_valid_reading() -> None:
    scope = _scope()
    for _ in range(4):
        _go_silent(scope, THRESHOLD - 1)
        scope._track_probe_silence(True)
    assert not any(call == ('banner', False) for call in scope.calls)


def test_the_heat_cut_keeps_the_box() -> None:
    """A latched emergency owns the panel; nothing may paint over it."""
    scope = _scope(emergency=True)
    _go_silent(scope, THRESHOLD * 2)
    assert scope.calls == []


def test_the_cooling_still_needs_the_probe() -> None:
    """The drop does not end the need for a temperature.

    The cooling is steered on the falling reading, and its automatic detection
    watches the same probe: a machine that goes quiet after the drop has to be
    reported just as loudly as one that goes quiet before it.
    """
    scope = _scope(recording=True, charged=True, dropped=True)
    _go_silent(scope, THRESHOLD)
    assert scope.calls == [('banner', False)]
    assert 'stop' not in scope.calls


class _Label:
    """Just enough QLabel for the box snapshot."""

    def __init__(self, text: str = '', style: str = '', hidden: bool = True) -> None:
        self._text, self._style, self._hidden = text, style, hidden
        self.raised = 0

    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:  # noqa: N802 - Qt API shape
        self._text = value

    def styleSheet(self) -> str:  # noqa: N802
        return self._style

    def setStyleSheet(self, value: str) -> None:  # noqa: N802
        self._style = value

    def isHidden(self) -> bool:  # noqa: N802
        return self._hidden

    def setVisible(self, visible: bool) -> None:  # noqa: N802
        self._hidden = not visible

    def show(self) -> None:
        self._hidden = False

    def hide(self) -> None:
        self._hidden = True

    def raise_(self) -> None:
        self.raised += 1

    def snapshot(self) -> tuple[str, str, bool]:
        return self._text, self._style, self._hidden


def _painted_scope(msg: _Label, container: _Label, blocks: list[_Label]) -> Any:
    scope = SimpleNamespace(
        _no_reading_shown=False,
        _no_reading_samples=0,
        _saved_face=None,
        msg_lbl=msg,
        phase_container=container,
        str_no_reading_title='TITLE',
        str_no_reading_body='BODY',
        str_no_reading_stopped='STOPPED',
        _phase_widgets=lambda: blocks,
    )
    for name in ('_show_no_reading_face', '_clear_no_reading_face'):
        setattr(scope, name, MethodType(_method(name, {'THEME': _THEME,
                                                       '_log': _LOG}), scope))
    return scope


_THEME: Final[dict[str, str]] = {
    'CRITICAL': '#F38BA8', 'CRUST': '#11111B', 'TEAL': '#94E2D5',
    'BORDER': '#313244',
}
_LOG: Final[Any] = SimpleNamespace(exception=lambda *_a, **_k: None)


def test_the_box_comes_back_exactly_as_it_was() -> None:
    """Whatever the box held is restored verbatim.

    The cooling message lives in this box, and so do the dropping, cooled and
    preheat ones. A restore that rebuilt one of them from scratch would wipe
    the other three.
    """
    msg = _Label('❄ COOLING IN PROGRESS', 'color: teal;', hidden=False)
    container = _Label(style='border: 1px solid cyan;')
    blocks = [_Label(hidden=True) for _ in range(3)]
    before = (msg.snapshot(), container.styleSheet(),
              [b.isHidden() for b in blocks])

    scope = _painted_scope(msg, container, blocks)
    scope._show_no_reading_face()
    assert msg.text() == 'TITLE\nBODY'
    assert msg.isHidden() is False

    scope._clear_no_reading_face()
    assert (msg.snapshot(), container.styleSheet(),
            [b.isHidden() for b in blocks]) == before


def test_the_phase_blocks_come_back_only_if_they_were_up() -> None:
    """Mid-roast the blocks are showing; during a preheat they are not."""
    for visible in (True, False):
        blocks = [_Label(hidden=not visible) for _ in range(3)]
        scope = _painted_scope(_Label(), _Label(), blocks)
        scope._show_no_reading_face()
        assert all(b.isHidden() for b in blocks), 'the warning stands alone'
        scope._clear_no_reading_face()
        assert [b.isHidden() for b in blocks] == [not visible] * 3


def test_the_stopped_line_is_added_only_when_it_is_true() -> None:
    scope = _painted_scope(_Label(), _Label(), [])
    scope._show_no_reading_face(stopped=True)
    assert scope.msg_lbl.text() == 'TITLE\nBODY\nSTOPPED'

from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from tilauscope.webcontrol import TilauWebControl


class _Socket:
    def __init__(self, device_id: str) -> None:
        self._tilau_device_id = device_id
        self.closed = False

    async def close(self, **_kwargs: Any) -> None:
        self.closed = True


def _control(active: _Socket) -> tuple[TilauWebControl, list[tuple[Any, str, dict]]]:
    control = TilauWebControl.__new__(TilauWebControl)
    control._controller = active._tilau_device_id
    control._controller_ws = active
    control._bridge = None
    control._controller_lease = Event()
    control._controller_lease.set()
    sent: list[tuple[Any, str, dict]] = []

    async def send(ws: Any, kind: str, payload: dict) -> None:
        sent.append((ws, kind, payload))

    control._send = send
    return control, sent


@pytest.mark.asyncio
async def test_only_the_socket_holding_the_controller_lease_can_command() -> None:
    active = _Socket('same-device')
    stale = _Socket('same-device')
    control, sent = _control(active)
    submitted: list[tuple[Any, dict, int]] = []
    control._coalesce_slider = lambda ws, payload, ref: submitted.append((ws, payload, ref))

    await control._handle_command(stale, {
        'type': 'command', 'seq': 7,
        'payload': {'action': 'set_slider', 'channel': 'slider0', 'value': 42},
    })
    await control._handle_command(active, {
        'type': 'command', 'seq': 8,
        'payload': {'action': 'set_slider', 'channel': 'slider0', 'value': 43},
    })

    assert submitted == [(active, {
        'action': 'set_slider', 'channel': 'slider0', 'value': 43,
    }, 8)]
    assert sent == [(stale, 'ack', {
        'ref_seq': 7, 'status': 'rejected', 'reason': 'NOT_CONTROLLER',
    })]


@pytest.mark.asyncio
async def test_stale_socket_cannot_release_the_active_socket_lease() -> None:
    active = _Socket('same-device')
    stale = _Socket('same-device')
    control, sent = _control(active)

    await control._handle_command(stale, {
        'type': 'command', 'seq': 9, 'payload': {'action': 'release_control'},
    })

    assert control._controller == 'same-device'
    assert control._controller_ws is active
    assert sent == [(stale, 'ack', {
        'ref_seq': 9, 'status': 'rejected', 'reason': 'NOT_CONTROLLER',
    })]


def test_deferred_slider_from_a_stale_socket_is_not_submitted(monkeypatch: Any) -> None:
    active = _Socket('same-device')
    stale = _Socket('same-device')
    control, sent = _control(active)
    submitted: list[dict] = []
    control._bridge = SimpleNamespace(submit=submitted.append)
    control._loop = None
    control._slider_timers = {}
    control._pending_slider = {'slider0': (55, 10, stale)}

    scheduled = []
    monkeypatch.setattr(asyncio, 'ensure_future', scheduled.append)
    control._flush_slider('slider0')

    assert submitted == []
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
    assert sent == [(stale, 'ack', {
        'ref_seq': 10, 'status': 'rejected', 'reason': 'NOT_CONTROLLER',
    })]


def test_disconnect_invalidates_jobs_already_queued_for_qt() -> None:
    from tilauscope.command_bridge import CommandBridge

    lease = Event()
    lease.set()
    applied: list[tuple[str, int]] = []
    completed: list[dict] = []
    bridge = CommandBridge.__new__(CommandBridge)
    bridge._apply_set_slider = lambda channel, value: applied.append((channel, value)) or {
        'status': 'ok',
    }
    job = {
        'kind': 'set_slider', 'channel': 'slider0', 'value': 60,
        'lease': lease, 'done': completed.append,
    }

    # The WS loop accepted and queued the job, then the controller disconnected
    # before Qt's event loop delivered it.
    lease.clear()
    bridge._on_job(job)

    assert applied == []
    assert completed == [{'status': 'rejected', 'reason': 'NOT_CONTROLLER'}]


def test_command_burst_is_bounded_per_socket(monkeypatch: Any) -> None:
    ws = _Socket('device')
    now = 100.0
    monkeypatch.setattr('tilauscope.webcontrol.time.monotonic', lambda: now)

    decisions = [TilauWebControl._command_rate_limited(ws) for _ in range(21)]

    assert decisions[:20] == [False] * 20
    assert decisions[20] is True

    now = 101.01
    assert TilauWebControl._command_rate_limited(ws) is False


@pytest.mark.asyncio
async def test_revoking_device_closes_all_sessions_and_cancels_its_work() -> None:
    active = _Socket('revoked-device')
    second_tab = _Socket('revoked-device')
    other = _Socket('other-device')
    control, sent = _control(active)
    control._clients = {active, second_tab, other}
    control._grace_handle = None
    control._slider_timers = {}
    control._pending_slider = {
        'slider0': (50, 11, active),
        'slider1': (60, 12, other),
    }
    old_lease = control._controller_lease

    await control._revoke_device_sessions('revoked-device')

    assert control._controller is None
    assert control._controller_ws is None
    assert old_lease is not None and not old_lease.is_set()
    assert set(control._pending_slider) == {'slider1'}
    assert active.closed and second_tab.closed
    assert not other.closed
    assert len(sent) == 2
    assert {item[0] for item in sent} == {active, second_tab}
    assert all(item[1:] == ('error', {
        'code': 'AUTH_FAILED', 'message': 'device revoked',
    }) for item in sent)

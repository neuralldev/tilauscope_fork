from __future__ import annotations

from typing import Any

import pytest

from tilauscope.webcontrol import TilauWebControl
from tilauscope.webrecords import TilauWebRecords
from tilauscope import webrecords


@pytest.mark.parametrize('server_factory', [
    lambda: TilauWebControl(0),
    lambda: TilauWebRecords(0),
])
def test_failed_startup_does_not_leak_background_loop_or_thread(
        monkeypatch: Any, server_factory: Any) -> None:
    server = server_factory()

    async def fail_startup() -> None:
        raise OSError('simulated bind failure')

    monkeypatch.setattr(server, '_startup', fail_startup)

    with pytest.raises(OSError, match='simulated bind failure'):
        server.startWeb()

    assert server._loop is None
    assert server._thread is None
    assert server._runner is None


def test_records_shutdown_is_bounded_when_aiohttp_cleanup_stalls(monkeypatch: Any) -> None:
    server = TilauWebRecords.__new__(TilauWebRecords)
    server._zeroconf = None
    server._zc_info = None

    class Loop:
        stopped = False

        @staticmethod
        def is_running() -> bool:
            return True

        def stop(self) -> None:
            self.stopped = True

        def call_soon_threadsafe(self, callback: Any) -> None:
            callback()

    class Runner:
        @staticmethod
        async def cleanup() -> None:
            return None

    class Future:
        cancelled = False
        timeout = None

        def result(self, timeout: float | None = None) -> None:
            self.timeout = timeout
            raise TimeoutError('stalled cleanup')

        def cancel(self) -> None:
            self.cancelled = True

    class Thread:
        timeout = None

        def join(self, timeout: float | None = None) -> None:
            self.timeout = timeout

        @staticmethod
        def is_alive() -> bool:
            return True

    loop, runner, future, thread = Loop(), Runner(), Future(), Thread()
    server._loop = loop
    server._runner = runner
    server._thread = thread

    def stalled(cleanup: Any, selected_loop: Any) -> Future:
        cleanup.close()  # the fake future does not own/run the coroutine
        assert selected_loop is loop
        return future

    monkeypatch.setattr('tilauscope.webrecords.asyncio.run_coroutine_threadsafe', stalled)

    server.stopWeb()

    assert future.timeout == 2
    assert future.cancelled
    assert loop.stopped
    assert thread.timeout == 2
    assert server._runner is None
    assert server._loop is None
    assert server._thread is None


def test_oversized_profile_is_rejected_before_reading(
        monkeypatch: Any, tmp_path: Any) -> None:
    profile = tmp_path / 'oversized.alog'
    profile.write_bytes(b'{}')
    monkey_size = webrecords._MAX_PROFILE_BYTES + 1

    class Stat:
        st_size = monkey_size

    monkeypatch.setattr(webrecords.Path, 'stat', lambda _self: Stat())

    assert webrecords.read_profile(str(profile)) is None

"""Clean shutdown contracts for BLE asyncio loops."""

from __future__ import annotations

import asyncio
import threading

from artisanlib.async_comm import AsyncLoopThread
from artisanlib.ble_port import BLE, ClientBLE
from tilauscope.tc4ble import _BleLoop


def _pending_coroutine(
    started: threading.Event,
    finished: threading.Event,
):  # noqa: ANN202
    async def pending() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    return pending()


def test_async_loop_stop_waits_for_task_cleanup() -> None:
    loop_thread = AsyncLoopThread()
    started = threading.Event()
    finished = threading.Event()
    future = asyncio.run_coroutine_threadsafe(
        _pending_coroutine(started, finished),
        loop_thread.loop,
    )
    assert started.wait(timeout=1.0)

    assert loop_thread.stop(timeout=2.0)

    assert finished.wait(timeout=1.0)
    assert future.done()
    assert loop_thread.loop.is_closed()


def test_shared_ble_close_cancels_operations_before_loop_shutdown() -> None:
    manager = BLE()
    started = threading.Event()
    finished = threading.Event()
    future = manager._submit_operation(_pending_coroutine(started, finished))
    assert started.wait(timeout=1.0)

    manager.close()

    assert finished.wait(timeout=1.0)
    assert future.done()
    assert manager._asyncLoopThread is None
    assert not manager._pending_futures


def test_client_stop_cancels_runner_and_joins_its_loop() -> None:
    client = ClientBLE()
    loop_thread = AsyncLoopThread()
    client._async_loop_thread = loop_thread
    client._running = True
    started = threading.Event()
    finished = threading.Event()
    client._runner_future = asyncio.run_coroutine_threadsafe(
        _pending_coroutine(started, finished),
        loop_thread.loop,
    )
    assert started.wait(timeout=1.0)

    client.stop()

    assert finished.wait(timeout=1.0)
    assert client._runner_future is None
    assert client._async_loop_thread is None
    assert loop_thread.loop.is_closed()


def test_skywalker_ble_loop_drains_tasks_before_join() -> None:
    loop_thread = _BleLoop()
    loop_thread.start()
    started = threading.Event()
    finished = threading.Event()
    future = loop_thread.submit(_pending_coroutine(started, finished))
    assert started.wait(timeout=1.0)

    assert loop_thread.stop()

    assert finished.wait(timeout=1.0)
    assert future.done()
    assert loop_thread._loop.is_closed()


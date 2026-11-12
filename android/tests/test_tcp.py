# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

import asyncio
from contextlib import aclosing
import unittest

from tilauscope_mobile.tcp import tcp_chunks
from tilauscope_mobile.tc4 import TC4Decoder


class TcpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = None
        self.handlers = set()

    async def asyncTearDown(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for task in self.handlers:
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)

    async def serve(self, handler):
        def connected(reader, writer):
            task = asyncio.create_task(handler(reader, writer))
            self.handlers.add(task)
        self.server = await asyncio.start_server(connected, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def test_local_stream_decodes_and_closes_on_eof(self):
        async def handler(reader, writer):
            try:
                writer.write(b"25,140,180\r\n25,141,181\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        port = await self.serve(handler)
        decoder = TC4Decoder()
        frames = []
        async for data in tcp_chunks("127.0.0.1", port):
            frames.extend(decoder.feed(data, generation=0))
        self.assertEqual([frame.reading.bt_c for frame in frames], [180, 181])

    async def test_timeout_closes_connection_without_sending_commands(self):
        closed = asyncio.get_running_loop().create_future()
        async def handler(reader, writer):
            try:
                closed.set_result(await reader.read())
            finally:
                writer.close()
                await writer.wait_closed()
        port = await self.serve(handler)
        with self.assertRaises(TimeoutError):
            async for _ in tcp_chunks("127.0.0.1", port, timeout_s=0.05):
                self.fail("Silent server must not produce telemetry")
        self.assertEqual(await asyncio.wait_for(closed, 2), b"")

    async def test_consumer_can_close_stream_early(self):
        closed = asyncio.get_running_loop().create_future()
        async def handler(reader, writer):
            try:
                writer.write(b"sample")
                await writer.drain()
                closed.set_result(await reader.read())
            finally:
                writer.close()
                await writer.wait_closed()
        port = await self.serve(handler)
        async with aclosing(tcp_chunks("127.0.0.1", port)) as chunks:
            self.assertEqual(await anext(chunks), b"sample")
        self.assertEqual(await asyncio.wait_for(closed, 2), b"")

    async def test_cancelled_read_closes_connection(self):
        connected = asyncio.Event()
        closed = asyncio.get_running_loop().create_future()
        async def handler(reader, writer):
            try:
                connected.set()
                closed.set_result(await reader.read())
            finally:
                writer.close()
                await writer.wait_closed()
        port = await self.serve(handler)
        async with aclosing(tcp_chunks("127.0.0.1", port)) as chunks:
            task = asyncio.create_task(anext(chunks))
            await asyncio.wait_for(connected.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(await asyncio.wait_for(closed, 2), b"")


if __name__ == "__main__":
    unittest.main()

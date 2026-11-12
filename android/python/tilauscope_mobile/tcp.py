# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Read-only TCP byte stream for bench integration, not a roaster protocol."""

import asyncio
from collections.abc import AsyncIterator

from .session import finite


async def tcp_chunks(host: str, port: int, *, timeout_s: float = 3.0) -> AsyncIterator[bytes]:
    """Yield bounded chunks; EOF, timeout and cancellation close the socket.

    Caller owns protocol decoding and reconnect policy. No commands are sent.
    Use contextlib.aclosing when stopping consumption before EOF.
    """
    if not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("A host and valid TCP port are required")
    if not finite(timeout_s) or timeout_s <= 0:
        raise ValueError("Timeout must be finite and positive")
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
    try:
        while chunk := await asyncio.wait_for(reader.read(4096), timeout_s):
            yield chunk
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout_s)
        except (OSError, TimeoutError):
            pass

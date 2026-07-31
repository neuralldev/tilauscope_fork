# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# TiLau 2026

"""A printer on the other end of the wire, without the wire.

The Niimbot exchange is a *sequence*, and the sequence is the part that broke:
the D110M V4 firmware burns the label after ``pageEnd``, so cutting in with
``printEnd`` too early ejects a blank one. Nothing about a single packet is
wrong in that failure — every byte is well formed and the printer answers
politely. Only the order is wrong.

So this double records order. It replaces the two methods that touch Bluetooth,
keeps every byte of protocol code above them running for real, and answers each
request the way a printer that has finished its page would.
"""

from __future__ import annotations

from typing import Any, Final

#: Request codes, mirrored from ``Niimprint_RequestCodeEnum`` by value so the
#: expectations read as the protocol does rather than as an import graph.
#: Any drift is caught by :func:`assert_codes_match_the_enum`.
CODE_NAMES: Final[dict[int, str]] = {
    0x21: 'setDensity',
    0x23: 'setLabelType',
    0x01: 'printStart',
    0x03: 'pageStart',
    0x13: 'setPageSize',
    0xA3: 'printStatus',
    0xE3: 'pageEnd',
    0xF3: 'printEnd',
    0xDC: 'heartbeat',
    0x85: 'imageData',
    0x84: 'imageData',
    0x83: 'imageData',
}


class RecordingPrinter:
    """Records every request the driver sends, and answers plausibly.

    ``sent`` is the full trace as request codes. :attr:`sequence` collapses the
    image-data burst into one entry, because a sequence assertion cares that the
    pixels went out between ``setPageSize`` and ``pageEnd``, not that there were
    three hundred of them.
    """

    def __init__(self, status_pages: int = 1) -> None:
        self.sent: list[int] = []
        self.raw: list[bytes] = []
        #: What the status poll reports back. Set to 0 to simulate a printer
        #: still burning the label, which must not let the driver move on.
        self.status_pages = status_pages

    # ── the two methods that would touch Bluetooth ───────────────────────────

    def send(self, message: bytes, chunk: int = 0) -> None:  # noqa: ARG002
        self.raw.append(bytes(message))
        if len(message) > 2:
            self.sent.append(message[2])

    def transceive(self, reqcode: int, data: bytes = b'',
                   respoffset: int = 1, **_: Any) -> Any:
        """Answer a request/response exchange with a generic success packet."""
        self.sent.append(int(reqcode))
        self.raw.append(bytes(data))
        return _Reply(int(reqcode) + respoffset, b'\x01')

    # ── readable views ───────────────────────────────────────────────────────

    @property
    def sequence(self) -> list[str]:
        """The trace as protocol step names, consecutive image data collapsed."""
        names = [CODE_NAMES.get(c, f'0x{c:02x}') for c in self.sent]
        out: list[str] = []
        for name in names:
            if name == 'imageData' and out and out[-1] == 'imageData':
                continue
            out.append(name)
        return out

    def index_of(self, step: str) -> int:
        """Position of a step in the sequence, or -1. Used for ordering asserts."""
        seq = self.sequence
        return seq.index(step) if step in seq else -1


class _Reply:
    """The shape ``_transceive`` returns: a packet with a type and a body."""

    __slots__ = ('data', 'type')

    def __init__(self, type_: int, data: bytes) -> None:
        self.type = type_
        self.data = data


def install(printer_obj: Any, recorder: RecordingPrinter) -> None:
    """Redirect a real ``NiimbotBLE`` onto the recorder.

    Only the transport is replaced. ``_print_image_locked`` — the packet
    building, the padding maths, the ordering, the status wait — runs unmodified,
    which is the whole point: a double that reimplemented the sequence would
    agree with itself no matter what the driver did.
    """
    printer_obj.send = recorder.send
    printer_obj._transceive = recorder.transceive

    # The status wait blocks on a notification that will never arrive here.
    # Report the page count the recorder was configured with, so a test can
    # choose between "printer finished" and "printer still busy".
    def _wait(total_pages: int = 1, **_: Any) -> bool:
        recorder.sent.append(0xA3)
        return recorder.status_pages >= total_pages

    printer_obj._wait_print_finished_by_status = _wait


def assert_codes_match_the_enum(enum_cls: Any) -> None:
    """Guard the mirror: :data:`CODE_NAMES` restates the driver's own values.

    A mirrored table is a second copy, and a second copy drifts. Rather than
    import the enum into the expectations and lose the ability to see a rename,
    the two are compared once, here.
    """
    expected = {
        'setDensity': enum_cls.SET_LABEL_DENSITY,
        'setLabelType': enum_cls.SET_LABEL_TYPE,
        'printStart': enum_cls.START_PRINT,
        'setPageSize': enum_cls.SET_DIMENSION,
        'printStatus': enum_cls.GET_PRINT_STATUS,
        'pageEnd': enum_cls.END_PAGE_PRINT,
        'printEnd': enum_cls.END_PRINT,
    }
    wrong = {
        name: (hex(value), hex(code))
        for name, value in expected.items()
        for code, mapped in CODE_NAMES.items()
        if mapped == name and code != int(value)
    }
    missing = {
        name: hex(value) for name, value in expected.items()
        if int(value) not in CODE_NAMES
    }
    assert not wrong and not missing, (
        f'CODE_NAMES no longer matches Niimprint_RequestCodeEnum — '
        f'wrong: {wrong}, missing: {missing}'
    )

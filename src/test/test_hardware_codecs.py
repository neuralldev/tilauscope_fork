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

"""Hardware protocols, exercised without the hardware.

The transport is never tested here — Bluetooth is not ours and a test that
needed a printer in the room would be run once. What is tested is everything
above it: how bytes are framed, how a reading is decoded, and in what order the
steps of an exchange go out.

That last one earns its place. The blank-label bug was not a malformed packet;
every byte was correct and the printer answered politely. The D110M V4 firmware
burns the label *after* ``pageEnd``, so cutting in with ``printEnd`` before it
has finished ejects a blank one. Only the order was wrong, and no amount of
packet-level checking would have seen it.
"""

from __future__ import annotations

from typing import Any, Final

import fake_link
import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.usefixtures('qapp')


@pytest.fixture(scope='module')
def niimprint() -> Any:
    """The printer driver. Imports without pulling ``artisanlib.main``."""
    from tilauscope import niimprint as module

    return module


# ── Niimbot packet codec ─────────────────────────────────────────────────────

def test_packet_round_trips(niimprint: Any) -> None:
    """What is serialised must come back identical."""
    packet = niimprint.NiimbotPacket(0x85, b'\x01\x02\x03\xff')
    back = niimprint.NiimbotPacket.from_bytes(packet.to_bytes())
    assert back.get_type() == 0x85
    assert back.get_data() == b'\x01\x02\x03\xff'


@given(
    type_=st.integers(min_value=0, max_value=0xFF),
    data=st.binary(min_size=0, max_size=200),
)
def test_any_packet_round_trips(type_: int, data: bytes) -> None:
    """The round trip holds for every type and every body, including empty.

    Body length goes in a single byte, so 255 is the ceiling; 200 keeps the
    property inside the range the driver actually produces.
    """
    from tilauscope.niimprint import NiimbotPacket

    back = NiimbotPacket.from_bytes(NiimbotPacket(type_, data).to_bytes())
    assert (back.get_type(), back.get_data()) == (type_, data)


def test_frame_layout_is_what_the_printer_expects(niimprint: Any) -> None:
    """``55 55 | type | len | data | xor | AA AA`` — pinned byte by byte.

    The layout is the contract with a device that cannot be updated from here.
    Spelling it out means a change to the framing shows up as a diff on an
    expectation rather than as a printer that has gone quiet.
    """
    raw = niimprint.NiimbotPacket(0x21, b'\x03').to_bytes()
    assert raw[0:2] == b'\x55\x55', 'preamble'
    assert raw[2] == 0x21, 'request code'
    assert raw[3] == 1, 'body length'
    assert raw[4:5] == b'\x03', 'body'
    assert raw[5] == 0x21 ^ 1 ^ 0x03, 'checksum is xor of type, length and body'
    assert raw[6:8] == b'\xaa\xaa', 'trailer'
    assert len(raw) == 8


@pytest.mark.parametrize(
    ('corrupt', 'why'),
    [
        (lambda b: b'\x00' + b[1:], 'preamble'),
        (lambda b: b[:-1] + b'\x00', 'ending'),
        (lambda b: b[:5] + bytes([b[5] ^ 0xFF]) + b[6:], 'checksum'),
    ],
)
def test_a_corrupted_frame_is_refused(niimprint: Any, corrupt: Any, why: str) -> None:
    """A bad frame raises rather than decoding into a plausible lie.

    Silence here would be worse than an exception: the driver reads label
    dimensions and paper type out of these replies, and a body accepted on a
    broken checksum feeds wrong numbers into the print geometry.
    """
    raw = niimprint.NiimbotPacket(0x21, b'\x03').to_bytes()
    with pytest.raises(ValueError, match=why):
        niimprint.NiimbotPacket.from_bytes(corrupt(raw))


# ── the print sequence ───────────────────────────────────────────────────────

def _printer(niimprint: Any, recorder: fake_link.RecordingPrinter) -> Any:
    """A real driver with a recorder where its Bluetooth link would be."""
    obj = niimprint.NiimbotBLE()
    obj.paper_height = 0          # 0 = unknown, skips the physical-size padding

    heartbeat = niimprint.NiimbotHeartbeat()
    heartbeat.valid = True
    heartbeat.paperstate = 0      # cover closed
    heartbeat.closingstate = 0
    obj.get_heartbeat = lambda: heartbeat

    fake_link.install(obj, recorder)
    return obj


@pytest.fixture
def printed(niimprint: Any) -> fake_link.RecordingPrinter:
    """One completed print of a small label, with the exchange recorded."""
    from PIL import Image

    recorder = fake_link.RecordingPrinter(status_pages=1)
    _printer(niimprint, recorder).print_image(
        Image.new('1', (96, 16), 1), density=3,
        labelsize=niimprint.Niimprint_PaperType.WITH_GAPS,
    )
    return recorder


def test_the_mirrored_request_codes_still_match(niimprint: Any) -> None:
    """Guard the guard: the expectations below name steps, not numbers."""
    fake_link.assert_codes_match_the_enum(niimprint.Niimprint_RequestCodeEnum)


def test_the_page_is_never_cut_before_the_printer_has_finished(
    printed: fake_link.RecordingPrinter,
) -> None:
    """The regression itself: ``pageEnd`` → status poll → ``printEnd``.

    Between those two the D110M V4 is physically burning the label. Sending
    ``printEnd`` in that window ejects a blank one — the printer reports no
    error, the driver reports success, and the user gets a white sticker.
    """
    page_end = printed.index_of('pageEnd')
    print_end = printed.index_of('printEnd')
    assert page_end >= 0 and print_end >= 0, (
        f'the print did not complete: {printed.sequence}'
    )
    polls_between = [
        i for i, step in enumerate(printed.sequence)
        if step == 'printStatus' and page_end < i < print_end
    ]
    assert polls_between, (
        'printEnd follows pageEnd with no status poll in between. The firmware '
        'burns the label during that window, so cutting in early ejects a blank '
        f'one. Sequence was: {printed.sequence}'
    )


def test_the_d110m_v4_sequence_is_in_the_documented_order(
    printed: fake_link.RecordingPrinter,
) -> None:
    """Density, label type, printStart, status, page size, pixels, then the end.

    Pinned as an order rather than as an exact list: the assertion should survive
    an added step and fail on a reordered one.
    """
    expected: Final[list[str]] = [
        'setDensity', 'setLabelType', 'printStart', 'printStatus',
        'setPageSize', 'imageData', 'pageEnd', 'printEnd',
    ]
    positions = {step: printed.index_of(step) for step in expected}
    missing = [step for step, i in positions.items() if i < 0]
    assert not missing, f'missing from the exchange: {missing} — {printed.sequence}'

    out_of_order = [
        (a, b) for a, b in zip(expected, expected[1:], strict=False)
        if positions[a] > positions[b]
    ]
    assert not out_of_order, (
        f'steps out of order: {out_of_order}\nsequence: {printed.sequence}'
    )


def test_no_page_start_in_the_v4_flow(printed: fake_link.RecordingPrinter) -> None:
    """``pageStart`` belongs to the older firmware and desynchronises this one."""
    assert 'pageStart' not in printed.sequence, (
        'pageStart (0x03) is back in the flow — the D110M V4 firmware does not '
        'expect it and the page comes out blank.'
    )


def test_every_pixel_packet_is_written_on_its_own(
    printed: fake_link.RecordingPrinter, niimprint: Any,
) -> None:
    """One packet per BLE write. Grouping them desynchronises the firmware.

    Each raw write must be exactly one well-formed packet — concatenating two,
    or splitting one across writes, is what the current firmware cannot follow.
    """
    for raw in printed.raw:
        if len(raw) > 2 and raw[0:2] == b'\x55\x55':
            packet = niimprint.NiimbotPacket.from_bytes(raw)
            assert len(raw) == len(packet.to_bytes()), (
                f'a BLE write carried more than one packet: {raw[:12].hex()}…'
            )


def test_the_print_trace_stays_off_and_writes_nothing(niimprint: Any) -> None:
    """The TX/RX tracer appends to ``~/Downloads`` and must stay opt-in.

    It is switched on with ``TILAU_NIIMBOT_TRACE=1`` for a debugging session.
    Left on by accident it would silently grow a file in the user's Downloads
    folder on every label they print — so the print is run here and the file is
    measured before and after, rather than merely inspected.
    """
    import os
    from pathlib import Path

    from PIL import Image

    assert 'TILAU_NIIMBOT_TRACE' not in os.environ, (
        'the tracer is enabled in this environment; the check below would be '
        'measuring the debug path, not the default one'
    )
    trace = Path.home() / 'Downloads' / 'tilau_print_trace.txt'
    before = trace.stat().st_size if trace.exists() else None

    recorder = fake_link.RecordingPrinter(status_pages=1)
    _printer(niimprint, recorder).print_image(
        Image.new('1', (96, 16), 1), density=3,
        labelsize=niimprint.Niimprint_PaperType.WITH_GAPS,
    )

    after = trace.stat().st_size if trace.exists() else None
    assert after == before, (
        f'printing wrote to {trace} with the tracer off ({before} -> {after} '
        'bytes). That file grows on every label the user prints.'
    )


# ── label text ───────────────────────────────────────────────────────────────

def test_label_text_keeps_the_micro_sign() -> None:
    """Grind sizes print as ``µm``; NFKD would turn µ into a Greek mu.

    The A101 fonts in the printer do not carry that glyph, so the label comes
    out with an empty box where the unit should be. The label path therefore has
    its own NFD stripper, and this is what keeps the two from being merged.
    """
    from tilauscope.label_printer import _brew_clean

    cleaned = _brew_clean('Café 250 µm à 93 °C')
    assert 'µm' in cleaned, (
        f'the micro sign did not survive: {cleaned!r}. NFD keeps µ; NFKD '
        'decomposes it to a Greek mu the printer fonts cannot draw.'
    )
    assert '°C' in cleaned, 'the degree sign must survive too'
    assert 'Cafe' in cleaned, 'accents are still stripped'


def test_the_general_accent_stripper_is_the_one_that_breaks_micro() -> None:
    """Characterises *why* there are two strippers, so nobody merges them.

    This is not a bug report — the general helper is fine for its own callers.
    It is the reason the label path may not use it, written down where a future
    tidy-up will trip over it.
    """
    from tilauscope.label_printer import _brew_clean
    from tilauscope.tilauscope_types import replace_accents

    assert replace_accents('250 µm') != _brew_clean('250 µm'), (
        'the two accent strippers now agree on µ. If replace_accents was fixed, '
        'merge them deliberately and delete this test; if _brew_clean was '
        'pointed at it, labels are about to print a blank box.'
    )


# ── MQTT cache ───────────────────────────────────────────────────────────────

def test_mqtt_cache_returns_the_last_value_per_topic() -> None:
    """Topics are independent and the newest value wins."""
    from tilauscope.mqttbridge import MQTTDatabase

    db = MQTTDatabase()
    db.update('tilau/ambient/temp', 21.4)
    db.update('tilau/ambient/hum', 55.0)
    db.update('tilau/ambient/temp', 21.9)

    assert db.get_value('tilau/ambient/temp') == 21.9
    assert db.get_value('tilau/ambient/hum') == 55.0


def test_an_unknown_topic_reads_as_none_rather_than_raising() -> None:
    """The sampling loop polls on a timer and must not raise on a silent sensor.

    A sensor that has published nothing yet is the normal state for the first
    seconds after connecting, and an exception on that path would surface inside
    Artisan's 1 Hz loop.
    """
    from tilauscope.mqttbridge import MQTTDatabase

    assert MQTTDatabase().get_value('tilau/never/published') is None


def test_a_falsy_reading_is_still_a_reading() -> None:
    """Zero is a plausible measurement, not a missing one.

    ``0`` for a fan at rest or ``0.0`` for a RoR at the turning point must not
    be reported as "no value" by a truthiness test somewhere in the chain.
    """
    from tilauscope.mqttbridge import MQTTDatabase

    db = MQTTDatabase()
    db.update('tilau/fan/speed', 0)
    assert db.get_value('tilau/fan/speed') == 0
    assert db.get_value('tilau/fan/speed') is not None

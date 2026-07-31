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

"""Codec checks that have to run in their own process.

``difluid`` and ``tilauambient`` import ``artisanlib.main`` at module scope.
Two things follow, and either is enough on its own:

* the import runs a settings migration that writes to the real Artisan
  preferences — contained by the sandbox, but only because the sandbox is
  installed first;
* Artisan's single-instance guard calls ``sys.exit(0)`` *during* that import
  when another Artisan is already running. In the pytest process that would end
  the whole session, and whether it happens depends on whether the developer
  happens to have the application open.

So these run here, in a child, exactly like the import portico. The results come
back as JSON so the parent can report one pytest failure per check instead of a
wall of subprocess output.

Run directly for a quick look: ``python test/codecs_child.py``.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))          # _guard and friends
sys.path.insert(0, str(_HERE.parent))   # the `tilauscope` package itself

import _guard  # noqa: E402  # before anything can touch Qt settings

CHECKS: dict[str, object] = {}


def check(fn):  # noqa: ANN001, ANN201
    CHECKS[fn.__name__] = fn
    return fn


# ── DiFluid / Airwave framing ────────────────────────────────────────────────

def _difluid():  # noqa: ANN202
    from tilauscope.difluid import AirwaveCommands, AirwaveFunctions, DiFluidProtocol

    return DiFluidProtocol(), AirwaveFunctions, AirwaveCommands


@check
def difluid_round_trip() -> None:
    """A built message parses back to the same fields."""
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01\x02')
    parsed = proto.parse_full_message(raw)
    assert parsed['valid'], parsed
    assert parsed['function'] == int(funcs.DEVICEACTIONS)
    assert parsed['command'] == int(cmds.TEMPERATURE)
    assert parsed['data'] == b'\x01\x02'
    assert parsed['length'] == 2


@check
def difluid_frame_layout() -> None:
    """``df df | function | command | length | data | sum&0xFF`` — pinned."""
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\xaa')
    assert raw[0:2] == b'\xdf\xdf', 'preamble'
    assert raw[2] == int(funcs.DEVICEACTIONS)
    assert raw[3] == int(cmds.TEMPERATURE)
    assert raw[4] == 1, 'declared body length'
    assert raw[5] == 0xAA, 'body'
    assert raw[6] == (sum(raw[:6]) & 0xFF), 'checksum is the byte sum of all that precedes'
    assert len(raw) == 7


@check
def difluid_rejects_a_bad_checksum() -> None:
    """A corrupted reading must not decode into a plausible temperature."""
    proto, funcs, cmds = _difluid()
    raw = bytearray(proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01'))
    raw[-1] ^= 0xFF
    parsed = proto.parse_full_message(bytes(raw))
    assert not parsed['valid'], 'a wrong checksum was accepted'
    assert 'hecksum' in parsed['error'], parsed


@check
def difluid_rejects_a_truncated_message() -> None:
    """BLE notifications arrive in chunks; a partial frame must not be read."""
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01\x02\x03\x04')
    for cut in range(1, len(raw)):
        parsed = proto.parse_full_message(raw[:cut])
        assert not parsed.get('valid'), f'a {cut}-byte fragment parsed as valid'


@check
def difluid_splits_a_stream_into_messages() -> None:
    """Two replies arriving in one notification are separated again."""
    proto, funcs, cmds = _difluid()
    a = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01')
    b = proto.build_full_message(funcs.DEVICEACTIONS, cmds.STATUS, b'\x02')
    parts = proto.parse_messages_by_delimiter(a + b)
    assert len(parts) == 2, f'expected 2 messages, got {len(parts)}: {parts}'
    assert all(proto.parse_full_message(p)['valid'] for p in parts), parts


@check
def difluid_body_may_contain_the_preamble() -> None:
    """A body carrying ``df df`` is one frame, not two.

    The frame declares its own length, so the walk never has to guess where it
    ends. Splitting on the preamble did have to guess, and got it wrong here.
    """
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\xdf\xdf\x01')
    parts = proto.parse_messages_by_delimiter(raw)
    assert len(parts) == 1, f'a body containing the preamble was cut up: {parts}'
    parsed = proto.parse_full_message(parts[0])
    assert parsed['valid'], parsed
    assert parsed['data'] == b'\xdf\xdf\x01', parsed['data']


@check
def difluid_reads_the_temperature_that_used_to_be_lost() -> None:
    """111.936 °C — the reading that exposed the framing bug.

    It encodes as ``3B DF DF 42``. The old splitter saw the two middle bytes as
    a frame boundary, cut the reply in half, failed both checksums and dropped
    the measurement; the caller then reported −1.0 °C as if it were a reading.
    """
    proto, funcs, cmds = _difluid()
    body = struct.pack('<ff', 111.936, 25.0)
    assert b'\xdf\xdf' in body, 'the sample value no longer encodes the trap'

    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, body)
    parts = proto.parse_messages_by_delimiter(raw)
    assert len(parts) == 1, f'the reply was cut into {len(parts)} pieces'
    parsed = proto.parse_full_message(parts[0])
    assert parsed['valid'], parsed
    catalyst, inlet = struct.unpack('<ff', parsed['data'])
    assert round(catalyst, 3) == 111.936, catalyst
    assert inlet == 25.0, inlet


@check
def difluid_framing_is_independent_of_body_content() -> None:
    """One frame in, one frame out — whatever the bytes inside.

    This is the invariant, and it is stronger than sweeping temperatures: the
    old splitter was not wrong about floats, it was wrong about *content*. A
    float body was simply the first place the codebase happened to put a byte
    pattern it could not survive.

    So the body is made adversarial on purpose — the preamble planted at every
    position, at every length, alone and repeated — rather than sampled from a
    range and hoped to be representative.
    """
    proto, funcs, cmds = _difluid()
    bodies: list[bytes] = [b'', b'\xdf', b'\xdf\xdf', b'\xdf\xdf\xdf\xdf']
    for length in range(2, 17):
        for pos in range(length - 1):
            filler = bytes((i * 37 + 5) & 0xFF for i in range(length))
            bodies.append(filler[:pos] + b'\xdf\xdf' + filler[pos + 2:])

    for body in bodies:
        raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, body)
        parts = proto.parse_messages_by_delimiter(raw)
        assert len(parts) == 1, (
            f'body {body.hex()} was cut into {len(parts)} pieces'
        )
        parsed = proto.parse_full_message(parts[0])
        assert parsed['valid'] and parsed['data'] == body, (
            f'body {body.hex()} came back as {parsed}'
        )


@check
def difluid_splits_a_stream_of_adversarial_frames() -> None:
    """Several frames in one notification, each carrying the preamble inside.

    The two properties have to hold together: a body that looks like a boundary
    must not create one, and a real boundary must still be found right after it.
    """
    proto, funcs, cmds = _difluid()
    frames = [
        proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, body)
        for body in (b'\xdf\xdf', b'\x01\xdf\xdf\x02', b'', b'\xdf\xdf\xdf')
    ]
    parts = proto.parse_messages_by_delimiter(b''.join(frames))
    assert parts == frames, (
        f'expected {len(frames)} frames back unchanged, got {len(parts)}: '
        f'{[p.hex() for p in parts]}'
    )


@check
def difluid_skips_leading_noise() -> None:
    """Bytes before the first preamble are not a frame and are discarded."""
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.STATUS, b'\x02')
    parts = proto.parse_messages_by_delimiter(b'\x00\x11\x22' + raw)
    assert len(parts) == 1 and parts[0] == raw, parts


@check
def difluid_drops_a_truncated_tail() -> None:
    """A frame cut short by the notification boundary is not half-read.

    There is no reassembly buffer here, so an incomplete frame can only be
    dropped. What matters is that it is dropped whole rather than parsed as if
    the missing bytes were zeros.
    """
    proto, funcs, cmds = _difluid()
    raw = proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01\x02\x03\x04')
    for cut in range(2, len(raw)):
        parts = proto.parse_messages_by_delimiter(raw[:cut])
        assert not parts or all(
            not proto.parse_full_message(p)['valid'] for p in parts
        ), f'a {cut}-byte fragment was delivered as a valid frame: {parts}'


@check
def difluid_resyncs_after_a_corrupted_length() -> None:
    """A good frame behind a bad one is still delivered.

    A corrupted length byte claims more bytes than arrived. Stopping there would
    throw away whatever follows, so the walk falls back to looking for the next
    preamble.
    """
    proto, funcs, cmds = _difluid()
    good = proto.build_full_message(funcs.DEVICEACTIONS, cmds.STATUS, b'\x02')
    broken = bytearray(proto.build_full_message(funcs.DEVICEACTIONS, cmds.TEMPERATURE, b'\x01'))
    broken[4] = 0xFE          # declares 254 bytes of body that never arrive

    parts = proto.parse_messages_by_delimiter(bytes(broken) + good)
    valid = [p for p in parts if proto.parse_full_message(p)['valid']]
    assert good in valid, (
        f'the frame behind the corrupted one was lost: {parts}'
    )


# ── TilauAmbient: the ESP32 probe wire format ────────────────────────────────

def _ambient_frame(temp_x10: int, hum_x10: int = 500,
                   press_x10: int = 10132, alt_x10: int = 1200) -> bytearray:
    """Build a probe frame the way the firmware packs it."""
    body = struct.pack('<hhii', temp_x10, hum_x10, press_x10, alt_x10)
    checksum = sum(body) & 0xFF
    return bytearray(b'\x55\x55' + body + bytes([checksum]) + b'\xaa\xaa')


def _ambient():  # noqa: ANN202
    from tilauscope.tilauambient import TilauAmbientProtocol

    return TilauAmbientProtocol()


@check
def ambient_frame_is_seventeen_bytes() -> None:
    """The layout mirrors a packed C struct; its size is part of the contract."""
    frame = _ambient_frame(215)
    assert len(frame) == 17, f'frame is {len(frame)} bytes, firmware packs 17'
    assert frame[0:2] == b'\x55\x55' and frame[15:17] == b'\xaa\xaa'


@check
def ambient_decodes_a_normal_reading() -> None:
    """21.5 °C, 50 % RH, 1013.2 hPa, 120.0 m — tenths on the wire."""
    data = _ambient().parse_full_message(_ambient_frame(215, 500, 10132, 1200))
    assert data.valid, 'a well-formed frame was rejected'
    assert (data.temperature, data.humidity) == (21.5, 50.0), (data.temperature, data.humidity)
    assert data.pressure == 1013.2, data.pressure
    assert data.altitude == 120.0, data.altitude


@check
def ambient_temperature_is_signed() -> None:
    """A cellar below zero must read below zero, not as 6 500 °C.

    The field is ``int16``. Reading it unsigned turns −5.0 °C into 6 553.1 °C,
    which the plausibility gate then throws away — so a winter roast would lose
    its ambient reading entirely rather than fail loudly.
    """
    data = _ambient().parse_full_message(_ambient_frame(-50))
    assert data.valid, 'a sub-zero reading was rejected'
    assert data.temperature == -5.0, data.temperature


@check
def ambient_rejects_a_bad_checksum() -> None:
    frame = _ambient_frame(215)
    frame[14] ^= 0xFF
    assert not _ambient().parse_full_message(frame).valid, (
        'a corrupted probe frame was accepted'
    )


@check
def ambient_rejects_wrong_header_or_footer() -> None:
    for offset in (0, 15):
        frame = _ambient_frame(215)
        frame[offset] ^= 0xFF
        assert not _ambient().parse_full_message(frame).valid, (
            f'a frame with a broken marker at byte {offset} was accepted'
        )


@check
def ambient_rejects_a_short_frame() -> None:
    assert not _ambient().parse_full_message(_ambient_frame(215)[:10]).valid


@check
def ambient_gates_implausible_temperatures() -> None:
    """Outside −10..50 °C the whole reading is dropped, not clamped.

    A wild value is a fault, and a clamped fault looks exactly like a real
    measurement to everything downstream — including the roast plan, which
    adjusts the charge temperature on ambient conditions.
    """
    proto = _ambient()
    for temp_x10, expected in ((-100, True), (500, True), (-101, False), (501, False)):
        data = proto.parse_full_message(_ambient_frame(temp_x10))
        assert data.valid is expected, (
            f'{temp_x10 / 10:.1f} °C: valid={data.valid}, expected {expected}'
        )


# ── TilauAmbient: the acoustic crack counter ─────────────────────────────────

def _audio_frame(counter: int) -> bytearray:
    body = struct.pack('<i', counter)
    return bytearray(b'\x55\x55' + body + bytes([sum(body) & 0xFF]) + b'\xaa\xaa')


def _audio():  # noqa: ANN202
    from tilauscope.tilauambient import TilauAudioProtocol

    return TilauAudioProtocol()


@check
def audio_frame_is_nine_bytes() -> None:
    """Nine, not seven: the counter went from ``int16`` to ``int32`` in firmware.

    A parser still reading the old width would decode the checksum byte as part
    of the count and report thousands of cracks.
    """
    assert len(_audio_frame(0)) == 9
    assert _audio().AUDIO_STRUCT_SIZE == 9


@check
def audio_counts_beyond_the_old_sixteen_bit_ceiling() -> None:
    """A first crack can run long; 40 000 pops must not wrap to a negative."""
    data = _audio().parse_full_message_audio(_audio_frame(40_000))
    assert data.validity, 'a large but legitimate count was rejected'
    assert data.counter == 40_000, data.counter


@check
def audio_rejects_a_bad_checksum() -> None:
    frame = _audio_frame(120)
    frame[6] ^= 0xFF
    assert not _audio().parse_full_message_audio(frame).validity


@check
def audio_rejects_a_short_frame() -> None:
    assert not _audio().parse_full_message_audio(_audio_frame(120)[:6]).validity


# ── runner ───────────────────────────────────────────────────────────────────

def main() -> None:
    sandbox = sys.argv[1] if len(sys.argv) > 1 else None
    _guard.install(sandbox)

    results: dict[str, str | None] = {}
    for name, fn in CHECKS.items():
        try:
            fn()
            results[name] = None
        except BaseException:  # noqa: BLE001  # a check must never abort the run
            results[name] = traceback.format_exc(limit=4)

    if sandbox:
        _guard.verify(sandbox)

    if sys.stdout.isatty():   # run by hand: show something readable
        for name, failure in results.items():
            mark = 'ok  ' if failure is None else 'FAIL'
            sys.stdout.write(f'{mark}  {name}\n')
            if failure:
                sys.stdout.write('      ' + failure.strip().splitlines()[-1] + '\n')
        failed = sum(1 for f in results.values() if f)
        sys.stdout.write(f'\n{len(results) - failed} passed, {failed} failed\n')

    sys.stdout.write('---JSON---\n' + json.dumps(results))
    sys.stdout.flush()
    sys.stderr.flush()
    # artisanlib.main leaves non-daemon threads running, so a normal return
    # would hang here. Same reason, same fix, as the import portico.
    os._exit(0)


if __name__ == '__main__':
    main()

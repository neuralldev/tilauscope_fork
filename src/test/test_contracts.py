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

"""The remote-control protocol, held to what it says it is.

``v1`` is declared frozen. Freezing a protocol in a document only works if
something notices when the code stops matching it, and here there are three
copies to keep in step: the document, the Python server, and the JavaScript
client embedded in ``webclient.py``.

The client is the reason this matters more than usual. It is a home-screen PWA
served over plain ``http://`` on the LAN — no service worker, no update channel.
Once installed on the phone it keeps the build it was installed with. A rename
on the desktop side does not break the client loudly; it makes one branch stop
matching, forever, on a device the desktop cannot reach.

Every check below compares two independent statements of the same fact. Nothing
here restates the protocol in Python — that would just be a fourth copy to
forget to update.
"""

from __future__ import annotations

import json
import types
from typing import Any, Final

import protocol_contract as P
import pytest

#: Envelope keys, §4. Every message carries these and nothing else.
ENVELOPE_KEYS: Final[frozenset[str]] = frozenset({'v', 'type', 'seq', 'ts', 'payload'})

#: Keys a ``welcome`` must carry for the client to be able to draw its UI, §5.
WELCOME_KEYS: Final[frozenset[str]] = frozenset({
    'session_id', 'roaster', 'unit', 'role', 'channels', 'controls',
})

#: Keys of one entry of ``welcome.channels``, §5.
CHANNEL_KEYS: Final[frozenset[str]] = frozenset({
    'id', 'label', 'status', 'min', 'max', 'step', 'unit',
})

#: Keys a ``snapshot`` must carry, §5.
SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset({
    'phase', 'charge_marked', 'clock', 'series', 'markers', 'sliders',
})

#: Parallel arrays inside ``snapshot.series``, §5.
SERIES_KEYS: Final[frozenset[str]] = frozenset({'t', 'bt', 'et', 'ror'})


@pytest.fixture(scope='module')
def webcontrol() -> Any:
    """The server module. Imports cleanly — it never pulls ``artisanlib.main``."""
    from tilauscope import webcontrol as module

    return module


# ── the frozen version ───────────────────────────────────────────────────────

def test_protocol_version_is_still_1(webcontrol: Any) -> None:
    """Invariant 5: ``v`` is immutable — any change of shape is ``v:2``.

    Bumping this constant is a legitimate thing to do one day. It is not a
    legitimate thing to do *quietly*, because every installed client negotiates
    on it via ``proto_min``/``proto_max`` and a bump without that negotiation
    locks every phone out at the handshake.
    """
    assert webcontrol.PROTO_VERSION == 1, (
        'PROTO_VERSION changed. If v2 is really starting, the version negotiation '
        'and the client build have to move with it — see §5 handshake and §10.'
    )


def test_the_envelope_carries_exactly_the_contract_keys(webcontrol: Any) -> None:
    """§4: ``{v, type, seq, ts, payload}``, no more and no less.

    Built through the real method with a stand-in holding only the sequence
    counter, so nothing is constructed, no socket is opened, and the test still
    exercises the code that actually serialises every message.
    """
    stub = types.SimpleNamespace(_seq=0)
    raw = webcontrol.TilauWebControl._envelope(stub, 'heartbeat', {'clock': 12.0})
    message = json.loads(raw)

    assert set(message) == ENVELOPE_KEYS, (
        f'envelope keys are {sorted(message)}, contract says {sorted(ENVELOPE_KEYS)}'
    )
    assert message['v'] == webcontrol.PROTO_VERSION
    assert message['type'] == 'heartbeat'
    assert message['payload'] == {'clock': 12.0}
    assert isinstance(message['ts'], float), '§4: ts is epoch seconds'


def test_seq_is_monotonic_per_sender(webcontrol: Any) -> None:
    """§4: ``seq`` is a per-sender counter — the client uses it to order acks."""
    stub = types.SimpleNamespace(_seq=0)
    seqs = [
        json.loads(webcontrol.TilauWebControl._envelope(stub, 'telemetry', {}))['seq']
        for _ in range(5)
    ]
    assert seqs == sorted(set(seqs)), f'seq is not strictly increasing: {seqs}'


# ── desktop ↔ phone ──────────────────────────────────────────────────────────

def test_the_client_handles_every_message_the_desktop_sends() -> None:
    """A type with no branch on the phone is a message that vanishes."""
    missing = P.server_message_types() - P.client_handled_types()
    assert not missing, (
        f'the desktop sends {sorted(missing)} but the client has no case for it. '
        'Installed clients cannot be updated remotely — add the branch in '
        'webclient.py in the same change.'
    )


def test_the_client_never_waits_for_a_message_the_desktop_stopped_sending() -> None:
    """The other direction: a dead branch means a feature quietly does nothing."""
    orphaned = P.client_handled_types() - P.server_message_types()
    assert not orphaned, (
        f'the client handles {sorted(orphaned)} but nothing on the desktop emits '
        'it — either the emitter was removed, or it was renamed and only one side '
        'was updated.'
    )


def test_the_desktop_accepts_every_message_the_client_sends() -> None:
    """Handshake symmetry: ``hello`` / ``auth`` / ``command``."""
    unhandled = P.client_sent_types() - P.accepted_message_types()
    assert not unhandled, (
        f'the client sends {sorted(unhandled)}, which the server never reads. '
        'The message is dropped silently — the client waits forever.'
    )


def test_every_action_the_client_asks_for_is_dispatched() -> None:
    """An unknown action falls through to ``BAD_MESSAGE``, so this is user-visible.

    Only one direction is checked. The server may legitimately support more than
    the current client uses — ``save`` and ``discard`` exist for the follow-up
    confirmation flow — but the reverse would be a broken button.
    """
    undispatched = P.client_sent_actions() - P.command_actions()
    assert not undispatched, (
        f'the client sends action(s) {sorted(undispatched)} that the command '
        'handler does not dispatch — they are rejected with BAD_MESSAGE.'
    )


def test_event_kinds_agree_between_desktop_and_client() -> None:
    """``event`` is one type carrying several shapes; ``kind`` is the real switch."""
    emitted, expected = P.event_kinds(), P.client_expected_kinds()
    assert emitted == expected, (
        f'event kinds disagree — desktop emits {sorted(emitted)}, client branches '
        f'on {sorted(expected)}; only on the desktop: {sorted(emitted - expected)}, '
        f'only on the client: {sorted(expected - emitted)}'
    )


def test_the_client_only_branches_on_codes_the_desktop_emits() -> None:
    """A stale reason code is a toast that can never fire again."""
    unreachable = P.client_expected_reasons() - P.error_reasons()
    assert not unreachable, (
        f'the client tests for {sorted(unreachable)}, which nothing emits any '
        'more. The branch is dead and the user gets no feedback in that case.'
    )


def test_the_client_recalibrates_on_the_applied_value() -> None:
    """Invariant 2: the phone slider follows ``ack.applied_value``, not its own.

    Without this the slider keeps the value the finger left it at while the
    roaster sits at a clamped one — the display and the machine disagree, which
    is the one thing a remote control must never do.
    """
    js = (P.PKG_DIR / P.CLIENT_MODULE).read_text(encoding='utf-8')
    assert 'applied_value' in js, (
        'the client no longer reads ack.applied_value — it cannot follow a '
        'clamped or rejected slider move (§8 invariant 2).'
    )


# ── code ↔ document ──────────────────────────────────────────────────────────

def test_error_codes_agree_with_the_document() -> None:
    """The document's code list is the contract; the code is the implementation."""
    emitted, documented = P.error_reasons(), P.documented_error_codes()
    assert emitted == documented, (
        'error codes drifted from the protocol document.\n'
        f'  emitted but undocumented: {sorted(emitted - documented)}\n'
        f'  documented but never emitted: {sorted(documented - emitted)}\n'
        'The client is written against the document — both lists have to move '
        'together.'
    )


def test_ack_statuses_match_the_document() -> None:
    """§5: ``status`` ∈ ``ok | clamped | rejected``.

    ``clamped`` is the one the client cannot afford to lose: it is what tells the
    phone its request was honoured but not at the value asked for.
    """
    assert P.ack_statuses() == P.documented_enum('status'), (
        f'ack statuses are {sorted(P.ack_statuses())}, document says '
        f'{sorted(P.documented_enum("status"))}'
    )


# ── payload shapes ───────────────────────────────────────────────────────────

def test_welcome_carries_the_keys_the_client_builds_its_ui_from(webcontrol: Any) -> None:
    """§5: ``welcome`` defines the client UI, so a missing key is a missing control."""
    welcome = webcontrol._default_welcome()
    assert set(welcome) == WELCOME_KEYS, (
        f'welcome keys are {sorted(welcome)}, contract says {sorted(WELCOME_KEYS)}'
    )
    assert welcome['channels'], 'welcome with no channels leaves the grid empty'
    for channel in welcome['channels']:
        assert set(channel) == CHANNEL_KEYS, (
            f'channel {channel.get("id")!r} has keys {sorted(channel)}, contract '
            f'says {sorted(CHANNEL_KEYS)}'
        )


def test_channel_status_uses_the_documented_vocabulary(webcontrol: Any) -> None:
    """§5: ``controllable | display_only | absent`` — anything else is read-only.

    The client shows an *active* slider only for ``controllable``. A typo here
    does not raise; it silently turns a working control into a dead one.
    """
    allowed = P.documented_enum('channel.status')
    for channel in webcontrol._default_welcome()['channels']:
        assert channel['status'] in allowed, (
            f'channel {channel["id"]!r} has status {channel["status"]!r}, not one '
            f'of {sorted(allowed)} — the client will render it read-only'
        )


def test_snapshot_carries_the_full_state_the_client_starts_from(webcontrol: Any) -> None:
    """§5 + invariant 3: everything after the snapshot is a delta.

    So whatever the snapshot omits, the client has no way to learn later.
    """
    snapshot = webcontrol._default_snapshot()
    assert set(snapshot) == SNAPSHOT_KEYS, (
        f'snapshot keys are {sorted(snapshot)}, contract says {sorted(SNAPSHOT_KEYS)}'
    )
    assert set(snapshot['series']) == SERIES_KEYS, (
        f'snapshot.series holds {sorted(snapshot["series"])}, contract says '
        f'{sorted(SERIES_KEYS)}'
    )
    lengths = {k: len(v) for k, v in snapshot['series'].items()}
    assert len(set(lengths.values())) == 1, (
        f'§5: series are parallel arrays, but lengths differ: {lengths}'
    )


# ── guard the guards ─────────────────────────────────────────────────────────

def test_the_extractors_still_find_something() -> None:
    """A regex that silently stops matching turns every check above green.

    Each cross-check is an equality or a subset test, and both are trivially
    satisfied by an empty set. This is the one test that fails if the extraction
    breaks — for instance because the client's JavaScript is reformatted, or a
    server module is renamed out of the list.
    """
    extractors = {
        'server_message_types': P.server_message_types(),
        'accepted_message_types': P.accepted_message_types(),
        'command_actions': P.command_actions(),
        'error_reasons': P.error_reasons(),
        'ack_statuses': P.ack_statuses(),
        'event_kinds': P.event_kinds(),
        'client_handled_types': P.client_handled_types(),
        'client_sent_types': P.client_sent_types(),
        'client_sent_actions': P.client_sent_actions(),
        'client_expected_reasons': P.client_expected_reasons(),
        'client_expected_kinds': P.client_expected_kinds(),
        'documented_error_codes': P.documented_error_codes(),
    }
    empty = sorted(name for name, values in extractors.items() if not values)
    assert not empty, (
        f'{empty} extracted nothing. The contract tests are passing vacuously — '
        'fix the extraction in protocol_contract.py before trusting any of them.'
    )

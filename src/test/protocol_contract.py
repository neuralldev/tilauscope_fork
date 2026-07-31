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

"""Reads the remote-control wire vocabulary out of the three places it lives.

The `v1` protocol is written down in ``wiki/RemoteControl-Protocol-v1.md`` and
declared frozen there. It is then implemented twice — once in Python across the
server modules, once in JavaScript inside ``webclient.py`` — and the two halves
never meet at compile time. They agree only because someone kept them in step.

That is worth checking mechanically for a reason the desktop side does not have:
the client is a home-screen PWA. It is installed on a phone, cached there, and
served over plain ``http://`` on the LAN, so it has no service worker and no
update channel the desktop can force. Rename a reason code on the Python side
and the phone keeps running the old build, matching a string that will never
arrive again — silently, with no error anywhere, until the moment a roast needs
the message that no longer shows.

So this module extracts the vocabulary rather than restating it. A hand-written
copy of the message list would be a fourth place to forget.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

SRC_DIR: Final[Path] = Path(__file__).resolve().parent.parent
PKG_DIR: Final[Path] = SRC_DIR / 'tilauscope'
PROTOCOL_DOC: Final[Path] = SRC_DIR.parent / 'wiki' / 'RemoteControl-Protocol-v1.md'

#: Everything on the desktop side that can put bytes on the wire.
SERVER_MODULES: Final[tuple[str, ...]] = (
    'webcontrol.py',      # the WebSocket server and handshake
    'command_bridge.py',  # the Qt-side command executor, builds ack payloads
    'webhost.py',         # wiring: pumps telemetry into broadcast()
    'telemetry_tap.py',   # builds telemetry/event payloads from qmc
)

#: The mobile client. Its JavaScript is embedded in Python string literals, so
#: it is read as text — there is no JS parser here and none is needed: the
#: vocabulary appears in a handful of very regular shapes.
CLIENT_MODULE: Final[str] = 'webclient.py'

#: Calls that emit a message, mapped to the position of the message type.
_EMITTERS: Final[frozenset[str]] = frozenset({'_send', 'broadcast'})

#: Calls that emit an ``event`` payload, whose ``kind`` is the real discriminator.
_EVENT_EMITTERS: Final[frozenset[str]] = frozenset({
    '_broadcast_event', 'publish_event',
})


def _trees() -> dict[str, ast.Module]:
    return {
        name: ast.parse((PKG_DIR / name).read_text(encoding='utf-8'))
        for name in SERVER_MODULES
    }


def _client_js() -> str:
    return (PKG_DIR / CLIENT_MODULE).read_text(encoding='utf-8')


def _dict_pairs(node: ast.Dict) -> dict[str, str]:
    """Literal ``str -> str`` entries of a dict display, other entries dropped."""
    out: dict[str, str] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            out[key.value] = value.value
    return out


# ── desktop side ─────────────────────────────────────────────────────────────

def server_message_types() -> set[str]:
    """Message types the desktop sends, from every ``_send``/``broadcast`` call."""
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _EMITTERS):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
                        break
    return found


def accepted_message_types() -> set[str]:
    """Message types the desktop reads, from comparisons on ``…['type']``.

    Covers both spellings the handshake uses: ``data.get('type') == 'x'`` and
    ``data['type'] != 'x'``.
    """
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            left = node.left
            reads_type = (
                (isinstance(left, ast.Call) and isinstance(left.func, ast.Attribute)
                 and left.func.attr == 'get' and left.args
                 and isinstance(left.args[0], ast.Constant)
                 and left.args[0].value == 'type')
                or (isinstance(left, ast.Subscript)
                    and isinstance(left.slice, ast.Constant)
                    and left.slice.value == 'type')
            )
            if not reads_type:
                continue
            for cmp_node in node.comparators:
                if isinstance(cmp_node, ast.Constant) and isinstance(cmp_node.value, str):
                    found.add(cmp_node.value)
    return found


def command_actions() -> set[str]:
    """Actions the command handler dispatches on."""
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                    and node.left.id == 'action'):
                for cmp_node in node.comparators:
                    if isinstance(cmp_node, ast.Constant) and isinstance(cmp_node.value, str):
                        found.add(cmp_node.value)
    return found


def error_reasons() -> set[str]:
    """Machine-readable failure codes the desktop puts on the wire.

    They travel under two key names — ``code`` in an ``error`` message, ``reason``
    in a rejected ``ack`` — and are conventionally SCREAMING_SNAKE. That shape is
    what separates them from the prose values sharing those keys (``taken_over``
    is a human-facing revocation reason, not an error code).
    """
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in _dict_pairs(node).items():
                if key in ('code', 'reason') and re.fullmatch(r'[A-Z][A-Z_]{3,}', value):
                    found.add(value)
    return found


def ack_statuses() -> set[str]:
    """Values of ``ack.status``.

    Identified by company rather than by key name: ``status`` is also the field
    telling the client whether a channel is controllable. A dict carrying
    ``ref_seq`` is a reply to a command and nothing else; a dict returned by the
    bridge alongside ``saved``/``channel`` is the ack body before the server
    stamps the ref onto it.
    """
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if 'status' not in keys:
                    continue
                if not (keys & {'ref_seq', 'saved', 'reason', 'applied_value'}):
                    continue
                status = _dict_pairs(node).get('status')
                if status:
                    found.add(status)
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'status' for t in node.targets
            ):
                # `status = 'ok' if applied == requested else 'clamped'` — the
                # clamp verdict is decided before the payload is assembled, so
                # the dict never carries a literal.
                found.update(
                    sub.value for sub in ast.walk(node.value)
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                )
    return found


def event_kinds() -> set[str]:
    """The ``kind`` discriminator of every ``event`` payload the desktop builds."""
    found: set[str] = set()
    for tree in _trees().values():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            emits_event = node.func.attr in _EVENT_EMITTERS or (
                node.func.attr in _EMITTERS
                and any(isinstance(a, ast.Constant) and a.value == 'event'
                        for a in node.args)
            )
            if not emits_event:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    kind = _dict_pairs(arg).get('kind')
                    if kind:
                        found.add(kind)
    return found


# ── mobile client ────────────────────────────────────────────────────────────

def client_handled_types() -> set[str]:
    """Message types the JavaScript switch has a branch for."""
    return set(re.findall(r"case\s*'([a-z_]+)'\s*:", _client_js()))


def client_sent_types() -> set[str]:
    """Envelope types the client builds (``{type:'hello', …}``)."""
    return set(re.findall(r"\btype\s*:\s*'([a-z_]+)'", _client_js()))


def client_sent_actions() -> set[str]:
    """Command actions the client asks for."""
    return set(re.findall(r"\baction\s*:\s*'([a-z_]+)'", _client_js()))


def client_expected_reasons() -> set[str]:
    """Failure codes the client branches on."""
    return set(re.findall(r"reason\s*===?\s*'([A-Z][A-Z_]+)'", _client_js()))


def client_expected_kinds() -> set[str]:
    """Event kinds the client branches on."""
    return set(re.findall(r"kind\s*===?\s*'([a-z_]+)'", _client_js()))


# ── the written contract ─────────────────────────────────────────────────────

def documented_error_codes() -> set[str]:
    """The error-code list from the protocol document.

    Scoped to the section that declares them, so a code merely *mentioned* in
    prose elsewhere does not count as declared.
    """
    text = PROTOCOL_DOC.read_text(encoding='utf-8')
    section = text.split("### Codes d'erreur", 1)[1].split('---', 1)[0]
    return set(re.findall(r'`([A-Z][A-Z_]{3,})`', section))


def documented_enum(field: str) -> set[str]:
    """A closed value set the document spells out as ``field`` ∈ ``a | b | c``.

    The document uses that notation exactly where the wire has a fixed
    vocabulary, which makes it the one place the allowed values are stated
    without also being implemented.
    """
    text = PROTOCOL_DOC.read_text(encoding='utf-8')
    match = re.search(
        rf'`{re.escape(field)}`\s*∈\s*`([^`]+)`', text,
    )
    if match is None:
        raise LookupError(
            f'the protocol document no longer declares `{field}` ∈ `…` — the '
            'contract test can no longer read what it is meant to check',
        )
    return {v.strip() for v in match.group(1).split('|') if v.strip()}

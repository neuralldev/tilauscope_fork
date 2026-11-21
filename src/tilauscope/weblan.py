#
# ABOUT
# weblan.py - the phone servers answer the local network and nothing else

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

"""Refuse anything that did not come from the local network.

The phone protocol runs over plain ``ws://``: no TLS, no HMAC — Web Crypto is
unavailable over ``http://``, and a self-signed certificate on every phone is
not a thing a home roaster should have to do. That trade is written down in
``wiki/RemoteControl-Protocol-v1.md`` §7, and it holds on exactly one
condition: that the other end really is on the home network.

Both servers bind ``0.0.0.0``, which is every interface — a machine on a
network with a public address, or behind a forwarded port, would otherwise
serve the roaster to the internet. So the condition is enforced rather than
assumed, here, on the peer address of the connection.

That address is the TCP peer, not a header: a forged source cannot complete a
handshake, so it is not something a caller can claim. Proxy headers are
deliberately ignored — nothing legitimate sits in front of these servers.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Final

from tilauscope.tilau_privacy import _LOCAL_SUFFIXES

_log: Final[logging.Logger] = logging.getLogger(__name__)


def is_local_address(raw: str | None) -> bool:
    """True when *raw* is an address only reachable from the local network.

    Private ranges, loopback and link-local. Carrier-grade NAT (100.64.0.0/10)
    is **not** included: it is neither the home network nor the operator's to
    trust — which also means an overlay VPN using that range cannot pilot the
    roaster.
    """
    if not raw:
        return False                     # unknown peer: fail closed
    try:
        addr = ipaddress.ip_address(raw.strip().strip('[]'))
    except ValueError:
        return False

    # ::ffff:192.168.1.9 is an IPv4 peer on a dual-stack socket; classify the
    # address it actually carries, not its wrapper.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


def reject_remote_peer(request, server: str) -> bool:
    """True when this request must not be served. Logs the refusal once per peer."""
    remote = getattr(request, 'remote', None)
    if is_local_address(remote):
        return False
    _log.warning('%s: refused a request from outside the local network: %s',
                 server, remote or '<unknown>')
    return True


def reject_foreign_host(request, server: str) -> bool:
    """True when the page was asked under a name the phone never uses.

    The peer check cannot see DNS rebinding: a page from anywhere, loaded in a
    browser on the home network, asks again under its own domain once that
    domain resolves to this machine — the peer is then local. The phone asks by
    address, by tilauscope.local, by the machine's own .local name, or by the name
    the home router gives it (a bare name, .lan, .home…); none of them is an
    internet domain, so nobody can rebind one.
    """
    host = str(getattr(request, 'host', '') or '').strip().lower()
    name = host[1:host.find(']')] if host.startswith('[') else host.rsplit(':', 1)[0] if host.count(':') == 1 else host
    name = name.rstrip('.')
    try:
        ipaddress.ip_address(name)
        return False
    except ValueError:
        pass
    if name == 'localhost' or (name and '.' not in name):
        return False   # a bare machine name: no internet domain is dotless
    if any(name.endswith(suffix) and len(name) > len(suffix) for suffix in _LOCAL_SUFFIXES):
        return False   # the home router's own names (.lan, .home…): never delegated, nobody can rebind one
    _log.warning('%s: refused a request asked under a foreign name: %r', server, host)
    return True

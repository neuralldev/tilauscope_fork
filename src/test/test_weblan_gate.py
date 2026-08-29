"""The phone servers answer the local network and nothing else.

Plain ``ws://`` is accepted in protocol §7 on one condition: that the other end
is on the home network. Both servers bind every interface, so that condition is
enforced on the peer address rather than inferred from the bind.
"""

from __future__ import annotations

import pytest

from tilauscope.weblan import is_local_address, reject_remote_peer


class _Request:
    def __init__(self, remote):
        self.remote = remote


# ── what the home network looks like ─────────────────────────────────────────

@pytest.mark.parametrize('addr', [
    '127.0.0.1', '::1',                 # the machine itself
    '10.0.0.5', '172.16.4.9', '192.168.1.9',   # RFC1918
    '169.254.10.2', 'fe80::1',          # link-local, no DHCP
    'fd12:3456::1',                     # IPv6 unique local
    '::ffff:192.168.1.9',               # IPv4 peer on a dual-stack socket
])
def test_a_phone_on_the_home_network_is_served(addr) -> None:
    assert is_local_address(addr) is True
    assert reject_remote_peer(_Request(addr), 'control') is False


# ── and what it does not ─────────────────────────────────────────────────────

@pytest.mark.parametrize('addr', [
    '8.8.8.8', '93.184.216.34',                    # public IPv4
    '2001:4860:4860::8888',             # public IPv6
    '::ffff:8.8.8.8',                   # public IPv4 wearing an IPv6 wrapper
    '172.32.0.1',                       # just outside 172.16/12
])
def test_anything_off_the_home_network_is_refused(addr) -> None:
    assert is_local_address(addr) is False
    assert reject_remote_peer(_Request(addr), 'control') is True


def test_carrier_grade_nat_is_not_the_home_network() -> None:
    """100.64/10 is the carrier's, not the operator's — and it is what an
    overlay VPN uses, which is exactly the remote access this gate refuses."""
    assert is_local_address('100.64.0.1') is False
    assert is_local_address('100.115.92.2') is False


# ── the gate fails closed ────────────────────────────────────────────────────

@pytest.mark.parametrize('raw', [None, '', '   ', 'not-an-address',
                                 'localhost', '192.168.1.9:5000', '999.1.1.1'])
def test_an_address_that_cannot_be_read_is_refused(raw) -> None:
    """A peer that cannot be identified is not given the benefit of the doubt."""
    assert is_local_address(raw) is False
    assert reject_remote_peer(_Request(raw), 'records') is True


def test_a_request_with_no_peer_at_all_is_refused() -> None:
    class _Bare:
        pass
    assert reject_remote_peer(_Bare(), 'control') is True


def test_a_bracketed_ipv6_peer_is_still_read() -> None:
    assert is_local_address('[::1]') is True


# ── a claim in a header is not an address ────────────────────────────────────

def test_a_forwarded_header_cannot_pass_the_gate() -> None:
    """Nothing legitimate proxies these servers, so a claimed address is just
    a claim — only the TCP peer counts, and that one cannot be forged."""
    class _Spoofed:
        remote = '8.8.8.8'
        headers = {'X-Forwarded-For': '192.168.1.9',
                   'X-Real-IP': '127.0.0.1'}

    assert reject_remote_peer(_Spoofed(), 'control') is True


# ── both servers are actually wired to it ────────────────────────────────────

def _servers():
    from tilauscope.webcontrol import TilauWebControl
    from tilauscope.webrecords import TilauWebRecords
    return [('control', TilauWebControl(port=0)),
            ('records', TilauWebRecords(port=0))]


async def _served(server, remote) -> int:
    """Run the server's middleware for a peer and report the status."""
    from aiohttp import web

    async def _handler(_request):
        return web.Response(status=200, text='ok')

    resp = await server._security_middleware(_Request(remote), _handler)  # noqa: SLF001
    return resp.status


@pytest.mark.asyncio
@pytest.mark.parametrize('name,server', _servers())
async def test_a_local_peer_is_served(name, server) -> None:
    assert await _served(server, '192.168.1.9') == 200, (
        f'{name} refused a phone on the home network')


@pytest.mark.asyncio
@pytest.mark.parametrize('name,server', _servers())
async def test_a_remote_peer_gets_nothing(name, server) -> None:
    """Both servers bind every interface, so a machine with a public address —
    or one behind a forwarded port — would otherwise serve the roaster out."""
    for remote in ('93.184.216.34', '2001:4860:4860::8888', '::ffff:8.8.8.8', None):
        assert await _served(server, remote) == 403, (
            f'{name} served {remote}, which is not on the home network')

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Ed25519 signatures (RFC 8032, section 5.1) in the standard library only.

The tablets sign what they publish to the community library with it; the desktop signs with the
`cryptography` package, and the tests check that both give the same bytes. Signing only: the relay
verifies. Not constant time: it signs on the user's own device, with nothing an attacker can time.
"""

from __future__ import annotations

import hashlib

_P = 2 ** 255 - 19 # the field
_L = 2 ** 252 + 27742317777372353535851937790883648493 # the group order
_D = -121665 * pow(121666, _P - 2, _P) % _P # the curve constant, -121665/121666
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

Point = tuple[int, int, int, int] # extended coordinates (X, Y, Z, T), x = X/Z, y = Y/Z, x*y = T/Z


def _add(a: Point, b: Point) -> Point:
    """Addition on the twisted Edwards curve (RFC 8032, 5.1.4)."""
    p1 = (a[1] - a[0]) * (b[1] - b[0]) % _P
    p2 = (a[1] + a[0]) * (b[1] + b[0]) % _P
    c = 2 * a[3] * b[3] * _D % _P
    z = 2 * a[2] * b[2] % _P
    e, f, g, h = p2 - p1, z - c, z + c, p2 + p1
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _times(n: int, point: Point) -> Point:
    total: Point = (0, 1, 1, 0) # the neutral point
    while n:
        if n & 1:
            total = _add(total, point)
        point = _add(point, point)
        n >>= 1
    return total


def _x_of(y: int, odd: int) -> int:
    """The x of the curve point with this y, and its parity (RFC 8032, 5.1.3)."""
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _SQRT_M1 % _P
    if x & 1 != odd:
        x = _P - x
    return x


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _x_of(_BY, 0)
_BASE: Point = (_BX, _BY, 1, _BX * _BY % _P)


def _encode(point: Point) -> bytes:
    inverse = pow(point[2], _P - 2, _P)
    x, y = point[0] * inverse % _P, point[1] * inverse % _P
    return (y | (x & 1) << 255).to_bytes(32, "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    """The secret scalar and the prefix a 32-byte private key stands for (RFC 8032, 5.1.5)."""
    if len(seed) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return scalar, digest[32:]


def _reduced(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _L


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte private key."""
    return _encode(_times(_expand(seed)[0], _BASE))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of `message` (RFC 8032, 5.1.6)."""
    scalar, prefix = _expand(seed)
    public = _encode(_times(scalar, _BASE))
    r = _reduced(prefix + message)
    commitment = _encode(_times(r, _BASE))
    s = (r + _reduced(commitment + public + message) * scalar) % _L
    return commitment + s.to_bytes(32, "little")

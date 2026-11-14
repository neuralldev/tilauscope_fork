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
# Tilau 2026

"""This installation's key for the coffee library: an Ed25519 pair, the private half in the OS keychain.

Nothing in it names a person. The relay knows a coffee's author only by the
public key that signed its publication, and accepts a withdrawal only signed by
the same key. A key held for the session only would leave every coffee published
with it impossible to withdraw after a restart, so without a keychain there is no
key at all. Spec: wiki/CoffeeLibrary-Spec.md §3.2.
"""

from __future__ import annotations

import base64
import logging
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from tilaucore.coffee_library import Sign
from tilauscope import tilau_secrets

_log = logging.getLogger(__name__)

ACCOUNT: Final[str] = "library:key"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signer() -> Sign | None:
    """Signed text → (public key, signature), base64url without padding; None when the keychain cannot keep the key."""
    if not tilau_secrets.keychain_available():
        return None
    stored = tilau_secrets.get_secret(ACCOUNT)
    if not stored and tilau_secrets.last_error():
        return None   # a keychain that failed to answer: a new key would replace the one that published
    if stored:
        try:
            key = Ed25519PrivateKey.from_private_bytes(_unb64(stored))
        except ValueError:
            _log.warning("library key in the keychain is unreadable")
            return None
    else:
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        if not tilau_secrets.set_secret(ACCOUNT, _b64(raw)):
            tilau_secrets.delete_secret(ACCOUNT)   # set_secret kept a session copy; a session key is no key
            return None
    public = _b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    return lambda text: (public, _b64(key.sign(text)))

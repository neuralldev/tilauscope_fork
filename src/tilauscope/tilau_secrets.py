#
# ABOUT
# tilau_secrets.py - credentials live in the OS keychain, never in the settings

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

"""Every credential TilauScope holds, in the keychain the operating system runs.

The settings store is a plain file. It is also the thing the operator exports
when they share a machine setup — Artisan writes *every* setting into a
``.aset``, so a credential kept there travels with the profile. Base64 does not
help: it is an encoding, not a cipher, and it decodes in one line.

So credentials go to the macOS keychain / Windows Credential Manager through
``keyring``, which the application already carries for its artisan.plus login,
and the settings keep only what it takes to find them again: which provider,
which broker, which user.

Accounts are named so they are recognisable in Keychain Access:

``ai:<client_id>``
    One key per AI provider, so switching provider and back does not throw the
    first key away.

``mqtt:<username>@<host>:<port>``
    One password per broker login.

Nothing here raises. A keychain that refuses — no backend, a user declining the
prompt — must not stop a roast, so the value is held for the session only and
the caller is told through :func:`last_error`. It is never written back to disk.
"""

from __future__ import annotations

import logging
from typing import Final

_log: Final[logging.Logger] = logging.getLogger(__name__)

#: Shown as the item name in Keychain Access / Credential Manager.
SERVICE: Final[str] = 'TilauScope'

#: Values held only until the process exits, when the keychain is unusable.
#: Deliberately not persisted anywhere: a fallback that writes to disk would
#: reintroduce exactly the leak this module exists to close.
_session: dict[str, str] = {}

#: Why the last keychain call failed, for a caller that wants to say so.
_last_error: str = ''


def ai_account(client_id: str) -> str:
    """Keychain account holding the API key of one AI provider."""
    return f'ai:{client_id}'


def mqtt_account(username: str, host: str, port: int | str) -> str:
    """Keychain account holding the password of one broker login."""
    return f'mqtt:{username}@{host}:{port}'


def last_error() -> str:
    """Message from the most recent keychain failure, or '' if all is well."""
    return _last_error


def keychain_available() -> bool:
    """Whether a real keychain answered. False means the session fallback."""
    global _last_error  # noqa: PLW0603
    try:
        import keyring  # noqa: PLC0415

        backend = keyring.get_keyring()
        from keyring.backends.fail import Keyring as FailKeyring  # noqa: PLC0415

        if isinstance(backend, FailKeyring):
            _last_error = 'no keychain backend available on this system'
            return False
        _last_error = ''
        return True
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        return False


def get_secret(account: str) -> str:
    """The stored credential, or '' when there is none.

    A keychain that cannot be read falls back to whatever this session stored,
    never to the settings file.
    """
    global _last_error  # noqa: PLW0603
    if not account:
        return ''
    try:
        import keyring  # noqa: PLC0415

        value = keyring.get_password(SERVICE, account)
        _last_error = ''
        if value:
            return value
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        _log.warning('keychain read failed for %s: %s', account, exc)
    return _session.get(account, '')


def set_secret(account: str, value: str) -> bool:
    """Store a credential. Returns False when only this session holds it."""
    global _last_error  # noqa: PLW0603
    if not account:
        return False
    if not value:
        delete_secret(account)
        return True

    _session[account] = value            # so the session works either way
    try:
        import keyring  # noqa: PLC0415

        keyring.set_password(SERVICE, account, value)
        _last_error = ''
        _log.info('keychain stored %s', account)
        return True
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)
        _log.warning('keychain write failed for %s: %s', account, exc)
        return False


def delete_secret(account: str) -> None:
    """Forget a credential, in the keychain and in this session."""
    global _last_error  # noqa: PLW0603
    _session.pop(account, None)
    try:
        import keyring  # noqa: PLC0415

        keyring.delete_password(SERVICE, account)
        _last_error = ''
        _log.info('keychain cleared %s', account)
    except Exception as exc:  # noqa: BLE001
        # Deleting something that was never there is the ordinary case.
        _last_error = str(exc)
        _log.debug('keychain delete for %s: %s', account, exc)

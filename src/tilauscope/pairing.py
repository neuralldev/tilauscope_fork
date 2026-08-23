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
# Tilau 2025-2026

#
# pairing.py
#
# Remote-control pairing (protocol §7): one-time pairing token exchanged for a
# persistent per-device token stored in QSettings; revocation drops the token.

import hmac  # only for compare_digest (constant-time), not for HMAC crypto
import json
import logging
import secrets
import threading
import time
from typing import Callable, Optional

from PyQt6.QtCore import QSettings

_log = logging.getLogger(__name__)

_PT_TTL = 120           # seconds (protocol §7)
_DEVICES_KEY = 'tilauscope/remote_devices'


class PairingManager:
    def __init__(self) -> None:
        self._pt: Optional[tuple] = None  # (token, expiry_epoch)
        # In-memory devices dict, persisted write-through to QSettings. Shared
        # between the control-server thread and the Qt thread; _lock guards every access.
        self._lock = threading.Lock()
        self._devices: dict = self._load()
        self._revoke_callback: Optional[Callable[[str], None]] = None

    def set_revoke_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Notify the live transport after a persistent device is revoked."""
        with self._lock:
            self._revoke_callback = callback

    # ---- pairing token (desktop) -------------------------------------------

    def mint_pairing_token(self) -> tuple:
        """Generate a fresh one-time PT (invalidates any previous one)."""
        token = 'pt_' + secrets.token_urlsafe(16)
        with self._lock:
            self._pt = (token, time.time() + _PT_TTL)
        return token, _PT_TTL

    def clear_pairing_token(self) -> None:
        with self._lock:
            self._pt = None

    def _consume_pt_locked(self, token: str) -> bool:
        """Consume a pairing token while the caller holds ``_lock``."""
        if not self._pt or not token:
            return False
        tok, exp = self._pt
        if time.time() > exp:
            self._pt = None
            return False
        if not hmac.compare_digest(tok, token):
            return False
        self._pt = None  # one-time
        return True

    # ---- device tokens (persistent, QSettings) -----------------------------

    @staticmethod
    def _load() -> dict:
        try:
            raw = QSettings().value(_DEVICES_KEY, '', type=str)
            return json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _save(devices: dict) -> None:
        # Caller must hold self._lock: json.dumps() iterates `devices` and must
        # not run concurrently with a structural mutation from the other thread.
        try:
            s = QSettings()
            s.setValue(_DEVICES_KEY, json.dumps(devices))
            s.sync()  # flush now so a fresh QSettings on another thread sees it
        except Exception as e:  # noqa: BLE001
            _log.warning("pairing: cannot save devices: %s", e)

    def pair(self, token: str, device_id: str, display_name: str) -> Optional[str]:
        """Validate a PT and issue a persistent DT for this device."""
        with self._lock:
            # PT validation and consumption must be one critical section.  Besides
            # free-threaded Python, this prevents two server workers from exchanging
            # the same nominally one-time token.
            if not self._consume_pt_locked(token):
                return None
            dt = 'dt_' + secrets.token_urlsafe(24)
            self._devices[device_id] = {'token': dt, 'name': display_name or device_id,
                                        'paired_at': int(time.time())}
            self._save(self._devices)
        _log.info("pairing: device paired: %s", device_id)
        return dt

    def verify_token(self, device_id: str, device_token: str) -> bool:
        """Constant-time match of a presented DT against the stored one.
        No HMAC (Web Crypto unavailable over plain http); a revoked DT no longer matches."""
        with self._lock:
            dev = self._devices.get(device_id)
            token = str(dev.get('token', '')) if dev else ''
        if not token:
            return False
        return hmac.compare_digest(token, device_token or '')

    def list_devices(self) -> dict:
        # Deep copy under the lock: callers iterate names off-thread (dialog
        # poll), so they must never see a value dict being mutated by rename().
        with self._lock:
            return {k: dict(v) for k, v in self._devices.items()}

    def rename(self, device_id: str, name: str) -> bool:
        """Set a user-chosen display name for a paired device."""
        name = (name or '').strip()
        if not name:
            return False
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return False
            dev['name'] = name
            self._save(self._devices)
        _log.info("pairing: device renamed: %s", device_id)
        return True

    def revoke(self, device_id: str) -> None:
        with self._lock:
            removed = self._devices.pop(device_id, None) is not None
            if removed:
                self._save(self._devices)
            callback = self._revoke_callback
        if removed:
            _log.info("pairing: device revoked: %s", device_id)
            # Run outside _lock: the callback crosses into the asyncio thread and
            # must never be allowed to deadlock token verification/list_devices().
            if callback is not None:
                try:
                    callback(device_id)
                except Exception as e:  # noqa: BLE001
                    _log.warning("pairing: live-session revocation failed: %s", e)

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

# A device token is permanent until revoked, which assumes the operator
# remembers every phone they ever paired. One that has not connected for a
# month stops being valid: re-pairing is a QR scan, and a phone sold, lost or
# forgotten stops carrying a key to the roaster.
_DT_IDLE_TTL = 30 * 86400

# `last_seen` is written on every successful connection, and a flaky link
# reconnects often. Only persist when the stored value is this far behind, so
# the settings file is not rewritten on every handshake.
_LAST_SEEN_RESOLUTION = 3600


class PairingManager:
    def __init__(self) -> None:
        self._pt: Optional[tuple] = None  # (token, expiry_epoch)
        # In-memory devices dict, persisted write-through to QSettings. Shared
        # between the control-server thread and the Qt thread; _lock guards every access.
        self._lock = threading.Lock()
        self._devices: dict = self._load()
        self._revoke_callback: Optional[Callable[[str], None]] = None
        self._start_idle_clock()
        # A phone silent for a month is forgotten at startup, so the desktop
        # never lists — nor honours — a device that stopped being used.
        self.sweep_expired()

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
            now = int(time.time())
            self._devices[device_id] = {'token': dt, 'name': display_name or device_id,
                                        'paired_at': now, 'last_seen': now}
            self._save(self._devices)
        _log.info("pairing: device paired: %s", device_id)
        return dt

    def _start_idle_clock(self) -> None:
        """Give every device already paired a last-seen of now.

        Without this an upgrade would read the pairing date as the last sign of
        life and expire a phone used yesterday but paired three months ago. The
        idle clock starts when the rule does, not before it existed.
        """
        with self._lock:
            now = int(time.time())
            missing = [d for d in self._devices.values()
                       if isinstance(d, dict) and not d.get('last_seen')]
            for dev in missing:
                dev['last_seen'] = now
            if missing:
                self._save(self._devices)

    @staticmethod
    def _idle_seconds(dev: dict) -> int:
        """How long since this device last connected."""
        seen = int(dev.get('last_seen') or dev.get('paired_at') or 0)
        return int(time.time()) - seen if seen else 0

    def _drop_if_idle_locked(self, device_id: str, dev: dict) -> bool:
        """Forget a device that has not connected for a month. Caller holds the lock."""
        if self._idle_seconds(dev) < _DT_IDLE_TTL:
            return False
        self._devices.pop(device_id, None)
        self._save(self._devices)
        _log.info("pairing: device expired after %d days idle: %s",
                  self._idle_seconds(dev) // 86400, device_id)
        return True

    def sweep_expired(self) -> int:
        """Forget every device idle for longer than the limit. Returns the count."""
        with self._lock:
            stale = [d for d, dev in self._devices.items()
                     if isinstance(dev, dict) and self._idle_seconds(dev) >= _DT_IDLE_TTL]
            for device_id in stale:
                self._devices.pop(device_id, None)
            if stale:
                self._save(self._devices)
        for device_id in stale:
            _log.info("pairing: device expired (idle): %s", device_id)
        return len(stale)

    def verify_token(self, device_id: str, device_token: str) -> bool:
        """Constant-time match of a presented DT against the stored one.

        No HMAC (Web Crypto unavailable over plain http); a revoked DT no longer
        matches, and neither does one whose device has been silent for a month.
        A match records the connection, which is what keeps the device alive and
        what lets the desktop show which phones are still in use.
        """
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and self._drop_if_idle_locked(device_id, dev):
                return False
            token = str(dev.get('token', '')) if dev else ''
        if not token:
            return False
        if not hmac.compare_digest(token, device_token or ''):
            return False

        with self._lock:
            dev = self._devices.get(device_id)
            if dev is not None:
                now = int(time.time())
                if now - int(dev.get('last_seen') or 0) >= _LAST_SEEN_RESOLUTION:
                    dev['last_seen'] = now
                    self._save(self._devices)
        return True

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

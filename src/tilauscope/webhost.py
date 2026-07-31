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
# webhost.py
#
# ## TILAU ## App-level owner of the TilauScope web servers.
#
# Generalises the TilauWebRecords thread+loop pattern into a single host owned by
# ApplicationWindow and started with Artisan/TilauScope (both boot paths), so the
# read-only Records server no longer depends on the BeanCave window being open
# (see wiki/RemoteControl-Protocol-v1.md §3 and wiki/RemoteControl-Implementation-Plan.md).
#
# Phase 0 (this file): owns the Records server with settable resolvers; BeanCave
# only supplies the roast/bean resolvers when its catalogue is loaded.
# Phase 1+: mounts the opt-in Control server (remote piloting) on the same host.

import logging
from typing import Callable, Optional

from tilauscope.webrecords import TilauWebRecords

_log = logging.getLogger(__name__)

# TilauWebControl is imported lazily in start() so the opt-in server (and its
# aiohttp WS machinery) is only touched when remote control is actually enabled.


class TilauWebHost:
    """Owns the TilauScope web servers at application scope.

    Lifecycle is driven by ApplicationWindow: start() in main() for both boot
    paths, stop() in closeApp(). Independent of the BeanCave window — BeanCave
    registers the Records resolvers via set_records_resolvers() when available.
    """

    def __init__(self, records_port: int, control_port: int, *,
                 control_enabled: bool = False) -> None:
        self._records_port = records_port
        self._control_port = control_port
        self._control_enabled = control_enabled
        self._records: Optional[TilauWebRecords] = None
        self._control = None  # TilauWebControl | None (opt-in)
        self._last_snapshot: Optional[dict] = None  # built on the Qt thread by TelemetryTap
        self._pairing = None  # PairingManager (created with the Control server)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        # Records: always-on read-only server (phone QR scan target).
        try:
            self._records = TilauWebRecords(self._records_port)
            self._records.startWeb()
            _log.info("TilauWebHost: Records server on port %s", self._records_port)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            # a failed Records server (port in use, …) must never break startup
            _log.warning("TilauWebHost: Records server not started: %s", e)
            self._records = None
        # Control: opt-in remote-piloting server (Bonjour _tilauscope._tcp).
        # Started only when explicitly enabled -> zero attack surface otherwise.
        if self._control_enabled:
            try:
                from tilauscope.webcontrol import TilauWebControl, _default_snapshot
                from tilauscope.pairing import PairingManager
                if self._last_snapshot is None:
                    self._last_snapshot = _default_snapshot()
                self._pairing = PairingManager()
                self._control = TilauWebControl(
                    self._control_port,
                    snapshot_provider=lambda: self._last_snapshot,
                    pairing=self._pairing)
                self._control.startWeb()
                _log.info("TilauWebHost: Control server on port %s", self._control_port)
            except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                _log.warning("TilauWebHost: Control server not started: %s", e)
                self._control = None
        else:
            _log.info("TilauWebHost: Control server disabled (opt-in) — set "
                      "tilauscope/remote_enabled or launch with TILAU_REMOTE=1")
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        try:
            if self._records is not None:
                self._records.stopWeb()
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _log.debug("TilauWebHost: Records stop: %s", e)
        try:
            if self._control is not None:
                self._control.stopWeb()
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            _log.debug("TilauWebHost: Control stop: %s", e)
        self._records = None
        self._control = None
        self._started = False

    # ---- Records resolvers (BeanCave registers/clears these) ----------------

    def set_records_resolvers(self,
                              roast_resolver: Callable[[str], Optional[str]],
                              bean_resolver: Callable[[str], Optional[dict]],
                              sack_resolver: Optional[Callable[[str], Optional[str]]] = None) -> None:
        if self._records is not None:
            self._records.set_resolvers(roast_resolver, bean_resolver, sack_resolver)

    def clear_records_resolvers(self) -> None:
        if self._records is not None:
            self._records.clear_resolvers()

    # ---- Control telemetry (TelemetryTap on the Qt thread feeds these) -------

    def control_active(self) -> bool:
        return self._control is not None

    def has_clients(self) -> bool:
        return self._control is not None and self._control.client_count() > 0

    def publish_snapshot(self, snapshot: dict) -> None:
        """Store the latest full snapshot (served to clients on connect)."""
        self._last_snapshot = snapshot

    def patch_snapshot(self, **fields) -> None:
        """Amend a few fields of the stored snapshot without rebuilding it.

        Used when sampling stops: the last full snapshot was built while Artisan
        was still monitoring, and a phone connecting afterwards must not be told
        the frozen view is live.
        """
        if isinstance(self._last_snapshot, dict):
            self._last_snapshot = {**self._last_snapshot, **fields}

    def publish_telemetry(self, telemetry: dict) -> None:
        """Fan out a per-tick delta to connected observers (thread-safe)."""
        if self._control is not None:
            self._control.broadcast('telemetry', telemetry)

    def publish_event(self, payload: dict) -> None:
        """Fan out an `event` (milestone / recorder / …) to observers (§5)."""
        if self._control is not None:
            self._control.broadcast('event', payload)

    # ---- Control commands (Phase 2: downward path via the CommandBridge) -----

    def attach_command_bridge(self, bridge) -> None:
        """Wire the Qt-main-thread command applier into the Control server."""
        if self._control is not None:
            self._control.attach_bridge(bridge)

    # ---- pairing (used by the desktop pairing UI) ---------------------------

    @property
    def pairing(self):
        return self._pairing

    def lan_ip(self):
        """Best LAN IPv4 for the pairing URL, or None. Prefer a private-range
        address; falls back to the first. Used instead of `tilauscope.local`
        because iOS mDNS resolution of .local is slow/flaky (protocol §7)."""
        try:
            from tilauscope.webcontrol import TilauWebControl
            ips = TilauWebControl._local_ipv4s()
            for ip in ips:  # private ranges first (skip VPN/oddball adapters)
                if ip.startswith('192.168.') or ip.startswith('10.'):
                    return ip
            for ip in ips:
                if ip.startswith('172.'):
                    return ip
            return ips[0] if ips else None
        except Exception:  # noqa: BLE001
            return None

    def mint_pairing_token(self):
        """Mint a one-time pairing token; returns (token, ttl_seconds) or None."""
        if self._pairing is None:
            return None
        return self._pairing.mint_pairing_token()

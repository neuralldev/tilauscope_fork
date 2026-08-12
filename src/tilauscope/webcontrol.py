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
# webcontrol.py
#
# Opt-in remote-control server: WebSocket transport for the phone client, advertised
# via Bonjour _tilauscope._tcp (wiki/RemoteControl-Protocol-v1.md). Never touches
# Qt/qmc directly — welcome/snapshot come from injectable providers.

import asyncio
import json
import logging
import socket
import time
from contextlib import suppress
from threading import Thread
from typing import Callable, Optional, Set

from aiohttp import web

_log = logging.getLogger(__name__)

PROTO_VERSION = 1

_GRACE_S = 10.0          # deadman: keep control this long after a controller drops (§7)
_SLIDER_DEBOUNCE = 0.3   # s — coalesce non-final set_slider per channel (§6)
_DRUM_DEBOUNCE = 1.0     # s — drum is slower / more disruptive (§6)


def _device_label_from_ua(ua: str, device_id: str = '') -> str:
    """Best-effort human label from a browser User-Agent (e.g. 'iPhone · Safari').

    Zero client cooperation needed — the browser always sends User-Agent on the
    WS upgrade. A short suffix of the device id keeps two identical phones apart.
    """
    ua = ua or ''
    u = ua.lower()
    if 'ipad' in u:
        device = 'iPad'
    elif 'iphone' in u:
        device = 'iPhone'
    elif 'ipod' in u:
        device = 'iPod'
    elif 'android' in u:
        device = 'Android phone' if 'mobile' in u else 'Android tablet'
    elif 'macintosh' in u or 'mac os x' in u:
        # NB: iPadOS 13+ Safari sends a desktop "Macintosh" UA, indistinguishable
        # server-side; cooperating clients disambiguate via display_name instead.
        device = 'Mac'
    elif 'windows' in u:
        device = 'Windows PC'
    elif 'linux' in u:
        device = 'Linux'
    else:
        device = ''
    # browser (order matters: iOS wrappers advertise Safari too)
    if 'crios' in u:
        browser = 'Chrome'
    elif 'fxios' in u or 'firefox' in u:
        browser = 'Firefox'
    elif 'edgios' in u or 'edg/' in u or 'edga' in u:
        browser = 'Edge'
    elif 'opr/' in u or 'opios' in u:
        browser = 'Opera'
    elif 'chrome' in u:
        browser = 'Chrome'
    elif 'safari' in u:
        browser = 'Safari'
    else:
        browser = ''
    label = ' · '.join(x for x in (device, browser) if x)
    suffix = device_id[-4:] if device_id and len(device_id) >= 4 else ''
    if label and suffix:
        return f"{label} ({suffix})"
    return label or (f"Web ({suffix})" if suffix else 'Web')


def _default_welcome() -> dict:
    # Placeholder capabilities until the per-roaster resolver (§6) is wired.
    # role is "observer": Phase 1a has no controller lock and no commands yet.
    return {
        "session_id": "roast-session",
        "roaster": "TilauScope",
        "unit": "C",
        "role": "observer",
        # ids MUST follow the `slider{i}` convention the telemetry uses as its keys.
        # Labels stay generic; the real ones come from Artisan's slider config via the command bridge.
        "channels": [
            {"id": f"slider{i}", "label": f"Slider {i + 1}", "status": "controllable",
             "min": 0, "max": 100, "step": 1, "unit": "%"}
            for i in range(4)
        ],
        "controls": {
            "recorder": True,
            "mark": ["CHARGE", "DRYe", "FCs", "SCs", "DROP"],
            "save_on_stop": True,
            "autosave_default": True,
        },
    }


def _default_snapshot() -> dict:
    return {
        "phase": "idle",
        "charge_marked": False,
        "clock": 0.0,
        "series": {"t": [], "bt": [], "et": [], "ror": []},
        "markers": [],
        "sliders": {},
    }


class TilauWebControl:
    """Opt-in WebSocket control server (transport only, Phase 1a).

    welcome_provider() -> dict payload for `welcome` (role forced to observer here)
    snapshot_provider() -> dict payload for `snapshot`
    Both are called from the server thread and must only read plain-python data.
    """

    def __init__(self, port: int, *,
                 roaster_name: str = "TilauScope",
                 unit: str = "C",
                 welcome_provider: Optional[Callable[[], dict]] = None,
                 snapshot_provider: Optional[Callable[[], dict]] = None,
                 pairing=None) -> None:
        self._port = port
        self._roaster_name = roaster_name
        self._unit = unit
        self._welcome_provider = welcome_provider or _default_welcome
        self._snapshot_provider = snapshot_provider or _default_snapshot
        self._pairing = pairing  # PairingManager | None (None -> open, no auth)
        self._bridge = None      # CommandBridge | None (attached when control enabled)

        # UI translations for the mobile client, resolved ONCE here on the Qt main
        # thread (QApplication.translate must not run on the WS loop thread) and
        # injected into the served page as window.T. English is inline in the page
        # as the fallback if this ever fails.
        self._i18n_json = "{}"
        try:
            import json as _json
            from tilauscope.webclient import client_i18n
            # `<` is escaped so a translation that happened to contain "</script>"
            # cannot close the <script type="application/json"> block carrying this
            # JSON and inject markup into the page. json.dumps does not do it.
            self._i18n_json = _json.dumps(client_i18n(),
                                          ensure_ascii=False).replace('<', '\\u003c')
        except Exception:  # noqa: BLE001
            _log.debug("client i18n unavailable; page uses inline English")
        # the page is immutable once the translations are resolved: build it on the
        # first request and serve that, instead of a 50 kB replace() per request.
        self._client_html = ''

        # controller lock (§7) — all fields touched on the loop thread only
        self._controller = None       # device_id of the current controller (None = free)
        self._controller_ws = None    # its live socket (None while in the grace window)
        self._grace_handle = None     # asyncio TimerHandle for the deadman grace
        self._takeover_pending = False  # a desktop takeover confirmation is open
        # per-channel set_slider coalescing (loop thread only)
        self._pending_slider: dict = {}
        self._slider_timers: dict = {}

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._runner: Optional[web.AppRunner] = None
        self._zeroconf = None
        self._zc_info = None
        self._clients: Set[web.WebSocketResponse] = set()
        self._seq = 0
        self._hb_task: Optional[asyncio.Task] = None
        # strong refs to in-flight broadcast sends: asyncio keeps only a weak ref
        # to a bare ensure_future() task, which may be GC'd mid-send (documented
        # 3.14 pitfall). Held here on the loop thread, dropped on completion.
        self._pending: Set[asyncio.Task] = set()

        self._app = web.Application(middlewares=[self._security_middleware])
        self._app.on_response_prepare.append(self._strip_server_header)
        self._app.add_routes([
            web.get('/', self._client_page),      # real mobile client (Phase 4)
            web.get('/dev', self._test_page),     # raw protocol test harness
            web.get('/ws', self._ws_handler),
            web.get('/manifest.webmanifest', self._manifest),   # PWA (4c)
            web.get('/icon-{size:\\d+}.png', self._icon),       # home-screen icon
            web.get('/apple-touch-icon.png', self._apple_icon),
            web.get('/apple-touch-icon-precomposed.png', self._apple_icon),
            web.get('/{tail:.*}', self._not_found),
        ])

    # ---- hardening ----------------------------------------------------------

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler):
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'no-referrer')
        resp.headers.setdefault('Cache-Control', 'no-store')
        # The page is fully self-contained: its own inline <style>/<script>, icons
        # from this server, and a WebSocket back to it. Nothing else may load or be
        # contacted, so nothing injected into the page could phone anywhere out.
        resp.headers.setdefault('Content-Security-Policy',
                                "default-src 'none'; img-src 'self' data:; "
                                "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                "connect-src 'self' ws: wss:; manifest-src 'self'; "
                                "base-uri 'none'; form-action 'none'")
        return resp

    @staticmethod
    async def _strip_server_header(_request: web.Request, response: web.StreamResponse) -> None:
        with suppress(Exception):
            del response.headers['Server']

    async def _not_found(self, _request: web.Request) -> web.Response:
        return web.Response(status=404, text='Not found')

    # ---- envelope -----------------------------------------------------------

    def _envelope(self, mtype: str, payload: dict) -> str:
        self._seq += 1
        return json.dumps({"v": PROTO_VERSION, "type": mtype,
                           "seq": self._seq, "ts": round(time.time(), 2),
                           "payload": payload})

    async def _send(self, ws: web.WebSocketResponse, mtype: str, payload: dict) -> None:
        # Serialise all writes to a given socket: without a per-connection lock,
        # concurrent send_str() calls could interleave on the same writer (aiohttp forbids it).
        lock = getattr(ws, '_tilau_send_lock', None)
        if lock is None:
            lock = asyncio.Lock()
            ws._tilau_send_lock = lock
        with suppress(Exception):
            async with lock:
                await ws.send_str(self._envelope(mtype, payload))

    # ---- WebSocket ----------------------------------------------------------

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        # Cross-origin upgrades are refused: a page served by any other site must not
        # be able to open a control socket. Browsers send Origin on a WS upgrade; a same-origin one matches Host.
        origin = request.headers.get('Origin')
        if origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.headers.get('Host', ''):
                _log.warning("control: refused WS upgrade from origin %s", origin)
                raise web.HTTPForbidden(text='forbidden origin')
        ws = web.WebSocketResponse(heartbeat=None)
        await ws.prepare(request)

        # handshake: expect `hello` first
        try:
            first = await ws.receive(timeout=10)
        except Exception:  # noqa: BLE001
            await ws.close()
            return ws
        hello = self._parse(first)
        if not hello or hello.get('type') != 'hello':
            await self._send(ws, 'error', {"code": "BAD_MESSAGE",
                                           "message": "hello expected"})
            await ws.close()
            return ws
        p = hello.get('payload', {})
        if not (p.get('proto_min', 1) <= PROTO_VERSION <= p.get('proto_max', 1)):
            await self._send(ws, 'error', {"code": "UNSUPPORTED_VERSION",
                                           "message": "proto v1 only"})
            await ws.close()
            return ws
        device_id = str(p.get('client_id') or 'phone')

        # ---- pairing / auth (§7 web-http, no HMAC) : client sends `auth` after hello ----
        if self._pairing is not None:
            try:
                amsg = await ws.receive(timeout=15)
            except Exception:  # noqa: BLE001
                await ws.close()
                return ws
            auth = self._parse(amsg)
            ap = auth.get('payload', {}) if auth and auth.get('type') == 'auth' else None
            if ap is None:
                await self._send(ws, 'error', {"code": "AUTH_REQUIRED", "message": "auth expected"})
                await ws.close()
                return ws
            if ap.get('token'):  # first pairing (PT, one-time)
                aid = str(ap.get('device_id') or device_id)
                # Prefer an explicit client name; otherwise derive a readable one
                # from the User-Agent so devices aren't all labelled "Web".
                client_name = str(ap.get('display_name') or '').strip()
                if client_name and client_name.lower() != 'web':
                    dn = client_name
                else:
                    dn = _device_label_from_ua(request.headers.get('User-Agent', ''), aid)
                dt = self._pairing.pair(ap['token'], aid, dn)
                if not dt:
                    await self._send(ws, 'error', {"code": "AUTH_FAILED",
                                                   "message": "invalid or expired pairing code"})
                    await ws.close()
                    return ws
                device_id = aid
                await self._send(ws, 'paired', {"device_token": dt, "device_id": aid,
                                                "display_name": dn, "role": "observer"})
            elif ap.get('device_token') and ap.get('device_id'):  # reconnect (present DT)
                if not self._pairing.verify_token(str(ap['device_id']), str(ap['device_token'])):
                    await self._send(ws, 'error', {"code": "AUTH_FAILED",
                                                   "message": "unknown or revoked device"})
                    await ws.close()
                    return ws
                device_id = str(ap['device_id'])
            else:
                await self._send(ws, 'error', {"code": "AUTH_REQUIRED",
                                               "message": "pairing code or device token required"})
                await ws.close()
                return ws

        # controller lock (§7): a client reconnecting within the deadman grace window
        # re-attaches as the controller; everyone else is an observer.
        ws._tilau_device_id = device_id
        if self._controller == device_id:
            self._controller_ws = ws
            self._cancel_grace()
            _log.info("control: controller %s (re)attached", device_id)
        welcome = self._welcome_provider()
        welcome['role'] = 'controller' if self._controller == device_id else 'observer'
        # real channels from Artisan slider config (bounds/step/enabled) when the
        # command bridge is wired; the cached list is plain data (safe to read here)
        if self._bridge is not None:
            try:
                chans = self._bridge.channels()
                if chans:
                    welcome['channels'] = chans
            except Exception:  # noqa: BLE001
                pass
        await self._send(ws, 'welcome', welcome)
        await self._send(ws, 'snapshot', self._snapshot_provider())

        self._clients.add(ws)
        _log.info("control: client connected (%d total)", len(self._clients))
        try:
            async for msg in ws:
                data = self._parse(msg)
                if data and data.get('type') == 'command':
                    await self._handle_command(ws, data)
        finally:
            self._clients.discard(ws)
            # deadman (§7): if the controller drops, hold the lock for a grace
            # window so a brief wifi hiccup + reconnect keeps control. Hardware
            # never moves on its own — only a live controller can command.
            if ws is self._controller_ws:
                self._controller_ws = None
                self._start_grace()
            _log.info("control: client disconnected (%d left)", len(self._clients))
        return ws

    # ---- command routing / controller lock ----------------------------------

    async def _handle_command(self, ws: web.WebSocketResponse, data: dict) -> None:
        p = data.get('payload', {}) if isinstance(data.get('payload'), dict) else {}
        action = p.get('action')
        ref = data.get('seq')
        did = getattr(ws, '_tilau_device_id', None)

        if action == 'request_control':
            await self._request_control(ws, did, ref)
            return
        if action == 'release_control':
            if self._controller == did:
                self._free_controller()
                self.broadcast('event', {"kind": "control", "state": "released"})
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "ok"})
            return

        # every other command requires the controller role
        if self._controller != did or did is None:
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                         "reason": "NOT_CONTROLLER"})
            return

        if action == 'set_slider':
            self._coalesce_slider(ws, p, ref)
            return
        if action == 'mark':
            self._submit_command(ws, ref, {'kind': 'mark', 'milestone': p.get('milestone')})
            return
        if action == 'recorder':
            self._submit_command(ws, ref, {'kind': 'recorder', 'op': p.get('op'),
                                           'save': p.get('save')})
            return
        if action == 'save':
            self._submit_command(ws, ref, {'kind': 'save'})
            return
        if action == 'discard':
            self._submit_command(ws, ref, {'kind': 'discard', 'confirm': bool(p.get('confirm'))})
            return
        await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                     "reason": "BAD_MESSAGE"})

    async def _request_control(self, ws, did, ref) -> None:
        if did is None:
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                         "reason": "AUTH_REQUIRED"})
            return
        # free (or already ours) -> grant immediately (§7: 1st requester wins)
        if self._controller is None or self._controller == did:
            self._grant_controller(ws, did)
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "ok"})
            await self._send(ws, 'event', {"kind": "control", "state": "granted"})
            return
        # contested -> explicit desktop confirmation, never a silent takeover (§7)
        if self._bridge is None:
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                         "reason": "NOT_CONTROLLER"})
            return
        # one confirmation at a time — a 2nd contested request while a modal is
        # open would stack modals (re-entrant during exec()); reject as busy.
        if self._takeover_pending:
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                         "reason": "RATE_LIMITED"})
            return
        self._takeover_pending = True
        loop = self._loop

        def _done(allowed):  # runs on the Qt main thread -> marshal to the loop
            if loop is not None:
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._resolve_takeover(ws, did, ref, bool(allowed))))
        self._bridge.submit({'kind': 'confirm_takeover',
                             'requester_name': self._device_name(did), 'done': _done})

    async def _resolve_takeover(self, ws, did, ref, allowed) -> None:
        self._takeover_pending = False  # confirmation resolved (all paths)
        if getattr(ws, 'closed', False):
            # the requester left during the confirmation — abort, keep the
            # current controller. Granting to a dead socket would strand the lock
            # with no deadman (its disconnect handler already ran).
            return
        if not allowed:
            await self._send(ws, 'ack', {"ref_seq": ref, "status": "rejected",
                                         "reason": "NOT_CONTROLLER"})
            return
        old_ws = self._controller_ws
        if old_ws is not None and old_ws is not ws:
            await self._send(old_ws, 'event', {"kind": "control", "state": "revoked",
                                               "reason": "taken_over"})
        self._grant_controller(ws, did)
        await self._send(ws, 'ack', {"ref_seq": ref, "status": "ok"})
        await self._send(ws, 'event', {"kind": "control", "state": "granted"})

    def _grant_controller(self, ws, did) -> None:
        self._cancel_grace()
        self._controller = did
        self._controller_ws = ws

    def _free_controller(self) -> None:
        self._cancel_grace()
        self._controller = None
        self._controller_ws = None

    def _start_grace(self) -> None:
        self._cancel_grace()
        if self._loop is not None:
            self._grace_handle = self._loop.call_later(_GRACE_S, self._grace_expired)

    def _grace_expired(self) -> None:
        self._grace_handle = None
        if self._controller_ws is None:  # nobody reconnected in time -> release
            self._controller = None
            _log.info("control: controller lock released (deadman grace expired)")

    def _cancel_grace(self) -> None:
        if self._grace_handle is not None:
            self._grace_handle.cancel()
            self._grace_handle = None

    def _device_name(self, did) -> str:
        try:
            if self._pairing is not None:
                info = self._pairing.list_devices().get(did) or {}
                return str(info.get('name') or 'A phone')
        except Exception:  # noqa: BLE001
            pass
        return 'A phone'

    # ---- set_slider coalescing (§6 debounce) --------------------------------

    def _coalesce_slider(self, ws, p: dict, ref) -> None:
        channel = str(p.get('channel') or '')
        if not channel:
            return
        self._pending_slider[channel] = (p.get('value'), ref, ws)
        if p.get('final'):  # release -> flush now, bypass timer (§6)
            self._cancel_slider_timer(channel)
            self._flush_slider(channel)
        elif channel not in self._slider_timers and self._loop is not None:
            interval = _DRUM_DEBOUNCE if channel == 'drum' else _SLIDER_DEBOUNCE
            self._slider_timers[channel] = self._loop.call_later(
                interval, lambda c=channel: self._flush_slider(c))

    def _cancel_slider_timer(self, channel: str) -> None:
        h = self._slider_timers.pop(channel, None)
        if h is not None:
            h.cancel()

    def _flush_slider(self, channel: str) -> None:
        self._slider_timers.pop(channel, None)
        item = self._pending_slider.pop(channel, None)
        if item is None:
            return
        value, ref, ws = item
        if self._bridge is None:
            asyncio.ensure_future(self._send(ws, 'ack', {"ref_seq": ref,
                                  "status": "rejected", "reason": "CHANNEL_ABSENT"}))
            return
        loop = self._loop

        def _done(res):  # runs on the Qt main thread -> marshal back to the loop
            if loop is not None:
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._after_slider(ws, ref, res)))
        self._bridge.submit({'kind': 'set_slider', 'channel': channel,
                             'value': value, 'done': _done})

    async def _after_slider(self, ws, ref, res: dict) -> None:
        ack = {"ref_seq": ref, "status": res.get('status', 'rejected')}
        for k in ('channel', 'applied_value', 'advisory', 'reason'):
            if res.get(k) is not None:
                ack[k] = res[k]
        await self._send(ws, 'ack', ack)

    # ---- simple commands (mark / recorder) via the bridge -------------------

    def _submit_command(self, ws, ref, job: dict) -> None:
        if self._bridge is None:
            asyncio.ensure_future(self._send(ws, 'ack', {"ref_seq": ref,
                                  "status": "rejected", "reason": "BAD_MESSAGE"}))
            return
        loop = self._loop

        def _done(res):  # runs on the Qt main thread -> marshal back to the loop
            if loop is not None:
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._after_command(ws, ref, res)))
        job['done'] = _done
        self._bridge.submit(job)

    async def _after_command(self, ws, ref, res: dict) -> None:
        ack = {"ref_seq": ref, "status": res.get('status', 'rejected')}
        for k in ('reason', 'saved', 'path'):
            if res.get(k) is not None:
                ack[k] = res[k]
        await self._send(ws, 'ack', ack)

    @staticmethod
    def _parse(msg) -> Optional[dict]:
        try:
            if msg is None or msg.type != web.WSMsgType.TEXT:
                return None
            return json.loads(msg.data)
        except Exception:  # noqa: BLE001
            return None

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if not self._clients:
                continue
            clock = 0.0
            with suppress(Exception):
                clock = float(self._snapshot_provider().get('clock', 0.0))
            for ws in list(self._clients):
                await self._send(ws, 'heartbeat', {"clock": clock})

    def broadcast(self, mtype: str, payload: dict) -> None:
        """Thread-safe fan-out (call from the Qt thread for telemetry)."""
        loop = self._loop
        if loop is None:
            return
        def _do():  # runs on the loop thread
            for ws in list(self._clients):
                t = asyncio.ensure_future(self._send(ws, mtype, payload))
                self._pending.add(t)
                t.add_done_callback(self._pending.discard)
        loop.call_soon_threadsafe(_do)

    def client_count(self) -> int:
        return len(self._clients)

    def attach_bridge(self, bridge) -> None:
        """Wire the downward command path (CommandBridge on the Qt main thread)."""
        self._bridge = bridge

    # ---- real client (Phase 4) ----------------------------------------------

    async def _client_page(self, _request: web.Request) -> web.Response:
        if not self._client_html:
            from tilauscope.webclient import CLIENT_HTML
            self._client_html = CLIENT_HTML.replace('__TL_I18N__', self._i18n_json)
        return web.Response(text=self._client_html, content_type='text/html')

    # ---- PWA install: manifest + home-screen icon (Phase 4c) ----------------

    async def _manifest(self, _request: web.Request) -> web.Response:
        import json
        from tilauscope.webclient_assets import MANIFEST
        return web.Response(text=json.dumps(MANIFEST),
                            content_type='application/manifest+json')

    async def _icon(self, request: web.Request) -> web.Response:
        from tilauscope.webclient_assets import icon_png
        try:
            size = int(request.match_info.get('size', '512'))
        except ValueError:
            size = 512
        return web.Response(body=icon_png(size), content_type='image/png',
                            headers={'Cache-Control': 'max-age=86400'})

    async def _apple_icon(self, _request: web.Request) -> web.Response:
        from tilauscope.webclient_assets import icon_png
        return web.Response(body=icon_png(180), content_type='image/png',
                            headers={'Cache-Control': 'max-age=86400'})

    # ---- test page ----------------------------------------------------------

    async def _test_page(self, _request: web.Request) -> web.Response:
        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>TilauScope Control — test</title>"
            "<style>body{font:14px system-ui;background:#1E1E2E;color:#CDD6F4;margin:0;padding:16px}"
            "h1{font-size:16px;color:#89B4FA}#log{white-space:pre-wrap;font-family:ui-monospace,monospace;"
            "font-size:12px;background:#181825;border:1px solid #313244;border-radius:8px;padding:10px;"
            "margin-top:10px;max-height:70vh;overflow:auto}.ok{color:#A6E3A1}</style>"
            "<h1>TilauScope · Control (test)</h1>"
            "<div id=live style='font-family:ui-monospace,monospace;font-size:15px;"
            "margin:6px 0'>—</div>"
            "<div id=ctl style='margin:8px 0;font-size:13px'>"
            "<button id=req>Request control</button> "
            "<span id=role style='color:#F9E2AF'>observer</span>"
            "<div id=sliders></div>"  # rows built from welcome.channels (real names)
            "<div class=r style='margin-top:6px'>"
            "<button data-m=CHARGE>CHARGE</button> <button data-m=DRYe>DRYe</button> "
            "<button data-m=FCs>FCs</button> <button data-m=SCs>SCs</button> "
            "<button data-m=DROP>DROP</button></div>"
            "<div class=r><button id=rec_start>START</button> "
            "<button id=rec_stop>STOP</button></div>"
            "<div class=r><button id=stop_save>STOP+save</button> "
            "<button id=stop_keep>STOP keep</button> "
            "<button id=save_now>Save</button> <button id=discard>Discard</button></div>"
            "</div><div id=log>connecting…</div>"
            "<script>"
            "var L=document.getElementById('log'),V=document.getElementById('live');"
            "function p(s){L.textContent=(s+'\\n'+L.textContent).slice(0,4000);}"
            "var PT=(location.hash.match(/pt=([^&]+)/)||[])[1];"
            # iPadOS Safari lies with a desktop 'Macintosh' UA; touch points give
            # it away so we hand the server a correct name instead of 'Web'.
            "function DN(){var u=navigator.userAgent;"
            "if(/Macintosh/.test(u)&&navigator.maxTouchPoints>1)return 'iPad';return 'Web';}"
            "var CID=localStorage.getItem('tcid')||('web-'+Math.random().toString(36).slice(2,8));"
            "localStorage.setItem('tcid',CID);var stop=false;"
            "var WS=null,S={},sq=10;"
            "function send(o){if(WS&&WS.readyState===1)WS.send(JSON.stringify(o));}"
            "function refresh(){for(var k in S){var e=document.getElementById('v_'+k);"
            "if(e)e.textContent=S[k];}}"
            "function buildSliders(chans){var box=document.getElementById('sliders');box.innerHTML='';"
            "(chans||[]).forEach(function(ch){var st=ch.step||1;"
            "var row=document.createElement('div');row.className='r';"
            "row.appendChild(document.createTextNode(ch.label+' '));"
            "var mn=document.createElement('button');mn.textContent='−';"
            "mn.setAttribute('data-c',ch.id);mn.setAttribute('data-d',-st);row.appendChild(mn);"
            "row.appendChild(document.createTextNode(' '));"
            "var v=document.createElement('b');v.id='v_'+ch.id;v.textContent='–';row.appendChild(v);"
            "row.appendChild(document.createTextNode(' '));"
            "var pl=document.createElement('button');pl.textContent='+';"
            "pl.setAttribute('data-c',ch.id);pl.setAttribute('data-d',st);row.appendChild(pl);"
            "box.appendChild(row);});refresh();}"
            "document.getElementById('req').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'request_control'}});};"
            "document.getElementById('sliders').addEventListener('click',function(ev){var b=ev.target;"
            "if(!b||b.tagName!=='BUTTON'||!b.getAttribute('data-c'))return;"
            "var c=b.getAttribute('data-c'),d=+b.getAttribute('data-d');var cur=(S[c]!=null?S[c]:0)+d;"
            "send({v:1,type:'command',seq:++sq,ts:Date.now()/1000,"
            "payload:{action:'set_slider',channel:c,value:cur,final:true}});});"
            "document.querySelectorAll('#ctl button[data-m]').forEach(function(b){b.onclick=function(){"
            "send({v:1,type:'command',seq:++sq,ts:Date.now()/1000,"
            "payload:{action:'mark',milestone:b.getAttribute('data-m')}});};});"
            "document.getElementById('rec_start').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'recorder',op:'start'}});};"
            "document.getElementById('rec_stop').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'recorder',op:'stop'}});};"
            "document.getElementById('stop_save').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'recorder',op:'stop',save:true}});};"
            "document.getElementById('stop_keep').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'recorder',op:'stop',save:false}});};"
            "document.getElementById('save_now').onclick=function(){send({v:1,type:'command',"
            "seq:++sq,ts:Date.now()/1000,payload:{action:'save'}});};"
            "document.getElementById('discard').onclick=function(){if(confirm('Discard roast?'))"
            "send({v:1,type:'command',seq:++sq,ts:Date.now()/1000,payload:{action:'discard',confirm:true}});};"
            "function connect(){var ws=new WebSocket('ws://'+location.host+'/ws');"
            "ws.onopen=function(){WS=ws;V.innerHTML='<span class=ok>connected</span>';"
            "ws.send(JSON.stringify({v:1,type:'hello',seq:1,ts:Date.now()/1000,"
            "payload:{client_id:CID,client_ver:'0',proto_min:1,proto_max:1}}));"
            "var DT=localStorage.getItem('tdt');"
            "if(DT){ws.send(JSON.stringify({v:1,type:'auth',seq:2,ts:Date.now()/1000,"
            "payload:{device_id:CID,device_token:DT}}));}"
            "else if(PT){ws.send(JSON.stringify({v:1,type:'auth',seq:2,ts:Date.now()/1000,"
            "payload:{token:PT,device_id:CID,display_name:DN()}}));}"
            "else{p('no pairing code — open the link from TilauScope > Pair a phone');}};"
            "ws.onmessage=function(e){var m=JSON.parse(e.data),d=m.payload||{};"
            "if(m.type==='paired'){localStorage.setItem('tdt',d.device_token);p('paired OK');}"
            "else if(m.type==='welcome'){buildSliders(d.channels);}"
            "else if(m.type==='telemetry'||m.type==='snapshot'){var s=m.type==='snapshot'?'(snap) ':'';"
            "if(d.sliders){for(var k in d.sliders)S[k]=d.sliders[k];refresh();}"
            "V.textContent=s+'BT '+(d.bt!=null?d.bt:'-')+'  ET '+(d.et!=null?d.et:'-')+"
            "'  RoR '+(d.ror!=null?d.ror:'-')+'  · '+(d.phase||'');}"
            "else if(m.type==='error'){V.innerHTML='<span style=color:#F38BA8>'+(d.code||'error')+'</span>';"
            "if(d.code==='AUTH_FAILED'){localStorage.removeItem('tdt');stop=true;}}"
            "else if(m.type==='ack'){if(d.channel&&d.applied_value!=null){S[d.channel]=d.applied_value;refresh();}}"
            "else if(m.type==='event'&&d.kind==='control'){var r=document.getElementById('role');"
            "if(r)r.textContent=(d.state==='granted'?'controller':(d.state||'observer'));}"
            "p(m.type+': '+JSON.stringify(d));};"
            "ws.onclose=function(){if(!stop){p('— closed, reconnecting… —');setTimeout(connect,2000);}};"
            "ws.onerror=function(){try{ws.close();}catch(e){}};}"
            "connect();"
            "</script>"
        )
        return web.Response(text=html, content_type='text/html')

    # ---- lifecycle ----------------------------------------------------------

    async def _startup(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self._port)
        await asyncio.wait_for(site.start(), 0.7)
        self._hb_task = asyncio.ensure_future(self._heartbeat_loop())

    @staticmethod
    def _start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            for task in asyncio.all_tasks(loop):
                task.cancel()
            for t in [t for t in asyncio.all_tasks(loop) if not (t.done() or t.cancelled())]:
                with suppress(asyncio.CancelledError):
                    loop.run_until_complete(t)
        except Exception as e:  # noqa: BLE001
            _log.exception(e)
        finally:
            loop.close()

    def startWeb(self) -> bool:
        _log.info('start TilauWebControl on port %s', self._port)
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._start_background_loop,
                              args=(self._loop,), daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._startup(), self._loop)
        future.result()
        self._register_bonjour()
        return True

    def stopWeb(self) -> None:
        _log.info('stop TilauWebControl')
        self._unregister_bonjour()
        if self._loop is not None:
            if self._runner is not None:
                future = asyncio.run_coroutine_threadsafe(self._runner.cleanup(), self._loop)
                with suppress(Exception):
                    future.result(timeout=2)  # never wedge app shutdown
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
        if self._thread is not None:
            self._thread.join(timeout=2)  # daemon thread; give up rather than hang
            self._thread = None

    # ---- Bonjour ------------------------------------------------------------

    @staticmethod
    def _local_ipv4s() -> list:
        ips = []
        try:
            import ifaddr
            for adapter in ifaddr.get_adapters():
                for ip in adapter.ips:
                    if isinstance(ip.ip, str) and not ip.ip.startswith('127.') \
                            and not ip.ip.startswith('169.254.'):
                        ips.append(ip.ip)
        except Exception as e:  # noqa: BLE001
            _log.debug(f"ifaddr enumeration failed: {e}")
        return ips

    def _register_bonjour(self) -> None:
        try:
            from zeroconf import Zeroconf, ServiceInfo
            ips = self._local_ipv4s()
            if not ips:
                _log.warning('control: no LAN IPv4 found, Bonjour skipped')
                return
            self._zc_info = ServiceInfo(
                type_='_tilauscope._tcp.local.',
                name='TilauScope Control._tilauscope._tcp.local.',
                addresses=[socket.inet_aton(ip) for ip in ips],
                port=self._port,
                properties={b'proto': b'1',
                            b'roaster': self._roaster_name.encode('utf-8', 'replace'),
                            b'pairing': b'required'},
            )
            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._zc_info)
            _log.info('control: registered _tilauscope._tcp on %s', ips)
        except Exception as e:  # noqa: BLE001
            _log.warning(f"control: Bonjour registration failed: {type(e).__name__}: {e}")

    def _unregister_bonjour(self) -> None:
        try:
            if self._zeroconf is not None and self._zc_info is not None:
                self._zeroconf.unregister_service(self._zc_info)
                self._zeroconf.close()
        except Exception as e:  # noqa: BLE001
            _log.debug(f"control: Bonjour unregister: {e}")
        self._zeroconf = None
        self._zc_info = None

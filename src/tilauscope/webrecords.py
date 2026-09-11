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

# Record web server — phone-facing read-only record pages (wiki/QR-Scan-Spec.md §4).
# A label QR opens http://tilauscope.local:{port}/roast/{roastUUID}; GET-only, LAN-only,
# no auth. Runs off the Qt thread — providers must only touch plain-python data.

import io
import re
import ast
import html
import asyncio
import logging
import socket
from contextlib import suppress
from pathlib import Path
from threading import Thread
from typing import Final, Optional, Callable

from aiohttp import web

_log: Final[logging.Logger] = logging.getLogger(__name__)

_BONJOUR_HOST: Final[str] = 'tilauscope.local.'
_UUID_IN_BEANS = re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')
_MAX_PROFILE_BYTES: Final[int] = 32 * 1024 * 1024
_MAX_PROFILE_READS: Final[int] = 4
_MAX_CURVE_RENDERS: Final[int] = 2

# Catppuccin Mocha — same identity as the app and the desktop roast card.
# Deliberately a copy, not an import: this module depends on neither Qt nor any
# tilauscope module. Must be re-synced by hand if THEME's tokens change.
_BG = '#1E1E2E'
_SURFACE = '#181825'
_TEXT = '#CDD6F4'
_SUBTEXT = '#A6ADC8'
_ACCENT = '#89B4FA'
_GREEN = '#A6E3A1'
_RED = '#F38BA8'
_BORDER = '#313244'
_C_BT = '#89B4FA'
_C_ET = '#F9E2AF'


def _fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------------------
# Pure profile helpers (no Qt)
# ---------------------------------------------------------------------------

def read_profile(filepath: str) -> Optional[dict]:
    """Parse an .alog (Artisan native repr(dict), UTF-8 — cf. artisanlib.util)."""
    try:
        path = Path(filepath)
        if path.stat().st_size > _MAX_PROFILE_BYTES:
            _log.warning("webrecords: profile exceeds %d bytes: %s",
                         _MAX_PROFILE_BYTES, filepath)
            return None
        data = ast.literal_eval(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        _log.error(f"webrecords: cannot read {filepath}: {e}")
        return None


def roast_summary(profile: dict) -> dict:
    """Extract the displayable summary (same fields as the desktop roast card)."""
    computed = profile.get('computed') or {}
    out: dict = {'title': str(profile.get('title') or '').strip()}

    prefix = str(profile.get('roastbatchprefix', '') or '')
    nr = int(profile.get('roastbatchnr', 0) or 0)
    out['batch'] = f"{prefix}{nr}" if nr > 0 else ''

    bits = [str(profile.get('roastdate') or '').strip()]
    rt = str(profile.get('roasttime') or '').strip()
    if rt:
        bits.append(rt[:5])
    out['date'] = ' · '.join(b for b in bits if b)

    out['weight_line'] = ''
    w = profile.get('weight')
    if w and len(w) >= 3:
        try:
            w_in, w_out, unit = float(w[0]), float(w[1]), str(w[2])
            if w_in > 0:
                line = f"CHARGE {w_in:g} {unit}"
                if w_out > 0:
                    loss = (w_in - w_out) / w_in * 100.0
                    line += f"  →  DROP {w_out:g} {unit}  ·  loss {loss:.1f} %"
                out['weight_line'] = line
        except (TypeError, ValueError):
            pass

    stats = []
    try:
        agtron = int(float(profile.get('ground_color') or 0))
        if agtron > 0:
            stats.append(f"Agtron {agtron}")
    except (TypeError, ValueError):
        pass
    drop_t = float(computed.get('DROP_time') or 0)
    fcs_t = float(computed.get('FCs_time') or 0)
    if drop_t > 0 and 0 < fcs_t < drop_t:
        stats.append(f"DTR {(drop_t - fcs_t) / drop_t * 100.0:.0f} %")
    if drop_t > 0:
        stats.append(f"duration {_fmt_mmss(drop_t)}")
    out['stats_line'] = '   ·   '.join(stats)

    times = []
    for lbl, key in (('TP', 'TP_time'), ('DRYe', 'DRY_time'),
                     ('FC', 'FCs_time'), ('DROP', 'DROP_time')):
        try:
            t = float(computed.get(key) or 0)
        except (TypeError, ValueError):
            t = 0.0
        if t > 0:
            times.append(f"{lbl} {_fmt_mmss(t)}")
    out['times_line'] = ' · '.join(times)

    out['notes'] = str(profile.get('cuppingnotes') or '').strip()

    m = _UUID_IN_BEANS.search(str(profile.get('beans', '') or ''))
    out['bean_uuid'] = m.group(1).lower() if m else ''
    return out


def render_curve_png(profile: dict) -> Optional[bytes]:
    """BT/ET curve with event markers, rendered offline with the Agg backend
    (thread-safe: Figure + FigureCanvasAgg, no pyplot global state)."""
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        timex = profile.get('timex') or []
        bt = profile.get('temp2') or []
        et = profile.get('temp1') or []
        timeindex = profile.get('timeindex') or []
        computed = profile.get('computed') or {}
        if len(timex) < 2 or len(bt) != len(timex):
            return None
        charge_idx = timeindex[0] if timeindex and timeindex[0] > -1 else 0
        t0 = timex[charge_idx]
        xs = [(t - t0) / 60.0 for t in timex]

        fig = Figure(figsize=(6.0, 3.0), dpi=150, facecolor=_SURFACE)
        ax = fig.add_subplot(111)
        ax.set_facecolor(_SURFACE)
        if et and len(et) == len(timex):
            ax.plot(xs, et, color=_C_ET, linewidth=1.0, alpha=0.7, label='ET')
        ax.plot(xs, bt, color=_C_BT, linewidth=1.6, label='BT')

        marks = [('CHARGE', charge_idx if (timeindex and timeindex[0] > -1) else 0)]
        tp_idx = computed.get('TP_idx')
        if tp_idx and 0 < int(tp_idx) < len(timex):
            marks.append(('TP', int(tp_idx)))
        # sentinel convention: index 0 uses -1 for unmarked; 1..7 use 0
        for lbl, ti in (('DRYe', 1), ('FC', 2), ('DROP', 6)):
            if len(timeindex) > ti and timeindex[ti] > 0:
                marks.append((lbl, timeindex[ti]))
        y_top = max(bt) if bt else 0
        for lbl, idx in marks:
            if 0 <= idx < len(xs):
                ax.axvline(xs[idx], color='#6C7086', linewidth=0.7,
                           linestyle='--', alpha=0.8)
                ax.annotate(lbl, (xs[idx], y_top), fontsize=6.5, color=_SUBTEXT,
                            ha='center', xytext=(0, 4), textcoords='offset points')

        ax.tick_params(colors=_SUBTEXT, labelsize=7)
        for spine in ax.spines.values():
            spine.set_color(_BORDER)
        ax.grid(True, color=_BORDER, linewidth=0.4, alpha=0.5)
        ax.set_xlim(left=min(0.0, xs[0]))
        ax.margins(y=0.12)
        fig.tight_layout(pad=0.8)

        buf = io.BytesIO()
        FigureCanvasAgg(fig).print_png(buf)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        _log.warning(f"webrecords: curve rendering failed: {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# HTML (self-contained, mobile-first, no external assets)
# ---------------------------------------------------------------------------

def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{ background:{_BG}; color:{_TEXT}; margin:0; padding:16px;
         font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; }}
  .card {{ background:{_SURFACE}; border:1px solid {_BORDER}; border-radius:12px;
           padding:16px; max-width:640px; margin:0 auto; }}
  h1 {{ color:{_ACCENT}; font-size:1.15em; letter-spacing:.03em; margin:0 0 2px 0;
        font-family:'JetBrains Mono', ui-monospace, monospace; }}
  .sub {{ color:{_SUBTEXT}; font-size:.85em; margin-bottom:12px; }}
  .mono {{ font-family:'JetBrains Mono', ui-monospace, monospace; }}
  .w {{ font-weight:700; font-size:.95em; margin:10px 0 2px 0; }}
  .s {{ color:{_SUBTEXT}; font-size:.85em; margin:2px 0; }}
  .notes {{ font-style:italic; font-size:.9em; margin-top:10px;
            border-top:1px solid {_BORDER}; padding-top:10px; }}
  .ntitle {{ color:{_ACCENT}; font-size:.8em; font-weight:700; font-style:normal;
             margin-bottom:4px; }}
  img.curve {{ width:100%; border-radius:8px; margin:10px 0; display:block; }}
  a.btn {{ display:inline-block; margin-top:14px; padding:8px 16px; color:{_TEXT};
           background:{_BG}; border:1px solid {_BORDER}; border-radius:16px;
           text-decoration:none; font-weight:600; font-size:.9em; }}
  table.specs {{ width:100%; border-collapse:collapse; font-size:.9em; margin-top:8px; }}
  table.specs td {{ padding:5px 0; border-bottom:1px solid {_BORDER}; }}
  table.specs td:first-child {{ color:{_SUBTEXT}; width:42%; }}
  .err {{ color:{_RED}; }}
  .footer {{ color:{_SUBTEXT}; font-size:.7em; text-align:center; margin-top:14px; }}
</style></head>
<body><div class="card">{body}</div>
<div class="footer">TilauScope</div></body></html>"""


def _error_page(title: str, message: str, status: int = 404) -> web.Response:
    body = (f"<h1 class=\"err\">{html.escape(title)}</h1>"
            f"<p class=\"s\">{html.escape(message)}</p>")
    return web.Response(text=_page(title, body), content_type='text/html', status=status)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class TilauWebRecords:
    """Read-only record server + Bonjour registration of tilauscope.local.

    roast_resolver(roast_uuid) -> .alog filepath or None
    bean_resolver(uuid)        -> plain dict of GreenBean fields or None
    sack_resolver(sack_id)     -> owning bean uuid, or None if unassigned
    All three are called from the server thread and must only read
    plain-python data structures.
    """

    def __init__(self, port: int,
                 roast_resolver: Optional[Callable[[str], Optional[str]]] = None,
                 bean_resolver: Optional[Callable[[str], Optional[dict]]] = None,
                 sack_resolver: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self._port = port
        # resolvers are settable so TilauWebHost can start the server before BeanCave
        # exists; the no-op default returns None -> clean 404 on /roast and /bean.
        self._roast_resolver = roast_resolver or (lambda _u: None)
        self._bean_resolver = bean_resolver or (lambda _u: None)
        self._sack_resolver = sack_resolver or (lambda _s: None)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._runner: Optional[web.AppRunner] = None
        self._zeroconf = None
        self._zc_info = None
        self._png_cache: dict[str, tuple[float, bytes]] = {}  # uuid -> (mtime, png)
        self._profile_slots: Optional[asyncio.Semaphore] = None
        self._render_slots: Optional[asyncio.Semaphore] = None
        self._render_inflight: dict[str, asyncio.Task] = {}

        self._app = web.Application(middlewares=[self._security_middleware])
        self._app.on_response_prepare.append(self._strip_server_header)
        # Route params are charset/length-constrained at the router: anything
        # else falls through to the styled catch-all 404 (no reflection, no
        # framework default page).
        self._app.add_routes([
            web.get('/', self._index),
            web.get('/roast/{uuid:[0-9a-fA-F]{32}}', self._roast_page),
            web.get('/roast/{uuid:[0-9a-fA-F]{32}}/curve.png', self._roast_curve),
            web.get('/bean/{uuid:[0-9a-fA-F-]{36}}', self._bean_page),
            web.get('/sack/{sack_id:[A-Za-z0-9._-]{1,64}}', self._sack_page),
            web.get('/{tail:.*}', self._not_found),
        ])

    # ---- resolvers (settable by TilauWebHost / BeanCave) --------------------

    def set_resolvers(self,
                      roast_resolver: Optional[Callable[[str], Optional[str]]],
                      bean_resolver: Optional[Callable[[str], Optional[dict]]],
                      sack_resolver: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self._roast_resolver = roast_resolver or (lambda _u: None)
        self._bean_resolver = bean_resolver or (lambda _u: None)
        self._sack_resolver = sack_resolver or (lambda _s: None)

    def clear_resolvers(self) -> None:
        self._roast_resolver = lambda _u: None
        self._bean_resolver = lambda _u: None
        self._sack_resolver = lambda _s: None

    # ---- hardening ----------------------------------------------------------

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler):
        # Before anything is served: the plain-ws trade in protocol §7 is only
        # sound while the other end is on the home network. Checked here rather
        # than assumed from the bind address, which is every interface.
        from tilauscope.weblan import reject_remote_peer  # noqa: PLC0415
        if reject_remote_peer(request, 'records'):
            return web.Response(status=403, text='forbidden',
                                content_type='text/plain')
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'no-referrer')
        resp.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
            "form-action 'none'; base-uri 'none'; frame-ancestors 'none'")
        resp.headers.setdefault('Cache-Control', 'no-store')
        if isinstance(resp, web.HTTPException):
            raise resp
        return resp

    @staticmethod
    async def _strip_server_header(_request: web.Request,
                                   response: web.StreamResponse) -> None:
        # don't advertise python/aiohttp versions
        with suppress(KeyError):
            del response.headers['Server']

    # ---- handlers (server thread) ------------------------------------------

    async def _index(self, _request: web.Request) -> web.Response:
        body = ("<h1>TILAUSCOPE RECORDS</h1>"
                "<p class=\"s\">Scan a label QR code with your phone to open "
                "the matching roast or bean record here.</p>")
        return web.Response(text=_page('TilauScope', body), content_type='text/html')

    async def _not_found(self, _request: web.Request) -> web.Response:
        return _error_page('Not found', 'This page does not exist.')

    def _load_roast(self, roast_uuid: str) -> Optional[tuple[str, dict]]:
        filepath = self._roast_resolver(roast_uuid)
        if not filepath:
            return None
        profile = read_profile(filepath)
        return (filepath, profile) if profile else None

    async def _roast_page(self, request: web.Request) -> web.Response:
        roast_uuid = request.match_info['uuid'].lower()
        # file I/O + repr parse off the event loop (keeps the server responsive)
        slots = self._profile_slots
        if slots is None:
            raise web.HTTPServiceUnavailable(text='server starting')
        async with slots:
            loaded = await asyncio.get_running_loop().run_in_executor(
                None, self._load_roast, roast_uuid)
        if loaded is None:
            return _error_page('Roast not found',
                               'No roast with this identifier — is TilauScope '
                               'running with the right ALog directory?')
        _fp, profile = loaded
        s = roast_summary(profile)

        bean = self._bean_resolver(s['bean_uuid']) if s['bean_uuid'] else None
        display = (bean.get('name') if bean else '') or s['title'] or 'Roast'
        head = html.escape(display.upper()) + (
            f" — {html.escape(s['batch'])}" if s['batch'] else '')

        parts = [f"<h1>☕ {head}</h1>"]
        if s['date']:
            parts.append(f"<div class=\"sub\">roasted on {html.escape(s['date'])}</div>")
        parts.append(f"<img class=\"curve\" src=\"/roast/{roast_uuid}/curve.png\" "
                     f"alt=\"roast curve\">")
        if s['weight_line']:
            parts.append(f"<div class=\"w mono\">{html.escape(s['weight_line'])}</div>")
        if s['stats_line']:
            parts.append(f"<div class=\"s mono\">{html.escape(s['stats_line'])}</div>")
        if s['times_line']:
            parts.append(f"<div class=\"s mono\">{html.escape(s['times_line'])}</div>")
        if s['notes']:
            parts.append("<div class=\"notes\"><div class=\"ntitle\">Tasting notes"
                         f"</div>« {html.escape(s['notes'])} »</div>")
        if bean:
            parts.append(f"<a class=\"btn\" href=\"/bean/{s['bean_uuid']}\">"
                         f"🌱 Source bean sheet</a>")
        return web.Response(text=_page(display, ''.join(parts)),
                            content_type='text/html')

    async def _roast_curve(self, request: web.Request) -> web.Response:
        roast_uuid = request.match_info['uuid'].lower()
        filepath = self._roast_resolver(roast_uuid)
        if not filepath:
            return web.Response(status=404)
        try:
            mtime = Path(filepath).stat().st_mtime
        except OSError:
            return web.Response(status=404)
        cached = self._png_cache.get(roast_uuid)
        if cached and cached[0] == mtime:
            return web.Response(body=cached[1], content_type='image/png',
                                headers={'Cache-Control': 'private, max-age=300'})
        # Deduplicate simultaneous cache misses for one roast and cap distinct
        # matplotlib jobs.  run_in_executor alone only moves an unbounded queue off
        # the event loop; it does not provide backpressure.
        task = self._render_inflight.get(roast_uuid)
        if task is None:
            task = asyncio.create_task(self._render_curve(filepath))
            self._render_inflight[roast_uuid] = task
            task.add_done_callback(
                lambda done, key=roast_uuid: self._render_inflight.pop(key, None))
        png = await asyncio.shield(task)
        if png is None:
            return web.Response(status=404)
        if len(self._png_cache) >= 10:  # tiny LRU-ish cap
            self._png_cache.pop(next(iter(self._png_cache)))
        self._png_cache[roast_uuid] = (mtime, png)
        return web.Response(body=png, content_type='image/png',
                            headers={'Cache-Control': 'private, max-age=300'})

    async def _render_curve(self, filepath: str) -> Optional[bytes]:
        slots = self._render_slots
        if slots is None:
            return None

        def _parse_and_render() -> Optional[bytes]:
            profile = read_profile(filepath)
            return render_curve_png(profile) if profile else None

        async with slots:
            return await asyncio.get_running_loop().run_in_executor(None, _parse_and_render)

    async def _bean_page(self, request: web.Request) -> web.Response:
        uuid_str = request.match_info['uuid'].lower()
        bean = self._bean_resolver(uuid_str)
        if not bean:
            return _error_page('Bean not found',
                               'No green bean with this identifier in the '
                               'BeanCave catalogue.')
        name = str(bean.get('name') or 'Green bean')
        parts = [f"<h1>🌱 {html.escape(name.upper())}</h1>"]
        origin = ' · '.join(str(bean.get(k) or '').strip()
                            for k in ('country', 'farm') if str(bean.get(k) or '').strip())
        if origin:
            parts.append(f"<div class=\"sub\">{html.escape(origin)}</div>")
        rows = []
        for label, key, suffix in (
                ('Process', 'process', ''), ('Varieties', 'varieties', ''),
                ('Species', 'species', ''), ('Crop', 'crop', ''),
                ('Altitude', 'altitude', ' m'), ('Density', 'density', ' g/l'),
                ('SCA', 'sca', ''), ('Stock left', 'weight_left', ' g'),
                ('Supplier', 'supplier', '')):
            val = bean.get(key)
            if val in (None, '', 0, 0.0):
                continue
            rows.append(f"<tr><td>{label}</td>"
                        f"<td class=\"mono\">{html.escape(f'{val:g}' if isinstance(val, float) else str(val))}{suffix}</td></tr>")
        if rows:
            parts.append("<table class=\"specs\">" + ''.join(rows) + "</table>")
        notes = str(bean.get('flavour_notes') or '').strip()
        if notes:
            parts.append("<div class=\"notes\"><div class=\"ntitle\">Flavour notes"
                         f"</div>« {html.escape(notes)} »</div>")
        return web.Response(text=_page(name, ''.join(parts)), content_type='text/html')

    async def _sack_page(self, request: web.Request) -> web.Response:
        sack_id = request.match_info['sack_id']
        bean_uuid = self._sack_resolver(sack_id)
        if not bean_uuid:
            body = (f"<h1>🧺 SACK {html.escape(sack_id)}</h1>"
                    "<p class=\"s\">This label is not currently attached to "
                    "any coffee in the BeanCave catalogue.</p>")
            return web.Response(text=_page('Storage sack', body), content_type='text/html')
        raise web.HTTPFound(f"/bean/{bean_uuid}")

    # ---- lifecycle (weblcds pattern) ----------------------------------------

    async def _startup(self) -> None:
        self._profile_slots = asyncio.Semaphore(_MAX_PROFILE_READS)
        self._render_slots = asyncio.Semaphore(_MAX_CURVE_RENDERS)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self._port)
        await asyncio.wait_for(site.start(), 0.7)

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
        _log.info('start TilauWebRecords on port %s', self._port)
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._start_background_loop,
                              args=(self._loop,), daemon=True)
        self._thread.start()
        try:
            future = asyncio.run_coroutine_threadsafe(self._startup(), self._loop)
            future.result()
        except BaseException:
            # AppRunner.setup() may have succeeded before the socket bind fails.
            # Roll back both pieces here because TilauWebHost deliberately catches
            # the exception and otherwise loses the only reference to this thread.
            self._abort_startup()
            raise
        self._register_bonjour()
        return True

    def _abort_startup(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            if self._runner is not None:
                try:
                    future = asyncio.run_coroutine_threadsafe(self._runner.cleanup(), loop)
                    future.result(timeout=2)
                except Exception:  # noqa: BLE001
                    pass
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=2)
        self._runner = None
        self._loop = None
        self._thread = None

    def stopWeb(self) -> None:
        _log.info('stop TilauWebRecords')
        self._unregister_bonjour()
        loop = self._loop
        thread = self._thread
        if loop is not None:
            if self._runner is not None and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._runner.cleanup(), loop)
                try:
                    future.result(timeout=2)
                except Exception as e:  # noqa: BLE001
                    # Shutdown must remain bounded even when an aiohttp handler or
                    # executor never completes.  Cancelling is best-effort; stopping
                    # the loop below is the final backstop.
                    future.cancel()
                    _log.warning('webrecords: cleanup timed out or failed: %s', e)
            if loop.is_running():
                with suppress(RuntimeError):
                    loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=2)
            if thread.is_alive():
                _log.warning('webrecords: server thread did not stop within 2 seconds')
        self._runner = None
        self._loop = None
        self._thread = None

    # ---- Bonjour -------------------------------------------------------------

    @staticmethod
    def _local_ipv4s() -> list[str]:
        ips: list[str] = []
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
        """Advertise the server as tilauscope.local so printed labels stay valid
        across machines. Failure is non-fatal: the server still answers on the
        machine's own <hostname>.local / IP."""
        try:
            from zeroconf import Zeroconf, ServiceInfo
            ips = self._local_ipv4s()
            if not ips:
                _log.warning('webrecords: no LAN IPv4 found, Bonjour skipped')
                return
            self._zc_info = ServiceInfo(
                type_='_http._tcp.local.',
                name='TilauScope Records._http._tcp.local.',
                addresses=[socket.inet_aton(ip) for ip in ips],
                port=self._port,
                server=_BONJOUR_HOST,
            )
            self._zeroconf = Zeroconf()
            # allow_name_change: if another responder already claims the service
            # name (stale registration, second instance), register under a
            # suffixed name instead of failing — the tilauscope.local A record
            # is what printed labels rely on, not the service instance name
            self._zeroconf.register_service(self._zc_info, allow_name_change=True)
            _log.info('webrecords: registered %s on %s', _BONJOUR_HOST, ips)
        except Exception as e:  # noqa: BLE001
            _log.warning(f"webrecords: Bonjour registration failed: {type(e).__name__}: {e}")
            self._zeroconf = None
            self._zc_info = None

    def _unregister_bonjour(self) -> None:
        try:
            if self._zeroconf is not None:
                if self._zc_info is not None:
                    self._zeroconf.unregister_service(self._zc_info)
                self._zeroconf.close()
        except Exception as e:  # noqa: BLE001
            _log.debug(f"webrecords: Bonjour unregister: {e}")
        self._zeroconf = None
        self._zc_info = None

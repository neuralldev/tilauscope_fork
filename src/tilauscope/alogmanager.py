#
# ABOUT
# alog manager — persistent corpus index

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
# TiLau 2025

"""Single index over the .alog corpus, shared by every consumer.

An .alog is a repr(dict) of the whole roast, ~240 KB, dominated by the
timex/temp1/temp2 series. Every scalar a caller actually wants — roast date,
weights, bean field, colour readings — sits in the first few KB, and the
``computed`` block sits in the last few. Reading those two windows costs
~50x less than ast.literal_eval on the whole file (measured 0.065 s vs 3.3 s
over 97 logs), so the index never parses a full profile.

The index is persisted as JSON in the TilauScope data directory, keyed by the
indexed directory. Consumers read it synchronously; refreshing it is a
background pass that only touches files whose (mtime, size) moved.
"""

from dataclasses import dataclass, field
from mashumaro.mixins.json import DataClassJSONMixin
import ast as _ast
import json as _json
import os as _os
import re as _re
import threading as _threading
from pathlib import Path
from typing import Any, Final
import logging

from PyQt6.QtCore import (QObject, QRunnable, QSettings, QStandardPaths, QThread,
                          QThreadPool, pyqtSignal, pyqtSlot)

from artisanlib.util import (getDataDirectory, weight_units, convertWeight,
                             decodeLocalStrict, events_internal_to_external_value)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Bump on any change to the fields extracted below: a mismatch forces a full
# rebuild rather than serving entries that lack the new data.
INDEX_SCHEMA: Final[int] = 4

# Read windows. The head must cover every scalar key, the event lists AND the
# whole 'timex' array — the burner readings below turn event indices into times
# through it. The tail must cover the 'computed' block and 'pidSource'. Both are
# sized well past the observed extents (timex ends by 44 KB and pidSource sits
# within 4 KB of EOF on the reference corpus) so a long roast cannot silently
# truncate an entry; a value that does not fit is reported absent, never partial.
_HEAD_BYTES: Final[int] = 98304
_TAIL_BYTES: Final[int] = 65536

# etypes = [Air, Drum, Damper, Burner] — the burner is 3.
BURNER_ETYPE: Final[int] = 3

_UUID_RE: Final = _re.compile(r'uuid:\s*([a-fA-F0-9-]{36})')

# key -> whether a missing value is tolerable (all are: defaults apply)
_SCALAR_KEYS: Final[tuple[str, ...]] = (
    'roastisodate', 'roastepoch', 'roastUUID', 'title', 'beans', 'mode',
    'roastbatchprefix', 'roastbatchnr', 'ground_color', 'whole_color',
    'roastertype', 'machinesetup', 'pidSource',
    'ambientTemp', 'ambient_humidity', 'ambient_pressure',
    'tilau_exclude_learning', 'tilau_simulated',
)
_BLOCK_KEYS: Final[tuple[str, ...]] = ('weight', 'computed')
# Read only to derive the burner readings; never stored (timex alone is 20 KB).
_SERIES_KEYS: Final[tuple[str, ...]] = (
    'timex', 'timeindex', 'specialevents', 'specialeventstype', 'specialeventsvalue',
)

_OPENERS: Final[dict[bytes, bytes]] = {b'{': b'}', b'[': b']', b'(': b')'}


@dataclass
class AlogMetadata(DataClassJSONMixin):
    filename: str
    filepath_str: str
    mtime: float
    batch_prefix: str = ""
    batch_nr: int = 0
    title: str = ""
    bean_field: str = ""
    uuid: str = ""
    roastepoch: int = 0  # seconds since epoch from roastepoch field in .alog; 0 = unknown
    roast_uuid: str = ""  # Artisan roastUUID (hex-32) — QR scan lookup key
    # ── schema 2 ────────────────────────────────────────────────────────────
    size: int = 0
    roastisodate: str = ""
    mode: str = "C"            # unit the log was recorded in ('C' or 'F')
    roastertype: str = ""
    weight_in_g: float = 0.0   # green mass, unit honoured, always grams
    weight_out_g: float = 0.0  # roasted mass, idem
    ground_color: float = 0.0
    whole_color: float = 0.0
    exclude_learning: bool = False
    simulated: bool = False
    # Artisan's whole 'computed' block, verbatim. Kept whole rather than
    # cherry-picked so a new domain need does not cost a schema bump.
    computed: dict[str, Any] = field(default_factory=dict)
    # ── schema 3 ────────────────────────────────────────────────────────────
    machinesetup: str = ""
    pid_source: int = 1        # Artisan pidSource: 0/1 = BT, else ET
    # Top-level ambient readings as recorded (ambientTemp carries the log's own
    # unit — see `mode`). Distinct from computed.ambient_*, which the roast plan
    # reads; the preheat PID reads these, and the two are not interchangeable.
    ambient_temp: float = 20.0
    ambient_humidity: float = 50.0
    ambient_pressure: float = 1013.25
    # Burner percentage actually held at each milestone, read from the operator's
    # own events: mid-drying, mid-Maillard, mid-development, at FC, at DRY END.
    # None per slot when the phase is unmarked or no burner event covers it.
    heater_dry: "float | None" = None
    heater_maillard: "float | None" = None
    heater_dev: "float | None" = None
    heater_fc: "float | None" = None
    heater_de: "float | None" = None
    # False when the profile is incomplete (no CHARGE/DROP) or its series did not
    # fit the head window — the heater slots above are then not authoritative and
    # a caller that needs them must fall back on a full parse.
    heater_read: bool = False


@dataclass
class AlogCacheCollection(DataClassJSONMixin):
    records: dict[str, AlogMetadata] = field(default_factory=dict)


@dataclass
class _IndexFile(DataClassJSONMixin):
    schema: int = INDEX_SCHEMA
    directory: str = ""
    records: dict[str, AlogMetadata] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════════════
# Partial reading
# ════════════════════════════════════════════════════════════════════════════

def _slice_value(buf: bytes, key: str) -> "bytes | None":
    """Return the repr bytes of ``buf["<key>"]``, or None when absent.

    Walks the value with bracket matching and string awareness instead of a
    value regex, so a bean field containing braces or quotes cannot end the
    slice early.
    """
    m = _re.search(b"'" + _re.escape(key.encode()) + b"'\\s*:\\s*", buf)
    if m is None:
        return None
    i = m.end()
    if i >= len(buf):
        return None
    opener = buf[i:i + 1]
    closer = _OPENERS.get(opener)
    j = i
    depth = 0
    in_str = False
    quote = b""
    while j < len(buf):
        ch = buf[j:j + 1]
        if in_str:
            if ch == b"\\":
                j += 2
                continue
            if ch == quote:
                in_str = False
        elif ch in (b"'", b'"'):
            in_str = True
            quote = ch
        elif closer is not None:
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return buf[i:j + 1]
        elif ch in (b",", b"}"):
            return buf[i:j]
        j += 1
    return None  # truncated by the read window — treat as absent


def _literal(raw: "bytes | None") -> Any:
    if raw is None:
        return None
    try:
        return _ast.literal_eval(raw.decode('utf-8', 'replace').strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def _to_grams(raw_weight: object, position: int) -> float:
    """Convert ``weight`` = [in, out, unit] to grams, honouring the unit.

    A roast recorded in Kg is otherwise read as if it were grams.
    """
    if not isinstance(raw_weight, (list, tuple)) or len(raw_weight) <= position:
        return 0.0
    try:
        value = float(raw_weight[position])
    except (TypeError, ValueError):
        return 0.0
    unit = decodeLocalStrict(raw_weight[2], 'g') if len(raw_weight) >= 3 else 'g'
    try:
        unit_idx = weight_units.index(unit)
    except ValueError:
        unit_idx = 0  # unknown unit → assume grams
    return float(convertWeight(value, unit_idx, 0))  # index 0 = grams


def burner_events(data: dict, charge_ts: float) -> "list[tuple[float, float]]":
    """(seconds since charge, %) of the burner events only, sorted by time.

    Artisan doctrine: specialevents[k] is an INDEX into timex (not seconds);
    specialeventsvalue[k] is the internal value (8.0 -> 70 %), decoded by
    events_internal_to_external_value; the burner is etype 3.

    Single source: the corpus index and the roast plan both read the operator's
    hand from here. Reading it twice is how the two readings drift apart.
    """
    evt_idx = data.get("specialevents", []) or []
    evt_type = data.get("specialeventstype", []) or []
    evt_val = data.get("specialeventsvalue", []) or []
    tx = data.get("timex", []) or []
    out: list[tuple[float, float]] = []
    for k in range(min(len(evt_idx), len(evt_type), len(evt_val))):
        if int(evt_type[k]) != BURNER_ETYPE:
            continue
        i = int(evt_idx[k])
        if not (0 <= i < len(tx)):
            continue
        pct = float(events_internal_to_external_value(float(evt_val[k])))
        if not (0.0 <= pct <= 100.0):   # reject raw encodings / aberrations
            continue
        out.append((float(tx[i]) - charge_ts, pct))
    out.sort(key=lambda e: e[0])
    return out


def phase_heater(data: dict, phase_times: dict
                 ) -> "tuple[float | None, float | None, float | None, float | None, float | None]":
    """Burner % held at (mid-dry, mid-Maillard, mid-dev, FC, DRY END).

    "Held" = the last burner setting posted at or before the instant, so the
    charge setting carries forward until the operator moves it.
    """
    try:
        evt_idx = data.get("specialevents", []) or []
        ti = data.get("timeindex", []) or []
        tx = data.get("timex", []) or []
        if not (evt_idx and ti and tx) or ti[0] < 0:
            return None, None, None, None, None
        charge_ts = float(tx[ti[0]])
        burner = burner_events(data, charge_ts)
        if not burner:
            return None, None, None, None, None

        def _held_at(t_mid: float) -> "float | None":
            held = None
            for t_sc, pct in burner:
                if t_sc <= t_mid + 1e-6:
                    held = pct
                else:
                    break
            return held

        t_dry = phase_times.get("dry_end")
        t_fc = phase_times.get("fc_start")
        t_drop = phase_times.get("drop")
        dry = _held_at(t_dry / 2.0) if (t_dry and t_dry > 0) else None
        mai = (_held_at((t_dry + t_fc) / 2.0)
               if (t_dry and t_fc and t_fc > t_dry) else None)
        dev = (_held_at((t_fc + t_drop) / 2.0)
               if (t_fc and t_drop and t_drop > t_fc) else None)
        fc_h = _held_at(t_fc) if (t_fc and t_fc > 0) else None
        de_h = _held_at(t_dry) if (t_dry and t_dry > 0) else None
        return dry, mai, dev, fc_h, de_h
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        _log.debug("phase_heater failed: %s", exc)
        return None, None, None, None, None


def phase_times_from_profile(data: dict) -> "dict | None":
    """Milestones in seconds since CHARGE, or None when the roast is unusable."""
    ti = data.get("timeindex", []) or []
    tx = data.get("timex", []) or []
    # CHARGE=0, DRYEND=1, FCSTART=2, DROP=6
    if len(ti) < 7 or not tx or ti[0] == -1 or ti[6] == -1 or ti[6] <= ti[0]:
        return None
    try:
        charge_ts = tx[ti[0]]
        return {
            "dry_end":  tx[ti[1]] - charge_ts if ti[1] > 0 else None,
            "fc_start": tx[ti[2]] - charge_ts if ti[2] > 0 else None,
            "drop":     tx[ti[6]] - charge_ts,
        }
    except IndexError:
        return None


def read_alog_metadata(path: Path) -> "AlogMetadata | None":
    """Index one .alog from its head and tail windows. Never parses the series."""
    try:
        stat = path.stat()
    except OSError:
        return None
    size = stat.st_size
    if size == 0:
        return None
    try:
        with open(path, 'rb') as fh:
            head = fh.read(_HEAD_BYTES)
            tail = b""
            if size > _HEAD_BYTES:
                fh.seek(max(_HEAD_BYTES, size - _TAIL_BYTES))
                tail = fh.read()
    except OSError as exc:
        _log.debug("alog index: unreadable %s: %s", path.name, exc)
        return None

    def _get(key: str) -> Any:
        val = _literal(_slice_value(head, key))
        if val is None and tail:
            val = _literal(_slice_value(tail, key))
        return val

    values = {k: _get(k) for k in _SCALAR_KEYS + _BLOCK_KEYS}

    # A file with no roast date is not a profile we can place on a timeline.
    bean_field = str(values.get('beans') or "")
    uuid_match = _UUID_RE.search(bean_field)

    try:
        epoch_val = int(values.get('roastepoch') or 0)
    except (TypeError, ValueError):
        epoch_val = 0
    if epoch_val <= 0:
        epoch_val = int(stat.st_mtime)

    def _num(key: str) -> float:
        try:
            return float(values.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _num_default(key: str, default: float) -> float:
        # Artisan's own default when the key is absent — mirrors data.get(k, d)
        raw = values.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    raw_weight = values.get('weight')
    computed = values.get('computed')

    # Burner readings: needs the event lists AND timex, all of which live in the
    # head window. A profile whose series overflowed it yields heater_read=False
    # rather than a half-read answer.
    series = {k: _literal(_slice_value(head, k)) for k in _SERIES_KEYS}
    heater = (None, None, None, None, None)
    heater_read = False
    if all(series.get(k) is not None for k in _SERIES_KEYS):
        phase_times = phase_times_from_profile(series)
        if phase_times is not None:
            heater = phase_heater(series, phase_times)
            heater_read = True

    try:
        pid_source = int(values.get('pidSource') or 1)
    except (TypeError, ValueError):
        pid_source = 1

    return AlogMetadata(
        filename=path.name,
        filepath_str=str(path),
        mtime=stat.st_mtime,
        batch_prefix=str(values.get('roastbatchprefix') or ""),
        batch_nr=int(values.get('roastbatchnr') or 0),
        title=str(values.get('title') or ""),
        bean_field=bean_field,
        uuid=uuid_match.group(1) if uuid_match else "",
        roastepoch=epoch_val,
        roast_uuid=str(values.get('roastUUID') or ""),
        size=size,
        roastisodate=str(values.get('roastisodate') or ""),
        mode=str(values.get('mode') or "C"),
        roastertype=str(values.get('roastertype') or ""),
        weight_in_g=_to_grams(raw_weight, 0),
        weight_out_g=_to_grams(raw_weight, 1),
        ground_color=_num('ground_color'),
        whole_color=_num('whole_color'),
        exclude_learning=bool(values.get('tilau_exclude_learning') is True),
        simulated=bool(values.get('tilau_simulated') is True),
        computed=computed if isinstance(computed, dict) else {},
        machinesetup=str(values.get('machinesetup') or ""),
        pid_source=pid_source,
        ambient_temp=_num_default('ambientTemp', 20.0),
        ambient_humidity=_num_default('ambient_humidity', 50.0),
        ambient_pressure=_num_default('ambient_pressure', 1013.25),
        heater_dry=heater[0],
        heater_maillard=heater[1],
        heater_dev=heater[2],
        heater_fc=heater[3],
        heater_de=heater[4],
        heater_read=heater_read,
    )


# ════════════════════════════════════════════════════════════════════════════
# Directory scanning
# ════════════════════════════════════════════════════════════════════════════

def directory_signature(directory: Path) -> "tuple[int, int]":
    """(file count, total bytes) over the directory's .alog files.

    The cheap gate: unchanged signature means the index can be served without
    stat-ing anything else. It is a fast path, not the invalidation rule —
    per-file (mtime, size) still decides, so an in-place rewrite that keeps the
    same size is caught by the mtime pass below.
    """
    count = 0
    total = 0
    try:
        for f in directory.iterdir():
            if f.suffix.lower() == '.alog':
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
                count += 1
    except OSError:
        return (0, 0)
    return (count, total)


def scan_directory(directory: Path,
                   existing: "dict[str, AlogMetadata] | None" = None,
                   should_stop=None) -> "dict[str, AlogMetadata]":
    """Bring ``existing`` up to date against the directory. Pure, no Qt."""
    records: dict[str, AlogMetadata] = dict(existing or {})
    if not directory.is_dir():
        return records
    seen: set[str] = set()
    try:
        listing = list(directory.iterdir())
    except OSError as exc:
        _log.warning("alog index: cannot list %s: %s", directory, exc)
        return records
    for f in listing:
        if should_stop is not None and should_stop():
            return records  # partial but coherent: no pruning below
        if f.suffix.lower() != '.alog':
            continue
        f_str = str(f)
        seen.add(f_str)
        try:
            stat = f.stat()
        except OSError:
            continue
        hit = records.get(f_str)
        if hit is not None and hit.mtime == stat.st_mtime and hit.size == stat.st_size:
            continue
        meta = read_alog_metadata(f)
        if meta is not None:
            records[f_str] = meta
        elif hit is not None:
            del records[f_str]
    for gone in [p for p in records if p not in seen]:
        del records[gone]
    return records


# ════════════════════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════════════════════

def index_path() -> Path:
    """``<data dir>/tilauscope/alog_index.json`` — outside the alog directory.

    Deliberately not stored next to the profiles: the corpus stays clean, and
    a stale index cannot travel with a copied or synced roast folder.
    """
    base = None
    try:
        # Needs a live QCoreApplication; called early enough that it may not
        # exist yet, in which case the platform location is the right answer.
        base = getDataDirectory()
    except (AttributeError, RuntimeError):
        base = None
    if not base:
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base) / "tilauscope" / "alog_index.json"


def load_index(directory: Path) -> "dict[str, AlogMetadata]":
    """Load the persisted index for ``directory``. Any problem yields {}."""
    path = index_path()
    try:
        if not path.is_file():
            return {}
        payload = _json.loads(path.read_text(encoding='utf-8'))
        idx = _IndexFile.from_dict(payload)
    except Exception as exc:  # noqa: BLE001 — a broken index must never block startup
        _log.warning("alog index: unreadable, rebuilding (%s)", exc)
        return {}
    if idx.schema != INDEX_SCHEMA:
        _log.info("alog index: schema %s != %s, rebuilding", idx.schema, INDEX_SCHEMA)
        return {}
    if idx.directory != str(directory):
        _log.info("alog index: built for another directory, rebuilding")
        return {}
    return idx.records


def save_index(directory: Path, records: "dict[str, AlogMetadata]") -> None:
    """Write the index atomically (tmp + replace) so a crash cannot truncate it."""
    path = index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Two threads may save concurrently (BeanCave indexer, routine check):
        # give each its own tmp so only the atomic replace races, never the write.
        tmp = path.with_suffix(f'.{_os.getpid()}.{_threading.get_ident()}.tmp')
        payload = _IndexFile(schema=INDEX_SCHEMA, directory=str(directory),
                             records=records).to_dict()
        tmp.write_text(_json.dumps(payload), encoding='utf-8')
        _os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 — the index is a cache, never fatal
        _log.warning("alog index: cannot save (%s)", exc)


# ════════════════════════════════════════════════════════════════════════════
# Process-wide access
# ════════════════════════════════════════════════════════════════════════════

class AlogIndex:
    """Single in-process view of the corpus index, backed by the JSON file.

    ``records()`` is synchronous and may serve a slightly stale snapshot —
    that is the point: no caller blocks on disk. ``refresh()`` reconciles.
    """

    _instance: "AlogIndex | None" = None

    def __init__(self) -> None:
        self._directory: "Path | None" = None
        self._records: dict[str, AlogMetadata] = {}
        self._signature: "tuple[int, int] | None" = None
        # Serialises refresh/adopt: several consumers can reconcile at once
        # (BeanCave's indexer, the routine check, the post-save hook).
        self._lock = _threading.RLock()

    @classmethod
    def instance(cls) -> "AlogIndex":
        if cls._instance is None:
            cls._instance = AlogIndex()
        return cls._instance

    def records(self, directory: "Path | str | None" = None) -> "dict[str, AlogMetadata]":
        """Entries for ``directory``, loading the persisted index on first use."""
        if directory is None:
            return self._records
        d = Path(directory)
        with self._lock:
            if self._directory != d:
                self._directory = d
                self._records = load_index(d)
                self._signature = None
            return self._records

    def refresh(self, directory: "Path | str | None" = None,
                should_stop=None) -> "dict[str, AlogMetadata]":
        """Reconcile against disk and persist. Blocking — call off the GUI thread.

        Returns immediately when the directory signature is unchanged, which is
        the common case (~1 ms) once the index exists.
        """
        d = Path(directory) if directory is not None else self._directory
        if d is None:
            return self._records
        with self._lock:
            records = self.records(d)
            sig = directory_signature(d)
            if self._signature == sig and records:
                return records
            updated = scan_directory(d, records, should_stop)
            changed = updated != records
            self._records = updated
            self._signature = sig
            if changed:
                save_index(d, updated)
            return updated

    def adopt(self, directory: "Path | str", records: "dict[str, AlogMetadata]") -> None:
        """Take a set of entries computed elsewhere (a worker) and persist it."""
        d = Path(directory)
        with self._lock:
            self._directory = d
            self._records = records
            self._signature = directory_signature(d)
            save_index(d, records)

    def invalidate(self) -> None:
        """Drop the cheap gate so the next refresh re-stats every file."""
        self._signature = None

    def forget(self) -> None:
        """Drop the in-memory snapshot entirely.

        The persisted file needs no cleanup: it records which directory it was
        built for, and load_index() refuses one built for another.
        """
        with self._lock:
            self._directory = None
            self._records = {}
            self._signature = None


_refresh_queued: "set[str]" = set()
_refresh_lock = _threading.Lock()


class _RefreshRunnable(QRunnable):
    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._directory = directory

    def run(self) -> None:
        try:
            AlogIndex.instance().refresh(self._directory)
        except Exception as exc:  # noqa: BLE001 — a cache refresh is never fatal
            _log.warning("alog index: background refresh failed (%s)", exc)
        finally:
            with _refresh_lock:
                _refresh_queued.discard(str(self._directory))


def refresh_in_background(directory: "Path | str | None") -> None:
    """Fire-and-forget reconciliation. Cheap when nothing moved.

    Coalesced: a batch that rewrites fifty profiles in a loop schedules one
    scan, not fifty. The pass already running picks up whatever lands during it,
    and the per-file (mtime, size) diff makes a redundant pass nearly free.
    """
    if not directory:
        return
    d = Path(directory)
    if not d.is_dir():
        return
    with _refresh_lock:
        if str(d) in _refresh_queued:
            return
        _refresh_queued.add(str(d))
    QThreadPool.globalInstance().start(_RefreshRunnable(d))


def note_profile_saved(saved_path: "Path | str | None") -> None:
    """Fold a freshly written profile into the index, off-thread.

    Only when it landed in the indexed folder: a profile saved elsewhere (an
    export, a copy, a one-off "Save as" outside the roast folder) must not
    repoint the index at that folder, which would then be persisted in place of
    the real corpus.
    """
    if not saved_path:
        return
    try:
        folder = Path(saved_path).parent
        configured = QSettings().value('alogDirectory', "", str)
        if not configured or Path(configured) != folder:
            return
    except Exception:  # noqa: BLE001
        return
    # A profile rewritten in place (a repair, a re-save) can leave the file count
    # AND the total size untouched, which the cheap signature gate would read as
    # "nothing moved". Drop the gate so the per-file (mtime, size) pass runs.
    AlogIndex.instance().invalidate()
    refresh_in_background(folder)


def directory_changed(directory: "Path | str | None") -> None:
    """Call when the operator picks a different alog folder.

    Drops the snapshot built for the previous folder and rebuilds the new one
    off-thread, so the first consumer to ask does not pay the scan.
    """
    AlogIndex.instance().forget()
    _log.info("alog index: directory changed to %s — rebuilding", directory)
    refresh_in_background(directory)


class _AlogCacheIndexingWorker(QObject):
    """Background worker that updates a shared metadata collection.

    Seeded from the persisted index, so a cold start costs one partial-read
    pass over the corpus and every later start costs the signature check.
    """
    finished = pyqtSignal(dict)

    def __init__(self, directory: Path, existing_records: "dict[str, AlogMetadata]"):
        super().__init__()
        self.directory = Path(directory)
        self.records = dict(existing_records)

    @pyqtSlot()
    def run(self) -> None:
        thread = QThread.currentThread()

        def _stop() -> bool:
            return bool(thread is not None and thread.isInterruptionRequested())

        try:
            index = AlogIndex.instance()
            if not self.records:
                self.records = dict(index.records(self.directory))
            merged = scan_directory(self.directory, self.records, _stop)
            if not _stop():
                index.adopt(self.directory, merged)
            self.records = merged
        except Exception as e:  # noqa: BLE001
            _log.error(f"Error updating Alog metadata cache: {e}", exc_info=True)

        self.finished.emit(self.records)

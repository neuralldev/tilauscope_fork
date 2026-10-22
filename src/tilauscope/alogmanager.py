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
import threading as _threading
from pathlib import Path
from typing import Final
import logging

from PyQt6.QtCore import (QObject, QRunnable, QSettings, QStandardPaths, QThread,
                          QThreadPool, pyqtSignal, pyqtSlot)

from artisanlib.util import getDataDirectory

# The index itself (partial reader, records, scan, file format) lives in the
# library shared with the tablet; this module adds the desktop's location and
# its Qt background refresh.
from tilaucore import alog_index as _core
from tilaucore.alog_index import (  # noqa: F401  (re-exported for the desktop's readers)
    BURNER_ETYPE, INDEX_SCHEMA, AlogMetadata, _literal, _slice_value, _to_grams, burner_events,
    directory_signature, phase_heater, phase_times_from_profile, read_alog_metadata, scan_directory)

_log: Final[logging.Logger] = logging.getLogger(__name__)

@dataclass
class AlogCacheCollection(DataClassJSONMixin):
    records: dict[str, AlogMetadata] = field(default_factory=dict)


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
    return _core.load_index(index_path(), directory)


def save_index(directory: Path, records: "dict[str, AlogMetadata]") -> None:
    """Write the index atomically (tmp + replace) so a crash cannot truncate it."""
    _core.save_index(index_path(), directory, records)


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

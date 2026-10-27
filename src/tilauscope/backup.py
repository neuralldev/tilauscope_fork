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

"""Backup and restore on this machine: where the data lives, the settings store, the restart.

The archive itself is tilaucore.backup. A restore is applied by the NEXT start
(``apply_pending_restore``, called from main.py before the first settings
read): applied live, Artisan's own settings save on quit would write the old
session back over it.
"""

from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final

from PyQt6.QtCore import (QByteArray, QDate, QDateTime, QObject, QPoint, QPointF, QRect, QRectF, QSettings,
                          QSize, QSizeF, QStandardPaths, QTime, Qt, pyqtSignal)
from PyQt6.QtGui import QColor

from tilaucore import backup as core

_log = logging.getLogger(__name__)

KEY_FOLDER: Final[str] = "tilauscope/backup/folder"
KEY_AUTO: Final[str] = "tilauscope/backup/auto"
KEY_EXTRA: Final[str] = "tilauscope/backup/extra_folder"
KEY_KEEP: Final[str] = "tilauscope/backup/keep"
KEY_LAST_AUTO: Final[str] = "tilauscope/backup/last_auto"          # epoch of the last automatic run
KEY_LAST_RESULT: Final[str] = "tilauscope/backup/last_result"      # 'ok' | 'extra_failed' | 'failed'
KEY_EXTRA_FAILED: Final[str] = "tilauscope/backup/extra_failed"    # notice owed at next launch
KEY_RESTORED: Final[str] = "tilauscope/backup/restored"            # backup date, notice owed at next launch
KEY_RESTORE_FAILED: Final[str] = "tilauscope/backup/restore_failed"  # safety file, notice owed
KEEP_CHOICES: Final[tuple[int, ...]] = (3, 5, 10)

# Never in an archive and never cleared by a restore: they belong to this
# machine. Paired phones hold tokens; the backup preferences point at folders.
_MACHINE_KEYS: Final[tuple[str, ...]] = ("tilauscope/remote_devices",)
_MACHINE_PREFIXES: Final[tuple[str, ...]] = ("tilauscope/backup/",)


def app_version() -> tuple[str, int]:
    try:
        from artisanlib import __build__, __version__  # type: ignore[attr-defined]
        return str(__version__), int(str(__build__).strip("\"'"))
    except Exception:  # pylint: disable=broad-except
        return "0.0.0", 0


# ── where things are ────────────────────────────────────────────────────────

def data_directory() -> str:
    """Artisan's data folder (getDataDirectory), resolved the same way at backup and at start-up restore."""
    from artisanlib.util import getDataDirectory
    return getDataDirectory() or ""


def roots() -> dict[str, str]:
    settings = QSettings()
    return {core.ROAST: settings.value("alogDirectory", "", type=str),
            core.CAVE: settings.value("beancaveDirectory", "", type=str),
            core.DATA: data_directory(),
            core.APPDATA: QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)}


def default_folder() -> str:
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return str(Path(documents) / "TilauScope Backups")


def folder() -> str:
    return QSettings().value(KEY_FOLDER, "", type=str) or default_folder()


def keep_count() -> int:
    keep = QSettings().value(KEY_KEEP, 5, type=int)
    return keep if keep in KEEP_CHOICES else 5


def extra_reachable(path: str) -> bool:
    """A mounted share or a synced cloud folder answers like any folder; an unmounted one does not."""
    return bool(path) and os.path.isdir(path) and os.access(path, os.W_OK)


# ── the settings store ──────────────────────────────────────────────────────

def _own_store() -> QSettings:
    # A plain QSettings() also lists the fallback chain (NSGlobalDomain on macOS):
    # copying those keys would pin the system language and appearance.
    store = QSettings()
    return QSettings(store.fileName(), store.format())


def _machine_bound(key: str) -> bool:
    return key in _MACHINE_KEYS or key.startswith(_MACHINE_PREFIXES)


def encode(value: Any) -> dict[str, Any] | None:
    """A settings value as tagged JSON, so a bool comes back a bool. None: a type nobody stores."""
    if value is None:
        return {"t": "none"}
    for kind in (bool, int, float, str):
        if type(value) is kind:
            return {"t": kind.__name__, "v": value}
    if isinstance(value, (list, tuple)):
        items = [encode(v) for v in value]
        return None if None in items else {"t": "list", "v": items}
    if isinstance(value, dict):
        items = {str(k): encode(v) for k, v in value.items()}
        return None if None in items.values() else {"t": "dict", "v": items}
    if isinstance(value, QByteArray):
        return {"t": "bytes", "v": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, QDateTime):
        return {"t": "datetime", "v": value.toString(Qt.DateFormat.ISODateWithMs)}
    if isinstance(value, QDate):
        return {"t": "date", "v": value.toString(Qt.DateFormat.ISODate)}
    if isinstance(value, QTime):
        return {"t": "time", "v": value.toString(Qt.DateFormat.ISODateWithMs)}
    if isinstance(value, (QPoint, QPointF)):
        return {"t": type(value).__name__, "v": [value.x(), value.y()]}
    if isinstance(value, (QSize, QSizeF)):
        return {"t": type(value).__name__, "v": [value.width(), value.height()]}
    if isinstance(value, (QRect, QRectF)):
        return {"t": type(value).__name__, "v": [value.x(), value.y(), value.width(), value.height()]}
    if isinstance(value, QColor):
        return {"t": "color", "v": value.name(QColor.NameFormat.HexArgb)}
    return None


_GEOMETRY: Final[dict[str, type]] = {"QPoint": QPoint, "QPointF": QPointF, "QSize": QSize, "QSizeF": QSizeF,
                                     "QRect": QRect, "QRectF": QRectF}


def decode(tagged: dict[str, Any]) -> Any:
    kind, value = tagged["t"], tagged.get("v")
    if kind == "none":
        return None
    if kind in ("bool", "int", "float", "str"):
        return value
    if kind == "list":
        return [decode(v) for v in value]
    if kind == "dict":
        return {k: decode(v) for k, v in value.items()}
    if kind == "bytes":
        return QByteArray(base64.b64decode(value))
    if kind == "datetime":
        return QDateTime.fromString(value, Qt.DateFormat.ISODateWithMs)
    if kind == "date":
        return QDate.fromString(value, Qt.DateFormat.ISODate)
    if kind == "time":
        return QTime.fromString(value, Qt.DateFormat.ISODateWithMs)
    if kind in _GEOMETRY:
        return _GEOMETRY[kind](*value)
    if kind == "color":
        return QColor(value)
    raise ValueError(kind)


def dump_settings() -> dict[str, Any]:
    store = _own_store()
    out: dict[str, Any] = {}
    for key in store.allKeys():
        if _machine_bound(key):
            continue
        tagged = encode(store.value(key))
        if tagged is None:
            _log.warning("backup: setting %s has a type the backup does not carry", key)
            continue
        out[key] = tagged
    return out


def restore_settings(payload: dict[str, Any], moves: dict[str, str]) -> None:
    """Replace the store by ``payload``, folder paths moved to where the data now is."""
    store = _own_store()
    for key in store.allKeys():
        if not _machine_bound(key):
            store.remove(key)
    for key, tagged in payload.items():
        if _machine_bound(key):
            continue
        try:
            store.setValue(key, core.remap_paths(decode(tagged), moves))
        except (KeyError, TypeError, ValueError):
            _log.warning("backup: setting %s not restored", key)
    store.sync()


# ── running a backup off the GUI thread ─────────────────────────────────────

class BackupJob(QObject):
    """One backup, or one restore preparation, on a plain thread; results come back as queued signals.

    Parentless and kept alive by its thread: a dialog closed mid-run must not
    take the object its thread still emits on.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)   # the written Path, or the Manifest checked
    failed = pyqtSignal(str)        # BackupError kind, 'cancelled', or 'error'

    def __init__(self) -> None:
        super().__init__()
        self.cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, work) -> None:
        def run() -> None:
            try:
                self.finished.emit(work(self))
            except core.Cancelled:
                self.failed.emit("cancelled")
            except core.BackupError as e:
                self.failed.emit(e.kind)
            except Exception:  # pylint: disable=broad-except
                _log.exception("backup job failed")
                self.failed.emit("error")
        self._thread = threading.Thread(target=run, name="tilau-backup", daemon=True)
        self._thread.start()

    def report(self, done: int, total: int) -> None:
        self.progress.emit(done, total)

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join()


def backup_work(target: Path):
    """The job body for one backup to ``target``. Everything Qt-bound is read here, on the GUI thread."""
    settings, where = dump_settings(), roots()
    version, build = app_version()

    def work(job: BackupJob) -> Path:
        core.write_backup(target, where, settings, version=version, build=build,
                          progress=job.report, cancel=job.cancel)
        return target
    return work


def auto_backup_work():
    """The automatic run: local copy, pruned, then the extra copy when one is set."""
    local, extra, keep = Path(folder()), QSettings().value(KEY_EXTRA, "", type=str), keep_count()
    target = core.backup_name(core.AUTO_PREFIX, local)
    write = backup_work(target)

    def work(job: BackupJob) -> str:
        write(job)
        core.prune(local, core.AUTO_PREFIX, keep)
        if not extra:
            return "ok"
        try:
            if not extra_reachable(extra):
                raise OSError(extra)
            core.copy_to(target, Path(extra))
            core.prune(Path(extra), core.AUTO_PREFIX, keep)
        except OSError:
            _log.warning("backup: extra copy to %s failed", extra, exc_info=True)
            return "extra_failed"
        return "ok"
    return work


def record_auto_result(result: str) -> None:
    store = QSettings()
    store.setValue(KEY_LAST_AUTO, time.time())
    store.setValue(KEY_LAST_RESULT, result)
    store.setValue(KEY_EXTRA_FAILED, result == "extra_failed")
    store.sync()


def auto_backup_due() -> bool:
    """On, and a roast was saved since the last automatic backup."""
    settings = QSettings()
    if not settings.value(KEY_AUTO, False, type=bool):
        return False
    last = settings.value(KEY_LAST_AUTO, 0.0, type=float)
    return core.newest_roast_mtime(settings.value("alogDirectory", "", type=str)) > last


# ── restore across a restart ────────────────────────────────────────────────

def restore_work(archive: Path, manifest: core.Manifest, targets: dict[str, str]):
    """Check the archive, keep the current state in a safety backup, then leave the restore to the next start."""
    safety = core.backup_name(core.SAFETY_PREFIX, Path(folder()))
    write = backup_work(safety)
    data = Path(data_directory())

    def work(job: BackupJob) -> Path:
        core.verify(archive, manifest, cancel=job.cancel)
        write(job)
        core.write_pending(data, archive, targets, safety)
        return safety
    return work


def restore_pending() -> bool:
    return core.read_pending(Path(data_directory())) is not None


def apply_pending_restore() -> None:
    """Called once from main.py before anything reads settings or data files."""
    data = data_directory()
    if not data:
        return
    pending = core.read_pending(Path(data))
    if pending is None:
        return
    settings = QSettings()
    try:
        archive = Path(pending["archive"])
        version, build = app_version()
        manifest = core.read_manifest(archive, version=version, build=build)
        core.verify(archive, manifest)
        here = {core.DATA: data,
                core.APPDATA: QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)}
        targets = core.resolve_targets(manifest, {**pending["targets"], **here})
        core.restore_files(archive, manifest, targets)
        moves = {manifest.roots[key]["path"]: str(targets[key])
                 for key in core.OPERATOR_ROOTS if key in manifest.roots and key in targets}
        restore_settings(core.read_settings(archive), moves)
        settings.setValue(KEY_RESTORED, manifest.created)
    except Exception:  # pylint: disable=broad-except
        _log.exception("restore of %s failed", pending.get("archive"))
        settings.setValue(KEY_RESTORE_FAILED, pending.get("safety", ""))
    finally:
        (Path(data) / core.PENDING_RESTORE_NAME).unlink(missing_ok=True)
        settings.sync()


def relaunch_after_exit() -> bool:
    """Start a helper that reopens TilauScope once this process is gone.

    It waits for the exit: the single-instance guard turns away a start that
    overlaps the one quitting. Returns False when no way to relaunch is known.
    """
    pid = os.getpid()
    try:
        if getattr(sys, "frozen", False):
            command = [sys.executable]
            if platform.system() == "Darwin":
                bundle = Path(sys.executable).resolve().parents[2]
                command = ["open", str(bundle)] if bundle.suffix == ".app" else command
        else:
            command = [sys.executable, *sys.argv]
        if platform.system() == "Windows":
            args = ", ".join("'" + a.replace("'", "''") + "'" for a in command[1:])
            script = (f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; "
                      f"Start-Process -FilePath '{command[0]}'" + (f" -ArgumentList {args}" if args else ""))
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            import shlex
            script = f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done; exec {shlex.join(command)}"
            subprocess.Popen(["/bin/sh", "-c", script], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:  # pylint: disable=broad-except
        _log.exception("relaunch helper not started")
        return False

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

"""One-file backup of everything TilauScope keeps: roasts, BeanCave, learning, settings.

Qt-free. A backup is a zip holding ``manifest.json`` (what, when, from which
build, every file with its sha256), ``settings.json`` (the settings store,
already encoded by the caller) and each data folder under ``roots/<key>/``.
Restore is all or nothing: the cave and the learned files only make sense
with the roast list they were built from.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import platform
import shutil
import socket
import threading
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from tilaucore.archive import ArchiveError, member_path, sha256_file, sha256_stream, version_key

_log = logging.getLogger(__name__)

EXTENSION: Final[str] = ".tilaubackup"
FORMAT: Final[int] = 1
MANIFEST_NAME: Final[str] = "manifest.json"
SETTINGS_NAME: Final[str] = "settings.json"
PENDING_RESTORE_NAME: Final[str] = "pending_restore.json"

MANUAL_PREFIX: Final[str] = "TilauScope-"
AUTO_PREFIX: Final[str] = "TilauScope-auto-"
SAFETY_PREFIX: Final[str] = "TilauScope-before-restore-"

# Root keys. ROAST and CAVE are the operator's folders; DATA and APPDATA are the
# application's own (learning, PID calibration), always restored on this machine.
ROAST: Final[str] = "roasts"
CAVE: Final[str] = "beancave"
DATA: Final[str] = "data"
APPDATA: Final[str] = "appdata"
OPERATOR_ROOTS: Final[tuple[str, ...]] = (ROAST, CAVE)

# Never archived, never deleted by a restore: logs, rebuilt indexes and caches,
# machine-bound files (TLS key, Artisan's path→UUID cache, plus sync), runtime
# locks, and backups themselves.
EXCLUDED: Final[tuple[str, ...]] = (
    "*.log", "*.log.*", "*.tmp", "*_lock", "*-shm", "*-wal", ".DS_Store", "Thumbs.db",
    f"*{EXTENSION}", f"*{EXTENSION}.tmp", PENDING_RESTORE_NAME,
    "alog_index.json", "uuids.db", "sync", "tilau_snapshot_*.txt",
    "tilauscope-web.crt", "tilauscope-web.key",
)

Progress = Callable[[int, int], None]


BackupError = ArchiveError


class Cancelled(Exception):
    """The operator stopped the run; nothing was left behind."""


@dataclass
class Counts:
    roasts: int = 0
    coffees: int = 0
    tastings: int = 0
    size: int = 0


@dataclass
class Manifest:
    created: str
    version: str
    build: int
    system: str
    host: str
    roots: dict[str, dict[str, Any]]
    counts: Counts
    files: dict[str, dict[str, Any]] = field(default_factory=dict)


# ── what goes in ────────────────────────────────────────────────────────────

def is_excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED)


def plan_roots(roots: Mapping[str, str | os.PathLike | None]) -> dict[str, dict[str, Any]]:
    """Each root's path, and for a root inside another one, where it sits in it.

    On a default install the BeanCave lives in the roast folder: archiving it
    twice would double the size and restore two copies that could disagree.
    """
    resolved = {key: Path(path).expanduser().resolve() for key, path in roots.items()
                if path and Path(path).expanduser().is_dir()}
    plan: dict[str, dict[str, Any]] = {}
    for key, path in resolved.items():
        host = next((other for other, other_path in resolved.items()
                     if other != key and path != other_path and path.is_relative_to(other_path)), None)
        if host is None:
            # same folder under two keys: the first one listed owns it
            host = next((other for other in resolved if other != key and resolved[other] == path
                         and list(resolved).index(other) < list(resolved).index(key)), None)
        plan[key] = {"path": str(path),
                     "inside": None if host is None else [host, path.relative_to(resolved[host]).as_posix()]}
    return plan


def _walk(base: Path) -> list[Path]:
    """Every file under ``base`` an archive carries, excluded names pruned at any depth."""
    found: list[Path] = []
    for folder, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not is_excluded(d))
        found.extend(Path(folder) / name for name in sorted(files) if not is_excluded(name))
    return found


def collect(plan: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, Path]]:
    """(name in the archive, file on disk) for every hosting root."""
    entries: list[tuple[str, Path]] = []
    for key, info in plan.items():
        if info["inside"] is not None:
            continue
        base = Path(info["path"])
        entries.extend((f"roots/{key}/{p.relative_to(base).as_posix()}", p) for p in _walk(base))
    return entries


def _json_len(path: Path, *keys: str) -> int:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8-sig"))
        for key in keys:
            data = data[key]
        return len(data)
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def count(plan: Mapping[str, Mapping[str, Any]]) -> Counts:
    """What the operator recognises: roasts, coffees, tastings, and the bytes behind them."""
    counts = Counts()
    roast = plan.get(ROAST)
    if roast is not None:
        counts.roasts = sum(1 for p in _walk(Path(roast["path"])) if p.suffix == ".alog")
    cave = plan.get(CAVE) or roast
    if cave is not None:
        counts.coffees = _json_len(Path(cave["path"]) / "beancave.json", "green_beans")
        counts.tastings = _json_len(Path(cave["path"]) / "tastings.json", "entries")
    counts.size = sum(p.stat().st_size for _name, p in collect(plan))
    return counts


# ── writing ─────────────────────────────────────────────────────────────────

def backup_name(prefix: str, folder: Path, now: datetime | None = None) -> Path:
    """``<prefix><date>.tilaubackup``, the time added only when that name is taken."""
    now = now or datetime.now().astimezone()
    path = folder / f"{prefix}{now:%Y-%m-%d}{EXTENSION}"
    if prefix == MANUAL_PREFIX and not path.exists():
        return path
    return folder / f"{prefix}{now:%Y-%m-%d_%H%M%S}{EXTENSION}"


def write_backup(target: Path, roots: Mapping[str, str | os.PathLike | None], settings: Mapping[str, Any], *,
                 version: str, build: int, progress: Progress | None = None,
                 cancel: threading.Event | None = None) -> Manifest:
    """Write the backup to ``target``. Atomic: a stopped or failed run leaves no file."""
    plan = plan_roots(roots)
    entries = collect(plan)
    manifest = Manifest(created=datetime.now().astimezone().isoformat(timespec="seconds"),
                        version=version, build=int(build), system=platform.system(), host=socket.gethostname(),
                        roots=plan, counts=count(plan))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(SETTINGS_NAME, json.dumps(settings, ensure_ascii=False))
            for done, (name, path) in enumerate(entries):
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                manifest.files[name] = {"sha256": sha256_file(path), "size": path.stat().st_size}
                archive.write(path, name)
                if progress is not None:
                    progress(done + 1, len(entries))
            archive.writestr(MANIFEST_NAME, json.dumps(_manifest_dict(manifest), ensure_ascii=False, indent=1))
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def _manifest_dict(manifest: Manifest) -> dict[str, Any]:
    return {"format": FORMAT, "created": manifest.created, "version": manifest.version,
            "build": manifest.build, "system": manifest.system, "host": manifest.host,
            "roots": manifest.roots, "counts": vars(manifest.counts), "files": manifest.files}


# ── reading ─────────────────────────────────────────────────────────────────

def read_manifest(path: Path, *, version: str, build: int) -> Manifest:
    """The manifest, or BackupError: damaged, or written by a newer TilauScope."""
    try:
        with zipfile.ZipFile(path) as archive:
            raw = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            if SETTINGS_NAME not in archive.namelist():
                raise BackupError(BackupError.DAMAGED, "no settings")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise BackupError(BackupError.DAMAGED, str(e)) from e
    try:
        manifest = Manifest(created=raw["created"], version=raw["version"], build=int(raw["build"]),
                            system=raw["system"], host=raw["host"], roots=raw["roots"],
                            counts=Counts(**raw["counts"]), files=raw["files"])
        newer = raw["format"] > FORMAT or version_key(manifest.version, manifest.build) > version_key(version, build)
    except (KeyError, TypeError, ValueError) as e:
        raise BackupError(BackupError.DAMAGED, str(e)) from e
    if newer:
        raise BackupError(BackupError.NEWER, manifest.version)
    return manifest


def verify(path: Path, manifest: Manifest, progress: Progress | None = None,
           cancel: threading.Event | None = None) -> None:
    """Every listed file is there with the bytes it was written with."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for done, (name, info) in enumerate(manifest.files.items()):
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                if name not in names:
                    raise BackupError(BackupError.DAMAGED, f"missing {name}")
                with archive.open(name) as handle:
                    digest = sha256_stream(handle)
                if digest != info["sha256"]:
                    raise BackupError(BackupError.DAMAGED, f"checksum {name}")
                if progress is not None:
                    progress(done + 1, len(manifest.files))
    except (OSError, zipfile.BadZipFile) as e:
        raise BackupError(BackupError.DAMAGED, str(e)) from e


def read_settings(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(SETTINGS_NAME).decode("utf-8"))


# ── restoring ───────────────────────────────────────────────────────────────

def resolve_targets(manifest: Manifest, targets: Mapping[str, str | os.PathLike]) -> dict[str, Path]:
    """Where each archived root lands: hosting roots from ``targets``, nested ones inside their host."""
    out: dict[str, Path] = {}
    for key, info in manifest.roots.items():
        if info["inside"] is None and key in targets:
            out[key] = Path(targets[key]).expanduser()
    for key, info in manifest.roots.items():
        if info["inside"] is not None and info["inside"][0] in out:
            out[key] = out[info["inside"][0]] / info["inside"][1]
    return out


def safe_target(candidate: str | os.PathLike, known: tuple[str | os.PathLike | None, ...]) -> bool:
    """A restore may land on a folder it already owns, or on an empty one.

    Restoring replaces the folder's content: aimed at ~/Documents by mistake,
    it would delete everything there the backup does not hold.
    """
    path = Path(candidate).expanduser()
    if any(k and path.resolve() == Path(k).expanduser().resolve() for k in known):
        return True
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def restore_files(path: Path, manifest: Manifest, targets: Mapping[str, Path],
                  progress: Progress | None = None) -> None:
    """Replace each hosting root's content by the archive's.

    Everything in the archive is extracted beside the folder first; only then are
    the folder's own archivable files that the backup does not hold removed and
    the extracted ones moved in. Excluded files (logs, other backups) stay.
    """
    hosts = {key: targets[key] for key, info in manifest.roots.items()
             if info["inside"] is None and key in targets}
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.startswith("roots/")]
        staged: dict[str, Path] = {}
        try:
            for key, base in hosts.items():
                base.mkdir(parents=True, exist_ok=True)
                staged[key] = Path(f"{base.parent / ('.' + base.name)}.restore-tmp")
                shutil.rmtree(staged[key], ignore_errors=True)
            for done, name in enumerate(members):
                key, _, relative = name[len("roots/"):].partition("/")
                if key not in staged:
                    continue
                destination = member_path(staged[key], relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                if progress is not None:
                    progress(done + 1, len(members))
            for key, base in hosts.items():
                incoming = {p.relative_to(staged[key]) for p in _walk(staged[key])}
                for existing in _walk(base):
                    if existing.relative_to(base) not in incoming:
                        existing.unlink()
                for relative in incoming:
                    final = base / relative
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged[key] / relative, final)
        finally:
            for folder in staged.values():
                shutil.rmtree(folder, ignore_errors=True)


def remap_paths(value: Any, moves: Mapping[str, str]) -> Any:
    """A settings value with every path under an old root rewritten under its new one."""
    if isinstance(value, str):
        for old, new in moves.items():
            root = old.rstrip("/\\")
            if root and (value.rstrip("/\\") == root or value[len(root):len(root) + 1] in ("/", "\\")
                         and value.startswith(root)):
                return new.rstrip("/\\") + value[len(root):]
        return value
    if isinstance(value, list):
        return [remap_paths(item, moves) for item in value]
    if isinstance(value, dict):
        return {key: remap_paths(item, moves) for key, item in value.items()}
    return value


# ── housekeeping ────────────────────────────────────────────────────────────

def prune(folder: Path, prefix: str, keep: int) -> list[Path]:
    """Delete all but the ``keep`` newest ``prefix`` backups in ``folder``; returns what went."""
    try:
        found = sorted((p for p in folder.glob(f"{prefix}*{EXTENSION}") if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    gone = found[max(0, keep):]
    for path in gone:
        path.unlink(missing_ok=True)
    return gone


def newest_roast_mtime(roast_folder: str | os.PathLike | None) -> float:
    """When the most recent roast file changed, 0 without any."""
    if not roast_folder or not Path(roast_folder).is_dir():
        return 0.0
    return max((p.stat().st_mtime for p in _walk(Path(roast_folder)) if p.suffix == ".alog"), default=0.0)


def copy_to(source: Path, folder: Path) -> Path:
    """Copy a finished backup into another folder, atomically there too."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    partial = target.with_name(target.name + ".tmp")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def write_pending(folder: Path, archive: Path, targets: Mapping[str, str | os.PathLike], safety: Path) -> Path:
    """Ask the next start to restore ``archive``; ``safety`` holds the state it replaces."""
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / PENDING_RESTORE_NAME
    marker.write_text(json.dumps({"archive": str(archive), "safety": str(safety),
                                  "targets": {k: str(v) for k, v in targets.items()}}), encoding="utf-8")
    return marker


def read_pending(folder: Path) -> dict[str, Any] | None:
    marker = folder / PENDING_RESTORE_NAME
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

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

"""One coffee in one file: shared with another roaster, or moved to another of my computers. Qt-free.

A ``.tilaucoffee`` is a zip: ``manifest.json``, ``bean.json`` (the record),
``roasts/<roastUUID>.alog``, ``tastings.json`` and, when moving, ``brewlog.json``.
In *share* mode the record loses what is the sender's own business (stock,
bags, price) and every text goes through the caller's ``clean`` — the privacy
scrubber, which lives with Qt. Spec: wiki/CoffeeShare-Spec.md.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from tilaucore.archive import ArchiveError, member_path, version_key
from tilaucore.beans import BrewSample, GreenBean, RoastTasting, from_dict

EXTENSION: Final[str] = ".tilaucoffee"
FORMAT: Final[int] = 1
SHARE: Final[str] = "share"
MOVE: Final[str] = "move"

MANIFEST_NAME: Final[str] = "manifest.json"
BEAN_NAME: Final[str] = "bean.json"
TASTINGS_NAME: Final[str] = "tastings.json"
BREWLOG_NAME: Final[str] = "brewlog.json"
ROASTS_DIR: Final[str] = "roasts/"

#: The sender's own business, never shared: stock, bags, price, how it is kept,
#: and what the roast list adds up. The ★ too: on the other side a shared roast
#: guides only once its new owner adopts it.
SHARE_DROPPED_BEAN_FIELDS: Final[tuple[str, ...]] = (
    "weight_left", "sacks", "price_per_kg", "conditioning", "count", "weight", "reference_roast_uuid")

#: Emptied in a shared roast: who roasted it, and the room it was roasted in.
SHARE_EMPTIED_ALOG_KEYS: Final[dict[str, Any]] = {
    "operator": "", "organization": "", "ambientTemp": 0.0, "ambient_humidity": 0.0, "ambient_pressure": 0.0}

Clean = Callable[[str], str]


@dataclass
class Package:
    manifest: dict[str, Any]
    bean: GreenBean
    roasts: dict[str, dict[str, Any]]          # roastUUID → the roast file's dictionary
    tastings: dict[str, RoastTasting] = field(default_factory=dict)
    brews: list[BrewSample] = field(default_factory=list)

    @property
    def mode(self) -> str:
        return self.manifest["mode"]


# ── roast files ─────────────────────────────────────────────────────────────

def read_alog(path: Path) -> dict[str, Any]:
    """A roast file as Artisan reads it (artisanlib.util.deserialize)."""
    return ast.literal_eval(path.read_text(encoding="utf-8"))


def roast_uuid(roast: Mapping[str, Any]) -> str:
    return str(roast.get("roastUUID") or "")


def adopted(meta: Any) -> bool:
    """A shared roast the operator chose to learn from: it guides like one of theirs, no tasting asked."""
    return bool(getattr(meta, "shared", False)) and not getattr(meta, "exclude_learning", False)


def _clean_strings(value: Any, clean: Clean) -> Any:
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [_clean_strings(v, clean) for v in value]
    if isinstance(value, tuple):
        return tuple(_clean_strings(v, clean) for v in value)
    if isinstance(value, dict):
        return {_clean_strings(k, clean): _clean_strings(v, clean) for k, v in value.items()}
    return value


def scrub_alog(roast: Mapping[str, Any], clean: Clean) -> dict[str, Any]:
    """The roast as it may leave: who and where emptied, every text cleaned at any depth."""
    out = {key: _clean_strings(value, clean) for key, value in roast.items()}
    for key, empty in SHARE_EMPTIED_ALOG_KEYS.items():
        if key in out:
            out[key] = empty
    return out


# ── writing ─────────────────────────────────────────────────────────────────

def write_package(target: Path, *, mode: str, bean: GreenBean, roasts: Sequence[Path],
                  tastings: Mapping[str, RoastTasting], brews: Sequence[BrewSample] = (),
                  version: str, build: int, clean: Clean | None = None) -> dict[str, Any]:
    """Write the package; returns its manifest. ``clean`` is required in share mode."""
    if mode not in (SHARE, MOVE):
        raise ValueError(mode)
    if mode == SHARE and clean is None:
        raise ValueError("a shared coffee needs a cleaner")
    record = asdict(bean)
    if mode == SHARE:
        for name in SHARE_DROPPED_BEAN_FIELDS:
            record.pop(name, None)
        record = _clean_strings(record, clean)

    files: dict[str, bytes] = {}
    roaster = ""
    for path in roasts:
        roast = read_alog(path)
        uuid = roast_uuid(roast) or path.stem
        roaster = roaster or str(roast.get("roastertype") or "")
        if mode == SHARE:
            roast = scrub_alog(roast, clean)
        files[f"{ROASTS_DIR}{_safe(uuid)}.alog"] = repr(roast).encode("utf-8")
    carried = {uuid: asdict(t) for uuid, t in tastings.items()}
    if mode == SHARE:
        carried = _clean_strings(carried, clean)
    files[BEAN_NAME] = json.dumps(record).encode("utf-8")
    files[TASTINGS_NAME] = json.dumps(carried).encode("utf-8")
    if mode == MOVE:
        files[BREWLOG_NAME] = json.dumps([asdict(b) for b in brews]).encode("utf-8")

    if mode == SHARE:
        roaster = clean(roaster)
    manifest = {"format": FORMAT, "mode": mode, "created": datetime.now().astimezone().isoformat(timespec="seconds"),
                "version": version, "build": int(build), "coffee": record.get("name", ""), "roaster": roaster,
                "counts": {"roasts": len(roasts), "tastings": len(carried), "dial_ins": len(bean.dial_ins),
                           "brews": len(brews) if mode == MOVE else 0},
                "files": {name: _digest(data) for name, data in files.items()}}
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=1))
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_") or "roast"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── reading ─────────────────────────────────────────────────────────────────

def read_package(path: Path, *, version: str, build: int) -> Package:
    """The package, checked file by file; ArchiveError when damaged or written by a newer TilauScope."""
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            if manifest["format"] > FORMAT or version_key(manifest["version"], manifest["build"]) > version_key(version, build):
                raise ArchiveError(ArchiveError.NEWER, str(manifest["version"]))
            if manifest["mode"] not in (SHARE, MOVE):
                raise ArchiveError(ArchiveError.DAMAGED, "mode")
            data: dict[str, bytes] = {}
            for name, sha in manifest["files"].items():
                member_path(Path("."), name)
                data[name] = archive.read(name)
                if _digest(data[name]) != sha:
                    raise ArchiveError(ArchiveError.DAMAGED, f"checksum {name}")
            bean = from_dict(GreenBean, json.loads(data[BEAN_NAME]))
            roasts = {}
            for name, raw in data.items():
                if name.startswith(ROASTS_DIR):
                    roast = ast.literal_eval(raw.decode("utf-8"))
                    weight = roast.get("weight", [0]) if isinstance(roast, dict) else None
                    if not isinstance(weight, (list, tuple)) or not all(isinstance(w, (int, float)) for w in weight[:2]):
                        raise ValueError(f"roast {name}")
                    roasts[roast_uuid(roast) or Path(name).stem] = roast
            tastings = {k: from_dict(RoastTasting, v) for k, v in json.loads(data[TASTINGS_NAME]).items()}
            brews = [from_dict(BrewSample, b) for b in json.loads(data.get(BREWLOG_NAME, b"[]"))]
    except ArchiveError:
        raise
    except Exception as e:  # noqa: BLE001 — a file from elsewhere: whatever fails in it, it is damaged
        raise ArchiveError(ArchiveError.DAMAGED, str(e)) from e
    return Package(manifest=manifest, bean=bean, roasts=roasts, tastings=tastings, brews=brews)

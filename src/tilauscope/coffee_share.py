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

"""Sharing one coffee on this machine: the cleaner a shared package goes through. Format: tilaucore.coffee_share."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tilaucore import coffee_share as core
from tilaucore.alog_index import AlogMetadata
from tilaucore.beans import BrewSample, GreenBean, RoastTasting
from tilaucore.coffee_share import Clean
from tilauscope.tilau_privacy import Profile, runtime_sensitive_values, sanitize_text


def shared_cleaner(keep: Iterable[str], sensitive: Iterable[str] | None = None) -> Clean:
    """Clean a text of a shared coffee: the log-export rules, plus notes typed by hand.

    ``keep`` are the coffee's and its roasts' identifiers, without which the
    package attaches to nothing on the other side. ``sensitive`` defaults to
    this machine's identity: home folder name, computer name, operator.
    """
    ids = tuple(sorted({i for i in keep if i}, key=len, reverse=True))
    values = tuple(sensitive) if sensitive is not None else runtime_sensitive_values()
    return lambda text: sanitize_text(text, values, profile=Profile.SHARED_ROAST, keep=ids)


def _same_roast(a: str, b: str) -> bool:
    return bool(a) and a.replace("-", "").lower() == b.replace("-", "").lower()


@dataclass
class ShareSource:
    """One coffee as this BeanCave holds it, gathered once when the window opens."""

    bean: GreenBean
    roasts: list[AlogMetadata]                    # this coffee's own roasts, newest first
    reference: AlogMetadata | None
    tastings: dict[str, RoastTasting] = field(default_factory=dict)
    brews: list[BrewSample] = field(default_factory=list)

    def roasts_for(self, mode: str) -> list[AlogMetadata]:
        if mode == core.MOVE:
            return self.roasts
        return [self.reference] if self.reference is not None else []

    def tastings_for(self, mode: str) -> dict[str, RoastTasting]:
        carried = self.roasts_for(mode)
        return {key: t for key, t in self.tastings.items()
                if any(_same_roast(key, r.roast_uuid) for r in carried)}


def gather(bean: GreenBean, records: Iterable[AlogMetadata], cave_directory: str | Path) -> ShareSource:
    from tilauscope import brew_log, tasting_log  # noqa: PLC0415
    uuid = (bean.uuid or "").lower()
    roasts = sorted((r for r in records
                     if uuid and (r.uuid or "").lower() == uuid and not r.simulated and r.filepath_str),
                    key=lambda r: r.roastepoch or r.mtime, reverse=True)
    reference = next((r for r in roasts if _same_roast(r.roast_uuid, bean.reference_roast_uuid or "")), None)
    return ShareSource(bean=bean, roasts=roasts, reference=reference,
                       tastings=dict(tasting_log.load(cave_directory).entries),
                       brews=list(brew_log.load(cave_directory).entries.get(bean.uuid, [])))


def save(target: Path, mode: str, source: ShareSource) -> dict[str, Any]:
    """Write the package for ``mode``; the shared one goes through this machine's cleaner."""
    from tilauscope.backup import app_version  # noqa: PLC0415
    roasts = [Path(r.filepath_str) for r in source.roasts_for(mode)]
    clean = None
    if mode == core.SHARE:
        # The roast file's own spelling of its id, dashed or not, is the one that must survive.
        ids = [source.bean.uuid, *(str(core.read_alog(p).get("roastUUID") or "") for p in roasts)]
        clean = shared_cleaner(ids)
    version, build = app_version()
    return core.write_package(target, mode=mode, bean=source.bean, roasts=roasts,
                              tastings=source.tastings_for(mode),
                              brews=source.brews if mode == core.MOVE else (),
                              version=version, build=build, clean=clean)


# ── import ──────────────────────────────────────────────────────────────────

@dataclass
class ImportPreview:
    """What an import would do, shown before it does it."""

    existing: GreenBean | None          # the same coffee already in this cave
    new_roasts: list[str]               # the package's roasts this machine does not hold yet
    other_machine: str                  # the shared roast's roaster when it is not this machine's, else ''


def _norm(roast_uuid: str) -> str:
    return roast_uuid.replace("-", "").lower()


def other_machine(roaster: str, this_roaster: str) -> str:
    """The roast's machine when it is known not to be this one, by its current name; else ''."""
    from tilaucore.roasters import canonical_roaster_name, roaster_identity_key  # noqa: PLC0415
    if roaster and this_roaster and roaster_identity_key(roaster) != roaster_identity_key(this_roaster):
        return canonical_roaster_name(roaster)
    return ""


def preview(package: core.Package, beans: Iterable[GreenBean], records: Iterable[AlogMetadata],
            this_roaster: str) -> ImportPreview:
    held = {_norm(r.roast_uuid) for r in records if r.roast_uuid}
    roaster = str(package.manifest.get("roaster", ""))
    return ImportPreview(
        existing=next((b for b in beans if b.uuid and b.uuid.lower() == package.bean.uuid.lower()), None),
        new_roasts=[u for u in package.roasts if _norm(u) not in held],
        other_machine=other_machine(roaster, this_roaster) if package.mode == core.SHARE else "")


def learn_from(path: Path, on: bool) -> None:
    """Let the plan learn from a shared roast, or stop; its shared origin stays written."""
    from tilauscope.alog_repair import (LEARNING_ADMITTED, LEARNING_EXCLUDED, apply_learning_state,  # noqa: PLC0415
                                        parse_alog, write_alog)
    data = parse_alog(path)
    if data is None or not data.get("tilau_shared"):
        raise OSError(f"{path.name} is not a shared roast that can be read")
    write_alog(apply_learning_state(data, LEARNING_ADMITTED if on else LEARNING_EXCLUDED), path)


def _roast_file(folder: Path, coffee: str, roast: dict[str, Any], uuid: str, shared: bool) -> Path:
    name = "".join(c if c.isalnum() or c in " -_" else "_" for c in coffee).strip() or "coffee"
    day = str(roast.get("roastisodate") or "")[:10]
    stem = f"{name}{' - shared' if shared else ''}{' ' + day if day else ''} {_norm(uuid)[:8]}"
    return folder / f"{stem}.alog"


def apply_import(package: core.Package, *, beans: list[GreenBean], preview: ImportPreview,
                 alog_directory: str | Path, cave_directory: str | Path, replace_record: bool = False) -> bool:
    """Bring the package in; True when ``beans`` changed and must be saved.

    Nothing already here is deleted or overwritten: a roast this machine holds
    is skipped, a tasting it holds is kept. A shared coffee leaves an existing
    record alone; a moved one replaces it only when asked.
    """
    from tilaucore import tasting_log  # noqa: PLC0415
    from tilauscope import brew_log  # noqa: PLC0415
    shared = package.mode == core.SHARE
    changed = False
    if preview.existing is None:
        beans.append(package.bean)
        changed = True
    elif not shared and replace_record:
        beans[beans.index(preview.existing)] = package.bean
        changed = True

    folder = Path(alog_directory)
    for uuid in preview.new_roasts:
        roast = dict(package.roasts[uuid])
        if shared:
            roast["tilau_shared"] = {"shared_on": package.manifest.get("created", ""),
                                     "roaster": str(roast.get("roastertype") or "")}
            roast["tilau_exclude_learning"] = True
        target = _roast_file(folder, package.bean.name, roast, uuid, shared)
        if not target.exists():
            target.write_text(repr(roast), encoding="utf-8")

    held = tasting_log.load(cave_directory).entries
    for uuid, tasting in package.tastings.items():
        if not any(_norm(k) == _norm(uuid) for k in held):
            tasting_log.record(cave_directory, uuid, tasting)

    if not shared and package.brews:
        here = brew_log.load(cave_directory).entries.get(package.bean.uuid, [])
        for sample in package.brews:
            if sample not in here:
                brew_log.record(cave_directory, package.bean.uuid, sample)
    return changed

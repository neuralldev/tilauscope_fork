# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""One coffee in one file, on the tablet: open a .tilaucoffee, browse the community library, send a coffee to the computer.

The format and its checks are the shared core's (tilaucore.coffee_share, tilaucore.coffee_library); the import follows
the desktop's apply_import: nothing already here is replaced or deleted. Spec: wiki/CoffeeLibrary-Spec.md §6.
"""

import ast
from pathlib import Path
import shutil
import tempfile

from tilaucore import coffee_share as core, tasting_log
from tilaucore.archive import ArchiveError
from tilaucore.coffee_library import LIBRARY_URL, Library, LibraryError, card_from, card_to_json
from tilaucore.roasters import canonical_roaster_name, roaster_identity_key

from .roasts import profile_detail

# The tablet's own version is on another track (0.1.0): a package is compared with the TilauScope version whose
# files this tablet reads and writes, the one its .alog say (alog.profile "version"). Read: every build of it.
# Written: build 0, so that no desktop of that version finds it newer than itself.
VERSION = "4.3"
READS_BUILD = 99999
WRITES_BUILD = 0
NAME_CHARS = 60 # a coffee's name in a file name: the file system's limit is 255 bytes
# Where the roasts of a package go: another roaster's, or the user's own from another computer (a moved coffee)
ORIGIN = {core.SHARE: "shared", core.MOVE: "computer"}
ROASTS_KEPT = 32 # the library roasts read this session: a package each, read again past that


def _norm(roast_uuid: str) -> str:
    return roast_uuid.replace("-", "").lower()


def _same_machine(roaster: str, machine: str) -> bool:
    return bool(machine and roaster) and roaster_identity_key(roaster) == roaster_identity_key(machine)


def _view(card, machine: str) -> dict:
    """A card as the pages read it: the file's §2 object, the relay's id and day, its machine by its current name, and
    whether that is this tablet's machine or known to be another one (the desktop's other_machine)."""
    same = _same_machine(card.roaster, machine)
    return {**card_to_json(card), "id": card.id, "published": card.published, "same_machine": same,
            "roaster_name": canonical_roaster_name(card.roaster) if card.roaster else "",
            "other_machine": bool(card.roaster and machine) and not same}


def _card_view(bean, roast: dict, machine: str, card=None) -> dict | None:
    """What the sheets draw of a roast: the library card (the package's own, else built from the roast), or None."""
    try:
        card = card or card_from(bean, roast, None)
    except ValueError: # CHARGE or DROP unmarked: nothing to draw
        return None
    return _view(card, machine)


def _read(path: str) -> core.Package:
    """The package, or ArchiveError (damaged, newer); a coffee without an id cannot be linked to its roasts."""
    package = core.read_package(Path(path), version=VERSION, build=READS_BUILD)
    if not package.bean.uuid:
        raise ArchiveError(ArchiveError.DAMAGED, "no id")
    return package


def preview(path: str, roasts, owner: str, machine: str, beans: list) -> dict:
    """What opening this file would do, without doing it; `state` says when it cannot be read."""
    try:
        package = _read(path)
    except ArchiveError as error:
        return {"state": error.kind}
    bean, held = package.bean, roasts.held()
    first = next(iter(package.roasts.values()), None)
    return {"state": "ok", "mode": package.mode, "owner": owner, "name": bean.name, "country": bean.country,
            "process": bean.process, "crop": bean.crop, "flavours": [f.strip() for f in bean.flavour_notes.split(",") if f.strip()][:8],
            "card": _card_view(bean, first, machine, package.card) if first is not None else None,
            "existing": any(b.uuid.lower() == bean.uuid.lower() for b in beans),
            "roasts": len(package.roasts), "new_roasts": sum(_norm(u) not in held for u in package.roasts),
            "tastings": len(package.tastings), "settings": len(bean.dial_ins)}


def apply(path: str, cave, roasts) -> dict:
    """Brings the package in: the coffee when the cave lacks it, each roast the tablet lacks, the tastings it lacks."""
    package = _read(path)
    shared = package.mode == core.SHARE
    bean = package.bean
    added = cave.add_bean(bean)
    held, written = roasts.held(), 0
    for uuid, roast in package.roasts.items():
        if _norm(uuid) in held:
            continue
        roast = dict(roast)
        if shared: # the sender's alarms and programs never run here, whatever the package says
            roast = core.disarm(roast)
            roast["tilau_shared"] = {"shared_on": package.manifest.get("created", ""), "roaster": str(roast.get("roastertype") or "")}
            roast["tilau_exclude_learning"] = True
        name = core.roast_file_name(bean.name[:NAME_CHARS], roast, uuid, shared)
        written += roasts.store(ORIGIN[package.mode], name, roast)
        held.add(_norm(uuid))
    kept = {_norm(k) for k in tasting_log.load(cave.directory).entries}
    for uuid, tasting in package.tastings.items():
        if _norm(uuid) not in kept:
            tasting_log.record(str(cave.directory), uuid, tasting)
    if package.brews:
        cave.add_brews(bean.uuid, package.brews)
    return {"uuid": bean.uuid, "name": bean.name, "added": added, "roasts": written}


def theirs(uuid: str, cave, roasts, machine: str) -> dict:
    """The shared roast a coffee came with (the newest): its card and day, for the coffee's sheet; no card when it has none."""
    bean = next((b for b in cave.beans() if b.uuid.lower() == uuid.lower()), None)
    found = [m for o, m in roasts.records() if o == "shared" and m.shared and (m.uuid or "").lower() == uuid.lower()]
    if bean is None or not found:
        return {"uuid": uuid, "card": None, "shared_on": ""}
    meta = max(found, key=lambda m: m.roastepoch or m.mtime)
    profile = ast.literal_eval(roasts.path("shared", meta.filename).read_text(encoding="utf-8"))
    return {"uuid": uuid, "card": _card_view(bean, profile, machine), "shared_on": str((profile.get("tilau_shared") or {}).get("shared_on") or "")[:10]}


def pack(uuid: str, cave, roasts, directory: str) -> str:
    """A Move package of a coffee into `directory`: the roasts of it the tablet holds (its own, and the shared
    reference it was roasted from), their tastings and the coffee's brew settings. Returns the file's path."""
    bean = next((b for b in cave.beans() if b.uuid and b.uuid == uuid), None)
    if bean is None:
        raise ValueError("No such coffee in the BeanCave")
    carried = sorted(((o, m) for o, m in roasts.records() if o != "computer" and (m.uuid or "").lower() == uuid.lower() and not m.simulated),
                     key=lambda r: r[1].roastepoch or r[1].mtime, reverse=True) # the computer's roasts are already there
    keys = {_norm(m.roast_uuid) for _, m in carried}
    tastings = {k: t for k, t in tasting_log.load(cave.directory).entries.items() if _norm(k) in keys}
    folder = Path(directory)
    shutil.rmtree(folder, ignore_errors=True) # one package at a time: the last one sent
    stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in bean.name[:NAME_CHARS]).strip() or "coffee"
    target = folder / f"{stem}{core.EXTENSION}"
    core.write_package(target, mode=core.MOVE, bean=bean, roasts=[roasts.path(o, m.filename) for o, m in carried],
                       tastings=tastings, brews=cave.brews(bean.uuid), version=VERSION, build=WRITES_BUILD)
    return str(target)


class Browser:
    """The community library as the tablet browses it. `fetch` and `url` are the core's own injection points."""

    def __init__(self, url: str = LIBRARY_URL, fetch=None) -> None:
        self._library = Library(url, fetch)
        self._roasts: dict[str, dict] = {} # a card's published roast by coffee id, read once this session

    def page(self, text: str, my_machine: bool, machine: str, cursor: str = "") -> dict:
        """Slow (the network): one page of the relay's search, newest roast day first. `text` and the machine are
        searched by the relay, nothing is filtered here; with `my_machine`, only the roasts of this tablet's machine
        (none set: every machine). {cards, next, total, machine}, `next` empty on the last page; else {error}."""
        try:
            found = self._library.search(text=text, roaster=machine if my_machine else "", cursor=cursor)
        except LibraryError as error:
            return {"error": error.kind}
        return {"machine": machine, "total": found.total, "next": found.next, "cards": [_view(c, machine) for c in found.cards]}

    def roast(self, coffee_id: str, directory: str, unit: str) -> dict:
        """Slow. The roast a card was published with, as the Roasts tab draws a roast of this tablet: {id, detail};
        else {id, error}, a library kind or 'local' (this tablet could not read it). The package is downloaded into a
        folder of its own under `directory`, gone once read whatever happened; the roast is kept for the session."""
        profile = self._roasts.get(coffee_id)
        if profile is None:
            folder = None
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
                folder = tempfile.mkdtemp(prefix="card-", dir=directory)
                package = core.read_package(self._library.download(coffee_id, Path(folder)), version=VERSION, build=READS_BUILD)
                profile = next(iter(package.roasts.values())) # a published coffee holds the one roast it was published with
            except LibraryError as error:
                return {"id": coffee_id, "error": error.kind}
            except Exception: # noqa: BLE001 — damaged, newer, without a roast, or the cache cannot be written
                return {"id": coffee_id, "error": "local"}
            finally:
                if folder:
                    shutil.rmtree(folder, ignore_errors=True)
            while len(self._roasts) >= ROASTS_KEPT:
                del self._roasts[next(iter(self._roasts))]
            self._roasts[coffee_id] = profile
        try:
            detail = profile_detail(profile, unit)
        except Exception: # noqa: BLE001 — a roast from elsewhere
            return {"id": coffee_id, "error": "local"}
        # Their energy was measured on their machine, and its sheet reads a roast of this tablet: not shown
        detail["tiles"] = [t for t in detail["tiles"] if t["caption"] != "Energy"]
        return {"id": coffee_id, "detail": detail}

    def download(self, coffee_id: str, directory: str) -> dict:
        """Slow. The package into `directory` (emptied first: one download at a time), or the library's error."""
        shutil.rmtree(directory, ignore_errors=True)
        try:
            return {"path": str(self._library.download(coffee_id, Path(directory)))}
        except LibraryError as error:
            return {"error": error.kind}

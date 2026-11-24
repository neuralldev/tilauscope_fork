# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""One coffee in one file, on the tablet: open a .tilaucoffee, browse the community library, send a coffee to the computer.

The format and its checks are the shared core's (tilaucore.coffee_share, tilaucore.coffee_library); the import follows
the desktop's apply_import: nothing already here is replaced or deleted. Spec: wiki/CoffeeLibrary-Spec.md §6.
"""

import ast
import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from tilaucore import coffee_share as core, ed25519, tasting_log
from tilaucore.archive import ArchiveError
from tilaucore.coffee_library import LIBRARY_URL, MAX_IDS, CardError, Library, LibraryError, card_from, card_to_json
from tilaucore.privacy import Profile, sanitize_text
from tilaucore.roasters import canonical_roaster_name, roaster_identity_key

from .alog import TILAUSCOPE_VERSION
from .files import write_text_atomic
from .roasts import profile_detail

# The tablet's own version is on another track (0.1.0): a package is compared with the TilauScope version whose
# files this tablet reads and writes, the one its .alog say (alog.profile "version"). Read: every build of it.
# Written: build 0, so that no desktop of that version finds it newer than itself.
VERSION = TILAUSCOPE_VERSION
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


def _view(card, machine: str, mine: frozenset = frozenset()) -> dict:
    """A card as the pages read it: the file's §2 object, the relay's id and day, its machine by its current name,
    whether that is this tablet's machine or known to be another one (the desktop's other_machine), and whether this
    tablet published it (`mine`: the ids it did)."""
    same = _same_machine(card.roaster, machine)
    return {**card_to_json(card), "id": card.id, "published": card.published, "same_machine": same,
            "roaster_name": canonical_roaster_name(card.roaster) if card.roaster else "",
            "other_machine": bool(card.roaster and machine) and not same, "mine": card.id in mine}


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


SHARE_KEPT_S = 3600.0 # a package sent stays this long: the app it went to may read it later (a draft, an upload)


def _share_folder(directory: Path) -> Path:
    """A folder of its own for a new package; the packages sent over an hour ago go (Tilau, 2026-11-21)."""
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in directory.iterdir():
        try:
            if now - old.stat().st_mtime > SHARE_KEPT_S:
                shutil.rmtree(old) if old.is_dir() else old.unlink()
        except OSError:
            pass
    folder = directory / str(time.time_ns())
    folder.mkdir()
    return folder


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
    folder = _share_folder(Path(directory))
    stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in bean.name[:NAME_CHARS]).strip() or "coffee"
    target = folder / f"{stem}{core.EXTENSION}"
    core.write_package(target, mode=core.MOVE, bean=bean, roasts=[roasts.path(o, m.filename) for o, m in carried],
                       tastings=tastings, brews=cave.brews(bean.uuid), version=VERSION, build=WRITES_BUILD)
    return str(target)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii") # the relay's encoding (spec §3.2)


class Author:
    """This tablet as an author of the library: its Ed25519 key and the coffees it published, in one file of the app
    (no system keychain without a library, as the MQTT password). A key per device: what a tablet published, only it
    withdraws (Tilau, 2026-11-24). The key is made at the first publication, never over a file that cannot be read:
    that would lose the key the relay knows, and with it every withdrawal."""

    def __init__(self, path) -> None:
        self.path = Path(path) if path else None
        self._unsaved: list[str] = [] # published, but the file could not take it: kept for this run

    def _read(self) -> dict | None:
        """The file's data; {} when there is none yet; None when it is there but cannot be read."""
        if self.path is None or not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def published(self) -> list[str]:
        data = self._read() or {}
        saved = [str(i) for i in data.get("published") or [] if isinstance(i, str)]
        return saved + [i for i in self._unsaved if i not in saved]

    def sign(self, text: bytes) -> tuple[str, str]:
        """The library core's Sign: (public key, signature), base64url without padding. OSError when the file
        cannot be read or written: nothing is signed then."""
        data = self._read()
        if data is None:
            raise OSError("The library key cannot be read")
        try:
            seed = base64.b64decode(data["key"], validate=True)
        except KeyError:
            seed = b""
        except (TypeError, ValueError) as error:
            raise OSError("The library key is damaged") from error
        if not seed:
            if self.path is None:
                raise OSError("No file keeps a library key here")
            seed = os.urandom(32)
            write_text_atomic(self.path, json.dumps({**data, "key": base64.b64encode(seed).decode("ascii")})) # kept before it signs
        if len(seed) != 32:
            raise OSError("The library key is damaged")
        return _b64(ed25519.public_key(seed)), _b64(ed25519.sign(seed, text))

    def note(self, coffee_id: str, mine: bool) -> None:
        """Records a publication or a withdrawal; when the file cannot take it, kept for this run (never lost silently:
        a coffee published and not recorded could not be withdrawn)."""
        data = self._read()
        if mine and coffee_id not in self._unsaved:
            self._unsaved.append(coffee_id)
        if not mine:
            self._unsaved = [i for i in self._unsaved if i != coffee_id]
        if data is None or self.path is None:
            return
        saved = [str(i) for i in data.get("published") or [] if isinstance(i, str) and i != coffee_id]
        try:
            write_text_atomic(self.path, json.dumps({**data, "published": saved + ([coffee_id] if mine else [])}))
        except OSError:
            return
        if mine:
            self._unsaved = [i for i in self._unsaved if i != coffee_id]


def publishable(origin: str, name: str, cave, roasts):
    """(bean, roast, tasting, card) of a roast the tablet may publish, or the reason it may not: 'computer' (recorded on
    the computer, published from there: Tilau, 2026-11-24), 'shared' (another roaster's), 'unreadable' (the file is
    gone or damaged), 'no_coffee' (a simulation, or no coffee of the BeanCave), or a CardError reason (spec §2)."""
    if origin == "shared":
        return "shared"
    if origin != "tablet":
        return "computer"
    meta = next((m for o, m in roasts.records() if o == origin and m.filename == name), None)
    if meta is None:
        return "unreadable"
    try:
        roast = core.read_alog(roasts.path(origin, name))
    except (OSError, ValueError, SyntaxError):
        return "unreadable"
    if roast.get("tilau_shared"):
        return "shared"
    bean = next((b for b in cave.beans() if meta.uuid and b.uuid.lower() == meta.uuid.lower()), None) if cave else None
    if meta.simulated or bean is None:
        return "no_coffee"
    key = _norm(str(roast.get("roastUUID") or ""))
    tasting = next((t for k, t in tasting_log.load(cave.directory).entries.items() if _norm(k) == key), None) if key else None
    try:
        card = card_from(bean, roast, tasting)
    except CardError as error:
        return error.reason
    return bean, roast, tasting, card


def package(origin: str, name: str, cave, roasts, sensitive: list[str], directory: str) -> dict:
    """The package that publishes a roast of this tablet with its coffee, cleaned as the desktop cleans a shared coffee:
    {bytes, name}, or {refused: reason} (publishable), or {error: 'too_large' or 'local'}. It reads the BeanCave and the
    roasts: the session's worker calls it, never the network's thread."""
    found = publishable(origin, name, cave, roasts)
    if isinstance(found, str):
        return {"refused": found}
    bean, roast, tasting, card = found
    uuid = str(roast.get("roastUUID") or "")
    keep = tuple(sorted({i for i in (bean.uuid, uuid) if i}, key=len, reverse=True)) # what links the package to itself
    names = [str(roast.get(k) or "") for k in ("operator", "organization")] # the roast's own, even renamed since
    values = tuple(sorted({v for v in (*sensitive, *names) if v and len(v) >= 3}, key=len, reverse=True))
    def clean(text: str) -> str:
        return sanitize_text(text, values, profile=Profile.SHARED_ROAST, keep=keep)
    folder = None
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
        folder = tempfile.mkdtemp(prefix="publish-", dir=directory)
        target = Path(folder) / f"coffee{core.EXTENSION}"
        core.write_package(target, mode=core.SHARE, bean=bean, roasts=[roasts.path(origin, name)],
                           tastings={uuid: tasting} if tasting and uuid else {}, version=VERSION, build=WRITES_BUILD,
                           clean=clean, card=card)
        return {"bytes": target.read_bytes(), "name": card.name}
    except ArchiveError as error:
        return {"error": "too_large" if error.kind == ArchiveError.TOO_LARGE else "local"}
    except Exception: # noqa: BLE001 — the package could not be written here
        return {"error": "local"}
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


class Browser:
    """The community library as the tablet browses and publishes to it. `fetch` and `url` are the core's own injection
    points; `author` is this tablet's key and publications (None: browsing only). Its calls run on the network's thread:
    they touch the relay and the author's file only."""

    def __init__(self, url: str = LIBRARY_URL, fetch=None, author: Author | None = None) -> None:
        self._library = Library(url, fetch)
        self._roasts: dict[str, dict] = {} # a card's published roast by coffee id, read once this session
        self.author = author or Author(None)

    def page(self, text: str, my_machine: bool, machine: str, cursor: str = "", own: bool = False) -> dict:
        """Slow (the network): one page of the relay's search, newest roast day first. `text` and the machine are
        searched by the relay, nothing is filtered here; with `my_machine`, only the roasts of this tablet's machine
        (none set: every machine); with `own`, only the coffees this tablet published, asked MAX_IDS ids at a time
        (the cursor then names the batch). {cards, next, total, machine, mine}, `next` empty on the last page, `total`
        None when a search spans several batches, `mine` the count of this tablet's publications; else {error}."""
        mine = self.author.published()
        roaster = machine if my_machine else ""
        try:
            if own:
                if not mine: # no id would filter nothing: none published, none shown
                    return {"machine": machine, "total": 0, "next": "", "cards": [], "mine": 0}
                # The cursor is "end:inner": this batch is the MAX_IDS ids before `end`, counted from the oldest, so a
                # withdrawal or a new publication while scrolling moves no batch still to come.
                index, _, inner = cursor.partition(":")
                end = min(int(index), len(mine)) if index.isdigit() else len(mine)
                start = max(0, end - MAX_IDS)
                found = self._library.search(text=text, roaster=roaster, ids=mine[start:end], cursor=inner)
                after = f"{end}:{found.next}" if found.next else f"{start}:" if start > 0 else ""
                filtered = bool(text.strip() or roaster)
                total = found.total if len(mine) <= MAX_IDS else None if filtered else len(mine) # None: not known here
            else:
                found = self._library.search(text=text, roaster=roaster, cursor=cursor)
                after, total = found.next, found.total
        except LibraryError as error:
            return {"error": error.kind}
        ids = frozenset(mine)
        return {"machine": machine, "total": total, "next": after, "mine": len(mine),
                "cards": [_view(c, machine, ids) for c in found.cards]}

    def send(self, data: bytes, name: str) -> dict:
        """Slow. Publishes a package `package` made: {id, name}, or {error}. The id is recorded for Mine and Withdraw."""
        try:
            coffee_id = self._library.publish(data, self.author.sign)
        except LibraryError as error:
            return {"error": error.kind}
        except OSError: # the key cannot be read or kept: nothing was sent
            return {"error": "local"}
        self.author.note(coffee_id, True)
        return {"id": coffee_id, "name": name}

    def withdraw(self, coffee_id: str) -> dict:
        """Slow. Takes a coffee this tablet published out of the library: {id}, or {error}."""
        if coffee_id not in self.author.published():
            return {"error": "not_mine"} # this tablet has no record of publishing it
        try:
            self._library.withdraw(coffee_id, self.author.sign)
        except LibraryError as error:
            if error.kind != "unknown": # already gone: it is no longer this tablet's either
                return {"error": error.kind}
        except OSError:
            return {"error": "local"}
        self.author.note(coffee_id, False)
        return {"id": coffee_id}

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

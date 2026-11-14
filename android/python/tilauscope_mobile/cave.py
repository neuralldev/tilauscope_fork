# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The green coffee cave: the desktop's own beancave.json, kept as it came.

The file is stored byte for byte as imported, so an export gives the desktop
back exactly its file, until a coffee is edited here: the file is then written
as the desktop writes it. An empty cave is written as the desktop writes an
empty BeanCaveContainer. A note beside the file says where it came from and when.

The cave moves as one set with the files that depend on it (tastings, brews),
from the desktop's BeanCave folder and back: never one without the others.
"""

import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from tilaucore import bean_edit, tasting_log
from tilaucore.data_files import BEANCAVE_LISTS_JSON

from tilaucore.bean_qualifiers import SCREEN_SIZE_OPTIONS, SCREEN_SIZE_RANGES, family_pace, physical_qualifier
from tilaucore.bean_text import beans_text, roast_title
from tilaucore.beans import BeanCaveContainer, BrewLog, GreenBean, TastingLog, from_dict, from_json, to_json

FILE = "beancave.json"
NOTE = "beancave.note.json"
EMPTY = to_json(BeanCaveContainer()) # the desktop's empty container
COMPANIONS = {tasting_log.TASTINGS_FILE_NAME: TastingLog, "brewlog.json": BrewLog} # beside beancave.json; absent until first used
FILES = (FILE, *COMPANIONS)


def parse(text: str) -> list[GreenBean]:
    """The coffees of a beancave.json text, read as the desktop reads them, or ValueError."""
    try:
        data = json.loads(text.lstrip("﻿")) # the desktop writes a BOM on Windows
        if not isinstance(data, dict) or "green_beans" not in data: # any other JSON is not a cave
            raise ValueError
        return from_dict(BeanCaveContainer, data).green_beans
    except ValueError:
        raise ValueError("not a BeanCave") from None


def read_folder(folder: str) -> dict[str, str]:
    """The BeanCave files of a folder, each checked as the desktop reads it, or ValueError saying which is not."""
    if not (Path(folder) / FILE).is_file():
        raise ValueError("No BeanCave in this folder")
    texts = {}
    for name in FILES:
        path = Path(folder) / name
        if path.is_file():
            try:
                texts[name] = path.read_bytes().decode("utf-8") # kept as they came, line ends too
                if name == FILE:
                    parse(texts[name])
                else:
                    from_json(COMPANIONS[name], texts[name].lstrip("\ufeff"))
            except ValueError: # not UTF-8, not JSON, or not that file's shape
                raise ValueError(f"{name} cannot be read") from None
    return texts


def summary(beans: list[GreenBean]) -> dict:
    stock = [bean.weight_left for bean in beans if bean.weight_left > 0]
    return {"coffees": len(beans), "in_stock": len(stock), "stock_g": round(sum(stock))}


def view(bean: GreenBean) -> dict:
    """A coffee as the BeanCave screen shows it, in the desktop's words."""
    def measure(kind: str, value: float) -> dict:
        word, level = physical_qualifier(kind, value)
        return {"value": value if value > 0 else None, "word": word[1] if word else "", "level": level}
    blend = None
    if bean.is_blend: # the record itself first; a ratio of 0 is unknown
        blend = [[bean.varieties or bean.name or "?", bean.bean1_ratio]]
        blend += [[n or "?", r] for n, r in ((bean.bean2_name, bean.bean2_ratio), (bean.bean3_name, bean.bean3_ratio)) if n or r > 0]
    family, words = family_pace(bean.varieties)
    return {
        "uuid": bean.uuid, "name": bean.name, "country": bean.country, "process": bean.process,
        "category": bean.category, "supplier": bean.supplier, "crop": bean.crop, "sca": bean.sca,
        "roasts": bean.count, "stock_g": bean.weight_left, "is_blend": bean.is_blend, "blend": blend,
        "flavours": [p.strip() for p in bean.flavour_notes.split(",") if p.strip()][:8],
        "memo": bean.tips.strip(), "species": bean.species,
        "varieties": "" if bean.is_blend else bean.varieties,
        "screen_size": dict(SCREEN_SIZE_OPTIONS).get(bean.screen_size, ("", ""))[1] if bean.screen_size else "",
        "density": measure("density", bean.density), "humidity": measure("humidity", bean.last_humidity),
        "aw": measure("aw", bean.water_activity),
        "family": f"{family} — {words[1]}" if family else words[1],
        "farm": bean.farm, "altitude": bean.altitude, "price_per_kg": bean.price_per_kg,
        "edit": {key: getattr(bean, key) for zone in bean_edit.ZONES.values() for key in zone},
    }


def lists() -> dict:
    """The closed lists of the editors, as the desktop loads them from the shared file."""
    data = json.loads(BEANCAVE_LISTS_JSON.read_text(encoding="utf-8"))
    return {"countries": data["country"], "categories": data["category"],
            "processes": {c: data[c] for c in data["category"]},
            "species": data["varieties"], "varieties": {s: data[s] for s in data["varieties"]},
            "screen_sizes": [[key, label[1]] for key, label in SCREEN_SIZE_OPTIONS]}


def chosen(bean: GreenBean) -> dict:
    """What a roast keeps of its coffee: the pill's name and stock, the title and beans text."""
    return {"uuid": bean.uuid, "name": bean.name, "stock_g": bean.weight_left,
            "title": roast_title(bean), "beans": beans_text(bean)}


def roast_setup(bean: GreenBean) -> dict:
    """What Roast Setup proposes for a coffee, as the desktop fills it from the record."""
    return {"title": roast_title(bean), "green": None, "decrease": True, "density": bean.density,
            "moisture": bean.last_humidity, "greens_temp": 0.0,
            "beansize": list(SCREEN_SIZE_RANGES.get(bean.screen_size or "", (0, 0)))}


class Cave:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)

    @property
    def path(self) -> Path:
        return self.directory / FILE

    def _note(self) -> dict:
        try:
            return json.loads((self.directory / NOTE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def state(self) -> dict:
        if not self.path.exists():
            return {"present": False}
        note = self._note()
        return {"present": True, **summary(parse(self.path.read_text(encoding="utf-8"))), "tastings": len(tasting_log.load(self.directory).entries),
                "source": note.get("source"), "since": note.get("since")}

    def beans(self) -> list[GreenBean]:
        return parse(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    @staticmethod
    def preview(folder: str) -> dict:
        """What a folder's BeanCave holds, before it replaces the tablet's; ValueError if it cannot."""
        texts = read_folder(folder)
        tasted = texts.get(tasting_log.TASTINGS_FILE_NAME)
        return {**summary(parse(texts[FILE])), "files": [name for name in FILES if name in texts],
                "tastings": len(from_json(TastingLog, tasted.lstrip("\ufeff")).entries) if tasted else 0}

    def replace_folder(self, folder: str, source: str) -> dict:
        """The tablet's cave and its files become the folder's, all checked first; a file the folder lacks goes."""
        texts = read_folder(folder)
        for name in COMPANIONS:
            if name in texts:
                self._write(name, texts[name])
            else:
                (self.directory / name).unlink(missing_ok=True) # it belonged to the cave being replaced
        return self.replace(texts[FILE], source)

    def replace(self, text: str, source: str) -> dict:
        """The tablet's cave becomes this file, unchanged."""
        parse(text)
        self._write(FILE, text)
        self._write(NOTE, json.dumps({"source": source, "since": time.time()}))
        return self.state()

    def start_empty(self) -> dict:
        if self.path.exists():
            raise ValueError("A BeanCave is already on the tablet")
        return self.replace(EMPTY, "")

    def save_bean(self, bean_uuid: str | None, zone: str, values: dict) -> str:
        """One zone of a coffee, or a new coffee (no uuid, every zone); returns its uuid."""
        container = from_dict(BeanCaveContainer, json.loads(self.path.read_text(encoding="utf-8").lstrip("\ufeff")))
        countries = lists()["countries"]
        if bean_uuid is None:
            if zone != "all" or bean_edit.missing_to_create(values):
                raise ValueError("A new coffee needs every required field")
            bean = GreenBean(uuid=str(uuid.uuid4()))
            bean_edit.apply(bean, "all", values, countries)
            container.green_beans.append(bean)
        else:
            bean = next((b for b in container.green_beans if b.uuid and b.uuid == bean_uuid), None)
            if bean is None or zone == "all":
                raise ValueError("No such coffee in the BeanCave")
            bean_edit.apply(bean, zone, values, countries)
        self._write(FILE, to_json(container))
        return bean.uuid

    def add_bean(self, bean: GreenBean) -> bool:
        """A coffee of a package, when the cave does not hold it (same uuid, case ignored); nothing is replaced."""
        if not self.path.exists():
            self.replace(EMPTY, "")
        container = from_dict(BeanCaveContainer, json.loads(self.path.read_text(encoding="utf-8").lstrip("\ufeff")))
        if any(b.uuid.lower() == bean.uuid.lower() for b in container.green_beans):
            return False
        container.green_beans.append(bean)
        self._write(FILE, to_json(container))
        return True

    def brews(self, bean_uuid: str) -> list:
        """The brew settings kept for a coffee in brewlog.json."""
        path = self.directory / "brewlog.json"
        return from_json(BrewLog, path.read_text(encoding="utf-8").lstrip("\ufeff")).entries.get(bean_uuid, []) if path.is_file() else []

    def add_brews(self, bean_uuid: str, samples: list) -> None:
        """The samples of a package this cave lacks, appended to the coffee's brew settings."""
        path = self.directory / "brewlog.json"
        log = from_json(BrewLog, path.read_text(encoding="utf-8").lstrip("\ufeff")) if path.is_file() else BrewLog()
        here = log.entries.setdefault(bean_uuid, [])
        fresh = [s for s in samples if s not in here]
        if fresh:
            here.extend(fresh)
            self._write("brewlog.json", to_json(log))

    def decrease(self, bean_uuid: str, grams: float) -> float:
        """Takes a roast's green weight off a coffee's stock, floored at 0, as Roast Setup does; returns the stock left."""
        container = from_dict(BeanCaveContainer, json.loads(self.path.read_text(encoding="utf-8").lstrip("\ufeff")))
        bean = next((b for b in container.green_beans if b.uuid and b.uuid == bean_uuid), None)
        if bean is None:
            raise ValueError("No such coffee in the BeanCave")
        bean.weight_left = max(0.0, float(bean.weight_left or 0.0) - grams)
        self._write(FILE, to_json(container))
        return bean.weight_left

    def set_reference(self, bean_uuid: str, roast_uuid: str, on: bool) -> bool:
        """Mark or clear a roast as its coffee's reference, as the desktop; True once saved."""
        container = from_dict(BeanCaveContainer, json.loads(self.path.read_text(encoding="utf-8").lstrip("\ufeff")))
        bean = next((b for b in container.green_beans if b.uuid and b.uuid == bean_uuid), None)
        if bean is None:
            raise ValueError("No such coffee in the BeanCave")
        current, target = bean.reference_roast_uuid or "", roast_uuid if on else ""
        if target == current or (not on and current != roast_uuid):
            return False
        bean.reference_roast_uuid = target
        self._write(FILE, to_json(container))
        return True

    def _write(self, name: str, text: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".cave-", delete=False, newline="") as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

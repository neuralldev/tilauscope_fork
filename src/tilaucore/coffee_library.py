# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""The coffee library: the card a published coffee carries, the list's search keys, and the relay's HTTP client.

Qt-free and standard library only: the Android tablet loads this module through
Chaquopy, where ``requests`` and ``cryptography`` are not available. The key
pair lives with the caller; ``Library`` only receives a ``sign`` callable.
Spec: wiki/CoffeeLibrary-Spec.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from tilaucore.alog_index import _to_grams
from tilaucore.beans import GreenBean, RoastTasting
from tilaucore.roasters import LEGACY_ROASTER_NAMES
from tilaucore.units import c_from_f

MAX_PACKAGE_BYTES: Final[int] = 512 << 10

#: The relay's address, without a trailing slash or a route; empty means the library is unreachable.
LIBRARY_URL: Final[str] = "https://tilau-library.tilauscope.workers.dev"

CARD_VERSION: Final[int] = 1
MAX_TEXT: Final[int] = 80
MAX_FLAVOURS: Final[int] = 8
MAX_POINTS: Final[int] = 48
VERDICTS: Final[tuple[str, ...]] = ("yes", "almost", "no", "")
_TIMEOUT_S: Final[int] = 15
_ID = re.compile(r"[0-9a-f]{32}")
#: Roasts per page of the list; the relay serves at most 20.
PAGE_SIZE: Final[int] = 10
#: The ids the relay takes in one request (the "Mine" view).
MAX_IDS: Final[int] = 50

#: (seconds since CHARGE, °C)
Point = tuple[int, float]


@dataclass(frozen=True)
class Card:
    """What the library list shows of a coffee; ``id`` and ``published`` are the relay's, '' before publication."""
    name: str
    country: str
    process: str
    crop: int
    roaster: str
    batch_g: int
    total_s: int
    after_fc_s: int
    drop_c: int
    flavours: tuple[str, ...]
    verdict: str
    curve: tuple[Point, ...]
    roasted: str = ""      # the roast's day, YYYY-MM-DD; '' on a card written before it was carried
    id: str = ""
    published: str = ""


@dataclass(frozen=True)
class Page:
    """One page of the list; ``next`` is the cursor of the page after it, '' after the last one."""
    cards: tuple[Card, ...]
    next: str
    total: int        # the roasts matching the filters, on every page


class LibraryError(Exception):
    """``kind``: offline, refused, rate, too_large or unknown. The application words each one; never the raw code."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


# ── the card ────────────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT]


def card_from(bean: GreenBean, roast: Mapping[str, Any], tasting: RoastTasting | None) -> Card:
    """The card of a roast of ``bean``; ValueError when it cannot be published (CHARGE or DROP unmarked, out of bounds)."""
    index = roast.get("timeindex") or []
    charge = index[0] if len(index) > 0 else -1
    drop = index[6] if len(index) > 6 else 0
    first_crack = index[2] if len(index) > 2 else 0
    timex, temps = roast.get("timex") or [], roast.get("temp2") or []
    if charge < 0 or drop <= charge or drop >= min(len(timex), len(temps)):
        raise ValueError("CHARGE and DROP must be marked")
    fahrenheit = str(roast.get("mode") or "C").upper() == "F"

    def celsius(i: int) -> float:
        return round(c_from_f(float(temps[i])) if fahrenheit else float(temps[i]), 1)

    def seconds(i: int) -> int:
        return int(round(timex[i] - timex[charge]))

    points = min(MAX_POINTS, drop - charge + 1)
    picks = [charge + round(n * (drop - charge) / (points - 1)) for n in range(points)]
    flavours = [_text(f) for f in str(bean.flavour_notes or "").split(",")]
    card = Card(name=_text(bean.name), country=_text(bean.country), process=_text(bean.process), crop=int(bean.crop or 0),
                roaster=_text(roast.get("roastertype")), batch_g=int(round(_to_grams(roast.get("weight"), 0))),
                total_s=seconds(drop), after_fc_s=seconds(drop) - seconds(first_crack) if first_crack > 0 else 0,
                drop_c=int(round(celsius(drop))), flavours=tuple(f for f in flavours if f)[:MAX_FLAVOURS],
                verdict=tasting.verdict if tasting else "", curve=tuple((seconds(i), celsius(i)) for i in picks),
                roasted=_day(roast.get("roastisodate")))
    return card_from_json(card_to_json(card))


def _day(value: Any) -> str:
    """The roast's day when the file holds a real one, else ''."""
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat() if len(text) == 10 else ""
    except ValueError:
        return ""


def card_to_json(card: Card) -> dict[str, Any]:
    """The §2 object, without ``id`` and ``published`` (the relay adds them to the index)."""
    return {"v": CARD_VERSION, "name": card.name, "country": card.country, "process": card.process, "crop": card.crop,
            "roaster": card.roaster, "batch_g": card.batch_g, "total_s": card.total_s, "after_fc_s": card.after_fc_s,
            "drop_c": card.drop_c, "flavours": list(card.flavours), "verdict": card.verdict,
            "curve": [[t, c] for t, c in card.curve], **({"roasted": card.roasted} if card.roasted else {})}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _within(value: Any, low: float, high: float) -> bool:
    return _number(value) and low <= value <= high


def card_from_json(data: Mapping[str, Any]) -> Card:
    """The card of a JSON object; ValueError when a key is missing or any bound of the spec is broken. Unknown keys are ignored."""
    try:
        if data["v"] != CARD_VERSION:
            raise ValueError("version")
        texts = [data[k] for k in ("name", "country", "process", "roaster", "verdict")]
        flavours, curve, id_, published = data["flavours"], data["curve"], data.get("id", ""), data.get("published", "")
        if not all(isinstance(t, str) and len(t) <= MAX_TEXT for t in texts) or data["verdict"] not in VERDICTS:
            raise ValueError("text")
        if not (isinstance(flavours, list) and len(flavours) <= MAX_FLAVOURS
                and all(isinstance(f, str) and len(f) <= MAX_TEXT for f in flavours)):
            raise ValueError("flavours")
        if not isinstance(id_, str) or not isinstance(published, str):
            raise ValueError("id")
        roasted = data.get("roasted", "")
        if roasted != "" and not (isinstance(roasted, str) and _day(roasted) == roasted):
            raise ValueError("roasted")
        crop, total = data["crop"], data["total_s"]
        if not (isinstance(crop, int) and (crop == 0 or 1990 <= crop <= 2100)):
            raise ValueError("crop")
        for key, low, high in (("batch_g", 0, 5000), ("total_s", 60, 3600), ("after_fc_s", 0, 1800), ("drop_c", 100, 300)):
            if not _within(data[key], low, high):
                raise ValueError(key)
        if not (isinstance(curve, list) and len(curve) <= MAX_POINTS):
            raise ValueError("curve")
        for point in curve:
            if not (isinstance(point, (list, tuple)) and len(point) == 2 and _within(point[0], 0, total)
                    and _within(point[1], 0, 350)):
                raise ValueError("curve point")
    except (KeyError, TypeError) as e:
        raise ValueError(f"card: {e!r}") from e
    return Card(name=texts[0], country=texts[1], process=texts[2], crop=crop, roaster=texts[3], batch_g=int(data["batch_g"]),
                total_s=int(total), after_fc_s=int(data["after_fc_s"]), drop_c=int(data["drop_c"]), flavours=tuple(flavours),
                verdict=data["verdict"], curve=tuple((int(t), float(c)) for t, c in curve), roasted=roasted,
                id=id_, published=published)


# The list's search keys: relay/src/keys.js applies the very same rules, and both sides are
# tested on relay/test/keys.json. Built on lower() and the Unicode categories rather than
# casefold() and isalnum(), which JavaScript has no exact match for.
_SPACE = re.compile("[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+")


def _unaccented(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def search_key(text: str) -> str:
    """Lower case, accents dropped (NFD, then the non-spacing marks), runs of spaces made one."""
    return " ".join(part for part in _SPACE.split(_unaccented(text)) if part)


def _machine_text(name: str) -> str:
    return "".join(c for c in _unaccented(name) if unicodedata.category(c)[0] in "LN")


_LEGACY_MACHINE_KEYS: Final[dict[str, str]] = {_machine_text(k): _machine_text(v) for k, v in LEGACY_ROASTER_NAMES.items()}


def machine_key(roaster: str) -> str:
    """Letters and digits of the machine's name, lower case without accents, a former name resolved.

    The same key as ``roasters.roaster_identity_key`` for every machine name written in plain letters."""
    key = _machine_text(roaster)
    return _LEGACY_MACHINE_KEYS.get(key, key)


# ── the relay ───────────────────────────────────────────────────────────────

def signing_text(method: str, path: str, time_s: int, body: bytes) -> bytes:
    """The bytes the relay checks the signature against (§3.2); ``body`` is empty for DELETE."""
    return "\n".join(("tilau-library-v1", method, path, str(int(time_s)), hashlib.sha256(body).hexdigest())).encode("utf-8")


Fetch = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]
Sign = Callable[[bytes], tuple[str, str]]    # signed text → (public key, signature), base64url without padding


def _urllib_fetch(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> tuple[int, Mapping[str, str], bytes]:
    """An HTTP error status is returned, not raised; only a connection that fails is "offline"."""
    # Cloudflare refuses Python's default client name with a 403 (error 1010).
    request = urllib.request.Request(url, data=body, headers={"User-Agent": "TilauScope", **headers},  # noqa: S310 — the relay URL is a constant
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read(MAX_PACKAGE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(MAX_PACKAGE_BYTES + 1)
    except (OSError, ValueError) as e:     # URLError, timeout, refused connection, malformed URL
        raise LibraryError("offline") from e


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((v for k, v in headers.items() if k.lower() == name), "")


class Library:
    def __init__(self, base_url: str, fetch: Fetch | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._fetch = fetch or _urllib_fetch

    def _call(self, method: str, path: str, headers: Mapping[str, str] | None = None,
              body: bytes | None = None) -> tuple[Mapping[str, str], bytes]:
        if not self._base:
            raise LibraryError("offline")
        status, received, data = self._fetch(method, self._base + path, headers or {}, body)
        if status >= 400 or not 200 <= status < 300:
            raise LibraryError({429: "rate", 413: "too_large", 404: "unknown"}.get(status, "refused"))
        return received, data

    def _signed(self, method: str, path: str, sign: Sign, body: bytes) -> dict[str, str]:
        now = int(time.time())
        key, signature = sign(signing_text(method, path, now, body))
        return {"X-Tilau-Key": key, "X-Tilau-Time": str(now), "X-Tilau-Signature": signature}

    def search(self, text: str = "", roaster: str = "", ids: Sequence[str] = (), cursor: str = "",
               limit: int = PAGE_SIZE) -> Page:
        """One page of the published roasts matching every filter given, newest roast day first.

        ``roaster`` is a machine's name; ``ids`` keeps the last MAX_IDS well-formed ones, and none
        of them well-formed means no roast, without a request. ``cursor`` is the ``next`` of the
        page before. A row of the relay that breaks the bounds is left out."""
        params = {"limit": str(limit)}
        query = search_key(text)[:MAX_TEXT]
        if query:
            params["q"] = query
        machine = machine_key(roaster)
        if machine:
            params["machine"] = machine
        if ids:
            wanted = [i for i in ids if _ID.fullmatch(i)][-MAX_IDS:]
            if not wanted:
                return Page(cards=(), next="", total=0)
            params["ids"] = ",".join(wanted)
        if cursor:
            params["cursor"] = cursor
        _, data = self._call("GET", "/v1/coffees?" + urllib.parse.urlencode(params))
        try:
            answer = json.loads(data.decode("utf-8"))
            rows, following, total = answer["coffees"], answer["next"], answer["total"]
        except (ValueError, KeyError, TypeError) as e:
            raise LibraryError("refused") from e
        if not (isinstance(rows, list) and isinstance(following, str) and isinstance(total, int)
                and not isinstance(total, bool)):
            raise LibraryError("refused")
        cards = []
        for row in rows:
            try:
                cards.append(card_from_json(row))
            except ValueError:
                continue
        return Page(cards=tuple(cards), next=following, total=total)

    def download(self, coffee_id: str, target: Path) -> Path:
        """The package into the directory ``target`` as ``<id>.tilaucoffee``; refused above MAX_PACKAGE_BYTES."""
        if not _ID.fullmatch(coffee_id):
            raise LibraryError("refused")
        headers, data = self._call("GET", f"/v1/coffees/{coffee_id}")
        announced = _header(headers, "content-length")
        if len(data) > MAX_PACKAGE_BYTES or (announced.isdigit() and int(announced) > MAX_PACKAGE_BYTES):
            raise LibraryError("too_large")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{coffee_id}.tilaucoffee"
        handle, partial = tempfile.mkstemp(dir=target, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            os.replace(partial, path)
        finally:
            Path(partial).unlink(missing_ok=True)
        return path

    def publish(self, package: bytes, sign: Sign) -> str:
        """Publish the package; returns its id (the same one when the relay already holds it)."""
        headers = {"Content-Type": "application/zip", **self._signed("POST", "/v1/coffees", sign, package)}
        _, data = self._call("POST", "/v1/coffees", headers, package)
        try:
            coffee_id = json.loads(data.decode("utf-8"))["id"]
        except (ValueError, KeyError, TypeError) as e:
            raise LibraryError("refused") from e
        if not isinstance(coffee_id, str) or not _ID.fullmatch(coffee_id):
            raise LibraryError("refused")
        return coffee_id

    def withdraw(self, coffee_id: str, sign: Sign) -> None:
        if not _ID.fullmatch(coffee_id):
            raise LibraryError("refused")
        path = f"/v1/coffees/{coffee_id}"
        self._call("DELETE", path, self._signed("DELETE", path, sign, b""))

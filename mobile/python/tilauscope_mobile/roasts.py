# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roasts the tablet holds: its own (saved after a roast), the computer's (imported as files) and the
ones another roaster shared (opened from a .tilaucoffee), indexed with the desktop's index, listed, opened read-only.

The three folders never mix: an imported or shared roast is never sent back as a tablet roast.
Nothing here deletes a roast.
"""

import ast
from dataclasses import replace
import os
from pathlib import Path
import shutil

from tilaucore.alog_index import _UUID_RE, load_index, read_alog_metadata, save_index, scan_directory
from tilaucore.artisan_compat import events_internal_to_external_value, fromCtoFstrict, fromFtoCstrict
from tilaucore.display_colours import LEVER_COLOURS
from tilaucore.energy_model import ESTIMATED, MEASURED, MIXED, NONE
from tilaucore import roast_card as rc
from tilaucore.roast_colour import agtron_text, get_agtron_color
from tilaucore.roast_summary import english, roast_facts, roast_tiles
from tilaucore.roasters import canonical_roaster_name
from tilaucore.ror import RoRSettings, rate_of_rise

from .alog import EVENT_TYPE, curves_c
from .energy import bill

FOLDERS = {"tablet": "roasts", "computer": "roasts-computer", "shared": "roasts-shared"}
_LEVER_OF = {kind: lever for lever, kind in EVENT_TYPE.items()}
CURVE_STEP_S = 2.0 # enough to draw a curve, small enough to send to the screen


def energy_tile(profile: dict) -> dict:
    """The desktop's Energy tile (cave/viewer_detail.energy_tile): the roast's kWh, CHARGE to DROP, then where
    it comes from; from the roast's own energy bill, else rebuilt from its saved power curve."""
    tile = {"caption": "Energy", "value": "—", "sub": "Not recorded", "swatch": "", "filled": False}
    saved = bill(profile)
    if saved is None:
        return tile
    session, summary = saved
    if summary.roast is None:
        return tile
    roast = summary.total(summary.roast.per_channel)
    if roast.provenance == NONE:
        return tile
    word = {MEASURED: "Measured", ESTIMATED: "Estimated", MIXED: "Mixed"}[roast.provenance]
    bits = ["Charge → Drop"]
    bits.append(f"◐ {word} · incomplete" if roast.incomplete else f"● {word}")
    if session.rebuilt:
        bits.append("rebuilt")
    return {**tile, "value": f"{roast.wh / 1000:.3f} kWh", "sub": " · ".join(bits)}


def profile_detail(profile: dict, unit: str = "C") -> dict:
    """One roast read whole, from its profile: its summary tiles in `unit`, its curve (°C) and settings lanes.
    A roast of the library is drawn from this too, without a file of its own."""
    facts = roast_facts(profile)
    if facts.unit != unit: # the tiles in the unit shown, whatever the roast was recorded in
        to = fromFtoCstrict if unit == "C" else fromCtoFstrict
        facts = replace(facts, unit=unit, drop_bt=to(facts.drop_bt) if facts.drop_bt else 0.0,
                        first_crack_bt=to(facts.first_crack_bt) if facts.first_crack_bt else 0.0)
    tiles = [{"caption": t.caption[1], "value": t.value, "sub": " · ".join(english(p) for p in t.sub),
              "swatch": t.swatch, "filled": t.swatch_filled} for t in roast_tiles(facts)] + [energy_tile(profile)]
    timex, (bt, et) = profile.get("timex") or [], curves_c(profile)
    ti = list(profile.get("timeindex") or [-1])
    charge = timex[ti[0]] if ti and 0 <= ti[0] < len(timex) else (timex[0] if timex else 0.0)
    curve, last = [], None
    for t, b, e in zip(timex, bt, et):
        if last is None or t - last >= CURVE_STEP_S:
            curve.append([round(t - charge, 1), round(b, 1) if b > 0 else None, round(e, 1) if e > 0 else None])
            last = t
    marks, points = {}, [] # points: each milestone's time and bean temperature (°C), for its chip
    for key, slot in (("charge", 0), ("dry_end", 1), ("first_crack", 2), ("drop", 6)):
        index = ti[slot] if len(ti) > slot else 0
        if (index >= 0 if slot == 0 else index > 0) and index < len(timex): # CHARGE unmarked is -1, the others 0
            marks[key] = round(timex[index] - charge, 1)
            if index < len(bt) and bt[index] > 0:
                points.append({"key": key, "t": marks[key], "bt": round(bt[index], 1)})
    # The turning point as the desktop saved it (seconds from CHARGE, in the roast's unit): computed, not marked
    computed = profile.get("computed") if isinstance(profile.get("computed"), dict) else {}
    tp_s, tp_bt = computed.get("TP_time"), computed.get("TP_BT")
    if isinstance(tp_s, (int, float)) and isinstance(tp_bt, (int, float)) and tp_s > 0 and tp_bt > 0:
        fahrenheit = str(profile.get("mode") or "C").upper() == "F"
        points.append({"key": "tp", "t": round(float(tp_s), 1), "bt": round(fromFtoCstrict(tp_bt) if fahrenheit else float(tp_bt), 1)})
    lanes = {}
    for index, kind, value in zip(profile.get("specialevents") or [], profile.get("specialeventstype") or [],
                                  profile.get("specialeventsvalue") or []):
        lever = _LEVER_OF.get(kind)
        if lever and 0 <= index < len(timex):
            lanes.setdefault(lever, []).append([round(timex[index] - charge, 1), events_internal_to_external_value(value)])
    found = _UUID_RE.search(str(profile.get("beans") or ""))
    return {"title": profile.get("title") or "", "epoch": profile.get("roastepoch") or 0,
            "bean_uuid": found.group(1) if found else "", "roast_uuid": str(profile.get("roastUUID") or ""),
            "tiles": tiles, "curve": curve, "marks": marks, "points": sorted(points, key=lambda p: p["t"]), "lanes": lanes}


def _figure(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def card_data(profile: dict, bean=None, ror_settings: RoRSettings | None = None) -> dict:
    """The desktop's roast card (Roasts › Export › Roast card) as mobile/web/roast-card.js draws it: what
    tilaucore.roast_card says, in the roast's unit, the curve from CHARGE to DROP in seconds from CHARGE."""
    marks = rc.milestones(profile)
    agtron, basis = rc.colour(profile)
    energy = energy_tile(profile)["value"]
    country, process = (str(getattr(bean, k, "") or "").strip() for k in ("country", "process"))
    card = {"kicker": " · ".join(v for v in (country, process) if v).upper(),
            "name": str(getattr(bean, "name", "") or profile.get("title") or "").strip(),
            "epoch": rc.number(profile.get("roastepoch")) or 0, "date": str(profile.get("roastdate") or "").strip(),
            "roaster": canonical_roaster_name(str(profile.get("roastertype") or "")),
            "figures": rc.figures(profile, marks), "agtron": agtron, "basis": basis,
            "agtron_text": agtron_text(agtron, basis) if agtron else "", "swatch": get_agtron_color(agtron) if agtron else "",
            "energy": "" if energy == rc.DASH else energy, "frame": rc.has_frame(profile, marks)}
    if not card["frame"]:
        return card
    times, bt, et = profile.get("timex") or [], profile.get("temp2") or [], profile.get("temp1") or []
    # The limits are in °C/min; a °F roast's RoR is 1.8 times larger, as on the desktop (library_tab._roast_ror)
    s = ror_settings or RoRSettings()
    if str(profile.get("mode") or "C").upper() == "F":
        s = replace(s, limit_min=s.limit_min * 1.8, limit_max=s.limit_max * 1.8)
    ror = rate_of_rise(times, bt, s) + [None] * len(times)
    charge, drop = marks["charge"], marks["drop"]
    t0, start = times[charge], rc.rise_start(profile, marks)
    span = range(charge, drop + 1)
    tp = rc.turning_point(profile, marks)
    moments = [("charge", charge)] + ([("tp", tp)] if tp is not None else [])
    moments += [(k, marks[k]) for k in ("dry", "fc") if k in marks] + [("drop", drop)]
    played = rc.lanes(profile, marks, {kind: LEVER_COLOURS[lever] for lever, kind in EVENT_TYPE.items()})
    peak = rc.peak_rise(profile, marks, ror)
    rows = []
    for row in rc.key_moments(profile, marks, played):
        i = rc.sample_at(profile, marks, row.t)
        temp = rc.number(bt[i]) if i < len(bt) else None
        rows.append({"t": row.t, "text": row.text, "key": row.key, "color": row.color, "milestone": row.milestone,
                     "bean": None if temp is None or temp == -1 else round(temp, 1),
                     "rise": _figure(ror[i], 1) if i >= start else None})
    card.update({"total": times[drop] - t0, "t": [round(times[i] - t0, 2) for i in span],
                 "bt": [_figure(rc.reading(bt, i)) for i in span], "et": [_figure(rc.reading(et, i)) for i in span],
                 "ror": [_figure(ror[i]) if i >= start else None for i in span],
                 "scales": vars(rc.scales(profile, marks, ror)), "phases": rc.phase_durations(profile, marks),
                 "moments": [{"key": k, "t": times[i] - t0, "bt": _figure(rc.reading(bt, i))} for k, i in moments],
                 "peak": {"t": times[peak[1]] - t0, "r": round(peak[0], 2)} if peak else None,
                 "lanes": [{"name": lane.name, "color": lane.color, "steps": lane.steps} for lane in played],
                 "rows": rows})
    return card



def _same_roast(roast_uuid: str) -> str:
    """A roast id as two files of the same roast share it: dashes and case ignored, as the desktop's import."""
    return roast_uuid.replace("-", "").lower()

class Roasts:
    def __init__(self, files_directory: str) -> None:
        self.base = Path(files_directory)

    def folder(self, origin: str) -> Path:
        return self.base / FOLDERS[origin]

    def _fresh(self, origin: str) -> dict:
        """One folder's index entries by file path; the index file is a cache."""
        folder, cache = self.folder(origin), self.base / f"alog_index_{origin}.json"
        known = load_index(cache, folder)
        fresh = scan_directory(folder, known)
        if fresh != known:
            save_index(cache, folder, fresh)
        return fresh

    def records(self) -> list:
        """(origin, index entry) of both folders."""
        return [(origin, meta) for origin in FOLDERS for meta in self._fresh(origin).values()]

    def index(self) -> dict:
        """Both folders' index entries by file path, as the plan reads past roasts."""
        return {path: meta for origin in FOLDERS for path, meta in self._fresh(origin).items()}

    def held(self) -> set[str]:
        """The roastUUIDs held in any folder, dashes and case ignored as the desktop's import does."""
        return {_same_roast(m.roast_uuid) for _, m in self.records() if m.roast_uuid}

    def store(self, origin: str, name: str, profile: dict) -> bool:
        """A roast file written into `origin`'s folder; False when that name is taken: nothing is overwritten."""
        folder = self.folder(origin)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.parent != folder or target.exists(): # the name is built from a package: it must stay in the folder
            return False
        temporary = target.with_suffix(".tmp")
        temporary.write_text(repr(profile), encoding="utf-8")
        os.replace(temporary, target)
        return True

    def path(self, origin: str, name: str) -> Path:
        folder = self.folder(origin).resolve()
        target = (folder / name).resolve()
        if target.parent != folder or not target.is_file():
            raise ValueError("No such roast")
        return target

    def detail(self, origin: str, name: str, unit: str = "C") -> dict:
        """One roast file read whole, as profile_detail draws it."""
        profile = ast.literal_eval(self.path(origin, name).read_text(encoding="utf-8"))
        return {"origin": origin, "name": name, **profile_detail(profile, unit)}

    def _sorted(self, paths: list[str]):
        """(path, metadata, verdict) of each file: 'new', 'already' (same roast held, or twice in the lot) or 'invalid'."""
        held = self.held()
        for source in map(Path, paths):
            meta = read_alog_metadata(source) if source.suffix.lower() == ".alog" else None
            if meta is None or not meta.roast_uuid:
                yield source, meta, "invalid"
            elif _same_roast(meta.roast_uuid) in held:
                yield source, meta, "already"
            else:
                held.add(_same_roast(meta.roast_uuid))
                yield source, meta, "new"

    def preview(self, paths: list[str]) -> dict:
        """What an import of these files would do, without doing it."""
        counts = {"new": 0, "already": 0, "invalid": 0}
        for _source, _meta, verdict in self._sorted(paths):
            counts[verdict] += 1
        return counts

    def import_files(self, paths: list[str]) -> dict:
        """The computer's roast files, copied into their own folder; one already held (same roast) is skipped."""
        folder = self.folder("computer")
        folder.mkdir(parents=True, exist_ok=True)
        counts = {"imported": 0, "already": 0, "invalid": 0}
        for source, meta, verdict in list(self._sorted(paths)):
            if verdict != "new":
                counts[verdict] += 1
            else:
                target = folder / source.name
                if target.exists():
                    target = folder / f"{source.stem}_{meta.roast_uuid[:8]}{source.suffix}"
                temporary = target.with_suffix(".tmp")
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
                counts["imported"] += 1
        return counts

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A finished roast as a desktop `.alog`: the Artisan profile keys TilauScope
desktop reads, written the way it writes them (`repr` of the dict, UTF-8), so a
roast made on the tablet opens on the desktop as one of its own.

The file's units, rounding, event values and weight loss are tilaucore.units; TP is
tilaucore.milestones.turning_point. The `computed` fields are the
format's: times from CHARGE, readings at each milestone, phase lengths. What needs the
desktop's engine (AUC, RoR by phase, energy) is left for the desktop to compute.
"""

from datetime import datetime
import os
from pathlib import Path
import tempfile

from tilaucore.milestones import turning_point
from tilaucore.units import c_from_f as fromFtoCstrict
from tilaucore.units import event_from_slider as event_value
from tilaucore.units import round_to as float2float
from tilaucore.units import weight_loss_pct as weight_loss

from .session import Session

# Desktop event types, as the operator's Skywalker setup numbers them.
EVENT_TYPE = {"air": 0, "drum": 1, "extractor": 2, "burner": 3}
TIMEINDEX = ("charge", "dry_end", "first_crack", "fc_end", "second_crack", "sc_end", "drop", "cool")

# Accessories recorded as desktop extra devices: registry key, channel 1, channel 2,
# names, and the display settings of the operator's own profiles.
EXTRA_DEVICES = (
    ("difluid", "inlet_c", "catalyst_c", "Inlet", "Catalyst", ("#148286ff", "#168083ff"), (False, False), (True, True)),
    ("tilau12", "room_c", "room_rh", "Temp", "Hum", ("#fffc79ff", "#fffb00ff"), (False, True), (True, True)),
    ("tilau34", "pressure_hpa", "altitude_m", "Press", "Alt", ("#fffb00ff", "#fffb00ff"), (True, True), (True, False)),
)
# Registry ids at the time of writing; the desktop resolves them through tilau_name_map.
REGISTRY_ID = {"difluid": 190, "tilau12": 191, "tilau34": 192}
MISSING = -1.0 # Artisan's "no reading"


def curves_c(profile: dict) -> tuple[list[float], list[float]]:
    """BT and ET of a recorded roast in °C, the tablet's unit: a roast recorded in °F is converted
    as the desktop converts it on load (Artisan's strict conversion: -1 stays -1)."""
    bt, et = [float(v) for v in profile.get("temp2") or []], [float(v) for v in profile.get("temp1") or []]
    if str(profile.get("mode") or "C").upper() == "F":
        bt, et = [fromFtoCstrict(v) for v in bt], [fromFtoCstrict(v) for v in et]
    return bt, et


def find_tp(timeindex: list[int], timex: list[float], temp: list[float]) -> int:
    """The turning point's sample, 0 when the roast has none (no CHARGE, BT never turned before Dry End)."""
    end = min((m for m in timeindex[1:] if m > timeindex[0]), default=None)
    return turning_point(timex, temp, timeindex[0], end) or 0


def _events(session: Session, timex: list[float], levers: dict) -> dict:
    indices, types, values, strings = [], [], [], []
    for i, (elapsed, lever, value) in enumerate(session.settings):
        if lever not in EVENT_TYPE:
            continue
        index = next((i for i, t in enumerate(timex) if t >= elapsed), len(timex) - 1)
        indices.append(index)
        types.append(EVENT_TYPE[lever])
        values.append(float2float(event_value(value)))
        # The preheat's commands as the desktop's TilauPID writes them: its learning reads them so.
        if i in session.pid_settings:
            strings.append(f"S{EVENT_TYPE[lever]}:{value}%")
        elif i in session.alarm_settings: # as the desktop writes an alarm's slider move
            strings.append(f"A{session.alarm_settings[i]} (S{EVENT_TYPE[lever]})")
        else:
            strings.append(f"{value}%")
    names = {kind: levers[key]["name"] if key in levers else key.capitalize() for key, kind in EVENT_TYPE.items()}
    return {"specialevents": indices, "specialeventstype": types, "specialeventsvalue": values,
            "specialeventsStrings": strings,
            "etypes": [names[0], names[1], names[2], names[3], "--"],
            "eventsliderunits": ["%", "%", "%", "%"]}


def _computed(session: Session, timeindex: list[int], timex: list[float], et: list[float], bt: list[float]) -> dict:
    c: dict = {}
    start = 0.0
    if timeindex[0] != -1:
        start = timex[timeindex[0]]
        c.update(CHARGE_time=float2float(start), CHARGE_ET=float2float(et[timeindex[0]]),
                 CHARGE_BT=float2float(bt[timeindex[0]]))
    tp = find_tp(timeindex, timex, bt)
    if tp > 0:
        c.update(TP_idx=tp, TP_time=float2float(timex[tp] - start), TP_ET=float2float(et[tp]), TP_BT=float2float(bt[tp]))
        if timeindex[6]:
            ets = [v for v in et[tp:timeindex[6]] if v != MISSING]
            if ets:
                c["MET"] = float2float(max(ets))
    for slot, key in ((1, "DRY"), (2, "FCs"), (3, "FCe"), (4, "SCs"), (5, "SCe"), (6, "DROP"), (7, "COOL")):
        if timeindex[slot]:
            i = timeindex[slot]
            c.update({f"{key}_time": float2float(timex[i] - start), f"{key}_ET": float2float(et[i]),
                      f"{key}_BT": float2float(bt[i])})
    dry, fcs, drop, cool = timeindex[1], timeindex[2], timeindex[6], timeindex[7]
    if fcs and drop and timex[drop] != start:
        c["totaltime"] = float2float(timex[drop] - start, 3)
        c["finishphasetime"] = float2float(timex[drop] - timex[fcs], 3)
        if dry:
            c["dryphasetime"] = float2float(timex[dry] - start, 3)
            c["midphasetime"] = float2float(timex[fcs] - timex[dry], 3)
        if cool:
            c["coolphasetime"] = float2float(timex[cool] - timex[drop], 3)
    if "TP_BT" in c and "DROP_BT" in c and c["DROP_time"] != c["TP_time"]:
        c["total_ror"] = float2float((c["DROP_BT"] - c["TP_BT"]) / (c["DROP_time"] - c["TP_time"]) * 60)
    green, roasted = session.weights["green"] or 0, session.weights["roasted"] or 0
    loss = weight_loss(green, roasted)
    if loss:
        c["weight_loss"] = float2float(loss)
    c["weightin"], c["weightout"] = float(green), float(roasted)
    if green:
        c["total_yield"] = float(roasted or green)
        total = weight_loss(green, roasted or green)
        if total:
            c["total_loss"] = float2float(total)
    greens = session.greens or {}
    if greens.get("density"):
        c["set_density"] = float2float(greens["density"])
    if greens.get("moisture"):
        c["moisture_greens"] = float2float(greens["moisture"])
    for key, name in (("humidity_pct", "ambient_humidity"), ("pressure_hpa", "ambient_pressure"), ("temperature_c", "ambient_temperature")):
        if key in (session.ambient or {}): # an MQTT room may give only some of them
            c[name] = float2float(session.ambient[key])
    return c


def _extra_devices(session: Session, timex: list[float]) -> dict:
    used = [d for d in EXTRA_DEVICES
            if any(s.extras and (d[1] in s.extras or d[2] in s.extras) for s in session.samples)]
    def series(channel: str) -> list[float]:
        return [float2float(s.extras[channel], 2) if s.extras and channel in s.extras else MISSING for s in session.samples]
    n = len(used)
    return {
        "extradevices": [REGISTRY_ID[d[0]] for d in used],
        "tilau_name_map": {slot: d[0] for slot, d in enumerate(used)},
        "extraname1": [d[3] for d in used], "extraname2": [d[4] for d in used],
        "extratimex": [list(timex) for _ in used],
        "extratemp1": [series(d[1]) for d in used], "extratemp2": [series(d[2]) for d in used],
        "extramathexpression1": [""] * n, "extramathexpression2": [""] * n,
        "extradevicecolor1": [d[5][0] for d in used], "extradevicecolor2": [d[5][1] for d in used],
        "extraNoneTempHint1": [d[6][0] for d in used], "extraNoneTempHint2": [d[6][1] for d in used],
        "extraLCDvisibility1": [d[7][0] for d in used], "extraLCDvisibility2": [d[7][1] for d in used],
        "extraCurveVisibility1": [False] * n, "extraCurveVisibility2": [False] * n,
        "extraDelta1": [False] * n, "extraDelta2": [False] * n,
        "extraFill1": [0] * n, "extraFill2": [0] * n,
        "extramarkersizes1": [6.0] * n, "extramarkersizes2": [6.0] * n,
        "extramarkers1": ["None"] * n, "extramarkers2": ["None"] * n,
        "extralinewidths1": [1.0] * n, "extralinewidths2": [1.0] * n,
        "extralinestyles1": ["-"] * n, "extralinestyles2": ["-"] * n,
        "extradrawstyles1": ["default"] * n, "extradrawstyles2": ["default"] * n,
    }


def profile(session: Session, *, levers: dict, operator: str = "", roaster: str = "") -> dict:
    """The Artisan profile of a stopped session."""
    timex = [float2float(s.elapsed_s, 3) for s in session.samples]
    bt = [float2float(s.bt_c, 2) for s in session.samples]
    et = [float2float(s.et_c, 2) if s.et_c is not None else MISSING for s in session.samples]
    m = session.milestones
    timeindex = [m.get("charge", -1)] + [m.get(key, 0) for key in TIMEINDEX[1:]]
    epoch = int(session.started_epoch or 0)
    local = datetime.fromtimestamp(epoch) if epoch else None # local wall clock, summer time included
    green, roasted = session.weights["green"] or 0, session.weights["roasted"] or 0
    title = session.title or "TilauScope roast"
    greens = session.greens or {}
    data = {
        "recording_version": "4.3", "version": "4.3", "artisan_os": "Android", "mode": "C",
        "title": title, "operator": operator, "roastertype": roaster, "machinesetup": roaster,
        "roastUUID": session.uuid, "roastepoch": epoch, "roasttzoffset": session.tz_offset,
        "roastisodate": local.strftime("%Y-%m-%d") if local else "",
        "roastdate": local.strftime("%a %b %d %Y") if local else "",
        "roasttime": local.strftime("%H:%M:%S") if local else "",
        "beans": session.beans, "weight": [float(green), float(roasted), "g"],
        "whole_color": session.colours["whole"] or 0.0, "ground_color": session.colours["ground"] or 0.0,
        "color_system": "Agtron",
        # Roast Setup, as Artisan stores it: density per litre, moisture and bean temperature, screen size in 1/64"
        "density": [float(greens.get("density") or 0.0), "g", 1.0, "l"],
        "moisture_greens": float(greens.get("moisture") or 0.0), "greens_temp": float(greens.get("greens_temp") or 0.0),
        "beansize_min": str(int((greens.get("beansize") or (0, 0))[0])), "beansize_max": str(int((greens.get("beansize") or (0, 0))[1])),
        "samplinginterval": 1.0, "timex": timex, "temp1": et, "temp2": bt, "timeindex": timeindex,
        **_events(session, timex, levers),
        **_extra_devices(session, timex),
        "computed": _computed(session, timeindex, timex, et, bt),
    }
    if session.simulated:
        data["tilau_simulated"] = True # never enters the desktop's learning
    if session.energy:
        data["tilau_energy"] = session.energy
    if session.late_sampling:
        data["tilau_late_sampling"] = list(session.late_sampling) # late ticks, longest gap (s)
    data["pidSource"] = session.pid_source
    if session.preheat_sv_c is not None:
        data["tilau_preheat_sv_c"] = session.preheat_sv_c # a guided preheat: the desktop learns from it
    for key, name in (("temperature_c", "ambientTemp"), ("humidity_pct", "ambient_humidity"), ("pressure_hpa", "ambient_pressure")):
        if key in (session.ambient or {}):
            data[name] = session.ambient[key]
    return data


def file_name(data: dict) -> str:
    """As the desktop names a roast: title, then yy-mm-dd_hhmm."""
    title = "".join(ch for ch in data["title"] if ch not in '/\\:*?"<>|')
    stamp = datetime.strptime(f'{data["roastisodate"]} {data["roasttime"]}', "%Y-%m-%d %H:%M:%S") \
        if data["roastisodate"] else datetime(1970, 1, 1)
    return f"{title}_{stamp.strftime('%y-%m-%d_%H%M')}.alog"


def write(path: str, data: dict) -> None:
    """Atomic: a failed write leaves the previous file, or none, never a partial roast."""
    text = repr(data)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".alog-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Alarm lists on the tablet (android/ALARM-SPEC.md C2): the operator's Artisan .alrm files,
the one used for every roast, and what each fired row asks the tablet to do.

The firing rule is the desktop's (tilaucore.alarms); an alarm acts as the operator's hand
(decision 7): the caller runs the lever, button and extractor actions on the same path as a
touch. What the tablet cannot run is said, row by row, never guessed.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, replace
from pathlib import Path

from tilaucore.alarms import (AIRWAVE, AMBIENT, ANCHORS, EVENT_BUTTON, IF_ALARM, NO_SOURCE, POPUP, SLIDERS, Alarm,
                              AlarmRun, Readings, TurningPoint, event_buttons, read_alrm, slider_value, write_alrm)
from tilaucore.artisan_compat import events_internal_to_external_value
from tilaucore.artisan_setup import LEVERS, MachineSetup

from .alog import EXTRA_DEVICES
from .session import Session

# The tablet's channels of each desktop device, by the stable key the desktop writes in tilau_name_map.
CHANNELS = {key: (first, second, (label1, label2)) for key, first, second, label1, label2, *_ in EXTRA_DEVICES}

# Artisan's timeindex position of each tablet milestone (canvas.py: 0 CHARGE … 6 DROP)
MARK_INDEX = {"charge": 0, "dry_end": 1, "first_crack": 2, "drop": 6}
ANCHOR_WORDS = {"on": "Start", "start": "Start", "charge": "Charge", "tp": "TP", "dry_end": "Dry end",
                "first_crack": "First crack", "first_crack_end": "First crack end", "second_crack": "Second crack",
                "second_crack_end": "Second crack end", "drop": "Drop", "cool_end": "Cool end"}
PHASES = {"on": "Setup", "start": "Setup", "charge": "Drying", "tp": "Drying", "dry_end": "Maillard",
          "first_crack": "Development", "first_crack_end": "Development", "second_crack": "Development",
          "second_crack_end": "Development", "drop": "Finish", "cool_end": "Finish"}
SOURCES = {-2: "ET RoR", -1: "BT RoR", 0: "ET", 1: "BT"}
CONDITIONS = ("below", "above", "at", "not at")
# Artisan's own actions, by code, for the rows the tablet does not run
ARTISAN_ACTIONS = {1: "Call program", 7: "START", 8: "DRY END", 9: "FC START", 10: "FC END", 11: "SC START",
                   12: "SC END", 13: "DROP", 14: "COOL END", 15: "OFF", 16: "CHARGE", 17: "Ramp/soak on",
                   18: "Ramp/soak off", 19: "PID on", 20: "PID off", 21: "PID SV", 22: "Playback on",
                   23: "Playback off", 24: "Canvas colour", 25: "Canvas colour reset", 28: "Kernel command"}
EXTRACTOR_SPEED = (30, 100) # the AirWave's speed range (desktop: AirwaveSpeed)
# The crack counter's commands as the desktop names them (tilauambient.send_command), exact words only:
# "CAL" is the start of "CALMAILLARD". Their codes are the probe firmware's audio commands.
AMBIENT_COMMANDS = {"CAL": 0x0000, "CALEMPTY": 0x0000, "CAL1": 0x0000, "CALMAILLARD": 0x0006, "CAL2": 0x0006,
                    "CALSTATE": 0x0003, "START": 0x0001, "STOP": 0x0002, "DEBUG": 0x0010, "NODEBUG": 0x0011}
TOAST_S = 4.0 # how long a fired alarm stays in the roast screen's toast
# One count for every roast of the process: the roast screen shows an id once, and stays open from roast to roast.
_FIRED = itertools.count(1)
_NAME = re.compile(r"[^\w .()-]")


@dataclass(frozen=True)
class Act:
    """What one fired row asks: a lever value, a roaster command, an extractor command or a message."""
    row: int
    lever: str | None = None
    value: int | None = None
    commands: tuple[str, ...] = ()
    relative: str | None = None # "+": the value moves the lever, "%": by that percentage of it
    extractor: tuple[tuple[str, str], ...] = () # (power|speed|mode, its argument)
    ambient: tuple[int, ...] = () # the crack counter's command codes, in order
    message: str | None = None


def threshold_kind(source: int, desktop_devices: list[str]) -> str:
    """What an alarm's value is, for the unit shown (UNIT-SPEC): "temperature", "rate" (a RoR, °/min)
    or "" (no source, or a reading that is no temperature, such as a humidity)."""
    if source in (0, 1):
        return "temperature"
    if source in (-1, -2):
        return "rate"
    position, channel = (source - 2) // 2, (source - 2) % 2
    if source >= 2 and position < len(desktop_devices) and desktop_devices[position] in CHANNELS:
        return "temperature" if CHANNELS[desktop_devices[position]][channel].endswith("_c") else ""
    return ""


def in_unit(value: float, kind: str, unit: str) -> float:
    """A threshold kept in °C, in `unit`. 500 is Artisan's "no value" and stays."""
    if unit != "F" or not kind or value == 500:
        return value
    return round(value * 1.8 + 32 if kind == "temperature" else value * 1.8, 2)


def from_unit(value: float, kind: str, unit: str, typed: bool = False) -> float:
    """A threshold in `unit`, back to °C; `typed`: by the operator, so 500 is a value, not Artisan's "none"."""
    if unit != "F" or not kind or (value == 500 and not typed):
        return value
    return round((value - 32) / 1.8 if kind == "temperature" else value / 1.8, 4)


def rows_in_unit(rows: list[Alarm], desktop_devices: list[str], unit: str, back: bool = False) -> list[Alarm]:
    """The rows with their thresholds in `unit` (`back`: from `unit` to °C)."""
    convert = from_unit if back else in_unit
    return [replace(a, temperature=convert(a.temperature, threshold_kind(a.source, desktop_devices), unit)) for a in rows]


class AlarmLists:
    """The .alrm files kept on the tablet, one list each, named after its file."""

    def __init__(self, folder: str) -> None:
        self.folder = Path(folder)

    def names(self) -> list[str]:
        return sorted((p.stem for p in self.folder.glob("*.alrm")), key=str.lower) if self.folder.is_dir() else []

    def rows(self, name: str) -> list[Alarm]:
        return read_alrm(self._path(name).read_text(encoding="utf-8"))

    def add(self, name: str, text: str) -> str:
        """Keeps an .alrm's text under `name` (a list of the same name is replaced); ValueError if it is not one."""
        try:
            read_alrm(text)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("This file is not an Artisan alarm list") from error
        name = _NAME.sub("", Path(name).stem).strip()[:60] or "Alarms"
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(name).write_text(text, encoding="utf-8")
        return name

    def save(self, name: str, rows: list[Alarm]) -> None:
        self._path(name).write_text(write_alrm(rows), encoding="utf-8")

    def remove(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def new_name(self) -> str:
        """"New list", then "New list 2"…: a name no list has yet."""
        taken, n = set(self.names()), 1
        while (name := "New list" if n == 1 else f"New list {n}") in taken:
            n += 1
        return name

    def path(self, name: str) -> str:
        return str(self._path(name))

    def _path(self, name: str) -> Path:
        path = (self.folder / f"{name}.alrm").resolve()
        if path.parent != self.folder.resolve():
            raise ValueError("No such alarm list")
        return path


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _span(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60}:{seconds % 60:02d}"


class TabletAlarms:
    """One roast's run of the active list: fires rows, says what each asks and how it went."""

    def __init__(self, name: str, rows: list[Alarm], setup: MachineSetup, levers: dict, extractor: bool,
                 ambient: bool = False, desktop_devices: list[str] | None = None, unit: str = "C") -> None:
        self.name, self.rows, self.setup = name, rows, setup
        self.levers = levers # the roast screen's levers: key -> {"name", "step"}
        self.extractor = extractor # an AirWave in the setup
        self.ambient = ambient # a TilauAmbient in the setup
        # The computer's extra devices, in its order (tilau_name_map): an alarm source 2+ points into it.
        self.desktop_devices = desktop_devices or []
        self.unit = unit # the thresholds are kept in °C; the sentences say them in this unit
        self.run = AlarmRun(rows)
        self.tp = TurningPoint()
        self.fired_at: dict[int, float] = {} # row -> roast time it fired
        self.recent: list[dict] = [] # the latest fired rows, for the toast
        self.message: dict | None = None # the latest message alarm
        self.texts = [self._describe(i) for i in range(len(rows))]

    # ── firing ───────────────────────────────────────────────────────────
    def step(self, session: Session, now: float) -> list[Act]:
        """The rows that fire at this sample, as acts for the caller to run."""
        samples = session.samples
        if not samples:
            return []
        times = [s.elapsed_s for s in samples]
        bt = [s.bt_c for s in samples]
        et = [s.et_c if s.et_c is not None else -1 for s in samples]
        marks = [-1, 0, 0, 0, 0, 0, 0, 0]
        for key, index in session.milestones.items():
            marks[MARK_INDEX[key]] = index
        tp = self.tp.update(times, bt, marks)
        extra = []
        for key in self.desktop_devices: # each device's two channels as Artisan holds them (-1: no reading)
            first, second, _ = CHANNELS.get(key, (None, None, None))
            extra.append(tuple([(s.extras or {}).get(ch, -1) for s in samples] if ch else [] for ch in (first, second)))
        readings = Readings(clock_s=times[-1], recording=True, times=times, et=et, bt=bt,
                            delta_et=list(session.et_ror_series), delta_bt=list(session.ror_series), marks=marks, tp=tp,
                            extra=extra)
        acts = []
        for i in self.run.step(readings):
            self.fired_at[i] = now
            act = self._act(i)
            seq = next(_FIRED)
            self.recent = [r for r in self.recent if now - r["at"] < TOAST_S] + [
                {"id": seq, "at": now, "row": i + 1, "what": self.texts[i]["what"], "when": self.texts[i]["when"],
                 "run": self.texts[i]["why"] is None, "beep": bool(self.rows[i].beep)}]
            if act is not None and act.message is not None:
                self.message = {"id": seq, "text": act.message, "row": i + 1, "when": self.texts[i]["when"]}
            if act is not None:
                acts.append(act)
        return acts

    def _act(self, i: int) -> Act | None:
        a = self.rows[i]
        if self.texts[i]["why"] is not None:
            return None
        if a.action in SLIDERS:
            lever = LEVERS[SLIDERS[a.action]]
            return Act(i, lever=lever, value=self._clamp(lever, slider_value(a.text)))
        if a.action == EVENT_BUTTON:
            return self._button(i, a.text)
        if a.action == POPUP:
            return Act(i, message=a.text)
        if a.action == AIRWAVE:
            return Act(i, extractor=tuple(_extractor_commands(a.text)))
        if a.action == AMBIENT:
            return Act(i, ambient=tuple(_ambient_commands(a.text)))
        return None

    def _button(self, i: int, text: str) -> Act | None:
        """The first button of the row's spec the tablet can press (Artisan's recordextraevent)."""
        for number, override in event_buttons(text):
            if not 1 <= number <= len(self.setup.event_buttons):
                continue
            button = self.setup.event_buttons[number - 1]
            value = events_internal_to_external_value(button.value) if override is None else override
            kind = button.kind
            if kind in (4, 9):
                if button.command is None:
                    continue
                command = button.command.format(*([value] * button.command.count("{}")))
                return Act(i, commands=tuple(part.strip() for part in command.split(";") if part.strip()))
            if kind <= 3:
                return Act(i, lever=LEVERS[kind], value=value)
            if 5 <= kind <= 8:
                return Act(i, lever=LEVERS[kind - 5], value=value, relative="+")
            if 10 <= kind <= 13:
                return Act(i, lever=LEVERS[kind - 10], value=value, relative="%")
        return None

    def resolve(self, act: Act, current: dict) -> int | None:
        """The lever value an act sets, from the lever's current value for a relative button."""
        if act.lever is None or act.lever not in current:
            return None
        value = act.value
        if act.relative == "+":
            value = current[act.lever] + act.value
        elif act.relative == "%":
            value = current[act.lever] + int(round(current[act.lever] * act.value / 100))
        return self._clamp(act.lever, value)

    def _clamp(self, lever: str, value: int) -> int:
        command = self.setup.levers.get(lever)
        low, high = (command.minimum, command.maximum) if command else (0, 100)
        return max(0, min(100, max(low, min(high, int(value)))))

    # ── what the screen shows ────────────────────────────────────────────
    def _describe(self, i: int) -> dict:
        """When the row fires, what it does, and why the tablet does not run it (None when it does)."""
        a = self.rows[i]
        anchor = ANCHORS.get(a.anchor, "")
        when = "then" if a.anchor == IF_ALARM else ANCHOR_WORDS.get(anchor, "?")
        if a.offset > 0:
            when += f" + {_span(a.offset)}"
        why = None
        if a.source != NO_SOURCE:
            source = SOURCES.get(a.source)
            if source is None:
                source, why = self.probe(a.source)
            value = in_unit(a.temperature, threshold_kind(a.source, self.desktop_devices), self.unit)
            condition = f"{source} {CONDITIONS[a.cond] if 0 <= a.cond < 4 else '?'} {round(value, 1):g}"
            when = f"{when} and {condition}" if a.offset > 0 else (condition if a.anchor == IF_ALARM else f"{when} · {condition}")
        what, why = self._what(a, why)
        if not a.on:
            why = "Off in this list"
        if anchor not in ("if_alarm", "on", "start", "charge", "tp", "dry_end", "first_crack", "drop"):
            why = why or "This milestone is not marked on the tablet"
        return {"when": when, "what": what, "why": why, "phase": self._phase(i, set())}

    def probe(self, source: int) -> tuple[str, str | None]:
        """The computer's extra probe an alarm source names, and why the tablet cannot read it (None if it can)."""
        position, channel = (source - 2) // 2, (source - 2) % 2
        if position >= len(self.desktop_devices):
            return f"Extra probe {source - 1}", "The computer's extra devices are not known yet: import its roasts"
        key = self.desktop_devices[position]
        if key not in CHANNELS:
            return f"{key} {channel + 1}", "This device of the computer is not read on the tablet"
        return CHANNELS[key][2][channel], None

    def _what(self, a: Alarm, why: str | None) -> tuple[str, str | None]:
        if a.action in SLIDERS:
            lever = LEVERS[SLIDERS[a.action]]
            name = self.levers.get(lever, {}).get("name") or lever.capitalize()
            if lever not in self.levers:
                why = why or f"No {name.lower()} on this roaster"
            return f"{name} {slider_value(a.text)} %", why
        if a.action == EVENT_BUTTON:
            numbers = [n for n, _ in event_buttons(a.text)]
            pressable = [n for n in numbers if 1 <= n <= len(self.setup.event_buttons)
                         and (self.setup.event_buttons[n - 1].kind not in (4, 9) or self.setup.event_buttons[n - 1].command)]
            label = ", ".join(str(n) for n in numbers) or a.text
            if not pressable:
                why = why or "This button is not on the tablet's roaster setup"
            return f"Button {label}", why
        if a.action == POPUP:
            return f"Message “{a.text}”", why
        if a.action == AIRWAVE:
            if not self.extractor:
                why = why or "No extractor in the tablet's setup"
            elif not _extractor_commands(a.text):
                why = why or "The tablet runs FAN, MODE and POWER only"
            return f"Extractor {a.text}", why
        if a.action == AMBIENT:
            if not self.ambient:
                why = why or "No TilauAmbient in the tablet's setup"
            elif not _ambient_commands(a.text):
                why = why or "Unknown TilauAmbient command"
            return f"TilauAmbient {a.text}", why
        name = ARTISAN_ACTIONS.get(a.action, f"Action {a.action}")
        if a.action in (19, 20):
            return name, why or "The preheat is set in Roast Setup"
        return name, why or "Not run on the tablet"

    def _phase(self, i: int, seen: set) -> str:
        a = self.rows[i]
        if a.anchor == IF_ALARM:
            if 0 <= a.guard < len(self.rows) and a.guard not in seen:
                return self._phase(a.guard, seen | {i})
            return "Conditional"
        return PHASES.get(ANCHORS.get(a.anchor, ""), "Conditional")

    def view(self, now: float, charge_s: float | None) -> dict:
        rows = []
        for i, text in enumerate(self.texts):
            at = self.fired_at.get(i)
            state = "off" if not self.rows[i].on else "skip" if text["why"] else "done" if at is not None else "wait"
            shown = None # the roast time it fired, from Charge (before it, the rule says enough)
            if at is not None and charge_s is not None and at >= charge_s:
                shown = _clock(at - charge_s)
            rows.append({"n": i + 1, "state": state, "fired": at is not None, "at": shown, **text})
        return {"name": self.name, "total": len(self.rows), "fired": len(self.fired_at), "rows": rows,
                "recent": [r for r in self.recent if now - r["at"] < TOAST_S], "message": self.message}


def _ambient_commands(text: str) -> list[int]:
    """The probe's command codes for `CAL1,START` and the like (unknown words are left out, as on the desktop)."""
    return [AMBIENT_COMMANDS[word] for word in (part.strip().upper() for part in text.split(","))
            if word in AMBIENT_COMMANDS]


def _extractor_commands(text: str) -> list[tuple[str, str]]:
    """The AirWave subcommands the tablet runs (the desktop's grammar: `MODE FAN,FAN 30`, `POWER OFF`)."""
    commands = []
    for part in text.split("#")[0].replace(";", ",").split(","):
        words = part.strip().upper().split()
        if len(words) != 2:
            continue
        verb, argument = words
        if verb.startswith("FAN") and argument.isdigit() and EXTRACTOR_SPEED[0] <= int(argument) <= EXTRACTOR_SPEED[1]:
            commands.append(("speed", argument))
        elif verb.startswith("MODE") and argument in ("STD", "EXT", "FAN"):
            commands.append(("mode", argument))
        elif verb.startswith("POWER") and argument in ("ON", "OFF"):
            commands.append(("power", argument.lower()))
    return commands

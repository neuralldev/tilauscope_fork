# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A machine's Artisan setup (.aset, Qt's INI format), read into named entries.

What the tablet takes from it (android/MACHINE-SPEC.md steps A and A0): the RoR
settings, the command sent at each milestone and at the ON, OFF, START and RESET
buttons, the command and range of each lever (the sliders), and the extra event
buttons an alarm can press (android/ALARM-SPEC.md).
Artisan keeps the commands by position in parallel lists; here they are named, so
nothing downstream depends on a position. Only IO commands written
`skywalker(<command>)` are kept as commands; any other action is listed in
`unsupported`, never guessed.

The RoR limits stay Artisan's defaults: the Skywalker presets carry none, and a
preset does not say in which unit they would be written.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from tilaucore.artisan_compat import RoRSettings

# Artisan's DefaultButtons, by position (canvas.py: buttonactions; extra and xextra buttons).
MILESTONES = ("charge", "dry_end", "first_crack", "first_crack_end", "second_crack", "second_crack_end", "drop", "cool_end")
EXTRA_BUTTONS = ("on", "off", "sample")
XEXTRA_BUTTONS = ("reset", "start")
# Artisan's sliders, by position: its four event types (canvas.py etypesdefault: Air, Drum, Damper, Burner).
LEVERS = ("air", "drum", "extractor", "burner")
IO_COMMAND = 5  # the action's index in Artisan's button action list ("IO Command")
EXTRA_IO_COMMAND = 6  # the same action in the extra event buttons' own list
_SKYWALKER = re.compile(r"^skywalker\((.*)\)$")


@dataclass(frozen=True)
class MachineSetup:
    """What a machine's Artisan setup says, by name."""
    ror: RoRSettings
    on_milestone: dict[str, list[str]] = field(default_factory=dict)  # milestone -> roaster commands, in order
    on_button: dict[str, list[str]] = field(default_factory=dict)     # on, off, sample, reset, start -> commands
    unsupported: dict[str, str] = field(default_factory=dict)         # name -> the action as written, not sent
    levers: dict[str, "Lever"] = field(default_factory=dict)          # air, drum, extractor, burner -> its command
    event_buttons: tuple["EventButton", ...] = ()                     # the extra event buttons, in Artisan's order


@dataclass(frozen=True)
class Lever:
    """A slider's roaster command (`OT1,{}`: `{}` takes the value) and its range."""
    command: str
    minimum: int
    maximum: int

    def command_for(self, value: int) -> str:
        """The command for `value`, clamped to the range, as the whole number the firmware wants."""
        return self.command.format(int(max(self.minimum, min(self.maximum, round(value)))))


@dataclass(frozen=True)
class EventButton:
    """An extra event button: its event type, its value (Artisan's internal one) and its IO command.

    Types 0-3 set a lever (air, drum, extractor, burner) to the value, 5-8 move it by the
    value, 10-13 by that percentage of it; 4 records nothing, 9 an untyped event. `command`
    is the `skywalker(…)` command inside (with `{}` for the value), None for any other action.
    """
    kind: int
    value: float
    command: str | None


def _unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _values(raw: str) -> list[str]:
    """A Qt INI value as its list of strings: split on commas outside quotes, quotes removed."""
    parts, current, quoted, i = [], [], False, 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            current.append(raw[i:i + 2])
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif c == "," and not quoted:
            parts.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    parts.append("".join(current))
    return [_unescape(p.strip()) for p in parts]


def parse_ini(text: str) -> dict[str, dict[str, str]]:
    """Sections of a Qt INI text, each a dict of raw values; [General] holds the top-level keys."""
    sections: dict[str, dict[str, str]] = {}
    current = sections.setdefault("General", {})
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        elif "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
    return sections


def _bool(value: str | None, default: bool) -> bool:
    return default if value is None else value.strip().lower() == "true"


def _int(value: str | None, default: int) -> int:
    try:
        return int(float(value)) if value is not None else default
    except ValueError:
        return default


def _commands(names: tuple[str, ...], kinds: str | None, actions: str | None,
              found: dict[str, list[str]], unsupported: dict[str, str]) -> None:
    if not kinds or actions is None:
        return
    for name, kind, action in zip(names, _values(kinds), _values(actions)):
        if not action:
            continue
        match = _SKYWALKER.match(action) if _int(kind, 0) == IO_COMMAND else None
        if match is None:
            unsupported[name] = action
            continue
        # An IO command may hold several, separated by ';'
        found[name] = [part.strip() for part in match.group(1).split(";") if part.strip()]


def read_setup(text: str) -> MachineSetup:
    """The named entries of an .aset's text."""
    ini = parse_ini(text)
    general, roc, buttons = ini.get("General", {}), ini.get("RoC", {}), ini.get("DefaultButtons", {})
    defaults = RoRSettings()
    span = _int(roc.get("DeltaSpan"), 0)
    ror = dataclasses.replace(
        defaults,
        curvefilter=_int(general.get("curvefilter"), defaults.curvefilter),
        interpolate_drops=_bool(general.get("interpolateDropsflag"), defaults.interpolate_drops),
        delta_span_s=float(span) if span > 0 else defaults.delta_span_s,
        delta_filter=_int(roc.get("deltafilter"), defaults.delta_filter),
        filter_dropouts=_bool(general.get("filterDropOuts"), defaults.filter_dropouts))
    on_milestone: dict[str, list[str]] = {}
    on_button: dict[str, list[str]] = {}
    unsupported: dict[str, str] = {}
    _commands(MILESTONES, buttons.get("buttonactions"), buttons.get("buttonactionstrings"), on_milestone, unsupported)
    _commands(EXTRA_BUTTONS, buttons.get("extrabuttonactions"), buttons.get("extrabuttonactionstrings"), on_button, unsupported)
    _commands(XEXTRA_BUTTONS, buttons.get("xextrabuttonactions"), buttons.get("xextrabuttonactionstrings"), on_button, unsupported)
    sliders = ini.get("Sliders", {})
    levers: dict[str, Lever] = {}
    if "slidercommands" in sliders:
        lows, highs = _values(sliders.get("slidermin", "")), _values(sliders.get("slidermax", ""))
        for i, (name, action) in enumerate(zip(LEVERS, _values(sliders["slidercommands"]))):
            match = _SKYWALKER.match(action)
            if match is None:
                if action:
                    unsupported[f"lever_{name}"] = action
                continue
            low = _int(lows[i] if i < len(lows) else None, 0)
            levers[name] = Lever(match.group(1), low, _int(highs[i] if i < len(highs) else None, 100))
    extra = ini.get("ExtraEventButtons", {})
    buttons = []
    if "extraeventstypes" in extra:
        kinds, values = _values(extra["extraeventstypes"]), _values(extra.get("extraeventsvalues", ""))
        actions, strings = _values(extra.get("extraeventsactions", "")), _values(extra.get("extraeventsactionstrings", ""))
        for i, kind in enumerate(kinds):
            match = _SKYWALKER.match(strings[i]) if i < len(strings) else None
            is_io = i < len(actions) and _int(actions[i], -1) == EXTRA_IO_COMMAND
            try:
                value = float(values[i]) if i < len(values) else 0.0
            except ValueError:
                value = 0.0
            buttons.append(EventButton(_int(kind, 4), value, match.group(1) if is_io and match else None))
    return MachineSetup(ror=ror, on_milestone=on_milestone, on_button=on_button, unsupported=unsupported,
                        levers=levers, event_buttons=tuple(buttons))

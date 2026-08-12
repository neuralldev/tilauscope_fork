# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Pure attribution of recorded slider events for guidance replay.

The doctrine is intentionally binary: a slider event is automatic only when it
is proven by the persisted alarm table; every other recorded slider event is
manual. This module knows neither Qt nor Artisan runtime objects.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from tilauscope.guidance_observer import ActionSource

_ALARM_SLIDER = re.compile(r'A(\d+) \(S(\d+)\)')


@dataclass(frozen=True)
class RecordedAction:
    at_s: float
    lever: int
    value: float
    source: ActionSource


@dataclass(frozen=True)
class AlarmAutomationMatch:
    alarm_number: int
    lever: int
    command_pct: float


def match_alarm_automation(
    *, label: str, lever: int, stored_value: float,
    flags: list[Any], actions: list[Any], commands: list[Any],
) -> AlarmAutomationMatch | None:
    """Prove that one stored event was emitted by an enabled slider alarm."""
    match = _ALARM_SLIDER.fullmatch(label)
    if match is None:
        return None
    alarm_idx = int(match.group(1)) - 1
    alarm_lever = int(match.group(2))
    try:
        if not (0 <= alarm_idx < len(flags)
                and alarm_idx < len(actions)
                and alarm_idx < len(commands)
                and bool(flags[alarm_idx])
                and alarm_lever == int(lever)
                and int(actions[alarm_idx]) == alarm_lever + 3):
            return None
        command = int(str(commands[alarm_idx]).split('#', 1)[0].strip())
        value = float(stored_value)
    except (TypeError, ValueError):
        return None
    # Artisan stores a slider command N as (N + 10) / 10 in special events.
    if abs(value - (command + 10.0) / 10.0) <= 0.11:
        return AlarmAutomationMatch(alarm_idx + 1, alarm_lever, float(command))
    return None


def recorded_actions(profile: dict[str, Any]) -> tuple[RecordedAction, ...]:
    """Classify in-roast slider changes using the persisted alarm contract."""
    timex = profile.get('timex') or []
    timeindex = profile.get('timeindex') or []
    if not timex or not timeindex:
        return ()
    try:
        charge_idx = int(timeindex[0])
        drop_idx = int(timeindex[6]) if len(timeindex) > 6 else len(timex) - 1
    except (TypeError, ValueError):
        return ()
    if not (0 <= charge_idx < len(timex)):
        return ()
    charge_s = float(timex[charge_idx])
    indexes = profile.get('specialevents') or []
    levers = profile.get('specialeventstype') or []
    values = profile.get('specialeventsvalue') or []
    labels = profile.get('specialeventsStrings') or []
    result: list[RecordedAction] = []
    previous: dict[int, tuple[float, ActionSource]] = {}
    for pos, (raw_idx, raw_lever, raw_value) in enumerate(
            zip(indexes, levers, values, strict=False)):
        try:
            idx, lever, value = int(raw_idx), int(raw_lever), float(raw_value)
        except (TypeError, ValueError):
            continue
        if not (charge_idx <= idx <= drop_idx and idx < len(timex)
                and 0 <= lever <= 3 and math.isfinite(value)):
            continue
        label = str(labels[pos]).strip() if pos < len(labels) else ''
        alarm = match_alarm_automation(
            label=label, lever=lever, stored_value=value,
            flags=profile.get('alarmflag') or [],
            actions=profile.get('alarmaction') or [],
            commands=profile.get('alarmstrings') or [])
        source = (ActionSource.ALARM_AUTOMATION
                  if alarm is not None else ActionSource.OPERATOR)
        signature = (value, source)
        if previous.get(lever) == signature:
            continue
        previous[lever] = signature
        result.append(RecordedAction(
            float(timex[idx]) - charge_s, lever, value, source))
    return tuple(result)

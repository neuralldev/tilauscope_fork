# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Tablet configuration: machine, its Bluetooth link, accessories, lever names and steps,
and who keeps the green coffee stock (this tablet, or a computer).

Colours are never configured: they come from the theme.
"""

import json
import os
from pathlib import Path
import tempfile

from tilaucore.roast_colour import AGTRON_SCALES
from tilaucore.roast_plan import ROAST_DESTINATION_KEYS

from . import mqtt
from .catalogue import DEVICES, MACHINES

DEFAULT_STEP = 5
CAVE_OWNERS = ("tablet", "computer")
AUTO_MILESTONES = ("charge", "dry_end", "first_crack", "drop")
AUTO_DEFAULT = ["charge", "dry_end", "first_crack"] # the Drop stays the operator's own gesture
LEVER_NAMES = {"burner": "Burner", "air": "Air", "drum": "Drum", "extractor": "Extractor"}
MAX_NAME = 24


def default() -> dict:
    return {"schema_version": 1, "machine": None, "roaster": None, "devices": {},
            "levers": {key: {"name": name, "step": DEFAULT_STEP} for key, name in LEVER_NAMES.items()},
            "operator": "", "unit": "C", "cave_owner": "tablet", "currency": "", # "" = the system currency, as on the desktop
            "plan_level": "", "roast_destination": "omni", # no level until one is chosen; the desktop's default use
            "preheat_on": False, "preheat_input": "BT", # TilauPID at the start of the roast, and the probe it reads
            "alarm_list": None, # the alarm list every roast runs (ALARM-SPEC decision 8), None for none
            "auto_marks": list(AUTO_DEFAULT), # the milestones that mark themselves (AUTOMATION-SPEC D1)
            "charge_detection": True, # without a plan, Charge found from the bean probe, as the desktop's Auto CHARGE
            "dry_end_detection": False, # by hand: Dry end found from the bean probe
            "crack_detection": False, # TilauAmbient calibrates, then counts the cracks, every roast (decision 11)
            "mqtt": None} # the broker and its sensors (MQTT-SPEC), None for none


def _link(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("address"), str) or not value["address"]:
        raise ValueError("A Bluetooth link needs an address")
    return {"name": str(value.get("name") or ""), "address": value["address"]}


def validate(data: dict) -> dict:
    """A clean copy of data, or ValueError naming the first problem."""
    if not isinstance(data, dict):
        raise ValueError("Configuration must be an object")
    clean = default()
    machine = data.get("machine")
    if machine is not None and machine not in MACHINES:
        raise ValueError("Unknown machine")
    clean["machine"] = machine
    clean["roaster"] = None if data.get("roaster") is None else _link(data["roaster"])
    devices = data.get("devices") or {}
    if not isinstance(devices, dict) or any(key not in DEVICES for key in devices):
        raise ValueError("Unknown device")
    clean["devices"] = {key: {**_link(value), "enabled": bool(value.get("enabled", True))}
                        for key, value in devices.items()}
    for key, lever in (data.get("levers") or {}).items():
        if key not in LEVER_NAMES or not isinstance(lever, dict):
            raise ValueError("Unknown lever")
        step = lever.get("step", DEFAULT_STEP)
        if type(step) is not int or not 1 <= step <= 25:
            raise ValueError("A step is a whole percentage from 1 to 25")
        name = LEVER_NAMES[key]
        if key == "extractor": # the only free name: it is a separate device
            name = str(lever.get("name") or "").strip()[:MAX_NAME] or LEVER_NAMES[key]
        clean["levers"][key] = {"name": name, "step": step}
    clean["operator"] = str(data.get("operator") or "").strip()[:40]
    if data.get("unit", "C") not in ("C", "F"):
        raise ValueError("The temperature unit is C or F")
    clean["unit"] = data.get("unit", "C") # shown and typed only: the tablet keeps °C (UNIT-SPEC)
    owner = data.get("cave_owner", "tablet")
    if owner not in CAVE_OWNERS:
        raise ValueError("The stock is kept by this tablet or by a computer")
    clean["cave_owner"] = owner
    currency = data.get("currency") or ""
    if currency and not (isinstance(currency, str) and len(currency) == 3 and currency.isascii() and currency.isupper()):
        raise ValueError("A currency is an ISO code such as EUR")
    clean["currency"] = currency
    level = data.get("plan_level") or ""
    if level and level not in {scale.name for scale in AGTRON_SCALES}:
        raise ValueError("Unknown roast level")
    clean["plan_level"] = level
    destination = data.get("roast_destination") or "omni"
    if destination not in ROAST_DESTINATION_KEYS:
        raise ValueError("Unknown use of the coffee")
    clean["roast_destination"] = destination
    clean["preheat_on"] = bool(data.get("preheat_on", False))
    probe = data.get("preheat_input") or "BT"
    if probe not in ("BT", "ET"):
        raise ValueError("The preheat reads BT or ET")
    clean["preheat_input"] = probe
    alarm_list = data.get("alarm_list")
    if alarm_list is not None and not (isinstance(alarm_list, str) and 0 < len(alarm_list) <= 60):
        raise ValueError("An alarm list is named")
    clean["alarm_list"] = alarm_list
    auto = data.get("auto_marks", AUTO_DEFAULT)
    if not isinstance(auto, list) or any(m not in AUTO_MILESTONES for m in auto):
        raise ValueError("Unknown milestone")
    clean["auto_marks"] = [m for m in AUTO_MILESTONES if m in auto]
    clean["charge_detection"] = bool(data.get("charge_detection", True))
    clean["dry_end_detection"] = bool(data.get("dry_end_detection", False))
    clean["crack_detection"] = bool(data.get("crack_detection", False))
    clean["mqtt"] = None if data.get("mqtt") is None else mqtt.validate(data["mqtt"])
    return clean


def levers(config: dict) -> dict:
    """The levers shown on the roast screen: the machine's own, plus an enabled extractor."""
    keys = list(MACHINES[config["machine"]]["levers"]) if config["machine"] else ["burner", "air", "drum"]
    extractor = config["devices"].get("extractor")
    if config["machine"] is None or (extractor and extractor["enabled"]):
        keys.append("extractor")
    return {key: config["levers"][key] for key in keys}


def load(path: str) -> dict | None:
    """The saved configuration, or None before the first setup."""
    target = Path(path)
    if not target.exists():
        return None
    return validate(json.loads(target.read_text(encoding="utf-8")))


def save(path: str, data: dict) -> dict:
    clean = validate(data)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".config-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(clean, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return clean

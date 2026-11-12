# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Machines and Bluetooth devices the tablet can recognise.

Copied, not imported, from the desktop sources: roasters.json (machines, links,
ble_prefix), devices.py _resolve_prefixes, scales/colormeters registries and
onboarding._KNOWN_BLE_SIGNATURES. Keep them in step by hand.
"""

from tilaucore import display_colours
from tilaucore.currency import CURRENCIES
from tilaucore import storage_advisor

# Machines reachable over Bluetooth, with the levers they expose.
MACHINES = {
    "skywalker-v2": {"manufacturer": "Skywalker", "model": "V2", "link": "Bluetooth",
                     "prefixes": ["TD5325A"], "levers": ["burner", "air", "drum"],
                     "stop": ["OFF"], # stops burner, air and drum (link test 2026-10-13)
                     # Cooled first: the .aset's cooling button, then its levers as roasters.json sets them.
                     "cool": ["CLDN,ON"], "lever_commands": {"burner": "OT1", "air": "OT2", "drum": "OT3"}},
    "skywalker-v1": {"manufacturer": "Skywalker", "model": "V1", "link": "Bluetooth · Skycommand",
                     "prefixes": ["ESP32_Skycommand_BLE"], "levers": ["burner", "air"],
                     "stop": [], "cool": [], "lever_commands": {}}, # its stop and cooling are not known yet
}

# Shown greyed in the machine step, with the reason.
UNAVAILABLE = [
    ("Santoker X3", "Bluetooth name not known yet"),
    ("Kaleido M1 Pro", "network · later"), ("Kaleido M2 Pro", "network · later"),
    ("Kaleido M6 Pro", "network · later"), ("Kaleido M10 Pro", "network · later"),
    ("Aillio Bullet R1 V2", "USB only"), ("Cormorant CR600e", "USB only"),
    ("Cormorant CR600g", "USB only"), ("Cormorant CR1200e", "USB only"),
    ("Hottop KN-8828B-2K+", "USB only"), ("Skywalker V1 Beast", "USB only"),
    ("IKAWA Pro V3", "not supported yet"), ("Smola BC150", "not supported yet"),
    ("Smola BC300 Pro", "not supported yet"),
]

# Accessories, matched by advertised name prefix or by service UUID.
DEVICES = {
    "extractor": {"label": "AirWave extractor", "prefixes": ["AirWave "],
                  "uuids": ["000000e3-0000-1000-8000-00805f9b34fb"]}, # difluid.AirwaveUUID
    "ambient": {"label": "TilauAmbient", "prefixes": ["TLSCAM"], "uuids": []},
    "scale": {"label": "Scale", "uuids": ["00000ffe-0000-1000-8000-00805f9b34fb"],
              "prefixes": ["ACAIAS-P", "ACAIA", "LUNAR-", "PROCHBT", "PEARLS", "PEARL-", "CINCO",
                           "PYXIS", "UMBRA", "COSMO-10", "COSMO-100", "Decent Scale", "BOOKOO_SC"]},
    "colour": {"label": "Colour meter", "prefixes": ["RoastSee C1"],
               "uuids": ["000000e0-0000-1000-8000-00805f9b34fb"]},
    "water": {"label": "Water activity meter", "prefixes": ["RoastSee AquaGauge"], "uuids": []},
    "printer": {"label": "Label printer", "prefixes": ["B21"], "uuids": []},
}

# Recognised by name only, never used: "also nearby".
OTHERS = [
    ("Santoker (Cube)", "SANTOKER", "6e400001-b5a3-f393-e0a9-e50e24dcca9e"),
    ("Santoker R", "Santoker", "0000fff0-0000-1000-8000-00805f9b34fb"),
    ("IKAWA", "IKAWA", "c92a6046-6c8d-4116-9d1d-d20a8f6a245f"),
    ("ColorTrack", "ColorTrack", "713d0000-503e-4c75-ba94-3148f18d941e"),
    ("BlueDOT", "BlueDOT", None),
    ("Lebrew RoastSeeNEXT", "RoastSeeNEXT", "000000bb-0000-1000-8000-00805f9b34fb"),
]


def _hit(name: str, uuids: list[str], prefixes: list[str], wanted: list[str]) -> bool:
    folded = name.casefold()
    return (any(folded.startswith(p.casefold()) for p in prefixes)
            or any(u.casefold() in wanted for u in uuids))


def classify(name: str | None, uuids: list[str] | None = None) -> tuple[str, str] | None:
    """('machine'|'device'|'other', key) for an advertisement, or None."""
    name, uuids = name or "", [u.casefold() for u in (uuids or [])]
    for key, machine in MACHINES.items():
        if _hit(name, [], machine["prefixes"], []):
            return "machine", key
    for key, device in DEVICES.items():
        if _hit(name, uuids, device["prefixes"], [u.casefold() for u in device["uuids"]]):
            return "device", key
    for label, prefix, uuid in OTHERS:
        if _hit(name, uuids, [prefix], [uuid.casefold()] if uuid else []):
            return "other", label
    return None


def export() -> dict:
    aw = storage_advisor.DEFAULT_THRESHOLDS # the desktop's storage zones, from the shared library
    return {"machines": MACHINES, "unavailable": [list(u) for u in UNAVAILABLE],
            "devices": {k: {"label": d["label"]} for k, d in DEVICES.items()},
            "aw_zones": {"dry": aw.dry, "warn": aw.warn, "risk": aw.risk},
            "currencies": CURRENCIES,
            "colours": {"grain": display_colours.COLOR_GRAIN, "air": display_colours.COLOR_AIR,
                        "grain_rise": display_colours.COLOR_GRAIN_RISE, "air_rise": display_colours.COLOR_AIR_RISE,
                        "levers": display_colours.LEVER_COLOURS}}

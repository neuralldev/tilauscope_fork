# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The machine's Artisan setup on the tablet (MACHINE-SPEC step A): its RoR settings and the
commands its milestones and buttons send, read from the .aset that roasters.json names for
its Bluetooth link.

The .aset files are packaged into `machine_setups` at build time from src/includes/Machines
(app/build.gradle.kts); a development checkout reads them from there.
"""

import pkgutil
from functools import lru_cache
from pathlib import Path

from tilaucore.artisan_setup import MachineSetup, read_setup
from tilaucore.roasters import CoolingSettings, RoasterManager

from .catalogue import MACHINES

_CHECKOUT = Path(__file__).resolve().parents[3] / "src" / "includes" / "Machines"


def _text(preset: str) -> str:
    try:
        data = pkgutil.get_data("machine_setups", preset)
    except (ImportError, OSError):
        data = None
    return data.decode("utf-8") if data is not None else (_CHECKOUT / preset).read_text(encoding="utf-8")


@lru_cache(maxsize=4)
def setup(machine: str) -> MachineSetup:
    """The Artisan setup of a catalogue machine, as its Bluetooth link loads it on the desktop."""
    entry = MACHINES[machine]
    roaster = RoasterManager().get_by_name(entry["manufacturer"], entry["model"])
    preset = next(s.preset for s in roaster.artisan_setups if s.link == "bluetooth")
    return read_setup(_text(preset))


@lru_cache(maxsize=4)
def bt_offsets(machine: str) -> tuple[float, ...]:
    """The roaster's bean probe deviation at Charge, Dry end, First crack and Drop (roasters.json), °C."""
    entry = MACHINES[machine]
    return tuple(RoasterManager().get_by_name(entry["manufacturer"], entry["model"]).bean_temperature_offset_c)


@lru_cache(maxsize=4)
def drop_detection(machine: str) -> tuple[float | None, float | None]:
    """The roaster's auto DROP values (roasters.json drop_fall_c, drop_probe_lag_s); None: the shared default."""
    entry = MACHINES[machine]
    roaster = RoasterManager().get_by_name(entry["manufacturer"], entry["model"])
    return roaster.drop_fall_c, roaster.drop_probe_lag_s


COOL_UNTIL = "UNTIL_BT_BELOW" # pseudo-command for the link: wait for the bean probe under the value (°C)


def cooling(machine: str) -> CoolingSettings | None:
    """The roaster's cooling (roasters.json): its levers at the end of the roast and where it ends."""
    entry = MACHINES[machine]
    return RoasterManager().get_by_name(entry["manufacturer"], entry["model"]).cooling


def end_roast(machine: str) -> list[str]:
    """End roast: burner off and the roaster cooled first, then its stop (operator, 2026-10-16).

    The burner as the roaster's cooling sets it, its cooling button, then its air and drum, until
    the bean probe is under the cooling's end (roasters.json); then the setup's COOL END (the
    tablet has no such milestone: its end roast is the desktop's Cool end, operator 2026-10-24),
    its OFF button and the roaster's own stop. The link runs the wait on the real readings, and
    never stops on a guess: no reading, no stop. A roaster with no cooling declared is stopped at once.
    """
    entry, machine_setup, settings = MACHINES[machine], setup(machine), cooling(machine)
    heads, cool = entry["lever_commands"], []
    if settings is not None and settings.end_below_c is not None and "burner" in heads:
        levers = [f"{heads[lever]},{pct:g}" for lever, pct in (("air", settings.air_pct), ("drum", settings.drum_pct))
                  if pct is not None and lever in heads]
        cool = [f"{heads['burner']},{settings.burner_pct:g}", *entry["cool"], *levers,
                f"{COOL_UNTIL},{settings.end_below_c:g}"]
    return cool + machine_setup.on_milestone.get("cool_end", []) + machine_setup.on_button.get("off", []) + entry["stop"]

# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# Tilau 2025-2026

"""Roast tastings, and the one change a tasting asks of the next roast of the same coffee.

Qt-free; reads/writes `tastings.json` (sidecar of `beancave.json`) keyed by the
roast's Artisan roastUUID, so it survives Artisan re-saving the .alog.
"""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
from typing import Final

from tilaucore.beans import RoastTasting, TastingLog, from_json, to_json

_log = logging.getLogger(__name__)
_ENCODING = "utf-8-sig" if platform.system() == "Windows" else "utf-8"

TASTINGS_FILE_NAME: Final[str] = "tastings.json"

# Defect → the one change the next plan of the same coffee makes, in priority
# order: with several defects ticked, the first listed wins. One burner notch is
# 5 %; temperatures in °C; development in seconds. Cross-roast only — nothing
# here acts during a roast.
DEFECT_CHANGES: Final[dict[str, tuple[str, float]]] = {
    'burnt':  ('charge_c', -3.0),
    'bitter': ('burner_before_fc_pct', -5.0),
    'flat':   ('burner_before_fc_pct', 5.0),
    'bready': ('burner_start_pct', 5.0),
    'grassy': ('development_s', 20.0),
    'sour':   ('drop_c', 2.0),
}


def QT_TRANSLATE_NOOP(context: str, text: str) -> tuple[str, str]:  # noqa: N802  (the name the tools look for)
    """Marks a text for the desktop's translation tools; it is translated on display."""
    return context, text


# What the operator tastes, in the order of DEFECT_CHANGES, and the verdicts with their thumb.
DEFECT_WORDS: Final[dict[str, tuple[str, str]]] = {
    'burnt': QT_TRANSLATE_NOOP("tilauscope_beancave", "Burnt"),
    'bitter': QT_TRANSLATE_NOOP("tilauscope_beancave", "Bitter, smoky"),
    'flat': QT_TRANSLATE_NOOP("tilauscope_beancave", "Flat, papery"),
    'bready': QT_TRANSLATE_NOOP("tilauscope_beancave", "Bready, dull"),
    'grassy': QT_TRANSLATE_NOOP("tilauscope_beancave", "Grassy, raw"),
    'sour': QT_TRANSLATE_NOOP("tilauscope_beancave", "Sour, thin"),
}
# The change a defect asks of the next roast, and why; {0} is a temperature step.
CHANGE_WORDS: Final[dict[str, tuple[tuple[str, str], tuple[str, str]]]] = {
    'burnt': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Charge {0} cooler"),
              QT_TRANSLATE_NOOP("tilauscope_beancave", "Burnt usually means the beans met too much heat at the start.")),
    'bitter': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Burner one notch lower before first crack"),
               QT_TRANSLATE_NOOP("tilauscope_beancave", "Bitter, smoky usually means too much heat at the end.")),
    'flat': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Burner one notch higher before first crack"),
             QT_TRANSLATE_NOOP("tilauscope_beancave", "Flat, papery usually means too little heat reaching first crack.")),
    'bready': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Start with the burner one notch higher"),
               QT_TRANSLATE_NOOP("tilauscope_beancave", "Bready, dull usually means the roast dragged for lack of heat.")),
    'grassy': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Let it develop 20 s longer after first crack"),
               QT_TRANSLATE_NOOP("tilauscope_beancave", "Grassy, raw usually means the roast ended too soon after first crack.")),
    'sour': (QT_TRANSLATE_NOOP("tilauscope_beancave", "Drop {0} later"),
             QT_TRANSLATE_NOOP("tilauscope_beancave", "Sour, thin usually means the beans needed a little more development.")),
}


# The "Next time" answer when no defect asks for a change.
NEXT_SAME: Final[tuple[tuple[str, str], tuple[str, str]]] = (
    QT_TRANSLATE_NOOP("tilauscope_beancave", "Nothing to change"),
    QT_TRANSLATE_NOOP("tilauscope_beancave", "Roast it the same way next time."))
NEXT_TICK: Final[tuple[tuple[str, str], tuple[str, str]]] = (
    QT_TRANSLATE_NOOP("tilauscope_beancave", "Tick what was off"),
    QT_TRANSLATE_NOOP("tilauscope_beancave", "It tells the next roast what to change."))


def degrees(delta_c: float, mode: str) -> str:
    return f"{abs(delta_c) * 1.8:.0f} °F" if mode == 'F' else f"{abs(delta_c):.0f} °C"


def change_text(defect: str, mode: str, translate) -> tuple[str, str]:  # noqa: ANN001  (text pair -> str)
    """(the change for next time, why) for a defect, through the caller's translation."""
    change, why = CHANGE_WORDS[defect]
    return translate(change).format(degrees(DEFECT_CHANGES[defect][1], mode)), translate(why)


VERDICT_WORDS: Final[dict[str, tuple[str, tuple[str, str]]]] = {
    'yes': ("👍", QT_TRANSLATE_NOOP("HelpDlg", "Yes")),
    'almost': ("🤏", QT_TRANSLATE_NOOP("tilauscope_beancave", "Almost")),
    'no': ("👎", QT_TRANSLATE_NOOP("tilauscope_beancave", "No")),
}


def next_change(tasting: RoastTasting | None) -> tuple[str, str, float] | None:
    """(defect, lever, delta) this tasting asks of the next roast, or None."""
    if tasting is None:
        return None
    for defect, (lever, delta) in DEFECT_CHANGES.items():
        if defect in tasting.defects:
            return defect, lever, delta
    return None


def log_path(directory) -> Path | None:
    """Where the tastings live, or None if no bean library directory is set."""
    if not directory:
        return None
    try:
        p = Path(directory).expanduser()
    except (TypeError, ValueError):
        return None
    if str(p) in ("", "."):
        return None
    return p / TASTINGS_FILE_NAME


def load(directory) -> TastingLog:
    """Read the tastings. A missing or unreadable file yields an empty log; never raises."""
    path = log_path(directory)
    if path is None or not path.exists():
        return TastingLog()
    try:
        return from_json(TastingLog, path.read_text(encoding=_ENCODING))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Tastings: %s unreadable (%s); starting empty", path, exc)
        return TastingLog()


def record(directory, roast_uuid: str, tasting: RoastTasting) -> bool:
    """Store (or replace) one roast's tasting. True only if it reached the disk.

    Re-reads before writing, and refuses to write over a file it cannot read.
    """
    path = log_path(directory)
    if path is None or not roast_uuid:
        return False
    if path.exists():
        try:
            log = from_json(TastingLog, path.read_text(encoding=_ENCODING))
        except Exception:  # noqa: BLE001
            _log.error("Tastings: %s unreadable; tasting not recorded over it", path)
            return False
    else:
        log = TastingLog()
    log.entries[roast_uuid] = tasting
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(to_json(log), encoding=_ENCODING)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        _log.error("Tastings: writing %s failed: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False

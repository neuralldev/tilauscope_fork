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

from tilauscope.tilauscope_types import RoastTasting, TastingLog

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
        return TastingLog.from_json(path.read_text(encoding=_ENCODING))
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
            log = TastingLog.from_json(path.read_text(encoding=_ENCODING))
        except Exception:  # noqa: BLE001
            _log.error("Tastings: %s unreadable; tasting not recorded over it", path)
            return False
    else:
        log = TastingLog()
    log.entries[roast_uuid] = tasting
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(log.to_json(), encoding=_ENCODING)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        _log.error("Tastings: writing %s failed: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False

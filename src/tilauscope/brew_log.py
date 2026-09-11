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

"""Brew journal — measured extractions, kept for later analysis.

Qt-free; reads/writes `brewlog.json` (sidecar of `beancave.json`, keyed by `GreenBean.uuid`) as raw per-brew rows, not running averages, so grind→flow relationships stay analyzable. Diagnostic only, never feeds back into a recipe.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from pathlib import Path
from typing import Optional

from tilauscope.tilauscope_types import BrewLog, BrewSample

_log = logging.getLogger(__name__)
_IS_WINDOWS = platform.system() == "Windows"

BREWLOG_FILE_NAME: str = "brewlog.json"

# Ring size per bean. Bounds the absolute worst case (33 beans x 50 x ~429 B
# is well under a megabyte) without ever biting in practice: a bean is finished long
# before fifty tasted brews. Measured 2026-07-21: beancave.json = 25.1 kB / 33 beans,
# one serialised sample = 429 B.
MAX_SAMPLES_PER_BEAN: int = 50

_ENCODING = "utf-8-sig" if _IS_WINDOWS else "utf-8"


def log_path(directory) -> Optional[Path]:
    """Where the journal lives, or None if no bean library directory is set.

    An unconfigured BeanCave holds `Path("")`, which pathlib turns into a truthy
    `PosixPath('.')`; '' and '.' both mean "not configured here".
    """
    if not directory:
        return None
    try:
        p = Path(directory).expanduser()
    except (TypeError, ValueError):
        return None
    if str(p) in ("", "."):
        return None
    return p / BREWLOG_FILE_NAME


def load(directory) -> BrewLog:
    """Read the journal. A missing or unreadable file yields an empty log.

    Never raises: brewing must work whatever state this file is in.
    """
    path = log_path(directory)
    if path is None or not path.exists():
        return BrewLog()
    try:
        return BrewLog.from_json(path.read_text(encoding=_ENCODING))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Brew log: %s unreadable (%s); starting from an empty journal", path, exc)
        return BrewLog()


def save(directory, log: BrewLog) -> bool:
    """Write the journal. True only if it reached the disk.

    Written to a temporary file and moved into place: a crash mid-write must not
    truncate a journal that took months to fill.
    """
    path = log_path(directory)
    if path is None:
        _log.warning("Brew log: no bean library directory; journal kept in memory only")
        return False
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(log.to_json(), encoding=_ENCODING)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        _log.error("Brew log: writing %s failed: %s", path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def append(log: BrewLog, bean_uuid: str, sample: BrewSample) -> bool:
    """Add one sample to a bean's journal, dropping the oldest past the ring size.

    False when the bean carries no uuid — a normal state for a bean never linked to a
    roast, and not something to report as an error.
    """
    if not bean_uuid or sample is None:
        return False
    rows = log.entries.setdefault(str(bean_uuid), [])
    rows.append(sample)
    if len(rows) > MAX_SAMPLES_PER_BEAN:
        del rows[:len(rows) - MAX_SAMPLES_PER_BEAN]
    return True


def record(directory, bean_uuid: str, sample: BrewSample) -> bool:
    """Load, append, save. The whole write path for one measured extraction.

    Re-reads before writing so a journal changed elsewhere is not clobbered.
    """
    if not bean_uuid:
        return False
    log = load(directory)
    if not append(log, bean_uuid, sample):
        return False
    return save(directory, log)


def samples_for(log: BrewLog, bean_uuid: str,
                method_id: str = "") -> list[BrewSample]:
    """This bean's samples, oldest first, optionally for one brew method."""
    rows = log.entries.get(str(bean_uuid or ""), [])
    return [s for s in rows if not method_id or s.method_id == method_id]


def previous_sample(log: BrewLog, bean_uuid: str, method_id: str) -> Optional[BrewSample]:
    """The last extraction recorded for this bean on this method, if any."""
    rows = samples_for(log, bean_uuid, method_id)
    return rows[-1] if rows else None


def _selfcheck() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        assert load(d).entries == {}, "missing file must read as an empty journal"
        assert not load(None).entries, "no directory must read as an empty journal"

        # an unconfigured BeanCave must never scatter the journal into the CWD
        for unset in (None, "", ".", Path(""), Path(".")):
            assert log_path(unset) is None, f"{unset!r} must not resolve to a path"
        cwd_before = set(Path.cwd().glob("brewlog*"))
        assert not record(Path(""), "u0", BrewSample(method_id="V60")), \
            "an unconfigured directory must refuse to write"
        assert set(Path.cwd().glob("brewlog*")) == cwd_before, \
            "nothing may be written to the working directory"

        s1 = BrewSample(method_id="V60", grind_um=650, drawdown_s=65,
                        drawdown_valid=True, iso_date="2026-07-18")
        assert record(d, "u1", s1), "record must reach the disk"
        assert not record(d, "", s1), "a bean with no uuid is not journalled"

        log = load(d)
        assert len(samples_for(log, "u1")) == 1
        assert samples_for(log, "u1")[0].drawdown_s == 65, "round-trip must keep the value"
        assert previous_sample(log, "u1", "V60") is not None
        assert previous_sample(log, "u1", "ESPRESSO") is None, "methods must not mix"

        # ring: oldest falls out, order preserved, newest last
        for i in range(MAX_SAMPLES_PER_BEAN + 10):
            record(d, "u2", BrewSample(method_id="V60", grind_um=600 + i))
        rows = samples_for(load(d), "u2")
        assert len(rows) == MAX_SAMPLES_PER_BEAN, f"ring must cap at {MAX_SAMPLES_PER_BEAN}"
        assert rows[-1].grind_um == 600 + MAX_SAMPLES_PER_BEAN + 9, "newest must be last"
        assert rows[0].grind_um == 610, "oldest must have been dropped"
        assert len(samples_for(load(d), "u1")) == 1, "beans must not interfere"

        # a corrupt journal degrades to empty rather than breaking the brew
        (Path(d) / BREWLOG_FILE_NAME).write_text("{not json", encoding=_ENCODING)
        assert load(d).entries == {}, "corrupt file must read as an empty journal"

        # no .tmp left behind
        assert not list(Path(d).glob("*.tmp")), "temporary files must not survive"

    print("brew_log self-check: OK")


if __name__ == "__main__":
    _selfcheck()

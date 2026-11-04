# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""One writer at a time on a bean library.

TilauScope's BeanCave and BeanCave alone can point at the same library. Whichever
opens it first holds this lock; the other reads it and changes nothing. A program
that died leaves a lock the next one takes over (QLockFile checks its process).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QLockFile

#: Held for as long as the window is open: never stale by age, only by a dead process.
_HELD_FOR_MS = 7 * 24 * 3600 * 1000


class LibraryLock:
    """The lock of one library folder."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self._lock = QLockFile(str(self.folder / '.beancave.lock'))
        self._lock.setStaleLockTime(_HELD_FOR_MS)

    def acquire(self) -> bool:
        """True when this program now writes the library."""
        return self._lock.isLocked() or self._lock.tryLock(0)

    def release(self) -> None:
        if self._lock.isLocked():
            self._lock.unlock()

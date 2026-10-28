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

"""What every TilauScope archive (backup, coffee package) checks the same way. Qt-free."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final


class ArchiveError(Exception):
    """An archive that cannot be read. ``kind`` names the screen to show."""

    DAMAGED: Final[str] = "damaged"
    NEWER: Final[str] = "newer"

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind


def sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle)


def version_key(version: str, build: int) -> tuple[int, ...]:
    """4.3 build 41 → (4, 3, 0, 41): comparable, newest last; 4.3 and 4.3.0 are one version."""
    parts = [int(part) for part in re.findall(r"\d+", version)][:3]
    return (*parts, *[0] * (3 - len(parts)), int(build))


def member_path(base: Path, relative: str) -> Path:
    """The file a member lands on — never outside ``base`` (no ``..``, no absolute name)."""
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in ("..", "") or ":" in p or "\\" in p for p in parts):
        raise ArchiveError(ArchiveError.DAMAGED, f"unsafe name {relative}")
    return base.joinpath(*parts)

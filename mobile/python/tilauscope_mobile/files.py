# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Writing a file whole or not at all."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


def write_text_atomic(target: Path, text: str) -> None:
    """The file becomes `text`, or stays as it was: a write cut short (the app killed, the battery flat)
    never leaves it empty or half written."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.stem}-", delete=False, newline="") as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

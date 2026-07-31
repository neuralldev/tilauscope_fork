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
# TiLau 2026

"""Rewrite the golden snapshot. Run via `make golden`, then review the git diff.

This is the deliberate half of the loop: the test tells you something moved,
this tells the repository what it moved to. Never run it to make a red suite
green without reading the diff first — that is the one way a characterisation
corpus stops being worth anything.
"""

from __future__ import annotations

import json
import sys

import _guard

_guard.install()

import corpus_harness as H  # noqa: E402  # must follow the sandbox install
import corpus_snapshot as S  # noqa: E402


def main() -> int:
    snapshot = S.build()
    H.GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    H.GOLDEN_PATH.write_text(
        json.dumps(snapshot, indent=1, sort_keys=True, default=str) + '\n',
        encoding='utf-8',
    )
    size_kb = H.GOLDEN_PATH.stat().st_size // 1024
    print(f'wrote {H.GOLDEN_PATH} ({size_kb} KB)')
    print(f'  {len(snapshot["roasts"])} roasts, {len(snapshot["plans"])} scenarios')
    print('review the diff before committing: git diff -- src/test/golden/')
    return 0


if __name__ == '__main__':
    sys.exit(main())

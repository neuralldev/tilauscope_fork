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

"""Strip local filesystem paths from the committed roast fixtures.

The corpus ships in a public repository. A recorded roast carries whatever
absolute paths Artisan happened to store — background-profile references in
practice — and those spell out the developer's home directory and account name.
They are pure provenance noise: no field holding a path takes part in any
computation.

Editing is deliberately **minimal**. The file is not parsed and re-serialised —
that would rewrite two megabytes of float formatting for a fifty-character fix
and make the diff unreviewable. Only the offending path text is cut out of the
raw bytes, leaving `'backgroundpath': ''`. Every other byte is untouched, and
the result is verified to be structurally identical to the original except for
the values that were meant to change.

Run with `make sanitize-fixtures`; `test_fixtures_carry_no_local_paths` in the
fast suite is what stops a fresh fixture from reintroducing one.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any, Final

CORPUS_DIR: Final[Path] = Path(__file__).resolve().parent / 'fixtures' / 'corpus'

#: A string is a local path if it looks like an absolute filesystem location.
#: Deliberately broad — matching one path too many costs nothing here, since no
#: computation reads these fields, while missing one leaks a home directory.
LOCAL_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r'^(/(Users|home|Volumes|private|tmp|var)/|[A-Za-z]:[\\/])',
)


def find_local_paths(node: Any, trail: str = '') -> list[tuple[str, str]]:
    """Every (key trail, value) in a profile whose value is a local path."""
    if isinstance(node, str):
        return [(trail, node)] if LOCAL_PATH_RE.match(node) else []
    if isinstance(node, dict):
        found: list[tuple[str, str]] = []
        for key, value in node.items():
            found += find_local_paths(value, f'{trail}.{key}' if trail else str(key))
        return found
    if isinstance(node, (list, tuple)):
        found = []
        for item in node:
            found += find_local_paths(item, f'{trail}[]')
        return found
    return []


def sanitize_text(raw: str, paths: list[str]) -> str:
    """Cut each path out of the raw file text, leaving an empty string literal."""
    for path in paths:
        if path not in raw:
            raise ValueError(
                f'path {path!r} was parsed out of the profile but does not appear '
                'verbatim in the file text; refusing to guess at the encoding',
            )
        raw = raw.replace(path, '')
    return raw


def _strip_paths(node: Any) -> Any:
    """Same structure with every local-path string blanked, for comparison."""
    if isinstance(node, str):
        return '' if LOCAL_PATH_RE.match(node) else node
    if isinstance(node, dict):
        return {k: _strip_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strip_paths(v) for v in node]
    if isinstance(node, tuple):
        return tuple(_strip_paths(v) for v in node)
    return node


def sanitize_file(path: Path, *, dry_run: bool = False) -> list[tuple[str, str]]:
    """Sanitize one fixture in place. Returns what was removed."""
    raw = path.read_text(encoding='utf-8')
    profile = ast.literal_eval(raw)
    found = find_local_paths(profile)
    if not found:
        return []

    cleaned_raw = sanitize_text(raw, [value for _, value in found])
    cleaned = ast.literal_eval(cleaned_raw)

    # The only permitted difference is the blanked paths themselves. Anything
    # else means the textual edit clipped something it should not have.
    if cleaned != _strip_paths(profile):
        raise ValueError(
            f'{path.name}: sanitised profile differs from the original beyond the '
            'removed paths — aborting rather than corrupting a fixture',
        )
    if not dry_run:
        path.write_text(cleaned_raw, encoding='utf-8')
    return found


def main() -> int:
    dry_run = '--dry-run' in sys.argv
    total = 0
    for fixture in sorted(CORPUS_DIR.glob('*.alog')):
        removed = sanitize_file(fixture, dry_run=dry_run)
        for trail, value in removed:
            print(f'{fixture.name}\n    {trail} = {value}')
        total += len(removed)

    if total == 0:
        print(f'{CORPUS_DIR}: already clean, no local paths found')
    else:
        verb = 'would remove' if dry_run else 'removed'
        print(f'\n{verb} {total} local path(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

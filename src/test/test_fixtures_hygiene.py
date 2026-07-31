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

"""Hygiene of the committed roast fixtures.

The corpus is published under AGPL along with the rest of the fork, so a
recorded roast must not carry the machine it was recorded on. Artisan stores
absolute paths in a profile (background-profile references in practice), and
those spell out a home directory and an account name.

These checks are deliberately in the **fast** suite: they cost milliseconds and
they guard something that only ever goes wrong when someone drops a new fixture
in without thinking about it. A guard that runs only on demand is a guard that
will be missed exactly once.

Note the developer's account name is never written down here — it is read from
the environment at run time. Hard-coding it would publish the very string this
test exists to keep out of the repository.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import pytest
from sanitize_fixtures import CORPUS_DIR, find_local_paths, sanitize_file

CORPUS_FILES = sorted(CORPUS_DIR.glob('*.alog'))


def _local_identifiers() -> set[str]:
    """Strings that would identify this machine, gathered at run time."""
    names = {Path.home().name}
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001  # no controlling terminal, CI sandboxes
        pass
    return {n for n in names if n and len(n) > 2}


def test_the_corpus_is_not_empty() -> None:
    """Guard the guards: an empty glob would make every check below vacuous."""
    assert CORPUS_FILES, f'no fixtures found under {CORPUS_DIR}'


@pytest.mark.parametrize('fixture', CORPUS_FILES, ids=lambda p: p.name)
def test_fixtures_carry_no_local_paths(fixture: Path) -> None:
    """No profile field may hold an absolute filesystem path.

    Fix with `make sanitize-fixtures`, which blanks them in place without
    reserialising the file.
    """
    import ast

    found = find_local_paths(ast.literal_eval(fixture.read_text(encoding='utf-8')))
    assert not found, (
        f'{fixture.name} carries local path(s):\n'
        + '\n'.join(f'    {trail} = {value}' for trail, value in found)
        + '\n\nRun `make sanitize-fixtures` to strip them.'
    )


@pytest.mark.parametrize('fixture', CORPUS_FILES, ids=lambda p: p.name)
def test_fixtures_do_not_name_the_developer_machine(fixture: Path) -> None:
    """Belt and braces: the account name must not appear anywhere in the bytes.

    The path check above works on parsed values; this one reads the raw text, so
    it also catches a name embedded in free-text notes or a field the path
    pattern does not recognise.
    """
    raw = fixture.read_text(encoding='utf-8')
    leaked = sorted(name for name in _local_identifiers() if name in raw)
    assert not leaked, (
        f'{fixture.name} contains the local account name in {len(leaked)} form(s). '
        'Remove it before committing — this fixture is published.'
    )


def test_sanitizer_is_idempotent() -> None:
    """Running the sanitizer on a clean corpus must change nothing.

    If this ever fails the sanitizer is rewriting files it has already cleaned,
    which would churn the diff of a two-megabyte fixture on every run.
    """
    for fixture in CORPUS_FILES:
        assert sanitize_file(fixture, dry_run=True) == [], (
            f'{fixture.name} still reports paths to remove after sanitising'
        )

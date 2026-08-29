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

"""One pytest failure per BeanCave check, from a dialog built in a child process.

The building happens in ``beancave_child.py`` and for the reason written there:
importing Artisan into this process would make it the ArtisanViewer whenever the
developer has TilauScope open, and every later isolated test would then exit(0).
Here we only run that child once and report what it found.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator  # noqa: F401

CHILD: Final[Path] = Path(__file__).resolve().parent / 'beancave_child.py'
TIMEOUT_S: Final[int] = 300

#: Named here as well as in the child, so a check that stops running is a
#: failure rather than a silent gap.
EXPECTED_CHECKS: Final[frozenset[str]] = frozenset({
    'the_parameter_files_are_read',
    'opening_beancave_raises_no_dialog',
    'the_library_on_disk_reaches_the_table',
    'every_slice_reaches_qt',
    'a_second_folder_scan_replaces_the_first',
    'a_roast_appears_once_in_the_list',
    'a_rebuilt_list_never_leaves_the_viewer_on_its_placeholder',
    'the_list_lands_on_the_roast_open_in_tilauscope',
    'with_nothing_open_the_list_lands_on_the_latest_roast',
    'the_roast_left_selected_is_where_the_next_session_opens',
    'a_remembered_roast_that_is_gone_falls_back_to_the_latest',
    'what_was_selected_is_written_out_as_a_uuid',
})


@pytest.fixture(scope='module')
def child_results(sandbox: Path) -> dict[str, str | None]:
    """Open BeanCave once in a child and bring back every check's verdict.

    The child gets this session's sandbox path, so its Qt settings land in the
    same place and are verified there before it exits — the isolation is about
    which process imports Artisan, not about escaping the seal.
    """
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(CHILD), str(sandbox)],
        capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )
    if '---JSON---' not in proc.stdout:
        pytest.fail(
            f'the BeanCave child produced no results (exit {proc.returncode}).\n'
            f'--- stdout ---\n{proc.stdout[-2000:]}\n'
            f'--- stderr ---\n{proc.stderr[-2000:]}',
        )
    return json.loads(proc.stdout.split('---JSON---', 1)[1])


def test_the_child_ran_every_expected_check(
    child_results: dict[str, str | None],
) -> None:
    """Guard the guard: parametrising over nothing would pass silently."""
    found = set(child_results)
    assert found == EXPECTED_CHECKS, (
        f'missing from the run: {sorted(EXPECTED_CHECKS - found)}\n'
        f'unlisted in EXPECTED_CHECKS: {sorted(found - EXPECTED_CHECKS)}'
    )


@pytest.mark.parametrize('check', sorted(EXPECTED_CHECKS))
def test_beancave_check(check: str, child_results: dict[str, str | None]) -> None:
    """One BeanCave check, as run against a real dialog on a real folder."""
    failure = child_results.get(check, 'the child never ran this check')
    assert failure is None, f'{check} failed in the child process:\n{failure}'

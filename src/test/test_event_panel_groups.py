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

"""One pytest failure per check on the floating event-button bar.

The bar is built in ``event_panel_child.py`` and for the reason written there.
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
    from pathlib import Path as _Path  # noqa: F401

CHILD: Final[Path] = Path(__file__).resolve().parent / 'event_panel_child.py'
TIMEOUT_S: Final[int] = 180

#: Named here as well as in the child, so a check that stops running is a
#: failure rather than a silent gap.
EXPECTED_CHECKS: Final[frozenset[str]] = frozenset({
    'a_gap_splits_the_bar_into_two_welded_groups',
    'the_ends_of_a_group_are_the_only_rounded_corners',
    'a_row_boundary_is_a_break_the_width_cannot_undo',
    'the_weld_between_two_buttons_outweighs_the_block_outline',
    'the_block_is_centred_in_a_bar_wider_than_it_needs',
})


@pytest.fixture(scope='module')
def child_results(sandbox: Path) -> dict[str, str | None]:
    """Build the bar once in a child and bring back every check's verdict."""
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(CHILD), str(sandbox)],
        capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )
    if '---JSON---' not in proc.stdout:
        pytest.fail(
            f'the event-panel child produced no results (exit {proc.returncode}).\n'
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
def test_event_panel_check(check: str, child_results: dict[str, str | None]) -> None:
    """One bar check, as run against a real panel in a child process."""
    failure = child_results.get(check, 'the child never ran this check')
    assert failure is None, f'{check} failed in the child process:\n{failure}'

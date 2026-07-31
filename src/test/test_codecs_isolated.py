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

"""Surfaces the out-of-process codec checks as ordinary pytest results.

``codecs_child.py`` does the work in its own interpreter, for the reasons
written at the top of that file. This module launches it **once** and turns each
result into a test, so a broken frame layout shows up as one named failure
rather than as a wall of subprocess output attached to a single opaque test.

The list of check names is frozen here. Without it, a child that failed to start
would report nothing at all and parametrisation over an empty result set would
be silently green.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

CHILD: Final[Path] = Path(__file__).resolve().parent / 'codecs_child.py'
TIMEOUT_S: Final[float] = 180.0

#: Every check the child is expected to run. Frozen deliberately — see the
#: module docstring. Add a name here when adding one there.
EXPECTED_CHECKS: Final[frozenset[str]] = frozenset({
    'difluid_round_trip',
    'difluid_frame_layout',
    'difluid_rejects_a_bad_checksum',
    'difluid_rejects_a_truncated_message',
    'difluid_splits_a_stream_into_messages',
    'difluid_body_may_contain_the_preamble',
    'difluid_reads_the_temperature_that_used_to_be_lost',
    'difluid_framing_is_independent_of_body_content',
    'difluid_splits_a_stream_of_adversarial_frames',
    'difluid_skips_leading_noise',
    'difluid_drops_a_truncated_tail',
    'difluid_resyncs_after_a_corrupted_length',
    'ambient_frame_is_seventeen_bytes',
    'ambient_decodes_a_normal_reading',
    'ambient_temperature_is_signed',
    'ambient_rejects_a_bad_checksum',
    'ambient_rejects_wrong_header_or_footer',
    'ambient_rejects_a_short_frame',
    'ambient_gates_implausible_temperatures',
    'audio_frame_is_nine_bytes',
    'audio_counts_beyond_the_old_sixteen_bit_ceiling',
    'audio_rejects_a_bad_checksum',
    'audio_rejects_a_short_frame',
})


@pytest.fixture(scope='module')
def child_results(sandbox: Path) -> dict[str, str | None]:
    """Run every isolated check in one child process.

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
            f'the isolated codec child produced no results (exit {proc.returncode}).\n'
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
def test_isolated_codec_check(
    child_results: dict[str, str | None], check: str,
) -> None:
    """One pytest result per protocol check performed in the child."""
    failure = child_results.get(check, 'the check did not run')
    assert failure is None, f'{check} failed in the isolated process:\n{failure}'

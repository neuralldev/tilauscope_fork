# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. TilauScope is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""An energy meter that read nothing at all, from end to end of a session.

Turning monitoring off conditions each configured meter's recorded array. A
cable out of its socket fills that array with the -1 no-reading sentinel and
nothing else, which left the search for valid samples empty — and the very next
line indexed it. The verdict was right anyway, the function's own broad handler
catching what should never have been raised; this is about not raising it.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any


def _canvas() -> Any:
    errors: list[str] = []
    return SimpleNamespace(adderror=errors.append, errors=errors)


def _condition(qapp: Any, samples: list[float]) -> Any:
    # importing the canvas pulls plus/ in, which reads this off the application
    qapp.artisanviewerMode = False
    from artisanlib.canvas import tgraphcanvas

    return tgraphcanvas.conditionMeterData(_canvas(), samples)


def test_a_meter_that_never_read_is_rejected_without_raising(
        qapp: Any, caplog: Any) -> None:
    """The unplugged-cable session: every sample is the sentinel."""
    samples = [-1.0] * 30

    with caplog.at_level(logging.ERROR, logger='artisanlib.canvas'):
        result = _condition(qapp, samples)

    assert result == (samples, -1, True)
    assert caplog.records == [], 'the rejection went through the exception path'


def test_a_single_sentinel_sample_is_rejected_the_same_way(
        qapp: Any, caplog: Any) -> None:
    with caplog.at_level(logging.ERROR, logger='artisanlib.canvas'):
        result = _condition(qapp, [-1.0])

    assert result == ([-1.0], -1, True)
    assert caplog.records == []


def test_an_empty_array_keeps_its_own_verdict(qapp: Any) -> None:
    """The case just above the new one — same three-part answer."""
    assert _condition(qapp, []) == ([], -1, True)


def test_a_meter_that_read_normally_still_passes(qapp: Any) -> None:
    """The guard must reject nothing that was being accepted before it."""
    samples = [float(i) for i in range(30)]

    conditioned, rollover, failed = _condition(qapp, samples)

    assert failed is False
    assert rollover == -1
    assert conditioned == samples


def test_a_meter_that_starts_late_is_still_rejected(qapp: Any) -> None:
    """Neighbouring case: some readings, but none for the first 10 samples."""
    samples = [-1.0] * 15 + [float(i) for i in range(15)]

    assert _condition(qapp, samples) == (samples, -1, True)

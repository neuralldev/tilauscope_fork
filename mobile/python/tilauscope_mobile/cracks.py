# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""What the crack counter heard during one roast, read off the recorded `cracks` channel.

The header's chip and the ticks along the foot of the curve both come from here, and both are
read from the samples rather than accumulated live: a roast recovered after a crash, or replayed
from a file, shows what the roast that ran showed. The phase words follow the desktop's crack bar
(tilauscope/graph/crackbar.py): display only, the First crack milestone is the detector's.
"""

WINDOW_S = 35.0 # the cracks counted for the rate, as the desktop's FC window
THRESHOLD = 4 # cracks in the window that make a rolling crack, as the desktop's FC threshold
LULL_S = 20.0 # under the threshold this long after First crack: the crack is settling
SEGMENTS = 10 # the meter's bars; three times the threshold fills it
MAX_PER_SAMPLE = 16 # a counter that overflows must not flood the ticks


def crack_times(samples) -> list[float]:
    """When each crack was heard (session seconds): one time per unit the counter rose. A counter that
    went back is a probe that restarted: counted again from there."""
    times, previous = [], None
    for s in samples:
        value = s.extras.get("cracks") if s.extras else None
        if value is None or value < 0:
            continue
        count = int(value)
        if previous is not None and count > previous:
            times.extend([s.elapsed_s] * min(count - previous, MAX_PER_SAMPLE))
        previous = count
    return times


def _in_window(times: list[float], at: float) -> int:
    return sum(1 for t in times if at - WINDOW_S < t <= at)


def meter(samples, first_crack_s: float | None) -> dict | None:
    """The chip: its phase word, the cracks heard so far and the bars lit; None before any count."""
    counted = [s for s in samples if s.extras and s.extras.get("cracks") is not None]
    if not counted:
        return None
    times, now = crack_times(samples), samples[-1].elapsed_s
    n = _in_window(times, now)
    if first_crack_s is None:
        phase = "first" if n >= 1 else "listening"
    else:
        # The lull starts at the first sample after the last one where the crack was rolling (or at First crack)
        lull = first_crack_s
        for s in samples:
            if s.elapsed_s >= first_crack_s and _in_window(times, s.elapsed_s) >= THRESHOLD:
                lull = None
            elif s.elapsed_s >= first_crack_s and lull is None:
                lull = s.elapsed_s
        phase = "rolling" if lull is None or now - lull < LULL_S else "settling"
    bars = 0 if phase == "listening" else max(0, min(SEGMENTS, round(SEGMENTS * n / (3 * THRESHOLD))))
    return {"phase": phase, "count": len(times), "bars": bars}

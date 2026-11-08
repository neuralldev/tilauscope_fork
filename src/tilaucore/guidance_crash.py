# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A RoR crash: the RoR lost over a sliding 15 s window, held a few seconds.

The same rule in every phase; only the gesture the screen announces changes. Replayed on
60 roasts: 3 in development, 1 before first crack, none on a sound roast. The screen says
the words and sounds the beep; this module only decides.
"""

from __future__ import annotations

import time
from collections.abc import Sequence


class CrashDetector:
    """reset(mode) is called at each phase change, so the threshold follows the unit (°C or °F)."""

    FALL_WINDOW_S    = 15.0  # window the fall is measured over
    FALL_C_PER_WIN   = 3.0   # °C/min lost over the window: a clear crash
    MIN_SPAN_S       = 10.0  # history the window must cover before judging
    MIN_DURATION_SEC = 5.0   # how long the condition holds (< 4-5 s = noise)
    DRUM_QUIET_S     = 30.0  # quiet after a drum move (it disturbs the RoR measurement)

    def __init__(self) -> None:
        self._consecutive:    int   = 0
        self._last_beep_ror:  float = 0.0
        self._fall_thr:       float = self.FALL_C_PER_WIN  # °C/min per 15 s by default
        self._drum_quiet_until: float = 0.0   # monotonic, kept across reset()

    def notify_drum_event(self) -> None:
        """A drum move disturbs the RoR measurement (+50 % median excursion, 64 of 81
        roasts of the corpus): no detection for DRUM_QUIET_S. Deliberately kept by reset()."""
        self._drum_quiet_until = time.monotonic() + self.DRUM_QUIET_S

    def reset(self, mode: str = 'C') -> None:
        """Start again, the threshold in the unit (a delta: ×1.8 in °F)."""
        self._consecutive   = 0
        self._last_beep_ror = 0.0
        self._fall_thr      = self.FALL_C_PER_WIN * (9.0 / 5.0 if mode == 'F' else 1.0)

    def fall(self, ror_hist: Sequence[float], dt: float = 1.0) -> float | None:
        """The RoR lost per 15 s once a crash is confirmed, None otherwise.

        Window and hold are in seconds, so they do not depend on the sampling interval `dt`.
        """
        if len(ror_hist) < 4:
            return None
        if time.monotonic() < self._drum_quiet_until:
            self._consecutive = 0   # drum window: the RoR measurement is disturbed
            return None

        dt = dt if (dt and dt > 0) else 1.0
        _n = min(len(ror_hist), max(2, int(round(self.FALL_WINDOW_S / dt)) + 1))
        _vals = list(ror_hist)[-_n:]
        _span = (len(_vals) - 1) * dt
        if _span < self.MIN_SPAN_S:
            return None
        # fall brought to the nominal window (°C/min lost per 15 s)
        _fall = (_vals[0] - _vals[-1]) * (self.FALL_WINDOW_S / _span)
        if _fall < self._fall_thr:
            self._consecutive = 0
            return None
        self._consecutive += 1
        if self._consecutive < max(2, int(-(-self.MIN_DURATION_SEC // dt))):
            return None
        return _fall

    def beep_due(self, ror: float) -> bool:
        """A crash beeps again only once the RoR has moved by more than 0.5 since the last beep."""
        if abs(ror - self._last_beep_ror) > 0.5:
            self._last_beep_ror = ror
            return True
        return False

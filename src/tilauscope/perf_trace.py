"""Segment timings for a one-shot operation, logged in one line.

Reusable: keep this module. What is temporary is the wiring — every call site is
tagged `## TILAU-PERF ##`, so an instrumentation campaign lifts out with:

    grep -rn 'TILAU-PERF' src/

Timings are logged at INFO so they reach artisan.log without turning debug
logging on. A segment shorter than `MIN_MS` is folded into a trailing count: the
point is to find where the seconds go, not to read forty sub-millisecond rows.

    _perf = PerfTrace('OnMonitor')
    ...            ; _perf.mark('reset')
    ...            ; _perf.mark('redraw')
    _perf.done()   # PERF OnMonitor total=1830ms | reset=910  redraw=140 (+6 <2ms)

Never measure the ~1 Hz sampling path with this: one log line per tick is its own
kind of load. It is built for clicks and transitions.
"""

import logging
import time

_log = logging.getLogger(__name__)

MIN_MS = 2.0     # segments shorter than this are folded into a count
ENABLED = True   # set False to make every trace inert without unwiring it


class PerfTrace:
    """Stopwatch with named laps. Never raises: instrumentation must not be the
    thing that breaks the operation it is measuring."""

    __slots__ = ('label', '_t0', '_last', '_marks')

    def __init__(self, label: str) -> None:
        self.label = label
        self._t0 = time.perf_counter()
        self._last = self._t0
        self._marks: list[tuple[str, float]] = []

    def mark(self, name: str) -> None:
        """Close the segment that ends here and name it."""
        try:
            now = time.perf_counter()
            self._marks.append((name, (now - self._last) * 1000.0))
            self._last = now
        except Exception:  # noqa: BLE001
            pass

    def done(self) -> None:
        """Log the whole run. Safe to reach through an early return or a finally."""
        if not ENABLED:
            return
        try:
            total = (time.perf_counter() - self._t0) * 1000.0
            shown = [f'{n}={d:.0f}' for n, d in self._marks if d >= MIN_MS]
            hidden = len(self._marks) - len(shown)
            _log.info('PERF %s total=%.0fms | %s%s', self.label, total,
                      '  '.join(shown),
                      f' (+{hidden} <{MIN_MS:.0f}ms)' if hidden else '')
        except Exception:  # noqa: BLE001
            pass

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Single-owner recording model; timestamps are local monotonic seconds."""

from collections import deque
from dataclasses import asdict, dataclass
import math


def finite(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Reading:
    bt_c: float
    et_c: float | None = None

    def __post_init__(self) -> None:
        # -1 is a missing-probe sentinel, not a temperature sample.
        if not finite(self.bt_c) or self.bt_c <= 0:
            raise ValueError("BT must be a finite positive Celsius measurement")
        if self.et_c is not None and (not finite(self.et_c) or self.et_c <= 0):
            raise ValueError("ET must be absent or a finite positive Celsius measurement")


@dataclass(frozen=True)
class Sample:
    elapsed_s: float
    bt_c: float
    et_c: float | None
    extras: dict | None = None # accessory channels read with this sample (EXTRA_CHANNELS)


# Accessory channels recorded with each sample, as the desktop's extra devices do.
EXTRA_CHANNELS = ("inlet_c", "catalyst_c", "room_c", "room_rh", "pressure_hpa", "altitude_m")


MAX_WEIGHT_G = 5000
MAX_COLOUR = 150

class Session:
    """One recording; create another instance for the next roast.

    RoR is a prototype 20-second least-squares slope, available after 5 seconds.
    It is not claimed to match Artisan's configurable filters.
    """

    STALE_AFTER_S = 3.0
    ROR_WINDOW_S = 20.0
    ROR_MIN_SPAN_S = 5.0
    MILESTONES = ("charge", "dry_end", "first_crack", "drop")
    LEVERS = ("burner", "air", "drum", "extractor")

    def __init__(self, *, simulated: bool = False) -> None:
        self.simulated = simulated
        self.state = "idle"
        self.samples: list[Sample] = []
        self.ror_series: list[float | None] = [] # RoR at each sample's receipt
        self.et_ror_series: list[float | None] = [] # the drum probe's, the same way (alarms on ET RoR)
        self.milestones: dict[str, int] = {}
        self.settings: list[tuple[float, str, int]] = [] # (elapsed, lever, commanded %)
        self.ambient: dict | None = None # room conditions read at CHARGE
        self.weights: dict[str, int | None] = {"green": None, "roasted": None} # whole grams
        self.colours: dict[str, float | None] = {"whole": None, "ground": None} # never pooled
        self.uuid = "" # roastUUID, set when the recording starts
        self.title = "" # roast title and beans text of the chosen coffee ("" = none)
        self.beans = ""
        self.greens: dict | None = None # Roast Setup: density, moisture, greens_temp, beansize
        self.stock_move: dict | None = None # the stock taken at the start, and by whom
        self.exported: str | None = None # file name of the saved roast
        self.started_epoch: float | None = None # wall clock at the start, for the roast date
        self.preheat_sv_c: float | None = None # the TilauPID target, when the preheat drove this roast
        self.pid_source = 1 # the probe the preheat read: Artisan's pidSource (1 BT, 2 ET)
        self.pid_settings: set[int] = set() # indices of the settings the preheat commanded
        self.late_sampling: tuple[int, float] | None = None # (late ticks, longest gap in s): the tablet fell behind
        self.energy: dict | None = None # the energy session closed at STOP (tilau_energy)
        self.alarm_settings: dict[int, int] = {} # index of a setting an alarm made -> the alarm's number (from 1)
        self.tz_offset = 0 # seconds west of UTC, as Artisan stores it
        self._window: deque[Sample] = deque()
        self._started_at: float | None = None
        self._last_received_at: float | None = None
        self._stopped_at: float | None = None

    def start(self, now: float) -> None:
        if self.state != "idle" or not finite(now):
            raise ValueError("A session starts once, with a finite monotonic timestamp")
        self._started_at = now
        self.state = "recording"

    def _validate_time(self, now: float) -> None:
        if self._started_at is None or not finite(now) or now < self._started_at:
            raise ValueError("Timestamp precedes session start or is invalid")
        if self._last_received_at is not None and now < self._last_received_at:
            raise ValueError("Timestamp precedes the latest sample")

    def ingest(self, reading: Reading, received_at: float, extras: dict | None = None) -> None:
        if self.state != "recording":
            raise ValueError("Only recording sessions accept samples")
        self._validate_time(received_at)
        if self._last_received_at is not None:
            gap = received_at - self._last_received_at
            if gap == 0:
                raise ValueError("Duplicate sample timestamp")
            if gap >= self.STALE_AFTER_S:
                self._window.clear() # never compute RoR across a telemetry outage
        assert self._started_at is not None
        if extras and (set(extras) - set(EXTRA_CHANNELS) or not all(finite(v) for v in extras.values())):
            raise ValueError("Unknown or invalid accessory channel")
        sample = Sample(received_at - self._started_at, reading.bt_c, reading.et_c, dict(extras) if extras else None)
        self.samples.append(sample)
        self._window.append(sample)
        while self._window[0].elapsed_s < sample.elapsed_s - self.ROR_WINDOW_S:
            self._window.popleft()
        self._last_received_at = received_at
        self.ror_series.append(self._slope())
        self.et_ror_series.append(self._slope(lambda s: s.et_c))

    def stale(self, now: float) -> bool:
        self._validate_time(now)
        return self._last_received_at is None or now - self._last_received_at >= self.STALE_AFTER_S

    def ror(self, now: float) -> float | None:
        return None if self.stale(now) else self._slope()

    def _slope(self, probe=lambda s: s.bt_c) -> float | None:
        if len(self._window) < 2:
            return None
        if self._window[-1].elapsed_s - self._window[0].elapsed_s < self.ROR_MIN_SPAN_S:
            return None
        values = [probe(s) for s in self._window]
        if any(v is None for v in values): # a probe the roaster does not have, or a reading it missed
            return None
        mean_t = sum(s.elapsed_s for s in self._window) / len(self._window)
        mean_v = sum(values) / len(values)
        covariance = sum((s.elapsed_s - mean_t) * (v - mean_v) for s, v in zip(self._window, values))
        variance = sum((s.elapsed_s - mean_t) ** 2 for s in self._window)
        return 60 * covariance / variance

    def mark(self, milestone: str, now: float, index: int | None = None) -> None:
        """At the latest sample, or at `index` for a milestone found back in the curve."""
        if self.state != "recording" or not self.samples or self.stale(now):
            raise ValueError("Milestones require a recording with fresh telemetry")
        if milestone not in self.MILESTONES or milestone in self.milestones:
            raise ValueError("Unknown or already marked milestone")
        position = self.MILESTONES.index(milestone)
        if any(self.MILESTONES.index(key) > position for key in self.milestones):
            raise ValueError("Cannot mark an earlier milestone after a later one")
        if milestone != "charge" and "charge" not in self.milestones:
            raise ValueError("CHARGE must be marked first")
        latest = len(self.samples) - 1
        if index is None:
            index = latest
        elif not max(self.milestones.values(), default=0) <= index <= latest:
            raise ValueError("A milestone goes on a sample after the previous one")
        self.milestones[milestone] = index

    def record_setting(self, lever: str, value: int, now: float) -> None:
        """A commanded lever value; what the machine confirmed is not part of the record."""
        if self.state != "recording" or lever not in self.LEVERS:
            raise ValueError("Settings are recorded for a known lever while recording")
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("A setting is a whole percentage")
        self._validate_time(now)
        assert self._started_at is not None
        self.settings.append((now - self._started_at, lever, value))

    def unmark(self, milestone: str) -> None:
        """Remove the latest milestone only, while recording."""
        if self.state != "recording" or not self.milestones:
            raise ValueError("Nothing to undo")
        if milestone != max(self.milestones, key=self.MILESTONES.index):
            raise ValueError("Only the latest milestone can be undone")
        del self.milestones[milestone]
        if milestone == "charge":
            self.ambient = None # it was read for that charge

    def set_weight(self, kind: str, grams: int) -> None:
        """Green before the roast, roasted after it, in whole grams."""
        allowed = {"green": ("idle", "recording"), "roasted": ("stopped",)}
        if kind not in allowed or self.state not in allowed[kind]:
            raise ValueError("Green is weighed before the roast, roasted after it")
        if type(grams) is not int or not 1 <= grams <= MAX_WEIGHT_G:
            raise ValueError("A weight is a whole number of grams")
        self.weights[kind] = grams

    def set_colour(self, kind: str, value: float) -> None:
        """Roast colour of whole beans or ground coffee, measured once the roast is over."""
        if kind not in self.colours or self.state != "stopped":
            raise ValueError("Whole or ground colour, once the roast is over")
        if type(value) not in (int, float) or not finite(value) or not 0 < value <= MAX_COLOUR:
            raise ValueError("A colour is a value on the SCA scale")
        self.colours[kind] = round(float(value), 1)

    def stop(self, now: float) -> None:
        if self.state != "recording":
            raise ValueError("Session is not recording")
        self._validate_time(now)
        self._stopped_at = now
        self.state = "stopped"

    def snapshot(self, now: float) -> dict:
        if self.state == "idle":
            raise ValueError("Session has not started")
        self._validate_time(now)
        at = self._stopped_at if self._stopped_at is not None else now
        last = self.samples[-1] if self.samples else None
        assert self._started_at is not None
        return {
            "schema_version": 1, "state": self.state, "simulated": self.simulated,
            "elapsed_s": at - self._started_at, "sample_count": len(self.samples),
            "bt_c": last.bt_c if last else None, "et_c": last.et_c if last else None,
            "stale": self.stale(at), "ror_c_per_min": self.ror(at),
            "milestones": dict(self.milestones),
        }

    def document(self, now: float) -> dict:
        return {"format": "tilauscope-mobile-session", **self.snapshot(now),
                "samples": [asdict(sample) for sample in self.samples],
                "settings": [list(setting) for setting in self.settings],
                "ambient_at_charge": self.ambient, "weights_g": dict(self.weights),
                "colours": dict(self.colours)}

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""TilauPID on the tablet (PREHEAT-SPEC P2): the desktop's preheat controller
(tilaucore.preheat_controller), its law and its learning, on the session's samples.

The tablet gives it what is its own: the session clock, one sample a second, the
burner command (sent to the roaster by the core), the preheat mark on the roast,
the room from TilauAmbient, and its learned values in a JSON file beside the
settings. Each app learns on its own, from the roasts it holds (decision 2): here
the tablet's and the computer's. One thing the desktop does not have: touching
the burner pauses the preheat until it is re-armed (decision 4).
"""

import json
import os
from collections import deque
from pathlib import Path
from typing import Any, Callable

from tilaucore.preheat import (PREHEAT_BAND_C, PREHEAT_NEAR_C, AmbientConditions, PIDConfig, preheat_eta)
from tilaucore.preheat_controller import PreheatController
from tilaucore.preheat_learning import AlogScanner
from tilaucore.preheat_safety import SensorSafetyLimits

from .catalogue import MACHINES
from .roasts import Roasts

INPUTS = {"BT": 1, "ET": 2} # Artisan's pidSource: 0/1 read the bean probe, 2 the drum probe
SAMPLING_DT = 1.0 # the session takes one sample a second


class JsonSettings:
    """QSettings' calls the learning makes, over a JSON file (written at once, atomically)."""

    def __init__(self, path: str | None) -> None:
        self.path = Path(path) if path else None # None: kept in memory only (tests, the command line)
        try:
            self._data: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
        except (OSError, ValueError):
            self._data = {}

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002 (QSettings' name)
        value = self._data.get(key, default)
        if type is None or value is None:
            return value
        try:
            return bool(value) if type is bool else type(value)
        except (TypeError, ValueError):
            return default

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self._data[key] = value
        self.sync()

    def contains(self, key: str) -> bool:
        return key in self._data

    def allKeys(self) -> list[str]:  # noqa: N802
        return list(self._data)

    def remove(self, key: str) -> None:
        """The key and everything under it, as QSettings removes a group."""
        for name in [k for k in self._data if k == key or k.startswith(key + "/")]:
            del self._data[name]
        self.sync()

    def sync(self) -> None:
        if self.path is None:
            return
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


class TabletScanner(AlogScanner):
    """Past preheats of the tablet's two roast folders, sorted out on their index."""

    def __init__(self, roasts: Roasts, window: int, *, machine: str, pid_source: int, scan_budget: int | None) -> None:
        super().__init__(str(roasts.folder("tablet")), window, machine=machine, pid_source=pid_source,
                         scan_budget=scan_budget)
        self._roasts = roasts
        self._records: dict | None = None

    def _index_records(self) -> dict:
        """Both folders' index, read once per scan: asked for each file, it would rescan both folders each time."""
        if self._records is None:
            self._records = self._roasts.index()
        return self._records

    def _list_recent(self) -> list[Path]:
        self._records = None # a new scan sees the roasts saved since
        records = self._index_records()
        files = sorted((Path(path) for path in records), key=lambda p: p.stat().st_mtime, reverse=True)
        return [f for f in files if self._index_admits(f)][:max(0, self.scan_budget)]


class TabletPreheat(PreheatController):
    """The preheat of one roast, driven from the core's tick."""

    def __init__(self, *, roasts: Roasts, machine: str, input_probe: str, store_path: str | None,
                 clock: Callable[[], float], burner: Callable[[int], None], mark: Callable[[float | None], None],
                 fault: Callable[[str], None],
                 simulated: bool, room: Callable[[], AmbientConditions | None], ror_span_s: float) -> None:
        self._clock, self._burner, self._mark, self._room, self._sim = clock, burner, mark, room, simulated
        self._fault = fault
        self._ror_span = ror_span_s
        self._store = JsonSettings(store_path)
        entry = MACHINES[machine]
        self._machine = f'{entry["manufacturer"]} {entry["model"]}'
        self._pid_source = INPUTS[input_probe]
        self._roasts = roasts
        self._to_c = lambda value: value # the tablet is in °C throughout
        self._to_native = lambda value: value
        self._unit = lambda: "C"
        self.cfg = PIDConfig()
        self._init_controller_state()
        self._watching = False
        self.paused = False
        self.fault: str | None = None
        self._apply_sampling_cadence()
        self._precompute_targets()
        self._adaptive_init(alog_dir=str(roasts.folder("tablet")), window=10, ambient=room(), scan_budget=None)

    # ── The shared controller's hooks ─────────────────────────────────────
    def _guard_clock(self) -> float:
        return self._clock()

    def _control_clock(self) -> float:
        return self._clock()

    def _learning_clock(self) -> float:
        return self._clock()

    def _display_ror_span(self) -> float:
        return self._ror_span

    def _apply_sampling_cadence(self) -> None:
        dt = self.cfg.polling_dt = SAMPLING_DT
        self.ror_span_sec = self._ror_span
        self.window_size = max(2, round(self.ror_span_sec / dt))
        self.short_window_size = max(2, round(self.cfg.ror_short_sec / dt))
        self.temp_history = deque(maxlen=self.window_size)
        self.time_history = deque(maxlen=self.window_size)
        self.temp_history_short = deque(maxlen=self.short_window_size)
        self.time_history_short = deque(maxlen=self.short_window_size)
        self._sensor_guard.limits = SensorSafetyLimits(stale_after_sec=max(3.5, dt * 3.5), min_ror_dt_sec=max(1.0, dt))
        self._hold_integrator.max_dt_sec = max(2.5, dt * 2.5)
        detector = getattr(self, "_stabilisation_detector", None)
        if detector is not None:
            detector.polling_dt = dt

    def _command_output(self, slider_nr: int, power: int) -> None:
        if slider_nr == self.cfg.heater_slider:
            self._burner(power)

    def _notify_fault(self, reason: str) -> None:
        self.fault = reason
        self._fault(reason) # the roaster is cooled, then stopped

    def _mark_preheat(self) -> None:
        self._mark(float(self.cfg.target_sv))

    def _clear_preheat_sv_marker(self) -> None:
        self._mark(None)

    def _start_watchdog(self) -> None:
        self._watching = not self._sim

    def _stop_watchdog(self) -> None:
        self._watching = False

    def _schedule_learning(self) -> None:
        self._learn_pending = True # run once stop() has returned

    def stop(self, reason: str = "operator_abort") -> None:
        self._learn_pending = False
        super().stop(reason=reason)
        if self._learn_pending:
            self._learn_pending = False
            self._deferred_preheat_complete()

    def _settings(self) -> JsonSettings:
        return self._store

    def _simulated(self) -> bool:
        return self._sim

    def _make_scanner(self, alog_dir: str, window: int, scan_budget: int | None) -> TabletScanner:
        return TabletScanner(self._roasts, window, machine=self._machine, pid_source=self._pid_source,
                             scan_budget=scan_budget)

    def get_real_time_ambients(self) -> AmbientConditions | None:
        return self._room()

    # ── The tablet's own: one tick, the pause, what the screen shows ──────
    def tick(self, reading_c: float | None) -> None:
        """Each second of the session: the sample when there is one, the watchdog always."""
        if not self.active or self.paused: # paused: the operator has the burner
            return
        if reading_c is not None:
            self.cycle(reading_c)
        elif self._watching:
            self._watchdog_tick() # no sample: the guard trips once it is stale

    def pause(self) -> None:
        """The operator took the burner: the preheat waits, and this session teaches nothing."""
        if self.active and not self.paused:
            self.paused = True
            self._learning_allowed = False

    def resume(self, burner_now: int) -> None:
        """Re-armed: the law takes the burner back from where the operator left it."""
        if self.active and self.paused:
            self.paused = False
            self.prev_power = burner_now
            self._hold_integrator.reset()

    def view(self, reading_c: float | None, rate: float | None) -> dict:
        """The preheat as the roast screen shows it."""
        target = float(self.cfg.target_sv)
        delta = None if reading_c is None else target - reading_c
        arrived = delta is not None and abs(delta) <= PREHEAT_BAND_C
        state = ("fault" if self.fault else "done" if not self.active else "paused" if self.paused
                 else "arrived" if arrived else "climb")
        return {"state": state, "target": round(target, 1), "fault": self.fault,
                "projected": None if self.t_proj_c is None else round(self.t_proj_c, 1),
                "eta_s": None if delta is None or arrived else preheat_eta(delta, rate),
                "near": delta is not None and abs(delta) < PREHEAT_NEAR_C,
                "badge": dict(self.learning_badge) if self.learning_badge else None}

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

"""AutoPilot core — pure trim engine (AutoRoast-Spec §3/§3bis).

Deliberately Qt-free and aw-free: the same engine runs in the offline shadow
simulator (tools/autopilot_sim.py) and, later, inside the assistant panel
(v1b). All magnitudes/cadences/bounds are per-roaster parameters
(TrimParams) — the defaults are Tilau's Skywalker calibration, meant for
concept testing, never universal.

Doctrine:
- airflow SUPPORTS the thermal reaction (raises RoR); it is NEVER a brake;
- braking = heater -step per cadence while uncorrected, then extraction;
- release rule: once RoR is back in band the extraction brake MUST be walked
  back to its plan value (otherwise stall), with priority over new trims;
- one attribution window at a time; trims reset at each milestone (phase).

All temperatures/RoR are °C / °C-per-minute (unit doctrine: °C internal).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

_logd: Final[logging.Logger] = logging.getLogger('tilau')

EPS_ROR: Final[float] = 0.5   # °C/min floor used for relative deviation


class Phase(Enum):
    DRY = 'drying'
    MAILLARD = 'maillard'
    DEV = 'development'


class Lever(Enum):
    AIR = 'air'         # roaster airflow slider (etype 0)
    HEATER = 'heater'   # burner slider (etype 3)
    EXT = 'ext'         # extraction / AirWave FAN (etype 2)


@dataclass(frozen=True)
class TrimParams:
    """Per-roaster tuning — defaults = Tilau's Skywalker (concept-test values).

    v2: step magnitudes become learned from manual roasts (per roaster)."""
    ok_rel: float = 0.15                 # RoR relative deadband (coach OK threshold)
    warn_rel: float = 0.30               # beyond this the gap is "large" -> full 5% blocks
    small_step_pct: float = 2.5          # heater/ext step while the gap is moderate (2-3%)
    persistence_ticks: int = 5           # consecutive out-of-band ticks before acting
    trend_window_s: float = 10.0         # RoR slope window for the trend gate
    # support (adding energy = the risky direction -> strict bounds)
    air_step_pct: float = 5.0            # airflow resolution step
    air_window_s: float = 8.0            # attribution window after an airflow action
    air_bound_steps: int = 1             # cumulative support bound (+1 step)
    heater_support_step_pct: float = 2.5
    heater_support_window_s: float = 28.0
    heater_support_bound_pct: float = 5.0
    # braking (removing energy = the safe direction -> aggressive cadence)
    brake_cadence_s: float = 10.0        # one brake tranche per cadence while uncorrected
    brake_heater_step_pct: float = 5.0
    brake_ext_step_pct: float = 5.0
    brake_improve_ror: float = 0.3       # °C/min drop per tranche counted as "correcting"
    brake_heater_max_tranches: int = 3   # escalate to extraction after N uncorrected tranches
    ext_bound_pct: float = 10.0          # cumulative extraction brake bound (to calibrate)
    # release (mandatory unwind once back in band; extraction first — stall risk)
    release_cadence_s: float = 10.0
    release_air: bool = False            # Tilau mandates ext release only; air support may stay
    heater_restore_in_dev: bool = False  # post-FC one almost never brings heat back up
    # adding heat right before FC contradicts the plan's own pre-FC ramp-down
    pre_fc_guard_s: float = 60.0           # no heater SUPPORT within this window before FC (MAI)
    pre_fc_restore_guard_s: float = 120.0  # no heater RESTORE within this window (pointless: ramp will lower it)
    # in DEV heater support is off by default: airflow carries the support and a real
    # crash pauses AUTO via the crash detector anyway (corpus: 8 KO / 1 OK)
    dev_heater_support: bool = False
    # early re-entry into an open attribution window when the gap clearly worsens
    worsen_abs_floor: float = 0.3        # °C/min
    worsen_rel: float = 0.10             # fraction of target
    # absolute clamps
    max_burner_pct: float = 80.0
    airflow_min_pct: float = 20.0
    ext_max_pct: float = 100.0


@dataclass
class Action:
    t: float                 # seconds since CHARGE
    lever: Lever
    delta_pct: float         # signed step
    target_value: float      # absolute % to set on the slider (already clamped)
    kind: str                # 'support' | 'brake' | 'release'
    reason: str              # short, log-friendly ("RoR -22% vs plan")


@dataclass
class _PhaseState:
    phase: Phase
    t_start: float
    t_end: float
    ror_start: float         # target RoR at phase start (°C/min)
    ror_end: float           # target RoR at phase end
    plan_levers: dict[Lever, float | None] = field(default_factory=dict)
    # cumulative trims relative to the plan values (per phase, reset on milestone)
    air_steps: int = 0
    heater_support_pct: float = 0.0
    heater_brake_pct: float = 0.0        # cumulative amount braked below plan (>= 0)
    ext_trim_pct: float = 0.0            # cumulative extraction brake (>= 0)
    brake_tranches: int = 0              # uncorrected heater tranches in the current episode


class AutoPilotCore:
    """State-aware bounded trim engine. Feed it 1 Hz ticks; it emits at most
    one Action per tick. In shadow mode the caller never applies actions but
    keeps calling observe_levers() with the real (human) values."""

    def __init__(self, params: TrimParams | None = None) -> None:
        self.p = params or TrimParams()
        self._ph: _PhaseState | None = None
        self._ror_hist: deque[tuple[float, float]] = deque(maxlen=64)
        self._levers: dict[Lever, float | None] = {lv: None for lv in Lever}
        self._persist_low = 0
        self._persist_high = 0
        self._window_until = 0.0
        self._window_d0 = 0.0            # |ror - target| when the window opened
        self._last_brake_t = -1e9
        self._ror_at_brake = 0.0
        self._next_release_t = -1e9
        self.bound_hit: str | None = None  # set when a trim hits its ceiling (coach message)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start_phase(self, phase: Phase, t_start: float, t_end: float,
                    ror_start: float, ror_end: float,
                    plan_levers: dict[Lever, float | None]) -> None:
        """Milestone crossed: new plan values, trims reset (spec §3bis)."""
        self._ph = _PhaseState(phase=phase, t_start=t_start, t_end=t_end,
                               ror_start=ror_start, ror_end=ror_end,
                               plan_levers=dict(plan_levers))
        self._persist_low = self._persist_high = 0
        self._window_until = 0.0
        self._last_brake_t = -1e9
        self._next_release_t = -1e9
        self.bound_hit = None

    def disarm(self) -> None:
        """Drop the active phase — no action can be emitted until the next
        start_phase (belt-and-suspenders: callers also gate on their own state)."""
        self._ph = None

    def observe_levers(self, air: float | None = None, heater: float | None = None,
                       ext: float | None = None) -> None:
        """Actual slider values (human or applied) — shadow keeps these real."""
        if air is not None:
            self._levers[Lever.AIR] = air
        if heater is not None:
            self._levers[Lever.HEATER] = heater
        if ext is not None:
            self._levers[Lever.EXT] = ext

    # ── helpers ───────────────────────────────────────────────────────────

    def target_ror(self, t: float) -> float | None:
        ph = self._ph
        if ph is None or ph.t_end <= ph.t_start:
            return None
        frac = min(1.0, max(0.0, (t - ph.t_start) / (ph.t_end - ph.t_start)))
        return ph.ror_start + (ph.ror_end - ph.ror_start) * frac

    def _slope(self) -> float:
        """RoR slope (°C/min per min) over the trend window; 0 if not enough data."""
        if len(self._ror_hist) < 4:
            return 0.0
        t1 = self._ror_hist[-1][0]
        pts = [(t, r) for (t, r) in self._ror_hist if t >= t1 - self.p.trend_window_s]
        if len(pts) < 4:
            return 0.0
        n = float(len(pts))
        st = sum(t for t, _ in pts); sr = sum(r for _, r in pts)
        stt = sum(t * t for t, _ in pts); str_ = sum(t * r for t, r in pts)
        den = n * stt - st * st
        return 0.0 if den == 0 else (n * str_ - st * sr) / den * 60.0

    def _mk(self, t: float, lever: Lever, delta: float, kind: str, reason: str) -> Action | None:
        cur = self._levers.get(lever)
        if cur is None:
            return None
        lo, hi = 0.0, 100.0
        if lever is Lever.HEATER:
            hi = self.p.max_burner_pct
        elif lever is Lever.AIR:
            lo = self.p.airflow_min_pct
        elif lever is Lever.EXT:
            hi = self.p.ext_max_pct
        target = min(hi, max(lo, cur + delta))
        if abs(target - cur) < 0.5:
            return None
        return Action(t=t, lever=lever, delta_pct=target - cur, target_value=target,
                      kind=kind, reason=reason)

    # ── main entry ────────────────────────────────────────────────────────

    def tick(self, t: float, ror: float) -> Action | None:  # noqa: PLR0911, PLR0912
        ph = self._ph
        self._ror_hist.append((t, ror))
        if ph is None:
            return None
        target = self.target_ror(t)
        if target is None or target < EPS_ROR:
            return None
        d_rel = (ror - target) / max(target, EPS_ROR)
        gap = abs(ror - target)
        p = self.p

        # ── in band: release ladder (mandatory, priority over everything) ──
        if abs(d_rel) <= p.ok_rel:
            self._persist_low = self._persist_high = 0
            ph.brake_tranches = 0
            if t >= self._next_release_t:
                act = self._release(t)
                if act is not None:
                    self._next_release_t = t + p.release_cadence_s
                    return act
            return None

        # ── A residual extraction brake while RoR sags pumps heat away from a
        #    reaction that needs it — unwind extraction FIRST, ahead of the support
        #    ladder and any open attribution window. Walks back toward the plan
        #    value only (never below), cadence limited. ──
        if d_rel < 0 and ph.ext_trim_pct > 0 and t >= self._next_release_t:
            step = min(p.brake_ext_step_pct, ph.ext_trim_pct)
            act = self._mk(t, Lever.EXT, -step, 'release',
                           'RoR sagging — release extraction brake')
            if act is not None:
                ph.ext_trim_pct = max(0.0, ph.ext_trim_pct + act.delta_pct)
                self._next_release_t = t + p.release_cadence_s
                return act

        # ── deviation present: persistence + trend gates ──
        if d_rel < 0:
            self._persist_low += 1
            self._persist_high = 0
        else:
            self._persist_high += 1
            self._persist_low = 0
        slope = self._slope()
        low = self._persist_low >= p.persistence_ticks and slope <= 0.0
        high = self._persist_high >= p.persistence_ticks and slope >= 0.0

        # ── attribution window (one at a time; early re-entry only on worsening) ──
        if t < self._window_until:
            worsen = gap > self._window_d0 + max(p.worsen_abs_floor, p.worsen_rel * target)
            if not worsen:
                return None

        if low:
            return self._support(t, d_rel, gap)
        if high:
            return self._brake(t, ror, d_rel, gap)
        return None

    # ── ladders ───────────────────────────────────────────────────────────

    def _support(self, t: float, d_rel: float, gap: float) -> Action | None:
        """RoR sagging: airflow first (fast, supports the reaction), heater second."""
        p, ph = self.p, self._ph
        assert ph is not None
        reason = f'RoR {d_rel * 100:+.0f}% vs plan'
        if ph.air_steps < p.air_bound_steps:
            act = self._mk(t, Lever.AIR, +p.air_step_pct, 'support', reason)
            if act is not None:
                ph.air_steps += 1
                self._open_window(t, p.air_window_s, gap)
                return act
        # heater rung gates (validated on the 81-roast shadow corpus):
        # - DEV is airflow-first: heater support only on a LARGE gap;
        # - never add heat within the pre-FC guard (the ramp is about to step down).
        heater_ok = True
        if ph.phase is Phase.DEV and not p.dev_heater_support:
            heater_ok = False
        if ph.phase is Phase.MAILLARD and t > ph.t_end - p.pre_fc_guard_s:
            heater_ok = False
        if heater_ok and ph.heater_support_pct < p.heater_support_bound_pct:
            # step modulated by the actual gap: 2-3% while moderate, 5% blocks when far out
            base = p.brake_heater_step_pct if abs(d_rel) >= p.warn_rel else p.small_step_pct
            step = min(base, p.heater_support_bound_pct - ph.heater_support_pct)
            act = self._mk(t, Lever.HEATER, +step, 'support', reason)
            if act is not None:
                ph.heater_support_pct += act.delta_pct
                self._open_window(t, p.heater_support_window_s, gap)
                return act
        self.bound_hit = 'support'
        return None

    def _brake(self, t: float, ror: float, d_rel: float, gap: float) -> Action | None:
        """RoR runaway: heater -step per cadence while uncorrected, then
        extraction. Airflow is NEVER used to brake (it raises RoR)."""
        p, ph = self.p, self._ph
        assert ph is not None
        if t - self._last_brake_t < p.brake_cadence_s:
            return None
        reason = f'RoR {d_rel * 100:+.0f}% vs plan'
        improved = (self._last_brake_t > -1e8
                    and self._ror_at_brake - ror >= p.brake_improve_ror)
        if improved:
            ph.brake_tranches = 0   # correcting — keep waiting on the same lever
        heater_val = self._levers.get(Lever.HEATER)
        heater_exhausted = (heater_val is not None and heater_val <= 0.5) \
            or ph.brake_tranches >= p.brake_heater_max_tranches
        # step modulated by the actual gap: 2-3% while moderate, 5% blocks when far out
        step_h = p.brake_heater_step_pct if abs(d_rel) >= p.warn_rel else p.small_step_pct
        if not heater_exhausted:
            act = self._mk(t, Lever.HEATER, -step_h, 'brake', reason)
            if act is not None:
                ph.heater_brake_pct += -act.delta_pct
                ph.brake_tranches += 1
                self._last_brake_t, self._ror_at_brake = t, ror
                self._open_window(t, p.brake_cadence_s, gap)
                return act
        if ph.ext_trim_pct < p.ext_bound_pct:
            base = p.brake_ext_step_pct if abs(d_rel) >= p.warn_rel else p.small_step_pct
            step = min(base, p.ext_bound_pct - ph.ext_trim_pct)
            act = self._mk(t, Lever.EXT, +step, 'brake', reason)
            if act is not None:
                ph.ext_trim_pct += act.delta_pct
                self._last_brake_t, self._ror_at_brake = t, ror
                self._open_window(t, p.brake_cadence_s, gap)
                return act
        self.bound_hit = 'brake'
        return None

    def _release(self, t: float) -> Action | None:
        """Back in band: unwind trims toward plan values. Extraction FIRST and
        mandatory (a forgotten extraction brake = guaranteed stall)."""
        p, ph = self.p, self._ph
        assert ph is not None
        if ph.ext_trim_pct > 0:
            step = min(p.brake_ext_step_pct, ph.ext_trim_pct)
            act = self._mk(t, Lever.EXT, -step, 'release', 'RoR back in band — release brake')
            if act is not None:
                ph.ext_trim_pct = max(0.0, ph.ext_trim_pct + act.delta_pct)
                return act
        # heater restore: skipped in DEV (post-FC heat rarely comes back) and inside
        # the pre-FC guard (the ramp is about to lower it anyway) — corpus-validated.
        restore_ok = not (ph.phase is Phase.DEV and not p.heater_restore_in_dev)
        if ph.phase is Phase.MAILLARD and t > ph.t_end - p.pre_fc_restore_guard_s:
            restore_ok = False
        if restore_ok and ph.heater_brake_pct > 0:
            step = min(p.brake_heater_step_pct, ph.heater_brake_pct)
            act = self._mk(t, Lever.HEATER, +step, 'release', 'RoR back in band — restore heater')
            if act is not None:
                ph.heater_brake_pct = max(0.0, ph.heater_brake_pct - act.delta_pct)
                return act
        if p.release_air and ph.air_steps > 0:
            act = self._mk(t, Lever.AIR, -p.air_step_pct, 'release', 'RoR back in band — restore airflow')
            if act is not None:
                ph.air_steps -= 1
                return act
        return None

    def _open_window(self, t: float, dur: float, gap: float) -> None:
        self._window_until = t + dur
        self._window_d0 = gap
        self._persist_low = self._persist_high = 0

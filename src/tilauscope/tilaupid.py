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
# TiLau 2025

import logging
import math
import time
import types
from collections.abc import Mapping
from typing import Any, Final,TYPE_CHECKING
from collections import deque
from dataclasses import dataclass, fields

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

from PyQt6.QtCore import QMetaObject, QSettings, Qt, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from artisanlib.util import fromFtoCstrict, fromCtoFstrict, convertRoRstrict
from tilauscope.tilaupid_adaptative import AdaptivePIDMixin, AmbientConditions, AmbientCorrector
from tilauscope.tilaupid_safety import PreheatSensorGuard, SensorSafetyLimits

_logd: Final[logging.Logger] = logging.getLogger("tilau")

# Dispositions that end a preheat successfully: learning is kept and the preheat
# setpoint marker stays. `handover` additionally leaves the burner at its hold
# power, so the PID calibration inherits a settled machine (protocol 8.1).
_BUMPLESS_STOP_REASONS: Final[frozenset[str]] = frozenset(
    {"charge", "stable_complete", "handover"}
)

# depending on tilauscope settings selecting the roaster, it will adjust accordingly, if using Airwave % of fan is added
# Roaster                   zone_fuzzy_start    coast_lookahead_sec fan_brake_power
# Gas drum, moderate mass   0.84                8                   25-35%
# Gas drum, heavy cast iron 0.80                12                  35-45%
# Electric drum             0.86-0.88           6                   15-25%
# Fluid bed                 0.88                4                   10-20%
# for testing purpose the setting is fixed for SW on electric drum


@dataclass(slots=True)
class PIDConfig:
    heater_slider: int = 3  # slider number in Artisan for the heater control (default 3, but can be changed in config)
    fan_slider: int = 2 # slider number for fan control, not used in this version but reserved for future use
    polling_dt: float = 1.0 # fallback only: the live value is read from qmc.delay by _apply_sampling_cadence()
    target_sv: float = 200.0 # target setpoint in °C (always stored internally in °C regardless of Artisan mode)
    # HARD ceiling on burner power, not a tuning hint: effective_max_burner() clamps the
    # learned adjustment DOWN to this value only, never above (radiant FIR drums trip their thermal cutoff above it).
    max_burner: float = 80.0 # maximum burner power percentage during preheat (hard safety ceiling)
    soft_start_sec: float = 8.0 # duration in seconds for the soft start phase during ramp-up (default 8s, can be adjusted based on roaster response)
    # Hard over-temperature backstop: °C above SV at which the burner is
    # force-cut regardless of phase. Reclaims control well below the roaster's own
    # hardware thermal cutoff.
    safety_margin_c: float = 2.0
    # Output smoothing (anti-chatter, applied in cycle() via _smooth_burner):
    burner_deadband: int = 2   # %: ignore sub-deadband changes to kill ~1 Hz chatter (lowered 4→2 so the proportional hold can fine-trim toward SV)
    burner_slew_max: int = 12  # %/cycle: max burner change per cycle (a full cut to 0 is exempt)
    # ── Proportional-on-projected-temperature control law ──────────────
    # burner = clamp(0, max, P_ss·ambient + Kp·(SV − t_proj) + I_hold), with
    # t_proj = t + ror_short·(lead_sec/60). SV is the stable attractor: burner saturates high
    # below SV, tapers to the steady hold P_ss near SV, and falls toward 0 once t_proj crosses SV.
    kp: float = 5.0                 # burner % per °C of projected error (saturates ~12°C out)
    p_ss_default: float = 20.0      # fallback only: _precompute_targets()'s physical estimate wins
    lead_sec_default: float = 5.0   # initial projection lead = response_lag + FIR residual tail
    lead_sec_min: float = 2.3       # floor on lead (≈ pure actuator response lag)
    lead_sec_max: float = 12.0      # ceiling on lead (anti timid-approach)
    ror_short_sec: float = 4.0      # short RoR window feeding the projection (NOT the 14s display RoR)
    # Slow hold-only integral: acts on actual temperature error (not projected), only
    # after a quiet dwell close to SV — removes the residual offset left by an imperfect P_ss estimate.
    hold_ki_pct_per_c_sec: float = 0.02
    hold_integral_limit_pct: float = 6.0
    hold_integral_band_c: float = 2.0
    # 3°C/min over the 4s short window = 0.2°C of travel: reachable on a 0.1°C
    # probe. At 1.0 the endpoints had to be bit-identical and the gate never armed.
    hold_integral_max_ror_c_per_min: float = 3.0
    hold_integral_arm_sec: float = 10.0
    # Unwind stays faster than accumulation (~0.04%/s at the band edge) but no
    # longer erases twelve seconds of integration per ineligible second.
    hold_integral_unwind_pct_per_sec: float = 0.1
    fan_enabled: bool = False    # Set True to activate fan-assist inertia braking
    # DEPRECATED — retired with the relay control law. No longer read by
    # compute_fuzzy_power; kept only so legacy metric dataclasses populate without churn.
    zone_fuzzy_start: float = 0.87        # (unused)
    coast_lookahead_sec: float = 6.0      # (unused)
    # Fan / damper settings
    fan_brake_ror_threshold: float = 10.0    # °C/min: open fan above this RoR in fuzzy zone
    fan_brake_power: int = 45                # % damper opening during inertia braking
    fan_stabilise_power: int = 30            # % damper during hold phase (usually closed)

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None, *, target_sv: float) -> 'PIDConfig':
        """Build a validated configuration from the public PID mapping.

        PID keys may live directly in ``config`` or in its ``pid`` section.  The
        latter wins, while ``targets.target_sv`` is handled by the caller because
        it is expressed in Artisan's current display unit.
        """
        raw = config or {}
        nested = raw.get("pid", {})
        if nested is None:
            nested = {}
        if not isinstance(nested, Mapping):
            raise ValueError("PID config section 'pid' must be a mapping")

        defaults = cls()
        names = {field.name for field in fields(cls)}
        values: dict[str, Any] = {"target_sv": target_sv}
        for name in names - {"target_sv"}:
            if name in raw:
                values[name] = raw[name]
            if name in nested:
                values[name] = nested[name]

        for name, value in tuple(values.items()):
            default = getattr(defaults, name)
            try:
                if isinstance(default, bool):
                    if isinstance(value, bool):
                        converted = value
                    elif isinstance(value, str) and value.strip().lower() in {"true", "false", "on", "off", "1", "0"}:
                        converted = value.strip().lower() in {"true", "on", "1"}
                    else:
                        raise ValueError("expected a boolean")
                elif isinstance(default, int):
                    converted = int(value)
                else:
                    converted = float(value)
                    if not math.isfinite(converted):
                        raise ValueError("must be finite")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid PID config value {name}={value!r}: {exc}") from exc
            values[name] = converted

        positive = {
            "polling_dt", "soft_start_sec", "kp", "lead_sec_default",
            "lead_sec_min", "lead_sec_max", "ror_short_sec",
            "hold_integral_arm_sec", "hold_integral_unwind_pct_per_sec",
        }
        non_negative = {
            "target_sv", "max_burner", "safety_margin_c", "burner_deadband",
            "burner_slew_max", "p_ss_default", "hold_ki_pct_per_c_sec",
            "hold_integral_limit_pct", "hold_integral_band_c",
            "hold_integral_max_ror_c_per_min", "fan_brake_ror_threshold",
            "fan_brake_power", "fan_stabilise_power",
        }
        for name in positive:
            value = values.get(name, getattr(defaults, name))
            if value <= 0:
                raise ValueError(f"PID config value {name} must be > 0")
        for name in non_negative:
            value = values.get(name, getattr(defaults, name))
            if value < 0:
                raise ValueError(f"PID config value {name} must be >= 0")
        for name in ("max_burner", "p_ss_default", "fan_brake_power", "fan_stabilise_power"):
            value = values.get(name, getattr(defaults, name))
            if value > 100:
                raise ValueError(f"PID config value {name} must be <= 100")
        for name in ("heater_slider", "fan_slider"):
            value = values.get(name, getattr(defaults, name))
            if not 0 <= value <= 3:
                raise ValueError(f"PID config value {name} must be between 0 and 3")
        if values.get("lead_sec_min", defaults.lead_sec_min) > values.get("lead_sec_max", defaults.lead_sec_max):
            raise ValueError("PID config lead_sec_min must be <= lead_sec_max")
        return cls(**values)


@dataclass(slots=True)
class SlowHoldIntegrator:
    """Slow integral trim with hold gating and conditional anti-windup.

    ``correction`` is expressed directly in burner percentage points. Integration
    starts only after a continuous quiet dwell near SV. Outside that zone the trim
    unwinds toward zero, so a correction learned during hold cannot leak back into
    a ramp or prolong an overshoot.
    """

    ki_pct_per_c_sec: float = 0.02
    limit_pct: float = 6.0
    band_c: float = 2.0
    max_ror_c_per_min: float = 1.0
    arm_sec: float = 10.0
    unwind_pct_per_sec: float = 0.5
    max_dt_sec: float = 2.5
    correction: float = 0.0
    _eligible_since: float | None = None
    _last_time: float | None = None

    def reset(self) -> None:
        self.correction = 0.0
        self._eligible_since = None
        self._last_time = None

    @staticmethod
    def _toward_zero(value: float, amount: float) -> float:
        if value > 0.0:
            return max(0.0, value - amount)
        if value < 0.0:
            return min(0.0, value + amount)
        return 0.0

    def update(
        self,
        *,
        error_c: float,
        ror_c_per_min: float,
        base_output_pct: float,
        output_max_pct: float,
        now: float,
    ) -> float:
        """Advance and return the burner correction in percentage points."""
        if self._last_time is None:
            self._last_time = now
            if abs(error_c) <= self.band_c and abs(ror_c_per_min) <= self.max_ror_c_per_min:
                self._eligible_since = now
            return self.correction

        elapsed = max(0.0, now - self._last_time)
        self._last_time = now
        interrupted = elapsed > self.max_dt_sec
        dt = min(elapsed, self.max_dt_sec)
        eligible = (
            not interrupted
            and abs(error_c) <= self.band_c
            and abs(ror_c_per_min) <= self.max_ror_c_per_min
        )

        if not eligible:
            self._eligible_since = None
            self.correction = self._toward_zero(
                self.correction,
                self.unwind_pct_per_sec * dt,
            )
            return self.correction

        if self._eligible_since is None:
            self._eligible_since = now
            return self.correction
        if now - self._eligible_since < self.arm_sec:
            return self.correction

        delta = self.ki_pct_per_c_sec * error_c * dt
        candidate = max(-self.limit_pct, min(self.limit_pct, self.correction + delta))
        candidate_output = base_output_pct + candidate

        # Conditional integration: freeze only when the proposed movement would
        # push farther into actuator saturation. Movement back out remains allowed.
        if candidate_output >= output_max_pct and delta > 0.0:
            return self.correction
        if candidate_output <= 0.0 and delta < 0.0:
            return self.correction

        self.correction = candidate
        return self.correction


class TilauPreheatPID(AdaptivePIDMixin):
    # ── Learning-maturity badge constants (annotation + TilauScope window) ──
    # Marker → glyph/colour for the two capability lines (holding power, braking
    # anticipation); level → segment fill/colour/label key for the EXPERIENCE band.
    _BADGE_MARKER_GLYPH: Final[dict[str, str]] = {"check": "✓", "approx": "≈", "learning": "~"}
    _BADGE_MARKER_COLOR: Final[dict[str, str]] = {"check": "#A6E3A1", "approx": "#89B4FA", "learning": "#F9E2AF"}
    _BADGE_LEVEL_FILL: Final[dict[str, int]] = {"Learning": 1, "Estimated": 2, "Tuned": 3, "Calibrated": 4}
    _BADGE_LEVEL_COLOR: Final[dict[str, str]] = {
        "Learning": "#F9E2AF", "Estimated": "#89B4FA", "Tuned": "#89B4FA", "Calibrated": "#A6E3A1",
    }
    _BADGE_LEVEL_LABEL_KEY: Final[dict[str, str]] = {
        "Learning": "LevelLearning", "Estimated": "LevelEstimated",
        "Tuned": "LevelTuned", "Calibrated": "LevelCalibrated",
    }
    _BADGE_HOLD_TEXT_KEY: Final[dict[str, str]] = {
        "check": "CapHold_check", "approx": "CapHold_approx", "learning": "CapHold_learning",
    }
    _BADGE_LEAD_TEXT_KEY: Final[dict[str, str]] = {
        "check": "CapLead_check", "approx": "CapLead_approx", "learning": "CapLead_learning",
    }

    def __init__(self, aw: 'ApplicationWindow', config: dict | None= None):
        self.aw = aw

        # ── Temperature unit helpers ──────────────────────────────────────────
        # All internal PID maths are in °C; _to_c()/_to_native() convert at the boundary.
        # Each helper reads self.aw.qmc.mode live, so a unit change at runtime is handled transparently.

        def _to_c(self, val: float) -> float:
            """Convert a value from the current Artisan unit to °C."""
            return fromFtoCstrict(val) if self.aw.qmc.mode == 'F' else val

        def _to_native(self, val_c: float) -> float:
            """Convert a °C value to the current Artisan unit for display."""
            return fromCtoFstrict(val_c) if self.aw.qmc.mode == 'F' else val_c

        def _unit(self) -> str:
            return self.aw.qmc.mode   # 'C' or 'F' for log strings

        # Bind helpers as instance methods
        self._to_c       = types.MethodType(_to_c,       self)
        self._to_native  = types.MethodType(_to_native,  self)
        self._unit       = types.MethodType(_unit,        self)

        c = config or {}
        tg = c.get("targets", {"target_sv": 200})
        if not isinstance(tg, Mapping):
            raise ValueError("PID config section 'targets' must be a mapping")

        # target_sv from config is expected in the current Artisan unit; store internally in °C
        _raw_sv = tg.get("target_sv", self.aw.pidcontrol.sv)
        self.cfg = PIDConfig.from_mapping(c, target_sv=self._to_c(_raw_sv))
        # Initialisation dynamique du RoR basée sur Artisan

        # Every window below is a DURATION in seconds; the number of samples that
        # spans it depends on the operator-settable sampling interval, so it is
        # derived in _apply_sampling_cadence() at the end of __init__ and again at
        # each start(). The declarations here only fix the attribute types.
        self.ror_span_sec: float = getattr(self.aw.qmc, "deltaBTspan", 15.0)
        self.window_size: int = 2
        self.temp_history: deque = deque(maxlen=2)
        self.time_history: deque = deque(maxlen=2)
        # Short RoR window (control): the 14s display window lags ~7s and
        # fires the cut too late on a fast radiant ramp. The control law projects
        # temperature with a fresh ~4s derivative instead.
        self.short_window_size: int = 2
        self.temp_history_short: deque = deque(maxlen=2)
        self.time_history_short: deque = deque(maxlen=2)

        self.active = False
        self.prev_power = -1
        self.prev_fan = -1
        self.start_time = 0.0
        # Ramp baseline (native unit, same channel as cycle()'s input) captured on the
        # first valid cycle() — qmc temps are still empty at start(). None until then.
        self.ramp_start_temp: float | None = None
        # Learning-maturity badge for the preheat annotation: computed once per
        # start() (QSettings + corpus reads) and cached as ready HTML fragments so
        # the canvas redraw and the TilauScope window never touch disk. See
        # _compute_learning_badge().
        self.learning_badge: dict | None = None
        self.learning_badge_html = ""
        self.learning_badge_compact_html = ""
        # Sensor guard + independent Qt watchdog. The guard is pure
        # Python; the timer catches the distinct failure mode where sample()
        # stops calling cycle() and the last physical burner command persists.
        self._sensor_guard = PreheatSensorGuard(SensorSafetyLimits())
        self._learning_allowed = True
        self._fault_reason: str | None = None
        self._safety_watchdog = QTimer()
        self._safety_watchdog.timeout.connect(self._watchdog_tick)
        # Native SV to stamp as the "Preheat started" marker, deferred to the
        # first cycle() — at START time qmc.timex is still empty (OnRecorder just called
        # resetTimer) and EventRecordAction silently drops events until the first sample.
        self._pending_start_sv_native: float | None = None

        # Ambients cache
        self.ambient_cache:AmbientConditions | None = None

        # Control-law parameters (learned per-SV from history, loaded at start()):
        #   p_ss    — steady hold power near SV; learned from roasts that plateaued ±0.5°C of SV
        #   lead_sec— projection lead compensating actuator lag + FIR residual radiation;
        #             learned from signed overshoot (overshoot → brake earlier)
        self.p_ss = self.cfg.p_ss_default        # % steady hold near SV
        self.lead_sec = self.cfg.lead_sec_default # s projection lead
        # Last projected temperature, published for the screens. None until
        # the law has run once: a preheat that has not computed anything yet
        # has no projection, and a zero would read as one.
        self.t_proj_c: float | None = None
        self.computed_ramp_power = 80.0          # burner % ceiling for the far-from-SV ramp
        # Session-local bias trim. It is deliberately not persisted: a
        # qualified stable burner median transfers its useful final value into P_ss.
        self._hold_integrator = SlowHoldIntegrator(
            ki_pct_per_c_sec=self.cfg.hold_ki_pct_per_c_sec,
            limit_pct=self.cfg.hold_integral_limit_pct,
            band_c=self.cfg.hold_integral_band_c,
            max_ror_c_per_min=self.cfg.hold_integral_max_ror_c_per_min,
            arm_sec=self.cfg.hold_integral_arm_sec,
            unwind_pct_per_sec=self.cfg.hold_integral_unwind_pct_per_sec,
        )
        # Bind every cadence-dependent window to the real sampling interval.
        self._apply_sampling_cadence()

        #le fallback sur cfg fonctionne donc correctement au premier appel. Mais le threshold calculé à l'init n'intègre pas encore les corrections adaptatives. Ce n'est pas un bug — il sera recalculé au prochain start()
        # Variables pré-calculées
        self._precompute_targets()
        _logd.debug(
            f"Control law ready | display_win={self.ror_span_sec}s ctrl_win={self.cfg.ror_short_sec}s "
            f"SV={self._to_native(self.cfg.target_sv):.1f}°{self._unit()} "
            f"Kp={self.cfg.kp}%/°C Ki_hold={self.cfg.hold_ki_pct_per_c_sec}%/(°C·s) "
            f"fan={'ON' if self.cfg.fan_enabled else 'OFF'}"
        )

        # ── Adaptive learning init ────────────────────────────────────────────
        # alog_dir : répertoire des fichiers .alog Artisan.
        settings = QSettings()
        self.alog_directory = settings.value('alogDirectory', "", str)


        self._adaptive_init(
            alog_dir=self.alog_directory,
            window=c.get("adaptive_window", 10),
            # Read ceiling, distinct from the memory window: how deep the scanner
            # may go when usable preheats are scarce. None = derive from window.
            scan_budget=c.get("adaptive_scan_budget"),
            ambient=self.get_real_time_ambients(),
            aw=self.aw
        )

    # ── Get ambients if any temperature source ────────────────────────────────────

    @staticmethod
    def _map_ambient_source(src: int | None, qmc: object) -> float | None:
        """Résout un index de source ambiante Artisan vers sa valeur float courante.

        Définie comme méthode statique (pas de closure) pour éviter toute
        réallocation à chaque cycle de torréfaction.
        """
        if src is None or src == 0:
            return None
        if src == 1:
            return qmc.on_temp1[-1] if qmc.on_temp1 else None
        elif src == 2:
            return qmc.on_temp2[-1] if qmc.on_temp2 else None
        elif src == 3:
            return qmc.on_delta1[-1] if qmc.on_delta1 else None
        elif src == 4:
            return qmc.on_delta2[-1] if qmc.on_delta2 else None
        elif src > 4:
            # Extra channels : après un run simulateur, RTextratemp1/2[idx] peut
            # être un float scalaire (dernière valeur RT) plutôt qu'une liste.
            # On vérifie explicitement le type avant tout accès par index.
            idx = ((src - 1) // 2) - 1
            try:
                if src % 2 == 1:  # impair → extratemp1
                    series = qmc.on_extratemp1
                    rt     = qmc.RTextratemp1
                else:             # pair → extratemp2
                    series = qmc.on_extratemp2
                    rt     = qmc.RTextratemp2
                if (len(series) > idx
                        and qmc.flagstart
                        and isinstance(series[idx], (list, deque))
                        and len(series[idx]) > 0):
                    return float(series[idx][-1])
                if qmc.flagon:
                    if isinstance(rt, (list, deque)) and len(rt) > idx:
                        return float(rt[idx])  # RT array is a list of float, not a list of list
            except (IndexError, TypeError, AttributeError):
                pass
        return None

    def get_real_time_ambients(self) -> AmbientConditions | None:
        qmc = self.aw.qmc  # résolution unique — évite 7 lookups chaînés self.aw.qmc
        t = qmc.ambientTempSource
        h = qmc.ambientHumiditySource
        p = qmc.ambientPressureSource
        if not (t or h or p):
            return None
        ms = self._map_ambient_source
        # AmbientConditions is a °C frame; the mapped channels carry the DISPLAY
        # unit. Sources 3/4 are RoR channels — a rate converts by scale only.
        _t_raw = ms(t, qmc)
        if _t_raw is not None and qmc.mode == 'F':
            _t_raw = (convertRoRstrict(_t_raw, 'F', 'C') if t in (3, 4)
                      else fromFtoCstrict(_t_raw))
        # A failed ambient probe reports -1, which the plausibility band accepts as
        # a real temperature: it would add ~6% burner to the hold for the whole
        # preheat and poison the corpus weighting axis. Reject it explicitly, and
        # do not let a truthiness test turn a genuine 0.0 into the default either.
        return AmbientConditions(
            temp_ambient=self._ambient_or(_t_raw, 20.0),
            humidity    =self._ambient_or(ms(h, qmc), 50.0),
            pressure    =self._ambient_or(ms(p, qmc), 1013.25),
        )

    @staticmethod
    def _ambient_or(value: float | None, default: float) -> float:
        """Ambient channel reading, or the default when absent or sentinel."""
        if value is None:
            return default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(v) or v == -1.0:
            return default
        return v

    # ── Sampling cadence: measured, never assumed ────────────────────────
    def _sampling_dt(self) -> float:
        """Live sampling interval in seconds, read from Artisan.

        qmc.delay is in milliseconds and operator-settable from 100 ms upward.
        Every window, timeout and watchdog below is a duration, so all of them
        must follow it instead of a hard-coded 1 Hz assumption.
        """
        try:
            dt = float(getattr(self.aw.qmc, "delay", 1000.0)) / 1000.0
        except (TypeError, ValueError):
            return 1.0
        if not math.isfinite(dt) or dt <= 0.0:
            return 1.0
        return min(30.0, max(0.1, dt))

    def _apply_sampling_cadence(self) -> None:
        """Re-derive every cadence-dependent window from the live interval.

        Called at construction and at each start(): the operator can change the
        sampling rate between two preheats.
        """
        self.cfg.polling_dt = self._sampling_dt()
        dt = self.cfg.polling_dt
        self.ror_span_sec = getattr(self.aw.qmc, "deltaBTspan", 15.0)
        self.window_size = max(2, round(self.ror_span_sec / dt))
        self.short_window_size = max(2, round(self.cfg.ror_short_sec / dt))
        self.temp_history = deque(maxlen=self.window_size)
        self.time_history = deque(maxlen=self.window_size)
        self.temp_history_short = deque(maxlen=self.short_window_size)
        self.time_history_short = deque(maxlen=self.short_window_size)
        self._sensor_guard.limits = SensorSafetyLimits(
            stale_after_sec=max(3.5, dt * 3.5),
            min_ror_dt_sec=max(1.0, dt),
        )
        self._safety_watchdog.setInterval(max(250, int(dt * 500)))
        self._hold_integrator.max_dt_sec = max(2.5, dt * 2.5)
        detector = getattr(self, "_stabilisation_detector", None)
        if detector is not None:
            detector.polling_dt = dt

    def _control_clock(self) -> float:
        """Monotonic seconds on the same time base as the samples themselves.

        Accelerated profile replay advances the recorded profile faster than wall
        time. Dividing a replayed temperature delta by wall seconds returns N× the
        real slope, so the projection would brake N× too early and the simulated
        preheat would stall short of SV.
        """
        now = time.perf_counter()
        if getattr(self.aw, 'simulator', None) is None:
            return now
        try:
            speed = float(self.aw.qmc.timeclock.getBase()) / 1000.0
        except (AttributeError, TypeError, ValueError):
            return now
        return now * speed if speed > 0.0 else now

    def _stop_watchdog(self) -> None:
        """Stop the timer on the thread that owns it.

        cycle() — hence stop() and _trip_fault() — runs on Artisan's sampling
        thread, while the timer lives on the GUI thread. A direct stop() there is
        refused by Qt and leaves the timer armed for the life of the manager.
        """
        timer = self._safety_watchdog
        try:
            if timer.thread() is QThread.currentThread():
                timer.stop()
            else:
                QMetaObject.invokeMethod(timer, "stop", Qt.ConnectionType.QueuedConnection)
        except (RuntimeError, TypeError):
            _logd.exception("TilauPID could not stop its safety watchdog")

    def _precompute_targets(self) -> None:
        # All maths here are in °C.  cfg.target_sv is always stored in °C.
        target = self.cfg.target_sv

        # Hold power: physical first estimate, superseded by the learned per-SV
        # P_ss as soon as the corpus has evidence. Yields ~33.8% at 150 °C and
        # ~42.2% at 230 °C (cfg.p_ss_default is only the no-estimate fallback).
        self._base_hold_power = 18.0 + (target / 9.5)
        self._close_zone = target * 0.025   # ~5 °C at 200 °C

        _logd.debug(
            f"Preheat model (°C internal): "
            f"hold={self._base_hold_power:.1f}%  "
            f"(SV={self._to_native(target):.1f}°{self._unit()})"
        )

    def sv_native(self) -> float:
        """Target SV in the current Artisan display unit.

        cfg.target_sv is ALWAYS stored in °C internally; external readers
        (assistant preheat page, displayscope SV mirror / proximity check)
        must go through this accessor, never read cfg.target_sv raw.
        """
        return float(self._to_native(self.cfg.target_sv))

    def start(self, sv: float | None = None) -> None:
        # START can arrive both from the initial guided command and an
        # Artisan alarm a moment later. Treat it as idempotent while active: a
        # duplicate must not reset control state or reload historical profiles.
        if self.active:
            _logd.info("TilauPID duplicate START ignored: preheat is already active")
            return

        if sv is not None:
            # sv is received in the current Artisan unit; store internally in °C
            self.cfg.target_sv = self._to_c(sv)
            self._precompute_targets()
            self.aw.pidcontrol.setSV(int(sv))  # Artisan SV stays in native unit

        # Stamp the preheat SV (°C) onto qmc so getProfile writes it into the alog as
        # `tilau_preheat_sv_c` — the primary source the corpus reader trusts (no timex/event decode needed).
        self.aw.qmc.tilau_preheat_sv_c = float(self.cfg.target_sv)

        # Also mark the preheat start as an on-graph type-4 event. Deferred to the first
        # cycle(): at start() qmc.timex is still empty and EventRecordAction would drop the event.
        self._pending_start_sv_native = self.sv_native()

        # Re-derive every window from the interval in force NOW: this also
        # replaces the four sample deques, so no clear() is needed here.
        self._apply_sampling_cadence()
        # Reset the smoother so a reused instance gets a fresh full-power ramp
        # on the next preheat instead of slew-limiting up from a stale previous value.
        self.prev_power = -1
        self.prev_fan = -1
        # Cleared here, captured on the first valid cycle() (see _cycle_validated).
        self.ramp_start_temp = None
        self._hold_integrator.reset()
        self.start_time = time.perf_counter()
        # A new explicit start is the only operation that clears a
        # latched sensor fault. Any degraded session remains barred from
        # learning even if its sensor later recovers.
        self._sensor_guard.reset(self.start_time)
        self._learning_allowed = True
        self._fault_reason = None
        self.adaptive_start()

        # Resolve learned control-law parameters continuously at THIS SV.
        # P_ss and lead_sec are the only two knobs the law consumes; both are
        # persisted per-SV in QSettings and refined at _on_preheat_complete().
        self.p_ss, self.lead_sec = self.load_law_params()
        # Far-from-SV ramp is always the full (safety-capped) burner for FIR.
        self.computed_ramp_power = self.effective_max_burner()

        _logd.debug(
            f"Preheat starting → SV={self._to_native(self.cfg.target_sv):.1f}°{self._unit()} | "
            f"P_ss={self.p_ss:.1f}%  lead={self.lead_sec:.1f}s  "
            f"Kp={self.cfg.kp:.1f}%/°C  ramp_cap={self.computed_ramp_power:.0f}%"
        )
        # What the alog corpus implied for this SV (seed provenance) — lets the
        # operator sanity-check the model against past roasts before trusting it, incl. in sim.
        _logd.info(self.format_law_diagnostic())

        # Learning-maturity badge for the annotation: QSettings + corpus reads happen
        # once, here — never on the canvas redraw path (see _compute_learning_badge).
        self._compute_learning_badge()

        self.active = True
        # Profile replay has its own clock and may run faster than wall
        # time. The physical-sensor watchdog is therefore meaningful only on a
        # real input; malformed simulator values are still checked in cycle().
        if self.aw.simulator is None:
            self._safety_watchdog.start()
        else:
            self._safety_watchdog.stop()

    # ── Learning-maturity badge (EXPERIENCE band + capability lines) ───────
    # Built once per start(); the canvas annotation and the TilauScope window
    # only concatenate the cached HTML — no QSettings/corpus read on a redraw.

    # One block glyph per notch. A run of several widened the badge past the text
    # lines and stretched the whole annotation; a single glyph reads as a notch and
    # keeps the EXPERIENCE row narrower than the sentences below it.
    _BADGE_SEG_BLOCK: Final[str] = "&#9608;"

    @classmethod
    def _badge_segments_html(cls, fill_n: int, color: str) -> str:
        """4 segments drawn with block glyphs. Table cells with a px width/height and a
        background colour are NOT honoured by Qt's rich-text subset — the cell collapses
        to its glyph and the bar renders as a row of dots. Glyph runs always render."""
        seg = cls._BADGE_SEG_BLOCK
        gap = "&nbsp;"
        filled = gap.join(seg for _ in range(fill_n))
        empty = gap.join(seg for _ in range(4 - fill_n))
        parts = []
        if filled:
            parts.append(f'<span style="color:{color};">{filled}</span>')
        if empty:
            parts.append(f'<span style="color:#45475A;">{gap if filled else ""}{empty}</span>')
        return f'<span style="font-size:13px;">{"".join(parts)}</span>'

    @classmethod
    def _badge_capability_line(cls, marker: str, text: str) -> str:
        if not text:   # missing label set: a bare marker glyph says nothing
            return ""
        glyph = cls._BADGE_MARKER_GLYPH[marker]
        color = cls._BADGE_MARKER_COLOR[marker]
        return (
            f'<span style="color:{color};font-weight:bold;font-size:12px;">{glyph}</span>'
            f'<span style="color:#CDD6F4;font-size:11px;"> {text}</span>'
        )

    def _compute_learning_badge(self) -> None:
        """Resolve what the adaptive law knows about this SV into a fixed-geometry
        badge: a 4-step EXPERIENCE level (with its counter) and two independently
        resolved capability lines (holding power, braking anticipation).

        Reads QSettings and the alog corpus — must run here, once, never on the
        canvas redraw path. Any failure falls back to an empty badge rather than
        raising: a missing learning summary must never take the annotation down.
        """
        try:
            L = self.aw.qmc._tilau_labels
        except Exception:  # noqa: BLE001 - a missing label set must not block the annotation
            L = {}

        try:
            s = QSettings()
            sv = self.cfg.target_sv
            learned_p_ss, learned_lead, weight, provenance, prefixes = self._resolve_law_nodes(s, sv)
            seed_p_ss, seed_lead = self._seed_law_params_from_history()
            thermal_p_ss, thermal_lead = self._thermal_prior_params()

            n_updates = 0
            for prefix in prefixes:
                try:
                    n_updates += int(s.value(f"{prefix}/n_updates", 0, int) or 0)
                except (TypeError, ValueError):
                    continue

            is_exact = provenance.startswith("learned@")
            is_interp = provenance.startswith("interpolated:")
            is_edge = provenance.startswith("edge-blend@")
            has_seed_or_thermal = any(
                v is not None for v in (seed_p_ss, seed_lead, thermal_p_ss, thermal_lead))

            n_roasts = 0
            if is_exact and n_updates >= 5:
                level = "Calibrated"
            elif is_exact or is_interp:
                level = "Tuned"
            elif is_edge or has_seed_or_thermal:
                level = "Estimated"
                n_roasts = int(self.law_corpus_summary(sv).get("n_held_calibrated", 0) or 0)
            else:
                level = "Learning"

            def knob_marker(learned_val: float | None, seed_val: float | None,
                             thermal_val: float | None) -> str:
                # Both knobs share the same resolved node/weight; they diverge only
                # when there is no node and the per-knob seed/thermal prior differs
                # (_seed_law_params_from_history / _thermal_prior_params are each
                # independently Optional per knob) — that divergence is expected.
                if learned_val is not None:
                    return "check" if weight >= 0.5 else "approx"
                return "approx" if (seed_val is not None or thermal_val is not None) else "learning"

            hold_marker = knob_marker(learned_p_ss, seed_p_ss, thermal_p_ss)
            lead_marker = knob_marker(learned_lead, seed_lead, thermal_lead)

            self.learning_badge = {
                "level": level, "n_updates": n_updates, "n_roasts": n_roasts,
                "hold_marker": hold_marker, "lead_marker": lead_marker,
                "is_sim": getattr(self.aw, 'simulator', None) is not None,
            }
            self.learning_badge_html = self._build_learning_badge_html(L)
            self.learning_badge_compact_html = self._build_learning_badge_compact_html(L)
        except Exception:  # noqa: BLE001 - the annotation must degrade gracefully, never crash the canvas
            _logd.exception("TilauPID learning badge computation failed")
            self.learning_badge = None
            self.learning_badge_html = ""
            self.learning_badge_compact_html = ""

    def _build_learning_badge_html(self, L: dict) -> str:
        """EXPERIENCE band (segments + level/counter [+ sub-line]) and the two
        capability lines, as one cached HTML fragment for the canvas annotation."""
        b = self.learning_badge
        if not b:
            return ""
        level = b["level"]
        level_color = self._BADGE_LEVEL_COLOR[level]
        fill_n = 0 if b["is_sim"] else self._BADGE_LEVEL_FILL[level]
        segments = self._badge_segments_html(fill_n, level_color)

        sub_line = ""
        # A simulated preheat learns nothing, so the level colour would be a lie:
        # the caution yellow marks it as evidence that will not be kept.
        text_color = level_color
        if b["is_sim"]:
            level_text = L.get("SimNotRecorded", "Simulation — not recorded")
            text_color = self._BADGE_LEVEL_COLOR["Learning"]
        else:
            level_word = L.get(self._BADGE_LEVEL_LABEL_KEY[level], level)
            if level in ("Calibrated", "Tuned"):
                counter = L.get("CounterPreheats", "{n} preheats").format(n=b["n_updates"])
                level_text = f"{level_word} &middot; {counter}"
            elif level == "Estimated":
                # An edge-blend node, or a seed carried by the braking knob alone, can
                # reach this level with no calibrated hold to count. Announcing
                # "0 roasts" would contradict the level: the sub-line says it instead.
                level_text = level_word
                if b["n_roasts"] > 0:
                    counter = L.get("CounterRoasts", "{n} roasts").format(n=b["n_roasts"])
                    level_text = f"{level_word} &middot; {counter}"
                sub_line = L.get("EstimatedSub", "Adjusted from nearby setpoints")
            else:  # Learning: no evidence to count yet
                level_text = level_word
                sub_line = L.get("FirstPreheatSub", "First preheat at this setpoint")

        sub_line_html = (
            f'<div><span style="color:#6C7086;font-size:10px;">{sub_line}</span></div>'
            if sub_line else ""
        )
        cap_hold = self._badge_capability_line(
            b["hold_marker"], L.get(self._BADGE_HOLD_TEXT_KEY[b["hold_marker"]], ""))
        cap_lead = self._badge_capability_line(
            b["lead_marker"], L.get(self._BADGE_LEAD_TEXT_KEY[b["lead_marker"]], ""))

        # Segments and level word share one line: a two-column table would collapse
        # (Qt honours neither `width:100%` nor a px cell width in rich text).
        return f"""
                    <div style="margin-top:5px;"><span style="color:#6C7086;font-size:10px;">{L.get('Experience', 'EXPERIENCE')}</span></div>
                    <div>{segments}<span style="color:{text_color};font-weight:bold;font-size:11px;"> &nbsp;{level_text}</span></div>
                    {sub_line_html}
                    <div style="margin-top:4px;">{cap_hold}</div>
                    <div>{cap_lead}</div>
                    """

    def _build_learning_badge_compact_html(self, L: dict) -> str:
        """TilauScope window mirror: segments + the level word only — no counter,
        no room (see get_pid_status in displayscope.py)."""
        b = self.learning_badge
        if not b:
            return ""
        level = b["level"]
        level_color = self._BADGE_LEVEL_COLOR[level]
        fill_n = 0 if b["is_sim"] else self._BADGE_LEVEL_FILL[level]
        segments = self._badge_segments_html(fill_n, level_color)
        level_word = (L.get("SimNotRecorded", "Simulation — not recorded") if b["is_sim"]
                      else L.get(self._BADGE_LEVEL_LABEL_KEY[level], level))
        # Same rule as the canvas badge: a simulated run never wears a level colour.
        text_color = self._BADGE_LEVEL_COLOR["Learning"] if b["is_sim"] else level_color
        return (
            f'{segments}'
            f'<span style="color:{text_color};font-weight:bold;font-size:11px;"> &nbsp;{level_word}</span>'
        )

    def stop(self, reason: str = "operator_abort") -> None:
        """Stop preheating with an explicit safety/learning disposition.

        CHARGE is a bumpless hand-off to roast control and may learn, and so is
        `handover`, which passes a settled machine to the PID calibration with
        the burner left where it holds. Every other reason commands a safe
        burner zero; aborted or degraded sessions never train the persistent law.
        """
        was_active = self.active
        self._stop_watchdog()
        if was_active:
            # eventRecordActionSignal est en QueuedConnection — safe depuis le sémaphore ET hors sémaphore
            # signature : pyqtSignal(int, float, str, bool) → EventRecordActionSlot(eventtype, eventvalue, description, doupdategraphics)
            self.aw.qmc.eventRecordActionSignal.emit(
                4, 0.0, f"TilauPID Preheat stopped ({reason})", False)
            if reason in _BUMPLESS_STOP_REASONS and self._learning_allowed:
                # CHARGE calls us with qmc.profileDataSemaphore held: learning ends in two
                # full QSettings flushes, which would stall the sampling thread at the most
                # timing-critical moment. Nothing it reads is protected by that semaphore
                # (session state is PID-owned), so defer it one event-loop turn.
                QTimer.singleShot(0, self._deferred_preheat_complete)
        if reason not in {"charge", "handover"}:
            self._force_safe_output(reason)
        if reason not in _BUMPLESS_STOP_REASONS or not self._learning_allowed:
            self._clear_preheat_sv_marker()
        self.active = False
        # Drop any start marker that never fired (preheat aborted before its
        # first cycle) so it can't stamp a later, unrelated recording.
        self._pending_start_sv_native = None
        _logd.debug(f"Preheat PID stopped ({reason}).")

    def _deferred_preheat_complete(self) -> None:
        """Run the session's learning and persistence outside any caller's lock.

        Scheduled by stop(); the session state it reads is frozen because cycle()
        returns on `not self.active`. A new preheat started in between owns the
        state now, so the stale result is dropped rather than learned.
        """
        if self.active:
            _logd.debug("Deferred preheat learning dropped: a new session already started.")
            return
        try:
            self._on_preheat_complete()
        except Exception:  # noqa: BLE001 - an escaping exception would close the app
            _logd.exception("Deferred preheat learning failed")

    def _clear_preheat_sv_marker(self) -> None:
        """Drop the `tilau_preheat_sv_c` stamp from qmc.

        The key survives until the next reset(), so an aborted preheat finished by
        hand on the slider would still be saved as a guided one and mined as PID
        evidence — undoing, through the corpus, the learning ban set here.
        """
        try:
            self.aw.qmc.tilau_preheat_sv_c = None
        except AttributeError:
            pass

    def _force_safe_output(self, reason: str) -> None:
        """Command burner zero immediately, bypassing all output smoothing."""
        integrator = getattr(self, "_hold_integrator", None)
        if integrator is not None:
            integrator.reset()
        try:
            if self.prev_power != 0:
                self._update_artisan_slider(self.cfg.heater_slider, 0)
            self.prev_power = 0
        except Exception:  # noqa: BLE001 - a failed safe-off must not hide the original fault
            self.prev_power = -1
            _logd.exception(f"TilauPID safe-off command failed ({reason})")

    def _trip_fault(self, reason: str) -> None:
        """Latch a fault, cut heat and suppress all learning for the session."""
        if self._fault_reason is not None:
            return
        self._fault_reason = reason
        self._learning_allowed = False
        self._clear_preheat_sv_marker()
        self._sensor_guard.latch(reason)
        self._force_safe_output(reason)
        self.active = False
        self._stop_watchdog()
        self._pending_start_sv_native = None
        try:
            self.aw.qmc.eventRecordActionSignal.emit(
                4, 0.0, f"TilauPID SAFETY STOP: {reason}", False)
        except Exception:  # noqa: BLE001 - logging must not interfere with the safe state
            _logd.exception("TilauPID could not record its safety-stop event")
        try:
            if reason.startswith("control_exception"):
                message = QApplication.translate(
                    "Message", "Preheat stopped because its controller encountered an error.")
            elif reason == "sensor_timeout":
                message = QApplication.translate(
                    "Message", "Preheat stopped: no valid temperature reading was received.")
            else:
                message = QApplication.translate(
                    "Message", "Preheat stopped: the temperature reading is invalid.")
            self.aw.sendmessageSignal.emit(message, True, None)
        except Exception:  # noqa: BLE001 - operator notification is secondary to safe-off
            _logd.exception("TilauPID could not display its safety-stop message")
        _logd.error(f"TilauPID safety fault latched: {reason}")

    def _watchdog_tick(self) -> None:
        """Trip when the sampling loop no longer supplies valid measurements."""
        if not self.active or self.aw.simulator is not None:
            return
        reason = self._sensor_guard.stale_reason(time.perf_counter())
        if reason is not None:
            self._trip_fault(reason)


    def get_ror(self, current_t: float) -> float:
        """Append sample and return RoR in °C/min using real elapsed time.

        current_t is expected in the current Artisan unit (°C or °F).
        The history and returned RoR are always in °C/min internally.
        """
        now = self._control_clock()
        t_c = self._to_c(current_t)               # store in °C
        self.temp_history.append(t_c)
        self.time_history.append(now)
        # feed the short control window in lock-step
        self.temp_history_short.append(t_c)
        self.time_history_short.append(now)

        if len(self.temp_history) < 2:
            return 0.0

        dt_sec = self.time_history[-1] - self.time_history[0]
        if dt_sec <= 0:
            return 0.0

        # Both values are in °C (stored via _to_c), so delta is always °C/min
        return (self.temp_history[-1] - self.temp_history[0]) / (dt_sec / 60.0)

    def get_ror_short(self) -> float:
        """RoR (°C/min) over the short control window (~4s).

        Uses the freshest available slope so the projection reacts to the actual
        approach acceleration instead of the ~7s-lagged display RoR. Must be
        called AFTER get_ror() (which populates the short deque this cycle).
        """
        if len(self.temp_history_short) < 2:
            return 0.0
        dt_sec = self.time_history_short[-1] - self.time_history_short[0]
        if dt_sec <= 0:
            return 0.0
        return (self.temp_history_short[-1] - self.temp_history_short[0]) / (dt_sec / 60.0)

    def compute_fuzzy_power(
        self,
        t: float,
        ror: float,
        *,
        now: float | None = None,
    ) -> tuple[int, int]:
        """
        Returns (burner_power, fan_power) as percentages.

        t   : current temperature in the Artisan native unit (°C or °F).
        ror : SHORT-window RoR in °C/min (from get_ror_short) — the projection derivative.

 Proportional-on-projected-temperature law for a radiant FIR drum.
        The burner is a single continuous function of the projected error, so SV is
        the stable attractor (no relay, no positive hold above SV):

            t_proj = t + ror · (lead_sec / 60)      # anticipate actuator lag + FIR residual
            burner = clamp(0, max_burner, P_ss·ambient + Kp·(SV − t_proj) + I_hold)

        Far below SV the Kp term saturates the burner high; near SV it tapers to the
        steady hold P_ss; once t_proj crosses SV the term goes negative and the burner
        drops BELOW P_ss toward 0, letting the drum fall back to SV. A hard cut at
        SV+safety_margin remains as a rarely-hit backstop, not the operating point.
        """
        # All thresholds are in °C; convert incoming temperature once.
        t_c = self._to_c(t)
        sv = self.cfg.target_sv

        # ── Hard over-temperature backstop (safety net, not the set point) ──
        if t_c >= sv + self.cfg.safety_margin_c:
            self._hold_integrator.reset()
            return 0, (self.cfg.fan_brake_power if self.cfg.fan_enabled else 0)

        # ── Projected temperature: anticipate lag + FIR residual radiation ──
        t_proj = t_c + ror * (self.lead_sec / 60.0)
        proj_error = sv - t_proj                          # >0 below SV, <0 projected past SV
        # Published for the screens: the quantity the law steers on is what
        # explains a burner tapering while the drum is still short of target.
        # Read, never recomputed elsewhere — a second implementation would
        # eventually show a projection this law did not use.
        self.t_proj_c = t_proj

        ambient_factor = self._ambient_corrector.compute_factor(
            self.ambient_cache or AmbientConditions())

        # ── Continuous proportional law + slow hold-only integral ────────────
        base_burner = self.p_ss * ambient_factor + self.cfg.kp * proj_error
        integral = self._hold_integrator.update(
            error_c=sv - t_c,
            ror_c_per_min=ror,
            base_output_pct=base_burner,
            output_max_pct=self.effective_max_burner(),
            now=self._control_clock() if now is None else now,
        )
        burner = base_burner + integral
        burner = max(0.0, min(self.effective_max_burner(), burner))

        return int(round(burner)), 0


    def _update_artisan_slider(self, slider_nr: int, power: int) -> None:
        """
        Déplace le slider Artisan et enregistre l'événement.

        En mode simulateur :
          - moveslider() met à jour l'UI normalement.
          - EventRecordAction avec takeLock=True peut deadlocker si la sémaphore
            est tenue par sample_processing().  On utilise donc le signal queued
            (eventRecordActionSignal) dans tous les cas, et on saute fireslideraction
            qui enverrait une commande matérielle inexistante.
        """
        signal = getattr(self.aw, "tilaupidSliderCommandSignal", None)
        if signal is not None:
            # ApplicationWindow owns the signal and its receiving slot. Qt therefore
            # queues this complete UI/hardware transaction when cycle() runs in the
            # sampling worker, preserving command order without touching widgets here.
            signal.emit(slider_nr, power, getattr(self.aw, 'simulator', None) is None)
            return

        # Lightweight non-Qt harness compatibility. Production ApplicationWindow
        # always provides tilaupidSliderCommandSignal.
        self.aw.moveslider(slider_nr, power)
        self.aw.extraeventsactionslastvalue[slider_nr] = power
        ev_value = self.aw.qmc.eventsExternal2InternalValue(power)
        self.aw.qmc.eventRecordActionSignal.emit(slider_nr, ev_value, f"S{slider_nr}:{power}%", False)
        if getattr(self.aw, 'simulator', None) is None:
            self.aw.fireslideraction(slider_nr)


    def _smooth_burner(self, target: int) -> int:
        """Anti-chatter output conditioning for the burner command.

        Mitigates the ~1 Hz limit cycle caused by discrete RoR-band selection
        in compute_fuzzy_power (the 33↔63 swing). Two filters:
          - deadband: ignore sub-deadband changes so the burner stops twitching
            on tiny RoR fluctuations.
          - slew-rate limit: cap the per-cycle change to damp large swings.

        A full cut to 0 is ALWAYS honoured immediately (no deadband, no slew) so
        the safety backstop and the SV crossover take effect without delay. The
        re-engagement after a 0 is slew-limited, giving a soft restart.
        """
        prev = self.prev_power
        if prev < 0:                       # first cycle: nothing to smooth against
            return target
        if target == 0:                    # safety / SV cut: apply immediately
            return 0
        delta = target - prev
        if abs(delta) < self.cfg.burner_deadband:
            return prev
        slew = self.cfg.burner_slew_max
        if delta > slew:
            return prev + slew
        if delta < -slew:
            return prev - slew
        return target

    def cycle(self, t: float) -> None:
        """Main PID cycle.  t is in the current Artisan unit (°C or °F)."""
        if not self.active:
            return

        # Validate before recording the start event, calculating RoR,
        # or touching adaptive state. A rejected sample cuts heat immediately;
        # recovery requires three valid samples and re-enters through the normal
        # 12%-per-cycle slew limiter. Any exception is fail-safe, not log-only.
        try:
            t_c = self._to_c(t)
            decision = self._sensor_guard.evaluate(
                t_c,
                time.perf_counter(),
                burner_pct=max(0, self.prev_power),
                target_c=self.cfg.target_sv,
                # Accelerated replay is not a physical sensor: its
                # temperature delta cannot be divided by wall-clock time.
                temporal_checks=self.aw.simulator is None,
            )
            if not decision.control_allowed:
                self._learning_allowed = False
                if decision.latched:
                    self._trip_fault(decision.reason or "sensor_fault")
                else:
                    self._force_safe_output(decision.reason or "sensor_recovering")
                    _logd.warning(
                        f"TilauPID sample rejected: {decision.reason}; burner forced to 0%")
                return
            self._cycle_validated(t, t_c)
        except Exception as exc:  # noqa: BLE001 - the actuator must fail safe on every control error
            _logd.exception("TilauPID control-cycle exception")
            self._trip_fault(f"control_exception:{type(exc).__name__}")

    def _cycle_validated(self, t: float, t_c: float) -> None:
        """Run one control cycle after the canonical °C sample passed safety."""

        # Emit the deferred "Preheat started" marker now that a real sample has
        # landed (cycle() is driven by the sampling loop ⇒ qmc.timex is non-empty here),
        # so EventRecordAction actually persists it. Queued signal = thread-safe, no
        # semaphore deadlock. SV encoded to Artisan's internal event value for a clean
        # round-trip on read (see events_external/internal_to_value).
        if self._pending_start_sv_native is not None:
            sv_internal = self.aw.qmc.eventsExternal2InternalValue(round(self._pending_start_sv_native))
            self.aw.qmc.eventRecordActionSignal.emit(4, sv_internal, "TilauPID Preheat started", False)
            self._pending_start_sv_native = None

        # Climb-gauge baseline for the annotation: the first real sample on this
        # channel (t is already BT or ET, whichever cycle() was fed — see the
        # pidSource selection at the call site). qmc temps are still empty at start().
        if self.ramp_start_temp is None:
            self.ramp_start_temp = t

        #recompute ambients at every cycle if something is configured and accessible
        a = self.get_real_time_ambients()
        if a is not None and (self.ambient_cache is None or not(self.ambient_cache.temp_ambient == a.temp_ambient and self.ambient_cache.humidity == a.humidity and self.ambient_cache.pressure == a.pressure)):
            self.update_ambient(a.temp_ambient, a.humidity, a.pressure)
            self._refresh_learned()
            self.ambient_cache = a   # mémorise le dernier ambient pris en compte (maillon manquant)

        current_ror = self.get_ror(t)           # converts t to °C internally; returns °C/min (14s display window)
        control_ror = self.get_ror_short()      # fresh ~4s slope — drives the projection in the control law
        raw_burner, fan = self.compute_fuzzy_power(t, control_ror)
        # Smooth the raw command before applying AND before learning, so the
        # adaptive hold metric reflects what actually drove the roaster, not the
        # pre-filter target.
        burner = self._smooth_burner(raw_burner)
        self._on_cycle(t_c, current_ror, burner)

        if burner != self.prev_power:
            self._update_artisan_slider(self.cfg.heater_slider, burner)
            self.prev_power = burner
            _logd.debug(
                f"T:{t:.1f}°{self._unit()} RoR:{current_ror:.1f}°C/m → "
                f"Burner:{burner}% I_hold:{self._hold_integrator.correction:+.2f}%")

        if self.cfg.fan_enabled and fan != self.prev_fan:
            self._update_artisan_slider(self.cfg.fan_slider, fan)
            self.prev_fan = fan
            _logd.debug(f"T:{t:.1f}°{self._unit()} RoR:{current_ror:.1f}°C/m → Fan:{fan}%")

    def processcommand(self, cmd: str, value: str | None = None):
        if not cmd:
            return

        # Nettoyage et normalisation de la commande
        match cmd.upper().strip():
            case "START":
                # Conversion sécurisée de la valeur si présente
                try:
                    val = float(value) if value and value.strip() else None
                    self.start(val)  # val is in native unit; start() converts to °C
                except ValueError:
                    _logd.error(f"Valeur SV invalide pour START: {value}")
                    self.start() # Start avec la valeur par défaut

            case "STOP":
                self.stop()

            case "SV":
                if value:
                    try:
                        sv_native = float(value)
                        self.cfg.target_sv = self._to_c(sv_native)  # store in °C internally
                        self._precompute_targets() # Crucial pour la réactivité du PID
                        # A bias accumulated for one setpoint is invalid at another.
                        self._hold_integrator.reset()
                        # Resolve the continuous learned law immediately; keeping
                        # the previous SV's P_ss/lead until the next START would defeat the
                        # interpolation precisely when the operator adjusts the setpoint.
                        self.p_ss, self.lead_sec = self.load_law_params()
                        # Only a live preheat owns the marker: re-stamping it while
                        # stopped or faulted would re-declare a hand-driven session
                        # as guided in the saved profile.
                        if self.active:
                            self.aw.qmc.tilau_preheat_sv_c = float(self.cfg.target_sv)
                        # set artisan pid target in native unit
                        self.aw.pidcontrol.setSV(sv_native)
                        _logd.debug(f"SV mis à jour via Displayscope : {sv_native:.1f}°{self._unit()} ({self.cfg.target_sv:.1f}°C interne)")
                    except ValueError:
                        _logd.error(f"Valeur SV invalide : {value}")

            case "FAN":
                # Runtime toggle: FAN ON / FAN OFF
                if value and value.upper().strip() == "ON":
                    self.cfg.fan_enabled = True
                    _logd.debug("Fan-assist braking enabled.")
                elif value and value.upper().strip() == "OFF":
                    self.cfg.fan_enabled = False
                    if self.prev_fan != 0:
                        self._update_artisan_slider(self.cfg.fan_slider, 0)
                        self.prev_fan = 0
                    _logd.debug("Fan-assist braking disabled, damper closed.")

            case _:
                _logd.warning(f"Commande Displayscope inconnue : {cmd}")

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

"""The preheat controller's law (TilauPID), shared by the desktop and the Android tablet.

`PreheatLaw` holds the law's methods; the app's controller inherits it and gives it
its clock (`_control_clock`), its unit conversion (`_to_c`, `_to_native`, `_unit`),
its burner ceiling (`effective_max_burner`) and its state (cfg, p_ss, lead_sec, the
RoR windows, the hold integrator, the ambient). Standard library only.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, Final

_logd: Final[logging.Logger] = logging.getLogger("tilau")

#: The preheat target counts as reached inside this band, below or above it —
#: ready to charge, not merely close. Every screen that says the drum has arrived reads it here.
PREHEAT_BAND_C: Final[float] = 2.0
#: Below this gap to the target the approach has started; above it the drum is still far out.
PREHEAT_NEAR_C: Final[float] = 15.0
#: Past this a time to target has stopped meaning anything: the rate is near zero.
PREHEAT_ETA_CAP_S: Final[float] = 45 * 60.0


def preheat_eta(delta: float, rate: float | None) -> float | None:
    """Seconds to the target, or None when the climb does not support one.

    A tapering burner lets the rate sag well before the close band is reached;
    that is the anticipation working, not a stall, so it gets no number rather
    than a frozen one.
    """
    if rate is None or rate <= 0 or delta <= 0:
        return None
    seconds = delta / rate * 60.0
    return seconds if seconds <= PREHEAT_ETA_CAP_S else None


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


@dataclass
class AmbientConditions:
    """Conditions ambiantes au moment du démarrage de la torréfaction."""
    temp_ambient: float = 20.0      # °C
    humidity: float = 50.0          # %RH
    pressure: float = 1013.25       # hPa

    def is_valid(self) -> bool:
        # -1 is the "no reading" sentinel of every ambient source and sits inside
        # the plausible temperature band, unlike the humidity/pressure bands.
        return ( self.temp_ambient is not None and self.humidity is not None and self.pressure is not None and (
            self.temp_ambient != -1.0
            and -10 < self.temp_ambient < 50
            and 0 < self.humidity < 100
            and 800 < self.pressure < 1100
        ))


class AmbientCorrector:
    """
    Calcule un facteur correctif de puissance basé sur les conditions ambiantes.

    Modèle physique simplifié :
    ───────────────────────────
    La perte thermique d'un tambour est approximée par :
        Q_loss ∝ (T_drum - T_ambient)

    À température ambiante de référence (20°C), le hold power est calibré.
    Si T_ambient descend, les pertes augmentent → correction positive.
    L'humidité influence la capacité thermique de l'air (faible effet).
    La pression influence la densité de l'air (convection naturelle).

    Retourne un facteur multiplicatif centré sur 1.0.
    """

    REF_TEMP = 20.0         # °C de référence
    REF_HUMIDITY = 50.0     # %RH de référence
    REF_PRESSURE = 1013.25  # hPa de référence

    # Sensibilités empiriques (à affiner via les alogs)
    K_TEMP = 0.003          # 0.3% de correction par °C d'écart ambiant
    K_HUMIDITY = 0.0005     # 0.05% par %RH d'écart (effet mineur)
    K_PRESSURE = 0.0002     # 0.02% par hPa d'écart (très faible)

    def compute_factor(self, ambient: AmbientConditions) -> float:
        """
        Retourne un facteur multiplicatif à appliquer sur la puissance de hold.
        Ex : 0.97 = réduire de 3%, 1.04 = augmenter de 4%.
        """
        if not ambient.is_valid():
            return 1.0

        delta_temp = self.REF_TEMP - ambient.temp_ambient         # + si froid
        delta_humidity = ambient.humidity - self.REF_HUMIDITY     # + si humide
        delta_pressure = self.REF_PRESSURE - ambient.pressure     # + si basse pression

        factor = (
            1.0
            + self.K_TEMP * delta_temp
            + self.K_HUMIDITY * delta_humidity
            + self.K_PRESSURE * delta_pressure
        )
        # Borne ±15% pour éviter les corrections absurdes
        factor = max(0.85, min(1.15, factor))
        _logd.debug(
            f"AmbientCorrector: T={ambient.temp_ambient:.1f}°C "
            f"HR={ambient.humidity:.0f}% P={ambient.pressure:.0f}hPa "
            f"→ factor={factor:.4f}"
        )
        return factor


class PreheatLaw:
    """The law's methods, inherited by each app's preheat controller."""

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
        if not math.isfinite(burner):   # the clamp below would read NaN as the ceiling
            return 0, 0
        burner = max(0.0, min(self.effective_max_burner(), burner))

        return int(round(burner)), 0


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

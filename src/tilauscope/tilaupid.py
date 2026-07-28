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
import time
import types
from typing import Final,TYPE_CHECKING
from collections import deque
from dataclasses import dataclass

if TYPE_CHECKING:
    from artisanlib.main import ApplicationWindow

from PyQt6.QtCore import QSettings

from artisanlib.util import fromFtoCstrict, fromCtoFstrict
from tilauscope.tilaupid_adaptative import AdaptivePIDMixin, AmbientConditions, AmbientCorrector

_logd: Final[logging.Logger] = logging.getLogger("tilau")

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
    polling_dt: float = 1.0 # interval in seconds for PID updates, ideally matching the Artisan timer delay (default 1s)
    target_sv: float = 200.0 # target setpoint in °C (always stored internally in °C regardless of Artisan mode)
    ## TILAU ## HARD ceiling on burner power. This is a safety cap, not a tuning hint:
    ## effective_max_burner() clamps the learned adjustment DOWN to this value, so
    ## adaptive learning can only ever reduce it, never push above. Lowered 85→80
    ## after a radiant FIR drum reached 87% (learned) and tripped its thermal cutoff.
    max_burner: float = 80.0 # maximum burner power percentage during preheat (hard safety ceiling)
    soft_start_sec: float = 8.0 # duration in seconds for the soft start phase during ramp-up (default 8s, can be adjusted based on roaster response)
    ## TILAU ## Hard over-temperature backstop: °C above SV at which the burner is
    ## force-cut regardless of phase. Reclaims control well below the roaster's own
    ## hardware thermal cutoff.
    safety_margin_c: float = 2.0
    ## TILAU ## Output smoothing (anti-chatter, applied in cycle() via _smooth_burner):
    burner_deadband: int = 2   # %: ignore sub-deadband changes to kill ~1 Hz chatter (lowered 4→2 so the proportional hold can fine-trim toward SV)
    burner_slew_max: int = 12  # %/cycle: max burner change per cycle (a full cut to 0 is exempt)
    ## TILAU ## ── Proportional-on-projected-temperature control law ──────────────
    ## Replaces the old three-branch relay (ramp 80% / flat hold above SV / hard cut),
    ## whose above-SV positive hold made the drum park ~2°C hot and never settle to SV.
    ## The law is:  burner = clamp(0, max_burner, P_ss·ambient + Kp·(SV − t_proj))
    ## with t_proj = t + ror_short·(lead_sec/60).  SV is the stable attractor: below SV
    ## it saturates high, near SV it tapers to the steady hold P_ss, and once the
    ## PROJECTED temperature crosses SV it drops below P_ss toward 0 so the drum falls back.
    kp: float = 5.0                 # burner % per °C of projected error (saturates ~12°C out)
    p_ss_default: float = 20.0      # initial steady hold % near SV (learned per-SV thereafter)
    lead_sec_default: float = 5.0   # initial projection lead = response_lag + FIR residual tail
    lead_sec_min: float = 2.3       # floor on lead (≈ pure actuator response lag)
    lead_sec_max: float = 12.0      # ceiling on lead (anti timid-approach)
    ror_short_sec: float = 4.0      # short RoR window feeding the projection (NOT the 14s display RoR)
    fan_enabled: bool = False    # Set True to activate fan-assist inertia braking
    ## TILAU ## DEPRECATED — retired with the relay control law. No longer read by
    ## compute_fuzzy_power; kept only so legacy metric dataclasses populate without churn.
    zone_fuzzy_start: float = 0.87        # (unused)
    coast_lookahead_sec: float = 6.0      # (unused)
    # Fan / damper settings
    fan_brake_ror_threshold: float = 10.0    # °C/min: open fan above this RoR in fuzzy zone
    fan_brake_power: int = 45                # % damper opening during inertia braking
    fan_stabilise_power: int = 30            # % damper during hold phase (usually closed)

class TilauPreheatPID(AdaptivePIDMixin):
    def __init__(self, aw: 'ApplicationWindow', config: dict | None= None):
        self.aw = aw

        # ── Temperature unit helpers ──────────────────────────────────────────
        # All internal PID maths are in °C.  Artisan may be running in °F.
        # Use _to_c() to convert an incoming value to °C before processing,
        # and _to_native() to convert a °C value back to the Artisan unit for
        # display / logging.  Each helper reads self.aw.qmc.mode live on every
        # call, so a unit change at runtime is handled transparently.

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

        # target_sv from config is expected in the current Artisan unit; store internally in °C
        _raw_sv = tg.get("target_sv", self.aw.pidcontrol.sv)
        self.cfg = PIDConfig(target_sv=self._to_c(_raw_sv))   
        # Initialisation dynamique du RoR basée sur Artisan
          
        self.ror_span_sec = getattr(self.aw.qmc, "deltaBTspan", 15.0)
        self.window_size = max(2, int(self.ror_span_sec / self.cfg.polling_dt))
        self.temp_history: deque = deque(maxlen=self.window_size)
        self.time_history: deque = deque(maxlen=self.window_size)

        ## TILAU ## Short RoR window (control): the 14s display window lags ~7s and
        ## fires the cut too late on a fast radiant ramp. The control law projects
        ## temperature with a fresh ~4s derivative instead.
        self.short_window_size = max(2, int(self.cfg.ror_short_sec / self.cfg.polling_dt))
        self.temp_history_short: deque = deque(maxlen=self.short_window_size)
        self.time_history_short: deque = deque(maxlen=self.short_window_size)

        self.active = False
        self.prev_power = -1
        self.prev_fan = -1
        self.start_time = 0.0
        ## TILAU ## Native SV to stamp as the "Preheat started" marker, deferred to the
        ## first cycle() — at START time qmc.timex is still empty (OnRecorder just called
        ## resetTimer) and EventRecordAction silently drops events until the first sample.
        self._pending_start_sv_native: float | None = None

        # Ambients cache
        self.ambient_cache:AmbientConditions | None = None

        ## TILAU ## Control-law parameters (learned per-SV from history, loaded at start()):
        ##   p_ss    — steady hold power near SV; learned from roasts that plateaued ±0.5°C of SV
        ##   lead_sec— projection lead compensating actuator lag + FIR residual radiation;
        ##             learned from signed overshoot (overshoot → brake earlier)
        self.p_ss = self.cfg.p_ss_default        # % steady hold near SV
        self.lead_sec = self.cfg.lead_sec_default # s projection lead
        self.computed_ramp_power = 80.0          # burner % ceiling for the far-from-SV ramp

        #le fallback sur cfg fonctionne donc correctement au premier appel. Mais le threshold calculé à l'init n'intègre pas encore les corrections adaptatives. Ce n'est pas un bug — il sera recalculé au prochain start()
        # Variables pré-calculées
        self._precompute_targets()
        _logd.debug(
            f"Control law ready | display_win={self.ror_span_sec}s ctrl_win={self.cfg.ror_short_sec}s "
            f"SV={self._to_native(self.cfg.target_sv):.1f}°{self._unit()} "
            f"Kp={self.cfg.kp}%/°C "
            f"fan={'ON' if self.cfg.fan_enabled else 'OFF'}"
        )

        # ── Adaptive learning init ────────────────────────────────────────────
        # alog_dir : répertoire des fichiers .alog Artisan.
        settings = QSettings()
        self.alog_directory = settings.value('alogDirectory', "", str)

        
        self._adaptive_init(
            alog_dir=self.alog_directory,   
            window=c.get("adaptive_window", 10),
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
        return AmbientConditions(
            temp_ambient=ms(t, qmc) or 20.0,
            humidity    =ms(h, qmc) or 50.0,
            pressure    =ms(p, qmc) or 1013.25,
        )

    def _precompute_targets(self) -> None:
        # All maths here are in °C.  cfg.target_sv is always stored in °C.
        target = self.cfg.target_sv

        # Hold power: keep it modest — just enough to fight heat loss.
        # ~20% at 150 °C, ~28% at 230 °C.
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
        if sv is not None:
            # sv is received in the current Artisan unit; store internally in °C
            self.cfg.target_sv = self._to_c(sv)
            self._precompute_targets()
            self.aw.pidcontrol.setSV(int(sv))  # Artisan SV stays in native unit

        ## TILAU ## Robust learning key: stamp the preheat SV (°C, canonical unit) straight
        ## onto qmc so getProfile writes it into the alog as `tilau_preheat_sv_c`. This is
        ## the PRIMARY source the corpus reader trusts — it needs no timex, no event decode,
        ## and no mode conversion. Cleared on RESET; round-tripped on load.
        self.aw.qmc.tilau_preheat_sv_c = float(self.cfg.target_sv)

        ## TILAU ## Also mark the preheat start as an on-graph type-4 event (the visible
        ## "Preheat started" annotation + precise start index). DEFERRED to the first
        ## cycle(): start() runs synchronously inside OnRecorder right after resetTimer(),
        ## so qmc.timex is empty and EventRecordAction would drop the event (its guard needs
        ## len(timex) > 0). The SV is stored in Artisan's INTERNAL event encoding so it
        ## round-trips back to the true SV on read (raw native would decode to ~10× off).
        self._pending_start_sv_native = self.sv_native()

        self.temp_history.clear()
        self.time_history.clear()
        self.temp_history_short.clear()
        self.time_history_short.clear()
        ## TILAU ## Reset the smoother so a reused instance gets a fresh full-power ramp
        ## on the next preheat instead of slew-limiting up from a stale previous value.
        self.prev_power = -1
        self.prev_fan = -1
        self.start_time = time.perf_counter()
        self.adaptive_start()

        ## TILAU ## Load the learned control-law parameters for THIS SV bucket.
        ## P_ss and lead_sec are the only two knobs the law consumes; both are
        ## persisted per-SV in QSettings and refined at _on_preheat_complete().
        self.p_ss, self.lead_sec = self.load_law_params()
        # Far-from-SV ramp is always the full (safety-capped) burner for FIR.
        self.computed_ramp_power = self.effective_max_burner()

        _logd.debug(
            f"Preheat starting → SV={self._to_native(self.cfg.target_sv):.1f}°{self._unit()} | "
            f"P_ss={self.p_ss:.1f}%  lead={self.lead_sec:.1f}s  "
            f"Kp={self.cfg.kp:.1f}%/°C  ramp_cap={self.computed_ramp_power:.0f}%"
        )
        ## TILAU ## What the alog corpus implied for this SV (seed provenance) — lets the
        ## operator sanity-check the model against past roasts before trusting it, incl. in sim.
        _logd.info(self.format_law_diagnostic())

        self.active = True

    def stop(self) -> None:
        if self.active:
            # eventRecordActionSignal est en QueuedConnection — safe depuis le sémaphore ET hors sémaphore
            # signature : pyqtSignal(int, float, str, bool) → EventRecordActionSlot(eventtype, eventvalue, description, doupdategraphics)
            self.aw.qmc.eventRecordActionSignal.emit(4, 0.0, "TilauPID Preheat stopped", False)
            self._on_preheat_complete()
        self.active = False
        ## TILAU ## Drop any start marker that never fired (preheat aborted before its
        ## first cycle) so it can't stamp a later, unrelated recording.
        self._pending_start_sv_native = None
        _logd.debug("Preheat PID stopped.")


    def get_ror(self, current_t: float) -> float:
        """Append sample and return RoR in °C/min using real elapsed time.

        current_t is expected in the current Artisan unit (°C or °F).
        The history and returned RoR are always in °C/min internally.
        """
        now = time.perf_counter()
        t_c = self._to_c(current_t)               # store in °C
        self.temp_history.append(t_c)
        self.time_history.append(now)
        ## TILAU ## feed the short control window in lock-step
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

    def compute_fuzzy_power(self, t: float, ror: float) -> tuple[int, int]:
        """
        Returns (burner_power, fan_power) as percentages.

        t   : current temperature in the Artisan native unit (°C or °F).
        ror : SHORT-window RoR in °C/min (from get_ror_short) — the projection derivative.

        ## TILAU ## Proportional-on-projected-temperature law for a radiant FIR drum.
        The burner is a single continuous function of the projected error, so SV is
        the stable attractor (no relay, no positive hold above SV):

            t_proj = t + ror · (lead_sec / 60)      # anticipate actuator lag + FIR residual
            burner = clamp(0, max_burner, P_ss·ambient + Kp·(SV − t_proj))

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
            return 0, (self.cfg.fan_brake_power if self.cfg.fan_enabled else 0)

        # ── Projected temperature: anticipate lag + FIR residual radiation ──
        t_proj = t_c + ror * (self.lead_sec / 60.0)
        proj_error = sv - t_proj                          # >0 below SV, <0 projected past SV

        ambient_factor = self._ambient_corrector.compute_factor(
            self.ambient_cache or AmbientConditions())

        # ── Continuous proportional law ─────────────────────────────────────
        burner = self.p_ss * ambient_factor + self.cfg.kp * proj_error
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
        self.aw.moveslider(slider_nr, power)
        self.aw.extraeventsactionslastvalue[slider_nr] = power
        # Utilisation du signal pour éviter tout deadlock (queued connection, thread-safe)
        ## TILAU ## eventvalue MUST encode the actual power: EventRecordAction dedups on
        ## (type, value, string), so a constant value made every change after the first
        ## one collapse into the previous event and never get marked. Convert the 0–100%
        ## power to Artisan's internal event value exactly as recordsliderevent() does.
        ev_value = self.aw.qmc.eventsExternal2InternalValue(power)
        self.aw.qmc.eventRecordActionSignal.emit(slider_nr, ev_value, f"S{slider_nr}:{power}%", False)
        # En simulateur pas de matériel à piloter — fireslideraction enverrait une
        # commande série à un device fantôme et bloquerait le cycle.
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

        ## TILAU ## Emit the deferred "Preheat started" marker now that a real sample has
        ## landed (cycle() is driven by the sampling loop ⇒ qmc.timex is non-empty here),
        ## so EventRecordAction actually persists it. Queued signal = thread-safe, no
        ## semaphore deadlock. SV encoded to Artisan's internal event value for a clean
        ## round-trip on read (see events_external/internal_to_value).
        if self._pending_start_sv_native is not None:
            sv_internal = self.aw.qmc.eventsExternal2InternalValue(round(self._pending_start_sv_native))
            self.aw.qmc.eventRecordActionSignal.emit(4, sv_internal, "TilauPID Preheat started", False)
            self._pending_start_sv_native = None

        #recompute ambients at every cycle if something is configured and accessible
        a = self.get_real_time_ambients()
        if a is not None and (self.ambient_cache is None or not(self.ambient_cache.temp_ambient == a.temp_ambient and self.ambient_cache.humidity == a.humidity and self.ambient_cache.pressure == a.pressure)):
            self.update_ambient(a.temp_ambient, a.humidity, a.pressure)
            self._refresh_learned()
            self.ambient_cache = a   # mémorise le dernier ambient pris en compte (maillon manquant)

        current_ror = self.get_ror(t)           # converts t to °C internally; returns °C/min (14s display window)
        control_ror = self.get_ror_short()      # fresh ~4s slope — drives the projection in the control law
        raw_burner, fan = self.compute_fuzzy_power(t, control_ror)
        t_c = self._to_c(t)

        ## TILAU ## Smooth the raw command before applying AND before learning, so the
        ## adaptive hold metric reflects what actually drove the roaster, not the
        ## pre-filter target.
        burner = self._smooth_burner(raw_burner)
        self._on_cycle(t_c, current_ror, burner)

        if burner != self.prev_power:
            self._update_artisan_slider(self.cfg.heater_slider, burner)
            self.prev_power = burner
            _logd.debug(f"T:{t:.1f}°{self._unit()} RoR:{current_ror:.1f}°C/m → Burner:{burner}%")

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
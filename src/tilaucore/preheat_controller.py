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

"""TilauPID's sequence — start, one cycle per sample, stop, faults — shared by the desktop and the tablet.

`PreheatController` runs the law (`tilaucore.preheat`) and the learning
(`tilaucore.preheat_learning`) on the app's samples. The app gives it what is its
own: clock, sampling cadence, burner output, roast events, operator messages,
watchdog timer, the preheat mark on the roast, ambient readings, the badge's look.
Standard library only.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Final

from tilaucore.preheat import AmbientConditions, PreheatLaw, SlowHoldIntegrator
from tilaucore.preheat_learning import _BUMPLESS_STOP_REASONS, PreheatLearning
from tilaucore.preheat_safety import PreheatSensorGuard, SensorSafetyLimits

_logd: Final[logging.Logger] = logging.getLogger("tilau")


class PreheatController(PreheatLearning, PreheatLaw):
    """The preheat controller's sequence; the app's controller inherits it and gives the hooks."""

    # ── What the app gives the controller ─────────────────────────────────
    def _guard_clock(self) -> float:
        """Monotonic seconds for the sensor guard and the watchdog."""
        raise NotImplementedError

    def _display_ror_span(self) -> float:
        """The span of the RoR the operator reads, in seconds."""
        raise NotImplementedError

    def _apply_sampling_cadence(self) -> None:
        """Size every cadence-dependent window on the sampling interval in force."""
        raise NotImplementedError

    def _command_output(self, slider_nr: int, power: int) -> None:
        """Send a burner (or fan) percentage to the roaster and record it."""
        raise NotImplementedError

    def _record_event(self, value: float, text: str) -> None:
        """A preheat event on the roast (started, stopped, safety stop)."""

    def _record_start_marker(self, sv_native: float) -> None:
        """The "Preheat started" mark, with the first real sample."""

    def _notify_fault(self, reason: str) -> None:
        """Tell the operator the preheat stopped on a fault."""

    def _before_start(self) -> None:
        """What the app checks or sets before a preheat starts."""

    def _announce_target(self, sv: float) -> None:
        """The new target, in the app's unit, where the app shows it."""

    def _mark_preheat(self) -> None:
        """Stamp the preheat target on the roast (`tilau_preheat_sv_c`)."""

    def _clear_preheat_sv_marker(self) -> None:
        """Drop that stamp: the roast was not a guided preheat after all."""

    def _start_watchdog(self) -> None:
        """Arm the timer that trips the preheat when samples stop coming."""

    def _stop_watchdog(self) -> None:
        """Disarm it."""

    def _schedule_learning(self) -> None:
        """Run `_deferred_preheat_complete` once stop() has returned (the preheat is no longer active then)."""
        raise NotImplementedError

    def _after_safe_zero(self) -> None:
        """Anything the app must do once a safe zero was commanded."""

    def _render_learning_badge(self) -> None:
        """The badge's look, from `learning_badge`."""

    def get_real_time_ambients(self) -> AmbientConditions | None:
        """The room now, when a probe answers."""
        return None

    # ── State ─────────────────────────────────────────────────────────────
    def _init_controller_state(self) -> None:
        """The controller's state before its first start (the app's __init__ calls it once cfg is set)."""
        # Held by cycle(), stop() and _trip_fault(): no burner command can follow a safe zero.
        self._output_lock = threading.RLock()
        self.ror_span_sec: float = self._display_ror_span()
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

        self._before_start()

        if sv is not None:
            # sv is received in the current Artisan unit; store internally in °C
            self.cfg.target_sv = self._to_c(sv)
            self._precompute_targets()
            self._announce_target(sv)

        # Stamp the preheat SV (°C) on the roast: the roast file carries it as
        # `tilau_preheat_sv_c`, the source the corpus reader trusts.
        self._mark_preheat()

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
        self.start_time = self._guard_clock()
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
        self._start_watchdog()

    def _compute_learning_badge(self) -> None:
        """Resolve what the adaptive law knows about this SV into a fixed-geometry
        badge: a 4-step EXPERIENCE level (with its counter) and two independently
        resolved capability lines (holding power, braking anticipation).

        Reads QSettings and the alog corpus — must run here, once, never on the
        canvas redraw path. Any failure falls back to an empty badge rather than
        raising: a missing learning summary must never take the annotation down.
        """
        try:
            s = self._settings()
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
                "is_sim": self._simulated(),
            }
            self._render_learning_badge()
        except Exception:  # noqa: BLE001 - the annotation must degrade gracefully, never crash the canvas
            _logd.exception("TilauPID learning badge computation failed")
            self.learning_badge = None
            self.learning_badge_html = ""
            self.learning_badge_compact_html = ""

    def stop(self, reason: str = "operator_abort") -> None:
        """Stop preheating with an explicit safety/learning disposition.

        CHARGE is a bumpless hand-off to roast control and may learn, and so is
        `handover`, which passes a settled machine to the PID calibration with
        the burner left where it holds. Every other reason commands a safe
        burner zero; aborted or degraded sessions never train the persistent law.
        """
        with self._output_lock:
            was_active = self.active
            self._stop_watchdog()
            if was_active:
                self._record_event(0.0, f"TilauPID Preheat stopped ({reason})")
                if reason in _BUMPLESS_STOP_REASONS and self._learning_allowed:
                    # CHARGE calls us with qmc.profileDataSemaphore held: learning ends in two
                    # full QSettings flushes, which would stall the sampling thread at the most
                    # timing-critical moment. Nothing it reads is protected by that semaphore
                    # (session state is PID-owned), so defer it one event-loop turn.
                    self._schedule_learning()
            if reason not in {"charge", "handover"}:
                self._force_safe_output(reason)
                self._after_safe_zero()
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

    def _force_safe_output(self, reason: str) -> None:
        """Command burner zero immediately, bypassing all output smoothing."""
        integrator = getattr(self, "_hold_integrator", None)
        if integrator is not None:
            integrator.reset()
        try:
            if self.prev_power != 0:
                self._command_output(self.cfg.heater_slider, 0)
            self.prev_power = 0
        except Exception:  # noqa: BLE001 - a failed safe-off must not hide the original fault
            self.prev_power = -1
            _logd.exception(f"TilauPID safe-off command failed ({reason})")

    def _trip_fault(self, reason: str) -> None:
        """Latch a fault, cut heat and suppress all learning for the session."""
        with self._output_lock:
            if self._fault_reason is not None:
                return
            self._fault_reason = reason
            self._learning_allowed = False
            self._clear_preheat_sv_marker()
            self._sensor_guard.latch(reason)
            self._force_safe_output(reason)
            self._after_safe_zero()
            self.active = False
            self._stop_watchdog()
            self._pending_start_sv_native = None
            try:
                self._record_event(0.0, f"TilauPID SAFETY STOP: {reason}")
            except Exception:  # noqa: BLE001 - logging must not interfere with the safe state
                _logd.exception("TilauPID could not record its safety-stop event")
            try:
                self._notify_fault(reason)
            except Exception:  # noqa: BLE001 - operator notification is secondary to safe-off
                _logd.exception("TilauPID could not display its safety-stop message")
            _logd.error(f"TilauPID safety fault latched: {reason}")

    def _watchdog_tick(self) -> None:
        """Trip when the sampling loop no longer supplies valid measurements."""
        if not self.active or self._simulated():
            return
        reason = self._sensor_guard.stale_reason(self._guard_clock())
        if reason is not None:
            self._trip_fault(reason)


    def cycle(self, t: float) -> None:
        """Main PID cycle.  t is in the current Artisan unit (°C or °F)."""
        with self._output_lock:
            self._cycle(t)

    def _cycle(self, t: float) -> None:
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
                self._guard_clock(),
                burner_pct=max(0, self.prev_power),
                target_c=self.cfg.target_sv,
                # Accelerated replay is not a physical sensor: its
                # temperature delta cannot be divided by wall-clock time.
                temporal_checks=not self._simulated(),
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

        # The "Preheat started" marker, recorded with the first real sample.
        if self._pending_start_sv_native is not None:
            self._record_start_marker(self._pending_start_sv_native)
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
            self._command_output(self.cfg.heater_slider, burner)
            self.prev_power = burner
            _logd.debug(
                f"T:{t:.1f}°{self._unit()} RoR:{current_ror:.1f}°C/m → "
                f"Burner:{burner}% I_hold:{self._hold_integrator.correction:+.2f}%")

        if self.cfg.fan_enabled and fan != self.prev_fan:
            self._command_output(self.cfg.fan_slider, fan)
            self.prev_fan = fan
            _logd.debug(f"T:{t:.1f}°{self._unit()} RoR:{current_ror:.1f}°C/m → Fan:{fan}%")

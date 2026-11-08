# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""AUTO: the live plan executed on the levers, shared by the desktop and the tablet.

AUTO never chases a RoR gap. At each milestone it sets the phase's plan levers; after the
turning point the burner follows `Heater Ramp`, the air `Air Ramp` from mid-Maillard, and in
development `Dev Ramp` brings the burner down (rate-limited, never back up) and the air up.
A ramp step fires only when BT crosses its threshold going up. It marks Dry end and First
crack itself, drops at the plan's drop temperature after a 10 s countdown, sets the roaster's
cooling and disarms. Any lever move it did not make pauses it; so do a crash before
development and stale data. In development a crash raises the air by stages (the net).

The screen is the host (`AutoHost`): it reads and sets the levers, marks the milestones,
beeps and words what happened. Levers are named by the host's own ids (`ids`), so the
desktop keys them by slider index and the tablet by name.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Hashable
from typing import Any, Final, Protocol

from tilaucore.guidance_steps import DEV_STAGE
from tilaucore.milestones import MILESTONE_HALF_C

_log = logging.getLogger("tilaucore.autopilot")

TICK_FAIL_MAX: Final = 3            # failed ticks in a row before handing back (1 Hz)
DROP_CONFIRM_TICKS: Final = 3       # BT held at the drop target this many ticks before the countdown
DROP_COUNTDOWN_S: Final = 10.0
CHARGE_SETTLE_S: Final = 8.0        # after a milestone: its button actions are not the operator's hand
DEV_RATE_PCT_PER_MIN: Final = 5.0   # fastest burner descent in the exothermic window
DEV_RATE_WINDOW_S: Final = 75.0     # exothermic window, FC → FC + 75 s
NET_STEP_PCT: Final = 5.0           # one stage of the net, on the air
NET_CADENCE_S: Final = 30.0         # the air answers in 20-40 s: no stage on an effect not yet seen
NET_MAX_STAGES: Final = 3
NET_ROR_BACK_C: Final = 0.5         # °C/min regained: the RoR picks up, the net stops
TP_GRACE_S: Final = 45.0            # the RoR recovers from the charge dip: unreadable until then

# plan keys of the per-phase lever values
LEVER_KEYS: Final = {
    "air": "Airflow (%) (Dry|Mai|Dev)",
    "drum": "Drum Speed (%) (Dry|Mai|Dev)",
    "extractor": "Extraction (%) (Dry|Mai|Dev)",
}
PHASE_COL: Final = {"DRY": 0, "MAI": 1, "DEV": 2}
_HEATER_KEY: Final = "Heater (%) (Dry|Mai|Dev)"


class AutoHost(Protocol):
    """What AUTO needs from the screen running it."""

    ids: dict[str, Hashable]   # 'air', 'drum', 'extractor', 'burner' -> the host's lever id
    plan: dict | None
    context: Any               # the roaster (RoasterContext): heater ceilings, drum lock, cooling

    def t_now(self) -> float: ...
    def phase(self) -> str | None: ...   # 'DRY', 'MAI', 'DEV', None outside them; read live
    def read(self, lever: Hashable) -> float | None: ...
    def apply(self, lever: Hashable, pct: float) -> bool: ...
    def step(self, lever: Hashable) -> float: ...
    def has_extractor(self) -> bool: ...
    def moved(self, lever: Hashable) -> None: ...
    def report(self, kind: str, **data: Any) -> None: ...
    def on_state(self, state: str, lag_s: float | None) -> None: ...
    def crash(self, ror: float, dev_mode: bool, raise_burner: bool) -> str | None: ...
    def mark(self, which: str) -> None: ...
    def beep(self) -> None: ...
    def original_mark(self, index: int) -> bool | None: ...
    def extractor_mode(self, mode: str) -> None: ...


# ── Plan readers ─────────────────────────────────────────────────────────────

def plan_heater_pct(plan: dict | None, phase: str) -> float | None:
    """The phase's planned burner ('70% | 60% | 40%'), None when absent or unreadable."""
    try:
        col = PHASE_COL.get(phase)
        if col is None or not plan:
            return None
        parts = str(plan.get(_HEATER_KEY, "")).split(" | ")
        return float(parts[col].strip().rstrip("%"))
    except (ValueError, IndexError, TypeError):
        return None


def next_ramp_bt(plan: dict | None, keys: tuple[str, ...], bt: float) -> float | None:
    """BT of the next step of the ramps `keys` above bt, None without one."""
    nxt: float | None = None
    try:
        for key in keys:
            for step in (plan or {}).get(key) or []:
                thr = float(step["bt"])
                if thr > bt and (nxt is None or thr < nxt):
                    nxt = thr
    except (TypeError, ValueError, KeyError):
        return None
    return nxt


def heater_ramp_crossed(plan: dict | None, bt_prev: float, bt_now: float) -> tuple[float, int] | None:
    """The `Heater Ramp` step whose BT was just crossed going up (bt_prev < threshold <= bt_now).
    Going up only: at charge the probe plunges through every threshold towards the turning
    point, and that descent must never fire a step. None when none was crossed this tick."""
    if bt_now <= bt_prev:
        return None
    hit: tuple[float, int] | None = None
    try:
        for step in (plan or {}).get("Heater Ramp") or []:
            thr = float(step["bt"])
            if bt_prev < thr <= bt_now:
                hit = (thr, int(step["heater"]))   # the tick's last threshold
    except (TypeError, ValueError, KeyError):
        return None
    return hit


def entry_ramp_crossed(plan: dict | None, key: str, bt_prev: float, bt: float) -> dict | None:
    """The highest step of ramp `key` crossed going up this tick. Absolute values: a BT jump
    over a step lands on the right setting. Serves `Dev Ramp` and `Air Ramp`."""
    if bt <= bt_prev:
        return None
    hit: dict | None = None
    try:
        for step in (plan or {}).get(key) or []:
            thr = float(step["bt"])
            if bt_prev < thr <= bt:
                hit = step
    except (TypeError, ValueError, KeyError):
        return None
    return hit


def crash_readable(t_now_sec: float, t_tp_sec: float) -> bool:
    """Drying is judged only after the turning point: the charge dip is not a crash."""
    return t_tp_sec > 0.0 and t_now_sec - t_tp_sec >= TP_GRACE_S


def dev_air_step(target: float, current: float) -> float | None:
    """The next air stage towards the plan's target. The air never comes back down."""
    return current + DEV_STAGE if target - current >= DEV_STAGE else None


def burner_may_rise(plan: dict | None, t_now_sec: float, t_fcs_sec: float) -> bool:
    """A coffee never roasted is the only one caught up on the burner, within the first minute
    after first crack. A learned coffee keeps its burner (Tilau, 2026-11-02)."""
    return ((plan or {}).get("Plan Confidence", "grid only") == "grid only"
            and t_now_sec - t_fcs_sec <= 60.0)


def milestone_due(which: str | None, suggested: bool, bt: float, dry_end_temp: float,
                  fc_temp: float, *, tp_seen: bool, scale: float = 1.0,
                  original: bool | None = None) -> bool:
    """AUTO marks a milestone when the detector calls it. Without a call, a simulation
    takes the original's own mark; live, BT leaving the detector's window decides.
    Nothing else moves the phase while AUTO is armed."""
    if which is None:
        return False
    if suggested:
        return True
    if original is not None:
        return original
    target = dry_end_temp if which == "DE" else fc_temp
    return tp_seen and target > 0 and bt >= target + MILESTONE_HALF_C * scale


# ── The pilot ────────────────────────────────────────────────────────────────

class AutoPilot:
    """AUTO's state (off / armed / paused) and decisions for one roast session."""

    def __init__(self, host: AutoHost) -> None:
        self.host = host
        self.state: str = "off"
        self.expected: dict[Hashable, float] = {}     # lever -> value AUTO set (its echo)
        self.slider_last: dict[Hashable, float] = {}  # last value seen (operator takeover)
        self.bt_prev: float | None = None             # previous tick's BT (ramp crossed going up)
        self.settle_until: float = 0.0                # milestone seam: grace window, no pause
        self.tick_failures: int = 0
        self.automark_done: set[str] = set()          # "DE"/"FC", once each
        self.cool_end_c: float | None = None          # COOL END threshold after AUTO's cooling, °C
        self.drop_deadline: float | None = None       # monotonic time of the auto-drop
        self.drop_confirm: int = 0                    # ticks in a row with BT at the drop target
        self.drop_cancelled: bool = False             # cancelled: never re-armed this session
        self.dev_heater_pending: float | None = None  # burner target queued (monotone)
        self.dev_rate_anchor: tuple[float, float] | None = None  # (t at FC, burner %)
        self.net_ror: float | None = None             # RoR at the last net stage; None = at rest
        self.net_stages: int = 0
        self.net_last: float = 0.0                    # monotonic time of the net's last stage

    # ── Session ──────────────────────────────────────────────────────────────

    def reset_session(self) -> None:
        """A new assistant session: nothing carried over from the last roast."""
        self.automark_done.clear()
        self.cool_end_c = None
        self.drop_deadline = None
        self.drop_confirm = 0
        self.drop_cancelled = False

    def watch_ids(self) -> tuple[Hashable, ...]:
        ids = self.host.ids
        return tuple(dict.fromkeys((ids["air"], ids["drum"], ids["extractor"], ids["burner"])))

    def max_burner(self) -> float:
        """The roaster's declared burner ceiling (roasters.json), 100 without one."""
        return float(getattr(self.host.context, "heater_max_pct", 100.0) or 100.0)

    def max_dev_burner(self) -> float:
        """The burner ceiling in development: above it the outside of the bean colours too fast."""
        return min(self.max_burner(),
                   float(getattr(self.host.context, "dev_heater_max_pct", 100.0) or 100.0))

    def set_state(self, state: str, lag_s: float | None = None) -> None:
        self.state = state
        if state == "armed":
            self.tick_failures = 0   # each arming starts with a clean slate
        if state != "armed":
            # The auto-drop countdown is an absolute deadline. Left set over a pause it was
            # already past on re-arming: the roast dropped at the next tick with no countdown,
            # no beep and no Cancel. The target must be held again and the 10 s won back.
            self.drop_deadline = None
            self.drop_confirm = 0
        if state == "off":
            self.expected.clear()
            self.dev_heater_pending = None
            self.dev_rate_anchor = None
            self.net_ror = None
            self.net_stages = 0
        self.host.on_state(state, lag_s)

    def resync(self) -> None:
        """Lever observation back on their current values: no surprise move when arming or resuming."""
        self.expected.clear()
        self.bt_prev = None   # never a phantom crossing after a resync
        for lever in self.watch_ids():
            v = self.host.read(lever)
            if v is not None:
                self.slider_last[lever] = v

    def arm(self, phase: str | None) -> str | None:
        """Select AUTO: 'resumed' from a pause (levers left as they are), 'armed' from off (the
        current phase's levers set at once, after the 'armed' report), None when already armed.
        The screen checks its own gates (an active session, a plan) before calling."""
        if self.state == "armed":
            return None
        if self.state == "paused":
            self.resync()
            self.set_state("armed")
            # A setting made by hand during the pause becomes the development burner's reference.
            # No phase levers: they stay as left.
            if phase == "DEV":
                self.start_phase("DEV")
            self.host.report("armed")
            return "resumed"
        self.resync()
        self.set_state("armed")
        self.host.report("armed")
        _log.info("AutoPilot: armed")
        if phase is not None:
            self.apply_phase(phase)
            self.start_phase(phase)   # armed during the roast
        return "armed"

    def cancel_drop(self) -> bool:
        """The operator cancels the auto-drop countdown: the drop is then by hand for this roast."""
        if self.drop_deadline is None:
            return False
        self.drop_deadline = None
        self.drop_confirm = 0
        self.drop_cancelled = True
        _log.info("AutoPilot: auto-DROP cancelled by operator")
        return True

    # ── Milestones ───────────────────────────────────────────────────────────

    def milestone(self, phase: str, now: float | None = None) -> None:
        """A milestone was marked and the phase is `phase` ('DRY', 'MAI', 'DEV', 'DROP',
        'COOL'), after the live plan was re-anchored on it. `now`: monotonic, this module's clock by default."""
        if self.state != "armed":
            return
        now = time.monotonic() if now is None else now
        if phase in PHASE_COL:
            # The mark fires the machine's button action, which may move a lever: without this
            # grace window AUTO read it as a takeover and paused at the milestone.
            self.settle_until = now + CHARGE_SETTLE_S
            self.apply_phase(phase)
            self.start_phase(phase)
        elif phase in ("DROP", "COOL"):
            self.apply_cooling()

    def start_phase(self, phase: str) -> None:
        """Entering a phase (milestone or resume). In development: the burner rate-limit anchor
        (t at FC, burner now), the burner queue emptied, the net back at rest."""
        # The bean may reach the mark past the plan's temperature: the steps it already
        # crossed in the previous phase still apply on the next tick.
        plan = self.host.plan
        ramp = plan.get({"MAI": "Air Ramp", "DEV": "Dev Ramp"}.get(phase, ""), []) if plan else []
        if ramp and self.bt_prev is not None:
            self.bt_prev = min(self.bt_prev, min(float(s["bt"]) for s in ramp) - 0.1)
        if phase != "DEV":
            return
        try:
            t0 = float(self.host.t_now())
            b0 = self.host.read(self.host.ids["burner"])
            self.dev_rate_anchor = (t0, float(b0)) if b0 is not None else None
            self.dev_heater_pending = None
            self.net_ror = None
            self.net_stages = 0
        except Exception:  # noqa: BLE001 - a failed anchor must not stop the milestone
            _log.warning("AutoPilot: start_phase failed", exc_info=True)

    def plan_levers(self, phase: str) -> list[tuple[Hashable, float]]:
        """(lever, plan %) for the phase. The burner within the roaster's ceiling; the extractor
        only with one present; the drum set at charge then locked on machines whose speed jumps
        (context.drum_midroast_locked: on the Skywalker a 5 % step upsets the mass's inertia)."""
        out: list[tuple[Hashable, float]] = []
        col = PHASE_COL.get(phase)
        plan, ids = self.host.plan, self.host.ids
        if col is None or not plan:
            return out
        extractor = self.host.has_extractor()
        drum_locked = getattr(self.host.context, "drum_midroast_locked", True)
        # In development a Dev Ramp carries air and burner gradually from the Maillard values:
        # setting them here would jump at first crack.
        dev_ramp_governs = phase == "DEV" and bool(plan.get("Dev Ramp"))
        for lever, key in LEVER_KEYS.items():
            if lever == "extractor" and not extractor:
                continue
            if lever == "drum" and drum_locked and phase != "DRY":
                continue   # drum fixed after charge on this machine
            if lever == "air" and dev_ramp_governs:
                continue   # air carried by the Dev Ramp; the extractor is set here, at FC
            try:
                parts = str(plan.get(key, "")).split(" | ")
                out.append((ids[lever], float(parts[col].strip().rstrip("%"))))
            except (ValueError, IndexError, TypeError):
                continue
        # The burner follows the ramp from the turning point (Heater Ramp in Maillard, Dev Ramp in
        # development): set only at charge, never a jump at dry end or first crack.
        heater_governed = dev_ramp_governs or (phase == "MAI" and bool(plan.get("Heater Ramp")))
        if not heater_governed:
            h = plan_heater_pct(plan, phase)
            if h is not None:
                out.append((ids["burner"], min(h, self.max_burner())))
        return out

    def _pose(self, lever: Hashable, pct: float) -> float | None:
        """Set a lever the human way; the value it took (read back), None when not set."""
        if not self.host.apply(lever, pct):
            return None
        rb = self.host.read(lever)
        self.expected[lever] = rb if rb is not None else pct
        return self.expected[lever]

    def apply_phase(self, phase: str) -> None:
        """The phase's plan levers, set at the milestone (event driven, never on the hot path)."""
        if self.state != "armed":
            return
        moves: list[tuple[Hashable, float]] = []
        for lever, pct in self.plan_levers(phase):
            cur = self.host.read(lever)
            if cur is not None and abs(cur - pct) < 1.0:
                continue
            took = self._pose(lever, pct)
            if took is not None:
                moves.append((lever, took))
        if moves:
            for lever, _pct in moves:
                self.host.moved(lever)
            self.host.report("phase", phase=phase, moves=moves)
            _log.info(f"AutoPilot: phase {phase} feedforward → {moves}")

    def apply_dev_step(self, step: dict) -> bool:
        """One development ramp step (burner down, air up, extractor gently up), extractor only
        with one present. True when a lever moved (the ramp comes before anything else)."""
        ids = self.host.ids
        pokes: list[tuple[Hashable, float]] = []
        if "heater" in step:
            pokes.append((ids["burner"], min(float(step["heater"]), self.max_burner())))
        if "airflow" in step:
            pokes.append((ids["air"], float(step["airflow"])))
        if self.host.has_extractor() and "extraction" in step:
            pokes.append((ids["extractor"], float(step["extraction"])))
        moves: list[tuple[Hashable, float]] = []
        for lever, val in pokes:
            cur = self.host.read(lever)
            if cur is not None and abs(cur - val) >= 1.0:
                took = self._pose(lever, val)
                if took is not None:
                    self.host.moved(lever)
                    moves.append((lever, took))
        if moves:
            self.host.report("dev_step", moves=moves)
            _log.info(f"AutoPilot: dev ramp step → {moves}")
        return bool(moves)

    def dev_heater_dispense(self, t_now: float) -> bool:
        """'Hold the burner' (bench 2026-07-11): the queued burner target delivered MONOTONE
        (never back up this way) and rate-limited in the exothermic window FC → FC + 75 s (the
        fast cut crashes 41 % of roasts, the gentle one 16 %). A step crossed too fast is
        deferred, never skipped. Called on each development tick. True when the burner moved."""
        target_p = self.dev_heater_pending
        if target_p is None:
            return False
        burner = self.host.ids["burner"]
        cur = self.host.read(burner)
        if cur is None:
            return False
        if cur <= target_p + 0.5:
            self.dev_heater_pending = None   # already there (operator or plan)
            return False
        floor = 0.0
        if self.dev_rate_anchor is not None:
            t0, b0 = self.dev_rate_anchor
            if t_now <= t0 + DEV_RATE_WINDOW_S:
                # linear descent budget from the start of development
                floor = max(0.0, b0 - DEV_RATE_PCT_PER_MIN * (t_now - t0) / 60.0)
        target = min(max(float(target_p), floor), self.max_burner())
        if target >= cur:
            return False   # monotone: the budget allows no step yet
        full = target <= float(target_p) + 1e-6
        # < 2 % does nothing on a loaded drum: wait for the budget, except for the last step
        # that reaches the target exactly (>= 1 %).
        if (cur - target) < (1.0 if full else 2.0):
            return False
        step = self.host.step(burner)
        if round(target / step) * step >= cur:
            # the lever's notch would hold the burner, or step it up: wait
            if full:
                self.dev_heater_pending = None   # nearest notch already held
            return False
        if self._pose(burner, target) is None:
            return False
        self.host.moved(burner)
        self.host.report("devfire", burner=target)
        if full:
            self.dev_heater_pending = None
        _log.info(f"AutoPilot: dev burner rate-limited → {target:.0f}% "
                  f"(pending {target_p:.0f}%, floor {floor:.0f}%)")
        return True

    def net_step(self, lever: Hashable, delta: float, ceiling: float) -> float:
        """Move a lever of the net (its echo expected). The way it went."""
        cur = self.host.read(lever)
        if cur is None:
            return 0.0
        target = max(0.0, min(ceiling, cur + delta))
        if abs(target - cur) < 1.0 or not self.host.apply(lever, target):
            return 0.0
        rb = self.host.read(lever)
        self.expected[lever] = rb if rb is not None else target
        self.host.moved(lever)
        return (rb if rb is not None else target) - cur

    def net_tick(self, crash_msg: str | None, ror: float, mode: str, raise_burner: bool = False) -> None:
        """The development net (Tilau, 2026-11-02): the air rises by 5 % stages while the RoR does
        not pick up, and never comes back down. The burner stays where it is, except with
        raise_burner (see burner_may_rise), where it follows the air."""
        now = time.monotonic()
        back = NET_ROR_BACK_C * (1.8 if mode == 'F' else 1.0)
        if crash_msg is None and (self.net_ror is None or ror >= self.net_ror + back):
            self.net_ror = None
            return
        if self.net_stages >= NET_MAX_STAGES or now - self.net_last < NET_CADENCE_S:
            return
        self.net_last = now
        self.net_ror = ror
        self.net_stages += 1
        self.dev_heater_pending = None   # the burner comes down no more this roast
        ids = self.host.ids
        if raise_burner:
            self.net_step(ids["burner"], NET_STEP_PCT, self.max_dev_burner())
        if self.net_step(ids["air"], NET_STEP_PCT, 100.0):
            self.host.report("net", crash=crash_msg, step=NET_STEP_PCT)
            _log.info(f"AutoPilot net: crash — air +{NET_STEP_PCT:.0f}%")

    def apply_cooling(self) -> None:
        """DROP marked: the roaster's cooling (roasters.json; the beans are out, the drum lock no
        longer applies), COOL END armed under its threshold, then disarmed."""
        if self.state != "armed":
            return
        ids = self.host.ids
        extractor = self.host.has_extractor()
        # The roaster's own cooling; undeclared, only the burner is cut.
        cooling = getattr(self.host.context, "cooling", None)
        levers = {ids["burner"]: cooling.burner_pct if cooling else 0.0}
        if cooling is not None:
            levers.update({lever: pct for lever, pct in (
                (ids["air"], cooling.air_pct), (ids["drum"], cooling.drum_pct),
                (ids["extractor"], cooling.extractor_pct if extractor else None)) if pct is not None})
        self.cool_end_c = cooling.end_below_c if cooling else None
        moves: list[tuple[Hashable, float]] = []
        for lever, pct in levers.items():
            cur = self.host.read(lever)
            if cur is not None and abs(cur - pct) < 1.0:
                continue
            if self.host.apply(lever, pct):
                moves.append((lever, pct))
        if extractor and cooling is not None and cooling.extractor_mode:
            self.host.extractor_mode(cooling.extractor_mode)
        self.set_state("off")
        self.host.report("cooling", moves=moves)
        _log.info(f"AutoPilot: DROP cooling feedforward → {moves} — disarmed")

    # ── The tick ─────────────────────────────────────────────────────────────

    def tick(self, bt: float, ror: float | None, *, t_now: float,
             t_tp: float, t_fcs: float, confirmed_dev: bool, pending: str | None,
             suggested: bool, dry_end_temp: float, fc_temp: float, mode: str,
             scale: float) -> None:
        """Each refresh (1 Hz), O(1): takeover → pause, crash guard, milestones, auto-drop, then
        the ramp step due. Outside the roast phases (host.phase() None: preheat above all) AUTO
        only watches: the preheat PID drives the burner, and reading it as a hand paused AUTO.
        The phase is read live at each step: a milestone marked here may change it at once."""
        if self.state != "armed":
            return
        host = self.host
        in_roast = host.phase() in PHASE_COL
        # ── takeover: a move AUTO did not expect is the operator's hand → pause ──
        for lever in self.watch_ids():
            v = host.read(lever)
            if v is None:
                continue
            last = self.slider_last.get(lever)
            self.slider_last[lever] = v
            if not in_roast or last is None or v == last:
                continue   # preheat/idle: followed silently, never a pause
            exp = self.expected.get(lever)
            if exp is not None and abs(v - exp) <= 0.5:
                self.expected.pop(lever, None)   # the echo of AUTO's own move
            elif lever == host.ids["extractor"] and abs(v - last) < 2.0:
                # the AirWave PID's ±1 % dithering: automation noise, not a hand
                continue
            elif time.monotonic() < self.settle_until:
                # milestone seam: a handoff or a button action, not the operator: followed
                continue
            else:
                self.set_state("paused")
                host.report("paused", reason="takeover")
                _log.info(f"AutoPilot: manual input on lever {lever} ({last}→{v}) — paused")
                return
        if not in_roast:
            return
        # ── crash guard, before any move. In development the net holds the burner and
        # raises the air by 5 %; before, a crash pauses and the operator follows the message.
        net_hold = False   # the net at work: no descent, milestones still go on
        if ror is not None:
            rise = confirmed_dev and burner_may_rise(host.plan, t_now, t_fcs)
            crash = None
            if host.phase() != "DRY" or crash_readable(t_now, t_tp):
                crash = host.crash(ror, confirmed_dev, rise)
            if confirmed_dev:
                self.net_tick(crash, ror, mode, rise)
                # during a crash: no burner descent, but milestones and the auto-drop go on
                # (BT at the target → drop, above all in a crash)
                net_hold = self.net_ror is not None
            elif crash:
                self.set_state("paused")
                host.report("paused", reason="crash", crash=crash)
                _log.info("AutoPilot: RoR crash detected — paused")
                return
        # ── milestones: a fresh detector call is marked at once while armed ──
        if (pending is not None and pending not in self.automark_done
                and milestone_due(pending, suggested, bt, dry_end_temp, fc_temp, tp_seen=t_tp > 0.0,
                                  scale=scale, original=host.original_mark(1 if pending == "DE" else 2))):
            self.automark_done.add(pending)
            host.mark(pending)
            host.report("marked", which=pending)
            _log.info(f"AutoPilot: milestone {pending} auto-marked")
            return
        # ── auto-drop: in development, once BT holds the live plan's drop target, a 10 s
        # countdown with Cancel, then DROP. Once: cancelled, never re-armed this session.
        if host.phase() == "DEV" and confirmed_dev and not self.drop_cancelled:
            now = time.monotonic()
            orig_drop = host.original_mark(6)
            if orig_drop:
                self.drop_cancelled = True   # once
                host.mark("DROP")
                host.report("drop_marked")
                _log.info("AutoPilot: DROP auto-marked at the original's")
                return
            try:
                drop_t = float((host.plan or {}).get("Drop Temp") or 0.0)
            except (TypeError, ValueError):
                drop_t = 0.0
            at_target = orig_drop is None and drop_t > 0 and bt >= drop_t
            if self.drop_deadline is None:
                # One sample does not drop a roast: the target must hold DROP_CONFIRM_TICKS ticks.
                self.drop_confirm = (self.drop_confirm + 1) if at_target else 0
                if self.drop_confirm >= DROP_CONFIRM_TICKS:
                    self.drop_deadline = now + DROP_COUNTDOWN_S
                    host.beep()
                    _log.info(f"AutoPilot: plan drop target {drop_t:.1f}° held "
                              f"{self.drop_confirm} ticks — auto-DROP countdown")
            if self.drop_deadline is not None:
                left = self.drop_deadline - now
                if left > 0:
                    host.report("drop_in", seconds=int(left) + 1)
                elif at_target:
                    self.drop_deadline = None
                    self.drop_cancelled = True   # once
                    host.mark("DROP")
                    host.report("drop_marked")
                    _log.info("AutoPilot: DROP auto-marked")
                else:
                    # BT back under the target during the countdown: no drop on a target no
                    # longer reached, and the operator did not cancel: it may arm again.
                    self.drop_deadline = None
                    self.drop_confirm = 0
                    host.report("drop_stood_down")
                    _log.info(f"AutoPilot: auto-DROP stood down — BT {bt:.1f}° "
                              f"back below target {drop_t:.1f}°")
        # ── burner ramp, keyed on BT, applied when the threshold is crossed going up only.
        # The charge descent fires nothing; drying's burner comes from the phase levers,
        # the ramp only brings it down later.
        ramp_acted = False
        prev = self.bt_prev
        self.bt_prev = bt
        plan = host.plan
        if host.phase() in ("DRY", "MAI"):
            hit = heater_ramp_crossed(plan, prev, bt) if prev is not None else None
            if hit is not None:
                thr, heater = hit
                heater = min(float(heater), self.max_burner())
                burner = host.ids["burner"]
                cur = host.read(burner)
                if cur is not None and abs(cur - heater) >= 1.0 and self._pose(burner, heater) is not None:
                    host.report("ramp", burner=heater, at=thr)
                    host.moved(burner)
                    ramp_acted = True
                    _log.info(f"AutoPilot: ramp step crossed at BT {thr:.0f} → burner {heater:.0f}%")
            # ── Maillard air ramp (a gentle rise to clear the smoke) ──
            if host.phase() == "MAI" and prev is not None:
                ahit = entry_ramp_crossed(plan, "Air Ramp", prev, bt)
                if ahit is not None and self.apply_dev_step(ahit):
                    ramp_acted = True
        # ── development ramp (learned trajectory): burner down, air up as BT crosses the
        # thresholds; the burner is never set direct but queued monotone and delivered
        # rate-limited (<= 5 %/min in the exothermic window).
        elif host.phase() == "DEV" and self.drop_deadline is None and not net_hold:
            if prev is not None:
                dhit = entry_ramp_crossed(plan, "Dev Ramp", prev, bt)
                if dhit is not None:
                    dhit = {k: v for k, v in dhit.items() if k not in ("bt", "_f")}
                    h = dhit.pop("heater", None)
                    a = dhit.pop("airflow", None)
                    cur_air = host.read(host.ids["air"])
                    next_air = dev_air_step(a, cur_air) if a is not None and cur_air is not None else None
                    if next_air is not None:
                        dhit["airflow"] = next_air
                    if h is not None and self.net_stages == 0:
                        p = self.dev_heater_pending
                        self.dev_heater_pending = float(h) if p is None else min(p, float(h))
                    if dhit:
                        ramp_acted = self.apply_dev_step(dhit)
            if not ramp_acted:
                ramp_acted = self.dev_heater_dispense(t_now)

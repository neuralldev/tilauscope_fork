# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The guided mode and AUTO on the tablet (android/GUIDED-SPEC.md), on the desktop's engines.

AUTO is tilaucore.autopilot with the tablet as its host; the guided bubble asks for the plan's
steps through tilaucore.guidance_steps, with the desktop's windows and estimates. A RoR crash
is tilaucore.guidance_crash in every mode. Words are English (decision 6).
"""

from collections import deque
from collections.abc import Hashable
from typing import Any

from tilaucore.autopilot import AutoPilot, crash_readable
from tilaucore.guidance_crash import CrashDetector
from tilaucore.guidance_steps import GestureTrack, gesture_steps, no_burner_step, plan_steps

NOW_WINDOW_C = 1.0            # "Now" means the bean is on the step (the desktop's)
FIRST_CRACK_WINDOW_C = 10.0   # first crack soon: within this of its target (the desktop's)
ROR_HISTORY = 64
LEVER_WORDS = {"burner": "Burner", "air": "Air", "drum": "Drum", "extractor": "Extractor"}
PHASE_OF = {"DRY": "Drying", "MAI": "Maillard", "DEV": "Development"}


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _eta_s(bt: float, target: float, ror: float | None, ror_end: float | None = None) -> float | None:
    """Seconds to `target` at the RoR now, or easing towards ror_end (the desktop's estimates)."""
    if ror is None or ror <= 0.5:
        return None
    delta = target - bt
    if delta <= 0:
        return 0.0
    if ror_end is None or ror_end <= 0.0 or ror_end >= ror:
        return delta / ror * 60.0
    return delta / max(0.3, (ror + ror_end) / 2.0) * 60.0


def crash_words(dev: bool, raise_burner: bool) -> tuple[str, str]:
    if dev and raise_burner:
        return "The roast is losing speed", "Air and burner up one step"
    if dev:
        return "The roast is losing speed", "Air up one step · leave the burner"
    return "The roast is losing speed", "Air up one step, then the burner if it does not pick up"


class Pilot:
    """AUTO's host on the tablet: the levers through the machine, the marks through the session."""

    ids = {"air": "air", "drum": "drum", "extractor": "extractor", "burner": "burner"}

    def __init__(self, demo, plan: dict, context: Any) -> None:
        self.demo, self.plan, self.context = demo, plan, context
        self.engine = AutoPilot(self)
        self.flash: dict[str, float] = {}     # lever -> roast time AUTO moved it
        self.event = {"seq": 0, "text": None}  # the latest move, for the screen's toast
        self.drop_in: int | None = None       # the auto-drop countdown, seconds
        self.beeps = 0
        self._crash: str | None = None

    # The host (tilaucore.autopilot.AutoHost)
    def t_now(self) -> float:
        return self.demo.roast_time()

    def phase(self) -> str | None:
        return self.demo.roast_phase()

    def read(self, lever: Hashable) -> float | None:
        value = self.demo.levers.get(lever)
        return None if value is None else float(value)

    def apply(self, lever: Hashable, pct: float) -> bool:
        if lever not in self.demo.levers:
            return False
        value = max(0, min(100, int(round(pct))))
        if lever == "extractor":
            self.demo.pilot_extractor(value)
        else:
            self.demo._lever(lever, value)  # noqa: SLF001 - the machine's own path, as a hand would
        return self.demo.levers[lever] == value

    def step(self, lever: Hashable) -> float:
        return float(self.demo.lever_setup[lever]["step"])

    def has_extractor(self) -> bool:
        return "extractor" in self.demo.levers

    def moved(self, lever: Hashable) -> None:
        self.flash[lever] = self.demo.now

    def report(self, kind: str, **data: Any) -> None:
        if kind == "drop_in":
            self.drop_in = data["seconds"]
            return
        self.drop_in = None
        text = self._words(kind, data)
        if text:
            self.event = {"seq": self.event["seq"] + 1, "text": text}

    def _words(self, kind: str, data: dict) -> str | None:
        def moves(items) -> str:
            return " · ".join(f"{LEVER_WORDS.get(lever, lever)} {pct:.0f} %" for lever, pct in items)
        if kind == "phase":
            return f"{PHASE_OF.get(data['phase'], data['phase'])} · {moves(data['moves'])}"
        if kind == "dev_step":
            return moves(data["moves"])
        if kind == "ramp":
            return f"Burner {data['burner']:.0f} %"
        if kind == "devfire":
            return f"Burner {data['burner']:.0f} %"
        if kind == "net":
            return f"Air +{data['step']:.0f} % · the roast is losing speed"
        if kind == "marked":
            return "Dry end marked" if data["which"] == "DE" else "First crack marked"
        if kind == "drop_marked":
            return "Drop marked"
        if kind == "cooling":
            return f"Cooling · {moves(data['moves'])}" if data["moves"] else "Cooling"
        if kind == "paused":
            return "Paused: the levers are yours" if data.get("reason") == "takeover" else "Paused: the roast is losing speed"
        if kind == "armed":
            return "Back on the levers" # the toast carries the AUTO tag
        return None

    def on_state(self, state: str, lag_s: float | None) -> None:
        if state != "armed":
            self.drop_in = None

    def crash(self, ror: float, dev_mode: bool, raise_burner: bool) -> str | None:
        return self.demo.crash_message(dev_mode, raise_burner)

    def mark(self, which: str) -> None:
        self.demo.auto_pilot_mark({"DE": "dry_end", "FC": "first_crack", "DROP": "drop"}[which])

    def beep(self) -> None:
        self.beeps += 1

    def original_mark(self, index: int) -> bool | None:
        return self.demo.replayed_mark({1: "dry_end", 2: "first_crack", 6: "drop"}[index])

    def extractor_mode(self, mode: str) -> None:
        self.demo.extractor_command("mode", mode)

    def view(self) -> dict:
        now = self.demo.now
        return {"state": self.engine.state, "drop_in": self.drop_in, "beeps": self.beeps,
                "flash": sorted(lever for lever, at in self.flash.items() if now - at < 10.0), **self.event}


class Guide:
    """The guided bubble over the curve while the plan is followed, and the crash bubble in every mode."""

    def __init__(self, plan: dict | None) -> None:
        self.plan = plan
        self.track = GestureTrack()
        self.crash = CrashDetector()
        self.ror_hist: deque[float] = deque(maxlen=ROR_HISTORY)
        self.crash_text: tuple[str, str] | None = None

    def crash_check(self, ror: float | None, phase: str | None, t_now: float, t_tp: float,
                    raise_burner: bool) -> tuple[str, str] | None:
        """Fed once a sample: the crash bubble's words, None without one."""
        if ror is None:
            return None
        self.ror_hist.append(ror)
        self.crash_text = None
        if phase is None or (phase == "DRY" and not crash_readable(t_now, t_tp)):
            return None
        if self.crash.fall(self.ror_hist, dt=1.0) is not None:
            self.crash_text = crash_words(phase == "DEV", raise_burner)
        return self.crash_text

    def bubble(self, *, phase: str | None, bt: float, ror: float | None, t_now: float, t_tp: float,
               levers: dict, steps: dict, targets: dict) -> dict | None:
        """What to do now, the desktop's card as a bubble; None when there is nothing to do."""
        if self.crash_text is not None:
            title, sub = self.crash_text
            return {"tone": "crash", "title": title, "sub": sub}
        if self.plan is None or phase is None:
            return None
        drop = targets.get("drop")
        if phase == "DRY" and t_tp <= 0:
            return None   # charge to turning point: nothing to read, nothing to do
        ror_target = targets.get("ror")
        due, ahead = gesture_steps(self.track, self._steps(levers), bt, NOW_WINDOW_C,
                                   {lever: levers.get(lever) for lever in ("air", "burner")}, steps,
                                   ror is not None and ror_target is not None and ror_target > 0 and ror > ror_target)
        due = no_burner_step(due, False)

        def words(step) -> str:
            return f"{LEVER_WORDS[step[1]]} {step[2]} %"
        if phase == "DRY":
            if due is None:
                return None
            sub = f"Now · next: {words(ahead).lower()} at {ahead[0]:.0f}°" if ahead else "Now"
            return {"tone": "guide", "title": words(due), "sub": sub}
        if phase == "MAI":
            fc = targets.get("first_crack")
            eta = _eta_s(bt, fc, ror) if fc else None
            if due is not None:
                sub = f"Now · first crack in about {_clock(eta)}" if eta else "Now"
                return {"tone": "guide", "title": words(due), "sub": sub}
            if fc and fc - bt <= FIRST_CRACK_WINDOW_C:
                return {"tone": "listen", "title": "Listen: first crack soon",
                        "sub": f"In about {_clock(eta)}" if eta else ""}
            return None
        if drop is None:
            return None
        if bt >= drop - NOW_WINDOW_C:
            return {"tone": "guide", "title": f"Drop at {drop:.0f}°", "sub": "Now"}
        if due is not None:
            return {"tone": "guide", "title": words(due), "sub": f"Now · drop at {drop:.0f}°"}
        eta = _eta_s(bt, drop, ror, targets.get("ror_drop"))
        return {"tone": "guide", "title": f"Drop at {drop:.0f}°", "sub": f"In about {_clock(eta)}" if eta else ""}

    def _steps(self, levers: dict) -> list:
        return [step for step in plan_steps(self.plan) if step[1] in levers]

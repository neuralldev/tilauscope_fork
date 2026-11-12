# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""Deterministic simulated roaster shared by the CLI and the Android screen.

One `advance(1)` is one simulated second; the Android service calls it once a
second while recording.
"""

import ast
from collections import deque
import json
import math
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import time
import uuid

from tilaucore.alog_index import _UUID_RE, _literal, _slice_value
from tilaucore.bean_edit import NUMBERS, REQUIRED_TO_CREATE, ZONES
from datetime import date
from tilaucore.beans import GreenBean, RoastTasting
from tilaucore.currency import CURRENCIES
from tilaucore import tasting_log
from tilaucore.flavour_wheel import FLAVOR_WHEEL_DATA
from tilaucore.roast_colour import get_agtron_color, roast_agtron
from tilaucore.roast_memory import last_roast
from tilaucore.roast_plan_view import english
from tilaucore.roast_colour import AGTRON_SCALES
from tilaucore.roast_label import label_data, lines_30mm

from . import alog, catalogue, config as configuration, machine, mqtt
from .automation import AutoMarks
from .follow import LEVER_OF, FollowedRoast, live as follow_live
from .alarms import (ANCHOR_WORDS, ARTISAN_ACTIONS, MARK_INDEX, Act, AlarmLists, TabletAlarms, from_unit, in_unit, rows_in_unit,
                     threshold_kind)
from tilaucore.alarms import (ANCHORS, NEW_ALARM, Alarm, TurningPoint, append_row, move_row, read_alrm, remove_row,
                              write_alrm)
from tilaucore.artisan_compat import events_internal_to_external_value
from tilaucore.ror import RoRSettings, rate_now
from tilaucore.roasters import RoasterManager
from .energy import TabletEnergy, bill as energy_bill, sheet as energy_sheet
from tilaucore.energy_model import EnergySession, PhaseBounds, phase_bounds
from tilaucore.artisan_setup import read_setup
from tilaucore.milestones import PROFESSION_DE_TRUE_C, PROFESSION_FC_TRUE_C
from tilaucore.drop_door import DoorState, DropDoor, parse_frame
from tilaucore.lever_response import LeverResponse
from tilaucore.roast_replay import Replay
from .preheat import INPUTS, TabletPreheat
from tilaucore.preheat import AmbientConditions
from .cave import Cave, chosen, lists, roast_setup, view
from .plan import LEVELS, ROAST_DESTINATION_KEYS, ROOM_DEFAULT, TabletPlan, apply_colour_gap, generate as plan_generate, view as plan_view
from .guided import Guide, Pilot
from tilaucore.autopilot import burner_may_rise
from .roasts import Roasts
from .journal import AMBIENT_KEYS, Journal, append_after_stop, recover
from .session import EXTRA_CHANNELS, Reading, Session


def _profile() -> list[float]:
    # Synthetic curve only: an RoR envelope integrated into BT, not a roast plan.
    knots = [(60, 0), (100, 18), (180, 18), (300, 14), (450, 10), (560, 7), (640, 5), (900, 3)]

    def ror(t: int) -> float:
        for (a, ra), (b, rb) in zip(knots, knots[1:]):
            if t <= b:
                return ra + (rb - ra) * (t - a) / (b - a)
        return 3

    bt, value = [], 92.0
    for t in range(901):
        if t < 60:
            bt.append(92 + 108 * (1 - math.sqrt(t / 60)))
        else:
            if t > 60:
                value += ror(t) / 60
            bt.append(value)
    return bt


PROFILE = _profile()

# Simulated machine: the level each lever starts from.
INITIAL_LEVERS = {"burner": 65, "air": 40, "drum": 70, "extractor": 20}


# Roast levels for the colour row: name, lowest and highest value, tint (shared SCA scale).
COLOUR_LEVELS = [(s.name, s.agtron_range.min_value, s.agtron_range.max_value, s.color_map) for s in AGTRON_SCALES]

CHOICE_FILE = "roast_choice.json" # the chosen coffee and its Roast Setup, kept across restarts
ROOM_MAX_AGE_S = 3.0 # an older ambient reading is no reading (as on the desktop)
MQTT_ROOM_MAX_AGE_S = 600.0 # an MQTT room sensor reports on change or every few minutes (MQTT-SPEC)
MQTT_MAX_PAYLOAD = 4096
# The crack counter's sequence (AUTOMATION-SPEC decision 11): each step, its code and its delay after its anchor
CRACK_CODES = {"cal1": 0x0000, "cal2": 0x0006, "start": 0x0001, "stop": 0x0002}
CRACK_DELAYS_S = {"cal1": 20, "cal2": 90, "start": 40} # after Start, after Dry end, after CAL2
CRACK_ACQUISITION_S = 30
LATE_SAMPLING_S = 2.0 # a tick this long after the previous one: the tablet fell behind (ACQUISITION-SPEC 1b)
LATE_SHOWN_S = 30.0 # the link pill tells it this long after the last late tick
TICK_MIN_S = 0.5 # a tick run right after a late one samples nothing new
_BOOT_CLOCK = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC) # Android's: it counts while the CPU sleeps
CHARGE_WARNING_S = 30 # a fast replay drops to 1× this long before its beans go in # each calibration listens this long

def _number(value) -> float | None:
    """A figure of the plan (text or number) as a float, None when there is none."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _said(tasting) -> str:
    """What was tasted, in the desktop's words: the defects, else the verdict with its thumb."""
    if tasting is None:
        return ""
    defects = [tasting_log.DEFECT_WORDS[d][1] for d in tasting.defects if d in tasting_log.DEFECT_WORDS]
    if defects:
        return ", ".join(defects)
    if tasting.verdict in tasting_log.VERDICT_WORDS:
        thumb, word = tasting_log.VERDICT_WORDS[tasting.verdict]
        return f"{thumb}  {word[1]}"
    return ""


def _tasted(tasting) -> str:
    """A roast's tasting as the desktop's Roasts tab recalls it: the verdict, then the defects."""
    if tasting is None:
        return ""
    verdict = tasting_log.VERDICT_WORDS.get(tasting.verdict)
    parts = [f"{verdict[0]}  {verdict[1][1]}" if verdict else ""]
    parts += [tasting_log.DEFECT_WORDS[d][1] for d in tasting.defects if d in tasting_log.DEFECT_WORDS]
    return " · ".join(p for p in parts if p)


def _tasting_words(unit: str) -> dict:
    """The desktop's tasting words, in the order the next change is chosen (tilaucore.tasting_log)."""
    return {"verdicts": [[key, f"{thumb}  {word[1]}"] for key, (thumb, word) in tasting_log.VERDICT_WORDS.items()],
            "defects": [[key, tasting_log.DEFECT_WORDS[key][1], *tasting_log.change_text(key, unit, english)]
                        for key in tasting_log.DEFECT_CHANGES],
            "same": [text[1] for text in tasting_log.NEXT_SAME], "tick": [text[1] for text in tasting_log.NEXT_TICK]}


def _memory(memory) -> dict | None:
    """The last roast of a coffee as the sheet shows it, in the desktop's words."""
    if memory is None:
        return None
    tasting = memory.tasting
    return {"count": memory.count, "epoch": memory.epoch, "level": memory.level, "weight_in_g": memory.weight_in_g,
            "dev_pct": memory.dev_pct, "loss_pct": memory.loss_pct, "colour": memory.colour,
            "colour_basis": memory.colour_basis, "verdict": tasting.verdict if tasting else None,
            "said": _said(tasting),
            "defects": list(tasting.defects) if tasting else [], "tasted": tasting.iso_date if tasting else "",
            "change": list(memory.change) if memory.change else None}


AIRWAVE_SPEED = (30, 100) # AirWaveLink.SPEED_MIN, SPEED_MAX


class Demo:
    def __init__(self, journal_path: str | None = None, config_path: str | None = None,
                 cave_directory: str | None = None) -> None:
        """With a journal path, an existing journal is restored read-only instead."""
        self.journal_path = journal_path
        self.journal: Journal | None = None
        self.config_path = config_path
        self.config = None
        if config_path:
            try:
                self.config = configuration.load(config_path)
            except ValueError:
                # Kept aside, as an unreadable journal: the app starts unconfigured, never blocked.
                os.replace(config_path, config_path + ".unreadable")
        apply_colour_gap((self.config or {}).get("machine"))
        self.cave = Cave(cave_directory) if cave_directory else None
        self.roasts = Roasts(str(Path(cave_directory).parent)) if cave_directory else None
        self.coffee: dict | None = None # the chosen coffee, kept from roast to roast
        self.setup: dict | None = None # its Roast Setup, kept from roast to roast
        self.choice_path = str(Path(config_path).with_name(CHOICE_FILE)) if config_path else None
        self.machine_log: list[str] = [] # what the roaster was told, in order
        # The real roaster (MACHINE-SPEC §7): its link's state for the screen, its last reading,
        # and the commands not yet handed to the link (they leave with the next snapshot).
        self.link: dict | None = None
        self.preheat: TabletPreheat | None = None # TilauPID, from the start of the roast to Charge
        # Built between roasts, as the desktop loads its preheat history at ON: Start then waits for nothing
        self._preheat_ready: tuple[tuple, TabletPreheat] | None = None
        self._preheat_store = str(Path(config_path).with_name("preheat_learning.json")) if config_path else None
        self.alarm_lists = AlarmLists(str(Path(config_path).with_name("alarms"))) if config_path else None
        self.alarms: TabletAlarms | None = None # the active list's run, from the start of the roast
        self.auto: AutoMarks | None = None # the milestones that mark themselves this roast (AUTOMATION-SPEC D1)
        # Follow (decision 13): the plan, or a recorded roast whose levers the next roast plays back
        self._follow = "hand" # this roast's: by hand, the plan or a roast, chosen at START
        self._follow_pick: tuple[str, str] | None = None # a roast picked by hand, else the coffee's reference ★
        self._replay_source: tuple[str, str] | None = None # the roast a simulation replays: also the one it follows
        self._replay_marks: dict[str, float] = {} # its own milestones, in replay time
        self._replay_charge_s: float | None = None # when the replayed roast's beans went in, in replay time
        self._slowed_for_charge = False
        self._followed: tuple[tuple, FollowedRoast] | None = None # the roast read, kept while it is the one
        self.playback = None # this roast's playback, from CHARGE until a hand takes the levers back
        self._follow_paused = False # the link dropped: the playback waits for the operator to resume it
        self._follow_tp = TurningPoint()
        self._tp = TurningPoint() # the roast's turning point, found live, drawn on the curve
        self._follow_extractor: deque = deque() # the speeds the playback sent and the AirWave has not confirmed yet
        self._auto_event = {"seq": 0, "kind": None, "milestone": None} # the latest, for the screen's toast
        self._plan_targets: dict | None = None # Dry end and FC this roast follows; None by hand
        self._live_plan: dict | None = None # the plan this roast follows, re-anchored at Dry end and FC (GUIDED-SPEC)
        self.guide: Guide | None = None # the guided bubble, and the crash in every mode
        self.pilot: Pilot | None = None # AUTO, chosen at START
        self._bubble: dict | None = None
        self._cracks: tuple[float, int] | None = None # the crack counter's last count and when it came
        # The drop door's contact on TilauAmbient (wiki/Drop-Door-Contact-Spec.md): armed for the app's life,
        # through dropped links; the last frame not yet applied, and when it was read on the roast clock.
        self._door = DropDoor()
        self._door_opened: float | None = None # the roast time the door opened, its DROP not yet marked
        self._door_seq = -1
        self._door_heard: float | None = None # clock() of the last door frame
        self._crack_sent: dict[str, float] | None = None # this roast's sequence: step -> when it was sent; None when off
        self._started_s = 0.0
        self._devices_out: list[dict] = [] # accessory commands (the extractor), for the service to send
        self._alarm_extractor: tuple[int, int] | None = None # (speed, alarm number) until the extractor confirms it
        self._alarm_undo: tuple[str, list] | None = None # the list before the last deleted alarm, for Undo
        self._live: tuple[float, Reading] | None = None
        self._outbox: list[str] = []
        # Simulation (SIM-SPEC S2): a recorded roast replayed in place of every device, at 1×, 2× or 8×
        self.replay: Replay | None = None
        self._replay_channels: list[tuple[int, str, str]] = [] # (device in the file, first channel, second)
        self._replay_cracks: int | None = None # the file's crack counter (TilauAmbient's tilau56, first channel)
        self.speed = 1
        self.replay_name = ""
        self._replay_moves: dict[str, list] = {} # the replayed roast's burner and air moves, in replay time
        self.response: LeverResponse | None = None # how this simulated roast answers the levers (SIM-SPEC S3)
        self._restore_choice()
        self.readonly = False
        self.levers: dict[str, int] = {}
        self.echo: dict[str, int] = {}
        self.pending: set[str] = set()
        self.clock = time.monotonic # replaced in tests
        self.real_clock = lambda: time.clock_gettime(_BOOT_CLOCK) # the roast's time; replaced in tests
        self._origin: float | None = None # real_clock() at roast time 0; None for a replay
        self._late: tuple[float, float] | None = None # the last late tick: (roast time, gap)
        self._room: tuple[float, dict] | None = None # last room reading and when it came
        self._extras: dict[str, tuple[float, float]] = {} # channel: (when, value)
        self._mqtt_raw: dict[str, tuple[float, str]] = {} # topic: (when, the last message)
        self.energy: TabletEnergy | None = None # a real roast's energy, START to STOP
        self._energy_bill: tuple | None = None # (what it was read on, its session and summary)
        self._planner: TabletPlan | None = None # kept while its history holds: its caches are the costly part
        self._planner_key: tuple | None = None
        self._plan_choice = {"plan_level": "", "roast_destination": "omni"} # before the first setup is saved
        self._apply_levers()
        if journal_path and Path(journal_path).exists():
            try:
                self.session, self.interrupted = recover(journal_path)
                self.signal = True
                samples = self.session.samples
                self.now = samples[-1].elapsed_s if samples else 0.0
                return
            except ValueError:
                # Keep the evidence aside; never block every later start on it.
                os.replace(journal_path, journal_path + ".unreadable")
        self.reset()

    def reset(self) -> str:
        """Discard the current session; the next one waits for start()."""
        self._end_preheat("operator_abort")
        self.preheat = None
        self.alarms = None
        self.auto = None
        self.energy = None
        self.guide = self.pilot = self._live_plan = self._bubble = None
        if self.journal:
            self.journal.close()
            self.journal = None
        if self.journal_path:
            Path(self.journal_path).unlink(missing_ok=True) # the finished roast is not restored again
        self.now = 0.0
        self.interrupted = False
        self.signal = True
        self.session = Session(simulated=True)
        if self.coffee and self.setup and self.setup["green"]:
            # the next roast of this coffee starts from its last weight, as Roast Setup proposes it on the desktop
            self.session.set_weight("green", self.setup["green"])
        self._warm_preheat()
        return self.snapshot()

    def _real(self) -> bool:
        """A roaster declared in Settings, with its machine: the tablet drives it instead of the simulation."""
        config = self.config or {}
        return bool(config.get("roaster") and config.get("machine")) and self.replay is None

    def simulate(self, data: str) -> str:
        """Replays a listed roast ({origin, name}) in place of the roaster and the accessories, from its start."""
        if self.session.state != "idle" or self.interrupted:
            raise ValueError("A roast is on screen: finish it first")
        request = json.loads(data)
        profile = ast.literal_eval(self.roasts.path(request["origin"], request["name"]).read_text(encoding="utf-8"))
        replay = Replay(profile)
        if replay.empty:
            raise ValueError("This roast has no curve to replay")
        names = {int(slot): name for slot, name in (profile.get("tilau_name_map") or {}).items()}
        known = {d[0]: (d[1], d[2]) for d in alog.EXTRA_DEVICES}
        self._replay_channels = [(slot, *known[name]) for slot, name in sorted(names.items()) if name in known]
        self._replay_cracks = next((slot for slot, name in names.items() if name == "tilau56"), None)
        self.replay, self.speed, self._speed_before_pause = replay, 1, 1
        timex, bt = profile.get("timex") or [], profile.get("temp2") or []
        first = next((i for i, v in enumerate(bt) if v != -1), 0) # the replay's 0, as Replay counts it
        self._replay_moves = {}
        for i, kind, value in zip(profile.get("specialevents") or [], profile.get("specialeventstype") or [],
                                  profile.get("specialeventsvalue") or []):
            lever = LEVER_OF.get(kind)
            if lever in ("burner", "air") and first <= i < len(timex):
                self._replay_moves.setdefault(lever, []).append((timex[i] - timex[first], events_internal_to_external_value(value)))
        self._levers_before = dict(self.levers) # what the replay's alarms and touches change, given back on Exit
        self._replay_source = (request["origin"], request["name"])
        charge = (profile.get("timeindex") or [-1])[0]
        self._replay_charge_s = timex[charge] - timex[first] if 0 <= charge < len(timex) else None
        marks = profile.get("timeindex") or []
        self._replay_marks = {name: timex[marks[slot]] - timex[first]
                              for name, slot in (("dry_end", 1), ("first_crack", 2), ("drop", 6))
                              if slot < len(marks) and 0 < marks[slot] < len(timex)}
        self.replay_name = replay.title or Path(request["name"]).stem
        self._warm_preheat() # with a roaster declared it is already built: its history stays
        return json.dumps({"title": self.replay_name})

    def _slow_before_charge(self) -> bool:
        """Once, 30 s before the replayed beans go in, a fast replay drops to 1×: time to touch Charge."""
        at = self._replay_charge_s
        if (self.replay is None or self.speed <= 1 or self._slowed_for_charge or at is None
                or "charge" in self.session.milestones or not at - CHARGE_WARNING_S <= self.now < at):
            return False
        self.speed, self._slowed_for_charge = 1, True
        return True

    def set_speed(self, speed: int) -> str:
        if speed not in (0, 1, 2, 8): # 0: paused, nothing is sampled until a speed is chosen again
            raise ValueError("The replay runs at 1×, 2× or 8×, or is paused")
        if speed == 0 and self.speed == 0: # pause touched again: back to the speed chosen before
            speed = self._speed_before_pause
        elif speed == 0:
            self._speed_before_pause = self.speed
        self.speed = speed
        return self.snapshot()

    def exit_simulation(self) -> str:
        """Back to the real roaster; a simulated roast in progress is dropped, never saved."""
        if self.replay is not None:
            self.levers = dict(self._levers_before)
            self.echo, self.pending = dict(self.levers), set()
        self.replay, self._replay_channels, self.speed = None, [], 1
        self._replay_source, self._replay_marks = None, {}
        self._extras.clear()
        return self.reset()

    def start(self, mode: str = "hand") -> str:
        """START, by hand, with the plan, on AUTO or following a roast: the one choice that sets alarms, AUTO and
        the probe. AUTO follows the plan and drives the levers (GUIDED-SPEC decision 2)."""
        targets = live = None
        if mode in ("plan", "auto"):
            try: # once, before the session starts: a plan that fails leaves no roast half started
                live = self._roast_plan()
            except Exception as error: # noqa: BLE001 - START refuses, as without a plan
                print(f"TilauScope roast plan failed: {error}")
            if live is None:
                raise ValueError("No plan ready: open Roast Setup › Plan")
            targets = {"dry_end": _number(live.get("End of Dry Temp")), "first_crack": _number(live.get("First Crack Temp"))}
        elif mode == "roast":
            if self._followed_roast() is None:
                raise ValueError("No roast to follow: star a reference roast, or pick one in Roasts")
        elif mode != "hand":
            raise ValueError("Start by hand, with the plan, on AUTO or following a roast")
        self.session.start(self.now)
        self._origin = self.real_clock() - self.now if self.replay is None else None
        self._late = None
        self._follow, self._plan_targets = mode, targets
        self._live_plan = live
        self.guide = Guide(self._live_plan)
        self.pilot = Pilot(self, self._live_plan, self._roast_context()) if mode == "auto" else None
        self._bubble = None
        self.session.simulated = not self._real()
        if self._real():
            self.link = {"name": self._roaster_name(), "state": "connecting", "recovered": False,
                         "connected_once": False}
            self._live = None # a cooling roaster's last reading is not this roast's: it starts once connected
        self.session.uuid = uuid.uuid4().hex
        self.session.started_epoch = time.time()
        self.session.tz_offset = time.timezone
        if self.coffee:
            self.session.title, self.session.beans = self.setup["title"], self.coffee["beans"]
            self.session.greens = {k: self.setup[k] for k in ("density", "moisture", "greens_temp", "beansize")}
        if self.journal_path:
            self.journal = Journal(self.journal_path, simulated=self.session.simulated, uuid=self.session.uuid,
                                   epoch=self.session.started_epoch, tz_offset=self.session.tz_offset,
                                   title=self.session.title, beans=self.session.beans, greens=self.session.greens)
        self._take_stock()
        self._slowed_for_charge = False
        self._tp = TurningPoint()
        self.response = LeverResponse(self._replay_moves) if self.replay is not None else None
        self._start_energy()
        self._start_preheat()
        self._start_follow()
        self._started_s = self.now
        self._crack_sent = {} if self._crack_listening() else None
        self._start_auto()
        self._start_alarms()
        if self.pilot is not None:
            self.pilot.engine.arm(None) # armed now; it acts from CHARGE
        self._sample()
        if self.journal and self.session.weights["green"] is not None:
            self.journal.weight("green", self.session.weights["green"], self.now)
        for lever, value in self.levers.items(): # the levels the roast starts from
            self._record(lever, value)
        return self.snapshot()

    def _take_stock(self) -> None:
        """At the start, the green weight leaves the stock (Roast Setup's box), once; never given back."""
        grams = self.session.weights["green"]
        if not (self.coffee and self.setup["decrease"] and grams) or not self._real(): # no beans in a demo or a replay
            return
        owner = (self.config or configuration.default())["cave_owner"]
        if owner == "computer":
            # The exchange with the computer does not exist yet: it is not reached.
            self.session.stock_move = {"owner": owner, "grams": grams, "done": False}
            return
        try:
            left = self.cave.decrease(self.coffee["uuid"], grams)
            self._refresh_coffee()
            self.session.stock_move = {"owner": owner, "grams": grams, "done": True, "left": left}
        except (OSError, ValueError):
            self.session.stock_move = {"owner": owner, "grams": grams, "done": False}

    def set_roast_setup(self, data: str) -> str:
        """Roast Setup of the chosen coffee, before the roast: green weight, stock box, title, density, moisture, bean temperature."""
        if self.session.state != "idle":
            raise ValueError("Roast Setup is for the next roast")
        if not self.coffee:
            raise ValueError("Choose a coffee first")
        values = json.loads(data)
        clean = dict(self.setup)
        for key, field in (("density", "density"), ("moisture", "last_humidity")):
            low, high, _ = NUMBERS[field]
            number = float(values.get(key) or 0)
            if not low <= number <= high:
                raise ValueError(f"{key} is between {low:g} and {high:g}")
            clean[key] = number
        clean["greens_temp"] = float(values.get("greens_temp") or 0)
        if not math.isfinite(clean["greens_temp"]):
            raise ValueError("A bean temperature is a number")
        clean["title"] = str(values.get("title") or "").strip() or clean["title"]
        clean["decrease"] = bool(values.get("decrease"))
        green = values.get("green")
        if green is not None:
            self.session.set_weight("green", green)
        clean["green"] = green
        preheat = values.get("preheat")
        if preheat is not None: # TilauPID at the start: on/off and the probe are kept for the next roasts
            target = preheat.get("target")
            if target is not None and not (type(target) in (int, float) and 50 <= target <= 300):
                f = (self.config or {}).get("unit") == "F"
                raise ValueError("A preheat target is between 122 and 572 °F" if f else "A preheat target is between 50 and 300 °C")
            clean["preheat_target"] = None if target is None else float(target)
            # The plan's charge offered as the target is this roast's only: the next Roast Setup offers the plan again.
            clean["preheat_typed"] = target is not None and bool(preheat.get("typed"))
            choice = {"preheat_on": bool(preheat.get("on")), "preheat_input": preheat.get("input") or "BT"}
            if self.config is not None and self.config_path:
                self.config = configuration.save(self.config_path, {**self.config, **choice})
            elif self.config is not None:
                self.config = configuration.validate({**self.config, **choice})
        self.setup = clean
        self._save_choice()
        return self.snapshot()

    def _apply_levers(self) -> None:
        """Levers of the configured machine (all of them before the first setup)."""
        self.lever_setup = configuration.levers(self.config or configuration.default())
        if self.readonly:
            self.lever_setup = {k: v for k, v in self.lever_setup.items() if k == "extractor"}
        self.levers = {k: self.levers.get(k, INITIAL_LEVERS[k]) for k in self.lever_setup}
        self.echo = {k: self.echo.get(k, v) for k, v in self.levers.items()}
        self.pending &= set(self.levers)

    def set_readonly(self, readonly: bool) -> str:
        """Simulation only: a roaster exposing no burner, air or drum command."""
        if self.session.state != "idle":
            raise ValueError("The simulated machine changes only between roasts")
        self.readonly = bool(readonly)
        self._apply_levers()
        return self.snapshot()

    def get_setup(self) -> str:
        machine_key = (self.config or {}).get("machine")
        return json.dumps({"configured": self.config is not None,
                           "config": self.config or configuration.default(),
                           "catalogue": catalogue.export(),
                           # What the roast link runs when it is let go hot: cool first, then stop.
                           "end_roast": machine.end_roast(machine_key) if machine_key else [],
                           "simulation": self.replay is not None}) # no device is connected while replaying

    def save_setup(self, data: str) -> str:
        """Applied between roasts only, never during one."""
        if self.session.state == "recording":
            raise ValueError("Settings change only between roasts")
        if not self.config_path:
            raise ValueError("No configuration file")
        self.config = configuration.save(self.config_path, json.loads(data))
        apply_colour_gap(self.config.get("machine"))
        self._apply_levers()
        self._warm_preheat()
        return self.get_setup()

    def save_mqtt(self, data: str) -> str:
        """Settings › Network, saved at each change: an app closed before leaving the page keeps the
        broker and its sensors. Between roasts only, as every setting."""
        if self.session.state == "recording":
            raise ValueError("Settings change only between roasts")
        if not self.config_path or self.config is None:
            raise ValueError("No configuration file")
        self.config = configuration.save(self.config_path, {**self.config, "mqtt": json.loads(data)})
        return json.dumps({"mqtt": self.config["mqtt"]})

    def get_cave(self) -> str:
        return json.dumps(self.cave.state())

    @staticmethod
    def cave_preview(folder: str, source: str) -> str:
        """What a folder's BeanCave holds, every file checked, before it replaces the tablet's."""
        try:
            return json.dumps({"valid": True, "source": source, **Cave.preview(folder)})
        except ValueError as refused:
            return json.dumps({"valid": False, "source": source, "reason": str(refused)})

    def cave_import(self, folder: str, source: str) -> str:
        state = self.cave.replace_folder(folder, source)
        self._planner = None
        self._refresh_coffee()
        return json.dumps(state)

    def cave_start_empty(self) -> str:
        state = self.cave.start_empty()
        self._refresh_coffee()
        return json.dumps(state)

    def get_coffees(self) -> str:
        """The coffees of the tablet's cave, for the BeanCave screen."""
        state = self.cave.state()
        records = [meta for _, meta in self.roasts.records()] if self.roasts else []
        tastings = tasting_log.load(self.cave.directory).entries
        coffees = [{**view(bean), "memory": _memory(last_roast(bean.uuid, records, tastings))}
                   for bean in self.cave.beans()] if state["present"] else []
        config = self.config or configuration.default()
        return json.dumps({"present": state["present"], "coffees": coffees,
                           "chosen": self.coffee["uuid"] if self.coffee else None, "currencies": CURRENCIES,
                           "currency": config["currency"], "editable": config["cave_owner"] == "tablet",
                           "owner": config["cave_owner"], "setup": self.setup,
                           "lists": lists(), "limits": NUMBERS, "required": REQUIRED_TO_CREATE,
                           "zones": ZONES, "blank": {key: getattr(GreenBean(), key) for zone in ZONES.values() for key in zone},
                           "wheel": FLAVOR_WHEEL_DATA})

    def get_roasts(self) -> str:
        """Every roast the tablet holds, its own and the computer's, for the Roasts tab."""
        beans = {b.uuid: b for b in self.cave.beans()} if self.cave and self.cave.state()["present"] else {}
        tastings = tasting_log.load(self.cave.directory).entries if self.cave else {}
        rows = []
        for origin, m in self.roasts.records():
            bean = beans.get(m.uuid)
            colour, basis = roast_agtron(m.ground_color, m.whole_color, "")
            tasting = tastings.get(m.roast_uuid) if m.roast_uuid else None
            rows.append({"origin": origin, "name": m.filename, "epoch": m.roastepoch, "title": m.title,
                         "coffee": bean.name if bean else m.title, "bean_uuid": m.uuid,
                         "process": bean.process if bean else "", "crop": bean.crop if bean else 0,
                         "weight_in_g": m.weight_in_g, "weight_out_g": m.weight_out_g,
                         "colour": colour, "ground": basis == "ground", "swatch": get_agtron_color(colour) if colour > 0 else "",
                         "simulated": m.simulated, "excluded": m.exclude_learning,
                         "verdict": tasting.verdict if tasting else None})
        return json.dumps({"roasts": rows})

    def get_roast(self, data: str) -> str:
        request = json.loads(data)
        detail = self.roasts.detail(request["origin"], request["name"], (self.config or {}).get("unit", "C"))
        uuid = detail["roast_uuid"]
        tasting = tasting_log.load(self.cave.directory).entries.get(uuid) if self.cave and uuid else None
        bean = next((b for b in self.cave.beans() if b.uuid == detail["bean_uuid"]), None) \
            if self.cave and detail["bean_uuid"] else None
        reference = (bean.reference_roast_uuid or "") if bean else ""
        return json.dumps({**detail, "tasted": _tasted(tasting), "defects": list(tasting.defects) if tasting else [],
                           "tasting": {"verdict": tasting.verdict, "defects": list(tasting.defects), "notes": tasting.notes}
                           if tasting else None,
                           "coffee": bean.name if bean else "", "is_reference": bool(uuid) and reference == uuid,
                           "has_reference": bool(reference),
                           "rest_days": (date.today() - date.fromtimestamp(detail["epoch"])).days if detail["epoch"] else None,
                           "words": _tasting_words((self.config or {}).get("unit", "C")), "colours": catalogue.export()["colours"]})

    def delete_roast(self, data: str) -> str:
        """{origin, name}: the roast file leaves the tablet (from the computer: only its copy); the stock stays."""
        if self.session.state != "idle" or self.replay is not None:
            raise ValueError("Roasts are deleted between roasts")
        request = json.loads(data)
        source = (request["origin"], request["name"])
        meta = next((m for origin, m in self.roasts.records() if (origin, m.filename) == source), None)
        self.roasts.path(*source).unlink()
        if meta is not None and meta.uuid and meta.roast_uuid and self.cave and self.cave.state()["present"] \
                and any(b.uuid == meta.uuid for b in self.cave.beans()): # a reference ★ goes with its roast
            self.cave.set_reference(meta.uuid, meta.roast_uuid, False)
        if self._follow_pick == source:
            self._follow_pick = None
            self._save_choice()
        self._followed = None
        self._planner = None # the plan and the preheat learn from the roasts left
        self._preheat_ready = None
        self._warm_preheat()
        return self.get_roasts()

    def save_tasting(self, data: str) -> str:
        """The tasting of a roast ({origin, name, verdict, defects, notes, reference}), and its star, as the desktop."""
        request = json.loads(data)
        detail = self.roasts.detail(request["origin"], request["name"])
        if not detail["roast_uuid"]:
            raise ValueError("This roast cannot be tasted: it has no identifier")
        defects = [d for d in tasting_log.DEFECT_CHANGES if d in request.get("defects", [])]
        verdict = request.get("verdict") or ""
        if verdict and verdict not in tasting_log.VERDICT_WORDS:
            raise ValueError("Unknown verdict")
        tasting = RoastTasting(bean_uuid=detail["bean_uuid"], iso_date=date.today().isoformat(), verdict=verdict,
                               defects=defects, notes=str(request.get("notes") or "").strip())
        if not tasting_log.record(str(self.cave.directory), detail["roast_uuid"], tasting):
            raise ValueError("The tasting could not be saved")
        if request.get("reference") is not None and detail["bean_uuid"]:
            self.cave.set_reference(detail["bean_uuid"], detail["roast_uuid"], bool(request["reference"]))
        self._planner = None # the plan reads the last tasting and the reference
        return self.get_roast(json.dumps({"origin": request["origin"], "name": request["name"]}))

    def roasts_preview(self, data: str) -> str:
        """The roast files of a folder picked on the tablet: how many are new, already here, not roasts."""
        request = json.loads(data)
        return json.dumps({"folder": request["folder"], **self.roasts.preview(request["paths"])})

    def import_roasts(self, data: str) -> str:
        """Roast files picked on the tablet (copied to a staging folder by the app)."""
        self._planner = None
        return json.dumps(self.roasts.import_files(json.loads(data)))

    def save_coffee(self, data: str) -> str:
        """A zone of a coffee ({uuid, zone, values}), or a new coffee (no uuid); tablet owner only."""
        if (self.config or configuration.default())["cave_owner"] != "tablet":
            raise ValueError("A computer keeps these coffees")
        request = json.loads(data)
        saved = self.cave.save_bean(request.get("uuid"), request["zone"], request["values"])
        self._planner = None
        self._refresh_coffee()
        reply = json.loads(self.get_coffees())
        reply["saved"] = saved
        return json.dumps(reply)

    def choose_coffee(self, uuid: str) -> str:
        """The coffee the next roasts name, chosen between roasts (a roast keeps the one it started with)."""
        if self.session.state == "recording":
            raise ValueError("The coffee is chosen between roasts")
        bean = next((b for b in self.cave.beans() if b.uuid and b.uuid == uuid), None)
        if bean is None:
            raise ValueError("No such coffee in the BeanCave")
        same = self.coffee is not None and self.coffee["uuid"] == uuid and self.setup is not None
        weighed = self.setup["green"] if same else None # chosen again, the coffee keeps the weight its roast starts with
        self.coffee = chosen(bean)
        self.setup = roast_setup(bean)
        if weighed is not None:
            self.setup["green"] = weighed
        if self._follow_pick is not None and self.roasts is not None and any( # a roast picked of another coffee
                (origin, m.filename) == self._follow_pick and m.uuid and m.uuid != uuid for origin, m in self.roasts.records()):
            self._follow_pick = None
        self._save_choice()
        return self.snapshot()

    def _refresh_coffee(self) -> None:
        """A new cave file: the chosen coffee follows it, or is dropped when it is gone."""
        if self.coffee:
            bean = next((b for b in self.cave.beans() if b.uuid == self.coffee["uuid"]), None)
            self.coffee = chosen(bean) if bean else None
            if not self.coffee:
                self.setup = None
            self._save_choice()

    def _restore_choice(self) -> None:
        """The coffee chosen before the app was closed, if the BeanCave still holds it."""
        if not (self.choice_path and self.cave and Path(self.choice_path).exists()):
            return
        try:
            saved = json.loads(Path(self.choice_path).read_text(encoding="utf-8"))
            bean = next((b for b in self.cave.beans() if b.uuid and b.uuid == saved["uuid"]), None)
        except (OSError, ValueError, KeyError, TypeError):
            return
        if bean is not None and isinstance(saved.get("setup"), dict):
            self.coffee, self.setup = chosen(bean), {**roast_setup(bean), **saved["setup"]}
            pick = saved.get("follow_pick") # the roast picked to follow, kept as the coffee is
            if isinstance(pick, list) and len(pick) == 2 and all(isinstance(x, str) for x in pick):
                self._follow_pick = (pick[0], pick[1])

    def _save_choice(self) -> None:
        if not self.choice_path:
            return
        target = Path(self.choice_path)
        if not self.coffee:
            target.unlink(missing_ok=True)
            return
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"uuid": self.coffee["uuid"], "setup": self.setup,
                                         "follow_pick": list(self._follow_pick) if self._follow_pick else None}),
                             encoding="utf-8")
        os.replace(temporary, target)

    @staticmethod
    def classify_scan(results: str) -> str:
        """Scan results [{address, name, rssi, uuids}] with what each one is, if known."""
        out = []
        for item in json.loads(results):
            found = catalogue.classify(item.get("name"), item.get("uuids"))
            if found:
                out.append({**item, "kind": found[0], "key": found[1]})
        return json.dumps(out)

    def set_lever(self, lever: str, value: int) -> str:
        if lever not in self.levers:
            raise ValueError("This machine has no such lever")
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("A lever value is a whole percentage")
        if self.session.state == "stopped":
            raise ValueError("The roast is over")
        self._drop_auto(lever=True) # the operator's hand (decision 8)
        self._lever(lever, value)
        if self.link is not None:
            self.link["recovered"] = False # any lever touched: the operator has the roast, the banner goes
        return self.snapshot()

    def _lever(self, lever: str, value: int, alarm: int | None = None) -> None:
        """The operator's gesture on a lever; an alarm (its number) makes the very same one (ALARM-SPEC decision 7)."""
        if lever != "extractor" and self._link_away(): # the extractor is another machine, still reachable
            return
        self.levers[lever] = value
        self.pending.add(lever) # confirmed by the machine at the next tick
        if self.session.state == "recording":
            self._record(lever, value, alarm)
        if lever == "burner" and self.preheat is not None:
            self.preheat.pause() # the operator has the burner (decision 4)
        if self.link is not None:
            command = machine.setup(self._machine()).levers.get(lever)
            if command is not None:
                self._send([command.command_for(value)])
            if lever == "burner":
                self.link["recovered"] = False # the operator took the burner back

    def device_lever(self, lever: str, value: int) -> str:
        """A value the real device reports (a command it confirmed, or its own knob).

        It needs no echo of its own; while recording, a change is a setting.
        """
        if lever not in self.levers:
            raise ValueError("This machine has no such lever")
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("A lever value is a whole percentage")
        changed = value != self.levers[lever]
        if lever == "extractor" and changed and self.playback is None and self.session.state == "recording":
            self._drop_auto(lever=True) # its own buttons, following a plan: the operator's hand (decision 8)
        elif lever == "extractor" and changed and self.playback is not None and self.session.state == "recording":
            sent = self._follow_extractor
            match = next((k for k, speed in enumerate(sent) if speed == value), None)
            if match is None: # the operator's hand on the AirWave (decision 8)
                self._drop_auto(lever=True)
            else:
                for _ in range(match): # the speeds before it are confirmed past
                    sent.popleft()
        self.levers[lever] = self.echo[lever] = value
        self.pending.discard(lever)
        if changed and self.session.state == "recording":
            asked = self._alarm_extractor
            by = asked[1] if lever == "extractor" and asked is not None and asked[0] == value else None # an alarm's speed
            self._record(lever, value, by)
            if by is not None:
                self._alarm_extractor = None
        return self.snapshot()

    def _record(self, lever: str, value: int, by: str | int | None = None) -> None:
        """A setting, and who made it: "pid" for TilauPID, an alarm's number, None for the operator."""
        self.session.record_setting(lever, value, self.now)
        index = len(self.session.settings) - 1
        if by == "pid":
            self.session.pid_settings.add(index)
        elif by is not None:
            self.session.alarm_settings[index] = by
        if self.journal:
            self.journal.setting(lever, value, self.now, by)

    def _elapsed(self, milestone: str) -> float | None:
        index = self.session.milestones.get(milestone)
        return None if index is None else self.session.samples[index].elapsed_s

    def _reading(self) -> Reading | None:
        if self.link is not None: # the roaster's last reading, or none when it is too old
            fresh = self._live is not None and self.clock() - self._live[0] < Session.STALE_AFTER_S
            return self._live[1] if fresh else None
        if self.replay is not None:
            et, bt = self.replay.read(self.now)
            now = self.clock()
            for slot, first, second in self._replay_channels:
                for channel, value in zip((first, second), self.replay.read_extra(slot, self.now)):
                    if value != -1 and math.isfinite(value):
                        self._extras[channel] = (now, value)
            if self._replay_cracks is not None:
                count = self.replay.read_extra(self._replay_cracks, self.now)[0]
                if count >= 0:
                    self._cracks = (now, int(count))
            if bt > 0 and self.response is not None:
                bt += self.response.bt_offset # the simulated roaster answers the levers (SIM-SPEC S3)
            return Reading(bt, et if et > 0 else None) if bt > 0 else None # -1 or 0: the file had no reading
        charge, drop = self._elapsed("charge"), self._elapsed("drop")
        if charge is None:
            return Reading(201 + 0.4 * math.sin(self.now / 5), 188 + 0.6 * math.sin(self.now / 7))
        t = int(self.now - charge)
        if drop is not None and self.now > drop:
            top = PROFILE[min(900, int(drop - charge))]
            bt = top - (top - 45) * (1 - math.exp(-(self.now - drop) / 50))
        else:
            bt = PROFILE[min(900, t)] + 0.25 * math.sin(t / 6)
        et = 170 - 90 * t / 60 if t < 60 else bt - 14 + 1.5 * math.sin(t / 11)
        return Reading(bt, et)

    def _sample(self) -> None:
        reading = self._reading()
        if reading is None: # the link is down: the curve has a gap
            return
        now = self.clock()
        extras = {key: value for key, (at, value) in self._extras.items() if now - at <= ROOM_MAX_AGE_S} or None
        self.session.ingest(reading, self.now, extras)
        if self.journal:
            self.journal.sample(self.now, reading, extras)

    def extra_readings(self, data: str) -> None:
        """Accessory values read just now (any of EXTRA_CHANNELS); each sample takes the fresh ones."""
        values = json.loads(data)
        if set(values) - set(EXTRA_CHANNELS) or not all(type(v) in (int, float) and math.isfinite(v) for v in values.values()):
            raise ValueError("Unknown or invalid accessory channel")
        now = self.clock()
        for key, value in values.items():
            self._extras[key] = (now, float(value))

    def export_alog(self, directory: str) -> str:
        """The roast as a desktop .alog in `directory`; returns its path."""
        if self.session.state != "stopped" or not self.session.samples:
            raise ValueError("A roast is exported once it is over")
        profile = self._profile()
        target = Path(directory) / alog.file_name(profile)
        # Saved again, a roast keeps its file; another roast of the same title and minute never takes it.
        n = 1
        while target.exists() and target.name != self.session.exported:
            n += 1
            target = target.with_name(f"{alog.file_name(profile)[:-5]}_{n}.alog")
        target.parent.mkdir(parents=True, exist_ok=True)
        alog.write(str(target), profile)
        self.session.exported = target.name
        self._planner = None
        self._after_stop({"event": "exported", "name": target.name, "t": self.now})
        return str(target)

    def _profile(self) -> dict:
        """The roast as the desktop reads it (.alog content)."""
        config = self.config or configuration.default()
        machine = catalogue.MACHINES.get(config["machine"]) if config["machine"] else None
        return alog.profile(self.session, levers=configuration.levers(config) if config["machine"] else self.lever_setup,
                            operator=config["operator"],
                            roaster=f'{machine["manufacturer"]} {machine["model"]}' if machine else "")

    def roast_label(self, data: str = "") -> str:
        """The lines of the desktop's 30 mm label: of a listed roast ({origin, name}), else of the roast just over.

        ValueError when Dry end, First crack or Drop is not marked, as on the desktop.
        """
        if data:
            request = json.loads(data)
            profile = ast.literal_eval(self.roasts.path(request["origin"], request["name"]).read_text(encoding="utf-8"))
        elif self.session.state == "stopped" and self.session.samples:
            profile = self._profile()
        else:
            raise ValueError("A label is printed once the roast is over")
        found = _UUID_RE.search(str(profile.get("beans") or ""))
        bean = next((b for b in self.cave.beans() if found and b.uuid == found.group(1)), None) if self.cave else None
        if bean is None:
            raise ValueError("The roast's coffee is not in the BeanCave")
        roast_data, _qr, _phases = label_data(bean, profile, lambda: "")  # no QR on 30 mm
        return json.dumps(lines_30mm(roast_data))

    def advance(self, seconds: int = 1) -> str:
        if type(seconds) is not int or not 1 <= seconds <= 3600:
            raise ValueError("Advance must be an integer between 1 and 3600 seconds")
        self._confirm_pending()
        if self.session.state == "recording":
            for _ in range(seconds * (self.speed if self.replay is not None else 1)):
                if self._slow_before_charge():
                    break
                self.now += 1
                self._step()
        return self.snapshot()

    def tick(self) -> str:
        """The service's 1 Hz tick: a live roast's time is the real clock, as Artisan's timex; a replay counts
        simulated seconds. A late tick keeps its real time, so the curve shows the gap; nothing is filled in."""
        if self._origin is None or self.session.state != "recording":
            return self.advance(1)
        self._confirm_pending()
        now = round(self.real_clock() - self._origin, 3)
        gap = now - self.now
        if gap < TICK_MIN_S:
            return self.snapshot()
        if gap > LATE_SAMPLING_S:
            count, longest = self.session.late_sampling or (0, 0.0)
            self.session.late_sampling = (count + 1, max(longest, round(gap, 1)))
            self._late = (now, gap)
            print(f"TilauScope sampling late: {gap:.1f} s without a tick at {self.now:.1f} s of the roast")
        self.now = now
        self._step()
        return self.snapshot()

    def _confirm_pending(self) -> None:
        if self.link is None: # the simulated machine confirms at the next tick; a real one through its echo
            for lever in self.pending:
                self.echo[lever] = self.levers[lever]
            self.pending.clear()

    def _step(self) -> None:
        """One second of the roast at `now`: a sample and what reads it, the preheat, the alarms."""
        self._door_step()
        if self.signal:
            count = len(self.session.samples)
            self._respond()
            self._sample()
            self._crack_step()
            if len(self.session.samples) > count:
                self._tp_step()
            if self.playback is not None and not self._follow_paused and len(self.session.samples) > count:
                self._follow_step()
            if self.auto is not None and len(self.session.samples) > count:
                self._auto_step()
            if self.guide is not None and len(self.session.samples) > count:
                self._guide_step()
        if self.preheat is not None and (self.link is None or self.session.samples):
            self.preheat.tick(self._preheat_reading()) # from the roaster's first reading (2-3 s after connecting)
        if self.alarms is not None and self.session.state == "recording":
            for act in self.alarms.step(self.session, self.now):
                self._run_alarm(act)
        if self.energy is not None and self.session.state == "recording":
            m = self.session.milestones
            self.energy.step(self.now, *(float(self.echo.get(k, -1)) for k in ("burner", "air", "extractor")),
                             roasting="charge" in m and "drop" not in m)

    def set_weight(self, kind: str, grams: int) -> str:
        """Green before the roast (kept for the next start), roasted once it is over."""
        if self.interrupted:
            raise ValueError("An interrupted roast is read only")
        self.session.set_weight(kind, grams)
        if kind == "green" and self.setup and self.session.state == "idle":
            self.setup["green"] = grams # the weight the roast starts with, kept for the next one
            self._save_choice()
        if self.journal:
            self.journal.weight(kind, grams, self.now)
        elif kind == "roasted":
            self._after_stop({"event": "weight", "kind": kind, "grams": grams, "t": self.now})
        return self.snapshot()

    def set_colour(self, kind: str, value: float) -> str:
        """Whole or ground colour, from the colour meter or the wheel, once the roast is over."""
        if self.interrupted:
            raise ValueError("An interrupted roast is read only")
        self.session.set_colour(kind, value)
        self._after_stop({"event": "colour", "kind": kind, "value": self.session.colours[kind], "t": self.now})
        return self.snapshot()

    def _after_stop(self, event: dict) -> None:
        if self.journal_path and Path(self.journal_path).exists():
            append_after_stop(self.journal_path, event)

    def ambient_reading(self, data: str) -> None:
        """A valid reading of the ambient probe: temperature, humidity, pressure."""
        values = json.loads(data)
        if set(values) != set(AMBIENT_KEYS) or not all(type(v) in (int, float) and math.isfinite(v) for v in values.values()):
            raise ValueError("An ambient reading has a temperature, a humidity and a pressure")
        self._room = (self.clock(), {key: float(values[key]) for key in AMBIENT_KEYS})

    def room(self) -> dict | None:
        """The room: TilauAmbient's three readings while fresh, else what the MQTT sensors give, each
        reading on its own as on the desktop (MQTT-SPEC decision 5); None when nothing reads."""
        return self._room_and_source()[0]

    def _room_and_source(self) -> tuple[dict | None, str | None]:
        if self._room is not None and self.clock() - self._room[0] <= ROOM_MAX_AGE_S:
            return self._room[1], "probe"
        values = self._mqtt_values(mqtt.ROOM_KEYS, MQTT_ROOM_MAX_AGE_S)
        return (values, "mqtt") if values else (None, None)

    def _mqtt_values(self, feeds: dict, max_age_s: float) -> dict:
        """{name: value} of the configured sensors feeding `feeds`, from messages younger than max_age_s."""
        values, now = {}, self.clock()
        for sensor in ((self.config or {}).get("mqtt") or {}).get("sensors", []):
            heard = self._mqtt_raw.get(sensor["topic"])
            if sensor["feeds"] in feeds and heard is not None and now - heard[0] <= max_age_s:
                value = mqtt.reading(sensor, heard[1])
                if value is not None:
                    values[feeds[sensor["feeds"]]] = value
        return values

    def mqtt_message(self, data: str) -> None:
        """A message the broker delivered: kept by topic with its arrival time, read when needed."""
        message = json.loads(data)
        if not isinstance(message.get("topic"), str) or not isinstance(message.get("payload"), str):
            raise ValueError("An MQTT message has a topic and a payload")
        self._mqtt_raw[message["topic"]] = (self.clock(), message["payload"][:MQTT_MAX_PAYLOAD])
        if self.energy is not None and self._origin is not None:
            self.energy.reading(self.real_clock() - self._origin, message["topic"], message["payload"])

    def mqtt_check(self, data: str) -> str:
        """Settings: what a sensor, as typed, reads in the last message on its topic."""
        request = json.loads(data)
        sensor, key = mqtt.sensor(request), request.get("key") # the page's own name for the row asking
        heard = self._mqtt_raw.get(sensor["topic"])
        if heard is None:
            return json.dumps({"key": key, "heard": False})
        return json.dumps({"key": key, "heard": True, "age_s": round(self.clock() - heard[0]), "value": mqtt.reading(sensor, heard[1])})

    def _plan_settings(self) -> dict:
        config = self.config
        return {key: config[key] for key in self._plan_choice} if config else dict(self._plan_choice)

    def _plan_engine(self) -> TabletPlan:
        config = self.config or configuration.default()
        key = (config["machine"], self._plan_settings()["roast_destination"])
        if self._planner is None or self._planner_key != key:
            self._planner = TabletPlan(self.roasts, config["machine"], str(self.cave.directory), key[1])
            self._planner_key = key
        return self._planner

    def _plan_room(self) -> tuple[float, float, float, bool]:
        """The probe's room when fresh, else the desktop's 20 °C and 50 %; its altitude, else sea level."""
        room = self.room() or {}
        temperature, humidity = room.get("temperature_c", ROOM_DEFAULT[0]), room.get("humidity_pct", ROOM_DEFAULT[1])
        altitude = self._extras.get("altitude_m")
        fresh = altitude is not None and self.clock() - altitude[0] <= ROOM_MAX_AGE_S
        return temperature, humidity, altitude[1] if fresh else 0.0, "temperature_c" in room and "humidity_pct" in room

    def get_plan(self, data: str = "{}") -> str:
        """The Plan tab: the choices, then the plan, or what it still needs.

        `data` may carry the green weight typed on Roast Setup, not applied yet.
        """
        settings = self._plan_settings()
        reply = {"levels": LEVELS, "level": settings["plan_level"], "destinations": list(ROAST_DESTINATION_KEYS),
                 "destination": settings["roast_destination"]}
        bean = self._bean()
        typed = json.loads(data or "{}").get("green")
        green = float(typed if typed is not None else (self.setup or {}).get("green") or 0)
        if bean is None:
            reply["state"] = "no_coffee"
        elif not (self.config or {}).get("machine"): # without the machine's offsets the plan would be wrong
            reply["state"] = "no_machine"
        elif not settings["plan_level"]:
            reply["state"] = "no_level"
        elif green <= 0:
            reply["state"] = "no_weight"
        else:
            temperature, humidity, altitude, probe = self._plan_room()
            reply.update(plan_view(self._plan_engine(), bean, settings["plan_level"], green,
                                   (temperature, humidity, altitude, (self.room() or {}).get("pressure_hpa")),
                                   (self.config or {}).get("unit", "C")))
            reply.update(state="ready", green=green,
                         room={"temperature": temperature, "humidity": humidity, "altitude": altitude, "probe": probe})
        reply["follow"] = self._follow_view(bean)
        reply.update(auto=(self.config or {}).get("auto_marks") or [])
        return json.dumps(reply)

    def set_plan_choice(self, data: str) -> str:
        """The level and the use of the coffee, kept for the next roasts, as on the desktop."""
        request = json.loads(data)
        choice = {key: value for key, value in request.items() if key in self._plan_choice}
        if self.config is not None and self.config_path:
            self.config = configuration.save(self.config_path, {**self.config, **choice})
        else:
            self._plan_choice = {key: value for key, value in
                                 configuration.validate({**configuration.default(), **choice}).items()
                                 if key in self._plan_choice}
        return self.get_plan(json.dumps({"green": request.get("green")}))

    def _send(self, commands: list[str]) -> None:
        """Commands for the roaster, in order; the real link sends them, the simulated machine only logs them."""
        self.machine_log.extend(commands)
        if self.link is not None:
            self._outbox.extend(commands)

    def _link_away(self) -> bool:
        """The real roaster is not reachable: it cut its burner, and its levers are locked until the link is back."""
        return self.link is not None and self.link["state"] != "connected"

    def _burner_held(self) -> None:
        """The burner as the roaster has it after a (re)connection: 0, until the operator raises it."""
        if "burner" not in self.levers:
            return
        self.levers["burner"] = self.echo["burner"] = 0
        self.pending.discard("burner")
        if self.session.state == "recording":
            self._record("burner", 0)

    # ── TilauPID (PREHEAT-SPEC P2) ────────────────────────────────────────
    def _preheat_key(self) -> tuple | None:
        """What a preheat is built for: the machine and the probe it reads; None when there is none."""
        config = self.config or {}
        if not ((self._real() or self.replay is not None) and config.get("preheat_on")):
            return None
        return self._machine(), config.get("preheat_input") or "BT"

    def _warm_preheat(self) -> None:
        """Between roasts: the preheat built now loads its history in the background."""
        key = self._preheat_key()
        if key is None:
            self._preheat_ready = None
        elif self._preheat_ready is None or self._preheat_ready[0] != key:
            self._preheat_ready = (key, self._new_preheat(key))

    def _new_preheat(self, key: tuple) -> TabletPreheat:
        machine_key, probe = key
        setup = machine.setup(machine_key)
        return TabletPreheat(
            roasts=self.roasts, machine=machine_key, input_probe=probe, store_path=self._preheat_store,
            # a replay runs on its own seconds (8 per real second at 8×)
            clock=lambda: self.now if self.replay is not None else self.clock(), burner=self._pid_burner,
            mark=self._mark_preheat, simulated=not self._real(), fault=self._preheat_fault,
            room=self._preheat_room, ror_span_s=setup.ror.delta_span_s or 15.0)

    def _start_preheat(self) -> None:
        """At the start, with the real roaster (or a replay in its place) and the preheat on in Roast Setup."""
        self.preheat = None
        key, target = self._preheat_key(), (self.setup or {}).get("preheat_target")
        ready, self._preheat_ready = self._preheat_ready, None # one roast each: the next is built after it
        if key is None or not target:
            return
        self.session.pid_source = INPUTS[key[1]]
        self.preheat = ready[1] if ready is not None and ready[0] == key else self._new_preheat(key)
        self.preheat._sim = self.session.simulated # a replay never learns; read from the start on
        self.preheat.start(float(target))

    def _preheat_reading(self) -> float | None:
        reading = self._reading()
        if reading is None:
            return None
        return reading.et_c if self.session.pid_source == INPUTS["ET"] else reading.bt_c

    def _preheat_room(self) -> AmbientConditions | None:
        room = self.room()
        if not room or set(AMBIENT_KEYS) - set(room):
            return None
        return AmbientConditions(room["temperature_c"], room["humidity_pct"], room["pressure_hpa"])

    def _preheat_fault(self, reason: str) -> None:
        """A safety stop of the preheat: burner off, the roaster cooled, then stopped (operator, 2026-10-16)."""
        self._send(machine.end_roast(self._machine()))

    def _mark_preheat(self, target_c: float | None) -> None:
        self.session.preheat_sv_c = target_c
        if self.journal: # with the probe it reads, for a roast restored after the app was closed
            self.journal.preheat(target_c, self.session.pid_source, self.now)

    def _pid_burner(self, power: int) -> None:
        """A burner command of the preheat: on the lever, recorded as TilauPID's, sent to the roaster."""
        if self._link_away():
            return
        self.levers["burner"] = power
        self.pending.add("burner")
        if self.session.state == "recording":
            self._record("burner", power, "pid")
        command = machine.setup(self._machine()).levers.get("burner")
        if command is not None:
            self._send([command.command_for(power)])

    def resume_follow(self) -> str:
        """Resume the roast followed after a dropped link: its playback takes the levers back, at the values it holds."""
        self._follow_paused = False
        if self.playback is not None:
            for kind, value in self.playback.held().items():
                if kind in LEVER_OF:
                    self._follow_move(LEVER_OF[kind], value)
        if self.link is not None:
            self.link["recovered"] = False
        return self.snapshot()

    def resume_preheat(self) -> str:
        """Re-arm the preheat: TilauPID takes the burner back."""
        if self.preheat is not None:
            self.preheat.resume(self.levers.get("burner", 0))
        return self.snapshot()

    def _end_preheat(self, reason: str) -> None:
        if self.preheat is not None and self.preheat.active:
            self.preheat.stop(reason=reason)

    def link_state(self, data: str) -> str:
        """The roaster link changed (connecting, verifying, connected, reconnecting, idle…).

        On the first connection the burner is held at 0 and the air and drum are sent as the
        screen shows them; after a drop the roaster cut its burner: it stays at 0 (recovered).
        """
        state = json.loads(data)
        if self.link is None:
            return self.snapshot()
        if state.get("state") == "idle":
            self.link, self._live = None, None
            return self.snapshot()
        first = state.get("state") == "connected" and not self.link["connected_once"]
        self.link["state"] = state.get("state") or self.link["state"]
        if self.link["state"] == "connected":
            self.link["connected_once"] = True
        elif self.link["connected_once"] and self.preheat is not None:
            self.preheat.pause() # the link dropped: the roaster cut its burner, a silent probe is no fault
        if state.get("recovered"):
            self.link["recovered"] = True
            self._burner_held()
            if self.preheat is not None:
                self.preheat.pause() # heat is never re-applied by itself: the operator re-arms the preheat
            if self.playback is not None:
                self._follow_paused = True # nor by the roast followed: the operator resumes it
        elif first:
            self._burner_held()
            setup = machine.setup(self._machine())
            self._send([setup.levers[k].command_for(self.levers[k]) for k in ("air", "drum")
                        if k in self.levers and k in setup.levers])
        return self.snapshot()

    def _live_after_roast(self) -> dict:
        """Once the roast is over (the roaster cooling), BT and ET as the roaster reads them now; not recorded."""
        if self.session.state != "stopped" or self.link is None or self._live is None:
            return {}
        if self.clock() - self._live[0] >= Session.STALE_AFTER_S:
            return {}
        return {"bt_c": self._live[1].bt_c, "et_c": self._live[1].et_c}

    def link_reading(self, data: str) -> None:
        """One reading of the roaster: BT, ET and the echoes of the burner and the air."""
        reading = json.loads(data)
        try:
            et = reading.get("et")
            self._live = (self.clock(), Reading(float(reading["bt"]), None if et is None or et <= 0 else float(et)))
        except (KeyError, TypeError, ValueError): # no bean probe reading (-1): not a sample
            return
        for lever in ("burner", "air"):
            echo = reading.get(lever)
            if lever in self.levers and type(echo) is int:
                self.echo[lever] = echo
                if echo == self.levers[lever]:
                    self.pending.discard(lever)

    def _start_energy(self) -> None:
        """A real roast's energy, as the desktop's from monitoring on: the preheat is part of it."""
        config = self.config or {}
        if not self._real():
            self.energy = None
            return
        entry = catalogue.MACHINES[self._machine()]
        extractor = config.get("devices", {}).get("extractor")
        self.energy = TabletEnergy(self._roaster_name(), RoasterManager().get_by_name(entry["manufacturer"], entry["model"]),
                                   (config.get("mqtt") or {}).get("sensors", []), bool(extractor and extractor.get("enabled")))

    def _bill(self):
        """The closed energy session and its summary on the roast's milestones, kept until they change."""
        if not self.session.energy:
            return None
        key = (id(self.session.energy), tuple(self.session.milestones.items()), self.session.weights["green"])
        if self._energy_bill is None or self._energy_bill[0] != key:
            session = EnergySession.from_dict(self.session.energy)
            bounds = PhaseBounds(*(self._elapsed(k) for k in ("charge", "dry_end", "first_crack", "drop")))
            self._energy_bill = (key, session, session.summarize(bounds, (self.session.weights["green"] or 0) / 1000))
        return self._energy_bill[1:]

    def _energy_card(self) -> dict | None:
        """The end card's Energy: the roast's kWh once CHARGE and DROP are marked, else since START."""
        bill = self._bill()
        if bill is None:
            return None
        _, summary = bill
        per = summary.roast.per_channel if summary.roast is not None else summary.since_start
        total = summary.total(per)
        return {"kwh": round(total.wh / 1000, 3), "roast": summary.roast is not None, "provenance": total.provenance,
                "per_kg_kwh": None if summary.wh_per_kg is None else round(summary.wh_per_kg / 1000, 2)}

    def get_energy(self) -> str:
        """The energy sheet of the roast just over."""
        bill = self._bill()
        if bill is None:
            raise ValueError("This roast has no energy")
        return json.dumps(energy_sheet(*bill, self._elapsed("charge"), self._elapsed("drop")))

    def get_roast_energy(self, data: str) -> str:
        """The energy sheet of a saved roast ({origin, name}), from BeanCave › Roasts."""
        request = json.loads(data)
        profile = ast.literal_eval(self.roasts.path(request["origin"], request["name"]).read_text(encoding="utf-8"))
        saved = energy_bill(profile)
        if saved is None:
            raise ValueError("This roast has no energy")
        bounds = phase_bounds(profile.get("timex") or [], profile.get("timeindex") or [])
        return json.dumps(energy_sheet(*saved, bounds.charge, bounds.drop))

    def _machine(self) -> str | None:
        return (self.config or {}).get("machine")

    def mark(self, milestone: str) -> str:
        self._mark(milestone)
        return self.snapshot()

    def _mark(self, milestone: str, index: int | None = None) -> None:
        """A milestone, touched or found (then at the sample it was found on): the same effects."""
        self.session.mark(milestone, self.now, index)
        if milestone == "charge":
            self._door.charge() # the openings from now on are this roast's
        if milestone == "drop":
            self._door.stop()
        if milestone == "charge":
            self._end_preheat("charge") # the roast takes over; the preheat is learned from
        if milestone == "drop":
            self._crack_command("stop")
            self.playback = None # the followed roast ends with this one's beans out
        if milestone == "charge" and self.playback is not None:
            self._engage_follow()
        if self._machine():
            self._send(machine.setup(self._machine()).on_milestone.get(milestone, []))
        if self.journal:
            self.journal.mark(milestone, self.now, self.session.milestones[milestone])
        room = self.room()
        if milestone == "charge" and room is not None:
            self.session.ambient = room
            if self.journal:
                self.journal.ambient(room, self.now)
        self._after_mark(milestone)

    def unmark(self) -> str:
        if not self.session.milestones:
            raise ValueError("Nothing to undo")
        self._drop_auto() # the operator's hand (decision 8)
        if self.pilot is not None and self.pilot.engine.state == "armed":
            self.pilot.engine.set_state("paused") # an undo is the operator's hand too
            self.pilot.report("paused", reason="takeover")
        latest = max(self.session.milestones, key=Session.MILESTONES.index)
        self.session.unmark(latest)
        if latest == "charge":
            self._tp = TurningPoint()
        if self.journal:
            self.journal.unmark(latest, self.now)
        return self.snapshot()

    def toggle_signal(self) -> str:
        """Simulation only: interrupt or restore the sensor stream."""
        self.signal = not self.signal
        return self.snapshot()

    def stop(self) -> str:
        if self.pilot is not None and self.pilot.engine.state != "off":
            self.pilot.engine.set_state("off")
        self._end_preheat("recording_stop")
        self._crack_command("stop") # a roast stopped before its Drop
        self.playback = None
        self.session.stop(self.now)
        if self.energy is not None:
            self.session.energy = self.energy.close(self.now)
            self.energy = None
        if self._machine():
            self._send(machine.end_roast(self._machine()))
            self._cool_extractor()
        if self.journal:
            self.journal.stop(self.now)
            self.journal = None
        return self.snapshot()

    # ── Alarms (ALARM-SPEC C2) ───────────────────────────────────────────
    def get_alarms(self) -> str:
        """The lists on the tablet and the one every roast runs."""
        lists = []
        if self.alarm_lists is not None:
            setup = machine.setup(self._machine()) if self._machine() else None
            for name in self.alarm_lists.names():
                try:
                    run = self._alarm_run(name, setup)
                except ValueError:
                    continue
                lists.append({"name": name, "count": len(run.rows),
                              "not_run": sum(1 for t, a in zip(run.texts, run.rows) if a.on and t["why"])})
        return json.dumps({"lists": lists, "active": (self.config or {}).get("alarm_list")})

    def set_alarm_list(self, name: str) -> str:
        """The list every roast runs ("" for none), kept in the configuration across coffees."""
        if self.config is None or self.config_path is None:
            raise ValueError("Set the tablet up first")
        if name and (self.alarm_lists is None or name not in self.alarm_lists.names()):
            raise ValueError("No such alarm list")
        self.config = configuration.save(self.config_path, {**self.config, "alarm_list": name or None})
        return self.get_alarms()

    def import_alarms(self, path: str, name: str) -> str:
        """An .alrm file picked on the tablet, kept as a list; it becomes the active one."""
        if self.alarm_lists is None:
            raise ValueError("Set the tablet up first")
        text = Path(path).read_text(encoding="utf-8")
        unit = (self.config or {}).get("unit", "C")
        if unit != "C": # an .alrm says no unit: read in the one shown, kept in °C (UNIT-SPEC decision 3)
            try:
                text = write_alrm(rows_in_unit(read_alrm(text), self._desktop_devices(), unit, back=True))
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError("This file is not an Artisan alarm list") from error
        kept = self.alarm_lists.add(name, text)
        return self.set_alarm_list(kept)

    # ── The alarm editor (ALARM-SPEC C3): every change is written to the list at once ──
    def get_alarm_list(self, name: str) -> str:
        """A list as the editor shows it: each row's fields and its sentence, plus what can be chosen."""
        setup = machine.setup(self._machine()) if self._machine() else None
        run = self._alarm_run(name, setup)
        shown = rows_in_unit(run.rows, run.desktop_devices, run.unit) # the thresholds in the unit shown
        rows = [{"n": i + 1, **{f: getattr(a, f) for f in Alarm.__dataclass_fields__}, **run.texts[i]}
                for i, a in enumerate(shown)]
        sources = [{"code": -3, "name": "None"}, {"code": 1, "name": "BT"}, {"code": 0, "name": "ET"},
                   {"code": -1, "name": "BT RoR"}, {"code": -2, "name": "ET RoR"}]
        sources += [{"code": 2 + 2 * d + c, "name": run.probe(2 + 2 * d + c)[0]}
                    for d in range(len(run.desktop_devices)) for c in (0, 1)]
        buttons = [{"n": k + 1, "command": b.command or "", "kind": b.kind} for k, b in enumerate(run.setup.event_buttons)]
        return json.dumps({"name": name, "rows": rows, "sources": sources, "buttons": buttons,
                           # ON and START are both the tablet's Start: the editor offers START
                           "anchors": [{"code": code, "name": ANCHOR_WORDS.get(key, "After another alarm")}
                                       for code, key in ANCHORS.items() if key != "on"],
                           "levers": {k: v["name"] for k, v in run.levers.items()},
                           "computer_actions": [{"code": c, "name": n} for c, n in ARTISAN_ACTIONS.items()]})

    def _alarm_rows(self, name: str) -> list[Alarm]:
        if self.alarm_lists is None or name not in self.alarm_lists.names():
            raise ValueError("No such alarm list")
        return self.alarm_lists.rows(name)

    def _save_alarms(self, name: str, rows: list[Alarm]) -> str:
        self.alarm_lists.save(name, rows)
        return self.get_alarm_list(name)

    def edit_alarm(self, data: str) -> str:
        """{"name", "row" (from 0), "fields"}: the fields a chip or a switch changed."""
        request = json.loads(data)
        rows = self._alarm_rows(request["name"])
        index = int(request["row"])
        if not 0 <= index < len(rows):
            raise ValueError("No such alarm")
        changes = _alarm_fields(request["fields"], len(rows), index)
        unit, devices = (self.config or {}).get("unit", "C"), self._desktop_devices()
        kind = threshold_kind(changes.get("source", rows[index].source), devices)
        if "temperature" in changes: # typed in the unit shown, kept in °C
            changes["temperature"] = from_unit(changes["temperature"], kind, unit, typed=True)
        elif "source" in changes: # a new source keeps the value shown
            shown = in_unit(rows[index].temperature, threshold_kind(rows[index].source, devices), unit)
            changes["temperature"] = from_unit(shown, kind, unit)
        rows[index] = replace(rows[index], **changes)
        return self._save_alarms(request["name"], rows)

    def add_alarm(self, name: str) -> str:
        return self._save_alarms(name, append_row(self._alarm_rows(name), NEW_ALARM))

    def delete_alarm(self, data: str) -> str:
        """{"name", "row"}: the alarm goes; the list before it is kept for Undo."""
        request = json.loads(data)
        rows = self._alarm_rows(request["name"])
        self._alarm_undo = (request["name"], rows)
        return self._save_alarms(request["name"], remove_row(rows, int(request["row"])))

    def undo_alarm(self, name: str) -> str:
        if self._alarm_undo is None or self._alarm_undo[0] != name:
            raise ValueError("Nothing to undo")
        rows, self._alarm_undo = self._alarm_undo[1], None
        return self._save_alarms(name, rows)

    def move_alarm(self, data: str) -> str:
        """{"name", "from", "to"}: positions from 0; references follow their alarms."""
        request = json.loads(data)
        rows = self._alarm_rows(request["name"])
        source, target = int(request["from"]), int(request["to"])
        if not (0 <= source < len(rows) and 0 <= target < len(rows)):
            raise ValueError("No such alarm")
        return self._save_alarms(request["name"], move_row(rows, source, target))

    def new_alarm_list(self) -> str:
        """An empty list, opened at once."""
        if self.alarm_lists is None:
            raise ValueError("Set the tablet up first")
        self.alarm_lists.folder.mkdir(parents=True, exist_ok=True)
        name = self.alarm_lists.new_name()
        self.alarm_lists.save(name, [])
        return self.get_alarm_list(name)

    def delete_alarm_list(self, name: str) -> str:
        self._alarm_rows(name)
        self.alarm_lists.remove(name)
        self.alarm_lists.folder.with_name("alarms-shared").joinpath(f"{name}.alrm").unlink(missing_ok=True)
        if (self.config or {}).get("alarm_list") == name:
            return self.set_alarm_list("")
        return self.get_alarms()

    def alarm_list_file(self, name: str) -> str:
        """The list's .alrm file for the share sheet, its thresholds in the unit shown (UNIT-SPEC decision 3)."""
        rows = rows_in_unit(self._alarm_rows(name), self._desktop_devices(), (self.config or {}).get("unit", "C"))
        shared = self.alarm_lists.folder.with_name("alarms-shared") / f"{name}.alrm"
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text(write_alrm(rows), encoding="utf-8")
        return str(shared)

    def _alarm_run(self, name: str, setup) -> TabletAlarms:
        config = self.config or configuration.default()
        levers = configuration.levers(config) if config["machine"] else {}
        devices = config["devices"]
        extractor = bool((devices.get("extractor") or {}).get("enabled"))
        ambient = bool((devices.get("ambient") or {}).get("enabled"))
        return TabletAlarms(name, self.alarm_lists.rows(name), setup or read_setup(""), levers, extractor, ambient,
                            self._desktop_devices(), config.get("unit", "C"))

    def _desktop_devices(self) -> list[str]:
        """The computer's extra devices, in its order, from its latest roast on the tablet (its tilau_name_map)."""
        if self.roasts is None:
            return []
        files = sorted(self.roasts.folder("computer").glob("*.alog"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:5]:
            try:
                # The one key read out of the file, as the roast index reads its fields: parsing it whole costs seconds
                names = _literal(_slice_value(path.read_bytes(), "tilau_name_map")) or {}
                return [str(names[slot]) for slot in sorted(names, key=int)]
            except (OSError, ValueError, AttributeError, KeyError, TypeError):
                continue
        return []

    def _start_auto(self) -> None:
        """Following the coffee's plan, its AUTO milestones; by hand, the detections of Settings › General.
        Following a roast, Charge detection only (decision 13)."""
        self.auto = None
        if not (self._real() or self.replay is not None):
            return
        config, targets, following = self.config or {}, self._plan_targets, self.playback is not None
        if targets is not None and not following:
            armed = config.get("auto_marks") or []
        else:
            targets = {}
            armed = ["charge"] if config.get("charge_detection", True) else []
            if not following:
                armed += [m for m, key in (("dry_end", "dry_end_detection"), ("first_crack", "crack_detection")) if config.get(key)]
        if armed:
            # Without the plan's, the target is the trade's in this roaster's bean probe frame, as Artisan's Phases
            offsets = machine.bt_offsets(self._machine()) if self._machine() else None
            offsets = offsets if offsets and len(offsets) > 2 else None
            dry_end = targets.get("dry_end") or (PROFESSION_DE_TRUE_C[0] + offsets[1] if offsets else None)
            first_crack = targets.get("first_crack") or (PROFESSION_FC_TRUE_C[0] + offsets[2] if offsets else None)
            drop = machine.drop_detection(self._machine()) if self._machine() else (None, None)
            self.auto = AutoMarks(armed, dry_end, first_crack, self._replay_marks if self.replay is not None else None, drop)

    def _crack_probe(self) -> bool:
        """A crack counter to listen to: TilauAmbient switched on, or the replayed file's."""
        if self.replay is not None:
            return self._replay_cracks is not None
        probe = ((self.config or {}).get("devices") or {}).get("ambient")
        return bool(probe and probe.get("enabled"))

    def _crack_listening(self) -> bool:
        """The probe's sequence this roast: for the plan's AUTO First crack, or by hand for Crack detection."""
        config = self.config or {}
        wanted = "first_crack" in (config.get("auto_marks") or []) if self._plan_targets is not None \
            else config.get("crack_detection")
        return self._crack_probe() and bool(wanted) and self.playback is None # following a roast, no AUTO uses the count

    def _respond(self) -> None:
        """From CHARGE to DROP, the replayed BT moves away by what the burner and air did differently."""
        marks = self.session.milestones
        if self.response is None or "charge" not in marks or "drop" in marks:
            return
        phase = "dev" if "first_crack" in marks else "mai" if "dry_end" in marks else "dry"
        self.response.step(self.now, {lever: self.levers.get(lever, 0) for lever in ("burner", "air")}, phase)

    def _marks(self) -> list[int]:
        """The milestones as Artisan's timeindex: CHARGE -1 when unmarked, the others 0."""
        marks = [-1, 0, 0, 0, 0, 0, 0, 0]
        for key, index in self.session.milestones.items():
            marks[MARK_INDEX[key]] = index
        return marks

    def _tp_step(self) -> None:
        if self._tp.index is None and "charge" in self.session.milestones:
            samples = self.session.samples
            self._tp.update([s.elapsed_s for s in samples], [s.bt_c for s in samples], self._marks())

    def _tp_view(self) -> dict | None:
        """The turning point for the curve: live while recording, else the lowest BT as the roast file has it."""
        samples = self.session.samples
        if "charge" not in self.session.milestones or not samples:
            return None
        index = self._tp.index
        if index is None and (self.session.state != "recording" or self.interrupted):
            index = alog.find_tp(self._marks(), [s.elapsed_s for s in samples], [s.bt_c for s in samples]) or None
        if index is None or index <= self.session.milestones["charge"]:
            return None
        return {"s": samples[index].elapsed_s, "c": round(samples[index].bt_c, 1)}

    def _crack_step(self) -> None:
        """The next step of the crack counter's sequence, once its time has come."""
        sent, marks = self._crack_sent, self.session.milestones
        if sent is None:
            return
        if "cal1" not in sent:
            if "charge" in marks: # beans in before the empty drum was heard: the probe refuses CAL2 without CAL1
                self._crack_sent = None
            elif self.now - self._started_s >= CRACK_DELAYS_S["cal1"]:
                self._crack_command("cal1")
        elif "drop" in marks: # STOP left with the mark
            return
        elif "cal2" not in sent:
            dry_end = self._elapsed("dry_end") # touched or found; undone before CAL2, it is waited for again
            if dry_end is not None and self.now - dry_end >= CRACK_DELAYS_S["cal2"]:
                self._crack_command("cal2")
        elif "start" not in sent and self.now - sent["cal2"] >= CRACK_DELAYS_S["start"]:
            self._crack_command("start")

    def _crack_command(self, step: str) -> None:
        sent = self._crack_sent
        if sent is None or step in sent or (step == "stop" and "start" not in sent):
            return
        sent[step] = self.now
        if self._real():
            self._devices_out.append({"device": "ambient", "op": "command", "value": CRACK_CODES[step]})

    def _crack_view(self) -> dict | None:
        """The calibration listening now, and the seconds it has left, for the roast screen's chip."""
        for step, phase in (("cal2", "beans"), ("cal1", "empty")):
            when = (self._crack_sent or {}).get(step)
            if when is not None and self.session.state == "recording" and self.now - when < CRACK_ACQUISITION_S:
                return {"phase": phase, "left_s": int(CRACK_ACQUISITION_S - (self.now - when))}
        return None

    def crack_count(self, count: int) -> None:
        """The crack counter's cumulative count, as TilauAmbient sends it."""
        if type(count) is not int or count < 0:
            raise ValueError("A crack count is a whole number")
        self._cracks = (self.clock(), count)

    def door_frame(self, data: str, seq: int, age_ms: int) -> None:
        """A drop door frame read by the probe link (hex), its read number, and how long ago it was read."""
        if type(seq) is not int or type(age_ms) is not int or age_ms < 0:
            raise ValueError("A door frame comes with its read number and age")
        frame = parse_frame(bytes.fromhex(data))
        if frame is None:
            raise ValueError("Not a drop door frame")
        self._door_heard = self.clock()
        if seq == self._door_seq:
            return
        self._door_seq = seq
        clock = self.now if self._origin is None else self.real_clock() - self._origin
        opened = self._door.read(frame, clock - age_ms / 1000.0)
        if opened is not None:
            self._door_opened = opened

    def _door_view(self) -> str | None:
        """The header's door pill: "closed" or "open", None (grey) without a contact seen closed or a fresh frame."""
        if self._door_heard is None or self.clock() - self._door_heard > ROOM_MAX_AGE_S:
            return None
        return {DoorState.READY: "closed", DoorState.OPEN: "open"}.get(self._door.state)

    def _door_step(self) -> None:
        """The door's DROP, on the sample it opened, whatever the automatic marks: it measures, it does not guess."""
        opened, marks, samples = self._door_opened, self.session.milestones, self.session.samples
        if opened is None:
            return
        if self.session.state != "recording" or "charge" not in marks or "drop" in marks:
            self._door_opened = None
            return
        if not samples or self.session.stale(self.now):
            return # marked once the readings are fresh again
        self._door_opened = None
        index = min(range(len(samples)), key=lambda i: abs(samples[i].elapsed_s - opened))
        self._mark("drop", max(index, max(marks.values())))

    def _auto_step(self) -> None:
        if self.session.stale(self.now): # a detector fires once: never on a sample the session refuses to mark
            return
        cracks = self._cracks[1] if self._cracks and self.clock() - self._cracks[0] <= ROOM_MAX_AGE_S else None
        found = self.auto.step(self.session, cracks)
        if found is not None and self.session.state == "recording":
            self._mark(*found)
            self._auto_toast("marked", found[0])

    def _drop_auto(self, lever: bool = False) -> None:
        """Following a roast, the automation drops at the first hand. Following the plan (guided or AUTO) a lever
        is the gesture the plan asks for: only an undo drops the milestones (GUIDED-SPEC, 2026-11-08). By hand,
        levers are the roast itself and only an undo drops the detections."""
        if self.session.state != "recording" or (lever and (self._plan_targets is None or self.playback is None)):
            return
        if lever and "charge" not in self.session.milestones: # in preheat a hand takes the PID only; AUTO waits for CHARGE
            return
        followed = self.playback is not None
        self.playback = None
        if self.auto is not None and self.auto.active:
            self.auto.dropped = True
        elif not followed:
            return
        self._auto_toast("unfollowed" if followed else "dropped", None)

    def _auto_toast(self, kind: str, milestone: str | None) -> None:
        self._auto_event = {"seq": self._auto_event["seq"] + 1, "kind": kind, "milestone": milestone}

    def set_auto_mark(self, data: str) -> str:
        """AUTO of one milestone on or off, kept for the next roasts; answers with the Plan tab."""
        request = json.loads(data)
        if request.get("milestone") not in configuration.AUTO_MILESTONES:
            raise ValueError("Unknown milestone")
        armed = set((self.config or {}).get("auto_marks") or [])
        (armed.add if request.get("on") else armed.discard)(request.get("milestone"))
        if self.config is None or not self.config_path:
            raise ValueError("No configuration file")
        self.config = configuration.save(self.config_path, {**self.config, "auto_marks": sorted(armed)})
        return self.get_plan(json.dumps({"green": request.get("green")}))

    # ── Guided and AUTO (GUIDED-SPEC) ───────────────────────────────────
    def _roast_plan(self) -> dict | None:
        """The coffee's plan as the Plan tab shows it now (its batch weight), None when the tab has none."""
        bean = self._bean()
        green = float((self.setup or {}).get("green") or 0)
        if bean is None or green <= 0 or not (self.config or {}).get("machine") or not self._plan_settings()["plan_level"]:
            return None
        temperature, humidity, altitude, _probe = self._plan_room()
        return plan_generate(self._plan_engine(), bean, self._plan_settings()["plan_level"], green,
                             (temperature, humidity, altitude, (self.room() or {}).get("pressure_hpa")))

    def _roast_context(self):
        entry = catalogue.MACHINES.get(self._machine() or "")
        return RoasterManager().get_roast_context(f"{entry['manufacturer']} {entry['model']}") if entry else None

    def roast_time(self) -> float:
        """Seconds since CHARGE, 0 before it."""
        charge = self._elapsed("charge")
        return 0.0 if charge is None else self.now - charge

    def roast_phase(self) -> str | None:
        """'DRY', 'MAI' or 'DEV' between CHARGE and DROP, None outside the roast."""
        marks = self.session.milestones
        if "charge" not in marks or "drop" in marks:
            return None
        return "DEV" if "first_crack" in marks else "MAI" if "dry_end" in marks else "DRY"

    def _since_charge(self, milestone: str) -> float:
        at, charge = self._elapsed(milestone), self._elapsed("charge")
        return 0.0 if at is None or charge is None else at - charge

    def _tp_s(self) -> float:
        index, charge = self._tp.index, self.session.milestones.get("charge")
        if index is None or charge is None or index <= charge:
            return 0.0
        return self.session.samples[index].elapsed_s - self.session.samples[charge].elapsed_s

    def _plan_number(self, key: str) -> float | None:
        return _number((self._live_plan or {}).get(key))

    def _guide_ror(self) -> float | None:
        """BT RoR now, as the plan reads a past roast's (tilaucore.ror, the machine's smoothing level): the
        rate the crash rule and AUTO read. The last minute is enough."""
        samples, charge = self.session.samples, self.session.milestones.get("charge")
        if charge is None or self.session.stale(self.now):
            return None
        tail = samples[max(charge, len(samples) - 60):]
        if len(tail) < 10:
            return None
        settings = machine.setup(self._machine()).ror if self._machine() else RoRSettings()
        return rate_now([s.elapsed_s for s in tail], [s.bt_c for s in tail], settings)

    def _guide_step(self) -> None:
        """Once a sample: the crash rule, AUTO's tick, then the bubble (none while AUTO drives)."""
        phase, t_now, bt = self.roast_phase(), self.roast_time(), self.session.samples[-1].bt_c
        ror = self._guide_ror()
        rise = phase == "DEV" and burner_may_rise(self._live_plan, t_now, self._since_charge("first_crack"))
        self.guide.crash_check(ror, phase, t_now, self._tp_s(), rise)
        targets = self._plan_targets or {}
        engine = self.pilot.engine if self.pilot is not None else None
        if engine is not None and engine.state == "armed" and self.session.state == "recording":
            pending = None
            if phase is not None:
                pending = "FC" if "dry_end" in self.session.milestones else "DE"
                pending = None if "first_crack" in self.session.milestones else pending
            engine.tick(bt, ror, t_now=t_now, t_tp=self._tp_s(), t_fcs=self._since_charge("first_crack"),
                        confirmed_dev=phase == "DEV", pending=pending, suggested=False,
                        dry_end_temp=targets.get("dry_end") or 0.0, fc_temp=targets.get("first_crack") or 0.0,
                        mode="C", scale=1.0)
        if engine is not None and engine.state == "armed":
            self._bubble = None # AUTO speaks through its toast
            return
        steps = {lever: float(self.lever_setup[lever]["step"]) for lever in ("air", "burner") if lever in self.lever_setup}
        self._bubble = self.guide.bubble(
            phase=phase, bt=bt, ror=ror, t_now=t_now, t_tp=self._tp_s(), levers=self.levers, steps=steps,
            targets={"first_crack": targets.get("first_crack"), "drop": self._plan_number("Drop Temp"), "ror": None,
                     "ror_drop": None})

    def crash_message(self, dev: bool, raise_burner: bool) -> str | None:
        """The crash this sample, for AUTO (its pause or its net); None without one."""
        if self.guide is None or self.guide.crash_text is None:
            return None
        return " · ".join(self.guide.crash_text)

    def _after_mark(self, milestone: str) -> None:
        """A milestone marked, by touch, a detector or AUTO: the live plan re-anchored on it, then AUTO's levers."""
        if self.guide is not None:
            self.guide.crash.reset("C")
        key = {"dry_end": "dry_end", "first_crack": "fc_start"}.get(milestone)
        if key is not None and self._live_plan is not None and self.session.state == "recording":
            try:
                index = self.session.milestones[milestone]
                bt = self.session.samples[index].bt_c
                plan = self._plan_engine().replan_from_milestone(self._live_plan, key, self._since_charge(milestone) / 60.0, bt)
                self._live_plan = self.guide.plan = plan
                if self.pilot is not None:
                    self.pilot.plan = plan
            except Exception as error: # noqa: BLE001 - a plan not re-anchored still guides
                print(f"TilauScope replan {key} skipped: {error}")
        if self.pilot is not None and self.session.state == "recording":
            phase = {"charge": "DRY", "dry_end": "MAI", "first_crack": "DEV", "drop": "DROP"}.get(milestone)
            if phase is not None:
                self.pilot.engine.milestone(phase)

    def auto_pilot_mark(self, milestone: str) -> None:
        if self.session.state == "recording" and milestone not in self.session.milestones:
            self._mark(milestone)

    def replayed_mark(self, milestone: str) -> bool | None:
        """In a simulation, whether the replayed roast has reached its own milestone; None live or without one."""
        if self.replay is None:
            return None
        at = self._replay_marks.get(milestone)
        return None if at is None else self.now >= at

    def extractor_command(self, op: str, value: str) -> None:
        extractor = ((self.config or {}).get("devices") or {}).get("extractor")
        if extractor and extractor.get("enabled") and self._real():
            self._devices_out.append({"device": "extractor", "op": op, "value": value})

    def pilot_extractor(self, value: int) -> None:
        """AUTO's extractor speed: sent to the AirWave, held as its value so the echo reads as AUTO's.
        Within the AirWave's own range (AirWaveLink.SPEED_MIN/MAX): a speed it clamps would echo back as a hand."""
        value = max(AIRWAVE_SPEED[0], min(AIRWAVE_SPEED[1], value))
        self.extractor_command("speed", str(value))
        if self.levers.get("extractor") != value:
            self.levers["extractor"] = value
            if self.session.state == "recording":
                self._record("extractor", value)

    def _drop_gauge(self) -> float | None:
        """In development, the bean's way from first crack to the plan's drop temperature, 0 to 1."""
        drop, fc = self._plan_number("Drop Temp"), self.session.milestones.get("first_crack")
        if self.roast_phase() != "DEV" or drop is None or fc is None or not self.session.samples:
            return None
        start = self.session.samples[fc].bt_c
        if drop <= start:
            return None
        return round(max(0.0, min(1.0, (self.session.samples[-1].bt_c - start) / (drop - start))), 3)

    def resume_auto(self) -> str:
        """The AUTO chip after a pause: AUTO drives again, the levers left as they are."""
        if self.pilot is not None and self.pilot.engine.state == "paused" and self.session.state == "recording":
            self.pilot.engine.arm(self.roast_phase())
        return self.snapshot()

    def cancel_auto_drop(self) -> str:
        """Wait: no auto-drop this roast, the drop is by hand."""
        if self.pilot is not None:
            self.pilot.engine.cancel_drop()
            self.pilot.drop_in = None
        return self.snapshot()

    # ── Follow a roast (AUTOMATION-SPEC decision 13) ────────────────────
    def _bean(self):
        """The chosen coffee's BeanCave record, None without one."""
        return next((b for b in self.cave.beans() if b.uuid == self.coffee["uuid"]), None) \
            if self.coffee and self.cave else None

    def _follow_source(self, bean=None) -> tuple[str, str] | None:
        """The roast to follow: in simulation the one replayed, else picked by hand, else the coffee's reference ★."""
        if self.replay is not None and self._replay_source is not None:
            return self._replay_source
        if self._follow_pick is not None:
            return self._follow_pick
        bean = bean or self._bean()
        reference = bean.reference_roast_uuid if bean else ""
        if not reference or self.roasts is None:
            return None
        return next(((origin, m.filename) for origin, m in self.roasts.records() if m.roast_uuid == reference), None)

    def _followed_roast(self, bean=None) -> FollowedRoast | None:
        source = self._follow_source(bean)
        if source is None:
            return None
        ror = machine.setup(self._machine()).ror if self._machine() else RoRSettings()
        key = (source, ror)
        if self._followed is None or self._followed[0] != key:
            try:
                self._followed = (key, FollowedRoast(self.roasts.path(*source), ror))
            except (OSError, ValueError, SyntaxError, TypeError, KeyError, MemoryError):
                return None # unreadable: nothing to follow, the plan stays reachable
        return self._followed[1]

    def _follow_view(self, bean=None) -> dict:
        """The roast START can follow, for its button: picked by hand, else the coffee's reference ★."""
        bean = bean or self._bean()
        roast = self._followed_roast(bean)
        source = self._follow_source(bean)
        reference = bean.reference_roast_uuid if bean else None
        view = roast.view() if roast is not None else None
        if view is not None:
            view.update(origin=source[0], name=source[1], reference=bool(reference) and any(
                (origin, m.filename) == source and m.roast_uuid == reference for origin, m in self.roasts.records()))
        return {"roast": view}

    def set_follow(self, data: str) -> str:
        """The roast START follows ({origin, name}), picked in BeanCave › Roasts in place of the reference ★."""
        if self.session.state == "recording":
            raise ValueError("What a roast follows is chosen before it")
        request = json.loads(data)
        self.roasts.path(request["origin"], request["name"]) # raises when there is no such roast
        self._follow_pick = (request["origin"], request["name"])
        if self._followed_roast() is None:
            raise ValueError("No roast to follow: star a reference roast, or pick one in Roasts")
        self._save_choice()
        return self.get_plan(json.dumps({"green": request.get("green")}))

    def _start_follow(self) -> None:
        """Following a roast, its playback waits for CHARGE, touched by hand."""
        self.playback = None
        self._follow_extractor.clear()
        if self._follow != "roast" or not (self._real() or self.replay is not None):
            return
        roast = self._followed_roast()
        if roast is None:
            return
        self.playback = roast.playback()
        self._follow_paused = False
        self._plan_targets = roast.targets() # a roast followed is a plan followed: no alarms (decision 9)
        self._follow_tp = TurningPoint()

    def _roaster_name(self) -> str:
        entry = catalogue.MACHINES[self._machine()]
        return f"{entry['manufacturer']} {entry['model']}"

    def _engage_follow(self) -> None:
        """At CHARGE: the followed roast moves onto this one's CHARGE. A CHARGE found is marked a few seconds
        back: the moves of those seconds are due at once, not past."""
        charge = self.session.samples[self.session.milestones["charge"]].elapsed_s
        self.playback.align(charge)
        self.playback.engage(charge, charge, 1.0)

    def _follow_step(self) -> None:
        if "charge" not in self.session.milestones or self.session.state != "recording":
            return
        live = follow_live(self.session)
        live.tp_index = self._follow_tp.update(live.timex, live.temp2, [self.session.milestones["charge"], 0, 0, 0, 0, 0, 0, 0])
        jumps, _ = self.playback.step(live.timex[-1], live)
        for kind, value in jumps.items(): # a move of the followed roast: recorded as the hand's would be
            self._follow_move(LEVER_OF[kind], value)

    def _follow_move(self, lever: str, value: float) -> None:
        percent = max(0, min(100, int(round(value))))
        if lever == "extractor": # the AirWave, as its own buttons would; its echo records the setting
            extractor = ((self.config or {}).get("devices") or {}).get("extractor")
            last = self._follow_extractor[-1] if self._follow_extractor else None
            if extractor and extractor.get("enabled") and self._real() and percent != last:
                self._devices_out.append({"device": "extractor", "op": "speed", "value": str(percent)})
                self._follow_extractor.append(percent)
            return
        if lever in self.levers:
            self._lever(lever, percent)

    def _start_alarms(self) -> None:
        self.alarms = None
        if self._plan_targets is not None: # alarms are a manual tool: none while a plan is followed (decision 9)
            return
        name = (self.config or {}).get("alarm_list")
        if not name or self.alarm_lists is None or name not in self.alarm_lists.names() or not self._machine():
            return
        self.alarms = self._alarm_run(name, machine.setup(self._machine()))

    def _run_alarm(self, act: Act) -> None:
        """A fired alarm, run as the operator's hand would (decision 7)."""
        number = act.row + 1
        if act.lever is not None:
            value = self.alarms.resolve(act, self.levers)
            if value is not None and self.session.state == "recording":
                self._lever(act.lever, value, alarm=number)
        if act.commands:
            self._send(list(act.commands))
        for verb, argument in act.extractor:
            self._devices_out.append({"device": "extractor", "op": verb, "value": argument})
            if verb == "speed":
                self._alarm_extractor = (int(argument), number)
        for code in act.ambient if self._crack_sent is None else (): # the sequence is the probe's one master
            self._devices_out.append({"device": "ambient", "op": "command", "value": code})

    def _cool_extractor(self) -> None:
        """The extractor as the roaster's cooling sets it (roasters.json): its mode first, which brings back
        the device's last speed, then the speed."""
        settings = machine.cooling(self._machine())
        extractor = ((self.config or {}).get("devices") or {}).get("extractor")
        if settings is None or settings.extractor_pct is None or not (extractor and extractor.get("enabled")) or not self._real():
            return
        if settings.extractor_mode:
            self._devices_out.append({"device": "extractor", "op": "mode", "value": settings.extractor_mode})
        self._devices_out.append({"device": "extractor", "op": "speed", "value": f"{settings.extractor_pct:g}"})

    def take_device_commands(self) -> str:
        """The accessory commands since the last call, in order (the service sends them)."""
        commands, self._devices_out = self._devices_out, []
        return json.dumps(commands)

    def take_commands(self) -> str:
        """The commands for the roaster since the last call, in order (the link sends them)."""
        commands, self._outbox = self._outbox, []
        return json.dumps(commands)

    def snapshot(self, since: int = 0) -> str:
        """Live values plus the samples from index `since` (0 when it is out of range)."""
        session = self.session
        room, room_source = self._room_and_source()
        if session.state == "idle":
            # The real roaster is read once its link opens with the roast: nothing before.
            reading = None if self._real() else self._reading()
            data = {"schema_version": 1, "state": "idle", "simulated": not self._real(), "elapsed_s": 0,
                    "sample_count": 0, "bt_c": reading.bt_c if reading else None, "et_c": reading.et_c if reading else None,
                    "stale": False, "ror_c_per_min": None, "milestones": {}}
        else:
            data = session.snapshot(self.now)
        if not 0 <= since <= len(session.samples):
            since = 0
        data.update({
            "interrupted": self.interrupted, "signal": self.signal,
            "readonly": self.readonly, "configured": self.config is not None,
            "levers": {k: {"value": v, "echo": self.echo[k], "pending": k in self.pending,
                           "step": self.lever_setup[k]["step"], "name": self.lever_setup[k]["name"]}
                       for k, v in self.levers.items()},
            "settings": [list(setting) for setting in session.settings],
            "ambient_at_charge": session.ambient,
            "weights_g": dict(session.weights),
            "colours": dict(session.colours), "colour_levels": COLOUR_LEVELS,
            "exported": session.exported,
            "coffee": {"name": self.coffee["name"], "stock_g": self.coffee["stock_g"], "decrease": self.setup["decrease"]}
                      if self.coffee else None,
            "stock_move": session.stock_move,
            "alarms": self.alarms.view(self.now, self._elapsed("charge")) if self.alarms is not None else None,
            "alarm_settings": sorted(session.alarm_settings),
            "link": dict(self.link) if self.link else None,
            "auto": {"active": self.auto is not None and self.auto.active, **self._auto_event},
            "pilot": self.pilot.view() if self.pilot is not None else None, # AUTO (GUIDED-SPEC)
            "guide": self._bubble if session.state == "recording" else None, # the bubble over the curve
            "drop_gauge": self._drop_gauge() if session.state == "recording" else None,
            "follow": self._follow, # what this roast follows, chosen at START
            "follow_paused": self.playback is not None and self._follow_paused,
            "crack_detection": self._crack_view(),
            "tp": self._tp_view(),
            "simulation": {"title": self.replay_name, "position_s": min(self.now, self.replay.length_s),
                           "length_s": self.replay.length_s, "speed": self.speed} if self.replay is not None else None,
            **self._live_after_roast(),
            "preheat": self.preheat.view(self._preheat_reading(), self.session.ror(self.now) if self.session.state == "recording" else None)
                       if self.preheat is not None else None,
            # The coffee the roast names, whose label can be printed once it is over.
            "label_coffee": session.beans.split("\n", 1)[0] if _UUID_RE.search(session.beans) else None,
            "last_sample_s": session.samples[-1].elapsed_s if session.samples else None,
            "room": room, "room_source": room_source, # the header's Room pill
            "door": self._door_view(), # the header's door pill
            "late_s": round(self._late[1]) if self._late and session.state == "recording"
                      and self.now - self._late[0] < LATE_SHOWN_S else None, # the link pill's late state
            "late_sampling": session.late_sampling,
            "energy": self._energy_card() if session.state == "stopped" else None, # the end card's Energy
            "unit": (self.config or {}).get("unit", "C"), # what the screens show (UNIT-SPEC); the session is °C
            "milestone_s": {key: self._elapsed(key) for key in session.milestones},
            "samples_from": since,
            "samples": [[s.elapsed_s, round(s.bt_c, 2), None if s.et_c is None else round(s.et_c, 2),
                         None if r is None else round(r, 2)]
                        for s, r in zip(session.samples[since:], session.ror_series[since:])],
        })
        return json.dumps(data, allow_nan=False)

    def save(self, filename: str) -> str:
        """Atomic JSON checkpoint. Caller supplies an app-private path, never .alog."""
        target = Path(filename)
        if target.suffix != ".json":
            raise ValueError("Prototype checkpoints must use the .json extension")
        payload = json.dumps(self.session.document(self.now), allow_nan=False, indent=2)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             prefix=".session-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self.snapshot()


def _alarm_fields(fields: dict, count: int, index: int) -> dict:
    """The editor's changes to one alarm, checked as the .alrm holds them; ValueError names the first wrong one."""
    clean = {}
    for key, value in fields.items():
        if key in ("on", "beep"):
            if value not in (0, 1, True, False):
                raise ValueError(f"{key} is on or off")
            clean[key] = int(value)
        elif key == "anchor":
            if value not in ANCHORS:
                raise ValueError("Unknown moment")
            clean[key] = value
        elif key == "offset":
            if type(value) is not int or not 0 <= value <= 3600:
                raise ValueError("A delay is whole seconds, up to an hour")
            clean[key] = value
        elif key in ("guard", "negguard"):
            if type(value) is not int or not (value == -1 or (0 <= value < count and value != index)):
                raise ValueError("No such alarm to follow")
            clean[key] = value
        elif key == "cond":
            if value not in (0, 1, 2, 3):
                raise ValueError("Unknown comparison")
            clean[key] = value
        elif key == "source":
            if type(value) is not int or not -3 <= value < 64:
                raise ValueError("Unknown probe")
            clean[key] = value
        elif key == "temperature":
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("A value is a number")
            clean[key] = float(value)
        elif key == "action":
            if type(value) is not int or not -1 <= value <= 28:
                raise ValueError("Unknown action")
            clean[key] = value
        elif key == "text":
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("The action's text is too long")
            clean[key] = value
        else:
            raise ValueError(f"Unknown field {key}")
    return clean

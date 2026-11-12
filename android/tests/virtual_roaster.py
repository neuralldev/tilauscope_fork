# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""A Skywalker V2 on the bench, so the app is checked from START to the roaster's stop without a machine.

`Bench` plays the service's part (SessionService): it runs the session's 1 Hz tick, hands its commands to the
link, lets the link go after End roast, and opens the roast link once START is taken, as the roast screen does.
`VirtualRoaster` plays the link and the machine: the states and rules of Tc4Link (burner verified at 0 at each
connection, heat never kept while away, recovery with air and drum only, the cooling wait, back to back), and a
drum that warms with the burner and cools with the air. The thermal law is qualitative only: it checks the
app's logic (does the burner rise, does the cooling end), never a roasting value. Tc4Link's own rules are
checked on the GATT bench (app/src/test, Tc4LinkTest): what is mirrored here must follow them.
"""
import json

ROOM_C = 22.0
VERIFY_S = 1 # Tc4Link: OT1,0 then its echo read back
CONNECT_S = 2


def kept_while_away(commands):
    """Tc4Link.keptWhileAway: never heat, the roaster cut it by itself."""
    def heat(cmd):
        name, _, value = cmd.partition(",")
        try:
            return name.strip().upper() == "OT1" and float(value) > 0
        except ValueError:
            return False
    return [c for c in commands if not heat(c)]


class VirtualRoaster:
    def __init__(self, bt=ROOM_C):
        self.bt = bt
        self.burner, self.air, self.drum = 0, 0, 0
        self.cooling_on = False # its cooling button (CLDN,ON)
        self.stopped = True
        self.state = "idle"
        self.roast = False
        self.live = False # a roast link once connected: a later connection is a recovery
        self.recovered = False
        self.script, self.after = [], None
        self.cmd_air = self.cmd_drum = None
        self.received = [] # every order the machine got, in order
        self._wait = 0
        self._next = None
        self.on_state = lambda state, recovered: None

    # ── the machine ──────────────────────────────────────────────────────
    def step(self):
        """One second of the drum: the burner heats, the room and the air take heat away."""
        loss = 0.004 + (0.015 if self.cooling_on else 0.0) + 0.002 * self.air / 100
        self.bt += 0.02 * self.burner - loss * (self.bt - ROOM_C)

    def _order(self, cmd):
        self.received.append(cmd)
        name, _, value = cmd.partition(",")
        name = name.strip().upper()
        if name in ("OT1", "OT2", "OT3"):
            setattr(self, {"OT1": "burner", "OT2": "air", "OT3": "drum"}[name], int(float(value)))
            self.stopped = False
            if name == "OT2":
                self.cmd_air = int(float(value))
            elif name == "OT3":
                self.cmd_drum = int(float(value))
        elif cmd == "CLDN,ON":
            self.cooling_on = True
        elif cmd == "CLDN,OF":
            self.cooling_on = False
        elif cmd == "OFF":
            self.burner = self.air = self.drum = 0
            self.cooling_on, self.stopped = False, True

    # ── the link (Tc4Link) ───────────────────────────────────────────────
    def _set(self, state):
        if state != self.state or self.recovered:
            self.state = state
            self.on_state(state, self.recovered)
            self.recovered = False

    def connect(self, roast=True):
        if roast and self.state == "cooling": # back to back: the cooling stops, the burner verified again
            self.script, self.after = [], None
            self._order("CLDN,OF")
            self.roast, self.live = True, False
            self._then("verifying", VERIFY_S, self._verified)
            return
        self.roast, self.live = roast, False
        self.script, self.after = [], None
        self.cmd_air = self.cmd_drum = None
        self._then("connecting", CONNECT_S, lambda: self._then("verifying", VERIFY_S, self._verified))

    def _then(self, state, seconds, next_step):
        self._set(state)
        self._wait, self._next = seconds, next_step

    def _verified(self):
        self._order("OT1,0")
        if self.roast and self.live: # back into a live roast: the mechanical state again, never the heat
            for value, cmd in ((self.cmd_air, "OT2"), (self.cmd_drum, "OT3")):
                if value is not None:
                    self._order(f"{cmd},{value}")
            self.recovered = True
        if self.roast:
            self.live = True
        self._set("connected")
        self._run()

    def command(self, commands):
        if not self.roast:
            return
        self.script += commands if self.state in ("connected", "cooling") else kept_while_away(commands)
        self._run()

    def _run(self):
        while self.script and self.state in ("connected", "cooling"):
            head = self.script[0]
            if head.startswith("UNTIL_BT_BELOW"):
                if self.bt >= float(head.split(",")[1]):
                    return
                self.script.pop(0)
                continue
            self._order(self.script.pop(0))
        if not self.script and self.after is not None:
            self.after = None
            self._close()

    def disconnect(self):
        """End roast: a hot roast is cooled first (its script), then stopped and let go."""
        if self.roast and self.state == "connected" and self.script:
            self.roast, self.live, self.after = False, False, "idle"
            self._set("cooling")
            self._run()
            return
        self.roast, self.live = False, False
        self._close()

    def _close(self):
        self.script, self.after = [], None
        self._order("OT1,0")
        self._order("OFF")
        self._set("idle")

    def drop(self, away_s):
        """The link goes for `away_s` seconds: the roaster cuts its burner by itself, then the link comes back."""
        self.burner = 0
        self._then("reconnecting", away_s, lambda: self._then("verifying", VERIFY_S, self._verified))

    def second(self):
        """One second of the link's own clock: a connection or a verification moves on."""
        if self._next is not None:
            self._wait -= 1
            if self._wait <= 0:
                step, self._next = self._next, None
                step()
        if self.state == "cooling":
            self._run() # the cooling wait reads the bean probe


class Bench:
    """The service around the session and the virtual roaster (SessionService)."""

    def __init__(self, demo, roaster=None):
        self.demo, self.roaster = demo, roaster or VirtualRoaster()
        self.clock = [1000.0]
        demo.clock = demo.real_clock = lambda: self.clock[0]
        self.link_roast = False
        self.burners = [] # the burner the machine had, each second
        self.roaster.on_state = self._link_state

    def _link_state(self, state, recovered):
        if not self.link_roast:
            return
        self.demo.link_state(json.dumps({"state": state, "recovered": recovered}))
        if state == "idle":
            self.link_roast = False

    def _route(self, method=None):
        commands = json.loads(self.demo.take_commands())
        if self.link_roast:
            self.roaster.command(commands)
            if method == "stop":
                self.roaster.disconnect()

    def do(self, method, *args):
        """An operator's action, as the page sends it; START then opens the roast link."""
        answer = json.loads(getattr(self.demo, method)(*args))
        if method == "start" and answer.get("state") == "recording":
            self.link_roast = True
            self.roaster.connect()
        self._route(method)
        return answer

    def run(self, seconds, until=None):
        """`seconds` of the service at most, stopping once `until(snapshot)` is true; the last snapshot.

        Each second the session ticks before the link moves on: every link state lasts at least one tick, the
        worst order for the app (on the tablet the 1 Hz tick and the link's 400 ms verification are not in step)."""
        snap = json.loads(self.demo.snapshot())
        for _ in range(seconds):
            self.clock[0] += 1
            self.roaster.step()
            if self.link_roast and self.roaster.state in ("connected", "cooling"):
                self.demo.link_reading(json.dumps({"bt": round(self.roaster.bt, 1), "et": round(self.roaster.bt - 10, 1),
                                                   "burner": self.roaster.burner, "air": self.roaster.air}))
            snap = json.loads(self.demo.tick())
            self._route()
            self.roaster.second()
            self.burners.append(self.roaster.burner)
            if until is not None and until(snap):
                break
        return snap

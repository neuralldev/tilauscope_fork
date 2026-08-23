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

"""An Artisan double shaped for the roast screen, plus the states it must survive.

The screen reads a narrow, well-known slice of ``aw``/``aw.qmc``. This double
carries exactly that slice — nothing more, so a widget that starts reading a
new attribute fails here loudly instead of drifting.

Two things the corpus cannot give us, and that this file exists to provide:

*States, not roasts.* Most defects on this screen have been state defects, not
arithmetic ones: a screen that is correct mid-roast and wrong before charge, or right on a
live roast and lying on a loaded one. :func:`scenario` enumerates those states,
including the degenerate ones no recorded roast contains — no samples at all, a
single sample, a probe reading nothing but Artisan's -1.

*Both sentinel dialects.* "Unmarked" in ``timeindex`` is -1 in a real roast and
0 in the simulator, for indices 1..7. Every state that has milestones is built
in both dialects, because a screen that only ever met one of them is a screen
that has only been half tested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PyQt6.QtCore import QDateTime, QObject, pyqtSignal

from artisanlib.util import events_internal_to_external_value

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Artisan's "no reading" value in a temperature array.
NO_READING: Final[float] = -1.0

#: Channel order Artisan uses for the four event types.
AIR: Final[int] = 0
DRUM: Final[int] = 1
DAMPER: Final[int] = 2
BURNER: Final[int] = 3

_ETYPES: Final[list[str]] = ['Air', 'Drum', 'Damper', 'Burner']
_EVALUE_COLOR: Final[list[str]] = ['#89B4FA', '#A6E3A1', '#F9E2AF', '#F38BA8']


class FakeCrackDetector:
    """The acoustic first-crack counter.

    Silent by default: `-1` is the sentinel for no microphone configured, which
    is what most roasts run with. The counter only reaches the cards when a
    device index is set.
    """

    def __init__(self) -> None:
        self._cached_crack_device_idx: int = -1
        self.last_count: int = 0
        self.threshold: int = 3


class FakeQmc(QObject):
    """The subset of ``tgraphcanvas`` the roast screen reads.

    Arrays are plain lists that grow by append, exactly as Artisan's sampling
    loop grows them, so a consumer that reads ``[-1]`` is exercised on the same
    path it runs on in production.
    """

    tilauUpdateSignal = pyqtSignal(int, object, object, bool)
    # The queued mark signals. Marking redraws Artisan's canvas, so the screen
    # asks through these and never calls the mark methods itself.
    markChargeSignal = pyqtSignal(bool)   # noqa: N815 - Artisan's name
    markDRYSignal = pyqtSignal(bool)      # noqa: N815 - Artisan's name
    markFCsSignal = pyqtSignal(bool)      # noqa: N815 - Artisan's name
    markDropSignal = pyqtSignal(bool)     # noqa: N815 - Artisan's name

    def __init__(self) -> None:
        super().__init__()
        self.timex: list[float] = []
        self.temp1: list[float] = []
        self.temp2: list[float] = []
        self.delta1: list[float] = []
        self.delta2: list[float] = []
        # Artisan's smoothed temperatures. They exist on a loaded profile even
        # when the deltas do not — the smoothing runs before the gate that
        # decides whether to compute the rate of rise at all.
        self.stemp1: list[float] = []
        self.stemp2: list[float] = []
        #: Set when the screen asked Artisan to recompute the rise.
        self.recomputed = 0

        # [CHARGE, DRY END, FCs, FCe, SCs, SCe, DROP, COOL END], indices into timex.
        self.timeindex: list[int] = [-1, -1, -1, -1, -1, -1, -1, -1]

        self.flagon: bool = False     # monitoring
        self.flagstart: bool = False  # recording
        #: The clock the LCD runs on — ahead of the last sample by up to
        #: one sampling interval, which is the whole point of reading it.
        self.timeclock = FakeClock()
        #: Artisan marks a drop by itself past five minutes when this is on.
        self.autoDROPenabled: bool = True   # noqa: N815 - Artisan's name
        #: The smoothed rise BEFORE the display clipping — what the preheat
        #: countdown is drawn from, since a ramp leaves the display band.
        self.rateofchange1: float | None = None  # noqa: N815 - Artisan's name
        self.rateofchange2: float | None = None  # noqa: N815 - Artisan's name
        #: Keeps a roast out of the learning corpus.
        self.tilau_exclude_learning: bool = False
        #: What books a roast: a schedule item and a batch number.
        self.scheduleID: str | None = 'sched-7'   # noqa: N815 - Artisan's name
        self.roastbatchnr: int = 0                # noqa: N815 - Artisan's name
        self.batchcounter: int = 41               # noqa: N815 - Artisan's name
        #: How the recorder was stopped, so a test can see the autosave choice.
        self.stopped: list[tuple[bool, bool]] = []
        self.mode: str = 'C'
        #: Artisan's own curve palette — the single source both the readouts
        #: and the curve take their colours from.
        self.palette: dict[str, str] = {
            'bt': '#89B4FA', 'et': '#FAB387',
            'deltabt': '#A6E3A1', 'deltaet': '#F9E2AF',
        }

        # Measured after the roast, and often simply absent: the account has to
        # read as honestly with them missing as with them present.
        self.ground_color: float = 0.0
        self.whole_color: float = 0.0
        # A tuple at runtime, exactly as Artisan carries it: a double using a
        # list would let code that mutates it in place pass here and fail there.
        self.weight: tuple[float, float, str] = (0.0, 0.0, 'g')

        #: Artisan's colour scales. Entry 0 is the empty string and index 0 is
        #: the default, so an unset scale is the shape production starts in.
        self.color_systems: list[str] = ['', 'Agtron', 'ColorTrack', 'ColorTest']
        self.color_system_idx: int = 0

        #: The roast name Artisan composes and holds on the canvas — batch
        #: prefix, number, the operator's own title.
        self.title_text: str = ''
        #: Free text carrying the bean record's identity, BeanCave's shape.
        self.beans: str = ''
        #: Artisan's own cupping field, saved with the profile.
        self.cuppingnotes: str = ''
        #: Stamped at reset and never refilled on load — Artisan's own trap.
        self.roastepoch: int = 0
        #: The date a roast actually happened; refilled when a profile loads.
        self.roastdate: QDateTime = QDateTime()
        # Phase boundaries, as the annotation formatters read them.
        self.phases: list[float] = [95.0, 150.0, 200.0, 210.0]
        self.phases_celsius_defaults: tuple[int, ...] = (95, 150, 200, 210)
        self.phases_fahrenheit_defaults: tuple[int, ...] = (203, 302, 392, 410)
        self.fc_detector: FakeCrackDetector = FakeCrackDetector()

        # Rate-of-rise smoothing, in the shape Artisan carries it.
        self.deltaBTspan: int = 15
        self.deltaETspan: int = 10
        self.deltaBTfilter: int = 7
        self.deltaETfilter: int = 7
        self.deltaBTsamples: int = 15
        self.deltaETsamples: int = 10

        self.etypes: list[str] = list(_ETYPES)
        self.EvalueColor: list[str] = list(_EVALUE_COLOR)  # noqa: N803 - Artisan's name

        # Slider gestures. In the live qmc these index timex; in a roast loaded
        # from a .alog they are seconds since charge. Both dialects are built
        # by scenario(), because the attribute name does not distinguish them.
        self.specialevents: list[Any] = []
        self.specialeventstype: list[int] = []
        self.specialeventsvalue: list[float] = []
        # The description is the ONLY trace of who commanded an event, and it
        # is what the Origin column is read from.
        self.specialeventsStrings: list[str] = []

        #: Every EventRecordAction the screen fired, for tests to inspect.
        self.recorded_actions: list[tuple[Any, Any, Any, str]] = []

    def EventRecordAction(self, extraevent: int | None = None,  # noqa: N802 - Artisan's name
                          eventtype: int | None = None,
                          eventvalue: float | None = None,
                          eventdescription: str = '',
                          takeLock: bool = True) -> None:  # noqa: N803, ARG002 - Artisan's signature
        """Records the gesture instead of writing it into a roast profile."""
        self.recorded_actions.append((extraevent, eventtype, eventvalue, eventdescription))

    @staticmethod
    def eventsInternal2ExternalValue(v: float | None) -> int:  # noqa: N802 - Artisan's name
        """Artisan's own encoding, imported rather than reimplemented: a double
        that invents this would let an encoding bug through unnoticed."""
        return events_internal_to_external_value(v)

    # ── construction helpers ─────────────────────────────────────────────
    def append(self, t: float, et: float, bt: float, ror: float) -> None:
        self.timex.append(t)
        self.temp1.append(et)
        self.temp2.append(bt)
        self.delta1.append(ror)
        self.delta2.append(ror)
        self.stemp1.append(et)
        self.stemp2.append(bt)
        self.rateofchange1 = self.rateofchange2 = ror
        self.timeclock.seconds = t

    # ── what the annotation formatters read ─────────────────────────────
    # The cards are built from the real code now, so the double has to answer
    # the same questions the canvas did.

    def EvalPredictiveValues(self) -> dict[str, float]:  # noqa: N802 - Artisan's name
        """Artisan's forecast. Flat here: the cards must render without one."""
        return {'pDRY': 0.0, 'pFCs': 0.0}

    def OffRecorder(self, autosave: bool = True) -> None:  # noqa: N802 - Artisan's name
        """Records the stop and whether a drop could still be written."""
        self.stopped.append((bool(autosave), bool(self.autoDROPenabled)))
        self.flagstart = False

    def updateDeltaSamples(self) -> None:  # noqa: N802 - Artisan's name
        """Artisan derives the sample count from the span at 1 Hz."""
        self.deltaBTsamples = max(1, self.deltaBTspan)
        self.deltaETsamples = max(1, self.deltaETspan)

    def drop_the_deltas(self) -> None:
        """The shape a profile loads in when both rate-of-rise curves are
        unticked in Artisan's display: temperatures present, deltas never
        computed."""
        self.delta1 = []
        self.delta2 = []

    def recomputeDeltas(self, timex, charge, drop, t1, t2,  # noqa: N802, ANN001, ARG002
                        **kwargs) -> tuple:  # noqa: ANN003, ARG002
        """Artisan's own recompute, standing in: returns a rise per sample."""
        self.recomputed += 1
        series = [12.0] * len(timex)
        return series, series

    def add_event(self, when: Any, channel: int, percent: int,
                  description: str | None = None) -> None:
        """Record a slider gesture at sample index ``when``.

        ``description`` defaults to the shape a gesture on a TilauScope control
        writes; pass one of the other writers' shapes to build an event the
        operator did not make.
        """
        self.specialevents.append(when)
        self.specialeventstype.append(channel)
        # The inverse of eventsInternal2ExternalValue over the 0..100 range.
        self.specialeventsvalue.append(percent / 10.0 + 1.0)
        self.specialeventsStrings.append(
            f'S{channel:d}' if description is None else description)


class FakeScaleManager:
    """Just enough of the scale manager for the measurement bar to decide
    whether weighing is on offer. It never reports a connection: the band must
    not need a live scale to lay itself out."""

    def __init__(self, *, configured: bool = False) -> None:
        self._configured = configured

    def is_scale1_configured(self) -> bool:
        return self._configured

    def is_scale1_connected(self) -> bool:
        return False


class FakeClock:
    """Artisan's roast clock. Settable, so a test is not at the mercy of one.

    `elapsedMilli` is named for its resolution, not its unit: it returns
    seconds, and that is the contract the screens read.
    """

    def __init__(self, seconds: float = 0.0) -> None:
        self.seconds = seconds
        self.base = 1000.0

    def elapsedMilli(self) -> float:  # noqa: N802 - Artisan's name
        return float(self.seconds)

    def setBase(self, base: float) -> None:  # noqa: N802 - Artisan's name
        self.base = float(base)

    def elapsed(self) -> float:
        return float(self.seconds) * self.base

    def addClock(self, offset: float) -> None:  # noqa: N802 - Artisan's name
        self.offset = getattr(self, 'offset', 0.0) + offset

    def getBase(self) -> float:  # noqa: N802 - Artisan's name
        """1000 is real time; the simulator raises it to run the clock fast."""
        return self.base


class FakePreheatPID:
    """TilauPID while it ramps the drum, in the shape the screens read it.

    `t_proj_c` is published by the real law each cycle, in °C as everything
    inside it is; a double that leaves it None stands for a preheat whose law
    has not run yet.
    """

    def __init__(self, *, target: float = 200.0, projected: float | None = None,
                 active: bool = True) -> None:
        self.active = active
        self._target = target
        self.t_proj_c = projected
        self.stopped: list[str] = []

    def sv_native(self) -> float:
        return self._target

    def stop(self, reason: str = '') -> None:
        """The screen stops the law when the charge is marked. Recorded rather
        than ignored: which reason it gave is part of what the screen does."""
        self.stopped.append(reason)
        self.active = False


class FakePIDControl:
    """Artisan's own PID settings. Only the probe choice is read here."""

    def __init__(self, source: int = 0) -> None:
        self.pidSource = source  # noqa: N815 - Artisan's name


class FakeRoasterLink(QObject):
    """The roaster's BLE link, in the shape the safety layer emits.

    Only the two signals the screen listens to. Real recovery — re-asserting
    air and drum, holding the burner at zero — belongs to the controller and
    happens before the second one ever fires.
    """

    safetyAlert = pyqtSignal(str)                   # noqa: N815 - tc4ble's name
    roastInterrupted = pyqtSignal(str, float, int)  # noqa: N815 - tc4ble's name

    def drop_link(self) -> None:
        self.safetyAlert.emit('link_lost')

    def recover(self, last_bt: float = 178.0, echo: int = 0) -> None:
        self.roastInterrupted.emit('link_recovered', last_bt, echo)


class FakeAw:
    """The subset of Artisan's ApplicationWindow the roast screen reads.

    Every command the controls band sends to the machine is recorded in
    :attr:`commands` rather than sent: this double must be able to stand in for
    a roaster without one being in the room.
    """

    def __init__(self, qmc: FakeQmc) -> None:
        self.qmc = qmc
        # Artisan's canvas points back at the window it belongs to, and the
        # annotation formatters follow that link to reach the controllers.
        qmc.aw = self
        self.eventslidervisibilities: list[int] = [1, 1, 1, 1]
        self.eventslidervalues: list[int] = [0, 0, 0, 0]
        self.eventslidermin: list[int] = [0, 0, 0, 0]
        self.eventslidermax: list[int] = [100, 100, 100, 100]
        self.extraeventsactionslastvalue: list[int] = [0, 0, 0, 0]
        self.tilau_menu = None
        self.commands: list[tuple[str, int, Any]] = []
        #: Set on the scenarios built in the simulator dialect. The replay
        #: speed control exists only when one is running.
        self.simulator: Any = None
        #: The operator's switch for the roast card. On here, because a double
        #: that hides the thing under test proves nothing; the test that cares
        #: turns it off itself.
        self.TilauScopeAnnotation: bool = True  # noqa: N815 - Artisan's name

        # The roast file, and what the measurement bar does with it. None is
        # the honest default: a roast that has not been saved yet has no path,
        # and that is the case where a measurement can silently go nowhere.
        self.curFile: str | None = None  # noqa: N815 - Artisan's name
        self.saved: list[str] = []
        self.save_succeeds = True
        #: Empty means no colour reader paired — the common case.
        self.bleRoastSeeDeviceName: str = ''  # noqa: N815 - Artisan's name
        self.scale_manager = FakeScaleManager()
        self.beancave_opened = 0
        self.beancaveWindow: Any = None  # noqa: N815 - Artisan's name
        #: Profiles the screen asked Artisan to open, in order.
        self.loaded: list[str] = []
        #: None until a Cyberroaster is paired — Artisan builds it late.
        self.bleSkywalkerDevice: Any = None  # noqa: N815 - Artisan's name
        #: None unless an Omniflux is paired — the roast card reads colour off it.
        self.bleAirwaveDevice: Any = None  # noqa: N815 - Artisan's name
        #: None unless a preheat is running — the common case.
        self.tilauPreheatingPid: Any = None  # noqa: N815 - TilauScope's name
        self.pidcontrol = FakePIDControl()

    def fileSave(self, path: str | None) -> bool:  # noqa: N802 - Artisan's name
        """Records the write instead of touching the corpus."""
        if not self.save_succeeds:
            return False
        self.saved.append(str(path))
        return True

    def handleBeancave(self, _checked: bool = False) -> None:  # noqa: N802 - Artisan's name
        self.beancave_opened += 1

    def loadFile(self, path: str) -> None:  # noqa: N802 - Artisan's name
        """Records the request. Loading a profile really does replace
        everything on screen, which is exactly what must not happen by
        accident — so the test asserts on the ask, not on a fake result."""
        self.loaded.append(str(path))

    def eventSliderStepSize(self, n: int) -> int:  # noqa: N802 - Artisan's name
        return 1 if n == BURNER else 5

    def moveslider(self, n: int, v: int) -> None:
        self.eventslidervalues[n] = int(v)
        self.commands.append(('moveslider', n, int(v)))

    def fireslideraction(self, n: int) -> None:
        self.commands.append(('fireslideraction', n, None))


# ── scenarios ────────────────────────────────────────────────────────────

def _unmarked(simulator: bool) -> list[int]:
    """A fresh ``timeindex``, in the dialect of the mode being simulated."""
    return [-1, 0, 0, 0, 0, 0, 0, 0] if simulator else [-1] * 8


def _ramp(qmc: FakeQmc, seconds: int, start: float, end: float,
          t0: float = 0.0, ror: float = 12.0) -> None:
    """Append one sample per second along a straight bean-temperature ramp."""
    for i in range(seconds):
        frac = i / max(1, seconds - 1)
        bt = start + (end - start) * frac
        qmc.append(t0 + i, bt + 20.0, bt, ror)


#: Every state the screen must survive, by name. Each entry is a builder so a
#: test gets a fresh, unshared double.
def scenario(name: str, *, simulator: bool = False) -> FakeAw:
    """Build the named roast state. See :data:`SCENARIOS` for the list."""
    qmc = FakeQmc()
    qmc.timeindex = _unmarked(simulator)
    _simulated = simulator

    if name == 'cold':
        # Artisan just started: nothing sampled, nothing monitored.
        pass

    elif name == 'monitoring':
        # Probes live, no charge yet: timex has grown but timeindex[0] is unset.
        qmc.flagon = True
        _ramp(qmc, 30, 180.0, 200.0, ror=0.0)

    elif name == 'single_sample':
        # One point. Every span, every scale and every zip has length 1 here.
        qmc.flagon = True
        qmc.append(0.0, 200.0, 190.0, 0.0)

    elif name == 'no_readings':
        # The probe is configured but answering nothing. -1 is not a temperature
        # and must never reach the screen as one.
        qmc.flagon = True
        for i in range(20):
            qmc.append(float(i), NO_READING, NO_READING, NO_READING)

    elif name == 'drying':
        qmc.flagon = qmc.flagstart = True
        _ramp(qmc, 20, 190.0, 185.0, ror=0.0)          # pre-charge monitoring
        qmc.timeindex[0] = len(qmc.timex)
        _ramp(qmc, 180, 90.0, 150.0, t0=20.0)          # charge to now

    elif name == 'maillard':
        qmc.flagon = qmc.flagstart = True
        _ramp(qmc, 20, 190.0, 185.0, ror=0.0)
        qmc.timeindex[0] = len(qmc.timex)
        _ramp(qmc, 300, 90.0, 170.0, t0=20.0)
        qmc.timeindex[1] = qmc.timeindex[0] + 180      # dry end
        qmc.add_event(qmc.timeindex[0], BURNER, 80)
        qmc.add_event(qmc.timeindex[0] + 120, BURNER, 60)
        qmc.add_event(qmc.timeindex[0] + 150, AIR, 40)

    elif name == 'development':
        qmc.flagon = qmc.flagstart = True
        _ramp(qmc, 20, 190.0, 185.0, ror=0.0)
        qmc.timeindex[0] = len(qmc.timex)
        _ramp(qmc, 560, 90.0, 205.0, t0=20.0)
        qmc.timeindex[1] = qmc.timeindex[0] + 180
        qmc.timeindex[2] = qmc.timeindex[0] + 500      # first crack
        qmc.add_event(qmc.timeindex[0], BURNER, 80)
        qmc.add_event(qmc.timeindex[0] + 300, BURNER, 55)
        qmc.add_event(qmc.timeindex[0] + 480, DRUM, 60)

    elif name == 'cooling':
        # Dropped, still monitoring: the beans on screen really are cooling.
        qmc.flagon = True
        qmc.flagstart = False
        _build_full_roast(qmc)

    elif name == 'replay':
        # A roast loaded from disk: full arrays, nothing sampling.
        _build_full_roast(qmc)
        qmc.flagon = False
        qmc.flagstart = False

    else:
        raise ValueError(f'unknown scenario: {name!r}')

    aw = FakeAw(qmc)
    if _simulated:
        aw.simulator = object()   # only its presence is ever read
    return aw


def _build_full_roast(qmc: FakeQmc) -> None:
    """Charge to drop, every milestone marked, gestures on three channels.

    The arrays run PAST the drop, because real ones do: Artisan keeps sampling
    into the cooling tray, so the last sample of a saved roast is a cold bean.
    A fixture that stopped at the drop would let every "reads the tail instead
    of the milestone" defect pass.
    """
    _ramp(qmc, 20, 190.0, 185.0, ror=0.0)
    qmc.timeindex[0] = len(qmc.timex)
    _ramp(qmc, 620, 90.0, 210.0, t0=20.0)
    charge = qmc.timeindex[0]
    qmc.timeindex[1] = charge + 180    # dry end
    qmc.timeindex[2] = charge + 500    # FCs
    qmc.timeindex[6] = charge + 619    # drop
    qmc.add_event(charge, BURNER, 80)
    qmc.add_event(charge + 200, BURNER, 65)
    qmc.add_event(charge + 350, AIR, 45)
    qmc.add_event(charge + 500, BURNER, 50)
    qmc.add_event(charge + 520, DRUM, 70)
    # Cooling: recorded, and part of the profile, but not part of the roast.
    _ramp(qmc, 90, 208.0, 45.0, t0=float(len(qmc.timex)), ror=-40.0)
    qmc.timeindex[7] = len(qmc.timex) - 1   # cool end


#: Names accepted by :func:`scenario`, in roast order.
SCENARIOS: Final[tuple[str, ...]] = (
    'cold', 'monitoring', 'single_sample', 'no_readings',
    'drying', 'maillard', 'development', 'cooling', 'replay',
)

#: Scenarios that have at least one milestone marked, and so exist in both
#: sentinel dialects.
MILESTONE_SCENARIOS: Final[tuple[str, ...]] = (
    'drying', 'maillard', 'development', 'cooling', 'replay',
)


def all_states() -> Iterator[tuple[str, FakeAw]]:
    """Every scenario, in both sentinel dialects where that distinction exists."""
    for name in SCENARIOS:
        yield name, scenario(name)
        if name in MILESTONE_SCENARIOS:
            yield f'{name}/simulator', scenario(name, simulator=True)

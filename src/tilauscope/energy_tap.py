#
# ABOUT
# Energy session service: follows monitoring ON → OFF and feeds energy_model.

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
# Tilau 2026

"""Energy session on the Qt main thread.

Independent of the assistant and of any open panel: it listens to
`qmc.tilauUpdateSignal` like `TelemetryTap`, starts a session on monitoring ON
and keeps it through START, so the energy spent before CHARGE is kept even
though Artisan records nothing before START.

Sources are MQTT sensors whose id is a reserved name (`roaster`, `extractor`)
and whose declared unit is `W`. Each reading is stamped with its ARRIVAL time
from the MQTT cache, not the sampling time: Artisan repeats the last cached
value on every sample, so a silent plug would otherwise look alive.

Per tick: a few dictionary reads and an incremental integration of the newly
settled interval. No I/O, no scan of the history.
"""

import logging
import time
from statistics import quantiles
from typing import Any, Final

from PyQt6.QtCore import QObject, QSettings, pyqtSignal, pyqtSlot

from tilauscope.energy_model import (
    CHANNELS, EXTRACTOR, ROASTER, EnergySession, Totals, heater_watts,
)

_log: Final[logging.Logger] = logging.getLogger(__name__)

SETTING_EXTRACTOR_ON_ROASTER_METER: Final[str] = "tilauscope/energy_extractor_on_roaster_meter"

# Sensor status per reserved name, read by the panel.
OK: Final[str] = "ok"
MISSING: Final[str] = "missing"
DUPLICATE: Final[str] = "duplicate"
UNIT: Final[str] = "unit"

# A push sensor (no gateway poll) reports on change plus a periodic report —
# about 60 s on the Fibaro plug. Absence of a message within that period means
# "unchanged", not "down", so its period is the periodic report, never the
# median of the change bursts.
_PUSH_PERIOD_S: Final[float] = 60.0
_PERIOD_SAMPLES: Final[int] = 20     # arrivals observed before the cadence is fixed


def resolve_sensors(sensors: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """Reserved-name sensors, and a status for each name.

    The name makes the association; the declared unit `W` proves it. Two
    sensors under one name are both refused rather than picked arbitrarily.
    """
    found: dict[str, list[Any]] = {n: [] for n in CHANNELS}
    for s in sensors or []:
        key = str(getattr(s, "id", "") or "").strip().lower()
        if key in found and getattr(s, "topic", ""):
            found[key].append(s)
    chosen: dict[str, Any] = {}
    status: dict[str, str] = {}
    for name, hits in found.items():
        if not hits:
            status[name] = MISSING
        elif len(hits) > 1:
            status[name] = DUPLICATE
        elif str(getattr(hits[0], "unit", "")) != "W":
            status[name] = UNIT
        else:
            status[name] = OK
            chosen[name] = hits[0]
    return chosen, status


class EnergyTap(QObject):
    """One per application; lives on `aw.tilau_energy_tap`."""

    updated = pyqtSignal()

    def __init__(self, aw) -> None:
        super().__init__()
        self._aw = aw
        self.session: EnergySession | None = None
        self.status: dict[str, str] = dict.fromkeys(CHANNELS, MISSING)
        # running totals since ON, per channel, and up to where they are summed
        self.acc: dict[str, Totals] = {}
        self._acc_t: dict[str, float] = {}
        self._sensors: dict[str, Any] = {}
        self._last_ts: dict[str, float] = {}
        self._arrivals: dict[str, list[float]] = {}
        self._rated_w: float | None = None
        self._rated_exp = 1.0
        self._rated_curve: list[list[float]] | None = None
        self._on = False
        self._rec = False
        self._last_sec = -1
        self._last_on = 0.0
        try:
            aw.qmc.tilauUpdateSignal.connect(self._on_update)
        except Exception as e:  # noqa: BLE001
            _log.warning("EnergyTap not connected: %s", e)

    # ── public ───────────────────────────────────────────────────────────

    @property
    def live(self) -> bool:
        return self._on and self.session is not None

    def sensor(self, name: str) -> Any:
        return self._sensors.get(name)

    def last_arrival(self, name: str) -> float | None:
        return self._last_ts.get(name)

    def sync_state(self) -> None:
        """Follow ON / START / OFF. Called on ticks and from the status refresh,
        which also runs after OFF when no tick comes any more."""
        try:
            self._sync(time.time())
        except Exception as e:  # noqa: BLE001  never disturb the caller
            _log.debug("EnergyTap: %s", e)

    # ── internals ────────────────────────────────────────────────────────

    @pyqtSlot(int, object, object, bool)
    def _on_update(self, data: int, _value: Any = None, _raw: Any = None, _button: bool = True) -> None:
        if data in (10, 12):
            self.sync_state()

    def _sync(self, now: float) -> None:
        aw = self._aw
        qmc = aw.qmc
        on = bool(getattr(qmc, "flagon", False)) and getattr(aw, "simulator", None) is None
        if on and not self._on:
            self._begin(now)
        elif not on and self._on:
            self._on = False
            # OFF may come before the next reading: close at the last tick,
            # the time left without a reading counts as unknown
            if self.session is not None:
                self._accumulate(self._last_on, final=True)
                self.session.end = max(self.session.end, self._last_on)
            self.updated.emit()
            return
        self._on = on
        if not on or self.session is None:
            return
        self._last_on = now
        sec = int(now)
        if sec == self._last_sec:
            return
        self._last_sec = sec
        rec = bool(getattr(qmc, "flagstart", False))
        if rec and not self._rec:
            # timex 0 is START: remember where it sits on the wall clock
            self.session.offset = now - float(qmc.timeclock.elapsedMilli())
            self.session.recorded = True
        self._rec = rec
        self._feed(now)
        # RESET under monitoring clears the profile's reference; put it back
        if getattr(qmc, "tilau_energy", None) is not self.session:
            qmc.tilau_energy = self.session
        self.updated.emit()

    def _begin(self, now: float) -> None:
        aw = self._aw
        self.session = EnergySession(start=now, end=now)
        self.session.roaster = str(getattr(aw, "tilau_roaster", "") or "")
        self.session.extractor_on_roaster_meter = bool(
            QSettings().value(SETTING_EXTRACTOR_ON_ROASTER_METER, False, type=bool))
        self.acc, self._acc_t = {}, {}
        self._sensors, self._last_ts, self._arrivals = {}, {}, {}
        self._rec = False
        self._last_sec = -1
        self._rated_w, self._rated_exp, self._rated_curve = self._rated_heater()
        aw.qmc.tilau_energy = self.session
        _log.info("EnergyTap: session started (rated %s W, exponent %s, curve %s)",
                  self._rated_w, self._rated_exp, bool(self._rated_curve))

    def _rated_heater(self) -> tuple[float | None, float, list[list[float]] | None]:
        """Declared rating of the selected roaster, the shape of its heater
        command and its measured curve, if any. Read once per session: the
        roaster database is a file."""
        try:
            from tilauscope.roasters import RoasterManager
            r = RoasterManager().get_by_display_name(str(getattr(self._aw, "tilau_roaster", "") or ""))
            spec = r.electrical_specification if r is not None else None
            if spec is None:
                return None, 1.0, None
            kw = spec.max_power_draw_kw
            return ((float(kw) * 1000.0 if kw else None),
                    float(spec.heater_power_exponent or 1.0), spec.heater_power_curve)
        except Exception as e:  # noqa: BLE001
            _log.debug("EnergyTap rated power: %s", e)
            return None, 1.0, None

    def _resolve(self) -> None:
        """Pick the reserved sensors. The MQTT list may arrive after ON, so this
        runs until both names are settled; a list of a few sensors per second."""
        cfg = getattr(self._aw, "mqtt_database", None)
        chosen, self.status = resolve_sensors(getattr(cfg, "sensors", None))
        for name, sensor in chosen.items():
            self._sensors.setdefault(name, sensor)

    def _period(self, topic: str) -> float | None:
        """Cadence guaranteed by the gateway poll, when this topic is polled."""
        try:
            from tilauscope.mqttbridge import _POLL_MIN_INTERVAL_S, derive_poll_request
            cfg = self._aw.tilauscope_mqtt_client.config
            if cfg.poll_topic.strip() and cfg.poll_interval > 0 and derive_poll_request(topic):
                return float(max(cfg.poll_interval, _POLL_MIN_INTERVAL_S))
        except Exception:  # noqa: BLE001
            pass
        return None

    def _feed(self, now: float) -> None:
        sess = self.session
        assert sess is not None
        self._resolve()
        client = getattr(self._aw, "tilauscope_mqtt_client", None)
        db = getattr(client, "db", None)
        for name, sensor in self._sensors.items():
            if db is None:
                break
            ts = db.get_timestamp(sensor.topic)
            # a cached message from before ON says nothing about this session
            if ts is None or ts < sess.start or ts == self._last_ts.get(name):
                continue
            self._last_ts[name] = ts
            try:
                from tilauscope.mqttbridge import _scale_reading
                watts = _scale_reading(db.get_value(sensor.topic), sensor)
            except Exception:  # noqa: BLE001  unreadable payload: not a reading
                continue
            ch = sess.channel(name, "mqtt")
            if ch.topic != sensor.topic:
                # first reading, possibly on a channel the estimate opened
                polled = self._period(sensor.topic)
                ch.source, ch.topic = "mqtt", sensor.topic
                ch.period_s = polled or _PUSH_PERIOD_S
                if polled is None:
                    self._arrivals[name] = []
            if ch.add_measure(ts, watts) and name in self._arrivals:
                arr = self._arrivals[name]
                arr.append(ts)
                if len(arr) > _PERIOD_SAMPLES:
                    # push sensor: widen to its own longest regular interval, fixed once seen
                    gaps = [b - a for a, b in zip(arr, arr[1:], strict=False)]
                    ch.period_s = max(_PUSH_PERIOD_S, quantiles(gaps, n=10)[-1])
                    del self._arrivals[name]

        burner, air, fan = self._controls()
        # A declared rating gives an estimate, between CHARGE and DROP only:
        # before, the machine's thermostat holds the preheat whatever the
        # command; after DROP the heater is cut while the command stays set.
        # A fresh measurement always wins.
        watts_est = heater_watts(burner, self._rated_w, self._rated_exp, self._rated_curve) \
            if burner >= 0 and self._roasting() else None
        if watts_est is not None:
            sess.channel(ROASTER, "model").add_estimate(now, watts_est)
        elif ROASTER in sess.channels:
            sess.channels[ROASTER].stop_estimate(now)
        sess.extractor_expected = (EXTRACTOR in self._sensors
                                   or getattr(self._aw, "bleAirwaveDevice", None) is not None)
        sess.add_context(now, burner, air, fan)

        self._accumulate(now)
        sess.end = sess.horizon(now)

    def _accumulate(self, now: float, final: bool = False) -> None:
        """Add each channel's newly settled interval to its running total;
        `final` settles everything up to `now`."""
        sess = self.session
        assert sess is not None
        for name, ch in sess.channels.items():
            t0 = self._acc_t.get(name, sess.start)
            t1 = now if final else ch.settled(now)
            if t1 > t0:
                self.acc.setdefault(name, Totals())
                self.acc[name] += ch.integrate(t0, t1)
                self._acc_t[name] = t1

    def _roasting(self) -> bool:
        """Recording, CHARGE marked, DROP not yet (per-index sentinels)."""
        qmc = self._aw.qmc
        try:
            ti = qmc.timeindex
            return bool(qmc.flagstart) and ti[0] > -1 and not ti[6] > 0
        except Exception:  # noqa: BLE001
            return False

    def _controls(self) -> tuple[float, float, float]:
        """Burner, air and extraction in %, -1 when unknown. The burner is the
        roaster's own echo when it reports one, else the last command."""
        def pct(idx: int) -> float:
            try:
                from tilauscope.roast_asssistant import _read_slider_pct
                v = _read_slider_pct(self._aw, idx)
                return float(v) if v is not None else -1.0
            except Exception:  # noqa: BLE001
                return -1.0
        burner = -1.0
        dev = getattr(self._aw, "bleSkywalkerDevice", None)
        if dev is not None:
            try:
                burner = float(dev.getBurner())
            except Exception:  # noqa: BLE001
                burner = -1.0
        if burner < 0:
            burner = pct(3)
        return burner, pct(0), pct(2)

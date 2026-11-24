# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Tilau
# This file is part of TilauScope.

"""The roast's energy (MQTT-SPEC E2): the desktop's model (tilaucore.energy_model) fed as the desktop's
EnergyTap feeds it, from START to STOP, the preheat included. Times are the roast's: the session's
recording axis, written to the .alog as `tilau_energy` for the desktop's Energy tile."""

from statistics import quantiles

from tilaucore.energy_model import (EXTRACTOR, ROASTER, EnergySession, Summary, heater_watts, phase_bounds,
                                   session_for_profile)

from . import mqtt

FEEDS = {"roaster_w": ROASTER, "extractor_w": EXTRACTOR}
PUSH_PERIOD_S = 60.0 # a sensor that publishes on its own (the desktop's _PUSH_PERIOD_S)
PERIOD_SAMPLES = 20  # arrivals seen before its own cadence is fixed


class TabletEnergy:
    def __init__(self, roaster_name: str, roaster, sensors: list, extractor_device: bool):
        """`roaster`: its roasters.json record (None when unknown); `sensors`: the MQTT sensors;
        `extractor_device`: an extractor paired on the tablet."""
        self.session = EnergySession(start=0.0, end=0.0, recorded=True, roaster=roaster_name)
        found = {name: [s for s in sensors if s["feeds"] == feeds] for feeds, name in FEEDS.items()}
        # Two sensors for one power are both left out rather than one picked, as on the desktop.
        self._sensors = {name: hits[0] for name, hits in found.items() if len(hits) == 1}
        self._arrivals: dict[str, list[float]] = {}
        spec = getattr(roaster, "electrical_specification", None)
        kw = getattr(spec, "max_power_draw_kw", None)
        self._rated_w = float(kw) * 1000.0 if kw else None
        self._exponent = float(getattr(spec, "heater_power_exponent", None) or 1.0)
        self._curve = getattr(spec, "heater_power_curve", None)
        self.session.extractor_expected = EXTRACTOR in self._sensors or extractor_device

    def reading(self, t: float, topic: str, payload: str) -> None:
        """A message, stamped with its arrival on the roast's time."""
        for name, sensor in self._sensors.items():
            if sensor["topic"] != topic:
                continue
            watts = mqtt.reading(sensor, payload)
            if watts is None:
                continue
            ch = self.session.channel(name, "mqtt")
            if ch.topic != topic: # first reading, possibly on the channel the estimate opened
                ch.source, ch.topic, ch.period_s = "mqtt", topic, PUSH_PERIOD_S
                self._arrivals[name] = []
            if ch.add_measure(t, watts) and name in self._arrivals:
                arrivals = self._arrivals[name]
                arrivals.append(t)
                if len(arrivals) > PERIOD_SAMPLES: # widened to its own longest regular interval, fixed once seen
                    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
                    ch.period_s = max(PUSH_PERIOD_S, quantiles(gaps, n=10)[-1])
                    del self._arrivals[name]

    def step(self, t: float, burner: float, air: float, extraction: float, roasting: bool) -> None:
        """Each second. The burner estimates the roaster between CHARGE and DROP only: before, the
        thermostat holds the preheat whatever the command; after, the heater is cut. A fresh
        measurement always wins over it."""
        watts = heater_watts(burner, self._rated_w, self._exponent, self._curve) if burner >= 0 and roasting else None
        if watts is not None:
            self.session.channel(ROASTER, "model").add_estimate(t, watts)
        elif ROASTER in self.session.channels:
            self.session.channels[ROASTER].stop_estimate(t)
        self.session.add_context(t, burner, air, extraction)
        self.session.end = self.session.horizon(t)

    def close(self, t: float) -> dict:
        """At STOP: the block the .alog keeps."""
        self.session.end = max(self.session.end, t)
        return self.session.to_dict()


KG_PER = {"g": 0.001, "kg": 1.0, "lb": 0.45359237, "oz": 0.028349523125} # Artisan's weight units


def bill(profile: dict) -> tuple[EnergySession, Summary] | None:
    """A saved roast's energy session and its summary on the roast's milestones and green weight: its own
    tilau_energy, else rebuilt from its saved power curve, as the desktop reads it. None without either."""
    session = session_for_profile(profile)
    if session is None:
        return None
    weight = profile.get("weight") or (0, 0, "g")
    green_kg = float(weight[0] or 0) * KG_PER.get(str(weight[2]).lower(), 0.0)
    return session, session.summarize(phase_bounds(profile.get("timex") or [], profile.get("timeindex") or []), green_kg)


def sheet(session: EnergySession, summary: Summary, charge_s: float | None, drop_s: float | None) -> dict:
    """The energy sheet: the total, the power of each source, the three periods, one line per source."""
    total = summary.total(summary.since_start)
    periods = [(name, p) for name, p in (("Preheat", summary.before_charge), ("Roast", summary.roast),
                                         ("Cooling", summary.after_drop)) if p is not None]
    return {
        "kwh": round(total.wh / 1000, 3), "provenance": total.provenance, "rebuilt": session.rebuilt,
        "complete": summary.complete(summary.since_start), "start": session.start, "end": session.end,
        "charge": charge_s, "drop": drop_s,
        "per_kg_kwh": None if summary.wh_per_kg is None else round(summary.wh_per_kg / 1000, 2),
        "periods": [{"name": name, "kwh": round(summary.total(p.per_channel).wh / 1000, 3), "s": round(p.end - p.start)}
                    for name, p in periods],
        "sources": [{"name": name, "kwh": round(t.wh / 1000, 3), "provenance": t.provenance}
                    for name, t in summary.since_start.items()],
        "channels": {name: {k: ch.to_dict()[k] for k in ("measured", "estimated", "max_gap_s")}
                     for name, ch in session.channels.items()},
    }

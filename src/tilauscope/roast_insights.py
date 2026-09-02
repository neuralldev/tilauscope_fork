#
# ABOUT
# Beancave – Roast Insights engine (pre-roast educational panel)
#
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

"""Heuristics translating green-bean parameters and session setup into a structured
educational summary of roast-phase implications, consumed by ``_RoastInsightsPanel``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication

from tilauscope.tilauscope_types import (
    get_ror_ideal_band, standardization_map, weight_loss_target_from_plan,
)

if TYPE_CHECKING:
    from tilauscope.tilauscope_types import GreenBean
    from tilauscope.roasters import RoasterContext


# ─────────────────────────────────────────────────────────────────────────────
# Thresholds (conventional values) — single source of truth
# ─────────────────────────────────────────────────────────────────────────────

# Density (g/L)
_DENSITY_SOFT      = 650.0
_DENSITY_DENSE     = 720.0
_DENSITY_VERYDENSE = 760.0

# Moisture (% wet basis)
_MOISTURE_LOW  = 9.5
_MOISTURE_HIGH = 12.0

# Water activity (aw)
_AW_LO   = 0.45
_AW_HI   = 0.55
_AW_CRIT_LO = 0.40
_AW_CRIT_HI = 0.62

# Load ratio (% of optimal batch)
_LOAD_LO   = 85.0
_LOAD_HI   = 105.0
_LOAD_CRIT_LO = 70.0
_LOAD_CRIT_HI = 115.0

# Charge bean temperature (°C) — comfort window
_BEAN_COOL = 18.0
_BEAN_WARM = 30.0

# First-crack BT estimate by heater class (°C)
_FC_BT_RADIANT = 187.0
_FC_BT_GENERIC = 198.0


def _c_to_f(c: float) -> float:
    return c * 1.8 + 32.0


# ─────────────────────────────────────────────────────────────────────────────
# Output data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    value_text: str
    severity: str
    implication: str


@dataclass(frozen=True)
class PhaseBand:
    name: str
    lo: float
    hi: float
    unit: str


@dataclass(frozen=True)
class Target:
    label: str
    value_text: str
    known: bool


@dataclass(frozen=True)
class LoadInfo:
    pct: float | None
    severity: str
    text: str
    note: str


@dataclass
class RoastInsights:
    signals: list[Signal] = field(default_factory=list)
    load: LoadInfo | None = None
    bands: list[PhaseBand] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    strategy: str = ""
    roaster_known: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Per-parameter classifiers (pure)
# ─────────────────────────────────────────────────────────────────────────────

def _density_signal(density: float, unit: str) -> Signal | None:
    if not density or density <= 0:
        return None
    label = QApplication.translate("tilauscope_roast_review", "Density")
    if density < _DENSITY_SOFT:
        return Signal("density", label,
                      f"{density:.0f} g/L · " + QApplication.translate("tilauscope_roast_review", "soft"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "Absorbs heat fast → develops quickly. Gentler charge, watch baking/tipping."))
    if density >= _DENSITY_VERYDENSE:
        return Signal("density", label,
                      f"{density:.0f} g/L · " + QApplication.translate("tilauscope_roast_review", "very dense"),
                      "crit",
                      QApplication.translate("tilauscope_roast_review",
                          "Very hard bean → slow heat penetration. More drying energy, FC later, guard surface scorch."))
    if density >= _DENSITY_DENSE:
        return Signal("density", label,
                      f"{density:.0f} g/L · " + QApplication.translate("tilauscope_roast_review", "dense"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "Hard bean → solid drying energy, FC later, watch surface scorch."))
    return Signal("density", label,
                  f"{density:.0f} g/L · " + QApplication.translate("tilauscope_roast_review", "standard"),
                  "ok",
                  QApplication.translate("tilauscope_roast_review",
                      "Standard thermal behaviour; follow the phase bands."))


def _moisture_signal(moisture: float) -> Signal | None:
    if not moisture or moisture <= 0:
        return None
    label = QApplication.translate("tilauscope_roast_review", "Moisture")
    if moisture > _MOISTURE_HIGH:
        return Signal("moisture", label,
                      f"{moisture:.1f} % · " + QApplication.translate("tilauscope_roast_review", "high"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "High steam load → longer drying, slower TP recovery. Don't rush or it under-develops."))
    if moisture < _MOISTURE_LOW:
        return Signal("moisture", label,
                      f"{moisture:.1f} % · " + QApplication.translate("tilauscope_roast_review", "low"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "Dry/fragile → shorter drying, scorch risk. Ease heat early."))
    return Signal("moisture", label,
                  f"{moisture:.1f} % · " + QApplication.translate("tilauscope_roast_review", "normal"),
                  "ok",
                  QApplication.translate("tilauscope_roast_review",
                      "Standard steam load; drying on target."))


def _water_activity_signal(aw: float) -> Signal | None:
    if not aw or aw <= 0:
        return None
    label = QApplication.translate("tilauscope_roast_review", "Water activity")
    if aw < _AW_CRIT_LO or aw > _AW_CRIT_HI:
        tag = (QApplication.translate("tilauscope_roast_review", "over-dried") if aw < _AW_CRIT_LO
               else QApplication.translate("tilauscope_roast_review", "stale/mould risk"))
        return Signal("water_activity", label, f"{aw:.2f} aw · {tag}", "crit",
                      QApplication.translate("tilauscope_roast_review",
                          "Out of safe range → uneven roast and storage instability."))
    if aw < _AW_LO or aw > _AW_HI:
        return Signal("water_activity", label,
                      f"{aw:.2f} aw · " + QApplication.translate("tilauscope_roast_review", "edge"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "Near window edge; expect slightly uneven core moisture."))
    return Signal("water_activity", label,
                  f"{aw:.2f} aw · " + QApplication.translate("tilauscope_roast_review", "in window"),
                  "ok",
                  QApplication.translate("tilauscope_roast_review",
                      "Free water 0.45–0.55 → even, reactive, predictable."))


def _process_class(process: str) -> str:
    """Return 'washed' | 'sugary' | 'unknown' from a free-text process string."""
    p = (process or "").strip()
    if not p:
        return "unknown"
    pl = p.casefold()
    for k, v in standardization_map.items():
        if k.casefold() in pl:
            pl = v.casefold()
            break
    if any(x in pl for x in (
        "natural", "dry", "honey", "pulped", "anaerobic",
        "carbonic", "experimental", "ferment", "yeast",
    )):
        return "sugary"
    if any(x in pl for x in ("washed", "wet", "fully washed")):
        return "washed"
    return "unknown"


def _process_signal(process: str) -> Signal | None:
    cls = _process_class(process)
    label = QApplication.translate("tilauscope_roast_review", "Process")
    if cls == "sugary":
        return Signal("process", label,
                      f"{process} · " + QApplication.translate("tilauscope_roast_review", "caution"),
                      "warn",
                      QApplication.translate("tilauscope_roast_review",
                          "Residual sugars → faster browning, tipping risk. Ease through Maillard."))
    if cls == "washed":
        return Signal("process", label,
                      f"{process} · " + QApplication.translate("tilauscope_roast_review", "clean"),
                      "ok",
                      QApplication.translate("tilauscope_roast_review",
                          "Clean, predictable drying; standard browning curve."))
    if process:
        return Signal("process", label, process, "info",
                      QApplication.translate("tilauscope_roast_review",
                          "Unclassified process; rely on the phase bands."))
    return None


def _bean_temp_note(bean_temp: float | None, mode: str) -> str:
    if bean_temp is None:
        return ""
    cool = _BEAN_COOL if mode == "C" else _c_to_f(_BEAN_COOL)
    warm = _BEAN_WARM if mode == "C" else _c_to_f(_BEAN_WARM)
    unit = "°F" if mode == "F" else "°C"
    if bean_temp <= cool:
        return QApplication.translate("tilauscope_roast_review",
            "Charge BT {0} {1} (cool) → expect a deeper TP dip and slower recovery.").format(f"{bean_temp:.0f}", unit)
    if bean_temp >= warm:
        return QApplication.translate("tilauscope_roast_review",
            "Charge BT {0} {1} (warm) → shallower TP dip, faster recovery.").format(f"{bean_temp:.0f}", unit)
    return QApplication.translate("tilauscope_roast_review",
        "Charge BT {0} {1} (ambient).").format(f"{bean_temp:.0f}", unit)


# ─────────────────────────────────────────────────────────────────────────────
# Load, bands, targets, strategy
# ─────────────────────────────────────────────────────────────────────────────

def _load_info(green_weight: float, ctx: "RoasterContext | None",
               bean_temp: float | None, mode: str) -> LoadInfo:
    note = _bean_temp_note(bean_temp, mode)
    optimal = getattr(ctx, "batch_optimal_g", 0) if ctx else 0
    if not optimal or optimal <= 0:
        reason = QApplication.translate("tilauscope_roast_review", "Roaster optimal capacity unknown.")
    elif not green_weight or green_weight <= 0:
        reason = QApplication.translate("tilauscope_roast_review", "Enter the green weight to compute load.")
    else:
        reason = ""
    if reason:
        body = f"{note} {reason}".strip() if note else reason
        return LoadInfo(None, "info",
                        f"{green_weight:.0f} g" if green_weight else "—", body)

    pct = green_weight / optimal * 100.0
    if pct < _LOAD_CRIT_LO or pct > _LOAD_CRIT_HI:
        sev = "crit"
    elif pct < _LOAD_LO or pct > _LOAD_HI:
        sev = "warn"
    else:
        sev = "ok"
    text = (f"{green_weight:.0f} / {optimal:.0f} g "
            + QApplication.translate("tilauscope_roast_review", "optimal"))
    if sev == "ok":
        body = QApplication.translate("tilauscope_roast_review", "Good fill → stable thermal buffer.")
    elif pct < _LOAD_LO:
        body = QApplication.translate("tilauscope_roast_review",
            "Under-loaded → little thermal buffer, RoR can run away.")
    else:
        body = QApplication.translate("tilauscope_roast_review",
            "Over-loaded → sluggish, longer drying, flick risk.")
    return LoadInfo(round(pct), sev, text, f"{body} {note}".strip())


def _bands(mode: str) -> list[PhaseBand]:
    unit = "°F/min" if mode == "F" else "°C/min"
    names = (
        QApplication.translate("tilauscope_roast_review", "Drying"),
        QApplication.translate("tilauscope_roast_review", "Maillard"),
        QApplication.translate("tilauscope_roast_review", "Develop."),
    )
    phases = ("drying", "maillard", "development")
    out: list[PhaseBand] = []
    for name, phase in zip(names, phases):
        lo, hi = get_ror_ideal_band(phase, mode)
        out.append(PhaseBand(name, lo, hi, unit))
    return out


def _targets(ctx: "RoasterContext | None", mode: str) -> list[Target]:
    if ctx is not None:
        fc_c = _FC_BT_RADIANT if getattr(ctx, "is_radiant_electric", False) else _FC_BT_GENERIC
        fc_val = fc_c if mode == "C" else _c_to_f(fc_c)
        unit = "°F" if mode == "F" else "°C"
        suffix = (" (" + QApplication.translate("tilauscope_roast_review", "radiant") + ")"
                  if getattr(ctx, "is_radiant_electric", False) else "")
        fc = Target(QApplication.translate("tilauscope_roast_review", "FC BT"),
                    f"≈{fc_val:.0f} {unit}{suffix}", True)
    else:
        fc = Target(QApplication.translate("tilauscope_roast_review", "FC BT"), "—", False)
    return [
        fc,
        Target(QApplication.translate("tilauscope_roast_review", "DTR"), "—", False),
        Target(QApplication.translate("tilauscope_roast_review", "Weight loss"), "—", False),
        Target(QApplication.translate("tilauscope_roast_review", "Total time"), "—", False),
    ]


def _strategy(density: float, moisture: float, process_cls: str,
              ctx: "RoasterContext | None") -> str:
    drivers: list[str] = []
    energy = 0

    if density:
        if density >= _DENSITY_DENSE:
            energy += 1
            drivers.append(QApplication.translate("tilauscope_roast_review", "dense"))
        elif density < _DENSITY_SOFT:
            energy -= 1
            drivers.append(QApplication.translate("tilauscope_roast_review", "soft"))
    if moisture:
        if moisture > _MOISTURE_HIGH:
            energy += 1
            drivers.append(QApplication.translate("tilauscope_roast_review", "wet"))
        elif moisture < _MOISTURE_LOW:
            energy -= 1
            drivers.append(QApplication.translate("tilauscope_roast_review", "dry"))
    careful = process_cls == "sugary"
    if careful:
        drivers.append(QApplication.translate("tilauscope_roast_review", "sugary process"))

    if careful and energy >= 1:
        label = QApplication.translate("tilauscope_roast_review", "standard-to-careful")
    elif energy >= 2:
        label = QApplication.translate("tilauscope_roast_review", "energy-tolerant")
    elif energy <= -2 or (careful and energy <= 0):
        label = QApplication.translate("tilauscope_roast_review", "gentle")
    elif careful:
        label = QApplication.translate("tilauscope_roast_review", "careful")
    else:
        label = QApplication.translate("tilauscope_roast_review", "standard")

    driver_txt = " + ".join(drivers) if drivers else QApplication.translate(
        "tilauscope_roast_review", "balanced inputs")
    parts = [f"{driver_txt} → {label}."]

    if ctx is not None and getattr(ctx, "is_radiant_electric", False):
        parts.append(QApplication.translate("tilauscope_roast_review",
            "Radiant: BT leads ET after TP — commit drying energy early, then manage power down."))
    if careful:
        parts.append(QApplication.translate("tilauscope_roast_review",
            "Back off through Maillard to protect sugars and avoid tipping."))
    elif energy >= 1:
        parts.append(QApplication.translate("tilauscope_roast_review",
            "Sustain heat into the Maillard phase, then settle the RoR before FC."))
    else:
        parts.append(QApplication.translate("tilauscope_roast_review",
            "Keep a smooth, declining RoR across all phases."))
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Roast-plan integration — map the plan dict into the reserved Targets
# ─────────────────────────────────────────────────────────────────────────────

def targets_from_plan(plan: dict | None, mode: str = "C") -> list[Target] | None:
    """Map the plan dict into the four panel targets (temperatures already in
    native unit). Returns None when unavailable so the caller keeps heuristic targets."""
    if not plan:
        return None
    unit = "°F" if mode == "F" else "°C"

    def _val(key: str):
        v = plan.get(key)
        return None if v in (None, "", "N/A") else v

    def _num(key: str):
        v = _val(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    chg = _num("Charge Temp")
    fc  = _num("First Crack Temp")
    dtr = _num("Target DTR")
    tot = _val("Total Time")
    # Weight loss follows the water and the development, not the colour alone —
    # both come from the plan itself, so the panel promises what it planned.
    wl  = weight_loss_target_from_plan(plan)
    min_lbl = QApplication.translate("tilauscope_roast_review", "min")

    return [
        # Charge leads: it is the first figure the operator acts on, and the one
        # the preheat PID is set from. It was computed and silently pushed into
        # the PID field, but never stated.
        Target(QApplication.translate("tilauscope_roast_review", "Charge"),
               f"{chg:.0f} {unit}" if chg is not None else "—", chg is not None),
        Target(QApplication.translate("tilauscope_roast_review", "FC BT"),
               f"{fc:.0f} {unit}" if fc is not None else "—", fc is not None),
        Target(QApplication.translate("tilauscope_roast_review", "DTR"),
               f"{dtr:.1f} %" if dtr is not None else "—", dtr is not None),
        Target(QApplication.translate("tilauscope_roast_review", "Weight loss"),
               f"{wl.target:.1f} %" if wl else "—", wl is not None),
        Target(QApplication.translate("tilauscope_roast_review", "Total time"),
               f"{tot} {min_lbl}" if tot else "—", tot is not None),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_insights(
    bean: "GreenBean",
    *,
    density: float,
    moisture: float,
    green_weight: float,
    bean_temp: float | None,
    ctx: "RoasterContext | None",
    mode: str = "C",
) -> RoastInsights:
    """Build the educational insights for a pre-roast setup. ``density`` and
    ``moisture`` are the effective setup values (may override the bean's stored
    values); everything else is read from ``bean``."""
    signals: list[Signal] = []
    for s in (
        _density_signal(density, mode),
        _moisture_signal(moisture),
        _water_activity_signal(getattr(bean, "water_activity", 0.0)),
        _process_signal(getattr(bean, "process", "")),
    ):
        if s is not None:
            signals.append(s)

    return RoastInsights(
        signals=signals,
        load=_load_info(green_weight, ctx, bean_temp, mode),
        bands=_bands(mode),
        targets=_targets(ctx, mode),
        strategy=_strategy(density, moisture,
                           _process_class(getattr(bean, "process", "")), ctx),
        roaster_known=ctx is not None,
    )
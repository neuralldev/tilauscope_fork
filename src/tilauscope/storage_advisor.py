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
# Tilau 2025-2026

## TILAU ##
"""Green-coffee storage advisor — water-activity (aw) conservation engine.

Pure, Qt-free, offline-testable. Given a bean's measured water activity (from the
AquaGauge), the real storage-room ambient humidity (from an MQTT sensor) and the
bean's conditioning, it classifies a storage-risk zone and a moisture-drift trend,
and estimates the equilibrium moisture content the bean would reach in that room.

This is an *estimate*, never a precision instrument. Sorption isotherms vary by
variety, process, particle size and temperature; the zones below are the classic
food-safety mould threshold (aw > 0.65) plus a specialty green-storage window.
UI thresholds are user-overridable via QSettings (load_thresholds()).

Run `python -m tilauscope.storage_advisor` for a self-check.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

# --------------------------------------------------------------------------- #
# Conditioning (matches GreenBean.conditioning language-neutral keys)
# --------------------------------------------------------------------------- #

CONDITIONING_SEALED: frozenset[str] = frozenset({"vacuum", "grainpro", "ecotact", "bocal"})
CONDITIONING_OPEN: frozenset[str] = frozenset({"toile"})
# '' (unknown) is treated as OPEN on purpose: better to warn than to hide a drift.


def is_sealed(conditioning: str) -> bool:
    return (conditioning or "").strip().lower() in CONDITIONING_SEALED


# --------------------------------------------------------------------------- #
# Risk zones
# --------------------------------------------------------------------------- #

class AwZone(Enum):
    UNKNOWN = "unknown"      # aw not measured (<= 0)
    TOO_DRY = "too_dry"      # aw < dry    → aromatics loss, faster staling
    OPTIMAL = "optimal"      # dry <= aw < warn
    WATCH = "watch"          # warn <= aw < risk
    MOLD_RISK = "mold_risk"  # aw >= risk  → mould / degradation


@dataclass(frozen=True)
class StorageThresholds:
    dry: float = 0.45   # below → too dry
    warn: float = 0.60  # above → watch
    risk: float = 0.65  # above → mould risk


DEFAULT_THRESHOLDS = StorageThresholds()


def classify_aw(aw: float, thresholds: StorageThresholds = DEFAULT_THRESHOLDS) -> AwZone:
    """Map a measured water activity to a storage-risk zone."""
    if aw is None or aw <= 0:
        return AwZone.UNKNOWN
    if aw < thresholds.dry:
        return AwZone.TOO_DRY
    if aw < thresholds.warn:
        return AwZone.OPTIMAL
    if aw < thresholds.risk:
        return AwZone.WATCH
    return AwZone.MOLD_RISK


# --------------------------------------------------------------------------- #
# Moisture-drift trend
# --------------------------------------------------------------------------- #

class MoistureTrend(Enum):
    UNKNOWN = "unknown"  # no aw or no ambient reading
    SEALED = "sealed"    # conditioning suspends exchange → no meaningful drift
    GAINING = "gaining"  # room is more humid than the bean → aw drifts up
    DRYING = "drying"    # room is drier than the bean → slow moisture loss
    STABLE = "stable"    # bean and room roughly in equilibrium


# aw and equilibrium relative humidity are the same quantity: aw = ERH / 100.
# The room drives the bean toward ERH_room over time (open conditioning only).
TREND_DEADBAND = 0.03  # |ERH_room - aw| within this → considered stable


def compute_trend(
    aw: float,
    ambient_rh: float | None,
    conditioning: str,
    deadband: float = TREND_DEADBAND,
) -> MoistureTrend:
    """Direction the bean's moisture will drift in the given room.

    ambient_rh is the storage-room relative humidity in percent (e.g. 62.0).
    """
    if aw is None or aw <= 0:
        return MoistureTrend.UNKNOWN
    if is_sealed(conditioning):
        return MoistureTrend.SEALED
    if ambient_rh is None:
        return MoistureTrend.UNKNOWN
    erh_room = ambient_rh / 100.0
    diff = erh_room - aw
    if diff > deadband:
        return MoistureTrend.GAINING
    if diff < -deadband:
        return MoistureTrend.DRYING
    return MoistureTrend.STABLE


# --------------------------------------------------------------------------- #
# Equilibrium moisture content (coarse green-coffee isotherm ~25 °C)
# --------------------------------------------------------------------------- #

# aw (== ERH fraction) -> equilibrium moisture content (% wet basis).
# Coarse monotonic curve for green coffee near 25 °C; interpolated linearly.
# Deliberately low-resolution: this is guidance, not a calibrated isotherm.
_EMC_CURVE: tuple[tuple[float, float], ...] = (
    (0.20, 5.5),
    (0.30, 7.0),
    (0.40, 8.5),
    (0.45, 9.2),
    (0.50, 10.0),
    (0.55, 10.9),
    (0.60, 11.8),
    (0.65, 12.9),
    (0.70, 14.2),
    (0.80, 17.5),
)


def estimate_emc(aw_or_erh: float) -> float | None:
    """Equilibrium moisture content (% wet basis) for a given aw / ERH fraction.

    Pass a bean's aw to estimate its current moisture, or the room's ERH
    (ambient_rh / 100) to estimate the moisture it would reach in that room.
    """
    if aw_or_erh is None or aw_or_erh <= 0:
        return None
    x = aw_or_erh
    lo = _EMC_CURVE[0]
    hi = _EMC_CURVE[-1]
    if x <= lo[0]:
        return lo[1]
    if x >= hi[0]:
        return hi[1]
    for (x0, y0), (x1, y1) in zip(_EMC_CURVE, _EMC_CURVE[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return None


# --------------------------------------------------------------------------- #
# Combined assessment
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StorageAssessment:
    zone: AwZone
    trend: MoistureTrend
    equilibrium_moisture: float | None  # % wet basis the room would drive toward
    aw: float
    ambient_rh: float | None
    conditioning: str


def assess(
    aw: float,
    ambient_rh: float | None,
    conditioning: str = "",
    thresholds: StorageThresholds = DEFAULT_THRESHOLDS,
) -> StorageAssessment:
    """Full storage assessment for one bean in one room."""
    return StorageAssessment(
        zone=classify_aw(aw, thresholds),
        trend=compute_trend(aw, ambient_rh, conditioning),
        equilibrium_moisture=(
            estimate_emc(ambient_rh / 100.0) if ambient_rh is not None else None
        ),
        aw=aw,
        ambient_rh=ambient_rh,
        conditioning=conditioning,
    )


# --------------------------------------------------------------------------- #
# MQTT ambient payload parsing (pure; the db read itself lives in the UI layer)
# --------------------------------------------------------------------------- #

# QSettings keys (read by the UI layer, defined here so they live with the engine).
# Humidity and temperature are configured INDEPENDENTLY: they may be published on
# different topics (not just different fields of one payload).
STORAGE_HUMIDITY_TOPIC_KEY = "tilauscope/storage_mqtt_humidity_topic"
STORAGE_HUMIDITY_FIELD_KEY = "tilauscope/storage_mqtt_humidity_field"
STORAGE_TEMP_TOPIC_KEY = "tilauscope/storage_mqtt_temp_topic"
STORAGE_TEMP_FIELD_KEY = "tilauscope/storage_mqtt_temp_field"
STORAGE_AW_DRY_KEY = "tilauscope/storage_aw_dry"
STORAGE_AW_WARN_KEY = "tilauscope/storage_aw_warn"
STORAGE_AW_RISK_KEY = "tilauscope/storage_aw_risk"

DEFAULT_HUMIDITY_FIELD = "humidity"
DEFAULT_TEMP_FIELD = "temperature"


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_value(payload: Any, field: str = "") -> float | None:
    """Pull one numeric value out of a cached MQTT payload.

    ``field`` empty      → the payload is itself the value (a bare scalar).
    ``field`` "humidity" → payload["humidity"].
    ``field`` "a.b.c"    → nested payload["a"]["b"]["c"] (dotted path).
    Returns None when the path is missing or not numeric.
    """
    if payload is None:
        return None
    field = (field or "").strip()
    if not field:
        return _coerce_float(payload) if not isinstance(payload, (dict, list)) else None
    cur: Any = payload
    for part in field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return _coerce_float(cur)


# --------------------------------------------------------------------------- #
# Self-check
# --------------------------------------------------------------------------- #

def _selfcheck() -> None:
    t = DEFAULT_THRESHOLDS
    assert classify_aw(0.0, t) is AwZone.UNKNOWN
    assert classify_aw(0.42, t) is AwZone.TOO_DRY
    assert classify_aw(0.55, t) is AwZone.OPTIMAL
    assert classify_aw(0.63, t) is AwZone.WATCH
    assert classify_aw(0.67, t) is AwZone.MOLD_RISK

    assert compute_trend(0.55, None, "vacuum") is MoistureTrend.SEALED
    assert compute_trend(0.55, 62.0, "grainpro") is MoistureTrend.SEALED
    assert compute_trend(0.55, 66.0, "ecotact") is MoistureTrend.SEALED
    assert compute_trend(0.55, None, "toile") is MoistureTrend.UNKNOWN
    assert compute_trend(0.55, 62.0, "toile") is MoistureTrend.GAINING   # 0.62 > 0.55+0.03
    assert compute_trend(0.60, 45.0, "toile") is MoistureTrend.DRYING    # 0.45 < 0.60-0.03
    assert compute_trend(0.60, 61.0, "toile") is MoistureTrend.STABLE    # within deadband
    assert compute_trend(0.60, 66.0, "") is MoistureTrend.GAINING        # unknown == open

    assert estimate_emc(0.0) is None
    emc = estimate_emc(0.62)
    assert emc is not None and 11.8 < emc < 12.9

    assert extract_value({"humidity": 62}, "humidity") == 62.0
    assert extract_value(62) == 62.0                       # bare scalar, no field
    assert extract_value({"humidity": 62}) is None         # dict needs a field
    assert extract_value({"data": {"rh": 62}}, "data.rh") == 62.0  # dotted path
    assert extract_value({"a": 1}, "missing") is None
    assert extract_value(None, "x") is None

    assert extract_value({"temperature": 24}, "temperature") == 24.0

    a = assess(0.66, 75.0, "toile", t)  # already at risk AND a humid room drives it higher
    assert a.zone is AwZone.MOLD_RISK and a.trend is MoistureTrend.GAINING
    assert a.equilibrium_moisture is not None
    # A bean drier than the room dries down even if its own aw is high
    assert assess(0.67, 62.0, "toile", t).trend is MoistureTrend.DRYING

    print("storage_advisor self-check: OK")


if __name__ == "__main__":
    _selfcheck()

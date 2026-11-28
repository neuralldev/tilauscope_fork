# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2025-2026 Tilau
# This file is part of TilauScope.

"""Roast colour, shared by the desktop and the tablet: the SCA roast levels and
the conversion of any colour reading to the Agtron Gourmet scale."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgtronRange:
    min_value: float
    max_value: float

@dataclass
class AgtronScale:
    name: str
    agtron_range : AgtronRange
    description : str
    color_map: str


AGTRON_SCALES: list[AgtronScale] = [
    AgtronScale(
        name="Extremely Dark",
        agtron_range=AgtronRange(0.0, 25.99),
        description="Italian",
        color_map="#2D1A0E",
    ),
    AgtronScale(
        name="Very Dark",
        agtron_range=AgtronRange(26.0, 34.99),
        description="French",
        color_map="#4C2B16",
    ),
    AgtronScale(
        name="Dark",
        agtron_range=AgtronRange(35.0, 40.99),
        description="Vienna",
        color_map="#6B3D1E",
    ),
    AgtronScale(
        name="Medium Dark",
        agtron_range=AgtronRange(41.0, 50.99),
        description="Full City",
        color_map="#855734",
    ),
    AgtronScale(
        name="Medium",
        agtron_range=AgtronRange(51.0, 60.99),
        description="City",
        color_map="#A0704A",
    ),
    AgtronScale(
        name="Medium Light",
        agtron_range=AgtronRange(61.0, 70.99),
        description="American",
        color_map="#B98B5E",
    ),
    AgtronScale(
        name="Light",
        agtron_range=AgtronRange(71.0, 100.99),
        description="New England",
        color_map="#D2A679",
    ),
    AgtronScale(
        name="Very Light",
        agtron_range=AgtronRange(101.0, 130.0),
        description="Cinnamon",
        color_map="#E8CDA5",
    ),
]


def in_agtron_scale(value: float, scale: AgtronScale) -> bool:
    """True when *value* falls in *scale*, from its lower bound up to the next level's.

    The levels are written x.00 to x.99: read inclusively, a converted figure
    such as 60.995 fell between two and had no level at all.
    """
    rng = scale.agtron_range
    names = [s.name for s in AGTRON_SCALES]
    if scale.name in names and names.index(scale.name) + 1 < len(names):
        return rng.min_value <= value < AGTRON_SCALES[names.index(scale.name) + 1].agtron_range.min_value
    return rng.min_value <= value <= rng.max_value


def agtron_scale_for(value: float) -> "AgtronScale | None":
    """The roast level an Agtron figure falls in, or None off the scale."""
    return next((s for s in AGTRON_SCALES if in_agtron_scale(value, s)), None)


# ── Colour helpers ────────────────────────────────────────────────────────────
# These functions are pure (no Qt dependency) so they can be imported at module
# level in any consumer without triggering Qt initialisation.

# Roast-colour systems whose readings are already on (or aligned to) the Agtron
# Gourmet scale (0-100, higher = lighter) and are used as-is.
# ColorTrack (Probat): SCAA cupping standard (coffeelabequipment.com/SCAA_COFFEE_COLOR.pdf)
# sets Agtron Gourmet=63.0 ↔ ColorTrack=62.0 (within the ±1 document tolerance),
# confirming the two scales are effectively 1:1 around the medium-light reference.
_AGTRON_NATIVE: frozenset[str] = frozenset({"agtron", "colortest", "colortrack", ""})


def to_agtron(value: float, system: str) -> float:
    """SINGLE SOURCE OF TRUTH for converting any roast-colour reading to the
    Agtron Gourmet scale (0-100, higher = lighter). Every TilauScope module that
    needs an Agtron value MUST go through this function so the whole app shares
    one definition.

    Agtron is the only *normalised* roast-level reference, so readings on other
    meters are APPROXIMATED rather than rejected — for roast-level purposes an
    approximation is more useful than no value at all.

    Sources:
      [S-SCAA] SCAA Standard "Roast Level for Cupping" (coffeelabequipment.com/
               SCAA_COFFEE_COLOR.pdf): single-point anchors at the cupping
               reference roast (Agtron Gourmet 63 ± 1).
      [S-TON]  Tonino-App official calibration files (github.com/myTonino/
               Tonino-App, src/scales/*.toni v1.0.24): 13 measured Agtron/
               Tonino pairs bridged through the shared raw-sensor axis.
               OLS linear fit: Tonino → Agtron  (σ ≈ 4 Ag).
      [S-PROB] Probat Colorette product page (probat.com): Colorette scale
               range 0–200.

    ColorTrack [S-SCAA]: CT=62.0 ↔ Ag=63.0 — within SCAA ±1 tolerance, so
    ColorTrack ≈ Agtron Gourmet (same scale, same direction). Listed in
    _AGTRON_NATIVE; value returned as-is.

    Tonino [S-TON]: T-values run lighter-is-higher, same direction as Agtron.
    OLS on 13 pairs from Agtron.toni + Tonino.toni:
      Agtron = 0.777 × T − 16.6   (±4 Ag at 1σ, unbiased)

    Probat Colorette 3b [S-SCAA + S-PROB]: scale 0–200, lighter-is-higher.
    SCAA anchor: Col3b=96.0 ↔ Ag=63.0.  Assuming proportional through origin
    (both read ≈ 0 for carbonised/unroasted green):
      Agtron = 0.656 × Colorette   (single-anchor estimate; ±8 Ag uncertainty)

    Returns 0.0 only when there is genuinely no reading (value <= 0), which
    callers treat as "unknown colour".
    """
    if value <= 0:
        return 0.0
    s = (system or "").strip().lower()
    if s in _AGTRON_NATIVE:
        return value
    if s == "tonino":
        # [S-TON] OLS on 13 Agtron.toni/Tonino.toni calibration pairs.
        return (value * 0.777) - 16.6
    if s == "colorette":
        # [S-SCAA + S-PROB] Colorette 3b, scale 0–200.  Single SCAA anchor
        # (Col3b=96 ↔ Ag=63) + proportional-through-origin assumption.
        return value * 0.656
    return value  # unknown meter → assume already Agtron-comparable


DEFAULT_COLOR_SYSTEM: str = "Agtron"


## Ground minus whole-bean Agtron on the selected roaster (roasters.json): the
## gap between the bean's surface and its inside depends on the technology.
_whole_to_ground_offset: float = 0.0


def set_whole_to_ground_offset(offset: float) -> None:
    """Called by the single resolver of the selected roaster."""
    global _whole_to_ground_offset  # noqa: PLW0603  # one roaster selected per process
    _whole_to_ground_offset = float(offset or 0.0)


def roast_agtron(ground: float, whole: float, system: str) -> "tuple[float, str]":
    """SINGLE SOURCE OF TRUTH for a roast's colour: (Agtron, basis).

    The ground colour is the true colour of a roast. A roast measured whole only
    reads at its estimated ground colour ('estimated'); 'whole' only when the
    roaster declares no gap; (0.0, '') without a reading.
    """
    if ground and ground > 0:
        return to_agtron(ground, system), 'ground'
    if whole and whole > 0:
        _agtron = to_agtron(whole, system)
        if _agtron > 0 and _whole_to_ground_offset:
            return _agtron + _whole_to_ground_offset, 'estimated'
        return _agtron, 'whole'
    return 0.0, ''


def agtron_text(agtron: float, basis: str) -> str:
    """A roast colour as shown: an estimate carries its ~."""
    return f"{'~' if basis == 'estimated' else ''}{agtron:.0f}"


def resolve_color_system(current: str, ground: float, whole: float,
                         default: str = DEFAULT_COLOR_SYSTEM) -> str:
    """Name the colour scale of a roast that carries a reading but no scale.

    Artisan's colour-system index defaults to 0, and entry 0 is the empty
    string: a profile saved without an explicit choice reads back as
    `color_system: ''`. Every consumer that needs the scale to interpret the
    figure — the dial-in advice, the label — takes that for "no colour
    measured" and refuses a roast that was in fact measured. The TilauScope
    colour fields are Agtron, so the scale is named as soon as a reading
    exists.

    Returns *current* when it is already set, *default* when a reading exists
    without one, and "" when there is genuinely nothing measured.
    """
    cur = (current or "").strip()
    if cur:
        return cur
    if ground > 0 or whole > 0:
        return default
    return ""


def get_agtron_color(agtron: float) -> str:
    """Return the grain-colour hex that matches *agtron* on the SCA Gourmet scale.

    The colour is taken directly from AGTRON_SCALES.color_map so the
    annotation always reflects the actual visual colour of the bean.
    Falls back to a neutral grey when the value is out of range (e.g. -1
    sentinel or pre-stabilisation noise).
    """
    scale = agtron_scale_for(agtron)
    return scale.color_map if scale is not None else "#9E9E9E"  # grey — out of range / sensor not ready


class ColourSeries:
    """One to five readings of the same sample, averaged.

    When the series is full, the next reading overwrites the first slot and the
    following ones go round the list. A slot tapped to redo takes the next
    reading in place; its old value counts until then.
    """

    MAX_SIZE = 5

    def __init__(self, size: int = 3) -> None:
        self.size = min(max(int(size), 1), self.MAX_SIZE)
        self.readings: list[float] = []
        self._next = 0   # slot the next reading overwrites once full
        self._redo: int | None = None   # slot tapped to redo: the next reading lands there

    def add(self, value: float) -> None:
        if self._redo is not None:
            self.readings[self._redo] = float(value)
            if self.full:
                self._next = (self._redo + 1) % self.size
            self._redo = None
            return
        if len(self.readings) < self.size:
            self.readings.append(float(value))
            return
        self.readings[self._next] = float(value)
        self._next = (self._next + 1) % self.size

    def redo(self, index: int) -> None:
        if 0 <= index < len(self.readings):
            self._redo = index

    def resize(self, size: int) -> None:
        """A size below the readings taken is refused."""
        size = min(max(int(size), 1), self.MAX_SIZE)
        if size >= len(self.readings):
            self.size = size
            self._next = 0

    def clear(self) -> None:
        self.readings = []
        self._next = 0
        self._redo = None

    @property
    def full(self) -> bool:
        return len(self.readings) == self.size

    @property
    def next_slot(self) -> int:
        """The slot the next reading lands in."""
        if self._redo is not None:
            return self._redo
        return self._next if self.full else len(self.readings)

    @property
    def mean(self) -> "float | None":
        return round(sum(self.readings) / len(self.readings), 1) if self.readings else None

    @property
    def spread(self) -> float | None:
        """Half the gap between the highest and lowest reading; None below two."""
        if len(self.readings) < 2:
            return None
        return (max(self.readings) - min(self.readings)) / 2

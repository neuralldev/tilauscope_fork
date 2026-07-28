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
# TiLau 2025

import uuid
import platform
from dataclasses import dataclass, field
from mashumaro.mixins.json import DataClassJSONMixin
from mashumaro.mixins.dict import DataClassDictMixin
from mashumaro.config import BaseConfig
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QFrame, QLabel, QProgressBar
from PyQt6.QtCore import Qt, QPropertyAnimation, QTimer

_IS_MACOS   = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"
_IS_LINUX   = platform.system() == "Linux"

class AUCStartEvent:
    CHARGE = 0
    TP = 1
    DRYEND = 2
    FCSTART = 3

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

@dataclass
class BrewDialIn(DataClassJSONMixin):
    """One accepted brew dial-in for a bean, keyed by brew method.

    Stores the corrected recipe plus what produced it, so a later brew of the
    same bean reopens on the setting that actually tasted right instead of the
    generic recommendation. One entry per method (latest wins).
    """
    method_id: str = ''
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    ## TILAU ## What the engine recommended BEFORE the correction. A dial-in is
    ## a relative adjustment, not an absolute setting: storing the base lets the
    ## same ratio be re-applied to a different roast of the same bean (a darker
    ## roast legitimately needs a coarser grind), and makes the corrections
    ## comparable across beans. 0 = legacy entry recorded before this was kept.
    base_grind_um: int = 0
    base_temp_c: float = 0.0
    base_ratio: float = 0.0       # the N in 1:N before the correction
    dose_g: float = 0.0
    taste: list[str] = field(default_factory=list)   # TasteCode values reported
    diagnosis: str = ''                              # DiagnosisCode value
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    iso_date: str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True


## TILAU ## One measured extraction, kept for later analysis — NOT for reopening.
## `dial_ins` above answers "what setting should I reopen on"; this answers "did the
## last change actually do anything". They are deliberately separate: dial_ins is
## latest-wins (one per method), this is an append-only journal, and it lives in its
## own file (brewlog.json) because it is analysis data with its own life cycle.
##
## Doctrine (wiki/Brew-DialIn-Feedback-Spec.md, from feedback_settings_first_doctrine):
## the SETTING is the cause, the flow time is the CONSEQUENCE. Recording both plus the
## context is what makes the cause/consequence link auditable later. Nothing here is
## ever fed back into a recipe automatically.
@dataclass
class BrewSample(DataClassJSONMixin):
    method_id: str = ''
    iso_date: str = ''
    # ── the cause: what was actually brewed ──
    grind_um: int = 0
    ratio: float = 0.0            # the N in 1:N
    temp_c: float = 0.0
    dose_g: float = 0.0
    # ── what the engine had recommended before any correction ──
    base_grind_um: int = 0
    base_ratio: float = 0.0
    base_temp_c: float = 0.0
    # ── the target: needed to recompute the gap once the engine has moved on ──
    planned_time_s: int = 0
    planned_water_g: float = 0.0
    # ── the consequence ──
    measured_time_s: int = 0
    measured_yield_g: float = 0.0
    ## TILAU ## The clean filter signal. Total time is mostly the operator's pour
    ## schedule; only the final drain reflects the bed, hence the grind. False when
    ## no scale was on the line — never estimated, the gap is left visible.
    drawdown_s: int = 0
    drawdown_valid: bool = False
    ## TILAU ## Where the two measurements above came from: "scale" when Artisan
    ## read them off the Acaia, "manual" when the operator typed them because the
    ## machine has an integrated scale no cup fits over (La Marzocco Mini and
    ## friends). Kept because a typed shot time is rounded to the second and read
    ## off another device: the row is worth the same to the operator, but a later
    ## fit must be able to tell the two populations apart before trusting a slope.
    measured_source: str = 'scale'
    # ── the context, without which the two above cannot be compared ──
    agtron: float = 0.0
    days_off_roast: int = -1
    espresso_style: str = ''
    # ── the verdict that justified recording this at all ──
    taste: list[str] = field(default_factory=list)
    diagnosis: str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True


@dataclass
class BrewLog(DataClassJSONMixin):
    """Journal of measured extractions, keyed by GreenBean.uuid.

    Lives in brewlog.json beside beancave.json. Its absence is a normal state:
    nothing depends on it to brew.
    """
    version: int = 1
    entries: dict[str, list[BrewSample]] = field(default_factory=dict)
    class Config(BaseConfig):
        ignore_missing_keys = True


@dataclass
class GreenBean(DataClassJSONMixin):
    name: str = ''
    farm: str = ''
    country: str = ''
    supplier: str = ''
    category: str = ''
    process: str = ''
    crop: int = 0
    density: float = 0.0
    last_humidity: float = 0.0
    water_activity: float = 0.0
    volume: float = 0.0
    altitude: int = 0
    species: str = ""
    varieties: str = ""
    weight_left: float = 0.0 # input green beans left in stock
    flavour_notes: str = ''
    sca: float = 0.0
    count: int = 0
    weight: float = 0.0 # calculation of total weight roasted from alogs
    # --- Blend Fields ---
    is_blend: bool = False
    bean1_ratio: float = 100.0
    bean2_name: str = ''
    bean2_ratio: float = 0.0
    bean3_name: str = ''
    bean3_ratio: float = 0.0
    blend_notes: str = ''
    tips: str = ''
    ## TILAU ## Sack identifiers attached to this bean (labelled bags). Fully
    ## optional: an empty list is a normal, permanent state — nothing depends
    ## on a sack being registered. weight_left stays the single global stock.
    sacks: list[str] = field(default_factory=list)
    ## TILAU ## Storage conditioning for the water-activity advisor (Stockage tab).
    ## Language-neutral key: '' (unknown) | 'vacuum' | 'grainpro' | 'ecotact' | 'bocal' | 'toile'.
    ## Sealed conditionings suspend the moisture-drift trend (no air exchange).
    conditioning: str = ''
    ## TILAU ## Accepted brew dial-ins, one per brew method (latest wins). Fully
    ## optional and additive: an empty list is the normal state for a bean never
    ## brewed with taste feedback, and old libraries load unchanged
    ## (ignore_missing_keys).
    dial_ins: list[BrewDialIn] = field(default_factory=list)
    uuid:str = ''
    class Config(BaseConfig):
        ignore_missing_keys = True

@dataclass
class ReferenceProfile(DataClassJSONMixin):
    title: str =''
    count: int = 0
    avg_drop_bt: float = 0.0
    avg_weight_loss : float = 0.0
    avg_roast_color : float = 0.0
    avg_total_time_min : float = 0.0
    avg_dtr_pct : float = 0.0

@dataclass
class BeanCaveContainer(DataClassJSONMixin):
    green_beans: list[GreenBean] = field(default_factory=list)
    reference_profiles: list[ReferenceProfile] = field(default_factory=list)
    class Config(BaseConfig):
        ignore_missing_keys = True

GREEN_BEAN_COLUMNS = [
    lambda b: b.name,
    lambda b: b.farm,
    lambda b: b.country,
    lambda b: b.supplier,
    lambda b: b.category,
    lambda b: b.process,
    lambda b: str(b.crop),
    lambda b: f"{b.density:.1f}",
    lambda b: f"{b.last_humidity:.1f}",
    lambda b: f"{b.water_activity:.2f}",
    lambda b: f"{b.volume:.3f}",
    lambda b: str(b.altitude),
    lambda b: b.species,
    lambda b: b.varieties,
    lambda b: f"{b.weight_left:.1f}",
    lambda b: b.flavour_notes,
    lambda b: f"{b.sca:.1f}",
    lambda b: str(b.count),
    lambda b: f"{b.weight:.1f}",
    lambda b: "Oui" if b.is_blend else "Non",
    lambda b: f"{b.bean1_ratio:.1f}%",
    lambda b: b.bean2_name,
    lambda b: f"{b.bean2_ratio:.1f}%",
    lambda b: b.bean3_name,
    lambda b: f"{b.bean3_ratio:.1f}%",
    lambda b: b.blend_notes,
    lambda b: b.tips,
    lambda b: b.uuid if b.uuid!='' else str(uuid.uuid4()),
]

AGTRON_SCALES: list[AgtronScale] = [
    AgtronScale(
        name="Extremely Dark",
        agtron_range=AgtronRange(0.0, 25.99),
        description="Italian",
        color_map="#2f1202",
    ),
    AgtronScale(
        name="Very Dark",
        agtron_range=AgtronRange(26.0, 34.99),
        description="French",
        color_map="#431902",
    ),
    AgtronScale(
        name="Dark",
        agtron_range=AgtronRange(35.0, 40.99),
        description="Vienna",
        color_map="#3c1601",
    ),
    AgtronScale(
        name="Medium Dark",
        agtron_range=AgtronRange(41.0, 50.99),
        description="Full City",
        color_map="#561f01",
    ),
    AgtronScale(
        name="Medium",
        agtron_range=AgtronRange(51.0, 60.99),
        description="City",
        color_map="#7b3916",
    ),
    AgtronScale(
        name="Medium Light",
        agtron_range=AgtronRange(61.0, 70.99),
        description="American",
        color_map="#863C14",
    ),
    AgtronScale(
        name="Light",
        agtron_range=AgtronRange(71.0, 100.99),
        description="New England",
        color_map="#9d4515",
    ),
    AgtronScale(
        name="Very Light",
        agtron_range=AgtronRange(101.0, 130.0),
        description="Cinnamon",
        color_map="#a14513",
    ),
]

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


def get_agtron_color(agtron: float) -> str:
    """Return the grain-colour hex that matches *agtron* on the SCA Gourmet scale.

    The colour is taken directly from AGTRON_SCALES.color_map so the
    annotation always reflects the actual visual colour of the bean.
    Falls back to a neutral grey when the value is out of range (e.g. -1
    sentinel or pre-stabilisation noise).
    """
    for scale in AGTRON_SCALES:
        if scale.agtron_range.min_value <= agtron <= scale.agtron_range.max_value:
            return scale.color_map
    return "#9E9E9E"  # grey — out of range / sensor not ready


def get_roc_color(roc: float) -> str:
    """Return a colour for the Omniflux Rate-of-Color value (Agtron/min).

    The RoC is negative during normal roasting (bean darkens → Agtron drops).
    We work on the magnitude so the palette is direction-independent:

        blue  → slow / stalled   (abs < 1.0)
        green → steady brunissement (1.0 – 3.0)
        gold  → active / fast    (3.0 – 6.0)
        red   → aggressive       (> 6.0)
    """
    abs_roc = abs(roc)
    if abs_roc > 6.0:  return "#FF4500"  # OrangeRed  — aggressive
    if abs_roc > 3.0:  return "#FFD700"  # Gold       — active
    if abs_roc >= 1.0: return "#32CD32"  # LimeGreen  — steady
    return "#00BFFF"                     # DeepSkyBlue — slow / stalled


# ── RoR (Rate-of-Rise, bean temperature) phase classifier ───────────────────
# Distinct from get_roc_color() above (Rate-of-COLOUR, Agtron/min). RoR works on
# BT in degrees/min. Bands are dual-sided (both too-high and too-low matter) and
# phase-specific. Source: Rao / Cropster / Mill City / Anne Cooper.
_ROR_PHASE_BANDS_C = {
    # phase_key:  (warn_lo, warn_hi, crit_lo, crit_hi)   -- ideal band in comment
    "CHARGE_DRY": (6.0, 15.0, 3.0, 18.0),   # ideal 8-14
    "DRY_FC":     (4.0, 13.0, 2.0, 16.0),   # ideal 5-12
    "FC_DROP":    (1.5,  7.0, 0.5,  9.0),   # ideal 2-6
}
_ROR_IDEAL_C = {"CHARGE_DRY": (8.0, 14.0), "DRY_FC": (5.0, 12.0), "FC_DROP": (2.0, 6.0)}
_ROR_PHASE_ALIASES = {
    "drying": "CHARGE_DRY", "dry": "CHARGE_DRY", "charge_dry": "CHARGE_DRY",
    "maillard": "DRY_FC", "dry_fc": "DRY_FC",
    "development": "FC_DROP", "dev": "FC_DROP", "fc_drop": "FC_DROP",
}


def _ror_phase_key(phase: str) -> str:
    p = str(phase).strip()
    return _ROR_PHASE_ALIASES.get(p.lower(), p.upper())


def get_ror_color_by_phase(ror: float, phase: str, mode: str = "C") -> tuple[str, str, str]:
    """
    Classify a BT Rate-of-Rise (degrees/min) against dual-sided, phase-specific
    bands. Returns (level, direction, colour):

        level     : "ok" | "warn" | "crit"
        direction : "normal" | "high" | "low"
        colour    : hex string (green / gold / red)

    `phase` accepts a band key ("CHARGE_DRY"|"DRY_FC"|"FC_DROP") or an alias
    ("drying"|"maillard"|"development"). mode "F" scales the C bands by 1.8.

    This is the RoR (bean-temperature) classifier. For Rate-of-Colour
    (Agtron/min) use get_roc_color(): RoR and RoC are different signals.
    """
    band = _ROR_PHASE_BANDS_C.get(_ror_phase_key(phase))
    if band is None or ror is None:
        return "ok", "normal", "#32CD32"
    warn_lo, warn_hi, crit_lo, crit_hi = band
    if mode == "F":
        warn_lo, warn_hi, crit_lo, crit_hi = (v * 1.8 for v in (warn_lo, warn_hi, crit_lo, crit_hi))
    if ror > crit_hi:
        return "crit", "high", "#FF4500"
    if ror < crit_lo:
        return "crit", "low", "#FF4500"
    if ror > warn_hi:
        return "warn", "high", "#FFD700"
    if ror < warn_lo:
        return "warn", "low", "#FFD700"
    return "ok", "normal", "#32CD32"


def get_ror_ideal_band(phase: str, mode: str = "C") -> tuple[float, float]:
    """Ideal RoR target band (degrees/min) for a phase, for display/messaging."""
    lo, hi = _ROR_IDEAL_C.get(_ror_phase_key(phase), (0.0, 0.0))
    return (lo * 1.8, hi * 1.8) if mode == "F" else (lo, hi)


# dictionnaire de standardisation pour nettoyer les noms de processus courants
standardization_map = {
    # Cible les termes sans les séparateurs pour les rendre plus flexibles
    "Washed Wet": "Washed",
    "Natural - Dry": "Natural",
    "Natural - Wet": "Natural", 
    "Washed Process": "Washed",
    "Natural Process": "Natural",
}

# Artisan roasting phases from timeindex table
class RoastingPhase:
    CHARGE = 0
    DRYEND = 1
    FCSTART = 2
    FCEND = 3
    SCSTART = 4
    SCEND = 5
    DROP = 6
    COOLEND = 7


@dataclass
class MQTTSensor(DataClassDictMixin):
    id: str = ""
    topic: str =""
    command: str = ""
    multiplier: float | None = 1.0
    divider: float | None = 1.0

@dataclass
class MQTTSensorConfig(DataClassJSONMixin):
    sensors: list[MQTTSensor]

MQTT_SENSORS_KEY = "mqtt/sensors"

# temperature offset from BT probe to actual bean temp
@dataclass
class ProbeDeviationInterval:
    start_min: float = 0.0
    end_min: float = 0.0

# roaster BT deviation settings
@dataclass
class ProbeDeviation(DataClassDictMixin):
    probe_id: str
    bt_at_charge : ProbeDeviationInterval
    bt_at_de : ProbeDeviationInterval
    bt_at_fc : ProbeDeviationInterval
    bt_at_drop : ProbeDeviationInterval
    use_roaster_offsets: bool = True

@dataclass
class RoasterBasicPlanPerPhase:
   #  "Light"          : ((0.85,0.70,0.50), (175,185), (08.5, 11.0), (3.5, 5.5), (3.0,4.0), (1.0,1.5), (0.12,0.15), (192,196)),
   name: str
   heater_cmfc: tuple[float, float, float]
   charge_temp: tuple[int, int]
   total_time: tuple[float, float]
   drying_time: tuple[float, float]
   maillard_time: tuple[float, float]
   development_time: tuple[float, float]
   dtr_pct: tuple[float, float]
   drop_temp: tuple[int, int]
   fc_temp:int
   dry_temp:int

@dataclass
class RoasterBasicPlan(DataClassDictMixin):
    plans: list[RoasterBasicPlanPerPhase]
# 
# category = Traditional Wet
# process = Washed / Wet Process
# species = Arabica
# varieties = Bourbon

THEME = {
    "BG": "#1E1E2E",      # Base background
    "SURFACE": "#181825", # Secondary background
    "TEXT": "#CDD6F4",    # Main text
    "SUBTEXT": "#94A3B8", # Secondary text
    "ACCENT": "#89B4FA",  # Blue
    "BORDER": "#313244",
    "WARNING": "#E0903B",
    "CRITICAL": "#F38BA8", # Red for cleaning alerts
    "SUCCESS": "#A6E3A1",   # Green
    "HOVER": "#B9C098",
    "TODAY": "#FAB387",   
    "VERY_LIGHT_ROAST": "#BBE3A1",
    "LIGHT_ROAST": "#A6E3A1",
    "MED_ROAST": "#825E50",
    "DARK_ROAST": "#583121", 
    "VERY_DARK_ROAST": "#35190E", 
}

def format_batch_label(prefix: str, nr: int, pos: int | None = None) -> str:
    """Render an Artisan batch identity as a display string.

    Mirrors Artisan's convention: ``{prefix}{nr} (pos)``.
    Returns an empty string when ``nr <= 0`` (batch system inactive or
    not yet assigned — the number is assigned by Artisan at DROP).
    """
    if nr is None or nr <= 0:
        return ""
    label = f"{prefix or ''}{int(nr)}"
    if pos:
        label += f" ({int(pos)})"
    return label

import unicodedata
def replace_accents(texte):
    if not texte:
        return ""
    
    # Normalisation NFKD pour séparer les caractères de leurs accents
    charg_normalise = unicodedata.normalize('NFKD', texte)
    
    # On ne garde que les caractères qui ne sont pas des "combinaisons" (accents)
    # et on réencode en ASCII en ignorant les erreurs pour plus de sécurité
    return "".join([c for c in charg_normalise if not unicodedata.combining(c)])

def show_styled_message(parent, title, text, icon=QMessageBox.Icon.Information, rich=False, width:int= 0, buttons:list[str]=None):
    m = TilauMessageBox(parent, title, text, icon, rich, width, buttons)
    return m.exec() # call message box

class TilauMessageBox(QMessageBox):
    def __init__(self, parent, title, text, icon, rich, width,buttons:list[str]=None):
        ## TILAU ## Parent to the caller's window when it is a real visible window
        ## (e.g. TilauScope). Parent=None made the dialog unrecognised by
        ## TilauScope._safe_raise (it walks the parent chain), which then re-raised
        ## itself over the dialog and stole focus -> OK needed two clicks. Parenting
        ## ties activation/modality to that window and fixes the first-click.
        _p = parent if (parent is not None and parent.isVisible()) else None
        super().__init__(parent = _p)
        self.setModal(True)
        # 1. This allows the rounded corners to be transparent to the parent
#        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 2. Frameless keeps it clean.
        ## TILAU ## No Qt.Tool flag: a Tool window never becomes the key/active
        ## window on macOS, so OK needed two clicks (first to activate, second to
        ## press). A plain frameless dialog can take activation on the first click.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        
        self.setWindowTitle(title)
        self.setText(text)
        
        if rich:
            self.setTextFormat(Qt.TextFormat.RichText) 
        
        self.setIcon(QMessageBox.Icon.Information if icon is None else icon)

        
        if buttons is None:
            btn = self.addButton(QMessageBox.StandardButton.Ok)
            self._tilau_ok_button = btn
            btn.setDefault(True)
            btn.setAutoDefault(True)
        else:
            self._clicked_button_index = -1 # Valeur par défaut si fermé autrement
            for index, btn_text in enumerate(buttons):
                pb = self.addButton(btn_text, QMessageBox.ButtonRole.ActionRole)
                
                # On passe l'index actuel à la fonction qui gère le clic
                pb.clicked.connect(lambda checked, idx=index: self.on_button_clicked(idx))
        QTimer.singleShot(0, self._tilau_grab_focus)

        # 3. Use the stylesheet to force a solid background on the widget
        # We add a margin so the border-radius has "room" to exist inside the window
        self.setStyleSheet(f"""
            QMessageBox {{
                background-color: {THEME['BG']};
                border: 2px solid {THEME['ACCENT']};
                
            }}
            QLabel {{
                color: {THEME['TEXT']};
                font-family: 'JetBrains Mono';
                font-size: 14px;
                padding: 20px;
                background: transparent;
            }}
            QPushButton {{
                background-color: {THEME['ACCENT']};
                color: {THEME['BG']};
                border-radius: 5px;
                font-weight: bold;
                padding: 8px 20px;
                margin: 10px;
            }}
            QPushButton:hover {{
                background-color: {THEME['HOVER']};
            }}
        """)
        
        # Ensure it has a physical size
        self.setMinimumWidth(800 if width == 0 else width)
        self.setMinimumHeight(400)

    def on_button_clicked(self, index):
        # 1. On mémorise l'index du bouton qui a été cliqué
        self._clicked_button_index = index
        # 2. On lance votre animation de fade out
        self.start_fade_out()

    def _tilau_grab_focus(self):
        ## TILAU ## Bring the message box to the front and give it activation +
        ## button focus so the very first click on OK registers (see __init__).
        self.raise_()
        self.activateWindow()
        try:
            self._tilau_ok_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except (RuntimeError, AttributeError):
            pass

    def start_fade_out(self):
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(400)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self.close)
        self.fade_anim.start()
        self.conclude_dialog()

    def conclude_dialog(self):
        # done() ferme la boîte de dialogue et fait sauter le verrou du exec()
        # en renvoyant la valeur passée en argument.
        if hasattr(self, '_clicked_button_index'):
            self.done(self._clicked_button_index)
        else:
            self.done(0) # Pour le bouton OK standard par exemple

class TilauProgressDialog(QDialog):
    def __init__(self, message: str, parent=None, maxvalue=int|None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.setup_ui(message, maxvalue)
        self.resize(400, 180)

    def setup_ui(self, message, maxvalue):
        self.main_layout = QVBoxLayout(self)
        self.container = QFrame()
        self.container.setStyleSheet(f"""
            QFrame {{ 
                background-color: {THEME['BG']}; 
                border: 2px solid {THEME['ACCENT']}; 
                border-radius: 20px; 
            }}
        """)
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(30, 30, 30, 30)
        self.main_layout.addWidget(self.container)

        self.msg_label = QLabel(message.upper())
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setStyleSheet(f"color: white; font-weight: bold; font-family: 'JetBrains Mono'; border: none;")
        
        # Modern Indeterminate Progress Bar
        self.pbar = QProgressBar()
        self.pbar.setRange(0, 0 if maxvalue is None else maxvalue) # Indeterminate mode
        self.pbar.setFixedHeight(8)
        self.pbar.setTextVisible(False)
        self.pbar.setStyleSheet(f"""
            QProgressBar {{ 
                background: {THEME['SURFACE']}; 
                border-radius: 4px; 
                border: none; 
            }}
            QProgressBar::chunk {{ 
                background: {THEME['ACCENT']}; 
                border-radius: 4px; 
            }}
        """)

        self.content_layout.addWidget(self.msg_label)
        self.content_layout.addSpacing(20)
        self.content_layout.addWidget(self.pbar)

# ── Milestone temperature windows (DE / FC) ─────────────────────────────────
# Profession-standard milestone bands in the *true* bean frame (before per-roaster
# sensor offset). Resolution: (1) plan target >0 -> point (offset already applied
# by the plan); (2) else profession band + roaster per-phase BT offset
# (displayed = true + offset); offset 0 -> raw profession default.
PROFESSION_DE_TRUE_C: tuple[float, float] = (158.0, 163.0)
PROFESSION_FC_TRUE_C: tuple[float, float] = (195.0, 200.0)
_MILESTONE_HALF_C: float = 5.0


def resolve_milestone_window(plan_target_c: float, true_band_c: tuple[float, float],
                             sensor_offset_c: float = 0.0,
                             half_c: float = _MILESTONE_HALF_C
                             ) -> tuple[float, float, float, float]:
    """Returns (gate_lo, gate_hi, band_lo, band_hi) in the displayed BT frame."""
    if plan_target_c and plan_target_c > 0.0:
        band_lo = band_hi = float(plan_target_c)
    else:
        band_lo = float(true_band_c[0]) + float(sensor_offset_c)
        band_hi = float(true_band_c[1]) + float(sensor_offset_c)
    return band_lo - half_c, band_hi + half_c, band_lo, band_hi


def resolve_de_window(plan_target_c: float, bt_dry_offset_c: float = 0.0,
                      half_c: float = _MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_DE_TRUE_C, bt_dry_offset_c, half_c)


def resolve_fc_window(plan_target_c: float, bt_fc_offset_c: float = 0.0,
                      half_c: float = _MILESTONE_HALF_C) -> tuple[float, float, float, float]:
    return resolve_milestone_window(plan_target_c, PROFESSION_FC_TRUE_C, bt_fc_offset_c, half_c)
#
# ABOUT
# Beancave

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

# roaster management

from pathlib import Path
from enum import StrEnum, auto
from dataclasses import dataclass, field
from mashumaro.mixins.dict import DataClassDictMixin
import json
import math
from tilauscope.tilauscope_types import _IS_MACOS, _IS_WINDOWS
from typing import Final
import logging
_logd: Final[logging.Logger] = logging.getLogger('tilau')

LEGACY_ROASTER_NAMES: Final[dict[str, str]] = {
    'Cormorant': 'Cormorant CR600g',
    'Kaleido Serial': 'Kaleido M6 Pro',
    'Skywalker Series - Delta': 'ITOP Skywalker V1',
}


def canonical_roaster_name(name: str) -> str:
    """Normalize known legacy Artisan labels to a roasters.json display name."""
    stripped = name.strip()
    return LEGACY_ROASTER_NAMES.get(stripped, stripped)

class HeatingType(StrEnum):
    GAS = auto()
    ELECTRIC = auto()
    INFRARED = auto()
    INDUCTION = auto()
    HYBRID = auto()
    WOOD = auto()
    COAL = auto()


class RoasterTechnology(StrEnum):
    CONDUCTION = auto()
    CONVECTION = auto()
    RADIATION = auto()
    HYBRID = auto()

class RoasterType(StrEnum):
    DRUM = auto()
    FLUID_BED = auto()
    SPINNING_DRUM = auto()
    RECIRCULATING_FLUID_BED = auto()
    TANGENTIAL = auto()
    SAMPLE_ROASTER = auto()
    SHOP_ROASTER = auto()
    INDUSTRIAL = auto()


class DrumMaterial(StrEnum):
    CAST_IRON = auto()
    STAINLESS_STEEL = auto()
    CARBON_STEEL = auto()
    CERAMIC_COATED = auto()
    MIXED = auto()
    GLASS = auto()

class DrumDesign(StrEnum):
    SOLID = auto()
    PERFORATED = auto()
    HYBRID = auto()


class AirflowControlType(StrEnum):
    NONE = auto()
    STEPPED = auto()
    VARIABLE = auto()
    CLOSED_LOOP = auto()

class BurnerControlType(StrEnum):
    NONE = auto()
    STEPPED = auto()
    VARIABLE = auto()
    PID = auto()
    PWM = auto()


class CoolingSystemType(StrEnum):
    INTERNAL_TRAY = auto()
    EXTERNAL_COOLER = auto()
    VACUUM = auto()
    WATER_QUENCH = auto()
    NONE = auto()

class ProbeType(StrEnum):
    THERMOCOUPLE_K = auto()
    THERMOCOUPLE_J = auto()
    RTD_PT100 = auto()
    INFRARED = auto()
    OPTICAL = auto()


class ProbePlacement(StrEnum):
    BEAN_MASS = auto()
    EXHAUST = auto()
    INLET = auto()
    DRUM_WALL = auto()
    ENVIRONMENT = auto()
    COOLING_TRAY = auto()

class PowerUnit(StrEnum):
    WATT = auto()
    KILOWATT = auto()
    BTU = auto()


class PressureControlType(StrEnum):
    NONE = auto()
    MANUAL = auto()
    ELECTRONIC = auto()

class DataInterfaceType(StrEnum):
    USB = auto()
    SERIAL = auto()
    MODBUS = auto()
    BLUETOOTH = auto()
    WIFI = auto()
    MQTT = auto()
    ETHERNET = auto()


class RoastControlMode(StrEnum):
    MANUAL = auto()
    ASSISTED = auto()
    PID = auto()
    PROFILE_REPLAY = auto()
    AI_ASSISTED = auto()


class VoltageType(StrEnum):
    SINGLE_PHASE = auto()
    THREE_PHASE = auto()

class BeanDischargeType(StrEnum):
    FRONT = auto()
    SIDE = auto()
    AUTOMATIC = auto()


class AgitationType(StrEnum):
    DRUM_ROTATION = auto()
    STIRRER = auto()
    AIR_ONLY = auto()
    HYBRID = auto()

# ============================================================
# SENSOR MODELS
# ============================================================

@dataclass(slots=True)
class TemperatureProbe(DataClassDictMixin):
    name: str
    probe_type: ProbeType
    placement: ProbePlacement

    diameter_mm: float | None = None
    response_time_ms: int | None = None
    isolated_ground: bool = False

@dataclass(slots=True)
class OpticalSensor(DataClassDictMixin):
    supports_agtron: bool = False
    supports_rate_of_color: bool = False
    supports_crack_detection: bool = False

# ============================================================
# CONTROL CAPABILITIES
# ============================================================

@dataclass(slots=True)
class PhysicalRange(DataClassDictMixin):
    """
    Maps a 0-100% control percentage to a human-readable physical value.

    For display only (PDF plan, coaching hints).  The internal control
    pipeline always operates in percent — this struct is never used for
    calculations.

    Examples
    --------
    Cormorant CR600e heater : min=0, max=2400, step=100, unit="W"
      → pct_to_label(75) = "75% (1800 W)"
    Cormorant CR600e drum   : min=0, max=12,   step=0.5, unit="V"
      → pct_to_label(50) = "50% (6.0 V)"
    """
    min_physical: float
    max_physical: float
    unit: str
    step_physical: float | None = None   # None = linear interpolation, no snap

    def pct_to_label(self, pct: float) -> str:
        """Return '75%' or '75% (1800 W)' depending on available data."""
        pct_str = f"{pct:.0f}%"
        span = self.max_physical - self.min_physical
        if span <= 0.0:
            return pct_str
        raw = self.min_physical + (pct / 100.0) * span
        if self.step_physical and self.step_physical > 0.0:
            raw = round(raw / self.step_physical) * self.step_physical
        raw = max(self.min_physical, min(self.max_physical, raw))
        # Format: drop trailing zeros for floats; integer display when step ≥ 1
        if self.step_physical is not None and self.step_physical >= 1.0:
            phys_str = f"{raw:.0f}"
        else:
            phys_str = f"{raw:.4g}"
        return f"{pct_str} ({phys_str} {self.unit})"


@dataclass(slots=True)
class HeatingControl(DataClassDictMixin):
    control_type: BurnerControlType

    min_power_percent: float = 0.0
    max_power_percent: float = 100.0
    power_resolution_percent: float = 1.0

    # Optional physical mapping for display (PDF, coaching)
    physical_range: PhysicalRange | None = None


@dataclass(slots=True)
class AirflowControl(DataClassDictMixin):
    control_type: AirflowControlType

    min_airflow_percent: float = 0.0
    max_airflow_percent: float = 100.0
    airflow_resolution_percent: float = 1.0

    supports_negative_pressure_tracking: bool = False
    supports_closed_loop_exhaust: bool = False

    # Air path at the bean inlet: "push" = pressurised inlet (fan upstream),
    # "pull" = rear suction near the exhaust (airflow coupled with extraction).
    inlet_air_mode: str = "push"
    has_heater_control:  bool = True
    has_airflow_control: bool = True
    # Optional physical mapping for display (PDF, coaching)
    physical_range: PhysicalRange | None = None


@dataclass(slots=True)
class DrumControl(DataClassDictMixin):
    variable_speed: bool = False

    min_rpm: float | None = None
    max_rpm: float | None = None
    rpm_resolution: float | None = None
    min_rpm_setting: float | None = None
    step_rpm_setting: float | None = None

    # True = drum ramps speed progressively on a setting change. False
    # (default) = abrupt jump — drum must not be touched mid-roast.
    smooth_speed_transition: bool = False

    # Optional physical mapping for display (PDF, coaching)
    # e.g. Cormorant drum knob: 0–12 V, step 0.5 V
    physical_range: PhysicalRange | None = None

# ============================================================
# ENVIRONMENT / INSTALLATION
# ============================================================

@dataclass(slots=True)
class ElectricalSpecification(DataClassDictMixin):
    voltage: int| None = None
    phase_type: VoltageType = VoltageType.SINGLE_PHASE
    frequency_hz: int| None = None
    max_power_draw_kw: float | None = None

@dataclass(slots=True)
class GasSpecification(DataClassDictMixin):
    gas_type: str | None = None
    pressure_control: PressureControlType = PressureControlType.NONE

    nominal_consumption_kw: float | None = None

# ============================================================
# CORE ROASTER MODEL
# ============================================================

@dataclass(slots=True)
class Roaster(DataClassDictMixin):
    # --------------------------------------------------------
    # Identity
    # --------------------------------------------------------
    manufacturer: str
    model: str

    # --------------------------------------------------------
    # Classification
    # --------------------------------------------------------
    roaster_type: RoasterType
    heating_type: HeatingType
    technology: list[RoasterTechnology]

    # --------------------------------------------------------
    # Capacity
    # --------------------------------------------------------
    batch_capacity_min_g: int
    batch_capacity_max_g: int
    optimal_batch_capacity_g: int | None = None

    # --------------------------------------------------------
    # Drum / Bean Movement
    # --------------------------------------------------------
    agitation_type: AgitationType = AgitationType.DRUM_ROTATION

    drum_material: DrumMaterial | None = None
    drum_design: DrumDesign | None = None

    # --------------------------------------------------------
    # Thermal Characteristics
    # --------------------------------------------------------
    thermal_mass_index: float | None = None
    heat_retention_index: float | None = None
    airflow_dependency_index: float | None = None
    dev_thermal_inertia_factor: float | None = None   # 0.0–1.0; lower = faster response

    # Typical post-TP RoR reference (°C/min), not a physical ceiling.
    peak_ror_reference_c: float | None = None
    # Temporary read compatibility for older roaster JSON.
    peak_ror_ceiling_c: float | None = None

    ## Heater ceiling: hardware limit, not a style choice; the plan must
    ## never target above it. None (default) → RoasterContext falls back to 100.0.
    heater_max_pct: float | None = None
    # Machine-specific guidance thresholds; neither clamps a plan.
    heater_support_threshold_pct: float | None = None
    heater_caution_pct: float | None = None

    # Empirical geometric fallback for a reference curve. It is not a
    # stable physical machine signature.
    maillard_ror_decay: float | None = None

    # --------------------------------------------------------
    # Preheat PID Learning Model Kernel
    # --------------------------------------------------------
    # "triangular" = linear decay (FIR/fast roasters); "gaussian" = smooth
    # decay (inertia roasters).
    thermal_model_kernel: str = "triangular"
    ## Gaussian sigma parameter (only used if kernel="gaussian")
    thermal_model_sigma: float = 1.0

    # --------------------------------------------------------
    # Controls
    # --------------------------------------------------------
    heating_control: HeatingControl | None = None
    airflow_control: AirflowControl | None = None
    drum_control: DrumControl | None = None

    roast_control_mode: RoastControlMode = RoastControlMode.MANUAL

    # --------------------------------------------------------
    # Cooling
    # --------------------------------------------------------
    cooling_system: CoolingSystemType = CoolingSystemType.INTERNAL_TRAY

    # --------------------------------------------------------
    # Sensors
    # --------------------------------------------------------
    temperature_probes: list[TemperatureProbe] = field(default_factory=list)

    optical_sensor: OpticalSensor | None = None

    # --------------------------------------------------------
    # Connectivity
    # --------------------------------------------------------
    supported_interfaces: list[DataInterfaceType] = field(default_factory=list)

    artisan_compatible: bool = False

    # --------------------------------------------------------
    # Installation
    # --------------------------------------------------------
    electrical_specification: ElectricalSpecification | None = None
    gas_specification: GasSpecification | None = None

    # --------------------------------------------------------
    # Mechanical
    # --------------------------------------------------------
    bean_discharge_type: BeanDischargeType | None = None

    weight_kg: float | None = None
    width_mm: int | None = None
    depth_mm: int | None = None
    height_mm: int | None = None

    # --------------------------------------------------------
    # Roast Planning Variables
    # --------------------------------------------------------
    supports_preheat_profiles: bool = False
    supports_auto_charge_temperature: bool = False
    supports_auto_gas_events: bool = False
    supports_auto_airflow_events: bool = False
    supports_profile_replay: bool = False

    # Explicit JSON field so the plan generator never has to guess from
    # manufacturer/model strings. True = FIR/NIR/infrared heater technology.
    is_radiant_electric: bool = False

    # --------------------------------------------------------
    # Calibration / Offset
    # --------------------------------------------------------
    bean_temperature_offset_c: list[float] = field(default_factory=lambda: [0.0]*4)
    environmental_temperature_offset_c: list[float] = field(default_factory=lambda: [0.0]*4)
    # Stable slug matched against the device's handshake ROASTER_ID field,
    # e.g. "itop-cyberroaster". Optional — falls back to manufacturer/model
    # matching (see RoasterManager.get_by_roaster_id).
    roaster_id: str | None = None

    # --------------------------------------------------------
    # Notes
    # --------------------------------------------------------
    notes: str | None = None

    thermal_response_speed: float = 0.0


# ============================================================
# ROASTER CONTEXT  — flat, plan-friendly view of a Roaster
# ============================================================

@dataclass
class RoasterContext:
    """
    Flat, plan-friendly projection of a Roaster object.

    All values are guaranteed non-None with safe defaults so the
    plan generator never has to do None-checks inline.

    Usage::

        ctx = roaster_manager.get_roast_context()
        rpm_pct = ctx.rpm_to_percent(55.0)
    """

    display_name: str

    # ── Capacity ─────────────────────────────────────────────
    batch_min_g: int
    batch_max_g: int
    batch_optimal_g: int          # = max if not specified

    # ── Thermal indices ──────────────────────────────────────
    thermal_mass_index: float     # 0.0 – 1.0
    heat_retention_index: float   # 0.0 – 1.0
    airflow_dependency_index: float  # 0.0 – 1.0
    thermal_response_speed: float    # 0.0 – 1.0
    dev_thermal_inertia_factor: float  # 0.0 – 1.0 (lower = faster response)
    # Typical post-TP peak RoR reference (°C/min).
    peak_ror_reference_c: float

    # ── Heater ───────────────────────────────────────────────
    is_radiant_electric: bool        # replaces string-match is_fir_nir
    airflow_resolution_pct: float    # step size for rounding airflow values

    # ── Drum ─────────────────────────────────────────────────
    drum_variable_speed: bool
    drum_min_rpm: float
    drum_max_rpm: float
    drum_step_rpm: float             # minimum settable step
    drum_min_setting: float  # machine minimum % (e.g. 40%)

    # ── Probe offsets (indexed: 0=charge, 1=dry, 2=fc, 3=drop) ─
    bt_offsets: list[float]          # bean temperature offsets per phase

    # ── Capability flags ─────────────────────────────────────
    supports_preheat_profiles: bool
    supports_profile_replay: bool

    # ── Agitation ────────────────────────────────────────────
    agitation_type: AgitationType

    # ── Air path ─────────────────────────────────────────────
    # "push" (pressurised inlet) or "pull" (rear suction near exhaust). On a
    # pull machine, drum airflow and extraction are physically coupled.
    inlet_air_mode: str = "push"

    # ── Heater resolution ────────────────────────────────────
    heater_resolution_pct: float = 1.0  # step size for rounding heater values
    ## Heater ceiling: hardware limit, not a style choice — see
    ## Roaster.heater_max_pct. 100.0 = no declared ceiling.
    heater_max_pct: float = 100.0
    heater_support_threshold_pct: "float | None" = None
    heater_caution_pct: "float | None" = None

    ## Maillard RoR decay exponent — see Roaster.maillard_ror_decay.
    ## 2.0 = default (low-inertia radiant electric machines).
    maillard_ror_decay: float = 2.0

    # see comment in the Drum block above — populated by from_roaster
    # from DrumControl.smooth_speed_transition (safe default: locked).
    drum_midroast_locked: bool = True

    # ── Physical ranges (optional, display-only) ─────────────
    # None when the roaster has no known physical mapping for that control.
    heater_physical: "PhysicalRange | None" = None
    airflow_physical: "PhysicalRange | None" = None
    drum_physical: "PhysicalRange | None" = None

    # ── Capability flags (UI gating) ─────────────────────────
    has_heater_control:  bool = True
    has_airflow_control: bool = True

    @classmethod
    def from_roaster(cls, roaster: "Roaster") -> "RoasterContext":
        """Build a RoasterContext from a Roaster dataclass instance."""

        # --- drum rpm bounds ---
        dc = roaster.drum_control
        if dc and dc.variable_speed and dc.min_rpm is not None and dc.max_rpm is not None:
            drum_min   = float(dc.min_rpm)
            drum_max   = float(dc.max_rpm)
            drum_step  = float(dc.step_rpm_setting) if dc.step_rpm_setting is not None else 1.0
            drum_min_set = float(dc.min_rpm_setting or 0.0) # if no prom value given assume 0
        else:
            # Fixed-speed or unknown: use sentinel values that disable rpm conversion
            drum_min   = 0.0
            drum_max   = 0.0
            drum_step  = 1.0
            drum_min_set = 0.0

        # --- airflow resolution ---
        ac = roaster.airflow_control
        airflow_res = float(ac.airflow_resolution_percent) if ac else 5.0

        hc = roaster.heating_control
        # No trailing commas here: they turned these flags into always-truthy
        # 1-tuples, defeating every `if ctx.has_heater_control` gate downstream.
        has_heater_control  = hc is not None and hc.control_type != BurnerControlType.NONE
        has_airflow_control = ac is not None and ac.control_type != AirflowControlType.NONE
        heater_res = float(hc.power_resolution_percent) if hc else 1.0

        return cls(
            display_name             = f"{roaster.manufacturer} {roaster.model}",
            batch_min_g              = roaster.batch_capacity_min_g,
            batch_max_g              = roaster.batch_capacity_max_g,
            batch_optimal_g          = roaster.optimal_batch_capacity_g or roaster.batch_capacity_max_g,
            thermal_mass_index       = roaster.thermal_mass_index       or 0.65,
            heat_retention_index     = roaster.heat_retention_index     or 0.65,
            airflow_dependency_index = roaster.airflow_dependency_index or 0.65,
            thermal_response_speed   = roaster.thermal_response_speed   or 0.70,
            is_radiant_electric      = roaster.is_radiant_electric,
            airflow_resolution_pct   = airflow_res,
            heater_resolution_pct    = heater_res,
            heater_max_pct           = (roaster.heater_max_pct
                                        if roaster.heater_max_pct is not None else 100.0),
            heater_support_threshold_pct = roaster.heater_support_threshold_pct,
            heater_caution_pct       = roaster.heater_caution_pct,
            maillard_ror_decay       = (roaster.maillard_ror_decay
                                        if roaster.maillard_ror_decay is not None else 2.0),
            drum_variable_speed      = dc.variable_speed if dc else False,
            drum_min_rpm             = drum_min,
            drum_max_rpm             = drum_max,
            drum_step_rpm            = drum_step,
            bt_offsets               = list(roaster.bean_temperature_offset_c),
            supports_preheat_profiles= roaster.supports_preheat_profiles,
            supports_profile_replay  = roaster.supports_profile_replay,
            agitation_type           = roaster.agitation_type,
            drum_min_setting         = drum_min_set,
            inlet_air_mode           = (ac.inlet_air_mode if ac else "push"),
            dev_thermal_inertia_factor = (roaster.dev_thermal_inertia_factor
                                         if roaster.dev_thermal_inertia_factor is not None else 0.8),
            peak_ror_reference_c       = (roaster.peak_ror_reference_c
                                         if roaster.peak_ror_reference_c is not None
                                         else (roaster.peak_ror_ceiling_c
                                               if roaster.peak_ror_ceiling_c is not None else 21.0)),
            has_heater_control       = has_heater_control,
            has_airflow_control      = has_airflow_control,
            heater_physical          = hc.physical_range if hc else None,
            airflow_physical         = ac.physical_range if ac else None,
            drum_physical            = dc.physical_range if dc else None,
            # locked unless the drum declares progressive speed ramps
            drum_midroast_locked     = not (dc is not None and dc.variable_speed
                                            and getattr(dc, 'smooth_speed_transition', False)),
        )

    # ── helpers ──────────────────────────────────────────────

    def pct_to_heater_label(self, pct: float) -> str:
        """'75%' or '75% (1800 W)' depending on heater_physical availability."""
        return self.heater_physical.pct_to_label(pct) if self.heater_physical else f"{pct:.0f}%"

    def pct_to_airflow_label(self, pct: float) -> str:
        """'40%' or '40% (4.8 V)' depending on airflow_physical availability."""
        return self.airflow_physical.pct_to_label(pct) if self.airflow_physical else f"{pct:.0f}%"

    def pct_to_drum_label(self, pct: float) -> str:
        """'60%' or '60% (7.2 V)' depending on drum_physical availability."""
        return self.drum_physical.pct_to_label(pct) if self.drum_physical else f"{pct:.0f}%"

    def clamp_batch(self, weight_g: float) -> float:
        """
        Clamp a requested batch weight to this roaster's valid range
        and warn if the value was adjusted.
        """
        import logging
        clamped = max(float(self.batch_min_g), min(float(self.batch_max_g), weight_g))
        if clamped != weight_g:
            _logd.warning(
                f"[RoasterContext] batch weight {weight_g:.0f}g clamped to "
                f"[{self.batch_min_g}, {self.batch_max_g}]g for {self.display_name}"
            )
        return clamped

   # AFTER — round in RPM space first, then map to %
    def rpm_to_percent(self, rpm_target: float) -> str:
        """
        Maps rpm_target to a roaster setting percentage in [drum_min_setting, 100].

        Rounding is applied in RPM space (using drum_step_rpm) before the
        linear mapping, so the returned % always corresponds to a physically
        settable speed step.
        """
        if not self.drum_variable_speed or self.drum_max_rpm <= self.drum_min_rpm:
            return "--"

        # 1. Clamp to valid mechanical range
        rpm = max(self.drum_min_rpm, min(self.drum_max_rpm, rpm_target))

        # 2. Round to the machine's RPM step resolution (in RPM space)
        step_rpm = max(1.0, self.drum_step_rpm)
        rpm = round(rpm / step_rpm) * step_rpm
        # Re-clamp after rounding (rounding up could exceed max)
        rpm = max(self.drum_min_rpm, min(self.drum_max_rpm, rpm))

        # 3. Linear map: RPM range → setting range [drum_min_setting, 100]
        span_rpm = self.drum_max_rpm - self.drum_min_rpm
        span_set = 100.0 - self.drum_min_setting
        pct = self.drum_min_setting + ((rpm - self.drum_min_rpm) / span_rpm) * span_set
        # Snap to step in % space, rounded DOWN: keeps the setting on or below
        # the physically achievable step instead of overshooting the ceiling.
        pct = math.floor(pct / self.drum_step_rpm) * self.drum_step_rpm
        pct = max(self.drum_min_setting, min(100.0, pct))

        return f"{pct:.0f}%"

    def round_airflow(self, value: float) -> float:
        """Round an airflow % to this roaster's resolution step."""
        step = max(1.0, self.airflow_resolution_pct)
        return round(round(value / step) * step)

    @property
    def nominal_weight_g(self) -> float:
        """Reference batch weight for thermal-mass calculations."""
        return float(self.batch_optimal_g)


# ============================================================
# ROASTER MANAGER
# ============================================================

class RoasterManager:
    _DEFAULT_JSON = Path(__file__).parent / "roasters.json"

    def __init__(self, current_roaster: str | None = None) -> None:
        self._roasters: list[Roaster] = []
        self._loaded: bool = False          # tracks whether JSON was loaded
        self._current_roaster: str | None = current_roaster

    # ── internal loader called on demand ─────────────────────────────────────

    @property
    def roasters(self) -> list[Roaster]:
        return self._roasters

    def _ensure_loaded(self) -> None:
        """
        Load roasters.json exactly once.  Subsequent calls are no-ops.
        Raises FileNotFoundError if the JSON file is missing — callers
        that need a safe fallback should catch it.
        """
        if self._loaded:
            return
        self.load_json(self._DEFAULT_JSON)
        self._loaded = True

    # ── public API ───────────────────────────────────────────────────────────

    def get_roaster_list(self) -> list[str]:
        """Return display names, loading the JSON file if not yet loaded."""
        self._ensure_loaded()
        return self.get_display_names()

    def get_roast_context(self, name: str | None = None) -> RoasterContext | None:
        """
        Return a RoasterContext for *name* (or the QSettings-persisted
        roaster if name is None).

        Auto-loads roasters.json on first call.  Returns None if:
        - no name is configured/provided
        - the name is not found in the registry
        - the JSON file is missing (logs a warning, does not raise)
        """
        try:
            self._ensure_loaded()
        except FileNotFoundError:
            _logd.warning(
                "RoasterManager: roasters.json not found — no roaster context available"
            )
            return None

        if name is None:
            name = self._current_roaster
        if not name:
            return None

        roaster = self.get_by_display_name(name)
        if roaster is None:
            _logd.warning(
                "RoasterManager: roaster %r not found in registry", name
            )
            return None

        return RoasterContext.from_roaster(roaster)

    def get_by_name(self, manufacturer: str, model: str) -> Roaster|None:
        self._ensure_loaded()
        for roaster in self._roasters:
            if (
                roaster.manufacturer.lower() == manufacturer.lower()
                and roaster.model.lower() == model.lower()
            ):
                return roaster

        return None

    def get_by_roaster_id(self, roaster_id: str) -> Roaster | None:
        """Lookup by the stable TRP ROASTER_ID slug (spec §19.1), case-insensitive.

        Auto-loads roasters.json on first call. This is the preferred TRP
        resolution key — stable across firmware/label changes, unlike the
        free-text manufacturer/model strings.
        """
        self._ensure_loaded()
        rid = roaster_id.strip().lower()
        return next(
            (r for r in self._roasters if r.roaster_id and r.roaster_id.lower() == rid),
            None,
        )

    def remove(self, manufacturer: str, model: str) -> bool:
        roaster = self.get_by_name(manufacturer, model)

        if roaster is None:
            return False

        self._roasters.remove(roaster)

        return True

    def clear(self) -> None:
        self._roasters.clear()

    def add(self, roaster: Roaster) -> None:
        existing = self.get_by_name(
            roaster.manufacturer,
            roaster.model,
        )

        if existing is not None:
            raise ValueError(
                f"Roaster already exists: {roaster.manufacturer} {roaster.model}"
            )

        self._roasters.append(roaster)

    def load_json(self, path: str | Path) -> None:
        """
        Load roasters from a JSON file, replacing any previously loaded list.
        Resets the _loaded flag so get_roast_context re-reads on next call
        if explicitly reloaded (e.g. after editing).
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        with path.open("r", encoding="utf-8-sig" if _IS_WINDOWS else "utf-8") as f:
            data = json.load(f)

        self._roasters = [Roaster.from_dict(item) for item in data]
        self._loaded = True   # mark loaded whether called directly or via _ensure_loaded

    def get_display_names(self) -> list[str]:
        """Retourne la liste des noms complets (Constructeur + Modèle) pour l'UI."""
        return [f"{r.manufacturer} {r.model}" for r in self._roasters]

    def get_by_display_name(self, name: str) -> Roaster | None:
        """Find a roaster by display name; falls back to model-only match."""
        self._ensure_loaded()
        name = canonical_roaster_name(name)
        exact = next((r for r in self._roasters
                      if f"{r.manufacturer} {r.model}" == name), None)
        if exact is not None:
            return exact
        # Tolerate roastertype values stored as model-only (e.g. "Cyberroaster")
        return next((r for r in self._roasters if r.model == name), None)


# ============================================================
# QMC SYNC — push the TilauScope-configured roaster into Artisan
# ============================================================

# HeatingType -> qmc.roasterheating code (0: ??, 1: LPG, 2: NG, 3: Elec)
_QMC_HEATING_CODE: dict[HeatingType, int] = {
    HeatingType.GAS: 2,
    HeatingType.ELECTRIC: 3,
    HeatingType.INFRARED: 3,
    HeatingType.INDUCTION: 3,
    HeatingType.HYBRID: 3,
    HeatingType.WOOD: 0,
    HeatingType.COAL: 0,
}


def sync_roaster_to_qmc(aw: object, name: str | None) -> bool:
    """Single call site to mirror the TilauScope-configured
    roaster (aw.tilau_roaster) into Artisan's Machine-setup qmc fields
    (roastertype_setup/roastersize_setup/roasterheating_setup/machinesetup),
    so the canvas x-axis label / stats annotation (built from those _setup
    fields, see canvas.py default_xlabel_text/buildStat) reflect the roaster
    picked in TilauScope config instead of a stale manual Artisan setup.
    No-op if *name* is empty or not found in the registry, or if qmc is
    mid-roast (never rewrite an in-progress roast's machine identity).
    Returns True if qmc was updated."""
    if not name:
        return False
    qmc = getattr(aw, 'qmc', None)
    if qmc is None or getattr(qmc, 'flagstart', False):
        return False

    manager = RoasterManager()
    roaster = manager.get_by_display_name(name)
    ctx = manager.get_roast_context(name)
    if roaster is None or ctx is None:
        return False

    qmc.roastertype_setup = ctx.display_name
    qmc.machinesetup = ctx.display_name

    batch_g = ctx.batch_optimal_g or ctx.batch_max_g
    if batch_g:
        kg = batch_g / 1000.0
        qmc.roastersize_setup = kg
        qmc.roastersize_setup_default = kg

    heating_code = _QMC_HEATING_CODE.get(roaster.heating_type, 0)
    qmc.roasterheating_setup = heating_code
    qmc.roasterheating_setup_default = heating_code

    # mirror into the live (non-"_setup") fields too: they only get copied
    # from *_setup at CHARGE otherwise, and the canvas label reads *_setup
    # directly, but stats annotation (buildStat n==5) reads the live field.
    qmc.roastertype = qmc.roastertype_setup
    qmc.roastersize = qmc.roastersize_setup
    qmc.roasterheating = qmc.roasterheating_setup

    try:
        qmc.redraw()
    except Exception:
        _logd.exception('TilauScope: sync_roaster_to_qmc redraw failed')

    return True
